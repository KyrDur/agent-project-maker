"""Bounded evaluation storage/execution and version comparison."""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from datetime import timedelta
from time import perf_counter
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import (
    AgentProjectEvalRun,
    AgentProjectEvalSet,
    utcnow,
)
from app.schemas.agent_project import EvalRunCreate, EvalSetWrite, EvaluationCase
from app.services import agent_project_service as projects
from app.services.agent_project_executor import SnapshotExecutionUnavailable, execute_snapshot


def error(code: str, status: int = 422) -> AppError:
    return AppError(code=code, message=code, status=status)


async def get_set(
    db: AsyncSession, project_id: uuid.UUID, set_id: uuid.UUID
) -> AgentProjectEvalSet:
    row = await db.scalar(
        select(AgentProjectEvalSet).where(
            AgentProjectEvalSet.id == set_id, AgentProjectEvalSet.project_id == project_id
        )
    )
    if row is None:
        raise error("agent_project_eval_set_not_found", 404)
    return row


async def write_set(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    body: EvalSetWrite,
    set_id: uuid.UUID | None = None,
    *,
    rubric: dict[str, Any] | None = None,
) -> AgentProjectEvalSet:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    row = (
        await get_set(db, project.id, set_id)
        if set_id
        else AgentProjectEvalSet(project_id=project.id)
    )
    if row.frozen:
        raise error("agent_project_eval_set_frozen", 409)
    old = {case["id"]: case for case in (row.cases_json or []) if "id" in case}
    if len({case.id for case in body.cases}) != len(body.cases):
        raise error("duplicate_evaluation_case")
    now = utcnow().isoformat()
    cases = []
    for case in body.cases:
        data = case.model_dump(mode="json")
        data.update(
            project_id=str(project.id),
            created_at=old.get(str(case.id), {}).get("created_at", now),
            updated_at=now,
        )
        cases.append(projects.snapshot_value(data))
    if rubric is not None:
        row.rubric_json = deepcopy(rubric)
    row.name, row.cases_json = projects.snapshot_value(body.name), cases
    db.add(row)
    await db.commit()
    return row


async def remove_set(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, set_id: uuid.UUID
) -> None:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    row = await get_set(db, project.id, set_id)
    used = await db.scalar(
        select(AgentProjectEvalRun.id).where(AgentProjectEvalRun.eval_set_id == row.id).limit(1)
    )
    if used is not None or row.frozen:
        raise error("evaluation_dataset_in_use", 409)
    await db.delete(row)
    await db.commit()


async def create_run(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: EvalRunCreate
) -> AgentProjectEvalRun:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    version = await projects.get_version(db, agent_id, user_id, body.version_id)
    dataset = await get_set(db, project.id, body.eval_set_id)
    await expire_runs(db, project.id)
    prior = await db.scalar(
        select(AgentProjectEvalRun).where(
            AgentProjectEvalRun.project_id == project.id,
            AgentProjectEvalRun.request_id == body.request_id,
        )
    )
    if prior is not None:
        if prior.version_id != body.version_id or prior.eval_set_id != body.eval_set_id:
            raise error("evaluation_request_conflict", 409)
        await db.commit()
        return prior
    # Revalidate legacy Phase 1 JSON before executing it; never infer a case.
    cases = []
    for stored in dataset.cases_json:
        data = {key: value for key, value in stored.items() if key in EvaluationCase.model_fields}
        try:
            case = EvaluationCase.model_validate(data)
        except ValueError as exc:
            raise error("evaluation_dataset_invalid") from exc
        if case.enabled:
            cases.append(projects.snapshot_value(case.model_dump(mode="json")))
    if not cases or len(cases) > 20:
        raise error("evaluation_requires_enabled_cases")
    from app.services.agent_project_semantic import frozen_plan

    plan = frozen_plan(project.eval_spec_json, dataset, version.snapshot_json)
    row = AgentProjectEvalRun(
        project_id=project.id,
        version_id=version.id,
        eval_set_id=dataset.id,
        request_id=body.request_id,
        status="pending",
        cases_snapshot_json=deepcopy(cases),
        dataset_hash=canonical_json_hash(cases),
        metrics_json={"total": len(cases)},
        results_json=[],
        comparison_json=plan,
    )
    db.add(row)
    await db.commit()
    return row


async def expire_runs(db: AsyncSession, project_id: uuid.UUID) -> None:
    # Reconcile on authenticated, CSRF-protected submission, never from a GET.
    # No automatic replay after a process crash: a timed-out lease becomes failed.
    # Maximum work is 20 cases × 30 seconds, with 5 minutes of overhead allowance.
    await db.execute(
        update(AgentProjectEvalRun)
        .where(
            AgentProjectEvalRun.project_id == project_id,
            AgentProjectEvalRun.status.in_(["pending", "running"]),
            AgentProjectEvalRun.created_at < utcnow() - timedelta(minutes=45),
        )
        .values(status="failed", error="evaluation_worker_expired", completed_at=utcnow())
    )


async def list_runs(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID
) -> list[AgentProjectEvalRun]:
    project = await projects.require_project(db, agent_id, user_id)
    return list(
        (
            await db.scalars(
                select(AgentProjectEvalRun)
                .where(AgentProjectEvalRun.project_id == project.id)
                .order_by(AgentProjectEvalRun.created_at.desc())
                .limit(100)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def get_run(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, run_id: uuid.UUID
) -> AgentProjectEvalRun:
    project = await projects.require_project(db, agent_id, user_id)
    row = await db.scalar(
        select(AgentProjectEvalRun)
        .where(AgentProjectEvalRun.id == run_id, AgentProjectEvalRun.project_id == project.id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise error("agent_project_eval_run_not_found", 404)
    return row


def score_case(case: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    expected = case.get("expected") or {}
    names = {call["name"] for call in evidence.get("tool_calls", [])}
    checks = [
        {"kind": "execution_succeeded", "passed": True},
        {"kind": "answer_exists", "passed": bool(evidence.get("output", "").strip())},
    ]
    if expected.get("exact_answer") is not None:
        checks.append(
            {"kind": "exact_answer", "passed": evidence.get("output") == expected["exact_answer"]}
        )
    for name in expected.get("required_tools", []):
        checks.append({"kind": "required_tool", "target": name, "passed": name in names})
    for name in expected.get("forbidden_tools", []):
        checks.append({"kind": "forbidden_tool", "target": name, "passed": name not in names})
    if expected.get("handoff"):
        checks.append(
            {
                "kind": "handoff",
                "target": expected["handoff"],
                "passed": expected["handoff"] in evidence.get("handoffs", []),
            }
        )
    from app.services.agent_project_semantic import format_check

    if expected.get("format_rule"):
        checks.append(
            {"kind": "format_compliance", "passed": format_check(case, evidence.get("output", ""))}
        )
    return checks


async def execute_run(run_id: uuid.UUID, agent_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with async_session() as db:
        project = await projects.require_project(db, agent_id, user_id)
        claimed = await db.execute(
            update(AgentProjectEvalRun)
            .where(
                AgentProjectEvalRun.id == run_id,
                AgentProjectEvalRun.project_id == project.id,
                AgentProjectEvalRun.status == "pending",
            )
            .values(status="running", started_at=utcnow())
            .returning(AgentProjectEvalRun.id)
        )
        if claimed.scalar_one_or_none() is None:
            await db.rollback()
            return
        await db.commit()
        row = await db.get(AgentProjectEvalRun, run_id)
        if row is None:
            return
        from app.services.agent_project_semantic import grade_case, metric_summary

        plan = deepcopy(row.comparison_json)
        results: list[dict[str, Any]] = []
        try:
            version = await projects.get_version(db, agent_id, user_id, row.version_id)
            if canonical_json_hash(version.snapshot_json) != version.config_hash:
                raise SnapshotExecutionUnavailable("snapshot_hash_mismatch")
            snapshot = deepcopy(version.snapshot_json)
            cases = deepcopy(row.cases_snapshot_json or [])
            if not cases:
                raise SnapshotExecutionUnavailable("evaluation_dataset_invalid")
            for case in cases:
                start = perf_counter()
                result = {
                    "case_id": case["id"],
                    "name": case["name"],
                    "input": case["input"],
                    "expected": case.get("expected"),
                    "output": "",
                    "tool_calls": [],
                    "assertions": [],
                    "error": None,
                    "execution_status": "failed",
                    "metric_scores": {},
                    "judge_reasons": {},
                }
                try:
                    async with asyncio.timeout(30):
                        evidence = await execute_snapshot(db, snapshot, case, user_id)
                    checks = score_case(case, evidence)
                    result.update(
                        evidence,
                        execution_status="completed",
                        assertions=checks,
                        status="passed" if all(c["passed"] for c in checks) else "failed",
                    )
                    if plan:
                        async with asyncio.timeout(95):
                            result.update(
                                await grade_case(
                                    db, snapshot, user_id, case, evidence, checks, plan
                                )
                            )
                except SnapshotExecutionUnavailable as exc:
                    result.update(exc.evidence)
                    result.update(status="errored", error=str(exc))
                except TimeoutError:
                    result.update(status="errored", error="evaluation_timeout")
                except Exception:
                    # Provider exceptions may contain secrets; never persist or log them.
                    result.update(status="errored", error="evaluation_execution_failed")
                result.update(
                    passed=result["status"] == "passed",
                    actual_output=result["output"],
                    called_tools=result["tool_calls"],
                    deterministic_assertions=result["assertions"],
                    error_code=result["error"],
                )
                result["latency_ms"] = round((perf_counter() - start) * 1000)
                results.append(projects.snapshot_value(result))
                row.results_json = list(results)
                await db.commit()
            passed = sum(result["status"] == "passed" for result in results)
            errored = sum(result["status"] == "errored" for result in results)
            row.metrics_json = {
                "total": len(results),
                "passed": passed,
                "failed": len(results) - passed - errored,
                "errored": errored,
                "pass_rate": passed / len(results),
                "scoring": "semantic_v1" if plan else "structural_v1",
                "metric_scores": metric_summary(results),
            }
            row.pass_rate = passed / len(results)
            row.status = "failed" if errored else "completed"
            row.error = "evaluation_case_errors" if errored else None
        except (Exception, asyncio.CancelledError):
            await db.rollback()
            row = await db.get(AgentProjectEvalRun, run_id)
            if row is None:
                return
            row.status, row.error = "failed", "evaluation_execution_failed"
        row.completed_at = utcnow()
        await db.commit()


async def compare_versions(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    left_id: uuid.UUID,
    right_id: uuid.UUID,
) -> dict[str, Any]:
    left = await projects.get_version(db, agent_id, user_id, left_id)
    right = await projects.get_version(db, agent_id, user_id, right_id)
    a, b = left.snapshot_json["agent"], right.snapshot_json["agent"]
    changes = []
    fields = (
        "name",
        "description",
        "system_prompt",
        "identity_mode",
        "model",
        "model_params",
        "llm_credential_id",
        "model_fallback_list",
        "fallback_models",
        "tool_links",
        "skill_links",
        "mcp_tool_links",
        "middleware_configs",
        "runtime_policy",
        "opener_questions",
        "sub_agent_links",
    )
    identities = {
        "tool_links": "tool_id",
        "skill_links": "skill_id",
        "mcp_tool_links": "mcp_tool_id",
        "sub_agent_links": "sub_agent_id",
    }
    for field in fields:
        if a.get(field) == b.get(field):
            continue
        change: dict[str, Any] = {"field": field, "before": a.get(field), "after": b.get(field)}
        if field in identities:
            key = identities[field]
            before, after = ({item[key]: item for item in value.get(field, [])} for value in (a, b))
            change.update(
                added=sorted(after.keys() - before.keys()),
                removed=sorted(before.keys() - after.keys()),
                changed=sorted(
                    key for key in before.keys() & after.keys() if before[key] != after[key]
                ),
            )
        changes.append(change)
    summaries = []
    for version in (left, right):
        run = await db.scalar(
            select(AgentProjectEvalRun)
            .where(
                AgentProjectEvalRun.project_id == version.project_id,
                AgentProjectEvalRun.version_id == version.id,
                AgentProjectEvalRun.status == "completed",
            )
            .order_by(AgentProjectEvalRun.created_at.desc())
            .limit(1)
        )
        summaries.append(
            {"run_id": str(run.id), "dataset_hash": run.dataset_hash, "metrics": run.metrics_json}
            if run
            else None
        )
    return {
        "left_version_id": str(left.id),
        "right_version_id": str(right.id),
        "changes": changes,
        "evaluations": summaries,
        "same_dataset": bool(
            summaries[0]
            and summaries[1]
            and summaries[0]["dataset_hash"] == summaries[1]["dataset_hash"]
        ),
    }
