# M6 删除分析（贝索斯）— 2026-04-21

**负责人**：贝索斯（QA / Musk Step 2）
**base**：main @ `ad8c0fd`（PR #58 M5 merge）
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m6`
**参考**：`CHECKPOINT.md`（scope locked）, `progress.txt`（gotchas）, `HANDOFF.md`
**判定**：**注意（CAUTION）** — agent_tools.config drop 必须**同时**清理三部分才能无回归

Legend：`[D]`=删除 / `[S]`=简化（部分编辑）/ `[K]`=保留

---

## 确定删除 target（file:line 单位）

### 1. Model layer

- `[D] backend/app/models/tool.py:35-58` — 删除整个 `MCPServer` class
- `[D] backend/app/models/tool.py:72` — `Tool.mcp_server_id` FK
- `[D] backend/app/models/tool.py:82` — `Tool.auth_config` 列
- `[D] backend/app/models/tool.py:83-85` — `Tool.credential_id` FK
- `[D] backend/app/models/tool.py:92` — `Tool.mcp_server` relationship
- `[D] backend/app/models/tool.py:96-98` — `Tool.credential` relationship
- `[D] backend/app/models/tool.py:17-32` — `AgentToolLink.config` 字段（line 30）— **确认 drop agent_tools.config**
- `[S] backend/app/models/__init__.py:12, 22` — 删除 `MCPServer` export
- `[K] backend/app/models/tool.py:61-98` — `Tool` class 本身和 `connection_id`/`connection` relationship 保留

### 2. Service layer

#### 2-1. chat_service.py

- `[D] backend/app/services/chat_service.py:18` — 删除 import `MCPServer`
- `[D] backend/app/services/chat_service.py:26-27` — 删除 `resolve_server_auth` import
- `[D] backend/app/services/chat_service.py:195-199` — 删除 `selectinload(Tool.credential)` + `Tool.mcp_server ... MCPServer.credential` block（legacy eager-load）
- `[S] backend/app/services/chat_service.py:195-199` — `selectinload(Tool.credential)` 是否**保留或一并删除**？→ M6 后不存在 `tool.credential_id` 列，因此必须**一起删除**。保留会导致 AttributeError。
- `[D] backend/app/services/chat_service.py:313-340` — 删除 `_resolve_custom_auth` 内整个 bridge override。改为 connection_id 为空时 raise error（删除 legacy 路径）。
- `[S] backend/app/services/chat_service.py:301-340` — M6 后简化 `_resolve_custom_auth`：`connection_id IS NULL` → `ToolConfigError`，有则 Gate A → Gate B 直连。
- `[D] backend/app/services/chat_service.py:343-356` — 删除整个 `_resolve_legacy_tool_auth` 函数。PREBUILT 的 `provider_name IS NULL` case、BUILTIN legacy case 一并删除。
- `[S] backend/app/services/chat_service.py:427-443` — 简化 PREBUILT/CUSTOM 分支：删除 `provider_name IS NULL` 分支（PREBUILT 强制 provider_name），CUSTOM 只保留 connection 路径。
- `[D] backend/app/services/chat_service.py:417-424` — 删除 MCP `elif tool.mcp_server is not None` legacy fallback block。强制 `tool.connection_id IS NOT NULL`。
- `[S] backend/app/services/chat_service.py:376-426` — MCP 分支：只保留 connection 路径，在 else 中 raise `ToolConfigError`。删除 `cred_auth = {}` 恢复路径。
- `[D] backend/app/services/chat_service.py:441-443` — 删除 `else`（BUILTIN fallback 路径中的 `_resolve_legacy_tool_auth` 调用）。BUILTIN 无 auth 工作，因此改为 `cred_auth = {}`。
- `[D] backend/app/services/chat_service.py:445` — **★ `merged_auth = {**cred_auth, **(link.config or {})}` → 简化为 `merged_auth = cred_auth` ★**（确认 drop agent_tools.config 时）
- `[S] backend/app/services/chat_service.py:40-49` — 从 `__all__` 删除 `_resolve_legacy_tool_auth`

#### 2-2. credential_service.py

- `[D] backend/app/services/credential_service.py:11` — 删除 import `MCPServer`
- `[D] backend/app/services/credential_service.py:110-119` — 删除整个 `resolve_server_auth()` 函数
- `[D] backend/app/services/credential_service.py:135-140` — 删除 `get_usage_count` 的 `mcp_count_result` block
- `[S] backend/app/services/credential_service.py:122-142` — 从 `get_usage_count` 返回中删除 `mcp_server_count` key 或固定为 0。**需要确认 caller**（grep `routers/credentials.py`）。

#### 2-3. tool_service.py

- `[D] backend/app/services/tool_service.py:10` — 删除 import `MCPServer`
- `[D] backend/app/services/tool_service.py:11` — 删除 `MCPServerCreate` import
- `[D] backend/app/services/tool_service.py:89-130` — 删除整个 `register_mcp_server()` 函数
- `[D] backend/app/services/tool_service.py:133-140` — 删除 `get_mcp_servers()`
- `[D] backend/app/services/tool_service.py:143-189` — 删除 `list_mcp_server_items()`
- `[D] backend/app/services/tool_service.py:207-238` — 删除 `update_mcp_server()`
- `[D] backend/app/services/tool_service.py:241-260` — 删除 `delete_mcp_server()`
- `[S] backend/app/services/tool_service.py:192-204` — `_apply_credential_update` signature 从 `Tool | MCPServer` → 仅 `Tool`。**M6 后连 `tool.credential_id` 也不存在，因此可评估删除函数本身**。
- `[S] backend/app/services/tool_service.py:263-294` — 从 `update_tool_auth_config` 删除 `auth_config` / `credential_id` 字段处理。→ M6 后该 endpoint 本身无意义 → **建议在 router 层决定删除（Pichai/Jensen 最终确定）**。

#### 2-4. agent_service.py — **agent_tools.config drop cascade**

- `[D] backend/app/services/agent_service.py:45-50` — 从 `_build_tool_links` 删除 `config_map` 参数，`AgentToolLink(tool_id=tid, config=...)` → `AgentToolLink(tool_id=tid)`
- `[D] backend/app/services/agent_service.py:74-77` — 删除 `config_map` 构建 block
- `[S] backend/app/services/agent_service.py:97-98` — `_build_tool_links(tool_ids_to_link, config_map)` → `_build_tool_links(tool_ids_to_link)`
- `[D] backend/app/services/agent_service.py:124-137` — 删除整个 `tool_configs` 处理 `if/elif` block。只保留并简化 `if data.tool_ids is not None:`。

### 3. Router/Schema

#### 3-1. routers/tools.py

- `[D] backend/app/routers/tools.py:49-56` — `POST /api/tools/mcp-server`
- `[D] backend/app/routers/tools.py:58-63` — `GET /api/tools/mcp-servers`
- `[D] backend/app/routers/tools.py:66-77` — `PATCH /api/tools/mcp-servers/{server_id}`
- `[D] backend/app/routers/tools.py:80-88` — `DELETE /api/tools/mcp-servers/{server_id}`
- `[D] backend/app/routers/tools.py:91-112` — `POST /api/tools/mcp-server/{server_id}/test`（包含 `resolve_server_auth` 调用）
- `[S] backend/app/routers/tools.py:10-18` — 从 imports 删除 `MCPServerCreate, MCPServerListItem, MCPServerResponse, MCPServerUpdate`
- `[S] backend/app/routers/tools.py:9` — 删除 `mcp_server_not_found` import
- `[D/S] backend/app/routers/tools.py:115-128` — `PATCH /api/tools/{tool_id}/auth-config` — **若无调用处则删除**。Frontend 中 `updateAuthConfig` 已确认为 M6 dead API（参见下方 §4）。建议 router 也一起删除 — Jensen 最终确定。

#### 3-2. routers/agents.py — agent_tools.config drop cascade

- `[S] backend/app/routers/agents.py:40` — `ToolBrief(id=..., name=..., agent_config=link.config)` → `ToolBrief(id=..., name=...)`
- `[S] backend/app/schemas/agent.py:12-16` — 删除整个 `ToolConfigEntry` class
- `[S] backend/app/schemas/agent.py:41` — 删除 `AgentCreate.tool_configs` 字段
- `[S] backend/app/schemas/agent.py:54` — 删除 `AgentUpdate.tool_configs` 字段
- `[S] backend/app/schemas/agent.py:68-73` — 删除 `ToolBrief.agent_config` 字段

#### 3-3. schemas/tool.py

- `[D] backend/app/schemas/tool.py:57-62` — `MCPServerCreate`
- `[D] backend/app/schemas/tool.py:102-112` — `MCPServerResponse`
- `[D] backend/app/schemas/tool.py:123-134` — `MCPServerListItem`
- `[D] backend/app/schemas/tool.py:137-142` — `MCPServerUpdate`
- `[D] backend/app/schemas/tool.py:115-120` — `CredentialBrief` — 只被 `MCPServerListItem` 使用。若还有其他使用处则保留。**需要确认**。
- `[D] backend/app/schemas/tool.py:50-54` — `ToolAuthConfigUpdate`（若删除 PATCH auth-config router）
- `[D] backend/app/schemas/tool.py:11-26` — `AUTH_CONFIG_MASK` 常量 + `_reject_mask_sentinel`
- `[D] backend/app/schemas/tool.py:70` — `ToolResponse.mcp_server_id`
- `[D] backend/app/schemas/tool.py:71` — `ToolResponse.credential_id`
- `[D] backend/app/schemas/tool.py:79` — `ToolResponse.auth_config`
- `[D] backend/app/schemas/tool.py:86-99` — `ToolResponse._mask_auth_config` field_serializer
- `[D] backend/app/schemas/tool.py:45` — `ToolCustomCreate.auth_config`（可选）
- `[S] backend/app/schemas/tool.py:46` — 是否保留 `ToolCustomCreate.credential_id`？→ M6 后 tool.credential_id 列也 drop。应整理 POST /api/tools/custom，让其接收 credential_id 后只用于 `connection_id` derivation。**这里注意 scope creep** — 此值作为 connection_id derivation，在 M4 已迁移为 connection（tool_service.py:57-66）。`credential_id` 字段接收后被忽略，写法有利于迁移。M6 可安全完全删除。
- `[D] backend/app/schemas/tool.py:46` — 建议 `ToolCustomCreate.credential_id` 也纳入 scope（可选）。

### 4. Frontend

#### 4-1. lib/api/tools.ts

- `[D] frontend/src/lib/api/tools.ts:15-24` — 删除 `registerMCPServer`, `testMCPConnection` 方法
- `[D] frontend/src/lib/api/tools.ts:25-36` — 删除 `updateAuthConfig` 方法（若删除 PATCH router）
- `[D] frontend/src/lib/api/tools.ts:38-45` — 删除 `listMCPServers`, `updateMCPServer`, `deleteMCPServer`
- `[S] frontend/src/lib/api/tools.ts:1-9` — 缩减 imports

#### 4-2. lib/hooks/use-tools.ts

- `[D] frontend/src/lib/hooks/use-tools.ts:39-43` — `useRegisterMCPServer`
- `[D] frontend/src/lib/hooks/use-tools.ts:52-60` — `useUpdateToolAuthConfig`（若删除 router）
- `[D] frontend/src/lib/hooks/use-tools.ts:71-80` — `useMCPServers`
- `[D] frontend/src/lib/hooks/use-tools.ts:82-105` — `useToolsByConnection` 的 MCP 路径 — 依赖 `t.mcp_server_id`（line 99）
- `[D] frontend/src/lib/hooks/use-tools.ts:113-128` — `useUpdateMCPServer`, `useDeleteMCPServer`

#### 4-3. lib/types/index.ts

- `[D] frontend/src/lib/types/index.ts:220` — `Tool.mcp_server_id`
- `[D] frontend/src/lib/types/index.ts:229` — `Tool.auth_config`
- `[D] frontend/src/lib/types/index.ts:231` — `Tool.credential_id`
- `[D] frontend/src/lib/types/index.ts:318-326` — `MCPServer` 类型
- `[D] frontend/src/lib/types/index.ts:334-344` — `MCPServerListItem`
- `[D] frontend/src/lib/types/index.ts:346-350` — `MCPServerUpdateRequest`
- `[D] frontend/src/lib/types/index.ts:364-370` — `MCPServerCreateRequest`
- `[S] frontend/src/lib/types/index.ts:352-362` — 删除 `ToolCustomCreateRequest.auth_config`（可选）

#### 4-4. 引用处 cascade（只**删除**因 type drop 导致 build error 的地方，禁止新逻辑）

- `[S] frontend/src/app/tools/page.tsx:20, 40, 98-111, 401, 477-500, 529, 634-644` — 删除 MCP section / `mcp_server_id` 使用处 / `auth_config` configured-state 推断 / `useMCPServers`。**此文件有超出 Zuckerberg S4 范围的风险 — 需要单独 cleanup。**
- `[S] frontend/src/components/tool/add-tool-dialog.tsx:21, 47` — 删除 `useRegisterMCPServer` 调用。MCP 注册 UI 本身在 M5 后 dead，因此建议删除。
- `[D] frontend/src/components/tool/mcp-server-rename-dialog.tsx` — 删除整个文件
- `[D] frontend/src/components/tool/mcp-server-group-card.tsx` — 删除整个文件
- `[S] frontend/src/components/connection/connection-binding-dialog.tsx:35, 80, 467-506-521` — 删除 `useUpdateMCPServer` 使用。MCP binding 不应只更新 credential_id，而应经由 connection 本身。**M5.5/M6.1 Option D 区域 — M6 scope 中不能简单删除。需要 Zuckerberg S4 与 Pichai/Satya 达成一致。**

> **⚠ Zuckerberg S4 scope creep 警告**：`app/tools/page.tsx`, `add-tool-dialog.tsx`, `connection-binding-dialog.tsx`, `mcp-server-*-dialog` 可能超出 CHECKPOINT.md S4 "thin cleanup" 范围。建议向 Satya 申请批准拆分到 M6.1。

### 5. 测试（保留/删除决定）

#### 5-1. 整体删除（legacy 专用）

- `[D] backend/tests/test_agent_tool_config.py` — **整个文件（142 lines, 4 tests）**。一旦 drop `tool_configs` / `agent_config` 字段，所有 test 都会 broken。**但前提是确认 drop agent_tools.config。**
- `[D] backend/tests/test_tools.py:509-577` — `test_build_tools_config_mcp_uses_server_credential`（legacy server_credential 路径）。
- `[D] backend/tests/test_tools.py:267-404` — `_seed_mcp_server_with_tools` 以及 `test_list_mcp_servers_returns_tool_count` / `test_update_mcp_server_*` / `test_delete_mcp_server_cascades_tools`（整个 MCP server CRUD 部分）
- `[D] backend/tests/test_tools.py:60-74` — `test_register_mcp_server`
- `[D] backend/tests/test_tools.py:93-146` — `test_patch_tool_auth_config_preserves_unset_fields`（删除 auth-config PATCH 路由时）
- `[D] backend/tests/test_tools.py:148-175` — `test_patch_mcp_tool_rejects_other_user`
- `[D] backend/tests/test_tools.py:177-221` — `test_tool_response_masks_auth_config_string_values`
- `[K] backend/tests/test_tools.py:24-59` — 保留 `test_create_custom_tool` 等 CUSTOM 相关内容
- `[D] backend/tests/test_tools_router_extended.py:62-85` — `test_test_mcp_connection_success`
- `[D] backend/tests/test_tools_router_extended.py:86-99` — `test_test_mcp_connection_server_not_found`
- `[D] backend/tests/test_tools_router_extended.py:100-150` — `test_update_auth_config_*` 3 类（删除路由时）
- `[D] backend/tests/test_tools_router_extended.py:152-175` — `test_mcp_server_register_via_api`
- `[K] backend/tests/test_tools_router_extended.py:177-430` — 保留 provider_name / connection 相关内容
- `[D] backend/tests/test_conversations_router.py:40-58, 270-282` — 删除 `AgentToolLink(... config={"extra": "cfg"})` 以及 merged auth assertion。**测试本身保留，但简化 fixture**：在不使用 `auth_config`/`link.config` 的情况下改写为 PREBUILT connection 路径，或在删除整个 agent_tools.config 场景中二选一。**建议：简化 fixture**。

#### 5-2. 部分删除（保留 connection path）

**`test_connection_mcp_resolve.py` (850 lines)** — 按函数列出的保留/删除表：

| line | 函数 | 决定 | 依据 |
|---|---|---|---|
| 216 | `test_build_tools_config_uses_connection_extra_config` | `[K]` | connection path |
| 382 | `test_build_tools_config_legacy_mcp_server_fallback` | `[D]` | legacy fallback 路径 |
| 427 | `test_build_tools_config_legacy_fallback_inline_auth_config` | `[D]` | legacy `auth_config` |
| 468 | `test_connection_takes_precedence_over_mcp_server` | `[D]` | 虽是 precedence 测试，但删除 legacy 一侧后即失去意义 |
| 522 | `test_template_regex_contract` | `[K]` | env_vars 模板 |
| 656 | `test_resolve_env_vars_rejects_non_dict_shape` | `[K]` | |
| 671 | `test_tool_config_error_is_app_error` | `[K]` | |
| 690 | `test_build_tools_config_forwards_connection_headers` | `[K]` | connection path |
| 769 | `test_migrated_extra_config_passes_strict_schema` | `[K]` | m9 contract |
| 817 | `test_response_tolerates_legacy_non_string_env_var_values` | `[K]` | |
| 857 | `test_response_redacts_env_var_secret_values` | `[K]` | |
| 889 | `test_extra_config_rejects_migration_sentinel_leak` | `[K]` | |
| 910 | `test_m9_generates_env_vars_from_credential_field_keys` | `[K]` | m9 contract — 即使声明 downgrade 不可用，m9 contract 本身仍保留 |
| 938-1029 | `test_mcp_credential_*` 4 类 | `[K]` | connection path |
| 1125 | `test_response_validator_does_not_mutate_input_dict` | `[K]` | |
| 1169 | `test_response_redacts_header_values` | `[K]` | |
| 1217 | `test_distinct_transport_headers_create_separate_mcp_groups` | `[K]` | |
| 1281 | `test_executor_server_key_is_deterministic_across_calls` | `[K]` | |
| 1318 | `test_m9_skips_unrecoverable_credential_backed_server` | `[S]` | 保留 m9 helper 测试，但 DB 创建 fixture 中引用 `MCPServer` → 存在文件加载失败风险。**需要重写 fixture** — 隔离为仅直接调用 m9 模块 helper 的方式。 |

**`test_connection_custom_resolve.py` (850 lines)** — 按函数：

| line | 函数 | 决定 | 依据 |
|---|---|---|---|
| 224 | `test_custom_resolves_current_user_connection_not_other_user` | `[K]` | |
| 288 | `test_custom_with_active_connection_resolves_credential` | `[K]` | |
| 327 | `test_custom_disabled_connection_fails_closed` | `[K]` | |
| 360 | `test_custom_connection_with_null_credential_fails_closed` | `[K]` | |
| 399 | `test_custom_bridge_override_when_tool_credential_rotated` | `[D]` | **删除 bridge override** |
| 448 | `test_custom_bridge_override_blocked_by_disabled_connection` | `[D]` | bridge override |
| 499 | `test_custom_resolves_raises_when_connection_missing_despite_fk` | `[S]` | connection_id NULL 路径 → 修改 ToolConfigError 预期值 |
| 528 | `test_custom_legacy_credential_path_preserved` | `[D]` | legacy path |
| 565 | `test_custom_legacy_inline_auth_config_returned_as_is` | `[D]` | legacy path |
| 601 | `test_custom_rejects_connection_credential_user_mismatch` | `[K]` | |
| 650 | `test_m11_revision_ids_and_marker_are_stable` | `[K]` | m11 contract |
| 661 | `test_m11_migrate_custom_credentials_source_contract` | `[K]` | m11 contract |
| 719 | `test_m11_preserves_tool_credential_id_for_legacy_fallback` | `[S]` | 以 m11 当时存在 `tool.credential_id` 为前提 — m12 之后 m11 helper 本身仍能运行，但从集成验证语境看**需要修改**。交给詹森。 |
| 747 | `test_m11_downgrade_only_deletes_seed_marker_rows` | `[K]` | |
| 794 | `test_m11_upgrade_dedup_preexisting_custom_duplicates` | `[K]` | |

**`test_connection_prebuilt_resolve.py`** — 仅删除 provider_name NULL fallback 场景（line 552: `auth_config={"api_key": "legacy-inline-key"}`）。其余 `[K]`。

**`test_executor.py`** — 基于 `tools_config` 输入 (fixture)。需要重新确认包含 MCP legacy fallback 的 case。詹森在 S3 实现中确定 `build_tools_config` 输出签名后做第2轮整理。

#### 5-3. agent_tools.config 相关测试

- `[D] backend/tests/test_agent_service_extended.py:89-110` — `test_create_agent_with_tool_configs`
- `[D] backend/tests/test_agent_service_extended.py:180-210` — `test_update_agent_tool_configs_only`
- `[S] backend/tests/test_assistant_read_tools.py:53, 326` — `AgentToolLink(... config=None)` → `AgentToolLink(... )`（随 model change 自动 fail）
- `[S] backend/tests/test_assistant_write_tools.py:53` — 同上
- `[S] backend/tests/test_chat_service.py:227` — 同上
- `[S] backend/tests/test_connection_mcp_resolve.py:119, 616, 740` — 同上
- `[S] backend/tests/test_connection_custom_resolve.py:213, test_connection_prebuilt_resolve.py:198` — 同上
- `[S] backend/tests/test_trigger_executor.py:55` — 删除 `config={"agent_override": "ov"}`。agent_override 验证块也一并删除。
- `[S] backend/tests/test_tools.py:567` — OK（已经在没有 `config` 的情况下添加）

#### 5-4. Assistant 内部工具（★ drop agent_tools.config 时必须修改）

- `[S] backend/app/agent_runtime/assistant/tools/write_tools.py:312-330` — 删除整个 `update_tool_config` 工具定义，或改为 no-op。**必须**。保留原样会导致 `link.config` AttributeError。
- `[S] backend/app/agent_runtime/assistant/tools/read_tools.py:60-103` — 从 `get_agent_config` 返回 dict 的 `tools_info` 中删除 `config` 键。
- `[S] backend/app/agent_runtime/assistant/tools/read_tools.py:124-146` — 删除 `get_tool_config` 工具定义本身，或做简化（删除 config 返回后几乎没有意义 → **建议删除**）。
- `[S] backend/app/schemas/assistant.py:57-62` — 删除 `AgentToolInfo.agent_config` 字段（若存在）。

> **如果漏掉 §5-4，AI agent 创建对话中的工具会报错。詹森 S3 必须包含。**

---

## agent_tools.config 安全性判断

### 调查结果

**Write 路径**：
1. `POST /api/agents`（routers/agents.py → agent_service.create_agent:60-106）— 将 API body 的 `tool_configs: [{tool_id, config}]` 保存到 `AgentToolLink.config`。
2. `PUT /api/agents/{id}`（agent_service.update_agent:109-144）— 输入 `tool_configs` 时更新 config。
3. **Assistant 内部 `update_tool_config` 工具**（write_tools.py:327）— 在 AI agent 创建过程中，以对话方式覆盖 link.config。

**Read 路径**：
1. `GET /api/agents/{id}` → `_agent_to_response` (routers/agents.py:40) → `ToolBrief.agent_config`
2. `chat_service.build_tools_config:445` → `merged_auth = {**cred_auth, **(link.config or {})}` — **实际 merge 到 runtime auth 中**
3. `read_tools.py:70, 142` — assistant `get_agent_config` / `get_tool_config` JSON 响应

**前端使用情况**：
- `agent_config` / `tool_configs` / `toolConfigs` / `agentConfig` grep: **No matches found** in `frontend/src/`
- **前端 UI 从不发送/展示该字段**

**当前 DB 中可能已存储值的情况**：
- **LOW to MEDIUM**.
- PoC 环境（mock user）+ 没有 UI write 路径 → 大多数实际设置中为 NULL。
- 但过去 TASKS 曾以 "per-agent tool config (例如 Google Chat webhook_url)" 为目的，存在直接调用 API / assistant write tool / pytest fixture → 生产 DB 中可能存在 non-NULL row。
- 建议 pre-check 查询：`SELECT COUNT(*) FROM agent_tools WHERE config IS NOT NULL`

### 判断

**[注意 — drop agent_tools.config 时必须原子性地同时清理 3 个部分]**

依据：
1. Merge 逻辑（`chat_service.py:445`）仍是 live — 保存的值会实际反映到 runtime auth 中（`test_conversations_router.py:280` 证明）。
2. 但**前端未使用 write 路径** → 无 UI 回归。
3. Assistant 内部 `update_tool_config` 工具是 live write — **如果不一起删除，会在 AI agent 创建对话中发生 AttributeError**。
4. Pydantic schema（`ToolConfigEntry`, `AgentUpdate.tool_configs`, `ToolBrief.agent_config`）属于 API 外部 contract 变更 — 会影响 API 客户端。

**M6 中是否 drop**：**YES — 但下面 3 个文件必须包含在**同一个 PR**中**：
1. `backend/app/schemas/agent.py`（删除 ToolConfigEntry / tool_configs / agent_config 字段）
2. `backend/app/services/agent_service.py`（删除 tool_configs 处理逻辑）
3. `backend/app/agent_runtime/assistant/tools/write_tools.py`, `read_tools.py`（删除 update_tool_config, get_tool_config, get_agent_config.tools[].config）

建议备份 pre-migration 数据（m12 upgrade 前）：
```sql
-- 备份：若存在 non-null config，则向用户展示并引导重新设置
SELECT agent_id, tool_id, config FROM agent_tools WHERE config IS NOT NULL;
```

---

## scope creep 阻断检查表

- [x] 与选项 D（PATCH /api/tools/{id} connection_id）相关的变更 **0 项** — 删除 PATCH `/auth-config` endpoint 只是清理现有 dead API，不属于选项 D。选项 D 新增 `connection_id` 参数属于 M6.1。
- [x] 与 `ConnectionBindingDialog` / `triggerContext` 相关的逻辑变更 **0 项** — `useUpdateMCPServer` 使用处仅做清理 dead API 所必需的最小删除，binding dialog 重构属于 M6.1。
- [x] 与 M5.5（`agent_tools.connection_id` override）相关的变更 **0 项**
- [x] 后端新功能 **0 项**（仅新增 m12 migration）
- [x] 前端新功能 **0 项**

**⚠ scope 边界模糊**：
- 移除 `frontend/src/app/tools/page.tsx` 的 MCP 部分可能超出 CHECKPOINT.md §S4 "thin cleanup" 的范围。**需由扎克伯格 S4 单独判断** — 是只做类型/API 删除导致 build error 的最小修改，还是 drop 整个 MCP 部分。
- 是否删除 `PATCH /api/tools/{tool_id}/auth-config` 路由 — 技术上是 dead，但删除属于 API contract 变更。保守判断：可以**保留 + internal no-op 处理**，但建议**删除**（M6 目标是 "彻底删除 legacy"）。

---

## 给詹森的指示（S3 input）

### 1. m12 migration 编写顺序（upgrade）

皮查伊会在 S2 确定详细规格，但建议顺序如下：
```
1. PRE-CHECK (warning only):
   SELECT COUNT(*) FROM tools WHERE credential_id IS NOT NULL AND connection_id IS NULL
   SELECT COUNT(*) FROM tools WHERE mcp_server_id IS NOT NULL AND connection_id IS NULL
   SELECT COUNT(*) FROM agent_tools WHERE config IS NOT NULL
2. FK drop:
   ALTER TABLE tools DROP CONSTRAINT fk_tools_credential_id ...
   ALTER TABLE tools DROP CONSTRAINT fk_tools_mcp_server_id ...
3. Column drop:
   ALTER TABLE tools DROP COLUMN credential_id, auth_config, mcp_server_id
   ALTER TABLE agent_tools DROP COLUMN config
4. Table drop:
   DROP TABLE mcp_servers   -- 因 credential FK ondelete=SET NULL，可直接 drop
```
downgrade：仅恢复结构，无法恢复数据（progress.txt 已注明）。

### 2. `_resolve_legacy_tool_auth` 处理方式

**完全删除**。所有调用处：
- PREBUILT `provider_name IS NULL` 分支 (chat_service.py:433) — **删除分支本身**，PREBUILT 强制 provider_name。provider_name NULL row 应已在 m10 中完成 backfill (progress.txt: "m10 backfill 失败 row" = 理论上 0)。
- CUSTOM `connection_id IS NULL` 分支（chat_service.py:319）— 改为 **raise ToolConfigError**。M4/M5 中所有 CUSTOM tool 都已通过 connection 完成迁移（m11 migration）。
- BUILTIN else（chat_service.py:441-443）— BUILTIN 不需要 auth → 改为 `cred_auth = {}`。还需搜索是否存在使用 credential 的 legacy BUILTIN — 若没有则完全删除。

**PRE-CHECK 未满足时让 migration 失败**：若存在 `credential_id IS NOT NULL AND connection_id IS NULL` row，则 abort upgrade 并要求手动迁移。已在 CHECKPOINT.md §风险 #3 中说明。

### 3. 测试编辑指南

核心 3 点：

**(a) 先做 Import/fixture sweep**
- 从所有测试文件中的 `from app.models.tool import ..., MCPServer, ...` 移除 `MCPServer`，并确认 grep 为 0
- 将 `AgentToolLink(... config=...)` → `AgentToolLink(...)` 批量删除。ripgrep 轮次：
  ```
  rg "AgentToolLink\([^)]*config=" backend/tests/
  ```
- 全部删除 `Tool(... auth_config=...)` / `Tool(... credential_id=...)` / `Tool(... mcp_server_id=...)`。PREBUILT tool fixture 改写为经由 connection。

**(b) connection path 测试**必须保留****
- `test_connection_mcp_resolve.py` / `test_connection_custom_resolve.py` / `test_connection_prebuilt_resolve.py` 的 connection-path `[K]` 测试在 m12 之后**必须通过才能视为 M6 ready**。不要删除。
- m9/m10/m11 migration helper 测试也保留（即使声明 downgrade 不可用，helper contract 仍然有效）。

**(c) 严格遵守 scope**
- 只有在确定 drop agent_tools.config 时，才删除整个 `test_agent_tool_config.py` 文件。如果用户把 scope 改为 "保留 agent_tools.config"，则该文件也必须保留。
- `test_tools.py`, `test_tools_router_extended.py` 中只删除标记为 `[D]` 的 MCP 专用测试。CUSTOM / provider_name / connection_id 相关测试用 grep 再次确认后保留。

### 追加建议

- **是否删除 `PATCH /api/tools/{tool_id}/auth-config` 路由，要提前与萨提亚达成一致**。若留在 M6 scope 外，虽是 dead code 但安全。建议删除，但最终决定由萨提亚做出。
- **`ToolCustomCreate.auth_config`/`credential_id` 字段**的删除范围 — 必须 grep 前端是否仍在发送这些字段。`frontend/src/lib/types/index.ts:359` 的引用表明可能会发送（创建 CUSTOM 时使用 legacy auth 路径）。确认后再决定。
- **验证 cascade 路径**：m12 upgrade 后运行完整 `uv run pytest`，`AttributeError: 'Tool' object has no attribute 'auth_config'` 一类错误必须为 0。grep：
  ```
  rg "\.auth_config|\.credential_id|\.mcp_server(_id)?|\.mcp_server\b" backend/app/
  ```
  这一步在 S3 结束时**必须**执行。

---

## 验证检查

- [x] 已完备文件:行级别的删除列表
- [x] agent_tools.config safety 判断 — 已明确要求同时清理 3 个部分
- [x] 测试按函数列出的保留/删除表
- [x] scope creep 阻断检查表
- [x] 詹森 S3 指南的 3 个核心点
