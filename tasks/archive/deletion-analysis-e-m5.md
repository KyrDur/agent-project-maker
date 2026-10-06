# S1 删除分析报告 — Backlog E M5

**作者**：贝索斯
**日期**：2026-04-19
**Scope**：仅 Frontend（Backend 修改 0 项）
**依据**：CHECKPOINT.md §S1, ADR-008, exec-plan §4 M5

---

## Working-Backwards 摘要

从用户视角看 M5 完成后的世界：
- 进入 `/connections` → Connection 卡片（PREBUILT/CUSTOM/MCP section）为 1 级对象，Credential 卡片直接暴露 0 个。
- 点击 "添加连接" 后，无论从哪里进入都会打开**相同的 ConnectionBindingDialog**（3 种 surface → 1）。
- 工具卡片的 "认证" 按钮、`/add-tool` MCP tab 的 "注册" 按钮也收敛到同一个 shell。
- Backend 保持 M4 状态不变（`connections` 表 + 无 `agent_tools.connection_id`）。

**M5.5（后续）**：agent-level override（`agent_tools.connection_id`）— 本 M5 中**绝对不触碰**。
**M6（后续）**：legacy 列 drop（`tool.credential_id`, `tool.auth_config`, `tool.mcp_server_id`, `agent_tools.config`, `mcp_servers` 表）— 本 M5 中**不触碰**。

---

## 1. 立即删除（M5 中直接删除）

### 1.1 `frontend/src/app/connections/page.tsx` — Credential 卡片 surface
| 对象 | 位置 | 原因 |
|------|------|------|
| `CredentialCard` 组件 | `page.tsx:302-368` | Credential 只在 Connection detail drawer 中暴露。禁止作为 1 级卡片列出（ADR-008 重构方向） |
| `filteredCredentials`/`search`/`typeFilter` | `page.tsx:64-84, 108-134` | Credential 搜索/filter 在 Connection 中心页面没有意义。替换为 Connection 自身搜索（S4 中重构） |
| `deletingTarget` + `AlertDialog` delete 流程 | `page.tsx:67, 172-199` | Credential 删除在 Connection detail 中执行（包含解除连接 UX） |
| `openCreate`/`openEdit` 单独入口 | `page.tsx:86-94, 130-134, 166-170` | "添加连接" CTA → 统一为 ConnectionBindingDialog |
| 顶层使用 `useCredentialProviders`/`getProviderLabel` | `page.tsx:59, 99-102, 148` | 删除 Credential 卡片后，同一数据在 Connection detail 中引用（迁移到 re-use） |

**依据**：CHECKPOINT §scope 协议 "删除 Credential 卡片，Connection 为 1 级对象"。
**注意**：`useCredentials`/`useDeleteCredential` **hook 本身保留** — Connection detail drawer 会复用（与下方 §3 暂缓对象区分）。

### 1.2 调用处：`tools/page.tsx` 的 PREBUILT 分支
| 对象 | 位置 | 处理 |
|------|------|------|
| `PrebuiltAuthDialog` import + 调用 | `app/tools/page.tsx:30, 241-249` | 改为直接调用 `ConnectionBindingDialog(type='prebuilt', providerName=tool.provider_name)`。从 trigger prop 切换为 open state（S3） |
| `PrebuiltAuthDialog` 文件本身 | `components/tool/prebuilt-auth-dialog.tsx`（60 行） | 当前 thin wrapper。只剩一行 legacy fallback（`!isPrebuiltProviderName → CustomAuthDialog`）。删除会导致 fallback 路径消失 → 与 M6 legacy drop 一起处理才安全，因此**文件保留到 M6**，只替换调用处 |

**决定**：文件作为 thin wrapper 保留到 M6，但将 `tools/page.tsx` 调用处改为直接调用 `ConnectionBindingDialog`，让 **M5 的 "3 dialog → 1" 吸收验证可以通过 grep**。

---

## 2. 简化/替换（吸收到 ConnectionBindingDialog）

### 2.1 `CustomAuthDialog`（components/tool/custom-auth-dialog.tsx, 108 行）
- **当前 surface**：`CredentialSelect` + `CredentialFormDialog` + `useUpdateToolAuthConfig({credentialId})` — 直接编辑 `tool.credential_id`。
- **M5 处理**：给 ConnectionBindingDialog 新增 `type='custom'` 分支（find-or-create connection，CUSTOM `provider_name='custom_api_key'` scope）。
- **替换调用处**：`app/tools/page.tsx:252-260` — CustomAuthDialog → ConnectionBindingDialog(type='custom', tool)。
- **注意（M4 bridge）**：CustomAuthDialog 只执行 "替换现有 tool 的 credential" — 不更改 connection_id。替换后 chat_service `_resolve_custom_auth` 从 `tool.connection_id` derive credential，因此**已设置 connection_id 的 tool 的 credential 替换**通过 connection.credential_id PATCH 解决（ADR-008 N:1）。
- **文件本身是否保留**：CustomAuthDialog 也被 `PrebuiltAuthDialog` 的 legacy fallback（§3）引用。**文件保留到 M6**，只替换调用处。

### 2.2 `MCPServerAuthDialog`（components/tool/mcp-server-auth-dialog.tsx, 110 行）
- **当前 surface**：`server.credential_id` + `useUpdateMCPServer({credential_id})` — 直接编辑 mcp_servers row 的 credential FK。
- **M5 处理**：给 ConnectionBindingDialog 新增 `type='mcp'` 分支。但 backend `mcp_servers` 表/`useUpdateMCPServer` API **保留到 M6**。
- **替换调用处**：`components/tool/mcp-server-group-card.tsx:28, 143`。
- **非对称性**：MCP 与 PREBUILT/CUSTOM 不同，**server entity（URL+name）先存在**，credential 是 2 级属性。M5 中进入 "认证" 时，只将**credential binding**吸收到 ConnectionBindingDialog，server create/rename/delete 保持原样。也就是说 `type='mcp'` 设计为接收 mcp_server_id 作为外部 context、只替换 credential 的 shell。
- **risk**：需要确认 MCP connection entity 本身在 M4 是否存在 — exec-plan §4 M5 明确到 "输入 server config"，但 ADR-008 中 MCP connection = 1 server，credential 是 server 属性。由团队 Cook 在 S2 spec 中确定。

### 2.3 `add-tool-dialog` MCP tab（components/tool/add-tool-dialog.tsx, 383 行）
- **当前流程**：form(name, url, credential_id) → `useRegisterMCPServer` → 显示 discoveredTools。
- **M5 处理**：保留 MCP tab 本体，但将 credential select 区域重新接线为**进入 ConnectionBindingDialog 的按钮** OR 保留当前 CredentialSelect，只将 "创建新 credential" 统一到 ConnectionBindingDialog(type='mcp')。
- **推荐**：MCP tab 目的是 "注册新 server"，因此整合 ConnectionBindingDialog 过度。保留 CredentialSelect，只让**"创建新 credential" CTA** 收敛到 ConnectionBindingDialog — 由 Zuckerberg 在 S3 判断。
- **Custom tab**：M4 已切换为 connection find-or-create（add-tool-dialog.tsx:96-116）。**不变**。但传递 `credential_id: customCredentialId` bridge 的行（157-160）移交 §3 暂缓（M6）。

---

## 3. 暂缓 M6 — Legacy Drop 对象（M5 中绝对不触碰）

### 3.1 基于 `tool.credential_id` 的代码
| 文件 | 行 | 暂缓原因 |
|------|------|-----------|
| `components/tool/prebuilt-auth-dialog.tsx` | 33-35 | provider_name NULL fallback → 委托给 CustomAuthDialog。与 backend legacy fallback 1:1 对应。M6 中统一删除 fallback 路径时同步删除 |
| `components/tool/custom-auth-dialog.tsx` | 16, 36, 42-46 | 通过 `useUpdateToolAuthConfig` 直接编辑 `tool.credential_id`。必须与 backend `tool.credential_id` 列 drop 绑定才安全 |
| `components/tool/add-tool-dialog.tsx` | 153-160 | 创建 Custom tool 时同时发送 `credential_id` 字段（bridge）。虽有 "M5 consumer 切换后删除" 注释，但 consumer = `tools/page.tsx` getAuthStatus 也依赖 `tool.credential_id` — **全部在 M6 中统一删除**才安全 |
| `app/tools/page.tsx` | `getAuthStatus`（未阅读区间） | Custom tool "configured" 判定基于 `tool.credential_id`。切换为 Connection-based 后需确认 backend API response 是否要包含 connection summary — **M6 scope** |

### 3.2 `tool.auth_config` (inline auth)
- **暂缓**：M6 legacy drop 对象。`components/tool/custom-auth-dialog.tsx:42-45` 的 `useUpdateToolAuthConfig({authConfig: {}, credentialId})` 调用会清空 `auth_config`。M6 中与列一起删除。

### 3.3 `tool.mcp_server_id` & `mcp_servers` 表
- **暂缓**：`lib/api/` 内 mcp_server 相关 API、`useRegisterMCPServer`、`useUpdateMCPServer`、`useDeleteMCPServer`、`mcp-server-group-card.tsx`、`mcp-server-rename-dialog`、整个 `mcp-server-auth-dialog.tsx`。M6 中将 server entity 整合到 Connection(type='mcp') 后统一删除。
- **M5 允许**：M5.2 调用处替换（§2.2）只改变 surface — `useUpdateMCPServer({credential_id})` 调用本身保留（在 ConnectionBindingDialog 内调用或通过单独 mutation hook 绕行）。

### 3.4 `agent_tools.config` JSON
- **暂缓**：agent 级工具设置 JSON。超出 M5 scope。若 agent 编辑页面仍在使用，则保留到 M6。

### 3.5 `PrebuiltAuthDialog`/`CustomAuthDialog`/`MCPServerAuthDialog` 文件本身
- **暂缓**：根据 §1.2、§2.1、§2.2 决定，**只替换调用处**，文件作为 thin wrapper 保留到 M6。F 吸收验证以 grep 调用处 0 判定（按 CHECKPOINT §S3 最后 checklist 为 OK）。

---

## 4. 暂缓 M5.5 — agent_tools.connection_id override（M5 中绝对不触碰）

### 当前 codebase 扫描结果
- **不存在 agent_tools.connection_id 列**（M4 状态）。grep `connection_id.*agent_tools` → 0。
- **不存在 agent 工具级 connection override UI**。`app/agents/[id]/config/*` 只处理基于 agent_tools.config JSON 的设置。
- **结论**：M5.5 的 backend m12 + chat_service 分支 + 新 UI 全部是**新工作**。M5 中没有现有代码可触碰。

**M5 中的行为**：`frontend/src/app/agents/[id]/config/**`, `backend/app/services/chat_service*`, `backend/app/routers/agent_tools*`, `backend/alembic/versions/**` — **禁止 touch**。

---

## 5. 新工作（M5 中要创建的项目 — 虽非删除对象但用于上下文）

- `components/connection/connection-binding-dialog.tsx` — 已在 M3 作为 PREBUILT 专用存在（237 行）。M5 S3 中扩展为 `type` discriminated union（prebuilt | custom | mcp）。
- `messages/ko.json` 新增 `connection.binding.{custom,mcp}.*` key（已有 prebuilt section）。
- Connection detail drawer/modal（S4）— 复用 `credentials` hook。

---

## 6. 验证 checklist（M5 完成时重新确认）

```bash
# F 吸收：3 个 AuthDialog 调用处必须为 0（文件保留为 thin wrapper）
rg -n "PrebuiltAuthDialog|CustomAuthDialog|MCPServerAuthDialog" frontend/src/app frontend/src/components --glob '!*auth-dialog.tsx'
# 预期：0 hits

# ConnectionBindingDialog 调用处 ≥ 3（tools/page.tsx × 2, mcp-server-group-card.tsx × 1, connections/page.tsx × 1）
rg -l "ConnectionBindingDialog" frontend/src

# Backend 0 项
git diff main...HEAD -- backend/ | wc -l
# 预期：0

# agent_tools / chat_service / alembic 0 项
git diff main...HEAD -- 'backend/app/services/chat_service*' 'backend/app/routers/agent_tools*' 'backend/alembic/' | wc -l
# 预期：0
```

---

## 7. 风险信号（与 Satya 共享）

1. **PrebuiltAuthDialog 文件保留 vs 删除判断**：当前 thin wrapper + legacy fallback 与 backend fallback 1:1 对应。删除会使 legacy provider_name NULL tool "无法管理"。**推荐：保留文件，只替换调用处**。
2. **CustomAuthDialog 的 connection semantics**："只替换 credential" → 可通过 connection.credential_id PATCH 解决。但如果用户已经创建了使用 M4 bridge override 流程（`tool.credential_id != connection.credential_id`）的 row，PATCH 方向可能覆盖 bridge — **S3 实现时需在团队 Cook spec 中明确 "如何处理现有 bridge row"**。
3. **MCP server + credential 分离 UX**：ConnectionBindingDialog(type='mcp') 需要通过 props 接收 server_id。新 server create 仍在 add-tool-dialog 中执行 — UX 被分到两处。团队 Cook S2 中需要决定整合 vs 分离。
4. **tools/page.tsx getAuthStatus**：本分析未阅读文件上半部分（~30-220）。如果存在基于 `tool.credential_id` 的 "configured" 判定，替换 CustomAuthDialog 后是否仍能在 UI 中无回归工作，**S3 实现中确认**。
5. **Credential hook 复用边界**：`useCredentials` 本身在 Connection detail drawer 中复用。但 `useDeleteCredential` 容易与 Connection 删除混淆 — spec 需要明确 "Connection 删除 = Credential 删除" 还是 "Connection 删除 ≠ Credential 删除（可能被其他 connection 引用）"。

---

## 8. 分类摘要表

| 类别 | 数量 |
|----------|------|
| 立即删除（M5） | 5 个（connections/page.tsx Credential 卡片 section 相关）+ 调用处替换 3 项 |
| 简化/替换（M5） | 3 个 dialog 调用处 → 吸收到 ConnectionBindingDialog |
| 暂缓 M6 | legacy 列 4 类 + 文件 3 个（thin wrapper）+ 全部 mcp_servers API |
| 暂缓 M5.5 | 无（新功能，不改现有代码） |
| Backend 变更 | **0 项** |

**Bezos "?"**：如果 tools/page.tsx `getAuthStatus` 的 Custom tool 判定依赖 `tool.credential_id`，S3 实现后可能出现 "Custom 工具已绑定 connection 仍显示为 '未设置'" 的回归 → Zuckerberg 实现时确认。
