# CHECKPOINT — Agent Edit Workbench（集成工作台重构）

**Plan**: `/Users/chester/.claude/plans/image-41-ticklish-sky.md`
**Branch**: `feature/agent-edit-workbench`
**Base**: `main @ 0609210`
**PO**: Satya
**开始**: 2026-04-28

---

## 目标

将 `/agents/[agentId]/settings` 从原有 5 个 tab 分离结构重构为**左侧（form/visual toggle）/ 右侧（Fix·test·opener·schedule·settings 5 tab）**的一体化 workbench。header 的名称·描述 inline edit，model·subagent 用 dialog，tool·middleware 使用 2 列 grid + modal。后端新增 `agents.opener_questions` JSON column。

---

## M1 — backend `opener_questions`（Jensen DRI）

- [ ] alembic `m16_add_opener_questions.py`
- [ ] `models/agent.py` Mapped column
- [ ] `schemas/agent.py` Response/Update/Create + validator（≤12，1~200 字）
- [ ] `services/agent_service.py` update 路径
- [ ] `tests/test_agents.py` PATCH case
- 验证：`cd backend && uv run alembic upgrade head && uv run pytest && uv run ruff check .`
- done-when：migration 应用，全部 pytest PASS，ruff clean

## M2 — design spec + deletion analysis（Satya 直接）

- [ ] `docs/design-docs/agent-edit-workbench.md`（layout·interface·inline edit pattern）
- [ ] `tasks/deletion-analysis-workbench.md`（basic-info-tab/model-tab/tools-skills-tab 废弃分类）
- 验证：两个文件存在
- done-when：细节达到 Zuckerberg 仅凭 spec 即可实现的程度

## M3 — frontend：页面骨架 + header inline（Zuckerberg DRI）

- [ ] `settings/page.tsx` 重写左/右 grid，移除 sticky save bar
- [ ] header：`[←]` + 小型 `AgentAvatar` + 名称·描述 ghost-input + `[🗑] [保存]`
- [ ] 左侧 [form]/[visual] Tabs，右侧 [Fix][test][opener][schedule][settings] Tabs
- [ ] 页面 state 增加 `openerQuestions: string[]`，包含在 isDirty 比较中
- 验证：`cd frontend && pnpm build`
- done-when：build PASS，route 正常

## M4 — frontend：左侧 form mode + dialog（Zuckerberg DRI）

- [ ] `_components/form-mode/{form-mode,section-instructions,section-sub-agents,section-model,tools-middlewares-grid}.tsx`
- [ ] `_components/dialogs/{model-dialog,sub-agents-dialog,add-tool-modal,add-middleware-modal}.tsx`
- [ ] 工具箱/middleware 2 列 grid，row layout（`name [⚙][🗑]`）
- [ ] 废弃：`basic-info-tab.tsx`, `model-tab.tsx`, `tools-skills-tab.tsx`
- 验证: `cd frontend && pnpm build && pnpm lint`
- done-when：build/lint PASS，4 种 modal 可用

## M5 — frontend：左侧 visual inline + 右侧 panel（Zuckerberg DRI）

- [ ] `tab === 'visual'` 时 inline render `<VisualSettingsFlow>`
- [ ] `_components/right-panel/{right-panel,test-chat-panel,opener-editor,settings-panel}.tsx`
- [ ] [Fix] 复用现有 `AssistantPanel`（新增 `showHeader` prop）
- [ ] [schedule] 复用现有 `triggers-tab.tsx`
- [ ] [settings] 仅用于 image create/regenerate/remove
- 验证：`cd frontend && pnpm build`
- done-when：5-tab 切换可用，visual mode 显示 node graph

## M6 — frontend：新聊天 empty state opener + 连接（Zuckerberg DRI）

- [ ] 在新聊天 empty state 渲染 `agent.opener_questions` 按钮
- [ ] 点击后将文本注入 composer（不发送 X）— `useComposer` hook
- [ ] 增强 `lib/types/agent.ts` 类型
- [ ] `lib/hooks/use-agents.ts` update payload 增加 `opener_questions`
- [ ] 新增 i18n key（`messages/ko.json` 之外）
- 验证: `cd frontend && pnpm build && pnpm lint`
- done-when：进入新对话时显示 opener 按钮 + 点击可用

## M7 — 集成验证（Bezos DRI）

- [ ] backend：`uv run pytest` 全量 + `uv run ruff check .`
- [ ] frontend: `pnpm build` + `pnpm lint`
- [ ] 回归场景：现有页面（/agents dashboard、conversation 页面、/agents/new）无影响
- [ ] 功能场景：header inline edit / form ↔ visual / 右侧 5 tab / opener 添加·保存·新对话展示
- 验证：综合报告 `tasks/verification-workbench.md`
- done-when：判定 GREEN

## M8 — HANDOFF + 整理（Satya）

- [ ] 更新 HANDOFF.md
- [ ] 新增 tasks/lessons.md
- [ ] AUDIT.log PROJECT_DONE
- [ ] TeamDelete
