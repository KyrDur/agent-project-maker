"""Follow-up suggestion generation (composer ghost text).

Generates ONE short follow-up prompt the user is likely to send next, from the
tail of the conversation, using the operator-selected system LLM (ADR-019
``text_primary``). Fail-safe by design: any failure — unconfigured system
model, provider error, empty output — returns ``None`` and the frontend simply
doesn't show the ghost. This must never block or degrade the chat itself.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.conversation import Conversation
from app.services import chat_service
from app.services.system_credential_resolver import (
    SystemModelNotConfiguredError,
    resolve_system_model,
)

logger = logging.getLogger(__name__)

# 在 E2E scripted 部署中，即使没有 system credential，也返回固定建议，
# 以便对整条管线（endpoint → hook → ghost → 接受）进行确定性验证。
E2E_FOLLOWUP_SUGGESTION = "把刚才的回答整理成表格"

_MAX_TAIL_MESSAGES = 6
_MAX_MESSAGE_CHARS = 1500
_MAX_SUGGESTION_CHARS = 120

_SYSTEM_PROMPT = (
    "你是聊天输入框的后续请求建议助手。根据对话记录，用简体中文（zh-CN）"
    "给出一句用户接下来可能提出的请求。\n"
    "- 只输出建议本身，不加引号、编号或项目符号。\n"
    "- 控制在 60 个字以内，简短、明确且可执行。\n"
    "- 自然衔接助手刚刚完成的工作。"
)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _sanitize_suggestion(raw: str) -> str | None:
    """模型输出 → 单行建议。移除 bullet/引号/code fence 装饰 + 长度上限。"""

    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("```"):
            continue
        text = text.lstrip("-*•").strip()
        # 移除 "1. " / "1) " 一类编号前缀。
        head = text.split(" ", 1)
        if len(head) == 2 and head[0].rstrip(".)").isdigit():
            text = head[1].strip()
        text = text.strip('"“”‘’`').strip()
        if not text:
            continue
        if len(text) > _MAX_SUGGESTION_CHARS:
            text = text[:_MAX_SUGGESTION_CHARS].rstrip()
        return text
    return None


def _transcript_tail(messages: list[Any]) -> str | None:
    tail = [
        message
        for message in messages
        if getattr(message, "role", None) in {"user", "assistant"}
        and isinstance(getattr(message, "content", None), str)
        and message.content.strip()
    ][-_MAX_TAIL_MESSAGES:]
    if not tail:
        return None
    lines = []
    for message in tail:
        speaker = "用户" if message.role == "user" else "助理"
        lines.append(f"{speaker}: {message.content[:_MAX_MESSAGE_CHARS]}")
    return "\n".join(lines)


async def generate_followup_suggestion(
    db: AsyncSession,
    conversation: Conversation,
    user_id: uuid.UUID,
) -> str | None:
    """Return ONE follow-up suggestion for the conversation tail, or ``None``."""

    if settings.e2e_scripted_model_enabled:
        return E2E_FOLLOWUP_SUGGESTION

    try:
        resolved = await resolve_system_model(db, "builder", user_id)
    except SystemModelNotConfiguredError:
        return None

    try:
        messages = await chat_service.list_messages_from_checkpointer(db, conversation, user_id)
        transcript = _transcript_tail(messages)
        if transcript is None:
            return None

        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agent_runtime.model_factory import create_chat_model

        model = create_chat_model(
            resolved.provider,
            resolved.model_name,
            resolved.api_key,
            resolved.base_url,
            allow_env_fallback=False,
        )
        result = await model.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=f"对话记录:\n{transcript}\n\n后续请求建议:"),
            ]
        )
        return _sanitize_suggestion(_content_text(getattr(result, "content", "")))
    except Exception:  # noqa: BLE001 — 建议是 nice-to-have；不应阻塞聊天。
        logger.warning("followup suggestion generation failed", exc_info=True)
        return None
