# M5 — ConnectionBindingDialog UX spec

**Owner**: Tim Cook (Tim Cook)
**Related**: ADR-008 §3, exec-plan §4 M5 · S3
**Status**: Draft for Zuckerberg 实现 (S3)
**Scope**: 仅 frontend。将 3 个认证 dialog(PREBUILT / CUSTOM / MCP) 收敛为**单一 shell**。

---

## 1. 背景与目标

### 1.0 本 spec 是**扩展现有 shell**的工作 (并非新建)

M3 中已存在 **PREBUILT 专用**的 `frontend/src/components/connection/connection-binding-dialog.tsx` (237 行)。M4 中已替换为由 `PrebuiltAuthDialog` thin-wrap 此 shell。**M5 的工作是将现有 shell 扩展为 `type` discriminated union，并添加 CUSTOM/MCP 分支**，不创建新文件。

因此 spec §2 的 Props 契约必须**向后兼容现有 shell 的 props**:

- 现有 prop: `type: 'prebuilt'`, `providerName: PrebuiltProviderName`, `toolName?`, `open`, `onOpenChange`, `onSaved?(connection)`
- 新增 prop: `triggerContext`, `currentConnectionId?`，以及扩展类型声明中的 `type` literal union
- 保留现有 `onSaved`，并将 `onBound` 作为 **alias** 添加 (相同 signature)。截至 M4 的 PREBUILT 调用方(`/connections` PREBUILT 卡片)必须无需更改 prop 即可运行。

### 1.1 当前 (截至 M4)

| Dialog | 文件 | 保存路径 | 状态 |
|---|---|---|---|
| PREBUILT | `components/tool/prebuilt-auth-dialog.tsx` | M4 已完成以 `ConnectionBindingDialog(type='prebuilt')` 形式 thin wrapper 化 | ✅ wrapper |
| CUSTOM | `components/tool/custom-auth-dialog.tsx` | `useUpdateToolAuthConfig` → `tool.credential_id` | ❌ legacy |
| MCP | `components/tool/mcp-server-auth-dialog.tsx` | `useUpdateMCPServer` → `mcp_servers.credential_id` | ❌ legacy |
| `add-tool-dialog.tsx` · Custom tab | inline 实现 | 基于 M4 find-or-create 流程的 Connection | ✅ 部分 |
| `add-tool-dialog.tsx` · MCP tab | inline 实现 | `useRegisterMCPServer` (直接使用 credential_id) | ❌ legacy |

### 1.2 目标 (M5)

由 1 个 **ConnectionBindingDialog** 文件处理 PREBUILT / CUSTOM / MCP 三种 `type`。现有 3 个 dialog 全部删除或变为 thin wrapper (是否删除依据 S1 Bezos 结果)。

设计原则 (Tim Cook):
1. **Simplicity** — 公共 surface(header/body/footer) + 仅按 `type` 分支 section。形成**一个一致的体验**，而非 3 套 UI。
2. **Minimal Steps** — “已有连接就选择，没有就创建”两条路径都在两次点击以内。
3. **Accessibility by Default** — 在 spec 中明确 focus trap、ESC、role=alert。
4. **Explicit Feedback** — 每次状态转换(查询/保存/成功/失败)都提供**视觉信号 + screen reader 提示**。

---

## 2. Props 契约

```ts
interface ConnectionBindingDialogProps {
  /** 当前是否打开 */
  open: boolean
  onOpenChange: (open: boolean) => void

  /** 要绑定的 Connection 类型 */
  type: 'prebuilt' | 'custom' | 'mcp'

  /**
   * provider_name。PREBUILT 必填且固定(PrebuiltProviderName)，
   * CUSTOM 始终固定为 'custom_api_key'，
   * MCP 为 optional (用户定义新 server 时由 body 的 name 派生)。
   */
  providerName?: string

  /**
   * Dialog 进入上下文。i18n copy/CTA label/完成行为会随之不同。
   *   - 'tool-create'     : 在 AddToolDialog 内部 (MCP tab)调用 — 完成后继续注册 tool
   *   - 'tool-edit'       : 在 Agent tool tab / tools/page 中调用 — 修改已有 tool 的 credential
   *   - 'standalone'      : 在 /connections 页面调用 — 单纯执行 Connection CRUD
   */
  triggerContext: 'tool-create' | 'tool-edit' | 'standalone'

  /**
   * 仅在 tool-edit 上下文中有意义。名称显示在 header title·description 中。
   * PREBUILT 时使用 provider 韩文 label 作为 fallback。
   */
  toolName?: string

  /**
   * 仅在 tool-edit 上下文中有意义。hydrate CUSTOM/MCP 的“当前 bound connection”。
   * 若为 undefined，则查找 default connection 并 hydrate。
   */
  currentConnectionId?: string

  /**
   * 保存成功后的 callback。各 type 的 payload shape 不同 (discriminated result)。
   *
   * - type='prebuilt' | 'custom'  → { kind: 'connection', connection }
   * - type='mcp'                  → { kind: 'mcp-credential', serverId, credentialId }
   *   (M5 仅执行 mcp_servers.credential_id PATCH。Connection 实体迁移在 M6。)
   *
   * 调用方用此 payload 决定下一步动作(tool POST / refetch / close)。
   */
  onBound?: (result: ConnectionBindingResult) => void

  /**
   * 向后兼容 alias。现有 PREBUILT 调用方(M4)继续使用 `onSaved(connection)`，
   * 因此仅对 `type='prebuilt' | 'custom'` 保留以单个 Connection 参数调用的
   * 旧式 callback。若提供 `onBound`，则忽略 `onSaved`。
   */
  onSaved?: (connection: Connection) => void

  /**
   * MCP 专用。在 `type='mcp'` + `triggerContext='tool-edit'` 中必填 —
   * 编辑目标 mcp_server row 的 id。作为 PATCH target。
   * 本 spec **不支持** standalone MCP “添加连接” (§4.3 参见)。
   */
  mcpServerId?: string
}

type ConnectionBindingResult =
  | { kind: 'connection'; connection: Connection }
  | { kind: 'mcp-credential'; serverId: string; credentialId: string | null }
```

**设计备注**
- PREBUILT 模式下 `providerName` 必须为 `PrebuiltProviderName` narrow 类型(Zuckerberg: 在 TS 层同时使用 runtime guard + 条件类型)。
- **保存行为不由调用方选择。** dialog 内部完成 Connection upsert 后，将结果通过 `onBound` 传出。调用方只负责“下一步做什么” (tool POST / PATCH / close)。
- `open`/`onOpenChange` 禁止 uncontrolled 模式。**始终 controlled** — 状态控制权在调用方。

---

## 3. 状态机

```
          ┌──────────┐
          │   idle   │  (open=false)
          └────┬─────┘
        open=true │
          ┌──────▼──────────┐
          │    loading      │  useConnections({type, provider_name}) 进行中
          │  (skeleton UI)  │  useCredentials 也并行查询
          └──────┬──────────┘
                 │ load done
        ┌────────┴────────┐
        │                 │
┌───────▼─────────┐  ┌────▼────────────────┐
│ connection_     │  │  credential_form    │  (no connection yet OR user chose "新建")
│ select          │  │  (inline sub-panel) │
│ (default + list)│  └────────┬────────────┘
└───────┬─────────┘           │ credential 已保存
        │ 保存                │
        └────────┬────────────┘
                 │
          ┌──────▼──────┐
          │   binding   │  createConnection / updateConnection 进行中
          │  (spinner)  │
          └──────┬──────┘
        ┌────────┴────────┐
   成功 │                 │ 失败
┌──────▼─────┐      ┌─────▼──────────────┐
│  success   │      │      error         │
│ toast→onBound│     │ role=alert inline  │
│ dialog close │     │ + retry available  │
└────────────┘      └────────────────────┘
```

### 转换规则

| 转换 | trigger | 备注 |
|---|---|---|
| idle → loading | `open=true` | PREBUILT/CUSTOM/MCP 全部查询连接列表 |
| loading → connection_select | 现有 active connection ≥1 个 | 有 default 时 hydrate 为对应选择状态 |
| loading → credential_form (skip) | 现有连接 0 个 AND PREBUILT | “直接新建” — 跳过中间选择页面 |
| connection_select → credential_form | 用户点击“新建连接” | 打开 inline panel (禁止新 dialog — 避免 nested dialog) |
| credential_form → binding | 用户保存 Credential | 创建 Credential → 自动 trigger Connection upsert |
| binding → success | 2xx | `toast.success` + `onBound(connection)` + dialog close |
| binding → error | 4xx/5xx | 409 立即 `invalidateQueries` + “重试” toast，其余为 inline `role=alert` |

### 409 竞争处理

与 M3/M4 相同:
1. invalidate `['connections', type, providerName]` scope + 整体 `['connections']` prefix。
2. 通过 `role=alert` 渲染“默认连接已在其他 session 中被更改。请基于最新状态重试。”。
3. Dialog **保持打开** — 用户查看最新列表后重新选择。

---

## 4. 按 Type 分支

公共 shell 包含 DialogHeader · DialogBody · DialogFooter 三个 section。仅正文按 `type` 不同。

### 4.1 PREBUILT (`type='prebuilt'`)

**保持** M4 已实现的流程。M5 的核心是“将 CUSTOM/MCP 也吸收到该 shell”，因此 PREBUILT section 的代码与 UX 均禁止回归。

```
┌─ DialogHeader ─────────────────────────────────┐
│ [KeyIcon] {toolName ?? t('provider.<key>')} 连接 │
│ 选择此工具要使用的 credential。           │
└─────────────────────────────────────────────────┘
┌─ DialogBody ───────────────────────────────────┐
│ [LinkIcon] 连接 (label)                          │
│ ┌───────────────────────────────────────────┐   │
│ │ CredentialSelect                          │   │
│ │  · 无认证 / 现有 credentials / 新建 │   │
│ └───────────────────────────────────────────┘   │
│                                                 │
│ (已选择) [CheckIcon] 已设置连接       │
└─────────────────────────────────────────────────┘
┌─ DialogFooter ─────────────────────────────────┐
│               [取消]  [保存]                      │
└─────────────────────────────────────────────────┘
```

**按条件的 UX**
- 使用 `provider_name` 作为 filter key，对 `useCredentials()` 结果进行 narrow → 不显示其他 provider 的 credential (防止 M3 回归)。
- “新建”通过 nested 方式打开 `CredentialFormDialog`，并以 `defaultProvider={providerName}` 固定 provider。

### 4.2 CUSTOM (`type='custom'`, providerName='custom_api_key')

将 M4 `add-tool-dialog` 的 custom tab 逻辑(find-or-create)**吸收到 shell 内部**。

#### 4.2.a Bridge override 保留策略 (M5 决策)

M4 中用户创建的 CUSTOM tool 可能存在 `tool.credential_id != connection.credential_id` 的“bridge override” row (`add-tool-dialog.tsx:153-160` 注释参见)。**M5 保留该 row**。决策依据与 PATCH 方向:

| 状态 | 当前值 | 保存时 PATCH 方向 |
|---|---|---|
| 正常 | `tool.credential_id == connection.credential_id` | 仅 PATCH `connection.credential_id` (`PATCH /api/connections/{id}`)。不修改 `tool.credential_id`。由 server 自动 derive。 |
| Bridge override | `tool.credential_id != connection.credential_id` | 默认保存时也**不修改 `tool.credential_id`**，仅 PATCH `connection.credential_id`。即 override 状态保持到 M6。 |

UI 上打破 override 的路径仅在用户明确选择时提供:

- 在 tool-edit 上下文进入时若检测到 `tool.credential_id != connection.credential_id`，在 DialogBody 顶部显示 **inline 警告 banner** + **“恢复为公共 connection”按钮** (可选)。仅点击该按钮时才同时发出清空 `tool.credential_id` 的 PATCH (调用方负责 — `onBound` result 的 `kind: 'connection'` 中附带 `overrideCleared: true` flag)。
- 默认路径(阅读警告后直接保存)保留 override。
- override clear 会在 **M6 legacy drop 中统一处理**，因此 M5 UI 默认也倾向“保留”。

```
┌─ DialogHeader ─────────────────────────────────┐
│ [KeyIcon] {toolName} 连接                         │
│ 选择此工具调用外部 API 时使用的认证信息。  │
└─────────────────────────────────────────────────┘
┌─ DialogBody ───────────────────────────────────┐
│ [LinkIcon] 连接                                  │
│ ┌───────────────────────────────────────────┐   │
│ │ CredentialSelect (显示所有 credential)     │   │
│ └───────────────────────────────────────────┘   │
│                                                 │
│ (已选择 AND N>1 个 tool 复用时)                    │
│ [InfoIcon] 此 credential 被 {n} 个工具复用。 │
└─────────────────────────────────────────────────┘
┌─ DialogFooter ─────────────────────────────────┐
│               [取消]  [保存]                      │
└─────────────────────────────────────────────────┘
```

**按条件的 UX**
- CredentialSelect 的 `credentials` prop 与 PREBUILT 不同，**不进行 narrow** (让用户可自由选择)。
- 保存时内部行为: 在 `scopeKey({type:'custom', provider_name:'custom_api_key'})` cache 中查找 `credential_id` 一致的现有 connection，没有则 `createConnection` — find-or-create。将 M4 `resolveCustomConnectionId` 逻辑提升为 shell 内部 util。
- **绝对禁止移除 bridge override** — 若 `triggerContext='tool-edit'` 且当前 tool 的 `credential_id != connection.credential_id`，UI 显示**“此工具当前正在使用直接指定的 credential”**警告 badge，并在调用 `onBound` 前确保用户知晓。是否实际更新 `tool.credential_id` 由调用方判断 (保留至 M6)。

### 4.3 MCP (`type='mcp'`)

#### 4.3.a Scope 决策 (M5) — credential binding **仅**负责

MCP 与 PREBUILT/CUSTOM **不对称**: server 实体(`mcp_servers` row — URL, transport, auth_type)先存在，credential 是**server 的 2 级属性**。exec-plan §4 M5 曾提到将“server config + credential”都放进单一 shell，但根据 Bezos S1 分析和共识，**M5 缩小 scope**:

- **M5 决策**: `type='mcp'` shell **仅负责替换 credential 绑定**。对现有 `mcp_servers` row 调用 `useUpdateMCPServer({ credential_id })`。
- server **创建**继续保留在 `add-tool-dialog` MCP tab (UX·backend 路径均保持)。仅 MCP tab 内的“新建 credential” CTA 进入 `CredentialFormDialog` — 与 M4 当前状态相同，不变。
- server **metadata(URL, transport, 名称) 编辑**由现有 `mcp-server-rename-dialog` 等 server 级 component 负责 (M5 scope 外)。M6 在统一 Connection 实体(type='mcp')时重新设计 `extra_config` 编辑 UX。
- 因此 M5 的 `type='mcp'` shell **只处理 `mcpServerId` + `credentialId`**。不创建/更新 Connection 实体 — 因为 backend `mcp_servers` 表在 M6 前仍是 source of truth。

依据 (Simplicity 原则):
1. 若单一 shell 内置 3 种 type 的所有异构保存路径，复杂度反而会爆炸。
2. 已有编辑 server metadata 的**独立路径**(add-tool-dialog / rename-dialog)，没有必要做重复 UI。
3. F 吸收验证标准是“3 个 AuthDialog 调用方为 0”，而 `MCPServerAuthDialog` 的实际职责仅为 **credential binding**，因此只需收敛该职责即可通过 checklist。

#### 4.3.b Wireframe (credential binding 专用)

```
┌─ DialogHeader ─────────────────────────────────┐
│ [KeyIcon] {serverName} 连接                       │
│ 请选择此 MCP server 要使用的 credential。        │
└─────────────────────────────────────────────────┘
┌─ DialogBody ───────────────────────────────────┐
│ [LinkIcon] 连接                                  │
│ ┌───────────────────────────────────────────┐   │
│ │ CredentialSelect                          │   │
│ │  · 无认证 / 现有 credentials / 新建 │   │
│ └───────────────────────────────────────────┘   │
│                                                 │
│ (已选择) [CheckIcon] 已设置连接       │
└─────────────────────────────────────────────────┘
┌─ DialogFooter ─────────────────────────────────┐
│               [取消]  [保存]                      │
└─────────────────────────────────────────────────┘
```

正文 layout 与 PREBUILT/CUSTOM **几乎相同，为 CredentialSelect-only**。尽量降低各 type 分支成本。

#### 4.3.c 保存路径

```ts
// Pseudocode
const credentialId = mode === CREDENTIAL_NONE ? null : mode
await updateMCPServer.mutateAsync({
  id: mcpServerId,
  data: { credential_id: credentialId },
})
onBound?.({ kind: 'mcp-credential', serverId: mcpServerId, credentialId })
```

- 不调用 `useConnections({type:'mcp'})` (因为 M5 不创建 MCP connection 实体)。仅查询 `useCredentials()`。
- 在没有 `mcpServerId` 的情况下以 `type='mcp'` 打开 shell 视为开发错误 — 渲染时 `console.error`，并显示 inline `role=alert`。
- **`/connections` MCP section 的“添加连接” CTA 不打开本 shell** (§8 调用方表中另行处理 — 进入 add-tool-dialog 或先选 server 的 UX)。

---

## 5. 公共 UX 规则

### 5.1 Loading 状态
- 初始 `useConnections` loading 时，在 CredentialSelect 位置显示 `<Skeleton className="h-9 w-full" />`。
- 保存(binding)期间，[保存]按钮显示 `<Loader2Icon className="animate-spin" />` + `disabled`。

### 5.2 Error UI
- Toast (`sonner`): 网络/server 错误(500, 普通 4xx)
- Inline `role=alert`: 422 validation 错误(例如 MCP URL 格式错误、env_vars template 规则违反)。紧贴字段下方，`text-sm text-destructive`。
- 409: 正文顶部 `role=alert` banner + “重试”提示。Dialog 不关闭。

### 5.3 成功 UI
- `toast.success(t('toast.saved'))`
- 调用 `onBound(connection)`
- 300ms 内关闭 dialog (避免动画重叠)

### 5.4 空状态 (connection 0 个, credential 0 个)
- PREBUILT: 直接进入 `credential_form` 状态。文案“还没有 {provider} credential。请新建”。
- CUSTOM: CredentialSelect 本身显示空列表 + “新建连接”按钮。无需额外文案。
- MCP: 原样显示 Section A form (空状态 = 首次注册的默认状态)。

---

## 6. 无障碍 (WCAG 2.1 AA)

明确实现时容易遗漏的项目。

- [ ] **Focus trap**: shadcn `Dialog` 默认提供。CredentialFormDialog 以 nested 打开时 focus 移入其中，关闭后回到原 Dialog 第一个字段。
- [ ] **ESC 关闭**: Radix Dialog 默认行为。但在 `binding` 状态下需通过 `onOpenChange` guard，禁止 ESC/outside click 关闭。
- [ ] **键盘导航**: Tab 顺序 = Header → CredentialSelect → (辅助按钮) → [取消] → [保存]。MCP 为 Section A 字段 → Section B → Section C(展开时) → Footer。
- [ ] **aria-live**: `role=alert` error banner (assertive)。保存中的 loading spinner 周围设置 `aria-busy="true"`。
- [ ] **label**: 所有 Input 均连接 `<label htmlFor>`。Select/Combobox 使用 shadcn 默认 `aria-labelledby`。
- [ ] **颜色对比度**: error 文本(`text-destructive`)与成功文本(`text-emerald-600`)在 dark/light 下均 ≥4.5:1 (保持现有 design token)。
- [ ] **motion**: 尊重 `prefers-reduced-motion` — Loader2Icon `animate-spin` 根据用户设置停止。

---

## 7. i18n key 命名

将现有 `connections.bindingDialog.*` 扩展为**按 type 的 sub-namespace**。现有 key 为兼容保留，但仅使用新 key。

```jsonc
"connections": {
  "bindingDialog": {
    // 公共 (所有 type)
    "save": "保存",
    "cancel": "取消",
    "configured": "连接已设置",
    "loading": "正在加载连接信息…",
    "toast": {
      "saved": "连接已保存",
      "saveFailed": "连接保存失败",
      "conflictRetry": "默认连接已在其他 session 中被更改。请基于最新状态重试。"
    },

    // PREBUILT
    "prebuilt": {
      "title": "{name} 连接",
      "description": "请选择此工具要使用的 credential。",
      "emptyCredential": "还没有 {provider} credential。请新建。"
    },

    // CUSTOM
    "custom": {
      "title": "{toolName} 连接",
      "description": "请选择此工具调用外部 API 时使用的认证信息。",
      "reusedBadge": "被 {count} 个工具复用",
      "bridgeOverrideWarning": "此工具当前正直接指定使用另一个 credential。保存后将恢复为公共 connection。"
    },

    // MCP
    "mcp": {
      "title": "MCP server 连接",
      "description": "请输入要连接的 MCP server 信息并指定 credential。",
      "sectionServer": "Server 基本信息",
      "sectionCredential": "Credential",
      "sectionAdvanced": "高级设置",
      "displayName": "显示名称",
      "url": "Server URL",
      "transport": "Transport",
      "authType": "认证类型",
      "timeout": "Timeout (秒)",
      "headers": "Headers",
      "envVars": "环境变量",
      "envVarTemplateHint": "值仅允许使用 ${credential.<field_name>} template。",
      "envVarTemplateError": "不允许明文值。请使用 credential 引用 template。"
    }
  }
}
```

**防冲突**: 为避免与现有 `tool.addDialog.*`、`tool.authDialog.provider.*`、`tool.customAuth.*`、`tool.mcpServer.auth.*` key 重复，必须放在 `connections.bindingDialog.<type>.*` 下。

---

## 8. 调用方 signature 变更 (S3 实现备注)

| 调用方 | Before | After |
|---|---|---|
| `/connections` PREBUILT 卡片 | `ConnectionBindingDialog(type='prebuilt', providerName, toolName, open, onOpenChange)` | **无变更** (与 M4 相同) |
| `/connections` CUSTOM section “添加连接” (新增) | — | `ConnectionBindingDialog(type='custom', providerName='custom_api_key', triggerContext='standalone', onBound)` |
| `/connections` MCP section “添加连接” (新增) | — | **不打开本 shell**。打开 `add-tool-dialog` MCP tab，或提示“请先注册 server” → server 注册后自动由 `type='mcp'` shell 要求指定 credential。具体 UX 参见 `m5-connections-page-redesign-spec.md` §3.3 |
| `tools/page.tsx` (Agent tool 编辑) CUSTOM | `<CustomAuthDialog tool trigger>` | `<ConnectionBindingDialog type='custom' triggerContext='tool-edit' toolName={tool.name} currentConnectionId={tool.connection_id} onBound={...}>` + trigger wrapper |
| `components/tool/mcp-server-group-card.tsx` (MCP server “认证”按钮) | `<MCPServerAuthDialog server open onOpenChange>` | `<ConnectionBindingDialog type='mcp' triggerContext='tool-edit' mcpServerId={server.id} toolName={server.name} onBound={...}>` — 内部为 `useUpdateMCPServer({credential_id})` |
| `add-tool-dialog.tsx` MCP tab | inline form + `useRegisterMCPServer` | **最小化变更** — 保留 server 创建 form(name/url)和 `useRegisterMCPServer` 调用。“新建 credential” CTA 继续使用现有 `CredentialFormDialog` (保持 M4 状态)。不包裹 ConnectionBindingDialog (§4.3.a 决策) |
| `add-tool-dialog.tsx` Custom tab | inline form (M4 find-or-create) | **无变更** (M4 已完成 — 禁止 drive-by) |

**wrapper 文件处理**:
- `prebuilt-auth-dialog.tsx`: M4 当前已为 thin wrapper。S3 中**若调用方消失则删除文件本身**的判断依据 Bezos S1 结果。
- `custom-auth-dialog.tsx`, `mcp-server-auth-dialog.tsx`: S3 中删除或变为 thin wrapper。若外部还残留 `import`，全部替换。

---

## 9. Wireframe (ASCII)

### PREBUILT — 已有连接状态

```
┌──────────────────────────────── 🔑 Naver 搜索连接 ─────┐
│ 请选择此工具要使用的 credential。                 │
│                                                         │
│ 🔗 连接                                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 我的 Naver API key                          ▾          │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ ✔ 已设置连接                                │
│                                                         │
│                                    [取消]  [保存]        │
└─────────────────────────────────────────────────────────┘
```

### CUSTOM — tool-edit 上下文, bridge override 警告

```
┌──────────────────────────────── 🔑 Weather API 连接 ────┐
│ 请选择此工具调用外部 API 时使用的认证信息。        │
│                                                         │
│ ⚠ 此工具当前正直接指定使用另一个 credential。 │
│   保存后将恢复为公共 connection。                 │
│                                                         │
│ 🔗 连接                                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 股票 API key (3 个工具正在使用)          ▾        │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│                                    [取消]  [保存]        │
└─────────────────────────────────────────────────────────┘
```

### MCP — tool-create 上下文, advanced 折叠

```
┌────────────────────────────────── 🖥 MCP server 连接 ──────┐
│ 请输入要连接的 MCP server 信息并指定 credential。 │
│                                                         │
│ ▸ Server 基本信息                                          │
│    显示名称  [                          ]               │
│    Server URL  [https://...                ]              │
│    Transport ( http )  ( stdio )                         │
│    认证类型 ( none | bearer | api_key | oauth2 | basic )│
│                                                         │
│ ▸ Credential  (认证类型 ≠ none)                         │
│    🔗 连接 [新建连接…          ▾]                  │
│                                                         │
│ ▸ 高级设置 (折叠)    ▸                                  │
│                                                         │
│                                    [取消]  [注册]        │
└─────────────────────────────────────────────────────────┘
```

---

## 10. 验收标准 (S3 验证用)

- [ ] 单个 `ConnectionBindingDialog` 文件处理全部 3 个 `type`。
- [ ] M4 PREBUILT 场景(Naver, Google 4 种)无回归 — 手动确认 screenshot 一致性。
- [ ] CUSTOM `tool-edit` 中 find-or-create 行为与现有 `add-tool-dialog` custom tab 等价。
- [ ] MCP `tool-create` 中现有 `add-tool-dialog` MCP tab 的“server 注册 + tool discovery”路径无回归。
- [ ] 发生 409 竞争时 dialog 保持 + toast + invalidate 正常工作。
- [ ] 检查 Focus trap / ESC / aria-live / prefers-reduced-motion。
- [ ] 新增 i18n key `connections.bindingDialog.{prebuilt|custom|mcp}.*`，与现有 `tool.addDialog.*` key 无冲突。
- [ ] 3 个 legacy dialog 文件被删除或只保留 thin wrapper，使 `rg "AuthDialog" frontend/src/components/tool/` 仅显示新 shell 调用。

---

## 11. Open issue / M5 scope 外

- `agent_tools.connection_id` override UI — **M5.5** (独立 worktree)。
- `tool.credential_id` / `tool.auth_config` / `agent_tools.config` drop — **M6**.
- MCP `mcp_servers` → Connection 实体吸收、`extra_config` 编辑 UX (headers / env_vars / URL / transport) — **M6**。M5 仅负责 credential binding。
- CUSTOM bridge override(`tool.credential_id != connection.credential_id`)统一清理 — 在 **M6** legacy drop 时处理。

---

## 12. Zuckerberg S3 实现时注意事项 (提前预警回归风险)

### 12.1 `tools/page.tsx` `getAuthStatus` 回归 (Bezos S1 §7-4 Bezos "?")

`app/tools/page.tsx` 中可能存在通过 **`tool.credential_id`** 判断 Custom tool 是否“configured”的 `getAuthStatus` 逻辑 (M5 scope 中 Bezos 未查看)。将 CustomAuthDialog → ConnectionBindingDialog(type='custom') 替换**后**，UI badge 可能错误显示“未设置”。

**实现 checklist**:
- [ ] 替换前通过 `rg "getAuthStatus|credential_id" frontend/src/app/tools/` 确认判断逻辑位置。
- [ ] 若判断标准仅为 `tool.credential_id`，则**(a) 根据现有 bridge override 保留原则，`tool.credential_id` 会继续有值，因此无回归** — 因为 ConnectionBindingDialog 只 PATCH connection.credential_id，不修改 tool.credential_id。此情况无需更改即可通过。
- [ ] 反之，若新创建的 CUSTOM tool 中存在 `tool.credential_id IS NULL` 的 row(find-or-create 只填 connection_id、credential_id 留空的情况 — 参见 `add-tool-dialog.tsx:157-160` bridge 发送行)，则需把判断逻辑扩展为基于 `tool.connection_id`。
- [ ] **手动 E2E (S5 Bezos)**: 在 M4 bridge row / 新 M5 row / legacy-only row 3 类情况下，确认 tool card “configured” badge 正确显示。

### 12.2 防止现有 PREBUILT 调用方回归

M4 中 `ConnectionBindingDialog(type='prebuilt')` 已在运行。扩展 `type` literal union 时检查 **TypeScript narrowing** 不被破坏:

```ts
if (type === 'prebuilt' && providerName) {
  // providerName 必须在此处 narrow 为 PrebuiltProviderName
}
```

- [ ] 保留 `isPrebuiltProviderName()` guard (`lib/types/index.ts:255`)。
- [ ] `useConnections({type, provider_name})` 调用在 `type='mcp'` 时必须 **skip** — 不使用 MCP connection 实体 (§4.3.c)。

### 12.3 i18n 冲突自动验证

```bash
# 验证新 key 是否侵入现有 namespace
jq 'paths(scalars) | map(tostring) | join(".")' frontend/messages/ko.json | sort | uniq -d
# 预期: 无输出 (无重复 key)
```

### 12.4 `components/tool/mcp-server-group-card.tsx` 调用处

该文件是唯一调用 `MCPServerAuthDialog` 的位置 (Bezos S1 §2.2)。替换为 ConnectionBindingDialog 后，**点击卡片“认证”按钮的体验**必须相同 — open state 管理方式(trigger vs controlled)不同，因此需从 trigger prop 改为 `open/onOpenChange`。
