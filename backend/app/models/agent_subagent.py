from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentSubAgentLink(Base):
    """Association: agent <-> agent (self-referential, parent → sub).

    parent_agent_id 可以调用（委派给）sub_agent_id。PK 是 (parent, sub) 复合键，
    因此相同 (parent, sub) link 只存在 1 次。按 position 进行 UI 排序。
    """

    __tablename__ = "agent_subagents"
    __table_args__ = (
        CheckConstraint(
            "parent_agent_id != sub_agent_id",
            name="ck_agent_subagents_no_self",
        ),
        Index("ix_agent_subagents_parent_agent_id", "parent_agent_id"),
    )

    parent_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sub_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )

    # 在 async 上下文中单独加载 link 时（例如 cascade delete 验证、直接查询单个 link），
    # 需要访问 sub_agent，因此 lazy="joined" 更安全。helpers/service 中显式的 selectinload
    # 用于避免 parent 侧 N+1，与这里的 joined 在不同路径上生效。
    sub_agent: Mapped[Agent] = relationship(
        "Agent",
        foreign_keys=[sub_agent_id],
        lazy="joined",
    )
