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


def snapshot_recursion_limit(graph: Any, middleware: list[Any]) -> int:
    """Budget graph steps for complete model turns, including middleware hooks.

    Model/tool middleware still enforce their own limits; the graph limit is
    only a bounded fallback against an execution graph that cannot terminate.
    """
    if not hasattr(graph, "get_graph"):
        return 30
    turns = 30
    for item in middleware:
        if item.__class__.__name__ == "ModelCallLimitMiddleware":
            limits = [getattr(item, key, None) for key in ("run_limit", "thread_limit")]
            turns = min([turns, *(limit for limit in limits if isinstance(limit, int))])
    # One extra turn lets before_model apply the configured limit and jump to end.
    nodes = max(1, len(graph.get_graph().nodes))
    return min(1024, nodes * (max(1, turns) + 1))


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
    from langgraph.errors import GraphRecursionError
    from langsmith import tracing_context

    from app.agent_runtime.runtime_policy import resolve_runtime_policy
    from app.services.agent_project_llm import resolve_model

    api_key = ""
    model_calls: list[dict[str, Any]] = []
    output = ""
    try:
        with tracing_context(enabled=False):
            llm, api_key = await resolve_model(db, snapshot, user_id, role="examinee")
            from app.services.agent_project_call_evidence import CallEvidence, model_descriptor

            descriptor = model_descriptor(llm)
            if snapshot.get("resolved_examinee") and snapshot["resolved_examinee"] != descriptor:
                raise SnapshotExecutionUnavailable("evaluation_examinee_configuration_changed")
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
            from langchain_core.messages import messages_from_dict, messages_to_dict

            history = (
                messages_from_dict(case["_conversation_messages"])
                if case.get("_conversation_messages")
                else case.get("context", [])
            )
            messages = [*history, {"role": "user", "content": case["input"]}]
            result = await graph.ainvoke(
                {"messages": messages},
                {
                    "recursion_limit": snapshot_recursion_limit(graph, middleware),
                    "callbacks": [CallEvidence(model_calls, descriptor)],
                },
            )
        answers = [
            message for message in result.get("messages", []) if isinstance(message, AIMessage)
        ]
        output = answers[-1].text if answers else ""
        model_limits = [
            limit
            for m in middleware
            if m.__class__.__name__ == "ModelCallLimitMiddleware"
            for limit in (getattr(m, "run_limit", None), getattr(m, "thread_limit", None))
            if isinstance(limit, int)
        ]
        # Private middleware state is omitted from graph output. Use captured
        # calls and the middleware's terminal message to detect an exhausted budget.
        if (
            model_limits
            and len(model_calls) >= min(model_limits)
            and output.startswith("Model call limits exceeded:")
        ):
            raise SnapshotExecutionUnavailable("evaluation_step_limit")
        if any(m.__class__.__name__ == "ToolCallLimitMiddleware" for m in middleware) and (
            output.startswith("Tool call limit reached:")
            or (output.startswith("'") and " tool call limit reached:" in output)
        ):
            raise SnapshotExecutionUnavailable("evaluation_tool_call_limit")
        if result.get("__interrupt__"):
            raise SnapshotExecutionUnavailable("evaluation_requires_approval")
        calls = [call for message in answers for call in message.tool_calls]
        called_tools = [{"name": event["name"]} for event in tool_trace] or [
            {"name": call["name"]} for call in calls
        ]
        evidence = {
            "output": output,
            "model_calls": model_calls,
            "termination_reason": "completed",
            "final_state": tool_trace[-1]["state_after"]
            if tool_trace
            else case.get("initial_state", {}),
            "limitations": limitations,
            "execution_mode": "mock_sandbox",
            "tool_calls": called_tools,
            "tool_trace": tool_trace,
            "mock_missing_tools": sorted(set(missing)),
            **(
                {"conversation_messages": messages_to_dict(result.get("messages", []))}
                if "_conversation_messages" in case
                else {}
            ),
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
    except BaseException as exc:
        import asyncio

        evidence = snapshot_value(
            redact_protocol_data(
                "project_evaluation",
                {
                    "output": output,
                    "execution_mode": "mock_sandbox",
                    "model_calls": model_calls,
                    "tool_trace": tool_trace,
                    "tool_calls": [{"name": t["name"]} for t in tool_trace],
                    "final_state": tool_trace[-1]["state_after"]
                    if tool_trace
                    else case.get("initial_state", {}),
                    "termination_reason": "timeout"
                    if isinstance(exc, asyncio.CancelledError)
                    else "failed",
                },
                redact_memory=False,
                secret_values=[api_key] if api_key else [],
            )
        )
        if isinstance(exc, asyncio.CancelledError):
            # Persist partial evidence before the surrounding timeout handles cancellation.
            from app.services.agent_project_llm import _calls

            collector = _calls.get()
            if collector is not None:
                collector.append({"partial_execution": evidence})
            raise
        if isinstance(exc, SnapshotExecutionUnavailable):
            evidence["termination_reason"] = exc.code
            exc.evidence = {**evidence, **exc.evidence}
            raise
        code = (
            "evaluation_step_limit"
            if isinstance(exc, GraphRecursionError)
            or exc.__class__.__name__ == "ModelCallLimitExceededError"
            else (
                "snapshot_credential_unavailable"
                if exc.__class__.__name__ == "LLMCredentialRequiredError"
                else "evaluation_execution_failed"
            )
        )
        evidence["termination_reason"] = code
        raise SnapshotExecutionUnavailable(code, evidence) from exc


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
