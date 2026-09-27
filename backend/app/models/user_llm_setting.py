"""Private model selection for each user's project roles."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.agent_project import utcnow

USER_LLM_ROLES = ("builder", "evaluation_generator", "judge_optimizer")


class UserLlmSetting(Base):
    __tablename__ = "user_llm_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_llm_role"),
        CheckConstraint(
            "role IN ('builder', 'evaluation_generator', 'judge_optimizer')",
            name="ck_user_llm_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(40))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credentials.id", ondelete="SET NULL")
    )
    model_name: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
