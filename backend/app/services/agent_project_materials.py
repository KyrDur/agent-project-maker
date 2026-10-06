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
                    f"  {name}：{metric['before']:.3f}→{metric['after']:.3f}，"
                    f"变化 {metric['delta']:+.3f}。"
                )
        if changes["regressed_cases"]:
            lines.append("新增失败：" + "、".join(changes["regressed_cases"]))
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
            "title": "失败与薄弱指标",
            "body": "\n".join(
                (
                    f"{c['reference']}：{c['status']}；"
                    f"错误：{c.get('error') or '无执行错误'}；"
                    f"指标：{c['metrics']}；"
                    f"规则检查：{c['assertions']}"
                )
                for _, c in failures
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
            "answer_points": ["解释程序规则与内容裁判的分工、通过率分母和未评分项。"],
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
