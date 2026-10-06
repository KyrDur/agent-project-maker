"""W3-out M3 — GET /api/conversations/{id}/stream resume endpoint。

验证4个分支（plan 文件 ``M3 — GET resume endpoint``）：
- 场景 A: live attach (broker hit) → 以 ``X-Resume-Mode: live`` 将 broker
  buffer + 后续 publish 传入 stream
- 场景 B: replay only (broker miss + DB row completed) → 以 ``X-Resume-Mode:
  replay`` 仅 emit events slice
- 场景 C: stale streaming (broker miss + DB row status='streaming') →
  emit events 后发布 ``event: stale`` marker
- 场景 D: HiTL interrupt pending → ``409 RESUME_INTERRUPT_PENDING``

所有 guard 分支统一为 ``404 RESUME_NOT_FOUND`` 单一响应（rules/security.md
— 防止 enumeration oracle）。分支区分仅通过服务器日志：
- conv 不存在
- ownership 失败（其他 user 的 agent）
- DB row 不存在
- broker live 但 conv_id 不一致（cross-tenant）
- DB row 属于其他 conversation

若 query 为空，``Last-Event-ID`` header 作为 fallback。

W3-out M6 — POST → GET roundtrip 集成。上面的 router 单元场景通过合成方式注入 broker /
DB row，而 M6 会真正通过 ``POST /messages`` 注册 broker，
将 partial flush 写入真实 DB（in-memory aiosqlite），随后通过 ``GET
/stream`` 接续，以捕捉 cross-handler invariant（live attach 过程中
abort、强制 evict broker 后 DB replay、finalize 未执行时 stale、interrupt
留在 DB 中时 resume）。关键是将 ``async_session`` monkeypatch 为 TestSession —
如果 partial flush / finalize_turn 使用的不是与 conftest in-memory DB 相同的
engine，GET 侧 ``trace_storage.get_trace_by_msg_id`` 会得到空结果并
落入 RESUME_NOT_FOUND。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.agent_runtime import event_broker
from app.agent_runtime.event_names import (
    CONTENT_DELTA,
    INTERRUPT,
    MESSAGE_END,
    MESSAGE_START,
    STALE,
)
from app.agent_runtime.streaming import format_sse
from app.models.message_event import MessageEvent
from tests.conftest import TestSession
from tests.integration._seed import seed_conversation_with_agent


async def _seed_conv() -> uuid.UUID:
    return await seed_conversation_with_agent(agent_name="Resume Agent", conv_title="Resume Conv")


def _parse_sse_events(body: str) -> list[dict[str, str]]:
    """Split a multi-event SSE payload into ``{event, id?, data}`` dicts."""
    events: list[dict[str, str]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        evt: dict[str, str] = {}
        for line in chunk.splitlines():
            if ":" not in line:
                continue
            field, _, value = line.partition(":")
            evt[field.strip()] = value.lstrip()
        if evt:
            events.append(evt)
    return events


# ---------------------------------------------------------------------------
# Scenario A — live broker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_live_broker_replays_buffer_and_streams_tail(
    client: AsyncClient,
) -> None:
    """broker live → 传递 buffered events + close 时自然结束。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())

    broker = event_broker.registry.get_or_create(run_id, conversation_id=str(conv_id))
    # Pre-publish two events so the GET request can replay them on subscribe.
    broker.publish_nowait(
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id, "role": "assistant"}}
    )
    broker.publish_nowait(
        {"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "hello"}}
    )

    async def push_tail() -> None:
        # Let the GET request register its listener before we publish more.
        await asyncio.sleep(0.05)
        broker.publish_nowait(
            {"id": f"{run_id}-3", "event": "content_delta", "data": {"delta": " world"}}
        )
        await asyncio.sleep(0.01)
        broker.publish_nowait(
            {
                "id": f"{run_id}-4",
                "event": "message_end",
                "data": {"content": "hello world", "usage": {}},
            }
        )
        # Close so the subscribe iterator exits.
        broker.close()

    pusher = asyncio.create_task(push_tail())
    try:
        async with client.stream(
            "GET",
            f"/api/conversations/{conv_id}/stream",
            params={"run_id": run_id},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["x-run-id"] == run_id
            assert resp.headers["x-resume-mode"] == "live"
            body = await resp.aread()
    finally:
        await pusher

    events = _parse_sse_events(body.decode())
    deltas = [json.loads(e["data"])["delta"] for e in events if e.get("event") == "content_delta"]
    assert deltas == ["hello", " world"]
    assert any(e.get("event") == "message_end" for e in events)


@pytest.mark.asyncio
async def test_resume_live_broker_after_id_skips_already_seen(
    client: AsyncClient,
) -> None:
    """仅 replay ``last_event_id`` 之后的事件。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())

    broker = event_broker.registry.get_or_create(run_id, conversation_id=str(conv_id))
    broker.publish_nowait({"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}})
    broker.publish_nowait({"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "a"}})
    broker.publish_nowait({"id": f"{run_id}-3", "event": "content_delta", "data": {"delta": "b"}})

    # Close after the GET subscribes — closing first would route the request
    # to the DB-replay branch (broker.is_closed → broker miss).
    async def close_after_subscribe() -> None:
        await asyncio.sleep(0.05)
        broker.close()

    closer = asyncio.create_task(close_after_subscribe())
    try:
        async with client.stream(
            "GET",
            f"/api/conversations/{conv_id}/stream",
            params={"run_id": run_id, "last_event_id": f"{run_id}-2"},
        ) as resp:
            assert resp.status_code == 200
            body = await resp.aread()
    finally:
        await closer

    events = _parse_sse_events(body.decode())
    deltas = [json.loads(e["data"])["delta"] for e in events if e.get("event") == "content_delta"]
    assert deltas == ["b"], "should only emit events after last_event_id"


# ---------------------------------------------------------------------------
# Scenario B — replay only (broker miss + DB completed row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_replay_completed_row(client: AsyncClient) -> None:
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {
            "id": f"{run_id}-1",
            "event": "message_start",
            "data": {"id": run_id, "role": "assistant"},
        },
        {"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "hello"}},
        {"id": f"{run_id}-3", "event": "message_end", "data": {"content": "hello", "usage": {}}},
    ]

    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-3",
                status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["x-resume-mode"] == "replay"
        assert resp.headers["x-run-id"] == run_id
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    assert [e.get("event") for e in events] == ["message_start", "content_delta", "message_end"]
    assert all(e.get("event") != "stale" for e in events)


@pytest.mark.asyncio
async def test_resume_replay_after_id_slices_correctly(
    client: AsyncClient,
) -> None:
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
        {"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "a"}},
        {"id": f"{run_id}-3", "event": "content_delta", "data": {"delta": "b"}},
        {"id": f"{run_id}-4", "event": "message_end", "data": {"content": "ab", "usage": {}}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-4",
                status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id, "last_event_id": f"{run_id}-2"},
    ) as resp:
        assert resp.status_code == 200
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    deltas = [
        json.loads(e["data"]).get("delta") for e in events if e.get("event") == "content_delta"
    ]
    assert deltas == ["b"]


@pytest.mark.asyncio
async def test_resume_replay_header_is_case_insensitive(
    client: AsyncClient,
) -> None:
    """部分 reverse proxy 会以 lowercase 传递 header — alias 匹配回归。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
        {"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "a"}},
        {"id": f"{run_id}-3", "event": "content_delta", "data": {"delta": "b"}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-3",
                status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
        headers={"last-event-id": f"{run_id}-2"},  # lowercase
    ) as resp:
        assert resp.status_code == 200
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    deltas = [
        json.loads(e["data"]).get("delta") for e in events if e.get("event") == "content_delta"
    ]
    assert deltas == ["b"]


@pytest.mark.asyncio
async def test_resume_replay_uses_last_event_id_header_fallback(
    client: AsyncClient,
) -> None:
    """Query 为空时 fallback 到 ``Last-Event-ID`` header。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
        {"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "a"}},
        {"id": f"{run_id}-3", "event": "content_delta", "data": {"delta": "b"}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-3",
                status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
        headers={"Last-Event-ID": f"{run_id}-2"},
    ) as resp:
        assert resp.status_code == 200
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    deltas = [
        json.loads(e["data"]).get("delta") for e in events if e.get("event") == "content_delta"
    ]
    assert deltas == ["b"]


# ---------------------------------------------------------------------------
# Scenario C — stale streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_replay_skips_corrupt_event_without_name(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """M-2: ``event`` 字段为空的 corrupt row 条目禁止 silent emit。"""
    import logging

    caplog.set_level(logging.WARNING, logger="app.routers.conversation_messages")
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
        # corrupt row — 缺少 event 字段
        {"id": f"{run_id}-2", "data": {"delta": "??"}},
        {"id": f"{run_id}-3", "event": "content_delta", "data": {"delta": "ok"}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-3",
                status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        assert resp.status_code == 200
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    # corrupt evt 不 emit — 只有 message_start + content_delta(ok)。
    assert [e.get("event") for e in events] == ["message_start", "content_delta"]
    assert any("stream_resume skip corrupt evt" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_resume_stale_payload_falls_back_when_last_event_id_null(
    client: AsyncClient,
) -> None:
    """M-3: row.last_event_id 为 None 时 fallback 到 events 最后一个 id。

    如果两者都没有，则分支到 ``reason='broker_lost_no_id'``，避免 client NPE。
    """
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=None,  # corrupt row — last_event_id 未填充
                status="streaming",
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    stale = next(e for e in events if e.get("event") == "stale")
    stale_data = json.loads(stale["data"])
    # 成功 fallback 到 events 最后一个 id。
    assert stale_data["last_event_id"] == f"{run_id}-1"
    assert stale_data["reason"] == "broker_lost"


@pytest.mark.asyncio
async def test_resume_stale_payload_no_id_when_events_empty_after_slice(
    client: AsyncClient,
) -> None:
    """events 为空且 stale → ``broker_lost_no_id`` reason。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=[],  # 空 events
                last_event_id=None,
                status="streaming",
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    stale = next(e for e in events if e.get("event") == "stale")
    stale_data = json.loads(stale["data"])
    assert stale_data["last_event_id"] is None
    assert stale_data["reason"] == "broker_lost_no_id"


@pytest.mark.asyncio
async def test_resume_stale_streaming_emits_marker(
    client: AsyncClient,
) -> None:
    """broker miss + DB status='streaming' → events 后发布 ``event: stale``。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
        {"id": f"{run_id}-2", "event": "content_delta", "data": {"delta": "hi"}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-2",
                status="streaming",
            )
        )
        await db.commit()

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["x-resume-mode"] == "replay"
        body = await resp.aread()

    events = _parse_sse_events(body.decode())
    assert events[-1]["event"] == "stale"
    stale_data = json.loads(events[-1]["data"])
    assert stale_data["reason"] == "broker_lost"
    assert stale_data["last_event_id"] == f"{run_id}-2"


# ---------------------------------------------------------------------------
# Scenario D — HiTL interrupt pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_interrupt_pending_returns_409(
    client: AsyncClient,
) -> None:
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    events_payload = [
        {"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}},
        {"id": f"{run_id}-2", "event": "interrupt", "data": {"interrupt_id": "abc"}},
    ]
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=run_id,
                events=events_payload,
                last_event_id=f"{run_id}-2",
                status="streaming",
            )
        )
        await db.commit()

    resp = await client.get(
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RESUME_INTERRUPT_PENDING"


# ---------------------------------------------------------------------------
# Error gates — 全部统一为 RESUME_NOT_FOUND（防止 enumeration oracle）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_missing_run_id_returns_404(client: AsyncClient) -> None:
    conv_id = await _seed_conv()
    resp = await client.get(
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RESUME_NOT_FOUND"


@pytest.mark.asyncio
async def test_resume_db_row_belongs_to_other_conversation_returns_404(
    client: AsyncClient,
) -> None:
    """DB row 的 ``conversation_id`` 与 URL 不同则返回 404（防止 oracle）。"""
    conv_a = await _seed_conv()
    conv_b = await _seed_conv()
    run_id = str(uuid.uuid4())
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_a,
                assistant_msg_id=run_id,
                events=[{"id": f"{run_id}-1", "event": "message_start", "data": {"id": run_id}}],
                last_event_id=f"{run_id}-1",
                status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db.commit()

    resp = await client.get(
        f"/api/conversations/{conv_b}/stream",
        params={"run_id": run_id},
    )
    # 外部响应应与 row 不存在的情况相同（RESUME_NOT_FOUND）。
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RESUME_NOT_FOUND"


@pytest.mark.asyncio
async def test_resume_live_broker_belongs_to_other_conversation_returns_404(
    client: AsyncClient,
) -> None:
    """broker live 但 broker.conversation_id 与 URL 不同则返回 404。"""
    conv_a = await _seed_conv()
    conv_b = await _seed_conv()
    run_id = str(uuid.uuid4())
    # 为 conv_a 注册 live broker。
    event_broker.registry.get_or_create(run_id, conversation_id=str(conv_a))
    # 用 conv_b URL 执行 GET → 在 broker live 分支中 conv_id mismatch。
    resp = await client.get(
        f"/api/conversations/{conv_b}/stream",
        params={"run_id": run_id},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RESUME_NOT_FOUND"


@pytest.mark.asyncio
async def test_resume_live_broker_with_none_conversation_id_returns_404(
    client: AsyncClient,
) -> None:
    """broker.conversation_id 为 None 时 fail-closed → 404。"""
    conv_id = await _seed_conv()
    run_id = str(uuid.uuid4())
    # 故意省略 conv_id 的 broker — 模拟异常注册 path。
    event_broker.registry.get_or_create(run_id, conversation_id=None)

    resp = await client.get(
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RESUME_NOT_FOUND"


@pytest.mark.asyncio
async def test_resume_unknown_conversation_returns_404(
    client: AsyncClient,
) -> None:
    """Unknown conv_id → 404 RESUME_NOT_FOUND（同样为单一响应）。"""
    resp = await client.get(
        f"/api/conversations/{uuid.uuid4()}/stream",
        params={"run_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RESUME_NOT_FOUND"


@pytest.mark.asyncio
async def test_resume_unknown_conversation_logs_unowned_reason(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """conv 存在 X 与 ownership 失败已通过单一 join 合并，因此 reason 也使用
    ``conv_unowned_or_missing`` 单一标签 — 减少 round-trip + 强化 oracle 防护。"""
    import logging

    caplog.set_level(logging.INFO, logger="app.routers.conversation_messages")
    resp = await client.get(
        f"/api/conversations/{uuid.uuid4()}/stream",
        params={"run_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert any(
        "stream_resume reject" in r.message and "reason=conv_unowned_or_missing" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_resume_logs_reject_reason(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """guard 分支对外统一响应，但服务器日志应能通过 reason 区分。"""
    import logging

    caplog.set_level(logging.INFO, logger="app.routers.conversation_messages")
    conv_id = await _seed_conv()
    resp = await client.get(
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    # 应留下 reason=row_missing 分支日志（conv 存在 + DB row 不存在）。
    assert any(
        "stream_resume reject" in r.message and "reason=row_missing" in r.message
        for r in caplog.records
    )


# N-3（client disconnect → listener cleanup）、gap（multi-listener fan-out /
# ring buffer overflow + after_id evict）都依赖 unit-level，因此
# 在 tests/agent_runtime/test_event_broker.py 中直接验证 broker AsyncGenerator
# （httpx ASGITransport 的 disconnect 时机不确定，若用
# router 集成测试捕捉会有 hang 风险）。multi-listener fan-out 与 ring
# overflow 后 subscribe 已由现有 broker unit test 保证：
# - test_multiple_listeners_broadcast
# - test_ring_buffer_drops_oldest
# - test_subscribe_after_ring_eviction_returns_buffer_only


# ---------------------------------------------------------------------------
# W3-out M6 — end-to-end POST → GET resume integration
# ---------------------------------------------------------------------------
#
# 上述场景通过合成注入 broker / DB row 后，仅单独验证 GET。
# M6 会真正经过 POST handler，其中 (a) `_prepare_stream_context` 注册 broker
# (b) partial flush 在 DB 中创建 status='streaming' row
# (c) finalize_turn 以终止状态收尾，将这些 cross-handler invariant 一并
# 验证。router 变更时只要有一处不一致就能捕捉。


def _build_events(run_id: str) -> list[dict[str, Any]]:
    """E2E 场景共用 — 4-event happy path。"""
    return [
        {"id": f"{run_id}-1", "event": MESSAGE_START, "data": {"id": run_id, "role": "assistant"}},
        {"id": f"{run_id}-2", "event": CONTENT_DELTA, "data": {"delta": "hi"}},
        {"id": f"{run_id}-3", "event": CONTENT_DELTA, "data": {"delta": " world"}},
        {
            "id": f"{run_id}-4",
            "event": MESSAGE_END,
            "data": {"content": "hi world", "usage": {}, "status": "completed"},
        },
    ]


def _make_executor_simulator(
    events_factory,  # callable: (run_id) -> list[event dict]
    *,
    pause_after: int | None = None,
    pause_event: asyncio.Event | None = None,
    close_broker_at_end: bool = True,
    captured: dict[str, Any] | None = None,
):
    """Build a mock for ``execute_agent_stream`` that simulates the streaming
    layer's dual-write contract (``broker.publish_nowait`` + ``trace_sink``
    append + ``persist_callback`` flush + SSE yield). ``stream_agent_response``
    的 finally 会调用 broker.close，但我们 patch 了 executor 本身，
    因此由 simulator 模拟该职责。

    pause_after: emit 前 N 个后在 ``pause_event.wait()`` 停住。live attach
    场景 — 确定性复现 POST 停留在 mid-stream、broker 仍存活时 GET
    进入的竞争。
    """

    async def mock_stream(*args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        broker = kwargs["broker"]
        persist_cb = kwargs["persist_callback"]
        trace_sink = kwargs["trace_sink"]
        run_id = kwargs["run_id"]
        if captured is not None:
            registered_broker = event_broker.registry.get(run_id)
            assert registered_broker is not None
            captured["broker"] = registered_broker

        events = events_factory(run_id)
        try:
            for idx, evt in enumerate(events):
                broker.publish_nowait(evt)
                trace_sink.append(evt)
                await persist_cb([evt])
                yield format_sse(evt["event"], evt["data"], event_id=evt["id"])
                if pause_after is not None and idx + 1 == pause_after:
                    assert pause_event is not None
                    await pause_event.wait()
        finally:
            if close_broker_at_end:
                broker.close()

    return mock_stream


async def _wait_for(
    predicate,
    *,
    timeout: float = 2.0,  # noqa: ASYNC109 — bespoke poll helper，与 asyncio.timeout cancel 含义不同
    interval: float = 0.01,
) -> None:
    """Poll ``predicate`` until truthy or timeout — race-free fixture sync."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("timeout waiting for predicate")


@pytest.fixture
def patch_async_session(monkeypatch: pytest.MonkeyPatch):
    """将 router 模块内的 ``async_session`` 替换为 TestSession，使
    `_build_persist_callback` / `_finalize_trace` 使用与 conftest in-memory DB
    相同的 engine。若未 patch，partial flush 会指向 production DB（未配置）并 silent
    drop → GET resume 找不到 row，落入 RESUME_NOT_FOUND。
    """
    monkeypatch.setattr("app.services.conversation_stream_service.async_session", TestSession)


async def _drive_post_to_completion(
    client: AsyncClient,
    conv_id: uuid.UUID,
    mock_stream,
    *,
    content: str = "go",
) -> None:
    """B/C/D 共用 — patch + POST + aread 一次完成。整合原来重复4次的序列。"""
    with patch("app.routers.conversation_messages.execute_agent_stream", side_effect=mock_stream):
        async with client.stream(
            "POST",
            f"/api/conversations/{conv_id}/messages",
            json={"content": content},
        ) as resp:
            assert resp.status_code == 200
            await resp.aread()


@pytest.mark.asyncio
async def test_e2e_post_inflight_get_attaches_live_and_receives_tail(
    client: AsyncClient,
    patch_async_session: None,
) -> None:
    """A: POST 处于 mid-stream 时进入 GET，则 attach 到 broker live，
    从 buffer replay 缺失 prefix 后继续接收 live tail。"""
    conv_id = await _seed_conv()
    captured: dict[str, Any] = {}
    pause = asyncio.Event()
    mock_stream = _make_executor_simulator(
        _build_events,
        pause_after=2,
        pause_event=pause,
        captured=captured,
    )

    async def consume_post() -> None:
        # POST 会一直停留在 mid-stream，直到 mock 的 pause 被解除 — pause.set
        # 之前不要 abort，而是一起流到结束（两者都跟到 close）。
        async with client.stream(
            "POST",
            f"/api/conversations/{conv_id}/messages",
            json={"content": "go"},
        ) as resp:
            assert resp.status_code == 200
            captured["post_run_id_header"] = resp.headers["x-run-id"]
            async for _ in resp.aiter_text():
                pass

    get_task: asyncio.Task[bytes] | None = None
    with patch("app.routers.conversation_messages.execute_agent_stream", side_effect=mock_stream):
        post_task = asyncio.create_task(consume_post())
        try:
            # 确认 mock 已 publish message_start + content_delta 两个事件并停在 pause
            # — 此时 broker buffer 有 2 events，broker live。
            await _wait_for(
                lambda: (
                    "broker" in captured and len(captured["broker"]._buffer) >= 2  # noqa: SLF001
                )
            )
            broker_live = captured["broker"]
            run_id = broker_live.run_id
            assert not broker_live.is_closed

            async def consume_get() -> bytes:
                async with client.stream(
                    "GET",
                    f"/api/conversations/{conv_id}/stream",
                    params={"run_id": run_id},
                ) as resp:
                    assert resp.status_code == 200
                    assert resp.headers["x-resume-mode"] == "live"
                    assert resp.headers["x-run-id"] == run_id
                    return await resp.aread()

            get_task = asyncio.create_task(consume_get())
            # 短暂让出，直到 GET listener 注册到 broker.subscribe —
            # 即使 pause.set 后 mock 立即 publish late events，也必须 fan-out 到 listener
            # queue 中必须 fan-out。
            #
            # Race-free invariant: ``EventBroker.subscribe`` 在第一次 ``__anext__``
            # 中按 ``listeners.add(queue)`` → ``buffer snapshot`` → buffer
            # slice yield 的顺序无 await 处理（单个 sync chunk）。当外部
            # observer 观察到 ``len(_listeners) >= 1`` 时，listener
            # 注册 + snapshot 都已完成，之后的 ``publish_nowait``
            # 必然 fan-out 到 queue，并通过 ``yielded_ids`` dedup 阻止 boundary
            # 重复（event_broker.py:194-240）。
            await _wait_for(
                lambda: len(broker_live._listeners) >= 1  # noqa: SLF001
            )
            pause.set()
            get_body = await get_task
        finally:
            # 即使因 Race / assertion 失败进入异常路径，也要防止 task leak —
            # 未回收的 listener task 遇到 conftest autouse `_clear()` 时，
            # 会在 `queue.get()` 永久 hang，导致后续测试 flake。
            #
            # 即使 Happy path，POST 侧 ``_finalize_trace``（DB write 2次）也会
            # 比 GET 侧 stream 结束稍晚，因此若无条件 cancel
            # 会与 SQLAlchemy connection mid-rollback 冲突（sqlite3 "no
            # active connection"）。优先等待自然结束，仅 timeout 时
            # cancel — 用 ``shield`` 阻止 wait_for cancel propagation。
            pause.set()
            # ``post_task`` 与 ``get_task`` 的 return 类型不同（None vs
            # bytes），因此会被归入 generic union，但 ``asyncio.shield``
            # 只接受单一 generic，pyright 会捕捉 mismatch。由于排序意图
            # 正确，cast 为 ``Any`` 以静默处理。
            from typing import cast

            for task in cast(list[asyncio.Task[Any]], [post_task, get_task]):
                if task is None or task.done():
                    continue
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (TimeoutError, asyncio.CancelledError):
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task

    sse_events = _parse_sse_events(get_body.decode())
    deltas = [
        json.loads(e["data"]).get("delta") for e in sse_events if e.get("event") == CONTENT_DELTA
    ]
    # buffer replay (hi) + live tail ( world) — 两者都到达 GET。
    assert deltas == ["hi", " world"]
    assert sse_events[-1]["event"] == MESSAGE_END
    # POST header 的 run_id 与 mock 接收到的 run_id 一致 — `_prepare_stream
    # _context` 在同一 turn 中统一 broker / persist / header 使用相同 id。
    assert captured["post_run_id_header"] == run_id


@pytest.mark.asyncio
async def test_e2e_post_completed_then_broker_evicted_get_replays_from_db(
    client: AsyncClient,
    patch_async_session: None,
) -> None:
    """B: POST 正常结束 → 通过 ``registry.evict_expired(ttl_seconds=0)``
    强制回收 closed broker → GET 进入时落入 DB replay 分支。"""
    conv_id = await _seed_conv()
    captured: dict[str, Any] = {}
    mock_stream = _make_executor_simulator(_build_events, captured=captured)

    await _drive_post_to_completion(client, conv_id, mock_stream, content="hi")

    run_id = captured["broker"].run_id

    # broker 在 mock finally 中 close，因此成为 evict 候选。用 ttl=0 强制回收。
    broker = event_broker.registry.get(run_id)
    assert broker is not None and broker.is_closed
    evicted = event_broker.registry.evict_expired(ttl_seconds=0)
    assert evicted >= 1
    assert event_broker.registry.get(run_id) is None

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["x-resume-mode"] == "replay"
        body = await resp.aread()

    sse_events = _parse_sse_events(body.decode())
    assert [e.get("event") for e in sse_events] == [
        MESSAGE_START,
        CONTENT_DELTA,
        CONTENT_DELTA,
        MESSAGE_END,
    ]
    deltas = [
        json.loads(e["data"]).get("delta") for e in sse_events if e.get("event") == CONTENT_DELTA
    ]
    assert deltas == ["hi", " world"]
    assert all(e.get("event") != STALE for e in sse_events)


@pytest.mark.asyncio
async def test_e2e_post_killed_before_finalize_get_emits_stale(
    client: AsyncClient,
    patch_async_session: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C: partial flush 已写入 status='streaming' row，但 backend
    在 finalize 前死亡的情况。将 ``_finalize_trace`` patch 为 no-op，使 row
    保持 'streaming' 状态，从而验证 broker miss → DB replay → ``event: stale``
    路径。
    """
    conv_id = await _seed_conv()
    captured: dict[str, Any] = {}

    async def _no_finalize(*args: Any, **kwargs: Any) -> None:
        return None

    async def _no_transition(*args: Any, **kwargs: Any) -> tuple[None, str]:
        return None, "completed"

    monkeypatch.setattr("app.services.conversation_stream_service.finalize_trace", _no_finalize)
    monkeypatch.setattr("app.services.conversation_run_worker._transition", _no_transition)

    def events_no_end(run_id: str) -> list[dict[str, Any]]:
        # 缺少 message_end — 模拟 backend 在过程中死亡。
        return [
            {
                "id": f"{run_id}-1",
                "event": MESSAGE_START,
                "data": {"id": run_id, "role": "assistant"},
            },
            {"id": f"{run_id}-2", "event": CONTENT_DELTA, "data": {"delta": "partial"}},
        ]

    mock_stream = _make_executor_simulator(events_no_end, captured=captured)

    await _drive_post_to_completion(client, conv_id, mock_stream)

    run_id = captured["broker"].run_id
    # finalize 为 no-op，因此 row.status 保持 partial flush 写入的 'streaming'
    # 状态。broker 在 mock finally 中 close，并以 ttl=0 回收。另外
    # 再调用 ``_clear()`` 清空 registry dict 本身 — 构造与真实 SIGKILL 后
    # backend 重启时（broker dict 为空）相同的 invariant。
    event_broker.registry.evict_expired(ttl_seconds=0)
    event_broker.registry._clear()  # noqa: SLF001 — 模拟 crash-after-restart
    assert event_broker.registry.get(run_id) is None
    async with TestSession() as db:
        from sqlalchemy import select

        record = (
            await db.execute(select(MessageEvent).where(MessageEvent.assistant_msg_id == run_id))
        ).scalar_one()
        assert record.status == "streaming"

    async with client.stream(
        "GET",
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["x-resume-mode"] == "replay"
        body = await resp.aread()

    sse_events = _parse_sse_events(body.decode())
    assert sse_events[-1]["event"] == STALE
    stale_payload = json.loads(sse_events[-1]["data"])
    assert stale_payload["reason"] == "broker_lost"
    assert stale_payload["last_event_id"] == f"{run_id}-2"


@pytest.mark.asyncio
async def test_e2e_post_emits_interrupt_then_get_returns_409(
    client: AsyncClient,
    patch_async_session: None,
) -> None:
    """D: POST 未 emit message_end，只 emit ``interrupt`` 后结束时，GET
    resume 应识别为 graph 正等待 HiTL 响应的信号并以 409 阻止
    （client 应改走 ``/messages/resume``）。
    """
    conv_id = await _seed_conv()
    captured: dict[str, Any] = {}

    def events_with_interrupt(run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": f"{run_id}-1",
                "event": MESSAGE_START,
                "data": {"id": run_id, "role": "assistant"},
            },
            {
                "id": f"{run_id}-2",
                "event": INTERRUPT,
                "data": {"interrupt_id": "abc", "value": "approve?"},
            },
        ]

    mock_stream = _make_executor_simulator(events_with_interrupt, captured=captured)

    await _drive_post_to_completion(client, conv_id, mock_stream, content="do thing")

    run_id = captured["broker"].run_id
    # broker 在 mock finally 中 close。以 ttl=0 回收，确保进入 broker miss
    # 路径（若 broker live，则会走 subscribe，不会得到 409）。
    event_broker.registry.evict_expired(ttl_seconds=0)
    assert event_broker.registry.get(run_id) is None

    resp = await client.get(
        f"/api/conversations/{conv_id}/stream",
        params={"run_id": run_id},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RESUME_INTERRUPT_PENDING"
