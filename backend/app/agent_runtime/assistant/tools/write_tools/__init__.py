"""Assistant 写入工具 — DB 修改工具（Verify First）。

工具列表：
1. add_tool_to_agent（批量）
2. remove_tool_from_agent（批量）
3. add_middleware_to_agent（批量）
4. remove_middleware_from_agent（批量）
5. add_subagent_to_agent（批量）
6. remove_subagent_from_agent（批量）
7. add_skill_to_agent（批量）
8. remove_skill_from_agent（批量）
9. edit_system_prompt（局部修改）
10. update_system_prompt（整体替换）
11. update_model_config
12. update_middleware_config
13. update_chat_openers
14. update_agent_metadata
15. update_agent_identity_mode
16. update_recursion_limit
17. create_cron_schedule
18. update_cron_schedule
19. delete_cron_schedule
20. enable_cron_schedule
21. disable_cron_schedule
"""

from __future__ import annotations

import uuid

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.assistant.tools.write_tools.agent_config import build_agent_config_tools
from app.agent_runtime.assistant.tools.write_tools.composition import build_composition_tools
from app.agent_runtime.assistant.tools.write_tools.context import WriteToolContext
from app.agent_runtime.assistant.tools.write_tools.cron import build_cron_tools
from app.agent_runtime.assistant.tools.write_tools.tool_links import build_tool_link_tools
from app.database import async_session as async_session_factory


def build_write_tools(
    db: AsyncSession,  # noqa: ARG001 — kept for interface compatibility
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[StructuredTool]:
    """创建 18 个 Assistant 写入工具。

    每个工具每次调用时都创建并使用fresh DB 会话。
    LangGraph 智能体的工具执行时，构建阶段闭包中的 DB 会话
    可能已经关闭，因此每次调用都重新打开会话才安全。
    """
    # call-time global lookup: 测试会对本模块的 `async_session_factory` 进行
    # monkeypatch，因此不在 import 时绑定，而是在调用时读取模块全局变量
    # 并注入上下文。组模块只能使用 ctx.session_factory。
    ctx = WriteToolContext(
        session_factory=async_session_factory,
        agent_id=agent_id,
        user_id=user_id,
    )
    return [
        *build_tool_link_tools(ctx),
        *build_composition_tools(ctx),
        *build_agent_config_tools(ctx),
        *build_cron_tools(ctx),
    ]
