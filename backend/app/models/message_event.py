from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

# W3-out M2: SSE turn lifecycle status. 通过 CHECK 约束，使用字符串而不是 Postgres ENUM
# 而不是 Postgres ENUM（alembic-friendly + dialect-agnostic）。
STREAMING_STATUS_VALUES = ("streaming", "completed", "failed")
STREAM_EVENT_ID_MAX_LENGTH = 255


class MessageEvent(Base):
    """SSE event trace for one assistant turn.

    Stores the full event sequence emitted during a single
    ``stream_agent_response`` call, keyed by the assistant message id.
    Foundation for W3-out (resume from ``last_event_id``) and W6 (shared
    page tool/skill chip rendering).

    One row per turn — edits and regenerates produce new rows ordered by
    ``created_at`` rather than overwriting.
    """

    __tablename__ = "message_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # ``stream_agent_response`` 的 msg_id（UUID 字符串）。也用作 SSE event id 前缀。
    assistant_msg_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # 已发布的 SSE 事件序列。每项 shape:
    #   {"id": "<msg_id>-<seq>", "event": "<name>", "data": {...}}
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # 最后发布的 SSE event id — W3-out resume 时 ``> last_event_id`` filter 的基准。
    last_event_id: Mapped[str | None] = mapped_column(
        String(STREAM_EVENT_ID_MAX_LENGTH), nullable=True
    )
    # W6 准确性 — 本 turn 中生成的 assistant message 的 parsed UUID 列表。
    # 与 ``MessageResponse.id`` 格式相同，因此 frontend 可直接匹配。
    # NULL 表示 m33 之前的 row，或 streaming 未暴露 message id。
    linked_message_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # External trace correlation for authenticated debug tooling. The public
    # /traces schema intentionally does not expose these fields.
    external_trace_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_trace_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
    # Stream 结束时间。None 表示进行中（Phase 1 仅在结束时记录一次，因此
    # 当前总是在创建时同时 set，但引入 W3-out 渐进式持久化后语义会分开）。
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # W3-out M2 — turn lifecycle:
    #   'streaming'  : 进行中。通过 partial flush 逐步追加 events。
    #   'completed'  : 正常结束（到达 message_end）。
    #   'failed'     : 异常/abort. last_event_id 是最后收到的事件。
    # 现有 row（m34 之前）由 server_default 'completed' 填充，回归为 0。
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="completed",
        default="completed",
    )
    # 每次进行中的 partial flush 都会更新。与 completed_at 不同，在 streaming 期间
    # 每次都用 NOW() bump（充当 heartbeat — 也可用于 stale broker GC 判定）。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )


class MessageEventChunk(Base):
    """Append-only payload chunks for a streaming assistant turn."""

    __tablename__ = "message_event_chunks"
    __table_args__ = (
        UniqueConstraint(
            "message_event_id",
            "first_event_id",
            name="uq_message_event_chunks_event_first_id",
        ),
        Index("ix_message_event_chunks_message_seq", "message_event_id", "seq_start"),
        Index("ix_message_event_chunks_assistant_seq", "assistant_msg_id", "seq_start"),
        Index("ix_message_event_chunks_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    message_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_msg_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq_start: Mapped[int] = mapped_column(Integer, nullable=False)
    seq_end: Mapped[int] = mapped_column(Integer, nullable=False)
    first_event_id: Mapped[str | None] = mapped_column(
        String(STREAM_EVENT_ID_MAX_LENGTH), nullable=True
    )
    last_event_id: Mapped[str | None] = mapped_column(
        String(STREAM_EVENT_ID_MAX_LENGTH), nullable=True
    )
    event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
