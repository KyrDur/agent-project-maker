# G5 对话 Export + G6 对话内搜索

分支：`feature/chat-export-search`（worktree）。顺序：G5 → G6，各自单独 commit。

## 共享
- 数据源：`useMessagesEnvelope(conversationId)` → `envelope.messages`（全部加载到 memory，无 pagination·virtualization）。无需 backend 变更。

## G5 — 对话 Export（与 share 对称）
- [ ] `lib/chat/conversation-export.ts`（新增）：`conversationToMarkdown(messages, opts)` / `conversationToJson(envelope)` / `downloadTextFile(content, filename, mime)`。纯函数，label 通过 parameter 传入（i18n 在调用方）。
- [ ] `ExportDialog(conversationId)`（新增，share-dialog 模式）：通过 `useMessagesEnvelope` fetch → 选择 format（Markdown/JSON）→ download。使用 DialogShell。
- [ ] `use-conversation-row-actions.tsx`：`openExportDialog` + `exportTarget` state + dialogs 中加入 ExportDialog（完全沿用 share 模式）。
- [ ] `chat-navigator-session-row.tsx`：session menu 新增 "导出" DropdownMenuItem（位于分享之后）。
- [ ] i18n（ko/en）+ utility unit test。

## G6 — 对话内搜索（Ctrl+F overlay）
- [ ] client in-memory 搜索：对 `message.content` 进行大小写不敏感 filter → 匹配 message id list。
- [ ] 复用 `jumpToMessage(messageId)`（jump-to-message.tsx）+ `moldy-jump-highlight`。
- [ ] Ctrl+F overlay 组件：search input + "N/M" count + previous/next + close（Esc）。位于对话 viewport 顶部。
- [ ] keyboard：Cmd/Ctrl+F toggle，Enter/Shift+Enter 移动，Esc close。
- [ ] i18n（ko/en）+ 搜索 filter unit test。

## 验证（各阶段）
- [ ] tsc / eslint / lint:i18n / lint:design-system / vitest
- [ ] E2E（export download，search jump）— 判断后
