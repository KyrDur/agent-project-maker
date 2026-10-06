# Sprint 1 / Story S3 — design token + base 整理 + DialogShell + 辅助组件

**角色**: 扎克伯格（TTH frontend silo）
**工作目录**: `/Users/chester/dev/ref/natural-mold/frontend/`
**参考**: ADR-010, sheet-deletion-analysis.md, progress.txt 2026-05-01 section

---

## 事前确认（read-only）

- [x] 精读 ADR-010 — 确认 oklch 精确值、DialogShell spec、focus ring 缓和 spec
- [x] 确认 globals.css 当前状态 — `@theme inline` block 为 Tailwind v4 形式，token 定义在 `:root` + `.dark`
- [x] components/shared/ 目录 — 9 个现有文件（page-header.tsx 等必须保留）
- [x] lib/ 目录 — `constants/` 不存在 → 需要新建
- [x] AGENTS.md — Next.js 16 注意: 参考 docs 文件夹（本任务无 SC 变更，因此影响较小）

**减少探索**: 27 个 DialogContent 使用处 / 9 个页面 / 4 个 detail-sheet 超出本 story 范围。不改动。

---

## 分阶段工作 + 验证

### Phase 1 — Constants & design tokens（依赖 0）

**Files（新增）**:
1. `src/lib/design-tokens.ts` — `DIALOG_SIZE` (sm/md/lg/xl/console), `DIALOG_HEIGHT` (auto/fixed/tall) + 类型
2. `src/lib/constants/model.ts` — `MODEL_DEFAULTS` (temperature/topP/maxTokens)
3. `src/lib/constants/timing.ts` — `COPY_FEEDBACK_MS`, `WITTY_LOADING_ROTATE_MS`, `HEALTH_POLL_INTERVAL_MS`
4. `src/lib/constants/usage.ts` — `USAGE_PRESETS` + 类型

这些文件未被项目中任何文件 import，因此不会影响 build。

### Phase 2 — globals.css token 更新（破坏性变更）

编辑 `src/app/globals.css`:

**A. `:root` block（light）**
- `--primary: oklch(0.205 0 0);` → `oklch(0.95 0.052 163.051);` (emerald-100)
- `--primary-foreground: oklch(0.985 0 0);` → `oklch(0.262 0.051 172.552);` (emerald-950)
- 新增: `--primary-strong: oklch(0.596 0.145 163.225);` (emerald-600)
- `--ring: oklch(0.708 0 0);` → `oklch(0.596 0.145 163.225 / 0.4);` (emerald-600 @ 40%)
- 新增 semantic status color:
  - `--status-success: oklch(0.596 0.145 163.225);`
  - `--status-info: oklch(0.685 0.169 237.323);` (sky-500)
  - `--status-warn: oklch(0.769 0.188 70.08);` (amber-500)
  - `--status-danger: oklch(0.637 0.237 25.331);` (red-500)
  - `--status-accent: oklch(0.606 0.25 292.717);` (violet-500)

**B. `.dark` block**
- `--primary: oklch(0.922 0 0);` → `oklch(0.378 0.077 168.94);` (emerald-900)
- `--primary-foreground: oklch(0.205 0 0);` → `oklch(0.95 0.052 163.051);` (emerald-100)
- 新增: `--primary-strong: oklch(0.765 0.177 163.223);` (emerald-400)
- `--ring: oklch(0.556 0 0);` → `oklch(0.765 0.177 163.223 / 0.45);`
- 新增 semantic status color（dark）:
  - `--status-success: oklch(0.765 0.177 163.223);`
  - `--status-info: oklch(0.746 0.16 232.661);` (sky-400)
  - `--status-warn: oklch(0.828 0.189 84.429);` (amber-400)
  - `--status-danger: oklch(0.704 0.191 22.216);` (red-400)
  - `--status-accent: oklch(0.702 0.183 293.541);` (violet-400)

**C. `@theme inline` block**
在保留现有 mapping 的同时添加:
```
--color-primary-strong: var(--primary-strong);
--color-status-success: var(--status-success);
--color-status-info: var(--status-info);
--color-status-warn: var(--status-warn);
--color-status-danger: var(--status-danger);
--color-status-accent: var(--status-accent);
```

**验证**: `pnpm build`。只添加 token，预计通过。`--primary` 变更会对现有使用处产生视觉影响，但 build 应通过。

**破坏性变更备注**: `bg-primary text-white` 这类假设会失效的使用处，本 story 不改动，记录到 progress.txt。Sprint 2(S4/S5) 统一处理。

### Phase 3 — UI base component 整理

**5 个文件统一替换 focus ring**:
- `src/components/ui/input.tsx`
- `src/components/ui/textarea.tsx`
- `src/components/ui/select.tsx`
- `src/components/ui/button.tsx`
- `src/components/ui/checkbox.tsx`

现有模式: `focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50`
新模式: `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`

先 Read 每个文件，再 Edit 准确的 class 字符串。保留 `aria-invalid:` 类内容。

**`src/components/ui/dialog.tsx`**:
- DialogContent: `rounded-xl` → `rounded-2xl`, `ring-1 ring-foreground/10` → `ring-1 ring-border/60`，添加 `shadow-2xl`（若没有），保留 `p-4`（兼容性）
- DialogOverlay: `bg-black/80` → `bg-black/40 backdrop-blur-sm`
- 如果定义了关闭 X button，则增强为 `hover:bg-muted/60 rounded-md size-8`

**`src/components/ui/sheet.tsx`**:
- 右侧 panel `rounded-l-2xl`，底部 `rounded-t-2xl`（若存在则保持 tone 一致）
- 大幅变更 X

**验证**: `pnpm build` 通过。

### Phase 4 — Shared components（新增 6 个）

顺序（按依赖）:
1. `src/components/shared/error-state.tsx` — 依赖: ui/button。验证 `text-status-danger` token（如果没有则 `text-destructive` fallback + 备注）
2. `src/components/shared/dialog-shell.tsx` — 依赖: ui/dialog, lib/design-tokens, lib/utils。确认 shadcn dialog 的 export 签名后编写
3. `src/components/shared/delete-confirm-inline.tsx` — 依赖: ui/button, lucide-react
4. `src/components/shared/form-footer.tsx` — 依赖: ui/button, lucide-react
5. `src/components/shared/page-shell.tsx` — 依赖: shared/page-header（现有）, shared/error-state（新增）
6. `src/components/shared/base-detail-dialog.tsx` — 依赖: dialog-shell, delete-confirm-inline, error-state, ui/skeleton, ui/button, @tanstack/react-query，添加 useEffect 以在 id 变更时 reset confirming

**验证**: `pnpm build` 通过（没有使用处，因此只需捕捉 import error 即可 OK）。

### Phase 5 — 最终验证
- `pnpm build` 最终通过
- `pnpm lint` errors 0（忽略 warnings）

---

## 失败时应对

- 第 1 次失败: 分析 error message 后立即修复
- 第 2 次失败: 采用其他方法（例如 token key name 冲突则调整 key name，shadcn export 签名不同则更改 import 路径）
- 第 3 次失败: 向萨提亚 escalation（注明尝试过什么/推测原因）

---

## 完成汇报（萨提亚）

1. 在 AUDIT.log 添加一行:
   `[ISO时间] zuckerberg S3_DONE token+base 整理+DialogShell 新增 6 个 — pnpm build PASS`
2. 在 progress.txt 记录 1-3 行 pattern:
   - shadcn dialog/sheet 实际 export 签名
   - globals.css `@theme inline` mapping 时的注意点（如有）
   - 破坏性变更（`--primary`）side effect（如有则写位置）
3. 简短汇报: build 结果 / 视觉异常位置 / 进入 S4 所需信息

---

## 范围限制（绝对禁止）

- 4 个 detail-sheet 转换 X (S4)
- 27 个 DialogContent 使用处修改 X (S5)
- 9 个页面引入 PageShell X (S5)
- emerald raw color 批量替换 X (Sprint 2)
- agents settings RHF+Zod 转换 X (Sprint 3)
