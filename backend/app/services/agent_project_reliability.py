"""Reserved validation cases, pinned repeated trials, and human/Judge agreement.

No claim of statistical independence or production readiness is made. A validation
set cannot feed the optimizer; its creation never receives candidate failures.
"""

from __future__ import annotations

import unicodedata
import uuid
from copy import deepcopy
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProjectEvalRun, AgentProjectEvalSet
from app.schemas.agent_project import EvalSetWrite, EvaluationCase
from app.schemas.agent_project_learning import HoldoutGenerate, RepeatRequest, ValidationRequest
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_service as projects
from app.services.agent_project_learning import fail
from app.services.agent_project_llm import json_call
from app.services.agent_project_report import report_for_run


def input_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


async def generate_holdout(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: HoldoutGenerate
) -> AgentProjectEvalSet:
    project = await projects.require_project(db, agent_id, user_id)
    development = await evaluation.get_set(db, project.id, body.development_set_id)
    rubric = deepcopy(development.rubric_json or {})
    if rubric.get("purpose") == "holdout" or not rubric.get("version_id") or not development.frozen:
        raise fail("reliability_development_required")
    set_id = uuid.uuid5(project.id, f"holdout:{body.request_id}")
    existing = await db.get(AgentProjectEvalSet, set_id)
    if existing:
        if (existing.rubric_json or {}).get("development_set_id") != str(development.id):
            raise fail("evaluation_request_conflict")
        return existing
    version = await projects.get_version(db, agent_id, user_id, uuid.UUID(rubric["version_id"]))
    # Read the ORIGINAL business requirements/rubric, not optimized candidate snapshots,
    # failure analyses, proposed patches or prior validation results.
    raw = await json_call(
        db,
        version.snapshot_json,
        user_id,
        "case_generator",
        "Generate exactly 20 NEW synthetic reserved validation cases from the original "
        "business contract and rubric. Do not tailor tests to any Agent answers or fixes. "
        "Use original enabled tool schemas with mock data only. Cover normal, edge, failure "
        "and the rubric capabilities. Excluded inputs are for deduplication ONLY; do not "
        "paraphrase them. Include verifiable expected.answer, tool assertions where needed, "
        "enabled=true and fresh UUID ids. No production calls. Return supplied schema.",
        {
            "business_contract": rubric.get("business_contract"),
            "rubric": rubric,
            "original_tool_schema": version.snapshot_json["agent"],
            "excluded_inputs": [c["input"] for c in development.cases_json],
            "schema": EvalSetWrite.model_json_schema(),
        },
    )
    try:
        data = EvalSetWrite.model_validate(raw)
    except ValueError as exc:
        raise fail("reliability_holdout_invalid") from exc
    if len(data.cases) != 20 or any(not c.enabled or not c.expected.answer for c in data.cases):
        raise fail("reliability_holdout_invalid")
    from app.services.agent_project_mock_tools import mock_tools

    await projects.lock_project(db, project)
    sets = list(
        (
            await db.scalars(
                select(AgentProjectEvalSet).where(AgentProjectEvalSet.project_id == project.id)
            )
        ).all()
    )
    excluded = {input_key(c["input"]) for s in sets for c in s.cases_json}
    keys = [input_key(c.input) for c in data.cases]
    if len(set(keys)) != 20 or set(keys) & excluded:
        raise fail("reliability_holdout_overlap")
    old_ids = {c["id"] for s in sets for c in s.cases_json}
    if len({c.id for c in data.cases}) != 20 or any(str(c.id) in old_ids for c in data.cases):
        raise fail("reliability_holdout_overlap")
    from app.services.agent_project_executor import SnapshotExecutionUnavailable

    try:
        for case in data.cases:
            mock_tools(version.snapshot_json["agent"], case.model_dump(mode="json"))
    except (SnapshotExecutionUnavailable, ValueError) as exc:
        raise fail("reliability_holdout_invalid") from exc
    dataset = await evaluation.write_set(
        db,
        agent_id,
        user_id,
        data,
        new_id=set_id,
        rubric={
            **rubric,
            "purpose": "holdout",
            "development_set_id": str(development.id),
            "source_version_id": str(version.id),
            "generation_policy": "baseline_contract_only",
        },
    )
    saved_cases_hash = canonical_json_hash(dataset.cases_json)
    dataset = await evaluation.judge_set(db, agent_id, user_id, dataset.id)
    # Cases are reserved and immutable even before first execution. A rejected set
    # must be regenerated with a NEW request, never adjusted to Agent performance.
    await projects.lock_project(db, project)
    await db.refresh(dataset)
    if canonical_json_hash(dataset.cases_json) != saved_cases_hash:
        raise fail("learning_evidence_changed")
    dataset.frozen = True
    await db.commit()
    return dataset


def trial_plan(source: AgentProjectEvalRun, metadata: dict[str, Any]) -> dict[str, Any]:
    value = {
        k: deepcopy((source.comparison_json or {})[k])
        for k in ("eval_spec", "spec_hash", "rubric_hash", "roles", "execution_mode", "purpose")
        if k in (source.comparison_json or {})
    }
    value["reliability"] = metadata
    return value


async def create_trials(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    source: AgentProjectEvalRun,
    versions: list[uuid.UUID],
    body: RepeatRequest,
    kind: str,
) -> list[AgentProjectEvalRun]:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(source)
    if (
        not source.cases_snapshot_json
        or canonical_json_hash(source.cases_snapshot_json) != source.dataset_hash
    ):
        raise fail("optimization_run_incomplete")
    existing_groups = list(
        (
            await db.scalars(
                select(AgentProjectEvalRun).where(AgentProjectEvalRun.project_id == project.id)
            )
        ).all()
    )
    for prior in existing_groups:
        meta = (prior.comparison_json or {}).get("reliability", {})
        if meta.get("group_id") == str(body.request_id) and (
            meta.get("source_run_id") != str(source.id)
            or meta.get("kind") != kind
            or meta.get("repetitions") != body.repetitions
            or prior.version_id not in versions
        ):
            raise fail("evaluation_request_conflict")
    rows = []
    for version_id in versions:
        version = await projects.get_version(db, agent_id, user_id, version_id)
        if canonical_json_hash(version.snapshot_json) != version.config_hash:
            raise fail("snapshot_hash_mismatch")
        for index in range(body.repetitions):
            request_id = (
                uuid.uuid5(body.request_id, "validation-anchor")
                if kind == "validation" and version_id == source.version_id and index == 0
                else uuid.uuid5(body.request_id, f"{kind}:{version_id}:{index}")
            )
            row = await db.scalar(
                select(AgentProjectEvalRun).where(
                    AgentProjectEvalRun.project_id == project.id,
                    AgentProjectEvalRun.request_id == request_id,
                )
            )
            metadata = {
                "group_id": str(body.request_id),
                "kind": kind,
                "repetitions": body.repetitions,
                "index": index,
                "source_run_id": str(source.id),
            }
            if row:
                saved = (row.comparison_json or {}).get("reliability")
                if saved is None and row.id == source.id and kind == "validation":
                    row.comparison_json = trial_plan(source, metadata)
                elif saved != metadata or row.eval_set_id != source.eval_set_id:
                    raise fail("evaluation_request_conflict")
            else:
                row = AgentProjectEvalRun(
                    project_id=project.id,
                    version_id=version_id,
                    eval_set_id=source.eval_set_id,
                    request_id=request_id,
                    status="pending",
                    cases_snapshot_json=deepcopy(source.cases_snapshot_json),
                    dataset_hash=source.dataset_hash,
                    metrics_json={"total": len(source.cases_snapshot_json)},
                    results_json=[],
                    comparison_json=trial_plan(source, metadata),
                )
                db.add(row)
            from app.services.agent_project_semantic import model_roles

            plan = deepcopy(row.comparison_json or {})
            if plan.get("roles"):
                plan["roles"]["examinee"] = model_roles(version.snapshot_json)["examinee"]
                row.comparison_json = plan
            rows.append(row)
    await db.commit()  # All trials committed together; worker handles restart/cancellation.
    return rows


async def repeat(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    body: RepeatRequest,
) -> list[AgentProjectEvalRun]:
    source = await evaluation.get_run(db, agent_id, user_id, run_id)
    if source.status not in {"completed", "failed"}:
        raise fail("reliability_terminal_required")
    return await create_trials(db, agent_id, user_id, source, [source.version_id], body, "repeat")


async def validate(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: ValidationRequest
) -> list[AgentProjectEvalRun]:
    project = await projects.require_project(db, agent_id, user_id)
    baseline = await evaluation.get_run(db, agent_id, user_id, body.baseline_run_id)
    dataset = await evaluation.get_set(db, project.id, body.holdout_set_id)
    rubric = dataset.rubric_json or {}
    if (
        rubric.get("purpose") != "holdout"
        or not dataset.frozen
        or rubric.get("source_version_id") != str(baseline.version_id)
        or rubric.get("development_set_id") != str(baseline.eval_set_id)
        or body.candidate_version_id == baseline.version_id
    ):
        raise fail("reliability_holdout_mismatch")
    await projects.get_version(db, agent_id, user_id, body.candidate_version_id)
    # One anchor pins the judge for BOTH versions and all repetitions; replay
    # recovers the exact anchor after a lost response instead of repinning.
    await projects.lock_project(db, project)
    anchor_request = uuid.uuid5(body.request_id, "validation-anchor")
    anchor = await db.scalar(
        select(AgentProjectEvalRun).where(
            AgentProjectEvalRun.project_id == project.id,
            AgentProjectEvalRun.request_id == anchor_request,
        )
    )
    if anchor is not None:
        if anchor.version_id != baseline.version_id or anchor.eval_set_id != dataset.id:
            raise fail("evaluation_request_conflict")
    else:
        if (dataset.quality_report_json or {}).get("status") != "approved":
            raise fail("agent_project_eval_set_quality_required")
        from app.services.agent_project_executor import SnapshotExecutionUnavailable
        from app.services.agent_project_model_pins import pin_judge
        from app.services.agent_project_semantic import frozen_plan

        version = await projects.get_version(db, agent_id, user_id, baseline.version_id)
        cases = [
            projects.snapshot_value(
                EvaluationCase.model_validate(
                    {k: v for k, v in c.items() if k in EvaluationCase.model_fields}
                ).model_dump(mode="json")
            )
            for c in dataset.cases_json
            if c.get("enabled", True)
        ]
        if len(cases) != 20:
            raise fail("formal_evaluation_requires_20_cases")
        plan = frozen_plan(None, dataset, version.snapshot_json)
        if plan is None:
            raise fail("evaluation_plan_required")
        try:
            plan["roles"]["judge"] = await pin_judge(db, user_id)
        except SnapshotExecutionUnavailable as exc:
            raise fail(str(exc)) from exc
        anchor = AgentProjectEvalRun(
            project_id=project.id,
            version_id=baseline.version_id,
            eval_set_id=dataset.id,
            request_id=anchor_request,
            status="pending",
            cases_snapshot_json=cases,
            dataset_hash=canonical_json_hash(cases),
            results_json=[],
            metrics_json={"total": len(cases)},
            comparison_json=plan,
        )
        db.add(anchor)
        await db.flush()  # No worker can see this anchor until the whole batch commits.
    return await create_trials(
        db,
        agent_id,
        user_id,
        anchor,
        [baseline.version_id, body.candidate_version_id],
        body,
        "validation",
    )


def summarize_runs(runs: list[AgentProjectEvalRun]) -> dict[str, Any]:
    reports = [report_for_run(r) for r in runs]
    reports = [r for r in reports if r.score is not None]
    scores = [r.score for r in reports if r.score is not None]
    comparable = len({r.comparison_key for r in reports}) == 1 and all(
        r.comparison_key for r in reports
    )
    # Do not pool cases as independent samples. Show run-level descriptive spread.
    return {
        "scheduled": len(runs),
        "completed": len(scores),
        "incomplete": len(runs) - len(scores),
        "comparable": bool(comparable),
        "mean": mean(scores) if scores and comparable else None,
        "min": min(scores) if scores and comparable else None,
        "max": max(scores) if scores and comparable else None,
        "stddev": pstdev(scores) if len(scores) > 1 and comparable else None,
        "run_ids": [str(r.id) for r in runs],
    }


async def summary(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, version_id: uuid.UUID
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.get_version(db, agent_id, user_id, version_id)
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
    return summarize_project_runs(runs, version_id)


def summarize_project_runs(
    runs: list[AgentProjectEvalRun], version_id: uuid.UUID
) -> dict[str, Any]:
    groups: dict[str, list[AgentProjectEvalRun]] = {}
    for run in runs:
        meta = (run.comparison_json or {}).get("reliability")
        if meta:
            groups.setdefault(meta["group_id"], []).append(run)
    trials = []
    for group_id, rows in groups.items():
        if not any(r.version_id == version_id for r in rows):
            continue
        by_version = {
            str(v): summarize_runs([r for r in rows if r.version_id == v])
            for v in dict.fromkeys(r.version_id for r in rows)
        }
        meta = (rows[0].comparison_json or {})["reliability"]
        trials.append({"group_id": group_id, "kind": meta["kind"], "versions": by_version})
    reviews = []
    for run in runs:
        if run.version_id != version_id:
            continue
        for case_id, review in (run.comparison_json or {}).get("case_reviews", {}).items():
            result = next((r for r in run.results_json or [] if r["case_id"] == case_id), None)
            if result and result["status"] in {"passed", "failed"}:
                reviews.append(
                    {
                        "run_id": str(run.id),
                        "case_id": case_id,
                        "judge_passed": result["status"] == "passed",
                        "human_passed": review["passed"],
                        "reason": review["reason"],
                        "agreed": review["passed"] == (result["status"] == "passed"),
                    }
                )
    return {
        "trials": trials,
        "calibration": {
            "reviewed": len(reviews),
            "disagreements": sum(not r["agreed"] for r in reviews),
            "agreement_rate": sum(r["agreed"] for r in reviews) / len(reviews) if reviews else None,
            "reviews": reviews,
        },
        "limitations": [
            "synthetic_cases",
            "mock_tools",
            "run_level_spread_only",
            "no_production_verification",
            "human_labels_do_not_overwrite_judge",
        ],
    }
