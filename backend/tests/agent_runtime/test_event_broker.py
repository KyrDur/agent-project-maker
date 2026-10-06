"""Unit tests for ``app.agent_runtime.event_broker`` (W3-out M1).

CHECKPOINT.md M1 done-when:
- publish/subscribe (single + multi listener)
- ring buffer maxlen 超出时 oldest drop
- subscribe(after_id=...) → 仅 after_id 之后
- close 后 subscribe = 仅接收 buffer 并立即结束
- queue maxsize 超出时 slow listener disconnect（其他 listener 正常）
- registry idempotency / evict_expired / close_for_conversation
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from app.agent_runtime.event_broker import (
    BrokeredEvent,
    BrokerRegistry,
    EventBroker,
)


def _make_event(seq: int, *, msg_id: str = "run-1") -> BrokeredEvent:
    return {
        "id": f"{msg_id}-{seq}",
        "event": "content_delta",
        "data": {"delta": f"chunk{seq}"},
    }


async def _collect(
    broker: EventBroker, *, after_id: str | None = None, limit: int | None = None
) -> list[BrokeredEvent]:
    events: list[BrokeredEvent] = []
    async for evt in broker.subscribe(after_id=after_id):
        events.append(evt)
        if limit is not None and len(events) >= limit:
            break
    return events


# --------------------------------------------------------------------------
# Core publish/subscribe
# --------------------------------------------------------------------------


async def test_publish_subscribe_single_listener() -> None:
    broker = EventBroker("run-1")
    consumer_task = asyncio.create_task(_collect(broker, limit=3))
    # Yield once so subscribe can register before publish.
    await asyncio.sleep(0)

    for i in range(1, 4):
        await broker.publish(_make_event(i))

    received = await asyncio.wait_for(consumer_task, timeout=1.0)
    assert [e["id"] for e in received] == ["run-1-1", "run-1-2", "run-1-3"]
    assert broker.last_event_id == "run-1-3"


async def test_subscribe_after_id_replays_only_newer() -> None:
    """Plan 场景 — 5个 publish → subscribe(after_id=event3) → 仅4,5。"""
    broker = EventBroker("run-1")
    for i in range(1, 6):
        await broker.publish(_make_event(i))

    received = await _collect(broker, after_id="run-1-3", limit=2)
    assert [e["id"] for e in received] == ["run-1-4", "run-1-5"]


async def test_subscribe_no_after_id_replays_full_buffer() -> None:
    broker = EventBroker("run-1")
    for i in range(1, 4):
        await broker.publish(_make_event(i))
    broker.close()  # close so subscribe drains and exits

    received = await _collect(broker)
    assert [e["id"] for e in received] == ["run-1-1", "run-1-2", "run-1-3"]


async def test_subscribe_after_id_unknown_yields_nothing_in_replay() -> None:
    """如果 after_id 不在 buffer 中（已经 evict 或为未来 id），则 replay 阶段
    不输出任何内容。live 模式下只接收新的 publish。"""
    broker = EventBroker("run-1")
    for i in range(1, 4):
        await broker.publish(_make_event(i))

    consumer_task = asyncio.create_task(_collect(broker, after_id="nonexistent-id", limit=1))
    await asyncio.sleep(0)
    await broker.publish(_make_event(99))

    received = await asyncio.wait_for(consumer_task, timeout=1.0)
    assert [e["id"] for e in received] == ["run-1-99"]


async def test_multiple_listeners_broadcast() -> None:
    broker = EventBroker("run-1")
    consumer_a = asyncio.create_task(_collect(broker, limit=2))
    consumer_b = asyncio.create_task(_collect(broker, limit=2))
    await asyncio.sleep(0)

    await broker.publish(_make_event(1))
    await broker.publish(_make_event(2))

    received_a = await asyncio.wait_for(consumer_a, timeout=1.0)
    received_b = await asyncio.wait_for(consumer_b, timeout=1.0)
    assert [e["id"] for e in received_a] == ["run-1-1", "run-1-2"]
    assert [e["id"] for e in received_b] == ["run-1-1", "run-1-2"]


# --------------------------------------------------------------------------
# Ring buffer behavior
# --------------------------------------------------------------------------


async def test_ring_buffer_drops_oldest() -> None:
    broker = EventBroker("run-1", buffer_size=3)
    for i in range(1, 6):
        await broker.publish(_make_event(i))
    # Internal buffer should retain only last 3 events.
    assert len(broker._buffer) == 3  # noqa: SLF001
    assert [e["id"] for e in broker._buffer] == [  # noqa: SLF001
        "run-1-3",
        "run-1-4",
        "run-1-5",
    ]
    assert broker.last_event_id == "run-1-5"


async def test_subscribe_after_ring_eviction_returns_buffer_only() -> None:
    """buffer drop oldest 后，新 listener 只看到剩余内容。"""
    broker = EventBroker("run-1", buffer_size=3)
    for i in range(1, 6):
        await broker.publish(_make_event(i))
    broker.close()

    received = await _collect(broker)
    assert [e["id"] for e in received] == ["run-1-3", "run-1-4", "run-1-5"]


# --------------------------------------------------------------------------
# Close semantics
# --------------------------------------------------------------------------


async def test_close_terminates_subscribe() -> None:
    broker = EventBroker("run-1")

    async def consume() -> list[BrokeredEvent]:
        out: list[BrokeredEvent] = []
        async for evt in broker.subscribe():
            out.append(evt)
        return out

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    await broker.publish(_make_event(1))
    # close should make the iterator exit cleanly.
    broker.close()

    received = await asyncio.wait_for(task, timeout=1.0)
    assert [e["id"] for e in received] == ["run-1-1"]
    assert broker.is_closed is True
    assert broker.closed_at is not None


async def test_subscribe_aclose_releases_listener_slot() -> None:
    """N-3: subscribe AsyncGenerator 断开时，应执行 ``_listeners.discard``，
    broker._listeners 应收敛到 0。

    否则 publish path 会尝试向 dead queue 执行 ``put_nowait``，
    导致 backpressure 错误工作或内存泄漏。router 集成中 httpx ASGI
    disconnect 时机具有不确定性，因此该 invariant 由 unit 测试覆盖。
    """
    broker = EventBroker("run-1")
    await broker.publish(_make_event(1))

    agen = broker.subscribe()
    first = await agen.__anext__()
    assert first["id"] == "run-1-1"
    # listener 已注册状态。
    assert len(broker._listeners) == 1  # noqa: SLF001 — invariant probe

    # 模拟 client disconnect — generator close。
    await agen.aclose()

    assert len(broker._listeners) == 0, (  # noqa: SLF001
        "subscribe finally 块未清理 listener"
    )
    # broker 应保持存活（可注册其他 listener）。
    assert not broker.is_closed
    broker.close()


async def test_subscribe_after_close_drains_buffer() -> None:
    broker = EventBroker("run-1")
    for i in range(1, 4):
        await broker.publish(_make_event(i))
    broker.close()

    # Already-closed broker → subscribe drains buffer and exits immediately
    # (no waiting on queue).
    received = await asyncio.wait_for(_collect(broker), timeout=1.0)
    assert [e["id"] for e in received] == ["run-1-1", "run-1-2", "run-1-3"]


async def test_publish_after_close_is_noop() -> None:
    broker = EventBroker("run-1")
    await broker.publish(_make_event(1))
    broker.close()
    await broker.publish(_make_event(2))  # should be silently dropped

    received = await asyncio.wait_for(_collect(broker), timeout=1.0)
    assert [e["id"] for e in received] == ["run-1-1"]
    assert broker.last_event_id == "run-1-1"


async def test_close_is_idempotent() -> None:
    broker = EventBroker("run-1")
    broker.close()
    first_closed_at = broker.closed_at
    broker.close()  # second call should not change closed_at
    assert broker.closed_at == first_closed_at


# --------------------------------------------------------------------------
# Slow-listener backpressure
# --------------------------------------------------------------------------


async def test_slow_listener_disconnect() -> None:
    """拥有已满 queue 的 slow listener 会 disconnect，fast listener 正常。"""
    broker = EventBroker("run-1", listener_queue_maxsize=3)

    fast_received: list[BrokeredEvent] = []
    slow_received: list[BrokeredEvent] = []
    started = asyncio.Event()

    async def fast_consume() -> None:
        async for evt in broker.subscribe():
            fast_received.append(evt)

    async def slow_consume() -> None:
        # 只注册，并使其在第一次 await 后绝不继续。
        agen = broker.subscribe()
        started.set()
        # Pull a single event then sleep — queue will fill.
        try:
            first = await agen.__anext__()
            slow_received.append(first)
        except StopAsyncIteration:
            return
        # Block forever to simulate slow consumer.
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass
        finally:
            await agen.aclose()

    fast_task = asyncio.create_task(fast_consume())
    slow_task = asyncio.create_task(slow_consume())
    await started.wait()
    await asyncio.sleep(0)  # let both register listener queues

    # Publish enough to overflow the slow listener's queue (maxsize=3).
    # Yield between publishes so the fast listener drains its own queue
    # (maxsize is per-broker, so both listeners share the bound).
    for i in range(1, 11):
        await broker.publish(_make_event(i))
        await asyncio.sleep(0)

    # Slow listener should have been kicked out → only 1 broker listener now.
    # Allow event loop to drain.
    await asyncio.sleep(0.05)

    # Confirm slow listener was removed.
    assert len(broker._listeners) == 1  # noqa: SLF001

    # Fast listener should still receive all 10 events; close to terminate.
    broker.close()
    await asyncio.wait_for(fast_task, timeout=1.0)
    assert [e["id"] for e in fast_received] == [f"run-1-{i}" for i in range(1, 11)]

    # Tear down the slow consumer (it's still parked on sleep).
    slow_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await slow_task


# --------------------------------------------------------------------------
# BrokerRegistry
# --------------------------------------------------------------------------


def test_registry_get_or_create_idempotent() -> None:
    reg = BrokerRegistry()
    b1 = reg.get_or_create("run-x", conversation_id="conv-1")
    b2 = reg.get_or_create("run-x")
    assert b1 is b2
    assert b1.conversation_id == "conv-1"


def test_registry_get_or_create_replaces_closed() -> None:
    """Closed broker 使用相同 run_id 重新创建时替换为新实例。"""
    reg = BrokerRegistry()
    b1 = reg.get_or_create("run-x")
    b1.close()
    b2 = reg.get_or_create("run-x")
    assert b2 is not b1
    assert not b2.is_closed


def test_registry_get_returns_none_for_unknown() -> None:
    reg = BrokerRegistry()
    assert reg.get("does-not-exist") is None


def test_registry_evict_expired_removes_closed() -> None:
    reg = BrokerRegistry()
    b = reg.get_or_create("run-x")
    b.close()
    # ttl=0 → 所有已关闭 broker 立即成为 evict 对象。
    evicted = reg.evict_expired(ttl_seconds=0)
    assert evicted == 1
    assert reg.get("run-x") is None


def test_registry_evict_expired_skips_live() -> None:
    reg = BrokerRegistry()
    reg.get_or_create("run-live")
    evicted = reg.evict_expired(ttl_seconds=0)
    assert evicted == 0
    assert reg.get("run-live") is not None


def test_registry_evict_expired_respects_ttl() -> None:
    reg = BrokerRegistry()
    b = reg.get_or_create("run-x")
    b.close()
    # ttl=300s → 刚关闭的 broker 尚不是 evict 对象。
    evicted = reg.evict_expired(ttl_seconds=300)
    assert evicted == 0
    assert reg.get("run-x") is not None


def test_registry_close_for_conversation() -> None:
    reg = BrokerRegistry()
    b1 = reg.get_or_create("run-1", conversation_id="conv-A")
    b2 = reg.get_or_create("run-2", conversation_id="conv-A")
    b3 = reg.get_or_create("run-3", conversation_id="conv-B")

    closed = reg.close_for_conversation("conv-A")
    assert closed == 2
    assert b1.is_closed
    assert b2.is_closed
    assert not b3.is_closed


def test_registry_close_for_conversation_skips_already_closed() -> None:
    reg = BrokerRegistry()
    b1 = reg.get_or_create("run-1", conversation_id="conv-A")
    b1.close()
    closed = reg.close_for_conversation("conv-A")
    assert closed == 0  # already closed → not double-counted


def test_registry_close_for_conversation_logs_when_count_positive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """M-6: 用于跟踪正常运行中的发生频率 — closed > 0 时 logger.info。"""
    import logging

    caplog.set_level(logging.INFO, logger="app.agent_runtime.event_broker")
    reg = BrokerRegistry()
    reg.get_or_create("run-1", conversation_id="conv-A")
    reg.get_or_create("run-2", conversation_id="conv-A")
    reg.close_for_conversation("conv-A")
    assert any("close_for_conversation conv=conv-A closed=2" in r.message for r in caplog.records)


def test_registry_close_for_conversation_silent_when_no_match(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """没有匹配时不留日志（防止 cron noise）。"""
    import logging

    caplog.set_level(logging.INFO, logger="app.agent_runtime.event_broker")
    reg = BrokerRegistry()
    reg.get_or_create("run-1", conversation_id="conv-A")
    reg.close_for_conversation("conv-B")
    assert not any("close_for_conversation" in r.message for r in caplog.records)


# --------------------------------------------------------------------------
# Smoke: ensure module-level singleton exists and is the right type.
# --------------------------------------------------------------------------


def test_module_level_registry_singleton() -> None:
    from app.agent_runtime import event_broker as eb

    assert isinstance(eb.registry, BrokerRegistry)


# ---------------------------------------------------------------------------
# In-band memory caps（M2 补强 — M4 APScheduler GC 到来前的安全网）
# ---------------------------------------------------------------------------


def test_registry_lru_cap_evicts_oldest_closed() -> None:
    """达到 ``max_brokers`` 时，最旧的 closed broker 优先 evict。"""
    reg = BrokerRegistry(max_brokers=3)
    b1 = reg.get_or_create("r1")
    b2 = reg.get_or_create("r2")
    b3 = reg.get_or_create("r3")
    b1.close()
    b2.close()  # b1, b2 closed; b3 live
    # 注册第4个 broker — b1（最先进入的 closed）应被移除
    reg.get_or_create("r4")
    assert reg.get("r1") is None  # evicted
    assert reg.get("r2") is b2  # closed but still under cap
    assert reg.get("r3") is b3
    assert reg.get("r4") is not None


def test_registry_lru_cap_force_closes_live_when_all_live() -> None:
    """即使所有 broker 都是 live，达到 cap 时也强制 close + pop 最旧的 live。"""
    reg = BrokerRegistry(max_brokers=2)
    b1 = reg.get_or_create("r1")
    reg.get_or_create("r2")
    # b1, b2 都是 live。添加新 broker 时应强制 close + pop b1。
    reg.get_or_create("r3")
    assert reg.get("r1") is None
    assert b1.is_closed  # 已被强制 close
    assert reg.get("r2") is not None
    assert reg.get("r3") is not None


def test_registry_evict_expired_force_closes_stale_live() -> None:
    """超过 ``max_live_age_seconds`` 的 live broker 会被强制 close，并在下次调用时 evict。"""
    from datetime import timedelta

    reg = BrokerRegistry(max_live_age_seconds=10)
    broker = reg.get_or_create("stale-live")
    # 人为将 created_at 调整到过去
    broker.created_at = broker.created_at - timedelta(seconds=20)
    # 第1次调用：强制 close（return 0 — closed_at + ttl 尚未到期）
    evicted = reg.evict_expired(ttl_seconds=300)
    assert evicted == 0
    assert broker.is_closed
    # 第2次调用：ttl=0 时立即 pop
    evicted = reg.evict_expired(ttl_seconds=0)
    assert evicted == 1
    assert reg.get("stale-live") is None


def test_registry_evict_expired_skips_recent_live() -> None:
    """刚创建的 live broker 不应被强制 close。"""
    reg = BrokerRegistry(max_live_age_seconds=1800)
    broker = reg.get_or_create("recent-live")
    reg.evict_expired()
    assert not broker.is_closed
    assert reg.get("recent-live") is broker


def test_registry_evict_expired_uses_naive_datetime_comparison() -> None:
    """M-4: 即使系统 timezone 不是 UTC，cutoff 也必须准确。

    旧实现存在 ``naive_dt.timestamp()`` 被解释为本地 tz 的陷阱 — 验证是否
    不依赖该函数，仅通过 timedelta 差值进行比较。
    """
    from datetime import timedelta

    reg = BrokerRegistry()
    b = reg.get_or_create("run-x")
    b.close()
    # 将 closed_at 精确设为 ttl + 1秒之前 — 无论本地 tz 如何都应 evict。
    assert b.closed_at is not None
    b.closed_at = b.closed_at - timedelta(seconds=301)
    evicted = reg.evict_expired(ttl_seconds=300)
    assert evicted == 1
    assert reg.get("run-x") is None


# ---------------------------------------------------------------------------
# W3-out M4 — close_all (shutdown hook)
# ---------------------------------------------------------------------------


def test_registry_close_all_closes_only_live_brokers() -> None:
    reg = BrokerRegistry()
    b1 = reg.get_or_create("r1")
    b2 = reg.get_or_create("r2")
    b3 = reg.get_or_create("r3")
    b2.close()  # already closed before close_all

    closed = reg.close_all()
    assert closed == 2  # only b1 + b3 newly closed
    assert b1.is_closed
    assert b2.is_closed
    assert b3.is_closed


def test_registry_close_all_is_idempotent() -> None:
    reg = BrokerRegistry()
    reg.get_or_create("r1")
    reg.get_or_create("r2")
    assert reg.close_all() == 2
    # 第2次调用时全部已 closed → 返回 0
    assert reg.close_all() == 0


def test_registry_close_all_on_empty_registry_returns_zero() -> None:
    reg = BrokerRegistry()
    assert reg.close_all() == 0


@pytest.mark.asyncio
async def test_subscribe_when_already_closed_emits_sentinel() -> None:
    """即使对已 closed 的 broker 执行 subscribe，也应通过 sentinel 分支立即结束。

    B1 fix 的 already-closed-at-subscribe 分支回归保护 — ``listeners.add``
    被 skip 时向 queue 放入 self-sentinel，防止在 ``await queue.get()`` 阶段
    陷入无限等待。虽然模拟真实 race 需要 monkey patch，但本用例会直接经过
    已 fix 的分支。
    """
    broker = EventBroker("race-test")
    broker.close()  # already closed before subscribe
    received: list[BrokeredEvent] = []
    async for evt in broker.subscribe():
        received.append(evt)
    # close 后 subscribe → buffer 为空，因此接收0个并立即结束。不会无限等待 X。
    assert received == []
