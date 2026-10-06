# 工作交接 — feature/w3-out-m3-get-stream (M3 + M4 + review fix)

> 新 session 进入: 本文件 + `progress.txt` 最后4-5个 section + `~/.claude/plans/1-ux-quirky-canyon.md`。
> 设计: `docs/design-docs/adr-011-sse-stream-resume.md`。
> ⚠️ 首项工作: 确认分支是否已 merge → 如果是 main 则 `/sync` 后 M5。

## 最后状态

- 分支: **`feature/w3-out-m3-get-stream`** (HEAD `358b2ab`, **尚未创建 PR**)
- main HEAD: `568cfd4` (PR #116 merge 时点), alembic head **m34**（无变化）
- backend **815 pass** / pyright 0 errors / ruff clean / frontend lint·test·build clean
- 对用户无影响 (仅 GET endpoint + lifecycle 整理, frontend 尚未集成)

## 本轮（8个 commit）

| Commit | 内容 |
|---|---|
| `3cf5086` | **M3** — GET `/api/conversations/{id}/stream?run_id=&last_event_id=` (4个分支) |
| `94f6ca8` | **M4** — `register_broker_eviction_job` (60s) + `BrokerRegistry.close_all` + lifespan |
| `1a5a0f5` | pyright fix — `subscribe` `AsyncIterator → AsyncGenerator` |
| `f2e0b33` | **review BLOCKER+HIGH** — shutdown 顺序 / oracle 统一 (单一 404) / broker.conv_id None fail-closed / 运营 logging |
| `3c00682` | **review MEDIUM 7** — `event_names.py` / corrupt evt skip / stale id fallback / tz fix / lowercase header / `close_for_conversation` logging / `get_agent_for_user` |
| `65a22e0` | **review NIT 5** — `_normalize_event_id` / `_clear()` underscore / 移除 `resume_gone` / `aclose` 回归 |
| `358b2ab` | `/simplify` — `slice_events_after` 共享 helper / `_log_resume_reject` / `_format_brokered` inline |

## 下一步工作

1. **M5 — Frontend lastEventId + withAutoResume + reconnect indicator** (~10h, plan M5). 新增8 + 修改8个文件
2. **M6 — 集成测试 + 中断模拟** (~6h). e2e 4个场景
3. 可先创建并 merge M3+M4 PR → 再开始 M5（PR 大小减半）

## 有意 follow-up

- 🟠 cross-tenant LRU sub-cap（与 auth 引入 PR 一起）
- 🟡 multi-worker 支持 — Redis pub/sub 或 sticky routing
- 🟡 `get_conversation` + `get_agent_for_user` schema-level join（当前 2 round-trip）
- 🟡 `evict_expired` dirty flag（在 workers=1 假设下未应用）
- 🟡 每个 turn events 达到 5000+ 时拆分为 `events_chunks` 表

## 已知问题

- W3-out 新增全局规则 (`~/.claude/rules/security.md` enumeration oracle / `~/.claude/rules/async-lifespan.md` shutdown 顺序) — **下个 session 起生效**
- W6 trace 映射: m32 以前 row `linked_message_ids = NULL`

## 代码 convention（本轮落地）

- **SSE event 名称**: `agent_runtime/event_names.py` 单一 source。禁止 magic string
- **Resume endpoint guard**: 所有失败统一 `404 RESUME_NOT_FOUND`。仅通过 `_log_resume_reject(reason, ...)` 将 reason 记录到 server log (rules/security.md)
- **Shutdown 顺序**: in-flight consumer → `await asyncio.sleep(0)` → scheduler → DB (rules/async-lifespan.md)
- **Naive UTC 比较**: 避免 `.timestamp()`（会按本地 tz 解释）。直接比较 `datetime`
- **Events slicing**: `slice_events_after[E: Mapping](events, after_id)` — broker subscribe + DB replay 共享

## 验证

```bash
cd backend && uv run alembic upgrade head && uv run ruff check . && uv run pytest tests/ && uv run pyright
cd frontend && pnpm lint && pnpm test --run && pnpm build
```

## 核心文件（M3+M4 入口）

- broker: `backend/app/agent_runtime/event_broker.py` (`slice_events_after`, `close_all`, tz fix)
- routes: `backend/app/routers/conversations.py` (`stream_resume`, `_log_resume_reject`, `_replay_resume_generator`)
- lifecycle: `backend/app/scheduler.py` (`register_broker_eviction_job`) + `backend/app/main.py`
- helpers: `backend/app/services/chat_service.py:get_agent_for_user`, `backend/app/agent_runtime/event_names.py`
- 测试: `backend/tests/integration/test_stream_resume.py` (15项)
- Plan: `~/.claude/plans/1-ux-quirky-canyon.md` (M5/M6 section)

## 新 track 开始检查

1. `gh pr view feature/w3-out-m3-get-stream` 确认是否 merge（当前尚未创建 PR）
2. 建议创建 PR — backend 自洽，对用户无影响
3. 开始 M5 时: 新建 `feature/w3-out-m5-frontend` 分支（从当前分支切出）
4. plan M5 section — `withAutoResume` + `lastEventIdRef` + `reconnect-indicator.tsx`
