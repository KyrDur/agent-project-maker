from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agent_runtime.offload_protocol_projection import project_offload_egress_data
from app.schemas.conversation import MessageResponse, TokenUsageBreakdown

logger = logging.getLogger(__name__)

_TYPE_TO_ROLE = {"human": "user", "ai": "assistant", "tool": "tool"}
_PRIVATE_REASONING_BLOCK_TYPES = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "thinking",
        "redacted_thinking",
    }
)


def flatten_base_messages(value: Any, *, source: str) -> list[BaseMessage]:
    """Return only ``BaseMessage`` instances from nested checkpoint containers.

    This deliberately descends only through outer list containers: once a
    ``BaseMessage`` is found, its ``content`` is left untouched even when that
    content is itself a provider-specific list of blocks. LangGraph checkpoint
    wrappers are handled at the checkpoint compatibility boundary.
    """

    flat: list[BaseMessage] = []
    pending: list[Any] = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, BaseMessage):
            flat.append(current)
        elif isinstance(current, list):
            pending.extend(reversed(current))
        elif current is not None:
            logger.warning(
                "Dropping malformed checkpoint message value from %s: %s",
                source,
                type(current).__name__,
            )
    return flat


def parse_msg_id(raw_id: str | None, conversation_id: uuid.UUID, idx: int) -> uuid.UUID:
    if not raw_id:
        return uuid.uuid5(conversation_id, str(idx))
    try:
        return uuid.UUID(raw_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, raw_id)


def _content_block_to_display_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""

    block_type = block.get("type")
    if isinstance(block_type, str) and block_type in _PRIVATE_REASONING_BLOCK_TYPES:
        return ""

    if block_type == "text":
        text = block.get("text")
        if isinstance(text, str):
            return text
    return ""


def content_to_text(content: Any) -> str:
    """将 LangChain BaseMessage.content 转换为面向用户显示的 plain text。

    Anthropic 会将 multi-block content（text + tool_use 等）返回为 list[dict]。
    只 concat text block，忽略 tool_use block（通过 tool_calls 字段单独暴露）。
    provider-private reasoning/thinking block 不应进入 SSE/DB 显示状态，
    因此在这里移除。其他非 list/dict 形式安全地使用 str() fallback。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            parts.append(_content_block_to_display_text(block))
        return "".join(parts)
    if isinstance(content, dict):
        return _content_block_to_display_text(content)
    return str(content)


def _project_message_display_values(msg: BaseMessage) -> tuple[Any, Any]:
    """Copy browser-facing message fields through the offload egress boundary."""

    tool_call_id = getattr(msg, "tool_call_id", None)
    envelope: dict[str, Any] = {
        "content": msg.content,
        "tool_calls": getattr(msg, "tool_calls", None),
    }
    if isinstance(tool_call_id, str) and tool_call_id:
        envelope["tool_call_id"] = tool_call_id
    projected = project_offload_egress_data(envelope)
    return projected["content"], projected["tool_calls"]


def langchain_messages_to_response(
    messages: list[BaseMessage],
    conversation_id: uuid.UUID,
    timestamps: list[datetime] | None = None,
    *,
    cost_per_input_token: float | None = None,
    cost_per_output_token: float | None = None,
) -> list[MessageResponse]:
    """将 LangChain BaseMessage list 转换为 MessageResponse list。

    如果提供 `timestamps`，则按 message idx 使用对应时间（永久映射优先）。
    fallback 为 `now() + idx*1ms`（用于测试/单次调用）。

    ``cost_per_*_token`` (W7-4)：如果 caller 传入与 conversation 的 agent 关联的 model 单价，
    则为每条消息计算 ``MessageResponse.usage.estimated_cost``。
    cache_read 通常按 input 的 10% 单价计费，但会因模型而异，因此本实现将
    cache_creation 按与 input 相同单价、cache_read 按 input 的 10% 单价
    进行近似（Anthropic prompt caching 默认值）。
    """
    results: list[MessageResponse] = []
    fallback_base = datetime.now(UTC).replace(tzinfo=None)

    for idx, msg in enumerate(messages):
        role = _TYPE_TO_ROLE.get(msg.type, msg.type)
        projected_content, projected_tool_calls = _project_message_display_values(msg)
        content = content_to_text(projected_content)

        if timestamps is not None and idx < len(timestamps):
            created_at = timestamps[idx]
        else:
            created_at = fallback_base + timedelta(milliseconds=idx)

        # W7 — 将 AIMessage 携带的 ``usage_metadata`` 扁平化。user/tool
        # message 为 None。没有 cache_* 字段时填 0。
        usage = extract_usage_breakdown(
            msg,
            cost_per_input_token=cost_per_input_token,
            cost_per_output_token=cost_per_output_token,
        )

        results.append(
            MessageResponse(
                id=parse_msg_id(msg.id, conversation_id, idx),
                conversation_id=conversation_id,
                role=role,
                content=content,
                tool_calls=projected_tool_calls or None,
                tool_call_id=getattr(msg, "tool_call_id", None),
                created_at=created_at,
                usage=usage,
            )
        )

    return results


def extract_usage_breakdown(
    msg: BaseMessage,
    *,
    cost_per_input_token: float | None = None,
    cost_per_output_token: float | None = None,
) -> TokenUsageBreakdown | None:
    """将 LangChain ``usage_metadata`` 扁平化为 ``TokenUsageBreakdown``。

    在 fetch 路径复用与 streaming.py 的 ``message_end`` 发布逻辑相同的扁平化。
    user/tool message 或没有 usage_metadata 的 chunk 为 ``None``。

    如果提供单价，则同时填充 ``estimated_cost``。``input_tokens`` 在
    LangChain 1.x 中是包含全部 cache token 的总 input，因此直接按
    ``prompt × cost_per_input + completion × cost_per_output`` 计算。
    cache_read 的准确单价可能不同，但 fetch 路径的显示值采用近似即可
    （准确累计由 Daily Spend / token_usages 通过单独 path 跟踪）。
    """
    meta = getattr(msg, "usage_metadata", None)
    if not meta:
        return None
    input_details = meta.get("input_token_details") or {}
    prompt = int(meta.get("input_tokens", 0))
    completion = int(meta.get("output_tokens", 0))
    cache_creation = int(input_details.get("cache_creation", 0))
    cache_read = int(input_details.get("cache_read", 0))
    if prompt == 0 and completion == 0 and cache_creation == 0 and cache_read == 0:
        return None

    estimated_cost: float | None = None
    if cost_per_input_token is not None or cost_per_output_token is not None:
        cost = (prompt * (cost_per_input_token or 0)) + (completion * (cost_per_output_token or 0))
        estimated_cost = round(cost, 8) if cost > 0 else 0.0

    return TokenUsageBreakdown(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
        estimated_cost=estimated_cost,
    )


def convert_to_langchain_messages(messages: list[dict[str, str]]) -> list[BaseMessage]:
    lc_messages: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
    return lc_messages


_JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)\s*```")


def extract_json_from_markdown(content: str) -> dict[str, Any] | None:
    """Extract and merge all JSON objects from markdown code blocks."""
    matches = _JSON_BLOCK_RE.findall(content)
    if not matches:
        return None
    merged: dict[str, Any] = {}
    for raw in matches:
        try:
            merged.update(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return merged if merged else None


def strip_json_blocks(content: str) -> str:
    """Remove JSON code blocks from displayed message content."""
    return _JSON_BLOCK_RE.sub("", content).strip()
