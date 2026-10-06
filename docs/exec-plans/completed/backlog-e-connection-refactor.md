# Backlog E — Connection entity 统一重构（执行计划）

**状态**：已终止·废弃并由后续方案承接 — ADR-009 移除 Connection 模型，并替换为 Credential 直连结构。
2026-09-08 对照源码后移至归档。以下阶段与等待批准文案是
2026-04-18 当时的计划，并非待恢复的工作列表。
**编写日期**：2026-04-18（M0 补强：2026-04-18）
**前置条件**：需在引入多用户认证前完成
**范围**：合并 Backlog E + F（CredentialPickerDialog 通用 shell）
**ADR**: [`adr-008-connection-entity.md`](../../design-docs/adr-008-connection-entity.md)

---

## M0 共识事项（摘要）

通过设计访谈确认以下决策。详细依据参见 ADR-008。

| 项目 | 决策 |
|------|------|
| `provider_name` | VARCHAR 自由字符串。PREBUILT 使用 `credential_registry` enum validator，MCP/CUSTOM 自由 |
| UNIQUE 约束 | **无**。仅 UUID PK + user_id FK + `(user_id, type, provider_name)` index |
| `user_id` | NOT NULL FK（权限隔离的基础） |
| env fallback | **从用户工具执行路径移除**。仅系统内部功能（creation_agent、图像生成）保留 env |
| M3 迁移 | mock user 的 env 值 → credential → 自动 seed default connection |
| `is_default` | 每用户每 provider 1 个。`agent_tools.connection_id = NULL` → 使用 default，有值则 override |
| `extra_config` | 仅 MCP 使用：`{url, auth_type, headers?, env_vars?, transport?, timeout?}`。PREBUILT/CUSTOM 为 NULL |
| MCP `env_vars` | 允许 credential 字段引用 template（`${credential.xxx}`）。M1 仅 schema，M2 实现解析 |
| CUSTOM 共享 | 1 credential = 1 connection，多个工具 N:1 共享 |
| 回滚 | M2~M5 保留 legacy 列 read-only + 必须支持 Alembic downgrade |

---

---

## 1. 需求摘要

**目标**：把 MCP/PREBUILT/CUSTOM 工具的 credential 绑定统一到单一 `connections` entity。在引入多用户认证前完成前置工作。

**解决对象**：
1. PREBUILT 共享 row 的 credential 混乱（user A 的连接被 user B 覆盖）
2. 绑定位置不一致（MCP=服务器粒度 / CUSTOM=工具粒度 / PREBUILT=共享 row）
3. 3 个 auth dialog 重复（吸收 Backlog F）

**范围外**：
- 多用户认证（登录/session）— E 完成后单独处理
- 保留工具执行 builder（`build_naver_search_tool` 等）的 `auth_config` dict 接口
- 更改 LangGraph PostgresSaver checkpoint 结构

---

## 2. 当前结构（探索结果摘要）

### Backend 解析路径
```
chat_service.build_tools_config (chat_service.py:164-205)
  ├── MCP: mcp_servers.credential_id → resolve_credential_data → auth_config
  │       OR mcp_servers.auth_config (inline)
  │       （MCP 中忽略 tool.credential_id — PR #47）
  └── PREBUILT/CUSTOM: tool.credential_id → resolve_credential_data → auth_config
          OR tool.auth_config (inline)

agent_tools.config → merged_auth = {**cred_auth, **link.config}

executor._prepare_agent
  ├── PREBUILT → create_prebuilt_tool(name, auth_config) → build_*_tool
  ├── CUSTOM → create_tool_from_db(..., auth_config) → _build_http_tool_func
  └── MCP → _build_mcp_tools → _AuthInjectorInterceptor
```

### 5 类 Provider（`credential_registry.py`）
- `naver` (api_key)
- `google_search` (api_key)
- `google_workspace` (oauth2)
- `google_chat` (api_key)
- `custom_api_key` (api_key)

### Frontend
- `CredentialSelect` / `CredentialFormDialog`：已有通用 component（4 处复用）
- 3 个 `*-auth-dialog.tsx`：90% 相同 — 区别仅是保存 endpoint 与 provider filter
- `/connections` 页面：以 Credential CRUD 为主（尚无 Connection 概念）

---

## 3. 设计方向

### Connection entity schema
```sql
connections（新增）
  id                UUID  PK
  user_id           UUID  FK users (NOT NULL)
  type              VARCHAR(20)   -- 'prebuilt' | 'mcp' | 'custom'
  provider_name     VARCHAR(50)   -- naver, google_search, google_workspace, ...
  display_name      VARCHAR(200)  -- UI 显示名称
  credential_id     UUID  FK credentials (nullable, ON DELETE SET NULL)
  extra_config      JSON  nullable   -- MCP: {url, auth_type}
  status            VARCHAR(20)   -- 'active' | 'disabled'
  created_at / updated_at
  UNIQUE (user_id, type, provider_name, display_name)
```

### 各工具类型连接
| 类型 | 解析逻辑 |
|------|----------|
| **PREBUILT** | `tool.provider_name` + `current_user_id` → 查询 `connections`（per-user, per-provider）。解决共享 row 问题 |
| **MCP** | `tool.connection_id`（1 connection = 1 MCP server，extra_config={url, auth_type}） |
| **CUSTOM** | `tool.connection_id`（将当前 credential_id 路径间接化为 connection） |

### `mcp_servers` 处理
吸收到 Connection 后 drop。通过 migration 迁移数据（type='mcp', extra_config={url, auth_type}）。

### `agent_tools` override
- 新增 `agent_tools.connection_id`（optional FK）— 特定 Agent 可使用非 default 的 connection
- 现有 `agent_tools.config` inline override 在 M6 废弃

### UI 统一（吸收 F）
3 个 `*-auth-dialog.tsx` → 通用 `ConnectionBindingDialog` + context prop（`{type, provider}`）。保存 endpoint 统一走 connection API。

### 保留基于 env 的 fallback
保留 `(auth_config or {}).get("naver_client_id") or settings.naver_client_id` 模式。无 Connection 时使用服务器 env 默认值。

---

## 4. 里程碑（6 PR）

> 单个 PR 规模不可行。每个 milestone 都应**可独立部署** + **大小适合审查**。milestone 之间保留 legacy fallback，确保随时可部署。

### **M0: ADR + 详细 spec**（docs PR，可单 session）
- 编写 `docs/design-docs/adr-008-connection-entity.md`
  - context/decision/alternatives/consequences 4 个 section
  - 确认 schema、解析逻辑、迁移策略
- 更新本 exec-plan 文档（补充细节）
- 测试场景列表（回归 + 新增）
- **产出**：ADR + exec-plan 最终版

### **M1: Connection 表 + CRUD API**（backend PR，可单 session）
- Alembic `m8_add_connections` — table + index + UNIQUE
- 新增 `app/models/connection.py`
- `app/schemas/connection.py` — CreateConnection, UpdateConnection, ConnectionResponse
- `app/services/connection_service.py` — CRUD + credential resolution helper
- `app/routers/connections.py` — `GET/POST/PATCH/DELETE /api/connections`
- 保留 `mcp_servers` table（parallel run）
- **尚未使用** → 对现有系统影响 0
- 新增测试：`tests/test_connections.py`
- **完成标准**：全部 pytest 通过，现有功能回归 0

### **M2: MCP → Connection 迁移** (backend PR, 推荐 TTH)
- Alembic `m9_migrate_mcp_to_connections` — 每个 `mcp_servers` row → `connections` row (type='mcp', extra_config={url, auth_type})
- 添加 `tools.connection_id` 列 (nullable FK)
- 将 `mcp_servers` 数据 → 复制到 `connections` + 以 `tools.mcp_server_id` 为基准映射 `tools.connection_id`
- 将 `chat_service.build_tools_config` 的 MCP 分支重写为经由 connection
- deprecate `mcp_servers` 表 (read-only, 尚未 drop)
- `test_mcp_connection`, `test_tools_router_extended` 回归验证
- **完成标准**：MCP 工具执行路径全部经由 connection，现有 MCP 测试通过

### **M3: PREBUILT per-user Connection** (backend + 部分 frontend)
- Backend: 修改 PREBUILT 解析逻辑
  ```python
  if tool.type == PREBUILT:
      conn = get_connection(user_id, provider_name=tool.provider_name, type='prebuilt')
      cred_auth = resolve_credential_data(conn.credential) if conn else {}
  ```
- `tools.credential_id` 在 PREBUILT 中忽略 (legacy fallback 保留至 M6)
- 保留 env var fallback 路径 (`settings.naver_*`)
- Frontend: 在 `/connections` 页面支持创建 PREBUILT connection (provider 下拉菜单)
- **完成标准**：多个用户可以使用各自的 connection 执行 PREBUILT 工具 (mock user 多 ID 测试)

### **M4: CUSTOM Connection 集成** (backend + 部分 frontend)
- Backend: CUSTOM 工具也经由 `tool.connection_id`
- Alembic `m10_migrate_custom_credentials` — 对现有带 `tool.credential_id` 的 CUSTOM 工具 → 创建 connection 后设置 FK
- `tools.credential_id` 从此时起 deprecated (M6 时 drop)
- Frontend: 重新接线 `add-tool-dialog.tsx` 的 Custom 标签页以创建 connection
- **完成标准**：CUSTOM 工具的全部执行路径经由 connection

### **M5: UI 集成 + 吸收 F** (frontend PR)
- 新增 `components/connection/ConnectionBindingDialog.tsx` — 通用 shell
- 替换 `prebuilt-auth-dialog.tsx` / `custom-auth-dialog.tsx` / `mcp-server-auth-dialog.tsx`
- 重新接线 `add-tool-dialog.tsx` MCP/Custom 标签页 (创建 connection)
- 重构 `/connections` 页面：以 Credential 为中心 → 以 Connection 为中心 (Credential 作为下级辅助)
- `agent_tools.connection_id` override UI (Agent 设置页面)
- 确认移除 3 个 dialog 的重复实现 (F 视为完成)

### **M6: Cleanup** (backend + frontend)
- Alembic `m11_drop_legacy_columns`:
  - drop `mcp_servers` 表
  - `tools.credential_id` drop
  - drop `tools.auth_config` (inline 字段)
  - `tools.mcp_server_id` drop
  - `agent_tools.config` drop (inline override)
- 移除 legacy fallback 代码 (credential_service 的 `resolve_server_auth`, `tool.credential_id` 分支)
- 整理类型/注释 (从 `lib/types/index.ts` 移除 deprecated 字段)
- 更新 HANDOFF.md — E 完成，下一项工作 = 多用户认证

---

## 5. 修改文件汇总

### Backend
| 文件 | 影响里程碑 |
|------|--------------|
| `app/models/connection.py` | M1 新增 |
| `app/models/tool.py` | M2(添加 connection_id), M6(legacy drop) |
| `app/models/mcp_server.py` | M2(deprecate), M6(drop) |
| `app/models/agent.py` (agent_tools) | M5(connection_id), M6(config drop) |
| `app/services/connection_service.py` | M1 新增 |
| `app/services/chat_service.py:164-205` | 按 M2/M3/M4 分支修改，M6 整理 |
| `app/services/credential_service.py` | M6 (移除 `resolve_server_auth`) |
| `app/routers/connections.py` | M1 新增 |
| `app/routers/tools.py` | M6 整理 auth_config 路由 |
| `alembic/versions/*` | M1(m8) / M2(m9) / M3(m10 PREBUILT seed 整理) / M4(m10?) / M6(m11 drop) |
| `app/seed/default_tools.py` | M3 整理 provider_name |
| `tests/test_connections.py` | M1 新增 |
| 现有 tool/mcp 测试 | M2~M4 回归更新 |

### Frontend
| 文件 | 影响里程碑 |
|------|--------------|
| `components/connection/ConnectionBindingDialog.tsx` | M5 新增 |
| `components/tool/prebuilt-auth-dialog.tsx` | M5 替换 |
| `components/tool/custom-auth-dialog.tsx` | M5 替换 |
| `components/tool/mcp-server-auth-dialog.tsx` | M5 替换 |
| `components/tool/add-tool-dialog.tsx` | M5 重新接线 |
| `app/connections/page.tsx` | M3 PREBUILT UI, M5 重构为以 Connection 为中心 |
| `lib/api/connections.ts` | M1 新增 |
| `lib/hooks/use-connections.ts` | M1 新增 |
| `lib/types/index.ts` | M1 Connection 类型, M2 Tool.connection_id, M6 移除 legacy |

---

## 6. 风险因素

| 风险 | 缓解措施 |
|------|--------|
| **数据迁移期间的双重状态** (M1~M5 期间 `mcp_servers` + `connections` 共存) | M2 中单向 sync，`mcp_servers` 设为 read-only deprecate。M6 中 drop |
| **PREBUILT env fallback 失效** (`settings.naver_*`) | M3 中无 connection 时保留 env fallback 路径 + 必须测试 |
| **agent_tools.config override 语义变更** | M5 引入 `connection_id` override 时，对现有 `link.config` 数据做一次性 migration。M6 前也接受 inline |
| **PoC mock user 前提与多用户前提混杂** | 各里程碑测试中用多个 user_id case 验证 (多个 mock user)。真正的多用户为后续 PR |
| **M1 通过后到 M6 的较长期间持续生产部署** | 设计为每个里程碑都可独立部署 — 保留 legacy fallback |
| **drop MCP server 表时的影响范围** | M6 前进行全量测试 + prod DB snapshot + rollback migration 验证 |
| **frontend/backend 类型不一致** | M1~M4 每个 PR 必须同步更新 `lib/types/index.ts` (PR checklist) |
| **credential_registry 与 connection.provider_name 不一致** | M0 ADR 中明确 enum 一致性，从 M1 起通过 validator enforce |

---

## 7. 验证策略

**各里程碑通用**：
```bash
cd backend
uv run ruff check .
uv run pytest
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head

cd ../frontend
pnpm lint && pnpm build
```

**各里程碑追加**：
- M1: 新增 test_connections.py (CRUD, IDOR)
- M2: MCP 工具执行 smoke + 验证 mcp_server_id→connection_id 映射
- M3: 用两个 mock user 执行同一个 PREBUILT 工具 — 确认各自使用不同 credential
- M4: CUSTOM 工具执行回归
- M5: 替换 3 个 dialog 后，对各 workflow 做 E2E (agent-browser)
- M6: 全量集成回归 + Alembic 双向往返

---

## 8. 推进策略建议

- **M0**：可在单个 session 中完成 (仅文档)。ADR 共识很重要。
- **M1~M4**：每个里程碑 = 1 PR = 1 worktree + 推荐 1 session。TTH 或独立实现均可。
- **M5**：以 frontend 为主 — `frontend` Agent 或独立完成。
- **M6**：Cleanup — 虽小但回归风险高，因此专注 QA。

每个里程碑完成时更新 HANDOFF.md + 下一里程碑文档链接。

---

## 9. Checklist (所有 PR 通用)

- [ ] Alembic migration 上下双向往返 PASS
- [ ] `backend/tests/` 新增 + 全量回归 PASS
- [ ] `frontend/` lint + build PASS
- [ ] frontend/backend 类型同步
- [ ] 在 HANDOFF.md 中反映进度状态
- [ ] 更新 ADR-008 状态 (如需要)
