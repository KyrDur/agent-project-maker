"""Human-reviewed optimization, stored alongside its source evaluation evidence."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProjectEvalRun, utcnow
from app.schemas.agent_project_optimization import (
    OptimizationDraft,
    OptimizationProposalSet,
    PatchProposal,
)
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_optimization as optimization
from app.services import agent_project_service as projects
from app.services.agent_project_llm import json_call
from app.services.agent_project_optimization_rules import apply_patches
from app.services.agent_project_semantic import capability_profile


def proposals(run: AgentProjectEvalRun) -> list[dict[str, Any]]:
    return deepcopy((run.comparison_json or {}).get("proposals", []))


def find(run: AgentProjectEvalRun, proposal_id: uuid.UUID) -> dict[str, Any]:
    for item in proposals(run):
        if item["id"] == str(proposal_id):
            return item
    raise optimization.fail("optimization_proposal_not_found", 404)


def save(run: AgentProjectEvalRun, proposal: dict[str, Any]) -> None:
    items = proposals(run)
    index = next((i for i, item in enumerate(items) if item["id"] == proposal["id"]), None)
    if index is None:
        items.append(deepcopy(proposal))
    else:
        items[index] = deepcopy(proposal)
    run.comparison_json = {**(run.comparison_json or {}), "proposals": items}


def save_many(run: AgentProjectEvalRun, values: list[dict[str, Any]]) -> None:
    items = proposals(run)
    by_id = {item["id"]: item for item in items}
    for value in values:
        by_id[value["id"]] = deepcopy(value)
    ordered = list(by_id.values())
    ordered.sort(key=lambda item: (item.get("created_at") or "", item.get("id") or ""))
    run.comparison_json = {**(run.comparison_json or {}), "proposals": ordered}


def draft_list(raw: dict[str, Any]) -> list[OptimizationDraft]:
    if not isinstance(raw, dict):
        raise ValueError("optimization_proposal_set_invalid")
    return OptimizationProposalSet.model_validate(raw).proposals


def proposal_value(
    *,
    proposal_id: uuid.UUID,
    request_id: uuid.UUID,
    parent_id: uuid.UUID,
    run: AgentProjectEvalRun,
    parent_hash: str,
    profile: dict[str, Any],
    draft: OptimizationDraft,
    groups: list[dict[str, Any]],
    diffs: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_cases = [str(item) for item in draft.targeted_case_ids]
    if not selected_cases:
        selected_cases = sorted(
            {
                str(case_id)
                for change in draft.changes
                for group in groups
                if group.get("case_ids") and group.get("target") == change.target
                for case_id in group.get("case_ids", [])
            }
        )
    if not selected_cases:
        selected_cases = sorted({str(case_id) for group in groups for case_id in group["case_ids"]})
    return projects.snapshot_value(
        {
            "id": str(proposal_id),
            "proposal_request_id": str(request_id),
            "source_version_id": str(parent_id),
            "source_run_id": str(run.id),
            "eval_set_id": str(run.eval_set_id),
            "status": "pending",
            "created_at": utcnow().isoformat(),
            "decided_at": None,
            "version_id": None,
            "source_config_hash": parent_hash,
            "capability_profile": profile,
            "title": draft.title,
            "what_changes": draft.what_changes
            or "; ".join(change.reason for change in draft.changes)[:1000],
            "why_it_may_work": draft.why_it_may_work
            or "; ".join(group["root_cause"] for group in groups)[:1000],
            "benefits": draft.benefits
            or ["Addresses the failed cases using evidence from this evaluation run."],
            "risks": draft.risks
            or [
                "May need another regression run to catch behavior changes "
                "outside the failed cases."
            ],
            "targeted_case_ids": selected_cases[:20],
            "affected_capabilities": draft.affected_capabilities,
            "failure_patterns": groups,
            "changes": draft.model_dump(mode="json")["changes"],
            "diffs": diffs,
            "deferred_changes": deferred,
            "can_accept": bool(diffs),
        }
    )


async def generate(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    request_id: uuid.UUID,
) -> dict[str, Any]:
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    proposal_id = uuid.uuid5(run.id, f"proposal:{request_id}:0")
    current_proposals = proposals(run)
    existing = next(
        (p for p in current_proposals if p["id"] == str(proposal_id)),
        None,
    )
    if existing is None:
        existing = next(
            (p for p in current_proposals if p.get("proposal_request_id") == str(request_id)),
            None,
        )
    if existing:
        return existing
    optimization.terminal_semantic(run)
    analysis = await optimization.analyze(db, agent_id, user_id, run.id)
    if not analysis["groups"]:
        raise optimization.fail("optimization_no_fixable_cases", 409)
    parent = await projects.get_version(db, agent_id, user_id, run.version_id)
    profile = (run.comparison_json or {}).get("eval_spec", {}).get("capability_profile")
    profile = profile or capability_profile(parent.snapshot_json)
    try:
        raw = await json_call(
            db,
            parent.snapshot_json,
            user_id,
            "optimization_proposal",
            "Propose 2-3 distinct, reasonable optimization strategies with minimal "
            "evidence-driven TEXT changes addressing the supplied failure groups. "
            "These are proposals for human review, not authorization to change the Agent. "
            "Each proposal must include title, what_changes, why_it_may_work, benefits, risks "
            "and targeted_case_ids. "
            "Use only capabilities from capability_profile.capabilities. "
            "Allowed targets: instructions/output_instructions (system_prompt), "
            "skill_content (frozen skill content only), "
            "tool_description (linked tool/MCP description). "
            "Use resource_id for skill_id/tool_id/mcp_tool_id. Use append or replace_section with "
            "one exact old_content anchor. replace_value is ONLY for tool_description with exact "
            "old_content. No whole-prompt rewrites, test answers, case-specific exceptions, "
            "credential/model changes, rubric changes or test changes. "
            "At most 3000 added characters. Changes for missing historical Skill content "
            "will be deferred, never applied to live Skills. "
            "Return the supplied schema; group_index is zero-based.",
            {
                "snapshot": parent.snapshot_json,
                "groups": analysis["groups"],
                "bad_cases": analysis["bad_cases"],
                "judge_results": run.results_json,
                "capability_profile": profile,
                "schema": OptimizationProposalSet.model_json_schema(),
            },
        )
        drafts = draft_list(raw)
        analyzed_case_ids = {
            str(item["case_id"]) for item in analysis["bad_cases"] if item.get("case_id")
        }
        signatures: set[str] = set()
        values = []
        for index, draft in enumerate(drafts):
            if set(draft.affected_capabilities) - set(profile.get("capabilities", [])):
                raise ValueError("Unknown capability")
            targeted_case_ids = {str(item) for item in draft.targeted_case_ids}
            if targeted_case_ids - analyzed_case_ids:
                raise ValueError("Optimization targets a case outside the failure analysis")
            signature = canonical_json_hash(draft.model_dump(mode="json").get("changes", []))
            if signature in signatures:
                raise ValueError("Optimization proposals must be distinct")
            signatures.add(signature)
            _, diffs, deferred = apply_patches(parent.snapshot_json, draft, analysis["groups"])
            values.append(
                proposal_value(
                    proposal_id=uuid.uuid5(run.id, f"proposal:{request_id}:{index}"),
                    request_id=request_id,
                    parent_id=parent.id,
                    run=run,
                    parent_hash=parent.config_hash or canonical_json_hash(parent.snapshot_json),
                    profile=profile,
                    draft=draft,
                    groups=analysis["groups"],
                    diffs=diffs,
                    deferred=deferred,
                )
            )
    except Exception as exc:
        raise optimization.fail("optimization_proposal_invalid") from exc
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    await db.refresh(run, ["comparison_json"])
    existing = next(
        (p for p in proposals(run) if p["id"] == str(proposal_id)),
        None,
    )
    if existing is None:
        existing = next(
            (p for p in proposals(run) if p.get("proposal_request_id") == str(request_id)),
            None,
        )
    if existing:
        await db.commit()
        return existing
    save_many(run, values)
    await db.commit()
    return values[0]


async def decide(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    proposal_id: uuid.UUID,
    decision: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    value = find(run, proposal_id)
    if value["status"] != "pending":
        if value["status"] != decision:
            raise optimization.fail("optimization_proposal_already_decided", 409)
        await db.commit()
        return value
    if decision == "accepted":
        accepted = next(
            (
                item
                for item in proposals(run)
                if item["id"] != value["id"] and item["status"] == "accepted"
            ),
            None,
        )
        if accepted:
            raise optimization.fail("optimization_proposal_already_decided", 409)
        parent = await projects.get_version(db, agent_id, user_id, run.version_id)
        if canonical_json_hash(parent.snapshot_json) != value["source_config_hash"]:
            raise optimization.fail("snapshot_hash_mismatch", 409)
        snapshot, diffs, deferred = apply_patches(
            parent.snapshot_json,
            PatchProposal(changes=value["changes"]),
            value["failure_patterns"],
        )
        if not diffs or diffs != value["diffs"] or deferred != value["deferred_changes"]:
            raise optimization.fail("optimization_no_supported_changes", 409)
        snapshot["created_from"] = {
            "source_version_id": str(parent.id),
            "optimization_proposal_id": str(proposal_id),
            "source_run_id": str(run.id),
        }
        snapshot["optimization"] = {
            "proposal_id": str(proposal_id),
            "patches": diffs,
            "plan": value["failure_patterns"],
            "deferred_changes": deferred,
        }
        version = await projects.append_snapshot_version(
            db,
            project,
            snapshot,
            parent_id=parent.id,
            request_id=uuid.uuid5(proposal_id, "accepted-version"),
            summary="; ".join(change["reason"] for change in diffs)[:1000],
        )
        value["version_id"] = str(version.id)
    decided_at = utcnow().isoformat()
    value.update(status=decision, decided_at=decided_at, decision_reason=decision_reason)
    if decision == "accepted":
        items = proposals(run)
        for item in items:
            if item["id"] == value["id"]:
                item.update(value)
            elif item["status"] == "pending":
                item.update(
                    status="rejected",
                    decided_at=decided_at,
                    superseded_by=value["id"],
                )
        run.comparison_json = {**(run.comparison_json or {}), "proposals": items}
    else:
        save(run, value)
    await db.commit()
    return value


async def regression(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    proposal_id: uuid.UUID,
    request_id: uuid.UUID,
) -> AgentProjectEvalRun:
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    source = await evaluation.get_run(db, agent_id, user_id, run_id)
    value = find(source, proposal_id)
    if value["status"] != "accepted":
        raise optimization.fail("optimization_proposal_not_accepted", 409)
    prior = await db.scalar(
        select(AgentProjectEvalRun).where(
            AgentProjectEvalRun.project_id == project.id,
            AgentProjectEvalRun.request_id == request_id,
        )
    )
    if prior:
        if (prior.comparison_json or {}).get("regression", {}).get("proposal_id") != str(
            proposal_id
        ):
            raise optimization.fail("evaluation_request_conflict", 409)
        await db.commit()
        return prior
    optimization.terminal_semantic(source)
    dataset = await evaluation.get_set(db, project.id, source.eval_set_id)
    if not dataset.frozen:
        raise optimization.fail("optimization_regression_inputs_changed", 409)
    await evaluation.expire_runs(db, project.id)
    plan = {
        key: deepcopy((source.comparison_json or {})[key])
        for key in ("eval_spec", "spec_hash", "rubric_hash", "roles", "execution_mode")
        if key in (source.comparison_json or {})
    }
    plan["regression"] = {"source_run_id": str(source.id), "proposal_id": str(proposal_id)}
    return await evaluation.insert_frozen_run(
        db,
        project.id,
        uuid.UUID(value["version_id"]),
        source.eval_set_id,
        request_id,
        deepcopy(source.cases_snapshot_json or []),
        plan,
    )
