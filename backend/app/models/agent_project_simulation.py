"""项目试用会话：冻结版本和场景，独立保存状态及每轮证据。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.agent_project import utcnow


class AgentProjectSimulation(Base):
    __tablename__ = "agent_project_simulations"
    __table_args__ = (
        UniqueConstraint("project_id", "request_id", name="uq_simulation_request"),
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["agent_project_versions.project_id", "agent_project_versions.id"],
            name="fk_simulation_version_scope",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_project_versions.id"))
    scenario_id: Mapped[uuid.UUID]
    request_id: Mapped[uuid.UUID]
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    scenario_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    messages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    turns_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
