"""Execute frozen reference paths against the same sandbox used by Agent A."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.agent_project import EvalSetWrite, EvalSpec
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from app.services.agent_project_mock_tools import mock_tools

EXECUTION_PROTOCOL = {
    "version": "mock_sandbox_v3",
    "execution_timeout_seconds": 30,
    "judge_timeout_seconds": 95,
    "judge_validation_retry_limit": 1,
    "recursion_policy": "graph_default_with_frozen_middleware_limits",
    "simulation_policy": "isolated_state_and_text_skills_only",
}

ENVIRONMENT_ERRORS = {
    "evaluation_mock_missing",
    "evaluation_mock_response_missing",
    "evaluation_mock_definition_invalid",
    "evaluation_mock_execution_failed",
}


def tool_definitions(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name") or item.get("tool_name")): item
        for field in ("tool_links", "mcp_tool_links", "planned_tools")
        for item in config.get(field, [])
        if item.get("enabled", True) and (item.get("name") or item.get("tool_name"))
    }


def preflight_case(config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    from app.services.agent_project_evaluation import score_case

    definitions = tool_definitions(config)
    mocks = case.get("mock_tool_data") or {}
    if set(definitions) != set(mocks):
        raise ValueError("Every enabled capability needs a mock; undeclared tools are forbidden")
    for behavior in mocks.values():
        if (
            behavior.get("operation", "static") == "static"
            and behavior.get("result") is None
            and not behavior.get("responses")
            and not behavior.get("error")
        ):
            raise ValueError(
                "Static responses need explicit data; missing data is not a null success"
            )
    expected = case.get("expected") or {}
    referenced = {
        *expected.get("required_tools", []),
        *expected.get("attempted_tools", []),
        *expected.get("forbidden_tools", []),
        *expected.get("necessary_order", []),
        *[rule["name"] for rule in expected.get("tool_arguments", [])],
    }
    if referenced - set(definitions):
        raise ValueError("Assertions reference an undeclared tool")
    injected = any(
        m.get("error")
        or m.get("fail_on_calls")
        or any(r.get("error") for r in m.get("responses", []))
        for m in mocks.values()
    )
    if injected and "tool_failure" not in case.get("tags", []):
        raise ValueError("Injected failures must be explicitly tagged")
    if case.get("recovery_goal") and not injected:
        raise ValueError("Recovery needs an explicitly injected failure")
    if not case.get("reference_answer"):
        raise ValueError("A reference answer is required for environment validation")
    if any(
        mocks.get(c["name"], {}).get("operation") == "update"
        for c in case.get("reference_trace", [])
    ) and not expected.get("state"):
        raise ValueError("Write goals need observable final state assertions")
    trace: list[dict[str, Any]] = []
    tools, missing = mock_tools(config, case, trace=trace)
    by_name = {t.name: t for t in tools}
    try:
        for call in case.get("reference_trace", []):
            by_name[call["name"]].invoke(call.get("arguments") or {})
    except (KeyError, ValueError, SnapshotExecutionUnavailable) as exc:
        raise ValueError("Reference path cannot execute in the frozen environment") from exc
    if missing or any(t.get("error") in ENVIRONMENT_ERRORS for t in trace):
        raise ValueError("Reference path hits a missing environment response")
    evidence = {
        "output": case["reference_answer"],
        "tool_calls": [{"name": t["name"]} for t in trace],
        "tool_trace": trace,
        "final_state": trace[-1]["state_after"] if trace else case.get("initial_state", {}),
    }
    checks = score_case(case, evidence, strict_tools=True)
    if not all(c["passed"] for c in checks):
        raise ValueError("Reference answer/path fails its own deterministic assertions")
    if case.get("recovery_goal") and not any(t.get("error") for t in trace):
        raise ValueError("Reference path never encounters the declared recoverable failure")
    return {"status": "approved", "checks": checks, "reference_evidence": evidence}


async def validate_generated_cases(
    config: dict[str, Any],
    requirements: dict[str, Any],
    spec: EvalSpec,
    body: EvalSetWrite,
    categories: list[str],
    call: Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]],
) -> tuple[EvalSetWrite, dict[str, Any]]:
    """B may repair rejected fixtures twice; only fully checked references are saved."""
    from collections import Counter

    from app.marketplace.payloads import canonical_json_hash
    from app.schemas.agent_project import SCENARIOS, RubricRuleReview
    from app.services.agent_project_rubric import validate_applicability

    attempts = []
    for attempt in range(3):
        failures = {}
        references = {}
        coverage = Counter(tag for case in body.cases for tag in case.tags if tag in categories)
        for case in body.cases:
            cid = str(case.id)
            try:
                if not case.enabled or not case.expected.answer:
                    raise ValueError("Missing expected behavior")
                tags = set(case.tags) & set(categories)
                if len(tags) != 1 or (set(case.tags) & set(SCENARIOS)) != tags:
                    raise ValueError("Need exactly one applicable category")
                validate_applicability(spec, case.model_dump(mode="json"))
                if case.expected_behavior is None:
                    case.expected_behavior = case.expected.model_dump(mode="json")
                references[cid] = preflight_case(config, case.model_dump(mode="json"))
            except (ValueError, KeyError, TypeError, SnapshotExecutionUnavailable) as exc:
                failures[cid] = str(exc) if type(exc) is ValueError else type(exc).__name__
        assigned = set()
        for category in set(categories) - set(coverage):
            replacement = next(
                (
                    c
                    for c in body.cases
                    if str(c.id) not in assigned and any(coverage[t] > 1 for t in c.tags)
                ),
                next(c for c in body.cases if str(c.id) not in assigned),
            )
            assigned.add(str(replacement.id))
            failures[str(replacement.id)] = (
                f"Missing required category {category}; replace this case to cover it."
            )
        reviews = []
        if not failures:
            response = await call(
                "judge",
                "Review every reference answer/path and applicability against the confirmed "
                "requirements and frozen rubric. Do not introduce extra obligations. Reject "
                "unsupported facts, contradictions, missing required behavior, or exclusion "
                "of an applicable requirement. These references validate the environment; "
                "they are never evidence for Agent A's future answers. Return exactly every "
                "case ID in rule_reviews:[{reference,supported,reason}].",
                {
                    "requirements": requirements,
                    "eval_spec": spec.model_dump(mode="json"),
                    "cases": [c.model_dump(mode="json") for c in body.cases],
                    "reference_results": references,
                },
            )
            reviews = [RubricRuleReview.model_validate(r) for r in response["rule_reviews"]]
            if len(reviews) != len(references) or {r.reference for r in reviews} != set(references):
                raise ValueError("Incomplete reference review")
            failures = {r.reference: r.reason for r in reviews if not r.supported}
        attempts.append(
            {
                "attempt": attempt + 1,
                "case_hash": canonical_json_hash([c.model_dump(mode="json") for c in body.cases]),
                "rejections": failures,
            }
        )
        if not failures:
            return body, {
                "case_hash": attempts[-1]["case_hash"],
                "program": references,
                "semantic": [r.model_dump() for r in reviews],
                "attempts": attempts,
            }
        if attempt == 2:
            raise SnapshotExecutionUnavailable("evaluation_reference_invalid")
        response = await call(
            "case_generator",
            "Repair ONLY the supplied rejected cases from program/C feedback. Keep their "
            "UUIDs exactly; do not change the confirmed requirements, frozen rubric, tools "
            "or any other case. Return {name,cases} matching the schema, with exactly the "
            "supplied case IDs. Fix reference answers, applicability/reasons and synthetic "
            "data as needed to make the declared task executable and consistent. Every "
            "enabled tool needs a response. No new obligations, tools or live operations.",
            {
                "requirements": requirements,
                "eval_spec": spec.model_dump(mode="json"),
                "config": config,
                "categories": categories,
                "rejections": failures,
                "cases": [c.model_dump(mode="json") for c in body.cases if str(c.id) in failures],
                "schema": EvalSetWrite.model_json_schema(),
            },
        )
        repaired = EvalSetWrite.model_validate(response)
        replacements = {str(c.id): c for c in repaired.cases}
        if len(replacements) != len(repaired.cases) or set(replacements) != set(failures):
            raise ValueError("Repair must preserve exactly the rejected case IDs")
        body.cases = [replacements.get(str(c.id), c) for c in body.cases]
    raise SnapshotExecutionUnavailable("evaluation_reference_invalid")
