<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Tailwind cn() / twMerge 陷阱

`cn()` 是 `twMerge(clsx(inputs))`。**同一组**（`p-*`, `gap-*`, `flex` vs `grid`, `rounded-*`）会正常 merge。但**响应式 prefix 会被视为独立组**，因此不会被 override。

```tsx
// base class
'w-full max-w-[calc(100%-2rem)] sm:max-w-sm'

// override
cn(base, 'w-[720px]')
// 结果：w-[720px] 会生效，但 sm:max-w-sm(384px) 会在 desktop 上把 max-width clamp 到 384px。
// 实际宽度被强制为 384px。
```

**解决方案**：显式设置响应式 reset
```tsx
cn(base, 'w-[720px] sm:max-w-none')
```

其他陷阱组：`dark:bg-*`, `hover:text-*`, `focus-visible:ring-*` 等所有 modifier prefix。

## React 19 useEffect setState 反模式

ESLint 规则 `react-hooks/set-state-in-effect` 会拒绝“响应 prop 变化并重置 state”的模式。

```tsx
// ❌ 被拒绝
useEffect(() => {
  setConfirming(false)
}, [id])
```

**替代方案**：

1. **推荐：在上层 remount**——拆分为 Inner component，通过变更 `key` 自然触发 unmount/remount。
   ```tsx
   export function MyDialog(props: Props) {
     return <MyDialogInner key={props.id ?? 'closed'} {...props} />
   }
   function MyDialogInner({ id, ... }: Props) {
     const [confirming, setConfirming] = useState(false)
     // id 变化时 Inner 会重新挂载，所有 state 自动重置
   }
   ```
   TanStack Query cache 与 component lifecycle 无关，会继续存在，因此不会重新进行 data fetch。

2. 如果是 derived state，则不要使用 useState，直接计算。

该模式目前用于 `components/{credential,skill,tool,mcp}/*-detail-dialog.tsx` 与 `shared/base-detail-dialog.tsx`。

## Playwright E2E 认证 session 规则

E2E 测试因 login 反复失败时，不要让每个 spec/test 都直接
通过 login form。标准做法是**在 Playwright global setup 中通过 API 创建一次
login session，并通过 `storageState` 注入所有 browser context**。

推荐结构：

- 在 `e2e/global-setup.mjs` 中，于测试开始前调用 `/api/auth/login`
- E2E 专用账户通过环境变量传入。推荐名称为
  `E2E_USER_EMAIL`, `E2E_USER_PASSWORD`；仅在本地 dev/test 环境中可以设置安全的
  默认值。不要将 production/shared staging 账户密码 hardcode 到 repo 中
- login 失败时，使用同一个 E2E 账户尝试 `/api/auth/register`；若已存在，
  在 `409` 后再次 login
- login 成功后，通过 `api.storageState({ path: './e2e/.auth/<lane>-user.json' })`
  保存包含 HttpOnly auth cookie 与 CSRF cookie 的 session
- 在 `playwright.config.ts` 中注册 `globalSetup` 和
  `use.storageState: './e2e/.auth/<lane>-user.json'`，使所有 page test
  都从已登录状态开始
- 在 `PW_SKIP_BACKEND=1` mock-only 模式下，global setup 保存伪造的
  `moldy_rt`, `moldy_csrf` cookie，并由 `e2e/fixtures.ts`
  将 `/api/auth/me` mock 为 E2E user
- 通过 `APIRequestContext` 直接创建/修改的 smoke test，应从 API login response 中
  获取 `csrf_token`，并在 mutation request 中放入 `X-CSRF-Token` header

修复 E2E auth failure 时优先检查：

- global setup 是否对同一 E2E 账户按 login → register fallback → login 顺序执行
- `playwright.config.ts` 中的 `globalSetup` 与 `storageState` 是否仍然有效
- `e2e/.auth/scripted-user.json` 与 `e2e/.auth/live-user.json` 是按 lane 生成的
  产物，因此不应 commit（允许显式 override `E2E_AUTH_STATE_PATH`）
- 测试是否不依赖 login page UI，而是在进入 `/` 时直接期待 dashboard/authenticated
  shell
- mock-only 测试在 `PW_SKIP_BACKEND=1` 下是否 mock 了 `/api/auth/me`
- 需要 CSRF 的 API 直接调用是否包含 `X-CSRF-Token`

### 并行执行时的 UI assertion timeout

对运行 live backend 的 UI assertion（`toBeVisible`/`toBeEnabled`）继续使用**默认 5 秒** timeout，
在 `--workers=4` + streaming spec 并发执行时会出现 flaky。原因是 checkpointer 的
共享 PostgreSQL pool（参见根目录 `CLAUDE.md`）和 DB 负载会让 backend 串行化，连无关的
列表查询也会变慢。

- 依赖 backend response 的 assertion 应宽松设置为 **`{ timeout: 15_000 }`~`20_000`**。
- API 验证遵循 `await expect.poll(async () => ..., { timeout: 15_000 })` 模式。
- flaky 判定：若隔离执行（`--workers=1`）时通过，则视为基础设施负载 flake（允许）；
  若单独执行也失败，则为真实 bug。通过 origin/main 对照判断是否为 regression。

## 设计 token + DialogShell

新建/migration dialog 时：
- 不要直接使用 `<DialogContent>`/`<Dialog>`，使用 `<DialogShell>`（`components/shared/dialog-shell.tsx`）
- size 仅使用 `DIALOG_SIZE`/`DIALOG_HEIGHT` token（`lib/design-tokens.ts`）。禁止任意值 `sm:max-w-2xl`/`max-h-[90vh]`。
- 强调色使用 `--primary`（chat 用户消息背景）/ `--primary-strong`（link·tab indicator）。禁止 raw `bg-emerald-*`——属于 Sprint 2 清理对象。
- 语义状态色：`--status-{success,info,warn,danger,accent}`。禁止 raw `bg-amber-*`/`bg-sky-*`。
- 详细规格：`docs/design-docs/ADR-010-ui-tokens-and-dialog-shell.md`

## Moldy 设计系统 guard

不要在产品页面代码中新增 surface、radius、shadow、typography、focus 例外。
新增页面/component 后执行以下命令：

```bash
pnpm lint:design-system
```

guard 会阻止以下内容：

- 直接使用 `rounded-xl/2xl/3xl`——迁移到 `moldy-card`、`moldy-panel`、`moldy-skeleton-card`、`moldy-muted-panel` 等公共 surface class
- 直接使用 `shadow-sm/md/lg/xl/2xl` 与 `shadow-[...]`——迁移到 `moldy-popover`、`moldy-floating-icon-button`、`moldy-side-panel` 等 elevation class
- `bg-[#...]`、`text-[#...]`、`border-[#...]` 等 raw hex utility——迁移到 `--primary`、`--status-*`、`--moldy-*` semantic token
- `bg-blue-500`、`text-emerald-700`、`border-rose-300` 等直接 Tailwind palette utility——迁移到 `moldy-status-*`、`moldy-favorite-icon`、`moldy-data-type-*`、Agent Prism token 等语义 class/token
- `gap-[...]`、`p-[...]`、`m-[...]`、`size-[...]`、`w-[...]`、`h-[...]`、`grid-cols-[...]` 等任意 spacing/sizing utility——迁移到 Tailwind scale token、`lib/design-tokens.ts`、公共 layout API，或 `scripts/check-design-system.mjs` 中狭窄的例外
- `z-[...]`、`z-40+`、`fixed inset-*`、`absolute inset-0`、`absolute ... z-*` 等 overlay/stacking utility——迁移到 shared overlay/positioning primitive，或 `scripts/check-design-system.mjs` 的文件级例外
- `text-[...]`、`leading-[...]`、`tracking-[...]`、`tracking-tight/tighter`、`outline-none`、`transition-all`——使用 Moldy typography/focus/explicit transition 规则
- 产品 button/menu/tab/toolbar 中的 inline `<svg>`——迁移到 `lucide-react` 或 Moldy-owned icon primitive
- `<Card>` 内嵌 `<Card>`、`moldy-card` 内嵌 `moldy-card`，以及在 `<section>/<aside>` 上附加 `moldy-card`/`moldy-panel` 的大型 surface——目前会作为 `pnpm lint:design-system` 的 warning baseline 报告。新增页面前，在增加此类 warning 之前，应先检查是否可以使用单一 surface + 内部 layout 或 shared panel/tool primitive 表达
- 任意 `style={...}`——仅 dynamic layout/library API 可在 `scripts/check-design-system.mjs` allowlist 中附理由显式声明

当前允许的 inline style 与 arbitrary layout 例外
已在 `scripts/check-design-system.mjs` 中按文件附理由明确声明。代表性例外包括
tree depth indentation, syntax highlighter theme, usage bar width, resource
grid columns, DialogShell size tokens, artifact preview panes, Agent Prism
trace/timeline layout、chat viewport clamps、phase progress ratio。即使看起来需要直接使用
palette 色，也应先增加语义 class。overlay/stacking 例外也
chat right rail mobile layer, sticky transcript header, popover, resize handle,
只允许 Agent Prism marker 等确实存在 stacking contract 的情况。Typography
例外只允许 Agent Prism trace geometry 等存在 renderer/layout contract 的情况。
inline SVG 例外只允许 data-driven chart 和品牌/vendor logo 等不适合由 icon library 替代的
情况。增加例外前，应先确认能否用公共 class/token 表达。
card structure warning 目前还不是失败条件，但在重构页面结构时，
优先整理 `pnpm lint:design-system` 输出中的 `section-as-card`、`nested-card`、
`nested-moldy-card` 候选项。

## i18n 静态文本规则

所有用户可见的静态文本都通过 `next-intl` message 管理。不要在 TS/TSX 中直接 hardcode 简体中文、
英文、placeholder、aria-label、title、toast 文案。

- 简体中文是 source of truth。新 copy 应先自然地添加到现有 `messages/zh-CN.json`，
  并将相同 key path 的恰当英文版本同步添加到 `messages/en.json`。
- 两个文件中的 key path 必须始终一致。不得只在一侧添加，也不得出现名称错位。
- 在 component 中使用 `useTranslations()`，或在 Server Component 中使用 `getTranslations()`。
- 添加/修改 UI copy 后运行 `pnpm lint:i18n`。
- `pnpm lint:i18n:strict` 用于更广泛地检查英文/ASCII 静态文本。目前
  仍存在部分 legacy Agent Prism 文案和代码片段误报；如果新代码被命中，
  应迁移到 i18n，并将现有误报的 guard 调整得更窄。

## Resource Card 语法

工具/skill/MCP/credential/marketplace/template 等资源列表卡片
使用 `components/shared/resource-layout.tsx` 中的 `ResourceListCard`。

- 顺序：`Header(icon + type badge)` → `Title` → `Subhead` → `Description` →
  `StatusRow` → `MetaRow` → `Footer`
- density：`compact`（选择候选）、`standard`（一般管理资源）、`rich`（状态/meta 较多的运营资源）
- category/tone 色不要用作整个 card 的背景或装饰 rail。仅在 neutral surface 上
  用于 icon、dot、status、hover/focus border 等有语义的位置。
- 单一 action card 可以让整个 `<button>`/`<Link>` 可交互。
- 只要存在任一辅助 action，root 就必须是 non-interactive `<article>`，并在 footer 中放置显式的
  `<Button>`/`<Link>`。新 resource card 禁止使用 `div role="button"` 和 inline `window.location.href`
  navigation。

## Frontend folder architecture

- `app/**/page.tsx` should be a Server Component wrapper unless the entire route genuinely requires browser APIs at the page boundary.
- Route-only UI lives under that route's `_components/`, `_hooks/`, or `_lib/`.
- Components used by multiple routes in one product domain live under `src/features/<domain>/`.
- Components used across unrelated domains live under `src/components/shared/`.
- `src/components/ui/` is for shadcn/base primitives only and must not import app/domain hooks.
- Do not add new barrel exports for frontend modules unless the importing ergonomics clearly outweigh bundle/dev-time costs.

## Frontend commonization rules

- Resource list pages use `ResourcePage`, `ResourcePanel`, `ResourceGrid`, `ResourceListCard`, `SearchFilterBar`, and `ResourceListState` before creating route-specific shells.
- Settings pages use `SettingsShell`, `SettingsSectionCard`, and `FormFieldShell` before creating local card/field wrappers.
- New counted tabs use `CountedTabs` or existing `LineTabs`; do not hand-roll `role="tablist"` buttons.
- New dialogs use `DialogShell`; direct `DialogContent` is limited to `components/ui/dialog.tsx`, `components/shared/dialog-shell.tsx`, and shared confirmation primitives.
- Do not use shared primitive implementation classes directly in product code:
  `moldy-empty-state`, `moldy-page-title`/`moldy-page-kicker`, and root
  `moldy-resource-panel`/`moldy-resource-card` classes belong to `EmptyState`,
  `PageHeader`/`PageShell`, and `ResourcePanel`/`ResourceListCard`.
- CRUD tables may use `DataTable`; domain-specific expandable tables can stay local. Do not force metric/read-only tables into `DataTable` unless behavior is reused.

## Frontend preflight and performance rules

- Run `pnpm preflight` before build/dev diagnostics. The project expects Node 22 and installed frontend dependencies.
- After frontend refactors run `pnpm lint`, `pnpm lint:a11y`, `pnpm lint:i18n`, `pnpm lint:design-system`, and `pnpm lint:frontend-architecture`.
- JSX accessibility coverage lives in `eslint.a11y.config.mjs` and
  `scripts/check-jsx-a11y.mjs`. Existing warnings are baselined in
  `scripts/jsx-a11y-baseline.json`; do not update that baseline unless the
  new/removed warnings were reviewed in the actual source.
- Do not add a new page-level `'use client'` without explaining why a Server Component wrapper plus Client island is insufficient.
- Keep heavy artifact viewers, markdown highlighters, document parsers, Mermaid, HWP/DOCX/XLSX/PPTX viewers, and similar libraries behind lazy/dynamic imports.
- New TanStack Query keys should be created through feature key factories, not ad hoc raw arrays inside components.
- Product date/time, number, USD, compact count, and file-size display formatting should use `src/lib/utils/display-format.ts`. Do not call `toLocaleString`, `toLocaleDateString`, `toLocaleTimeString`, or `new Intl.*Format` directly in `src/app` or `src/components`.
