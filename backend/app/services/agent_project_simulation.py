"""使用冻结场景的试用聊天，不评分，不连接真实业务资源。"""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_project import AgentProjectEvalRun, AgentProjectEvalSet
from app.models.agent_project_simulation import AgentProjectSimulation
from app.schemas.agent_project_simulation import SimulationCreate, SimulationMessage
from app.services import agent_project_service as projects
from app.services.agent_project_evaluation import error
from app.services.agent_project_executor import SnapshotExecutionUnavailable, execute_snapshot
from app.services.agent_project_llm import capture_calls

_locks: dict[uuid.UUID, asyncio.Lock] = {}


async def get(
    db: AsyncSession,
    agent_id: uuid.UUID,
    owner: uuid.UUID,
    session_id: uuid.UUID,
    *,
    lock: bool = False,
) -> AgentProjectSimulation:
    project = await projects.require_project(db, agent_id, owner)
    query = (
        select(AgentProjectSimulation)
        .where(
            AgentProjectSimulation.id == session_id,
            AgentProjectSimulation.project_id == project.id,
            AgentProjectSimulation.user_id == owner,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise error("project_simulation_not_found", 404)
    return row


async def create(
    db: AsyncSession, agent_id: uuid.UUID, owner: uuid.UUID, body: SimulationCreate
) -> AgentProjectSimulation:
    project = await projects.require_project(db, agent_id, owner)
    await projects.lock_project(db, project)
    prior = await db.scalar(
        select(AgentProjectSimulation).where(
            AgentProjectSimulation.project_id == project.id,
            AgentProjectSimulation.request_id == body.request_id,
        )
    )
    if prior:
        if prior.version_id != body.version_id or (
            body.scenario_id and prior.scenario_id != body.scenario_id
        ):
            raise error("simulation_request_conflict", 409)
        await db.commit()
        return prior
    version = await projects.get_version(db, agent_id, owner, body.version_id)
    from app.services.agent_project_practice import requirements_hash

    dataset = await db.scalar(
        select(AgentProjectEvalSet)
        .where(
            AgentProjectEvalSet.project_id == project.id,
            AgentProjectEvalSet.frozen.is_(True),
        )
        .order_by(AgentProjectEvalSet.created_at.desc())
    )
    if not dataset or (dataset.rubric_json or {}).get("requirements_hash") != requirements_hash(
        project
    ):
        raise error("simulation_scenarios_not_ready", 409)
    candidates = [c for c in dataset.cases_json if c.get("enabled", True)]
    scenario = (
        next((c for c in candidates if c["id"] == str(body.scenario_id)), None)
        if body.scenario_id
        else next(
            (c for c in candidates if "normal" in c.get("tags", [])),
            candidates[0] if candidates else None,
        )
    )
    if scenario is None:
        raise error("simulation_scenario_not_found", 404)
    run = await db.scalar(
        select(AgentProjectEvalRun)
        .where(
            AgentProjectEvalRun.project_id == project.id,
            AgentProjectEvalRun.version_id == version.id,
            AgentProjectEvalRun.eval_set_id == dataset.id,
        )
        .order_by(AgentProjectEvalRun.created_at.desc())
    )
    config = deepcopy(version.snapshot_json)
    if run:
        config["resolved_examinee"] = (run.comparison_json or {}).get("resolved_examinee")
        config["role_configurations"] = (run.comparison_json or {}).get("role_configurations")
    row = AgentProjectSimulation(
        project_id=project.id,
        user_id=owner,
        version_id=version.id,
        scenario_id=uuid.UUID(scenario["id"]),
        request_id=body.request_id,
        config_json=config,
        scenario_json=deepcopy(scenario),
        state_json=deepcopy(scenario.get("initial_state") or {}),
        messages_json=[],
        turns_json=[],
    )
    db.add(row)
    await db.commit()
    return row


async def send(
    db: AsyncSession,
    agent_id: uuid.UUID,
    owner: uuid.UUID,
    session_id: uuid.UUID,
    body: SimulationMessage,
) -> AgentProjectSimulation:
    # 本地锁覆盖 SQLite 测试；数据库行锁保证不同进程间同一会话串行。
    async with _locks.setdefault(session_id, asyncio.Lock()):
        row = await get(db, agent_id, owner, session_id, lock=True)
        prior = next((t for t in row.turns_json if t["request_id"] == str(body.request_id)), None)
        if prior:
            if prior["input"] != projects.snapshot_value(body.content):
                raise error("simulation_request_conflict", 409)
            await db.commit()
            return row
        if len(row.turns_json) >= 100:
            raise error("simulation_session_limit", 409)
        case = deepcopy(row.scenario_json)
        case["input"] = body.content
        case["initial_state"] = deepcopy(row.state_json)
        case["_conversation_messages"] = deepcopy(row.messages_json)
        counts = {}
        for turn in row.turns_json:
            for event in turn.get("evidence", {}).get("tool_trace", []):
                counts[event["name"]] = max(
                    counts.get(event["name"], 0), event.get("call_number", 0)
                )
        case["_call_counts"] = counts
        captured: list[dict[str, Any]] = []
        try:
            with capture_calls(captured):
                async with asyncio.timeout(90):
                    evidence = await execute_snapshot(db, row.config_json, case, owner)
        except TimeoutError:
            evidence = next(
                (c["partial_execution"] for c in reversed(captured) if "partial_execution" in c), {}
            )
            evidence = {**evidence, "termination_reason": "timeout"}
        except SnapshotExecutionUnavailable as exc:
            evidence = {**exc.evidence, "termination_reason": exc.code}
        evidence = projects.snapshot_value(evidence)
        messages = evidence.pop("conversation_messages", None)
        if messages is not None:
            row.messages_json = messages
        else:
            row.messages_json = [
                *row.messages_json,
                {
                    "type": "human",
                    "data": {"content": projects.snapshot_value(body.content), "type": "human"},
                },
                *(
                    [{"type": "ai", "data": {"content": evidence["output"], "type": "ai"}}]
                    if evidence.get("output")
                    else []
                ),
            ]
        row.state_json = deepcopy(evidence.get("final_state", row.state_json))
        row.turns_json = [
            *row.turns_json,
            {
                "request_id": str(body.request_id),
                "input": projects.snapshot_value(body.content),
                "output": evidence.get("output", ""),
                "evidence": evidence,
            },
        ]
        await db.commit()
        return row


async def reset(
    db: AsyncSession,
    agent_id: uuid.UUID,
    owner: uuid.UUID,
    session_id: uuid.UUID,
    request_id: uuid.UUID,
) -> AgentProjectSimulation:
    row = await get(db, agent_id, owner, session_id)
    project = await projects.require_project(db, agent_id, owner)
    await projects.lock_project(db, project)
    prior = await db.scalar(
        select(AgentProjectSimulation).where(
            AgentProjectSimulation.project_id == project.id,
            AgentProjectSimulation.request_id == request_id,
        )
    )
    config = deepcopy(row.config_json)
    config["reset_source_session_id"] = str(row.id)
    if prior:
        if prior.config_json.get("reset_source_session_id") != str(row.id):
            raise error("simulation_request_conflict", 409)
        await db.commit()
        return prior
    fresh = AgentProjectSimulation(
        project_id=row.project_id,
        user_id=owner,
        version_id=row.version_id,
        scenario_id=row.scenario_id,
        request_id=request_id,
        config_json=config,
        scenario_json=deepcopy(row.scenario_json),
        state_json=deepcopy(row.scenario_json.get("initial_state") or {}),
        messages_json=[],
        turns_json=[],
    )
    db.add(fresh)
    await db.commit()
    return fresh
