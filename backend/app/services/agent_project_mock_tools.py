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


def mock_tools(
    config: dict[str, Any],
    case: dict[str, Any],
    *,
    trace: list[dict[str, Any]] | None = None,
) -> tuple[list[Any], list[str]]:
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

        def make_invoke(tool_name: str, frozen: dict[str, Any] | None) -> Callable[..., str]:
            def invoke(**_kwargs: Any) -> str:
                started = perf_counter()
                event: dict[str, Any] = {
                    "name": tool_name,
                    "arguments": deepcopy(_kwargs),
                }
                try:
                    if frozen is None:
                        missing.append(tool_name)
                        event.update(
                            error="evaluation_mock_missing",
                            output=None,
                        )
                        return "Evaluation mock unavailable; no external tool was executed."
                    if frozen.get("error"):
                        event.update(
                            error=frozen["error"],
                            output={"error": frozen["error"]},
                        )
                        return json.dumps({"error": frozen["error"]})
                    output = deepcopy(frozen.get("result"))
                    event["output"] = output
                    return json.dumps(output, ensure_ascii=False)
                except Exception:
                    event.setdefault("error", "evaluation_mock_execution_failed")
                    raise
                finally:
                    event["latency_ms"] = round((perf_counter() - started) * 1000, 3)
                    if trace is not None:
                        event["order"] = len(trace) + 1
                        trace.append(event)

            return invoke

        definition = definitions.get(name, {})
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
                func=make_invoke(name, behavior),
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
    if skills:
        limitations.append("historical_skill_execution_unavailable")
    if len(texts) < len(skills):
        limitations.append("historical_skill_content_unavailable")
    return prompt, limitations
