"""Assistant 工具公共辅助函数 — 去除 Agent eager-load 查询重复。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.mcp_tool import AgentMcpToolLink
from app.models.skill import AgentSkillLink
from app.models.tool import AgentToolLink


async def get_agent_with_eager_load(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Agent | None:
    """查询 Agent，并一并加载关联关系（model、tool/mcp/skill links、sub_agent_links）。

    read_tools、write_tools 两侧共同使用。
    """
    # AgentSubAgentLink.sub_agent 为 lazy="joined"，因此加载 link 时会自动一并加载 —
    # 此处额外 selectinload 属于重复。
    result = await db.execute(
        select(Agent)
        .where(Agent.id == agent_id, Agent.user_id == user_id)
        .options(
            selectinload(Agent.model),
            selectinload(Agent.tool_links).selectinload(AgentToolLink.tool),
            selectinload(Agent.mcp_tool_links).selectinload(AgentMcpToolLink.mcp_tool),
            selectinload(Agent.skill_links).selectinload(AgentSkillLink.skill),
            selectinload(Agent.sub_agent_links),
        )
    )
    return result.scalar_one_or_none()
