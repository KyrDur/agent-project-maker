# Chat UI Performance Triage

编写日期：2026-06-01
当前 HEAD：`7ac1448`
输入文档：

- `/Users/chester/Downloads/performance-audit.md`
- `/Users/chester/Downloads/chat-ui-performance-audit.md`

## 目的

将两份审计文档中的性能改进候选项与当前源代码直接对照，区分当前 chat UI 重构中要推进的项目与需要拆分到独立轨道的项目。

初次编写时以决策记录起步，之后又在同一文档中补充了实际实现完成情况与验证结果。

## 确认方法

1. 阅读两份审计文档的优先级项目与详细分析。
2. 以当前 HEAD 为基准，重新确认实际文件与行位置。
3. 对 chat UI 相关项目，从 React/Next 性能角度进行分类。
4. 对 LangGraph/Deep Agents 相关项目，与 LangChain 层级选择、persistence、Deep Agents backend/memory 指南进行对照。
5. 尚未执行实际 profiling。因此部分项目被归类为“测量后推进”，而非直接“推进”。

## 总结结论

chat UI 重构的第 1 阶段范围建议定为以下五项。

1. 防止旧 stream cleanup race
2. 移除 render phase state update
3. streaming 期间禁用 code block syntax highlighting
4. 减少每次 streaming flush 触发的全量消息重计算
5. 对大型 tool result 的渲染成本做 lazy/memo 处理

全局性能文档中的 DB index、`/api/agents` 轻量化、checkpoint 查询优化、trace 存储结构、DeepAgent runtime cache 都是有效问题，但不建议与 chat UI 闪烁重构混在同一个 PR 中。这些内容需要作为 backend/runtime 性能轨道单独设计。

## 实现完成情况

完成日期：2026-06-01

由于用户将范围限定为“独立推进的内容不在这里做”，以下完成情况仅包含 Chat UI 第 1 阶段/可推进项目。Backend/API/DB/Runtime/Deep Agents 轨道中的“独立推进”项目未在本次工作中实现。

| 项目 | 状态 | 实施内容 | 代表性验证 |
| --- | --- | --- | --- |
| Stream stale guard 加强 | 完成 | 在 rAF callback、stream `finally`、`onStreamEnd`、final commit 路径中添加 stale token guard，并取消 pending rAF。 | `use-chat-runtime-commit.test.tsx` stale stream cleanup 回归测试 |
| 移除 Render phase state update | 完成 | 将 render 期间的 `setPrevMessages`/`setStreamingMessages` 调用移到 effect，并先比较 cheap message key。 | `use-chat-runtime-commit.test.tsx` commit/refetch 回归测试 |
| Streaming code block plain render | 完成 | streaming 期间 fenced code block 不使用 `SyntaxHighlighter`，而是以 plain `<pre><code>` 渲染。完成后保留现有 highlighter 路径。 | `markdown-content.test.tsx` streaming code block 测试 |
| 降低 Streaming projection/usage 成本 | 完成 | 将 token usage 计算拆分为 persisted/streaming 汇总，并阻止相同值的 atom update。`allMessages` merge 也减少了不必要的数组创建。 | token usage no-repeat update 测试、完整 Vitest |
| Tool UI JSON lazy/memo | 完成 | 对 tool args/result stringify、image URL extraction、right rail JSON parse/pretty stringify 做 memoize，并以已打开面板为基准进行计算。 | `collapsible-pill.test.tsx`、`tool-result-panel-content.test.tsx` |
| Right rail conversation reset | 完成 | 在 right rail payload 中关联 `conversationId`，若与当前对话不同则隐藏 stale panel 或 reset。 | `chat-right-rail.test.tsx` |
| 移除 SSE queue `shift()` | 完成 | 将 POST SSE bridge queue 改为 head-index queue，消除 slow consumer 情况下 O(n) 的 `shift()` 成本。 | `parse-sse.test.ts` head-index queue 测试 |

### 实现过程中额外整理的 E2E 稳定性改进

同时处理了阻碍完整 E2E 完成的测试 fixture 差异。

- 将 `/api/models?include_hidden=true` 请求无法被 `**/api/models` glob mock 捕获的问题，改为包含 query string 的 regex。
- 实际工具类型 seed 的韩文显示名 `HTTP 请求` 与现有测试期望值 `HTTP Request` 不一致，因此修改为两种表达都允许。
- Next dev cold compile 时首个 E2E 会超过 30 秒 timeout，因此将 Playwright 默认 timeout 提高到 60 秒。
- 将 Playwright webServer 的 frontend command 固定为 `pnpm exec next dev --port 3000`，防止随机选择端口。

### 最终验证结果

以下验证于 2026-06-01 在当前 worktree 中执行。

| 命令 | 结果 |
| --- | --- |
| `pnpm vitest run` | 通过。75 files, 381 tests |
| `pnpm build` | 通过 |
| `pnpm lint` | 通过。仅剩现有 warning 3 个，error 0 个 |
| `git diff --check` | 通过 |
| `E2E_BASE_URL=http://127.0.0.1:3000 E2E_API_BASE_URL=http://127.0.0.1:8001 NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 pnpm exec playwright test --workers=1` | 通过。33 passed, 2 skipped |

剩余 lint warning 是与本次工作无关的现有测试文件 unused symbol。

- `frontend/tests/components/chat/assistant-thread-actions.test.tsx`
- `frontend/tests/components/marketplace/marketplace-copy.test.tsx`

## 判定表

| 分类 | 项目 | 判定 | 理由 |
| --- | --- | --- | --- |
| Chat UI 第 1 阶段 | 加强 Stream stale guard | 推进 | 旧 stream 的 rAF/finally cleanup 可能覆盖新 stream 状态。 |
| Chat UI 第 1 阶段 | 移除 render phase state update | 推进 | refetch 切换过程中可能产生额外 render 和闪烁。 |
| Chat UI 第 1 阶段 | streaming code block plain render | 推进 | 长代码响应中 syntax highlighter 是最直接的 main-thread 成本候选。 |
| Chat UI 第 1 阶段 | 减少 streaming 全量消息重计算 | 推进，分阶段 | 结构性改进收益较大，但处于 assistant-ui 集成边界，需要测试。 |
| Chat UI 第 1 阶段 | Tool UI JSON 计算 lazy/memo | 推进 | 可避免大型 tool result 阻塞渲染路径。 |
| Chat UI 第 1 阶段/后续 | Right rail conversation reset | 可推进 | 更接近防止错误状态显示，而非性能问题，但改动小且安全。 |
| Chat UI 后续 | 移除 SSE queue `shift()` | 可推进 | 小幅改进。实际体感仅在 slow consumer 情况下明显。 |
| 优先测量 | 调整 `content-visibility:auto` | 测量后 | 对长列表优化有效。在复现滚动跳动前就移除还太早。 |
| 后续优先级 | 整理 ChatPage title/read 订阅 | 后续 | 属于 stale correctness 问题，不是 streaming 闪烁的核心原因。 |
| 后续优先级 | conversation list virtualization | 后续 | 对话数量很多时需要，但与当前 stream 闪烁直接相关性较低。 |
| 后续优先级 | `CollapsiblePill` auto expand 策略 | 后续 | 更偏 UX 一致性问题，而非性能。 |
| 已改进 | 按 `content_delta` 立即 state update | 监控 | 已经加入 rAF batching。 |
| Backend 轨道 | `/api/agents` 聚合/索引 | 独立推进 | 有效，但属于 DB/API 性能工作。 |
| Backend 轨道 | 移除 message read path write | 独立推进 | 有效，但需要 persistence/projection 设计。 |
| Backend 轨道 | 移除 checkpoint 重复遍历 | 独立推进 | 属于 LangGraph persistence 路径，需要独立测试。 |
| Backend 轨道 | 改进 trace JSON row rewrite | 独立推进 | 很可能涉及 schema 变更。 |
| Runtime 轨道 | DeepAgent/runtime cache | 独立设计 | 需要 cache key、invalidation、tenant/credential isolation。 |
| 不建议 | 移除 checkpointer、省略 `thread_id` | 不做 | 会破坏 HITL、branch、time travel、resume。 |
| 不建议 | 将 Deep Agents 降级为简单 LangChain agent | 不做 | 产品需求与 Deep Agents/LangGraph 层级匹配。 |

## Chat UI 第 1 阶段推进项目

### 1. 加强 Stream stale guard

#### 审计文档主张

旧 stream 的 `finally` 或已排队的 rAF callback 可能覆盖新 stream 状态。

#### 当前源码确认

`useChatRuntime` 在开始新 stream 时会 abort 旧 `AbortController`，并更新 stream guard token。

- `frontend/src/lib/chat/use-chat-runtime.ts:287`
- `frontend/src/lib/chat/use-chat-runtime.ts:297`

在 SSE 事件处理循环中会检查 stale token。

- `frontend/src/lib/chat/use-chat-runtime.ts:414`
- `frontend/src/lib/chat/use-chat-runtime.ts:417`

但以下位置没有 token guard。

- rAF callback: `frontend/src/lib/chat/use-chat-runtime.ts:402`
- rAF flush state update: `frontend/src/lib/chat/use-chat-runtime.ts:405`
- `finally` cleanup: `frontend/src/lib/chat/use-chat-runtime.ts:578`
- `setIsRunning(false)`: `frontend/src/lib/chat/use-chat-runtime.ts:579`
- 应用 final streaming state：`frontend/src/lib/chat/use-chat-runtime.ts:596`
- `onStreamEnd`: `frontend/src/lib/chat/use-chat-runtime.ts:603`

#### 判断

应当推进。用户在响应过程中快速执行 stop、新消息、edit、regenerate 时，旧 stream cleanup 可能扰乱新 stream 的 `isRunning`、`streamingMessages`、query refetch 时机。

#### 实现方向

- 保存 rAF id，并在 stream 结束/abort/stale 时取消。
- 在 rAF callback 内再次检查 `streamGuardRef.current.isStale(token)`。
- 若 `finally` 一开始就判定为 stale，则跳过 UI state update 和 `onStreamEnd`。
- 与 `onFailed` 类似，让 stale stream 的 `onStreamEnd` 也不触发 refetch。
- 正常因 interrupt 而 pause 的 stream 仍需要 refetch，因此区分 stale guard 与 interrupt 结束。

#### 验证

- 响应过程中 Stop 后立即发送新消息
- 响应过程中 Regenerate 后立即 Stop
- Edit 后立即 Regenerate
- 网络 resume 过程中发送新消息
- 单元测试：stale stream 中不调用 `onStreamEnd`

### 2. 移除 Render phase state update

#### 审计文档主张

`useChatRuntime` 底部可能在 render 过程中调用 `setPrevMessages`、`setStreamingMessages`。

#### 当前源码确认

当前代码会在 render phase 比较之前的 messages snapshot。

- `frontend/src/lib/chat/use-chat-runtime.ts:620`
- `frontend/src/lib/chat/use-chat-runtime.ts:621`

满足条件时，会在 render 过程中发生 state update。

- `setPrevMessages(messages)`: `frontend/src/lib/chat/use-chat-runtime.ts:622`
- `setStreamingMessages([])`: `frontend/src/lib/chat/use-chat-runtime.ts:625`
- `setStreamingMessages((sm) => ...)`: `frontend/src/lib/chat/use-chat-runtime.ts:631`

#### 判断

应当推进。React 中保存前一轮 render 信息的模式本身可行，但这里还同时执行 streaming cleanup。refetch 后的页面切换区间可能引发额外 render、optimistic user 移除时机问题和闪烁。

#### 实现方向

- 将 `prevMessages` 比较与 streaming cleanup 移到 `useEffect`。
- 在 `sameMessageSnapshot` 全量比较前先使用 cheap key。
  - length
  - first/last id
  - last assistant id
  - 若存在 active checkpoint id，则利用 envelope 侧的 key
- 在 effect 内明确检查 stale/running 状态。
- 保留 interrupted/partial stream 保存规则。

#### 验证

- 保留现有 `use-chat-runtime-commit.test.tsx` 回归测试
- 新增测试：refetch 后 streaming assistant 不闪烁
- 保留 mid-stream 中断时 partial assistant 被保存的测试
- 新增测试：仅去重 optimistic user

### 3. Streaming code block plain render

#### 审计文档主张

streaming 期间普通 fenced code block 若走 syntax highlighter，在长代码响应中可能造成 main thread block。

#### 当前源码确认

当 message status 为 running 时，`AssistantThread` 使用 streaming 专用 markdown components。

- `frontend/src/components/chat/assistant-thread.tsx:96`
- `frontend/src/components/chat/assistant-thread.tsx:100`

`buildMarkdownComponents({ isStreaming })` 仅让 mermaid 在 streaming 期间使用 raw code。

- `frontend/src/components/chat/markdown-content.tsx:186`
- `frontend/src/components/chat/markdown-content.tsx:187`

普通 fenced code block 无论是否 streaming 都渲染 `CodeBlock`。

- `frontend/src/components/chat/markdown-content.tsx:181`
- `frontend/src/components/chat/markdown-content.tsx:194`

`CodeBlock` 使用 `SyntaxHighlighter`。

- `frontend/src/components/chat/markdown-content.tsx:43`
- `frontend/src/components/chat/markdown-content.tsx:80`

#### 判断

应当推进。实现难度低，效果直接。LLM 生成 300 行以上代码文件时，仅靠 rAF batching 可能仍不够。

#### 实现方向

- 当 `isStreaming === true` 时，所有 fenced code block 以 plain `<pre><code>` 渲染。
- 决定 streaming 期间是否保留 copy button。
  - 最小改动：plain block 也保留 header/copy UI
  - 更轻量改动：streaming 期间不显示 header/copy，仅显示 plain block
- message complete 后切回现有 `SyntaxHighlighter` 路径。
- 后续评估是否为行数较大的 final code block 增加关闭 highlighter 的 threshold。

#### 验证

- 确认 300 行 code block streaming 时 long task 减少
- 确认 streaming 期间 code block 不损坏，并以 plain text 显示
- 确认 message complete 后应用 syntax highlight
- 确认 copy button 是否保持可用

### 4. 减少 Streaming 期间全量消息重计算

#### 审计文档主张

每次 content flush 都会重复执行全量消息 merge、token usage 汇总、assistant-ui 转换。

#### 当前源码确认

streaming flush 发生时，`streamingMessages` 会更新为新数组。

- `frontend/src/lib/chat/use-chat-runtime.ts:395`
- `frontend/src/lib/chat/use-chat-runtime.ts:405`
- `frontend/src/lib/chat/use-chat-runtime.ts:447`
- `frontend/src/lib/chat/use-chat-runtime.ts:494`

因此 `allMessages` 会重新合并全部 messages 与 streamingMessages。

- `frontend/src/lib/chat/use-chat-runtime.ts:308`
- `frontend/src/lib/chat/use-chat-runtime.ts:311`

随后 token usage 会遍历整个 `allMessages` 进行汇总。

- `frontend/src/lib/chat/use-chat-runtime.ts:325`
- `frontend/src/lib/chat/use-chat-runtime.ts:329`

assistant-ui 转换也会以完整 `allMessages` 作为输入。

- `frontend/src/lib/chat/use-chat-runtime.ts:343`
- `frontend/src/lib/chat/use-chat-runtime.ts:346`

#### 判断

应当推进，但需要分阶段进行。该项收益较大，但属于与 assistant-ui ExternalStoreRuntime 相连的核心路径，因此应从小改动开始。

#### 第 1 阶段实现方向

- 将 token usage 汇总限制在以下时点，而不是每次 content flush 都执行。
  - fetched messages 发生变化
  - `message_end`
  - 固定 interval
- 为 `setTokenUsage` 增加 guard：值相同时不 update。
- 在合并 `messages` 与 `streamingMessages` 时，避免创建 `[...messages, ...streamingMessages]` 临时数组。

#### 第 2 阶段实现方向

- 分离 persisted conversation runtime 与 local ephemeral runtime 的 commit 策略。
- 保留公共 stream consumer，但将 refetch-driven path 与 local commit path 通过 adapter 分离。
- 评估 assistant-ui API 边界，确认是否可以仅转换 streaming assistant message projection。

#### 验证

- 在长对话 100 条消息 + 5,000 字回答场景中测量 React commit count
- 在 tool_call 较多的 stream 中测量渲染次数
- 保留 builder/AssistantPanel/TestChatPanel 的 `onMessagesCommit` 路径回归测试
- 保留 duplicate id crash 回归测试

### 5. Tool UI JSON 计算 lazy/memo

#### 审计文档主张

大型 tool result JSON 可能会在每次 render 时执行 parse/stringify/遍历。

#### 当前源码确认

Generic tool UI 会在 render path 中执行 image URL 遍历。

- `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx:23`
- `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx:107`

args/result stringify 也在 render path 中执行。

- `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx:82`
- `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx:117`
- `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx:127`

Right rail 会 parse JSON string 并进行 pretty stringify。

- `frontend/src/components/chat/right-rail/tool-result-panel-content.tsx:24`
- `frontend/src/components/chat/right-rail/tool-result-panel-content.tsx:65`
- `frontend/src/components/chat/right-rail/tool-result-panel-content.tsx:69`
- `frontend/src/components/chat/right-rail/tool-result-panel-content.tsx:84`

#### 判断

应当推进。虽然不是 P0，但在对话中出现大型 tool result 的 agent 上可能有明显体感。

#### 实现方向

- 用 `useMemo` 包裹 `extractImageUrls(result)`。
- `formatToolValue(args/result)` 也用 `useMemo` 包裹。
- 确认 `CollapsiblePill` 的 `renderBody` 调用时机，确保 collapsed 状态下不计算大型 body。
- Right rail 仅在 panel 打开后才执行 parse/pretty stringify。
- 为大型 JSON 设置 threshold，初始仅显示摘要，展开时再 pretty stringify。

#### 验证

- 展示 1MB JSON tool result
- 测试 collapsed 状态下不调用 stringify
- 测试仅在 right rail open 时执行 pretty stringify

## Chat UI 后续推进项目

### Right rail conversation reset

#### 当前源码确认

Right rail state 是全局 Jotai atom，不包含 conversationId。

- `frontend/src/lib/stores/chat-right-rail.ts:24`
- `frontend/src/lib/stores/chat-right-rail.ts:30`

ChatRightRail 仅根据 atom state 决定是否打开。

- `frontend/src/components/chat/right-rail/chat-right-rail.tsx:24`
- `frontend/src/components/chat/right-rail/chat-right-rail.tsx:25`

#### 判断

这是一个小且安全的改进。虽然不是性能核心，但可以避免切换对话后仍显示上一段对话的 tool result/subagent/outline。

#### 实现方向

- 在 payload 中加入 `conversationId`。
- 向 `ChatRightRail` 传递当前 conversationId prop。
- 若 atom payload 的 conversationId 与当前 conversationId 不同，则隐藏或 reset。
- 也可以采用更简单的方法：对话 route 变化时将 atom 初始化为 `{ mode: 'none' }`。

### SSE queue head index

#### 当前源码确认

POST SSE bridge 会从 callback buffer 中通过 `shift()` 取出事件。

- `frontend/src/lib/sse/parse-sse.ts:139`
- `frontend/src/lib/sse/parse-sse.ts:201`
- `frontend/src/lib/sse/parse-sse.ts:233`

#### 判断

可以推进，但优先级较低。一般情况下 queue 很小，但当浏览器繁忙或 consumer 较慢时，可能显现 O(n) 成本。

#### 实现方向

- 使用 `let head = 0` pointer。
- yield 时使用 `buffer[head++]`。
- 当 head 超过一定大小时执行 `buffer.splice(0, head)` 或 slice compact。

## 测量后推进项目

### 调整 `content-visibility:auto`

#### 当前源码确认

message wrapper 使用 content visibility 和 intrinsic size。

- user message: `frontend/src/components/chat/assistant-thread.tsx:522`
- assistant message: `frontend/src/components/chat/assistant-thread.tsx:574`

#### 判断

暂不移除。这对长列表初始渲染是有效优化。等实际复现滚动跳动、图片加载后 layout shift、长 table/code block 问题时再调整。

#### 测量场景

- 包含 5 张以上图片的回答
- 长 table 回答
- 300 行以上 code block
- 对话超过 100 条消息时，滚动到中间位置后接收新 token

### Conversation list virtualization/pagination

#### 当前源码确认

ConversationList 接收完整 list，并在 client-side 执行 filter/sort/map。

- query: `frontend/src/components/chat/conversation-list.tsx:59`
- filter/sort: `frontend/src/components/chat/conversation-list.tsx:73`
- 全量 map render：`frontend/src/components/chat/conversation-list.tsx:245`

#### 判断

这不属于当前 chat streaming 闪烁重构的直接范围。在对话数量增多的生产阶段，再推进服务器 pagination 或 virtualization。

## 后续优先级或暂不处理项目

### 整理 ChatPage title/read 订阅

#### 当前源码确认

ChatPage 当前从 cache snapshot 而非 query observer 读取当前对话标题和 unread count。

- `frontend/src/app/agents/[agentId]/conversations/[conversationId]/page.tsx:68`
- `frontend/src/app/agents/[agentId]/conversations/[conversationId]/page.tsx:82`

#### 判断

这个问题指出得对，但不是速度/闪烁的核心原因。作为 title stale、unread badge 延迟清理等 correctness/UX 问题后续处理。

### `CollapsiblePill` defaultExpanded 策略

#### 当前源码确认

`defaultExpanded` 仅用于初始 state。

- `frontend/src/components/chat/tool-ui/collapsible-pill.tsx:125`

file tool preview 是否展开由 helper 计算。

- `frontend/src/components/chat/tool-ui/code-tool-ui.tsx:72`

#### 判断

这不是性能问题，而是 UX 一致性问题。等 running 状态下 preview 后续出现却未打开的现象真正成为问题时再单独处理。

### Dashboard/AppSidebar/DataTable 全量 client-side 处理

#### 当前源码确认

Dashboard 对完整 agents 执行 client-side filter/sort/render。

- `frontend/src/app/page.tsx:70`
- `frontend/src/app/page.tsx:250`

AppSidebar 也会先拿到完整 agents，再计算最近 5 个。

- `frontend/src/components/layout/app-sidebar.tsx:132`
- `frontend/src/components/layout/app-sidebar.tsx:212`

DataTable 是 client-side search/filter/sort/pagination 结构。

- `frontend/src/components/ui/data-table.tsx:110`
- `frontend/src/components/ui/data-table.tsx:157`

#### 判断

作为全局扩展性问题是有效的，但应与当前请求的 chat UI 闪烁/streaming 性能分离。

## 已解决或监控项目

### 按 `content_delta` 立即 React state update

#### 当前源码确认

`content_delta` 不会立刻调用 `setStreamingMessages`，而是通过 rAF batching。

- batching 说明：`frontend/src/lib/chat/use-chat-runtime.ts:397`
- rAF schedule: `frontend/src/lib/chat/use-chat-runtime.ts:407`
- content delta 处理：`frontend/src/lib/chat/use-chat-runtime.ts:426`

#### 判断

这是已经改进的项目。无需继续修改，只需通过 React Profiler 确认效果并保留回归测试。

## 独立 Backend/API/DB 轨道

### `/api/agents` 聚合与索引

#### 当前源码确认

`list_agents` 会按 `agent_id` 对完整 `conversations` 做 group by，然后与 user agent join。

- `backend/app/services/agent_service.py:49`
- `backend/app/services/agent_service.py:60`
- user filter 在 join 之后：`backend/app/services/agent_service.py:62`

`Conversation.agent_id` 在模型层没有声明 index。

- `backend/app/models/conversation.py:16`

`Agent.user_id`、`Agent.model_id` 在模型层也没有声明 index。

- `backend/app/models/agent.py:23`
- `backend/app/models/agent.py:29`

在 migration 搜索中，也未确认到符合 conversation list 排序需求的显式索引。

#### 判断

这个问题有效。但应拆分为 DB/API 性能 PR，而不是 chat UI 重构。

#### 实现方向

- 评估新增 `conversations(agent_id, is_pinned, updated_at DESC)`
- 在 `/api/agents` 中先缩小到 user-owned agents，再只聚合这些 agent 的 conversations
- 评估 `agents(user_id, updated_at DESC)`，或用于 last-used 排序的 denormalized column
- `agents(model_id)` 对按 model 统计 agent count/delete guard 有效

### Message read path timestamp write

#### 当前源码确认

`list_messages_from_checkpointer` 在查询缺少 timestamp 的消息时，会将其记录到 `Conversation.message_timestamps` JSON 并 commit。

- timestamp map copy: `backend/app/services/chat_service.py:189`
- 检测 missing timestamp：`backend/app/services/chat_service.py:197`
- update/commit: `backend/app/services/chat_service.py:206`

#### 判断

这个问题有效。单纯读取消息因此变成 write transaction，可能增加 DB 负载与 lock 风险。但由于需要 timestamp projection 设计，适合独立 PR。

#### 实现方向

- 在 message append/finalize 时保存 timestamp。
- 或建立 message projection table，在 read path 仅读取 projection。
- 需要现有 `message_timestamps` JSON 的 migration/backfill 策略。

### Checkpoint 重复遍历

#### 当前源码确认

普通 message list 已经围绕 leaf checkpoint 做过改进。

- `_collect_leaf_checkpoints`: `backend/app/services/thread_branch_service.py:684`
- `build_message_tree`: `backend/app/services/thread_branch_service.py:707`
- 在 list route 中构建一次 tree 并复用：`backend/app/routers/conversations.py:620`

但 edit/regenerate 路径仍有重复遍历。

- edit 可在 `_resolve_branch_checkpoint` 中调用 `_collect_checkpoints`：`backend/app/routers/conversations.py:993`
- `_resolve_branch_checkpoint` 会再次调用 `rewind_to_checkpoint_before_message`：`backend/app/routers/conversations.py:1008`
- `rewind_to_checkpoint_before_message` 内部也会调用 `_collect_checkpoints`：`backend/app/services/thread_branch_service.py:750`
- regenerate 会先执行 `_collect_checkpoints`：`backend/app/routers/conversations.py:1113`
- regenerate 后又在 `rewind_to_checkpoint_before_message` 中再次收集：`backend/app/routers/conversations.py:1162`

#### 判断

这个问题有效。由于与 LangGraph time travel/fork 路径相关，需要单独测试。

#### 从 LangGraph 角度看

在 LangGraph persistence 中，checkpointer 与 `thread_id` 是对话记忆、HITL、branch/time travel 的核心。解决瓶颈的方向不应是移除 checkpointer，而应是优化 UI projection/cache 并减少 checkpoint 查询。

### SSE trace JSON row rewrite

#### 当前源码确认

`message_events` 每个 turn 用一行保存一个 `events` JSON 数组。

- `backend/app/models/message_event.py:30`
- `backend/app/models/message_event.py:40`

partial flush 时会读取现有 row，构建现有 id set，再合并成新数组。

- existing row select: `backend/app/services/trace_storage.py:95`
- existing ids build: `backend/app/services/trace_storage.py:112`
- merged events assignment: `backend/app/services/trace_storage.py:128`

#### 判断

这个问题有效。长响应或工具调用较多的 turn 中可能产生较大的 write amplification。由于很可能需要 schema 变更，应作为独立 PR 推进。

#### 实现方向

- 新增 `message_event_chunks` 表
- 或采用 event-per-row 结构
- resume replay 通过 chunk pagination 处理
- public share/debug trace read path 需要 migration

## 独立 Runtime/Deep Agents 轨道

### DeepAgent/runtime 重建

#### 当前源码确认

每次 run 都会重新构建 model、tools、backend、graph。

- `_prepare_agent`: `backend/app/agent_runtime/executor.py:687`
- model build: `backend/app/agent_runtime/executor.py:700`
- regular tool build: `backend/app/agent_runtime/executor.py:707`
- MCP tool build: `backend/app/agent_runtime/executor.py:719`
- 创建 FilesystemBackend：`backend/app/agent_runtime/executor.py:732`
- 调用 `create_deep_agent`：`backend/app/agent_runtime/executor.py:808`
- 在 config 中传递 `thread_id`：`backend/app/agent_runtime/executor.py:823`

#### 判断

这个问题有效。但这是需要 cache key、invalidation、user/tenant/credential isolation 的大型设计，应与 chat UI 重构分离。

#### 从 LangChain/Deep Agents 角度看

当前产品需求包括以下内容。

- 长期对话
- HITL interrupt/resume
- branch/regenerate/time travel
- tools/MCP/skills/filesystem
- schedule trigger

因此 framework 选择 Deep Agents + LangGraph 是合适的。不建议降级为简单 LangChain `create_agent`。

推荐的优化方向如下。

- 按 agent config hash 缓存 compiled runtime
- request 级 `thread_id`、user context、hook context 绝不共享
- credential version、tool config version、skill version 纳入 cache key 或 invalidation
- 保留 checkpointer

### Deep Agents Backend

#### 当前源码确认

FastAPI runtime 默认使用 `FilesystemBackend(root_dir=data, virtual_mode=True)` 作为 backend。

- import: `backend/app/agent_runtime/executor.py:22`
- backend 创建：`backend/app/agent_runtime/executor.py:732`
- 传递给 create_deep_agent：`backend/app/agent_runtime/executor.py:815`

#### 判断

这里需要注意。根据 Deep Agents memory/backend 指南，在 web server 中，StateBackend/StoreBackend/sandbox/CompositeBackend 比默认 file backend 更合适。

但当前代码还与 filesystem permission、virtual mode、skill runtime mount 交织，因此不立即替换，留到独立设计中处理。

推荐方向：

- 默认工作文件使用 StateBackend
- 长期 memory 使用 StoreBackend
- 仅对 skill package 与 runtime files，通过 CompositeBackend route 连接 FilesystemBackend
- 若需要执行代码，评估 sandbox backend

### MCP tool loading

#### 当前源码确认

MCP tool config 在 `build_tools_config` 中被转换为 executor shape。

- `backend/app/services/chat_service.py:603`
- `backend/app/services/chat_service.py:625`

executor 会按服务器逐个顺序连接。

- server loop: `backend/app/agent_runtime/executor.py:507`
- `MultiServerMCPClient(...).get_tools()`: `backend/app/agent_runtime/executor.py:509`
- timeout: `backend/app/agent_runtime/executor.py:513`

#### 判断

这个问题有效。但无条件长期缓存 MCP session/client 有风险。应先确认 credential/user/server lifecycle，再优先应用 schema cache 与 concurrency 限制。

## LangChain 相关不建议项目

以下做法看似可能提升性能，但很可能破坏产品功能，因此不做。

| 建议 | 不建议的理由 |
| --- | --- |
| 在 main chat 中移除 checkpointer | 会破坏对话记忆、HITL resume、branch/time travel。 |
| 不带 `thread_id` 执行 invoke/stream | thread-scoped persistence 会消失。 |
| 在 HITL 路径中禁用 checkpointer | 无法恢复 interrupt/resume state。 |
| 将 Deep Agents 降级为简单 LangChain agent | 不符合 skills/filesystem/subagent/HITL 需求。 |
| 无限期共享 MCP client/session | 需要 credential isolation、close lifecycle、schema 变更检测。 |

## 推荐实现顺序

### PR 1：Stream race 稳定化

目标：

- 防止 stale stream cleanup 覆盖新 stream 状态。
- 在 rAF callback 与 `finally` 中添加 token guard。
- 实现 rAF cancel。

主要文件：

- `frontend/src/lib/chat/use-chat-runtime.ts`
- `frontend/src/lib/chat/__tests__/use-chat-runtime-commit.test.tsx`
- 必要时新增 race test 文件

验证：

- stop/new/edit/regenerate race 单元测试
- 现有 HITL tests
- 现有 commit dedup tests

### PR 2：将 Refetch cleanup effect 化

目标：

- 移除 render phase state update。
- 将 refetch 完成后的 streaming cleanup 规则移入 effect。
- 保留 partial stream 保存规则。

主要文件：

- `frontend/src/lib/chat/use-chat-runtime.ts`
- `frontend/src/lib/chat/__tests__/has-new-assistant-message.test.ts`
- `frontend/src/lib/chat/__tests__/use-chat-runtime-commit.test.tsx`

验证：

- normal stream 结束后 backend message 到达时清除 streaming
- mid-stream 中断时保留 partial assistant
- 去重 optimistic user

### PR 3：Streaming markdown/code 轻量化

目标：

- streaming 期间对 fenced code block 使用 plain render。
- message complete 后应用 syntax highlighting。

主要文件：

- `frontend/src/components/chat/markdown-content.tsx`
- `frontend/src/components/chat/__tests__/markdown-content.test.tsx`

验证：

- streaming code block plain render
- final code block highlighted render
- 保留 mermaid 现有行为

### PR 4：降低 Streaming projection/usage 成本

目标：

- 避免每次 flush 都对 token usage 进行全量汇总。
- 减少相同 token usage 的 atom update。
- 减少 message merge 临时数组创建。

主要文件：

- `frontend/src/lib/chat/use-chat-runtime.ts`
- `frontend/src/lib/stores/chat-store.ts`

验证：

- 保持 token bar 数值
- refresh 后保持 token/cost
- 测量 streaming 期间 commit count 的下降

### PR 5: Tool UI lazy/memo

目标：

- 将大型 result 的 parse/stringify 延迟到 expanded/open 状态。
- 对 right rail pretty JSON 计算做 memoize。

主要文件：

- `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx`
- `frontend/src/components/chat/right-rail/tool-result-panel-content.tsx`
- `frontend/src/components/chat/tool-ui/collapsible-pill.tsx`

验证：

- collapsed tool card 中不执行大型 JSON stringify
- right rail open 时正常 pretty render
- 保持 image URL extraction

## 性能测量计划

### 浏览器场景

1. 5,000 字以上 markdown 回答
2. 300 行以上 code block 回答
3. 大型 JSON tool result
4. 包含 5 张以上图片的回答
5. 响应过程中 stop 后立即发送新消息
6. regenerate 后立即 stop
7. edit 后立即 regenerate
8. 网络中断后，在 resume 过程中发送新消息

### 测量指标

- React commit count
- main thread long task count
- first token 后的平均 frame time
- stream 期间 input latency
- 是否发生 scroll jump
- stale stream 中是否发生错误 refetch
- message complete 前后是否闪烁

### 推荐工具

- React Profiler
- Chrome Performance panel
- Playwright race scenario
- Vitest hook tests

## 最终决定

本次聊天 UI 的速度/闪烁重构将优先稳定前端 hot path。

包括：

- stream stale guard
- rAF cancel
- 移除 render phase update
- streaming code plain render
- 降低 token usage/projection 成本
- Tool UI lazy/memo

拆分：

- DB index
- 轻量化 `/api/agents` brief/list
- message projection table
- trace chunk/event table
- DeepAgent runtime cache
- 替换 Deep Agents backend
- MCP schema/client cache

不做：

- 移除 checkpointer
- 省略 `thread_id`
- 将 Deep Agents 降级为简单 LangChain agent
- 在未复现问题的情况下移除 `content-visibility:auto`
