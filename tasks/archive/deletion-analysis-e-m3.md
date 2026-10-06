# 删除分析报告 — Backlog E M3（PREBUILT per-user Connection）

**分支**: `feature/prebuilt-per-user-connection`
**作者**：贝索斯（QA）
**编写日期**：2026-04-18
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**: `docs/exec-plans/active/backlog-e-connection-refactor.md` (§4 M3)
**上一份报告**：`tasks/deletion-analysis-e-m2.md`
**Scope 定义**：M3 是将 PREBUILT 工具的解析路径改为按 per-user 使用各自 credential 的 milestone。
核心产物 4 类：（a）`tools.provider_name` 列 + Alembic m10 + mock user env→credential→default connection 自动 seed，
（b）重写 `chat_service.build_tools_config` PREBUILT 分支 + `connection_service.get_default_connection` helper，
（c）引入 `ConnectionBindingDialog` 公共 shell + 重新接线现有 3 个 dialog（提前部分 M5），
（d）`/connections` PREBUILT tab。drop `tools.credential_id` / `tools.auth_config` 由 **M6 负责**。M3 只是把 PREBUILT 路径改为 "忽略 credential_id"，列本身仍保留，是迁移阶段。

---

## 摘要（立即删除 1 / 简化 6 / 暂缓 12）

M3 同时替换 PREBUILT hot path（`chat_service.build_tools_config` 非 MCP 分支）和 3 类 UI dialog，是**高风险 milestone**。legacy fallback（`provider_name IS NULL` + `credential_id` 路径）必须保留到 M6，因此 backend 立即删除为 0。仅 frontend 因 `ConnectionBindingDialog` 替换而可删除**唯一 1 个 util function** + **3 个 dialog 文件本身**，归入简化路径。

---

## 分析原则

以 ADR-008 §迁移策略 + M3 `progress.txt` 文件边界（Pichai/Jensen/Zuckerberg/贝索斯）为基准，只分类 M3 PR 关闭时可安全删除/简化的项目。M3 scope 外的删除建议全部作为**暂缓**处理 — 禁止 "顺手清理（drive-by）"。`naver_tools.py`/`google_tools.py` 的 `(auth_config or {}).get(...) or settings.*` 模式属于 ADR-008 §11 + 已商定 env fallback 保留 policy，因此**绝对不要触碰**。

---

## 事前事实确认

探索中确认了 M3 负责人需要知道的基线：

1. **`backend/app/models/tool.py` 当前没有 `provider_name` 列。** M2 中 `connection_id` 已提前反映（`tool.py:70-72`），但 `provider_name` 需要在 S2（Pichai）中完全新增。与 M2 不同，没有部分提前反映的情况 — 需要明确传达给 Pichai。
2. **`Tool.connection_id` 列已存在（M2 产物）**。但 PREBUILT 路径中**不使用** — 因为 PREBUILT tool 是 `user_id=NULL` 的共享 row，无法将 per-user binding 存在 `tool.connection_id` 中。按 ADR-008 §3，查询 `user_id + tool.provider_name + is_default=true` 才是 PREBUILT 的 SOT。提前共享这一事实，避免 S3（Jensen）的 query 设计混淆。
3. **M3 结束后 `tool.credential` 与 `tool.credential_id` 仍继续用于 CUSTOM 路径（M4 对象）**。M3 PR 中绝对禁止删除。仅 PREBUILT 切换为 "忽略"。
4. **当前没有 `connection_service.get_default_connection` helper。** 这是 S3（Jensen）需要新增的项目。与其给现有 `list_connections` 增加 `is_default=true` filter，更适合新增专用 helper（sync/async 由 Jensen 判断 — 根据 progress.txt，chat_service 是 sync，因此可在 selectinload 或单独 sync select 中选择）。
5. **`connection_service.py` 是 M1 产物，按文件边界 M3 中除新增 `get_default_connection` 外禁止修改**。这与 M2 报告简化 #3 原则相同。
6. **env fallback 已经在 tool builder 内部实现**（`naver_tools.py`, `google_tools.py` 的 `or settings.*` 模式）。因此 `chat_service` 的 PREBUILT 分支无需单独处理 env fallback — 传入 `cred_auth = {}` 后，tool builder 会自动使用 settings.*。如果 S3（Jensen）混淆这一点，在 chat_service 中加入 env 再查询逻辑，会造成 2 重 fallback 和代码重复。

如果 Satya 将这 6 项传达给 S2/S3 负责人，就能避免工作遗漏/重复。

---

## 可立即删除

### 1. **`frontend/src/components/tool/prebuilt-auth-dialog.tsx:27-34` — `detectProvider` helper 函数**

当前：
```typescript
function detectProvider(toolName: string): string {
  const lower = toolName.toLowerCase()
  if (lower.startsWith('naver')) return 'naver'
  if (lower.startsWith('google chat')) return 'google_chat'
  if (lower.startsWith('gmail') || lower.startsWith('calendar')) return 'google_workspace'
  if (lower.startsWith('google')) return 'google_search'
  return 'unknown'
}
```

- **依据**：M3 S2 中新设 `tools.provider_name` 列并在 backend tool response schema 中包含 `provider_name` 后，frontend 直接读取 `tool.provider_name`。这个通过 tool **name 字符串模式匹配**推断 provider 的函数将失去存在理由。"Gmail" / "Calendar" / "Google Chat" / "Naver" pattern 在四处分支，是 sample error（例如新增 PREBUILT name 与 pattern 不一致时返回 `unknown`）的根源。
- **影响范围**：只在 `prebuilt-auth-dialog.tsx` 内调用。S4 引入 `ConnectionBindingDialog` 时，这个 dialog 文件本身会重写为基于 `ConnectionBindingDialog` 的 adapter 或被删除，因此该函数也会自然消失。
- **条件**：必须先完成 S2（Pichai），即 `tool.provider_name` 列 + 包含在 API response 中。S4（Zuckerberg）在满足该条件后删除。
- **不是 drive-by 的依据**：S4 scope 已包含 `prebuilt-auth-dialog.tsx` 重接线。在该工作中自然删除。

---

## 简化建议（在 M3 PR 中处理）

### 1. **`backend/app/services/chat_service.py:254-260` — 重写 PREBUILT/CUSTOM 分支**（Jensen S3 指南）

当前结构（M2 结束时）：
```python
else:  # PREBUILT 或 CUSTOM（所有非 MCP case）
    if tool.credential_id and tool.credential:
        cred_auth = resolve_credential_data(tool.credential)
    elif tool.auth_config:
        cred_auth = tool.auth_config
    else:
        cred_auth = {}
```

M3 后需要的行为：
- `tool.type == PREBUILT AND tool.provider_name` → 查询 user default connection → 若有 `conn.credential` 则 `resolve_credential_data(conn.credential)`，否则 `cred_auth = {}`（env fallback 由 tool builder 内部负责）
- `tool.type == PREBUILT AND tool.provider_name IS NULL` → legacy：保留现有 `tool.credential_id`/`tool.auth_config` 路径（tolerance 到 M6）
- `tool.type == CUSTOM` → **现有路径原样保留**（M4 工作对象，不要触碰）

建议：
```python
else:
    if tool.type == ToolType.PREBUILT and tool.provider_name:
        cred_auth = _resolve_prebuilt_auth(tool, user_default_conn_map)
    else:
        # CUSTOM 或 legacy PREBUILT(provider_name IS NULL)
        cred_auth = _resolve_legacy_tool_auth(tool)
```

- `_resolve_prebuilt_auth(tool, user_default_conn_map)`：module-private。以 `(tool.user_id, tool.provider_name)` 为 key 从 `user_default_conn_map` 中 lookup connection → 返回 `resolve_credential_data(conn.credential)` 或 `{}`。**cross-tenant guard**（`assert_credential_ownership`）复用 M2 模式。
- `_resolve_legacy_tool_auth(tool)`：原样提取当前 254-260 的 4-way fallback（保持行为）。
- **依据**：如果 4-way fallback 发生 2 重嵌套，可读性/回归风险增加。拆为 2 个 helper 后，M4 将 CUSTOM 改为经由 connection 时只需修改 `_resolve_legacy_tool_auth` 一处。M6 做 legacy drop 时也只需 1 处。
- **禁止新抽象**：不要创建单独 class/module。仅在 `chat_service` module 内增加 2 个 module-private function。
- **防止 drive-by**：CUSTOM 分支逻辑（`tool.credential_id`/`tool.auth_config` fallback）**semantic 变化 0**。只是将 PREBUILT 拆出的 refactoring。

### 2. **`backend/app/services/chat_service.py:152-174` — 扩展 `get_agent_with_tools` selectinload**（Jensen S3 指南）

当前：针对 MCP 的 `selectinload(Tool.connection).selectinload(Connection.credential)` chain 已存在。PREBUILT default connection 的 scope **不是每个 tool，而是 (user, provider)**，因此无法通过 selectinload chain 连接。

建议：
- 在 `get_agent_with_tools` 末尾遍历 agent.tool_links，从**拥有 PREBUILT + provider_name 的 tool 集合**中收集 `(user_id, provider_name)` 列表。
- user_default_conn_map：单独 query 1 次 — `SELECT * FROM connections WHERE user_id=:u AND type='prebuilt' AND provider_name IN (:providers) AND is_default=true` + `selectinload(Connection.credential)`。
- 映射成 dict 后注入 `build_tools_config`。N+1 防护的核心。
- **依据**：直接对应 progress.txt 高风险点 #1。如果每个 PREBUILT tool N 个都发 connection query，就会 N+1。用 IN query 1 次实现 O(1) round-trip。
- **简单性原则**：禁止引入 cache layer。只传一个 `dict[(user_id, provider_name), Connection]` in-memory。Query 结果只在 request 生命周期内存活。

### 3. **`backend/app/services/chat_service.py:273-278` — 保持 MCP 专用 config key 不变**（Jensen S3 指南）

```python
if tool.type == ToolType.MCP and mcp_server_url is not None:
    config_entry["mcp_server_url"] = mcp_server_url
    config_entry["mcp_tool_name"] = tool.name
    if mcp_transport_headers:
        config_entry["mcp_transport_headers"] = mcp_transport_headers
```

- **建议**：**禁止更改**。不要因为 PREBUILT 走新路径就触碰这个 MCP 专用 block。它是 M2 已稳定的路径。
- **依据**：MCP 分支是 M2 PR #54 中通过 Codex 第 6 次 adversarial 验证的代码。在 PREBUILT 修改 PR 中改动 semantic，会使回归表面积成倍增加。
- **措施**：S3 只新增 PREBUILT helper，并明确该 MCP block 1 行也不修改。

### 4. **新建 `frontend/src/components/connection/ConnectionBindingDialog.tsx` 公共 shell + 重新接线 3 个 dialog**（Zuckerberg S4 指南）

3 个 dialog 文件（`prebuilt-auth-dialog.tsx` / `custom-auth-dialog.tsx` / `mcp-server-auth-dialog.tsx`）结构上有 **90% 相同的 CredentialSelect + 保存按钮 + CredentialFormDialog 组合**。只有保存时调用的 API 不同：

| Dialog | 保存 API |
|--------|---------|
| prebuilt-auth-dialog | `useUpdateToolAuthConfig({authConfig: {}, credentialId})` |
| custom-auth-dialog | `useUpdateToolAuthConfig({authConfig: {}, credentialId})`（相同） |
| mcp-server-auth-dialog | `useUpdateMCPServer({credential_id})` |

目前称得上差异的点：
- `prebuilt-auth-dialog` 的 `detectProvider` + `matchingCredentials` filter（立即删除 #1）
- `mcp-server-auth-dialog` 的 `open/onOpenChange` 由外部控制（其余两个是内部状态）
- i18n namespace（`tool.authDialog` / `tool.customAuth` / `tool.mcpServer.auth`）

建议：
- `ConnectionBindingDialog` props: `{ type: 'prebuilt' | 'custom' | 'mcp', toolId?: string, mcpServerId?: string, providerName?: string, open?, onOpenChange?, trigger? }`
- 内部：复用 `CredentialSelect` + `CredentialFormDialog`。`type` 分支仅限保存时的 API 分支。
- 3 个文件**缩成薄 adapter，或在直接调用处替换为 `ConnectionBindingDialog`**。S4 由 Zuckerberg 判断 — 二者选择更少增加表面积的一边。
- **依据**：ADR-008 §正向 "UI 整合 — 3 个 auth dialog → 1 个 ConnectionBindingDialog + context prop（吸收 Backlog F）"。M3 scope 协议包含提前部分 M5（F）。
- **新抽象边界**：`ConnectionBindingDialog` 是单文件组件。禁止新增 HOC/自定义 hook。用 1 个 `type` prop 接收所有分支。

### 5. **`frontend/src/app/connections/page.tsx` — 添加 PREBUILT tab，保留现有 Credential list**（Zuckerberg S4 指南）

当前 page.tsx 只渲染 **credentials 列表**（`CredentialCard`）。根据 ADR-008 §正向 / CHECKPOINT S4 "/connections 页面重构"，M3 中需要暴露 PREBUILT connection。

建议：
- 现有 `CredentialCard` 列表**保留**（M5 计划以 Connection 为中心重构）。
- 顶部或单独 tab（例如 Tabs）添加 "连接（Connections）" section — PREBUILT provider dropdown + default toggle + credential 选择。
- **简化点**：不要重写现有 page.tsx，只新增 section。到 M5 前 Credential 中心 UX 共存。
- **依据**：CHECKPOINT §风险 #4 "Frontend ConnectionBindingDialog 整合难度"。如果同一 PR 中连 page.tsx 全面重构都尝试，会让回归表面积暴增。M3 目标到 "提供可编辑 PREBUILT connection 的 UX" 为止。
- **防止 drive-by**：`CredentialCard` 组件（190-256）、`credentials` filtering 逻辑（61-75）、delete flow（158-185）保持原样。禁止 semantic 变化。

### 6. **测试隔离 policy — 新建 1 个文件，现有 PREBUILT 测试仅 mechanical change**（贝索斯本人 S5 指南）

- 新建 `tests/test_connection_prebuilt_resolve.py` 1 个文件，容纳 **5+ scenario**（重复 M2 模式）：
  1. 2 个 mock user 运行同一个 PREBUILT tool，各自使用自己的 credential → 验证各自 `resolve_credential_data` 结果不同（ADR-008 §M3 测试 #1 "必须多用户隔离"）
  2. 没有 default connection 时返回 `cred_auth={}` + 验证保留 tool builder 的 env fallback
  3. `provider_name IS NULL` 的 legacy PREBUILT tool → `tool.credential_id` 路径仍工作（tolerance 到 M6）
  4. Alembic m10 mock user 自动 seed idempotent（再次运行相同 `(user_id, type='prebuilt', provider_name, is_default=true)` 组合时无 `IntegrityError`，直接 skip）
  5. Cross-tenant guard：即使 user_A 的 connection 被错误映射到 user_B 执行的 PREBUILT tool，`assert_credential_ownership` 也会阻断（证明复用 M2 引入的 guard）
- `tests/test_naver_tool.py`, `tests/test_tools_router_extended.py` 等现有 PREBUILT 测试**目标是 semantic 变化 0**。只允许因新增 `provider_name` 列而给 fixture 增加字段的 mechanical change。如果需要改期望值（assert），向 Satya 报告原因。
- **依据**：与 M2 报告简化 #5 原则相同。legacy fallback + env fallback 应保留现有测试的 semantic。若变化，本身就是 regression 信号。

---

## 暂缓（移交后续 milestone）

M3 PR 中**绝对不要触碰**。上一份 M1/M2 报告移交项 + M3 分析中新识别项。

| # | 位置 | 当前角色 | 建议时点 | 原因 |
|---|------|-----------|-----------|------|
| 1 | `backend/app/models/tool.py:80-82` `Tool.credential_id` FK | PREBUILT（legacy）/CUSTOM 公用 credential binding | **M6**（`m12_drop_legacy_columns`） | M3 中 PREBUILT 忽略。CUSTOM 使用到 M4。`is_system=True + provider_name IS NULL` case 的 legacy fallback 也需要 → 到 M6 前不可 drop。 |
| 2 | `backend/app/models/tool.py:79` `Tool.auth_config` JSON | PREBUILT（legacy）/CUSTOM inline auth | **M6** | 同上。CUSTOM 路径 + legacy PREBUILT fallback。 |
| 3 | `backend/app/models/tool.py:78` `Tool.auth_type` VARCHAR | CUSTOM HTTP auth 类型（`basic`/`bearer`/...） | **M6** | CUSTOM 路径仍引用。chat_service 通过 `config_entry["auth_type"] = tool.auth_type` 暴露。 |
| 4 | `backend/app/models/tool.py:30` `AgentToolLink.config` JSON | per-agent 工具 override | **M6** | ADR-008 §3 — 由 `agent_tools.connection_id`（M3+ 可支持，但迁移计划为 M5）替代，M6 drop。 |
| 5 | `backend/app/services/credential_service.py:110-119` `resolve_server_auth` | MCPServer auth 解析 helper | **M6** | M2 报告 #5 移交。legacy MCP fallback 路径调用。 |
| 6 | `backend/app/services/credential_service.py:122-142` `get_usage_count` | credential usage 汇总 | **M5/M6** | M5 添加 `connection_count` 后 M6 drop。M3 中保留 Tool/MCPServer 汇总。贝索斯/Jensen 都禁止修改区域。 |
| 7 | `backend/app/models/tool.py:35-58` 整个 `MCPServer` 表 | MCP server metadata | **M6** | M2 报告 #1 移交。 |
| 8 | `backend/app/models/tool.py:69` `Tool.mcp_server_id` FK | MCP tool → MCPServer link | **M6** | M2 报告 #2 移交。 |
| 9 | `backend/app/seed/default_tools.py` 1-357 当前结构 | PREBUILT tool seed metadata（无 provider_name） | **S2 内更新，不删除** | S2（Pichai）需为每个 PREBUILT entry 添加 `provider_name` key。现有 field 无删除对象。Web Search / Web Scraper / Current DateTime 等 `type='builtin'` entry 保持 `provider_name` NULL。 |
| 10 | `frontend/src/components/tool/credential-select.tsx` | Credential 选择 dropdown | **M5** | 继续在 `ConnectionBindingDialog` 内复用。M5 重构为 Connection 中心 UI 时，CredentialSelect 可重新定位为 ConnectionSelect 辅助组件。 |
| 11 | `frontend/src/app/connections/page.tsx:190-256` `CredentialCard` | credential 列表卡片 | **M5** | 根据简化 #5，M3 中保留。M5 替换为 ConnectionCard。 |
| 12 | `frontend/src/lib/hooks/use-tools.ts` `useUpdateToolAuthConfig` | tool auth_config/credential_id PATCH hook | **M4-M5** | CUSTOM 路径继续使用。M4 完成后替换为 connection-based hook。M3 中禁止修改。 |

---

## 安全/回归检查（M3 PR 中必须验证）

M3 hot path 变更可能引发的回归。反映到贝索斯 S5 新测试：

1. **防止 PREBUILT cross-tenant credential 泄露（ADR-008 §问题 1 的本质）**
   - user_A 的 default connection 绝不能映射到 user_B 执行的同一 PREBUILT tool。
   - 验证：在 `test_connection_prebuilt_resolve.py` 中加入 "2 user + 同一 tool + 各自 credential" scenario + 验证 `assert_credential_ownership` 调用路径。

2. **保留 env fallback（ADR-008 §11 协议）**
   - 在没有 connection 的 PREBUILT tool 执行时，`naver_tools.py` 内部必须自动使用 `settings.naver_client_id`。
   - 验证：connection 0 个状态 + 设置了 `NAVER_CLIENT_ID` env 的状态下执行 Naver Blog Search 时，response 使用 env 值（通过 mock HTTP call 验证 header/parameter）。

3. **保留 legacy fallback（provider_name IS NULL）**
   - m10 之后仍可能有映射失败的 PREBUILT tool（例如新增 tool 名与 mapping table 不一致）保留为 `provider_name=NULL`。此时现有 `tool.credential_id` 路径必须工作 — 防止现有 PoC 用户配置的 credential 中断。
   - 验证：新测试中新增 1 个 provider_name=NULL scenario。

4. **m10 idempotent**
   - 相同 `(user_id, type='prebuilt', provider_name, is_default=true)` 组合已由 partial unique index 阻止。m10 在第二次 upgrade/其他环境执行时，必须采用 "检查是否存在 + insert only" 模式，使 `INSERT` 在不发生 `IntegrityError` 的情况下 skip。
   - 验证：在 `test_connection_prebuilt_resolve.py` 中加入 idempotent scenario。

5. **env var 未设置环境中 m10 skip**
   - 如果 `settings.naver_client_id` 是空字符串/None，则不要创建该 provider 的 credential+connection seed（与 ENCRYPTION_KEY 未设置时相同 policy，ADR-007 模式）。
   - 验证：临时 unset env 的 alembic upgrade 中确认 connection 0 项。

6. **Response schema 不暴露 credential 明文**
   - 暴露 `tool.provider_name` OK（非敏感）。但 connection response 中绝不能 echo `credential.data_decrypted`/`data_encrypted`，需要重新验证现有 M1/M2 schema guard。
   - 验证：M1 的 `test_connections.py` response schema assertion 应原样 PASS（保留现有回归）。

---

## drive-by 禁止声明

**M3 scope**：`tools.provider_name` 列 + Alembic m10（列 backfill + mock user seed）+ 重写 `chat_service.build_tools_config` PREBUILT 分支 + 新增 `connection_service.get_default_connection` helper + 新建 `ConnectionBindingDialog` + 重新接线 3 个 dialog + `/connections` PREBUILT tab。上述简化 6 项都在此 scope 内处理。

**scope 外 legacy 删除在 M4（CUSTOM Connection 迁移）/ M5（UI 重构，agent_tools.connection_id override）/ M6（legacy 列 drop）中处理**。本 PR 中：

- 不 drop `tools.credential_id`, `tools.auth_config`, `tools.auth_type` 列
- 不触碰 `mcp_servers` 表和 `tools.mcp_server_id`
- 不触碰 `agent_tools.config` JSON
- 不修改 `credential_service.py` 的 signature（`get_default_connection` 只加到 `connection_service.py`）
- 不触碰 `naver_tools.py` / `google_tools.py` / `google_workspace_tools.py` 的 env fallback 模式
- 不更改 CUSTOM 分支（`_resolve_legacy_tool_auth`）的 semantic（仅简单 refactoring）
- 不重写 `/connections` 页面的现有 `CredentialCard` 列表（只新增 PREBUILT tab）

---

## 结论

| 分类 | 数量 | 备注 |
|------|------|------|
| **立即删除** | **1 项** | `prebuilt-auth-dialog.tsx` 的 `detectProvider` helper — 在 S4 内自然删除。 |
| **简化建议** | **6 项** | S3（Jensen）3 项 + S4（Zuckerberg）2 项 + S5（贝索斯）1 项。现有 module signature 变更 0。 |
| **暂缓（后续 milestone）** | **12 项** | M4 1 项，M5 3 项，M5/M6 1 项，M6 7 项。M1/M2 报告移交 + 新增 M3-specific 3 项。 |

**贝索斯判断**：M3 是（a）新列 + 数据 migration + mock user 自动 seed，（b）重写 hot path（`chat_service.build_tools_config` 非 MCP 分支）+ 新 N+1 防护 query，（c）UI dialog 3 类整合（提前部分 M5）这**三个高风险轴同时移动**的 milestone。表面积比 M2 的 MCP hot path 重写更大。

legacy fallback（`provider_name IS NULL` + `tool.credential_id`）保留到 M6 是 ADR-008 §迁移策略的核心承诺；如果本 PR drop legacy 列或触碰 CUSTOM 分支，回归区域会成倍爆炸。简化 6 项全部以**保留现有 signature，并拆分新 helper/component + 薄 adapter**的方向解决，不给已经很大的 PR 表面积增加额外风险。

根据 env fallback policy（ADR-008 §11），`naver_tools.py`/`google_tools.py` 内的 `or settings.*` 模式在**M3 结束后仍保留**。当没有 connection 时，`chat_service` 传 `cred_auth={}`，tool builder 会自动使用 env，这个 2 层结构已经工作 — 为防 S3（Jensen）在 chat_service 中加入 env 再查询逻辑，已在事前事实 #6 明确。

**向 Satya 报告**：建议将事前事实 6 项（尤其 #1 provider_name 未提前反映 / #2 PREBUILT 不使用 `tool.connection_id` / #4 不存在 `get_default_connection` / #6 防止 env fallback 2 重处理）**明确传达**给 S2/S3 负责人。简化 #1（chat_service 拆 2 个 helper）+ #2（注入 user_default_conn_map）是 S3 实现骨架，需要与 Jensen 1:1 共享。
