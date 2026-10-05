"""Bounded public model evidence, captured even when a graph is interrupted."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

PARAMETERS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_output_tokens",
    "max_completion_tokens",
    "max_retries",
)


def model_descriptor(llm: Any) -> dict[str, Any]:
    return {
        "implementation": type(llm).__name__,
        "model_name": getattr(llm, "model_name", None) or getattr(llm, "model", None),
        "base_url": str(
            getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None) or ""
        )
        or None,
        "parameters": {k: getattr(llm, k) for k in PARAMETERS if getattr(llm, k, None) is not None},
    }


class CallEvidence(BaseCallbackHandler):
    def __init__(self, calls: list[dict[str, Any]], descriptor: dict[str, Any]):
        self.calls = calls
        self.descriptor = descriptor
        self.active: dict[str, dict[str, Any]] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        call = {
            "model": self.descriptor,
            "status": "running",
            "invocation_parameters": kwargs.get("invocation_params", {}),
            "input_messages": [
                [{"type": m.type, "content": m.content} for m in batch] for batch in messages
            ],
        }
        self.calls.append(call)
        self.active[str(run_id)] = call

    def on_llm_end(self, response, *, run_id, **kwargs):
        call = self.active.get(str(run_id))
        if call is not None:
            call.update(
                status="completed",
                returns=[
                    {
                        "content": getattr(g.message, "content", ""),
                        "tool_calls": getattr(g.message, "tool_calls", []),
                        "response_metadata": getattr(g.message, "response_metadata", {}),
                        "usage_metadata": getattr(g.message, "usage_metadata", None),
                    }
                    for row in response.generations
                    for g in row
                    if hasattr(g, "message")
                ],
            )

    def on_llm_error(self, error, *, run_id, **kwargs):
        call = self.active.get(str(run_id))
        if call is not None:
            call.update(status="failed", error="model_call_failed")
