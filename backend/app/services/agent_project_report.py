"""Small read projection; run results remain the source of truth. No writes or LLM calls."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProjectEvalRun
from app.schemas.agent_project_report import EvaluationReport, EvaluationReports, ReportFailure
from app.services import agent_project_service as projects
from app.services.agent_project_portfolio import run_summary


def report_for_run(run: AgentProjectEvalRun) -> EvaluationReport:
    summary = run_summary(run)
    results = run.results_json or []
    plan = run.comparison_json or {}
    roles = plan.get("roles") or {}
    analyses = {item["case_id"]: item for item in run.bad_cases_json or []}
    failures = []
    for result in results:
        if result.get("status") == "passed":
            continue
        analysis = analyses.get(result["case_id"], {})
        reasons = [analysis["root_cause"]] if analysis.get("root_cause") else []
        if not reasons:
            reasons = [
                item["reason"]
                for item in result.get("metric_scores", {}).values()
                if not item.get("passed") and item.get("reason")
            ]
            reasons += [
                item["kind"] + (": " + str(item["target"]) if item.get("target") else "")
                for item in result.get("assertions", [])
                if not item.get("passed")
            ]
            if result.get("error"):
                reasons.append(result["error"])
        failures.append(
            ReportFailure(
                case_id=result["case_id"],
                trial=result.get("trial", 1),
                name=result.get("name", ""),
                reasons=list(dict.fromkeys(reasons)),
            )
        )
    # Errors/partial runs are visible, but cannot masquerade as a quality score.
    score = summary["pass_rate"] if summary["complete"] and run.status == "completed" else None
    key = (
        canonical_json_hash(
            {
                "dataset": run.dataset_hash,
                "requirements_hash": plan.get("requirements_hash"),
                "resolved_roles": plan.get("resolved_roles"),
                "role_configurations": plan.get("role_configurations"),
                "resolved_examinee": plan.get("resolved_examinee"),
                "resolved_role_models": plan.get("resolved_role_models"),
                "eval_set_id": str(run.eval_set_id),
                "eval_spec": plan.get("eval_spec"),
                "scoring": summary["scoring"],
                "judge": roles.get("judge"),
                "judge_prompt_version": roles.get("judge_prompt_version"),
                "execution_mode": plan.get("execution_mode"),
                "execution_protocol": plan.get("execution_protocol"),
                "validation_exposure": plan.get("validation_exposure"),
                "repetitions": plan.get("repetitions", 1),
                "purpose": plan.get("purpose", "regression"),
            }
        )
        if run.dataset_hash
        else None
    )
    suggestions = [
        group["proposed_change"]
        for group in (plan.get("analysis") or {}).get("groups", [])
        if group.get("proposed_change")
    ] or [item["suggested_fix"] for item in analyses.values() if item.get("suggested_fix")]
    return EvaluationReport(
        version_id=run.version_id,
        eval_set_id=run.eval_set_id,
        evaluation_run_id=run.id,
        status=run.status,
        score=score,
        metrics={name: value["score"] for name, value in summary["metrics"].items()},
        statistics=run.metrics_json or {},
        eval_spec=plan.get("eval_spec"),
        total=len(run.cases_snapshot_json or []) * plan.get("repetitions", 1),
        passed=sum(item.get("status") == "passed" for item in results),
        bad_case_count=len(failures),
        bad_cases=failures,
        optimization_suggestions=list(dict.fromkeys(suggestions)),
        comparison_key=key,
        created_at=run.completed_at or run.created_at,
        proposals=plan.get("proposals", []),
        source_run_id=plan.get("regression", {}).get("source_run_id"),
    )


async def list_reports(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EvaluationReports:
    project = await projects.require_project(db, agent_id, user_id)
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
    versions = {v.id: v.version_number for v in await projects.list_versions(db, agent_id, user_id)}
    reports = [
        report_for_run(run).model_copy(update={"version_number": versions.get(run.version_id)})
        for run in runs
        if run.status in {"completed", "failed"}
    ]
    best = select_best_reports(reports)
    return EvaluationReports(
        reports=list(reversed(reports)),
        best_run_ids={key: report.evaluation_run_id for key, report in best.items()},
        active=any(
            run.status in {"pending", "running"}
            or (run.comparison_json or {}).get("optimization", {}).get("state")
            in {"pending", "running"}
            for run in runs
        ),
    )


def select_best_reports(reports: list[EvaluationReport]) -> dict[str, EvaluationReport]:
    """V3 ranks versions over all valid runs in scope, never the best repeated run."""
    scopes: dict[str, list[EvaluationReport]] = {}
    for report in reports:
        if report.comparison_key and report.score is not None:
            scopes.setdefault(report.comparison_key, []).append(report)
    best = {}
    for key, cohort in scopes.items():
        if (cohort[0].eval_spec or {}).get("rubric_version", 1) < 3:
            best[key] = max(cohort, key=lambda r: r.score or 0)
            continue
        grouped: dict[uuid.UUID, list[EvaluationReport]] = {}
        for report in cohort:
            grouped.setdefault(report.version_id, []).append(report)
        winner = max(
            grouped.values(),
            key=lambda rs: (
                sum(r.passed for r in rs) / sum(r.total for r in rs),
                -(rs[0].version_number or 1000000),
            ),
        )
        best[key] = winner[-1]
    return best
