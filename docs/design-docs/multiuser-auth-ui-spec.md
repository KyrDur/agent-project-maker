# Multi-User Auth — UI/UX Spec

- **Status**: Accepted (2026-05-08)
- **Author**: tim-cook
- **Scope**：Phase 7（前端认证）— 基于 `~/.claude/plans/replicated-crunching-lark.md`
- **关联文档**：`ADR-010-ui-tokens-and-dialog-shell.md`（token 系统），`progress.txt`（API 契约）
- **已批准决定**：Email + Password (MVP), HttpOnly Cookie + CSRF, 首位注册用户自动成为 super_user

本文档编写目标是让 Zuckerberg（前端实现者）无需额外设计决策即可直接实现。
所有组件仅使用现有 shadcn/ui token — 不创建新 token。

---

## 1. 设计原则

### 1.1 简单即精品
- **认证应无摩擦地快速完成。** 用户的目标不是“登录”，而是“创建 Agent”。
- 登录页面的第一印象应在 **3 秒内**形成 — 2 个字段、1 个按钮、清晰层级。
- 底部辅助链接（注册/找回密码）应降低视觉权重（text link, no border）。
- 一个页面只做一件事 — 禁止广告/装饰。

### 1.2 设计语言一致性
- **使用组件(shadcn/ui)**：`Card`, `Form`, `Input`, `Button`, `Checkbox`, `Label`, `Dialog`(via `DialogShell`), `Avatar`, `DropdownMenu`, `Toast`(`sonner`), `Alert`。
- **布局 metric**：卡片 padding `p-8`（移动端 `p-6`），字段间距 `space-y-4`，表单内 label↔input `space-y-1.5`。与 ADR-010 的 DialogShell metric 保持相同节奏。
- **按钮优先级**：primary(`Button` default) = 主操作，ghost/link = 辅助操作。Dialog footer 右对齐规则相同。

### 1.3 简体中文优先，英文 fallback
- 所有 label/message/error 均以**简体中文第 1 优先**编写，i18n key 结构遵循现有 `t('user.name')` pattern（`app-sidebar.tsx`）。
- 新增 key namespace：`auth.*`, `auth.errors.*`, `auth.onboarding.*`。
- 英文 fallback 放在 i18n resource 的 `en` bundle 中（existing convention）。

### 1.4 深色模式兼容
- 因仅使用 shadcn token，可自动兼容 — 不定义新颜色。
- 但以下项目必须明确遵守：
  - 表单卡片背景：`bg-card text-card-foreground`（在深色模式下也有分离感）
  - 辅助文本：`text-muted-foreground`
  - 错误 inline：`text-destructive`
  - focus ring：按 ADR-010 使用 `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`

### 1.5 可访问性优先
- 所有 input 连接 `<Label>`，密码显示 toggle 使用 `aria-pressed`。
- 错误通过 `aria-live="polite"` 通知屏幕阅读器。
- Tab 顺序与视觉顺序一致 — 参见第 4 项。

---

## 2. 页面结构 wireframe

### 2.1 `/login` — 登录

#### 桌面端 (≥ md, 768px)

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌────────────────────────┐  ┌──────────────────────────────┐   │
│  │  [Brand Mark]          │  │  登录                       │   │
│  │  Moldy                 │  │  请输入账户信息              │   │
│  │                        │  │                              │   │
│  │  AI Agent              │  │  ┌────────────────────────┐ │   │
│  │  无需一行代码           │  │  │ 邮箱                    │ │   │
│  │  即可创建的            │  │  │ [you@example.com     ] │ │   │
│  │  最简单方式。          │  │  └────────────────────────┘ │   │
│  │                        │  │                              │   │
│  │  · no-code builder     │  │  ┌────────────────────────┐ │   │
│  │  · LangGraph runtime   │  │  │ 密码          [👁]      │ │   │
│  │  · 对话式 Agent        │  │  │ [••••••••           ]  │ │   │
│  │                        │  │  └────────────────────────┘ │   │
│  │  （可选插图/pattern）   │  │                              │   │
│  │                        │  │  ☐ 保持登录     找回密码 →  │   │
│  │                        │  │                              │   │
│  │                        │  │  ┌────────────────────────┐ │   │
│  │                        │  │  │      登录             │ │   │
│  │                        │  │  └────────────────────────┘ │   │
│  │                        │  │  ─────  或  ─────          │   │
│  │                        │  │  [🇬 使用 Google 登录（即将推出）]   │   │
│  │                        │  │                              │   │
│  │                        │  │  还没有账户？注册 →         │   │
│  │                        │  └──────────────────────────────┘   │
│  └────────────────────────┘                                      │
│   （左侧 1/2）                （右侧表单，max-w-[420px] center）    │
└──────────────────────────────────────────────────────────────────┘
```

左侧列：
- grid：`lg:grid-cols-2`（小尺寸桌面端 fallback 为单列）
- 背景：`bg-muted/30`（或轻微浅色 pattern — placeholder）
- 内容：居中对齐 `flex flex-col justify-center px-12`
- 品牌标识 + tagline + 核心价值 3 行 bullet（i18n key: `auth.login.benefits.*`）

右侧列：
- 表单：`Card`（border, `shadow-sm`, `rounded-2xl`, `p-8`, `max-w-[420px]`）
- header：标题 `text-2xl font-semibold tracking-tight` + 描述 `text-sm text-muted-foreground`

#### 移动端 (< md)

```
┌──────────────────────┐
│  Moldy               │  ← brand bar（非 sticky，可 scroll）
│  AI Agent Builder     │
├──────────────────────┤
│                      │
│  登录                 │
│  输入账户信息          │
│                      │
│  [邮箱            ]   │
│                      │
│  [密码      👁    ]   │
│                      │
│  ☐ 保持   找回密码    │
│                      │
│  [    登录       ]    │
│                      │
│  ── 或 ──           │
│  [ Google（即将推出）]  │
│                      │
│  注册 →               │
│                      │
└──────────────────────┘
```
- 单列，左右 padding `px-6`
- 表单卡片在移动端使用 `border-0 shadow-none p-0`（仅靠留白分隔）

#### 字段规范

| 字段 | type | 验证 | placeholder |
|------|------|------|-------------|
| 邮箱 | `email`, `autoComplete="email"`, `inputMode="email"`, `required` | 客户端仅检查是否包含 `@`。严格验证由服务器完成 | `you@example.com` |
| 密码 | `password`, `autoComplete="current-password"`, `required` | 仅检查非空 |（无）|

#### 辅助元素
- **保持登录复选框**（`Checkbox` + `Label`）：MVP 中为 **placeholder** — 始终表现为已勾选（refresh token 默认 30 天）。UI 可见，但 onChange 为 no-op，并设置 `data-placeholder="true"`。Tooltip "当前始终保持登录状态。"
- **"找回密码"** 链接：Phase 2 placeholder。不使用 `<a>`，改用 `<button type="button">`，`onClick` 为 toast.info("将在支持邮箱验证后提供 — Phase 2")。`aria-disabled="true"`。
- **使用 Google 登录** 按钮：`Button variant="outline"` + Google G 图标 + 文本 "使用 Google 登录"。`disabled`。`Tooltip`："即将支持 (Phase 2)"。按钮本身 `cursor-not-allowed` opacity 60%。
  - 按钮上方 separator：`<div className="relative my-4"><div className="border-t border-border/60" /><span className="absolute inset-0 flex items-center justify-center"><span className="bg-card px-2 text-xs text-muted-foreground">或</span></span></div>`

#### 底部链接
```
还没有账户？  注册 →
```
- `text-sm text-muted-foreground text-center`
- 仅“注册”部分使用 `text-primary-strong hover:underline`

### 2.2 `/register` — 注册

#### Layout
- 与 `/login` **使用相同的 2 列结构**（左侧 intro 相同，右侧表单卡片）
- 仅修改左侧文案："立即开始" + 注册后的第一步提示（i18n: `auth.register.intro.*`）

#### 字段（从上到下）

| 字段 | type | 验证（客户端）| placeholder |
|------|------|------|-------------|
| 姓名 | `text`, `autoComplete="name"`, `required`, `maxLength=80` | 至少 1 个字符 | `张三` |
| 邮箱 | `email`, `autoComplete="email"`, `required` | 包含 `@` | `you@example.com` |
| 密码 | `password`, `autoComplete="new-password"`, `required` | **至少 8 个字符**（与服务器一致）|（无）|
| 确认密码 | `password`, `autoComplete="new-password"`, `required` | 与上方一致 |（无）|

#### 密码强度 indicator

紧接在密码 input 下方 `mt-2`：
```
[━━━━━━─────────]  弱 / 一般 / 强
```
- 条形：`flex h-1 gap-1` 4 个 segment（`flex-1 rounded-full`）。
- 评分规则（仅基于长度，后续可替换为 zxcvbn）：
  - 0~7 个字符：0 个 segment 激活，label "密码至少需要 8 个字符" `text-destructive`
  - 8~9 个字符：1 个 segment（`bg-status-warn`），label "弱" `text-status-warn`
  - 10~13 个字符：2 个 segment（`bg-status-warn`），label "一般"
  - 14~17 个字符：3 个 segment（`bg-status-success`），label "强"
  - 18 个字符以上或字母数字+符号混合：4 个 segment（`bg-status-success`），label "非常强"
- 未激活 segment：`bg-muted`
- `aria-label="密码强度"`, `role="meter"`, `aria-valuenow={score}`, `aria-valuemin=0`, `aria-valuemax=4`。

确认密码 mismatch 时：`aria-invalid="true"` + helper text "两次输入的密码不一致" `text-destructive`。

#### 条款同意复选框（placeholder）
```
☐ 我同意服务使用条款和隐私政策（必选）
```
- MVP 中强制始终为 true（取消勾选时注册按钮 disabled）
- 条款/政策链接使用 `<a>` placeholder（"准备中"）
- Phase 2 连接实际条款页面 — UI 本身不变

#### 注册按钮
- 文本："注册"
- 禁用条件：任一必填字段不满足 OR 密码 mismatch OR 未同意条款
- pending：`<Loader2 className="mr-2 size-4 animate-spin" />` + 文本 "注册中..."，整个表单 `pointer-events-none opacity-70` + input `disabled`

#### 底部链接
```
已有账户？  登录 →
```

---

## 3. UserMenu（侧边栏底部）

### 3.1 位置与结构

直接替换现有 `app-sidebar.tsx:365-410` 的 "User Profile" 区域（结构保持，数据源仅改为 `useSession()`）。

```
┌─ Sidebar 底部 ────────────────────────┐
│  ...菜单项...                          │
│  ─────────────────────────────────────│
│  ┌──┐                              ▾  │
│  │JD│  John Doe         [管理员]      │  ← super_user 时显示 badge
│  └──┘  john@example.com              │
└──────────────────────────────────────┘
```

### 3.2 Avatar

- 组件：shadcn `Avatar`（`size-8 rounded-lg`）— 与现有 `bg-sidebar-accent` 统一
- 图片：用户 `avatar_url`（MVP 中没有，因此始终 fallback）
- Fallback：取姓名**前两个字符**并大写。中文姓名则取第一个字符（e.g. "张"）。
  ```tsx
  function initials(name: string): string {
    const parts = name.trim().split(/\s+/)
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
    return parts[0].slice(0, 2).toUpperCase()  // ASCII取2个字符，中文取前1个字符 = OK
  }
  ```
- Fallback 背景：`bg-primary/15 text-primary-strong`（品牌一致性）

### 3.3 文本区域

- 姓名：`truncate font-medium text-sm leading-tight`
- 邮箱：`truncate text-xs text-muted-foreground leading-tight`
- 容器：`grid flex-1 min-w-0` — `min-w-0` 是 truncate 的关键

### 3.4 super_user badge

姓名旁的小 badge（条件显示）：
```tsx
{user.is_super_user && (
  <span className="inline-flex h-4 items-center rounded-full bg-status-accent/15 px-1.5 text-[10px] font-medium uppercase tracking-wider text-status-accent">
    管理员
  </span>
)}
```
- 使用 ADR-010 的 `--status-accent` token（避免与品牌 primary 色冲突）
- 英文："ADMIN"

### 3.5 Dropdown menu（展开状态）

```
┌─────────────────────────┐
│  ▸ 个人资料设置        │  ← /settings（Phase 2 启用，MVP 为 placeholder）
│  ▸ API 密钥管理        │  ← /credentials（直接跳转）
├─────────────────────────┤
│  ▸ 退出登录            │  ← destructive 颜色
└─────────────────────────┘
```

使用 shadcn `DropdownMenu`（已 import）。项目：
1. **个人资料设置** — `<UserIcon />` + "个人资料设置"
   - MVP：`onClick={() => toast.info('个人资料设置即将支持')}`（placeholder）
   - Phase 2 改为 `/settings/profile`
2. **API 密钥管理** — `<KeyIcon />` + "API 密钥管理"
   - `onClick={() => router.push('/credentials')}`
3. (Separator)
4. **退出登录** — `<LogOutIcon />` + "退出登录"
   - `className="text-destructive focus:text-destructive focus:bg-destructive/10"`
   - `onClick={onLogout}` — 调用 `useAuth().logout()` mutation

### 3.6 首位注册后 super_user toast

注册响应中若 `user.is_super_user === true`，redirect 后仅显示 1 次：
```tsx
toast.success('🎉 已注册为 Super User', {
  description: '可以管理系统 credential。',
  duration: 6000,
})
```
防止重复：显示前检查 `sessionStorage.setItem('moldy.super_user_welcomed', '1')`。

---

## 4. 状态处理规范

### 4.1 加载状态

#### 表单提交中
- 按钮：`disabled` + 左侧 `<Loader2 className="mr-2 size-4 animate-spin" aria-hidden />` + 文本 "登录中..." / "注册中..."
- 整个表单：`<fieldset disabled={isLoading} className="contents">` — input 自动 disabled
- 在 `<form>` 上添加 `aria-busy="true"`

#### session 初始加载（`useSession()` pending）
- `AuthGuard` wrapper:
  - 全屏 skeleton：`<div className="flex h-screen items-center justify-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>`
  - 或仅侧边栏/header 区域使用 `<Skeleton>`（优先保证 UX 平滑）

### 4.2 错误状态

#### inline 表单错误（字段级）
- 字段下方 `text-xs text-destructive mt-1`
- 容器设置 `aria-invalid="true"` + `aria-describedby={errorId}`
- 输入时立即清除（live validation）

#### 表单级错误（提交后）
- `Alert variant="destructive"` 紧接表单卡片 header 下方（字段上方）
- `role="alert"` + `aria-live="assertive"`（立即通知）
- 无关闭按钮（下次提交时自动清除）

#### 错误消息映射

| HTTP | 场景 | 消息（简体中文）| 显示位置 |
|------|---------|----------------|----------|
| 401 | 登录失败 | "邮箱或密码不正确" | 表单级 Alert |
| 409 | 邮箱重复（注册）| "该邮箱已被使用" | 邮箱字段 inline |
| 422 | 密码过短 | "密码至少需要 8 个字符" | 密码字段 inline |
| 422 | 姓名为空 | "请输入姓名" | 姓名字段 inline |
| 423 | 账户锁定 | "账户已暂时锁定。请在 15 分钟后重试。" | 表单级 Alert |
| 429 | Rate limit | "请稍后重试" | 表单级 Alert |
| 5xx | 服务器错误 | "请稍后重试。如果问题持续，请联系管理员。" | 表单级 Alert |
| network | 连接失败 | "请检查网络连接" + [重试] 按钮 | 表单级 Alert |

422 的 detail 映射根据后端响应的 `loc`（e.g. `["body","password"]`）分支。未知字段则 fallback 到表单级 Alert。

### 4.3 global 401 处理（session 过期）

`apiFetch` 收到 401 且 `/refresh` 也失败时：
1. **显示 Toast**：`toast.error('会话已过期', { description: '请重新登录。' })`
2. **TanStack Query 缓存 invalidate**：`queryClient.clear()`
3. **Redirect**：将当前 path 保存到 `callbackUrl` query，并跳转 `/login`
   ```ts
   const callback = encodeURIComponent(window.location.pathname + window.location.search)
   router.push(`/login?callbackUrl=${callback}`)
   ```
4. **callbackUrl 验证**（login 页面 onSuccess）：`startsWith('/')` && `!startsWith('//')`（防止 open redirect）

此处理在 `lib/api/client.ts` interceptor 中作为单一入口 — 不在每个组件中分别处理。

### 4.4 空状态 / 首次进入

- **首次进入 `/login`**：表单为空状态（autofocus on 邮箱 input）
- **`/login?callbackUrl=...`（过期后进入）**：表单上方显示 Alert（info, `bg-status-info/10 text-status-info`）"需要登录"
- **已登录用户直接访问 `/login`**：middleware 在服务器端 redirect 到 `/`

### 4.5 网络错误

- `Alert variant="destructive"` + 消息 + `<Button variant="outline" size="sm" onClick={retry}>重试</Button>`
- 重试时原样重新调用最后一次 mutation

---

## 5. Onboarding 流程

### 5.1 首次登录后的欢迎 modal

#### 触发条件
- 注册后自动登录 → 进入 dashboard（`/`）时 1 次
- 或 `sessionStorage.getItem('moldy.onboarding_dismissed') !== '1'` && `useSession().data.user.created_at` 在 5 分钟内
- `OnboardingDialog` 组件 mount 在 dashboard root，自行判断

#### Dialog（使用 DialogShell）

```
┌──────────────────────────────────────────────────┐
│  🎉  欢迎来到 Moldy                              ✕  │
│      创建 AI Agent 的准备工作即将完成              │
├──────────────────────────────────────────────────┤
│                                                  │
│  要创建 AI Agent，需要注册 LLM API 密钥            │
│  。                                                │
│                                                  │
│  ┌─────────────────────────────────────────┐    │
│  │  📋 请注册以下任意一种：                  │    │
│  │     · OpenAI API Key                    │    │
│  │     · Anthropic API Key                 │    │
│  │     · Google AI Studio API Key          │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  密钥会加密保存，只有您本人可以查看。               │
│                                                  │
├──────────────────────────────────────────────────┤
│                       [稍后]   [立即注册]           │
└──────────────────────────────────────────────────┘
```

- `DialogShell` size=`md` height=`auto`
- header icon slot：`<PartyPopperIcon />` (lucide) 或 emoji `🎉` + `bg-status-accent/15 text-status-accent`
- 正文遵循 ADR-010 的 `space-y-6` / `space-y-3` 节奏
- highlight box：`bg-muted/40 rounded-lg p-4 border border-border/60`
- footer：
  - "稍后" — `Button variant="ghost"` → `sessionStorage.setItem('moldy.onboarding_dismissed', '1')` + 关闭
  - "立即注册" — `Button` (primary) → `router.push('/credentials')` + 关闭 + 设置 dismissed flag

### 5.2 首个 Agent 创建 guard

进入 `/agents/new` 或 builder 时：
1. 通过 `useSession()` 确认 user
2. 通过 `useQuery(['credentials','for-llm'])` 检查是否拥有 LLM credential
3. 若无 → redirect 到 `/credentials?redirect=/agents/new`
4. `/credentials` 页面顶部显示 `Alert` (info)：
   ```
   ⓘ  要创建 AI Agent，请先注册 LLM API 密钥。
       注册完成后会自动返回之前页面。
       [← 返回]
   ```
5. credential 注册完成时，在 mutation `onSuccess` 中根据 `redirect` query param 自动返回

此行为封装为 `useRequireLlmCredential()` hook 复用（signature: `() => { hasCredential: boolean, isLoading: boolean }`）。

### 5.3 super_user 专用显示（system credential）

在 `/credentials` 页面：
- 普通用户：仅显示自己的 credential（后端过滤）
- super_user：本人 + system — system credential 明确区分
  - 卡片左上角显示 `Badge variant="outline"` "系统"（`bg-status-accent/10 text-status-accent border-status-accent/30`）
  - 与普通卡片做轻微视觉区分（背景 `bg-muted/30`）

此部分不属于本 spec 直接范围，但因与 onboarding 相关而明确说明。

---

## 6. 组件列表

编写目标是让 Zuckerberg 只看下表即可实现，无需额外做任何决定。

| 组件 | 文件路径 | 核心 props | 依赖 | 备注 |
|----------|-----------|-----------|------|------|
| `LoginForm` | `frontend/src/components/auth/LoginForm.tsx` | `onSubmit(email, password): Promise<void>`, `isLoading: boolean`, `error: AuthError \| null`, `defaultEmail?: string` | shadcn Form, Input, Button, Checkbox, Alert | 内置密码显示 toggle。callbackUrl param 由页面组件处理 |
| `RegisterForm` | `frontend/src/components/auth/RegisterForm.tsx` | `onSubmit({name, email, password}): Promise<void>`, `isLoading`, `error` | 同上 + `Progress` 或自定义 strength bar | 密码强度 indicator + 确认字段 mismatch 验证 |
| `UserMenu` | `frontend/src/components/auth/UserMenu.tsx` | `user: { id, name, email, is_super_user }`, `onLogout: () => void` | shadcn Avatar, DropdownMenu | 替换侧边栏底部现有 block |
| `AuthGuard` | `frontend/src/components/auth/AuthGuard.tsx` | `children: ReactNode`, `fallback?: ReactNode` | `useSession()` | session pending 时使用 fallback，error/无 session 时 redirect /login |
| `OnboardingDialog` | `frontend/src/components/auth/OnboardingDialog.tsx` | `open: boolean`, `onClose: () => void`, `onPrimary: () => void` | `DialogShell` | 自身 trigger 逻辑位于 dashboard root |
| `PasswordStrengthMeter` | `frontend/src/components/auth/PasswordStrengthMeter.tsx` | `password: string` |（无）| 4 segment 条形 + label，`role="meter"` |
| `SessionExpiredToast` |（无 — 在 `lib/api/client.ts` 直接调用 `toast.error`）| — | sonner | 不创建单独组件，只调用函数 |

### 6.1 页面组件

| 文件 | 职责 |
|------|------|
| `frontend/src/app/(auth)/layout.tsx` | 认证专用 layout — 无侧边栏，在 `<main>` 中使用 2 列 grid |
| `frontend/src/app/(auth)/login/page.tsx` | 托管 `LoginForm`，`useAuth().login` mutation，处理 callbackUrl |
| `frontend/src/app/(auth)/register/page.tsx` | 托管 `RegisterForm`，`useAuth().register` mutation，super_user welcome toast |

### 6.2 hook/util

| 文件 | export |
|------|--------|
| `frontend/src/lib/auth/session.ts` | `useSession()` (TanStack Query) |
| `frontend/src/lib/hooks/useAuth.ts` | `useAuth()` returning `{ login, register, logout, isPending }` |
| `frontend/src/lib/auth/csrf.ts` | `getCsrfToken()`, `setCsrfToken(token)`, `clearCsrfToken()` (in-memory + sessionStorage backup) |

### 6.3 入口 — Zuckerberg 最先应修改的文件

```
frontend/src/lib/api/client.ts   ← 从这里开始
```
在此文件加入 `credentials: 'include'` + CSRF header + 401 自动 refresh + 过期 toast/redirect 后，其余组件即可自然构建在其上。

---

## 7. 可访问性 (WCAG AA)

### 7.1 表单 label

- 所有 `<Input>` 都与 `<Label htmlFor={id}>` 显式关联
- 密码显示 toggle：`<button type="button" aria-pressed={visible} aria-label="显示/隐藏密码">`
- Checkbox 同样处理 — 使用 `<Label htmlFor>` 或 wrapping `<Label>` 扩大点击区域

### 7.2 Tab 顺序

`/login` 桌面端：
1. 邮箱输入
2. 密码输入
3. 密码显示 toggle
4. "保持登录" checkbox
5. "找回密码" 链接（Phase 2 — 虽为 `aria-disabled` 但仍可 tab）
6. **"登录" 按钮** (primary)
7. "使用 Google 登录" 按钮（disabled — tab skip）
8. "注册" 链接

`/register`:
1. 姓名 → 2. 邮箱 → 3. 密码 → 4. 密码显示 toggle → 5. 确认密码 → 6. 条款 checkbox → 7. "注册" 按钮 → 8. "登录" 链接

UserMenu dropdown：
1. trigger 按钮（Tab 聚焦后按 Enter/Space 打开）
2. 第一个 menu item（用 Arrow Down 移动）
3. 按 ESC 关闭

### 7.3 错误通知

- 表单级 Alert：`role="alert"` + `aria-live="assertive"`（立即提示）
- inline helper text：`aria-live="polite"` + `id={`${field}-error`}` + 字段的 `aria-describedby`
- 密码强度：`role="meter" aria-valuenow aria-valuemin aria-valuemax aria-label`

### 7.4 focus 可见性

- ADR-010 标准 focus ring：`focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`
- 按钮额外使用：`focus-visible:ring-offset-2 focus-visible:ring-offset-background`
- Dialog 内 focus trap：Radix DialogPrimitive 默认行为（DialogShell 使用）

### 7.5 键盘快捷键

- Enter：提交表单（无需其他快捷键 — 简单优先）
- Tab/Shift+Tab：标准移动
- ESC：关闭 Dialog（Onboarding）— Radix 默认
- 密码显示 toggle：Space 或 Enter

### 7.6 motion

- 尊重 `prefers-reduced-motion` — 使用 Tailwind v4 的 motion-safe/motion-reduce variant
- Dialog 动画使用 ADR-010 的 200ms zoom + fade

---

## 8. 设计 token

**不创建新 token。** 仅使用 ADR-010 + shadcn 默认 token。

### 8.1 使用的 token inventory

| token | 用途 |
|------|------|
| `--background` / `--foreground` | 页面基础 |
| `--card` / `--card-foreground` | 表单卡片表面 |
| `--popover` / `--popover-foreground` | dropdown, dialog |
| `--primary` / `--primary-foreground` | 主 CTA 按钮 |
| `--primary-strong` | 链接、active 文本、avatar fallback 文本颜色 |
| `--secondary` / `--secondary-foreground` | 辅助按钮（较少使用）|
| `--muted` / `--muted-foreground` | 辅助文本、背景 fill、intro 区域 |
| `--accent` / `--accent-foreground` | hover 状态 |
| `--destructive` / `--destructive-foreground` | 错误、退出登录 |
| `--border` | 卡片/分隔线 |
| `--input` | input border |
| `--ring` | focus ring（ADR-010 内置 alpha）|
| `--status-success` | 密码强度“强”以上 |
| `--status-warn` | 密码强度“弱/一般” |
| `--status-info` | callback 提示、info Alert |
| `--status-accent` | super_user badge、onboarding icon |
| `--status-danger` |（= destructive alias）|

### 8.2 禁止事项

- ❌ 禁止直接使用 raw `bg-emerald-*`, `text-blue-*`, `bg-zinc-*` 等 Tailwind palette
- ❌ 禁止任意 hex（`#10b981`）或 oklch literal
- ❌ 禁止绕过 DialogShell（直接使用 `Dialog`）
- ❌ 禁止 `sm:max-w-2xl` 等任意尺寸 — 使用 `DIALOG_SIZE` token

### 8.3 spacing / round

- 卡片 round：`rounded-2xl`（与 DialogShell 相同）
- 卡片 shadow：`shadow-sm`（登录/注册是页面而非 dialog，无需强 shadow）
- 表单内部间距：`space-y-4`
- label↔input：`space-y-1.5`
- input↔helper text：`mt-1`

### 8.4 typography

- 页面标题：`text-2xl font-semibold tracking-tight`
- 描述：`text-sm text-muted-foreground`
- label：`text-sm font-medium`（shadcn Label 默认）
- inline error/helper：`text-xs`
- badge：`text-[10px] uppercase tracking-wider`

---

## 附录 A. i18n key inventory（简体中文第 1 优先）

```yaml
auth:
  login:
    title: "登录"
    subtitle: "请输入账户信息"
    email: "邮箱"
    password: "密码"
    rememberMe: "保持登录"
    forgotPassword: "找回密码"
    submit: "登录"
    submitting: "登录中..."
    googleButton: "使用 Google 登录"
    googleComingSoon: "即将支持"
    or: "或"
    noAccount: "还没有账户？"
    registerLink: "注册"
    benefits:
      title: "无需一行代码即可创建 AI Agent"
      item1: "no-code builder"
      item2: "LangGraph runtime"
      item3: "创建对话式 Agent"
    expiredNotice: "需要登录"
  register:
    title: "注册"
    subtitle: "创建 Moldy 账户"
    name: "姓名"
    email: "邮箱"
    password: "密码"
    passwordConfirm: "确认密码"
    terms: "我同意服务使用条款和隐私政策"
    submit: "注册"
    submitting: "注册中..."
    haveAccount: "已有账户？"
    loginLink: "登录"
    strength:
      tooShort: "密码至少需要 8 个字符"
      weak: "弱"
      medium: "一般"
      strong: "强"
      veryStrong: "非常强"
    mismatch: "两次输入的密码不一致"
  errors:
    invalidCredentials: "邮箱或密码不正确"
    emailTaken: "该邮箱已被使用"
    accountLocked: "账户已暂时锁定。请在 15 分钟后重试。"
    rateLimit: "请稍后重试"
    network: "请检查网络连接"
    serverError: "请稍后重试。如果问题持续，请联系管理员。"
    sessionExpired: "会话已过期"
    sessionExpiredDesc: "请重新登录。"
  onboarding:
    title: "欢迎来到 Moldy"
    subtitle: "创建 AI Agent 的准备工作即将完成"
    body: "要创建 AI Agent，需要注册 LLM API 密钥。"
    providers: "请注册以下任意一种"
    encryptedNote: "密钥会加密保存，只有您本人可以查看。"
    later: "稍后"
    register: "立即注册"
    superUserToast: "🎉 已注册为 Super User"
    superUserToastDesc: "可以管理系统 credential。"
  userMenu:
    profile: "个人资料设置"
    credentials: "API 密钥管理"
    logout: "退出登录"
    adminBadge: "管理员"
    profileComingSoon: "个人资料设置即将支持"
```

---

## 附录 B. 不变内容（Out of Scope）

本 spec **不处理**以下内容 — 明确推迟到后续工作：

- 密码重置页面 / 邮箱验证页面（Phase 2）
- Google OAuth callback 页面（Phase 2）
- 个人资料编辑页面（Phase 2）
- workspace switcher（Future Phase）
- 用户搜索 / 邀请（Future Phase）

为确保所有这些未来页面与**当前 spec 保持一致**，仅保证以下内容：
- `(auth)` route group 共用认证专用 layout — Phase 2 新增页面时复用相同 layout
- UserMenu 保持 `DropdownMenu` 结构以便未来新增项目（用 Separator 分组）
- 所有新页面只要使用 shadcn token 即可自动保持一致

---

## 验证清单（Zuckerberg 实现完成时）

- [ ] `/login` 桌面端/移动端视觉回归均 OK
- [ ] `/register` 密码强度 meter 4 级正常工作
- [ ] 表单级 Alert 在所有错误 case 中显示正确消息
- [ ] 保留 callbackUrl param（例如：`/agents/123` → 登录 → 自动返回）
- [ ] 401 → 自动 refresh → 失败时 toast + redirect 正常工作
- [ ] UserMenu dropdown 中，super_user 显示“管理员” badge
- [ ] OnboardingDialog 在首次注册后仅显示 1 次（检查 sessionStorage）
- [ ] dark mode 下所有页面正常（自动 — 因为只使用 token）
- [ ] 仅用键盘即可完成登录 → 注册 → 退出登录全流程
- [ ] axe-core devtools violation 0 个（或全部为 known false-positive）
- [ ] `pnpm build` && `pnpm lint` 通过
