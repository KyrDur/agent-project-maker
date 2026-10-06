# M6.1 — 删除分析报告（deletion-analysis-e-m6-1）

**作者**：贝索斯（QA/删除分析 DRI）
**编写日期**：2026-04-24
**Branch**：`feature/backlog-e-m6-1` @ `18d98be` base
**产物位置**：`tasks/deletion-analysis-e-m6-1.md`
**Plan**：`/Users/chester/.claude/plans/m6-1-spicy-kurzweil.md`
**最终判定**：**🟢 GREEN** — M2/M4 可立即开始

---

## 摘要（数字）

| 指标 | 值 |
|------|----|
| Backend 删除（D）对象文件 | **8 个** |
| Backend 重写（R）对象文件 | **1 个**（`routers/tools.py` `test_mcp_connection`） |
| Backend 新增（N）文件 | **1 个**（`alembic/versions/m13_drop_mcp_legacy.py`） |
| Frontend 删除（D）对象文件 | **2 个**（`mcp-server-rename-dialog.tsx` 整体删除 + mcp 引用 cleanup） |
| Frontend 新增（N）文件 | **1 个**（`binding-dialog-shell.tsx`） |
| `MCPServer`/`mcp_server_id`/`resolve_server_auth` backend grep hit | **57 项 / 9 个文件** |
| 同一 symbol 的 frontend grep hit | **53 项 / 10 个文件** |
| 删除对象 backend test 文件 | **4 个**（`test_connection_mcp_resolve.py` / `test_tools.py` 部分 / `test_tools_router_extended.py` 部分 / `test_connections.py` 引用） |
| 受影响的 alembic head | `m12_drop_legacy_columns` → `m13_drop_mcp_legacy`（新增） |

Grep 实测：
- `rg "mcp_server_id|MCPServer|resolve_server_auth" backend/app/` → **57 hits / 9 files**
- `rg "mcp-server" backend/app/routers/` → **6 hits / 1 file** (`routers/tools.py`)
- `rg "updateMCPServer|useUpdateMCPServer|useRegisterMCPServer|useMCPServers|useDeleteMCPServer|mcp_server_id|MCPServer" frontend/src/` → **53 hits / 10 files**

---

## 1. Backend 删除/重写 matrix

Tag：**D** = Delete, **R** = Rewrite（保留逻辑，替换依赖）, **K** = Keep（M6.1 不包含）

### 1.1 `backend/app/models/tool.py`

| 行 | Symbol | Tag |
|------|------|------|
| L34-57 | 整个 `class MCPServer(Base)` | **D** |
| L72 | `mcp_server_id: Mapped[uuid.UUID \| None] = mapped_column(ForeignKey("mcp_servers.id"))` | **D** |
| L88 | `mcp_server: Mapped[MCPServer \| None] = relationship(back_populates="tools")` | **D** |
| L13 | `from app.models.credential import Credential`（TYPE_CHECKING） | **K**（其他地方可能会用 — 当前只有 MCPServer 使用，所以可 drop，但保持现状也无害） |

### 1.2 `backend/app/models/__init__.py`

| 行 | Symbol | Tag |
|------|------|------|
| L12 | `from app.models.tool import AgentToolLink, MCPServer, Tool` → `AgentToolLink, Tool` | **D**（缩减 import） |
| L23 | `"MCPServer",` export | **D** |

### 1.3 `backend/app/schemas/tool.py`

| 行 | Symbol | Tag |
|------|------|------|
| L34-39 | `class MCPServerCreate` | **D** |
| L47 | `mcp_server_id: uuid.UUID \| None` 字段（ToolResponse） | **D** |
| L62-72 | `class MCPServerResponse` | **D** |
| L83-94 | `class MCPServerListItem` | **D** |
| L97-100 | `class MCPServerUpdate` | **D** |
| L11-17 | `ToolType` enum 本身 — `MCP = "mcp"` **K**（connection_id path 中继续使用） |
| 新增 | `class ToolUpdate(BaseModel)` + `model_config = ConfigDict(extra="forbid")` + `connection_id: uuid.UUID \| None = None` | **N**（M2） |

### 1.4 `backend/app/services/tool_service.py`

| 行 | Symbol | Tag |
|------|------|------|
| L10 | `from app.models.tool import AgentToolLink, MCPServer, Tool` → 删除 `MCPServer` | **D** |
| L11 | `from app.schemas.tool import MCPServerCreate, ToolCustomCreate, ToolType` → 删除 `MCPServerCreate` | **D** |
| L80-120 | `register_mcp_server()` | **D** |
| L123-130 | `get_mcp_servers()` | **D** |
| L133-179 | `list_mcp_server_items()` | **D** |
| L182-194 | `_apply_credential_update()` (private helper for MCPServer) | **D** |
| L197-228 | `update_mcp_server()` | **D** |
| L231-250 | `delete_mcp_server()` | **D** |
| 新增 | `async def update_tool(db, tool_id, user_id, payload: ToolUpdate) -> Tool` | **N**（M2） |

→ **删除 6 类函数**（L80-250 block，~170 行）。新增 1 类。

### 1.5 `backend/app/services/credential_service.py`

| 行 | Symbol | Tag |
|------|------|------|
| L12 | `from app.models.tool import AgentToolLink, MCPServer, Tool` → 删除 `MCPServer` | **D** |
| L112-121 | `def resolve_server_auth(server: MCPServer)` | **D** |
| L164-170 | `mcp_count_result` block + `mcp_server_count` 返回字段（get_usage_count） | **D** — 从返回 dict 中删除 `mcp_server_count` key，需要确认调用处（frontend）联动 |

**Scope note**：`get_usage_count` 的返回 shape 变更会连接到 `schemas/credential.py::CredentialUsage` + frontend `CredentialUsage` 类型字段删除（参见下方 §3.1）。

### 1.6 `backend/app/services/chat_service.py`

| 行 | Symbol | Tag |
|------|------|------|
| L18 | `from app.models.tool import AgentToolLink, MCPServer, Tool` → 删除 `MCPServer` | **D** |
| L26 | `resolve_server_auth,` import | **D** |
| L194-195 | `.selectinload(Tool.mcp_server).selectinload(MCPServer.credential),` prefetch | **D** |
| L384-392 | `elif tool.mcp_server is not None:` fallback 分支（注释写有 "M6.1 中删除"） | **D** |
| L393-394 | `else: cred_auth = {}` branch 只用于 MCP 的 third state — 建议在 connection_id 为空时切换为 fail-closed（参见 R5） | **R** |

**删除 fallback 后预期行为**（chat_service L343-402）：
```python
if tool.type == ToolType.MCP:
    if tool.connection_id is not None and tool.connection is not None:
        # ...（现有 M2+ 路径原样）...
    else:
        # M6.1: fail-closed（无 MCP legacy 路径）
        raise ToolConfigError(
            f"MCP tool '{tool.name}' has no connection — execution blocked."
        )
```
与 CUSTOM path 一致。删除 L394 的现有 `else: cred_auth = {}`，替换为 `ToolConfigError`。

### 1.7 `backend/app/schemas/connection.py`

| 行 | Symbol | Tag |
|------|------|------|
| L125 | `resolve_server_auth` 曾将 credential 全部作为 auth 返回` 注释 | **K**（保留 docstring context，如有需要仅整理术语） |
| L186 | `MCPServerResponse` 的 `auth_config` 全量 redaction policy 与之相符` 注释 | **D**（从注释删除 `MCPServerResponse` 引用） |

### 1.8 `backend/app/routers/tools.py`

| 行 | Symbol | Tag |
|------|------|------|
| L11-14 | `MCPServerCreate, MCPServerListItem, MCPServerResponse, MCPServerUpdate` import | **D** |
| L48-54 | `POST /mcp-server` (register) | **D** |
| L57-62 | `GET /mcp-servers` (list) | **D** |
| L65-76 | `PATCH /mcp-servers/{server_id}` | **D** |
| L79-87 | `DELETE /mcp-servers/{server_id}` | **D** |
| L90-111 | `POST /mcp-server/{server_id}/test`（test_mcp_connection） | **R**（参见 §2 重写规范） |
| L9 | `from app.error_codes import mcp_server_not_found, tool_not_found` | **D** 删除 `mcp_server_not_found` |
| 新增 | `PATCH /api/tools/{tool_id}`（ToolUpdate → tool_service.update_tool） | **N**（M2） |

→ **完整删除 4 个 route + 重写 1 个 + 新建 1 个**。整理 router 顺序时保持 `DELETE /{tool_id}`（L114）位于最后（FastAPI path 优先级）。

### 1.9 `backend/app/error_codes.py`

| Symbol | Tag |
|------|------|
| `mcp_server_not_found()` factory 函数 | **D**（M3 中完整删除） |

### 1.10 `backend/app/agent_runtime/tool_factory.py` / `executor.py`

| Symbol | Tag |
|------|------|
| `executor.py` L263-267, L401（`mcp_server_url`, `mcp_tool_name`, `mcp_transport_headers` key） | **K**（这些 key 由 `chat_service.build_tools_config` 填充，并在 **connection 路径**继续使用。不是删除对象） |

→ runtime 已经经由 `connection.extra_config`。无需修改。

### 1.11 `backend/app/main.py` / `services/legacy_invariants.py`

| Symbol | Tag |
|------|------|
| `_enforce_m6_legacy_invariants` startup guard | **N** 扩展（新增 m13 preflight） |
| `legacy_invariants.py` | **N**（新增 m13 helper：`assert_no_dangling_mcp_server_refs`） |

---

## 2. `test_mcp_connection` 重写规范（R tag）

### 2.1 当前（routers/tools.py L90-111）

```python
@router.post("/mcp-server/{server_id}/test")
async def test_mcp_connection(server_id: uuid.UUID, db, user):
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id, MCPServer.user_id == user.id)
    )
    server = result.scalar_one_or_none()
    if not server: raise mcp_server_not_found()
    effective_auth = resolve_server_auth(server)      # credential 优先 → auth_config fallback
    test_result = await mcp_test(server.url, effective_auth)
    return test_result
```

### 2.2 建议（新 route — 经由 connection）

**Route 路径**：`POST /api/connections/{connection_id}/test`（移到 connection router — router scope 重排）

或者为保持 scope，继续使用 `POST /api/tools/{tool_id}/test`（tool → connection chain）。**推荐后者** — URL 变更最小 + 仅在 `tool.type='mcp'` 时允许。

伪代码：
```python
from app.agent_runtime.mcp_client import test_mcp_connection as mcp_test
from app.models.connection import Connection
from app.services.credential_service import resolve_credential_data
from app.services.env_var_resolver import resolve_env_vars

@router.post("/{tool_id}/test")
async def test_tool_connection(tool_id: uuid.UUID, db, user):
    tool = await db.get(Tool, tool_id, options=[
        selectinload(Tool.connection).selectinload(Connection.credential)
    ])
    if not tool or tool.user_id != user.id:
        raise tool_not_found()
    if tool.type != ToolType.MCP or tool.connection is None:
        raise HTTPException(400, "Only MCP tools with a bound connection can be tested")

    conn = tool.connection
    extra = conn.extra_config or {}
    url = extra.get("url")
    if not url:
        raise HTTPException(422, "connection.extra_config.url is missing")

    effective_auth = resolve_env_vars(
        extra.get("env_vars"), conn.credential,
        context={"connection_id": str(conn.id), "tool_name": tool.name},
    )
    return await mcp_test(url, effective_auth)
```

**要点**：
- `resolve_server_auth` 替代 = `resolve_env_vars(extra.env_vars, conn.credential, context=…)`（与现有 `chat_service.build_tools_config` L369-376 path 相同）
- transport headers 只在 runtime 中需要，test 不需要 → 省略
- 认证/IDOR：检查 `tool.user_id == user.id`。connection ownership 在 tool 创建阶段已经保证（L57-58 validate_connection_for_custom_tool — MCP 在 M5.5 前创建 tool 时也经由 connection，因此保守起见建议再次确认 `conn.user_id == user.id`）

### 2.3 Frontend API client 影响

`frontend/src/lib/api/tools.ts::testMCPConnection(serverId)` → 参数语义改为 `testMCPConnection(toolId)`。
- 若调用处（`rg "testMCPConnection" frontend/src/`）为 0 项（未使用函数），则直接删除。
- **纳入 M5 Zuckerberg scope**："全面确认 testMCPConnection 调用处后清理，或重写为 tool-id based"。

---

## 3. Frontend 删除/重写 matrix

### 3.1 `frontend/src/lib/types/index.ts`

| 行 | Symbol | Tag |
|------|------|------|
| L210-213 | `CredentialUsage { tool_count, mcp_server_count }` → `mcp_server_count` 字段 | **D** |
| L220 | `Tool.mcp_server_id: string \| null` | **D** |
| L316-324 | `interface MCPServer` | **D** |
| L332-342 | `interface MCPServerListItem` | **D** |
| L344-348 | `interface MCPServerUpdateRequest` | **D** |
| L360-366 | `interface MCPServerCreateRequest` | **D** |
| 新增 | `interface ToolUpdateRequest { connection_id?: string \| null }` | **N**（M4） |

### 3.2 `frontend/src/lib/api/tools.ts`

| 行 | Symbol | Tag |
|------|------|------|
| L4-8 | `MCPServer, MCPServerListItem, MCPServerUpdateRequest, MCPServerCreateRequest` import | **D** |
| L15-19 | `registerMCPServer` | **D** (M5) |
| L20-24 | `testMCPConnection` | **R** (§2.3) |
| L26 | `listMCPServers` | **D** (M5) |
| L27-31 | `updateMCPServer` | **D** (M5) |
| L32-33 | `deleteMCPServer` | **D** (M5) |
| 新增 | `update: (id, { connection_id }) => apiFetch<Tool>(`/api/tools/${id}`, { method: 'PATCH', body: JSON.stringify({ connection_id }) })` | **N**（M4） |

### 3.3 `frontend/src/lib/hooks/use-tools.ts`

| 行 | Symbol | Tag |
|------|------|------|
| L13-14 | `MCPServerCreateRequest, MCPServerUpdateRequest` import | **D** |
| L22-25 | `invalidateMCPAndTools` helper | **D** (M5) |
| L39-45 | `useRegisterMCPServer` | **D** (M5) |
| L55-61 | `useMCPServers` | **D** (M5) |
| L71-95 | `useToolsByConnection` — MCP 分支（L76-84） | **R**（M5）：删除基于 `mcp_servers` 的双重 hop 后，缩减为 `tool.connection_id` 单一匹配。**PREBUILT/CUSTOM 逻辑原样保留。** |
| L97-106 | `useUpdateMCPServer` | **D** (M5) |
| L108-114 | `useDeleteMCPServer` | **D** (M5) |
| 新增 | `export function useUpdateTool()` — `mutationFn: ({ id, data }) => toolsApi.update(id, data)`, `onSuccess: invalidate(['tools']) + invalidate(['agents'])` | **N**（M4） |

**再次确认 `useUpdateTool` 命名冲突**：当前文件中不存在 `useUpdateTool`（grep 确认）。只存在 `useCreateCustomTool`, `useDeleteTool`, `useRegisterMCPServer`, `useUpdateMCPServer` 等。无冲突 → 可使用该名称。

### 3.4 `frontend/src/components/connection/connection-binding-dialog.tsx`

公共 — 参见 §4 BindingDialogShell 提取。

| 行 | Symbol | Tag |
|------|------|------|
| L36 | `import { useUpdateMCPServer } from '@/lib/hooks/use-tools'` | **D** (M5) |
| L78-86 | `McpProps` 类型（mcpServerId） | **R**（M5）— 改为基于 `connectionId: string` or 保留后在内部通过 connection 查询转换 |
| L339 | `const needsOptionDFirstBind = !!tool && !tool.connection_id` | **D** (M4) |
| L340 | `const saveDisabled = isPending \|\| needsOptionDFirstBind` → 仅 `isPending` | **R**（M4） |
| L343-346 | `if (needsOptionDFirstBind) { toast.error(...); return }` | **D** (M4) |
| L421-429 | `needsOptionDFirstBind` alert block | **D**（M4） |
| L362-365 | CustomBody `findOrCreate.run(credentialId, ...)` — 启用 first-bind 时新增 `useUpdateTool({ id: tool.id, data: { connection_id: result.id } })` chain | **N**（M4） |
| L456-516 | 整个 McpBody — 删除 `useUpdateMCPServer` + 重新接线为 `useUpdateConnection`（更新 extra_config）+ `useUpdateTool`（connection_id rebind） | **R**（M5） |
| L469, L496 | `const updateServer = useUpdateMCPServer()` / `updateServer.mutateAsync(...)` | **D** (M5) |

### 3.5 `frontend/src/components/tool/mcp-server-rename-dialog.tsx`

**文件存在与否**：✅ 存在（约 L1-40 的文件）。已通过 `ls` 结果确认。

| 行 | Symbol | Tag |
|------|------|------|
| 整个文件 | `MCPServerRenameDialog` | **D**（M5 — 删除文件） |

**替代 UX**：connection rename 替换为 `/connections` 页面的一般 PATCH。`frontend/src/components/connection/` 中已经存在基于 `useUpdateConnection` 的 rename dialog（M5 UI 整合）。

### 3.6 `frontend/src/components/tool/mcp-server-group-card.tsx`

| 行 | Symbol | Tag |
|------|------|------|
| L29 | `import { MCPServerRenameDialog }` | **D** (M5) |
| L30 | `import { useDeleteMCPServer }` | **D** (M5) |
| L46 | `const deleteServer = useDeleteMCPServer()` | **R**（M5）— 需要决定替代路径。选项：（a）删除 MCP server 删除 UI 本身（tools 页面的 group card 变得 redundant → 删除整个 render 分支）（b）替换为基于 connection |
| L143-151 | `<ConnectionBindingDialog type="mcp" mcpServerId={...} triggerContext="tool-edit" ... />` | **R**（M5）— prop 从 `mcpServerId` 改为 `connectionId` 后连接 |
| L152 | `<MCPServerRenameDialog server={server} ... />` | **D** (M5) |

**注意**：`tools/page.tsx` L379 的 `useMCPServers()` 调用 + L472-480 的基于 `mcp_server_id` grouping 逻辑（L472：`if (tl.type !== 'mcp' \|\| !tl.mcp_server_id) continue`）需要在 M5 中改为 connection-based。**Scope 再确认**："现有 UX 原样保留"（可能与 scope creep 警告 §5 冲突）→ Zuckerberg 应优先**保持 UX = tools 页面的 MCP group section**，仅将 grouping key 从 `mcp_server_id` → `connection_id`，采取 minimal rewrite 方针。

### 3.7 `frontend/src/app/tools/page.tsx`

| 行 | Symbol | Tag |
|------|------|------|
| L20 | `import { useTools, useDeleteTool, useMCPServers }` → 删除 `useMCPServers` | **R**（M5） |
| L31 | `import { MCPServerGroupCard }` | **K 或 R**（若保留 group card） |
| L40 | `import type { MCPServerListItem, Tool }` | **R** (M5) |
| L379 | `const { data: mcpServers } = useMCPServers()` | **R** (M5) → `useConnections({ type: 'mcp' })` |
| L472-480 | 基于 `mcp_server_id` 的 grouping | **R**（M5）→ `tool.connection_id` |
| L481-495 | `filteredMCPServers` → `filteredMcpConnections` | **R** (M5) |
| L524, L631-642 | render block | **R**（M5） |

→ M5 的 **R 工作密度高于预期**。需要重新估算 Zuckerberg 工作量（§6 警告）。

### 3.8 i18n (messages)

删除 `t('toast.unsupportedFirstBindM6')` / `t('custom.unsupportedFirstBindM6')` key。
- grep hit 2 项（connection-binding-dialog.tsx L344, L427）
- messages 文件（`frontend/messages/*.json`）中也需要删除相应 key — 包含在 M4 scope。

---

## 4. BindingDialogShell 提取分析

### 4.1 PrebuiltBody / CustomBody / McpBody 公共模式

| 模式 | PrebuiltBody | CustomBody | McpBody |
|------|:---:|:---:|:---:|
| `useCredentials()` | L137 | L307 | L467 |
| `useQueryClient` | L132 | L306 | ❌（无 conflict invalidate） |
| `useConnections({ type, provider_name })` | L133-136 | L308-311 | L468（仅 type='mcp'） |
| `const [createOpen, setCreateOpen] = useState(false)` | L140 | L314 | L471 |
| hydration 模式（hydrationKey + hydratedFor + setMode） | L153-161 | L323-331 | ❌（L472 简单初始化） |
| `isPending` | L170 | L334 | L518 |
| `handleSave()` (async, try/catch, 409 handling, toast) | L182-226 | L342-381 | L490-516 |
| `DialogHeader / DialogTitle / DialogDescription` | L230-239 | L387-393 | L522-528 |
| Credential section (label + Skeleton + CredentialSelect + configured badge) | L241-264 | L395-418 | L530-559 |
| `DialogFooter` (Cancel/Save) | L267-277 | L431-441 | L562-572 |
| `<CredentialFormDialog open/onOpenChange/onCreated/>` | L279-286 | L443-447 | L574-578 |

### 4.2 公共 Shell 的建议 signature

```ts
interface BindingDialogShellProps {
  title: ReactNode
  description: ReactNode
  credentials: Credential[]
  connectionsLoading?: boolean
  mode: string
  onModeChange: (v: string) => void
  onCreateRequested: () => void
  onSave: () => void | Promise<void>
  onCancel: () => void
  isPending: boolean
  saveDisabled?: boolean
  children?: ReactNode           // body-specific 元素，如 alert block
  createDialogProps: { open; onOpenChange; defaultProvider?; onCreated }
  configuredBadge?: boolean      // 默认 true — MCP 也采用相同模式
}
```

### 4.3 各 body 的独有逻辑（无法提取）

| Body | 独有逻辑 |
|------|-----------|
| PrebuiltBody | `targetConnection`（explicit vs default）+ `shouldCreateNew` 分支 + create/update branch + `onSaved` 向后兼容回调 |
| CustomBody | `currentConnection` 解析 + `findOrCreate.run()` +（M4 之后）`useUpdateTool` chain + first-bind guard alert |
| McpBody | `linkedConnections` / `sharedAcrossServers` 计算 + 双重 PATCH（server + connection） |

→ **Shell 提取可行**。各 body 可缩减到约 50 行。**hydration 模式只在 Prebuilt/Custom 中使用** — 可作为可选项内置到 Shell，或由 body 自己拥有。前者抽象成本高，因此**推荐后者**（body 计算 hydrationKey 后只把 mode state 传给 Shell）。

### 4.4 提取策略建议

**M5 最小 scope**：
1. Shell 只迁移 **UI chrome**（Dialog, Header, Footer, Credential section, configured badge, CredentialFormDialog）
2. hydration / save 逻辑由各 body 自己拥有
3. `ConnectionBindingDialog` dispatcher 原样保留

→ 回归风险最低 + 删除约 80 行代码重复。

---

## 5. Scope Creep 警告（Zuckerberg/Jensen 注意事项）

以下范围**不属于 M6.1 scope**。不要触碰：

### 5.1 `agent_tools.connection_id` override (M5.5)
- 禁止给 `backend/app/models/tool.py::AgentToolLink` 增加 `connection_id` 列
- 禁止给 `AgentToolLink` 增加新 FK
- 未经 PO（Satya）批准，连 M5.5 prototype 也不要做

### 5.2 禁止扩展 PATCH /api/tools/{id} 字段
- `ToolUpdate` **只有 `connection_id` 一个字段**
- 禁止新增 `name`, `description`, `parameters_schema`, `provider_name`, `is_system`, `tags` 等任何字段
- Pydantic 必须设置 `extra="forbid"`（测试中验证 `unknown_field`）

### 5.3 禁止 UI redesign
- 禁止修改 `/connections` 页面 card layout
- `/tools` 页面 MCP group section UX 保持不变（仅将 grouping key 从 `mcp_server_id` → `connection_id`，card structure/toolbar/i18n label 保持原样）
- 提取 BindingDialogShell 是 **refactoring，不是 redesign** — 保持 pixel 一致性

### 5.4 不要触碰 PREBUILT PATCH 400 原则
- `PATCH /api/tools/{id}` 只允许 `tool.type in ('custom','mcp')`
- 禁止尝试在 `is_system=True` 的 PREBUILT row 中植入 `connection_id` — 违反 ADR-008 §3。PREBUILT 继续保持 `(user_id, provider_name)` SOT

### 5.5 限定测试清理范围
- `backend/tests/test_connection_mcp_resolve.py` 是 MCP connection path regression test — **禁止 drop**。确认其中的 "mcp_server" 引用（39 项）是否只出现在 comment/docstring 后保持结构
- `backend/tests/test_tools.py`（32 hits）只删除 MCPServer CRUD test section，保留 CUSTOM tool test
- `backend/tests/test_tools_router_extended.py`（10 hits）只删除 MCP router case
- `backend/tests/integration/test_m9_pg_roundtrip.py`（5 hits）是 m9 migration round-trip — **M6.1 中不要触碰**（m9 已 released/applied）

---

## 6. 按文件 Delta 摘要（用于 review）

### Backend
| 文件 | 删除行（估算） | 新增行（估算） | net |
|------|:---:|:---:|:---:|
| `alembic/versions/m13_drop_mcp_legacy.py` | — | +80 | **+80**（新增） |
| `models/tool.py` | -28 | 0 | **-28** |
| `models/__init__.py` | -2 | 0 | **-2** |
| `schemas/tool.py` | -35 | +8 (ToolUpdate) | **-27** |
| `services/tool_service.py` | -170 | +35 (update_tool) | **-135** |
| `services/credential_service.py` | -16 | 0 | **-16** |
| `services/chat_service.py` | -15 | +3 (fail-closed raise) | **-12** |
| `services/legacy_invariants.py` | 0 | +20 (m13 preflight) | **+20** |
| `routers/tools.py` | -65 | +30（PATCH + test 重写） | **-35** |
| `main.py` | 0 | +3 | **+3** |
| `error_codes.py` | -5 | 0 | **-5** |
| `tests/*` | -200（估算） | +80（PATCH tool, MCP connection test） | **-120** |
| **合计** | **~-536** | **~+259** | **~-277 LOC** |

### Frontend
| 文件 | 删除行（估算） | 新增行（估算） | net |
|------|:---:|:---:|:---:|
| `lib/types/index.ts` | -40 | +5 (ToolUpdateRequest) | **-35** |
| `lib/api/tools.ts` | -18 | +6 (update) | **-12** |
| `lib/hooks/use-tools.ts` | -50 | +15 (useUpdateTool) | **-35** |
| `components/connection/connection-binding-dialog.tsx` | -80（McpBody 重构 + needsOptionDFirstBind） | +40 | **-40** |
| `components/connection/binding-dialog-shell.tsx` | — | +120 | **+120**（新增） |
| `components/tool/mcp-server-rename-dialog.tsx` | -40 | 0 | **-40**（删除文件） |
| `components/tool/mcp-server-group-card.tsx` | -10 | +5 | **-5** |
| `app/tools/page.tsx` | -15 | +15 | **~0**（替换 grouping key） |
| `messages/*.json` | -2 keys | 0 | **-2** |
| **合计** | **~-255** | **~+206** | **~-49 LOC** |

→ **整个 repository 净减少 ~-326 LOC**。规模足以在 single PR 中 review。按计划 §"工作顺序建议" 的推荐，可保持单一 PR。

---

## 7. 1-way door 决定事项（不可逆）

| 决定 | 风险度 | 缓解 |
|------|:---:|------|
| drop `mcp_servers` 表 | 🔴 High（1-way door） | ① 用 pre-check SQL 确认 dead refs = 0 ② alembic round-trip（docker PG）③ `SELECT to_regclass('mcp_servers')` 确认 NULL 后 PR merge |
| drop `tools.mcp_server_id` FK + 列 | 🔴 High（1-way door） | ① 按 m12 precedent 用 `\d tools` 实测 FK 名称 ② pre-check：`COUNT(*) WHERE mcp_server_id IS NOT NULL AND connection_id IS NULL = 0` |
| 删除 `resolve_server_auth` | 🟢 Low（2-way door） | 可 git revert |
| 新建 PATCH /api/tools/{id} | 🟢 Low（2-way door） | 用 schema `extra="forbid"` 防止误用。后续扩展字段时需明确批准 |
| 删除 `MCPServer` model/schema | 🔴 Medium-High | 代码删除可 revert，但与 DB drop paired — 与 drop 保持一致性 |

---

## 8. Verification Checklist（M6 整合验证前置）

贝索斯将在 M6 中执行的最终验证 — M2~M5 完成后：

```bash
cd backend
uv run ruff check .                                  # PASS
uv run pytest                                        # 0 regression (baseline 624)
uv run alembic upgrade head                          # 应用 m13
uv run alembic downgrade -1 && uv run alembic upgrade head  # round-trip

# 残留 grep — 必须为 0
rg "mcp_server_id|MCPServer|resolve_server_auth|mcp-server" backend/app/
rg "mcp_server_id|MCPServer|resolve_server_auth" backend/tests/ | grep -v "m9"  # 保留 m9 round-trip

cd ../frontend
pnpm lint
pnpm build

# 残留 — 必须为 0
rg "mcp_server_id|MCPServer|updateMCPServer|useUpdateMCPServer|useMCPServers|useDeleteMCPServer|useRegisterMCPServer|mcp-server-rename" frontend/src/

# Production pre-check（执行 m13 前）
psql $DB_URL -c "SELECT COUNT(*) FROM tools WHERE mcp_server_id IS NOT NULL AND connection_id IS NULL;"
# 预期：0

# 部署后
psql $DB_URL -c "\d tools"                           # 无 mcp_server_id
psql $DB_URL -c "SELECT to_regclass('mcp_servers');" # NULL
```

---

## 9. 最终判定：🟢 GREEN

### 依据
1. **删除对象已确定到 file:line** — 57 个 backend + 53 个 frontend grep hit 全部在上方 matrix 化。
2. **已建立 `test_mcp_connection` 重写路径** — 复用 `chat_service` L369-376 的 `resolve_env_vars(extra.env_vars, conn.credential, ...)` 模式。无新依赖。
3. **`useUpdateTool` 无命名冲突** — 通过 grep 全面确认现有 hook。
4. **BindingDialogShell 提取可行** — 只迁移 UI chrome + hydration 由 body 拥有策略。不是 redesign，而是纯 refactoring。
5. **1-way door 风险已通过 m12 precedent 缓解** — pre-check SQL、round-trip、FK 实测指南全部建立。
6. **Scope creep flag 4 项**已在 §5 明文化 → Jensen/Zuckerberg guard 完成。

### 无需 Satya 确认即可开始 M2/M4 的原因
- M2（backend Option D）：`ToolUpdate` schema + 单一 service 函数 + 单一 route — spec 已在 CHECKPOINT L43-54 完整明确。无新决策点。
- M4（frontend Option D）：`useUpdateTool` + 删除 CustomBody first-bind guard — 命名已确定，UI 无变化。

### 转为 YELLOW/RED 的条件
- ⚠️ **YELLOW trigger**：如果确认 `credential_service.get_usage_count` 返回 shape 变更（删除 `mcp_server_count` 字段）会影响现有 `/connections` 页面 card count UX — 需要协商 frontend 字段删除/fallback。**→ 当前建议在 M3 开始前 grep 确认 frontend 中使用 `CredentialUsage` 的位置**
- 🚫 **RED trigger**：如果 production `SELECT COUNT(*) WHERE mcp_server_id IS NOT NULL AND connection_id IS NULL > 0` — 需要重新运行 m9 migration。目前为 PoC 阶段 / local docker 环境，可能性较低。

---

## 10. M2/M4 开始前需要传达给 Jensen/Zuckerberg 的核心信息

### Jensen（M2）
- `ToolUpdate` 位置：添加到 `backend/app/schemas/tool.py` 底部（`class ToolUpdate(BaseModel): model_config = ConfigDict(extra="forbid"); connection_id: uuid.UUID | None = None`）
- `update_tool` 位置：放在 `backend/app/services/tool_service.py::delete_tool` 上方（L252 附近）
- PATCH router：在 `routers/tools.py` L114 的 `DELETE /{tool_id}` 正上方（L113）增加 `PATCH /{tool_id}` — FastAPI path 优先级下 `/mcp-server/*` 仍存在，因此无冲突（M3 删除 `/mcp-server*` 后也无影响）
- 验证 case（参见 CHECKPOINT L51）：正常 / 别人的 connection 404 / 类型不匹配 422 / PREBUILT 400 / 允许 None / 系统工具 MCP / 用 `extra="forbid"` 让 unknown_field 422

### Zuckerberg（M4）
- `useUpdateTool` 添加位置：`frontend/src/lib/hooks/use-tools.ts::useDeleteTool` 下方（L53 附近）
- invalidate key：`['tools']` + `['agents']`（因为 agent tool_links 包含 tool.connection_id）
- 删除 CustomBody guard：connection-binding-dialog.tsx L339-346, L421-429 — 但 `findOrCreate.run()` 调用成功后，需要新增 `toolsApi.update(tool.id, { connection_id: result.id })` chain
- first-bind 流程：`tool.connection_id IS NULL` 状态下选择 credential → `findOrCreate`（创建 connection）→ `useUpdateTool`（绑定 tool.connection_id）→ invalidate → toast
- 删除 i18n key：`toast.unsupportedFirstBindM6`, `custom.unsupportedFirstBindM6`（messages/ko.json + en.json 等所有语言文件）

---

**报告结束** — 贝索斯，2026-04-24
