"""Chinese AI product-manager artifacts from one immutable evidence projection."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.payloads import canonical_json_hash


def reference_label(value: str) -> str:
    for prefix, label in [
        ("experiment", "实验"),
        ("case-card", "案例"),
        ("case", "用例"),
        ("tool", "工具事件"),
        ("model", "模型调用"),
    ]:
        value = re.sub(rf"{prefix}-(\d+)", lambda m, label=label: label + m[1], value)
    return value


def rate(run: dict | None) -> str:
    if not run or run.get("pass_rate") is None:
        return "未完成评分"
    return (
        f"{run['passed']}/{run['total']}（全部用例通过率 {decimal_score(run['pass_rate'] * 100)}%）"
    )


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
            f"{label}：{decimal_score(rates['before'] * 100)}%→"
            f"{decimal_score(rates['after'] * 100)}%，{outcome}；"
            f"来源运行 {item['source_run_id']}，回归运行 {item['target_run_id']}。"
        )
        for name, metric in changes["metrics"].items():
            if metric["delta"] is None:
                lines.append(f"  {name}：未完整评分，不可比较。")
            else:
                lines.append(
                    f"  {METRIC_NAMES.get(name, name)}：平均得分 "
                    f"{decimal_score(metric['before'] * 100)}/100→"
                    f"{decimal_score(metric['after'] * 100)}/100，"
                    f"变化 {decimal_score(metric['delta'] * 100)} 分。"
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
        stats = summary.get("statistics", {})
        facts = stats.get("fact_support")
        if facts:
            lines.append(
                f"事实支持：{facts['supported']}/{facts['total']} 条；"
                f"不支持 {facts['unsupported']}，无法判断 {facts['unknown']}；"
                f"抽取覆盖 {facts['covered_cases']}/{summary.get('total')} 个试验。"
                "采用事实条数汇总，覆盖受模型抽取限制。"
            )
        for key, label in [("operation_success", "业务操作成功"), ("recovery_success", "恢复成功")]:
            value = stats.get(key)
            if value:
                lines.append(f"{label}：{value['successful']}/{value['total']} 个适用试验。")
        critical = stats.get("critical_violations")
        if critical:
            lines.append(
                f"关键违规：{critical['violating']}/{critical['total']} 个适用且已评分试验。"
            )
        if stats.get("repetitions"):
            lines.append(
                f"每例重复 {stats['repetitions']} 次，共 {stats.get('case_count')} 个场景；"
                + (
                    "单次运行，稳定性未验证。"
                    if stats["repetitions"] == 1
                    else "各轮全部用例通过率："
                    + "、".join(
                        decimal_score(x * 100) + "%" for x in stats.get("trial_pass_rates") or []
                    )
                )
            )
        usage = stats.get("model_accounting")
        if usage:
            tokens = usage.get("total_count")
            lines.append(
                f"模型调用 {usage['model_invocations']} 次；"
                f"Token 记录覆盖 {usage['usage_covered_invocations']} 次，"
                f"已记录 Token 合计 {tokens if tokens is not None else '不可用'}；"
                "服务商价格未配置，费用不可用。"
            )
        metrics = summary.get("metrics", {})
        for name in dict.fromkeys([*names, *metrics]):
            label = METRIC_NAMES.get(name) or names.get(name) or name
            value = metrics.get(name)
            if value is None:
                coverage = 0 if spec.get("rubric_version", 1) >= 2 else "历史缺失"
                lines.append(f"{label}：不可用，评分覆盖 {coverage}/{summary.get('total')}。")
                continue
            coverage = value.get("evaluated_cases", "历史缺失")
            lines.append(
                f"{label}：平均得分 {decimal_score(value['score'] * 100)}/100，"
                f"评分覆盖 {coverage}/{summary.get('total')}；来源 {run['reference']}。"
            )
        if spec.get("rubric_version", 1) < 2:
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
            f"{label}：本例得分 {decimal_score(result['score'] * 100)}/100；"
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


def readable(value: Any) -> str:
    if value is None:
        return "未记录"
    if isinstance(value, dict):
        return "；".join(f"{k}：{readable(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "、".join(readable(v) for v in value) or "空结果"
    return str(value)


def case_lines(card: dict[str, Any]) -> list[str]:
    lines = [f"{card['reference']}：{card['title']}", card["personal_task"], card["system_task"]]
    history = card["history"]
    # Full trials remain in evidence.json; the narrative compares recorded endpoints.
    endpoints = [history[0], history[-1]] if len(history) > 1 else history
    for trial in endpoints:
        status = {"passed": "通过", "failed": "失败", "errored": "评测错误"}.get(
            trial["status"], trial["status"]
        )
        lines += [
            f"V{trial['version']} / 第{trial['trial']}次试验 / {trial['reference']}",
            f"用户原话：{trial['user_request']}",
            f"初始模拟数据：{readable(trial['initial_state'])}",
            f"成功条件：{trial['success_conditions'] or '历史缺失'}",
            f"判据来源：{trial['judgment_basis'] or '见冻结评分规则'}",
        ]
        for event in trial["timeline"]:
            lines.append(
                f"{event['event']}：调用 {event['tool']}；参数 {readable(event['arguments'])}；"
                f"返回 {readable(event['returned_facts'])}；错误 {event['error'] or '无'}。"
            )
        lines += [
            f"实际回答：{trial['actual_answer']}",
            f"原判定：{status}；终止原因：{trial['termination'] or '未记录'}。",
        ]
        for name, verdict in trial["judgments"].items():
            lines.append(
                f"{METRIC_NAMES.get(name, name)}："
                f"{decimal_score(verdict.get('score', 0) * 100)}/100；"
                f"依据：{verdict.get('reason') or '未记录'}。"
            )
        for check in trial["checks"]:
            lines.append(
                f"程序检查 {check['kind']}：{'通过' if check['passed'] else '失败'}；"
                f"目标 {check.get('target') or '本例'}。"
            )
    for change in card["changes"]:
        lines.append(
            f"已确认改动：{change['title']}；理由原文：{change.get('reason') or '未记录'}；"
            f"作者来源：{change['author']}；来源：{change['source']}。"
        )
    for review in card["reviews"]:
        lines.append(
            f"独立复核（不改写原判定）：{review.get('finding')}；来源：{review.get('source')}。"
        )
    lines += ["剩余问题与边界：" + text for text in card["limitations"]]
    return [reference_label(line) for line in lines]


def decimal_score(value: float) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def render_chinese_report(data: dict[str, Any]) -> dict[str, Any]:
    cards = data.get("case_cards", [])
    sections = [
        {
            "title": "结论",
            "body": f"{data['project']['name']}｜模拟实践\n目标：{data['project']['goal']}\n"
            + "\n".join(f"V{v['version']}：{rate(v.get('evaluation'))}。" for v in data["versions"])
            + "\n未验证真实客户效果、生产部署或业务收益。",
        },
        {
            "title": "方法与个人贡献",
            "body": (
                "测试由模型 B 设计，模型 A 执行并提出改动，模型 C 自动评分；"
                "用户确认需求、能力与逐轮方案。\n"
            )
            + "\n".join(
                f"{d['stage']}：{d['choice']}；理由原文：{d['reason']}；"
                f"来源：{d.get('author', '历史缺失')}。"
                for d in data.get("decisions", [])
            )
            + "\n"
            + "\n".join(f"{k}：{v}" for k, v in data.get("requirements", {}).items()),
        },
        *[
            {"title": f"案例 {i}：{c['title']}", "body": "\n".join(case_lines(c))}
            for i, c in enumerate(cards, 1)
        ],
        {
            "title": "版本数据与回归",
            "body": "\n".join(comparison_lines(data) + scoring_lines(data)),
        },
        {
            "title": "局限与待补证据",
            "body": "裁判未经过本领域专家审定；事实条目覆盖仍依赖模型抽取。\n"
            + "重复试验保留全部结果；最佳版本按新口径内全部有效运行汇总，单次试验未验证稳定性。\n"
            + ("不足两个实际场景，材料待补充。\n" if len(cards) < 2 else "")
            + "\n".join(data.get("limitations", [])),
        },
        {
            "title": "证据附录",
            "body": "完整试验、逐条件判定与脱敏工具状态见 evidence.json，版本与差异见 versions/。\n"
            + "\n".join(
                f"{r['reference']} / V{r['version']}：{rate(r['summary'])}。"
                for r in data.get("experiment_references", [])
            ),
        },
    ]
    return {
        "evidence": data,
        "evidence_hash": canonical_json_hash(data),
        "sections": [{**section, "body": reference_label(section["body"])} for section in sections],
        "markdown": f"# {data['project']['name']}\n\n"
        + "\n\n".join(
            f"## {section['title']}\n\n{reference_label(section['body'])}" for section in sections
        ),
    }


def resume_material(data: dict[str, Any]) -> dict[str, Any]:
    decisions = [
        d for d in data.get("decisions", []) if d.get("author") in {"user", "user_confirmed"}
    ]
    bullets, claims = [], []
    for stage, label in [("requirements", "确认需求"), ("capabilities", "确认能力方案")]:
        d = next((d for d in decisions if d["stage"] == stage), None)
        if d:
            text = f"{label}：{d['choice']}；取舍理由：{d['reason']}。"
            bullets.append(text)
            claims.append(
                {
                    "text": text,
                    "type": "fact",
                    "author": d["author"],
                    "source": f"/decisions/{data['decisions'].index(d)}",
                    "verification": "recorded_confirmation",
                }
            )
    count = data["evaluation_design"].get("case_count")
    if count:
        text = (
            f"项目保存系统生成的 {count} 条冻结模拟用例及自动评测，"
            "报告关联实际回答与工具记录，呈现失败和测试边界。"
        )
        bullets.append(text)
        claims.append(
            {
                "text": text,
                "type": "fact",
                "author": "system",
                "source": "/evaluation_design",
                "verification": "recorded_experiment",
            }
        )
    d = next((d for d in decisions if d["stage"] == "optimization"), None)
    if d:
        text = f"确认修改方案：{d['choice']}；原理由“{d['reason']}”。"
        target = str(d.get("version") or "")
        comparison = next(
            (
                c
                for c in data["results"].get("comparisons", [])
                if f"V{c['target_version']}" == target and c.get("comparable")
            ),
            None,
        )
        if comparison:
            changes = comparison["changes"]
            text += (
                f" 同口径通过率 {decimal_score(changes['pass_rate']['before'] * 100)}%→"
                f"{decimal_score(changes['pass_rate']['after'] * 100)}%，"
                f"修复 {len(changes['fixed_cases'])} 条、"
                f"新增失败 {len(changes['regressed_cases'])} 条。"
            )
        bullets.append(text)
        claims.append(
            {
                "text": text,
                "type": "fact",
                "author": d["author"],
                "source": f"/decisions/{data['decisions'].index(d)}",
                "verification": "recorded_confirmation",
            }
        )
    return {
        "style": "ai_product",
        "title": f"{data['project']['name']}｜模拟项目实践",
        "goal": data["project"]["goal"],
        "bullets": bullets[:4],
        "claims": claims[:4],
        "evidence_hash": canonical_json_hash(data),
        "references": [r["reference"] for r in data.get("experiment_references", [])],
        "limitations": ["未记录的本人职责、理解、生产部署与业务收益不写入经历。"],
        "status": data.get("material_readiness", "missing_actual_cases"),
    }


def interview_material(data: dict[str, Any]) -> dict[str, Any]:
    cards = data.get("case_cards", [])
    questions = [
        {
            "question": "测试数据从哪里来，成功如何定义？",
            "references": ["evaluation_design", "eval_spec"],
            "answer_points": [
                "模型 B 根据确认需求生成冻结模拟数据；不是客户日志或专家标注。",
                "核心任务与关键约束决定任务通过，表达偏好单独展示；历史规则保留原口径。",
            ],
        },
        {
            "question": "程序和模型 C 各负责什么，参数是否都验证过？",
            "references": ["eval_spec"],
            "answer_points": [
                "程序检查明确参数、必要顺序、状态、次数和格式；C 检查语义与逐条事实支持。",
                "仅工具名通过不证明复杂参数语义正确；未声明检查的覆盖不可补造。",
            ],
        },
        {
            "question": "为什么选择修改，退步和新增失败如何处理？",
            "references": ["decisions/optimization"],
            "answer_points": [
                *[d["reason"] for d in data.get("decisions", []) if d["stage"] == "optimization"],
                *comparison_lines(data),
            ],
        },
        {
            "question": "如果重做，哪些结论仍需验证？",
            "references": ["limitations"],
            "answer_points": [
                "补齐正常与故障场景，验证参考轨迹；用独立反例校准裁判。",
                "重复运行观察波动，用单独验证集检查泛化；不声称统计显著性或生产收益。",
            ],
        },
    ]
    for card in cards:
        questions.append(
            {
                "question": f"请用 2–3 分钟讲清楚：{card['title']}",
                "references": [card["reference"], *[t["reference"] for t in card["history"]]],
                "answer_points": case_lines(card),
                "star": card["star"],
                "cannot_claim": [
                    "本人独立设计测试集或主导 Codex 演示改动。",
                    "调用失败后业务操作已成功，或旧裁判满分证明幻觉消失。",
                ],
                "missing_data": card["limitations"],
            }
        )
    return {
        "evidence_hash": canonical_json_hash(data),
        "questions": questions,
        "introduction": f"这是 {data['project']['name']} 的模拟实践，"
        f"目标是 {data['project']['goal']}。"
        "我能依据已保存的个人确认说明取舍；系统承担生成、自动评测与分析。"
        "成绩及退步见冻结运行。",
        "case_cards": cards,
        "status": data.get("material_readiness", "missing_actual_cases"),
    }


async def interview(db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    from app.services.agent_project_portfolio import evidence

    return interview_material(await evidence(db, agent_id, user_id))
