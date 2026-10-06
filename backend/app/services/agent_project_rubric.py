"""Versioned scoring contracts. Legacy runs are read without inventing missing evidence."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.agent_project import CriterionVerdict, EvalSpec, FactVerdict

TOOL_RULE = (
    "程序检查本用例明确声明的必要业务调用（区分尝试与成功）、禁止操作、参数、必要顺序和最终模拟状态。"
    "所有适用检查通过得 1 分，否则得 0 分；无适用检查时不评分。"
)
FORMAT_RULE = (
    "程序检查本用例声明的 JSON 格式、字符数上限或精确输出。"
    "全部满足得 1 分，否则得 0 分；无检查时不评分。"
)


def validate_sources(spec: EvalSpec, requirements: dict[str, Any]) -> None:
    if spec.rubric_version < 2:
        return
    for metric in spec.metrics:
        references = [*metric.requirement_refs]
        for criterion in metric.scoring_criteria:
            references.extend(criterion.requirement_refs)
        for ref in references:
            source = requirements.get(ref.field)
            if not isinstance(source, str) or ref.quote not in source:
                raise ValueError("Scoring rule has no confirmed requirement source")
        if metric.type == "deterministic":
            expected = TOOL_RULE if metric.name == "tool_correctness" else FORMAT_RULE
            if metric.criteria != expected:
                raise ValueError("Scoring prose differs from the program contract")


def validate_applicability(spec: EvalSpec, case: dict[str, Any]) -> None:
    if spec.rubric_version < 2:
        return
    semantic = {m.name: m for m in spec.metrics if m.type == "llm_judge"}
    selected = case.get("metric_applicability")
    if not isinstance(selected, dict) or set(selected) != set(semantic):
        raise ValueError("Missing frozen metric applicability")
    for name, metric in semantic.items():
        ids = selected[name]
        if not isinstance(ids, list) or len(set(ids)) != len(ids):
            raise ValueError("Duplicate criterion applicability")
        if not set(ids) <= {c.id for c in metric.scoring_criteria}:
            raise ValueError("Unknown scoring criterion")
        if name == "task_completion" and (
            not ids
            or (spec.rubric_version == 2 and set(ids) != {c.id for c in metric.scoring_criteria})
        ):
            raise ValueError("Task completion cannot be excluded")
        if spec.rubric_version >= 3 and ids:
            for cid in {c.id for c in metric.scoring_criteria} - set(ids):
                if (
                    not (case.get("metric_applicability_reasons") or {})
                    .get(f"{name}/{cid}", "")
                    .strip()
                ):
                    raise ValueError(
                        f"Missing non-applicability reason for excluded criterion; "
                        f"use key {name}/{cid}"
                    )
        if not ids and not (case.get("metric_applicability_reasons") or {}).get(name, "").strip():
            raise ValueError(f"Missing non-applicability reason for metric; use key {name}")
    if not any(selected.values()):
        raise ValueError("No applicable content criteria")


def evidence_sources(case: dict[str, Any], evidence: dict[str, Any]) -> dict[str, str]:
    def text(value: Any) -> str:
        return (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True)
        )

    sources = {"output": str(evidence.get("output", "")), "input": str(case.get("input", ""))}
    for i, message in enumerate(case.get("context") or []):
        sources[f"context/{i}/content"] = str(message.get("content", ""))
    for i, event in enumerate(evidence.get("tool_trace") or []):
        for key in ("name", "arguments", "output", "error"):
            if key in event and event[key] is not None:
                sources[f"tool_trace/{i}/{key}"] = text(event[key])
    return sources


def aggregate_verdicts(
    spec: EvalSpec, case: dict[str, Any], sources: dict[str, str], raw: dict[str, Any]
) -> dict[str, Any]:
    semantic = {
        m.name: m
        for m in spec.metrics
        if m.type == "llm_judge" and (case["metric_applicability"].get(m.name) or [])
    }
    judgments = raw.get("criterion_results")
    if not isinstance(judgments, dict) or set(judgments) != set(semantic):
        raise ValueError("Missing or extra metric verdict")
    scores = {}
    for name, metric in semantic.items():
        if not isinstance(judgments[name], list):
            raise ValueError("Expected criterion verdict list")
        verdicts = [CriterionVerdict.model_validate(v) for v in judgments[name]]
        ids = [v.criterion_id for v in verdicts]
        if len(set(ids)) != len(ids) or set(ids) != set(case["metric_applicability"][name]):
            raise ValueError("Missing or extra criterion verdict")
        for verdict in verdicts:
            if verdict.level > 0 and not any(
                ref.reference == "output" or ref.reference.startswith("tool_trace/")
                for ref in verdict.evidence
            ):
                raise ValueError("A successful behavior needs observed execution evidence")
            for ref in verdict.evidence:
                if not ref.quote.strip() or ref.quote not in sources.get(ref.reference, ""):
                    raise ValueError("Judge evidence does not exist in observed records")
        criteria = {c.id: c for c in metric.scoring_criteria}
        critical_failure = any(
            criteria[v.criterion_id].critical
            and (v.level == 0 or (spec.rubric_version == 3 and v.level < 1))
            for v in verdicts
        )
        score = 0.0 if critical_failure else sum(v.level for v in verdicts) / len(verdicts)
        scores[name] = {
            "score": score,
            "passed": score >= spec.pass_threshold,
            "reason": "\n".join(v.reason for v in verdicts),
            "method": "llm_judge",
            "criteria_results": [v.model_dump(mode="json") for v in verdicts],
            "critical_failure": critical_failure,
            "critical_applicable": any(criteria[v.criterion_id].critical for v in verdicts),
            "scoring_mode": "criterion_mean",
            "verdict_role": metric.verdict_role,
        }
    return scores


def validate_facts(sources: dict[str, str], raw: Any) -> dict[str, Any]:
    if not isinstance(raw, list):
        raise ValueError("Missing fact-level verdicts")
    facts = [FactVerdict.model_validate(item) for item in raw]
    claims = [f.claim for f in facts]
    if len(set(claims)) != len(claims):
        raise ValueError("Duplicate fact")
    for fact in facts:
        if fact.claim not in sources.get("output", ""):
            raise ValueError("Fact is not an exact excerpt of the actual answer")
        for ref in fact.evidence:
            if ref.quote not in sources.get(ref.reference, ""):
                raise ValueError("Fact evidence does not exist")
        if fact.verdict == "supported" and not any(
            ref.reference != "output" and ref.quote.strip() for ref in fact.evidence
        ):
            raise ValueError("The answer cannot support its own factual claims")
        if fact.kind == "fact" and fact.verdict == "not_applicable":
            raise ValueError("Factual assertions must be evaluated")
    checked = [f for f in facts if f.kind == "fact"]
    return {
        "items": [f.model_dump(mode="json") for f in facts],
        "supported": sum(f.verdict == "supported" for f in checked),
        "unsupported": sum(f.verdict == "unsupported" for f in checked),
        "unknown": sum(f.verdict == "unknown" for f in checked),
        "total": len(checked),
        "coverage": "model_C_extracted_claims_not_expert_validated",
    }
