# M5 — /connections 页面以 Connection 为中心的重构 spec

**Owner**: Tim Cook (Tim Cook)
**Related**: ADR-008, exec-plan §4 M5 · S4, `m5-connection-binding-dialog-spec.md`
**Status**: Draft for Zuckerberg 实现 (S4)
**Scope**: 仅 frontend。将 `/connections` 页面全面重构为 **Connection 1 级**结构。移除 Credential 卡片，Credential 仅在 Connection detail 内显示。

---

## 1. 当前结构 (M4 状态)

**文件**: `frontend/src/app/connections/page.tsx`

```
PageHeader “连接管理”
├─ Search + Type Filter + [添加连接] (= 创建 Credential)
├─ CredentialCard 列表            ← 将 Credential 作为 1 级实体显示 (现有)
└─ PrebuiltConnectionSection      ← M3 新增的按 PREBUILT provider 分组的 default section
```

**问题**
1. “Connection”和“Credential”两个概念混杂在同一页面 — 用户无法区分“什么是连接、什么是认证信息”。
2. 没有 CUSTOM section — CUSTOM connection 只能在 `/tools` 中通过 find-or-create 间接创建。已创建的 CUSTOM connection **无法在此页面查看/修改/删除**。
3. 也没有 MCP section — MCP connection 在 `/tools` 注册 server 时间接创建。无法独立管理。
4. 概念模型与 ADR-008 不一致 — ADR-008 将 Connection 定义为 1 级实体，Credential 为挂在 Connection 下的子概念。

---

## 2. 重构后结构 (M5 目标)

```
PageHeader “连接管理”
├─ (可选) 全局 filter / 搜索
│
├─ Section: PREBUILT
│    ├─ 按 provider 的子分组 (Naver, Google Search, Google Chat, Google Workspace)
│    │   └─ Connection Card 列表 (每个 provider 0~N 个, default badge)
│    └─ “添加连接” CTA (provider 选择 prompt)
│
├─ Section: CUSTOM
│    ├─ Connection Card 列表
│    └─ “添加连接” CTA
│
└─ Section: MCP
     ├─ Connection Card 列表
     └─ “添加连接” CTA
```

**原则**
- 不显示 Credential card/list。**Credential 仅在 Connection detail drawer 中显示**。
- 每个 section header 提供“添加连接” CTA — 以 `triggerContext='standalone'` 打开 `ConnectionBindingDialog`。
- Credential CRUD API(`lib/hooks/use-credentials.ts`) **不删除并保留**。内部调用(ConnectionBindingDialog → CredentialFormDialog)继续使用。

---

## 3. Section 详情

### 3.1 Section: PREBUILT

#### Layout

```
┌─ PREBUILT 连接 ─────────────────────────────────────────┐
│ 管理系统工具(Naver, Google 等)要使用的 API key。 │
│                                                        │
│ ┌─ Naver ──────────────────────── [+ 添加连接] ───┐    │
│ │ ┌ [ConnectionCard] 我的 Naver key     [默认]  [详情]┐│    │
│ │ └──────────────────────────────────────────────┘│    │
│ │ ┌ [ConnectionCard] 公司 Naver key          [详情]┐│    │
│ │ └──────────────────────────────────────────────┘│    │
│ └──────────────────────────────────────────────────┘    │
│                                                        │
│ ┌─ Google Search ─────────────── [+ 添加连接] ───┐    │
│ │  (暂无已注册连接。)                     │    │
│ └──────────────────────────────────────────────────┘    │
│                                                        │
│ ... Google Chat / Google Workspace 结构相同            │
└────────────────────────────────────────────────────────┘
```

#### 数据
- 调用一次 `useConnections({ type: 'prebuilt' })` → client-side groupBy `provider_name`。
- provider 顺序固定为 `['naver', 'google_search', 'google_chat', 'google_workspace']` (按 ADR-008 credential_registry 顺序)。
- 空 provider 分组也以折叠状态显示 — 让用户了解“有哪些 provider”。

#### “添加连接” CTA
- 打开 `ConnectionBindingDialog(type='prebuilt', providerName=<对应分组>, triggerContext='standalone')`。
- 因挂在各 Provider 分组 header 上，所以以 providerName 固定状态打开。

### 3.2 Section: CUSTOM

```
┌─ CUSTOM 连接 ─────────────────────── [+ 添加连接] ──┐
│ 管理可在自定义工具中复用的 API key。       │
│                                                       │
│ ┌ [ConnectionCard] 我的外部 API key    [3 个工具使用] ┐ │
│ └─────────────────────────────────────────────────┘ │
│ ┌ [ConnectionCard] Weather API key    [1 个工具使用] ┐ │
│ └─────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

#### 数据
- `useConnections({ type: 'custom' })`.
- provider_name 始终为 `custom_api_key` (CUSTOM 唯一 provider) — 无子分组，使用 flat 列表。

#### “添加连接” CTA
- 打开 `ConnectionBindingDialog(type='custom', providerName='custom_api_key', triggerContext='standalone')`。
- 保存时执行 find-or-create。若基于相同 credential，则复用现有 connection。

### 3.3 Section: MCP

```
┌─ MCP 连接 ────────────────────────── [+ 添加连接] ──┐
│ 连接 MCP server 并获取更多工具。              │
│                                                       │
│ ┌ [ConnectionCard] Notion MCP  http · bearer  [详情]┐│
│ └─────────────────────────────────────────────────┘ │
│ ┌ [ConnectionCard] Linear MCP  http · api_key [详情]┐│
│ └─────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

#### 数据
- `useConnections({ type: 'mcp' })`.
- 无子分组 (provider_name 由用户指定)。

#### “添加连接” CTA (MCP section)

**决策 (M5)**: 此 CTA 不打开 `ConnectionBindingDialog(type='mcp')` — 因该 shell **只负责替换现有 mcp_server 的 credential** (binding-dialog spec §4.3.a)。

M5 采用的路径为**选项 A**:

- **选项 A (采用)**: 点击“添加连接” CTA 后，**打开 `add-tool-dialog` MCP tab**。用户在其中完成 server 创建 + credential 设置后，自动返回 `/connections` MCP section (列表 refetch)。只是从 `/connections` 共享入口，实际 UI 仍为现有 add-tool-dialog MCP tab — 避免重复 UX。
- **选项 B (reject)**: 先从 server 列表中选择，再设置 credential — 但对于“尚无 server 的用户”，首次进入时会嵌套两层 empty state，反而更复杂。否决。

实现提示 (Zuckerberg):
- `AddToolDialog` 接收 `trigger` prop — 将 `/connections` MCP section 的“添加连接”按钮直接包在 `<AddToolDialog trigger={<Button ... />} />` 中调用。
- 若没有将默认 active tab 固定为 `mcp` 的 prop，S3 允许添加 `defaultTab='mcp'` prop (禁止对 add-tool-dialog 做 drive-by，但新增一行默认值 prop 在允许范围内)。

---

## 4. ConnectionCard

```
┌─────────────────────────────────────────────────────────┐
│ [🔗] {display_name}                                      │
│                                                         │
│      [provider badge] [status badge] [默认 badge(可选)]    │
│                                                         │
│      🔑 credential: {credential.name ?? "未指定"}        │
│      🛠  正被 {n} 个工具使用                           │
│                                    [详情] [⋮ 菜单]       │
└─────────────────────────────────────────────────────────┘
```

### 4.1 字段

| 元素 | 数据来源 | 备注 |
|---|---|---|
| 图标 | 按 type 的 lucide (`KeyRoundIcon`/`WrenchIcon`/`ServerIcon`) | 视觉信号 |
| 名称 | `connection.display_name` | 不换行，truncate |
| provider badge | `connection.provider_name` | PREBUILT 映射为韩文 label，MCP/CUSTOM 使用原文 |
| status badge | `connection.status` | active = `outline`, disabled = `secondary` + muted |
| “默认” badge | `connection.is_default === true` | `secondary`，尺寸很小 |
| credential 显示 | 使用 useCredentials 按 `connection.credential_id` lookup → `credential.name` | null 时显示“未指定”灰色文本 |
| 使用中 tool 数 | `useToolsByConnection(connection.id)` (新增 derived selector) | 0 时显示“无使用中工具” |

### 4.2 交互

| 区域 | action |
|---|---|
| 点击整张卡片 | 打开详情 drawer (PC)，全屏 sheet (移动端) |
| [详情]按钮 | 相同 |
| [⋮] 菜单 | [编辑名称] / [status toggle] / [删除] |
| [status toggle] | `useUpdateConnection({ status: 'active'|'disabled' })` — 立即生效，出错时 revert |

**删除行为**
- 使用中 tool 数 `> 0` 时通过 `AlertDialog` 警告 + **删除按钮 disabled** (M5 安全默认值)。
- 数量为 `0` 时警告后允许删除。
- 删除 PREBUILT 的 `is_default=true` connection 时: 若同一 provider 没有其他 connection，则警告“该 provider 将没有连接，所有 tool 将在无默认值的情况下运行”。

#### 4.3 Credential 删除 semantics (M5 决策)

根据 ADR-008 的 N:1 模型 (多个 Connection 可共享一个 Credential — CUSTOM 复用场景)制定策略:

| 动作 | 处理 |
|---|---|
| **删除 Connection ≠ 删除 Credential** | 只删除 Connection row。所引用的 credential **保留**。其他 connection 可能仍在引用，即使没有，也不会在用户未明确删除“key 本身”的情况下将其清除。 |
| 删除最后一个引用 connection 后的 credential | 作为“孤立 credential”保留。不会显示在 `/connections` 1 级列表中(已移除 Credential card)，但创建 Connection 时仍会出现在 CredentialSelect 选项中。 |
| 若要实际删除 Credential | 在 Connection 详情 drawer 的**“Credential 编辑”** (§5.2)流程中使用 `CredentialFormDialog` 内删除按钮。若该 credential row **还被其他 connection 引用则阻止此路径** (`useCredentials` 响应 + 全量 `useConnections` 查询作为 client-side 安全措施 — server FK 虽配置为 `ON DELETE SET NULL`，但 UX 层面阻止)。 |
| 批量清理孤立 credential | 不在 M5 scope。后续如需要“Credential 管理” UX，再单独规划。 |

**删除按钮 label**: Drawer 中“删除连接”明确写为“**仅删除此连接**” (告知用户 credential 会保留)。i18n key: `connections.detail.deleteButton` = “仅删除此连接 (保留 credential)”。

---

## 5. Connection 详情 (Drawer)

点击后从右侧以 drawer 打开 (推荐 shadcn `Sheet` — 需确认项目内现有类似模式)。

### 5.1 结构

```
┌─ Drawer ────────────────────────────────────┐
│ 🔗 {display_name}                    [✕]    │
│ {provider badge} {status badge}             │
├─────────────────────────────────────────────┤
│ 概览                                         │
│  · 类型        PREBUILT / CUSTOM / MCP      │
│  · Provider   naver / custom_api_key / ...  │
│  · 创建日期      2026-04-10                   │
│  · 修改日期      2026-04-18                   │
│                                             │
│ Credential (bound)                          │
│  · 名称        我的 Naver API key               │
│  · 类型        API Key / OAuth2             │
│  · 字段        client_id, client_secret     │
│  · [更换 credential]   [编辑 credential]     │
│                                             │
│ MCP 详情 (仅 type=mcp 时)                  │
│  · URL         https://...                 │
│  · Transport  http                         │
│  · Auth type  bearer                       │
│  · Headers    2 个                          │
│  · Env vars   1 个                          │
│                                             │
│ 使用中工具 ({n})                           │
│  · [ToolName] → /tools?highlight=...       │
│  · ...                                      │
│                                             │
│ 危险区域                                    │
│  · [状态切换: active ↔ disabled]            │
│  · [删除连接]                              │
└─────────────────────────────────────────────┘
```

### 5.2 交互

- **更换 Credential (替换为另一个 credential)**: 打开 `ConnectionBindingDialog(type, providerName, triggerContext='standalone', currentConnectionId=<this>)`。仅修改 Connection row 的 `credential_id` FK。原 credential row 保持不变。
- **编辑 Credential (轮换同一 credential 的值)**: 直接打开 `CredentialFormDialog(editingCredential=<credential>)`。替换 credential row 本身的 field 值(secret rotation)。不修改 Connection。
- **删除 Credential**: CredentialFormDialog 内“删除”按钮。但若通过全局 `useConnections()` 查询发现**其他 connection 正引用同一 credential_id，则 disabled** + tooltip “正在被其他连接使用。请先解除对应连接。”。可点击时，通过 `AlertDialog` 警告后执行 `useDeleteCredential`。
- **状态切换**: `useUpdateConnection({ status })`。禁用时显示“使用此连接的工具在执行时会失败” inline 警告。
- **删除 Connection**: 按 4.2 + 4.3 规则 (仅删除连接，保留 credential)。

为从视觉上区分三种动作，在 drawer 的 “Credential (bound)” section 中并排放置三个按钮:
```
[更换 credential]  [编辑 credential]       (在 ⋮ 菜单内 → [删除 credential])
```
`删除 credential` 属于破坏性动作，因此默认显示时隐藏一层 (Tim Cook 设计原则: 风险度 ≠ 可访问性)。

---

## 6. 空状态

### 6.1 页面整体空状态 (connection 0 个)

```
┌─────────────────────────────────────────────┐
│         🔗                                   │
│   暂无连接                        │
│   注册可在工具中复用的 API key。    │
│                                             │
│   [添加 PREBUILT 连接]                       │
│   [添加 CUSTOM 连接]                         │
│   [添加 MCP 连接]                            │
└─────────────────────────────────────────────┘
```

### 6.2 各 section 空状态

按 PREBUILT provider 的分组:
```
┌─ Naver ─────────────────── [+ 添加连接] ─┐
│ 暂无 Naver 连接。                  │
└──────────────────────────────────────────┘
```

CUSTOM / MCP:
```
┌─ CUSTOM 连接 ─────────── [+ 添加连接] ─┐
│ 暂无 CUSTOM 连接。               │
└──────────────────────────────────────────┘
```

---

## 7. 删除 / 移除项目 (防回归 checklist)

| 移除对象 | 位置 | 替换 |
|---|---|---|
| 现有 Credential card 列表 | `page.tsx:142-162` | 删除 — 替换为 Connection Card |
| Search / Type Filter | `page.tsx:108-134` | 删除或缩减为全局 filter (M5 scope 内建议直接删除) |
| 顶部 `[添加连接]` 按钮 (当前为创建 Credential) | `page.tsx:130-133` | 分散到各 section CTA |
| `PrebuiltConnectionSection` inline 实现 | `page.tsx:204-300` | 重写为新的 `PrebuiltConnectionSection` component |
| `AlertDialog` (credential 删除) | `page.tsx:172-199` | 替换为 Connection 删除 AlertDialog |
| 顶部 `CredentialFormDialog` 调用 | `page.tsx:166-170` | 删除 — 仅在 Connection 详情 drawer 内使用 |

**保留对象**
- `useCredentials` / `useCredentialProviders` hook — 继续用于 Connection 详情 drawer 中显示 credential 名称、编辑 credential。
- `CredentialFormDialog` component 本身。

---

## 8. 无障碍

- [ ] section header 使用 `<h2>` semantic，provider 分组 header 使用 `<h3>`。
- [ ] Connection Card 使用 `role="region"` + `aria-labelledby={idOfName}` — 让 screen reader 按 card 单位识别。
- [ ] Drawer 打开时 focus 移至 drawer 关闭按钮，关闭后返回 trigger card。
- [ ] [⋮] 菜单使用 shadcn `DropdownMenu` — 默认提供键盘导航。
- [ ] 确认 empty state CTA 按钮也可通过键盘 tabindex 到达。
- [ ] status toggle(Switch 或 Button)明确设置 `aria-checked` / `aria-pressed`。

---

## 9. i18n key (新增)

```jsonc
"connections": {
  "pageTitle": "连接管理",
  "pageDescription": "管理工具可复用的外部服务连接。",

  "sections": {
    "prebuilt": {
      "title": "PREBUILT 连接",
      "description": "管理系统工具(Naver, Google 等)要使用的 API key。",
      "addButton": "添加连接",
      "providerEmpty": "暂无 {provider} 连接。"
    },
    "custom": {
      "title": "CUSTOM 连接",
      "description": "管理自定义工具中可复用的 API key。",
      "addButton": "添加连接",
      "empty": "暂无 CUSTOM 连接。"
    },
    "mcp": {
      "title": "MCP 连接",
      "description": "连接 MCP server 并获取更多工具。",
      "addButton": "添加连接",
      "empty": "暂无 MCP 连接。"
    }
  },

  "card": {
    "credentialUnbound": "未指定 credential",
    "usedByTools": "正被 {count} 个工具使用",
    "noUsage": "无使用中工具",
    "isDefaultBadge": "默认",
    "statusActive": "启用",
    "statusDisabled": "停用"
  },

  "detail": {
    "sectionOverview": "概览",
    "sectionCredential": "Credential",
    "sectionMcp": "MCP 详情",
    "sectionUsage": "使用中工具",
    "sectionDanger": "危险区域",
    "changeCredential": "更换 credential",
    "editCredential": "编辑 credential",
    "toggleToDisabled": "停用",
    "toggleToActive": "启用",
    "disabledWarning": "使用此连接的工具在执行时会失败。",
    "deleteButton": "仅删除此连接",
    "deleteButtonHint": "保留 credential",
    "deleteBlockedByUsage": "有正在使用的工具，无法删除。请先更换工具的连接。",
    "credentialChange": "更换 credential",
    "credentialEdit": "编辑 credential",
    "credentialDelete": "删除 credential",
    "credentialDeleteBlocked": "正在被其他连接使用。请先解除对应连接。"
  },

  "emptyPage": {
    "title": "暂无连接",
    "description": "注册可在工具中复用的 API key。"
  },

  "toast": {
    "statusChanged": "连接状态已更改",
    "statusFailed": "更改连接状态失败",
    "deleted": "连接已删除",
    "deleteFailed": "删除连接失败"
  }
}
```

**现有 key 处理**
- `connections.prebuiltSection.*`: 仅将可复用 copy 迁移到新 namespace，其余标记为 deprecated (S6 前整理)。
- `connections.empty.*`、`connections.deleteConfirm` 等以 Credential 为中心的 key: S4 中设为未使用 (M5 scope 内不删除，保留到 M6 cleanup 时 drop)。

---

## 10. 派生 Selector — useToolsByConnection

为 Connection Card 的“使用中 tool 数”需要新增派生 selector。

```ts
// frontend/src/lib/hooks/use-connections.ts (新增派生 export)

export function useToolsByConnection(connectionId: string) {
  const { data: tools } = useTools()  // 复用现有 hook
  return useMemo(
    () => tools?.filter((t) => t.connection_id === connectionId) ?? [],
    [tools, connectionId],
  )
}
```

**设计备注**
- `useTools()` 已在全局 cache 中，因此没有额外请求。
- `mcp_server` 被多个 tool 共享时(MCP): 需要 `tool.mcp_server_id → mcp_server.connection_id` 的双跳 — S4 中 Zuckerberg 在确认复用 `useMCPServers()` 后实现。必要时按 type 分支 `useToolsByConnection`。

---

## 11. 验收标准 (S4 验证用)

- [ ] 进入 `/connections` 时只渲染 3 个 section(PREBUILT / CUSTOM / MCP)，Credential card 显示 0 个。
- [ ] 各 section “添加连接” CTA 以固定 type 打开 `ConnectionBindingDialog`。
- [ ] 现有 M3 用户创建的 PREBUILT connection 原样显示在新 UI 中 (Naver default 无回归)。
- [ ] 现有 M4 用户在 `/tools` 创建的 CUSTOM connection 显示在新的 CUSTOM section 中。
- [ ] 点击 Connection Card → 打开 drawer → credential meta/使用 tool 列表/status toggle/删除正常工作。
- [ ] 尝试删除有使用中 tool 的 connection → 阻止 + warning toast。
- [ ] 2 种 empty state(整体 / section)文案及 CTA 正常显示。
- [ ] 添加 i18n 新 key `connections.sections.*`, `connections.card.*`, `connections.detail.*`。
- [ ] 禁止 Drive-by: backend 文件修改 0、`lib/api/credentials.ts` signature 修改 0、M5.5/M6 区域修改 0。

---

## 11b. 实现时回归注意事项 (Zuckerberg S4)

### 11b.1 `tools/page.tsx` `getAuthStatus` (Bezos S1 §7-4 Bezos "?")

本 spec scope 是 `/connections` 页面，但**为计算 Connection card 的“使用中 tool 数”会读取 `useTools()` 全局 cache**。如果 `tools/page.tsx` 使用同一 cache 判断 “configured” badge，可能出现两个页面使用不同字段(如 `tool.credential_id` vs `tool.connection_id`)判断的情况。S4 实现时:

- [ ] `useToolsByConnection(connectionId)` 派生 selector 对 **MCP / CUSTOM 的过滤条件不同** — CUSTOM 为 `tool.connection_id === id`，MCP 需先确认 `tool.mcp_server_id` 是否指向对应 server，再将 `mcp_server.credential_id` 与 Connection 匹配。必须按 type 分支。
- [ ] 确认现有 M4 bridge row(`tool.credential_id != null && tool.connection_id != null`)也正确计入 — 使用**基于 connection_id**而非 credential_id 的匹配。
- [ ] tools/page.tsx `getAuthStatus` 由 S3 Zuckerberg 在**替换 CustomAuthDialog 时一并检查**。本 spec(§11b)仅处理同一问题在 `/connections` 侧的派生影响。

### 11b.2 Credential 孤立状态验证

- [ ] 手动 E2E 确认删除 Connection 后 `/connections` 任何地方都不显示该 credential，但创建其他 Connection 时 CredentialSelect 中仍可选 (Bezos S5)。
- [ ] 确认 Credential 删除在“被其他 connection 引用时 disabled” — 注意全局 `useConnections()` refetch 时序。

---

## 12. Open issue / M5 scope 外

- **Connection 编辑 (display_name / is_default 提升)**: 仅提供最小 inline edit (以 ConnectionBindingDialog 的 credential 更换流程替代)。M5 不制作独立“Connection 编辑 form” (性价比较低，如有需要后续再做)。
- **用量统计(usage analytics)**: 当前仅统计数量。最近调用/token 消耗等属于 `/usage` domain scope。
- **恢复 Search / Filter**: section 分离后概念已更清晰，因此 M5 无搜索上线。拥有多个 connection 的用户增加后再添加。
- **MCP Headers/env_vars 详情编辑 UX**: ConnectionBindingDialog spec(§4.3)规定最小实现。后续再改进。
