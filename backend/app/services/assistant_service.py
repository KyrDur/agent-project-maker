"""Assistant v2 服务 — 对话管理、SSE 流式传输。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Sequence

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import event_names
from app.agent_runtime.assistant.assistant_agent import build_assistant_agent
from app.agent_runtime.builder_i18n import get_locale, localized_stream, tr
from app.agent_runtime.streaming import format_sse, stream_agent_response
from app.schemas.conversation import Decision
from app.services.system_credential_resolver import SystemModelNotConfiguredError

logger = logging.getLogger(__name__)


@localized_stream
async def stream_assistant_message(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    thread_id: str,
    user_message: str,
    *,
    locale: str = "zh-CN",
) -> AsyncGenerator[str, None]:
    """通过 SSE 流式处理 Assistant 消息。

    原样复用现有聊天基础设施（stream_agent_response）（ADR-005 AD-6）。
    checkpointer 会自动管理历史记录，因此无需单独的会话表。
    """
    try:
        agent = await build_assistant_agent(db, agent_id, user_id, thread_id)
    except SystemModelNotConfiguredError as exc:
        # ADR-019: no .env fallback — surface a clear operator-action message
        # instead of crashing the SSE stream.
        logger.warning("Assistant model unconfigured: %s", exc)
        yield format_sse(
            event_names.ERROR,
            {
                "message": (tr("the_assistant_cannot_be_used_c11b21")),
                "code": "system_model_not_configured",
            },
        )
        return

    messages = [HumanMessage(content=user_message)]
    config = {"configurable": {"thread_id": thread_id, "ui_locale": get_locale()}}

    async for chunk in stream_agent_response(agent, messages, config):
        yield chunk


@localized_stream
async def stream_assistant_resume(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    thread_id: str,
    decisions: Sequence[Decision],
    *,
    locale: str = "zh-CN",
) -> AsyncGenerator[str, None]:
    try:
        agent = await build_assistant_agent(db, agent_id, user_id, thread_id)
    except SystemModelNotConfiguredError as exc:
        logger.warning("Assistant model unconfigured: %s", exc)
        yield format_sse(
            event_names.ERROR,
            {
                "message": (tr("the_assistant_cannot_be_used_c11b21")),
                "code": "system_model_not_configured",
            },
        )
        return

    decisions_payload = [decision.model_dump(exclude_none=True) for decision in decisions]
    config = {"configurable": {"thread_id": thread_id, "ui_locale": get_locale()}}

    async for chunk in stream_agent_response(
        agent,
        Command(resume={"decisions": decisions_payload}),
        config,
    ):
        yield chunk
