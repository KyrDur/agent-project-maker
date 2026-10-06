# HANDOFF — merge 后 hotfix + dashboard UX 打磨（session 9, 2026-04-29 晚）

**Base**: `main @ b5515bc` (PR #78 merge 后) — 8个文件未 commit
**状态**: BE pytest **647 passed** / ruff clean / FE lint 0/0 / build 14/14

---

## 本次 session 核心变更

### 🔴 Critical: Anthropic 聊天无响应 bug
- **症状**: 所有 Claude 智能体发送消息后只 emit SSE `error` event 并立即结束 (Anthropic API 400 `temperature and top_p cannot both be specified`)
- **原因**: agent.model_params default 为 `top_p=1.0`，因此每次请求都和 temperature 一起发送 → 仅 Anthropic 拒绝
- **修复**: `backend/app/agent_runtime/model_factory.py`
  - `top_p == 1.0`(sampling off default) → 在所有 provider 中 omit
  - 新增: `provider == "anthropic"` + 两者都显式指定(0.95等) → 自动移除 top_p (优先 Anthropic 推荐 knob temperature)

### Dashboard UX
- `src/app/page.tsx`: 固定 hero(`shrink-0`)/quickActions(`shrink-0`) + 仅卡片 grid 自身 scroll。外层 `overflow-hidden`, 内层 `scrollbar-hide flex min-h-0 flex-1 overflow-y-auto px-1` (px-1 防止卡片 ring 被裁剪)
- `src/app/globals.css`: 新增 `@utility scrollbar-hide` (Tailwind v4)
- 统一现有分散的 scrollbar class: `scrollbar-none`(right-panel) + `no-scrollbar`(sidebar) → 全部 `scrollbar-hide`

### 放大 Settings 角色尺寸
- 在 `AgentAvatar` sizeMap 新增 `xl` variant (`size-44 sm:size-52` = 176/208px) — 与 FixHero 相同
- `settings-panel.tsx`: `size="lg"` → `size="xl"`, spinner `size-6` → `size-10`, progress bar `w-48` → `w-52`

### i18n
- 在 `messages/ko.json` 新增 `agent.settings.defaultName: "新智能体"` — manual 页面 namespace mismatch fix（解决 `MISSING_MESSAGE`）

### 尝试更换图像生成模型 → 回滚
- 改为 `image_gen_model: openai/gpt-5.4-image-2`，但响应过慢 → 回滚为 `google/gemini-3.1-flash-image-preview`

### /simplify 后续整理
- 分离 `model_factory.py` 两个 guard 的意图注释 (default omit vs 规避 Anthropic 拒绝)
- 为 `page.tsx` wrapper 增加注释（明确意图）
- 在 `globals.css` 增加 EOF newline

---

## 下一步工作（与 PR #78 后续列表相同，无变化）

| 优先 | 项目 |
|---|---|
| 1 | **创建 PR** — 上述8个文件未 commit 变更（以 hotfix 为主，建议单一 PR） |
| 2 | 集成 LangGraph executor sub-agent 执行 (PR #78 后续) |
| 3 | 浏览器手动验证 — Anthropic 聊天正常、dashboard 卡片无限滚动、settings 角色尺寸 |
| 4 | 拆分 TestChatPanel ephemeral conversation endpoint |
| 5 | LangSmith 429 traces 超限 — 独立问题，不影响 graph 运行。下月 reset 或修改 LangSmith 设置 |

---

## 注意事项

- **`top_p < 1.0` + Anthropic 用户显式指定场景**: top_p 会被自动移除 (temperature 优先)。需要注意用户预期的 top_p 值会被忽略
- **AgentAvatar `xl` Image `unoptimized`**: 移动端也下载 px=208 → downscale 成本很小，但应用到 grid 时需重新评估
- **图像模型兼容性**: `image_service.py` 使用 Gemini 特化 payload (`image_config: aspect_ratio`, system message + 参考图)。切换到 OpenAI 系列时需要 endpoint/payload 分支
- **dashboard wrapper 子元素缩进**: 整理96行 indent 成本较高 + 不影响 lint，因此 skip。交给 prettier auto-format

---

## 核心文件（本次 session 修改）

- `backend/app/agent_runtime/model_factory.py` (top_p / Anthropic 分支) ⚠ Critical
- `frontend/src/app/page.tsx` (dashboard layout 拆分 + scrollbar-hide)
- `frontend/src/app/globals.css` (`@utility scrollbar-hide`)
- `frontend/src/components/agent/agent-avatar.tsx` (`xl` size)
- `frontend/src/app/agents/[agentId]/settings/_components/right-panel/settings-panel.tsx` (xl + spinner/progress)
- `frontend/src/app/agents/[agentId]/settings/_components/right-panel/right-panel.tsx` (统一 scrollbar-hide)
- `frontend/src/components/ui/sidebar.tsx` (统一 scrollbar-hide)
- `frontend/messages/ko.json` (defaultName)

---

新 session 中可通过"读取 HANDOFF.md 并创建 PR / 继续 executor sub-agent 集成"等继续。

---

# HANDOFF — sub-agent 拆分完成 + Codex review 4轮通过（session 8, 2026-04-29 下午）

**Base**: `main @ 0609210` (session 6 PR merge 后) → `feature/agent-edit-workbench` 分支累计 session 7 + 8 未 commit
**状态**: 所有验证 GREEN — BE pytest **647 passed** / ruff clean / alembic m17 roundtrip OK / FE lint 0/0 / build 14/14
**规模**: 33 changed +2521/-1023 + 23 untracked。相比 main 共56个文件。

---

## 本次 session 核心变更

### 1. sub-agent dialog UX 完成 (Image #68/69 方案)
- 行压缩: `[👥] sub-agent  名称1, 名称2 +N  [⚙]` 单行 button (text-[10px] summary, cursor-pointer, text-foreground/80 icon)
- dialog 左/右2栏: "当前 sub-agent(N)" + "可用智能体（搜索）"卡片列表
- dialog height 固定: `max-h-[60vh] sm:h-[60vh]` — 防止移动端 viewport overflow

### 2. Codex review 4轮 fix
- **R1 P1**: 对 `agent_service.create/update` 的 sub_agent_ids 增加 cross-tenant + 不存在校验 (`_validate_sub_agent_ids_owned`) — 与聊天 write_tool 相同保护
- **R1 P2**: 不存在 UUID → 4xx (此前 IntegrityError → 500)
- **R2 P1**: 将 `settings/page.tsx` useEffect 改为 **dirty-aware sync** — 以 `lastSyncedAgentRef`(server snapshot) 为基准逐字段比较，只 sync 用户未触碰字段的 server 值，保留已修改字段
- **R2 P2**: `read_tools.get_agent_config` 响应增加 `sub_agents` 字段 — LLM 在 ADD/REMOVE workflow 第1步即可获知当前 sub-agent 列表
- **R3（反驳）**: P1-B "thread.append 不会启动 stream"不准确 — 确认 assistant-ui v0.12.24 `ExternalThread.js:347-374` 中显式调用 `onNew?.()`，工作正常

### 3. /simplify 后续整理（8项）
**Backend**
- 增加 Tool/Skill ID owned 校验 (`_validate_tool_ids_owned`/`_validate_skill_ids_owned`) — 扩展与 sub_agent 相同的保护
- 从 `_selectin_agent`/`helpers.py` 移除 `selectinload(AgentSubAgentLink.sub_agent)` 步骤 (lazy="joined" 重复)
- `add_subagent_to_agent` **N+1 → 单一 IN query** (3-pass: parse → batch validate → append)
- 整理 skipped 消息韩/英混用 (`(already added)` → `(已添加)`, `(not found)` → `(找不到)`)

**Frontend**
- `useChatRuntime.onStreamEnd((didMutate: boolean) => void)` — 通过 `MUTATION_PREFIXES`(add_/remove_/update_/edit_/delete_/enable_/disable_/create_) 匹配进行精确 invalidate。纯文本/查询响应不 refetch 表单
- `clarifying-question-ui.tsx` cn nested → 3-state union (`'idle' | 'selected' | 'dimmed'`) + STATE_CLASS lookup
- 移除 `tools-middlewares-grid.tsx` Row 的 `removeLabel` props sprawl → 内部 `useTranslations('common')`

### 4. BE 新增测试6项（总 642 → 647）
- `test_sub_agent_self_reference_reject`, `test_sub_agent_duplicate_ids_reject`, `test_sub_agent_cascade_delete`, `test_sub_agent_mix_self_and_valid_reject`, `test_sub_agent_cross_user_owner_rejected`
- `test_sub_agent_nonexistent_id_rejected`, `test_tool_ids_nonexistent_rejected`, `test_skill_ids_nonexistent_rejected`

---

## 下一步工作

| 优先 | 项目 | 影响 |
|---|---|---|
| 1 | **创建 commit/PR** — 拆分 session 6/7/8 变更或单一 PR | 高 |
| 2 | 浏览器手动验证 — 与 Image #67 方案一致、聊天↔表单双向同步、dirty-aware sync edge case | 高 |
| 3 | 在 LangGraph executor 中将 sub_agent_links → deepagents `task` 工具转换·注入（实际执行逻辑） | 中 |
| 4 | 移除 `agent_subagent.py` 的 `lazy="joined"` 的可能性 — 在单独 PR 验证 async 环境无回归 | 低 |
| 5 | 提取 `useAgentFormState` hook (settings/manual state 镜像统一) — 判定为时机过早，新增字段时重新评估 | 低 |
| 6 | 拆分 `VisualSettingsFlow.Controlled / Standalone` (移除 isControlled 11对分支) | 低 |
| 7 | `(user_id, name)` UNIQUE constraint — 从根本上解决 Skill 同名 dedupe（当前 application-side dedupe） | 低 |

---

## 注意事项

- **dirty-aware sync 回归风险**: 11个字段的 `form === prev` 比较为手写。新增字段时若漏掉比较可能出现 silent revert 回归 — 建议增加 unit test
- **agent_subagent.py `lazy="joined"`**: 因回归风险决定保留。SQL 体积增大 → 后续 PR 单独验证后整理
- **assistant-ui thread.append 验证**: v0.12.24 `ExternalThread.js:347-374` 显式 `onNew?.()` — 升级到其他版本时注意行为可能改变
- **PRAGMA foreign_keys 未启用**: SQLite 测试环境。reverse cascade 等难以用 SQLite 验证 → 仅在 PostgreSQL prod 实际验证

---

## 核心文件（本次 session 修改）

**Backend**
- `app/services/agent_service.py` — `_validate_{sub_agent,tool,skill}_ids_owned` 3个 helper，create/update 均调用
- `app/agent_runtime/assistant/tools/write_tools.py` `add_subagent_to_agent` (移除 N+1 + 统一中文)
- `app/agent_runtime/assistant/tools/read_tools.py` `get_agent_config` (增加 sub_agents 字段)
- `app/agent_runtime/assistant/tools/helpers.py` (显式 sub_agent_links + 移除 selectinload sub_agent)
- `app/models/agent_subagent.py` (`lazy="joined"` 原因注释)
- `tests/test_agents.py` (sub_agent + tool/skill 校验测试8项)
- `tests/test_assistant_write_tools.py` (中文匹配)

**Frontend**
- `src/lib/chat/use-chat-runtime.ts` (`onStreamEnd(didMutate)`, `MUTATION_PREFIXES`)
- `src/components/agent/assistant-panel.tsx` (didMutate 分支)
- `src/app/agents/[agentId]/settings/page.tsx` (dirty-aware sync `lastSyncedAgentRef`)
- `src/app/agents/[agentId]/settings/_components/dialogs/sub-agents-dialog.tsx` (左/右2栏 + 固定 height + a11y)
- `src/app/agents/[agentId]/settings/_components/form-mode/section-sub-agents.tsx` (单行 compact 行)
- `src/app/agents/[agentId]/settings/_components/form-mode/tools-middlewares-grid.tsx` (整理 Row aria-label)
- `src/components/chat/tool-ui/clarifying-question-ui.tsx` (3-state union)
- `messages/ko.json` (扩展 `subAgents.*`, `common.remove`)

---

新 session 中可通过"读取 HANDOFF.md 并创建 PR/浏览器验证/executor 集成"等继续。

---

# HANDOFF — Workbench UX 打磨 + Fix 角色 + sub-agent 拆分（session 7, 2026-04-29）

**Base**: session 6 workbench PR merge 后 `main @ 0609210`
**Branch**: `main` (clean) — 本次 session 变更若未 commit 需拆到单独分支
**状态**: Plan mode 已启用 (`~/.claude/plans/image-41-ticklish-sky.md` — "ask_clarifying 直接输入 fix"计划仍残留，已完成 → 建议新 session 更新为"sub-agent 数据模型拆分"计划)

---

## 本次 session 累计变更（已应用）

### 1. 表单/tab UX 打磨
- `section-instructions`: `[field-sizing:fixed] flex-1 min-h-[200px]` — 防止自动高度被解除
- TabsList wrapper 增加 `overflow-y-hidden` — 移除垂直 scrollbar
- BaseUI tabs underline variant `after:bg-emerald-500 data-active:text-emerald-600` (与 sidebar chip 分离)
- ghost-input 模式(border-0 bg-transparent + hover/focus bg-muted/30) — 名称/描述 inline 编辑
- 开场白 UX: read/hover([✎][🗑])/edit + 新增使用单独 Dialog (n/12, 200字, 空值 reject)

### 2. Manual 创建页面 Workbench 整合
- `/agents/new/manual/page.tsx` — 镜像 settings workbench 相同布局（左侧 form/visual toggle + 右侧5 tab）
- `handleCreateModeFirstMessage`: createAgent → `sessionStorage('fix-initial-message')` → `router.replace(/agents/{id}/settings)`
- settings 页面 mount 后立即读取 sessionStorage carry-over 并自动发送（通过 `initialSentRef` 防止重复）
- 移除 dashboard visual 按钮 — 创建统一从 manual 入口进入

### 3. Fix 角色系统
- `public/agent-fix-hero.webp`（编辑模式）+ `agent-create-hero.webp`（创建模式, 500x500 webp）
- `AssistantPanel`: 通过 `createMode` prop 切换 hero/avatar 图像，通过 `showHeader` prop 切换 header
- 新增 `AgentAvatar.publicAsset` prop — 绕过 API_BASE prepend（静态资源时必需）
- `FixHero.imageSrc` 存在时不显示虚线 border，使用 `size-44 sm:size-52` 图像

### 4. ask_clarifying_question 工具 UI
- 注册 `chat/tool-ui/clarifying-question-ui.tsx` + `tool-ui-registry.ts`
- 点击选项1~3: `useAui` + `aui.thread().append({content: [{type:'text', text:opt}]})`（SuggestionTrigger 模式，绕过 composer）
- "直接输入": 不调用 composer，只切换 picked/disabled（规避 optional composer 在 setText 内部 throw 的问题）

### 5. Backend assistant tools 扩展
- 新增 `write_tools.update_agent_metadata(name?, description?)`
- `update_chat_openers` / `get_chat_openers`: 使用 `agent.opener_questions` 列（废弃绕过 model_params）
- 在 `prompt.md` 增加 "Update agent name and description" capability
- `add_subagent_to_agent` write_tool **仅存在 PoC stub** — 实际存储模型尚未决定

---

## 进行中 / 下一步

### CURRENT — sub-agent ≠ skill (Image #66 wrong → #67 correct)
> "现在 sub-agent 里显示的是 skill。sub-agent 指的是把当前打开智能体之外已经创建的其他智能体作为 sub-agent 调用。"

- `section-sub-agents.tsx` 当前使用 `useSkills` → 改为 `useAgents`（排除当前 agentId）
- `dialogs/sub-agents-dialog.tsx` 从 skill checklist → 重构为智能体卡片选择（avatar+名称+描述）
- page state: 新增 `selectedSubAgentIds: Set<string>`（与 `selectedSkillIds` 分离）
- **需要 BE 决策**: agent.sub_agent_ids 列 vs 单独 join table → m17 迁移
- manual 页面也需要镜像相同 state

### 后续（从 session 6 carry，未解决）
1. 创建 PR (m16 + workbench + session 7 打磨 → 单一或拆分)
2. 拆分 TestChatPanel ephemeral conversation endpoint (`/api/agents/{id}/test-chat`)
3. SettingsPanel 图像删除 BE API
4. 各工具 `[⚙]` config 编辑 UI

---

## 注意事项

- **Plan mode 已启用** — 新 session 开始时需要更新 plan 或 ExitPlanMode
- **AgentAvatar.publicAsset**: 以 `/` 开头的静态资源必须显式指定。遗漏时会被 API_BASE prepend 导致 404
- **VisualSettingsFlow controlled props**: workbench embedded 模式下绕过 internal Set updater — 注意不要遗漏 `isControlled` 分支
- **Composer optional**: `useComposerRuntime({optional:true})` 也可能在 setText/send 内部 throw — 使用 try-catch 或 `useAui().thread().append` 模式
- **ask_clarifying "直接输入"**: 意图是让用户在输入框直接输入 — 禁止调用 composer

## 核心文件（本次/下一步）

- `frontend/src/app/agents/[agentId]/settings/_components/form-mode/section-sub-agents.tsx` ⚠ 重构对象
- `frontend/src/app/agents/[agentId]/settings/_components/dialogs/sub-agents-dialog.tsx` ⚠ 重构对象
- `frontend/src/app/agents/[agentId]/settings/page.tsx` — 添加 `selectedSubAgentIds` state 的位置
- `frontend/src/app/agents/new/manual/page.tsx` — manual 页面镜像同一 state
- `frontend/src/components/agent/assistant-panel.tsx` — createMode/initialMessage carry
- `frontend/src/components/agent/fix-hero.tsx` — imageSrc 分支
- `frontend/src/components/chat/tool-ui/clarifying-question-ui.tsx` — 参考 useAui append 模式
- `backend/app/agent_runtime/assistant/tools/write_tools.py` — add_subagent_to_agent stub
- `backend/app/models/agent.py` — 增加 sub-agent 存储列时

## 最后状态

- 分支: `main` (clean) — 如果本次 session 变更仍在 working tree，先用 `git status` 确认后拆到 feature 分支
- 验证: session 7 部分变更尚未执行 lint/build — 新 session 开始时建议 `pnpm lint && pnpm build`
- DB: 已应用 `m16`，m17(sub-agent 存储) 尚未处理

新 session 中可通过"读取 HANDOFF.md 并从 sub-agent 数据模型拆分开始"或"下一步 #1 创建 PR"等继续。

---

# HANDOFF — Agent Edit Workbench 整合改版（session 6, 2026-04-28）

**Base**: `main @ 0609210` (PR #77 merge 后)
**Branch**: `feature/agent-edit-workbench`
**累计变更**: backend 5个文件 + 迁移 m16 + frontend 18个文件（废弃3 + 新增13 + 修改5）+ docs/tasks 4
**验证状态 (Final GREEN)**: backend pytest 628 PASS / ruff clean / alembic m16 roundtrip OK / frontend pnpm build PASS / pnpm lint 0 error · 0 warn

---

## 本次 session 核心变更

### 1. `/agents/[id]/settings` 整合 workbench 布局
- 原5 tab(basic·model·tools·triggers·assistant) 单列 → **左(form/visual toggle) / 右(Fix·测试·开场白·日程·设置 5 tab)** 拆分
- header inline 编辑: `[←]` + `<AgentAvatar size="sm">` + ghost-input 名称·描述 + `[🗑] [保存]`。**废弃 sticky save bar**
- 移动端: 低于 `lg:` 时 stack（左→右垂直排列）

### 2. 左侧 form 模式 — 单屏整合
- `_components/form-mode/`: `form-mode.tsx`, `section-instructions.tsx`(collapsible+字数+fullscreen Dialog), `section-sub-agents.tsx`, `section-model.tsx`, `tools-middlewares-grid.tsx`(2列 grid)
- 行模式: `[图标] name [摘要] [⚙][🗑]`。`[⚙]` 打开 dialog，`[🗑]` 立即从 page state 移除

### 3. 4种 dialog (`_components/dialogs/`)
- `model-dialog.tsx` — 将现有 ModelTab 内容原样 dialog 化 (ModelSelect + temperature/topP/maxTokens slider)
- `sub-agents-dialog.tsx` — useSkills + Checkbox 列表
- `add-tool-modal.tsx` — useTools + Checkbox 列表
- `add-middleware-modal.tsx` — useMiddlewares + Checkbox 列表

### 4. 左侧 visual 模式 inline + 阻止 dual-save
- `tab === 'visual'` 时 inline render `<ReactFlowProvider><VisualSettingsFlow embedded controlledState controlledHandlers /></ReactFlowProvider>`
- `VisualSettingsFlow` 增加 **hybrid controlled/uncontrolled 模式**: `embedded && controlledState && controlledHandlers` 时 controlled，否则 internal Set state（现有行为100%保持）
- `embedded` 时不 render 内部 Toolbar → 只显示 header 单一 Save 按钮

### 5. 右侧 panel 5 tab (`_components/right-panel/`)
- `right-panel.tsx` — 5 tab router
- **Fix 智能体** = 复用现有 `AssistantPanel`（新增 `showHeader?: boolean` prop，默认 `true`）。将 SUGGESTIONS chip 的 `/* TODO */` placeholder 用 `useComposerRuntime().setText` 填充
- **测试** = 新增 `test-chat-panel.tsx` — MVP 复用 `streamAssistant` + 顶部 amber tone 提示 banner("⚠ MVP: 与 Fix 智能体使用同一 endpoint，普通聊天拆分留到后续 PR")
- **开场白** = 新增 `opener-editor.tsx` — 行新增/删除, `n/12` counter, 200字限制
- **日程** = 原样 import 现有 `triggers-tab.tsx`（仅 label 改为"日程"）
- **设置** = 新增 `settings-panel.tsx` — 图像生成/重新生成/移除(useGenerateAgentImage)。**图像移除因 backend API 缺失，用 toast.info(coming soon) placeholder**

### 6. 新聊天空白页开场白按钮（Image #41 第二版方案）
- 将 `conversations/[conversationId]/page.tsx` 的 inline emptyContent 抽为 `ChatEmptyState` 组件（必须是 provider 子级才能使用 useComposerRuntime）
- `agent.opener_questions` 存在时 render rounded-full pill 按钮组 → 点击时注入 composer 文本（不发送）

### 7. Backend — `agents.opener_questions` 列
- Alembic `m16_add_opener_questions.py` (m15 → m16, roundtrip OK)
- `Agent.opener_questions: Mapped[list[str] | None]` (`JSON, nullable=True, default=list`) — 与 `middleware_configs` 模式相同
- `AgentCreate`/`AgentUpdate`/`AgentResponse` 3处均增加字段 + 共享 validator(`_validate_opener_questions`): ≤12个, strip 后1~200字, 空项 reject
- service `create_agent`/`update_agent` + router `_agent_to_response` 已反映
- 新增4个测试: roundtrip / 13个 reject / 空字符串 reject / 201字 reject

### 8. 废弃（3项，拆分单一调用处）
- `_components/basic-info-tab.tsx`（拆为 header + section-instructions）
- `_components/model-tab.tsx`（吸收到 model-dialog）
- `_components/tools-skills-tab.tsx`（拆为3个 modal）

---

## 下一步要做的工作

| 优先级 | 项目 | 影响/工作量 |
|---|---|---|
| 1 | **commit/PR**（建议: BE m16 / FE workbench / visual hybrid+开场白按钮 拆3份或单一 PR） | 中/低 |
| 2 | 用户手动浏览器验证5项（参照 verification-workbench.md） | 高/低 |
| 3 | 将 TestChatPanel 拆为真正 ephemeral conversation endpoint — 新增 BE `/api/agents/{id}/test-chat` + 更换 FE streamFn | 高/中 |
| 4 | SettingsPanel 图像删除 BE API — `DELETE /api/agents/{id}/image` + S3/local cleanup | 中/低 |
| 5 | TestChatPanel banner 字符串拆到 i18n（当前中文硬编码） | 低/低 |
| 6 | 各 `[⚙]` 工具 config 编辑 UI（当前 placeholder） | 中/中 |
| 7 | deprecate `/agents/[id]/visual-settings` 独立 route（redirect to settings?tab=visual） | 低/低 |

## 注意事项 / 已知风险

- **Next.js 16**: 保持 `frontend/AGENTS.md` + `node_modules/next/dist/docs/` 中的 `params: Promise<...>` + `use(params)` 模式
- **VisualSettingsFlow controlled props**: workbench 中为 controlled 模式时绕过 internal Set updater — 必须有 `isControlled` 分支。修改时注意所有 useEffect/toggle callback 不要漏掉分支
- **AgentUpdate.opener_questions**: 用 `[]` 清空, 用 `undefined` 表示不变。空项由 BE validator 返回 422 — FE 额外 guard 留到下个 PR
- **PUT method**: `PUT /api/agents/{id}`（不是 PATCH）。FE 的 `agentsApi.update` 已使用 PUT
- **图像移除**: 当前只有 toast.info placeholder。可能造成用户 confusion

## 核心文件

- `frontend/src/app/agents/[agentId]/settings/page.tsx` — workbench container
- `frontend/src/app/agents/[agentId]/settings/_components/form-mode/*.tsx` (5)
- `frontend/src/app/agents/[agentId]/settings/_components/dialogs/*.tsx` (4)
- `frontend/src/app/agents/[agentId]/settings/_components/right-panel/*.tsx` (4)
- `frontend/src/components/agent/visual-settings/visual-settings-flow.tsx` — embedded+controlled props
- `frontend/src/components/agent/assistant-panel.tsx` — showHeader prop
- `frontend/src/app/agents/[agentId]/conversations/[conversationId]/page.tsx` — 提取 ChatEmptyState + 开场白按钮
- `backend/alembic/versions/m16_add_opener_questions.py`
- `backend/app/{models,schemas,services}/agent.py` — opener_questions 字段/validator/service
- `backend/app/routers/agents.py` — 在 `_agent_to_response` 增加字段

## 最后状态

- 分支: `feature/agent-edit-workbench` (uncommitted, 25个文件)
- backend dev / frontend dev: 未启动（需要时由用户启动）
- DB: 已应用 `m16` 迁移
- 产物位置: `docs/design-docs/agent-edit-workbench.md`, `tasks/{deletion-analysis,verification}-workbench.md`

新 session 中可通过: "读取 HANDOFF.md 并创建 PR"或"继续下一项 #3（拆分 test endpoint）"等继续。

---

# 上一 session（session 5, 2026-04-28）— 聊天 UI 稳定化 + 时间系统落地

**Base**: `main @ 4f8df0c` (PR #76 merge 后)
**累计变更**: ~30个文件 (backend 7 + frontend 16 + alembic m15 + docs/支持 5)
**验证状态**: backend ruff + 624 pytest / frontend lint + format + 257 tests + build 全部 PASS
**上一 session 记录**: 参照本文件上方 section(session 1~3) + git log

## 本次 session 核心变更

### 1. 聊天气泡卡片布局 (Image #22)
- `page.tsx`: root `bg-muted/30 + p-3 + gap-3`, 左/右各自 `rounded-xl border bg-card shadow-sm` 卡片
- header 简化: 标题 + ⋯ dropdown（新对话/设置）
- `ConversationList`: 智能体卡片 header + "对话" label + 垃圾桶 footer(`toast.info` placeholder)

### 2. 时间系统（最棘手）
- **Backend**: 在 `MessageResponse`/`ConversationResponse` 增加 `UtcDatetime` annotation（通过 `PlainSerializer` 加 'Z' suffix）。`m15_add_message_timestamps` 迁移 — 将 `Conversation.message_timestamps: dict[msg_uuid, iso]` 永久保存，避免旧消息时间随发送时机漂移。
- **Frontend**: 新增 `lib/utils/format-relative-time.ts` — 直接使用 `Intl.DateTimeFormat(timeZone='Asia/Seoul')`（use-intl wrapper 的 timeZone option 不一致，因此绕过）。`parseTimestamp` 将不带 'Z' 的 string 视为 UTC。

### 3. 聊天 streaming bug（今天诊断/fix）
- **list-content fix** (`backend/app/agent_runtime/streaming.py`): 即使 Anthropic multi-block content 以 `list[dict]` 到达也处理。此前只处理 `isinstance(delta, str)`，使用 tool 时 token streaming 为0。现在通过共享 helper `content_to_text` 展平。
- **消息 refetch 闪烁 fix** (`use-chat-runtime.ts`): 在 `finally` 中立即调用 `setStreamingMessages([])` → refetch 到达前回复消失闪烁。改为通过 `prevMessagesRef` rendering-time 比较，在 messages 变化后 clear。
- **scroll fix** (`assistant-thread.tsx`): 为 `ThreadPrimitive.Root`/`Viewport` 增加 `min-h-0` — 消息多时输入框被挤出屏幕的问题。
- **streaming tool_call dedupe** (`streaming.py`): `_INTERNAL_TOOL_NAMES` filter（阻止 `ToolSelectionResponse` 等 middleware schema 暴露）+ 按 `(name, id)` dedupe。

### 4. UI 细节
- 用户消息 wrapper `flex flex-col items-end max-w-[80%]`（修复短消息右侧留白）
- 仅消息 hover 时显示时间/复制（提取 `MessageMetaRow`）
- AI avatar emerald 背景 + `imageUrl` 变化时自动 reset hasError（`prevImageUrl` rendering-time 模式）
- Composer: 模型在左, token bar `ml-auto` 右对齐, send 按钮 `variant="emerald"`
- 将 StreamingLoadingIndicator 设为 absolute(`-top-5 left-11`)，使回复文本位置 stable
- 在 `Button` cva 新增 `emerald`/`emeraldStrong` variant
- 图像转换为 webp (3.6MB → 142KB, -96%)
