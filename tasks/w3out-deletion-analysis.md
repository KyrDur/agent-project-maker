# W3-out 删除分析 — 引入 M1+M2 前的整理候选

> 编写: bezos · 2026-05-03 · scope: backend SSE 持久化路径
> Plan: ~/.claude/plans/1-ux-quirky-canyon.md
> 一句话结论: **几乎没有值得删除的 dead code。** 大部分 "M2 集成时一起简化" 才是正确答案。真正的陷阱是 BrokerRegistry process-local singleton 的测试泄漏。

---

## 1) 删除候选

### A. 随 M2 集成一起消失的代码（可立即移除 OK）

| 位置 | 项目 | 依据 |
|---|---|---|
| `app/routers/conversations.py:217-239` | 整个 `_persist_trace()` 函数 | M2 中替换为直接调用 `trace_storage.finalize_turn(...)`。4 个 endpoint（`send/resume/edit/regenerate`）中的 `on_complete=lambda: _persist_trace(...)` 全部一并替换。 |
| `app/routers/conversations.py:433/459/545/634` | 每个 endpoint 入口处的 `trace_sink: list = []` + `msg_id_sink: list = []` boilerplate（重复 4 次） | M2 中 broker 同时接收 publish + persist_callback，因此 sink 注入本身不再需要。若 `_sse_handler`（或 `_resolve_agent_context`）创建 1 个 broker 并连同 callback closure 一起封装，4 个 endpoint 可各减少 8 行。**建议: M2 工作时一起整理**。 |
| `app/agent_runtime/streaming.py:62-63 docstring` | "trace_sink (optional, W5)" 说明 + `trace_sink/msg_id_sink` keyword | M2 后 caller 可通过 `broker` 获取相同信息。**但立即删除有风险** — `tests/test_streaming.py` 25 个 + `tests/test_executor.py` 中的 stream_agent_response patch 依赖 sink keyword。**建议: M2 中作为 backward-compat keyword 保留，在 M5/M6 后续 PR 中移除 sink。** |
| `app/models/message_event.py:46-48` | `completed_at: datetime \| None` 列 | Phase 1 只在 "stream 结束时 set 一次"，与 `created_at` 语义重复。M2 引入 `status='streaming'`/`'completed'`/`'failed'` + `updated_at` 后，`completed_at` 可收窄为 **status='completed' 转换时刻**。**建议: 立即删除 X — m34 migration 只 ADD COLUMN，`completed_at` 再保留一个 cycle**（legacy reader/share router 虽未使用，但可能暴露在 JSON dump）。M5 整理时评估 drop。 |

### B. 不必特意改动（建议保留）

| 位置 | 项目 | 理由 |
|---|---|---|
| `app/services/trace_storage.py:43-86` | `record_turn()` | 计划明确写明: "现有 `record_turn` 是 backward-compat shim"。`tests/test_shares_router.py:175`、`tests/test_trace_storage.py` 12 个直接调用。M2 中改为调用 `finalize_turn` 的 thin wrapper，以保持兼容。 |
| `app/services/trace_storage.py:28-40` | `_extract_msg_id()` | M2 后仍可用于 fallback 路径（例如首次 batched flush 前 caller 手中没有 `assistant_msg_id` 时）。作为 module internal helper 保留。 |
| `app/services/trace_storage.py:89-108` | `get_traces_for_conversation` / `get_trace_by_msg_id` | 两者都保留。后者仍用于 M3 GET resume 的 replay 路径。前者由 share router 使用。 |
| `_sse_handler` (conversations.py:182) | 整体 | 刚由 P0-A SIMPLIFY 提取的 helper。M2 只需在签名中添加 `run_id` + `extra_headers={"X-Run-Id": ...}`。函数本身保留。 |
| `MessageEvent.linked_message_ids` | 列 + W6 hydration 路径 | shared page chip 正在使用。与 M2 修改无关。 |

### C. 真正的 dead code（扫描结果）

- **无。** 上述涉及的 4 个文件中的函数/方法都有 1+ 调用处。已确认 `grep -rn _persist_trace` `record_turn` `get_traces_for_conversation` `get_trace_by_msg_id` `stream_agent_response` `_sse_handler` 均有活跃调用处。

---

## 2) 受 M1+M2 影响的现有测试

### High risk — M2 工作中需要直接更新

| 文件 | case 数 | 风险 / 所需变更 |
|---|---|---|
| `tests/test_conversations_router.py` | 19（其中 streaming 4: send/resume/edit/regenerate） | **BrokerRegistry 泄漏**。由于是 process-local singleton dict，一旦测试间状态泄漏就会 flaky。M2 工作时在 `conftest.py` 中以 `autouse fixture` 调用 `registry._brokers.clear()` 或 `evict_expired(ttl_seconds=0)`。建议 send 测试新增 `X-Run-Id` 响应 header 验证。 |
| `tests/test_trace_storage.py` | 12 | `record_turn` shim 时新增验证 `MessageEvent.status='completed'`、`updated_at` 是否填充。现有断言应原样通过（仅新增字段时）。作为回归信号使用。 |

### Medium risk — 只要保持签名兼容即可通过

| 文件 | case 数 | 备注 |
|---|---|---|
| `tests/test_streaming.py` | 25 | 给 `stream_agent_response` 添加 `broker=None, persist_callback=None` 时保持 default-None。所有现有调用都是 keyword-arg，因此安全。新增 1 个分支测试验证 `emit()` 在 broker None 时是否 skip publish。 |
| `tests/test_executor.py` | 13（stream_agent_response patch 13 个） | mock 函数签名自由，因此新增 keyword 无害。**但确认 executor 是否显式传 broker=None** — 若不传，就不会向 mock 传 unexpected kwarg，因此 OK。默认值流为 None 即可。 |
| `tests/test_chat_integration.py` | 约 6 | 全 stream e2e。broker registry 泄漏风险同上。若 send response header 暴露 `X-Run-Id` 即 OK。 |

### Low risk — 实际上几乎无影响

| 文件 | 备注 |
|---|---|
| `tests/test_shares_router.py` | 仅使用 `record_turn` 调用（seed）。签名相同。 |
| `tests/test_migration_m{18,20,21,22}.py` | M2 中新增 `tests/test_migration_m34.py` 属于本 PR 范围（round-trip + idempotent）。现有 m18~m33 不修改。 |
| 其他 ~600个 | 无直接影响。 |

---

## 3) 注意事项（实现者 = jensen）

1. **BrokerRegistry process-local singleton 的测试泄漏是 1 号陷阱。** 一旦在 `app/agent_runtime/event_broker.py` 放置 module-level `registry = BrokerRegistry()`，broker 会在整个 pytest session 中累积。**必须**在 `backend/tests/conftest.py` 添加以下内容:
   ```python
   @pytest.fixture(autouse=True)
   def _clear_event_broker_registry():
       from app.agent_runtime import event_broker
       event_broker.registry._brokers.clear()  # 或添加 reset 方法
       yield
       event_broker.registry._brokers.clear()
   ```
   否则 `test_chat_integration` + `test_conversations_router` 会按 random 顺序失败。

2. **m34 migration 必须做 dialect 分支。** SQLite（测试 in-memory）不支持 (a) `CREATE INDEX CONCURRENTLY`，(b) PG ENUM。模式照搬 `m20_add_health_check_history` / `m21_add_daily_spend_aggregates` 的 `_has_table/_has_column/_has_index` + dialect helper。CHECK 约束（`status IN ('streaming','completed','failed')`）在 PG/SQLite 两边都最简单。

3. **`CREATE INDEX CONCURRENTLY` 不能在 transaction 内执行。** alembic 默认会开启 transaction。应在 `with op.get_context().autocommit_block():` 中调用 `op.execute("CREATE INDEX CONCURRENTLY ...")`。SQLite 分支使用普通 `op.create_index`。

4. **将 `_persist_trace` → `finalize_turn` 替换时保持 fresh session 模式。** 当前 `_persist_trace` 使用 `async with async_session() as session` + `await session.commit()`。因为在 SSE generator 的 finally 中调用，此时 request-scoped db 已 close。`finalize_turn` 也应基于相同假设，统一为调用方负责分离（或 finalize 内部打开 `async_session()`）二选一，并在 docstring 中说明。

5. **`emit()` 的 broker.publish 是 hot path。** 每个 Token chunk 约每 50ms 调用。`asyncio.Queue.put_nowait` 虽是同步，但存在 lock 竞争。测量后若出现回归，再增加 broker batch push 选项。先保持简单 path。

6. **`X-Run-Id` header 必须在 SSE generator 启动前确定。** `stream_agent_response` 内部才创建 msg_id（streaming.py:76），因此当前流程 router 事先不知道。解决: (a) router 提前生成 `run_id = uuid.uuid4()` 并通过 `stream_agent_response(..., run_id=run_id)` 注入 — 将 streaming.py:76 的 `msg_id = str(uuid.uuid4())` 改为 caller-injectable。或 (b) `_sse_handler` peek generator 第一个 chunk，从 message_start 中提取 id（复杂，不推荐）。**推荐 (a)。**

7. **保留 `record_turn` 签名。** 即使改成 shim，也要保持 caller（test_shares_router seed）以 `events=[...], raw_msg_ids=[...]` 形式调用。内部委托调用 `finalize_turn(... status='completed')`。

8. **m34 中不要动 `MessageEvent.completed_at`。** 两者都是允许 NULL 的列，只是语义略有重叠。再保留一个 cycle 后整理。

9. **share router 回归 0 guard。** `tests/test_shares_router.py:148` 的 seed case 是最快的回归信号。M2 PR pre-push gate 中至少先确认该 suite 通过。

---

## TL;DR

- **仅删除 1 项**: `_persist_trace()`（M2 中切换到 `finalize_turn` 时一起删除）。
- **简化 1 项**: 4 个 endpoint 的 `trace_sink/msg_id_sink` boilerplate → 吸收到 broker 注入。
- **其余保留**: 保持 backward-compat 的回归风险最低。
- **真正风险不在代码而在测试隔离**: `BrokerRegistry` autouse fixture 必须。
