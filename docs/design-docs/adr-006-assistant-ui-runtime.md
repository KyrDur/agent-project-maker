## ADR-006：assistant-ui ExternalStoreRuntime adapter

> **截至 2026-09-07 的当前实现附录。** 下方 2026-06-13 的决策记录保留当时的背景、方案和 legacy 路径。本附录只校正当前 main v3 界面的行为，不决定 AG-UI 迁移或 viewer 替换。

## 2026-09-07 当前实现附录

### Runtime 与官方 UI 界面

- main `langgraph_v3` 中，`useMoldyLangGraphStream` 持有 Moldy 的 conversation-scoped LangGraph stream 及 raw state/activity，并将结果 bridge 到 assistant-ui `useExternalStoreRuntime`。primary transport 是这条 custom LangGraph 路径，不会将 `@assistant-ui/react-langchain` full runtime hook 或 AG-UI 作为 primary 挂载。
- `AssistantPanel` 和 conversational Builder 继续保留 legacy `useChatRuntime`。不要假设所有聊天界面共用同一个 hook。
- 当前公开的 assistant-ui API 使用 `AuiConfig`、`Tools`、`defineToolkit`、`useAui`、`useAuiState`。main chat/AssistantPanel 使用包含 HITL 的 `ALL_TOOLKIT`，settings TestChatPanel 使用 `SETTINGS_TEST_TOOLKIT`，Builder 使用 `BUILDER_TOOLKIT`。
- 解析到的主要版本为 `@assistant-ui/react` 0.15.18、assistant-ui core 0.3.17、`@langchain/react` 1.0.35。lockfile 中直接依赖的 `@langchain/langgraph-sdk` 为 1.9.22，而 React 依赖下嵌套 SDK 为 1.10.2，因此不要把两者扁平化为同一版本。

### 当前对话契约与限制

- 普通输入作为 durable queue input 接收，只有服务器 claim 后才会产生 active run。没有 `run_id` 的 accepted pending input 并不代表失败。
- Steer 会先 durable 地接收纠正输入，请求并确认 predecessor 取消，然后从 committed state 启动**新 run**。same-run Steer 是另一种契约：保留当前 run，并在下一个 agent step 消费新指令，目前尚未实现。这也不同于修改或注入正在执行的 provider request token。对于尚未反映到 checkpoint 的外部 tool effect，不提供通用 exactly-once 保证。
- 失败 retry 会用新的 client request ID 重新接收准确的 failed durable input，并对不确定响应使用相同 request ID 做一次 reconcile。它不是成功 turn regenerate，也不是 checkpoint fork。
- slash command 只打开实际 capability。`/search` 是 rendered transcript 搜索，`/export` 是已加载 envelope 的 Markdown/JSON export，不是 backend full-history/PDF export。`/compact` 因没有认证的手动 action 而 disabled。未知或不可用 command 不会被静默发送给模型。
- `@file`、`@artifact`、`@skill`、`@conversation` 不是 multimodal model input，而是在 authorize 后固定的 text snapshot。最多 8 个，每个 UTF-8 32 KiB，总计 128 KiB；dispatch 时会重新检查权限，但不会用新内容替换 snapshot。label 仅用于显示。
- terminal metrics 是 nullable replay-safe snapshot。缺失 capture 不是 0，而是 `unknown`/`null`；需要区分 root/descendant tool·subagent count 与 inclusive total。如果 activity 被截断，会以 `activity_truncated` 告知；没有 usage 的 text-only response 可能只有 elapsed time，而 activity/token 为空。
- MCP App 使用按 conversation/run/tool/server provenance 限定范围的 backend proxy 和 sandbox renderer。metadata 不授予权限，也不会暴露 browser credential。即使官方 renderer 可以展示 capability，Moldy 仍会显式 deny `openLink` 和 `sendMessage`，widget 对可见 action 可能收到 policy error。
- side chat 仅在同一 user/agent 的 app-shell 中于 close/reopen 和 same-tab navigation 期间保留，切换 user 时会初始化。不会提供 reload/cross-device persistence，也不会把 main conversation 当作 side transcript 存储。pinned summary 只是 user-selected display snapshot，并非 memory/prompt injection/automatic summary。dictation 在 editable composer 中使用浏览器 `SpeechRecognition` adapter，没有独立 transcription backend 或 credential flow。QA 使用 speech double，实际 microphone end-to-end 尚未验证。

### 实现与验证路径

主要实现锚点为 `frontend/src/lib/chat/langgraph-runtime/use-moldy-langgraph-stream.ts`、`frontend/src/components/chat/chat-runtime-section.tsx`、`frontend/src/lib/chat/tool-ui-registry.ts`、`backend/app/services/conversation_run_worker.py`、`backend/app/services/chat_resource_context.py`、`frontend/src/lib/chat/mcp-apps/renderer.tsx`、`frontend/src/components/agent/assistant-side-chat-provider.tsx`。

按功能划分的 scripted-capture catalog 为 `frontend/e2e/chat-message-queue.spec.ts`、`chat-commands-context.spec.ts`、`chat-run-summary.spec.ts`、`chat-mcp-apps.spec.ts`、`chat-recovery-discovery.spec.ts`、`chat-dictation.spec.ts`。不必跑完整 suite，只运行其中一个 catalog spec，如下所示。

```sh
# Select Node 22 with the local toolchain manager first; node --version must print v22.x.
node --version
cd "$(git rev-parse --show-toplevel)"
manifest=".omo/evidence/project-restart-consolidated-roadmap/chat-recovery-discovery-$(date -u +%Y%m%dT%H%M%SZ).json"
NEXT_PUBLIC_CHAT_RUNTIME=langgraph_v3 E2E_TEST_HELPERS_ENABLED=true RATE_LIMIT_ENABLED=false E2E_CAPTURE_TOUR=1 \
  bash scripts/run-isolated-e2e-tests.sh scripted --project scripted-capture \
  --manifest "$manifest" \
  -- e2e/chat-recovery-discovery.spec.ts --workers=1 --retries=0
```

### 状态：已批准，2026-06-13 批准 LangGraph v3 扩展

### 背景
- 将 3 处（对话、创建、AssistantPanel）的聊天 UI 统一到 assistant-ui 库
- 现有 backend SSE API 必须保持不变
- 现有代码：Jotai atoms（streamingMessageAtom 等）+ 直接消费 SSE 的模式

### 决策
**使用 useExternalStoreRuntime + useExternalMessageConverter 组合**

1. **convert-message.ts**：`useExternalMessageConverter.Callback<Message>` callback
   - user → `{ role: 'user', content: string }`
   - assistant → `{ role: 'assistant', content: [text, ...tool-calls] }`
   - tool → `{ role: 'tool', toolCallId, result }`（自动合并）

2. **use-chat-runtime.ts**：基于 `useExternalStoreRuntime` 的 adapter hook
   - 合并 TanStack Query messages + streaming 中的 optimistic messages
   - 通过 `useExternalMessageConverter` 转换为 ThreadMessage[]
   - `onNew`：消费 SSE AsyncGenerator，累积 streaming 状态
   - `onCancel`：通过 AbortController 取消 stream

### 方案
- **方案 A**：ExternalStoreAdapter.convertMessage（per-message）
  - 优点：简单
  - 缺点：无法合并 tool 消息（per-message scope）
- **方案 B（选择）**：useExternalMessageConverter（batch）
  - 优点：自动把 tool 消息合并到 tool-call，基于 WeakMap 缓存
  - 缺点：增加额外 hook 调用
- **方案 C**：直接实现自定义 RuntimeCore
  - 优点：完全控制
  - 缺点：复杂度过高，依赖 assistant-ui 内部 API

### 结果
- 原有 SSE 基础设施（stream-chat.ts, stream-assistant.ts）原样复用
- Jotai atoms（streamingMessageAtom 等）可逐步移除
- 对话/AssistantPanel 都统一到同一个 useChatRuntime hook

### 2026-06-13 扩展决策：LangGraph v3 runtime

现有 `useExternalStoreRuntime` 决策继续用于 legacy Moldy SSE 路径。但为了正确表达 DeepAgents/LangGraph v3 streaming，将在聊天 runtime 中增加 feature-flagged LangGraph v3 路径。

决策：

- 当 `NEXT_PUBLIC_CHAT_RUNTIME=langgraph_v3` 时，前端只创建 1 个 `@langchain/react` `useStream`。
- 该 stream 使用 Moldy BFF 的 conversation-scoped Agent Streaming Protocol endpoint。
- assistant-ui 继续负责聊天界面，但语义上的 source of truth 是 LangGraph stream。
- `useMoldyLangGraphStream` 将 root coordinator messages 转换为 assistant-ui `useExternalStoreRuntime`，并将 raw stream 原样暴露给 DeepAgents state/subagent selector。
- HITL resume 由 assistant-ui tool UI 收集 decision 后，通过 `stream.respond` / BFF `input.respond` / LangGraph `Command(resume=...)` 处理。
- 为避免 approval 后 SDK thread lifecycle subscription 卡在 terminal 状态，resume 后立即通过公开的 `getThread().subscribe('lifecycle', ...)` 路径重新同步 thread stream。
- lifecycle/input subscription 保持在线程级而非 run 级。BFF 负责已保存事件 replay、跟随最新 live broker、broker rotation、idle replay throttling。

非决策：

- 不将 `@assistant-ui/react-langchain` 的 full runtime hook 作为 primary 挂载。Moldy 必须直接持有 raw `@langchain/react` stream，才能让 subagent selector、artifacts、memory、usage、branch/replay 状态共享同一 stream。
- `@assistant-ui/react-langgraph` 保留为参考实现/utility source，但不作为 primary runtime。该 adapter 适合通用 LangGraph assistant-ui 行为，但不直接满足 Moldy 将 root coordinator transcript 与 scoped subagent transcript 分离的需求。
- AG-UI 可继续作为外部兼容协议，但不会先把 LangGraph v3 事件扁平化成 AG-UI，再将其作为 Moldy 内部 primary runtime。

验证标准：

- 单元测试确认 `useMoldyLangGraphStream` 只创建一个 stream、bridge 到 assistant-ui，并在 `stream.respond` 后刷新 lifecycle subscription。
- 后端测试确认 lifecycle/input thread stream 在 broker rotation 后仍能通过同一 subscription 接收下一 run 的事件，且 idle DB replay polling 不会过度频繁。
- E2E 在 `frontend/e2e/chat-langgraph-v3.spec.ts` 中用一条流程验证 live state、HITL approve、subagent output、artifacts、usage tooltip、reload/replay、history、public share。
