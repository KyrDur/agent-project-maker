"""Authored requirements, revision-aware decisions and evidence-based completion."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProject, AgentProjectEvalRun, utcnow
from app.schemas.agent_project import ProjectDecision, ProjectRequirements
from app.services import agent_project_service as projects


def fail(code: str) -> AppError:
    return AppError(code=code, message=code, status=409)


def requirements(project: AgentProject) -> dict[str, Any]:
    return (project.requirements_json or {}).get("task", {})


def requirements_hash(project: AgentProject) -> str:
    return canonical_json_hash(requirements(project))


async def write_requirements(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: ProjectRequirements
) -> AgentProject:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(project, ["requirements_json", "decisions_json"])
    task = projects.snapshot_value(body.model_dump(mode="json"))
    if task != requirements(project):
        project.eval_spec_json = None
        project.completion_json = None
        project.requirements_json = {
            **(project.requirements_json or {}),
            "bootstrap": {"stage": "v1", "error": None},
        }
    project.requirements_json = {**(project.requirements_json or {}), "task": task}
    await db.commit()
    return project


async def record_decision(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: ProjectDecision
) -> AgentProject:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(project, ["requirements_json", "decisions_json"])
    version = await projects.get_version(db, agent_id, user_id, body.version_id)
    if not requirements(project):
        raise fail("project_requirements_required")
    value = body.model_dump(mode="json")
    value.update(
        id=str(uuid.uuid4()),
        created_at=utcnow().isoformat(),
        requirements_hash=requirements_hash(project),
        config_hash=version.config_hash,
    )
    if body.stage == "case_review":
        from app.services.agent_project_evaluation import get_set

        if body.eval_set_id is None or not body.case_ids:
            raise fail("project_case_review_required")
        dataset = await get_set(db, project.id, body.eval_set_id)
        enabled = {c["id"] for c in dataset.cases_json if c.get("enabled", True)}
        if not set(map(str, body.case_ids)) <= enabled:
            raise fail("project_case_review_invalid")
        value["dataset_hash"] = canonical_json_hash(dataset.cases_json)
    project.decisions_json = [*(project.decisions_json or []), projects.snapshot_value(value)]
    project.completion_json = None
    await db.commit()
    return project


def checked_decisions(
    project: AgentProject,
    version_id: uuid.UUID,
    dataset: Any,
    inherited: list[dict] | None = None,
) -> list[dict]:
    ProjectRequirements.model_validate(requirements(project))
    choices = [
        d
        for d in project.decisions_json or []
        if d.get("requirements_hash") == requirements_hash(project)
        and d.get("version_id") == str(version_id)
    ]
    for value in inherited or []:
        if (
            value.get("requirements_hash") == requirements_hash(project)
            and value.get("stage") in {"requirements", "capabilities"}
            and value not in choices
        ):
            choices.append(value)
    for stage in ("requirements", "capabilities"):
        valid = [d for d in choices if d["stage"] == stage]
        if stage == "case_review":
            valid = [
                d
                for d in valid
                if d.get("eval_set_id") == str(dataset.id)
                and d.get("dataset_hash") == canonical_json_hash(dataset.cases_json)
            ]
        if not valid:
            raise fail("project_decisions_required")
    return choices


async def completion(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, analysis: str | None = None
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    runs = list(
        (
            await db.scalars(
                select(AgentProjectEvalRun)
                .where(AgentProjectEvalRun.project_id == project.id)
                .order_by(AgentProjectEvalRun.created_at, AgentProjectEvalRun.id)
            )
        ).all()
    )
    reasons = []
    current_hash = requirements_hash(project)
    valid = [
        r
        for r in runs
        if r.completed_at
        and r.status in {"completed", "failed"}
        and len(r.results_json or [])
        == len(r.cases_snapshot_json or []) * (r.comparison_json or {}).get("repetitions", 1)
        and any(x.get("status") in {"passed", "failed"} for x in r.results_json or [])
        and (r.comparison_json or {}).get("requirements_hash") == current_hash
    ]
    candidates = [r for r in valid if (r.comparison_json or {}).get("regression")]
    candidate = candidates[-1] if candidates else None
    source_id = (
        (candidate.comparison_json or {}).get("regression", {}).get("source_run_id")
        if candidate
        else None
    )
    baseline = next((r for r in valid if str(r.id) == source_id), None)
    latest = valid[-1] if valid else None
    analysis_record = (latest.comparison_json or {}).get("analysis") if latest else None
    perfect = bool(
        latest
        and all(
            r.get("status") == "passed"
            and r.get("metric_scores")
            and all(m.get("score", 0) == 1 for m in r["metric_scores"].values())
            for r in latest.results_json or []
        )
    )
    no_improvement = bool(
        latest and (perfect or (analysis_record is not None and not analysis_record.get("groups")))
    )
    if not baseline or not candidate:
        if not no_improvement:
            reasons.append("project_comparable_experiment_required")
        elif latest:
            baseline = latest
            stages = {d.get("stage") for d in (latest.comparison_json or {}).get("decisions", [])}
            if not {"requirements", "capabilities"} <= stages:
                reasons.append("project_decisions_required")
    if baseline and candidate:
        from app.services.agent_project_optimization_rules import compare_runs

        try:
            compare_runs(baseline, candidate)
        except ValueError:
            reasons.append("project_comparable_experiment_required")
        stages = {d.get("stage") for d in (baseline.comparison_json or {}).get("decisions", [])}
        if not {"requirements", "capabilities"} <= stages:
            reasons.append("project_decisions_required")
        if not any(
            d.get("stage") == "optimization" and d.get("run_id") == source_id
            for d in project.decisions_json or []
        ):
            reasons.append("project_optimization_decision_required")
    # 每一轮回归都必须有对应的实际用户选择，而非只验证最后一轮。
    cursor = candidate
    seen: set[uuid.UUID] = set()
    while cursor and cursor.id not in seen:
        seen.add(cursor.id)
        parent_id = (cursor.comparison_json or {}).get("regression", {}).get("source_run_id")
        if not parent_id:
            break
        if (
            not any(
                d.get("stage") == "optimization"
                and d.get("run_id") == parent_id
                and d.get("reason", "").strip()
                for d in project.decisions_json or []
            )
            and "project_optimization_decision_required" not in reasons
        ):
            reasons.append("project_optimization_decision_required")
        cursor = next((r for r in valid if str(r.id) == parent_id), None)
    authored_analysis = analysis or (project.completion_json or {}).get("analysis")
    if not authored_analysis and latest:
        from collections import Counter

        counts = Counter(r["status"] for r in latest.results_json or [])
        cases = len(latest.cases_snapshot_json or [])
        repeats = (latest.comparison_json or {}).get("repetitions", 1)
        observations = [
            f"冻结场景 {cases} 条，每例重复 {repeats} 次，共 {cases * repeats} 个试验；"
            f"任务通过 {counts['passed']}，任务失败 {counts['failed']}，错误 {counts['errored']}。",
        ]
        for i, result in enumerate(latest.results_json or [], 1):
            status = {"passed": "通过", "failed": "失败", "errored": "评测错误"}.get(
                result["status"], result["status"]
            )
            observations.append(f"试验 {i} · {result.get('name') or '未命名场景'}：{status}。")
        if analysis_record:
            for group in analysis_record.get("groups", []):
                observations.append(
                    "裁判分析："
                    + str(group.get("root_cause") or group.get("proposed_change") or "未记录原因")
                )
        observations.append(
            "以上结论只适用于冻结测试范围；真实客户效果、生产部署和业务收益未验证。"
        )
        authored_analysis = "\n".join(observations)
    if not authored_analysis:
        reasons.append("project_analysis_required")
    if analysis is not None:
        await projects.lock_project(db, project)
        await db.refresh(project, ["report_json"])
        project.report_json = {
            **(project.report_json or {}),
            "authored_analysis": projects.snapshot_value(analysis) if analysis.strip() else None,
            "system_analysis": authored_analysis,
        }
        await db.flush()
    from app.services.agent_project_portfolio import report

    material = await report(db, agent_id, user_id)
    result = {
        "status": "completed" if not reasons else "incomplete",
        "reasons": reasons,
        "analysis": authored_analysis,
        "evidence_hash": material["evidence_hash"],
        "baseline_run_id": str(baseline.id) if baseline else None,
        "candidate_run_id": str(candidate.id) if candidate else None,
        "quality_gate": False,
        "no_supported_improvement": no_improvement,
        "analysis_source": "user" if analysis else "system",
    }
    if analysis is not None:
        await projects.lock_project(db, project)
        project.completion_json = projects.snapshot_value(
            {**result, "updated_at": utcnow().isoformat()}
        )
        await db.commit()
    return result
