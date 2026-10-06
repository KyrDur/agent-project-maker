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
        or len(results) != len(cases) * (run.comparison_json or {}).get("repetitions", 1)
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


async def save_failed_stage_calls(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    stage: str,
    calls: list[dict[str, Any]],
    code: str,
) -> None:
    await db.rollback()
    project = await projects.require_project(db, agent_id, user_id)
    await projects.lock_project(db, project)
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    await db.refresh(run, ["comparison_json"])
    attempts = (run.comparison_json or {}).get("stage_failures", [])
    run.comparison_json = {
        **(run.comparison_json or {}),
        "stage_failures": [
            *attempts,
            projects.snapshot_value(
                {"stage": stage, "code": code, "calls": calls, "created_at": utcnow().isoformat()}
            ),
        ],
    }
    await db.commit()


def analysis_evidence(cases: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep every repeat; a readable representative never replaces the full evidence."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result["case_id"], []).append(result)
    any_failure = any(r["status"] != "passed" for r in results)
    evidence = {}
    for cid, trials in grouped.items():
        weak = (
            [r for r in trials if r["status"] != "passed"]
            if any_failure
            else [
                r
                for r in trials
                if any(v.get("score", 1) < 1 for v in r.get("metric_scores", {}).values())
            ]
        )
        if not weak:
            continue
        representative = next((r for r in weak if r["status"] != "errored"), weak[0])
        item = case_evidence(cases[cid], representative)
        item["trials"] = [
            {
                **case_evidence(cases[cid], r),
                "trial": r.get("trial", 1),
                "status": r["status"],
                "tool_trace": r.get("tool_trace", []),
                "final_state": r.get("final_state"),
                "fact_check": r.get("fact_check"),
            }
            for r in trials
        ]
        evidence[cid] = item
    return evidence


def validate_analysis(raw: dict[str, Any], eligible: dict[str, Any]) -> AnalysisProposal:
    proposal = AnalysisProposal.model_validate(raw)
    records = {str(item.case_id): item for item in proposal.analyses}
    if len(records) != len(proposal.analyses) or set(records) != set(eligible):
        raise ValueError(
            f"Invalid analyzed case IDs; missing {sorted(set(eligible) - set(records))}; "
            f"unexpected {sorted(set(records) - set(eligible))}"
        )
    for case_id, item in records.items():
        for reference in item.evidence:
            try:
                observation(eligible[case_id], reference)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid evidence pointer {reference} for case {case_id}"
                ) from exc
        if (item.category in {"external_unfixable", "no_supported_change"}) != (
            item.recommended_target == "none"
        ):
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
    fixable = {k for k, v in records.items() if v.recommended_target != "none"}
    if len(set(grouped)) != len(grouped) or set(grouped) != fixable:
        raise ValueError(
            f"Invalid grouping coverage; exactly these cases are fixable: {sorted(fixable)}"
        )
    return proposal


async def analyze(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, run_id: uuid.UUID
) -> dict[str, Any]:
    run = await evaluation.get_run(db, agent_id, user_id, run_id)
    terminal_semantic(run)
    if (run.comparison_json or {}).get("purpose") == "validation" and (
        run.comparison_json or {}
    ).get("validation_exposure") != "used":
        raise fail("validation_evidence_not_for_optimization", 409)
    if "analysis" in (run.comparison_json or {}):
        return {"bad_cases": run.bad_cases_json or [], **(run.comparison_json or {})["analysis"]}
    version = await projects.get_version(db, agent_id, user_id, run.version_id)
    if canonical_json_hash(version.snapshot_json) != version.config_hash:
        raise fail("snapshot_hash_mismatch")
    cases = {case["id"]: case for case in run.cases_snapshot_json or []}
    evidence = analysis_evidence(cases, run.results_json or [])
    external = []
    eligible = {}
    for case_id, item in evidence.items():
        if item["error_code"]:
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
    role_calls: list[dict[str, Any]] = []
    proposal = AnalysisProposal(analyses=[], groups=[])
    if eligible:
        try:
            from app.services.agent_project_llm import capture_calls

            feedback = None
            previous = None
            with capture_calls(role_calls):
                for attempt in range(2):
                    raw = await json_call(
                        db,
                        {
                            **version.snapshot_json,
                            "resolved_role_models": (run.comparison_json or {}).get(
                                "resolved_role_models"
                            ),
                            "evaluation_roles": (run.comparison_json or {}).get(
                                "resolved_roles", {}
                            ),
                            "role_configurations": (run.comparison_json or {}).get(
                                "role_configurations"
                            ),
                        },
                        user_id,
                        "bad_case_analyzer",
                        "Analyze failed cases or imperfect metrics from the frozen experiment. "
                        "Do not label passing cases as failures; identify bounded improvements. "
                        "Infer likely causes conservatively, citing observable evidence. "
                        "evidence must be JSON pointer strings into each case evidence object, "
                        "for example /actual_output or /metric_scores/groundedness/score. "
                        "All repeat trials are in /trials; inspect every trial and describe "
                        "variation, never infer stability from a selected successful answer. "
                        "Do not claim inaccessible internal reasoning. Group similar failures into "
                        "at most five shared causes; prefer general fixes over case wording hacks. "
                        "Each fixable case belongs to exactly one group with the "
                        "same category and target "
                        "as its analysis. External outages: external_unfixable, target none, "
                        "and must not appear in fixable groups. Frozen Skill text "
                        "may be absent: propose "
                        "Skill changes as deferred advice rather than claiming access "
                        "to a live Skill. "
                        "When evidence does not justify a verifiable change, use "
                        "category no_supported_change, "
                        "target none, cite the actual weak metric or output, and "
                        "explain testing boundaries. "
                        "Do not create a group or invent a failure for that case. "
                        "Analyze exactly every supplied case ID, including "
                        "no_supported_change cases. "
                        "Keep each cause and suggestion concise. Return the supplied schema only.",
                        {
                            "snapshot": version.snapshot_json,
                            "eval_spec": (run.comparison_json or {})["eval_spec"],
                            "cases": list(eligible.values()),
                            "schema": AnalysisProposal.model_json_schema(),
                            "required_case_ids": list(eligible),
                            "evidence_pointer_examples": [
                                "/actual_output",
                                "/case/input",
                                "/metric_scores",
                                "/trials",
                            ],
                            "validation_error": feedback,
                            "previous_response": previous,
                        },
                    )
                    try:
                        proposal = validate_analysis(raw, eligible)
                        break
                    except (ValueError, KeyError, TypeError) as exc:
                        if role_calls:
                            role_calls[-1]["validation_status"] = "rejected"
                            role_calls[-1]["validation_error"] = type(exc).__name__
                        if attempt:
                            raise
                        from pydantic import ValidationError

                        feedback = (
                            exc.errors()[0]["msg"]
                            if isinstance(exc, ValidationError)
                            else str(exc).splitlines()[0]
                        )
                        previous = raw
        except Exception as exc:
            await save_failed_stage_calls(
                db,
                agent_id,
                user_id,
                run_id,
                "analysis",
                role_calls,
                "optimization_analysis_failed",
            )
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
    await db.refresh(run, ["comparison_json", "bad_cases_json"])
    if "analysis" in (run.comparison_json or {}):
        await db.commit()
        return {"bad_cases": run.bad_cases_json or [], **(run.comparison_json or {})["analysis"]}
    run.bad_cases_json = projects.snapshot_value(analyses)
    run.comparison_json = {
        **(run.comparison_json or {}),
        "analysis": projects.snapshot_value(
            {
                "groups": groups,
                "version": "analysis_v2",
                "model_role": "judge_optimizer",
                "calls": role_calls,
            }
        ),
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
        for key in (
            "eval_spec",
            "spec_hash",
            "rubric_hash",
            "roles",
            "execution_mode",
            "requirements",
            "requirements_hash",
            "decisions",
            "resolved_roles",
            "resolved_examinee",
            "resolved_role_models",
            "role_configurations",
            "repetitions",
            "purpose",
            "trial_policy",
            "execution_protocol",
            "validation_exposure",
        )
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
        response.created_from = version.snapshot_json.get("created_from")
        if str(version.id) in decisions:
            response.status = decisions[str(version.id)]
        responses.append(response)
    return responses
