"""Bounded project-only analyze -> patch -> evaluate -> compare loop."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProject, AgentProjectEvalRun, utcnow
from app.schemas.agent_project_optimization import AnalysisProposal, PatchProposal
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_service as projects
from app.services.agent_project_llm import json_call
from app.services.agent_project_optimization_rules import apply_patches, compare_runs, observation


def fail(code: str, status: int = 422) -> AppError:
    return AppError(code=code, message=code, status=status)


def terminal_semantic(run: AgentProjectEvalRun) -> None:
    if (
        run.status not in {"completed", "failed"}
        or not run.completed_at
        or not run.comparison_json
        or not run.comparison_json.get("eval_spec")
        or (run.metrics_json or {}).get("scoring") != "semantic_v1"
    ):
        raise fail("optimization_requires_semantic_run")
    cases = run.cases_snapshot_json or []
    results = run.results_json or []
    if (
        not cases
        or len(results) != len(cases)
        or {r["case_id"] for r in results} != {c["id"] for c in cases}
        or canonical_json_hash(cases) != run.dataset_hash
    ):
        raise fail("optimization_run_incomplete")


def case_evidence(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "input": case["input"],
        "context": case.get("context", []),
        "expected": case.get("expected"),
        "mock_tool_data": case.get("mock_tool_data", {}),
        "actual_output": result.get("actual_output", result.get("output", "")),
        "called_tools": result.get("called_tools", result.get("tool_calls", [])),
        "deterministic_assertions": result.get(
            "deterministic_assertions", result.get("assertions", [])
        ),
        "metric_scores": result.get("metric_scores", {}),
        "judge_reasons": result.get("judge_reasons", {}),
        "error_code": result.get("error_code") or result.get("error"),
    }


async def analyze(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, run_id: uuid.UUID
) -> dict[str, Any]:
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    terminal_semantic(run)
    if "analysis" in (run.comparison_json or {}):
        return {"bad_cases": run.bad_cases_json or [], **(run.comparison_json or {})["analysis"]}
    version = await projects.get_version(db, agent_id, user_id, run.version_id)
    if canonical_json_hash(version.snapshot_json) != version.config_hash:
        raise fail("snapshot_hash_mismatch")
    cases = {case["id"]: case for case in run.cases_snapshot_json or []}
    evidence = {
        r["case_id"]: case_evidence(cases[r["case_id"]], r)
        for r in run.results_json or []
        if r["status"] != "passed"
    }
    external = []
    eligible = {}
    for case_id, item in evidence.items():
        result = next(r for r in run.results_json or [] if r["case_id"] == case_id)
        if item["error_code"] or result["status"] == "errored":
            external.append(
                {
                    "case_id": case_id,
                    "category": "external_unfixable",
                    "root_cause": "Infrastructure failure, not an Agent quality diagnosis.",
                    "evidence": ["/error_code"],
                    "recommended_target": "none",
                    "suggested_fix": "Resolve the infrastructure failure outside optimization.",
                }
            )
        else:
            eligible[case_id] = item
    proposal = AnalysisProposal(analyses=[], groups=[])
    if eligible:
        try:
            raw = await json_call(
                db,
                version.snapshot_json,
                user_id,
                "bad_case_analyzer",
                "Analyze only these failed cases from the frozen experiment. "
                "Infer likely causes conservatively, citing observable evidence. "
                "evidence must be JSON pointer strings into each case evidence object, "
                "for example /actual_output or /metric_scores/groundedness/score. "
                "Do not claim inaccessible internal reasoning. Group similar failures into "
                "at most five shared causes; prefer general fixes over case wording hacks. "
                "Each fixable case belongs to exactly one group with the same category and target "
                "as its analysis. External outages: external_unfixable, target none, "
                "and must not appear in fixable groups. Frozen Skill text may be absent: propose "
                "Skill changes as deferred advice rather than claiming access to a live Skill. "
                "Return the supplied schema only.",
                {
                    "snapshot": version.snapshot_json,
                    "eval_spec": (run.comparison_json or {})["eval_spec"],
                    "cases": list(eligible.values()),
                    "schema": AnalysisProposal.model_json_schema(),
                },
            )
            proposal = AnalysisProposal.model_validate(raw)
            records = {str(item.case_id): item for item in proposal.analyses}
            if len(records) != len(proposal.analyses) or set(records) != set(eligible):
                raise ValueError("Invalid analyzed case IDs")
            for case_id, item in records.items():
                for reference in item.evidence:
                    observation(eligible[case_id], reference)
                if (item.category == "external_unfixable") != (item.recommended_target == "none"):
                    raise ValueError("Invalid external target")
            grouped = []
            for group in proposal.groups:
                if group.category == "external_unfixable" or group.target == "none":
                    raise ValueError("External group cannot be optimized")
                for case_id in group.case_ids:
                    item = records[str(case_id)]
                    if item.category != group.category or item.recommended_target != group.target:
                        raise ValueError("Group contradicts case analysis")
                    grouped.append(str(case_id))
            fixable = {k for k, v in records.items() if v.category != "external_unfixable"}
            if len(set(grouped)) != len(grouped) or set(grouped) != fixable:
                raise ValueError("Invalid grouping coverage")
        except Exception as exc:
            raise fail("optimization_analysis_failed") from exc
    analyses = [*external, *(item.model_dump(mode="json") for item in proposal.analyses)]
    for item in analyses:
        item["observations"] = [
            {"reference": ref, "value": observation(evidence[item["case_id"]], ref)}
            for ref in item["evidence"]
        ]
    groups = [group.model_dump(mode="json") for group in proposal.groups]
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    run.bad_cases_json = projects.snapshot_value(analyses)
    run.comparison_json = {
        **(run.comparison_json or {}),
        "analysis": projects.snapshot_value({"groups": groups, "version": "analysis_v1"}),
    }
    await db.commit()
    return {"bad_cases": run.bad_cases_json, "groups": groups}


def state_of(project: AgentProject) -> dict[str, Any] | None:
    return (project.report_json or {}).get("optimization")


async def save_state(db: AsyncSession, project: AgentProject, state: dict[str, Any]) -> None:
    await projects.lock_project(db, project)
    await db.refresh(project, ["report_json"])
    project.report_json = {**(project.report_json or {}), "optimization": deepcopy(state)}
    root = await db.get(AgentProjectEvalRun, uuid.UUID(state["root_run_id"]))
    if root:
        await db.refresh(root, ["comparison_json"])
        root.comparison_json = {**(root.comparison_json or {}), "optimization": deepcopy(state)}
    await db.commit()


async def start(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    request_id: uuid.UUID,
) -> tuple[dict[str, Any], bool]:
    project = await projects.require_project(db, agent_id, user_id)
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    terminal_semantic(run)
    await projects.lock_project(db, project)
    await db.refresh(project, ["report_json"])
    existing = state_of(project)
    if existing:
        await db.commit()
        if str(run_id) not in {existing["root_run_id"], *(r["run_id"] for r in existing["rounds"])}:
            raise fail("optimization_chain_already_exists", 409)
        return existing, False
    version = await projects.get_version(db, agent_id, user_id, run.version_id)
    if version.snapshot_json.get("optimization"):
        raise fail("optimization_chain_already_exists", 409)
    state = {
        "state": "pending",
        "root_run_id": str(run.id),
        "request_id": str(request_id),
        "best_version_id": str(run.version_id),
        "best_run_id": str(run.id),
        "rounds": [],
        "stop_reason": None,
        "started_at": utcnow().isoformat(),
    }
    await save_state(db, project, state)
    return state, True


async def create_candidate(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    parent_run: AgentProjectEvalRun,
    root_id: uuid.UUID,
    round_number: int,
    analysis: dict[str, Any],
    proposal: PatchProposal,
) -> tuple[Any, Any] | None:
    if round_number not in {1, 2}:
        raise fail("optimization_round_limit")
    project = await projects.require_project(db, agent_id, user_id)
    parent = await projects.get_version(db, agent_id, user_id, parent_run.version_id)
    terminal_semantic(parent_run)
    if canonical_json_hash(parent.snapshot_json) != parent.config_hash:
        raise fail("snapshot_hash_mismatch")
    snapshot, diffs, deferred = apply_patches(parent.snapshot_json, proposal, analysis["groups"])
    if not diffs:
        parent_run.comparison_json = {
            **(parent_run.comparison_json or {}),
            "deferred_changes": deferred,
        }
        await db.commit()
        return None
    snapshot["optimization"] = {
        "root_run_id": str(root_id),
        "parent_run_id": str(parent_run.id),
        "round": round_number,
        "plan": analysis["groups"],
        "patches": diffs,
        "deferred_changes": deferred,
    }
    snapshot["optimization"] = projects.snapshot_value(snapshot["optimization"])
    await projects.lock_project(db, project)
    candidate = await projects.append_snapshot_version(
        db,
        project,
        snapshot,
        parent_id=parent.id,
        request_id=uuid.uuid5(root_id, f"candidate:{round_number}"),
        summary="; ".join(change["reason"] for change in diffs)[:1000],
    )
    core = {
        key: deepcopy((parent_run.comparison_json or {})[key])
        for key in ("eval_spec", "spec_hash", "roles", "execution_mode")
        if key in (parent_run.comparison_json or {})
    }
    core["optimization"] = {
        "root_run_id": str(root_id),
        "parent_run_id": str(parent_run.id),
        "round": round_number,
        "decision": "candidate",
    }
    run = await evaluation.insert_frozen_run(
        db,
        project.id,
        candidate.id,
        parent_run.eval_set_id,
        uuid.uuid5(root_id, f"regression:{round_number}"),
        deepcopy(parent_run.cases_snapshot_json or []),
        core,
    )
    return candidate, run


async def execute_optimization(agent_id: uuid.UUID, user_id: uuid.UUID, root_id: uuid.UUID) -> None:
    async with async_session() as db:
        project = await projects.require_project(db, agent_id, user_id)
        await projects.lock_project(db, project)
        await db.refresh(project, ["report_json"])
        state = deepcopy(state_of(project))
        if not state or state["root_run_id"] != str(root_id) or state["state"] != "pending":
            await db.rollback()
            return
        state["state"] = "running"
        await save_state(db, project, state)
        try:
            parent_run = await evaluation.get_run(db, agent_id, user_id, root_id)
            for number in (1, 2):
                if all(r["status"] == "passed" for r in parent_run.results_json or []):
                    state["stop_reason"] = "all_cases_pass"
                    break
                analysis = await analyze(db, agent_id, user_id, parent_run.id)
                if not analysis["groups"]:
                    state["stop_reason"] = "no_fixable_cases"
                    break
                parent = await projects.get_version(db, agent_id, user_id, parent_run.version_id)
                raw = await json_call(
                    db,
                    parent.snapshot_json,
                    user_id,
                    "optimizer",
                    "Propose minimal TEXT patches addressing grouped root causes. "
                    "No whole-prompt rewrites, test answers or case-specific exceptions. "
                    "Allowed targets: instructions/output_instructions (system_prompt), "
                    "skill_content (only a frozen skill_links content string), "
                    "tool_description (a linked tool or MCP description). "
                    "Use resource_id equal to skill_id, tool_id or mcp_tool_id. "
                    "Use append or replace_section with one exact old_content anchor; "
                    "replace_value: ONLY tool_description, with exact old_content "
                    "(empty if missing). Never change tests, rubric, thresholds, model "
                    "configuration, credentials or other fields. At most 3000 added characters. "
                    "Skill changes without frozen content will be deferred. "
                    "Return the supplied patch schema with zero-based group_index.",
                    {
                        "snapshot": parent.snapshot_json,
                        "groups": analysis["groups"],
                        "schema": PatchProposal.model_json_schema(),
                    },
                )
                proposal = PatchProposal.model_validate(raw)
                built = await create_candidate(
                    db, agent_id, user_id, parent_run, root_id, number, analysis, proposal
                )
                if built is None:
                    state["stop_reason"] = "no_supported_changes"
                    break
                candidate, candidate_run = built
                entry = {
                    "version_id": str(candidate.id),
                    "run_id": str(candidate_run.id),
                    "parent_version_id": str(parent_run.version_id),
                    "decision": "candidate",
                    "round": number,
                }
                state["rounds"].append(entry)
                await save_state(db, project, state)
                await evaluation.execute_run(candidate_run.id, agent_id, user_id)
                await db.refresh(candidate_run)
                comparison = compare_runs(parent_run, candidate_run)
                candidate_run.comparison_json = {
                    **candidate_run.comparison_json,
                    "optimization": {**candidate_run.comparison_json["optimization"], **comparison},
                }
                entry.update(decision=comparison["decision"], comparison=comparison)
                if comparison["decision"] == "accepted":
                    state.update(
                        best_version_id=str(candidate.id), best_run_id=str(candidate_run.id)
                    )
                await save_state(db, project, state)
                if comparison["decision"] != "accepted":
                    state["stop_reason"] = "candidate_not_improved"
                    break
                parent_run = candidate_run
                if all(r["status"] == "passed" for r in parent_run.results_json or []):
                    state["stop_reason"] = "all_cases_pass"
                    break
            state["state"] = "completed"
            state["stop_reason"] = state["stop_reason"] or "two_round_limit"
        except Exception:
            await db.rollback()
            state["state"], state["stop_reason"] = "failed", "optimization_failed"
        await save_state(db, project, state)


async def version_responses(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, versions: list[Any]
) -> list[Any]:
    from app.schemas.agent_project import AgentProjectVersionResponse

    project = await projects.require_project(db, agent_id, user_id)
    state = state_of(project) or {}
    decisions = {item["version_id"]: item["decision"] for item in state.get("rounds", [])}
    responses = []
    for version in versions:
        response = AgentProjectVersionResponse.model_validate(version)
        if str(version.id) in decisions:
            response.status = decisions[str(version.id)]
        responses.append(response)
    return responses
