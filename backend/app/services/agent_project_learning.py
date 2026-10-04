"""Private, evidence-linked student aids; authored judgments remain distinguishable."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProjectEvalRun, utcnow
from app.schemas.agent_project_learning import (
    BriefConfirm,
    BriefContent,
    BriefGenerate,
    CaseReview,
    InterviewDraft,
)
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_service as projects
from app.services.agent_project_llm import json_call
from app.services.agent_project_report import report_for_run


def fail(code: str) -> AppError:
    return AppError(code=code, message=code, status=409)


async def generate_brief(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: BriefGenerate
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    version = await projects.get_version(db, agent_id, user_id, body.version_id)
    raw = await json_call(
        db,
        version.snapshot_json,
        user_id,
        "planner",
        "Draft a project brief for a non-programming college student. Use requested locale. "
        "Describe audience, problem, workflow and 2-6 verifiable BUSINESS success criteria "
        "independently of the current implementation, including missing requirements. "
        "Tools are simulated. Do not invent users, deployment or business results.",
        {
            "locale": body.locale,
            "snapshot": version.snapshot_json,
            "requirements": project.requirements_json,
            "schema": BriefContent.model_json_schema(),
        },
    )
    content = projects.snapshot_value(BriefContent.model_validate(raw).model_dump(mode="json"))
    value = {
        "version_id": str(version.id),
        "config_hash": version.config_hash,
        "locale": body.locale,
        "content": content,
        "draft_hash": canonical_json_hash(content),
        "status": "draft",
        "created_at": utcnow().isoformat(),
    }
    await projects.lock_project(db, project)
    await db.refresh(project, ["requirements_json"])
    project.requirements_json = {**(project.requirements_json or {}), "brief_draft": value}
    await db.commit()
    return value


async def confirm_brief(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: BriefConfirm
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(project, ["requirements_json"])
    version = await projects.get_version(db, agent_id, user_id, body.version_id)
    draft = (project.requirements_json or {}).get("brief_draft") or {}
    if (
        draft.get("draft_hash") != body.draft_hash
        or draft.get("version_id") != str(version.id)
        or draft.get("config_hash") != version.config_hash
    ):
        raise fail("learning_draft_changed")
    content = projects.snapshot_value(body.content.model_dump(mode="json"))
    value = {
        **draft,
        "content": content,
        "content_hash": canonical_json_hash(content),
        "status": "confirmed",
        "confirmed_at": utcnow().isoformat(),
        "contribution": "user_edited" if content != draft["content"] else "user_confirmed",
    }
    old = (project.requirements_json or {}).get("learning_brief", {}).get("content")
    if content != old:
        project.eval_spec_json = None
    history = list((project.requirements_json or {}).get("brief_history", []))
    if not history or history[-1]["content"] != content:
        history.append(value)
    project.requirements_json = {
        **(project.requirements_json or {}),
        "learning_brief": value,
        "brief_history": history,
        "goal": content["problem"],
    }
    await db.commit()
    return value


async def review_case(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    case_id: uuid.UUID,
    body: CaseReview,
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    result = next((r for r in run.results_json or [] if r["case_id"] == str(case_id)), None)
    if not result or result["status"] not in {"passed", "failed"}:
        raise fail("learning_case_unavailable")
    await projects.lock_project(db, project)
    await db.refresh(run, ["comparison_json"])
    reviews = deepcopy((run.comparison_json or {}).get("case_reviews", {}))
    value = projects.snapshot_value(
        {**body.model_dump(), "source": "user_authored", "confirmed_at": utcnow().isoformat()}
    )
    reviews[str(case_id)] = value
    run.comparison_json = {**(run.comparison_json or {}), "case_reviews": reviews}
    await db.commit()
    return value


async def learning_evidence(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, version_id: uuid.UUID
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    version = await projects.get_version(db, agent_id, user_id, version_id)
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
    records: dict[str, Any] = {
        "project": {
            "name": project.title,
            "version": version.version_number,
            "brief": (project.requirements_json or {}).get("learning_brief"),
        },
        "boundaries": {
            "environment": "mock_sandbox",
            "production_verified": False,
            "platform": "Platform builds Agent, generates tests, executes and grades. "
            "AI drafts are not user-authored contributions.",
        },
    }
    selected = [
        r for r in runs if r.version_id == version.id and r.status in {"completed", "failed"}
    ]
    # Keep actual evidence from selected version and its regression source.
    source_ids = {
        (r.comparison_json or {}).get("regression", {}).get("source_run_id") for r in selected
    }
    selected += [r for r in runs if str(r.id) in source_ids]
    for run in selected:
        report = report_for_run(run)
        records[f"run:{run.id}"] = report.model_dump(mode="json")
        for result in run.results_json or []:
            records[f"case:{run.id}:{result['case_id']}"] = {
                **result,
                "analysis": next(
                    (b for b in run.bad_cases_json or [] if b.get("case_id") == result["case_id"]),
                    None,
                ),
                "user_review": (run.comparison_json or {})
                .get("case_reviews", {})
                .get(result["case_id"]),
            }
    for run in runs:
        for proposal in (run.comparison_json or {}).get("proposals", []):
            if proposal.get("version_id") == str(version.id) or run.version_id == version.id:
                records[f"proposal:{proposal['id']}"] = proposal
    from app.services.agent_project_reliability import summary

    records["reliability"] = await summary(db, agent_id, user_id, version_id)
    return projects.snapshot_value(records)


async def interview(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: BriefGenerate
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    records = await learning_evidence(db, agent_id, user_id, body.version_id)
    evidence_hash = canonical_json_hash(records)
    key = f"{body.version_id}:{body.locale}"
    stored = (project.report_json or {}).get("learning_interviews", {}).get(key)
    if stored and stored.get("evidence_hash") == evidence_hash:
        return stored
    version = await projects.get_version(db, agent_id, user_id, body.version_id)
    raw = await json_call(
        db,
        version.snapshot_json,
        user_id,
        "planner",
        "Write interview reference answers for a college student in requested locale. "
        "Use ONLY supplied records. Distinguish platform implementation, AI drafts, "
        "user confirmation and authored edits. Never say student wrote platform code. "
        "Cover five topics exactly once: contribution, failure, decision, results, next_step. "
        "Link each answer to existing evidence_refs. Explain unfamiliar terms in simple words. "
        "Absent evidence: say not verified. Hypotheses are not proven causes. "
        "Only compare runs with identical nonnull comparison_key; repeated runs are not "
        "independent cases; holdout results do not prove production capability. "
        "Do not invent numbers, deployment, real users or business impact. Provide 30-second "
        "and 2-minute introductions with the same boundaries and evidence.",
        {"locale": body.locale, "records": records, "schema": InterviewDraft.model_json_schema()},
    )
    draft = InterviewDraft.model_validate(raw)
    if len({a.topic for a in draft.answers}) != 5 or any(
        ref not in records for answer in draft.answers for ref in answer.evidence_refs
    ):
        raise fail("learning_interview_invalid_evidence")
    await projects.lock_project(db, project)
    await db.refresh(project, ["report_json", "requirements_json"])
    if (
        canonical_json_hash(await learning_evidence(db, agent_id, user_id, body.version_id))
        != evidence_hash
    ):
        raise fail("learning_evidence_changed")
    value = {
        "status": "ai_draft",
        "version_id": str(body.version_id),
        "evidence_hash": evidence_hash,
        "draft": projects.snapshot_value(draft.model_dump(mode="json")),
        "evidence": records,
    }
    cache = {**(project.report_json or {}).get("learning_interviews", {}), key: value}
    project.report_json = {**(project.report_json or {}), "learning_interviews": cache}
    await db.commit()
    return value
