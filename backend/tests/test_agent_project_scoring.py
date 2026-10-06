"""Controlled scoring contracts; no live models or external services."""

from copy import deepcopy

import pytest

from app.schemas.agent_project import EvalSpec
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_rubric as rubric
from app.services import agent_project_semantic as semantic
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from tests import test_agent_project_phase3 as phase3

REQUIREMENTS = {
    "goal": "Complete the supplied task",
    "inputs": "Frozen test input",
    "deliverables": "Task answer",
    "business_rules": "Follow explicit test rules",
    "success_conditions": "Satisfy the stored expectations",
}


def structured_plan(*, tools=False):
    raw = phase3.plan()
    raw["rubric_version"] = 2
    if not tools:
        raw["metrics"][1].update(name="business_quality", type="llm_judge")
    for m in raw["metrics"]:
        m.update(
            display_name="任务检查",
            description="检查已确认的模拟要求。",
            requirement_refs=[{"field": "goal", "quote": REQUIREMENTS["goal"]}],
            scoring_mode="all_checks" if m["type"] == "deterministic" else "criterion_mean",
            scoring_criteria=[]
            if m["type"] == "deterministic"
            else [
                {
                    "id": "condition",
                    "description": "完成已确认任务。",
                    "requirement_refs": [
                        {"field": "success_conditions", "quote": REQUIREMENTS["success_conditions"]}
                    ],
                    "fail": "未满足",
                    "partial": "部分满足",
                    "full": "全部满足",
                    "critical": False,
                }
            ],
        )
        if m["type"] == "deterministic":
            m["criteria"] = rubric.TOOL_RULE
    return raw


def case_for(raw):
    return {
        "input": "查询订单",
        "context": [],
        "expected": {},
        "metric_applicability": {
            m["name"]: [c["id"] for c in m["scoring_criteria"]]
            for m in raw["metrics"]
            if m["type"] == "llm_judge"
        },
        "metric_applicability_reasons": {},
    }


def verdicts(raw):
    return {
        "criterion_results": {
            name: [
                {
                    "criterion_id": cid,
                    "level": 1,
                    "reason": "根据实际回复判断。",
                    "evidence": [{"reference": "output", "quote": "订单已发货"}],
                }
                for cid in ids
            ]
            for name, ids in case_for(raw)["metric_applicability"].items()
        }
    }


@pytest.mark.parametrize(
    "mutation", ["source", "method", "anchor", "duplicate", "explanation", "program"]
)
def test_invalid_contract(mutation):
    raw = structured_plan(tools=True)
    m = raw["metrics"][0]
    if mutation == "source":
        m["requirement_refs"][0]["quote"] = "未确认的额外规则"
    elif mutation == "method":
        raw["metrics"][1]["scoring_mode"] = "criterion_mean"
    elif mutation == "anchor":
        m["scoring_criteria"][0]["partial"] = ""
    elif mutation == "duplicate":
        m["scoring_criteria"] *= 2
    elif mutation == "explanation":
        m["display_name"] = None
    else:
        raw["metrics"][1]["criteria"] = "按比例计分"
    with pytest.raises(
        ValueError, match="validation error|Scoring|scoring|requirement|criterion|execution|Judge"
    ):
        rubric.validate_sources(EvalSpec.model_validate(raw), REQUIREMENTS)


@pytest.mark.parametrize(
    "mutation", ["level", "quote", "reference", "missing", "duplicate", "input_only"]
)
def test_invalid_judge(mutation):
    raw = structured_plan()
    value = verdicts(raw)
    row = value["criterion_results"]["task_completion"][0]
    if mutation == "level":
        row["level"] = 0.93
    elif mutation == "quote":
        row["evidence"][0]["quote"] = "编造的证据"
    elif mutation == "reference":
        row["evidence"][0]["reference"] = "mock_tool_data/hidden"
    elif mutation == "missing":
        value["criterion_results"]["task_completion"] = []
    elif mutation == "duplicate":
        value["criterion_results"]["task_completion"] *= 2
    else:
        row["evidence"] = [{"reference": "input", "quote": "查询订单"}]
    with pytest.raises(
        ValueError, match="validation error|Scoring|scoring|requirement|criterion|execution|Judge"
    ):
        rubric.aggregate_verdicts(
            EvalSpec.model_validate(raw),
            case_for(raw),
            {"output": "订单已发货", "input": "查询订单"},
            value,
        )


def test_applicability():
    raw = structured_plan()
    case = case_for(raw)
    case["metric_applicability"]["task_completion"] = []
    with pytest.raises(ValueError, match="Task completion"):
        rubric.validate_applicability(EvalSpec.model_validate(raw), case)
    case = case_for(raw)
    case["metric_applicability"]["groundedness"] = []
    with pytest.raises(ValueError, match="reason"):
        rubric.validate_applicability(EvalSpec.model_validate(raw), case)
    case["metric_applicability_reasons"]["groundedness"] = "无事实性陈述"
    rubric.validate_applicability(EvalSpec.model_validate(raw), case)


def test_mean_and_critical():
    raw = structured_plan()
    second = deepcopy(raw["metrics"][0]["scoring_criteria"][0])
    second["id"] = "additional"
    raw["metrics"][0]["scoring_criteria"].append(second)
    value = verdicts(raw)
    value["criterion_results"]["task_completion"][1]["level"] = 0
    result = rubric.aggregate_verdicts(
        EvalSpec.model_validate(raw), case_for(raw), {"output": "订单已发货"}, value
    )
    assert result["task_completion"]["score"] == 0.5
    second["critical"] = True
    result = rubric.aggregate_verdicts(
        EvalSpec.model_validate(raw), case_for(raw), {"output": "订单已发货"}, value
    )
    assert result["task_completion"]["score"] == 0


@pytest.mark.asyncio
async def test_grade_case(db, monkeypatch):
    raw = structured_plan(tools=True)
    value = verdicts(raw)

    async def judge(*_args):
        return value

    monkeypatch.setattr(semantic, "json_call", judge)
    args = (
        db,
        {},
        phase3.TEST_USER_ID,
        case_for(raw),
        {"output": "订单已发货"},
        [],
        {"eval_spec": raw, "requirements": REQUIREMENTS},
    )
    graded = await semantic.grade_case(*args)
    assert graded["metric_scores"]["task_completion"]["score"] == 1
    assert "tool_correctness" not in graded["metric_scores"]
    assert graded["metric_unavailable"]["tool_correctness"] == "no_applicable_program_checks"
    value["criterion_results"]["task_completion"][0]["evidence"][0]["quote"] = "编造"
    with pytest.raises(SnapshotExecutionUnavailable, match="evaluation_judge_invalid"):
        await semantic.grade_case(*args)


def test_failed_tool_and_retry():
    case = {
        "expected": {"required_tools": ["query"], "state": [{"path": "status", "value": "done"}]}
    }
    evidence = {
        "output": "done",
        "tool_calls": [{"name": "query"}],
        "tool_trace": [{"name": "query", "error": "timeout"}],
        "final_state": {"status": "pending"},
    }
    assert not all(c["passed"] for c in evaluation.score_case(case, evidence, strict_tools=True))
    evidence["tool_trace"].append({"name": "query", "output": "done", "error": None})
    evidence["final_state"]["status"] = "done"
    assert all(c["passed"] for c in evaluation.score_case(case, evidence, strict_tools=True))


def test_denominators_and_legacy():
    results = [
        {"metric_scores": {"task_completion": {"score": 1, "passed": True}}},
        {"metric_scores": {"task_completion": {"score": 0.5, "passed": False}}},
        {"metric_unavailable": {"task_completion": "不适用"}},
        {"status": "errored"},
    ]
    assert semantic.metric_summary(results)["task_completion"] == {
        "score": 0.75,
        "evaluated_cases": 2,
        "passed_cases": 1,
        "not_applicable_cases": 1,
        "unscored_cases": 1,
    }
    old = {**phase3.plan(), "capability_profile": {}}
    assert semantic.spec_dump(EvalSpec.model_validate(old)) == old


# Reuse isolated router fixtures, not the user's trial database.
db = phase3.db
client = phase3.client
setup_project = phase3.setup_project


@pytest.mark.asyncio
async def test_rule_review_rejection_preserves_previous_plan_and_retry(
    db, setup_project, monkeypatch
):
    from app.exceptions import AppError
    from app.services import agent_project_service as projects

    agent = setup_project
    project = await projects.require_project(db, agent.id, phase3.TEST_USER_ID)
    version = (await projects.list_versions(db, agent.id, phase3.TEST_USER_ID))[0]
    agent_id, version_id = agent.id, version.id
    previous = {**phase3.plan(), "version_id": str(version_id)}
    project.eval_spec_json = deepcopy(previous)
    await db.commit()
    approved = False

    async def model(*args):
        payload = args[-1]
        if "rubric_review_rules" in payload:
            return {
                "rule_reviews": [
                    {
                        "reference": key,
                        "supported": approved,
                        "reason": "额外业务条件没有需求依据"
                        if not approved
                        else "已确认需求支持条件",
                    }
                    for key in payload["rubric_review_rules"]
                ]
            }
        return {
            **structured_plan(),
            "rubric_version": 3,
            "pass_threshold_reason": "完整满足核心判据，部分满足不通过。",
        }

    monkeypatch.setattr(semantic, "json_call", model)
    with pytest.raises(AppError, match="evaluation_rubric_unsupported"):
        await semantic.generate(db, agent_id, phase3.TEST_USER_ID, version_id)
    await db.refresh(project)
    assert project.eval_spec_json == previous
    assert project.report_json is not None
    assert project.report_json["generation_failure"]["code"] == "evaluation_rubric_unsupported"
    approved = True
    result = await semantic.generate(db, agent_id, phase3.TEST_USER_ID, version_id)
    assert result["rubric_version"] == 3
    assert result["rule_validation"]["source"] == "model_C_requirement_review"


def test_format_character_checks_are_programmatic():
    case = {"expected": {"max_characters": 3}}
    assert semantic.format_check(case, "中文abc") is False
    assert semantic.format_check(case, "中文a") is True
    checks = evaluation.score_case(case, {"output": "中文abc"})
    assert next(c for c in checks if c["kind"] == "character_limit")["passed"] is False


def test_expected_tool_failure_can_pass_with_honest_fallback():
    case = {"expected": {"attempted_tools": ["query"]}}
    evidence = {
        "output": "查询暂不可用，请稍后再试。",
        "tool_calls": [{"name": "query"}],
        "tool_trace": [{"name": "query", "error": "timeout"}],
    }
    assert all(c["passed"] for c in evaluation.score_case(case, evidence, strict_tools=True))
    evidence["tool_calls"] = []
    assert not all(c["passed"] for c in evaluation.score_case(case, evidence, strict_tools=True))
