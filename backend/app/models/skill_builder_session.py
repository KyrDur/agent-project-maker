from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.skill import Skill
    from app.models.user import User

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

SKILL_BUILDER_MODES = ("create", "improve")
# v2 状态机（Skill Studio phase 1）：active → confirming → completed；离开则
# abandoned（GC 对象）。collecting/drafting/review/failed/cancelled 是旧 one-pass
# flow 的 legacy 值 — 为兼容现有 row 而保留。
SKILL_BUILDER_STATUSES = (
    "active",
    "collecting",
    "drafting",
    "review",
    "confirming",
    "completed",
    "failed",
    "cancelled",
    "abandoned",
)


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SkillBuilderSession(Base):
    __tablename__ = "skill_builder_sessions"
    __table_args__ = (
        Index("ix_skill_builder_sessions_user_updated", "user_id", "updated_at"),
        Index("ix_skill_builder_sessions_finalized_skill", "finalized_skill_id"),
        Index("ix_skill_builder_sessions_source_skill", "source_skill_id"),
        Index("ix_skill_builder_sessions_conversation", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="create",
        server_default="create",
    )
    source_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
    )
    base_skill_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_snapshot: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="collecting",
        server_default="collecting",
    )
    current_phase: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    messages: Mapped[list[JsonValue] | None] = mapped_column(JSON, nullable=True)
    intent: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    draft_package: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    compatibility_result: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    changelog_draft: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    eval_result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    trigger_eval_result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    finalized_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
    )
    # v2（技能构建器聊天）：构建器对话 = 隐藏智能体的真实 conversation.
    # 即使对话被删除，也通过 SET NULL. 让会话保留。
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ADR-018 相对路径 — 以 data_root 为基准（例如 ``skill-drafts/<session_id>``）。
    draft_workspace_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # AD-4 scoped consent：tool name → consent metadata（在 M4 中记录）。
    tool_consents: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        onupdate=utc_now_naive,
        nullable=False,
    )

    user: Mapped[User] = relationship()
    source_skill: Mapped[Skill | None] = relationship(foreign_keys=[source_skill_id])
    finalized_skill: Mapped[Skill | None] = relationship(foreign_keys=[finalized_skill_id])
