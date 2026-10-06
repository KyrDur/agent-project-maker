"""Personal model selections; credentials remain encrypted in the credential store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserLlmSetting(Base):
    __tablename__ = "user_llm_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_llm_settings_user_role"),
        CheckConstraint(
            "role IN ('builder', 'evaluation_generator', 'judge_optimizer', "
            "'text_primary', 'text_fallback', 'image')",
            name="ck_user_llm_settings_role",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
