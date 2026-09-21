"""Isolated snapshot adapter for the existing canonical graph factory.

No live Agent is persisted or invoked. Unpinned capabilities fail closed.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.protocol_redaction import redact_protocol_data
from app.services.agent_project_service import snapshot_value


class SnapshotExecutionUnavailable(Exception):
    """A fixed error code with optional already-redacted execution evidence."""

    def __init__(self, code: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = evidence or {}


async def execute_snapshot(
    db: AsyncSession, snapshot: dict[str, Any], case: dict[str, Any], user_id: uuid.UUID
) -> dict[str, Any]:
    config = snapshot.get("agent", {})
    if snapshot.get("schema_version") != 1 or not config.get("model"):
        raise SnapshotExecutionUnavailable("snapshot_invalid")
    for field in (
        "sub_agent_links",
        "model_fallback_list",
    ):
        if config.get(field):
            raise SnapshotExecutionUnavailable("snapshot_capabilities_not_supported")
    if "<redacted>" in json.dumps(config):
        raise SnapshotExecutionUnavailable("snapshot_redacted_configuration")
    middleware = snapshot_middlewares(config)
    from app.services.agent_project_mock_tools import frozen_skill_prompt, mock_tools

    tool_trace: list[dict[str, Any]] = []
    tools, missing = mock_tools(config, case, trace=tool_trace)
    skill_prompt, limitations = frozen_skill_prompt(config)
    try:
        from app.agent_runtime.runtime_component_builder import build_agent
    except ModuleNotFoundError as exc:
        raise SnapshotExecutionUnavailable("runtime_platform_unavailable") from exc

    from deepagents.backends import StateBackend
    from langchain_core.messages import AIMessage
    from langsmith import tracing_context

    from app.agent_runtime.runtime_policy import resolve_runtime_policy
    from app.services.agent_project_llm import resolve_model

    try:
        with tracing_context(enabled=False):
            llm, api_key = await resolve_model(db, snapshot, user_id, role="examinee")
            graph = build_agent(
                llm,
                tools,
                config["system_prompt"] + skill_prompt,
                middleware=middleware,
                backend=StateBackend(),
                checkpointer=None,
                store=None,
                memory=None,
                skills=None,
                name="project_evaluation",
                runtime_policy=resolve_runtime_policy(config.get("runtime_policy")),
            )
            messages = [*case.get("context", []), {"role": "user", "content": case["input"]}]
            result = await graph.ainvoke(
                {"messages": messages}, {"recursion_limit": 30, "callbacks": []}
            )
        if result.get("__interrupt__"):
            raise SnapshotExecutionUnavailable("evaluation_requires_approval")
        answers = [
            message for message in result.get("messages", []) if isinstance(message, AIMessage)
        ]
        output = answers[-1].text if answers else ""
        calls = [call for message in answers for call in message.tool_calls]
        called_tools = [{"name": event["name"]} for event in tool_trace] or [
            {"name": call["name"]} for call in calls
        ]
        evidence = {
            "output": output,
            "limitations": limitations,
            "execution_mode": "mock_sandbox",
            "tool_calls": called_tools,
            "tool_trace": tool_trace,
            "mock_missing_tools": sorted(set(missing)),
            "handoffs": [
                call.get("args", {}).get("subagent_type")
                for call in calls
                if call["name"] == "task"
            ],
        }
        # Scrub actual resolved values before any database/API boundary. No raw
        # tool arguments, tool results, headers, or provider errors are retained.
        return snapshot_value(
            redact_protocol_data(
                "project_evaluation",
                evidence,
                redact_memory=False,
                secret_values=[api_key] if api_key else [],
            )
        )
    except SnapshotExecutionUnavailable:
        raise
    except Exception as exc:
        if exc.__class__.__name__ == "LLMCredentialRequiredError":
            raise SnapshotExecutionUnavailable("snapshot_credential_unavailable") from exc
        raise SnapshotExecutionUnavailable("evaluation_execution_failed") from exc


def snapshot_middlewares(config: dict[str, Any]) -> list:
    from app.agent_runtime.middleware_registry import build_middleware_instances
    from app.services.builder_runtime_readiness import BUILDER_MIDDLEWARE_TYPES

    configs = config.get("middleware_configs") or []
    if any(c.get("type") not in BUILDER_MIDDLEWARE_TYPES for c in configs):
        raise SnapshotExecutionUnavailable("snapshot_capabilities_not_supported")
    instances = build_middleware_instances(configs)
    if len(instances) != len(configs):
        raise SnapshotExecutionUnavailable("snapshot_middleware_unavailable")
    return instances
