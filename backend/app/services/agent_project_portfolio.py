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
from app.services.agent_project_case_cards import decision_author

UNAVAILABLE = "Unavailable"
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
        and len(run.results_json or [])
        == len(run.cases_snapshot_json or []) * (run.comparison_json or {}).get("repetitions", 1)
        and metrics.get("total") == len(run.results_json or [])
    )
    return {
        "status": run.status,
        "complete": complete,
        "total": metrics.get("total") if complete else None,
        "passed": metrics.get("passed") if complete else None,
        "failed": metrics.get("failed") if complete else None,
        "errored": metrics.get("errored") if complete else None,
        "execution_errors": metrics.get("execution_errors") if complete else None,
        "judge_errors": metrics.get("judge_errors") if complete else None,
        "statistics": sanitize(
            {
                key: metrics.get(key)
                for key in (
                    "environment_errors",
                    "valid_scored_pass_rate",
                    "case_count",
                    "repetitions",
                    "stability",
                    "trial_pass_rates",
                    "trial_range",
                    "fact_support",
                    "operation_success",
                    "recovery_success",
                    "critical_violations",
                    "model_accounting",
                )
            }
        )
        if complete
        else {},
        "pass_rate": run.pass_rate if complete else None,
        "scoring": metrics.get("scoring"),
        "metrics": sanitize(metrics.get("metric_scores", {})) if complete else {},
        "purpose": (run.comparison_json or {}).get("purpose", "regression"),
        "validation_exposure": (run.comparison_json or {}).get("validation_exposure"),
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
                .order_by(AgentProjectEvalRun.created_at, AgentProjectEvalRun.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    state = (project.report_json or {}).get("optimization") or {}
    by_run = {str(r.id): r for r in runs}
    by_version = {str(v.id): v for v in versions}
    aliases = {str(r.id): f"experiment-{i}" for i, r in enumerate(runs, 1)}
    aliases.update({str(v.id): f"V{v.version_number}" for v in versions})
    for run in runs:
        for j, case in enumerate(run.cases_snapshot_json or [], 1):
            aliases.setdefault(case["id"], f"case-{j}（{case['name']}）")

    def alias(value: Any) -> Any:
        if isinstance(value, str):
            for identity, label in aliases.items():
                value = value.replace(identity, label)
            return value
        if isinstance(value, dict):
            return {k: alias(v) for k, v in value.items()}
        if isinstance(value, list):
            return [alias(v) for v in value]
        return value

    from app.services.agent_project_report import report_for_run, select_best_reports

    scored = [(run, report_for_run(run)) for run in runs if run.status == "completed"]
    valid = [
        (run, report)
        for run, report in scored
        if report.score is not None and report.comparison_key
    ]
    scope = valid[-1][1].comparison_key if valid else None
    cohort = [(run, report) for run, report in valid if report.comparison_key == scope]
    best_reports = select_best_reports(
        [
            report.model_copy(
                update={"version_number": by_version[str(run.version_id)].version_number}
            )
            for run, report in cohort
        ]
    )
    winning_report = best_reports.get(scope) if scope else None
    winner = next(
        (
            pair
            for pair in cohort
            if winning_report and pair[1].evaluation_run_id == winning_report.evaluation_run_id
        ),
        None,
    )
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
                "evaluation": cohort_summary([r for r, _ in cohort if r.version_id == version.id])
                if spec and spec.get("rubric_version", 1) >= 3
                else run_summary(run)
                if run
                else None,
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
        "评测使用冻结的模拟工具；未验证真实服务的行为。",
        "未保存生产流量、客户效果或部署验收。",
        "项目中的最佳版本可能与在线智能体不同，尚未验证配置一致性。",
        "案例保留脱敏的输入与工具事实；个人信息、凭据和内部思考不进入材料。",
        "导出是项目作品集快照，尚未验证可直接运行或部署。",
    ]
    if not selected:
        limitations.append("尚无可比较的有效成绩，最佳版本未确定。")
    if not baseline or not spec:
        limitations.append("冻结的评测设计或完整实验结果缺失。")
    if any(not s.get("historical_content_available") for s in config.get("skills", [])):
        limitations.append("历史文本指南正文缺失，不使用当前在线指南替代。")
    if state.get("state") in {"pending", "running", "failed"}:
        limitations.append("优化尚未完成；进程重启后后台任务需要显式重试。")
    if any((run.metrics_json or {}).get("errored", 0) for run in runs):
        limitations.append("存在执行或裁判错误，这些错误不能用来证明模型质量。")
    if any(
        r.get("error") == "runtime_platform_unavailable"
        or "runtime_import" in str(r.get("error", ""))
        or "fcntl" in str(r.get("error", ""))
        for run in runs
        for r in run.results_json or []
    ):
        limitations.append("历史运行环境加载失败，需要使用兼容的运行环境复验。")
    candidate = next(
        (
            r
            for r in reversed(runs)
            if (r.comparison_json or {}).get("regression")
            and report_for_run(r).comparison_key == scope
        ),
        None,
    )
    if candidate:
        baseline = (
            by_run.get((candidate.comparison_json or {}).get("regression", {}).get("source_run_id"))
            or baseline
        )
    baseline_summary = run_summary(baseline) if baseline else None
    best_summary = (
        cohort_summary([r for r, _ in cohort if best and r.version_id == best.version_id])
        if spec and spec.get("rubric_version", 1) >= 3
        else run_summary(best)
        if best
        else None
    )
    candidate_summary = run_summary(candidate) if candidate else None
    from app.services.agent_project_optimization_rules import compare_runs

    comparisons = []
    for right in runs:
        source = (right.comparison_json or {}).get("regression", {}).get("source_run_id")
        left = by_run.get(source)
        if not left or not right.completed_at:
            continue
        try:
            change = compare_runs(left, right)
            comparisons.append(
                {
                    "source_version": by_version[str(left.version_id)].version_number,
                    "target_version": by_version[str(right.version_id)].version_number,
                    "source_run_id": str(left.id),
                    "target_run_id": str(right.id),
                    "kind": "adjacent",
                    "comparable": True,
                    "changes": change,
                }
            )
        except ValueError:
            comparisons.append(
                {
                    "source_version": by_version[str(left.version_id)].version_number,
                    "target_version": by_version[str(right.version_id)].version_number,
                    "source_run_id": str(left.id),
                    "target_run_id": str(right.id),
                    "kind": "adjacent",
                    "comparable": False,
                    "changes": None,
                }
            )
    if candidate:
        root = candidate
        seen = set()
        while str(root.id) not in seen:
            seen.add(str(root.id))
            parent_run = by_run.get(
                (root.comparison_json or {}).get("regression", {}).get("source_run_id")
            )
            if not parent_run:
                break
            root = parent_run
        if (
            root.id != candidate.id
            and by_version[str(candidate.version_id)].version_number
            - by_version[str(root.version_id)].version_number
            > 1
        ):
            try:
                changes = compare_runs(root, candidate)
                comparisons.append(
                    {
                        "source_version": by_version[str(root.version_id)].version_number,
                        "target_version": by_version[str(candidate.version_id)].version_number,
                        "source_run_id": str(root.id),
                        "target_run_id": str(candidate.id),
                        "kind": "cumulative",
                        "comparable": True,
                        "changes": changes,
                    }
                )
            except ValueError:
                comparisons.append(
                    {
                        "source_version": by_version[str(root.version_id)].version_number,
                        "target_version": by_version[str(candidate.version_id)].version_number,
                        "source_run_id": str(root.id),
                        "target_run_id": str(candidate.id),
                        "kind": "cumulative",
                        "comparable": False,
                        "changes": None,
                    }
                )
    deltas = {}
    if baseline_summary and candidate_summary and baseline_summary["complete"]:
        for name, metric in baseline_summary["metrics"].items():
            other = candidate_summary["metrics"].get(name)
            if (
                other
                and metric.get("evaluated_cases") == baseline_summary["total"]
                and other.get("evaluated_cases") == candidate_summary["total"]
            ):
                deltas[name] = other["score"] - metric["score"]
    payload = sanitize(
        alias(
            {
                "project": {
                    "name": project.title,
                    "goal": (project.requirements_json or {}).get("task", {}).get("goal")
                    or config.get("description")
                    or UNAVAILABLE,
                    "intended_use": config.get("description") or UNAVAILABLE,
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
                    "basis": (
                        "Root causes are analysis of observable evidence, not hidden reasoning."
                    ),
                },
                "results": {
                    "best_version": selected.version_number if selected else None,
                    "best_run_id": str(best.id) if best else None,
                    "latest_version": versions[-1].version_number if versions else None,
                    "current": run_summary(runs[-1]) if runs else None,
                    "current_version": by_version[str(runs[-1].version_id)].version_number
                    if runs
                    else None,
                    "baseline": baseline_summary,
                    "baseline_version": by_version[str(baseline.version_id)].version_number
                    if baseline
                    else None,
                    "comparisons": comparisons,
                    "best": best_summary,
                    "candidate": candidate_summary,
                    "candidate_version": by_version[str(candidate.version_id)].version_number
                    if candidate
                    else None,
                    "metric_deltas": deltas,
                },
                "authored_analysis": (project.report_json or {}).get("authored_analysis"),
                "system_analysis": (project.report_json or {}).get("system_analysis"),
                "requirements": (baseline.comparison_json or {}).get("requirements", {})
                if baseline
                else {},
                "decisions": [
                    {
                        "stage": d.get("stage"),
                        "choice": d.get("choice"),
                        "reason": d.get("reason"),
                        "author": decision_author(d),
                        "version": aliases.get(str(d.get("version_id"))),
                        "source_run_id": aliases.get(str(d.get("run_id"))),
                        "type": "confirmation",
                    }
                    for d in project.decisions_json or []
                ],
                "experiment_references": [
                    {
                        "reference": f"experiment-{i + 1}",
                        "version": by_version[str(r.version_id)].version_number,
                        "status": r.status,
                        "summary": run_summary(r),
                        "eval_spec": (r.comparison_json or {}).get("eval_spec"),
                        "cases": [
                            {
                                "reference": f"experiment-{i + 1}/case-{j + 1}",
                                "status": x.get("status"),
                                "metrics": x.get("metric_scores", {}),
                                "assertions": x.get("assertions", []),
                                "error": x.get("error"),
                                "termination_reason": x.get("termination_reason"),
                                "model_names": [
                                    c.get("model", {}).get("model_name")
                                    for c in x.get("model_calls", [])
                                ],
                                "evidence_available": bool(x.get("model_calls")),
                            }
                            for j, x in enumerate(r.results_json or [])
                        ],
                    }
                    for i, r in enumerate(runs)
                ],
                "limitations": limitations,
            }
        )
    )
    from app.services.agent_project_case_cards import case_cards

    payload = remove_sources(payload, source_strings(runs))
    # Owner-visible case excerpts use value redaction. Public sharing projects them separately.
    cards = case_cards(
        runs,
        by_version,
        (project.report_json or {}).get("selected_case_ids", []),
        (project.report_json or {}).get("historical_reviews", []),
        project.decisions_json or [],
    )
    payload["case_cards"] = sanitize(alias(cards))
    payload["material_readiness"] = "ready" if len(cards) >= 2 else "missing_actual_cases"
    payload["reference_map"] = list(aliases.values())
    return payload


def cohort_summary(runs: list[AgentProjectEvalRun]) -> dict[str, Any] | None:
    """Aggregate all complete runs for a version, retaining errors in the denominator."""
    summaries = [run_summary(r) for r in runs if run_summary(r)["complete"]]
    if not summaries:
        return None
    total = sum(s["total"] for s in summaries)
    passed = sum(s["passed"] for s in summaries)
    result = {
        **summaries[-1],
        "total": total,
        "passed": passed,
        "pass_rate": passed / total,
        "run_count": len(summaries),
        "selection": "all_valid_runs_in_scope",
        "metrics": {},
    }
    for field in ("failed", "errored", "execution_errors", "judge_errors"):
        result[field] = (
            sum(s[field] for s in summaries)
            if all(s[field] is not None for s in summaries)
            else None
        )
    for name in {n for s in summaries for n in s["metrics"]}:
        values = [s["metrics"][name] for s in summaries if name in s["metrics"]]
        coverage = sum(v.get("evaluated_cases", 0) for v in values)
        if coverage:
            result["metrics"][name] = {
                "score": sum(v["score"] * v.get("evaluated_cases", 0) for v in values) / coverage,
                "evaluated_cases": coverage,
                "passed_cases": sum(v.get("passed_cases", 0) for v in values),
            }
    return result


def display(value: Any) -> str:
    if value is None:
        return UNAVAILABLE
    if isinstance(value, bool):
        return "Recorded" if value else UNAVAILABLE
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def rate(value: Any) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else UNAVAILABLE


def render_report(data: dict[str, Any]) -> dict[str, Any]:
    results, config = data["results"], data["architecture"]
    spec = data["eval_spec"] or {}
    design, bad = data["evaluation_design"], data["bad_cases"]

    def names(items: list[dict[str, Any]]) -> str:
        return ", ".join(str(item.get("name") or UNAVAILABLE) for item in items) or UNAVAILABLE

    architecture_text = (
        f"Provider: {display(config.get('model', {}).get('provider'))}\n"
        f"Model: {display(config.get('model', {}).get('model_name'))}\n"
        f"Tools: {names(config.get('tools', []))}\n"
        f"Skills: {names(config.get('skills', []))}\n"
        f"MCP tools: {names(config.get('mcp', []))}\n"
        f"Instructions: {display(config.get('instructions_summary'))}"
    )
    evaluation_text = (
        f"Frozen cases: {display(design['case_count'])}\n"
        "Scenarios: "
        + (", ".join(f"{k} ({v})" for k, v in design["scenarios"].items()) or UNAVAILABLE)
        + "\n"
        + f"Case pass threshold: {display(spec.get('pass_threshold'))}\n"
        "External tool responses come from the frozen mocks, not production services.\n"
        + "\n".join(
            f"- {m['name']}: {m['type']}; weight {m['weight']}; "
            f"criteria: {m.get('criteria', 'Private rubric text omitted.')}"
            for m in spec.get("metrics", [])
        )
    )
    bad_text = (
        f"Failed cases: {display(bad['failed_count'])}; "
        f"execution/judge errors: {display(bad['errored_count'])}; "
        f"analyzed: {bad['analyzed_count']}.\n{bad['basis']}\n"
        + "\n".join(f"- {k}: {v}" for k, v in bad["categories"].items())
        + "\nGrouped causes:\n"
        + (
            "\n".join(
                f"- {g['category']} → {g['target']} ({g['case_count']} cases): "
                f"{g.get('root_cause', 'Detailed analysis omitted from public share.')}"
                for g in bad["groups"]
            )
            or UNAVAILABLE
        )
        + "\nRepresentative observable results:\n"
        + (
            "\n".join(
                f"- Frozen case {r['case_number']}: {r['status']}; "
                + ", ".join(f"{k}={v['score']}" for k, v in r["metric_scores"].items())
                for r in bad["examples"]
            )
            or UNAVAILABLE
        )
    )
    journey = []
    for version in data["versions"]:
        run, comparison = version["evaluation"] or {}, version["comparison"]
        metric_changes = (
            ", ".join(
                f"{name}: {display(change.get('delta'))}"
                for name, change in comparison.get("metrics", {}).items()
            )
            or UNAVAILABLE
        )
        journey.append(
            f"V{version['version']} — {version['decision']}"
            + (" — Best" if version["best"] else "")
            + f"\nPassed: {display(run.get('passed'))} / {display(run.get('total'))} "
            f"({rate(run.get('pass_rate'))})\n"
            + "Fixes: "
            + (
                ", ".join(f"{fix['operation']} {fix['target']}" for fix in version["fixes"])
                or UNAVAILABLE
            )
            + "\n"
            + "; ".join(
                f"{key.replace('_', ' ')}: {display(comparison.get(key))}"
                for key in ("fixed_cases", "regressed_cases", "still_failing_cases")
            )
            + f"\nMetric deltas versus parent: {metric_changes}\n"
            + "Decision evidence: "
            + (", ".join(comparison.get("reasons", [])) or UNAVAILABLE)
        )
    sections = [
        {
            "title": "Project Overview",
            "body": f"{data['project']['name']}\nGoal: {data['project']['goal']}\n"
            f"Intended use: {data['project']['intended_use']}\n"
            f"Best Version: {display(results['best_version'])}",
        },
        {"title": "Agent Architecture", "body": architecture_text},
        {
            "title": "Build Process",
            "body": "User requirement → Agent Build → Project V1 → Eval Plan → EvalSet "
            "→ Evaluation → Optimization\nOnly stages marked Recorded have evidence.\n"
            + "\n".join(f"{k}: {display(v)}" for k, v in data["build_process"].items()),
        },
        {"title": "Evaluation Design", "body": evaluation_text},
        {"title": "Bad Case Analysis", "body": bad_text},
        {"title": "Optimization & Regression", "body": "\n\n".join(journey) or UNAVAILABLE},
        {
            "title": "Final Results",
            "body": f"Best Version: {display(results['best_version'])}\nControlled evaluation: "
            f"{rate((results['baseline'] or {}).get('pass_rate'))} → "
            f"{rate((results['best'] or {}).get('pass_rate'))}\nMetric deltas versus baseline:\n"
            + (
                "\n".join(f"- {k}: {v:.4f}" for k, v in results["metric_deltas"].items())
                or UNAVAILABLE
            )
            + "\n\n"
            + "\n".join(data["limitations"]),
        },
    ]
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


async def select_cases(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    runs = (
        await db.scalars(
            select(AgentProjectEvalRun).where(AgentProjectEvalRun.project_id == project.id)
        )
    ).all()
    recorded = {r["case_id"] for run in runs for r in run.results_json or []}
    selected = [str(identity) for identity in ids]
    if len(set(selected)) != len(selected) or not set(selected) <= recorded:
        raise AppError(
            code="project_case_evidence_not_found",
            message="project_case_evidence_not_found",
            status=422,
        )
    await save_content(db, project, "selected_case_ids", selected)
    return await report(db, agent_id, user_id)


async def report(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, *, save: bool = False
) -> dict[str, Any]:
    from app.services.agent_project_materials import render_chinese_report

    result = render_chinese_report(await evidence(db, agent_id, user_id))
    project = await projects.require_project(db, agent_id, user_id)
    result["artifact_status"] = {
        key: "missing"
        if not (project.report_json or {}).get(key)
        else "current"
        if (project.report_json or {})[key].get("evidence_hash") == result["evidence_hash"]
        else "stale"
        for key in ("portfolio_report", "portfolio_resume", "portfolio_interview")
    }
    if save:
        await save_content(
            db, await projects.require_project(db, agent_id, user_id), "portfolio_report", result
        )
    return result


async def resume(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, style: str
) -> dict[str, Any]:
    data = await evidence(db, agent_id, user_id)
    from app.services.agent_project_materials import resume_material

    result = resume_material(data)
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
        shared.pop("case_cards", None)
        shared.pop("reference_map", None)
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
