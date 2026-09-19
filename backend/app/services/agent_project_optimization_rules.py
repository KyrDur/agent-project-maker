"""Pure bounded patching and transparent, evidence-based regression decisions."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.schemas.agent_project_optimization import PatchProposal
from app.services.agent_project_service import snapshot_value

POLICY: dict[str, Any] = {
    "semantic_gain": 0.05,
    "maximum_metric_drop": 0.02,
    "maximum_regressed_fraction": 0.05,
    "protected_metrics": ["tool_correctness", "groundedness", "format_compliance"],
}


def apply_patches(
    snapshot: dict[str, Any], proposal: PatchProposal, groups: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    candidate = deepcopy(snapshot)
    candidate.pop("optimization", None)
    config = candidate["agent"]
    diffs: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    if sum(len(change.content) for change in proposal.changes) > 3000:
        raise ValueError("optimization_patch_too_large")
    for change in proposal.changes:
        if change.group_index >= len(groups):
            raise ValueError("optimization_patch_group_invalid")
        group = groups[change.group_index]
        if group["target"] != change.target or group["category"] == "external_unfixable":
            raise ValueError("optimization_patch_target_invalid")
        if snapshot_value(change.content) != change.content:
            raise ValueError("optimization_patch_redacted")
        holder, field = config, "system_prompt"
        if change.target == "skill_content":
            holder = next(
                (
                    s
                    for s in config.get("skill_links", [])
                    if str(s.get("skill_id")) == change.resource_id
                ),
                None,
            )
            field = "content"
            if not holder or not isinstance(holder.get(field), str) or not holder[field]:
                deferred.append(
                    {
                        **change.model_dump(mode="json"),
                        "limitation": "historical_skill_content_unavailable",
                    }
                )
                continue
        elif change.target == "tool_description":
            holder = next(
                (
                    tool
                    for name, key in [("tool_links", "tool_id"), ("mcp_tool_links", "mcp_tool_id")]
                    for tool in config.get(name, [])
                    if str(tool.get(key)) == change.resource_id
                ),
                None,
            )
            field = "description"
            if holder is None:
                raise ValueError("optimization_tool_reference_invalid")
        elif change.target not in {"instructions", "output_instructions"}:
            raise ValueError("optimization_patch_target_invalid")
        before = holder.get(field, "")
        if not isinstance(before, str) or "<redacted>" in before:
            raise ValueError("optimization_patch_redacted")
        if change.operation == "append":
            if change.content in before:
                continue
            after = before + ("\n" if before else "") + change.content
        elif change.operation == "replace_section":
            old = change.old_content
            if not old or before.count(old) != 1 or old == before:
                raise ValueError("optimization_section_invalid")
            after = before.replace(old, change.content, 1)
        elif change.operation == "replace_value" and field == "description":
            if change.old_content is None or change.old_content != before:
                raise ValueError("optimization_value_mismatch")
            after = change.content
        else:
            raise ValueError("optimization_operation_invalid")
        if after == before:
            continue
        holder[field] = after
        diffs.append({**change.model_dump(mode="json"), "before": before, "after": after})
    return candidate, diffs, deferred


def compare_runs(baseline: Any, candidate: Any) -> dict[str, Any]:
    # Compare the exact frozen experiment, not dataset IDs or freshly saved cases.
    keys = ("eval_spec", "spec_hash", "rubric_hash", "roles", "execution_mode")
    if (
        baseline.dataset_hash != candidate.dataset_hash
        or baseline.cases_snapshot_json != candidate.cases_snapshot_json
        or baseline.eval_set_id != candidate.eval_set_id
        or any(
            (baseline.comparison_json or {}).get(k) != (candidate.comparison_json or {}).get(k)
            for k in keys
        )
    ):
        raise ValueError("optimization_regression_inputs_changed")
    left = {r["case_id"]: r for r in baseline.results_json or []}
    right = {r["case_id"]: r for r in candidate.results_json or []}
    case_ids = {c["id"] for c in baseline.cases_snapshot_json or []}
    if not case_ids or set(left) != case_ids or set(right) != case_ids:
        raise ValueError("optimization_regression_incomplete")
    groups: dict[str, Any] = {
        key: []
        for key in ("fixed_cases", "regressed_cases", "still_failing_cases", "still_passing_cases")
    }
    for case_id in sorted(case_ids):
        a, b = left[case_id]["status"] == "passed", right[case_id]["status"] == "passed"
        key = (
            ("still_passing_cases" if a else "fixed_cases")
            if b
            else ("regressed_cases" if a else "still_failing_cases")
        )
        groups[key].append(case_id)
    n = len(case_ids)
    before_rate = sum(r["status"] == "passed" for r in left.values()) / n
    after_rate = sum(r["status"] == "passed" for r in right.values()) / n
    metric_specs = (baseline.comparison_json or {})["eval_spec"]["metrics"]
    deltas: dict[str, Any] = {}
    complete = True
    protected_regressions = []
    for metric in metric_specs:
        name = metric["name"]
        values = [
            [r.get("metric_scores", {}).get(name) for r in side.values()] for side in (left, right)
        ]
        if any(v is None for row in values for v in row):
            complete = False
            deltas[name] = {"before": None, "after": None, "delta": None}
            continue
        before = sum(v["score"] for v in values[0]) / n
        after = sum(v["score"] for v in values[1]) / n
        deltas[name] = {"before": before, "after": after, "delta": after - before}
        if name in POLICY["protected_metrics"]:
            protected_regressions.extend(
                case_id
                for case_id in case_ids
                if left[case_id]["metric_scores"][name]["passed"]
                and not right[case_id]["metric_scores"][name]["passed"]
            )
    errors = any(r["status"] == "errored" for side in (left, right) for r in side.values())
    reasons = []
    if errors or not complete:
        reasons.append("incomplete_quality_evidence")
    if len(groups["regressed_cases"]) > int(n * POLICY["maximum_regressed_fraction"]):
        reasons.append("too_many_regressions")
    if protected_regressions:
        reasons.append("protected_metric_regression")
    if any(
        v["delta"] is not None and v["delta"] < -POLICY["maximum_metric_drop"] - 1e-9
        for v in deltas.values()
    ):
        reasons.append("metric_drop")
    semantic_gain = any(
        m["type"] == "llm_judge"
        and deltas[m["name"]]["delta"] is not None
        and deltas[m["name"]]["delta"] >= POLICY["semantic_gain"] - 1e-9
        for m in metric_specs
    )
    improved = after_rate > before_rate or (after_rate == before_rate and semantic_gain)
    if not improved:
        reasons.append("no_improvement" if after_rate >= before_rate else "worse_than_parent")
    return {
        **groups,
        "pass_rate": {
            "before": before_rate,
            "after": after_rate,
            "delta": after_rate - before_rate,
        },
        "metrics": deltas,
        "decision": "rejected" if reasons else "accepted",
        "reasons": reasons
        or ["pass_rate_improved" if after_rate > before_rate else "semantic_metrics_improved"],
        "policy": deepcopy(POLICY),
    }


def observation(data: dict[str, Any], pointer: str) -> Any:
    allowed = {
        "input",
        "context",
        "expected",
        "actual_output",
        "called_tools",
        "deterministic_assertions",
        "metric_scores",
        "judge_reasons",
        "mock_tool_data",
        "error_code",
    }
    parts = pointer.split("/")[1:]
    if not pointer.startswith("/") or not parts or parts[0] not in allowed:
        raise ValueError("optimization_evidence_invalid")
    value: Any = data
    try:
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("optimization_evidence_invalid") from exc
    if len(json.dumps(value)) > 10000:
        return "Observation is available in the frozen case/run."
    return value
