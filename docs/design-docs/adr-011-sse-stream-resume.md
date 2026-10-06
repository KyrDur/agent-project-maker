# ADR-011: SSE Stream Resume (W3-out)

## 状态：M1-M6 实现完成（M6 PR 等待 merge）

相关文档：
- 执行计划：`~/.claude/plans/1-ux-quirky-canyon.md`
- milestone 进度：`HANDOFF.md`（根目录）
- merge PR：#116（M1+M2）、#117（M3+M4）、#118（M5）、本 PR（M6 集成测试 + ADR 整理）

---

## 背景

当前 Moldy chat SSE streaming 只支持**单向 POST**。一个 turn（`message_start` ~ `message_end`）的所有 SSE event 会累积在 in-memory `trace_sink: list[dict]` 中，turn 结束后由 `_persist_trace` batch 写入 `message_events` 表（W5）。

问题：
1. **客户端断开 = token 丢失**：移动端熄屏 / Wi-Fi 切换 / tab 切换 / 刷新时，进行中的 LangGraph turn 仍会在后端继续执行，但客户端将永远收不到断开后的 token（silent fail — 仅 console error）。
2. **刻意禁用自动重连**：POST 非 idempotent，重新执行会产生新的 LangGraph run = 新 LLM 调用，带来成本 + 响应重复。
3. **缺少 partial persistence**：turn 中途断开时，此前已 emit 的 event 也不会写入 DB。
4. **W5/W6 基础设施未利用**：trace storage 已具备保存全部 event 的结构，但尚未用于 replay。

---

## 决定

### 1. 单一 GET endpoint，服务器内部路由

```
GET /api/conversations/{conversation_id}/stream?run_id=<uuid>&last_event_id=<id>
```

服务器根据 `run_id` 查询 broker → 分成两种模式：
- **broker live**（in-flight）：subscribe → 发送 `last_event_id` 之后的 buffer event + 新 event live stream。header `X-Resume-Mode: live`
- **broker dead**：从 `message_events` 表切片 events（`> last_event_id`）→ emit + 立即结束。header `X-Resume-Mode: replay`

如果 query 为空，则 fallback 使用 `Last-Event-ID` header（SSE 标准，兼容 EventSource）。

所有 guard 分支统一为单一 `404 RESUME_NOT_FOUND`（遵循 `rules/security.md` 防止 enumeration oracle）— conv 不存在、ownership 失败、DB row 不存在、broker live 但 conv_id 不匹配、broker.conversation_id 为 None。分支原因仅通过 `_log_resume_reject(reason, ...)` 暴露在 server log 中。（HiTL interrupt pending 例外使用 `409 RESUME_INTERRUPT_PENDING` — 这是提示 client 应调用 `/messages/resume` 的 actionable signal，其 UX 准确性价值高于 oracle 风险。）

### 2. EventBroker primitive (per-run, in-memory)

```python
class EventBroker:
    run_id: str
    conversation_id: str | None
    buffer: deque[BrokeredEvent]  # ring, maxlen=2000
    listeners: set[asyncio.Queue]  # maxsize=512 each
    closed: bool

    def publish_nowait(self, evt) -> None
    async def publish(self, evt) -> None       # async wrapper, forward-compat
    async def subscribe(self, after_id) -> AsyncGenerator
    def close(self, *, error=None) -> None     # idempotent
```

- 支持多个 listener 同时 attach（multi-tab / mobile+desktop same conv）
- listener queue 超过 maxsize 时强制断开 slow listener（整体 broadcast 继续）。断开的客户端可通过 GET 重试恢复
- `slice_events_after(events, after_id)` — broker subscribe + DB replay 两条路径共享的 slicing invariant（在 M3 PR `/simplify` 中提取）
- `BrokerRegistry` 是 process-local singleton（`dict[run_id, EventBroker]`）— module-level `event_broker.registry`
- in-band memory protection：`max_brokers=256`（LRU eviction，closed 优先），`max_live_age_seconds=1800`（超过 30 分钟的 live broker 强制 close）
- TTL 300s `evict_expired` GC + 新 turn 开始时立即 close 同一 conv 的旧 broker（`close_for_conversation`）+ APScheduler 60s interval cleanup（M4 wired）

**Multi-worker 限制**：由于是 process-local，多 worker 环境中如果 resume 被路由到不同 worker，就一定退化为 replay-only。当前假设 `workers=1`。后续 track 引入 Redis pub/sub 或 sticky routing。

### 3. Run ID = `assistant_msg_id` (UUID)

引入新 identifier 的成本为 0。`_prepare_stream_context` 只生成一次 `uuid.uuid4()` → broker key + `message_start.data.id` + `assistant_msg_id`（DB 列）+ POST 响应 header `X-Run-Id` 全部统一使用同一 UUID。

`streaming.py` 的 `emit` closure 接收该 `run_id`，以 `{run_id}-{seq}` 格式发送 SSE `id:` 字段 — 作为 `last_event_id` 比较 / dedup 的单一 key。

### 4. Mid-stream batched persistence

`stream_agent_response` 的 `emit()` 累积 `flush_buffer`，当达到 **32 events 或 2 秒**阈值时，以 `asyncio.create_task` fire-and-forget 调用 `persist_callback(flush_buffer)` → `trace_storage.append_events` UPSERT（`status='streaming'`）。

依据：
- per-event flush 会因 LLM token chunk 频率（50ms）给 PG 带来过高负载
- 32 events / 2s 时最坏丢失窗口 = 2 秒，replay 精度足够
- 因为是 fire-and-forget，emit 本身 latency 为 0
- 失败的 chunk 单独收集到 `retry_buffer`，在 finally 的 final flush 中再尝试一次（恢复 DB 短暂故障）

`_build_persist_callback` 每次调用都会用 fresh `async_session()` 打开 own session — 与 SSE generate 的 request-scoped session 分离，避免 stream 结束后 callback 残留导致 session leak。

### 5. 扩展 `message_events` schema（m34）

```sql
ALTER TABLE message_events
  ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'completed'
    CHECK (status IN ('streaming', 'completed', 'failed')),
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX idx_message_events_status
  ON message_events(conversation_id, status);
```

- `DEFAULT 'completed' NOT NULL` → PG11+ 仅 metadata 变更（无需 table scan）
- 现有 row 自动 backfill 为 `completed`
- replay 时如果 `status='streaming'`，表示 broker 已死亡 → 最后发送 `event: stale` SSE（`reason: broker_lost` + `last_event_id`），让客户端停止自动重试并通知用户

### 6. 扩展 trace_storage API

```python
async def append_events(db, *, conversation_id, assistant_msg_id, events_chunk, status='streaming') -> MessageEvent | None
async def finalize_turn(db, *, assistant_msg_id, status='completed', raw_msg_ids=None, conversation_id=None) -> MessageEvent | None
```

- `append_events`：UPSERT 模式。必须按 id **dedup**（防止边界重复）— 先取出现有 events 的 id 集合，再从新 chunk 中只过滤出新 id。没有变更时避免无用 WAL write。
- `finalize_turn`：吸收 `_persist_trace` 的 final-write 职责。更新 `completed_at`、`status`、`linked_message_ids`。若 row 不存在则返回 `None` → caller（`_finalize_trace`）fallback 到 `record_turn`。
- 保留现有 `record_turn` 作为 backward-compat shim（保留 `IntegrityError` invariant 分离）。计划在 **M5/M6 后续重新评估 contract**。

### 7. POST 兼容性 — Dual-write

POST 继续像现有一样 generator yield，同时附带 `broker.publish_nowait`（dual-write）。不强制 background-only。

依据：若强制 background-only，可能带来首 token latency regression。dual-write 成本在 microsecond 级。不断开的客户端保持 100% 现有行为。

### 8. HiTL 兼容

现有 `/messages/resume`（恢复 interrupt）与新增 `/stream`（网络重连）是两个不同关注点：
- HiTL：控制 graph 执行流（interrupt → response）
- Stream resume：网络可靠性（连接中断 → event replay）

当 `_is_pending_interrupt(events)` 检测到 events 最后一个是 `interrupt` 且从未收到 `message_end` 时，判定 graph 处于暂停 → `409 RESUME_INTERRUPT_PENDING`。Frontend 若持有 `lastInterruptIdRef`，则跳过 GET resume。

`event_names.py` 作为单一 source — emit 侧与验证侧都 import 相同常量（`MESSAGE_START`、`INTERRUPT`、`MESSAGE_END` 等），防止 magic string rename 导致 silent breakage。

### 9. 并发

- 同一 conversation 禁止同时 2 个 turn（checkpointer 实际上已有 lock，且 `_prepare_stream_context` 会显式调用 `close_for_conversation`）
- 同一 run 允许多个 listener 并发（multi-tab broadcast）
- 即使并发 GET 2 个因 race 重复发送同一 event，客户端现有 `createEventDeduper` 会基于 `{msg_id}-{seq}` id dedup
- `subscribe` 的 `yielded_ids` set 用于 buffer snapshot ↔ live tail 边界 dedup（publish_nowait 当前为 sync，即使未来插入 await 也保持 idempotent）

### 10. Lifecycle (M4)

`app/main.py` lifespan:

```python
# startup
register_broker_eviction_job(scheduler, registry, interval_seconds=60, ttl_seconds=300)

# shutdown — 顺序很重要（rules/async-lifespan.md）
broker_registry.close_all()        # 1. 给 in-flight listener 发送 sentinel
await asyncio.sleep(0)             # 2. task switch — 保证执行 subscribe finally
scheduler.shutdown(wait=False)     # 3. 关闭 APScheduler
await checkpointer.shutdown()      # 4. persistent layer
```

如果反转 shutdown 顺序，scheduler 会先停止导致 GC 停止，而 listener 在收到 sentinel 前会永远等待 `queue.get()` → SSE generator hang。

### 11. Frontend auto-resume (M5)

`withAutoResume(streamFn, resumeFn, opts)` HOF — 若 POST stream 在 mid-turn 中断（保留 `runId` + `lastEventId`），按 `[500, 1500, 4000]ms` schedule 重试 GET resume，最多 3 次（`with-auto-resume.ts:45-46` `DEFAULT_BACKOFF_MS` / `DEFAULT_MAX_ATTEMPTS`）。4xx（404 RESUME_NOT_FOUND、409 RESUME_INTERRUPT_PENDING）不可重试 — 立即 `onFailed`。`AbortController` cancel 也会立即结束。

`event: stale` 是 backend 通知 broker 丢失的信号（`reason: broker_lost | broker_lost_no_id`）。当前 frontend `consumeStream` 的 switch 没有显式 `case 'stale'`，因此走 default no-op，stream 自然结束（自动 retry 也一起结束）— **不会把中断通知展示给用户**。通过 toast / persistent indicator 暴露该状态属于有意保留的后续事项（参见 HANDOFF.md）。

`onReconnecting/onReconnected/onFailed` callback → `reconnectStateAtom` → 在输入框上方显示 `<ReconnectIndicator>` badge（“正在重试连接...”）。

将 POST 响应 header 的 `X-Run-Id` + 每个 SSE event 的 `id:` 字段（由 parseSSEStream 提取）保存到 `runIdRef`/`lastEventIdRef` — 从 abort 时点起即可自然执行 GET resume。

---

## Milestone（实际进度）

| M | 内容 | 周期 | PR | 状态 |
|---|------|------|----|----|
| M1 | EventBroker primitive + 单元测试 | ~6h | #116 | ✅ |
| M2 | streaming.py 集成 + batched persistence + m34 migration + X-Run-Id | ~7h | #116 | ✅ |
| M3 | GET `/stream` endpoint + 4 种分支 + replay slice + 统一 security oracle | ~6h | #117 | ✅ |
| M4 | APScheduler lifecycle + close_for_conversation + 整理 shutdown 顺序 | ~3h | #117 | ✅ |
| M5 | Frontend lastEventId + GET resume + 显式 indicator UI | ~10h | #118 | ✅ |
| M6 | E2E POST→GET 集成测试 + ADR-011 整理 | ~6h | （本 PR） | ✅ |

按 milestone 拆分 PR — 每个 PR 分散 regression 风险并通过 pre-push gate。M3+M4 merge 时尚未集成 frontend，因此对用户无影响 — M5 merge 时才暴露。

---

## 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| Multi-worker 环境下 broker 为 process-local | 短期：保持 workers=1。中期：后续 track 引入 Redis pub/sub 或 sticky routing |
| `events` JSON row 膨胀（长 turn） | maxlen=2000 × 平均 200B ≈ 400KB。超限时 buffer drop，DB 只保留最近 1000 个（best-effort） |
| broker 比 client 更快（backpressure） | `asyncio.Queue(maxsize=512)`。满时强制 disconnect slow listener → GET 重试 |
| 混淆 HiTL 与 stream resume | `409 RESUME_INTERRUPT_PENDING` 错误。Frontend 若有 `lastInterruptIdRef` 则跳过 GET resume |
| m34 ALTER lock（prod 大表） | 新增 `DEFAULT 'completed' NOT NULL` 在 PG11+ 仅修改 metadata。index 使用 `CREATE INDEX CONCURRENTLY` |
| UPSERT events JSONB concat 成本 | events 小时可忽略。超过阈值（500KB）后改为单独 `events_chunks` 表（后续 PR） |
| backend 整体宕机 → broker 同时死亡 | 已知限制。只接收 DB replay 后结束（M3 stale marker 通知用户）。transient network drop（切换 Wi-Fi）时 broker 仍活着，可真正 live attach。 |
| BrokerRegistry 达到 capacity → 强制 close live broker | 防止 memory OOM 优先于保留 turn。引入 multi-tenant 后增加 per-user/conversation sub-cap（有意 follow-up） |

---

## 验证

### 自动化
- `cd backend && uv run alembic upgrade head`（应用 m34）
- `cd backend && uv run ruff check .`
- `cd backend && uv run pytest tests/` — broker unit 21 + trace_storage partial + integration test_stream_resume 21 + regression 0
- `cd backend && uv run pyright app/` — 0 errors / 0 warnings
- `cd frontend && pnpm lint && pnpm test --run && pnpm build` — withAutoResume / parse-sse / reconnect-indicator 单元验证 + regression 262 tests

### 手动 e2e（M5 merge 时已通过）
- 在 dev server 开始聊天 → backend SIGKILL → 重启 → frontend 自动 GET resume → 保留 partial token + reconnect indicator 短暂显示后消失
- 切换 Wi-Fi → indicator 短暂显示后 token 自然继续（X-Resume-Mode: live）

### M6 E2E（当前 PR）
`backend/tests/integration/test_stream_resume.py` 的 `W3-out M6` 部分 — 与 router-level synthetic test 不同，会真正经过 POST handler，并验证：
- A. live attach：POST 在 mid-stream pause → GET 进入时 broker live，可收到 buffer replay + live tail
- B. replay-only：POST 正常结束 → 强制 `evict_expired(ttl_seconds=0)` → GET 降级为 DB replay 模式
- C. stale streaming：patch `_finalize_trace` 为 no-op（模拟 crash）→ row.status='streaming' 保留 → GET 最后发送 `event: stale`
- D. interrupt pending：POST 只 emit `interrupt` event 后结束 → broker evict → GET 返回 `409 RESUME_INTERRUPT_PENDING`

---

## 有意保留的 follow-up（M6 之外）

- 🟠 cross-tenant LRU sub-cap（与 auth 引入 PR 一起）
- 🟡 multi-worker — Redis pub/sub 或 sticky routing
- 🟡 `get_conversation` + `get_agent_for_user` schema-level join
- 🟡 `evict_expired` dirty flag（在 workers=1 假设下未应用）
- 🟡 每个 turn events 达到 5000+ 时拆分为 `events_chunks` 表

---

## 决策依据摘要（TL;DR）

W5 trace storage 基础设施本就按可持久化全部 SSE event 的结构设计（`{msg_id}-{seq}` event_id、保证顺序、可 dedup）。在此基础上增加**一层 in-memory broker**，即可做到 (a) 客户端断开也不丢 token，(b) 无需重复 LLM 调用即可续传，(c) 自然支持 multi-device 同步展示。成本约 ~6 天开发 + lightweight m34 migration + 每个 run ~400KB memory。ROI 为正。运维上的已知限制（process-local broker、backend 整体宕机时 fallback 到 DB replay）已明确接受。
