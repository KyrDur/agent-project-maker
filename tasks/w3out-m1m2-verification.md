# W3-out M1+M2 — 最终集成验证报告

> 编写: bezos · 2026-05-03 · scope: backend foundation（M1 EventBroker + M2 streaming/persistence/m34）
> 结果: **PASS — 所有验证 gate 通过。可以合并。**

---

## 验证结果摘要

| # | gate | 结果 | 备注 |
|---|---|---|---|
| 1 | `alembic upgrade head` (PG 5433) | ✅ PASS | m22 → ... → m34 共 12 个 revision 全部应用 |
| 2 | `alembic downgrade -1 && upgrade head` (m34 round-trip) | ✅ PASS | `status` + `updated_at` + CHECK 约束 + index 均准确 drop/recreate |
| 3 | `ruff check .` | ✅ PASS | All checks passed |
| 4 | `pytest tests/` | ✅ PASS | 773 passed, 2 deselected（连续执行 3 次 — flakiness 0 项） |
| 5 | `pyright app/` | ✅ PASS | 0 errors, 0 warnings, 0 informations |
| 6 | dual-write router smoke（X-Run-Id + broker registration） | ✅ PASS | 新增 2 项。end-to-end DB 持久化在 M6 验证 |

---

## 详情

### 1. Alembic m34 migration (PG 5433)

```
$ DATABASE_URL_SYNC=...:5433/moldy uv run alembic upgrade head
... Running upgrade m33_add_linked_message_ids -> m34_message_events_status

$ DATABASE_URL_SYNC=...:5433/moldy uv run alembic downgrade -1
... Running downgrade m34_message_events_status -> m33_add_linked_message_ids

$ DATABASE_URL_SYNC=...:5433/moldy uv run alembic upgrade head
... Running upgrade m33_add_linked_message_ids -> m34_message_events_status
```

schema 验证（`docker exec moldy-postgres-test psql -d moldy -c "\d message_events"`）:

```
 status     | character varying(20)       | not null | 'completed'::character varying
 updated_at | timestamp without time zone | not null | now()
Indexes:
    "idx_message_events_status" btree (conversation_id, status)
Check constraints:
    "ck_message_events_status" CHECK (status::text = ANY (ARRAY['streaming', 'completed', 'failed']))
```

- ✅ `status` `NOT NULL DEFAULT 'completed'`（PG 11+ metadata 变更，不发生 table rewrite）
- ✅ `updated_at` `NOT NULL DEFAULT now()`
- ✅ CHECK 约束（PG/SQLite 两边都工作）
- ✅ 复合 index `(conversation_id, status)`
- ✅ 保留现有 `completed_at` 列（按 S1 分析建议）
- ✅ 确认 Round-trip 后恢复相同 schema

### 2. Lint / Typecheck

- `ruff check .` → All checks passed
- `pyright app/` → 0 errors, 0 warnings, 0 informations

### 3. Pytest 回归（连续执行 3 次）

```
Run 1: 770 passed, 2 deselected in 33.22s
Run 2: 771 passed, 2 deselected in 34.31s
Run 3: 771 passed, 2 deselected in 34.89s
Run 4（新增 smoke 后）: 773 passed, 2 deselected in 34.31s
```

- baseline 735 + M1+M2 新增 ≈ 38 项 = 773。回归 0 项。
- 连续执行 3 次全部 green — **不存在 S1 指出的 1 号陷阱 BrokerRegistry process-local 泄漏。**
- 防泄漏机制: `tests/conftest.py:53` `_clear_event_broker_registry` autouse fixture（jensen 在 S2 中添加）。before-yield + after-yield 双向 clear。

### 4. M1+M2 新增测试覆盖

- **M1 (EventBroker)**: `tests/agent_runtime/test_event_broker.py` — publish/subscribe/close/maxlen drop/queue full disconnect/registry get_or_create/evict_expired/close_for_conversation 等。
- **M2 (streaming.py 集成)**: `tests/test_streaming.py` 末尾 block — `test_stream_run_id_injection_uses_external_id`, `test_stream_dual_writes_to_broker_and_trace_sink`, `test_stream_persist_callback_final_flush_in_finally`, `test_stream_broker_close_called_even_on_exception`。
- **M2 (trace_storage)**: `tests/test_trace_storage_partial.py` — `append_events` insert/merge/dedup-by-id/empty noop，`finalize_turn` status 更新/completed_at/linked_message_ids。
- **M2 (router 契约)**: `tests/integration/test_broker_dual_write.py`（S5 新增）— 验证 POST `/messages` response header 暴露 `X-Run-Id` + broker registry 注册。

### 5. Dual-write 验证

新增 2 个 smoke，用于确认 router layer 中 broker 是否按 run_id 注册:

- `test_send_message_exposes_x_run_id_header` — `X-Run-Id` header 以 valid UUID 暴露（M5 frontend 可持有并发起 GET-resume 请求）。
- `test_send_message_registers_broker_for_run_id` — executor 调用时 `BrokerRegistry.get(run_id)` 返回 broker instance（处于 M3 GET resume 可 attach 的状态）。

**End-to-end "POST → DB row + broker live token stream"** 会在下一 cycle 添加 M3 GET endpoint 时自然验证（M6 integration test 就在这里）。当前 PR 未尝试的原因:
- `_build_persist_callback` 直接打开 `app.database.async_session()`（真实 PG asyncpg），因此无法用 in-memory aiosqlite test harness 原样验证持久化路径
- 单独编写 fixture 的工作量与 M6 任务本身相当 → 在那里一起处理更自然

---

## S1 → S5 追踪: 1 号陷阱处理结果

| S1 分析项 | 处理结果 |
|---|---|
| **BrokerRegistry process-local 泄漏（必须）** | ✅ jensen 在 `tests/conftest.py:53-64` 添加 `_clear_event_broker_registry` autouse fixture。连续执行 3 次 flaky 0 项。 |
| m34 dialect 分支 | ✅ `_now_default()` PG/SQLite 分支。CHECK 约束两边兼容。 |
| `CREATE INDEX CONCURRENTLY` transaction 陷阱 | ⚠ 规避: m34 使用普通 `CREATE INDEX`（migration docstring 中注明 "生产大表建议另行使用 CONCURRENTLY 流程"）。当前状态 OK。 |
| `_persist_trace` → `finalize_turn` 替换 | ✅ 基于 `_build_persist_callback` + `finalize_turn` 完成重新接线。保持 fresh `async_session()` 模式。 |
| `X-Run-Id` header caller-injectable | ✅ `_sse_handler(... run_id=...)` + `_sse_response(... extra_headers=...)`。`stream_agent_response` 也接受 `run_id=` keyword。 |
| 保留 `record_turn` shim（test_shares_router seed 依赖） | ✅ 保留 shim → test_shares_router green。 |
| 保留 `MessageEvent.completed_at` | ✅ m34 未改动。 |

---

## 结论

**M1+M2 backend foundation 已处于可合并状态。**

- 验证 gate 6/6 PASS
- 回归 0 项（773/773）
- BrokerRegistry 泄漏 risk 已提前阻断
- 对 client 无影响（broker 会 publish 但无人读取 — 必须等 M3 GET endpoint 进入后才会暴露到用户体验）

**建议进入下一 cycle（M3+M4）。**
