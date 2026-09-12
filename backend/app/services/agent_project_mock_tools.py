"""Synthetic tools only. No production factory, connections or credentials."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool

from app.services.agent_project_executor import SnapshotExecutionUnavailable


def mock_tools(config: dict[str, Any], case: dict[str, Any]) -> tuple[list[Any], list[str]]:
    behaviors = case.get("mock_tool_data") or {}
    required = case.get("expected", {}).get("required_tools", [])
    if any(name not in behaviors for name in required):
        raise SnapshotExecutionUnavailable("evaluation_mock_missing")
    definitions = {
        item["name"]: item
        for field in ("tool_links", "mcp_tool_links")
        for item in config.get(field, [])
        if item.get("enabled", True) and item.get("name")
    }
    names = set(definitions) | set(behaviors) | set(required)
    if len(names) > 60 or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n) for n in names):
        raise SnapshotExecutionUnavailable("evaluation_mock_definition_invalid")
    missing: list[str] = []
    tools = []
    for name in sorted(names):
        behavior = behaviors.get(name)

        def make_invoke(tool_name: str, frozen: dict[str, Any] | None) -> Callable[..., str]:
            def invoke(**_kwargs: Any) -> str:
                if frozen is None:
                    missing.append(tool_name)
                    return "Evaluation mock unavailable; no external tool was executed."
                if frozen.get("error"):
                    return json.dumps({"error": frozen["error"]})
                return json.dumps(frozen.get("result"), ensure_ascii=False)

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
