# progress.txt — backlog E M6.1

## 项目 context
- **目标**：确定 `tool.connection_id` single source of truth + 彻底删除 MCP legacy
- **Base**: main @ 18d98be（M6 PR #59 merge）
- **branch**: feature/backlog-e-m6-1
- **Worktree**: `.claude/worktrees/backlog-e-m6-1`
- **计划**：`/Users/chester/.claude/plans/m6-1-spicy-kurzweil.md`

## M6 继承资产（原样使用）
- m12 migration pattern（`backend/alembic/versions/m12_drop_legacy_columns.py`）— 作为 m13 template 使用
- `services/legacy_invariants.py` — m13 preflight helper 添加位置
- `main.py::_enforce_m6_legacy_invariants` — 扩展 startup guard
- `useFindOrCreateCustomConnection` — 前端 CUSTOM N:1 find-or-create
- `frontend/src/lib/types/index.ts` Tool 类型（M6 中已删除 auth_config/credential_id）
- pytest baseline：**624 passing**（M6 完成时）

## M6.1 删除对象（按文件:行）

### Backend
- `backend/app/models/tool.py:34` — `class MCPServer`
- `backend/app/models/tool.py:71` — `mcp_server_id` FK column
- `backend/app/models/tool.py` — `Tool.mcp_server` relationship
- `backend/app/services/credential_service.py:111` — `resolve_server_auth(server: MCPServer)`
- `backend/app/services/chat_service.py:384-392` — MCP fallback 分支（有注释 `# Legacy fallback — M3~M6 过渡期... M6.1 中删除`）
- `backend/app/services/tool_service.py` — 6 个 MCPServer CRUD 函数（`list_mcp_servers`, `register_mcp_server`, `update_mcp_server`, `delete_mcp_server` 等）
- `backend/app/routers/tools.py` — `/api/tools/mcp-server*` 4 个 route + 重写 `test_mcp_connection`
- `backend/app/schemas/tool.py` — `MCPServerCreate` / `MCPServerResponse` / `MCPServerUpdate` + `ToolResponse.mcp_server_id`

### Frontend
- `frontend/src/lib/hooks/use-tools.ts:97` — `useUpdateMCPServer`（类似地 useRegisterMCPServer、useMCPServers、useDeleteMCPServer、useToolsByConnection 的 mcp_server_id 引用）
- `frontend/src/lib/api/tools.ts` — `updateMCPServer` + 4 类 MCP server CRUD
- `frontend/src/lib/types/index.ts` — 全部 `MCPServer*` 类型 + `Tool.mcp_server_id`
- `frontend/src/components/tool/mcp-server-rename-dialog.tsx` — 删除整个文件
- `frontend/src/components/connection/connection-binding-dialog.tsx:339-345, 421-429` — 删除 `needsOptionDFirstBind` guard
- `frontend/src/components/connection/connection-binding-dialog.tsx:479` — 删除 `useUpdateMCPServer` 调用（MCP body）
- `frontend/src/components/tool/mcp-server-group-card.tsx:143-151` — 清理 triggerContext

## M6.1 新增对象

### Backend
- `backend/app/schemas/tool.py::ToolUpdate` — `connection_id: UUID | None` 单一字段，`extra="forbid"`
- `backend/app/services/tool_service.py::update_tool(db, tool_id, user_id, payload)`
- `backend/app/routers/tools.py` — `PATCH /api/tools/{id}`
- `backend/alembic/versions/m13_drop_mcp_legacy.py`

### Frontend
- `frontend/src/lib/api/tools.ts::toolsApi.update(id, { connection_id })`
- `frontend/src/lib/hooks/use-tools.ts::useUpdateTool`
- `frontend/src/components/connection/binding-dialog-shell.tsx` — 抽取公共 Shell

## Invariants（禁止变更）
- PREBUILT 使用 `(user_id, provider_name)` scope。不使用 `tool.connection_id`。收到 PATCH 请求时返回 **400**。
- PREBUILT `provider_name IS NULL` → `cred_auth = {}`（与 env fallback 等价）
- CUSTOM `connection_id` 为 NULL 时 `ToolConfigError` fail-closed（无 legacy delegation）
- aiosqlite 测试使用 model-based create_all。alembic round-trip 只在 docker PG 中执行。
- 传播 `extra="forbid"` — 前端/测试使用新字段时必须真实反映在 schema 中

## Codebase Patterns（M6 确认）
- Alembic revision naming：`m{N}_<snake_case>`。最新 head = `m12_drop_legacy_columns`。下一个 = `m13_drop_mcp_legacy`。
- FK constraint naming：显式时为 `fk_<table>_<col>`，未指定时为 PG 默认 `<table>_<col>_fkey`
- service layer：Router → Service → Model，async SQLAlchemy 2.0，select() 语法
- 测试惯例：`backend/tests/test_<resource>.py`，aiosqlite in-memory conftest

## Gotchas（继承自 M6）
- `tools.mcp_server_id` FK 名称 `tools_mcp_server_id_fkey` 由 initial migration 未命名创建，因此采用 PG 默认命名。部署前必须通过 `\d tools` 实测（`m12-cleanup-migration-spec.md §8.2`）。
- `useUpdateTool` naming conflict — use-tools.ts 中曾有 `useUpdateToolAuthConfig`（M6 中已删除）等 precedent。grep 后决定。
- `test_mcp_connection` route 完全改写为经由 connection entity。mcp URL/auth 从 `connection.extra_config` 读取。
- `mcp-server-rename-dialog.tsx` 在 M6 中因 "禁止 drive-by" 而保留 — M6.1 中是删除对象。connection rename 可由 `/connections` page 的 PATCH 替代 (M5 UI 集成部分)。
- `triggerContext` prop 仅在 PrebuiltBody L178-180 使用 (搜索结果)。删除或统一二者择1。
- `connection-binding-dialog.tsx` 的 CustomBody/McpBody/PrebuiltBody 使用相同 hydration pattern（hydrationKey, hydratedFor, mode state）→ 可抽取 Shell。

## 团队成员间契约
- **贝索斯 M1 → 全员**：删除对象确定报告（GREEN 判定）出来后，M2/M4 并行启动
- **詹森 M2 → 扎克伯格 M4**：`ToolUpdate` schema + `PATCH /api/tools/{id}` route commit 后，前端可调用 API（扎克伯格可提前定义类型）
- **詹森 M3 → 扎克伯格 M5**：`mcp_servers` drop + `/api/tools/mcp-server*` 删除 commit 后重接前端 MCP
- **贝索斯 M6**：所有实现完成后进行集成回归 + 手动 E2E

## 失败教训
（暂无）

## M1 贝索斯发现（2026-04-24）

### 新增 Gotcha
- `credential_service.get_usage_count` 返回中存在 `mcp_server_count` key（L172）。M3 删除时会传播到前端 `CredentialUsage` 类型（lib/types/index.ts L210-213）+ `/connections` page 使用量 badge。**M3 启动前必须 grep `CredentialUsage` consumer**。
- `test_mcp_connection` route 路径为 `POST /api/tools/mcp-server/{id}/test`。重写后改为 `POST /api/tools/{tool_id}/test`，路径语义变化（server_id → tool_id）。需要全面确认前端 `toolsApi.testMCPConnection(serverId)` 调用处（grep 结果可能为当前 0 处）。
- `frontend/src/app/tools/page.tsx` L472-495 的 mcp grouping 基于 `mcp_server_id`。M5 将 grouping key 重映射为 `tool.connection_id` 时保持 UX（group card section），仅替换内部 key — 禁止 scope creep。
- `connection-binding-dialog.tsx` McpBody（L456-516）使用双重 PATCH（server + connection）pattern。M5 重接时计划缩减为 `useUpdateConnection`（extra_config）+ `useUpdateTool`（connection rebind）组合 — 完全移除 server PATCH。

### 已确定决定
- **`useUpdateTool` 无 naming conflict**（grep 已确认）。可使用该 hook 名。
- `executor.py` L263-267, L401 的 `mcp_server_url`/`mcp_tool_name`/`mcp_transport_headers` key 在**connection 路径中也原样使用** — 不是删除对象 (K)。
- `schemas/connection.py` L125, L186 的 `resolve_server_auth`/`MCPServerResponse` 注释只是 docstring 引用 — L186 清理 (D), L125 保留 (K)。
- `chat_service.py` L393-394 `else: cred_auth = {}` MCP fallback 分支删除后**改为 `ToolConfigError` fail-closed** (与 CUSTOM 路径一致)。
- BindingDialogShell 只迁移**UI chrome（Dialog/Header/Footer/Credential section）**。hydration 逻辑由 body 持有 — 避免 abstraction 成本。
- `tests/integration/test_m9_pg_roundtrip.py` 中的 5 处 MCPServer 引用**保留**（m9 migration round-trip 测试 — M6.1 中不要碰）。

### Scope creep 警告
- `agent_tools.connection_id` override 属于 M5.5 — 不在 M6.1 范围。
- `ToolUpdate` 仅有 `connection_id` 一个字段。禁止扩展 `name`/`description` 等。
- `/tools` page MCP group section UX 保留 — grouping key 仅从 `mcp_server_id` → `connection_id`。
- 保持 PREBUILT PATCH 400 原则 — 禁止诱惑把 connection_id 填到 `is_system=True` PREBUILT row 中。

### 判定：GREEN
- M2/M4 可立即启动。M3 启动前只需再确认一次前端 `CredentialUsage.mcp_server_count` consumer。

## M2 詹森决定（2026-04-24）

### 实现位置
- `schemas/tool.py` — `ToolUpdate(BaseModel)`（`model_config = ConfigDict(extra="forbid")`, `connection_id: uuid.UUID | None = None`）。新增 pydantic v2 ConfigDict import。
- `services/tool_service.py::update_tool` — 放在 `delete_tool` 前。使用 `selectinload(Tool.connection)` + `selectinload(Connection.credential)`。
- `routers/tools.py` — `PATCH /{tool_id}`（response_model=ToolResponse）。放在 `DELETE /{tool_id}` 正上方（FastAPI 路径优先级安全，与 `/mcp-server/*` 无冲突）。

### 验证顺序（HTTP code mapping）
1. tool 不存在 → `tool_not_found()`（404）
2. user-tool & 属于其他 user → `tool_not_found()`（404，防止信息泄露）
3. PREBUILT(ToolType.PREBUILT) → 400 with English detail "PREBUILT tools use (user_id, provider_name) scoped connections..."
   - is_system PREBUILT row 也相同 — 因为是 global asset，跳过 ownership 检查后在 PREBUILT 分支拒绝
4. payload.connection_id is not None:
   - connection 不存在或属于其他 user → 404 "Connection not found"（IDOR）
   - connection.type != tool.type → 422 with detail
5. payload.connection_id is None → 直接 `tool.connection_id = None` 后 commit（解绑）
6. `await db.refresh(tool, attribute_names=["connection"])` — eager refresh

### 测试（新增 9 个，baseline 624 → 633）
- `test_patch_tool_connection_id_custom_success` — CUSTOM 正常 200
- `test_patch_tool_connection_id_mcp_success` — MCP 正常 200（不使用 mcp_server_id，直接创建 type='mcp' tool）
- `test_patch_tool_connection_id_prebuilt_400` — is_system=True PREBUILT（provider="naver"）→ 400，detail 包含 "PREBUILT"
- `test_patch_tool_connection_id_other_user_connection_404` — 其他 user connection_id → 404
- `test_patch_tool_connection_id_type_mismatch_422` — CUSTOM tool + MCP connection → 422，detail 包含 "does not match"
- `test_patch_tool_connection_id_none_clears_binding` — 发送 None → 200 + null
- `test_patch_tool_nonexistent_404` — 不存在的 tool_id → 404
- `test_patch_tool_unknown_field_422` — `{"name": "renamed"}` extra=forbid → 422
- `test_patch_tool_other_user_owned_tool_404` — PATCH 其他 user 的 user-tool → 404（防止 info leak）
- 新增 helper `_seed_credential_and_connection(db, conn_type, provider_name, display_name)` — 提升测试 fixture 可复用性

### 后续（供扎克伯格 M4）
- 实现 `useUpdateTool` hook 时，`PATCH /api/tools/{id}` body 仅有 `{connection_id: string | null}` 一个字段 — extra 字段返回 422
- 响应为 `ToolResponse`（与现有 GET /api/tools 响应 shape 相同，包含 `connection_id`）
- 发送 `connection_id=null` 时返回 200 + `connection_id: null` — 保证解绑行为

## M4 扎克伯格决定（2026-04-24）

### 文件:行修改摘要
- `frontend/src/lib/api/tools.ts:25-29` — 新增 `toolsApi.update(id, { connection_id })`。PATCH `/api/tools/${id}`，body single field，响应 `Tool`。
- `frontend/src/lib/hooks/use-tools.ts:55-67` — `useUpdateTool()` hook。`invalidateQueries(['tools'])` + `['agents']`。参数签名 `{id, data: {connection_id?: string | null}}`。
- `frontend/src/components/connection/connection-binding-dialog.tsx`
  - L36 — import 中新增 `useUpdateTool`（与现有 `useUpdateMCPServer` 同一行）
  - L314 — 新增 `const updateTool = useUpdateTool()`
  - L335 — 在 `isPending` 中 OR 加入 `updateTool.isPending`
  - L337-341（旧）— 完全删除 `needsOptionDFirstBind` 常量 + `saveDisabled` 计算
  - L343-345（旧）— 删除 `handleSave` guard/toast
  - L352-360（新）— CUSTOM `handleSave` else 分支：`findOrCreate.run` 返回后，当 `tool && !tool.connection_id` 时链式调用 `updateTool.mutateAsync({id: tool.id, data: {connection_id: result.id}})`
  - L421-429（旧）— 删除 warning UI block
  - L435（旧→新）— 将 `disabled={saveDisabled}` → 简化为 `disabled={isPending}`
- 保留 `AlertTriangleIcon` import，因为 McpBody（L526）仍在使用。

### Gotchas
- `pnpm lint` 预期 1 个（use-chat-runtime.ts:74），实际输出为 **0 warnings**。看起来 eslint config 中该规则目前 exempt，或问题已解决 — 贝索斯 M6 回归验证时需再次确认。
- `useFindOrCreateCustomConnection().run` 在 cached scope 中复用 credential_id 匹配的 connection（ADR-008 N:1）。即使共享现有 connection，PATCH /api/tools 也只创建新 binding — safe。不会覆盖其他 tool 的 connection_id。
- 链式顺序: (1) findOrCreate → (2) updateTool. updateTool 失败时 findOrCreate 创建的 connection 可能 "orphaned", 但按 N:1 复用 pattern, 重试时会重新利用，因此没有泄漏 — 贝索斯 M6 手动 E2E 覆盖失败场景。

### 遵守 scope 边界（反映贝索斯警告）
- McpBody（使用 `updateMCPServer`）**未修改** — M5
- `BindingDialogShell` 抽取 **无** — M5
- `mcp-server-rename-dialog.tsx` 删除 **无** — M5
- `triggerContext` 统一 **无** — M5
- `Tool.mcp_server_id` 类型整理 **无** — M5 (`MCPServer*` 类型删除在同一 commit 中)

### 验证结果
- `pnpm lint`: **PASS** (0 warnings, 0 errors)
- `pnpm build`: **PASS**（15 routes 全部编译成功，TypeScript 3.9s）

## M3 詹森决定（2026-04-24）

### 文件:行修改摘要
- `backend/alembic/versions/m13_drop_mcp_legacy.py`（新增）— preflight（`_assert_no_stale_legacy_rows()` → `collect_legacy_checks`）+ drop `tools_mcp_server_id_fkey` + drop `tools.mcp_server_id` column + drop `fk_mcp_servers_credential_id` + drop `mcp_servers` table。SQLite 分支跳过 FK drop（仅结构 round-trip）。down_revision=`m12_drop_legacy_columns`。
- `backend/app/models/tool.py` — 删除整个 `class MCPServer` + `Tool.mcp_server_id` + `Tool.mcp_server` relationship。也整理 `Credential` TYPE_CHECKING import。
- `backend/app/models/__init__.py` — 删除 `MCPServer` import + `__all__`。
- `backend/app/schemas/tool.py` — 删除 `MCPServerCreate`/`MCPServerResponse`/`CredentialBrief`/`MCPServerListItem`/`MCPServerUpdate` + `ToolResponse.mcp_server_id`。删除 `Field` import。
- `backend/app/services/credential_service.py` — 删除 `resolve_server_auth(server: MCPServer)` 函数 + `MCPServer` import + mcp_count subquery + 返回 dict 的 `mcp_server_count` key。返回改为 `{"tool_count": tool_count}`。
- `backend/app/services/tool_service.py` — 删除 `register_mcp_server`/`get_mcp_servers`/`list_mcp_server_items`/`_apply_credential_update`/`update_mcp_server`/`delete_mcp_server` 6 个函数。删除 `MCPServer`/`MCPServerCreate`/`credential_service` import。保留 `update_tool`（M2）/`delete_tool`。
- `backend/app/services/chat_service.py` — 删除 `selectinload(Tool.mcp_server).selectinload(MCPServer.credential)` prefetch chain。将 L384-394 的 elif/else legacy fallback 整体替换为 fail-closed `ToolConfigError`（`MCP tool '{name}' has no connection — execution blocked`）。
- `backend/app/routers/tools.py` — 删除 `POST /mcp-server`（register）、`GET /mcp-server`（list）、`PATCH /mcp-server/{id}`（update）、`DELETE /mcp-server/{id}`（delete）、`POST /mcp-server/{id}/test` 共 4+1 个 route。新增 `POST /{tool_id}/test` — `selectinload(Tool.connection).selectinload(Connection.credential)` + 通过 `extra_config.url`/`env_vars` 路径调用 `mcp_client.test_mcp_connection`。
- `backend/app/error_codes.py` — 删除 `mcp_server_not_found()` factory。
- `backend/app/services/legacy_invariants.py` — 新增 m13 invariant：`WHERE type='mcp' AND mcp_server_id IS NOT NULL AND connection_id IS NULL`（阻止 m9-skip 的 stale rows）。
- `backend/app/main.py` — startup guard column_exists cache loop 中新增 `("tools", "mcp_server_id")`。
- `backend/app/routers/credentials.py` — 删除 `CredentialUsageResponse(mcp_server_count=...)` 参数。
- `backend/app/schemas/credential.py` — 删除 `CredentialUsageResponse.mcp_server_count` 字段。
- `backend/app/schemas/connection.py:186` — 更新 docstring ("M6.1 中 drop mcp_servers").
- `frontend/src/lib/types/index.ts` — 删除 `CredentialUsage.mcp_server_count`。`Tool.mcp_server_id` 为 M5 整理而暂时保留为 optional。
- 测试：`test_tools.py`/`test_tools_router_extended.py`/`test_connection_mcp_resolve.py` — 删除 12 个引用 MCPServer 的 helper/case。保留 `test_m9_pg_roundtrip.py`（m9 history）。

### 新增 Gotcha
- **dev PG migration 被阻断**：执行 `alembic upgrade head` 时出现 `RuntimeError: M13 preflight failed — 7 row(s)`（Hancom-GW MCP server ID `0578a536...`）。这 7 条是在 m9 阶段因 `credential_auth_recoverable=False` 被 skip 的 row → `connection_id IS NULL AND mcp_server_id IS NOT NULL`。代码路径上已是 dead row，但 DROP 前需要萨提亚决定（delete vs manual connection 创建）。
- `routers/tools.py::test_tool_connection` 中，为实现 `selectinload(Tool.connection).selectinload(Connection.credential)` chain 需要直接 import `Connection`（使用 `Tool.connection.property.mapper.class_` 之类的绕法可读性较差）。
- `legacy_invariants.py` 中 `mcp_server_id` 字符串 grep 匹配的是预期 SQL — 不是实际代码引用。
- `frontend/src/app/tools/page.tsx`/`use-tools.ts` 中 `mcp_server_id` 使用处属于 M5（扎克伯格）scope — M3 中仅把类型 optional 保留以保证 build 通过。

### 验证结果
- `uv run pytest`: **621 PASS**（M2 baseline 633 → 删除 12 个 MCP-only test = 621）
- `uv run ruff check .`: **clean**
- alembic preflight：在 dev PG 中准确 abort 7 条（预期行为）

### 避免 Scope creep
- 未触碰 `agent_tools.connection_id`（M5.5）
- 未触碰前端 MCP UI/hook/card（M5）— 仅 optional 保留 `mcp_server_id` TS field
- 保留 `tests/integration/test_m9_pg_roundtrip.py` 的 MCPServer 引用（保护 m9 round-trip）

## M5（扎克伯格，2026-04-25）

### 完成工作
- `frontend/src/lib/api/tools.ts` — 删除 `registerMCPServer`/`listMCPServers`/`updateMCPServer`/`deleteMCPServer` 4 类 + 全部 MCP type import。仅保留 `list`/`createCustom`/`update`/`delete`。
- `frontend/src/lib/hooks/use-tools.ts` — 删除 `useRegisterMCPServer`/`useMCPServers`/`useUpdateMCPServer`/`useDeleteMCPServer` + `invalidateMCPAndTools`。`useToolsByConnection` 中 MCP 分支缩减为只匹配 `tool.connection_id`。
- `frontend/src/lib/types/index.ts` — 删除 `Tool.mcp_server_id`（M3 中 optional 保留的字段）。删除全部 `MCPServer*` 类型（`MCPServer`/`MCPServerListItem`/`MCPServerUpdateRequest`/`MCPServerCreateRequest`）+ `CredentialBrief`。
- `frontend/src/components/connection/binding-dialog-shell.tsx`（新增）— 只抽取 Prebuilt/Custom/Mcp body 共用的 UI chrome（Header/Footer/Credential section + CredentialFormDialog）。hydration/save 逻辑由各 body 保留 — 最小化 abstraction 成本。
- `frontend/src/components/connection/connection-binding-dialog.tsx` — 重写。删除 `triggerContext` prop，PrebuiltProps 新增 `createNew?: boolean`（区分 /connections `+ add` 与 tool-edit rotate）。McpProps 从 `mcpServerId` 完全替换为 `connectionId`，重新设计为 `connectionName`/`currentCredentialId`。McpBody：现有 dual PATCH（`useUpdateMCPServer` + `useUpdateConnection`）→ 单一 `useUpdateConnection`。N:1 shared warning 重新定义为检查 `mcpConnections` sibling。
- `frontend/src/components/tool/mcp-server-group-card.tsx` — 从基于 `MCPServerListItem` 重写为基于 `Connection`。删除 rename menu + `MCPServerRenameDialog` import。delete 使用 `useDeleteConnection({id, type, provider_name})`。credential label 使用 `useCredentials` lookup。
- `frontend/src/components/tool/mcp-server-rename-dialog.tsx` — 删除文件。
- `frontend/src/app/tools/page.tsx` — `useMCPServers()` → `useConnections({type:'mcp'})`。grouping key `mcp_server_id` → `connection_id`。`filteredMCPServers` → `filteredMCPConnections`。`MCPServerGroupCard` prop `server` → `connection`。删除 3 处 `triggerContext="tool-edit"`。
- `frontend/src/app/connections/page.tsx` — `triggerContext="standalone"` → `createNew` (PrebuiltSection), CustomSection 只删除 prop。McpSection "添加连接" 按钮 disabled + `addDisabledHint` tooltip。
- `frontend/src/components/connection/connection-detail-sheet.tsx` — 删除 2 处 `triggerContext` prop 使用（prebuilt 明确改用 `connectionId`，custom 明确改用 `currentConnectionId`，语义保持不变）。
- `frontend/src/components/tool/add-tool-dialog.tsx` — **删除整个 MCP tab**。Tabs → 单一 Custom form。全部删除 `useRegisterMCPServer`/`discoveredTools` state/`handleMCPSubmit`/MCP form fields。
- `frontend/messages/ko.json` — 删除 `connections.bindingDialog.custom.unsupportedFirstBindM6`/`toast.unsupportedFirstBindM6`。删除 `tool.mcpServer.menu.rename`/`rename` block。新增 `connections.sections.mcp.addDisabledHint`。

### 验证结果
- `pnpm lint`: clean
- `pnpm build`: PASS (14 pages, TypeScript clean)
- grep residue 检查（`mcp_server_id|MCPServer|useUpdate/Register/Delete MCPServer|registerMCPServer|listMCPServers|deleteMCPServer|mcp-server-rename|triggerContext|unsupportedFirstBindM6`）：**0 项**
- 只剩 `MCPServerGroupCard` component 名 — 它是展示 MCP server group 的 UI component 的功能性命名，因此不算 residue。

### 决定/顺延（在萨提亚/贝索斯 M6 中反映到 release note）
- **MCP server 新增注册路径顺延到 M6.1 之后**。Jensen M3 drop 了 backend `/mcp-server/*` 4 routes，新增注册 endpoint 因此消失 → AddToolDialog MCP tab 变成 dead code。team lead 已批准选项 1。
- 用户影响：可对现有 MCP tool 进行 credential rotate（`mcp-server-group-card` → `ConnectionBindingDialog type="mcp"`），新增 MCP server 注册 UI 在 `/connections` McpSection 中通过 tooltip 提示并禁用。
- 新增注册路径设计方向：`POST /api/connections (type=mcp, extra_config={url, env_vars})` + backend discovery 自动创建 MCP tool。需要新增 backend endpoint + agent_runtime discovery helper → 单独 scope。

### 避免 Scope creep
- BindingDialogShell 只抽取 UI chrome。PrebuiltBody/CustomBody/McpBody 的 hydration（hydrationKey + hydratedFor pattern）、409 handling、save path 均由各自 body 保留 → 最小化抽象成本/风险。
- 未执行 `MCPServerGroupCard` 文件名/component 名重命名 — UX 保持优先。属于功能性命名，无需做 scope 外清理。

## M6（贝索斯，2026-04-25）— 集成验证完成

### 验证结果全部 PASS
- backend ruff: clean
- backend pytest：621 passed, 1 deselected（M2 baseline 624 → M2 结果 633 → M3 drop 后 621。由于删除 12 个 MCPServer CRUD 专用测试，回归 0）
- frontend pnpm lint：0 warnings / 0 errors（M4 时预计 1 warning 为 false — 实际为 0）
- frontend pnpm build：14 pages PASS（M5 删除 MCP register tab 后 15→14）

### DB round-trip (docker PG)
- 确认 m12 → m13 → m12 → m13 可逆
- `\d tools`：无 mcp_server_id，存在 connection_id
- to_regclass('mcp_servers') = NULL
- 仅 2 个 FK：tools_user_id_fkey, fk_tools_connection_id（无 tools_mcp_server_id_fkey）

### residue grep
- backend：6 处预期 residue（main.py:94 column_exists cache，legacy_invariants.py:73-79 preflight SQL literal，schemas/connection.py:125+186 docstring）
- frontend：0 项（保留 MCPServerGroupCard component 名作为功能性命名）

### 回归测试点
- PATCH tool 9 项（CUSTOM/MCP success, PREBUILT 400, IDOR 404, type mismatch 422, none clears, nonexistent 404, extra forbid 422, 其他 user tool 404）
- chat_service fail-closed 2 项（MCP missing connection raises，MCP with connection succeeds）

### Gotcha（M6 验证中确认）
- dev DB 中 MCP tool 为 0 → 场景 2（MCP credential rotate）无法在浏览器确认。需要在 staging seed 或 PR review 时复现
- m13 downgrade 时 mcp_servers table + FK 正常恢复 → 在 PROD merge 前 确保 safety net
- legacy_invariants.py m13 preflight 用于 PROD 部署前阻止 stale row — 用户 Hancom-GW cleanup 已完成，目前 clean

### 产出物
- `tasks/verification-report-e-m6-1.md`（本次判定）
- `tasks/manual-e2e-e-m6-1.md`（5 个场景）
- `HANDOFF.md` 全面更新

### 最终判定
🟢 GREEN — 可 commit/PR。等待用户浏览器确认 + push + 创建 PR。
