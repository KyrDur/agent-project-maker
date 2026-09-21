"""Release gate: real Builder graph, storage, sandbox, optimizer and reports.

Only model responses are fake. No provider or production tools are contacted.
Run on Linux (the production runtime requires Unix filesystem primitives).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_runtime.builder_v3.graph import build_graph
from app.agent_runtime.builder_v3.nodes import (
    phase2_intent,
    phase3_tools,
    phase4_middlewares,
    phase5_prompt,
    phase6_image,
    phase7_save,
    phase8_build,
)
from app.credentials.service import encrypt_data
from app.models.agent import Agent
from app.models.agent_project import AgentProject, AgentProjectEvalRun, AgentProjectEvalSet
from app.models.credential import Credential
from app.models.model import Model
from app.models.user import User
from app.schemas.agent_project import EvalRunCreate
from app.schemas.builder import AgentCreationIntent, MiddlewareRecommendation
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_optimization as optimization
from app.services import agent_project_portfolio as portfolio
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services import builder_project_lifecycle as lifecycle
from app.services import builder_service
from tests import test_agent_projects as project_fixtures
from tests.test_agent_project_phase3 import generated_cases, plan

TEST_USER_ID = project_fixtures.TEST_USER_ID
db = project_fixtures.db


class ScriptedExaminee(BaseChatModel):
    """Model exercises the actual sandbox tool-call round trip after a patch."""

    @property
    def _llm_type(self):
        return "p0_fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        improved = "Consult sources before answering." in str(messages[0].content)
        if improved and not any(
            isinstance(m, ToolMessage) and m.name == "search" for m in messages
        ):
            answer = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search",
                        "args": {},
                        "id": "mock-search",
                    }
                ],
            )
        else:
            answer = AIMessage(content="Login reviewed" if improved else "Unsupported claim")
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def model_json(_db, _snapshot, _user, role, _instruction, payload):
    if role == "planner":
        return plan()
    if role == "case_generator":
        data = generated_cases()
        capabilities = payload.get("capability_profile", {}).get("capabilities", [])
        if capabilities:
            for case in data["cases"]:
                case["tags"] = [case["tags"][0], *capabilities]
        return data
    if role == "judge":
        passed = payload["actual_output"] == "Login reviewed"
        return {
            "metric_scores": {
                metric["name"]: {
                    "score": float(passed),
                    "passed": passed,
                    "reason": "Mock source evidence",
                }
                for metric in payload["metrics"]
            }
        }
    if role == "bad_case_analyzer":
        ids = [c["case_id"] for c in payload["cases"]]
        return {
            "analyses": [
                {
                    "case_id": case_id,
                    "category": "instruction_issue",
                    "root_cause": "Sources were not consulted.",
                    "evidence": ["/actual_output"],
                    "recommended_target": "instructions",
                    "suggested_fix": "Consult sources.",
                }
                for case_id in ids
            ],
            "groups": [
                {
                    "category": "instruction_issue",
                    "case_ids": ids,
                    "root_cause": "Sources were not consulted.",
                    "target": "instructions",
                    "proposed_change": "Consult sources before answering.",
                }
            ],
        }
    assert role == "optimizer"
    return {
        "changes": [
            {
                "group_index": 0,
                "target": "instructions",
                "operation": "append",
                "content": "Consult sources before answering.",
                "reason": "Ground answers in sources.",
            }
        ]
    }


@pytest.mark.asyncio
async def test_builder_through_report_release_gate(db, monkeypatch):
    # Real runtime import is required. Do not stub fcntl or the graph factory.
    from app.agent_runtime import (
        model_factory,
        runtime_component_builder,  # noqa: F401
    )
    from app.config import settings
    from app.security import key_provider

    monkeypatch.setattr(settings, "encryption_keys", "11" * 32)
    key_provider.reset_cache()
    encrypted, key_id, fields = encrypt_data({"api_key": "p0-dummy-personal-key"})
    db.add(User(id=TEST_USER_ID, email="p0@example.test", name="P0"))
    credential = Credential(
        user_id=TEST_USER_ID,
        name="Personal",
        definition_key="openai",
        data_encrypted=encrypted,
        key_id=key_id,
        field_keys=fields,
        is_system=False,
        status="active",
    )
    db.add(credential)
    await db.flush()
    model = Model(
        provider="openai",
        model_name="p0-fake",
        display_name="P0",
        default_credential_id=credential.id,
    )
    db.add(model)
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    for module in (evaluation, optimization, lifecycle):
        monkeypatch.setattr(module, "async_session", factory)
    monkeypatch.setattr(lifecycle, "engine", db.bind)
    for module in (phase7_save, phase8_build):
        monkeypatch.setattr(module, "async_session_factory", factory)
    queued = []
    monkeypatch.setattr(lifecycle, "schedule", lambda *args: queued.append(args))
    monkeypatch.setattr(model_factory, "create_chat_model", lambda *a, **k: ScriptedExaminee())
    monkeypatch.setattr(semantic, "json_call", model_json)
    monkeypatch.setattr(optimization, "json_call", model_json)
    intent = AgentCreationIntent(
        agent_name="周报整理助手",
        agent_description="整理周报",
        primary_task_type="report",
        use_cases=["周报"],
        required_capabilities=[],
    )
    monkeypatch.setattr(phase2_intent, "analyze_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(
        phase2_intent, "_suggest_name_options", AsyncMock(return_value=["周报整理助手", "周报助手"])
    )
    monkeypatch.setattr(phase3_tools, "recommend_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        phase4_middlewares,
        "recommend_middlewares",
        AsyncMock(
            return_value=[
                MiddlewareRecommendation(
                    middleware_name="model_retry", description="重试", reason="恢复临时失败"
                )
            ]
        ),
    )
    monkeypatch.setattr(
        phase5_prompt, "generate_system_prompt", AsyncMock(return_value="Answer clearly.")
    )
    monkeypatch.setattr(
        phase6_image, "is_image_generation_available", AsyncMock(return_value=False)
    )
    session = await builder_service.create_session(db, TEST_USER_ID, "整理周报")
    graph = build_graph().compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": str(session.id), "ui_locale": "zh-CN"}}
    await graph.ainvoke(
        {"session_id": str(session.id), "user_request": "整理周报", "messages": []}, config
    )
    for _ in range(12):
        state = await graph.aget_state(config)
        if not state.next:
            break
        response = (
            {
                "answers": {
                    "agent_name": ["周报整理助手"],
                    "response_tone": ["concise"],
                    "output_style": ["summary"],
                }
            }
            if state.next[0] == "phase2_intent_wait"
            else {"approved": True}
        )
        await graph.ainvoke(Command(resume=response), config)
    state = await graph.aget_state(config)
    assert state.values.get("completed"), state.values.get("error_message")
    await db.refresh(session)
    agent = await db.get(Agent, session.agent_id)
    assert agent.model_id == model.id and agent.llm_credential_id == credential.id
    assert len(queued) == 1
    versions = await projects.list_versions(db, agent.id, TEST_USER_ID)
    assert len(versions) == 1 and versions[0].version_number == 1
    v1 = deepcopy(versions[0].snapshot_json)
    await lifecycle.bootstrap(agent.id, TEST_USER_ID)
    await asyncio.gather(
        lifecycle.bootstrap(agent.id, TEST_USER_ID), lifecycle.bootstrap(agent.id, TEST_USER_ID)
    )
    assert await db.scalar(select(func.count()).select_from(AgentProject)) == 1

    # Builder bootstrap intentionally pauses at the human evaluation-focus checkpoint.
    # Resume the same golden path by selecting two generated focus options, then
    # generate, quality-check, freeze and execute the formal 20-case benchmark.
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    await db.refresh(project)
    assert project.eval_spec_json is not None
    assert await db.scalar(select(func.count()).select_from(AgentProjectEvalSet)) == 0
    focus_ids = [item["id"] for item in project.eval_spec_json["focus_options"][:2]]
    dataset = await semantic.generate(
        db,
        agent.id,
        TEST_USER_ID,
        versions[0].id,
        cases=True,
        evaluation_focus=focus_ids,
        evaluation_focus_reason="P0 golden-path checkpoint selection",
    )
    dataset = await evaluation.judge_set(db, agent.id, TEST_USER_ID, dataset.id)
    assert dataset.quality_report_json is not None
    assert dataset.quality_report_json["status"] == "approved"
    baseline = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(
            version_id=versions[0].id,
            eval_set_id=dataset.id,
            request_id=uuid.uuid4(),
        ),
    )
    await evaluation.execute_run(baseline.id, agent.id, TEST_USER_ID)

    assert await db.scalar(select(func.count()).select_from(AgentProjectEvalSet)) == 1
    assert await db.scalar(select(func.count()).select_from(AgentProjectEvalRun)) == 1
    await db.refresh(dataset)
    assert dataset.frozen and len(dataset.cases_json) == 20
    baseline = (await evaluation.list_runs(db, agent.id, TEST_USER_ID))[0]
    assert baseline.status == "completed", baseline.error
    assert baseline.results_json is not None
    assert len(baseline.results_json) == 20 and any(
        r["status"] == "failed" for r in baseline.results_json
    )
    frozen = deepcopy(baseline.cases_snapshot_json)
    await optimization.start(db, agent.id, TEST_USER_ID, baseline.id, uuid.uuid4())
    await optimization.execute_optimization(agent.id, TEST_USER_ID, baseline.id)
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    await db.refresh(project)
    assert project.report_json is not None
    assert project.report_json["optimization"]["state"] == "completed"
    versions = await projects.list_versions(db, agent.id, TEST_USER_ID)
    assert sorted(v.version_number for v in versions) == [1, 2]
    assert next(v for v in versions if v.version_number == 1).snapshot_json == v1
    candidate = next(v for v in versions if v.version_number == 2)
    assert project.report_json["optimization"]["best_version_id"] == str(candidate.id)
    for run in await evaluation.list_runs(db, agent.id, TEST_USER_ID):
        assert run.eval_set_id == dataset.id and run.cases_snapshot_json == frozen
        assert run.dataset_hash == baseline.dataset_hash
    report = await portfolio.report(db, agent.id, TEST_USER_ID, save=True)
    assert report["markdown"] and "p0-dummy-personal-key" not in json.dumps(report)
    share = await portfolio.share(db, agent.id, TEST_USER_ID)
    assert share["path"]
    from app.services.agent_project_portfolio_export import export_zip

    assert (await export_zip(db, agent.id, TEST_USER_ID)).startswith(b"PK")
    key_provider.reset_cache()

