# 删除分析报告：聊天 UI — assistant-ui 整合

**分析者**：bezos（QA Engineer）
**日期**：2026-04-09
**Branch**：feature/chat-ui-assistant-ui
**Scope**：引入 assistant-ui 后删除/修改/保留对象分类

---

## 分析对象摘要

| 目录 | 文件数 | 总行数 |
|----------|---------|---------|
| components/chat/ | 6 + CSS 1 | ~1,069 + CSS |
| lib/stores/chat-store.ts | 1 | ~40 |
| components/agent/assistant-panel.tsx | 1 | 370 |
| agents/new/conversational/_components/ | 4 | ~392 |
| lib/sse/ | 4 | ~134 |

---

## 1. 可立即删除（assistant-ui 替代完成后）

### 1.1 components/chat/ — 删除对象 5 个 + CSS 1 个

| 文件 | 行 | 替代方式 | import 位置 | 备注 |
|------|------|-----------|------------|------|
| `streaming-message.tsx` | 78 | assistant-ui Thread streaming 渲染 | conversation page（1 处） | 内部 ThinkingDots → 替换为 Wit loading |
| `message-bubble.tsx` | 221 | assistant-ui Thread 消息渲染 | conversation page（1 处） | **需要移动 parseToolContent, normalizeContent util**（参见下方 §3） |
| `chat-input.tsx` | 140 | assistant-ui Composer | conversation page（1 处） | 读取 sessionTokenUsageAtom → 在 Composer 中整合 token 显示 |
| `tool-call-display.tsx` | 190 | makeAssistantToolUI | message-bubble（1 处）, streaming-message（1 处） | 内部专用。父级删除时一起删除 |
| `markdown-content.tsx` | 190 | react-streamdown + Shiki + KaTeX | 4 处（下方详述） | **依赖最多 — 注意顺序** |
| `markdown-styles.css` | - | react-streamdown 自身样式 | markdown-content.tsx（1 处） | 与 markdown-content 一起删除 |

#### markdown-content.tsx 依赖链（删除前需要解除）

```
markdown-content.tsx
├── message-bubble.tsx         → 删除对象（同时删除 OK）
├── streaming-message.tsx      → 删除对象（同时删除 OK）
├── assistant-panel.tsx        → 在 S6 替换（之前保持或同时替换）
└── draft-config-card.tsx      → S7 中需要替换 Markdown renderer
```

**删除顺序**：按 S5（对话页面）→ S6（AssistantPanel）→ S7（Builder）顺序替换后，最后删除 markdown-content.tsx。或者在 S5 中创建基于 react-streamdown 的新 Markdown component，然后在 S6/S7 中只修改 import 路径并删除旧实现。

### 1.2 chat-store.ts — 部分删除（5 个 atoms 中的 3~4 个）

| Atom | 类别 | Reader | Writer | 判定 |
|------|---------|--------|--------|------|
| `streamingMessageAtom` | streaming 状态 | streaming-message.tsx | conversation page | **删除** — 由 assistant-ui runtime 替代 |
| `streamingToolCallsAtom` | streaming 状态 | streaming-message.tsx | conversation page | **删除** — 由 assistant-ui runtime 替代 |
| `isStreamingAtom` | UI 状态 | streaming-message.tsx | conversation page | **删除** — 由 assistant-ui runtime 替代 |
| `sessionTokenUsageAtom` | token 追踪 | chat-input.tsx | conversation page | **保留** — token 追踪是 assistant-ui 外部关注点 |
| `lastMessageTokensAtom` | token 追踪 | **无（dead code）** | conversation page | **删除** — 只写不读 |
| `StreamingToolCall` 类型 | 类型 | conversation page | - | **删除** — 替换为 assistant-ui 自身类型 |
| `TokenUsage` 类型 | 类型 | chat-input, conversation page | - | **保留** — 与 sessionTokenUsageAtom 一起 |

**结果**：不删除 chat-store.ts，仅保留 `sessionTokenUsageAtom` + `TokenUsage`。如果文件只剩 2 个 export，则评估迁移到其他 store。

### 1.3 assistant-panel.tsx — 整体替换（S6）

| 内部组件 | 行 | 替代方式 | 重复对象 |
|--------------|------|-----------|----------|
| `MessageBubble`（内部） | 81-131 | assistant-ui Thread 消息 | 与 chat/message-bubble.tsx **重复**（简化版本） |
| `ToolCallBadge`（内部） | 43-79 | makeAssistantToolUI | 与 chat/tool-call-display.tsx **重复**（轻量版本） |

**需要迁移的逻辑**：
- SSE 事件处理（5 种：content_delta, tool_call_start, tool_call_result, message_end, error）→ 移到 useExternalStoreRuntime 适配器
- `isComposingRef`（防止 IME 组合）→ 在 Composer 中处理 or 整合到自定义 Composer
- `crypto.randomUUID()` session 管理 → 移到 runtime 适配器层
- AbortController 管理 → 移到 runtime 适配器
- TanStack Query invalidation（`['agents']`）→ 移到工具执行回调

---

## 2. 保留项目

### 2.1 components/chat/ — 保留 1 个

| 文件 | 行 | 原因 |
|------|------|------|
| `conversation-list.tsx` | 250 | Sidebar 对话列表。与 assistant-ui 无关。基于 TanStack Query + Next.js Router。 |

### 2.2 lib/sse/ — 全部保留

| 文件 | 行 | 原因 |
|------|------|------|
| `parse-sse.ts` | 70 | 公共 SSE 解析器。3 个 stream module 依赖。 |
| `stream-chat.ts` | 16 | 继续在 useExternalStoreRuntime 适配器中使用（backend API 不变） |
| `stream-assistant.ts` | 21 | 继续在 AssistantPanel runtime 适配器中使用 |
| `stream-builder.ts` | 27 | 继续在 Builder 页面中使用 |

### 2.3 lib/hooks/ — 保留

| 文件 | 原因 |
|------|------|
| `use-conversations.ts` | TanStack Query hook。在 conversation-list + 对话页面中使用。 |

### 2.4 conversational/_components/ — 保留（超出本 PR scope）

| 文件 | 行 | 原因 |
|------|------|------|
| `phase-timeline.tsx` | 157 | Builder 专用。S7 中仅用 Thread 包裹，保留内部组件。 |
| `intent-card.tsx` | 53 | Builder 专用。保留。 |
| `recommendation-card.tsx` | 50 | 通用卡片。保留。 |
| `draft-config-card.tsx` | 132 | Builder 专用。**markdown-content import → S7 中需要替换为新的 Markdown renderer。** |

### 2.5 chat-store.ts — 部分保留

- 保留 `sessionTokenUsageAtom` + `TokenUsage` 类型

---

## 3. 需要迁移的工具函数

### message-bubble.tsx 内部工具函数（删除前提取）

| 函数 | 功能 | 迁移目标 |
|------|------|----------|
| `parseToolContent(content)` | 解析 Python dict + JSON 工具结果 | `lib/utils/convert-message.ts`（新增） |
| `extractTextFromParsed(parsed)` | 从解析后的工具结果中提取文本 | `lib/utils/convert-message.ts`（新增） |
| `normalizeContent(content)` | 规范化控制字符 | `lib/utils/convert-message.ts`（新增） |

**原因**：这些 util 很可能在 backend 消息 → assistant-ui 消息转换时复用。尤其 `parseToolContent` 是解析 LangGraph 工具结果格式的必需项。

### streaming-message.tsx 内部组件

| 组件 | 功能 | 判定 |
|---------|------|------|
| `ThinkingDots()` | loading 动画 | **删除** — 计划替换为 Wit loading（每 3 秒随机消息） |

---

## 4. 依赖关系图

```
[删除对象]                      [保留对象]
                                
streaming-message.tsx ──┐        conversation-list.tsx（独立）
                       │        
message-bubble.tsx ────┤        lib/sse/parse-sse.ts
  └─ parseToolContent  │          ├── stream-chat.ts（保留）
  └─ normalizeContent  │          ├── stream-assistant.ts（保留）
                       │          └── stream-builder.ts（保留）
chat-input.tsx ────────┤        
                       │        chat-store.ts
tool-call-display.tsx ─┤          └── sessionTokenUsageAtom（保留）
                       │          └── TokenUsage 类型（保留）
markdown-content.tsx ──┤        
  └─ markdown-styles.css│       conversational/_components/（全部保留）
                       │          └── draft-config-card.tsx
assistant-panel.tsx ───┘              （markdown-content → 替换为新 renderer）
  └─ MessageBubble（内部）
  └─ ToolCallBadge（内部）

chat-store.ts（部分删除）
  ├── streamingMessageAtom（删除）
  ├── streamingToolCallsAtom（删除）
  ├── isStreamingAtom（删除）
  ├── lastMessageTokensAtom（删除，dead code）
  └── StreamingToolCall 类型（删除）
```

---

## 5. 删除执行顺序（推荐）

| 顺序 | Story | 删除/修改对象 | 前置条件 |
|------|--------|--------------|----------|
| 1 | S2 | 从 message-bubble.tsx 提取 parseToolContent 等 → convert-message.ts | 无 |
| 2 | S3-S4 | 创建新的 Markdown renderer + Tool UI | S2 完成 |
| 3 | S5 | 删除 streaming-message, message-bubble, chat-input, tool-call-display。在 chat-store.ts 中删除 streaming atoms | S3, S4 完成 |
| 4 | S6 | 整体替换 assistant-panel.tsx | S3, S4 完成 |
| 5 | S7 | 替换 draft-config-card.tsx 的 markdown-content import | S3 完成 |
| 6 | S5 之后 | 删除 markdown-content.tsx + markdown-styles.css | S5, S6, S7 全部完成 |
| 7 | S8 | 确认删除 lastMessageTokensAtom，清理未使用 import，验证 build/lint | 全部完成 |

---

## 6. 风险 & 注意事项

| 风险 | 严重度 | 说明 |
|--------|--------|------|
| 过早删除 markdown-content.tsx | HIGH | 4 处 import。在 S5/S6/S7 全部完成前删除会导致 build 失败 |
| 丢失 parseToolContent | MEDIUM | 删除 message-bubble.tsx 时 util 函数也会一起消失。必须事先提取 |
| 误删 sessionTokenUsageAtom | MEDIUM | 清理 chat-store.ts 时如果连 token 相关 atom 一起删除，会破坏 token 追踪 |
| draft-config-card.tsx 损坏 | MEDIUM | 删除 markdown-content 后 Builder 页面无法渲染 Markdown |
| lastMessageTokensAtom dead code | LOW | 当前无人读取。如无未来使用计划则删除 |
| 丢失 IME 组合防护逻辑 | LOW | assistant-panel.tsx 的 isComposingRef。CJK 输入时需要 |

---

## 7. 定量摘要

| 分类 | 文件数 | 行数（估算） |
|------|---------|---------------|
| 可立即删除 | 7（chat 5 + CSS 1 + assistant-panel 1） | ~1,189 |
| 部分删除（atoms） | 1（chat-store.ts 内 4 atoms + 1 类型） | ~20 |
| 保留 | 10（conversation-list + sse 4 + hooks 1 + _components 4） | ~723 |
| 需要迁移的 util | 3 个函数（→ convert-message.ts） | ~30 |
| **总删除行数** | | **~1,209** |
