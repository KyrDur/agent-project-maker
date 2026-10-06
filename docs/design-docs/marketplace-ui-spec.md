# Marketplace UI Design Spec (M8a Slice G)

> 编写日期: 2026-05-18
> 作者: Tim Cook (TTH Designer / UX)
> 相关文档: PRD v0.2 §10·§11, Spec v0.1 §10, ADR-017, ADR-010 (design token + DialogShell), Module Contracts §3
> 目的: 将 Phase 1 Skill marketplace 的信息架构、状态显示、card/table 列、用户流程、component mapping、API interface 文档化，以 unblock Zuckerberg(M8b 实现者)。
> 产出范围: text-only design spec — 有意排除 pixel-perfect wireframe (Zuckerberg 在 shadcn/DialogShell/DataTable 上实现即可自动保证视觉一致性)。

---

## 0. Design Posture

### 0.1 设计原则

1. **优先复用 (Musk Step 2 — 删除)**: 新 component 仅限 marketplace domain 特有元素(`OriginBadge`, `PublicationBadge`, `InstallWizard`, `PublishWizard`, `MarketplaceCard`, `MarketplaceFilterBar`, `CredentialSummaryChip`, `UpdateAvailableBanner`)。其余(`Card`, `DataTable`, `Dialog`/`DialogShell`, `Badge`, `Tabs`, `Select`, `Combobox`, `Form`, `AlertDialog`, `Sheet`)全部原样复用 shadcn/ui + ADR-010 token。

2. **最小化认知负担 (Musk Step 3 — 简化)**: 每 1 张 card 显示的 1 级信息不超过 7 个 slot(name, description, owner, resource type, visibility, latest version, credential summary)。更多信息放到 detail 页面。

3. **来源/发布状态的视觉一致性**: `OriginBadge` 与 `PublicationBadge` 不仅在 marketplace catalog，也在 `/skills`, `/mcp-servers`, agent dashboard 任意位置使用同一 component 渲染 — 让用户一眼判断“这是我的、导入的还是共享的”。

4. **状态表达不只依赖颜色 (WCAG 2.1 AA)**: 所有状态 chip 同时使用 text label + icon + color。`is_listed=False` 的 public item 不用红色，而以 `text-muted-foreground + 锁形 icon + "Unlisted"` label 表示。

5. **全栈一致性**: 创建与 backend API surface(Spec §10.1~§10.7, progress.txt L60–101) 1:1 mapping 的 hook/api 函数，再在其上构建 page/component。UI 中创建的临时状态(local cache, optimistic update 等)不得与 backend contract 不一致。

6. **按错误 code 分支**: Spec §10.7 的 12 个 error code 各自对应不同 UX 分支。不合并为一条 generic toast(参见 §6 Error Matrix)。

### 0.2 token/pattern 复用 mapping (ADR-010)

| 用途 | token/class | 应用位置 |
|------|------------|--------|
| 卡片强调 hover/active border | `ring-1 ring-border/60` + `hover:ring-primary-strong/30` | `MarketplaceCard` |
| 强调文本 (link/primary CTA) | `text-primary-strong` | "Install" / "View details" 等 |
| 强调背景 (selected tab indicator) | `bg-primary-strong` (after pseudo) | `Tabs` |
| Subtle badge (kind, locale) | `bg-primary/15 text-primary-strong` | OriginBadge `built_in_k_skill` |
| 信息类 chip (`hosted_proxy`) | `bg-status-info/10 text-status-info` | CredentialSummaryChip |
| 警告 chip (`needs setup`, `unlisted`) | `bg-status-warn/10 text-status-warn` | InstallationStatusChip |
| 危险 chip (`disabled`, `secret detected`) | `bg-destructive/10 text-destructive` | PublicationBadge `disabled` |
| 成功 chip (`active`, `published_public_listed`) | `bg-status-success/10 text-status-success` | InstallationStatusChip |
| accent chip (`shared_with_me`, `restricted`) | `bg-status-accent/10 text-status-accent` | OriginBadge `shared_with_me` |
| Dialog 容器 | `DialogShell` + `DIALOG_SIZE.lg`(install) / `DIALOG_SIZE.xl`(publish) | InstallWizard / PublishWizard |
| Wizard side step list | `DialogShell.Sidebar` (260px) | PublishWizard 5-step |
| Table | `DataTable` (`columnId`, `FilterDef`) | `/marketplace`, `/skills` 更新 |
| 卡片 grid | `grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4` | `/marketplace` 默认 view |
| 空状态 | `EmptyState` | catalog 搜索无结果等 |

### 0.3 可访问性标准

- 所有交互元素均须通过 `focus-visible:ring-2 ring-ring` (ADR-010 D)。
- Wizard step indicator 使用 `aria-current="step"`。
- Origin/Publication badge 的文本标签不是 sr-only，而是 visible（屏幕阅读器 + 视觉均获得相同信息）。
- AlertDialog（选择 overwrite/install_new_copy/keep_current）应明确显示 destructive 操作（`variant="destructive"` + 需要二次确认）。
- 键盘导航：卡片 → 按 Enter 进入 detail，卡片内 primary CTA → 可通过 Tab 聚焦。
- 不仅依靠颜色传达含义。所有状态 chip 都同时带文本 + 图标。

---

## 1. Page Inventory

| 路径 | 角色 | 入口 | 访问权限 |
|------|------|------|--------|
| `/marketplace` | catalog（tab: All / Agents / MCP / Skills / Installed） | 点击 Sidebar `Marketplace` | 所有已登录用户 |
| `/marketplace/[item-id]` | item detail（latest version, versions list, credential requirements, install CTA, ACL 管理(owner)） | 点击 catalog 卡片，或 share link | 根据可见性通过 `can_view_item` 的用户 |
| `/marketplace/installed` | 管理我的安装项（skill/mcp/agent 合并 — Phase 1 实际仅指 skill） | catalog tab `Installed` 或侧边栏直接链接 | 仅本人 |
| `/marketplace/publish` | publish wizard 入口 hub（通常从 `/skills/{id}` detail 的 `Publish to Marketplace` 按钮进入） | `/skills/{id}` `Publish` CTA | skill owner |
| `/marketplace/admin/moderation` | super_user moderation（未批准 public 项目队列） | Sidebar `Admin > Moderation`（仅 super_user visible） | `is_super_user=True` |
| `/skills`（现有页面更新） | 我的 skill 管理 — 新增 Origin/Publication 列 + Marketplace source 列 + `Publish` CTA | Sidebar `Skills` | 本人 |
| `/mcp-servers`（Phase 2 预留） | 仅新增 Origin/Publication 列（install/publish 在 Phase 2） | Sidebar `MCP Servers` | 本人 |

**路径决定理由**：
- 将 `/marketplace/[item-id]` 设为 root path（不把 resource_type segment 放入 path）— 相同 item_id 会自动确定 resource type，因此 URL 更短，share link copy 更简单。
- `/marketplace/publish` 不是 standalone wizard 页面，而采用 catalog header 的 `Publish` 按钮 → 选择 `/skills` → `PublishWizard` dialog 的形式。因为用户始终从自己 owned skill 出发进行 publish。
- `/marketplace/installed` 仅用 catalog tab `Installed` 也足够，但为支持在 dashboard 中“只想快速查看我安装的内容”的 workflow，仍保留独立 path。

### 1.1 侧边栏入口

在现有侧边栏项目（`Dashboard / Agents / Skills / MCP Servers / Models / Tools / Credentials / Usage`）之间新增：

```
Dashboard
Agents
Skills
MCP Servers
─────────────
Marketplace          [new]
  Catalog
  Installed
  Moderation         [super_user only]
─────────────
Models
Tools
Credentials
Usage
```

- `Marketplace` 为分组 header。点击子项时分别路由到 `/marketplace`、`/marketplace/installed`、`/marketplace/admin/moderation`。
- 分组默认展开。将 collapse 状态保存到 localStorage。
- 对非 super_user 用户隐藏 `Moderation`（后端 403 也会 guard — UI 可见性仅作辅助）。

---

## 2. 卡片 / 表格 / 详情信息结构

### 2.1 `MarketplaceCard` (catalog grid)

卡片组件的 slot（上→下，左→右）：

```
┌─ Card ────────────────────────────────────────────┐
│ ① [Icon]  ② Name                ⑩ [Install CTA]   │
│           ③ owner · resource    ⑪ Card menu (⋮)   │
│                                                   │
│ ④ Description (2-line clamp)                      │
│                                                   │
│ ⑤ [Origin]  ⑥ [Publication]  ⑦ [Credential chip]  │
│ ⑧ [Support level chip] ⑨ [latest version]         │
└───────────────────────────────────────────────────┘
```

| # | slot | 数据源 | 组件 |
|---|------|------------|---------|
| ① | Icon (24px) | `item.icon_url` 或 resource_type 默认图标（`Sparkles`/`Server`/`Bot`） | `Icon` |
| ② | Name | `item.name` | `text-sm font-semibold` |
| ③ | Owner + type | `is_system ? "System" : item.owner.email`, `resource_type` | `text-xs text-muted-foreground` |
| ④ | Description | `item.description` (2-line clamp via `line-clamp-2`) | `text-sm text-muted-foreground` |
| ⑤ | Origin | `item.origin_summary.kind`（catalog 中从 viewer 视角而非 owner 视角 derive — `built_in_k_skill`, `community`, `shared_with_me`, `created_by_me`） | `OriginBadge` |
| ⑥ | Publication | `item.publication_summary.state`（其他用户的 item 始终为 `published_*` 或 `disabled`。owner 卡片中也可能为 `draft`/`not_published`） | `PublicationBadge` |
| ⑦ | Credential summary | `item.credential_summary.status` | `CredentialSummaryChip` |
| ⑧ | Support level | `item.execution_profile.support_level` | `SupportLevelChip` |
| ⑨ | Latest version | `item.latest_version.version_label`, `created_at` (relative time) | `text-xs text-muted-foreground` |
| ⑩ | Primary CTA | 基于 `item.installation` 映射（§2.4） | `Button` (size `sm`) |
| ⑪ | Card menu | `View details` / `Copy link` / (owner) `Manage` / (super_user) `Toggle listed` / `Disable` | `DropdownMenu` |

**避免 N+1**：卡片显示的所有数据都来自单个 `GET /api/marketplace/items` 响应（`origin_summary`、`publication_summary`、`credential_summary`、`installation`、`execution_profile`、`latest_version` 均 embed）。页面不会按卡片发起额外调用。

### 2.2 卡片 CTA 状态映射 (PRD §11.1)

`primary_cta` 由 `(installation.installed, installation.status, installation.update_available, installation.dirty, item.is_disabled, execution_profile.support_level)` 决定。

| 优先级 | 条件 | Primary CTA 标签 | 操作 | variant |
|---------|------|-----------------|------|---------|
| 1 | `item.status='disabled'` | `Disabled` | disabled button (tooltip: "此项目已被禁用") | `outline`, disabled |
| 2 | `support_level in ('manual_only', 'browser_or_local')` AND NOT installed | `View details` | 跳转 item detail | `outline` |
| 3 | NOT installed | `Install` | 打开 InstallWizard | `default` |
| 4 | installed AND `status='needs_setup'` | `Set up` | 直接进入 InstallWizard step 2(credential) | `default` (warn variant) |
| 5 | installed AND `update_available` AND `dirty` | `Review update` | 打开 UpdateDialog（选择 3-strategy） | `outline` |
| 6 | installed AND `update_available` AND NOT `dirty` | `Update` | 打开 UpdateDialog（default `overwrite` highlight） | `default` |
| 7 | installed AND active | `Open` | 跳转 `/skills/{installed_resource_id}` | `outline` |
| 8 | installed AND `status='disabled'` | `Disabled` | tooltip | `outline`, disabled |

`Card menu` 新增项目：
- 全部：`View details`, `Copy link`
- Owner: `Manage`, `New version`, `Disable`
- Super_user: `Toggle listed`, `Disable`
- Installed: `Uninstall`

### 2.3 卡片变体（按 tab）

| tab | 卡片 grid 输出 |
|----|---------------|
| `All` | 不区分 resource_type 的全部项目（Phase 1 实际仅指 skill）。卡片 ② 旁显示 type badge |
| `Agents` (Phase 2+) | 空状态 + "Coming in Phase 3" 文本 + 卡片 grid 禁用 |
| `MCP` (Phase 2+) | 空状态 + "Coming in Phase 2" 文本 + 卡片 grid 禁用 |
| `Skills` | Phase 1 主 view。默认排序：`is_listed_first, then created_at DESC` |
| `Installed` | 仅 viewer 本人的 installations。使用相同卡片组件，但 `installation` slot 始终有值，因此 CTA 为 `Open`/`Update`/`Set up`/`Review update`/`Disabled` 之一 |

### 2.4 `MarketplaceFilterBar`（catalog 顶部）

```
[Search input            ] [Resource type ▾] [Source ▾] [Visibility ▾] [Credential ▾] [Install state ▾] [Support ▾]
                                                                                       ⤷ "Reset filters" link
```

| filter | 组件 | API param | 选项 |
|------|---------|----------|------|
| 搜索 | `SearchInput` | `q` | free text. debounce 250ms |
| Resource type | `Select` | `resource_type` | All / Skill / MCP(Phase 2) / Agent(Phase 3) |
| Source | `Select` | `source_kind` | All / `user` / `k-skill` / `import` / `system_seed` |
| Visibility | `Select` | `visibility` | All / public / restricted / private / unlisted / system。Phase 1 中 catalog 通常仅指 public+restricted+system。owner 也能看到自己的 private |
| Credential | `Select` | `credential_status` | All / `none` / `required` / `optional` / `hosted_proxy` / `manual_login` |
| Install state | `Select` | `install_state` | All / `not_installed` / `installed` / `needs_setup` / `update_available` / `dirty` |
| Support | `Select` | `support_level` | All / `ready_python` / `proxy_http` / `node_package` / `browser_or_local` / `manual_only` |
| Locale | `Select` (optional, advanced) | `locale` | All / ko-KR / en-US |

**Listed toggle (super_user only)**：在右侧单独放置 `Show unlisted` toggle。追加 `is_listed=false` query。普通用户不可见。

默认排序 `?sort=`（Phase 1 不支持 server-side sort → frontend 默认 `is_listed_first, then created_at DESC`）。

### 2.5 catalog header 操作

```
┌ /marketplace ────────────────────────────────────────┐
│ Marketplace                              [Publish ▾] │
│ Discover and install shared skills…                  │
│                                                      │
│ [Tabs: All  Skills  Agents  MCP  Installed]          │
└──────────────────────────────────────────────────────┘
```

`Publish ▾` menu：
- `Publish a skill` → 跳转 `/skills` 页面 + 提示 toast（"Choose a skill to share"）
- `Request k-skill sync` (super_user only) → `/marketplace/admin/moderation`（k-skill status 区域）

### 2.6 `/marketplace/[item-id]` Detail 页面

```
┌ Breadcrumb: Marketplace › Skills › {name} ────────────────────────┐
│ ┌─ Hero ──────────────────────────────────────────────────────────┐│
│ │ [Icon] {name}                                  [Primary CTA]    ││
│ │        {owner · resource_type · locale}        [Card menu ⋮]    ││
│ │ [Origin] [Publication] [Credential] [Support] [latest version]  ││
│ │ Description (full)                                              ││
│ └─────────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌─ Left column ─────────────┐  ┌─ Right column ─────────────────┐ │
│ │ ## Credential requirements │  │ ## Versions                    │ │
│ │ (CredentialRequirementList)│  │ (VersionsTable)                │ │
│ │                            │  │                                │ │
│ │ ## Execution profile       │  │ ## Source                      │ │
│ │ - runner: python           │  │ - source_kind: k-skill         │ │
│ │ - requires_network         │  │ - upstream: github.com/...     │ │
│ │ - notes: …                 │  │ - commit: 80303f5              │ │
│ │                            │  │                                │ │
│ │ ## Tags / Categories       │  │ ## Shared with                 │ │
│ │ (badges)                   │  │ (restricted only — ACL chips)  │ │
│ └────────────────────────────┘  └────────────────────────────────┘ │
│                                                                   │
│ ## Owner / Moderation actions (conditional)                       │
│   - Owner: Edit metadata, Manage ACL, Publish new version, Disable │
│   - Super_user: Toggle listed, Disable                            │
└───────────────────────────────────────────────────────────────────┘
```

**Owner actions row** (only when current_user == item.owner_user_id):
- `Edit metadata` — name/description/tags/icon `PATCH /api/marketplace/items/{id}`
- `Manage shared users` — restricted ACL `POST/DELETE acl`
- `Publish new version` — PublishWizard short flow（仅 release_notes）
- `Disable` — AlertDialog 确认后 `POST /disable`

**Super_user actions row**:
- `Toggle listing` — `POST /admin/items/{id}/listed`
- `Disable` — `POST /admin/items/{id}/disable`

### 2.7 `/skills` 页面更新（DataTable 列）

| 列 | 类型 | 数据 |
|------|------|--------|
| Name | text | `skill.name` (font-medium) |
| Kind | Badge | `text` / `package` |
| Origin | `OriginBadge` | `skill.origin_summary.kind` |
| Marketplace | composite | `skill.publication_summary.state` (PublicationBadge) + 若存在 `skill.source_marketplace_item_id` 则显示 source name link |
| Credential | `CredentialSummaryChip` | `skill.credential_summary.status`（仅 status — required count 在 detail 中） |
| Used by | number | `skill.used_by_count` (agent count) |
| Updated | relative date | `skill.updated_at` |

**行操作** (DataTable row menu)：
- Open detail（现有）
- `Publish to Marketplace`（仅 publication_state ∈ `not_published` 时）
- `Update from marketplace` (`installation.update_available=true`)
- `Sync now`（super_user only — k-skill 项目）

### 2.8 `/mcp-servers` 页面更新（Phase 2 预留列）

| 列 | 类型 | 数据 |
|------|------|--------|
| Name | text | `mcp.name` |
| Transport | Badge | `stdio` / `sse` / `streamable_http` |
| Origin | `OriginBadge` | `mcp.origin_summary.kind`（Phase 1 始终为 `created_by_me`） |
| Marketplace | `PublicationBadge` | `mcp.publication_summary.state`（Phase 1 全部为 `not_published`） |
| Credential | `CredentialSummaryChip` | reserved |
| Health | StatusChip | M26 health_status |
| Updated | relative date | `mcp.updated_at` |

Phase 1 会显示 origin/publication 列，但 install/publish CTA 禁用。tooltip: "Coming in Phase 2"。

---

## 3. 核心用户流程

### 3.1 流程 1 — PRD §10.1 安装 built-in k-skill (no-credential)

**入口触发**：`/marketplace` Skills tab → `korean-spell-check` 卡片 → 点击 `Install`。

**步骤**：

1. 打开 `InstallWizard`（DialogShell size `lg`, height `auto`）。
   - Header: icon, title "Install korean-spell-check", description "将韩语拼写检查 skill 安装到我的账户。"
   - Right action: `<OriginBadge kind="built_in_k_skill" />` + `<CredentialSummaryChip status="none" />`
2. **Step 1: Review**.
   - 页面：
     - Resource type, latest version, source(`k-skill@80303f5`), execution profile (`ready_python · requires_network`)
     - 提示“此 skill 不需要 credential。”（status=`none`）
     - Optional `name_override` input (placeholder: `korean-spell-check`)
   - Footer: `Cancel` | `Install`
3. **Step 2: 无**（无需 credential，因此立即 install）。
4. **Install 操作**：`POST /api/marketplace/items/{item_id}/install` body `{install_mode: "reuse_or_update", install_missing_credentials: "needs_setup", credential_bindings: {}}`。
5. **成功**：关闭 Dialog + toast "Installed. Open in Skills"（操作：跳转 `/skills/{installed_resource_id}`）。卡片 CTA 变为 `Open`（optimistic + invalidate `useMarketplaceItem` query）。

**失败路径**：

| 错误代码 | 处理 |
|----------|------|
| `marketplace_item_not_found` (404) | 关闭 Dialog + redirect to `/marketplace` + toast "找不到此项目或您没有访问权限。"（因 enumeration oracle，无权限也使用相同消息） |
| `marketplace_item_disabled` (409) | Dialog 内显示 ErrorState + "此项目已被禁用。请联系管理员。" + `Close` 按钮 |
| `marketplace_invalid_package` (400) | ErrorState + 不显示 debug 信息的 generic "包验证失败" + 提示联系管理员 |
| network 错误 | toast + retry 按钮 |

### 3.2 流程 2 — PRD §10.2 安装 credential required skill (`srt-booking`)

**入口触发**：`/marketplace` → `srt-booking` 卡片 → 点击 `Install`。

**步骤**：

1. 打开 `InstallWizard`（size `lg`, height `fixed`）。使用 Sidebar（4-step indicator）。
   - 4-step indicator: `① Review · ② Credentials · ③ Confirm · ④ Done`
2. **Step 1: Review**.
   - Hero summary (version, source, support level)
   - `<CredentialSummaryChip status="required" requiredCount={1} missingRequiredCount={1} />`
   - 显示："此 skill 需要 SRT 账户凭据。"
   - Footer: `Cancel` | `Next`
3. **Step 2: Credentials**.
   - 每行一个 `CredentialRequirementRow`（compound: `requirement_key`, definition icon, label, description, fields chip, scope）。
   - 每个 row 使用 Combobox：通过 `useCredentialsByDefinition(definition_key)` 提供 user 的兼容 credential 候选 + `+ Create new credential` 项。
   - 若 Combobox 为空，则显示 inline empty state："没有兼容的 credential。新建"
   - 选择 `+ Create new credential` 时，在 right pane 显示 inline `<DynamicFieldsForm>`（复用现有 `/credentials` 组件）— 保存时 `POST /api/credentials/` 后自动选择。
   - Optional skip toggle："现在跳过，稍后再连接（以 needs_setup 安装）" → 发送 `install_missing_credentials="needs_setup"`
   - Footer：`Back` | `Next`（required 全部 binding 或 skip toggle ON 时启用）
4. **Step 3: Confirm**.
   - 摘要卡片：skill name, version, name_override, credential bindings 表（`requirement_key → credential name`）
   - 点击 "Install" 后将执行以下操作：
     - 创建用户 owned skill row (data/skills/<id>/)
     - 创建 skill_credential_bindings row
     - origin: `built_in_k_skill`
   - Footer: `Back` | `Install`
5. **Step 4: Done**.
   - Success state + `<InstallationStatusChip status={installation.status} />`
   - 后续操作：`Open in Skills` 或 `Attach to agent`（link to `/agents`）。

**失败路径**：

| 错误 | 步骤 | 处理 |
|------|------|------|
| `marketplace_credential_required` (409, install_missing_credentials="reject" 时) | Step 3 | 返回 Step 2 + 将缺失的 requirement row 标红 outline + 提示 "此凭据为必填项" |
| `marketplace_credential_mismatch` (400) | Step 3 | 对应 requirement row inline error "所选 credential 类型不匹配（可选类型：srt_account）" + 引导重新选择 Combobox |
| 创建 credential 时 422 (definition validation) | Step 2 inline form | 显示 DynamicFieldsForm 的标准 inline error |
| `marketplace_item_disabled` (409) | Step 1~3 | 整个 wizard ErrorState + Close |
| network/500 | toast + 保持当前 Step + Retry |

**accessibility**：Step indicator 使用 `role="list"` + 每个 step `aria-current="step"`。关闭 Wizard 时若存在 dirty 数据，则弹出 confirm AlertDialog（"已输入的内容将丢失"）。

### 3.3 流程 3 — PRD §10.3 用户分享自己的 skill（5-step publish wizard）

**入口触发**：`/skills/{skill_id}` detail dialog → 右上角 `Publish to Marketplace` 按钮。或 `/skills` 页面 row menu 的 `Publish to Marketplace`。

**步骤**：

1. 打开 `PublishWizard`（DialogShell size `xl`, height `tall`, Split layout）。
   - Sidebar (5-step indicator):
     - `① Review files · ② Metadata · ③ Credentials · ④ Visibility · ⑤ Confirm`
2. **Step 1: Review files**.
   - Skill package tree（复用 `<SkillPackageTree>`）— 展示哪些文件会被 packaging。
   - Top alert："发布到 Marketplace 之前会执行 secret 检查。"
   - 如果 frontend 可以 pre-scan（客户端较难 — 依赖服务器实际响应），则此步骤仅做提示。
   - Footer: `Cancel` | `Next`
3. **Step 2: Metadata**.
   - Form fields: `name`, `description`, `tags` (`Combobox` multi), `categories` (`Combobox` multi), `icon_url`(optional), `release_notes`
   - validation: name required, description recommended（提示 ≥30 个字符 — 不 block）
   - Footer: `Back` | `Next`
4. **Step 3: Credentials**.
   - PRD/Spec §11.5 — 显示当前 skill 的 `credential_requirements`。
   - 用户可 manually 添加/编辑 requirement（env_map 位于 advanced toggle 内）。
   - 每个 requirement row：`key`, `definition_key` (Select from registered definitions), `label`, `required` toggle, `scope` (`user`/`system_dependency`/`manual`), `injection`（固定 env）
   - `+ Add credential requirement` 按钮
   - **Beginner mode** (default ON)：留空并显示一行 "此 skill 不需要 credential"，可直接 Next。
   - Footer: `Back` | `Next`
5. **Step 4: Visibility**.
   - `Visibility` Select: `private` / `restricted` / `public` / `unlisted`
   - 选择 `private`：无额外 input
   - 选择 `restricted`：`acl_user_ids` Combobox (search by email) — 至少需要 1 人（`marketplace_acl_required`）
   - 选择 `public`：提示 alert "公开 publish 后，若要在 catalog 搜索中展示，仍需管理员批准。(Unlisted from search until approved)"
   - 选择 `unlisted`：提示 alert "只有持有直接链接的用户才能访问。"
   - Footer: `Back` | `Next`
6. **Step 5: Confirm**.
   - 摘要：所有输入值
   - "将执行以下操作：" 操作列表（创建/更新 item，创建新 version，创建 ACL row（如适用），创建 publication link）
   - Footer: `Back` | `Publish`
7. **Publish 操作**：`POST /api/marketplace/items/from-skill/{skill_id}` body `PublishSkillIn`。
8. **成功**：关闭 Dialog + redirect to `/marketplace/[item_id]` + toast "Published. Visibility: {state}"。

**失败路径**：

| 错误 | 步骤 | 处理 |
|------|------|------|
| `marketplace_secret_detected` (400) | Step 5（服务器响应） | 返回 Step 1 + 红色 alert + secret 检测文件列表（`detail.findings[].path` + pattern）。"移除 secret 后重试。" |
| `marketplace_acl_required` (400) | Step 4 client-validation 预先拦截。若收到服务器响应，则返回 Step 4 + 强调 acl combobox |
| `marketplace_invalid_visibility` (400) | Step 5（重新 publish 时 visibility 无法转换） | 返回 Step 4 + 提示可选 visibility |
| `marketplace_manage_forbidden` (403) | Step 5（重新 publish 时权限已被收回） | toast + 关闭 dialog + 返回 skills 页面 |
| `marketplace_invalid_package` (400) | Step 5 | 返回 Step 1 + "包验证失败：缺少 SKILL.md" 等具体原因 |

**dirty 输入保护**：按 ESC/Close 时弹出 confirm AlertDialog。

### 3.4 流程 4 — PRD §10.4 restricted ACL 分享

**入口触发**：PublishWizard Step 4 选择 `restricted` → Step 5 publish。或现有 item detail 的 `Manage shared users`。

**Manage shared users 流程**：

1. `/marketplace/[item-id]` (owner view) → `Manage shared users` 按钮。
2. 打开 `SharedUsersDialog`（DialogShell size `md`）。
3. 当前 ACL chips 列表（`<UserChip email="…" onRemove={…} />`）。
4. `+ Add user` Combobox — email search (`GET /api/users?search=…`).
5. Add 时 `POST /api/marketplace/items/{item_id}/acl` `{user_ids: [uuid], permission: "install"}`。
6. Remove 时 `DELETE /api/marketplace/items/{item_id}/acl/{user_id}`。
7. **失败：`marketplace_acl_required`** — 尝试 remove 最后一个 user 时显示 inline error "restricted item 至少需要 1 个共享对象。请先将 visibility 改为 private。"

**目标用户侧体验**：

- catalog 中显示 item 卡片（`OriginBadge=shared_with_me`, `PublicationBadge=published_restricted`）。
- 显示 Install CTA。进入正常 install 流程。
- 被移除后：卡片从 catalog 消失。已 install 的 copy 仍保留在 `/skills` 中（Spec §7.5 D7）。

### 3.5 流程 5 — PRD §10.5 应用 update available（overwrite vs new copy）

**入口触发**：`/marketplace` 或 `/skills` 中 `installation.update_available=true` 的项目 → `Update`（dirty 时为 `Review update`）CTA。

**步骤（clean update — dirty=false）**：

1. 打开 `UpdateDialog`（DialogShell size `md`, height `auto`）。
   - Header: title "Update korean-spell-check", description "有 v1 → v2 更新。"
2. **Body**:
   - 比较当前 version vs latest version 元数据（显示 release_notes）
   - 3-strategy 卡片（radio group）：
     - **Overwrite** (`overwrite`, default) — "将当前安装项替换为最新版本。个人修改将丢失。"（dirty=false 时提示无损失）
     - **Install as new copy** (`install_new_copy`) — "保留当前安装项，并额外安装一个新副本。"
     - **Keep current** (`keep_current`) — "不更新，保持当前状态。"（仅 dismiss + remember）
3. **Confirm**: `POST /api/marketplace/installations/{installation_id}/update` body `{strategy}`.
4. **成功**：toast "Updated to v2" + invalidate `useSkill(installed_skill_id)` + `useMarketplaceItem(item_id)`。

**Dirty update 路径（dirty=true）**：

1. CTA 为 `Review update`。
2. 进入 UpdateDialog 时顶部显示 `<UpdateAvailableBanner variant="dirty" />`："此安装项有过直接修改记录。覆盖后更改将丢失。"
3. `Overwrite` radio 旁显示 `<Badge variant="destructive">Destructive</Badge>`。
4. Confirm 时选择 `Overwrite` 会弹出 AlertDialog 第 2 次确认（"您将失去所有更改。是否继续？"）。

**失败**：

| 错误 | 处理 |
|------|------|
| `marketplace_dirty_installation` (409，未指定 strategy 时调用 — 后端 guard) | redirect 到 UpdateDialog（强制选择 strategy） |
| `marketplace_version_not_found` (404) | toast "找不到版本信息。请刷新后重试。" + invalidate |

### 3.6 流程 6（附加）— PRD §10.7 super_user moderation 批准

**入口触发**：Sidebar `Admin > Moderation` (super_user only) → `/marketplace/admin/moderation`。

**页面结构**：

```
┌ Page header: Moderation                          ┐
│ Public items pending listing approval            │
│                                                  │
│ [Tabs: Pending(N) · Disabled · k-skill status]   │
│                                                  │
│ DataTable                                        │
│  Name · Owner · Type · Created · Credential · ⋯  │
│  Row CTA: Review · Approve listing · Disable     │
└──────────────────────────────────────────────────┘
```

**Tab 1: Pending** — `GET /api/marketplace/admin/moderation` (is_listed=False AND visibility=public AND status=published).

**行操作**：
- `Review` → `/marketplace/[item-id]`（super_user view。owner action row + super_user action row 均显示）
- `Approve listing` → AlertDialog confirm → `POST /api/marketplace/admin/items/{item_id}/listed` `{is_listed: true}` → row 从 Pending tab 消失 + toast "Listed"
- `Disable` → AlertDialog confirm → `POST /api/marketplace/admin/items/{item_id}/disable` → toast "Disabled"

**Tab 2: Disabled** — `?status=disabled` filter。row 操作 `Re-enable`。

**Tab 3: k-skill status** — `GET /api/marketplace/admin/k-skill/sync`（查询 status。实际 sync 使用 CLI）。页面：
- 最后 sync 时间、upstream ref、item count
- 提示代码块：`uv run python -m app.scripts.sync_k_skill --ref main`
- 提示 "Sync 只能在 CLI 中执行。"（Spec §D12）

**失败**：
- `marketplace_manage_forbidden` (403) — 权限被收回时。redirect to `/marketplace` + toast。

---

## 4. State Machine 与组件映射

### 4.1 Visibility × Actor × Status UI affordance 矩阵

将 Spec §12.1 矩阵映射为 UI affordance。标记：`L`=List（catalog 展示），`D`=进入 Detail 页面，`I`=Install CTA，`M`=Manage 操作，`★`=Listed toggle。

| Status | Visibility | Owner | ACL user | Unrelated | Super_user |
|--------|-----------|-------|---------|-----------|------------|
| draft | private | L·D·M | — | — | D·M |
| draft | restricted | L·D·M | D·I | — | D·M |
| published | private | L·D·I·M | — | — | D·M |
| published | restricted | L·D·I·M | L·D·I | — | L·D·M |
| published | public+listed | L·D·I·M | L·D·I | L·D·I | L·D·M·★ |
| published | public+unlisted | L·D·I·M | L·D·I | D·I (link only) | L·D·M·★ |
| published | unlisted | L·D·I·M | — | D·I (link only) | L·D·M |
| published | system | L·D·I | L·D·I | L·D·I | L·D·M·★ |
| deprecated | * | L·D·M | L·D | L·D (badge) | L·D·M |
| disabled | * | D·M | — | — | D·M |

**渲染规则**：

- 没有 `L` 时，不显示在 `/marketplace` catalog 卡片 grid 中。detail 直接 URL 是否可进入由 `D` 单独决定。
- 没有 `I` 时，卡片/detail CTA fallback 为 `View details`(`outline`)。
- 没有 `M` 时，不渲染 owner action row 本身。
- 没有 `★` 时，super_user action row 的 `Toggle listing` 按钮禁用/隐藏。
- `disabled` × `unrelated` 时，detail 本身返回 404（enumeration oracle）。

### 4.2 Installation Status × UI 显示

| `installation.status` | 卡片右上 chip | 卡片 CTA | detail banner |
|----------------------|----------------|---------|--------------|
|（无 — not installed）|（无）| `Install` | (none) |
| `active` | `Installed` (`status-success`) | `Open` 或 `Update` |（无）|
| `needs_setup` | `Needs setup` (`status-warn`) + 锁图标 | `Set up` | yellow banner "此安装项需要连接凭据。[Open setup]" |
| `disabled` | `Disabled` (`destructive`) | `Disabled` (disabled) | red banner "此安装项已被禁用。" |
| `uninstalled` |（卡片中不显示）| `Install` |（uninstalled 在 catalog 中看起来像 not_installed）|

`update_available` 时新增 chip：`Update available` (`status-info`)。
`is_dirty` 时新增 chip：`Modified` (`status-accent`) — 表示 installed copy 被直接修改过。

### 4.3 组件映射（新增 / 复用）

**新增组件**（`frontend/src/components/marketplace/`）：

| 组件 | 文件 | 职责 |
|---------|------|------|
| `MarketplaceCard` | `marketplace-card.tsx` | catalog/installed tab 使用的单一 item 卡片 |
| `MarketplaceFilterBar` | `marketplace-filter-bar.tsx` | 搜索 + filter select 组合 |
| `OriginBadge` | `origin-badge.tsx` | 渲染 6 个 origin kind |
| `PublicationBadge` | `publication-badge.tsx` | 渲染 8 个 publication state |
| `CredentialSummaryChip` | `credential-summary-chip.tsx` | none/optional/required/hosted_proxy/manual_login 5 status |
| `SupportLevelChip` | `support-level-chip.tsx` | 6 个 support level（`ready_python` 等） |
| `InstallationStatusChip` | `installation-status-chip.tsx` | active/needs_setup/disabled/uninstalled + update_available + dirty 组合 |
| `InstallWizard` | `install-wizard.tsx` | 4-step (Review/Credentials/Confirm/Done) |
| `UpdateDialog` | `update-dialog.tsx` | 3-strategy radio (overwrite/new_copy/keep_current) |
| `PublishWizard` | `publish-wizard.tsx` | 5-step (Files/Metadata/Credentials/Visibility/Confirm) |
| `SharedUsersDialog` | `shared-users-dialog.tsx` | ACL 添加/删除 |
| `CredentialRequirementRow` | `credential-requirement-row.tsx` | InstallWizard Step 2 / Publish Step 3 共用 row |
| `UpdateAvailableBanner` | `update-available-banner.tsx` | detail 顶部/卡片顶部 banner（variants: `default`, `dirty`, `disabled_source`） |
| `VersionsTable` | `versions-table.tsx` | item detail 右侧 column versions list |
| `CredentialRequirementList` | `credential-requirement-list.tsx` | item detail 左侧 column requirement 列表 |
| `MarketplaceSourceLink` | `marketplace-source-link.tsx` | `/skills` row + skill detail 中的 source item link（small text + chevron） |

**复用组件**（不修改）：

- `Card`, `CardHeader`, `CardTitle`, `CardDescription` (ui/card)
- `Dialog`, `DialogShell`, `Sheet` (shared)
- `Button`, `Badge`, `Input`, `Textarea`, `Select`, `Combobox`(custom — `CommandList` pattern)
- `DataTable`, `FilterDef` (ui/data-table)
- `Tabs`, `LineTabs`
- `AlertDialog`
- `EmptyState`, `ErrorState`, `StatusChip`, `PageHeader`, `SearchInput`
- `DynamicFieldsForm`（credential 新建 inline）
- `SkillPackageTree` (publish wizard step 1)
- `Icon`, `Skeleton`, `Tooltip`

### 4.4 Badge 视觉规范

#### OriginBadge (PRD §6 — Resource Origin)

| kind | label | 图标 (lucide) | 颜色 (token) |
|------|-------|---------------|-----------|
| `created_by_me` | Created by me | `Pencil` | `bg-muted text-foreground` |
| `imported_by_me` | Imported by me | `Download` | `bg-muted text-foreground` |
| `built_in_k_skill` | Built-in · k-skill | `Sparkles` | `bg-primary/15 text-primary-strong` |
| `shared_with_me` | Shared by {name} | `Users` | `bg-status-accent/10 text-status-accent` |
| `community` | Community | `Globe` | `bg-status-info/10 text-status-info` |
| `system_seed` | System | `Cog` | `bg-muted text-foreground` |

#### PublicationBadge (PRD §6 — Publication State)

| state | label | 图标 | 颜色 |
|-------|-------|--------|----|
| `not_published` | Not published | `EyeOff` | `bg-muted text-muted-foreground` |
| `draft` | Draft | `FilePen` | `bg-muted text-foreground` |
| `published_private` | Private | `Lock` | `bg-muted text-foreground` |
| `published_restricted` | Restricted | `UserCheck` | `bg-status-accent/10 text-status-accent` |
| `published_public_listed` | Listed | `CheckCircle2` | `bg-status-success/10 text-status-success` |
| `published_public_unlisted` | Unlisted (pending) | `Hourglass` | `bg-status-warn/10 text-status-warn` |
| `published_unlisted` | Unlisted (link) | `Link` | `bg-status-info/10 text-status-info` |
| `disabled` | Disabled | `Ban` | `bg-destructive/10 text-destructive` |

#### CredentialSummaryChip

| status | label | 图标 | 颜色 |
|--------|-------|--------|----|
| `none` | No credential | `CircleDashed` | `bg-muted text-muted-foreground` |
| `optional` | Optional credential | `Plus` | `bg-muted text-foreground` |
| `required` | Credential required | `Key` | `bg-status-warn/10 text-status-warn` |
| `hosted_proxy` | Hosted proxy | `Cloud` | `bg-status-info/10 text-status-info` |
| `manual_login` | Manual login | `LogIn` | `bg-status-accent/10 text-status-accent` |

若 `missing_required_count > 0`，则在 chip 上添加红色 dot indicator（visually `after:bg-destructive`）。

#### SupportLevelChip

| level | label | 颜色 |
|-------|-------|----|
| `ready_python` | Python ready | `bg-status-success/10 text-status-success` |
| `proxy_http` | Proxy required | `bg-status-info/10 text-status-info` |
| `node_package` | Node required | `bg-muted text-muted-foreground` |
| `browser_or_local` | Browser/local | `bg-status-warn/10 text-status-warn` |
| `manual_only` | Manual only | `bg-status-warn/10 text-status-warn` |
| `disabled` | Unsupported | `bg-destructive/10 text-destructive` |

---

## 5. API 调用映射

整理各页面/wizard 调用的 backend endpoint。通过 `lib/api/marketplace.ts` 和 `lib/hooks/useMarketplace*.ts` 实现。

### 5.1 按页面 API 映射

| 页面/组件 | hook | endpoint | invalidation |
|---------------|------|----------|--------------|
| `/marketplace` catalog | `useMarketplaceItems(filters)` | `GET /api/marketplace/items?…` | install/uninstall/update 后 |
| `/marketplace` Installed tab | `useMarketplaceItems({installed: true})` | 相同（filter 中 `installed=true`） | install/uninstall/update 后 |
| `/marketplace/[item-id]` | `useMarketplaceItem(item_id)`, `useMarketplaceVersions(item_id)` | `GET /api/marketplace/items/{item_id}` + `GET /api/marketplace/items/{item_id}/versions` | publish/update_metadata/acl/disable 后 |
| `/marketplace/admin/moderation` | `useModerationQueue()`, `useKSkillStatus()` | `GET /api/marketplace/admin/moderation`, `GET /api/marketplace/admin/k-skill/sync` | listed toggle/disable 后 |
| InstallWizard | `useInstallItem()` | `POST /api/marketplace/items/{item_id}/install` | item + skills + installations |
| UpdateDialog | `useUpdateInstallation()` | `POST /api/marketplace/installations/{installation_id}/update` | item + skill + installation |
| Uninstall | `useUninstall()` | `DELETE /api/marketplace/installations/{installation_id}?delete_resource=…` | item + skills |
| PublishWizard | `usePublishSkill()` | `POST /api/marketplace/items/from-skill/{skill_id}` | items + skills(publication_summary) |
| New version | `usePublishNewVersion()` | `POST /api/marketplace/items/{item_id}/versions/from-skill/{skill_id}` | item + versions |
| Metadata edit | `useUpdateItemMetadata()` | `PATCH /api/marketplace/items/{item_id}` | item |
| ACL add | `useAddItemAcl()` | `POST /api/marketplace/items/{item_id}/acl` | item |
| ACL remove | `useRemoveItemAcl()` | `DELETE /api/marketplace/items/{item_id}/acl/{user_id}` | item |
| Disable (owner) | `useDisableItem()` | `POST /api/marketplace/items/{item_id}/disable` | items + item |
| Admin listed toggle | `useAdminToggleListed()` | `POST /api/marketplace/admin/items/{item_id}/listed` | items + moderation queue |
| Admin disable | `useAdminDisableItem()` | `POST /api/marketplace/admin/items/{item_id}/disable` | items + moderation queue |
| Publication status（我的面板）| `usePublicationStatus()` | `GET /api/marketplace/publication-status` | publish 后 |
| Skill credential reqs | `useSkillCredentialRequirements(skill_id)` | `GET /api/skills/{skill_id}/credential-requirements` | install 后 |
| Skill credential bindings | `useSkillCredentialBindings(skill_id)` | `GET /api/skills/{skill_id}/credential-bindings` | bind/unbind 后 |
| Bind credential | `useSetSkillCredentialBinding()` | `PUT /api/skills/{skill_id}/credential-bindings/{key}` | bindings + skill(needs_setup→active) |
| Unbind | `useUnsetSkillCredentialBinding()` | `DELETE /api/skills/{skill_id}/credential-bindings/{key}` | bindings + skill |

### 5.2 响应 shape 示例

`MarketplaceItemOut` 响应（用于 catalog 卡片/detail）：

```json
{
  "id": "uuid",
  "resource_type": "skill",
  "name": "korean-spell-check",
  "slug": "korean-spell-check",
  "description": "韩语拼写检查…",
  "visibility": "system",
  "status": "published",
  "is_system": true,
  "is_listed": true,
  "latest_version": {
    "id": "uuid",
    "version_label": "0.1.0",
    "version_number": 1,
    "content_hash": "sha256…",
    "source_commit": "80303f5",
    "created_at": "2026-05-15T…"
  },
  "credential_summary": {
    "status": "none",
    "required_count": 0,
    "optional_count": 0,
    "missing_required_count": 0
  },
  "execution_profile": {
    "support_level": "ready_python",
    "runners": ["python"],
    "requires_network": true
  },
  "origin_summary": {
    "kind": "built_in_k_skill",
    "label": "Built-in · k-skill",
    "source_name": "k-skill",
    "marketplace_item_id": "uuid",
    "marketplace_version_id": "uuid"
  },
  "publication_summary": {
    "state": "published_public_listed",
    "item_id": "uuid",
    "visibility": "system",
    "status": "published",
    "is_listed": true,
    "latest_version_id": "uuid",
    "version_number": 1,
    "shared_user_count": 0
  },
  "installation": {
    "installed": false,
    "installation_id": null,
    "installed_resource_id": null,
    "status": null,
    "update_available": false,
    "dirty": false
  }
}
```

`CredentialRequirementOut` (Step 2 Credentials):

```json
{
  "key": "srt_account",
  "definition_key": "srt_account",
  "required": true,
  "label": "SRT account",
  "description": "SRT 登录凭据",
  "fields": ["username", "password"],
  "injection": "env",
  "scope": "user"
}
```

`InstallationSummary`（卡片右上 chip）：

```json
{
  "installed": true,
  "installation_id": "uuid",
  "installed_resource_id": "uuid",
  "status": "needs_setup",
  "update_available": true,
  "dirty": false
}
```

### 5.3 错误代码 → UI 处理矩阵

标记 — Layer: `T`=Toast, `B`=Banner, `IF`=Inline Field error, `M`=Modal/ErrorState, `R`=Redirect。

| code | HTTP | 发生位置 | Layer | UX 文案（简体中文）| 后续操作 |
|------|------|----------|-------|----------------|----------|
| `marketplace_item_not_found` | 404 | catalog/detail/install | M+R | "找不到此项目或您没有访问权限。" | redirect 到 `/marketplace` |
| `marketplace_version_not_found` | 404 | install/update | T | "找不到版本信息。请刷新后重试。" | invalidate item query |
| `marketplace_install_forbidden` | 404 | install | M+R |（与 item_not_found 相同消息 — enumeration 一致）| redirect |
| `marketplace_manage_forbidden` | 403 | manage 操作 | T+R | "您没有权限执行此操作。" | `/marketplace` redirect（离开 manage view）|
| `marketplace_item_disabled` | 409 | install/update | B+M | "此项目已被禁用。" | 关闭 wizard / Close 按钮 |
| `marketplace_invalid_visibility` | 400 | publish（visibility 转换）| IF | "不允许进行此 visibility 变更。" | 返回 Step 4，提示可选选项 |
| `marketplace_acl_required` | 400 | publish/acl-remove | IF | "restricted 发布至少需要 1 个共享对象。" | Step 4(publish) / inline error(SharedUsersDialog) |
| `marketplace_invalid_package` | 400 | publish | M | "包验证失败：请检查 SKILL.md。" | 返回 Step 1 |
| `marketplace_secret_detected` | 400 | publish/upload | M+IF | "检测到包含 Secret 的文件。请移除后重试。"（+ findings 列表）| 返回 Step 1，突出文件列表 |
| `marketplace_credential_required` | 409 | install/runtime | B+IF | "运行此 skill 前需要连接凭据。" | 直接进入 InstallWizard Step 2 + 突出 required row |
| `marketplace_credential_mismatch` | 422 | install/binding PUT | IF | "所选 credential 类型不匹配（需要：{definition_key}）。" | 重新选择 Combobox |
| `marketplace_dirty_installation` | 409 | update | M | "此安装项已被修改。请选择更新方式。" | 强制进入 UpdateDialog |

**其他标准**：
- 401（auth 过期）— global interceptor redirect 到 `/auth/login`（复用现有 pattern）。
- 5xx — toast "发生临时错误。请稍后重试。" + retry 按钮（可用位置）。

---

## 6. Edge Case 与空状态

### 6.1 空状态（EmptyState 组件）

| 情况 | 页面 | 图标 | headline | 辅助文本 | CTA |
|------|--------|--------|---------|------------|-----|
| catalog 本身为空（system seed 前、k-skill sync 前）| `/marketplace` | `Sparkles` | "暂无共享项目" | "分享自己的 skill 或由管理员同步 k-skill 后，会显示在这里。" |（owner）`Publish a skill` 或（super_user）k-skill 提示 |
| 搜索无结果 | `/marketplace` | `Search` | "没有结果" | "请调整 filter 或搜索词。" | `Reset filters` |
| Installed tab 为空 | `/marketplace/installed` | `Package` | "暂无已安装项目" | "去 catalog 安装喜欢的项目吧。" | `Browse catalog` → `/marketplace` |
| Pending(moderation) 队列为空 | `/marketplace/admin/moderation` | `CheckCircle2` | "没有待处理项目" | "所有公开发布项目均已批准。" | — |
| 无 Versions（仅 draft）| item detail | `FilePen` | "暂无已 publish 的版本" |（owner）"请在 PublishWizard 中创建第一个版本。" |（owner）`Publish first version` |
| 用户没有 owned skill 却进入 publish | `/marketplace` Publish menu | `Plus` | "没有可分享的 skill" | "请先在 Skills 中创建或导入 skill。" | 跳转 `/skills` |
| 无兼容 credential（InstallWizard Step 2）| InstallWizard | `KeyRound` | "没有兼容的凭据" | "此 skill 需要 {definition_key} 类型的 credential。" | `Create new credential`（inline DynamicFieldsForm）|

### 6.2 Edge Cases

| 情况 | UX |
|-------|----|
| **认证过期 (401)** | global interceptor redirect 到 `/auth/login`（现有 ADR-016 pattern）+ 保留原位置 `?next=` |
| **CSRF token 过期** | 后端返回 403 + `code: csrf_invalid` → 自动重新签发后重试一次，失败时 toast "会话已过期。" |
| **网络错误 (offline)** | 显示 TanStack Query offline + 卡片 grid 使用缓存数据 + 顶部 banner "当前处于离线状态。" |
| **部分 sync 结果 (admin k-skill status)** | 若 last sync report 有 `failed` count，则显示 yellow chip "Partial — N failed" + 详情提示查看 CLI 日志 |
| **`is_dirty` 状态下尝试 update** | 卡片 CTA 变为 `Review update` + UpdateDialog 中明确 destructive 选项 + 第 2 次 confirm（参见 3.5）|
| **publish 过程中关闭 dialog** | dirty form 时弹出 confirm AlertDialog（"已输入的内容将丢失"）|
| **catalog 响应大页面 (1000+ items)** | Phase 1 若没有 server-side pagination，则使用 frontend 虚拟化（`@tanstack/react-virtual`）— 初始只渲染 30 个 grid + scroll-load。Backend pagination 在 Phase 2 添加 |
| **卡片图片损坏** | `icon_url` 加载失败时 fallback 到 resource_type 默认图标（`onError`）|
| **disabled item 通过直接 URL 访问** | super_user 可进入 detail + 显示 disabled banner。普通用户返回 404 → redirect 到 `/marketplace` + toast |
| **restricted item 访问权限刚被收回后的 catalog** | 卡片消失（`useMarketplaceItems` refetch）。已 install 的 copy 仍保留在 `/skills` — Origin 保持 `shared_with_me`，但 `installation.update_available` 固定为 false（因为无法访问 Marketplace）|
| **multi-tab race condition** | Mutation 后除 `invalidateQueries` 外，不通过 SSE/websocket sync（Phase 1 范围）。其他 tab 需要用户刷新才能获取最新状态 |
| **k-skill sync 过程中查询 catalog** | 后端仅按 transaction 可见，因此不会看到部分结果。catalog 只会看到 sync 前或 sync 后状态之一。UI 无需额外处理 |
| **OriginBadge `shared_with_me` 的 source_user_id 用户已 deactivated** | label fallback "Shared by (former user)" — 后端 `source_name` 为 null 时处理 |

### 6.3 移动端/平板自适应

- 卡片 grid `grid-cols-1 md:grid-cols-2 xl:grid-cols-3`。
- FilterBar 在移动端 collapse 为 `Sheet`（右侧滑出）— 合并为 1 个 `Filter` 按钮。
- InstallWizard/PublishWizard sidebar 在移动端切换为顶部 step indicator（隐藏 sidebar，使用 `LineTabs` 风格 step bar）。
- DataTable 在移动端 horizontal scroll。仅必需列（Name, Origin, Marketplace）sticky。

---

## 7. 实现优先级（给 Zuckerberg 的指南）

Zuckerberg 在 M8b 实现时推荐按以下 slice：

1. **Slice U1 — 基础组件**：`OriginBadge`, `PublicationBadge`, `CredentialSummaryChip`, `SupportLevelChip`, `InstallationStatusChip`。通过独立 storybook/preview 渲染所有 variant。作为其他 slice 的依赖。
2. **Slice U2 — `/skills` 页面更新**：新增列（Origin/Marketplace/Credential），row menu 添加 `Publish to Marketplace`。后端已 embed origin/publication summary。以最小改动立即产生价值。
3. **Slice U3 — `/marketplace` catalog read-only**：`MarketplaceCard`, `MarketplaceFilterBar`, 4-tab。`Install` CTA 使用 placeholder（"Coming soon" toast）。
4. **Slice U4 — InstallWizard**：4-step + credential inline create。包含 credential mismatch 分支。
5. **Slice U5 — `/marketplace/[item-id]` detail**: versions table, credential requirements list, owner action row.
6. **Slice U6 — UpdateDialog + Uninstall**.
7. **Slice U7 — PublishWizard**：5-step + secret_detected 分支。
8. **Slice U8 — SharedUsersDialog + ACL CRUD**.
9. **Slice U9 — `/marketplace/admin/moderation`** (super_user UI guard).
10. **Slice U10 — `/mcp-servers` 列更新**（虽然标注为 Phase 2，但会展示 origin/publication 列）。

每个 slice 都可在不修改后端的情况下完成（后端已在 M2~M7 完成）。

---

## 8. 验证清单（进入 M8b 前）

- [ ] 16 个新增组件与 `frontend/src/components/marketplace/` 文件夹 1:1 映射
- [ ] `OriginBadge`/`PublicationBadge` 在 `/skills` 页面复用相同组件
- [ ] InstallWizard 4-step、PublishWizard 5-step 均使用 `DialogShell`（`DIALOG_SIZE`/`DIALOG_HEIGHT` token）
- [ ] 12 个错误代码分别有不同 UX 分支（§5.3 矩阵）
- [ ] 所有颜色使用 ADR-010 token — 禁止直接使用 raw emerald/violet/amber/sky/red
- [ ] 卡片 CTA 8 种分支（§2.2）全部有表达
- [ ] OriginBadge 6 kind × PublicationBadge 8 state × CredentialSummaryChip 5 status × SupportLevelChip 6 level × InstallationStatusChip 4 status 均可在视觉上区分
- [ ] WCAG 2.1 AA：所有 chip 都使用颜色 + 标签 + 图标 3 重编码
- [ ] 移动端对 FilterBar/Wizard sidebar 做自适应处理
- [ ] Enumeration oracle：未授权 detail/install 统一返回 404（UI 也使用相同 toast 消息）

---

## 9. 备注

- **全栈一致性**：若 backend `MarketplaceItemOut` shape 发生变化，应同步更新本 spec 和 hook 接口。Pydantic v2 → TS type 理想上应使用 schema generator（zod/openapi-typescript 等），但 Phase 1 从手动 type definition（`lib/types/marketplace.ts`）开始 — 简单优先。
- **Phase 2 扩展点**：MCP marketplace 只需在 `MarketplaceCard`/`InstallWizard` 中增加 resource_type='mcp' 分支，即可在同一页面工作。Agent 同理。本 spec 的组件签名设计为接收 resource_type 后工作。
- **若本文档与 ADR-017 冲突，以 ADR-017 为准。若与 Spec 冲突，以 Spec 为准**（源文件原文）。
