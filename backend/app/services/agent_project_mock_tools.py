"""Synthetic tools only. No production factory, connections or credentials."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from time import perf_counter
from typing import Any

from langchain_core.tools import StructuredTool

from app.services.agent_project_executor import SnapshotExecutionUnavailable
from app.services.agent_project_tool_contracts import input_validator


def mock_tools(
    config: dict[str, Any],
    case: dict[str, Any],
    *,
    trace: list[dict[str, Any]] | None = None,
) -> tuple[list[Any], list[str]]:
    state = deepcopy(case.get("initial_state") or {})
    counts: dict[str, int] = deepcopy(case.get("_call_counts") or {})
    behaviors = case.get("mock_tool_data") or {}
    required = case.get("expected", {}).get("required_tools", [])
    if any(name not in behaviors for name in required):
        raise SnapshotExecutionUnavailable("evaluation_mock_missing")
    definitions: dict[str, dict[str, Any]] = {}
    for field in ("tool_links", "mcp_tool_links", "planned_tools"):
        for item in config.get(field, []):
            name = item.get("name") or item.get("tool_name")
            if item.get("enabled", True) and name:
                definitions[str(name)] = item
    names: list[str] = []
    for source in (definitions, behaviors, required):
        for name in source:
            if name not in names:
                names.append(name)
    if len(names) > 60 or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n) for n in names):
        raise SnapshotExecutionUnavailable("evaluation_mock_definition_invalid")
    missing: list[str] = []
    tools = []
    for name in names:
        behavior = behaviors.get(name)
        definition = definitions.get(name, {})
        try:
            schema = definition.get("input_schema")
            validator = input_validator(schema if schema is not None else {})
        except ValueError as exc:
            raise SnapshotExecutionUnavailable("evaluation_mock_definition_invalid") from exc

        def make_invoke(
            tool_name: str, frozen: dict[str, Any] | None, parameter_validator: Any
        ) -> Callable[..., str]:
            def invoke(**_kwargs: Any) -> str:
                started = perf_counter()
                counts[tool_name] = counts.get(tool_name, 0) + 1
                event: dict[str, Any] = {
                    "name": tool_name,
                    "arguments": deepcopy(_kwargs),
                    "call_number": counts[tool_name],
                    "state_before": deepcopy(state),
                }
                try:
                    if not parameter_validator.is_valid(_kwargs):
                        event.update(
                            error="invalid_tool_arguments",
                            output={"error": "invalid_tool_arguments"},
                        )
                        return json.dumps(event["output"])
                    if frozen is None:
                        missing.append(tool_name)
                        event.update(
                            error="evaluation_mock_missing",
                            output=None,
                        )
                        return "Evaluation mock unavailable; no external tool was executed."
                    if (frozen.get("error") and not frozen.get("fail_on_calls")) or counts[
                        tool_name
                    ] in frozen.get("fail_on_calls", []):
                        event.update(
                            error=frozen.get("error") or "simulated_failure",
                            output={"error": frozen.get("error") or "simulated_failure"},
                        )
                        return json.dumps(event["output"])
                    operation = frozen.get("operation", "static")
                    if operation in {"query", "update"}:
                        records = state.get(frozen["collection"], [])
                        fields = frozen.get("match_fields", [])
                        if any(field not in _kwargs for field in fields):
                            output = {"error": "missing_query_parameters"}
                        elif not isinstance(records, list) or any(
                            not isinstance(r, dict) for r in records
                        ):
                            raise ValueError("Invalid simulation collection")
                        else:
                            matched = [
                                r for r in records if all(r.get(k) == _kwargs[k] for k in fields)
                            ]
                            if operation == "update":
                                for record in matched:
                                    for key in frozen.get("update_fields", []):
                                        if key in _kwargs:
                                            record[key] = deepcopy(_kwargs[key])
                            output = deepcopy(matched)
                    elif frozen.get("responses"):
                        response = next(
                            (
                                r
                                for r in frozen["responses"]
                                if all(
                                    k in _kwargs and _kwargs[k] == v
                                    for k, v in r.get("arguments", {}).items()
                                )
                            ),
                            None,
                        )
                        output = (
                            deepcopy(response.get("result"))
                            if response
                            else {"error": "evaluation_mock_response_missing"}
                        )
                        if response and response.get("error"):
                            output = {"error": response["error"]}
                        if response is None:
                            missing.append(tool_name)
                    else:
                        output = deepcopy(frozen.get("result"))
                    if output is None:
                        output = {"error": "evaluation_mock_response_missing"}
                        missing.append(tool_name)
                    if isinstance(output, dict) and output.get("error"):
                        event["error"] = output["error"]
                    event["output"] = output
                    return json.dumps(output, ensure_ascii=False)
                except Exception:
                    event.setdefault("error", "evaluation_mock_execution_failed")
                    raise
                finally:
                    event["state_after"] = deepcopy(state)
                    event["latency_ms"] = round((perf_counter() - started) * 1000, 3)
                    if trace is not None:
                        event["order"] = len(trace) + 1
                        trace.append(event)

            return invoke

        tools.append(
            StructuredTool(
                name=name,
                description=definition.get("description")
                or (behavior or {}).get("description")
                or f"Frozen evaluation mock for {name}",
                args_schema=definition.get("input_schema")
                or {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
                func=make_invoke(name, behavior, validator),
            )
        )
    return tools, missing


def frozen_skill_prompt(config: dict[str, Any]) -> tuple[str, list[str]]:
    # Old snapshots contain reference/config metadata only. Never resolve a
    # storage_path or current Skill row here, even if the revision still exists.
    from app.skills.prompt import build_skills_prompt

    skills = config.get("skill_links") or []
    texts = [s for s in skills if isinstance(s.get("content"), str) and s["content"]]
    prompt = build_skills_prompt(texts) if texts else ""
    for skill in texts:
        prompt += (
            "\nFrozen Skill instructions (inline; filesystem is not mounted):\n" + skill["content"]
        )
    limitations = []
    if any(s.get("kind") == "package" for s in skills):
        limitations.append("script_skill_execution_unavailable")
    if len(texts) < len(skills):
        limitations.append("historical_skill_content_unavailable")
    return prompt, limitations
