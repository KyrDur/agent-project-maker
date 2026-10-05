"""Trace storage — persist SSE event sequences per assistant turn.

W5 Phase 1: end-of-turn batch persistence. Events accumulate in a list during
``stream_agent_response`` and are flushed once when the stream completes (or
fails). Sufficient for W6 shared-page rendering.

W3-out M2: partial flush — ``append_events`` UPSERT 在 stream 进行中每 32 events
或 2 秒调用一次，逐步填充 ``status='streaming'`` row。
``finalize_turn`` 在 message_end / 正常结束 / 失败分支中调用一次，
将 ``status`` 更新为终止状态并附加 ``linked_message_ids``。
现有 ``record_turn`` 是 [DEPRECATED] backward-compat shim — 新调用路径
使用 ``append_events`` + ``finalize_turn`` 组合（W3-out M6 retrospective）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.agent_runtime.message_utils import parse_msg_id
from app.models.message_event import MessageEvent, MessageEventChunk

# Status enum for message_events.status — 与 DB CHECK 约束一致。
TraceStatus = Literal["streaming", "completed", "failed"]

logger = logging.getLogger(__name__)


def _extract_msg_id(events: list[dict[str, Any]]) -> str | None:
    """使用 ``message_start`` event 的 ``data.id`` 作为 assistant message id。

    若刚开始 stream 就发生 graph 错误，导致 ``message_start`` 未发出的异常情况，
    返回 ``None``，让 caller 分配新的 UUID。
    """
    for evt in events:
        if evt.get("event") == "message_start":
            data = evt.get("data") or {}
            value = data.get("id")
            if isinstance(value, str) and value:
                return value
    return None


def _resolve_linked_ids(
    conversation_id: uuid.UUID, raw_msg_ids: list[str] | None
) -> list[str] | None:
    if not raw_msg_ids:
        return None
    return [str(parse_msg_id(raw, conversation_id, idx)) for idx, raw in enumerate(raw_msg_ids)]


async def append_events(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    assistant_msg_id: str,
    events_chunk: list[dict[str, Any]],
    status: TraceStatus = "streaming",
    known_event_ids: set[str] | None = None,
) -> MessageEvent | None:
    """Partial flush — append event payload into chunk rows for the turn.

    W3-out M2 的核心 hot path。由 ``stream_agent_response`` 的 emit closure
    每 32 events 或 2 秒调用。通过 dedup-by-id 防止 boundary 重复
    （同一 chunk 因重试等到达两次）。

    Behavior:
    - 若 row 不存在则 INSERT。Parent ``events`` 为 legacy 兼容保持为空。
    - 若 row 存在，则 payload 以 append-only 方式 insert 到 ``message_event_chunks``。
    - ``last_event_id`` = ``events_chunk[-1]["id"]``（chunk 为空时 no-op）。
    - ``status`` 由 caller 显式指定。默认 'streaming'。
    - ``updated_at`` 由 model 的 ``onupdate=now()`` 自动更新
      （INSERT 时也应用 server_default）。
    - ``known_event_ids`` (BE-P5(d)): caller 维护的 run-scoped persisted
      event id 集。提供后可跳过每次 flush 都重新 SELECT 累计 chunk 全量
      O(T²/64) 的加载。**必须与 DB 状态一致** — caller 只将
      commit 成功部分加入集合；失败时下一次 flush 必须走重新加载路径（None），
      才不会丢失（通过 :func:`load_persisted_event_ids` seed）。

    Caller commits the session.

    Returns:
        Updated/inserted MessageEvent row, or ``None`` if ``events_chunk`` 为空。
    """
    if not events_chunk:
        return None

    last_id = events_chunk[-1].get("id") if events_chunk else None
    last_event_id = last_id if isinstance(last_id, str) and last_id else None

    existing = await db.execute(
        select(MessageEvent).where(MessageEvent.assistant_msg_id == assistant_msg_id)
    )
    record = existing.scalar_one_or_none()

    if record is None:
        record = MessageEvent(
            conversation_id=conversation_id,
            assistant_msg_id=assistant_msg_id,
            events=[],
            last_event_id=last_event_id,
            status=status,
            # completed_at 在 finalize_turn 中 set。streaming 期间为 None。
        )
        db.add(record)
        await db.flush()

    existing_ids = (
        known_event_ids
        if known_event_ids is not None
        else await _load_existing_event_ids(db, record)
    )
    new_events = [
        evt
        for evt in events_chunk
        if not (isinstance(evt.get("id"), str) and evt.get("id") in existing_ids)
    ]

    if not new_events and last_event_id == record.last_event_id and record.status == status:
        # Nothing changed — skip UPDATE to avoid useless WAL write.
        return record

    if new_events:
        seq_start = len(existing_ids) + 1
        seq_end = seq_start + len(new_events) - 1
        event_ids = [
            str(evt.get("id"))
            for evt in new_events
            if isinstance(evt.get("id"), str) and evt.get("id")
        ]
        db.add(
            MessageEventChunk(
                message_event_id=record.id,
                conversation_id=conversation_id,
                assistant_msg_id=assistant_msg_id,
                seq_start=seq_start,
                seq_end=seq_end,
                first_event_id=event_ids[0] if event_ids else None,
                last_event_id=event_ids[-1] if event_ids else None,
                event_ids=event_ids,
                events=list(new_events),
            )
        )
    if last_event_id:
        record.last_event_id = last_event_id
    record.status = status
    # ``onupdate=`` 会在 ORM flush 时更新 updated_at。
    return record


async def load_persisted_event_ids(db: AsyncSession, *, assistant_msg_id: str) -> set[str]:
    """BE-P5(d) seed — 一次加载 run 已有的全部 persisted event id。

    ``build_persist_callback`` 在第一次 flush 时用它 seed 缓存。若 row
    尚不存在（新 run），返回空集合。若 row 已存在（如同一 run_id 恢复），
    合并 legacy ``events`` + 所有 chunk 的 id，提供准确的 dedup 基准。
    """

    existing = await db.execute(
        select(MessageEvent).where(MessageEvent.assistant_msg_id == assistant_msg_id)
    )
    record = existing.scalar_one_or_none()
    if record is None:
        return set()
    return await _load_existing_event_ids(db, record)


async def _load_existing_event_ids(db: AsyncSession, record: MessageEvent) -> set[str]:
    ids: set[str] = {
        evt.get("id")  # type: ignore[misc]
        for evt in (record.events or [])
        if isinstance(evt.get("id"), str)
    }
    result = await db.execute(
        select(MessageEventChunk.event_ids)
        .where(MessageEventChunk.message_event_id == record.id)
        .order_by(MessageEventChunk.seq_start)
    )
    for chunk_ids in result.scalars().all():
        ids.update(str(event_id) for event_id in (chunk_ids or []) if event_id)
    return ids


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for event in events:
        event_id = event.get("id")
        if isinstance(event_id, str) and event_id:
            if event_id in seen:
                continue
            seen.add(event_id)
        merged.append(event)
    return merged


async def load_events(db: AsyncSession, record: MessageEvent) -> list[dict[str, Any]]:
    """Return legacy row events plus append-only chunk events, deduped by id."""

    events: list[dict[str, Any]] = list(record.events or [])
    result = await db.execute(
        select(MessageEventChunk.events)
        .where(MessageEventChunk.message_event_id == record.id)
        .order_by(MessageEventChunk.seq_start, MessageEventChunk.created_at)
    )
    for chunk_events in result.scalars().all():
        events.extend(chunk_events or [])
    return _dedupe_events(events)


async def load_events_many(
    db: AsyncSession, records: Sequence[MessageEvent]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Batch variant of :func:`load_events` — one IN query for every record.

    The poll-path interrupt hydration previously called ``load_events`` per
    MessageEvent row (BE-P1: 1+N queries per GET /messages on long
    conversations). The global (seq_start, created_at) ordering preserves each
    record's own chunk order, so per-record extend matches the single-record
    path exactly.
    """

    by_record: dict[uuid.UUID, list[dict[str, Any]]] = {
        record.id: list(record.events or []) for record in records
    }
    if not by_record:
        return {}
    result = await db.execute(
        select(MessageEventChunk.message_event_id, MessageEventChunk.events)
        .where(MessageEventChunk.message_event_id.in_(by_record.keys()))
        .order_by(MessageEventChunk.seq_start, MessageEventChunk.created_at)
    )
    for message_event_id, chunk_events in result.all():
        bucket = by_record.get(message_event_id)
        if bucket is not None:
            bucket.extend(chunk_events or [])
    return {record_id: _dedupe_events(events) for record_id, events in by_record.items()}


async def finalize_turn(
    db: AsyncSession,
    *,
    assistant_msg_id: str,
    status: TraceStatus = "completed",
    raw_msg_ids: list[str] | None = None,
    conversation_id: uuid.UUID | None = None,
    external_trace_provider: str | None = None,
    external_trace_id: str | None = None,
    external_trace_url: str | None = None,
) -> MessageEvent | None:
    """Mark a streaming turn as finished and attach linked message ids.

    W3-out M2 — 吸收 ``_persist_trace`` 的 final-write 职责。正常结束
    （message_end）、异常、GraphInterrupt 都在 finally 块中调用。

    Behavior:
    - row 不存在 → 返回 ``None``（events 为 0，因此 append_events 从未被
      调用的异常情况。caller 决定是否使用 record_turn fallback）。
    - row 存在 → 更新 status、completed_at、updated_at。提供 raw_msg_ids 时
      更新 linked_message_ids（NULL 覆盖 OK）。

    ``conversation_id`` 仅用于 raw_msg_ids → linked_ids 转换。若 row
    已存在，可使用 row 的 conversation_id，因此 caller 可省略。

    Caller commits the session.
    """
    existing = await db.execute(
        select(MessageEvent).where(MessageEvent.assistant_msg_id == assistant_msg_id)
    )
    record = existing.scalar_one_or_none()
    if record is None:
        return None

    record.status = status
    record.completed_at = datetime.now(UTC).replace(tzinfo=None)
    if raw_msg_ids:
        conv_id = conversation_id or record.conversation_id
        record.linked_message_ids = _resolve_linked_ids(conv_id, raw_msg_ids)
    if external_trace_provider or external_trace_id or external_trace_url:
        record.external_trace_provider = external_trace_provider
        record.external_trace_id = external_trace_id
        record.external_trace_url = external_trace_url
    return record


async def record_turn(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    events: list[dict[str, Any]],
    raw_msg_ids: list[str] | None = None,
    status: TraceStatus = "completed",
    external_trace_provider: str | None = None,
    external_trace_id: str | None = None,
    external_trace_url: str | None = None,
) -> MessageEvent | None:
    """[DEPRECATED — 禁止新增调用方] one-shot turn persistence shim.

    截至 W3-out 轨道结束（M6），production 调用方只有 1 处：
    ``routers/conversations._finalize_trace`` 的 fallback path（``finalize_turn``
    找不到 row 且 ``trace_sink`` 中积累了 events 的异常结束情况）。
    其余调用方全部是测试（``test_trace_storage.py`` 12 处 + ``test_shares_
    router.py`` seed）。

    **新代码必须**使用 ``append_events``（partial flush）+ ``finalize_turn``
    组合。新增 ``record_turn`` 调用会分散 invariant（``IntegrityError`` 保证
    vs ``append_events`` UPSERT），增加调试难度。

    移除步骤（单独 PR）：
    1. 给 ``finalize_turn`` 增加 ``events_fallback: list | None = None`` 选项
       — 吸收 caller 在 row 缺失时用 events insert 新 row + IntegrityError invariant
       保持分支。
    2. 将唯一 production 调用方改为调用 ``finalize_turn(events_fallback=trace_sink)``，
       完成迁移。
    3. 将 test_trace_storage.py 12 处迁移为 ``finalize_turn(events_fallback=...)`` 或
       ``append_events`` 模式。
    4. 删除 ``record_turn``。

    --- 现有 contract（当前调用方依赖）---
    No-op when ``events`` is empty (interrupt before message_start, etc.).
    Caller commits the session.

    ``raw_msg_ids``（W6 准确性）：该 turn 中暴露的 langchain message raw id
    列表（已去重，保留 streaming 顺序）。通过 ``parse_msg_id`` 转为 UUID 后
    存入 ``linked_message_ids`` 列。None 时该列为 NULL。
    """
    if not events:
        return None

    msg_id = _extract_msg_id(events) or str(uuid.uuid4())
    last_event_id = events[-1].get("id")
    last_id = last_event_id if isinstance(last_event_id, str) and last_event_id else None

    linked_ids = _resolve_linked_ids(conversation_id, raw_msg_ids)

    now = datetime.now(UTC).replace(tzinfo=None)
    record = MessageEvent(
        conversation_id=conversation_id,
        assistant_msg_id=msg_id,
        events=events,
        last_event_id=last_id,
        linked_message_ids=linked_ids,
        external_trace_provider=external_trace_provider,
        external_trace_id=external_trace_id,
        external_trace_url=external_trace_url,
        status=status,
        completed_at=now,
        # ORM-level explicit set — 除 server_default(now()) 外，确保 SQLite/PG
        # 一致性和回归 guard。（model 的 default lambda + server_default 会
        # 填充，但这里作为双重保险。）
        updated_at=now,
    )
    db.add(record)
    return record


async def get_traces_for_conversation(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[MessageEvent]:
    """Return all turn traces for a conversation, oldest-first."""
    result = await db.execute(
        select(MessageEvent)
        .where(MessageEvent.conversation_id == conversation_id)
        .order_by(MessageEvent.created_at)
    )
    records = list(result.scalars().all())
    for record in records:
        set_committed_value(record, "events", await load_events(db, record))
    return records


async def get_trace_by_msg_id(db: AsyncSession, assistant_msg_id: str) -> MessageEvent | None:
    """Lookup a single turn trace by its assistant message id."""
    result = await db.execute(
        select(MessageEvent).where(MessageEvent.assistant_msg_id == assistant_msg_id)
    )
    record = result.scalar_one_or_none()
    if record is not None:
        set_committed_value(record, "events", await load_events(db, record))
    return record
