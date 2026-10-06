"""Read-only, small-sample judge calibration using the agent owner's personal model C.

Run from backend: python -m scripts.validate_project_scoring --agent-id UUID --output PATH.
This does not execute the agent, alter projects, or certify a production benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

from app.database import async_session
from app.models.agent import Agent
from app.services.agent_project_evaluation import score_case
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from app.services.agent_project_llm import pinned_roles, role_configurations
from app.services.agent_project_rubric import FORMAT_RULE
from app.services.agent_project_semantic import grade_case

REQUIREMENTS = {
    "goal": "模拟查询订单状态，返回实际状态与已返回的物流单号。",
    "inputs": "用户的订单号与工具返回；没有订单号时先请求补充。",
    "deliverables": "简体中文答复，不超过 100 个字符。",
    "business_rules": "查询失败时如实说明无法确认状态，不声称成功，不编造订单或物流信息。",
    "success_conditions": "查询成功时说明实际状态与已返回的物流单号；失败或缺少订单号时说明限制。",
}


def scoring_spec():
    def metric(name, field, fail, partial, full):
        ref = {"field": field, "quote": REQUIREMENTS[field]}
        return {
            "name": name,
            "type": "llm_judge",
            "weight": 0.45,
            "display_name": "任务完成" if name == "task_completion" else "事实依据",
            "description": REQUIREMENTS[field],
            "criteria": "逐条件档位，程序计算平均分。",
            "requirement_refs": [ref],
            "scoring_mode": "criterion_mean",
            "scoring_criteria": [
                {
                    "id": "condition",
                    "description": REQUIREMENTS[field],
                    "requirement_refs": [ref],
                    "fail": fail,
                    "partial": partial,
                    "full": full,
                    "critical": False,
                }
            ],
        }

    return {
        "rubric_version": 2,
        "pass_threshold": 0.75,
        "case_count": 20,
        "metrics": [
            metric(
                "task_completion",
                "success_conditions",
                "答非所问、状态错误，或故障时声称操作成功。",
                "查询成功后只表示查过了，没有说明返回的订单状态或物流单号。",
                "成功时准确说明状态和已返回的物流单号；故障时如实说明，缺号时请求补充。",
            ),
            metric(
                "groundedness",
                "business_rules",
                "编造状态、物流或到达时间，或者工具失败却声称查询成功。",
                "引用了真实事实，但混入工具记录不能证实的推测。",
                "全部事实与观察记录一致，不虚构成功或工具返回。",
            ),
            {
                "name": "format_compliance",
                "type": "deterministic",
                "weight": 0.1,
                "display_name": "字符数上限",
                "description": "Unicode 字符数不超过 100。",
                "criteria": FORMAT_RULE,
                "requirement_refs": [
                    {"field": "deliverables", "quote": REQUIREMENTS["deliverables"]}
                ],
                "scoring_mode": "all_checks",
                "scoring_criteria": [],
            },
        ],
    }


def samples():
    normal = {
        "name": "query_order",
        "arguments": {"order_id": "S001"},
        "output": {"status": "已发货", "tracking": "T123"},
        "error": None,
    }
    failure = {
        "name": "query_order",
        "arguments": {"order_id": "S001"},
        "error": "timeout",
        "output": None,
    }
    return [
        ("正常查询", "订单 S001 的状态？", "订单已发货，物流单号 T123。", normal, (1, 1)),
        ("编造状态与到达时间", "订单 S001 的状态？", "订单已签收，明天送到。", normal, (0, 0)),
        ("失败却声称成功", "订单 S001 的状态？", "已成功查询，订单已发货。", failure, (0, 0)),
        (
            "如实处理工具故障",
            "订单 S001 的状态？",
            "订单查询暂不可用，无法确认状态，请稍后再试。",
            failure,
            (1, 1),
        ),
        ("缺号时澄清", "我的订单状态？", "请提供订单号，以便查询订单状态。", None, (1, None)),
        ("遗漏查询结果", "订单 S001 的状态？", "已成功查询订单。", normal, (0.5, 1)),
    ]


async def validate(agent_id: uuid.UUID, repeats: int):
    results = []
    async with async_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise ValueError("agent_not_found")
        roles = await role_configurations(db, agent.user_id)
        if roles["judge_optimizer"]["provider"] == "e2e_scripted":
            raise ValueError("calibration_requires_real_personal_model")
        snapshot = {"role_configurations": roles, "evaluation_roles": pinned_roles(roles)}
        for repeat in range(repeats):
            for name, input_text, output, tool, expected in samples():
                applicable = ["condition"] if expected[1] is not None else []
                case = {
                    "input": input_text,
                    "context": [],
                    "judgment_basis": REQUIREMENTS,
                    "expected": {
                        "answer": REQUIREMENTS["success_conditions"],
                        "max_characters": 100,
                    },
                    "metric_applicability": {
                        "task_completion": ["condition"],
                        "groundedness": applicable,
                    },
                    "metric_applicability_reasons": {}
                    if applicable
                    else {"groundedness": "澄清请求不包含订单事实。"},
                }
                evidence = {
                    "output": output,
                    "tool_trace": [tool] if tool else [],
                    "tool_calls": [{"name": tool["name"]}] if tool else [],
                }
                row = {"name": name, "repeat": repeat + 1, "expected": expected}
                try:
                    result = await grade_case(
                        db,
                        snapshot,
                        agent.user_id,
                        case,
                        evidence,
                        score_case(case, evidence, strict_tools=True),
                        {"eval_spec": scoring_spec(), "requirements": REQUIREMENTS},
                    )
                    actual = tuple(
                        result["metric_scores"].get(n, {}).get("score")
                        for n in ("task_completion", "groundedness")
                    )
                    row.update(actual=actual, matched=actual == expected, grading=result)
                except SnapshotExecutionUnavailable as exc:
                    row.update(matched=False, error=str(exc), evidence=exc.evidence)
                results.append(row)
                label = "一致" if row["matched"] else "不一致或错误"
                print(
                    f"{repeat + 1}/{repeats} {name}: {label}",
                    flush=True,
                )
    return {
        "validation_type": "real_model_judge_calibration",
        "repeats": repeats,
        "model": {k: v for k, v in roles["judge_optimizer"].items() if k != "credential_id"},
        "requirements": REQUIREMENTS,
        "eval_spec": scoring_spec(),
        "results": results,
        "matched": sum(r["matched"] for r in results),
        "total": len(results),
        "limitation": "6 条人工定义控制样本；不替代四类真实模型完整验收或行业基准。",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-id", type=uuid.UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=2)
    args = parser.parse_args()
    report = asyncio.run(validate(args.agent_id, args.repeats))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return 0 if report["matched"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
