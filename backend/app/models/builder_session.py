"""BuilderSession DB model — 保存 Builder v2 Build Session 状态。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.schemas.builder import BuilderStatus


class BuilderSession(Base):
    __tablename__ = "builder_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=BuilderStatus.BUILDING, nullable=False)
    current_phase: Mapped[int] = mapped_column(default=0, nullable=False)
    project_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    # 各 Phase 的中间结果（JSON 列）
    intent: Mapped[dict | None] = mapped_column(JSON)  # type: ignore[type-arg]
    tools_result: Mapped[list | None] = mapped_column(JSON)  # type: ignore[type-arg]
    middlewares_result: Mapped[list | None] = mapped_column(JSON)  # type: ignore[type-arg]
    system_prompt: Mapped[str | None] = mapped_column(Text)
    draft_config: Mapped[dict | None] = mapped_column(JSON)  # type: ignore[type-arg]

    # ``ON DELETE SET NULL`` — 即使 agent 被删除，builder session 仍会为审计/
    # history trail 保留，只断开 reference，并非 cascade。
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )

    user: Mapped[User] = relationship(  # type: ignore[name-defined]
        back_populates="builder_sessions"
    )
