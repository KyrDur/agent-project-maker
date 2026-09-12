"""Isolated snapshot adapter for the existing canonical graph factory.

No live Agent is persisted or invoked. Unpinned capabilities fail closed.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.protocol_redaction import redact_protocol_data
from app.models.agent import Agent
from app.models.model import Model
from app.services.agent_project_service import snapshot_value


class SnapshotExecutionUnavailable(Exception):
    """A public, fixed error code, never a provider exception or payload."""


async def execute_snapshot(
    db: AsyncSession, snapshot: dict[str, Any], case: dict[str, Any], user_id: uuid.UUID
) -> dict[str, Any]:
    config = snapshot.get("agent", {})
    if snapshot.get("schema_version") != 1 or not config.get("model"):
        raise SnapshotExecutionUnavailable("snapshot_invalid")
    for field in (
        "tool_links",
        "skill_links",
        "mcp_tool_links",
        "sub_agent_links",
        "middleware_configs",
        "model_fallback_list",
    ):
        if config.get(field):
            raise SnapshotExecutionUnavailable("snapshot_capabilities_not_supported")
    if "<redacted>" in json.dumps(config):
        raise SnapshotExecutionUnavailable("snapshot_redacted_configuration")
    try:
        from app.agent_runtime.runtime_component_builder import build_agent
    except ModuleNotFoundError as exc:
        raise SnapshotExecutionUnavailable("runtime_platform_unavailable") from exc

    from deepagents.backends import StateBackend
    from langchain_core.messages import AIMessage
    from langsmith import tracing_context

    from app.agent_runtime.credential_resolution import resolve_llm_api_key_for_agent
    from app.agent_runtime.model_factory import create_chat_model
    from app.agent_runtime.runtime_policy import resolve_runtime_policy
    from app.credentials.service import get_for_user

    model_snapshot = config["model"]
    model = Model(
        id=uuid.UUID(model_snapshot["id"]),
        provider=model_snapshot["provider"],
        model_name=model_snapshot["model_name"],
        display_name=model_snapshot["model_name"],
        base_url=model_snapshot.get("base_url"),
        context_window=model_snapshot.get("context_window"),
        default_credential_id=(
            uuid.UUID(model_snapshot["default_credential_id"])
            if model_snapshot.get("default_credential_id")
            else None
        ),
    )
    agent = Agent(id=uuid.UUID(config["id"]), user_id=user_id, model=model)
    reference = config.get("llm_credential_id")
    agent.llm_credential = (
        await get_for_user(db, uuid.UUID(reference), user_id) if reference else None
    )
    # An explicitly bound credential must not silently fall back after deletion.
    if reference and agent.llm_credential is None:
        raise SnapshotExecutionUnavailable("snapshot_credential_unavailable")
    if (
        model.default_credential_id
        and not reference
        and await get_for_user(db, model.default_credential_id, user_id) is None
    ):
        raise SnapshotExecutionUnavailable("snapshot_credential_unavailable")
    api_key = await resolve_llm_api_key_for_agent(db, agent)
    if not api_key:
        # Do not let a provider SDK implicitly pick up operator environment keys.
        raise SnapshotExecutionUnavailable("snapshot_credential_unavailable")
    try:
        with tracing_context(enabled=False):
            llm = create_chat_model(
                model.provider,
                model.model_name,
                api_key,
                model.base_url,
                allow_env_fallback=False,
                context_window=model.context_window,
                **(config.get("model_params") or {}),
            )
            graph = build_agent(
                llm,
                [],
                config["system_prompt"],
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
        evidence = {
            "output": output,
            "tool_calls": [{"name": call["name"]} for call in calls],
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
        raise SnapshotExecutionUnavailable("evaluation_execution_failed") from exc
