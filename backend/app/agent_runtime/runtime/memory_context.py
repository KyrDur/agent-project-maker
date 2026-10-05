"""长期记忆上下文加载 + 回忆 brief + 写入策略（BE-S10 拆分）。

注意：``memory_service``/DB session 的函数内局部 import 保持现有代码不变
— 改为参数注入反转属于 BE-S4(Stage 5) 工作，此处仅做纯移动。
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

from app.agent_runtime.runtime_config import AgentConfig

logger = logging.getLogger(__name__)


def _parse_uuid(value: str | None) -> _uuid.UUID | None:
    if not value:
        return None
    try:
        return _uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


# 回忆 chip payload 中携带的记忆内容预览上限 — 全文在 memory 设置页面中
# 查看，stream 事件仅携带可识别的一行内容。
_RECALLED_MEMORY_PREVIEW_CHARS = 200


def _recalled_memory_briefs(records: list[Any]) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    for record in records:
        content = str(record.content or "").strip()
        if len(content) > _RECALLED_MEMORY_PREVIEW_CHARS:
            content = content[:_RECALLED_MEMORY_PREVIEW_CHARS] + "…"
        briefs.append(
            {
                "id": str(record.id),
                "scope": record.scope,
                "content": content,
            }
        )
    return briefs


async def _load_memory_context(cfg: AgentConfig) -> tuple[str, list[dict[str, Any]]]:
    """Load the long-term memory prompt block plus recall briefs.

    Returns ``(prompt, briefs)`` — ``briefs`` feed the ``moldy.memory_recalled``
    stream-head event so the chat can show which memories informed this run.
    """

    user_uuid = _parse_uuid(cfg.user_id)
    if user_uuid is None:
        return "", []
    agent_uuid = _parse_uuid(cfg.agent_id)
    try:
        from app.database import async_session as _async_session_factory
        from app.services import memory_service

        async with _async_session_factory() as db:
            policy = await memory_service.resolve_effective_policy(
                db,
                user_id=user_uuid,
                agent_id=agent_uuid,
            )
            if not policy.read_enabled:
                return "", []
            records = await memory_service.list_runtime_memory_records(
                db,
                user_id=user_uuid,
                agent_id=agent_uuid,
                allowed_scopes=policy.allowed_scopes,
            )
            prompt = memory_service.render_memory_prompt(records)
            return prompt, _recalled_memory_briefs(records) if prompt else []
    except Exception:  # noqa: BLE001 — memory is helpful context, not a hard runtime dependency
        logger.warning("memory prompt load failed", exc_info=True)
        return "", []


async def _memory_write_policy_for_run(cfg: AgentConfig, *, is_trigger_mode: bool) -> str:
    user_uuid = _parse_uuid(cfg.user_id)
    if user_uuid is None:
        return "off"
    agent_uuid = _parse_uuid(cfg.agent_id)
    try:
        from app.database import async_session as _async_session_factory
        from app.services import memory_service

        async with _async_session_factory() as db:
            policy = await memory_service.resolve_effective_policy(
                db,
                user_id=user_uuid,
                agent_id=agent_uuid,
            )
            return policy.trigger_write_policy if is_trigger_mode else policy.write_policy
    except Exception:  # noqa: BLE001 — memory writes are optional runtime affordances
        logger.warning("memory write policy load failed", exc_info=True)
        return "off"
