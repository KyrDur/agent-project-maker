"""Outcome-based simulation acceptance for four task categories."""

import io
import json
import uuid
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from app.exceptions import AppError
from app.schemas.agent_project import (
    CaseExpected,
    EvalRunCreate,
    EvalSetWrite,
    EvaluationCase,
    ProjectRequirements,
)
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_portfolio as portfolio
from app.services import agent_project_practice as practice
from app.services import agent_project_proposals as proposals
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services.agent_project_mock_tools import mock_tools
from app.services.agent_project_optimization_rules import compare_runs
from app.services.agent_project_portfolio_export import export_zip
from tests import test_agent_project_phase2 as phase2
from tests.project_practice_helpers import author_practice

db = phase2.db
client = phase2.client
setup_project = phase2.setup_project
TEST_USER_ID = phase2.TEST_USER_ID


def test_simulation_parameters_state_retry_and_reset():
    case = {
        "initial_state": {"orders": [{"id": "a", "status": "paid"}, {"id": "b", "status": "paid"}]},
        "mock_tool_data": {
            "lookup": {"operation": "query", "collection": "orders", "match_fields": ["id"]},
            "refund": {
                "operation": "update",
                "collection": "orders",
                "match_fields": ["id"],
                "update_fields": ["status"],
                "fail_on_calls": [1],
                "error": "temporary",
            },
        },
    }
    trace = []
    tools, _ = mock_tools({}, case, trace=trace)
    assert json.loads(tools[0].invoke({"id": "b"})) == [{"id": "b", "status": "paid"}]
    assert json.loads(tools[1].invoke({"id": "a", "status": "refunded"}))["error"] == "temporary"
    assert json.loads(tools[1].invoke({"id": "a", "status": "refunded"}))[0]["status"] == "refunded"
    assert trace[-1]["state_after"]["orders"][1]["status"] == "paid"
    fresh, _ = mock_tools({}, case)
    assert json.loads(fresh[0].invoke({"id": "a"}))[0]["status"] == "paid"


def test_outcomes_before_paths_and_necessary_dependencies():
    case: dict[str, Any] = {
        "expected": {"state": [{"path": "orders.0.status", "value": "refunded"}]}
    }
    evidence = {
        "output": "Refunded",
        "tool_calls": [{"name": "alternative"}],
        "final_state": {"orders": [{"status": "refunded"}]},
    }
    assert all(c["passed"] for c in evaluation.score_case(case, evidence))
    case["expected"]["necessary_order"] = ["verify", "refund"]
    assert not all(c["passed"] for c in evaluation.score_case(case, evidence))


@pytest.mark.asyncio
async def test_decision_gate_and_requirement_revision(db, setup_project):
    agent = setup_project
    v = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    dataset = await evaluation.write_set(
        db,
        agent.id,
        TEST_USER_ID,
        EvalSetWrite(
            name="One",
            cases=[
                EvaluationCase(
                    name="One", input="hello", expected=CaseExpected(exact_answer="hello")
                )
            ],
        ),
    )
    await evaluation.judge_set(db, agent.id, TEST_USER_ID, dataset.id)
    await author_practice(db, agent, TEST_USER_ID, dataset.id)
    row = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=v.id, eval_set_id=dataset.id),
    )
    assert row.comparison_json is not None
    old = deepcopy(row.comparison_json["requirements"])
    await practice.write_requirements(
        db,
        agent.id,
        TEST_USER_ID,
        ProjectRequirements(
            goal="Changed",
            inputs="input",
            deliverables="reply",
            business_rules="none",
            success_conditions="accurate",
        ),
    )
    assert row.comparison_json["requirements"] == old
    with pytest.raises(AppError):
        practice.checked_decisions(
            await projects.require_project(db, agent.id, TEST_USER_ID), v.id, dataset
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["writing", "support", "knowledge", "dialogue"])
@pytest.mark.parametrize("candidate_score", [0.9, 0.3, 0.2])
async def test_four_categories_v1_v2_materials(
    db, setup_project, monkeypatch, kind, candidate_score
):
    agent = setup_project
    v1 = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    spec = {
        "metrics": [
            {"name": n, "type": "llm_judge", "weight": w, "criteria": "Meets business expectation"}
            for n, w in [("task_completion", 0.4), ("groundedness", 0.3), ("business_quality", 0.3)]
        ],
        "pass_threshold": 0.7,
        "capability_profile": {"capabilities": ["workflow"]},
    }
    dataset = await evaluation.write_set(
        db,
        agent.id,
        TEST_USER_ID,
        EvalSetWrite(
            name=kind,
            cases=[
                EvaluationCase(
                    name=kind,
                    tags=["workflow"],
                    input=f"Perform {kind} task",
                    judgment_basis="Complete the task accurately",
                    expected=CaseExpected(answer="Complete task using available evidence"),
                )
            ],
        ),
        rubric=spec,
    )
    await evaluation.judge_set(db, agent.id, TEST_USER_ID, dataset.id)
    await author_practice(db, agent, TEST_USER_ID, dataset.id)

    async def execute(_db, snapshot, case, _user):
        good = "Check business expectations" in snapshot["agent"]["system_prompt"]
        return {
            "output": "complete" if good else "incomplete",
            "tool_calls": [],
            "model_calls": [{"model": {"model_name": "fixed-response-test"}}],
            "termination_reason": "completed",
        }

    async def judge(_db, _snapshot, _user, _role, _instruction, payload):
        score = candidate_score if payload["actual_output"] == "complete" else 0.3
        assert payload["observed_sources"] == []
        return {
            "metric_scores": {
                m["name"]: {
                    "score": score,
                    "passed": score >= 0.7,
                    "reason": "Complete task evidence"
                    if score >= 0.7
                    else "Missing business expectation",
                }
                for m in payload["metrics"]
            }
        }

    async def analyze(*_args):
        cid = dataset.cases_json[0]["id"]
        return {
            "analyses": [
                {
                    "case_id": cid,
                    "category": "instruction_issue",
                    "root_cause": "Business expectation missing",
                    "evidence": ["/actual_output"],
                    "recommended_target": "instructions",
                    "suggested_fix": "Check business expectations",
                }
            ],
            "groups": [
                {
                    "case_ids": [cid],
                    "category": "instruction_issue",
                    "root_cause": "Business expectation missing",
                    "target": "instructions",
                    "proposed_change": "Check business expectations",
                }
            ],
        }

    async def propose(*_args):
        return {
            "proposals": [
                {
                    "title": f"Approach {i}",
                    "affected_capabilities": ["workflow"],
                    "changes": [
                        {
                            "group_index": 0,
                            "target": "instructions",
                            "operation": "append",
                            "content": "Check business expectations" + "." * i,
                            "reason": "Addresses observed missing expectation",
                        }
                    ],
                }
                for i in (1, 2)
            ]
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    monkeypatch.setattr(semantic, "json_call", judge)
    from app.services import agent_project_optimization as optimization

    monkeypatch.setattr(optimization, "json_call", analyze)
    monkeypatch.setattr(proposals, "json_call", propose)
    baseline = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=v1.id, eval_set_id=dataset.id),
    )
    await evaluation.execute_run(baseline.id, agent.id, TEST_USER_ID)
    await db.refresh(baseline)
    assert baseline.pass_rate == 0
    proposal = await proposals.generate(db, agent.id, TEST_USER_ID, baseline.id, uuid.uuid4())
    pid = uuid.UUID(proposal["id"])
    await proposals.decide(
        db,
        agent.id,
        TEST_USER_ID,
        baseline.id,
        pid,
        "accepted",
        "Addresses the missing business expectation",
    )
    regression = await proposals.regression(
        db, agent.id, TEST_USER_ID, baseline.id, pid, uuid.uuid4()
    )
    await evaluation.execute_run(regression.id, agent.id, TEST_USER_ID)
    await db.refresh(regression)
    assert regression.pass_rate == (1 if candidate_score >= 0.7 else 0)
    assert compare_runs(baseline, regression)["outcome"] == (
        "improved"
        if candidate_score > 0.3
        else "unchanged"
        if candidate_score == 0.3
        else "regressed"
    )
    assert (
        await practice.completion(
            db,
            agent.id,
            TEST_USER_ID,
            "V1 missed a business condition. V2 addressed it. Simulation coverage remains limited.",
        )
    )["status"] == "completed"
    report = await portfolio.report(db, agent.id, TEST_USER_ID)
    assert report["evidence"]["results"]["metric_deltas"]["task_completion"] == pytest.approx(
        candidate_score - 0.3
    )
    resume = await portfolio.resume(db, agent.id, TEST_USER_ID, "ai_product")
    from app.services.agent_project_materials import interview

    questions = await interview(db, agent.id, TEST_USER_ID)
    assert report["evidence_hash"] == resume["evidence_hash"] == questions["evidence_hash"]
    archive = zipfile.ZipFile(io.BytesIO(await export_zip(db, agent.id, TEST_USER_ID)))
    assert (
        json.loads(archive.read("agent-project/interview.json"))["evidence_hash"]
        == questions["evidence_hash"]
    )
    assert "模拟" in report["markdown"]


def test_regression_reports_ties_and_drops():
    def run(score):
        return SimpleNamespace(
            dataset_hash="same",
            cases_snapshot_json=[{"id": "one"}],
            eval_set_id="same",
            comparison_json={
                "eval_spec": {"metrics": [{"name": "task_completion", "type": "llm_judge"}]}
            },
            results_json=[
                {
                    "case_id": "one",
                    "status": "passed" if score >= 0.7 else "failed",
                    "metric_scores": {"task_completion": {"score": score, "passed": score >= 0.7}},
                }
            ],
        )

    assert compare_runs(run(0.9), run(0.9))["outcome"] == "unchanged"
    assert compare_runs(run(0.9), run(0.2))["outcome"] == "regressed"


@pytest.mark.asyncio
async def test_actual_graph_records_model_returns_and_tool_state(db, monkeypatch):
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from app.services import agent_project_llm
    from app.services.agent_project_executor import execute_snapshot

    class ControlledModel(BaseChatModel):
        model_name: str = "controlled-graph-model"

        @property
        def _llm_type(self):
            return "controlled-test"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(isinstance(m, ToolMessage) for m in messages):
                answer = AIMessage(content="Order a is paid.")
            else:
                answer = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "lookup-1",
                            "name": "lookup",
                            "args": {"id": "a"},
                            "type": "tool_call",
                        }
                    ],
                )
            return ChatResult(generations=[ChatGeneration(message=answer)])

    async def resolve(*_args, **_kwargs):
        return ControlledModel(), "test-key-never-persist"

    monkeypatch.setattr(agent_project_llm, "resolve_model", resolve)
    snapshot = {
        "schema_version": 1,
        "agent": {
            "model": {"model_name": "intended-model"},
            "system_prompt": "Look up the order, then answer.",
            "planned_tools": [
                {
                    "tool_name": "lookup",
                    "input_schema": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    },
                }
            ],
        },
    }
    case = {
        "input": "Check order a",
        "initial_state": {"orders": [{"id": "a", "status": "paid"}]},
        "mock_tool_data": {
            "lookup": {"operation": "query", "collection": "orders", "match_fields": ["id"]}
        },
    }
    result = await execute_snapshot(db, snapshot, case, TEST_USER_ID)
    assert result["output"] == "Order a is paid."
    assert result["tool_trace"][0]["arguments"] == {"id": "a"}
    assert len(result["model_calls"]) == 2
    assert result["model_calls"][0]["model"]["model_name"] == "controlled-graph-model"
    assert result["model_calls"][1]["returns"][0]["content"] == "Order a is paid."
    assert "test-key-never-persist" not in json.dumps(result)

    # Frozen actual model selection cannot silently switch between V1 and V2.
    from app.services.agent_project_call_evidence import model_descriptor
    from app.services.agent_project_executor import SnapshotExecutionUnavailable

    snapshot["resolved_examinee"] = model_descriptor(ControlledModel())

    async def changed(*_args, **_kwargs):
        return ControlledModel(model_name="different-model"), "test-key-never-persist"

    monkeypatch.setattr(agent_project_llm, "resolve_model", changed)
    with pytest.raises(
        SnapshotExecutionUnavailable, match="evaluation_examinee_configuration_changed"
    ) as caught:
        await execute_snapshot(db, snapshot, case, TEST_USER_ID)
    assert caught.value.evidence["model_calls"] == []
    assert (
        caught.value.evidence["termination_reason"] == "evaluation_examinee_configuration_changed"
    )


def test_credential_reference_redaction_is_idempotent_and_values_remain_hidden():
    reference = str(uuid.uuid4())
    value = {
        "role_configurations": {"builder": {"credential_id": reference}},
        "agent": {"llm_credential_id": reference},
        "api_key": "sk-private-value",
    }
    clean = projects.snapshot_value(value)
    assert clean["agent"]["llm_credential_id"] == reference
    assert clean["role_configurations"]["builder"]["credential_id"] == reference
    assert clean["api_key"] == "<redacted>"
    assert projects.snapshot_value(clean) == clean
