# Sprint 1 / Story S2 — 设计 token oklch 修复 + DialogShell 视觉规范（Tim Cook）

## 目标
1. 确定 `--primary` / `--primary-foreground` / `--primary-strong` / `--ring` + semantic 状态色的精确 oklch 值（light/dark）
2. 将 DialogShell 视觉规范以精确 Tailwind class 记录到 ADR-010
3. 现有 raw color → 新 token 映射表
4. focus ring 弱化规范
5. base component（`ui/dialog.tsx`, `ui/sheet.tsx`）整理规范

## 产出物
- `docs/design-docs/ADR-010-ui-tokens-and-dialog-shell.md`（新增）
- 在 `AUDIT.log` 中新增一行（S2_DONE）
- 在 `progress.txt` 中新增 1-2 行 oklch 精确值（供 Zuckerberg 复制粘贴）

---

## A. 确定 oklch 精确值（基于 Tailwind v4 emerald palette）

Tailwind CSS v4 的颜色全部以 oklch 定义（参考 Tailwind v4.0 发布文与 tailwindcss/dist/preflight）。emerald 系列的 v4 oklch 值：

| Tailwind class | oklch 精确值 |
|---|---|
| emerald-50  | `oklch(0.979 0.021 166.113)` |
| emerald-100 | `oklch(0.95 0.052 163.051)` |
| emerald-200 | `oklch(0.905 0.093 164.15)` |
| emerald-300 | `oklch(0.845 0.143 164.978)` |
| emerald-400 | `oklch(0.765 0.177 163.223)` |
| emerald-500 | `oklch(0.696 0.17 162.48)` |
| emerald-600 | `oklch(0.596 0.145 163.225)` |
| emerald-700 | `oklch(0.508 0.118 165.612)` |
| emerald-800 | `oklch(0.432 0.095 166.913)` |
| emerald-900 | `oklch(0.378 0.077 168.94)` |
| emerald-950 | `oklch(0.262 0.051 172.552)` |

此外，用于 semantic 状态色的 v4 palette：

| Tailwind class | oklch 精确值 |
|---|---|
| amber-500   | `oklch(0.769 0.188 70.08)` |
| amber-400   | `oklch(0.828 0.189 84.429)` |
| sky-500     | `oklch(0.685 0.169 237.323)` |
| sky-400     | `oklch(0.746 0.16 232.661)` |
| violet-500  | `oklch(0.606 0.25 292.717)` |
| violet-400  | `oklch(0.702 0.183 293.541)` |
| red-500     | `oklch(0.637 0.237 25.331)` (= destructive light) |
| red-400     | `oklch(0.704 0.191 22.216)` (= destructive dark，当前已使用) |

### 决定值

light：
- `--primary: oklch(0.95 0.052 163.051);`        (= emerald-100，保持用户消息框背景不变)
- `--primary-foreground: oklch(0.262 0.051 172.552);` (= emerald-950)
- `--primary-strong: oklch(0.596 0.145 163.225);` (= emerald-600)
- `--ring: oklch(0.596 0.145 163.225 / 0.4);`     (= emerald-600 @ 40%)

dark：
- `--primary: oklch(0.378 0.077 168.94);`         (= emerald-900)
- `--primary-foreground: oklch(0.95 0.052 163.051);` (= emerald-100)
- `--primary-strong: oklch(0.765 0.177 163.223);` (= emerald-400)
- `--ring: oklch(0.765 0.177 163.223 / 0.45);`    (= emerald-400 @ 45%)

状态色（light/dark 共用——通过 alpha 调整背景色调）：
- `--status-success: oklch(0.596 0.145 163.225);` light / `oklch(0.765 0.177 163.223);` dark (= 与 primary-strong 相同)
- `--status-info: oklch(0.685 0.169 237.323);` light / `oklch(0.746 0.16 232.661);` dark (= sky-500/400)
- `--status-warn: oklch(0.769 0.188 70.08);` light / `oklch(0.828 0.189 84.429);` dark (= amber-500/400)
- `--status-danger: oklch(0.637 0.237 25.331);` light / `oklch(0.704 0.191 22.216);` dark (= red-500/400，destructive alias)
- `--status-accent: oklch(0.606 0.25 292.717);` light / `oklch(0.702 0.183 293.541);` dark (= violet-500/400)

### 明度对比验证（WCAG AA 4.5:1）
- light：emerald-100 (L=0.95) × emerald-950 (L=0.262) —— 近白背景 vs 近黑文本，contrast ≈ 14:1 ✅
- dark：emerald-900 (L=0.378) × emerald-100 (L=0.95) —— contrast ≈ 8:1 ✅
- ring alpha(35-45%) 随背景变化仍有足够可感知度（移除 border-ring，因此 visible focus 只通过 ring 呈现）

### Tailwind v4 @theme 格式注册
将添加到 `globals.css` 的 `@theme inline` block 中的行：
```
--color-primary-strong: var(--primary-strong);
--color-status-success: var(--status-success);
--color-status-info: var(--status-info);
--color-status-warn: var(--status-warn);
--color-status-danger: var(--status-danger);
--color-status-accent: var(--status-accent);
```
（`--primary`、`--primary-foreground`、`--ring` 复用现有映射）

---

## B. DialogShell 视觉规范

### 容器
```
flex flex-col overflow-hidden rounded-2xl shadow-2xl ring-1 ring-border/60 bg-popover
```
+ `DIALOG_SIZE` class + `DIALOG_HEIGHT` class + `max-h-[calc(100vh-4rem)]`

`DIALOG_SIZE` token（TS object → Tailwind class 映射）：
- `sm`: `w-[400px]`
- `md`: `w-[560px]`
- `lg`: `w-[720px]`
- `xl`: `w-[920px]`
- `console`: `w-[1080px]`

`DIALOG_HEIGHT` token：
- `auto`: `h-[480px] max-h-[calc(100vh-4rem)]`
- `fixed`: `h-[640px] max-h-[calc(100vh-4rem)]`
- `tall`: `h-[760px] max-h-[calc(100vh-4rem)]`

### Header（固定）
```
border-b border-border/60 px-6 py-5 flex items-start gap-4 relative
```
- icon slot：`flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary-strong`（currentColor domain icon）
- text wrap: `flex-1 min-w-0`
  - title: `text-base font-semibold tracking-tight text-foreground`
  - description: `mt-1 text-sm text-muted-foreground leading-relaxed`
- right action slot：`ml-auto flex items-center gap-2`（StatusChip、菜单等）
- close X: `absolute top-4 right-4 size-8 rounded-md hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring inline-flex items-center justify-center text-muted-foreground hover:text-foreground`

### Body（滚动）
```
flex-1 overflow-y-auto px-6 py-5
```
- section 间距：`space-y-6`
- section 内部：`space-y-3`
- input group：`space-y-1.5`
- label：`text-xs font-medium text-muted-foreground`
- divider：直接使用 `<div className="border-t border-border/60" />`（不使用 Separator component——保持 token 一致性）

### Footer（固定）
```
border-t border-border/60 bg-muted/30 px-6 py-4 flex items-center justify-end gap-2
```
- 标准按钮：`min-w-[80px]`
- pending: `<Loader2 className="mr-1 size-4 animate-spin" aria-hidden />`
- variant 优先级：左侧 secondary（“取消”），右侧 primary（“保存”）

### Sidebar（可选 slot）
```
w-[260px] shrink-0 border-r border-border/60 bg-muted/30 px-4 py-5 overflow-y-auto
```
当 DialogShell container 切换为 `flex-row` 时，与 `flex-1` 的 main 区域配对。

### 可访问性
- `role="dialog"`, `aria-labelledby={titleId}`, `aria-describedby={descriptionId}`（保持 Radix DialogPrimitive 默认实现）
- focus trap、ESC 关闭、点击 overlay —— Radix 默认行为
- motion：`data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 duration-200`

---

## C. 现有 raw color → 新 token 映射表

| 现有 class（light / dark） | 新 token class | 用途 / 位置示例 |
|---|---|---|
| `bg-emerald-100 dark:bg-emerald-900` | `bg-primary` | 用户消息框（assistant-thread.tsx:243）、发送按钮、active node 背景 |
| `text-emerald-950 dark:text-emerald-100` | `text-primary-foreground` | 上述强调背景上的文本 |
| `text-emerald-600 dark:text-emerald-400` | `text-primary-strong` | 链接、active tab 文本、hover、“active 用户消息”辅助文本 |
| `bg-emerald-500 dark:bg-emerald-400` (after::, indicator) | `bg-primary-strong` | tab indicator（`after:bg-...`） |
| `bg-emerald-100 ring-emerald-200 dark:bg-emerald-900 dark:ring-emerald-800` | `bg-primary/15 ring-primary-strong/30` | model badge、subtle chip |
| `bg-emerald-50 dark:bg-emerald-950/30` | `bg-primary/10` | 非常浅的强调背景 |
| `bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100` | `bg-status-accent/10 text-status-accent` | 对话式 card、分区强调 |
| `bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100` | `bg-status-warn/10 text-status-warn` | warning/注意 box |
| `bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100` | `bg-status-info/10 text-status-info` | 信息/提示 box |
| `bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-100` | `bg-destructive/10 text-destructive` | error box（复用现有 destructive token） |

按分析报告，约 58 处 ≈ 直接使用 emerald，另有 violet/amber/sky section。Zuckerberg 使用 mgrep + 映射表批量替换。

---

## D. focus ring 弱化规范

现有（input.tsx、textarea.tsx、select.tsx、button.tsx、checkbox.tsx 共用 pattern）：
```
focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50
```

新：
```
focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
```

原因：
1. `border-ring` 会把 input container 的 border color 整体改为强调色，产生“边框变厚”的感觉，因此移除。
2. `ring-3` 为 3px → 改为 `ring-2` 2px，降低强度。
3. `--ring` token 本身已内置 alpha(0.4 / 0.45)，因此 class 中无需再写 `/50`。只修改 CSS 变量即可自动应用 light/dark alpha。
4. 明确写 `outline-none`：避免部分浏览器默认 outline 与 ring 重叠显示。

补充：为保证键盘可访问性，`focus-visible:ring-offset-2 focus-visible:ring-offset-background` **只应用于按钮类**（input 不加 offset）。在 patch base component 时决定。

---

## E. base component 整理规范

### `ui/dialog.tsx`
- `DialogContent`:
  - 现有：`rounded-xl bg-popover p-4 ... ring-1 ring-foreground/10`
  - 新：  `rounded-2xl bg-popover ring-1 ring-border/60 shadow-2xl` —— 移除 `p-4`（由 DialogShell 管理 padding），`ring-foreground/10` → `ring-border/60`
- `DialogOverlay`:
  - 现有：`bg-black/80` 类
  - 新：  `bg-black/40 backdrop-blur-sm`
- 移除默认 `max-w` —— 由 DialogShell 的 `DIALOG_SIZE` 控制

### `ui/sheet.tsx`
- 只保留 mobile sidebar + conversation list 两处
- 圆角整理：右侧 panel 为 `rounded-l-2xl`，底部 panel 为 `rounded-t-2xl`。左/上边为 0
- shadow/ring token 化：`ring-1 ring-border/60 shadow-2xl`
- padding 由使用处管理（sheet 本身只作为 container）

### base input/textarea/select/button/checkbox
- 批量替换为上文 D 的 focus class
- 保留 `aria-invalid:ring-destructive/40 aria-invalid:border-destructive/60` pattern（error 状态表达）

---

## migration 影响

| 项目 | 变更位置数量 |
|---|---|
| globals.css token 新增/修改 | 1（`:root` + `.dark` + `@theme`） |
| ui/dialog.tsx | 1 |
| ui/sheet.tsx | 1 |
| ui/input·textarea·select·button·checkbox.tsx | 5 |
| emerald raw → primary token 替换 | ~58 处（mgrep） |
| violet/amber/sky raw → status token 替换 | 约 20-30 处（参见分析报告） |

代码工作由 Zuckerberg 在 Sprint 1-1~1-4 中拆分执行。ADR-010 是单一事实来源。

---

## 验证方法

1. **视觉回归**：用户消息框（assistant-thread.tsx）应与现有视觉完全一致——primary token 原样吸收 emerald-100/900
2. **WCAG AA**：light/dark 下 primary × primary-foreground contrast 均 ≥ 4.5 —— 上文已验证为 14:1 / 8:1
3. **focus 可见性**：使用键盘 Tab 时，所有 interactive element 都能看到 ring（CI：axe-core 或手动 QA）
4. **dark mode round-trip**：light→dark→light 切换时无闪烁，hue 相同，仅 lightness 改变
5. **build**：`pnpm build` 通过（Tailwind v4 `@theme inline` 能识别 token）

---

## 权衡（供 Satya 汇报）

**将用户消息颜色升级为 brand primary vs 单独拆分 `--user-bubble` token。**

选择：升级。原因：
- chat 是 Moldy 的核心 surface——最频繁出现的强调背景就是 brand identity
- 如果拆成 2 个 token，会把“只有用户消息使用另一种颜色”这种偶然差异固化，破坏一致性
- 成本：emerald-100 成为 light mode `--primary` 后，会偏离“primary 上使用黑色文本”的一般预期 → 通过 `--primary-foreground = emerald-950` 明确修正。因此依赖“primary 总是强强调色”这一常见假设的代码（例如随意组合 `bg-primary text-white`）可能出错——这种情况应立即改为 `text-primary-foreground`。

拒绝的替代方案：拆分 `--user-bubble` 需要额外维护 1 个 token，而且最终仍是同一 emerald tone，只是“对齐但分成两处”，反而模糊设计意图。

---

## 工作顺序（执行步骤）

1. 编写 ADR-010 —— 包含上文 A~E + migration 影响 + 验证方法 + 权衡
2. 在 `AUDIT.log` 新增一行：`[ISO时间] timcook S2_DONE ADR-010 + token oklch 修复 + DialogShell 视觉规范`
3. 在 `progress.txt` 中添加 1-2 行 oklch 核心值（供 Zuckerberg 复制到 globals.css）：
   ```
   - token oklch 修复（light）：--primary oklch(0.95 0.052 163.051) / --primary-foreground oklch(0.262 0.051 172.552) / --primary-strong oklch(0.596 0.145 163.225) / --ring oklch(0.596 0.145 163.225 / 0.4)
   - token oklch 修复（dark）：  --primary oklch(0.378 0.077 168.94) / --primary-foreground oklch(0.95 0.052 163.051) / --primary-strong oklch(0.765 0.177 163.223) / --ring oklch(0.765 0.177 163.223 / 0.45)
   ```
4. 向 Satya 汇报：ADR 路径 + 核心 oklch + 一句权衡

## 完成条件
- ADR-010 文件存在（Accepted, 2026-05-01）
- AUDIT.log 中有 S2_DONE 行
- progress.txt 中已添加 oklch 核心值
- 所有决定值都与 Tailwind v4 emerald/amber/sky/violet/red palette 的官方 oklch 一致（可验证）
