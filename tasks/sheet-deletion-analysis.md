# Sheet 使用处 + 删除分析 — UI Refactor M-UI1 (S1, bezos)

> **NOTE**：由于 Plan 模式 已启用，本报告写入 plan 文件。
> 萨提亚可在执行阶段将本内容移至 `tasks/sheet-deletion-analysis.md`，并
> 同时更新 AUDIT.log + progress.txt。
> （贝索斯的分析本身已 100% 完成）

---

## 1. Sheet 使用处全量清单（grep 结果）

| # | 文件路径:行 | 类型 | 转换/保留 |
|---|---|---|---|
| 1 | `src/components/ui/sheet.tsx` | UI primitive（定义） | 保留（sidebar 需要） |
| 2 | `src/components/ui/sidebar.tsx:177-196` | 移动端侧边栏 | **保留**（移动端滑动 UX 合适） |
| 3 | `src/app/agents/[agentId]/conversations/[conversationId]/page.tsx:105-126` | 移动端 对话 列表（`md:hidden`） | **保留**（移动端 左侧 滑动 UX 合适） |
| 4 | `src/components/credential/credential-detail-sheet.tsx:73-205` | Credential 详情 | **转换为 Dialog** |
| 5 | `src/components/skill/skill-detail-sheet.tsx:36-46, 108-210` | Skill 详情（双 SheetContent） | **转换为 Dialog** ⚠ |
| 6 | `src/components/tool/tool-detail-sheet.tsx:57-127` | Tool 详情 | **转换为 Dialog** |
| 7 | `src/components/mcp/mcp-server-detail-sheet.tsx:95-182` | MCP 详情 | **转换为 Dialog** |

**验证**：除以上 7 处外没有 Sheet 使用处。与 PRD 假设一致。

---

## 2. Dialog 转换对象（4 个）— 调用映射

### 2-1. credential-detail-sheet.tsx (219 lines)
- **调用处**：`src/app/credentials/page.tsx:14, 156`
- **prop 签名**：`{ credentialId: string | null, open: boolean, onOpenChange: (open: boolean) => void }`
- **调用模式**：
  ```tsx
  <CredentialDetailSheet
    credentialId={detailId}
    open={!!detailId}
    onOpenChange={(open) => !open && setDetailId(null)}
  />
  ```
- **删除确认 内联 UI**：line 179 — `border-destructive/40 bg-destructive/5 p-3`
- **风险**：包含 Audit logs 部分 — Dialog 内需要滚动区域

### 2-2. skill-detail-sheet.tsx（212 lines）⚠ 特殊用例
- **调用处**：`src/app/skills/page.tsx:15, 185`
- **prop 签名**：`{ skillId, open, onOpenChange }`（与上面相同模式）
- **结构特殊**：外层 `SkillDetailSheet` + 内层 `SkillDetailBody`（独立组件，key reset 模式），有两个 SheetContent。
  - 外层（line 42）：Loading placeholder
  - 内层（line 108）：实际正文 — `SkillDetailBody` 是独立函数
- **删除确认 内联 UI**：line 191
- **转换时注意**：改为 Dialog 包裹时必须保留 `key={skillId}` 模式。`DialogContent` 保留 `sm:max-w-xl` 宽度。

### 2-3. tool-detail-sheet.tsx (130 lines)
- **调用处**：`src/app/tools/page.tsx:16, 155`
- **prop 签名**：`{ toolId, open, onOpenChange }`
- **删除确认 内联 UI**：line 108
- **风险**：最简单。转换最容易。

### 2-4. mcp-server-detail-sheet.tsx（242 lines）⚠ prop 名不同
- **调用处**：`src/app/mcp-servers/page.tsx:16, 166`
- **prop 签名**：`{ serverId: string | null, open, onOpenChange }` — `serverId`（其他 3 个是 `xxxId` 模式，但语义相同）
- **删除确认 内联 UI**：line 163
- **附加功能**：调用 `useTestMcpServer`、`useDiscoverMcpTools` — 需要在 Dialog 中保留 操作 区域

---

## 3. 保留 Sheet（2 处）

| 位置 | 原因 |
|------|------|
| `components/ui/sidebar.tsx:177` | 移动端侧边栏 — 左侧滑入模式是 Sheet 的标准用法。Dialog 不合适。 |
| `app/agents/[agentId]/conversations/[conversationId]/page.tsx:105` | `md:hidden` 移动端 专用 对话 列表 — 需要保留左侧 滑动 UX。 |

→ 因为以上 2 处，`components/ui/sheet.tsx` primitive **必须保留**。

---

## 4. 可立即删除（Musk Step 2）

Dialog 转换完成后：
- 从 4 个 detail-sheet 文件的 import 中移除 `Sheet`, `SheetContent`, `SheetHeader`, `SheetTitle`, `SheetDescription`
- 建议在转换 PR 中将文件名 rename 为 `*-detail-dialog.tsx`（萨提亚决定）
- 同时修改 4 个调用处的 import 路径 + 组件名

**已确认：没有额外 dead code。**

---

## 5. 需要审查删除（需萨提亚确认）

### `components/shared/page-header.tsx` — **禁止删除** ⚠
PRD 写的是"使用处 0 个"，但**重新验证发现有 7 个页面正在使用**：
- `src/app/settings/page.tsx:8,16`
- `src/app/settings/system-credentials/page.tsx:8,52`
- `src/app/tools/page.tsx:8,105`
- `src/app/agents/new/template/page.tsx:15,54`
- `src/app/usage/page.tsx:36,153`
- `src/app/models/page.tsx:17,349`
- `src/app/skills/page.tsx:10,95`
- `src/app/mcp-servers/page.tsx:11,130`
- `src/app/credentials/page.tsx:8,119`

→ **PageHeader 正在被频繁使用。删除会破坏 9 个页面。**
→ "?": PRD 的 "PageHeader 使用处 0 处" 分析是从哪里得出的？推测是与其他组件混淆了。

---

## 6. 风险/注意事项

### 🔴 风险-A: skill-detail-sheet 的双重 SheetContent
- 外部 wrapper + 内部 `SkillDetailBody` 分离的结构 (line 36-46 + 108-210)
- 如果简单用 sed 将 `Sheet→Dialog` 替换，**会出现类型错误 + key reset 行为失效**
- 转换时需整合为 `Dialog open={open} onOpenChange={...}` + 内部 1 个 `<DialogContent>`
- 保留 `SkillDetailBody` 的 `onClose={() => onOpenChange(false)}` 签名

### 🟡 风险-B: 内容长度
- `mcp-server-detail-sheet.tsx` (242行)、`credential-detail-sheet.tsx` (219行) 的表单 + 测试 + 审计日志等内容较长
- Dialog 默认 max-h 较小，因此需明确指定 **`max-h-[85vh] overflow-y-auto`**
- Sheet 的 `sm:max-w-md` / `sm:max-w-xl` 宽度可原样迁移到 Dialog

### 🟡 风险-C: prop 签名一致性
- 4个全部采用 `{ <name>Id: string | null, open, onOpenChange }` 相同模式
- 但 mcp 使用 `serverId`，名称依赖领域 — 转换时建议原样保留（尽量减少调用方变更）

### 🟢 安全: 删除确认内联 UI
- 4个全部使用 `rounded border border-destructive/40 bg-destructive/5 p-3 text-xs` 相同模式
- 转换为 Dialog 时保持相同 class — 回归风险低
- （注意: text-xs 是 OK，但 PRD 提到的 `text-[10px/11px]` 任意值在这 4 个文件中未发现 — Sprint 2 中另行识别）

---

## 7. 转换后验证命令

```bash
# 1. 确认 SheetContent 除 mobile sidebar + conversation list 外是否为 0 处
cd frontend && grep -rn "SheetContent" src/components/ src/app/
#   → 预期结果: 仅匹配 ui/sheet.tsx（定义）、ui/sidebar.tsx、app/agents/.../conversations/[id]/page.tsx

# 2. 确认 4 个 detail-sheet 文件是否已 rename 为 detail-dialog
ls frontend/src/components/{credential,skill,tool,mcp}/*detail*

# 3. 确认 4 处调用方是否从 Dialog import
grep -rn "DetailDialog" frontend/src/app/

# 4. 构建通过
cd frontend && pnpm build

# 5. 类型检查
cd frontend && pnpm exec tsc --noEmit
```

---

## 向萨提亚汇报

**报告位置**: 本 plan 文件。执行阶段移至 `tasks/sheet-deletion-analysis.md`。

**2 个核心风险**:
1. **PRD 误判 — 严禁删除 `PageHeader`**: 9 个页面正在使用。PRD 的 "使用处 0 处" 分析有误。("?" 需要)
2. **`skill-detail-sheet.tsx` 双重 SheetContent**: 无法简单替换。转换为 Dialog 时必须保留 `SkillDetailBody` 分离结构和 `key={skillId}` reset 模式，才能避免回归。

**附加信息**:
- 4 个转换目标文件的 prop 签名采用相同模式（`{xxxId, open, onOpenChange}`）— 调用方改动最小。
- 仅 mcp 使用 `serverId`（其他 3 个为 `credentialId/skillId/toolId`）— 属于有意的领域命名，建议保留。
- 4 个删除确认内联 UI 相同（`border-destructive/40 bg-destructive/5 p-3`）— 后续可提取为 `<DeleteConfirmInline>` 公共组件（Sprint 2~3 候选）。
