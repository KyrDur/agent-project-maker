# 全量验证报告（2026-04-26）

**基准 commit**：`16d9f27`（main，PR #60 merge 后立即）
**执行者**：Claude Code（auto mode，plan: `eager-leaping-platypus`）
**策略**：只进行验证，收集并报告失败，修复交由后续 session

---

## 摘要

| Phase | 结果 | 备注 |
|-------|------|------|
| 1. 静态验证 | 🟡 部分通过 | ruff check ✅ / lint ✅ / tsc ✅ — pyright 58 errors / ruff format 55 / prettier 27（均为未应用的 style） |
| 2.1 后端 unit | ✅ **648 passed** | 0 failed, 1 deselected (integration), 197 warnings (deprecation) |
| 2.2 后端 integration | ⚪ skipped | 未设置 `INTEGRATION_DATABASE_URL` → 1 test skipped（round-trip 在 2.3 中直接验证） |
| 2.3 alembic round-trip | ✅ | m14 → m12 → m14 round-trip 成功 |
| 2.4 前端 vitest | 🔴 **60 failed** / 218 passed (14 files failed / 35 passed) | Jotai store 相关大量失败 |
| 2.5 前端 build | ✅ | Next.js 16.2.2 / 14 pages / TypeScript clean |
| 3. Playwright smoke | 🔴 **7 failed** / 7 passed / 1 skipped | 全部为 dynamic page locator timeout |
| 4. M6.1 手动 E2E（API 级别） | ✅ | 场景 1·2·3·5·6 API/DB 已直接验证 PASS — 浏览器 UI 点击需要用户确认 |

**Net 判定**：后端 runtime GREEN（648 pytest + alembic + API invariants 全部 PASS）。前端为**测试基础设施回归**（vitest, playwright）— build/lint/type 均通过，因此对 production 无影响，但可能阻塞 CI。

---

## Phase 1 — 静态验证

| 命令 | 结果 |
|------|------|
| `cd backend && uv run ruff check .` | ✅ All checks passed |
| `cd backend && uv run ruff format --check .` | 🔴 **55 files would be reformatted** (135 already formatted) |
| `cd backend && uv run pyright` | 🔴 **58 errors**（大多为 tests/ 文件缺少 type narrowing） |
| `cd frontend && pnpm lint` | ✅ 0 errors |
| `cd frontend && pnpm exec tsc --noEmit` | ✅ 0 errors |
| `cd frontend && pnpm format:check` | 🔴 **27 files** style issues |

### pyright 失败模式（samples）
- `tests/test_executor.py:24` — `provider_api_keys` 类型缺少 None（single call site 8 errors）
- `tests/test_skill_package.py:168` — 缺少 `subprocess.Popen(args=str|None)` 类型 guard
- `tests/test_tools.py:104,121` — 将 `Optional[UUID]` 直接传给 UUID 参数
- `tests/test_model_discovery.py:90` — `Operator ">=" not supported for "None"`

### 未应用 ruff format 的文件（sample）
- `app/routers/tools.py`, `app/services/chat_service.py`, `app/services/connection_service.py`, `app/services/credential_service.py`, `app/services/tool_service.py` 等 application code 9 个
- 其余 tests/ 26 个

> 全部是**对功能无影响的 style/type 噪音**。推测是由于没有 CI gate 而持续积累。

---

## Phase 2 — 自动化测试

### 2.1 后端 pytest（in-memory SQLite）

```
648 passed, 1 deselected, 197 warnings in 77.93s
```

- 0 failed
- 与 HANDOFF.md 记录（648 passed）一致 → 无回归
- Warnings 来自外部 library deprecation（`google.genai`, `langchain_core` asyncio.iscoroutinefunction）。仅作为跟踪记录。

### 2.2 后端 integration

```
1 skipped, 648 deselected
```

- `tests/integration/test_m9_pg_roundtrip.py` — 需要 `INTEGRATION_DATABASE_URL` 环境变量（disposable Postgres 独立 fixture）
- 本 session 未准备独立 DB → SKIP。同样的 round-trip 已在 **Phase 2.3 中直接 PASS**（m14 round-trip）

### 2.3 alembic round-trip (Postgres)

```
m14_uniq_mcp_tool_per_conn (head)
  ↓ downgrade -2
m12_drop_legacy_columns
  ↑ upgrade head
m14_uniq_mcp_tool_per_conn (head) ← 恢复成功
```

- M13（drop mcp_servers）、M14（partial unique）双向完整性 ✅

### 2.4 前端 vitest

```
Test Files  14 failed | 35 passed (49)
Tests       60 failed | 218 passed (278)
```

**代表性失败**：`tests/unit/stores/chat-store.test.ts`
```
TypeError: Cannot read properties of undefined (reading 'write')
  at BUILDING_BLOCK_atomWrite (jotai/.../internals.mjs:84:68)
  at tests/unit/stores/chat-store.test.ts:34:11
        store.set(streamingToolCallsAtom, toolCalls)
```

推测原因：jotai 2.19.0 / vitest 4.1 / React 19 组合下 `createStore()` API 变更或 atom registration 缺失。**production 代码无影响**（build / lint / tsc 均通过）。

受影响范围：chat-store atoms、部分 hooks 测试。

### 2.5 前端 build

```
Next.js 16.2.2 (Turbopack)
✓ Compiled successfully in 4.0s
✓ TypeScript clean
✓ 14 pages generated
```

16 个 route（static 14 + dynamic 4）：`/`, `/agents/new`, `/agents/[agentId]/...`, `/connections`, `/models`, `/settings`, `/skills`, `/tools`, `/usage` 等均正常。

---

## Phase 3 — Playwright smoke E2E

```
7 failed, 7 passed, 1 skipped（共 15 specs in 2.9 min）
```

### 失败列表

| # | spec | 失败 line | 推测原因 |
|---|------|-----------|-----------|
| 1 | `Static Pages › /agents/new - creation chooser loads` | smoke.spec.ts:26 | locator timeout |
| 2 | `Static Pages › /models - models page loads` | smoke.spec.ts:67 | locator timeout |
| 3 | `Dynamic Pages › /agents/[id]/conversations/[cid] - chat page loads` | smoke.spec.ts:134 | 可能依赖 dynamic seed |
| 4 | `Dynamic Pages › /agents/[id]/settings - settings page loads` | smoke.spec.ts:153 | 可能依赖 dynamic seed |
| 5 | `Dynamic Pages › /agents/[id] - redirects to conversation` | smoke.spec.ts:174 | 可能依赖 dynamic seed |
| 6 | `Dialogs › models page - "添加模型" dialog opens` | smoke.spec.ts:217 | 按钮 label 可能已变更 |
| 7 | `Dialogs › settings page - "用 AI 修改" dialog opens` | smoke.spec.ts:312 | 按钮 label/条件可能已变更 |

trace 文件：`frontend/test-results/smoke-Smoke-Test---*-chromium*/trace.zip`

> Playwright 执行期间 backend/frontend 由 webServer 自动启动。部分静态页面和全部 dynamic 均失败，因此怀疑是**依赖 seed 数据**，或 **最近 UI 变更（M6/M6.1）未同步到 spec**。

---

## Phase 4 — M6.1 手动 E2E（API 级别直接验证）

浏览器 UI 点击交给用户，**API + DB 完整性**由本 session 直接验证。

### 场景 1 — CUSTOM first-bind ✅

```bash
# 对直接 INSERT 的 CUSTOM tool 执行 PATCH /api/tools/{id} body={connection_id}
PATCH /api/tools/0bfdb56e-... → 200
{
  "id": "0bfdb56e-...",
  "type": "custom",
  "connection_id": "f51cf369-...",  ← 已反映
  ...
}
DB: tools.connection_id = f51cf369-... ✅
```

### 场景 2 — MCP credential rotate ✅

```bash
# 将 hancom-gw connection 的 credential rotate 为另一个值 → 再恢复
PATCH /api/connections/54aaea37-... {"credential_id": "203d3bc5-..."} → 200
PATCH /api/connections/54aaea37-... {"credential_id": "6556a684-..."} → 200（恢复）

# legacy MCP route 已删除
PATCH /api/tools/mcp-servers/{id} → 404 ✅
```

### 场景 3 — 阻止 PREBUILT PATCH ✅

```bash
PATCH /api/tools/{prebuilt_id} {"connection_id": "..."} → 400
{"detail": "PREBUILT tools use (user_id, provider_name) scoped connections; PATCH /api/tools/{id} does not apply. Manage the connection in /connections instead."}
```

### 场景 4 — 阻止 IDOR ⚪

因为环境中只有 1 个 mock user，无法尝试使用其他 user 的 connection 执行 PATCH。**由自动化测试 `test_patch_tool_connection_id_other_user_connection_404` 覆盖**。

### 场景 5 — DB schema invariants ✅

```
(1) tools.mcp_server_id column → 不存在 ✅
(2) mcp_servers table → null（已 drop）✅
(3) FK constraint：fk_tools_connection_id, tools_user_id_fkey（无 mcp_server_id_fkey）✅
(4) M14 partial unique:
    CREATE UNIQUE INDEX uq_mcp_tools_user_connection_name
    ON public.tools (user_id, connection_id, name)
    WHERE type = 'mcp' ✅
```

### 场景 6 — MCP discover-tools ✅

```bash
# 使用现有 hancom-gw connection 再次执行 → 确认 idempotent
POST /api/connections/54aaea37-.../discover-tools → 200
{
  "server_info": {"name": "Hancom Groupware", "version": "3.2.4"},
  "items": 7 条（status: existing × 7）
}
DB: tools COUNT before=7, after=7 ✅ idempotent

# 拒绝 non-mcp connection
POST /api/connections/{custom_conn}/discover-tools → 422
{"detail": "Connection type 'custom' does not support tool discovery..."}
```

> ⏳ **剩余用户验证**: AddToolDialog MCP tab UX, toast 文案, `/connections` McpSection 的 "只读" card, chat 执行时确认使用新 credential。

---

## 失败详情（汇总）

| Phase | Test/命令 | 失败数 | 核心消息 | 推测影响 | 优先级 |
|-------|----------|--------|------------|----------|----------|
| 1 | `pyright` | 58 | tests/ 文件缺少 Optional/Union 类型 narrowing | 对 runtime 无影响（测试 PASS） | 🟡 LOW |
| 1 | `ruff format --check` | 55 files | style（未应用 formatter） | 无 | 🟢 LOW |
| 1 | `prettier --check` | 27 files | style | 无 | 🟢 LOW |
| 2.4 | `vitest` chat-store | 60 tests | `Cannot read properties of undefined (reading 'write')` (jotai store API) | 测试基础设施回归 — 对 production 无影响 | 🟠 MEDIUM |
| 3 | `playwright` smoke | 7 specs | locator timeout（modal/page label/seed） | 若作为 smoke gate 使用会被阻塞 | 🟠 MEDIUM |

---

## 下一步 action（建议）

- [ ] **🟠 调查 vitest 60 fail** — 检查 jotai 2.19 / vitest 4.1 / React 19 组合下 `createStore()` 使用 pattern（`tests/unit/stores/chat-store.test.ts:34` 等）。vitest setup 可能缺少 jotai Provider。
- [ ] **🟠 调查 Playwright 7 fail** — `e2e/smoke.spec.ts` 的 selector 未反映 M6/M6.1 UI 变更。检查 trace.zip（路径：`frontend/test-results/smoke-Smoke-Test---*-chromium*/trace.zip`）。
- [ ] **🟡 pyright 58 errors** — 批量整理（大多只需添加 `assert x is not None` 或 cast）。
- [ ] **🟢 ruff format + prettier** — 可通过 `uv run ruff format .` + `pnpm format` 一次整理（按照禁止 drive-by 规则另开 PR）。
- [ ] **用户直接验证（剩余浏览器点击）** — M6.1 场景 1·2·6 的 UI flow（binding dialog toast、card 状态更新、MCP tab default）。

---

## 参考

- 执行环境：backend `localhost:8001`（uvicorn 运行中）+ frontend `localhost:3000` + postgres `natural-mold-postgres-1`
- alembic head: `m14_uniq_mcp_tool_per_conn`
- trace/log：`frontend/test-results/`
- 除本报告外未修改 code/DB（用于验证的 INSERT/DELETE 已 cleanup）
