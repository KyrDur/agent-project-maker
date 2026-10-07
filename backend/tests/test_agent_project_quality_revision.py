"""Developer-authored counterexamples; fixed responses do not calibrate real model C."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.agent_project import EvalSpec
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_semantic as semantic
from app.services.agent_project_case_cards import decision_author
from app.services.agent_project_optimization_rules import trial_outcomes
from app.services.agent_project_preflight import preflight_case
from app.services.agent_project_rubric import validate_facts
from tests.conftest import TEST_USER_ID
from tests.test_agent_project_scoring import REQUIREMENTS, case_for, structured_plan, verdicts


def quality_plan():
    raw = structured_plan()
    raw["rubric_version"] = 3
    raw["pass_threshold_reason"] = "要求核心判据完整满足；0.75 排除仅部分满足的 0.5 档。"
    raw["metrics"][1]["verdict_role"] = "quality"
    return raw


def test_resume_attributes_regression_to_the_confirmed_source_run():
    from app.services.agent_project_materials import resume_material

    decision = {
        "stage": "optimization",
        "author": "user_confirmed",
        "version": "V1",
        "source_run_id": "experiment-2",
        "choice": "先核验订单",
        "reason": "优先修复工具",
    }
    comparison = {
        "source_version": 1,
        "target_version": 2,
        "source_run_id": "experiment-2",
        "kind": "adjacent",
        "comparable": True,
        "changes": {
            "pass_rate": {"before": 0.6, "after": 0.55},
            "fixed_cases": ["a", "b", "c", "d"],
            "regressed_cases": ["e", "f", "g", "h", "i"],
        },
    }
    data = {
        "project": {"name": "客服", "goal": "模拟验证"},
        "decisions": [decision],
        "evaluation_design": {},
        "results": {"comparisons": [comparison]},
    }
    text = " ".join(resume_material(data)["bullets"])
    assert "60.0%→55.0%" in text
    assert "修复 4 条、新增失败 5 条" in text
    assert "优先修复工具" in text
    # Another experiment on the same source version is not this personal decision.
    decision["source_run_id"] = "experiment-8"
    assert "%" not in " ".join(resume_material(data)["bullets"])


def test_demo_interview_does_not_claim_personal_confirmation():
    from app.services.agent_project_materials import interview_material

    data = {
        "project": {"name": "演示", "goal": "模拟验证。"},
        "decisions": [{"stage": "requirements", "author": "codex_demo"}],
        "results": {"comparisons": []},
    }
    introduction = interview_material(data)["introduction"]
    assert "未保存个人确认" in introduction
    assert "我能依据" not in introduction
    assert "。。" not in introduction


@pytest.mark.asyncio
async def test_judge_protocol_retry_preserves_the_original_evidence(db, monkeypatch):
    raw = quality_plan()
    first: dict[str, Any] = verdicts(raw)
    first["criterion_results"]["task_completion"][0]["evidence"] *= 6
    first["fact_results"] = []
    corrected: dict[str, Any] = verdicts(raw)
    corrected["fact_results"] = []
    payloads = []

    async def judge(_db, _snapshot, _owner, _role, _instruction, payload):
        payloads.append(deepcopy(payload))
        return first if len(payloads) == 1 else corrected

    monkeypatch.setattr(semantic, "json_call", judge)
    result = await semantic.grade_case(
        db,
        {},
        TEST_USER_ID,
        case_for(raw),
        {"output": "订单已发货"},
        [],
        {
            "eval_spec": raw,
            "requirements": REQUIREMENTS,
            "execution_protocol": {"judge_validation_retry_limit": 1},
        },
    )
    assert result["status"] == "passed"
    assert len(payloads) == 2
    assert payloads[0]["evidence_sources"] == payloads[1]["evidence_sources"]
    assert payloads[1]["previous_verdict"] == first
    assert len(first["criterion_results"]["task_completion"][0]["evidence"]) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_fact", ["平铺测量", "已登记转接人工客服", "提供订单号可核实价保"])
async def test_unsupported_facts_override_high_judge_scores(db, monkeypatch, extra_fact):
    raw = quality_plan()
    response: dict[str, Any] = verdicts(raw)
    response["fact_results"] = [
        {"claim": extra_fact, "kind": "fact", "verdict": "unsupported", "evidence": []}
    ]

    async def judge(*args):
        return response

    monkeypatch.setattr(semantic, "json_call", judge)
    result = await semantic.grade_case(
        db,
        {},
        TEST_USER_ID,
        case_for(raw),
        {"output": "订单已发货；" + extra_fact},
        [],
        {"eval_spec": raw, "requirements": REQUIREMENTS},
    )
    assert result["status"] == "failed"
    assert result["fact_check"]["unsupported"] == 1
    assert all(m["score"] == 1 for m in result["metric_scores"].values())


@pytest.mark.asyncio
async def test_missing_greeting_only_affects_quality(db, monkeypatch):
    raw = quality_plan()
    response: dict[str, Any] = verdicts(raw)
    response["criterion_results"]["business_quality"][0]["level"] = 0
    response["fact_results"] = [
        {
            "claim": "订单已发货",
            "kind": "fact",
            "verdict": "supported",
            "evidence": [{"reference": "tool_trace/0/output", "quote": "已发货"}],
        }
    ]

    async def judge(*args):
        return response

    monkeypatch.setattr(semantic, "json_call", judge)
    result = await semantic.grade_case(
        db,
        {},
        TEST_USER_ID,
        case_for(raw),
        {"output": "订单已发货", "tool_trace": [{"name": "query", "output": "已发货"}]},
        [],
        {"eval_spec": raw, "requirements": REQUIREMENTS},
    )
    assert result["status"] == "passed"
    assert result["metric_scores"]["business_quality"]["score"] == 0


def test_minimal_tool_free_contract_and_no_keyword_retrieval_inference():
    raw = quality_plan()
    raw["metrics"] = raw["metrics"][:1]
    raw["metrics"][0]["weight"] = 1
    assert len(EvalSpec.model_validate(raw).metrics) == 1
    profile = semantic.capability_profile(
        {
            "agent": {
                "system_prompt": "knowledge retrieval",
                "skill_links": [{"content": "writing guide"}],
            }
        }
    )
    assert profile["capabilities"] == ["conversation"]


@pytest.mark.parametrize("mutation", ["self", "hidden", "invented", "duplicate"])
def test_fact_evidence_cannot_be_invented_or_self_supporting(mutation):
    fact = {
        "claim": "平铺测量",
        "kind": "fact",
        "verdict": "supported",
        "evidence": [{"reference": "output", "quote": "平铺测量"}],
    }
    if mutation == "hidden":
        fact["evidence"][0]["reference"] = "mock_tool_data/hidden"
    if mutation == "invented":
        fact["claim"] = "编造"
    facts = [fact, deepcopy(fact)] if mutation == "duplicate" else [fact]
    with pytest.raises(
        ValueError,
        match="answer|Fact|fact|Duplicate|capability|tool|Reference|Recovery|response|injected|Static",
    ):
        validate_facts({"output": "平铺测量"}, facts)


def reference_case():
    return {
        "input": "把订单 a 标记为退款",
        "tags": ["tool_failure"],
        "recovery_goal": True,
        "initial_state": {"orders": [{"id": "a", "status": "paid"}]},
        "mock_tool_data": {
            "refund": {
                "operation": "update",
                "collection": "orders",
                "match_fields": ["id"],
                "update_fields": ["status"],
                "error": "temporary",
                "fail_on_calls": [1],
            }
        },
        "expected": {"state": [{"path": "orders.0.status", "value": "refunded"}]},
        "reference_answer": "退款状态已更新",
        "reference_trace": [
            {"name": "refund", "arguments": {"id": "a", "status": "refunded"}},
            {"name": "refund", "arguments": {"id": "a", "status": "refunded"}},
        ],
    }


def test_reference_path_recovery_writes_observable_state_and_is_isolated():
    config = {"planned_tools": [{"name": "refund"}]}
    case = reference_case()
    first = preflight_case(config, case)
    second = preflight_case(config, case)
    assert first["reference_evidence"]["final_state"] == second["reference_evidence"]["final_state"]
    assert first["checks"] == second["checks"]
    assert case["initial_state"]["orders"][0]["status"] == "paid"
    assert first["reference_evidence"]["final_state"]["orders"][0]["status"] == "refunded"


@pytest.mark.parametrize("mutation", ["wrong_type", "invalid_schema", "external_reference"])
def test_reference_parameter_schema_is_checked_without_external_resolution(mutation):
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    }
    case = reference_case()
    if mutation == "wrong_type":
        case["reference_trace"][0]["arguments"]["id"] = 42
    elif mutation == "invalid_schema":
        schema["type"] = "not_a_json_schema_type"
    else:
        schema["$ref"] = "https://example.invalid/tool-schema.json"
    with pytest.raises(ValueError, match="Reference path|parameter schema|external resources"):
        preflight_case({"planned_tools": [{"name": "refund", "input_schema": schema}]}, case)


@pytest.mark.parametrize(
    "mutation", ["missing", "unknown", "no_recovery", "wrong_parameter", "missing_response"]
)
def test_environment_errors_block_reference_freezing(mutation):
    config = {"planned_tools": [{"name": "refund"}]}
    case = reference_case()
    if mutation == "missing":
        config["planned_tools"].append({"name": "handoff"})
    elif mutation == "unknown":
        case["mock_tool_data"]["undeclared"] = {"result": "fake"}
    elif mutation == "no_recovery":
        case["mock_tool_data"]["refund"]["fail_on_calls"] = []
        case["mock_tool_data"]["refund"]["error"] = None
    elif mutation == "wrong_parameter":
        case["reference_trace"][1]["arguments"]["id"] = "b"
    else:
        case["mock_tool_data"]["refund"] = {
            "responses": [{"arguments": {"id": "b"}, "result": "ok"}]
        }
    with pytest.raises(
        ValueError,
        match="answer|Fact|fact|Duplicate|capability|tool|Reference|Recovery|response|injected|Static",
    ):
        preflight_case(config, case)


def test_repeats_preserve_failure_instead_of_selecting_best():
    results = [
        {
            "case_id": "a",
            "trial": trial,
            "status": status,
            "metric_scores": {"task_completion": {"score": score, "passed": score >= 0.7}},
        }
        for trial, status, score in [(1, "passed", 1), (2, "failed", 0), (3, "passed", 1)]
    ]
    outcome = trial_outcomes(results)["a"]
    assert outcome["status"] == "failed"
    assert outcome["metric_scores"]["task_completion"]["score"] == pytest.approx(2 / 3)
    stats = evaluation.outcome_statistics([{"id": "a"}], results, 3)
    assert stats["trial_pass_rates"] == [1, 0, 1]
    assert stats["trial_range"] == 1
    assert stats["fact_support"] is None
    assert stats["operation_success"]["total"] == 0


def test_codex_demonstration_is_not_a_user_contribution():
    assert decision_author({"reason": "【Codex 操作演示记录，非用户本人撰写】"}) == "codex_demo"


def test_incomplete_trials_are_unavailable_and_operation_denominators_stay_frozen():
    cases = [
        {
            "id": "a",
            "expected": {"state": [{"path": "done", "value": True}]},
            "recovery_goal": True,
        },
        {"id": "b", "expected": {"state": [{"path": "done", "value": True}]}},
    ]
    results = [
        {
            "case_id": "a",
            "trial": 1,
            "status": "passed",
            "execution_status": "completed",
            "assertions": [{"kind": "final_state", "passed": True}],
        }
    ]
    stats = evaluation.outcome_statistics(cases, results, 3)
    assert stats["trial_pass_rates"] == [None, None, None]
    assert stats["trial_range"] is None
    assert stats["stability"] == "incomplete_trials"
    assert stats["operation_success"] == {"successful": 1, "total": 6}
    assert stats["recovery_success"] == {"successful": 1, "total": 3}


def test_explicit_forbidden_operations_count_as_critical_violations():
    stats = evaluation.outcome_statistics(
        [{"id": "a"}],
        [
            {
                "case_id": "a",
                "status": "failed",
                "assertions": [{"kind": "forbidden_tool", "passed": False}],
            }
        ],
        1,
    )
    assert stats["critical_violations"] == {"violating": 1, "total": 1}


def test_usage_does_not_double_count_invocation_and_return_metadata():
    usage = {"total_count": 10, "input_count": 6, "output_count": 4}
    stats = evaluation.outcome_statistics(
        [{"id": "a"}],
        [
            {
                "case_id": "a",
                "status": "passed",
                "model_calls": [{"accounting": usage, "returns": [{"accounting": usage}]}],
            }
        ],
        1,
    )
    assert stats["model_accounting"]["total_count"] == 10


@pytest.mark.parametrize("source", ["tool_trace/0/name", "tool_trace/0/arguments"])
def test_tool_request_cannot_prove_factual_success(source):
    with pytest.raises(ValueError, match="tool request"):
        validate_facts(
            {"output": "已经转接", source: "escalate"},
            [
                {
                    "claim": "已经转接",
                    "kind": "fact",
                    "verdict": "supported",
                    "evidence": [{"reference": source, "quote": "escalate"}],
                }
            ],
        )


@pytest.mark.asyncio
async def test_unknown_fact_is_a_judge_error_with_preserved_evidence(db, monkeypatch):
    from app.services.agent_project_executor import SnapshotExecutionUnavailable

    raw = quality_plan()
    response: dict[str, Any] = verdicts(raw)
    response["fact_results"] = [
        {"claim": "订单已发货", "kind": "fact", "verdict": "unknown", "evidence": []}
    ]

    async def judge(*args):
        return response

    monkeypatch.setattr(semantic, "json_call", judge)
    with pytest.raises(
        SnapshotExecutionUnavailable, match="evaluation_judge_unassessable"
    ) as failure:
        await semantic.grade_case(
            db,
            {},
            TEST_USER_ID,
            case_for(raw),
            {"output": "订单已发货"},
            [],
            {"eval_spec": raw, "requirements": REQUIREMENTS},
        )
    assert failure.value.evidence["fact_check"]["unknown"] == 1
    assert failure.value.evidence["fact_check"]["items"][0]["claim"] == "订单已发货"


@pytest.mark.parametrize("arguments", [{}, {"id": 7}, {"id": "a", "status": "invented"}])
def test_runtime_enforces_the_same_parameter_contract_before_writes(arguments):
    import json

    from app.services.agent_project_mock_tools import mock_tools

    schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"const": "refunded"}},
        "required": ["id", "status"],
        "additionalProperties": False,
    }
    case = {
        "initial_state": {"orders": [{"id": "a", "status": "paid"}]},
        "mock_tool_data": {
            "refund": {
                "operation": "update",
                "collection": "orders",
                "match_fields": ["id"],
                "update_fields": ["status"],
            }
        },
    }
    trace = []
    tools, missing = mock_tools(
        {"planned_tools": [{"tool_name": "refund", "input_schema": schema}]}, case, trace=trace
    )
    assert json.loads(tools[0].invoke(arguments)) == {"error": "invalid_tool_arguments"}
    assert trace[-1]["state_after"]["orders"][0]["status"] == "paid"
    assert missing == []
    assert json.loads(tools[0].invoke({"id": "a", "status": "refunded"}))[0]["status"] == "refunded"


def test_null_mock_responses_are_environment_errors_in_reference_and_runtime():
    import json

    from app.services.agent_project_mock_tools import mock_tools

    config = {"planned_tools": [{"tool_name": "lookup"}]}
    case = {
        "mock_tool_data": {"lookup": {"responses": [{"arguments": {}, "result": None}]}},
        "reference_answer": "无法查询",
    }
    with pytest.raises(ValueError, match="explicit data"):
        preflight_case(config, case)
    trace = []
    tools, missing = mock_tools(config, case, trace=trace)
    assert json.loads(tools[0].invoke({}))["error"] == "evaluation_mock_response_missing"
    assert missing == ["lookup"]
    assert trace[0]["error"] == "evaluation_mock_response_missing"
    assert decision_author({"reason": "优先修复工具"}) == "user_confirmed"


def test_no_fabricated_two_cases():
    from app.services.agent_project_case_cards import case_cards

    run = SimpleNamespace(
        version_id="v",
        cases_snapshot_json=[{"id": "a", "input": "hello", "name": "hello"}],
        results_json=[{"case_id": "a", "status": "passed", "output": "hello"}],
        comparison_json={},
    )
    assert len(case_cards([run], {"v": SimpleNamespace(version_number=1)}, [], [])) == 1


def test_v3_critical_partial_cannot_be_offset():
    from app.services.agent_project_rubric import aggregate_verdicts

    raw = quality_plan()
    raw["metrics"][0]["scoring_criteria"][0]["critical"] = True
    additional = deepcopy(raw["metrics"][0]["scoring_criteria"][0])
    additional.update(id="additional", critical=False)
    raw["metrics"][0]["scoring_criteria"].append(additional)
    case = case_for(raw)
    values = verdicts(raw)
    values["criterion_results"]["task_completion"][0]["level"] = 0.5
    scored = aggregate_verdicts(
        EvalSpec.model_validate(raw), case, {"output": "订单已发货"}, values
    )
    assert scored["task_completion"]["score"] == 0
    assert scored["task_completion"]["critical_failure"] is True


def test_analysis_retains_all_trial_answers():
    from app.services.agent_project_optimization import analysis_evidence

    case = {"id": "a", "input": "query", "expected": {}}
    trials = [
        {"case_id": "a", "trial": n, "status": status, "output": output}
        for n, status, output in [
            (1, "passed", "done"),
            (2, "failed", "wrong"),
            (3, "passed", "done"),
        ]
    ]
    item = analysis_evidence({"a": case}, trials)["a"]
    assert item["actual_output"] == "wrong"
    assert [t["actual_output"] for t in item["trials"]] == ["done", "wrong", "done"]


def test_best_version_uses_all_v3_runs_not_one_peak():
    import uuid
    from datetime import datetime

    from app.schemas.agent_project_report import EvaluationReport
    from app.services.agent_project_report import select_best_reports

    versions = [uuid.uuid4(), uuid.uuid4()]
    reports = [
        EvaluationReport(
            version_id=versions[v],
            eval_set_id=uuid.uuid4(),
            evaluation_run_id=uuid.uuid4(),
            status="completed",
            score=passed / 20,
            metrics={},
            total=20,
            passed=passed,
            bad_case_count=20 - passed,
            bad_cases=[],
            optimization_suggestions=[],
            comparison_key="same",
            created_at=datetime(2026, 10, 7),
            eval_spec={"rubric_version": 3},
        )
        for v, passed in [(0, 20), (0, 0), (1, 14)]
    ]
    assert select_best_reports(reports)["same"].version_id == versions[1]


def test_conditional_task_criteria_need_frozen_non_applicability_reason():
    from app.services.agent_project_rubric import validate_applicability

    raw = quality_plan()
    criterion = deepcopy(raw["metrics"][0]["scoring_criteria"][0])
    criterion["id"] = "conditional"
    raw["metrics"][0]["scoring_criteria"].append(criterion)
    case = case_for(raw)
    case["metric_applicability"]["task_completion"] = ["condition"]
    with pytest.raises(ValueError, match="excluded criterion"):
        validate_applicability(EvalSpec.model_validate(raw), case)
    case["metric_applicability_reasons"] = {
        "task_completion/conditional": "本场景资料齐全，不需要缺失字段澄清。"
    }
    validate_applicability(EvalSpec.model_validate(raw), case)
    case["metric_applicability"]["task_completion"] = []
    with pytest.raises(ValueError, match="cannot be excluded"):
        validate_applicability(EvalSpec.model_validate(raw), case)


@pytest.mark.asyncio
@pytest.mark.parametrize("always_reject", [False, True])
async def test_reference_repairs_only_rejected_cases_and_rechecks_every_case(always_reject):
    import uuid

    from app.schemas.agent_project import EvalSetWrite
    from app.services.agent_project_preflight import validate_generated_cases

    raw = quality_plan()
    first, second = [str(uuid.uuid4()) for _ in range(2)]
    cases = [
        {
            **case_for(raw),
            "id": cid,
            "name": f"case {i}",
            "tags": ["normal"],
            "reference_answer": "订单已发货",
        }
        for i, cid in enumerate([first, second])
    ]
    body = EvalSetWrite.model_validate({"name": "reference repair", "cases": cases})
    for case in body.cases:
        case.expected.answer = "如实回答订单状态"
    calls = []

    async def call(role, instruction, payload):
        calls.append((role, deepcopy(payload)))
        if role == "judge":
            return {
                "rule_reviews": [
                    {
                        "reference": cid,
                        "supported": cid != first or (not always_reject and len(calls) > 1),
                        "reason": "核对参考事实",
                    }
                    for cid in [first, second]
                ]
            }
        assert {c["id"] for c in payload["cases"]} == {first}
        repaired = deepcopy(payload["cases"][0])
        repaired["reference_answer"] = "订单待发货"
        return {"name": "repair", "cases": [repaired]}

    if always_reject:
        with pytest.raises(semantic.SnapshotExecutionUnavailable) as error:
            await validate_generated_cases(
                {}, REQUIREMENTS, EvalSpec.model_validate(raw), body, ["normal"], call
            )
        assert error.value.code == "evaluation_reference_invalid"
        proof = error.value.evidence
        assert len(proof["reference_validation"]["attempts"]) == 3
        assert proof["reference_validation"]["attempts"][-1]["rejections"] == {
            first: "核对参考事实"
        }
        assert {c["id"] for c in proof["rejected_cases"]} == {first, second}
        assert len(calls) == 5  # Three reviews, exactly two repair calls, no freeze.
        return
    updated, validation = await validate_generated_cases(
        {}, REQUIREMENTS, EvalSpec.model_validate(raw), body, ["normal"], call
    )
    assert updated.cases[0].reference_answer == "订单待发货"
    assert updated.cases[1].reference_answer == "订单已发货"
    assert [role for role, _ in calls] == ["judge", "case_generator", "judge"]
    assert set(calls[-1][1]["reference_results"]) == {first, second}
    assert len(validation["attempts"]) == 2
    assert validation["attempts"][0]["rejections"] == {first: "核对参考事实"}
    assert validation["attempts"][1]["rejections"] == {}


def test_model_accounting_keeps_numeric_usage_and_missing_is_unavailable():
    from app.services.agent_project_call_evidence import accounting
    from app.services.agent_project_llm import safe_value

    value = accounting(
        SimpleNamespace(
            usage_metadata={
                "input_tokens": 17,
                "output_tokens": 5,
                "total_tokens": 22,
                "api_key": "private",
            }
        )
    )
    assert safe_value(value, "private") == {"input_count": 17, "output_count": 5, "total_count": 22}
    assert accounting(SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_frozen_personal_role_parameters_cannot_drift(db, monkeypatch):
    from app.agent_runtime import model_factory
    from app.services import agent_project_llm as llm
    from app.services.agent_project_call_evidence import model_descriptor
    from app.services.system_credential_resolver import ResolvedSystemModel

    model = SimpleNamespace(model_name="personal", temperature=0.2)

    async def resolve(*args):
        return ResolvedSystemModel(
            provider="openai", model_name="personal", api_key="dummy", base_url=None
        )

    monkeypatch.setattr(llm, "resolve_system_model", resolve)
    monkeypatch.setattr(model_factory, "create_chat_model", lambda *args, **kwargs: model)
    frozen = {"resolved_role_models": {"judge_optimizer": model_descriptor(model)}}
    await llm.resolve_model(db, frozen, TEST_USER_ID, "judge")
    model.temperature = 0.8
    with pytest.raises(semantic.SnapshotExecutionUnavailable, match="configuration_changed"):
        await llm.resolve_model(db, frozen, TEST_USER_ID, "judge")
