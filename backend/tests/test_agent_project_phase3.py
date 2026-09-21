"""Controlled Phase 3 tests. No live model or external tool is contacted."""

# pyright: reportArgumentType=false

from __future__ import annotations

import json
import sys
import uuid
from copy import deepcopy
from types import ModuleType

import pytest
from langchain_core.messages import AIMessage

from app.schemas.agent_project import SCENARIOS, EvalRunCreate, EvalSetWrite, EvalSpec
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_llm as llm
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services.agent_project_executor import SnapshotExecutionUnavailable, execute_snapshot
from app.services.agent_project_mock_tools import frozen_skill_prompt, mock_tools
from app.services.system_credential_resolver import ResolvedSystemModel
from tests import test_agent_project_phase2 as phase2

TEST_USER_ID = phase2.TEST_USER_ID
db = phase2.db
client = phase2.client
setup_project = phase2.setup_project


def plan():
    return {
        "metrics": [
            {
                "name": "task_completion",
                "type": "llm_judge",
                "weight": 0.4,
                "criteria": "Complete the requested task.",
            },
            {
                "name": "tool_correctness",
                "type": "deterministic",
                "weight": 0.3,
                "criteria": "Call required tools; avoid forbidden tools.",
            },
            {
                "name": "groundedness",
                "type": "llm_judge",
                "weight": 0.3,
                "criteria": "Only report facts present in sources.",
            },
        ],
        "pass_threshold": 0.7,
    }


def focus_body(version_id):
    return {
        "version_id": str(version_id),
        "evaluation_focus": ["tool_correctness", "groundedness"],
        "evaluation_focus_reason": "工具调用和事实依据是上线前最大的风险。",
    }


def generated_cases():
    return {
        "name": "Generated test cases",
        "cases": [
            {
                "id": str(uuid.uuid4()),
                "name": f"Case {i}",
                "input": "Summarize the project.",
                "context": [],
                "expected": {
                    "answer": "Report login review only.",
                    "required_tools": ["search"],
                    "forbidden_tools": ["delete"],
                },
                "tags": [SCENARIOS[i % 6], "conversation"],
                "enabled": True,
                "mock_tool_data": {"search": {"result": ["Login reviewed"]}},
            }
            for i in range(20)
        ],
    }


@pytest.mark.asyncio
async def test_project_llm_roles_use_platform_system_slots(monkeypatch):
    seen_roles: list[str] = []

    async def resolve_system_model(_db, role: str):
        seen_roles.append(role)
        return ResolvedSystemModel(
            provider="openai",
            model_name="gpt-5.4-mini",
            api_key="sk-platform",
            base_url=None,
        )

    def create_chat_model(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(llm, "resolve_system_model", resolve_system_model)
    monkeypatch.setattr("app.agent_runtime.model_factory.create_chat_model", create_chat_model)

    for role in (
        "planner",
        "case_generator",
        "judge",
        "bad_case_analyzer",
        "optimizer",
        "optimization_proposal",
        "unknown_future_role",
    ):
        await llm.resolve_model(db, {}, TEST_USER_ID, role)

    assert seen_roles == [
        "evaluation_generator",
        "evaluation_generator",
        "judge_optimizer",
        "judge_optimizer",
        "judge_optimizer",
        "judge_optimizer",
        "judge_optimizer",
    ]


@pytest.mark.parametrize("mutation", ["duplicate", "custom", "type", "weight", "count"])
def test_invalid_metric_plans_rejected(mutation):
    data = plan()
    if mutation == "duplicate":
        data["metrics"][1]["name"] = "task_completion"
    if mutation == "custom":
        data["metrics"][0]["name"] = "custom_one"
        data["metrics"][2]["name"] = "custom_two"
    if mutation == "type":
        data["metrics"][1]["type"] = "llm_judge"
    if mutation == "weight":
        data["metrics"][0]["weight"] = 0.9
    if mutation == "count":
        data["metrics"].pop()
    with pytest.raises(ValueError, match="validation error"):
        EvalSpec.model_validate(data)


def test_capability_profile_includes_mcp_and_planned_tools():
    profile = semantic.capability_profile(
        {
            "agent": {
                "system_prompt": "Use knowledge retrieval to summarize source documents.",
                "tool_links": [{"definition_key": "web_search", "name": "web_search"}],
                "mcp_tool_links": [{"name": "search_notion"}],
                "planned_tools": [{"tool_name": "search_feishu"}],
                "skill_links": [],
                "middleware_configs": [],
            }
        }
    )

    assert profile["capabilities"] == ["knowledge_retrieval", "tool_calling"]
    assert profile["tools"] == ["web_search", "search_notion", "search_feishu"]


@pytest.mark.asyncio
async def test_generation_editing_freeze_and_ownership(client, db, setup_project, monkeypatch):
    agent = setup_project
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    original = deepcopy(version.snapshot_json)

    async def generate_json(_db, snapshot, user, role, instruction, payload):
        assert snapshot == original and user == TEST_USER_ID
        return plan() if role == "planner" else generated_cases()

    monkeypatch.setattr(semantic, "json_call", generate_json)
    path = f"/api/agents/{agent.id}/project"
    body = {"version_id": str(version.id)}
    response = await client.post(path + "/eval-spec/generate", json=body)
    assert response.status_code == 200
    spec = response.json()
    assert len(spec["metrics"]) == 3 and spec["case_count"] == 20
    response = await client.post(path + "/eval-sets/generate", json=body)
    assert response.status_code == 422
    response = await client.post(path + "/eval-sets/generate", json=focus_body(version.id))
    assert response.status_code == 201
    dataset = response.json()
    assert len(dataset["cases_json"]) == 20 and not dataset["frozen"]
    assert [item["id"] for item in dataset["evaluation_focus_json"]] == [
        "tool_correctness",
        "groundedness",
    ]
    assert dataset["evaluation_focus_reason"] == "工具调用和事实依据是上线前最大的风险。"
    assert {c["tags"][0] for c in dataset["cases_json"]} == set(SCENARIOS)
    authored = EvalSetWrite.model_validate(
        {
            "name": dataset["name"],
            "cases": [
                {k: v for k, v in c.items() if k not in {"project_id", "created_at", "updated_at"}}
                for c in dataset["cases_json"]
            ],
        }
    )
    authored.cases[0].input = "Edited before submission"
    await evaluation.write_set(db, agent.id, TEST_USER_ID, authored, uuid.UUID(dataset["id"]))
    await evaluation.judge_set(db, agent.id, TEST_USER_ID, uuid.UUID(dataset["id"]))
    run = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(
            request_id=uuid.uuid4(), version_id=version.id, eval_set_id=uuid.UUID(dataset["id"])
        ),
    )
    frozen = deepcopy(run.cases_snapshot_json)
    frozen_spec = deepcopy(run.comparison_json)
    authored.cases[0].input = "Edited after submission"
    from app.exceptions import AppError

    with pytest.raises(AppError, match="agent_project_eval_set_frozen"):
        await evaluation.write_set(db, agent.id, TEST_USER_ID, authored, uuid.UUID(dataset["id"]))
    assert frozen is not None
    assert frozen[0]["input"] == "Edited before submission"
    assert run.cases_snapshot_json == frozen
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    project.eval_spec_json = None
    await db.commit()
    assert run.comparison_json == frozen_spec
    assert (
        version.snapshot_json == original
        and agent.system_prompt == original["agent"]["system_prompt"]
    )
    foreign = f"/api/agents/{uuid.uuid4()}/project"
    assert (await client.post(foreign + "/eval-spec/generate", json=body)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["count", "coverage", "mock", "duplicate"])
async def test_invalid_generated_cases_not_persisted(db, setup_project, monkeypatch, invalid):
    agent = setup_project
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    project.eval_spec_json = {**plan(), "version_id": str(version.id)}
    await db.commit()
    data = generated_cases()
    if invalid == "count":
        data["cases"].pop()
    if invalid == "coverage":
        for case in data["cases"]:
            case["tags"] = ["normal"]
    if invalid == "mock":
        data["cases"][0]["mock_tool_data"] = {}
    if invalid == "duplicate":
        data["cases"][1]["id"] = data["cases"][0]["id"]

    async def response(*_args):
        return data

    monkeypatch.setattr(semantic, "json_call", response)
    with pytest.raises(Exception, match="evaluation_generation_invalid"):
        await semantic.generate(
            db,
            agent.id,
            TEST_USER_ID,
            version.id,
            cases=True,
            evaluation_focus=["tool_correctness", "groundedness"],
        )
    assert not await projects.list_eval_sets(db, agent.id, TEST_USER_ID)


@pytest.mark.asyncio
async def test_mock_invocation_never_uses_production_or_model_arguments():
    case = generated_cases()["cases"][0]
    trace = []
    tools, missing = mock_tools(
        {
            "tool_links": [{"name": "search", "enabled": True}],
            "mcp_tool_links": [{"name": "mcp_read", "enabled": True}],
        },
        {
            **case,
            "mock_tool_data": {
                "search": {"result": ["Login reviewed"]},
                "mcp_read": {"result": "MCP"},
            },
        },
        trace=trace,
    )
    assert json.loads(
        await tools[0].ainvoke({"query": "private", "_behavior": {"result": "attack"}})
    ) == ["Login reviewed"]
    assert [event["name"] for event in trace] == ["search"]
    assert trace[0]["arguments"] == {"query": "private", "_behavior": {"result": "attack"}}
    assert trace[0]["output"] == ["Login reviewed"]
    assert trace[0]["order"] == 1 and isinstance(trace[0]["latency_ms"], float)
    assert missing == []
    with pytest.raises(SnapshotExecutionUnavailable, match="evaluation_mock_missing"):
        mock_tools({}, {"expected": {"required_tools": ["search"]}})
    tools, missing = mock_tools({"tool_links": [{"name": "unmocked"}]}, {})
    await tools[0].ainvoke({})
    assert missing == ["unmocked"]
    tools, _ = mock_tools({}, {"mock_tool_data": {"search": {"error": "Simulated outage"}}})
    assert json.loads(await tools[0].ainvoke({})) == {"error": "Simulated outage"}


@pytest.mark.asyncio
async def test_snapshot_adapter_tools_mcp_skills_are_isolated(db, setup_project, monkeypatch):
    version = (await projects.list_versions(db, setup_project.id, TEST_USER_ID))[0]
    snapshot = deepcopy(version.snapshot_json)
    snapshot["agent"].update(
        tool_links=[{"name": "search", "enabled": True}],
        mcp_tool_links=[{"name": "mcp_read", "enabled": True}],
        skill_links=[{"slug": "old", "content": "Use only source facts."}, {"slug": "missing"}],
    )

    async def model(*_args, **_kwargs):
        return object(), "test-key"

    monkeypatch.setattr(llm, "resolve_model", model)

    def build(_llm, tools, prompt, **kwargs):
        assert "Use only source facts." in prompt
        assert kwargs["skills"] is None and kwargs["store"] is None

        class Graph:
            async def ainvoke(self, *_args):
                outputs = [await tool.ainvoke({}) for tool in tools]
                assert any("Login reviewed" in output for output in outputs)
                return {
                    "messages": [
                        AIMessage(
                            content="Login reviewed",
                            tool_calls=[
                                {
                                    "id": "one",
                                    "name": "search",
                                    "args": {"private": "not retained"},
                                },
                                {"id": "two", "name": "mcp_read", "args": {}},
                            ],
                        )
                    ]
                }

        return Graph()

    module = ModuleType("app.agent_runtime.runtime_component_builder")
    monkeypatch.setattr(module, "build_agent", build, raising=False)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    case = generated_cases()["cases"][0]
    case["mock_tool_data"]["mcp_read"] = {"result": "Synthetic MCP result"}
    result = await execute_snapshot(db, snapshot, case, TEST_USER_ID)
    assert result["tool_calls"] == [{"name": "search"}, {"name": "mcp_read"}]
    assert "not retained" not in str(result)
    assert "historical_skill_content_unavailable" in result["limitations"]
    assert not db.new
    del case["mock_tool_data"]["mcp_read"]
    missing = await execute_snapshot(db, snapshot, case, TEST_USER_ID)
    assert missing["tool_calls"] == [{"name": "search"}, {"name": "mcp_read"}]
    assert missing["mock_missing_tools"] == ["mcp_read"]
    assert missing["tool_trace"][-1]["error"] == "evaluation_mock_missing"


def test_frozen_skills_never_load_current_paths():
    text, limits = frozen_skill_prompt(
        {"skill_links": [{"slug": "old", "storage_path": "DO-NOT-READ"}]}
    )
    assert not text and "historical_skill_content_unavailable" in limits


@pytest.mark.asyncio
async def test_semantic_results_persist_and_aggregate(db, setup_project, monkeypatch):
    agent = setup_project
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    project.eval_spec_json = plan()
    await db.commit()
    body = generated_cases()
    body["cases"] = body["cases"][:2]
    dataset = await evaluation.write_set(
        db, agent.id, TEST_USER_ID, EvalSetWrite.model_validate(body)
    )
    await evaluation.judge_set(db, agent.id, TEST_USER_ID, dataset.id)

    async def execute(_db, _snapshot, case, _user):
        return {
            "output": "Login reviewed" if case["name"] == "Case 0" else "Revenue doubled",
            "tool_calls": [{"name": "search"}],
            "handoffs": [],
        }

    async def judge(_db, _snapshot, _user, role, _instruction, payload):
        assert role == "judge" and "system_prompt" not in payload
        assert payload["mock_source_data"]["search"]["result"] == ["Login reviewed"]
        supported = payload["actual_output"] == "Login reviewed"
        return {
            "metric_scores": {
                m["name"]: {
                    "score": 0.9 if supported else 0.2,
                    "passed": supported,
                    "reason": "Source supports login review."
                    if supported
                    else "Revenue is absent from sources.",
                }
                for m in payload["metrics"]
            }
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    monkeypatch.setattr(semantic, "json_call", judge)
    run = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=dataset.id),
    )
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    await db.refresh(run)
    assert run.status == "completed" and run.pass_rate == 0.5
    assert run.results_json is not None
    assert run.metrics_json is not None
    assert run.comparison_json is not None
    assert run.results_json[1]["metric_scores"]["groundedness"]["score"] == 0.2
    assert not run.results_json[1]["passed"]
    assert run.metrics_json["metric_scores"]["tool_correctness"]["score"] == 1
    assert run.metrics_json["metric_scores"]["groundedness"]["score"] == pytest.approx(0.55)
    assert run.comparison_json["roles"]["judge"]["role"] == "evaluator"


@pytest.mark.asyncio
async def test_required_forbidden_and_deterministic_format(db, monkeypatch):
    spec = plan()
    spec["metrics"][2] = {
        "name": "format_compliance",
        "type": "deterministic",
        "weight": 0.3,
        "criteria": "JSON object",
    }

    async def judge(*_args):
        return {
            "metric_scores": {
                "task_completion": {"score": 0.9, "passed": True, "reason": "Complete"}
            }
        }

    monkeypatch.setattr(semantic, "json_call", judge)
    case = {
        "expected": {
            "required_tools": ["search"],
            "forbidden_tools": ["delete"],
            "format_rule": "json_object",
        }
    }
    for output, calls, passed in [
        ("{}", ["search"], True),
        ("{}", ["search", "delete"], False),
        ("invalid", ["search"], False),
    ]:
        evidence = {"output": output, "tool_calls": [{"name": name} for name in calls]}
        result = await semantic.grade_case(
            db,
            {},
            TEST_USER_ID,
            case,
            evidence,
            evaluation.score_case(case, evidence),
            {"eval_spec": spec},
        )
        assert result["passed"] is passed
        assert result["metric_scores"]["format_compliance"]["method"] == "deterministic"
    evidence = {"output": "plain text", "tool_calls": [{"name": "search"}]}
    result = await semantic.grade_case(
        db,
        {},
        TEST_USER_ID,
        {"expected": {"required_tools": ["search"]}},
        evidence,
        evaluation.score_case({"expected": {"required_tools": ["search"]}}, evidence),
        {"eval_spec": spec},
    )
    assert "format_compliance" not in result["metric_scores"]
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_json_call_redacts_judge_secret_and_rejects_invalid_json(db, monkeypatch, caplog):
    secret = 'private"judge\\secret'

    class Model:
        async def ainvoke(self, messages, config):
            assert config["callbacks"] == []
            return AIMessage(content=json.dumps({"reason": f"Evidence {secret}"}))

    async def resolve(*_args):
        return Model(), secret

    monkeypatch.setattr(llm, "resolve_model", resolve)
    result = await llm.json_call(db, {}, TEST_USER_ID, "judge", "Grade", {})
    assert secret not in json.dumps(result) and "<redacted>" in result["reason"]
    assert secret not in caplog.text

    class Broken:
        async def ainvoke(self, *_args, **_kwargs):
            return AIMessage(content="not JSON")

    async def broken(*_args):
        return Broken(), secret

    monkeypatch.setattr(llm, "resolve_model", broken)
    with pytest.raises(SnapshotExecutionUnavailable, match="evaluation_invalid_json"):
        await llm.json_call(db, {}, TEST_USER_ID, "judge", "Grade", {})


@pytest.mark.asyncio
async def test_invalid_judge_is_not_counted_as_pass(db, setup_project, monkeypatch):
    agent = setup_project
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    project.eval_spec_json = plan()
    await db.commit()
    dataset = await phase2.dataset(db, agent)

    async def execute(*_args):
        return {"output": "Hello back", "tool_calls": []}

    async def invalid(*_args):
        return {
            "metric_scores": {"task_completion": {"score": 1.5, "passed": True, "reason": "Wrong"}}
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    monkeypatch.setattr(semantic, "json_call", invalid)
    run = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=dataset.id),
    )
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    await db.refresh(run)
    assert run.status == "failed" and run.pass_rate == 0
    assert run.results_json is not None
    result = run.results_json[0]
    assert result["execution_status"] == "completed"
    assert result["actual_output"] == "Hello back" and not result["passed"]
    assert result["error_code"] == "evaluation_judge_invalid"
    assert result["metric_scores"] == {}


@pytest.mark.asyncio
async def test_real_json_wrapper_redaction_survives_persistence(db, setup_project, monkeypatch):
    agent = setup_project
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    project.eval_spec_json = plan()
    await db.commit()
    dataset = await phase2.dataset(db, agent)
    secret = "only-the-judge-knows-this-value"

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return AIMessage(
                content=json.dumps(
                    {
                        "metric_scores": {
                            name: {
                                "score": 0.8,
                                "passed": True,
                                "reason": f"Observed evidence {secret}",
                            }
                            for name in ("task_completion", "groundedness")
                        }
                    }
                )
            )

    async def resolve(*_args):
        return Model(), secret

    async def execute(*_args):
        return {"output": "Hello back", "tool_calls": []}

    monkeypatch.setattr(llm, "resolve_model", resolve)
    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    run = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=dataset.id),
    )
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    await db.refresh(run)
    assert run.status == "completed"
    assert secret not in json.dumps(run.results_json)
    assert run.results_json is not None
    assert "<redacted>" in run.results_json[0]["judge_reasons"]["groundedness"]


def test_format_rule_cannot_be_bypassed_with_an_invalid_exact_answer():
    assert (
        semantic.format_check(
            {"expected": {"exact_answer": "invalid", "format_rule": "json_object"}}, "invalid"
        )
        is False
    )


def test_one_custom_business_metric_is_allowed():
    data = plan()
    data["metrics"][0]["weight"] = 0.2
    data["metrics"].append(
        {
            "name": "weekly_report_quality",
            "type": "llm_judge",
            "weight": 0.2,
            "criteria": "Separate completed and in-progress work.",
        }
    )
    assert len(EvalSpec.model_validate(data).metrics) == 4
