"""Per-run SSE EventBroker primitive (W3-out M1).

连接可靠性层的核心要素。POST `/messages` publish 时，broker 将其保存在 ring
buffer 中 + fan-out 到所有实时 listener 的 asyncio.Queue。断开的
客户端通过 GET `/stream?run_id=&last_event_id=` 重新连接时，如果 broker
仍存活，就会立即 replay 缺失的 event，并继续实时订阅新的令牌。

设计说明
- process-local 单进程假设 (workers=1)。多 worker 属于后续轨道
  (Redis pub/sub 或 sticky routing) 另行决定。
- asyncio single-threaded — publish/subscribe 之间的同步区间 (没有 await 的
  区间) 实际上是 atomic，因此无需额外加锁即可消除 listener 注册与 buffer snapshot 之间的
  race。
- ring buffer 满时，oldest event 会 silently drop。若 last_event_id 已经
  被挤出 ring 的 client，单靠 broker 无法补齐，因此由 router 层委托给
  DB replay (`trace_storage.get_trace_by_msg_id`)。
- listener queue 满的 slow listener 会在 publish 路径中被强制 disconnect，
  其他 listener 的 broadcast 不受影响。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncGenerator, Iterable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class BrokeredEvent(TypedDict):
    """Per-event payload published on the broker.

    ``id`` 是 SSE 标准 ``id:`` 字段，是 W3-out resume 时 ``last_event_id`` 的
    基准。格式由 ``streaming.py`` 的 emit 闭包决定
    (当前为 ``{msg_id}-{seq}``)。
    """

    id: str
    event: str
    data: dict[str, Any]


_DEFAULT_BUFFER_SIZE = 2000
_DEFAULT_LISTENER_QUEUE_MAXSIZE = 512


def slice_events_after[E: Mapping[str, Any]](
    events: Iterable[E], after_id: str | None
) -> Iterator[E]:
    """Yield events strictly after the one whose ``id`` matches ``after_id``.

    Shared invariant for two replay paths:
    - ``EventBroker.subscribe`` 的 buffer snapshot 切片 (live broker)
    - ``routers/conversations._replay_resume_generator`` 的 DB events 切片

    Semantics:
    - ``after_id is None`` → yield 所有 evt。
    - 如果有与 ``after_id`` 匹配的 evt，则 skip 到该 evt 为止（包含该 evt），之后开始 yield。
    - 如果 ``after_id`` 不在 events 中（已经被 evict 或者 newer），则不 yield 任何事件（X）。
      caller 对该含义 ("evicted/missing") 单独解析。
    """
    seen_after = after_id is None
    for evt in events:
        if not seen_after:
            if evt.get("id") == after_id:
                seen_after = True
            continue
        yield evt


# Memory-protection caps. APScheduler GC is the primary defense (60s interval,
# ttl=300s); in-band cap is the burst safeguard between GC ticks.
_DEFAULT_MAX_BROKERS = 256
_DEFAULT_MAX_LIVE_AGE_SECONDS = 1800  # 30 min — longer than any reasonable turn


class EventBroker:
    """Per-run SSE event broker.

    Args:
        run_id: assistant message uuid (str). LangGraph turn 标识符。
        buffer_size: ring buffer maxlen — 默认 `2000`。按平均事件 200B 估算，
            内存上限约为 400KB。
        listener_queue_maxsize: 单个 listener queue maxsize。backpressure
            保护机制。满时该 listener 会 disconnect。
        conversation_id: 同一 conversation 开始新 turn 时，
            用于通过 ``BrokerRegistry.close_for_conversation`` 批量 close 的
            元数据。
    """

    def __init__(
        self,
        run_id: str,
        *,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
        listener_queue_maxsize: int = _DEFAULT_LISTENER_QUEUE_MAXSIZE,
        conversation_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.buffer_size = buffer_size
        self._listener_queue_maxsize = listener_queue_maxsize
        self._buffer: deque[BrokeredEvent] = deque(maxlen=buffer_size)
        # Sentinel `None` signals close to subscribers blocked on `queue.get()`.
        self._listeners: set[asyncio.Queue[BrokeredEvent | None]] = set()
        self._listener_attached = asyncio.Event()
        self._closed = False
        self._error: Exception | None = None
        self._last_event_id: str | None = None
        self.created_at: datetime = datetime.now(UTC).replace(tzinfo=None)
        self.closed_at: datetime | None = None

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def last_event_id(self) -> str | None:
        return self._last_event_id

    @property
    def error(self) -> Exception | None:
        return self._error

    def has_event_id(self, event_id: str | None) -> bool:
        """Return whether ``event_id`` is still present in the in-memory buffer."""
        if not event_id:
            return False
        return any(evt.get("id") == event_id for evt in self._buffer)

    def publish_nowait(self, evt: BrokeredEvent) -> None:
        """Synchronous publish — buffer.append + fan-out to listener queues.

        ``stream_agent_response`` 的 ``emit()`` 闭包是 sync 函数，因此需要 sync
        入口点。``publish`` (async) 内部也会调用此方法。

        Closed broker 会 silently drop publish（防止已 close 后迟到的
        publish 引发 stale broadcast）。

        Slow listener (queue 已满) 会立即从 listeners 中移除并收到 sentinel，
        从而自然结束 iterator。
        """
        if self._closed:
            return
        self._buffer.append(evt)
        evt_id = evt.get("id")
        if isinstance(evt_id, str) and evt_id:
            self._last_event_id = evt_id
        # Snapshot to allow safe mutation during iteration (slow listeners
        # are removed mid-broadcast).
        for q in list(self._listeners):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                self._listeners.discard(q)
                # Slow listener detected — disconnect for backpressure
                # protection. 为了运行可观测性进行 logging（恶意 slow consumer
                # 检测 + 跟踪正常运行中的 disconnect 频率）。evt id 是最后一次
                # publish 时的 SSE id，用于估算大致位置。
                logger.warning(
                    "EventBroker slow listener disconnected run_id=%s "
                    "(queue maxsize=%d). last_event_id=%s",
                    self.run_id,
                    self._listener_queue_maxsize,
                    self._last_event_id,
                )
                # Make room for the sentinel so the subscriber's `queue.get()`
                # eventually wakes up and exits cleanly. Drop one buffered
                # event — the listener already lost causality.
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):  # pragma: no cover - defensive
                    q.put_nowait(None)

    async def publish(self, evt: BrokeredEvent) -> None:
        """Async wrapper for ``publish_nowait`` (forward-compat).

        publish 本身不会 await，因此是 atomic。提供该包装以便 caller 在 async context 中
        方便调用。
        """
        self.publish_nowait(evt)

    async def wait_until_subscribed(self) -> None:
        if self._listeners:
            return
        await self._listener_attached.wait()

    async def subscribe(self, after_id: str | None = None) -> AsyncGenerator[BrokeredEvent, None]:
        """Subscribe to events, optionally replaying buffered events past ``after_id``.

        Behavior:
        - ``after_id is None`` → replay full buffer, then enter live mode.
        - ``after_id`` matches a buffered event → replay events strictly
          after, then live mode.
        - ``after_id`` does NOT match (already evicted from ring buffer or
          newer than last buffered) → yield nothing in replay phase, enter
          live mode. Caller (router) is responsible for detecting this case
          (last_event_id present but no replay events) and emitting a stale
          marker via DB replay.

        atomic 保证：``listeners.add`` 与 ``buffer snapshot`` 之间没有 await，
        因此 publish 与 subscribe 不会在单个 task 内发生 race。
        """
        # Snapshot buffer + register listener under same sync execution.
        queue: asyncio.Queue[BrokeredEvent | None] = asyncio.Queue(
            maxsize=self._listener_queue_maxsize
        )
        if not self._closed:
            self._listeners.add(queue)
            self._listener_attached.set()
        else:
            # Defensive against future await insertions in this block:
            # if close() raced with our subscribe entry, ensure subscriber
            # still receives the sentinel and exits cleanly.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        snapshot: list[BrokeredEvent] = list(self._buffer)
        already_closed = self._closed

        try:
            yielded_ids: set[str] = set()
            for evt in slice_events_after(snapshot, after_id):
                evt_id = evt.get("id")
                if isinstance(evt_id, str):
                    yielded_ids.add(evt_id)
                yield evt

            # Closed-at-subscribe case: drain buffer only, no live wait.
            if already_closed:
                return

            while True:
                item = await queue.get()
                if item is None:
                    return
                evt_id = item.get("id")
                # Defensive dedup vs buffer snapshot — keep, do not remove.
                # 因为 asyncio single-threaded，所以 ``listeners.add`` 与 ``buffer
                # snapshot`` 之间没有 await，实际上不会发生 race，但
                # (a) 如果未来有人在该区间插入 await，就会打开 race 窗口，
                # (b) 而且 ``publish_nowait`` 是 sync，因此在 ``put_nowait`` 之后
                # 同一个 evt 也可能在 ABI 变更时进入 buffer snapshot，
                # 这种可能性虽然很小。yielded_ids set 以平均每个 turn 200 events
                # 计，约用 ~10KB 成本来强制保证 idempotency — invariant 保证
                # 比这点成本更有价值。
                if isinstance(evt_id, str) and evt_id in yielded_ids:
                    continue
                yield item
        finally:
            self._listeners.discard(queue)

    def close(self, *, error: Exception | None = None) -> None:
        """Mark broker closed and signal all live listeners to terminate.

        Idempotent: subsequent calls are no-ops. After close,
        ``publish`` becomes a no-op and ``subscribe`` only drains the
        buffer.
        """
        if self._closed:
            return
        self._closed = True
        self._error = error
        self.closed_at = datetime.now(UTC).replace(tzinfo=None)
        for q in list(self._listeners):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                # Subscriber will eventually drain queue and re-enter
                # `queue.get()` on a now-empty queue, then block. Best-effort:
                # drop one and retry.
                with contextlib.suppress(asyncio.QueueEmpty):  # pragma: no cover - defensive
                    q.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):  # pragma: no cover - defensive
                    q.put_nowait(None)
        self._listeners.clear()


class BrokerRegistry:
    """Process-local registry of EventBrokers keyed by ``run_id``.

    多 worker 环境支持属于后续轨道。单 worker 下使用 dict + asyncio
    single-thread 模型就足够了（无需 lock）。

    内存保护 — 两种机制以不同 contract 共存：
    - **APScheduler GC**（正式清理器，60s interval，ttl=300s）：正常运行
      期间定期回收 closed broker + 强制 close stale live broker。
    - **in-band emergency cap**（立即触发，``_enforce_capacity``）：即使在 GC
      interval 之间 broker 暴增（例如短时间内开始大量 turn），也能确保
      不超过 ``max_brokers`` 上限。closed broker 优先，
      如果全是 live，则强制 close 最旧的 live broker。
    - **per-broker live age cap**（``max_live_age_seconds``）：超过 30 分钟的
      live broker 表示缺少 close() 回调信号 — ``evict_expired`` 会强制
      close，并在下一周期回收。
    """

    def __init__(
        self,
        *,
        max_brokers: int = _DEFAULT_MAX_BROKERS,
        max_live_age_seconds: int = _DEFAULT_MAX_LIVE_AGE_SECONDS,
    ) -> None:
        self._brokers: dict[str, EventBroker] = {}
        self._max_brokers = max_brokers
        self._max_live_age_seconds = max_live_age_seconds

    def get_or_create(
        self,
        run_id: str,
        *,
        conversation_id: str | None = None,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
    ) -> EventBroker:
        """Idempotent get-or-create.

        同一 run_id 调用两次时返回同一个 EventBroker 实例。
        如果现有 broker 已经 close（复用同一 run_id 属于异常），
        则替换为新的 broker。

        达到上限时进行 in-band LRU eviction：若超过 ``max_brokers``，则从 dict 中
        pop 最旧的 closed broker。若全是 live，则强制 close + pop 最旧的
        live broker。防止运行 OOM 的优先级
        高于保留正常 turn。
        """
        broker = self._brokers.get(run_id)
        if broker is None or broker.is_closed:
            # 在复用同一 run_id（closed）的情况下，先 pop，避免把自身作为 LRU eviction
            # 不成为候选，先执行 pop。随后检查 capacity → 注册新的 broker
            # 。避免依赖 _enforce_capacity 恰好 evict 自己的 dict slot
            # 这种偶然一致性。
            self._brokers.pop(run_id, None)
            self._enforce_capacity()
            broker = EventBroker(
                run_id,
                buffer_size=buffer_size,
                conversation_id=conversation_id,
            )
            self._brokers[run_id] = broker
        return broker

    def _enforce_capacity(self) -> None:
        """Drop oldest closed (or oldest live) brokers until under the cap.

        实际采用基于 insertion-order 的 FIFO + closed-优先策略（并非 true LRU
        — 即使同一 broker 再次调用 ``get_or_create``，dict 顺序也
        不会改变）。从最早加入的 broker 开始检查，closed 就立即
        pop，live 则强制 close 后 pop。必须清理到 ``max_brokers - 1``，
        才能为新的 entry 腾出位置。

        ⚠️ 正常运行中强制 close live broker 会中断正在进行的 stream
        （subscriber 会收到 sentinel）。内存保护优先于保留 turn。
        引入多租户后，需要添加 per-user/conversation sub-cap，
        防止某个用户通过 cross-tenant eviction 中断其他用户的 stream
        （M3+ 后续轨道）。
        """
        if len(self._brokers) < self._max_brokers:
            return
        target = self._max_brokers - 1
        for run_id in list(self._brokers.keys()):
            if len(self._brokers) <= target:
                break
            broker = self._brokers[run_id]
            if not broker.is_closed:
                logger.warning(
                    "BrokerRegistry capacity reached (%d) — force-closing live "
                    "broker run_id=%s to make room",
                    self._max_brokers,
                    run_id,
                )
                broker.close()
            self._brokers.pop(run_id, None)

    def get(self, run_id: str) -> EventBroker | None:
        return self._brokers.get(run_id)

    def evict_expired(self, ttl_seconds: int = 300) -> int:
        """Evict closed brokers past TTL + force-close stale live brokers.

        分两步清理：

        1. 如果 ``broker.closed_at + ttl_seconds`` 已经过期，则从 dict 中 pop。
        2. live broker 中，如果 ``broker.created_at + max_live_age_seconds`` 已
           过期，则强制 close（下一次调用时在第 1 步清理）。
           正常 turn 会在数分钟内结束，因此超过 30 分钟的 live broker
           表示缺少 close() 回调或 finally 未调用。

        Returns:
            Number of brokers evicted (closed broker pops only — force-closed
            live broker 会在下一次调用时 evict)。
        """
        # M-4 fix — created_at/closed_at 通过 ``datetime.now(UTC).replace(tzinfo=
        # None)`` 以 naive UTC 保存。naive datetime 的 ``.timestamp()`` 会
        # **按本地 tz 解析** (Python docs)，因此如果系统 timezone 不是 UTC，
        # cutoff 就会偏移。直接比较 naive datetime 彼此则与 timezone 假设
        # 无关且准确。
        now_dt = datetime.now(UTC).replace(tzinfo=None)
        closed_cutoff_dt = now_dt - timedelta(seconds=ttl_seconds)
        live_cutoff_dt = now_dt - timedelta(seconds=self._max_live_age_seconds)
        to_remove: list[str] = []
        for run_id, broker in self._brokers.items():
            if broker.closed_at is None:
                # Force-close stale live broker. Will be evicted on next call.
                if broker.created_at <= live_cutoff_dt:
                    age_seconds = int((now_dt - broker.created_at).total_seconds())
                    logger.warning(
                        "Force-closing stale live broker run_id=%s (age %ds > max %ds)",
                        run_id,
                        age_seconds,
                        self._max_live_age_seconds,
                    )
                    broker.close()
                continue
            if broker.closed_at <= closed_cutoff_dt:
                to_remove.append(run_id)
        for run_id in to_remove:
            self._brokers.pop(run_id, None)
        return len(to_remove)

    def close_for_conversation(self, conversation_id: str) -> int:
        """Force-close all live brokers belonging to a conversation.

        同一 conversation 开始新 turn 时立即回收之前的 broker
        （虽然同时进行 2 个 turn 已被 checkpointer lock 禁止，但会清理此前 turn 的
        broker 仍持有实时 listener 的情况）。

        M-6: count > 0 时 logger.info — 跟踪正常运行中的发生频率
        有助于调试（识别 frontend race 导致发送两次 turn 的情况）。

        Returns:
            Number of brokers closed.
        """
        closed_run_ids: list[str] = []
        for broker in list(self._brokers.values()):
            if broker.conversation_id == conversation_id and not broker.is_closed:
                broker.close()
                closed_run_ids.append(broker.run_id)
        if closed_run_ids:
            logger.info(
                "BrokerRegistry close_for_conversation conv=%s closed=%d run_ids=%s",
                conversation_id,
                len(closed_run_ids),
                closed_run_ids,
            )
        return len(closed_run_ids)

    def all_brokers(self) -> list[EventBroker]:
        """Snapshot list of all registered brokers (live + closed)."""
        return list(self._brokers.values())

    def close_all(self) -> int:
        """Force-close every live broker (shutdown hook).

        比 APScheduler 的 ``evict_expired`` GC 更强 — 忽略 TTL，
        向当前所有存活 broker 的 listener 发送 sentinel 以优雅
        结束。在 lifespan shutdown 阶段调用，防止 in-flight stream consumer
        hang。Idempotent: 已经 closed 的 broker 会 skip。

        Returns:
            Number of brokers actually closed in this call.
        """
        count = 0
        for broker in list(self._brokers.values()):
            if not broker.is_closed:
                broker.close()
                count += 1
        return count

    def _clear(self) -> None:
        """Test-only helper — drop all brokers without closing.

        N-4: 通过 underscore prefix 将其排除在 production import 表面之外，防止误
        调用导致 active broker 未 close 就 leak（listener task 会
        永远等待 ``queue.get()``）。Production code 使用
        ``evict_expired`` 或 ``close_for_conversation`` / ``close_all``。
        """
        self._brokers.clear()


# Module-level singleton. M2 的 streaming.py 集成与 M3 的 GET resume endpoint
# 引用同一个实例。
registry: BrokerRegistry = BrokerRegistry()
