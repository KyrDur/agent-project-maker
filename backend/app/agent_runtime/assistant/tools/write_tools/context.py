"""Assistant 写入工具 — 共享上下文。

不使用闭包捕获(agent_id/user_id/async_session_factory)，而是通过显式对象传递。
`session_factory` 由 `build_write_tools` 在调用时读取包级全局
`async_session_factory` 并注入（保留测试 monkeypatch 表面 —
如果组模块直接对 `async_session_factory` 执行 import，会绕过 patch，因此禁止）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.assistant.tools.helpers import get_agent_with_eager_load
from app.models.agent import Agent


@dataclass(frozen=True)
class WriteToolContext:
    """写入工具组构建器共享的执行上下文。"""

    session_factory: Callable[[], AsyncSession]
    agent_id: uuid.UUID
    user_id: uuid.UUID


async def get_agent_with_session(
    ctx: WriteToolContext,
    session: AsyncSession,
) -> Agent | None:
    return await get_agent_with_eager_load(session, ctx.agent_id, ctx.user_id)
