# Verification — Agent Edit Workbench

**Date**: 2026-04-28
**Verifier**：Bezos（Jeff Bezos / QA DRI）
**Branch**: `feature/agent-edit-workbench`
**Plan**: `~/.claude/plans/image-41-ticklish-sky.md`
**判定（复验）**：**GREEN** — 自动 gate 全部 PASS。造成 YELLOW 的 2 个 MAJOR 已通过 hotfix 解决。剩余 1 个 MINOR（图片移除 placeholder）可顺延到下一个 PR。

> **复验时间**：2026-04-28（hotfix after initial YELLOW）
> **复验者**：Bezos
> **之前判定**：YELLOW（MAJOR 2 / MINOR 1）
> **当前判定**：GREEN（MAJOR 0 / MINOR 1）

---

## 自动 gate（全部 PASS）

| gate | 命令 | 结果 |
|---|---|---|
| Backend migration | `cd backend && uv run alembic upgrade head` | OK（已是 head，幂等 OK） |
| Backend tests | `cd backend && uv run pytest` | **628 passed**，1 deselected，17.82s — 保持 Jensen baseline |
| Backend lint | `cd backend && uv run ruff check .` | **All checks passed!** |
| Frontend build | `cd frontend && pnpm build` | **Compiled successfully in 4.0s**, TypeScript 4.4s, 14/14 static pages |
| Frontend lint | `cd frontend && pnpm lint` | **0 error / 0 warn** |

所有 gate PASS — 满足 CHECKPOINT.md done-when。

---

## regression 区域检查（Zuckerberg 剩余 5 项）

### 1. VisualSettingsFlow 内嵌 Save vs workbench 单一 Save → ⚠️ **MAJOR（已确认 regression）**

`frontend/src/components/agent/visual-settings/visual-settings-flow.tsx`
- L48~63：自身持有 11 种 internal state（name/description/systemPrompt/modelId/temperature/topP/maxTokens/selectedToolIds/selectedSkillIds/selectedMiddlewareTypes）
- L126~153：内部 `handleSave()` — 直接调用 `useUpdateAgent(agentId)`
- L368~374：仍然 render `<Toolbar onSave={handleSave} ... />`

`frontend/src/app/agents/[agentId]/settings/page.tsx`
- L298~312：`tab === 'visual'` 时 inline render `<VisualSettingsFlow ... />`，没有任何 prop 关闭内置 Toolbar/Save
- L247~252：header 中也存在单独的 `<Button onClick={handleSave}>`

**结果**：切换到 visual mode 时，画面出现 2 个 Save 按钮。
- 数据丢失风险：低（各自从自己的 state 调用相同 update API，即使 race 也是最后一次调用获胜）
- isDirty signal 分离风险：**存在** — 用户在 visual mode 切换 ToolboxNode 时，仅 VisualSettingsFlow internal state 改变，而页面 header 的 isDirty 保持 false，导致 "保存" 按钮禁用。用户必须按 Toolbar 内置 Save 才能保存 → 如果 form/visual 两边同时存在变更，一边会覆盖另一边。

**建议**：以下二选一
- (a) 为 `VisualSettingsFlow` 新增 `embedded?: boolean` prop → true 时隐藏 Toolbar + 从 internal state 切换为由 props 驱动的 controlled mode
- (b) 在 M8 HANDOFF 明确 "visual mode 仅在独立 route（`/agents/[id]/visual-settings`）使用"，并将 workbench [visual] tab 降级为 read-only preview

### 2. SettingsPanel "图片移除" toast placeholder → MINOR

`_components/right-panel/settings-panel.tsx:28~31, 67~71`
- `handleRemove()` 仅显示 `toast.info(tc('comingSoon.default'))`
- 按钮始终显示（`{imageUrl && ... 图片移除 ...}`）
- 用户 confusion 风险：中等 — 点击后图片不会消失，只弹 toast，可能怀疑 "是 bug 吗？"
- **建议**：在下一个 PR 前将按钮改为 disabled + tooltip "即将支持"，或直接从 menu 隐藏

### 3. TestChatPanel 复用 streamAssistant(Fix endpoint) → MAJOR（UX mismatch）

`_components/right-panel/test-chat-panel.tsx:34~38`
- `streamFn = streamAssistant(agentId, content, signal, sessionId)` — 使用 Fix(meta-agent) endpoint
- 组件注释明确写着 "MVP: 复用 streamAssistant(Fix endpoint)。如果新增独立 ephemeral conversation endpoint，只需替换 streamFn。"

**问题**：[测试] tab 并不是 preview 用户创建 agent 的实际行为，而是获得 "该如何修改 agent" 的 meta response。与 PRD/spec 的 "新增 — 一般 agent 自由对话聊天" 定义不一致。

**风险度**：高 — 用户如果信任 [测试]，可能错误评估实际 agent 行为。

**建议**：在 M8 前 / 下个 sprint 拆出新增 ephemeral conversation endpoint 任务。短期在 [测试] tab 增加 "Fix panel preview" label/banner。

### 4. 保留 `/agents/[id]/visual-settings` 独立 route → OK

`pnpm build` 结果正常生成 `ƒ /agents/[agentId]/visual-settings` route。页面组件（`visual-settings/page.tsx`）也原样工作 — 无 regression。下一个 PR 计划处理 `redirect()`（spec 已明确）。

### 5. 每行 [⚙] config edit placeholder → 无关（实际未暴露）

`tools-middlewares-grid.tsx:163~181` 的 `Row` 组件仅在有 `onConfig` prop 时 render [⚙] 按钮。目前 `ToolsBox` / `MiddlewaresBox` 均未传递 `onConfig`（L60~67, L101~107）。→ 用户看不到 [⚙] 本身。spec 的 "即将支持 toast" 场景尚无执行路径。无 regression。

`section-model.tsx`, `section-sub-agents.tsx` 的 [⚙] 分别正常打开 ModelDialog / SubAgentsDialog。

---

## 废弃残留验证

```bash
grep -rn "basic-info-tab\|model-tab\|tools-skills-tab" frontend/src/ | grep -v node_modules
```

**结果**：0 hits。3 项废弃内容的 import / reference 已全部移除。

`ls _components/`:
```
dialogs/  form-mode/  right-panel/  triggers-tab.tsx
```
被废弃的 3 个文件在 git status 中显示为 `D`（已确认 status snapshot）。

---

## 场景验证（静态代码 review）

| 场景 | 文件:行 | 结果 |
|---|---|---|
| `/agents` dashboard 正常 | `app/page.tsx`（无修改） | OK — Agent 类型仅新增 `opener_questions` optional（lib/types/index.ts:18） |
| `/agents/new` 正常 | `app/agents/new/*`（无修改） | OK — creation flow 未修改 |
| `/agents/[id]/conversations/[cid]` empty state opener | `conversations/[cid]/page.tsx:185~224` | OK — `agent.opener_questions ?? []` fallback，长度 0 时不显示按钮。安全调用 `composer?.setText(q)`（optional）。 |
| header inline 编辑 → 保存 | `settings/page.tsx:206~217, 247~252, 141~161` | OK — name/description Input → page state → 包含在 handleSave payload |
| form ↔ visual toggle | `settings/page.tsx:258~313` | OK，但存在上面 #1 dual-save regression |
| 每行 [⚙] → dialog | `section-model.tsx:44`, `section-sub-agents.tsx:43` | OK |
| +工具/+middleware → modal | `tools-middlewares-grid.tsx:55, 96` | OK |
| [Fix] AssistantPanel 行为 | `right-panel.tsx:72~79`, `assistant-panel.tsx:21~88` | OK — `showHeader={false}` prop 正常应用 |
| [测试] 聊天行为 | `test-chat-panel.tsx` | 行为 OK，含义存在上面 #3 regression |
| [opener] 添加/删除/保存 | `opener-editor.tsx`（结构 OK），`page.tsx:323~324` | OK — onChange → page state → save payload `opener_questions`（page.tsx:155） |
| [schedule] trigger 添加/删除 | `right-panel.tsx:93~95`，复用 `triggers-tab.tsx` | OK — `onRequestDelete` callback 正常 wired（page.tsx:325, 343~348） |
| [设置] 图片生成/重新生成/移除 | `settings-panel.tsx` | 生成/重新生成 OK（`useGenerateAgentImage`），移除是 placeholder（见上面 #2） |
| 未保存 [←] confirm | `page.tsx:172~183` | OK — `window.confirm(t('unsavedWarning'))`。beforeunload 也在 132~139 行处理 |
| Backend opener_questions wiring | `models/agent.py:30`, `schemas/agent.py:15~36, 72~77, 93~98, 127`, `services/agent_service.py:67, 116~117`, `alembic/versions/m16_add_opener_questions.py` | OK — migration + model + schema（validator 12 个 / 200 字 / non-empty）+ service create/update 路径 |

---

## 已发现问题摘要

| # | 分类 | 区域 | 要点 |
|---|---|---|---|
| 1 | **MAJOR** | VisualSettingsFlow inline 使用 | workbench header Save 与 visual 内置 Toolbar Save 同时暴露 → isDirty 分离，一边可能覆盖另一边 |
| 2 | MINOR | SettingsPanel "图片移除" | 暴露了点击时仅弹 toast 的 placeholder，可能造成用户 confusion |
| 3 | MAJOR | TestChatPanel | 复用 Fix endpoint → [测试] 显示 meta agent 响应。无法验证真实 agent 行为 |
| 4 | — | visual-settings 独立 route | 无 regression（下一个 PR 计划 redirect） |
| 5 | — | 工具/middleware 行 [⚙] | 未暴露 — 无 regression |

**BLOCKER**：0 项
**MAJOR**：2 项（#1, #3）
**MINOR**：1 项（#2）

---

## 建议用户手动验证的项目（5）

1. **[⚠️] visual mode dual-save 体验**：在 workbench 点击 [visual] tab → 确认右上角 ToolBar Save 按钮是否与 header Save 重复出现。若出现，尝试用其中一个保存 → 回到 form mode 检查变更是否反映。
2. **[⚠️] [测试] tab 响应性质**：输入 "你好" → 确认响应是一般 assistant 语气，还是 "要怎么修改呢" 语气。若是后者，实证 issue #3 的 UX mismatch。
3. **opener end-to-end**：在 workbench [opener] 添加 1~3 个问题 → 保存 → 进入 `/agents/[id]/conversations/new` → 点击空页面按钮 → 确认 composer 文本被注入（不发送）。
4. **header inline 编辑 + 刷新**：修改名称/描述 → 保存 → F5 → 确认保持。
5. **点击 [设置] 图片移除**：仅弹 toast，图片保持不变 → 实证 issue #2。

---

## 判定依据

- **自动 gate**：全部 PASS — 满足 done-when
- **regression 场景**：数据丢失可能性 0，废弃残留 0
- **致命缺陷**：无（BLOCKER 0）
- **但是**：2 个 MAJOR 是直接暴露给用户的 UX regression — 不应视为 "Good enough"

→ **YELLOW**。Satya 判断：
- (A) 2 个 MAJOR 在 M7 内立即修复后重新判定 GREEN → 推荐
- (B) 拆分为 M8 follow-up 任务 + 在 HANDOFF 中显式登记 risk 后 merge → 次选

技术上当前状态可 merge 到 main，但按 Bezos 标准 "Day 1 mentality" 推荐选择 (A)。

---

## 复验（Hotfix Verification, 2026-04-28）

Zuckerberg 按 (A) 路径进行 hotfix。Bezos 复验结果 → **GREEN**。

### 自动 gate（重新执行）
- `pnpm build`: PASS — 14/14 static pages, no TypeScript error
- `pnpm lint`: PASS — 0 error / 0 warn
- backend：无变更（省略重新执行）

### MAJOR #1 — VisualSettingsFlow dual-save → 已解决 ✅

`components/agent/visual-settings/visual-settings-flow.tsx`
- L22~46：新增 `ControlledVisualState` / `ControlledVisualHandlers` interface（state 11 种 + handler 10 种）
- L62~65：props 新增 `embedded?: boolean` + `controlledState?` + `controlledHandlers?`
- L108：明确 guard `isControlled = embedded && !!controlledState && !!controlledHandlers` — 三者都满足才 controlled（防止不完整 prop 导致事故）
- L109~138：所有 read/write 路径统一为 `isControlled ? controlled... : internal...` 分支
- L141~164：同步 agent prop 的 useEffect / default model 设置也加入 `if (isControlled) return` guard — controlled mode 下绕过 internal state setter ✅
- L166~197：`toggleTool` / `toggleSkill` / `toggleMiddleware` callback 也按 `if (isControlled) controlledHandlers!.onToggleX(...) else setInternalSelectedX(...)` 分支 ✅
- L469~477：`{!embedded && <Toolbar ... />}` — embedded 时不 render 内置 Toolbar ✅

`app/agents/[agentId]/settings/page.tsx`
- L301~337：`<VisualSettingsFlow ... embedded controlledState={...} controlledHandlers={...} />` — 直接委托页面 useState 值/setter。Set toggle 采用 `(prev) => toggleSetItem(prev, id)` 模式 immutable 处理

**Backward compat 确认**：
- `app/agents/[agentId]/visual-settings/page.tsx`：未传 `embedded` → false → 显示 Toolbar + 使用 internal state。现有行为 100% 保留 ✅
- `app/agents/new/manual/*`：grep 结果 0 hit。无 embedded ✅
- `pnpm build` Route 列表中 `/agents/[agentId]/visual-settings` 仍显示为 ƒ ✅

**剩余 note（参考）**：embedded mode 下内部 `useUpdateAgent`/`useCreateAgent` hook 仍会实例化，但调用路径（handleSave）因 Toolbar 移除而不可达。无 memory/network 影响。未来整理时可条件拆分 useMutation，但受 React Hooks 规则（禁止条件调用）限制，当前结构更安全。

### MAJOR #2 — TestChatPanel banner → 已解决 ✅

`_components/right-panel/test-chat-panel.tsx:53~57`
- panel 最上方（thread 上方）添加 amber tone banner：
  ```
  ⚠ MVP: 当前使用与 Fix agent 相同的 endpoint。一般聊天拆分将在后续 PR 进行。
  ```
- dark mode 对应：`border-amber-200 bg-amber-50 text-amber-900`（light）→ `dark:border-amber-900/40 dark:bg-amber-950/40 dark:text-amber-200`（dark）✅
- container 使用 `border-b` 与正文 thread 视觉分隔 ✅
- 用户 confusion 风险：已解决 — 首次 interaction 前明确 limitation
- streamFn(Fix endpoint) 行为本身无变更（按 spec，ephemeral endpoint 在后续 PR 拆分）

**剩余 note（参考）**：banner 字符串是非 i18n key 的硬编码韩文。向英文用户暴露时未翻译。建议在 M8/HANDOFF 整理 i18n，但不至于阻塞本次 PR → PASS。

### MINOR #1 — 图片移除 placeholder

不在本次 hotfix 范围。状态不变 — 顺延到下一个 PR。建议在 HANDOFF 登记 follow-up 项。

### 新增 regression 检查（hotfix 本身可能引发）
- VisualSettingsFlow 内部 `handleAgentNodeUpdate` 使用 `setName`/`setDescription` 等 polymorphic setter — controlled mode 调用页面 useState → 正常。uncontrolled mode 调用 internal setter → 正常。
- ReactFlow node data（`nodes` state）由 `useNodesState(initialNodes)` 仅初始化一次，并通过 useEffect 更新（L296~）。controlled mode 下 page state 变化会改变 read 值（name/description/...），且这些值包含在 useEffect dependency 中，因此 node 也重新计算 → 正常 ✅
- `useEdgesState(computedEdges)` + useEffect 同步也采用相同模式 → 正常

### 最终判定

| 项目 | 之前 | 当前 |
|---|---|---|
| 自动 gate | PASS | PASS |
| BLOCKER | 0 | 0 |
| MAJOR | 2 | **0** |
| MINOR | 1 | 1（顺延） |
| 废弃残留 | 0 | 0 |
| 判定 | YELLOW | **GREEN** |

→ **GREEN**。满足 M7 done-when。可继续 M8(HANDOFF)。
