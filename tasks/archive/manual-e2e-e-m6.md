# Manual E2E — Backlog E M6（缩减 cleanup）

**作者**: 贝索斯（QA DRI，S5 集成验证）
**日期**: 2026-04-21
**基础**: S3 Jensen + S4 Zuckerberg 产出 + S5 自行验证
**验证方式**: (A) 自动回归全量 + (B) grep 保留/删除 invariant + (C) alembic round-trip docker PG + (D) 手动 E2E 5 个场景（用户执行检查清单）
**浏览器实测**: **未执行** — 在 Satya S6 或用户 PR review 阶段执行。通过静态路径追踪 + pytest fail-closed 覆盖证明。

---

## 0. 自动验证结果（全部 PASS）

| 项目 | 预期 | 实际 | 耗时 | 判定 |
|------|------|------|------|------|
| Backend ruff | 0 error | `All checks passed!` | 0.14s | PASS |
| Backend pytest | 624 pass（S3 减少值） | `624 passed, 1 deselected, 3 warnings` | 81.21s | PASS |
| Frontend lint | 现有 1 项（use-chat-runtime.ts:74） | `1 problem (0 errors, 1 warning)` 相同位置 | 4.40s | PASS（新增 0） |
| Frontend build | 15 routes | `✓ 15 routes` Turbopack | 10.19s | PASS |
| Alembic upgrade | m12_drop_legacy_columns | PG docker round-trip PASS | — | PASS |
| Alembic downgrade -1 | m11_custom_connection | PG docker PASS | — | PASS |
| Alembic re-upgrade | m12_drop_legacy_columns | PG docker PASS | — | PASS |

**执行命令（贝索斯 S5）**:
```bash
cd backend && uv run ruff check .                  # PASS
cd backend && uv run pytest -q                     # 624 passed
cd frontend && pnpm lint                           # 1 warning (pre-existing)
cd frontend && pnpm build                          # 15 routes PASS
# Postgres round-trip (external docker natural-mold-postgres-1, fresh DB moldy_m6verify)
DATABASE_URL=postgresql+asyncpg://moldy:moldy@localhost:5432/moldy_m6verify uv run alembic upgrade head    # m12 head
DATABASE_URL=... uv run alembic downgrade -1                                                                # m11
DATABASE_URL=... uv run alembic upgrade head                                                                # m12 head
```

---

## 1. grep invariant（删除 0 / 保留项存在）

### 1-1. 删除 scope — 预期 app 代码中 0 项

| 模式 | 对象 | 实际 | 判定 |
|------|------|------|------|
| `rg "\.auth_config" backend/app/` (py) | Tool/AgentToolLink | 4 项 — 全部为 **MCPServer.auth_config**（转入 M6.1） | PASS |
| `rg "link\.config\|AgentToolLink.*config" backend/app/` | agent_tools.config | **0** | PASS |
| `rg "tool\.credential_id\|Tool\.credential_id" backend/app/` | Tool.credential_id | **0**（除 chat_service.py:299 docstring） | PASS |
| `rg "ToolConfigEntry\|tool_configs\|ToolAuthConfigUpdate" backend/app/` | legacy schema | **0** | PASS |
| `rg "_mask_auth_config\|AUTH_CONFIG_MASK" backend/app/` | masking util | **0** | PASS |
| `rg "_resolve_legacy_tool_auth" backend/app/` | legacy resolver | **0** | PASS |
| `rg "\.auth_config" frontend/src --ts/tsx` | FE Tool.auth_config | 3 项 — **MCPServer** 相关（types 347/364 + hooks 注释 102） | PASS |
| `rg "tool_configs\|agent_config" frontend/src` | FE dead | **0** | PASS |
| `rg "updateAuthConfig\|useUpdateToolAuthConfig" frontend/src` | FE dead API | **0** | PASS |

### 1-2. 保留 scope — 转入 M6.1（必须存在）

| 模式 | 位置 | 结果 | 判定 |
|------|------|------|------|
| `mcp_server_id` | `backend/app/models/tool.py:71` | 存在 | PASS |
| `class MCPServer` | `backend/app/models/tool.py:34` | 存在 | PASS |
| `resolve_server_auth` | `backend/app/services/credential_service.py:111` | 存在 | PASS |
| `useUpdateMCPServer` | `frontend/src/lib/hooks/use-tools.ts:97` | 存在 | PASS |

---

## 2. 直接确认 DB schema（docker PG，fresh upgrade head）

```
-- \d tools（现有列）
id, user_id, type, mcp_server_id, name, description, parameters_schema,
api_url, http_method, auth_type, created_at, is_system, tags,
connection_id, provider_name

-- ★ 缺失列（确认 M6 drop）★
auth_config, credential_id   -- 不存在

-- FK
fk_tools_connection_id → connections(id) ON DELETE SET NULL
tools_mcp_server_id_fkey → mcp_servers(id)   -- 保留到 M6.1
tools_user_id_fkey → users(id)

-- \d agent_tools（现有列）
agent_id, tool_id

-- ★ 缺失列（确认 M6 drop）★
config   -- 不存在

-- mcp_servers 表
SELECT to_regclass('mcp_servers')   -- → mcp_servers（存在，转入 M6.1）
```

**判定**: PASS — M6 缩减 scope 的 3 个 drop 全部应用，MCP 路径完整保留。

---

## 3. 调查潜在回归点（重新验证 S1 贝索斯警告点）

### 3-1. 移除 `credential_service.get_usage_count` — Tool.credential_id 后是否仍正常工作

**调查**:
- 调用处 grep：`rg "get_usage_count"` → 1 个（`routers/credentials.py:93`）
- 新查询：`SELECT count(*) FROM tools JOIN connections ON tools.connection_id = connections.id WHERE connections.credential_id = X`（credential_service.py:130-136）
- `mcp_server_count` 查询仍使用 MCPServer.credential_id（M6.1 转入 scope）
- pytest `test_credentials.py` 5/5 PASS

**判定**: PASS — 无回归。保持 credential 使用位置聚合功能。UI 调用 `/api/credentials/{id}/usage` 正常工作。

### 3-2. 删除 `_resolve_legacy_tool_auth` 后 CUSTOM null connection_id fail-closed 覆盖

**调查**:
- `chat_service.py:302-306` — CUSTOM tool 中 `tool.connection_id is None` → raise `ToolConfigError`
- pytest 覆盖：
  - `test_custom_resolves_raises_when_connection_id_is_null` PASS（新增 M6 场景）
  - `test_custom_resolves_raises_when_connection_missing_despite_fk` PASS
  - `test_custom_disabled_connection_fails_closed` PASS
  - `test_custom_connection_with_null_credential_fails_closed` PASS
- `test_connection_custom_resolve.py` 中共 12/12 PASS

**判定**: PASS — fail-closed 4 个场景全部覆盖。删除 legacy resolver 无回归。

### 3-3. 移除 `_mask_auth_config` 后是否可能发生 masking 泄漏

**调查**:
- M6 之后 `ToolResponse` 已没有 `auth_config` 字段本身 — masking 对象消失
- `MCPServerResponse.auth_config`（转入 M6.1）属于独立区域，仅用于内部 CRUD，现有 masking 策略为 raw 返回（保持现有行为）
- `rg "_mask\|AUTH_CONFIG_MASK\|mask_auth"` backend/app/ → **0**

**判定**: PASS — masking 泄漏 0 项。Tool 路径无敏感数据暴露路径。

---

## 4. 手动 E2E 场景（用户执行检查清单）

**准备**:
```bash
docker compose up -d postgres   # 或复用现有 natural-mold-postgres-1
cd backend && uv run alembic upgrade head     # 确认 m12 head
cd backend && uv run uvicorn app.main:app --reload --port 8001
cd frontend && pnpm dev
# → http://localhost:3000
```

### 场景 1 — PREBUILT 路径无回归（Naver）

**目的**: 证明 M3/M5 无回归。

1. [ ] 进入 `/connections` → "Prebuilt"区域 → "Naver"卡片 → "添加连接"
2. [ ] 打开 ConnectionBindingDialog → 选择（或创建）新 Credential → "连接"
3. [ ] 确认 `connections` 表中创建 `type=prebuilt, provider_name='naver', is_default=true, status='active'` row（开发者工具 Network 标签页 POST /api/connections 201）
4. [ ] 移动到 `/tools` → 确认"Naver 网页搜索"等 Naver provider tool 卡片显示**"已认证（绿色）"**徽章
5. [ ] "添加工具" → 将 Naver 搜索工具绑定到 agent
6. [ ] agent 聊天 → "搜索最近的 AI 新闻"等 query → 确认响应流正常（工具调用成功）

**预期结果**: 所有步骤正常。工具执行时 `cred_auth` = connection.credential.data 解析，保持 PREBUILT auto-match。

### 场景 2 — CUSTOM 路径无回归

**目的**: M4 自定义 connection 自动创建无回归。

1. [ ] `/tools` → "添加工具" → Custom 标签页 → 输入名称/URL/方法 → 选择新 Credential → "创建"
2. [ ] Backend：`POST /api/tools/custom` → 确认 body 中**没有** `credential_id: null` 字段（Zuckerberg S4 修改）
3. [ ] `tools` 表中创建 row，`tools.connection_id IS NOT NULL`（兼容 m11 migration），`tools.credential_id` **列本身不存在**（m12）
4. [ ] tool 卡片"已认证"状态
5. [ ] 绑定到 agent → 在聊天中调用工具 → custom API 执行成功

**预期结果**: `chat_service.build_tools_config` → Gate A: connection active → Gate B: credential resolve → merged_auth = cred_auth（已移除 agent_tools.config merge）。200 响应。

### 场景 3 — MCP 路径无回归（保留 M6.1 scope）

**目的**: 证明 MCP 相关代码（live）未被 M6 破坏。

1. [ ] `/tools` → "添加工具" → MCP 标签页 → URL/名称 + 选择 Credential → "注册"
2. [ ] `POST /api/tools/mcp-server` → 201。`mcp_servers` 表创建 row，设置 `tools.mcp_server_id`
3. [ ] `/connections` → MCP 区域 → 对应服务器卡片 → "管理连接" → ConnectionBindingDialog
4. [ ] 更改 Credential → 保存 → `useUpdateMCPServer` → 确认 PATCH `/api/tools/mcp-servers/{id}` 200
5. [ ] 绑定 agent → 聊天 → MCP 工具调用成功

**预期结果**: MCPServer CRUD 4 类 + resolve_server_auth + chat_service MCP fallback 全部 live。已准备好提升到 M6.1。

### 场景 4 — Connection fail-closed（保持 kill-switch）

**目的**: `status='disabled'` kill-switch 在 M6 后仍有效。

1. [ ] 延续场景 1 — `/connections` → Naver 卡片 → 切换"禁用"（PATCH status='disabled'）
2. [ ] agent 聊天 → query"搜索一下"
3. [ ] 确认工具调用时出现 **`ToolConfigError`**。SSE 错误事件显示"connection disabled"类消息
4. [ ] 检查 backend 日志 — `chat_service._resolve_custom_auth` or `_resolve_prebuilt` → `raise ToolConfigError`

**预期结果**: pytest `test_custom_disabled_connection_fails_closed` + `test_prebuilt_disabled_fails_closed` 自动覆盖此路径。实际 UI 中再次确认相同路径。

### 场景 5 — 直接确认 DB 结构（m12 schema invariant）

**目的**: 生产部署后 DBA 检查清单。

```sql
-- psql 或 docker exec
\d tools
-- 预期：
--   auth_config 列不存在
--   credential_id 列不存在
--   mcp_server_id 列存在（转入 M6.1）
--   connection_id 列存在

\d agent_tools
-- 预期：（agent_id, tool_id）仅 2 列。config 列不存在

SELECT to_regclass('mcp_servers');
-- 预期：'mcp_servers'（转入 M6.1）

-- data 完整性
SELECT COUNT(*) FROM tools WHERE connection_id IS NULL AND type = 'custom';
-- 预期：0（m11 migration 已全部迁移完成）。若存在则 fail-closed，并要求用户重新设置

SELECT COUNT(*) FROM tools WHERE provider_name IS NULL AND type = 'prebuilt' AND is_system = true;
-- 预期：0（m10 回填完成）
```

**判定条件**: 上述所有查询与预期值一致。

---

## 5. 综合判定

| 区域 | 结果 |
|------|------|
| 自动回归（ruff/pytest/lint/build） | 全部 PASS |
| Alembic round-trip (docker PG) | PASS |
| grep invariant（删除 0 / 保留项存在） | PASS |
| DB schema 实测 | PASS |
| 潜在回归点 3 个 | 全部 PASS |
| 手动 E2E 5 个场景 | 文档化完成（等待用户执行） |

**贝索斯判定**: **绿色** — 完成 M6 缩减 scope（auth_config + credential_id + agent_tools.config 共 3 个 drop）的集成验证。S3 Jensen + S4 Zuckerberg 产出无回归集成。未越界 MCP 边界（转入 M6.1）。Satya 可推进 S6（commit）。
