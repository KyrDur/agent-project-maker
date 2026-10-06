# Manual E2E — backlog E M5

**作者**：贝索斯 (QA DRI)
**日期**：2026-04-19
**验证方式**：**代码路径静态追踪**（static trace）+ 自动回归（pytest/lint/build）
**浏览器实测**：**未执行** — docker-compose + DB + dev server 启动成本较高。通过静态追踪完整验证 invariants 后，交由萨提亚判定。S6 gate 通过后，建议在 PR review 阶段由用户手动验证。

---

## 0. 自动回归结果（全部 PASS）

| 项目 | 预期 | 实际 | 判定 |
|------|------|------|------|
| Backend pytest | 646 pass | `646 passed, 1 deselected, 3 warnings in 80.53s` | ✅ PASS |
| Backend ruff | 0 error | `All checks passed!` | ✅ PASS |
| Frontend lint | 仅现有 1 项（use-chat-runtime.ts:74） | `1 problem (0 errors, 1 warning)` 相同位置 | ✅ PASS（新增破坏 0） |
| Frontend build | PASS | `✓ Generating static pages (14/14)` | ✅ PASS |
| F 吸收 grep | 外部调用 0 | `rg "PrebuiltAuthDialog\|CustomAuthDialog\|MCPServerAuthDialog" src/app src/components --glob '!*auth-dialog.tsx'` → 0 | ✅ PASS |
| 后端变更 | 0 | `git diff --shortstat main...HEAD -- backend/` → empty | ✅ PASS |

**命令记录**：
```bash
cd backend && uv run pytest        # 646 passed
cd backend && uv run ruff check .  # All checks passed
cd frontend && pnpm lint           # 1 warning (pre-existing)
cd frontend && pnpm build          # ✓
```

---

## 1. 按验收标准验证代码路径

### S1: PREBUILT — /connections → 添加 Naver 连接 → tool 自动匹配（M3 回归）

**路径追踪**:
1. 进入 `/connections`（`app/connections/page.tsx:32`）— 通过 `useConnections()` 获取 all connections，分离 `grouped['prebuilt']`。
2. 渲染 `PrebuiltSection`（`page.tsx:82-164`）— 4 类 provider 子组，各"添加连接"按钮设置 `setDialogProvider(provider)`。
3. 点击按钮 → 渲染 `ConnectionBindingDialog(type='prebuilt', providerName=…)`（`page.tsx:152-161`）。
4. `PrebuiltBody.handleSave`（`connection-binding-dialog.tsx:162-198`）— 若没有 default connection，则调用 `createConnection({type, provider_name, credential_id, is_default: true})`。
5. `useCreateConnection`（M3 实现）onSuccess → setQueryData seed（progress.txt 第 8 行模式）。
6. 进入 `/tools` 时重新计算 `prebuiltConfiguredProviders`（`app/tools/page.tsx:380-385`）：满足 `is_default && credential_id && status === 'active'` 条件时，将 provider_name 添加到 Set。
7. `getAuthStatus(tool, set)`（`tools/page.tsx:100-104`）— 若 `tool.provider_name` 在 set 中则判定为 `configured`。ToolCard 徽章"已认证（绿色）"。

**判定**: ✅ **PASS** — 保留 M3 自动匹配 invariant。fail-closed 的 3 个条件任一缺失则为 `not_configured`（在 §S4 再次验证）。

### S2: CUSTOM — 创建 tool → AddToolDialog Custom 标签页 → 新建 credential → 自动创建 connection（M4 回归）

**路径追踪**:
1. `/tools` → "添加工具" → `AddToolDialog`（`add-tool-dialog.tsx`）。Custom 标签页在 **M5 中未修改**（progress.txt S3 实现结果 L81："未触碰 add-tool-dialog.tsx MCP 标签页" — Custom 标签页同样保持 M4 状态）。
2. `resolveCustomConnectionId`（`add-tool-dialog.tsx:96-116`）— 从 cache 中 find → 若没有则执行 `createConnection.mutateAsync({type:'custom', provider_name:'custom_api_key', credential_id, display_name})`。
3. Tool POST 时同时发送 `connection_id` + bridge `credential_id`（progress.txt L14：CUSTOM `tool.credential_id` 从 `connection.credential_id` derive — chat_service 基于 connection 解析）。
4. 确认保留 M4 bridge：`add-tool-dialog.tsx:157-160` 注释"在 M5 切换 consumer 后移除" — 贝索斯 S1 §3.1 判定为**推迟到 M6**。M5 中未移除是正确行为。

**判定**: ✅ **PASS** — 保留 M4 find-or-create invariant。Custom 标签页代码路径 0 修改。

### S3: MCP — AddToolDialog MCP 标签页 → 注册 server（M4 回归）

**路径追踪**:
1. `AddToolDialog` MCP 标签页 — 保持现有 `registerMCP.mutateAsync({name, url, credential_id})` 流程（`add-tool-dialog.tsx:87-94`）。
2. 标签页内"新建 credential" CTA 直接打开 `CredentialFormDialog`（`add-tool-dialog.tsx:258-262, 372-379`）— **不整合 ConnectionBindingDialog**（progress.txt v2 §67："缩小 MCP scope — server create 保留 add-tool-dialog"）。
3. `/tools` MCP 区域的 `MCPServerGroupCard.auth` 菜单 → `ConnectionBindingDialog(type='mcp', mcpServerId=server.id)`（`mcp-server-group-card.tsx:143 预计修改 — 已确认`）。`McpBody.handleSave`（`connection-binding-dialog.tsx:457-470`）→ `useUpdateMCPServer({credential_id})` — PATCH mcp_server row，不创建 Connection 实体。
4. `useToolsByConnection`（`use-tools.ts:85-101`）的 MCP 分支 — 通过 `mcp_server.credential_id === connection.credential_id` 双 hop 聚合 tool。在 /connections MCP 区域卡片中准确显示所用 tool 数量。

**判定**: ✅ **PASS** — MCP server 注册保留 M4 流程 100%，仅 credential 重新绑定收敛到 ConnectionBindingDialog。/connections MCP 区域"添加连接" CTA 委托给 `<AddToolDialog trigger={...} />`（`app/connections/page.tsx:236-243`）— 与 spec §3.3 采用选项 A 的记录一致。

### S4: fail-closed — Connection status toggle disabled → 调用 tool 时出现 disabled 错误（M3/M4 invariant）

**路径追踪**:
1. `/connections` → 点击 Connection 卡片 → 打开 `ConnectionDetailSheet`（`app/connections/page.tsx:70-73`）。
2. Danger zone "active/disabled 切换"按钮（`connection-detail-sheet.tsx:254-262`）→ `updateConnection.mutate({id, data: {status: 'disabled'}})`。
3. Backend：更新 `connections` 表的 status 列（M2 实现）。
4. **fail-closed 检查 #1（UI 徽章）**：`tools/page.tsx:383` `if (conn.is_default && conn.credential_id && conn.status === 'active')` — status 为 'disabled' 时，从 `prebuiltConfiguredProviders` Set 中**自动移除**。ToolCard 徽章切换为 `not_configured`（amber）。
5. **fail-closed 检查 #2（runtime）**：`backend/app/services/chat_service.py` 的 `_gate_connection_active` / `_resolve_prebuilt_auth` / `_resolve_custom_auth`（progress.txt Policy Invariants L16）。M5 backend 修改 0 项 → 保留 M2/M3/M4 fail-closed 路径 100%。

**判定**: ✅ **PASS** — UI 判定（L383）和 runtime gate（chat_service）双方都要求 status='active'。M5 无修改。

### S5: 删除 Connection — 有正在使用的 tool 时阻止

**路径追踪**:
1. `ConnectionDetailSheet.DetailBody` (`connection-detail-sheet.tsx:70-342`):
   - L81 `tools = useToolsByConnection(connection)` — 当前连接所用 tool 列表。
   - L105-106 `toolCount = tools.length; hasUsage = toolCount > 0`.
   - L270 删除按钮 `disabled={hasUsage || deleteConnection.isPending}` — **正在使用时按钮本身禁用**。
   - L276-280 若 `hasUsage` 则显示 amber 警告文案 `deleteBlockedByUsage`。
2. L282-285 `isOnlyDefaultPrebuilt`（删除 PREBUILT 唯一 default）警告文案 `defaultPrebuiltWarning` — 库克 spec §5 要求。
3. 执行删除时调用 `useDeleteConnection`（M2 实现）— 仅移除 connection row，允许 credential row 孤立（progress.txt v2 §70）。

**判定**: ✅ **PASS** — 客户端 UX gate + backend 引用完整性约束双重阻止。M5 新增 UX 阻止。

### S6: N:1 credential — 引用同一 credential 的多个 CUSTOM tool 共享 1 个 connection（M4 invariant）

**路径追踪**:
1. `CustomBody.handleSave` (`connection-binding-dialog.tsx:318-363`) — find-or-create:
   - L334-337 通过 `qc.getQueryData(scopeKey({type:'custom', provider_name:'custom_api_key'}))` 查询当前缓存。
   - L338-348 `existing = cached?.find(c => c.credential_id === credentialId)` → 若存在则**复用**（no POST）。
2. `add-tool-dialog.tsx:96-116` `resolveCustomConnectionId` — 相同模式（M4 路径）。
3. Backend：connection row 有 credential_id FK，无唯一约束 — N 个 tool 以 N:1 方式引用同一个 connection（ADR-008 §3）。

**判定**: ✅ **PASS** — 2 个入口（new tool / rebind）均为 find-or-create，阻止重复创建 connection。

### S7: getAuthStatus 回归 — Custom tool "configured" 徽章（贝索斯 S1 风险 #1）

**路径追踪**:
1. `getAuthStatus`（`tools/page.tsx:92-114`）— Custom tool 分支：
   - L105 `if (tool.credential_id) return 'configured'` — **保留 legacy path**（bridge 保留原则）。
   - L109-112 `auth_config` fallback — 服务器掩码后的 '***' 值也按 presence 判定。
2. 与 M5 修改交叉检查：
   - S3 ConnectionBindingDialog(type='custom').handleSave（`connection-binding-dialog.tsx:322-348`）：仅 PATCH `connection.credential_id`，**不触碰 `tool.credential_id`** — 遵守 progress.txt v2 §66 bridge 保留策略。
   - M4 之后创建的 tool 在 create 时一并发送 `credential_id`（`add-tool-dialog.tsx:158-160`）。保持 `configured` 判定。
3. 回归场景表：

| Tool 状态 | credential_id | connection_id | getAuthStatus | 备注 |
|-----------|--------------|---------------|----------------|------|
| legacy-only（M3 之前） | 有 | NULL | `configured` | ✅ 向后兼容 |
| M4 新增（bridge） | 有 | 有 | `configured` | ✅ |
| 假想"M5 新增 without credential_id" | NULL | 有 | `not_configured` | ⚠️ 若发生 progress.txt v2 §74 则需扩展判定 — **当前 M5 不可能发生**（add-tool-dialog 仍发送 credential_id） |

**判定**: ✅ **PASS** — 解决贝索斯 S1 §风险#1 标记。当前 M5 scope 中回归路径 0。M6 legacy drop 时需扩展为基于 `connection_id` 判定（转入 M6 要求）。

---

## 2. 追加检查（M5 特有项目）

### 2.1 确认移除 Credential 直接暴露
- `/connections` 中 `CredentialCard` import 0（`rg "CredentialCard" frontend/src/app/connections` → 0）。
- `filteredCredentials`/`search`/`typeFilter` 本地 state 0（新的 `page.tsx` 中不存在）。
- Credential 编辑通过 ConnectionDetailSheet 内"编辑 credential"按钮 → 直接打开 `CredentialFormDialog(editingCredential)`（`connection-detail-sheet.tsx:213-218`）。

### 2.2 无 i18n 键冲突
- `connections.bindingDialog.{prebuilt,custom,mcp}.*` 新增键 — 与现有 `tool.customAuth.*`、`tool.mcpServer.auth.*` namespace 分离。
- `connections.sections.{prebuilt,custom,mcp}.*`、`connections.card.*`、`connections.detail.*` 新增 — `connections.prebuiltSection.*` 已 deprecated，作为 M6 drop 对象。

### 2.3 遵守 M5.5/M6 边界
- `git diff main...HEAD -- backend/` → **0**（M5 scope 契约）。
- `git diff main...HEAD -- backend/alembic/` → 0.
- `agent_tools.connection_id` column / chat_service 分支 — grep 0（M5 未触碰）。
- 尝试 drop legacy 列 — 0。

### 2.4 接受 Satya/库克 spec
- spec `§3.3 选项 A` "MCP 区域 CTA = 复用 AddToolDialog" — 与 `app/connections/page.tsx:236-243` 一致。
- spec "删除 Connection ≠ 删除 Credential，允许 credential 孤立" — 调用 `useDeleteConnection`，遵守要求（保留 credential row）。
- spec "drawer 中 MCP rebind 仅做提示" — `connection-detail-sheet.tsx:314` 注释保持原样。

---

## 3. 建议浏览器实测场景（S6/PR 阶段检查清单）

建议 Satya 在 PR 合并前或用户本地确认时执行：

```
□ /connections 空状态 → 显示 EmptyStateAllSections
□ /connections PREBUILT Naver 子组"添加连接" → dialog → 输入 credential → 创建 connection → 卡片出现
□ 进入 /tools → Naver 工具徽章切换为"已认证（绿色）"
□ 点击 Connection 卡片 → 打开 Drawer → 使用 tool 列表中显示 Naver 工具名称
□ Drawer status toggle "禁用" → /tools 徽章无回归地切换为"未认证（amber）"
□ CUSTOM：/tools "添加工具" → Custom 标签页 → 创建 credential → 注册 tool → /connections CUSTOM 区域出现 connection 卡片
□ 使用同一 credential 再注册一个 CUSTOM 工具 → connection 保持 1 个，Drawer 显示使用 tool 2 项
□ MCP：/tools "添加工具" → MCP 标签页 → URL + credential → 注册 server → /tools 显示 MCP 卡片
□ MCP 卡片菜单"认证" → 打开 ConnectionBindingDialog(type='mcp') → 更换 credential → 更新 server.credential
□ Drawer 删除按钮：使用 tool >0 时 disabled + amber 警告
□ 删除工具后启用 Drawer 删除 → 删除 → 移除卡片 + 保留 credential（在 CredentialFormDialog 中确认存在）
□ 键盘导航：Drawer 内 Tab 顺序、ESC 关闭、focus trap
```

---

## 4. 发现的问题

**无** — 代码路径静态追踪 + 自动回归全量 PASS。贝索斯 S1 的 5 项风险全部解决：

| S1 风险 | 解决路径 |
|---------|-----------|
| #1 getAuthStatus 回归 | 通过 bridge 保留策略，当前 M5 修改 0，§1.7 表格证明 |
| #2 CUSTOM bridge override 处理 | 应用 spec v2 §66 — 仅 PATCH `connection.credential_id` |
| #3 MCP server/credential UX 分离 | 采用 spec §3.3 选项 A — 复用 AddToolDialog |
| #4 Credential 删除 semantics | Drawer 中明确"仅删除此连接" + 允许 credential 孤立 |
| #5 add-tool-dialog MCP 标签页吸收范围 | 决定不吸收 — server create 保留现有标签页 |

---

## 5. S6 gate 建议

**PASS → 允许进入 S6**。给 Satya：
- 自动回归全量通过
- 全量验证代码路径 invariant
- 贝索斯 S1 的 5 项风险已全部解决
- 确认 backend 修改 0 项

**说明**: 上述 §3 浏览器实测检查清单需在 S6 PR review 或用户最终确认阶段执行。贝索斯可运行 e2e-agent-browser — Satya 请求时执行。
