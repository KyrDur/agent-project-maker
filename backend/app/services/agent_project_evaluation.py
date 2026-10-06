"""Bounded evaluation storage/execution and version comparison."""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from datetime import timedelta
from time import perf_counter
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import (
    AgentProjectEvalRun,
    AgentProjectEvalSet,
    utcnow,
)
from app.schemas.agent_project import EvalRunCreate, EvalSetWrite, EvaluationCase
from app.services import agent_project_service as projects
from app.services.agent_project_executor import SnapshotExecutionUnavailable, execute_snapshot


def error(code: str, status: int = 422) -> AppError:
    return AppError(code=code, message=code, status=status)


async def get_set(
    db: AsyncSession, project_id: uuid.UUID, set_id: uuid.UUID
) -> AgentProjectEvalSet:
    row = await db.scalar(
        select(AgentProjectEvalSet)
        .where(AgentProjectEvalSet.id == set_id, AgentProjectEvalSet.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise error("agent_project_eval_set_not_found", 404)
    return row


async def write_set(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    body: EvalSetWrite,
    set_id: uuid.UUID | None = None,
    *,
    rubric: dict[str, Any] | None = None,
    evaluation_focus: list[dict[str, Any]] | None = None,
    evaluation_focus_reason: str | None = None,
    new_id: uuid.UUID | None = None,
) -> AgentProjectEvalSet:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    if new_id:
        existing = await db.get(AgentProjectEvalSet, new_id)
        if existing:
            if existing.project_id != project.id:
                raise error("evaluation_request_conflict", 409)
            await db.commit()
            return existing
    row = (
        await get_set(db, project.id, set_id)
        if set_id
        else AgentProjectEvalSet(project_id=project.id, **({"id": new_id} if new_id else {}))
    )
    if row.frozen:
        raise error("agent_project_eval_set_frozen", 409)
    old = {case["id"]: case for case in (row.cases_json or []) if "id" in case}
    if len({case.id for case in body.cases}) != len(body.cases):
        raise error("duplicate_evaluation_case")
    now = utcnow().isoformat()
    cases = []
    for case in body.cases:
        data = case.model_dump(mode="json")
        if case.metric_applicability is None:
            data.pop("metric_applicability")
            data.pop("metric_applicability_reasons")
        if not case.expected.attempted_tools:
            data["expected"].pop("attempted_tools")
        if case.expected.max_characters is None:
            data["expected"].pop("max_characters")
        data.update(
            project_id=str(project.id),
            created_at=old.get(str(case.id), {}).get("created_at", now),
            updated_at=now,
        )
        cases.append(projects.snapshot_value(data))
    if rubric is not None:
        row.rubric_json = deepcopy(rubric)
    if evaluation_focus is not None:
        row.evaluation_focus_json = deepcopy(evaluation_focus)
    if evaluation_focus_reason is not None:
        row.evaluation_focus_reason = evaluation_focus_reason
    row.name, row.cases_json = projects.snapshot_value(body.name), cases
    row.quality_report_json = None  # Edited cases must pass quality review again.
    db.add(row)
    await db.commit()
    return row


async def judge_set(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, set_id: uuid.UUID
) -> AgentProjectEvalSet:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    dataset = await get_set(db, project.id, set_id)
    await db.refresh(dataset)
    if dataset.frozen:
        await db.commit()
        return dataset
    profile = (dataset.rubric_json or project.eval_spec_json or {}).get("capability_profile", {})
    cases = [case for case in dataset.cases_json or [] if case.get("enabled", True)]
    covered = {tag for case in cases for tag in case.get("tags", [])}
    capabilities = set(profile.get("capabilities", [])) if isinstance(profile, dict) else set()
    coverage = 1.0 if not capabilities else len(capabilities & covered) / len(capabilities)

    def has_basis(case: dict[str, Any]) -> bool:
        expected = case.get("expected", {})
        return bool(
            case.get("judgment_basis")
            or any(
                expected.get(k)
                for k in (
                    "answer",
                    "state",
                    "tool_arguments",
                    "necessary_order",
                    "required_tools",
                    "attempted_tools",
                    "forbidden_tools",
                    "format_rule",
                    "handoff",
                )
            )
            or expected.get("exact_answer") is not None
        )

    valid = sum(bool(case.get("input")) for case in cases) / max(len(cases), 1)
    unique_inputs = len({str(case.get("input", "")).strip().lower() for case in cases})
    diversity = unique_inputs / max(len(cases), 1)
    evaluable = sum(has_basis(case) for case in cases) / max(len(cases), 1)
    scores = {
        "coverage_score": coverage,
        "validity_score": valid,
        "diversity_score": diversity,
        "evaluability_score": evaluable,
    }
    overall = sum(scores.values()) / 4
    issues = []
    from app.services.agent_project_rubric import validate_applicability, validate_sources
    from app.services.agent_project_semantic import spec_value

    stored = dataset.rubric_json or project.eval_spec_json or {}
    if stored.get("rubric_version", 1) >= 2:
        try:
            spec = spec_value(stored)
            from app.services.agent_project_practice import requirements

            validate_sources(spec, requirements(project))
            for case in cases:
                validate_applicability(spec, case)
        except (ValueError, TypeError):
            issues.append("invalid_scoring_contract")
    preflight = []
    if stored.get("rubric_version", 1) >= 3:
        from app.services.agent_project_preflight import preflight_case

        try:
            version = await projects.get_version(
                db, agent_id, user_id, uuid.UUID(stored["version_id"])
            )
            preflight = [preflight_case(version.snapshot_json["agent"], case) for case in cases]
            if not stored.get("reference_validation", {}).get("semantic"):
                issues.append("missing_reference_review")
            reviewed_hash = stored.get("reference_validation", {}).get("case_hash")
            current_hash = canonical_json_hash(
                [
                    EvaluationCase.model_validate(
                        {k: v for k, v in c.items() if k in EvaluationCase.model_fields}
                    ).model_dump(mode="json")
                    for c in cases
                ]
            )
            if reviewed_hash != current_hash:
                from app.schemas.agent_project import RubricRuleReview
                from app.services import agent_project_semantic as semantic
                from app.services.agent_project_llm import capture_calls

                references = {c["id"]: p for c, p in zip(cases, preflight, strict=True)}
                calls: list[dict[str, Any]] = []
                with capture_calls(calls):
                    review = await semantic.json_call(
                        db,
                        {
                            **version.snapshot_json,
                            "role_configurations": stored.get("role_configurations"),
                        },
                        user_id,
                        "judge",
                        "Review each reference answer and path against confirmed requirements "
                        "and frozen rubric. Return rule_reviews [{reference,supported,reason}] "
                        "for exactly every case ID. Reject contradictions and added assumptions.",
                        {
                            "requirements": requirements(project),
                            "eval_spec": stored,
                            "cases": cases,
                            "reference_results": references,
                        },
                    )
                reviews = [RubricRuleReview.model_validate(r) for r in review["rule_reviews"]]
                if (
                    len(reviews) != len(cases)
                    or {r.reference for r in reviews} != set(references)
                    or not all(r.supported for r in reviews)
                ):
                    issues.append("invalid_reference_review")
                else:
                    stored = deepcopy(stored)
                    stored["reference_validation"] = {
                        "case_hash": current_hash,
                        "program": references,
                        "semantic": [r.model_dump() for r in reviews],
                        "calls": calls,
                    }
                    dataset.rubric_json = stored
        except (ValueError, TypeError, KeyError, SnapshotExecutionUnavailable):
            issues.append("invalid_simulation_environment")
    if capabilities - covered:
        issues.append("missing_capabilities")
    if diversity < 0.8:
        issues.append("low_diversity")
    if evaluable < 1:
        issues.append("missing_judgment_basis")
    status = (
        "approved"
        if overall >= 0.75
        and evaluable == 1
        and not (capabilities - covered)
        and (
            not issues
            if stored.get("rubric_version", 1) >= 3
            else "invalid_scoring_contract" not in issues
        )
        else "rejected"
    )
    dataset.quality_report_json = {
        "eval_set_id": str(dataset.id),
        **scores,
        "overall_score": overall,
        "issues": issues,
        "recommendation": "approve" if status == "approved" else "regenerate",
        "status": status,
        "environment_preflight": preflight,
    }
    await db.commit()
    return dataset


async def remove_set(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, set_id: uuid.UUID
) -> None:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    row = await get_set(db, project.id, set_id)
    used = await db.scalar(
        select(AgentProjectEvalRun.id).where(AgentProjectEvalRun.eval_set_id == row.id).limit(1)
    )
    if used is not None or row.frozen:
        raise error("evaluation_dataset_in_use", 409)
    await db.delete(row)
    await db.commit()


async def create_run(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: EvalRunCreate
) -> AgentProjectEvalRun:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    version = await projects.get_version(db, agent_id, user_id, body.version_id)
    dataset = await get_set(db, project.id, body.eval_set_id)
    await expire_runs(db, project.id)
    prior = await db.scalar(
        select(AgentProjectEvalRun).where(
            AgentProjectEvalRun.project_id == project.id,
            AgentProjectEvalRun.request_id == body.request_id,
        )
    )
    if prior is not None:
        if (
            prior.version_id != body.version_id
            or prior.eval_set_id != body.eval_set_id
            or (prior.comparison_json or {}).get("repetitions", 1) != body.repetitions
        ):
            raise error("evaluation_request_conflict", 409)
        await db.commit()
        return prior
    # Revalidate legacy Phase 1 JSON before executing it; never infer a case.
    cases = []
    for stored in dataset.cases_json:
        data = {key: value for key, value in stored.items() if key in EvaluationCase.model_fields}
        try:
            case = EvaluationCase.model_validate(data)
        except ValueError as exc:
            raise error("evaluation_dataset_invalid") from exc
        if case.enabled:
            data = case.model_dump(mode="json")
            if case.metric_applicability is None:
                data.pop("metric_applicability")
                data.pop("metric_applicability_reasons")
            if not case.expected.attempted_tools:
                data["expected"].pop("attempted_tools")
            if case.expected.max_characters is None:
                data["expected"].pop("max_characters")
            cases.append(projects.snapshot_value(data))
    if not cases or len(cases) > 20:
        raise error("evaluation_requires_enabled_cases")
    if (dataset.rubric_json or {}).get("formal_benchmark") and len(cases) != 20:
        raise error("formal_evaluation_requires_20_cases")
    from app.services.agent_project_semantic import frozen_plan

    if not dataset.quality_report_json or dataset.quality_report_json.get("status") != "approved":
        raise error("agent_project_eval_set_quality_required", 409)
    from app.services.agent_project_practice import (
        checked_decisions,
        requirements,
        requirements_hash,
    )

    confirmed_run = await db.scalar(
        select(AgentProjectEvalRun)
        .where(
            AgentProjectEvalRun.project_id == project.id,
            AgentProjectEvalRun.version_id == version.id,
            AgentProjectEvalRun.status.in_(["completed", "failed"]),
        )
        .order_by(AgentProjectEvalRun.created_at.desc())
        .limit(1)
    )
    inherited = []
    if confirmed_run and (confirmed_run.comparison_json or {}).get(
        "requirements_hash"
    ) == requirements_hash(project):
        inherited = (confirmed_run.comparison_json or {}).get("decisions", [])
    try:
        decisions = checked_decisions(project, version.id, dataset, inherited)
    except ValueError as exc:
        raise error("project_requirements_required", 409) from exc
    for case in cases:
        expected = case.get("expected", {})
        if not (
            case.get("judgment_basis")
            or expected.get("answer")
            or expected.get("exact_answer") is not None
            or expected.get("state")
            or expected.get("format_rule")
            or expected.get("required_tools")
            or expected.get("attempted_tools")
            or expected.get("forbidden_tools")
            or expected.get("tool_arguments")
            or expected.get("necessary_order")
        ):
            raise error("evaluation_judgment_basis_required", 409)
    rubric = dataset.rubric_json or project.eval_spec_json or {}
    if rubric.get("requirements_hash") and rubric["requirements_hash"] != requirements_hash(
        project
    ):
        raise error("evaluation_requirements_changed", 409)
    plan = frozen_plan(project.eval_spec_json, dataset, version.snapshot_json) or {}
    if (plan.get("eval_spec") or {}).get("rubric_version", 1) >= 2:
        from app.services.agent_project_rubric import validate_applicability, validate_sources
        from app.services.agent_project_semantic import spec_value

        try:
            spec = spec_value(plan["eval_spec"])
            validate_sources(spec, requirements(project))
            for case in cases:
                validate_applicability(spec, case)
        except (ValueError, TypeError) as exc:
            raise error("evaluation_rubric_invalid", 409) from exc
    plan.update(
        requirements=requirements(project),
        requirements_hash=requirements_hash(project),
        decisions=decisions,
        repetitions=body.repetitions,
        trial_policy="all_trials_retained",
        validation_exposure=(
            "used"
            if str(dataset.id) in (project.report_json or {}).get("validation_usage", {})
            else plan.get("validation_exposure")
        ),
    )
    if not plan.get("eval_spec") and any(
        c.get("expected", {}).get("answer") or c.get("judgment_basis") for c in cases
    ):
        raise error("evaluation_semantic_plan_required", 409)
    from app.services.agent_project_llm import (
        check_role_configurations,
        pinned_roles,
        role_configurations,
    )

    try:
        configurations = plan.get("role_configurations") or await role_configurations(db, user_id)
        await check_role_configurations(db, user_id, configurations)
    except Exception as exc:
        raise error("evaluation_role_configuration_changed", 409) from exc
    plan["role_configurations"] = configurations
    plan["resolved_roles"] = pinned_roles(configurations)
    from app.services.agent_project_call_evidence import model_descriptor
    from app.services.agent_project_llm import resolve_model

    try:
        examinee, _ = await resolve_model(db, version.snapshot_json, user_id, "examinee")
    except Exception as exc:
        raise error("snapshot_credential_unavailable", 409) from exc
    plan["resolved_examinee"] = model_descriptor(examinee)
    if rubric.get("rubric_version", 1) >= 3:
        plan["resolved_role_models"] = {}
        for role, selection in [
            ("planner", "evaluation_generator"),
            ("judge", "judge_optimizer"),
            ("optimization_proposal", "builder"),
        ]:
            model, _ = await resolve_model(
                db, {**version.snapshot_json, "role_configurations": configurations}, user_id, role
            )
            plan["resolved_role_models"][selection] = model_descriptor(model)
    dataset.frozen = True
    if rubric.get("rubric_version", 1) >= 3:
        from app.services.agent_project_preflight import preflight_case

        try:
            for case in cases:
                preflight_case(version.snapshot_json["agent"], case)
        except (ValueError, TypeError, KeyError, SnapshotExecutionUnavailable) as exc:
            raise error("evaluation_environment_invalid", 409) from exc
    return await insert_frozen_run(
        db,
        project.id,
        version.id,
        dataset.id,
        body.request_id,
        cases,
        plan,
    )


async def insert_frozen_run(
    db: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    eval_set_id: uuid.UUID,
    request_id: uuid.UUID,
    cases: list[dict[str, Any]],
    plan: dict[str, Any] | None,
) -> AgentProjectEvalRun:
    """Shared insertion boundary; caller owns scope checks and project write lock."""
    row = AgentProjectEvalRun(
        project_id=project_id,
        version_id=version_id,
        eval_set_id=eval_set_id,
        request_id=request_id,
        status="pending",
        cases_snapshot_json=deepcopy(cases),
        dataset_hash=canonical_json_hash(cases),
        metrics_json={"total": len(cases) * (plan or {}).get("repetitions", 1)},
        results_json=[],
        comparison_json=deepcopy(plan),
    )
    db.add(row)
    await db.commit()
    return row


async def expire_runs(db: AsyncSession, project_id: uuid.UUID) -> None:
    # Reconcile on authenticated, CSRF-protected submission, never from a GET.
    # No automatic replay after a process crash: a timed-out lease becomes failed.
    repeats = AgentProjectEvalRun.comparison_json["repetitions"].as_integer()
    judge_limit = AgentProjectEvalRun.comparison_json["execution_protocol"][
        "judge_timeout_seconds"
    ].as_integer()
    single = or_(repeats.is_(None), repeats != 3)
    short = or_(judge_limit.is_(None), judge_limit <= 95)
    # Include both bounded judge attempts; do not expire a valid 60-trial worker early.
    for minutes, condition in [
        (45, and_(short, single)),
        (135, and_(short, repeats == 3)),
        (90, and_(judge_limit > 95, single)),
        (270, and_(judge_limit > 95, repeats == 3)),
    ]:
        await db.execute(
            update(AgentProjectEvalRun)
            .where(
                AgentProjectEvalRun.project_id == project_id,
                AgentProjectEvalRun.status.in_(["pending", "running"]),
                AgentProjectEvalRun.created_at < utcnow() - timedelta(minutes=minutes),
                condition,
            )
            .values(status="failed", error="evaluation_worker_expired", completed_at=utcnow())
        )


async def list_runs(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID
) -> list[AgentProjectEvalRun]:
    project = await projects.require_project(db, agent_id, user_id)
    return list(
        (
            await db.scalars(
                select(AgentProjectEvalRun)
                .where(AgentProjectEvalRun.project_id == project.id)
                .order_by(AgentProjectEvalRun.created_at.desc())
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def get_run(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, run_id: uuid.UUID
) -> AgentProjectEvalRun:
    project = await projects.require_project(db, agent_id, user_id)
    row = await db.scalar(
        select(AgentProjectEvalRun)
        .where(AgentProjectEvalRun.id == run_id, AgentProjectEvalRun.project_id == project.id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise error("agent_project_eval_run_not_found", 404)
    return row


def score_case(
    case: dict[str, Any], evidence: dict[str, Any], *, strict_tools: bool = False
) -> list[dict[str, Any]]:
    expected = case.get("expected") or {}
    names = {call["name"] for call in evidence.get("tool_calls", [])}
    successful = {
        event["name"] for event in evidence.get("tool_trace", []) if not event.get("error")
    }
    checks = [
        {"kind": "execution_succeeded", "passed": True},
        {"kind": "answer_exists", "passed": bool(evidence.get("output", "").strip())},
    ]
    if expected.get("exact_answer") is not None:
        checks.append(
            {"kind": "exact_answer", "passed": evidence.get("output") == expected["exact_answer"]}
        )
    for name in expected.get("attempted_tools", []):
        checks.append({"kind": "attempted_tool", "target": name, "passed": name in names})
    for name in expected.get("required_tools", []):
        checks.append(
            {
                "kind": "required_tool",
                "target": name,
                "passed": name in (successful if strict_tools else names),
            }
        )
    for name in expected.get("forbidden_tools", []):
        checks.append({"kind": "forbidden_tool", "target": name, "passed": name not in names})
    if expected.get("handoff"):
        checks.append(
            {
                "kind": "handoff",
                "target": expected["handoff"],
                "passed": expected["handoff"] in evidence.get("handoffs", [])
                and (not strict_tools or expected["handoff"] in successful),
            }
        )
    trace = evidence.get("tool_trace", [])
    for rule in expected.get("tool_arguments", []):
        checks.append(
            {
                "kind": "tool_arguments",
                "target": rule["name"],
                "passed": any(
                    t["name"] == rule["name"]
                    and not t.get("error")
                    and all(
                        t.get("arguments", {}).get(k) == v
                        for k, v in rule.get("arguments", {}).items()
                    )
                    for t in trace
                ),
            }
        )
    order = expected.get("necessary_order", [])
    if order:
        cursor = 0
        for event in trace:
            if cursor < len(order) and event["name"] == order[cursor] and not event.get("error"):
                cursor += 1
        checks.append({"kind": "necessary_order", "passed": cursor == len(order)})
    for rule in expected.get("state", []):
        value = evidence.get("final_state", {})
        try:
            for part in rule["path"].split("."):
                value = value[int(part)] if isinstance(value, list) else value[part]
            passed = value == rule["value"]
        except (KeyError, IndexError, ValueError, TypeError):
            passed = False
        checks.append({"kind": "final_state", "target": rule["path"], "passed": passed})
    from app.services.agent_project_semantic import format_check

    if expected.get("format_rule"):
        checks.append(
            {"kind": "format_compliance", "passed": format_check(case, evidence.get("output", ""))}
        )
    if expected.get("max_characters") is not None:
        checks.append(
            {
                "kind": "character_limit",
                "target": str(expected["max_characters"]),
                "passed": len(evidence.get("output", "")) <= expected["max_characters"],
            }
        )
    if expected.get("max_tool_calls") is not None:
        checks.append(
            {"kind": "tool_call_limit", "passed": len(trace) <= expected["max_tool_calls"]}
        )
    return checks


async def execute_run(run_id: uuid.UUID, agent_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with async_session() as db:
        project = await projects.require_project(db, agent_id, user_id)
        claimed = await db.execute(
            update(AgentProjectEvalRun)
            .where(
                AgentProjectEvalRun.id == run_id,
                AgentProjectEvalRun.project_id == project.id,
                AgentProjectEvalRun.status == "pending",
            )
            .values(status="running", started_at=utcnow())
            .returning(AgentProjectEvalRun.id)
        )
        if claimed.scalar_one_or_none() is None:
            await db.rollback()
            return
        await db.commit()
        row = await db.get(AgentProjectEvalRun, run_id)
        if row is None:
            return
        from app.services.agent_project_semantic import grade_case, metric_summary

        plan = deepcopy(row.comparison_json)
        results: list[dict[str, Any]] = []
        try:
            version = await projects.get_version(db, agent_id, user_id, row.version_id)
            if canonical_json_hash(version.snapshot_json) != version.config_hash:
                raise SnapshotExecutionUnavailable("snapshot_hash_mismatch")
            snapshot = deepcopy(version.snapshot_json)
            if plan:
                snapshot["evaluation_roles"] = plan.get("resolved_roles", {})
                snapshot["role_configurations"] = plan.get("role_configurations")
                snapshot["resolved_examinee"] = plan.get("resolved_examinee")
                snapshot["resolved_role_models"] = plan.get("resolved_role_models")
            cases = deepcopy(row.cases_snapshot_json or [])
            if not cases:
                raise SnapshotExecutionUnavailable("evaluation_dataset_invalid")
            repetitions = (plan or {}).get("repetitions", 1)
            trials = [(trial, case) for trial in range(1, repetitions + 1) for case in cases]
            for trial, case in trials:
                start = perf_counter()
                result = {
                    "case_id": case["id"],
                    "name": case["name"],
                    "input": case["input"],
                    "expected": case.get("expected"),
                    "output": "",
                    "tool_calls": [],
                    "assertions": [],
                    "error": None,
                    "execution_status": "failed",
                    "metric_scores": {},
                    "judge_reasons": {},
                    "trial": trial,
                }
                judgments: list[dict[str, Any]] = []
                try:
                    from app.services.agent_project_llm import capture_calls

                    partial: list[dict[str, Any]] = []
                    with capture_calls(partial):
                        async with asyncio.timeout(
                            (row.comparison_json or {})
                            .get("execution_protocol", {})
                            .get("execution_timeout_seconds", 30)
                        ):
                            evidence = await execute_snapshot(db, snapshot, case, user_id)
                    checks = score_case(
                        case,
                        evidence,
                        strict_tools=(plan or {}).get("eval_spec", {}).get("rubric_version", 1)
                        >= 2,
                    )
                    result.update(
                        evidence,
                        execution_status="completed",
                        assertions=checks,
                        status="passed" if all(c["passed"] for c in checks) else "failed",
                    )
                    if plan and plan.get("eval_spec"):
                        with capture_calls(judgments):
                            async with asyncio.timeout(
                                (row.comparison_json or {})
                                .get("execution_protocol", {})
                                .get("judge_timeout_seconds", 95)
                            ):
                                result.update(
                                    await grade_case(
                                        db, snapshot, user_id, case, evidence, checks, plan
                                    )
                                )
                except SnapshotExecutionUnavailable as exc:
                    from app.services.agent_project_preflight import ENVIRONMENT_ERRORS

                    result.update(exc.evidence)
                    result.update(
                        status="errored",
                        error=str(exc),
                        error_phase="environment"
                        if str(exc) in ENVIRONMENT_ERRORS
                        else "judge"
                        if result["execution_status"] == "completed"
                        else "execution",
                    )
                except TimeoutError:
                    if judgments:
                        result["judge_calls"] = judgments
                    for item in partial:
                        result.update(item.get("partial_execution", {}))
                    result.update(
                        status="errored",
                        error="evaluation_timeout",
                        error_phase="judge"
                        if result["execution_status"] == "completed"
                        else "execution",
                    )
                except Exception:
                    # Provider exceptions may contain secrets; never persist or log them.
                    result.update(
                        status="errored",
                        error="evaluation_execution_failed",
                        error_phase="judge"
                        if result["execution_status"] == "completed"
                        else "execution",
                    )
                result.update(
                    passed=result["status"] == "passed",
                    actual_output=result["output"],
                    called_tools=result["tool_calls"],
                    deterministic_assertions=result["assertions"],
                    error_code=result["error"],
                )
                result["latency_ms"] = round((perf_counter() - start) * 1000)
                results.append(projects.snapshot_value(result))
                row.results_json = list(results)
                await db.commit()
            passed = sum(result["status"] == "passed" for result in results)
            errored = sum(result["status"] == "errored" for result in results)
            row.metrics_json = {
                "total": len(trials),
                "passed": passed,
                "failed": len(results) - passed - errored,
                "errored": errored,
                "pass_rate": passed / len(results),
                "execution_errors": sum(r.get("error_phase") == "execution" for r in results),
                "environment_errors": sum(r.get("error_phase") == "environment" for r in results),
                "judge_errors": sum(r.get("error_phase") == "judge" for r in results),
                "executed_cases": sum(r.get("execution_status") == "completed" for r in results),
                "executed_pass_rate": passed
                / sum(r.get("execution_status") == "completed" for r in results)
                if any(r.get("execution_status") == "completed" for r in results)
                else None,
                "scored_pass_rate": passed / (len(results) - errored)
                if len(results) > errored
                else None,
                "complete": len(results) == len(trials),
                "scoring": "semantic_v1" if plan else "structural_v1",
                "metric_scores": metric_summary(results),
                "rubric_version": (plan or {}).get("eval_spec", {}).get("rubric_version", 1),
                **outcome_statistics(cases, results, repetitions),
            }
            row.pass_rate = passed / len(results)
            row.status = "failed" if errored else "completed"
            row.error = "evaluation_case_errors" if errored else None
        except (Exception, asyncio.CancelledError):
            await db.rollback()
            row = await db.get(AgentProjectEvalRun, run_id)
            if row is None:
                return
            row.status, row.error = "failed", "evaluation_execution_failed"
        row.completed_at = utcnow()
        await db.commit()


async def compare_versions(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    left_id: uuid.UUID,
    right_id: uuid.UUID,
) -> dict[str, Any]:
    left = await projects.get_version(db, agent_id, user_id, left_id)
    right = await projects.get_version(db, agent_id, user_id, right_id)
    a, b = left.snapshot_json["agent"], right.snapshot_json["agent"]
    changes = []
    fields = (
        "name",
        "description",
        "system_prompt",
        "identity_mode",
        "model",
        "model_params",
        "llm_credential_id",
        "model_fallback_list",
        "fallback_models",
        "tool_links",
        "skill_links",
        "mcp_tool_links",
        "middleware_configs",
        "runtime_policy",
        "opener_questions",
        "sub_agent_links",
    )
    identities = {
        "tool_links": "tool_id",
        "skill_links": "skill_id",
        "mcp_tool_links": "mcp_tool_id",
        "sub_agent_links": "sub_agent_id",
    }
    for field in fields:
        if a.get(field) == b.get(field):
            continue
        change: dict[str, Any] = {"field": field, "before": a.get(field), "after": b.get(field)}
        if field in identities:
            key = identities[field]
            before, after = ({item[key]: item for item in value.get(field, [])} for value in (a, b))
            change.update(
                added=sorted(after.keys() - before.keys()),
                removed=sorted(before.keys() - after.keys()),
                changed=sorted(
                    key for key in before.keys() & after.keys() if before[key] != after[key]
                ),
            )
        changes.append(change)
    summaries = []
    from app.services.agent_project_report import report_for_run

    for version in (left, right):
        run = await db.scalar(
            select(AgentProjectEvalRun)
            .where(
                AgentProjectEvalRun.project_id == version.project_id,
                AgentProjectEvalRun.version_id == version.id,
                AgentProjectEvalRun.status == "completed",
            )
            .order_by(AgentProjectEvalRun.created_at.desc())
            .limit(1)
        )
        summaries.append(
            {
                "run_id": str(run.id),
                "dataset_hash": run.dataset_hash,
                "metrics": run.metrics_json,
                "eval_set_id": str(run.eval_set_id),
                "score": report_for_run(run).score,
                "comparison_key": report_for_run(run).comparison_key,
            }
            if run
            else None
        )
    return {
        "left_version_id": str(left.id),
        "right_version_id": str(right.id),
        "changes": changes,
        "evaluations": summaries,
        "same_dataset": bool(
            summaries[0]
            and summaries[1]
            and summaries[0]["dataset_hash"] == summaries[1]["dataset_hash"]
            and summaries[0]["eval_set_id"] == summaries[1]["eval_set_id"]
        ),
        "comparable": bool(
            summaries[0]
            and summaries[1]
            and summaries[0]["score"] is not None
            and summaries[1]["score"] is not None
            and summaries[0]["comparison_key"]
            and summaries[0]["comparison_key"] == summaries[1]["comparison_key"]
        ),
    }


def outcome_statistics(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], repetitions: int
) -> dict[str, Any]:
    by_case = {c["id"]: c for c in cases}
    valid = [r for r in results if r.get("status") in {"passed", "failed"}]
    facts = [r["fact_check"] for r in valid if r.get("fact_check")]
    operations = [r for r in results if (by_case[r["case_id"]].get("expected") or {}).get("state")]
    recoveries = [r for r in results if by_case[r["case_id"]].get("recovery_goal")]
    critical = [
        r
        for r in valid
        if any(v.get("critical_failure") for v in r.get("metric_scores", {}).values())
        or (
            (r.get("fact_check") or {}).get("unsupported", 0) > 0
            and r.get("metric_scores", {}).get("groundedness", {}).get("critical_applicable")
        )
    ]
    trial_rates = [
        sum(r["status"] == "passed" for r in results if r.get("trial", 1) == trial) / len(cases)
        for trial in range(1, repetitions + 1)
    ]
    calls = [
        call
        for result in results
        for field in ("model_calls", "judge_calls")
        for call in result.get(field, [])
    ]
    usage = [
        value
        for call in calls
        for value in (
            [call.get("accounting")] + [r.get("accounting") for r in call.get("returns", [])]
        )
        if isinstance(value, dict)
    ]
    return {
        "model_accounting": {
            "model_invocations": len(calls),
            "usage_covered_invocations": sum(
                bool(c.get("accounting")) or any(r.get("accounting") for r in c.get("returns", []))
                for c in calls
            ),
            "input_count": sum(u.get("input_count", 0) for u in usage) if usage else None,
            "output_count": sum(u.get("output_count", 0) for u in usage) if usage else None,
            "total_count": sum(u.get("total_count", 0) for u in usage) if usage else None,
            "cost": None,
            "cost_reason": "provider_prices_not_configured",
        },
        "case_count": len(cases),
        "repetitions": repetitions,
        "stability": "unverified_single_trial" if repetitions == 1 else "observed_repeated_trials",
        "trial_pass_rates": trial_rates,
        "trial_range": max(trial_rates) - min(trial_rates),
        "fact_support": {
            "supported": sum(f["supported"] for f in facts),
            "unsupported": sum(f["unsupported"] for f in facts),
            "unknown": sum(f["unknown"] for f in facts),
            "total": sum(f["total"] for f in facts),
            "covered_cases": len(facts),
            "aggregation": "claim_counts",
        }
        if facts
        else None,
        "operation_success": {
            "successful": sum(
                all(c["passed"] for c in r.get("assertions", []) if c["kind"] == "final_state")
                and any(c["kind"] == "final_state" for c in r.get("assertions", []))
                and r.get("execution_status") == "completed"
                for r in operations
            ),
            "total": len(operations),
        },
        "recovery_success": {
            "successful": sum(r["status"] == "passed" for r in recoveries),
            "total": len(recoveries),
        },
        "critical_violations": {
            "violating": len(critical),
            "total": sum(
                any(v.get("critical_applicable") for v in r.get("metric_scores", {}).values())
                for r in valid
            ),
        },
    }


async def use_validation_for_optimization(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    reason: str,
) -> AgentProjectEvalRun:
    run = await get_run(db, agent_id, user_id, run_id)
    if (run.comparison_json or {}).get("purpose") != "validation":
        raise error("validation_run_required", 409)
    if run.status not in {"completed", "failed"}:
        raise error("optimization_run_incomplete", 409)
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(project, ["report_json"])
    uses = dict((project.report_json or {}).get("validation_usage", {}))
    key = str(run.eval_set_id)
    if key not in uses:
        safe_reason = projects.snapshot_value(reason.strip())
        if not safe_reason or safe_reason != reason.strip():
            raise error("validation_reason_invalid", 422)
        uses[key] = {
            "source_run_id": str(run_id),
            "reason": safe_reason,
            "author": "user_confirmed",
            "exposure": "used",
        }
        project.report_json = {**(project.report_json or {}), "validation_usage": uses}
        rows = (
            await db.scalars(
                select(AgentProjectEvalRun).where(
                    AgentProjectEvalRun.project_id == project.id,
                    AgentProjectEvalRun.eval_set_id == run.eval_set_id,
                )
            )
        ).all()
        for row in rows:
            row.comparison_json = {**(row.comparison_json or {}), "validation_exposure": "used"}
    await db.commit()
    return run
