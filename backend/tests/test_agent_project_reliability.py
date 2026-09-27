"""Regression contracts for model identity, incomplete evidence and trace preservation."""

import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.credentials import service as credentials
from app.models.user import User
from app.models.user_llm_setting import UserLlmSetting
from app.services import agent_project_llm as llm
from app.services import agent_project_semantic as semantic
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from app.services.agent_project_model_pins import pin_judge, resolve_pinned_judge
from app.services.agent_project_optimization import case_evidence
from app.services.agent_project_optimization_rules import compare_runs, observation
from app.services.agent_project_semantic import grade_case, metric_summary
from tests import test_agent_projects as phase1
from tests.test_agent_project_phase3 import plan
from tests.test_agent_projects import TEST_USER_ID

db = phase1.db


@pytest.mark.asyncio
async def test_judge_pin_survives_settings_change_and_rejects_endpoint_change(db, monkeypatch):
    with pytest.raises(SnapshotExecutionUnavailable, match="judge_not_configured"):
        await pin_judge(db, TEST_USER_ID)
    db.add(User(id=TEST_USER_ID, email="judge@example.invalid", name="Judge"))
    await db.flush()
    cred = await credentials.create(
        db,
        user_id=TEST_USER_ID,
        definition_key="openai",
        name="Private judge",
        data={"api_key": "private-test-key"},
    )
    setting = UserLlmSetting(
        user_id=TEST_USER_ID,
        role="judge_optimizer",
        credential_id=cred.id,
        model_name="test-judge",
    )
    db.add(setting)
    await db.commit()
    pin = await pin_judge(db, TEST_USER_ID)
    setting.model_name = "different-judge"
    await db.commit()
    calls = []
    monkeypatch.setattr(
        "app.agent_runtime.model_factory.create_chat_model",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    await resolve_pinned_judge(db, pin, TEST_USER_ID)
    assert calls[0][0] == ("openai", "test-judge")
    assert calls[0][1]["temperature"] == 0
    assert "api_key" not in pin
    changed = {**pin, "base_url": "https://changed.example.invalid"}
    with pytest.raises(SnapshotExecutionUnavailable, match="endpoint_changed"):
        await resolve_pinned_judge(db, changed, TEST_USER_ID)


@pytest.mark.asyncio
async def test_examinee_keeps_model_parameters(db, monkeypatch):
    from app.models.user import User

    db.add(User(id=TEST_USER_ID, email="params@example.invalid", name="Test"))
    await db.flush()
    cred = await credentials.create(
        db,
        user_id=TEST_USER_ID,
        definition_key="openai",
        name="Test",
        data={"api_key": "test-only"},
    )
    calls = []
    monkeypatch.setattr(
        "app.agent_runtime.model_factory.create_chat_model",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    await llm.resolve_examinee_model(
        db,
        {
            "agent": {
                "model": {"provider": "openai", "model_name": "frozen-model"},
                "llm_credential_id": str(cred.id),
                "model_params": {"temperature": 0.2, "max_tokens": 500},
            }
        },
        TEST_USER_ID,
    )
    assert calls[0][0] == ("openai", "frozen-model")
    assert calls[0][1]["temperature"] == 0.2
    assert calls[0][1]["max_tokens"] == 500


@pytest.mark.asyncio
async def test_unassessed_tool_metric_is_neither_zero_nor_a_pass(db, monkeypatch):
    async def judge(*args):
        return {
            "metric_scores": {
                m["name"]: {"score": 1, "passed": True, "reason": "Observed"}
                for m in args[-1]["metrics"]
            }
        }

    monkeypatch.setattr(semantic, "json_call", judge)
    result = await grade_case(
        db,
        {"agent": {"planned_tools": [{"name": "read"}]}},
        TEST_USER_ID,
        {},
        {"output": "Answer", "tool_calls": []},
        [],
        {"eval_spec": plan()},
    )
    assert result["status"] == "not_evaluated"
    assert result["metric_scores"]["tool_correctness"]["score"] is None
    assert "tool_correctness" not in metric_summary([result])

    named = await grade_case(
        db,
        {},
        TEST_USER_ID,
        {"expected": {"required_tools": ["read"]}},
        {"output": "Answer", "tool_calls": [{"name": "read"}]},
        [{"kind": "required_tool", "passed": True}],
        {"eval_spec": plan()},
    )
    assert named["metric_scores"]["tool_correctness"]["score"] is None


@pytest.mark.parametrize(("field", "value"), [("group", "team-b"), ("week", "2026-W38")])
def test_wrong_week_or_group_never_receives_sources(field, value):
    import json

    from app.services.agent_project_mock_tools import mock_tools
    from app.services.agent_project_weekly_example import TOOLS, dataset

    case = dataset().cases[0].model_dump(mode="json")
    tools, _ = mock_tools({"planned_tools": TOOLS}, case)
    args = {"group": "team-a", "week": "2026-W39", "page": "1", field: value}
    assert json.loads(tools[0].invoke(args)) == {"error": "evaluation_mock_arguments_unmatched"}


def test_regression_rejects_incomplete_quality_without_crashing():
    run = SimpleNamespace(
        dataset_hash="same",
        cases_snapshot_json=[{"id": "case"}],
        eval_set_id=uuid.uuid4(),
        comparison_json={"eval_spec": plan()},
        results_json=[
            {
                "case_id": "case",
                "status": "not_evaluated",
                "metric_scores": {
                    "tool_correctness": {"score": None, "passed": None, "method": "not_evaluated"}
                },
            }
        ],
    )
    comparison = compare_runs(run, deepcopy(run))
    assert comparison["decision"] == "rejected"
    assert "incomplete_quality_evidence" in comparison["reasons"]


def test_failure_analysis_can_cite_actual_tool_arguments_and_errors():
    trace = [{"name": "read", "arguments": {"group": "wrong"}, "error": "permission_denied"}]
    evidence = case_evidence({"id": "case", "input": "Read team-a"}, {"tool_trace": trace})
    assert observation(evidence, "/tool_trace/0/arguments/group") == "wrong"
    assert observation(evidence, "/tool_trace/0/error") == "permission_denied"
