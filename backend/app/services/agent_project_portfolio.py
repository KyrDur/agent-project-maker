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
    baseline = by_run.get(str(state.get("root_run_id")))
    if baseline is None and not state:
        baseline = next((r for r in runs if run_summary(r)["complete"]), None)
    best = by_run.get(str(state.get("best_run_id")))
    if best and (
        str(best.version_id) != state.get("best_version_id") or not run_summary(best)["complete"]
    ):
        best = None
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
        "Evaluation uses frozen mock external tools; live provider behavior may differ.",
        "No production traffic or deployment validation is stored.",
        "Project Best Version may differ from the live Agent; "
        "live configuration equivalence is unverified.",
        "Raw cases, private source data, tool outputs and hidden reasoning "
        "are omitted from portfolio artifacts.",
        "Export is a portfolio snapshot, not a runnable deployment package.",
    ]
    if not selected:
        limitations.append(
            "Best Version selection is unavailable; latest version is not assumed best."
        )
    if not baseline or not spec:
        limitations.append("Frozen evaluation design or completed results are unavailable.")
    if any(not s.get("historical_content_available") for s in config.get("skills", [])):
        limitations.append(
            "Historical Skill content is unavailable; current live Skills are not substituted."
        )
    if state.get("state") in {"pending", "running", "failed"}:
        limitations.append(
            "Optimization is incomplete; background tasks do not recover after process restart."
        )
    if any((run.metrics_json or {}).get("errored", 0) for run in runs):
        limitations.append(
            "Execution or judge errors occurred; they are not evidence of model quality."
        )
    if any(
        r.get("error") == "runtime_platform_unavailable"
        or "runtime_import" in str(r.get("error", ""))
        or "fcntl" in str(r.get("error", ""))
        for run in runs
        for r in run.results_json or []
    ):
        limitations.append("Stored runtime import failures may require a supported Linux runtime.")
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
    payload = sanitize(
        {
            "project": {
                "name": project.title,
                "goal": config.get("description") or UNAVAILABLE,
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
                "basis": "Root causes are analysis of observable evidence, not hidden reasoning.",
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


async def report(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, *, save: bool = False
) -> dict[str, Any]:
    result = render_report(await evidence(db, agent_id, user_id))
    if save:
        await save_content(
            db, await projects.require_project(db, agent_id, user_id), "portfolio_report", result
        )
    return result


async def resume(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, style: str
) -> dict[str, Any]:
    data = await evidence(db, agent_id, user_id)
    starts = {
        "ai_product": "Developed an evidence-based Agent product case study",
        "product": "Documented an Agent project's requirements, evaluation and iteration outcomes",
        "engineering": "Documented immutable Agent configuration "
        "and reproducible mock evaluation evidence",
    }
    bullets = [f"{starts[style]} for {data['project']['name']}."]
    design, results = data["evaluation_design"], data["results"]
    if design["case_count"]:
        bullets.append(
            f"Evaluated a frozen {design['case_count']}-case dataset covering "
            f"{', '.join(design['scenarios']) or 'stored scenarios'} using mock external tools."
        )
    before = (results["baseline"] or {}).get("pass_rate")
    after = (results["best"] or {}).get("pass_rate")
    if before is not None and after is not None:
        bullets.append(
            f"Recorded controlled evaluation pass rates of {rate(before)} at baseline "
            f"and {rate(after)} for selected V{results['best_version']}; "
            "production impact remains unvalidated."
        )
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
