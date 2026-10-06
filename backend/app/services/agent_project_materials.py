"""Chinese AI product-manager artifacts from one immutable evidence projection."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.payloads import canonical_json_hash


def rate(run: dict | None) -> str:
    if not run or run.get("pass_rate") is None:
        return "未完成评分"
    return f"{run['passed']}/{run['total']}（全部用例通过率 {run['pass_rate']:.1%}）"


def comparison_lines(data: dict[str, Any]) -> list[str]:
    lines = []
    for item in data["results"].get("comparisons", []):
        label = f"V{item['source_version']}→V{item['target_version']}"
        if not item["comparable"]:
            lines.append(label + "：实验口径不同，不可直接比较。")
            continue
        changes = item["changes"]
        rates = changes["pass_rate"]
        outcome = {"improved": "提升", "unchanged": "持平", "regressed": "退步"}[changes["outcome"]]
        lines.append(
            f"{label}：{rates['before']:.1%}→{rates['after']:.1%}，{outcome}；"
            f"来源运行 {item['source_run_id']}，回归运行 {item['target_run_id']}。"
        )
        for name, metric in changes["metrics"].items():
            if metric["delta"] is None:
                lines.append(f"  {name}：未完整评分，不可比较。")
            else:
                lines.append(
                    f"  {METRIC_NAMES.get(name, name)}：平均得分 "
                    f"{metric['before'] * 100:.1f}/100→{metric['after'] * 100:.1f}/100，"
                    f"变化 {metric['delta'] * 100:+.1f} 分。"
                )
        if changes["regressed_cases"]:
            lines.append("新增失败：" + "、".join(changes["regressed_cases"]))
    return lines


METRIC_NAMES = {
    "task_completion": "任务完成情况",
    "tool_correctness": "工具操作正确性",
    "groundedness": "事实依据",
    "format_compliance": "表达与格式规范",
    "business_quality": "业务质量",
    "compliance_escalation": "业务规则遵守与转人工处理",
}


def scoring_lines(data: dict[str, Any]) -> list[str]:
    def count(value: Any) -> str:
        return "历史缺失" if value is None else str(value)

    lines = ["指标显示已评分用例的平均得分，不是任务通过率；未评分项不计入平均值。"]
    for run in data.get("experiment_references", []):
        summary = run["summary"]
        spec = run.get("eval_spec") or {}
        names = {m["name"]: m.get("display_name") for m in spec.get("metrics", [])}
        lines.append(f"{run['reference']} / V{run['version']}：{rate(summary)}。")
        lines.append(
            f"任务失败 {count(summary.get('failed'))}，"
            f"执行错误 {count(summary.get('execution_errors'))}，"
            f"裁判错误 {count(summary.get('judge_errors'))}；历史缺失的计数不补造。"
        )
        metrics = summary.get("metrics", {})
        for name in dict.fromkeys([*names, *metrics]):
            label = METRIC_NAMES.get(name) or names.get(name) or name
            value = metrics.get(name)
            if value is None:
                coverage = 0 if spec.get("rubric_version") == 2 else "历史缺失"
                lines.append(f"{label}：不可用，评分覆盖 {coverage}/{summary.get('total')}。")
                continue
            coverage = value.get("evaluated_cases", "历史缺失")
            lines.append(
                f"{label}：平均得分 {value['score'] * 100:.1f}/100，"
                f"评分覆盖 {coverage}/{summary.get('total')}；来源 {run['reference']}。"
            )
        if spec.get("rubric_version") != 2:
            lines.append("历史文字评分规则未校准为结构化档位，不补造逐条件证据。")
    lines.append("本轮未测量 Hit@K、Recall@K、MRR；模拟返回不代表检索排序效果。")
    return lines


def case_scoring_lines(case: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    labels = {m["name"]: m.get("display_name") for m in spec.get("metrics", [])}
    status = {"passed": "任务通过", "failed": "任务失败", "errored": "评测错误"}
    lines = [f"{case['reference']}：{status.get(case['status'], case['status'])}。"]
    if case.get("error"):
        lines.append(f"错误：{case['error']}。")
    for name, result in case.get("metrics", {}).items():
        label = METRIC_NAMES.get(name) or labels.get(name) or name
        lines.append(
            f"{label}：本例得分 {result['score'] * 100:.1f}/100；"
            + ("达标。" if result.get("passed") else "未达标。")
        )
        if result.get("reason") and result.get("method") != "deterministic":
            lines.append(f"判定依据：{result['reason']}")
        for criterion in result.get("criteria_results", []):
            lines.append(
                f"条件 {criterion['criterion_id']}，档位 {criterion['level']}："
                f"{criterion['reason']}"
            )
            for ref in criterion.get("evidence", []):
                lines.append(f"证据 {ref['reference']}：{ref['quote']}")
    for rule in case.get("assertions", []):
        if not rule.get("passed"):
            lines.append(
                f"未通过的程序检查：{rule['kind']}；目标：{rule.get('target') or '本例输出'}。"
            )
    if not case.get("metrics"):
        lines.append("本例没有可用的指标评分，不补造得分。")
    return lines


def render_chinese_report(data: dict[str, Any]) -> dict[str, Any]:
    results = data["results"]
    baseline, candidate = results.get("baseline"), results.get("candidate")
    comparison = (
        f"V{results.get('baseline_version') or '未知'}：{rate(baseline)}；"
        f"V{results.get('candidate_version') or '未知'}：{rate(candidate)}。"
    )
    if (
        baseline
        and candidate
        and baseline.get("pass_rate") is not None
        and candidate.get("pass_rate") is not None
    ):
        delta = candidate["pass_rate"] - baseline["pass_rate"]
        outcome = "提升" if delta > 0 else "退步" if delta < 0 else "持平"
        comparison += f"变化：{delta * 100:+.1f} 个百分点（{outcome}）。"
    refs = data.get("experiment_references", [])
    failures = [(r, c) for r in refs for c in r["cases"] if c["status"] != "passed"]
    sections = [
        {
            "title": "项目概述",
            "body": (
                f"{data['project']['name']}\n目标：{data['project']['goal']}\n这是模拟项目实践，"
                f"结果仅代表固定实验范围。"
            ),
        },
        {
            "title": "任务与成功条件",
            "body": "\n".join(f"{k}：{v}" for k, v in data.get("requirements", {}).items())
            or "历史需求证据缺失。",
        },
        {
            "title": "能力与设计决策",
            "body": "\n".join(
                f"{d['stage']}：{d['choice']}；理由：{d['reason']}"
                for d in data.get("decisions", [])
            )
            or "历史决策记录缺失。",
        },
        {
            "title": "实验设计",
            "body": (
                f"固定用例数：{data['evaluation_design'].get('case_count')}。"
                f"评分规则和成功条件以冻结实验为准；"
                f"只在必要业务依赖下约束调用路径。"
            ),
        },
        {
            "title": "评分口径与覆盖",
            "body": "\n".join(scoring_lines(data)),
        },
        {
            "title": "失败与薄弱指标",
            "body": "\n".join(
                line
                for run, case in failures
                for line in case_scoring_lines(case, run.get("eval_spec") or {})
            )
            or "没有记录到失败；需结合逐项指标覆盖与测试边界判断，不代表通用能力合格。",
        },
        {
            "title": "逐轮迭代与回归",
            "body": (
                data.get("authored_analysis")
                or data.get("system_analysis")
                or "尚未保存系统实验分析。"
            )
            + "\n"
            + comparison
            + "\n"
            + "\n".join(comparison_lines(data))
            + "\n"
            + "\n".join(
                (f"{r['reference']} / V{r['version']}：{rate(r['summary'])}；状态：{r['status']}")
                for r in refs
            ),
        },
        {
            "title": "结果与限制",
            "body": (
                f"历史最高成绩：V{results.get('best_version')}，"
                f"{rate(results.get('best'))}。"
                f"\n项目完成与成绩分开判断。"
                f"工具运行在模拟环境中，"
                f"真实客户效果、生产部署和业务收益均未验证。"
                f"\n"
            )
            + "\n".join(data.get("limitations", []))
            + "\n"
            + "\n".join(
                f"{r['reference']}：模型证据"
                + ("已记录" if any(c["evidence_available"] for c in r["cases"]) else "历史缺失")
                for r in refs
            ),
        },
    ]
    return {
        "evidence": data,
        "evidence_hash": canonical_json_hash(data),
        "sections": sections,
        "markdown": f"# {data['project']['name']}\n\n"
        + "\n\n".join(f"## {s['title']}\n\n{s['body']}" for s in sections),
    }


def resume_material(data: dict[str, Any]) -> dict[str, Any]:
    results = data["results"]
    bullets = [f"围绕“{data['project']['name']}”整理智能体模拟项目实践材料。"]
    count = data["evaluation_design"].get("case_count")
    if count:
        bullets.append(
            f"建立 {count} 条固定用例，结合程序规则检查与大模型内容评价，分析任务失败及执行错误。"
        )
    if results.get("baseline") and results.get("candidate"):
        bullets.append(
            f"完成受控迭代：V{results.get('baseline_version')} {rate(results['baseline'])}；"
            f"V{results.get('candidate_version')} {rate(results['candidate'])}，"
            f"如实记录提升、持平或退步。"
        )
    bullets.extend(comparison_lines(data))
    if data.get("decisions"):
        bullets.append("保存需求、能力方案及逐轮优化选择的决策理由，并区分任务失败和执行错误。")
    bullets.append("结果来源于模拟实验；未验证生产效果或业务收益。")
    return {
        "style": "ai_product",
        "bullets": bullets,
        "evidence_hash": canonical_json_hash(data),
        "references": [r["reference"] for r in data.get("experiment_references", [])],
    }


def interview_material(data: dict[str, Any]) -> dict[str, Any]:
    results = data["results"]
    decisions = data.get("decisions", [])
    refs = data.get("experiment_references", [])
    cases = [c for r in refs for c in r["cases"] if c["status"] != "passed"]
    questions = [
        {
            "question": "为什么这样定义需求和成功条件？",
            "references": ["requirements", "decisions/requirements"],
            "answer_points": [
                str(data.get("requirements", {})),
                *[d["reason"] for d in decisions if d["stage"] == "requirements"],
            ],
        },
        {
            "question": "哪些能力需要工具，哪些可以由指令或技能完成？",
            "references": ["architecture", "decisions/capabilities"],
            "answer_points": [
                *[d["reason"] for d in decisions if d["stage"] == "capabilities"],
                "说明查询外部数据或改变状态的必要性，以及不使用工具的条件。",
            ],
        },
        {
            "question": "如何判断结果正确，而不是只复现固定路径？",
            "references": ["eval_spec", *[r["reference"] for r in refs]],
            "answer_points": [
                "解释程序规则与内容裁判的分工、通过率分母和未评分项。",
                *scoring_lines(data),
            ],
        },
        {
            "question": "举一个真实失败或薄弱指标案例。",
            "references": [c["reference"] for c in cases[:3]],
            "answer_points": [str(c) for c in cases[:3]]
            or ["没有记录到失败，不能编造案例；说明覆盖边界和仍未验证的能力。"],
        },
        {
            "question": "为什么选择各轮改动，回归结果是否支持改进？",
            "references": ["decisions/optimization", *[r["reference"] for r in refs]],
            "answer_points": [
                *[d["reason"] for d in decisions if d["stage"] == "optimization"],
                *comparison_lines(data),
                (
                    f"V{results.get('baseline_version')} {rate(results.get('baseline'))}；"
                    f"V{results.get('candidate_version')} {rate(results.get('candidate'))}。"
                    f"说明退步指标与新增失败。"
                ),
            ],
        },
    ]
    return {"evidence_hash": canonical_json_hash(data), "questions": questions}


async def interview(db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    from app.services.agent_project_portfolio import evidence

    return interview_material(await evidence(db, agent_id, user_id))
