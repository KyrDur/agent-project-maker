# 删除分析报告 — Backlog E M2（MCP → Connection 迁移）

**分支**：`feature/connection-mcp-migration`
**作者**：贝索斯（QA）
**编写日期**：2026-04-18
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**：`docs/exec-plans/active/backlog-e-connection-refactor.md`（M2 section）
**上一份报告**：`tasks/deletion-analysis-e-m1.md`
**Scope 定义**：M2 是将 MCP 工具的 credential/server 设置解析路径**切换为经由 connection**的 milestone。新增 `tool.connection_id` + 重写 chat_service MCP 分支 + runtime 解析 env_vars 模板。drop `mcp_servers` / `tool.mcp_server_id` / `tool.auth_*` 列由 **M6 负责**。M2 是迁移 + legacy fallback 共存阶段，因此几乎没有可立即删除项才是正常的。

---

## 分析原则

以 ADR-008 §迁移策略 + `progress.txt` 文件边界为依据，只分类 M2 PR 关闭时可安全删除/简化的项目。M2 会触碰 hot path（`chat_service.build_tools_config`），是**高风险 milestone**，因此绝对禁止 drive-by 删除。优先保证 legacy fallback（`connection_id IS NULL AND mcp_server_id IS NOT NULL`）。

---

## 事前事实确认

探索中确认了以下内容（Pichai S2 开始前基线）：

- **`backend/app/models/tool.py:70-72, 90-92`** — `Tool.connection_id` 列和 `connection` relationship **已经提前反映到 model 中**。也就是说 S2（Pichai）的 model 变更部分已 merge。Pichai 只剩编写 Alembic `m9` + 整理 `mcp_server_id` deprecate 注释（实际新增列 migration + 迁移 SQL）。
- **`tool.py:68`** — `mcp_server_id` 列已有 `# deprecated: M6 中计划删除。在迁移期间保留用于 legacy fallback。` 注释。无需再添加标记。

这一事实应由 Satya 告知 S2 负责人（Pichai）— 防止遗漏工作。

---

## 可立即删除

**0 项。**

M2 结束时 `mcp_servers` 表、`Tool.mcp_server_id`、`MCPServer.auth_type/auth_config`、Frontend `mcp-server-auth-dialog` 都必须继续存在（legacy fallback / 后续 milestone 依赖）。本 PR 中不存在可安全删除的代码。

---

## 简化建议（在 M2 PR 中处理）

### 1. **`backend/app/services/chat_service.py:174-187` — MCP/non-MCP 分支整合**（Jensen S3 指南）

当前结构：
```python
if tool.type == ToolType.MCP and tool.mcp_server:
    if tool.mcp_server.credential_id and tool.mcp_server.credential:
        cred_auth = resolve_credential_data(tool.mcp_server.credential)
    elif tool.mcp_server.auth_config:
        cred_auth = tool.mcp_server.auth_config
    else:
        cred_auth = {}
else:
    if tool.credential_id and tool.credential:
        cred_auth = resolve_credential_data(tool.credential)
    elif tool.auth_config:
        cred_auth = tool.auth_config
    else:
        cred_auth = {}
```

- 建议：提取为单一函数，采用新优先级 `connection → mcp_server(legacy fallback) → tool.credential → tool.auth_config → {}`。只有 MCP 工具优先 connection，其他保持现状。同一 4-way fallback tree 在两个分支中重复，本质上不是复杂性，而是偶然重复。
- 依据：M2 后 MCP 分支中再加入一层（connection）就会变成 4 层 if。提取 helper → M6 删除 legacy fallback 时只需修改一个函数。
- 措施：Jensen 在 S3 中拆出 `_resolve_tool_auth(tool)` 或 `_resolve_mcp_auth(tool)` helper。**禁止引入新抽象** — 只在现有 chat_service module 内新增 1 个 module-private function。

### 2. **`backend/app/services/chat_service.py:200-202` — `mcp_server_url` 输出路径**（Jensen S3 指南）

当前：
```python
if tool.type == ToolType.MCP and tool.mcp_server:
    config_entry["mcp_server_url"] = tool.mcp_server.url
    config_entry["mcp_tool_name"] = tool.name
```

- 建议：M2 后经由 `tool.connection` 时从 `connection.extra_config["url"]` 读取，只有 fallback 时才用 `tool.mcp_server.url`。key 名保持 `mcp_server_url` 不变（兼容 downstream）。
- 依据：ADR-008 §2 — MCP url 的 SOT 是 `extra_config.url`。迁移后 `mcp_server.url` 属于 legacy。
- 措施：Jensen S3 中按优先级分支。

### 3. **`backend/app/services/credential_service.py:110-119` — 扩展 `resolve_server_auth` 签名**（Jensen S3 指南，但 credential_service 文件本身是贝索斯/Jensen 都禁止修改的区域）

- 当前：`resolve_server_auth(server: MCPServer) -> dict | None` — 只接收 MCPServer。
- M2 后需要：经由 connection 解析。MCPServer fallback 原样保留。
- 建议：**此函数禁止修改**。改为在 chat_service 或 mcp_client 侧拆分新的 `_resolve_connection_auth(connection: Connection)` helper，由调用者适当选择两个函数。理由是（a）credential_service.py 按 progress.txt 文件边界不在 M2 范围，（b）修改签名会动摇 Backlog C 已稳定的 regression test。
- 依据：与贝索斯 M1 报告 #5 结论相同 — `resolve_server_auth` 是 M6 cleanup 项。
- 措施：Jensen 在 S3 中创建 `_resolve_connection_auth`，放在新位置（`agent_runtime/mcp_client.py` 或 `chat_service.py` module-private）并 import。不要动 credential_service.py 签名。

### 4. **`backend/app/agent_runtime/mcp_client.py:12-19` — 扩展 `auth_config` 输入格式**（Jensen S3 指南）

当前 `test_mcp_connection(url, auth_config)` 假设 `auth_config = {api_key, header_name}` 格式。与 ADR-008 §2 的 `extra_config = {url, auth_type, headers?, env_vars?, transport?, timeout?}` semantic 不同。

- 建议：签名**保持不变**（外部调用者 regression 0）。禁止在函数内部新增判断 `auth_config` 是新 `extra_config` 形态还是 legacy 形态的分支。改为在调用侧（tools_router, 新 connection 注册路径）事先转换 → mcp_client 保持 dumb httpx caller 角色。
- 依据：dual-shape 输入函数会使测试 case 成倍增加（安全/回归两边）。single-shape + 将转换责任委托给调用者更简单。
- 措施：Jensen 在 S3 中于调用前 inline 处理 1 行 connection→legacy auth_config 转换。不要创建单独 adapter class。

### 5. **测试隔离 policy — 新增 1 个文件，现有回归只保持行为**（贝索斯本人指南，S4）

- 建议：新建 1 个 `tests/test_connection_mcp_resolve.py`，容纳全部 5 个 scenario。`tests/test_mcp_connection.py` 与 `tests/test_tools_router_extended.py` **只做不改变期望值（semantic）的更新** — 仅限 connection 列新设导致的 fixture 添加/migration head 变更等 mechanical change。
- 依据：在修改 chat_service hot path 的 PR 中，如果现有测试 semantic 发生变化，本身就是 regression 信号（与 M1 报告 #4 同一原则）。要验证 Legacy fallback 路径未断，必须保留现有 regression semantic。
- 措施：贝索斯在 S4 中以 `test_mcp_connection.py` diff 尽可能 0 行为目标。如必须修改，向 Satya 报告原因。

---

## 暂缓（移交后续 milestone）

上一份 M1 报告的 8 项 + M2 分析中新识别的项目。**M2 PR 中绝对不要触碰。**

| # | 位置 | 当前角色 | 建议时点 | 原因 |
|---|------|-----------|-----------|------|
| 1 | `backend/app/models/tool.py:35-58` 整个 `MCPServer` 表 | MCP server metadata | **M6**（`m12_drop_legacy_columns`） | M3-M5 期间 legacy fallback 的真实标准。用户数据未完全迁移 row 的安全网。 |
| 2 | `backend/app/models/tool.py:69` `Tool.mcp_server_id` FK | MCP tool → MCPServer link | **M6** | M2 m9 只填充 `connection_id`，`mcp_server_id` 保持原样。M3-M5 期间二者共存。 |
| 3 | `backend/app/models/tool.py:78-82` `Tool.auth_type`, `Tool.auth_config`, `Tool.credential_id` | PREBUILT/CUSTOM 工具 inline auth | **M4-M6** | M4（`m11_migrate_custom_credentials`）中迁移到 connection，M6 drop。超出 M2 scope。 |
| 4 | `backend/app/models/tool.py:30` `AgentToolLink.config` JSON | per-agent 工具 override | **M6** | ADR-008 §3 — 由 `agent_tools.connection_id`（M3+）替代，M6 drop。 |
| 5 | `backend/app/services/credential_service.py:110-119` `resolve_server_auth` | MCPServer auth 解析 helper | **M6** | M2-M5 期间 legacy fallback 路径会调用。参见简化 #3。 |
| 6 | `backend/app/services/credential_service.py:135-140` `get_usage_count` 的 `mcp_count` | credential usage 汇总 | **M5/M6** | M5 中新增 `connection_count` 后 M6 drop。M2 中仍有意义。 |
| 7 | `frontend/src/components/tool/mcp-server-auth-dialog.tsx` | MCP server 认证编辑 UI | **M5**（Backlog F） | 整合吸收到 `ConnectionBindingDialog`。超出 M2 scope。 |
| 8 | `frontend/src/components/tool/add-tool-dialog.tsx` MCP tab 分支 | MCP tool 添加流程 | **M5**（Backlog F） | 重写为 connection 选择 UX。超出 M2 scope。 |
| 9 | `backend/app/agent_runtime/mcp_client.py:80-98` `list_mcp_tools` | MCP tool discovery | **M6** | 只接收 url 参数。M2 无需更改。 |
| 10 | 整个 `backend/tests/test_mcp_client.py` | mcp_client 单元测试 | **M5/M6** | 根据简化 #4 保留 mcp_client 签名 → regression test 原样不动。 |

---

## 安全/回归检查（M2 PR 中必须验证）

探索中发现的潜在风险。反映到贝索斯 S4 新测试中：

1. **env_vars 模板明文泄露风险**
   - `${credential.<field_name>}` 在未解析状态下不得泄露到外部（LLM 输入、log、API response）。反过来，解析后的明文如果再次持久化到 connection.extra_config，则违反 ADR §安全。
   - 验证：在 `test_connection_mcp_resolve.py` 中加入（a）ConnectionResponse 不包含 env_vars 明文，（b）runtime 解析后不重新写回 DB 的 scenario。
2. **legacy fallback 时 credential 暴露一致性**
   - 即使在 `connection_id IS NULL` 分支中，`MCPServer.auth_config` 明文也不得流到 response（与现有行为相同）。
   - 验证：确认现有 `test_mcp_connection.py` 回归是否覆盖。若没有，则新增 1 个 case。
3. **Migration 数据完整性**
   - `mcp_servers` row 数 = M2 后 `connections WHERE type='mcp'` row 数。tool.mcp_server_id 非空 row 数 = M2 后 tool.connection_id 已填充的 MCP tool row 数。
   - 验证：在新的 `test_connection_mcp_resolve.py` 中加入 row count assertion（Pichai m9 migration 验证）。

---

## 结论

| 分类 | 数量 | 备注 |
|------|------|------|
| **立即删除** | **0 项** | M2 是迁移 + legacy fallback 共存阶段。drop 在 M6。 |
| **简化建议** | **5 项** | 全部为 S3（Jensen）/S4（贝索斯）新工作指南。现有 module signature 变更 0。 |
| **暂缓（后续 milestone）** | **10 项** | M4 1 项，M5 4 项，M5/M6 1 项，M6 4 项。与 M1 报告 8 项一致 + 新增 2 个 MCP-specific 项（`mcp_client.list_mcp_tools`, `test_mcp_client.py`）。 |

**贝索斯判断**：M2 同时包含 hot path（`chat_service.build_tools_config`）重写 + 新数据 migration + 新 runtime 模板解析，是**高风险 milestone**。如果夹带代码删除·signature 变更，回归区域会成倍扩大。legacy fallback 是 M2 的**安全网**，保留到 M6 是 ADR §迁移策略的核心约定。

简化 5 项遵循拆分新 helper + 保持调用者责任原则，方向是在已经触碰 hot path 的 PR 中不增加额外表面积。尤其简化 #3 明确**不要触碰 `credential_service.py`** — 防止违反 progress.txt 文件边界。

**向 Satya 报告**：建议将事前确认事实（Tool.connection_id 已提前反映到 model）+ 简化 #3-#4（规避文件边界冲突）明确传达给 S2/S3 负责人。
