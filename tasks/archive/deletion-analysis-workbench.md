# Deletion Analysis — Agent Edit Workbench

**Status**: GREEN
**Owner**: 萨提亚（直接执行 M2）
**Date**: 2026-04-28

---

## 废弃 (Delete)

### 1. `frontend/src/app/agents/[agentId]/settings/_components/basic-info-tab.tsx`
- **原因**：已在统一 workbench 中拆分
  - 名称/描述/图片 → header inline（图片在右侧 [设置] tab）
  - systemPrompt → 左侧 `section-instructions.tsx`
- **调用处**：仅 `settings/page.tsx` — 重写 page 时删除 import

### 2. `frontend/src/app/agents/[agentId]/settings/_components/model-tab.tsx`
- **原因**：吸收到 dialog 中
- **迁移目标**：`_components/dialogs/model-dialog.tsx`（原样保留 ModelSelect + slider + reset 按钮内容）
- **调用处**：仅 `settings/page.tsx`

### 3. `frontend/src/app/agents/[agentId]/settings/_components/tools-skills-tab.tsx`
- **原因**：拆分为多个 modal
  - tools 区域 → `_components/dialogs/add-tool-modal.tsx`
  - skills 区域 → `_components/dialogs/sub-agents-dialog.tsx`
  - middlewares 区域 → `_components/dialogs/add-middleware-modal.tsx`
- **调用处**：仅 `settings/page.tsx`

---

## 保留 + 重新布置 (Preserve + Relocate)

### 4. `frontend/src/app/agents/[agentId]/settings/_components/triggers-tab.tsx`
- **原因**：在右侧 [日程] tab 中原样 import
- **变更**：仅将 label 改为 i18n key `agent.settings.tabs.schedule = "日程"`
- **重新布置**：保持原位并在 `right-panel.tsx` 中 import。或者 re-export 到 `_components/right-panel/schedule-tab.tsx`

### 5. `frontend/src/components/agent/assistant-panel.tsx`
- **原因**: 右侧 [Fix agent] tab 内容 — 已实现 "要怎么修改?" + suggestion chip
- **修改**：新增 `showHeader?: boolean = true` prop。在 RightPanel 内部使用 `showHeader={false}`，避免外层 header 重复
- **新增**：点击 SUGGESTIONS 时连接 `useComposer().setText(suggestion)`（当前为 `/* TODO */`）

### 6. `frontend/src/components/agent/visual-settings/visual-settings-flow.tsx`
- **原因**：在左侧 [视觉] tab 中 inline 渲染
- **无需修改**：已经是基于 props 的组件（`agent`, `agentId`, `models`, `tools`, `skills`, `middlewares`, `triggers`, `mode`）
- **新增调用处**：在 `settings/page.tsx` 中，当 `tab === 'visual'` 时渲染 `<ReactFlowProvider><VisualSettingsFlow ... /></ReactFlowProvider>`

### 7. `frontend/src/app/agents/[agentId]/visual-settings/page.tsx`
- **本次 PR**：保留（虽是 deprecate 对象，但保留 route）
- **下一个 PR**：`redirect('/agents/[agentId]/settings?tab=visual')` 或删除

---

## 新增 (New)

### Frontend

```
_components/
├── form-mode/
│   ├── form-mode.tsx
│   ├── section-instructions.tsx
│   ├── section-sub-agents.tsx
│   ├── section-model.tsx
│   └── tools-middlewares-grid.tsx
├── dialogs/
│   ├── model-dialog.tsx
│   ├── sub-agents-dialog.tsx
│   ├── add-tool-modal.tsx
│   └── add-middleware-modal.tsx
└── right-panel/
    ├── right-panel.tsx
    ├── test-chat-panel.tsx
    ├── opener-editor.tsx
    └── settings-panel.tsx
```

### Backend

```
alembic/versions/m16_add_opener_questions.py
```

修改：
- `app/models/agent.py`（+1 column）
- `app/schemas/agent.py`（+1 field, validator）
- `app/services/agent_service.py`（update 路径）
- `tests/test_agents.py`（+case）

---

## Scope Creep 标记

以下内容**不包含在本次 PR 中**：
- `[⚙]` 按 tool 编辑 config (row 右侧齿轮) — placeholder, "即将支持" toast
- deprecate visual-settings 独立 route（下一个 PR）
- 移动端响应式精细调优（lg: 以上 grid，以下 stack 程度即可）

---

## 影响回归检查表（贝索斯 M7）

- [ ] `/agents` dashboard — 无影响（仅在 Agent 类型中新增 opener_questions）
- [ ] `/agents/new` — 无影响
- [ ] chat page `/agents/[id]/conversations/[cid]` — 仅在 empty screen 新增 opener 按钮（回归 X）
- [ ] AssistantPanel — `showHeader` prop 可选，default true → 回归 X
- [ ] TriggersTab — 仅变更 import 位置 → 回归 X
- [ ] VisualSettingsFlow — 仅新增调用位置 → 回归 X

---

## 判定

**GREEN** — 废弃的 3 项都在单一调用处（settings/page.tsx）内拆分，安全。保留的 4 项仅为新增 prop / 变更 import 位置的程度，回归风险低。新增内容为隔离模块。
