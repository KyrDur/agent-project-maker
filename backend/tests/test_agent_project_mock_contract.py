import json

import pytest

from app.schemas.agent_project import EvaluationCase
from app.services.agent_project_evaluation import score_case
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from app.services.agent_project_mock_tools import mock_tools
from app.services.agent_project_weekly_example import TOOLS, dataset


def test_unknown_and_disabled_tools_cannot_be_injected():
    for config in ({}, {"planned_tools": [{"name": "evil", "enabled": False}]}):
        with pytest.raises(SnapshotExecutionUnavailable, match="not_in_snapshot"):
            mock_tools(config, {"mock_tool_data": {"evil": {"result": "ok"}}})


def test_weekly_pagination_retry_and_isolation():
    case = dataset().cases[1].model_dump(mode="json")
    trace = []
    tools, _ = mock_tools({"planned_tools": TOOLS}, case, trace=trace)
    args = case["mock_tool_data"]["feishu_read"]["rules"][0]["arguments"]
    assert json.loads(tools[0].invoke(args)) == {"error": "timeout"}
    assert json.loads(tools[0].invoke(args))["next_page"] == "2"
    second = {**args, "page": "2"}
    assert json.loads(tools[0].invoke(second))["items"] == ["Billing blocked on review"]
    tools[1].invoke({"group": "team-a", "body": "Search shipped; Billing blocked on review"})
    evidence = {"output": "Done", "tool_calls": trace, "tool_trace": trace}
    assert all(c["passed"] for c in score_case(case, evidence))
    fresh, _ = mock_tools({"planned_tools": TOOLS}, case)
    assert json.loads(fresh[0].invoke(args)) == {"error": "timeout"}
    assert json.loads(tools[0].invoke(args))["error"] == "evaluation_mock_responses_exhausted"
    assert not all(c["passed"] for c in score_case(case, evidence))


def test_wrong_group_does_not_receive_fixture_and_fails():
    case = dataset().cases[0].model_dump(mode="json")
    trace = []
    tools, _ = mock_tools({"planned_tools": TOOLS}, case, trace=trace)
    assert (
        json.loads(tools[0].invoke({"group": "other", "week": "2026-W39", "page": "1"}))["error"]
        == "evaluation_mock_arguments_unmatched"
    )
    checks = score_case(case, {"output": "fabricated", "tool_calls": trace, "tool_trace": trace})
    assert any(c["kind"] == "tool_mock_contract" and not c["passed"] for c in checks)


def test_schema_preserves_rules_and_rejects_invalid_counts():
    case = dataset().cases[0].model_dump(mode="json")
    assert EvaluationCase.model_validate(case).model_dump(mode="json") == case
    case["expected"]["tool_assertions"][0].update(min_calls=2, max_calls=1)
    with pytest.raises(ValueError, match="max_calls must be"):
        EvaluationCase.model_validate(case)
