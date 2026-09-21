"""Project storage around existing agents; versions are append-only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AgentProject(Base):
    __tablename__ = "agent_projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), unique=True
    )
    builder_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("builder_sessions.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(100))
    requirements_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    eval_spec_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AgentProjectVersion(Base):
    __tablename__ = "agent_project_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_project_version_scope"),
        UniqueConstraint("project_id", "request_id", name="uq_project_version_request"),
        UniqueConstraint("project_id", "version_number", name="uq_agent_project_version_number"),
        CheckConstraint("version_number > 0", name="ck_agent_project_version_positive"),
        CheckConstraint(
            "status IN ('original', 'candidate', 'accepted', 'rejected')",
            name="ck_agent_project_version_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_projects.id", ondelete="CASCADE")
    )
    version_number: Mapped[int]
    request_id: Mapped[uuid.UUID | None]
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_project_versions.id")
    )
    status: Mapped[str] = mapped_column(String(20))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    change_summary: Mapped[str | None] = mapped_column(Text)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


@event.listens_for(AgentProjectVersion, "before_update")
def prevent_version_update(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Agent project versions are immutable; create a new version")


class AgentProjectEvalSet(Base):
    __tablename__ = "agent_project_eval_sets"
    __table_args__ = (UniqueConstraint("project_id", "id", name="uq_project_eval_set_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    rubric_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evaluation_focus_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    evaluation_focus_reason: Mapped[str | None] = mapped_column(Text)
    cases_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    frozen: Mapped[bool] = mapped_column(default=False, server_default="false")
    quality_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AgentProjectEvalRun(Base):
    __tablename__ = "agent_project_eval_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["agent_project_versions.project_id", "agent_project_versions.id"],
            name="fk_eval_run_version_scope",
        ),
        ForeignKeyConstraint(
            ["project_id", "eval_set_id"],
            ["agent_project_eval_sets.project_id", "agent_project_eval_sets.id"],
            name="fk_eval_run_set_scope",
        ),
        UniqueConstraint("project_id", "request_id", name="uq_project_eval_run_request"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_project_eval_run_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_projects.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_project_versions.id"))
    eval_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_project_eval_sets.id"))
    status: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[uuid.UUID | None]
    cases_snapshot_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    dataset_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    results_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    pass_rate: Mapped[float | None]
    bad_cases_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    comparison_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None]
