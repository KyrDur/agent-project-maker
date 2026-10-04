"""Deterministic portfolio evidence. Never execute models or mutate Agent versions."""

from __future__ import annotations

import re
import secrets
import uuid
from collections import Counter
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.marketplace.redaction import is_sensitive_key, replace_secret_values
from app.models.agent_project import AgentProject, AgentProjectEvalRun, AgentProjectVersion
from app.schemas.agent_project import SCENARIOS
from app.services import agent_project_service as projects

UNAVAILABLE = "Unavailable"
NO_EVIDENCE = "暂无证据"
SCENARIO_LABELS = {
    "normal": "常规任务",
    "missing_information": "信息缺失",
    "ambiguous": "表达不清",
    "tool_failure": "工具异常",
    "edge_case": "边界情况",
    "hallucination": "事实编造风险",
}
CAUSE_LABELS = {
    "instruction_issue": "指令不够明确",
    "skill_issue": "技能流程问题",
    "tool_selection_issue": "工具选择问题",
    "tool_description_issue": "工具说明问题",
    "output_issue": "输出格式或内容问题",
    "external_unfixable": "外部环境问题",
}
TARGET_LABELS = {
    "instructions": "智能体指令",
    "output_instructions": "输出要求",
    "skill_content": "技能内容",
    "tool_description": "工具说明",
}
DECISION_LABELS = {
    "original": "原始版本",
    "candidate": "候选版本",
    "accepted": "已接受",
    "rejected": "未采纳",
}
LIMITATION_LABELS = {
    "mock_tools": "评测中的外部工具使用预设模拟结果，不能证明真实工具可用。",
    "no_production": "线上使用与部署效果尚未验证。",
    "live_difference": "项目最佳版本不一定是当前在线智能体的配置，也不会自动部署。",
    "private_sources": "公开材料不包含原始用例、私人来源资料、工具输出或隐藏推理。",
    "not_runnable": "下载包是项目案例与评测快照，不能直接作为智能体运行。",
    "no_best": "尚不能确定最佳版本；不会用最新版本代替。",
    "no_evaluation": "缺少完整的评测设计或结果，暂不能判断效果。",
    "missing_skill": "部分历史技能内容不可用，未用当前在线技能替代。",
    "optimization_incomplete": "优化流程尚未完成，当前结果仍需复核。",
    "execution_error": "部分用例发生执行或评判错误，不能据此判断模型质量。",
    "runtime_error": "部分记录存在运行环境错误，需在受支持的环境中复核。",
}
PRIVATE_KEYS = {
    "input",
    "context",
    "expected",
    "output",
    "actual_output",
    "tool_calls",
    "called_tools",
    "mock_tool_data",
    "observations",
    "reasoning",
    "thinking",
    "chain_of_thought",
    "private_data",
    "source_data",
    "raw_tool_output",
    "headers",
    "env",
    "env_vars",
    "base_url",
    "parameters",
    "config",
    "credential_bindings",
}
PRIVATE_TEXT = re.compile(
    r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|[A-Za-z]:[\\/][^\s\"<>]+"
    r"|(?<!\w)/(?:home|Users|users|tmp|var|etc|runtime|data|srv|opt|mnt)/[^\s\"<>]+"
    r"|\\\\[^\s]+|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def sanitize(value: Any) -> Any:
    """Outbound defense after allowlist projection; no credential IDs or source blobs."""
    if isinstance(value, dict):
        return {
            str(k): sanitize(v)
            for k, v in value.items()
            if str(k).lower() not in PRIVATE_KEYS
            and "credential" not in str(k).lower()
            and not is_sensitive_key(str(k))
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(
            r"(?is)<(?:think|thinking|analysis)>.*?</(?:think|thinking|analysis)>",
            "[omitted]",
            value,
        )
        value = PRIVATE_TEXT.sub("[redacted]", value)
        return projects.snapshot_value(value)
    return value


def source_strings(runs: list[AgentProjectEvalRun]) -> list[str]:
    """Known private source text must also disappear if copied into summaries."""
    found: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str) and len(value) >= 5:
            found.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for run in runs:
        for case in run.cases_snapshot_json or []:
            collect(case.get("context"))
            collect(case.get("mock_tool_data"))
        for result in run.results_json or []:
            for call in result.get("tool_calls", []):
                collect(call.get("args"))
                collect(call.get("arguments"))
                collect(call.get("result"))
    return found


def remove_sources(value: Any, sources: list[str]) -> Any:
    if isinstance(value, str):
        return replace_secret_values(value, sources, placeholder="[private source omitted]")
    if isinstance(value, dict):
        return {k: remove_sources(v, sources) for k, v in value.items()}
    if isinstance(value, list):
        return [remove_sources(v, sources) for v in value]
    return value


def architecture(snapshot: dict[str, Any], *, text: bool = False) -> dict[str, Any]:
    config = snapshot.get("agent", {})
    result = {
        "name": config.get("name"),
        "description": config.get("description"),
        "model": {k: config.get("model", {}).get(k) for k in ("provider", "model_name")},
        "tools": [
            {k: t.get(k) for k in ("name", "definition_key", "description", "enabled")}
            for t in config.get("tool_links", [])
        ],
        "skills": [
            {
                "name": s.get("slug"),
                "version": s.get("version"),
                "historical_content_available": bool(s.get("content")),
                **({"content": s.get("content")} if text else {}),
            }
            for s in config.get("skill_links", [])
        ],
        "mcp": [
            {"name": t.get("name"), "enabled": t.get("enabled")}
            for t in config.get("mcp_tool_links", [])
        ],
        "instructions_summary": (
            "Frozen instruction excerpt: " + config["system_prompt"][:240]
            if config.get("system_prompt")
            else UNAVAILABLE
        ),
        **({"instructions": config.get("system_prompt")} if text else {}),
    }
    return sanitize(result)


def run_summary(run: AgentProjectEvalRun) -> dict[str, Any]:
    metrics = run.metrics_json or {}
    # In-progress/aborted runs never contribute fabricated zero scores.
    complete = (
        run.completed_at is not None
        and run.status in {"completed", "failed"}
        and bool(run.cases_snapshot_json)
        and len(run.results_json or []) == len(run.cases_snapshot_json or [])
        and metrics.get("total") == len(run.cases_snapshot_json or [])
    )
    return {
        "status": run.status,
        "complete": complete,
        "total": metrics.get("total") if complete else None,
        "passed": metrics.get("passed") if complete else None,
        "failed": metrics.get("failed") if complete else None,
        "errored": metrics.get("errored") if complete else None,
        "pass_rate": run.pass_rate if complete else None,
        "scoring": metrics.get("scoring"),
        "metrics": sanitize(metrics.get("metric_scores", {})) if complete else {},
    }


def comparison_summary(data: dict[str, Any]) -> dict[str, Any]:
    return sanitize(
        {
            "decision": data.get("decision"),
            "reasons": data.get("reasons", []),
            "metrics": data.get("metrics", {}),
            "pass_rate": data.get("pass_rate"),
            **{
                key: len(data[key]) if isinstance(data.get(key), list) else None
                for key in (
                    "fixed_cases",
                    "regressed_cases",
                    "still_failing_cases",
                    "still_passing_cases",
                )
            },
        }
    )


async def evidence(db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    versions = list(
        (
            await db.scalars(
                select(AgentProjectVersion)
                .where(AgentProjectVersion.project_id == project.id)
                .order_by(AgentProjectVersion.version_number)
            )
        ).all()
    )
    runs = list(
        (
            await db.scalars(
                select(AgentProjectEvalRun)
                .where(AgentProjectEvalRun.project_id == project.id)
                .order_by(AgentProjectEvalRun.created_at)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    state = (project.report_json or {}).get("optimization") or {}
    by_run = {str(r.id): r for r in runs}
    by_version = {str(v.id): v for v in versions}
    from app.services.agent_project_report import report_for_run

    scored = [
        (run, report_for_run(run))
        for run in runs
        if run.status == "completed"
        and (run.comparison_json or {}).get("purpose") != "holdout"
        and not (run.comparison_json or {}).get("reliability")
    ]
    valid = [
        (run, report)
        for run, report in scored
        if report.score is not None and report.comparison_key
    ]
    scope = valid[-1][1].comparison_key if valid else None
    cohort = [(run, report) for run, report in valid if report.comparison_key == scope]
    winner = max(cohort, key=lambda pair: pair[1].score or 0) if cohort else None
    best = winner[0] if winner else None
    source_id = winner[1].source_run_id if winner else None
    baseline = by_run.get(source_id) if source_id else (cohort[0][0] if cohort else None)
    selected = by_version.get(str(best.version_id)) if best else None
    config_version = selected or (versions[0] if versions else None)
    config = architecture(config_version.snapshot_json) if config_version else {}
    frozen = (baseline.comparison_json or {}) if baseline else {}
    spec = frozen.get("eval_spec")
    cases = baseline.cases_snapshot_json or [] if baseline else []
    rounds = {entry["version_id"]: entry for entry in state.get("rounds", [])}
    journey = []
    for version in versions:
        entry = rounds.get(str(version.id), {})
        run = by_run.get(entry.get("run_id"))
        if not run:
            run = next((r for r, _ in reversed(cohort) if r.version_id == version.id), None)
        if best and version.id == best.version_id:
            run = best
        if baseline and version.id == baseline.version_id:
            run = baseline
        meta = version.snapshot_json.get("optimization", {})
        journey.append(
            {
                "version": version.version_number,
                "decision": entry.get("decision", version.status),
                "best": bool(selected and version.id == selected.id),
                "evaluation": run_summary(run) if run else None,
                "comparison": comparison_summary(entry.get("comparison", {})),
                "fixes": [
                    {"target": p.get("target"), "operation": p.get("operation")}
                    for p in meta.get("patches", [])
                ],
                "deferred_changes": len(meta.get("deferred_changes", [])),
            }
        )
    bad = baseline.bad_cases_json or [] if baseline else []
    # Only structural observations go into portfolio artifacts. Raw source text stays private.
    examples = [
        {
            "case_number": i + 1,
            "status": r.get("status"),
            "metric_scores": {
                k: {"score": v.get("score"), "passed": v.get("passed")}
                for k, v in r.get("metric_scores", {}).items()
            },
        }
        for i, r in enumerate(baseline.results_json or [] if baseline else [])
        if r.get("status") in {"failed", "errored"}
    ][:3]
    groups = (frozen.get("analysis") or {}).get("groups", [])
    limitations = [
        LIMITATION_LABELS[key]
        for key in (
            "mock_tools",
            "no_production",
            "live_difference",
            "private_sources",
            "not_runnable",
        )
    ]
    if not selected:
        limitations.append(LIMITATION_LABELS["no_best"])
    if not baseline or not spec:
        limitations.append(LIMITATION_LABELS["no_evaluation"])
    if any(not s.get("historical_content_available") for s in config.get("skills", [])):
        limitations.append(LIMITATION_LABELS["missing_skill"])
    if state.get("state") in {"pending", "running", "failed"}:
        limitations.append(LIMITATION_LABELS["optimization_incomplete"])
    if any((run.metrics_json or {}).get("errored", 0) for run in runs):
        limitations.append(LIMITATION_LABELS["execution_error"])
    if any(
        r.get("error") == "runtime_platform_unavailable"
        or "runtime_import" in str(r.get("error", ""))
        or "fcntl" in str(r.get("error", ""))
        for run in runs
        for r in run.results_json or []
    ):
        limitations.append(LIMITATION_LABELS["runtime_error"])
    baseline_summary = run_summary(baseline) if baseline else None
    best_summary = run_summary(best) if best else None
    deltas = {}
    if baseline_summary and best_summary and baseline_summary["complete"]:
        for name, metric in baseline_summary["metrics"].items():
            other = best_summary["metrics"].get(name)
            if (
                other
                and metric.get("evaluated_cases") == baseline_summary["total"]
                and other.get("evaluated_cases") == best_summary["total"]
            ):
                deltas[name] = other["score"] - metric["score"]
    from app.services.agent_project_reliability import summarize_project_runs

    reliability = []
    for version in versions:
        value = summarize_project_runs(runs, version.id)
        if value["trials"] or value["calibration"]["reviewed"]:
            reliability.append(
                {
                    "version": version.version_number,
                    "trials": [
                        {
                            "kind": g["kind"],
                            "result": {
                                k: v
                                for k, v in g["versions"][str(version.id)].items()
                                if k != "run_ids"
                            },
                        }
                        for g in value["trials"]
                    ],
                    "calibration": {
                        k: v for k, v in value["calibration"].items() if k != "reviews"
                    },
                    "limitations": value["limitations"],
                }
            )
    payload = sanitize(
        {
            "project": {
                "name": project.title,
                "goal": config.get("description") or UNAVAILABLE,
                "intended_use": config.get("description") or UNAVAILABLE,
            },
            "reliability": reliability,
            "participation": {
                "brief_confirmed": bool((project.requirements_json or {}).get("learning_brief")),
                "brief_edited": (project.requirements_json or {})
                .get("learning_brief", {})
                .get("contribution")
                == "user_edited",
                "authored_reviews": sum(
                    len((r.comparison_json or {}).get("case_reviews", {})) for r in runs
                ),
                "accepted_proposals": sum(
                    p.get("status") == "accepted"
                    for r in runs
                    for p in (r.comparison_json or {}).get("proposals", [])
                ),
                "platform_scope": (
                    "平台生成配置、测试与评分；AI 提供草稿，用户负责确认、修改和取舍。"
                ),
            },
            "architecture": config,
            "build_process": {
                "project_v1": bool(versions),
                "builder_linked": bool(project.builder_session_id),
                "requirement": (project.requirements_json or {}).get("goal", UNAVAILABLE),
                "eval_plan": bool(spec),
                "eval_set": bool(cases),
                "evaluation": bool(baseline),
                "optimization": bool(rounds),
            },
            "eval_spec": spec,
            "evaluation_design": {
                "case_count": len(cases) if cases else None,
                "scenarios": dict(
                    Counter(tag for c in cases for tag in c.get("tags", []) if tag in SCENARIOS)
                ),
                "execution_mode": frozen.get("execution_mode", UNAVAILABLE),
            },
            "versions": journey,
            "bad_cases": {
                "failed_count": (baseline_summary or {}).get("failed"),
                "errored_count": (baseline_summary or {}).get("errored"),
                "analyzed_count": len(bad),
                "categories": dict(Counter(b.get("category", "unavailable") for b in bad)),
                "groups": [
                    {
                        "category": g.get("category"),
                        "target": g.get("target"),
                        "case_count": len(g.get("case_ids", [])),
                        "root_cause": g.get("root_cause"),
                    }
                    for g in groups
                ],
                "examples": examples,
                "basis": "失败原因基于可观察的输出和评分推断，不代表模型内部推理。",
            },
            "results": {
                "best_version": selected.version_number if selected else None,
                "baseline": baseline_summary,
                "best": best_summary,
                "metric_deltas": deltas,
            },
            "limitations": limitations,
        }
    )
    return remove_sources(payload, source_strings(runs))


def display(value: Any) -> str:
    if value is None or value == UNAVAILABLE:
        return NO_EVIDENCE
    if isinstance(value, bool):
        return "已完成" if value else "尚未完成"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def rate(value: Any) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else NO_EVIDENCE


def _labels(items: dict[str, Any], labels: dict[str, str]) -> str:
    return (
        "、".join(f"{labels.get(key, '其他')} {value} 条" for key, value in items.items())
        or NO_EVIDENCE
    )


def _evaluation_conclusion(data: dict[str, Any]) -> str:
    results = data["results"]
    baseline, best = results["baseline"] or {}, results["best"] or {}
    if best.get("total") is None or best.get("passed") is None:
        return "尚无完整评测结果，不能判断智能体效果。"
    current = f"{best['passed']}/{best['total']} 条（{rate(best.get('pass_rate'))}）"
    if baseline.get("pass_rate") is None:
        return f"项目最佳版本通过 {current}；缺少可比较的初始结果。"
    original = f"{baseline['passed']}/{baseline['total']} 条（{rate(baseline['pass_rate'])}）"
    before, after = baseline["pass_rate"], best["pass_rate"]
    if after > before:
        comparison = "在这组固定用例上有所提高；真实使用效果仍需验证。"
    elif after == before:
        comparison = "通过率与初始版本相同，尚未证明效果提升。"
    else:
        comparison = "通过率低于初始版本，需要继续复核。"
    return f"初始版本通过 {original}，项目最佳版本通过 {current}。{comparison}"


def render_readme(data: dict[str, Any]) -> str:
    """Short reader-facing entry point; detailed evidence stays in the technical folder."""
    project = data["project"]
    goal = str(project.get("goal") or "").strip()
    if not goal or goal == UNAVAILABLE:
        goal = "尚未填写用途说明。"
    elif len(goal) > 220:
        goal = goal[:219].rstrip() + "…"
    audience_match = re.search(r"适用于([^。；，]{2,80})", goal)
    audience = (
        f"适合{audience_match.group(1)}。"
        if audience_match
        else "适合有上述需求、希望用自己的输入验证效果的人。"
    )
    best_version = data["results"].get("best_version")
    best_label = f"V{best_version}" if best_version is not None else "尚未确定"
    return (
        f"# {project['name']}\n\n"
        "这是一份智能体项目案例与评测材料，不是可直接运行的安装包。\n\n"
        f"## 它能做什么\n\n{goal}\n\n"
        "## 适合谁、怎么试用\n\n"
        f"{audience}"
        "请回到 Agent Project Maker，打开这个项目并点击「试用在线智能体」。"
        "在线智能体的配置可能与项目最佳版本不同。\n\n"
        f"## 目前评测结果\n\n{_evaluation_conclusion(data)}"
        f"项目评测选出的最佳版本：{best_label}。\n\n"
        "## 使用前须知\n\n"
        "- 评测使用固定用例；外部工具结果可能由模拟数据提供，不能代表真实服务。\n"
        "- 尚无线上使用或部署效果的验证数据，项目最佳版本不会自动部署。\n\n"
        "## 想进一步核查\n\n"
        "《项目报告.md》说明评测、失败原因和版本结论；"
        "「技术资料」目录保留评测数据、历史配置、完整指令和版本差异。"
        "技术资料中的 JSON 字段名供程序核查，普通阅读从本文件开始即可。\n"
    )


def render_report(data: dict[str, Any]) -> dict[str, Any]:
    results, config = data["results"], data["architecture"]
    design, bad = data["evaluation_design"], data["bad_cases"]

    def names(items: list[dict[str, Any]]) -> str:
        return "、".join(str(item.get("name") or "未命名") for item in items) or "未配置"

    architecture_text = (
        f"使用模型：{display(config.get('model', {}).get('provider'))} / "
        f"{display(config.get('model', {}).get('model_name'))}\n"
        f"工具：{names(config.get('tools', []))}；技能：{names(config.get('skills', []))}；"
        f"外部工具连接：{names(config.get('mcp', []))}。\n"
        "完整指令与历史配置仅放在下载包的「技术资料」中。"
    )
    process_labels = {
        "project_v1": "保存初始版本",
        "builder_linked": "关联创建对话",
        "requirement": "记录需求",
        "eval_plan": "制定评测计划",
        "eval_set": "建立固定测试集",
        "evaluation": "执行评测",
        "optimization": "记录优化版本",
    }
    process_text = (
        "、".join(
            label
            for key, label in process_labels.items()
            if data["build_process"].get(key) and data["build_process"][key] != UNAVAILABLE
        )
        or NO_EVIDENCE
    )
    evaluation_text = (
        (
            f"使用 {design['case_count']} 条固定测试用例，覆盖"
            f"{_labels(design['scenarios'], SCENARIO_LABELS)}。\n"
            "同一组用例用于比较版本；外部工具在评测中可能使用预设模拟结果。"
            "完整评分标准保存在「技术资料/评测标准.json」。\n"
        )
        if design["case_count"] is not None
        else "尚未建立可复核的固定测试集。\n"
    ) + (
        f"项目最佳版本在这组用例中通过 {results['best']['passed']}/{results['best']['total']} 条。"
        if results["best"] and results["best"].get("passed") is not None
        else "目前还没有完整评测结果。"
    )
    causes = (
        "\n".join(
            f"- {CAUSE_LABELS.get(g['category'], '其他问题')}（{g['case_count']} 条）："
            f"{display(g.get('root_cause'))}"
            for g in bad["groups"]
        )
        or "暂无可复核的失败原因分析。"
    )
    bad_text = (
        (
            f"初始评测未通过 {bad['failed_count']} 条；已分析 {bad['analyzed_count']} 条。"
            if bad["failed_count"] is not None
            else "尚无完整评测结果，暂不能分析失败用例。"
        )
        + (
            f"另有 {bad['errored_count']} 条执行或评判错误，不计作智能体质量问题。"
            if bad["errored_count"]
            else ""
        )
        + f"\n{bad['basis']}\n{causes}"
    )
    journey = []
    for version in data["versions"]:
        run, comparison = version["evaluation"] or {}, version["comparison"]
        status = DECISION_LABELS.get(version["decision"], "待评估")
        score = (
            f"通过 {run['passed']}/{run['total']} 条（{rate(run.get('pass_rate'))}）"
            if run.get("passed") is not None and run.get("total") is not None
            else "暂无完整评测结果"
        )
        fixes = "、".join(TARGET_LABELS.get(fix.get("target"), "配置") for fix in version["fixes"])
        details = f"；调整了{fixes}" if fixes else ""
        if comparison.get("fixed_cases") is not None:
            details += (
                f"；相对上一版修复 {comparison['fixed_cases']} 条，"
                f"退化 {display(comparison.get('regressed_cases'))} 条"
            )
        journey.append(
            f"- V{version['version']}（{status}{'、当前最佳' if version['best'] else ''}）："
            f"{score}{details}。"
        )
    best_version = results["best_version"]
    best_label = f"V{best_version}" if best_version is not None else NO_EVIDENCE
    sections = [
        {
            "title": "项目简介",
            "body": f"项目：{data['project']['name']}\n用途：{display(data['project']['goal'])}",
        },
        {"title": "智能体配置", "body": architecture_text},
        {"title": "建设过程", "body": process_text},
        {"title": "评测方式与结果", "body": evaluation_text},
        {"title": "失败原因", "body": bad_text},
        {"title": "版本迭代", "body": "\n".join(journey) or NO_EVIDENCE},
        {
            "title": "结论与限制",
            "body": f"项目评测选出的最佳版本：{best_label}。\n"
            + _evaluation_conclusion(data)
            + "\n"
            + "\n".join(f"- {item}" for item in data["limitations"]),
        },
    ]
    if data.get("participation"):
        contribution = data["participation"]
        sections.append(
            {
                "title": "用户参与与平台支持",
                "body": contribution["platform_scope"]
                + f"\n需求已确认：{contribution['brief_confirmed']}；"
                + f"需求有编辑：{contribution['brief_edited']}；"
                + f"人工复核：{contribution['authored_reviews']}；"
                + f"采纳建议：{contribution['accepted_proposals']}。",
            }
        )
    if data.get("reliability"):
        rows = ["重复运行只描述固定案例的波动；新验证案例仍是模拟数据，不证明线上效果。"]
        for entry in data["reliability"]:
            calibration = entry["calibration"]
            rows.append(
                f"V{entry['version']} 人工复核 {calibration['reviewed']} 条，"
                f"分歧 {calibration['disagreements']} 条。"
            )
            for group in entry["trials"]:
                kind = "保留验证集" if group["kind"] == "validation" else "重复测试"
                value = group["result"]
                rows.append(
                    f"{kind}：完整 {value['completed']}/{value['scheduled']} 次，"
                    f"均值 {rate(value['mean'])}，"
                    f"范围 {rate(value['min'])}–{rate(value['max'])}。"
                )
        sections.append({"title": "额外验证与评分复核", "body": "\n".join(rows)})
    return {
        "evidence": data,
        "evidence_hash": canonical_json_hash(data),
        "sections": sections,
        "markdown": "# "
        + str(data["project"]["name"])
        + "\n\n"
        + "\n\n".join(f"## {s['title']}\n\n{s['body']}" for s in sections),
    }


async def save_content(db: AsyncSession, project: AgentProject, key: str, value: Any) -> None:
    await projects.lock_project(db, project)
    await db.refresh(project, ["report_json"])
    project.report_json = {**(project.report_json or {}), key: value}
    await db.commit()


async def report(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, *, save: bool = False
) -> dict[str, Any]:
    result = render_report(await evidence(db, agent_id, user_id))
    if save:
        await save_content(
            db, await projects.require_project(db, agent_id, user_id), "portfolio_report", result
        )
    return result


def resume_bullets(data: dict[str, Any], style: str) -> list[str]:
    name = data["project"]["name"]
    starts = {
        "ai_product": (
            f"围绕「{name}」使用平台搭建智能体，并查看平台提供的需求、评测和交付边界记录。"
        ),
        "product": (
            f"将「{name}」在平台中的需求、评测和版本迭代整理为可追溯的项目案例，明确当前能力与限制。"
        ),
        "engineering": (
            f"为「{name}」使用平台保存配置快照和版本记录，保留可复核的评测证据与改动历史。"
        ),
    }
    bullets = [starts[style]]
    participation = data.get("participation", {})
    if participation.get("brief_confirmed"):
        action = "编辑并确认" if participation.get("brief_edited") else "阅读并确认"
        bullets.append(f"{action} AI 提供的需求草稿与成功标准，保留确认记录。")
    if participation.get("accepted_proposals"):
        bullets.append(
            f"确认采纳 {participation['accepted_proposals']} 项 AI 改进建议，保留选择与回测记录。"
        )
    design, results = data["evaluation_design"], data["results"]
    if design["case_count"]:
        scenario_names = [SCENARIO_LABELS.get(item, "其他场景") for item in design["scenarios"]]
        scenarios = "、".join(scenario_names[:3]) or "多类场景"
        if len(scenario_names) > 3:
            scenarios += f"等 {len(scenario_names)} 类场景"
        activity = {
            "ai_product": "使用平台执行",
            "product": "使用平台执行",
            "engineering": "使用平台执行",
        }[style]
        bullets.append(
            f"{activity}覆盖{scenarios}的 {design['case_count']} 条固定测试用例，"
            "在受控环境中比较不同版本的表现。"
        )
    else:
        bullets.append("记录智能体配置与项目目标，为后续评测和改进保留依据。")
    baseline, best = results["baseline"] or {}, results["best"] or {}
    before, after = baseline.get("pass_rate"), best.get("pass_rate")
    if before is not None and after is not None and best.get("total"):
        if after > before:
            comparison = (
                f"受控评测通过率从 {rate(before)} 提高到 {rate(after)}"
                f"（{best['passed']}/{best['total']} 条通过）"
            )
        elif after == before:
            comparison = (
                f"初始版本与项目最佳版本均通过 {best['passed']}/{best['total']} 条"
                f"（{rate(after)}），尚未证明效果提升"
            )
        else:
            comparison = (
                f"项目最佳版本通过 {best['passed']}/{best['total']} 条（{rate(after)}），"
                "低于初始结果，需继续复核"
            )
        bullets.append(f"{comparison}；真实线上效果尚未验证。")
    return bullets


async def resume(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, style: str
) -> dict[str, Any]:
    data = await evidence(db, agent_id, user_id)
    bullets = resume_bullets(data, style)
    result = {"style": style, "bullets": bullets, "evidence_hash": canonical_json_hash(data)}
    await save_content(
        db, await projects.require_project(db, agent_id, user_id), "portfolio_resume", result
    )
    return result


async def share(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, *, revoke: bool = False
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(project, ["report_json"])
    content = deepcopy(project.report_json or {})
    if revoke:
        content.pop("portfolio_share", None)
        result = {"path": None}
    else:
        existing = content.get("portfolio_share")
        if existing:
            await db.commit()
            return {"path": existing["path"]}
        token = secrets.token_urlsafe(32)
        path = f"/shared/projects/{project.id}/{token}"
        shared = await evidence(db, agent_id, user_id)
        # Public projection deliberately omits authored rubric prose and analysis prose.
        for metric in (shared.get("eval_spec") or {}).get("metrics", []):
            metric.pop("criteria", None)
        for group in shared["bad_cases"]["groups"]:
            group.pop("root_cause", None)
        shared["build_process"]["requirement"] = "Private requirement text omitted."
        shared["architecture"]["instructions_summary"] = "Private instruction text omitted."
        for tool in shared["architecture"].get("tools", []):
            tool.pop("description", None)
        content["portfolio_share"] = {
            "token": token,
            "path": path,
            "report": render_report(shared),
        }
        result = {"path": path}
    project.report_json = content
    await db.commit()
    return result


async def public_share(db: AsyncSession, project_id: uuid.UUID, token: str) -> dict[str, Any]:
    project = await db.get(AgentProject, project_id)
    stored = (project.report_json or {}).get("portfolio_share") if project else None
    if not stored or not secrets.compare_digest(stored["token"], token):
        raise AppError(
            code="project_share_not_found", message="Project share not found", status=404
        )
    return stored["report"]
