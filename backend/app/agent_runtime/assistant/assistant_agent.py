"""Assistant v2 智能体 — build_agent + 绑定 35 个工具。

将 assistant/prompt.md 加载为系统提示词，
并绑定 read/write/clarify 工具。
"""

from __future__ import annotations

import functools
import logging
import uuid
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.assistant.tools.clarify_tools import build_clarify_tools
from app.agent_runtime.assistant.tools.read_tools import build_read_tools
from app.agent_runtime.assistant.tools.write_tools import build_write_tools
from app.agent_runtime.builder_i18n import localized_prompt
from app.agent_runtime.checkpointer import get_checkpointer
from app.agent_runtime.model_factory import create_chat_model
from app.agent_runtime.runtime_component_builder import build_agent
from app.agent_runtime.runtime_policy import ASSISTANT_RUNTIME_POLICY
from app.services.system_credential_resolver import resolve_system_model

logger = logging.getLogger(__name__)

# Assistant 系统提示词文件路径
# __file__ = backend/app/agent_runtime/assistant/assistant_agent.py
# .parent = assistant/（与 prompt.md 位于同一目录）
_PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"


@functools.cache
def _load_system_prompt() -> str:
    """从文件加载 Assistant 系统提示词（已缓存）。"""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Assistant prompt file not found: %s, using fallback", _PROMPT_PATH)
        return (
            "You are Agent Project Maker Assistant, an AI that modifies existing "
            "agent configurations. Always VERIFY before MODIFY."
        )


def _assistant_write_interrupt_on(write_tools: list[Any]) -> dict[str, Any]:
    return {
        tool.name: {"allowed_decisions": ["approve", "edit", "reject"]}
        for tool in write_tools
        if isinstance(getattr(tool, "name", None), str) and tool.name
    }


async def build_assistant_agent(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    thread_id: str,
) -> Any:
    """创建 Assistant 智能体。

    Args:
        db: DB 会话（工具直接访问 DB）
        agent_id: 目标智能体 ID
        user_id: 用户 ID
        thread_id: 对话线程 ID（供 checkpointer 使用）

    Returns:
        CompiledStateGraph — build_agent 的返回值
    """
    # ADR-019: the assistant text model is the operator-selected ``builder``
    # role. Raises ``SystemModelNotConfiguredError`` if unset (surfaced by the
    # caller) — no silent ``.env`` fallback.
    resolved = await resolve_system_model(db, "builder", user_id)
    model: BaseChatModel = create_chat_model(
        resolved.provider,
        resolved.model_name,
        api_key=resolved.api_key,
        allow_env_fallback=False,
        base_url=resolved.base_url,
    )

    # 35 个工具 = 16 read + 18 write + 1 clarify
    read_tools = build_read_tools(db, agent_id, user_id)
    write_tools = build_write_tools(db, agent_id, user_id)
    clarify_tools = build_clarify_tools()
    tools = read_tools + write_tools + clarify_tools

    system_prompt = localized_prompt(_load_system_prompt())

    return build_agent(
        model=model,
        tools=tools,  # type: ignore[arg-type]  # StructuredTool 与 BaseTool 兼容（langchain runtime 运行 OK）
        system_prompt=system_prompt,
        middleware=[],
        interrupt_on=_assistant_write_interrupt_on(write_tools),
        checkpointer=get_checkpointer(),
        name=f"assistant_{str(agent_id)[:8]}",
        runtime_policy=ASSISTANT_RUNTIME_POLICY,
    )
