# 基于 Moldy DeepAgents 运行时源码的改进审计

编写日期：2026-05-30
对象：`natural-mold` 当前源码、已安装的 `deepagents==0.6.1`、4 份附件文档

> 2026-06-07 文档同步备注：该审计文档记录了当时的 runtime/doc gap，
> 属于 historical audit。P2-4 中对 `AGENTS.md`、`docs/PRD.md`、
> `docs/ARCHITECTURE.md`、`docs/marketplace-resources-prd.md` 不一致问题的指出，
> 已通过 2026-06-07 的文档更新解决。最新标准优先以 `docs/ARCHITECTURE.md` 和
> `docs/PRD.md` 为准。

审查的附件文档：

- `/Users/chester/Downloads/deepagents-runtime-audit.md`
- `/Users/chester/Downloads/fleet-vs-moldy-analysis.md`
- `docs/design-docs/hitl-ask-user-standardization-plan.md`
- `docs/design-docs/langfuse-trace-debugger-plan.md`

审查标准：

- 本地 LangChain/Deep Agents skill 文档
  - `framework-selection`
  - `deep-agents-core`
  - `deep-agents-memory`
  - `deep-agents-orchestration`
  - `langgraph-human-in-the-loop`
- 当前已安装的 DeepAgents API
  - 已确认 `create_deep_agent()` 签名支持：`subagents`、`skills`、`memory`、`permissions`、`backend`、`interrupt_on`、`store`、`checkpointer`
  - 已确认 `FilesystemBackend` 不是 `SandboxBackendProtocol`
  - 已确认 `FilesystemPermission` 的结构：`operations`、`paths`、`mode`

## 1. 结论摘要

Moldy 选择 DeepAgents 这一方向本身是正确的。产品是 no-code agent builder，并且需要长周期任务、skill、文件、调度、MCP、HITL、subagent delegation。相比 LangChain 单一的 `create_agent`，这些需求更适合 DeepAgents 层。

问题在于，虽然已经“调用”了 DeepAgents，但产品配置模型与 DeepAgents harness 仍有很多部分没有完全打通。尤其是 DB/UI 中已有的 sub-agent 并未真正传入 `create_deep_agent(subagents=...)`，文件权限在没有 `permissions` 的情况下开放了全局 `backend/data`，而 skill script 执行则绕过 DeepAgents sandbox 模型，以服务器进程权限运行。

附件文档中的部分判断已经在当前代码中得到改善。典型例子是 broad `/skills/` mount 和缺少 schedule run history，按当前源码已基本解决。但 core runtime 仍存在重要问题，其中一些风险甚至比附件文档描述得更明确。

最先要修的事项，相比“开启新功能”，更应是“先建立权限/credential/审批边界”。sub-agent runtime 打通虽然是核心功能，但如果在当前 file permission 和 HITL 都较弱的状态下先开启，会把高风险 tool surface 扩展到 child agent。

重新排序后的最高优先级：

1. 为现有 `/api/conversations/{conversation_id}/traces` 添加 auth/ownership guard。
2. 阻止 user agent middleware model 使用 system/env credential。
3. 将 `ask_user` 与审批 HITL 统一到 DeepAgents top-level `interrupt_on` 标准路径。
4. 建立 tool risk policy，并在 trigger mode 下默认阻止高风险工具。
5. 为 `FilesystemBackend(root_dir=data)` 加上 DeepAgents `permissions`，或通过 `CompositeBackend` 进行隔离。
6. 先将 `execute_in_skill` 设为 HITL/deny-by-default，再迁移为基于 sandbox/worker 的实现。
7. 确保 MCP runtime 支持与 discovery 相同的 credential interpolation/transport。
8. 在上述安全边界建立后，再把已保存的 sub-agent 真正传入 DeepAgents `subagents` 配置。
9. 将基于 `stream_mode="messages"` 的 SSE 扩展为以 DeepAgents event stream/tool_call_id 为中心。
10. 传播失败状态，避免 streaming error 在 hook/trace/message_events 中被记录成成功。
11. 之后接入 Langfuse trace debugger POC，用外部 span waterfall 补强内部 trace。

## 2. 附件文档判断验证

### 2.1 `deepagents-runtime-audit.md` 验证

| 附件 ID | 当前判断 | 依据 |
|---|---|---|
| DA-01/02：已保存的 sub-agent 未传入 runtime | 有效 | 存在 `Agent.sub_agent_links` 和 API 保存路径，但 `AgentConfig`/`build_agent()`/`create_deep_agent()` 调用中没有 `subagents`。 |
| DA-03：skill slug/UUID path mismatch | 基本解决 | 当前已有 per-thread `/runtime/{thread_id}/skills/{slug}` copytree 和 prompt prefix rewrite。但 canonical `/skills/<uuid>` 仍位于全局 backend 下。 |
| DA-04：挂载整个 `/skills/` 而非 selected skill | 部分解决 | 已改为 `skills_sources = ["/runtime/{thread_id}/skills/"]`。但由于 Filesystem tool 没有权限控制，模型仍可尝试访问 `/skills/<uuid>` 等 data root 下的其他路径。 |
| DA-05：`execute_in_skill` 不是 sandbox，而是 host subprocess | 有效，且更严重 | 当前不仅允许 Python，也允许 `curl`，并注入 credential env。没有 OS sandbox/chroot/network 限制。 |
| DA-06：全局 `FilesystemBackend`，未使用 `permissions` | 有效 | 仅使用 `FilesystemBackend(root_dir=str(_DATA_DIR), virtual_mode=True)`，wrapper 中没有 `permissions` 参数。 |
| DA-07：memory 并非基于 Store/CompositeBackend | 部分有效 | 虽然使用 `/agents/{agent_id}/AGENTS.md` file memory，但没有 StoreBackend/namespace/approval/UI。 |
| DA-08：HITL 漏掉 built-in file tools | 有效，且更严重 | auto `interrupt_on` 的计算发生在添加 skill tool/ask_user 之前，DeepAgents built-in `write_file`/`edit_file` 不在计算范围内。 |
| DA-09：在 trigger mode 下强制关闭 HITL | 有效 | 为避免 hang 的目的合理，但没有用于 schedule/channel 的 risk policy/approval queue。 |
| DA-10/11：streaming 结构和 tool result 匹配脆弱 | 有效 | 仅使用 `stream_mode="messages"`，SSE 中没有 `tool_call_id`。frontend 会把普通 result 绑定到最后一个 tool call。 |
| DA-12：assistant fixer 也会获得 DeepAgents built-in tools | 有效 | assistant 也使用 `build_agent()`，因此 DeepAgents built-in tool suite 会以 additive 方式加入。 |
| DA-13：middleware catalog 与 runtime filtering 不一致 | 有效 | public API 会隐藏 auto-injected，但 assistant read tool 会展示完整 registry。 |
| DA-14：provider middleware 可能重复 | 有效 | DeepAgents 0.6.1 会无条件在 tail stack 添加 AnthropicPromptCachingMiddleware。Moldy 也会针对 anthropic provider 直接添加。 |

### 2.2 `fleet-vs-moldy-analysis.md` 验证

附件中的 Fleet 对比文档方向是对的，但其中部分 schedule 内容已经落后于当前代码。

已经补齐的部分：

- 已有 `agent_trigger_runs` 模型和 run history API。
  - `backend/app/models/agent_trigger_run.py`
  - `backend/app/services/trigger_service.py:368-493`
  - `backend/app/routers/triggers.py:98-107`
- 已有 schedule conversation policy。
  - `schedule_thread`, `new_per_run`, `selected_conversation`
  - `backend/app/services/trigger_service.py:18-22`, `388-424`
- `one_time` trigger 已连接到 scheduler。
  - `backend/app/scheduler.py:100-119`
- frontend `/schedules` 中已有 history dialog。
  - `frontend/src/app/schedules/page.tsx:411-469`

仍然有效的 Fleet gap：

- Channels 仍是 placeholder。
  - `frontend/src/components/agent/visual-settings/nodes/channels-node.tsx:7-23`
- 尚无 Agent identity、fixed/user credential policy、channel delivery target、async approval inbox。
- MCP 的 discovery 与 runtime 在 credential/transport 处理上仍有差异。
- LangSmith Fleet 水平的 run/trace/eval/replay 目前仍只实现了一部分。

文档本身此前也需要更新，并已在 2026-06-07 的文档同步中解决：

- `AGENTS.md`/`CLAUDE.md` 已更新为 M59、executor split、marketplace/memory/artifact 状态。
- `docs/PRD.md` 已移除 PoC/mock auth 描述，并按 ADR-016 之后的产品状态重写。
- `docs/ARCHITECTURE.md` 已从 M1/M2 规划文档替换为当前 runtime/source map。
- `docs/marketplace-resources-prd.md` 已加入 v0.3 current implementation status，并将 spec 标记为 historical baseline。

### 2.3 `hitl-ask-user-standardization-plan.md` 验证

该文档与当前源码高度一致。尤其是对 P0-4 root cause 的说明更准确。

有效的判断：

- `ask_user` tool 会在 `interrupt_on` 计算之后才添加。
  - wrap 尝试：`backend/app/agent_runtime/executor.py:703-706`
  - 实际添加 tool：`backend/app/agent_runtime/executor.py:773-776`
- `ask_user` 标准策略仅在 `interrupt_on is not None` 时 merge。也就是说，如果没有 explicit HITL 设置，`ask_user` 不会被标准 `respond` decision 包裹。
  - `backend/app/agent_runtime/executor.py:703-706`
- 直接把 `HumanInTheLoopMiddleware` 放进 middleware list，并以 `create_deep_agent(interrupt_on=None)` 调用。
  - 直接注入：`backend/app/agent_runtime/executor.py:715-716`
  - 禁用 DeepAgents top-level path：`backend/app/agent_runtime/executor.py:786-789`
- DeepAgents 0.6.1 会把 top-level `interrupt_on` 继承给 declarative subagent 和默认 `general-purpose` subagent。
  - `deepagents/graph.py:591-609`
  - `deepagents/graph.py:665-666`
- native `ask_user.py` 会将 `interrupt()` 的 resume 值直接以 `str(response)` 返回。
  - `backend/app/agent_runtime/tools/ask_user.py:29-36`
  - resume router 总是发送 `{"decisions": [...]}` 形式。
  - `backend/app/routers/conversations.py:843-856`
- native ask_user fallback adapter 使用 `tool_name`，而不是 `review_configs[].action_name`。
  - `backend/app/agent_runtime/streaming.py:111-116`
- frontend `useChatRuntime` 支持 `onStandardInterrupt` callback，但普通对话页面没有传入它。
  - callback 调用：`frontend/src/lib/chat/use-chat-runtime.ts:446-458`
  - 普通对话页面：`frontend/src/app/agents/[agentId]/conversations/[conversationId]/page.tsx:120-128`

补充判断：

- 这份 plan 可以直接作为实施计划使用。
- 但需要与 P0-2/P0-3 一起处理。即使完成 `ask_user` 标准化，如果 file write/edit、skill execution、MCP mutation tool 仍未纳入策略，安全性依然不足。
- frontend 工作不能只停留在连接 `onStandardInterrupt`，还需要一个 coordinator，把 standard interrupt payload 转换为 assistant-ui synthetic tool call。当前 `UserInputUI` 和 `ApprovalCard` 是单 decision 立即 resume 的结构，对 multi-action interrupt 较脆弱。

### 2.4 当前 plan 与 memory 的运行状态

#### Plan / TodoList

当前的“plan”基于 DeepAgents `TodoListMiddleware`，只实现了部分能力。

已生效的部分：

- Moldy 会通过 `create_deep_agent()` 创建所有 main agent。
  - `backend/app/agent_runtime/executor.py:781-794`
- DeepAgents 0.6.1 会自动把 `TodoListMiddleware` 添加到 main agent、custom subagent 和默认 `general-purpose` subagent stack。
  - `deepagents/graph.py:547-548`
  - `deepagents/graph.py:619-620`
  - `deepagents/graph.py:670-673`
- `TodoListMiddleware` 会添加 `write_todos` tool，并更新 graph state 中的 `todos`。
  - installed `langchain/agents/middleware/todo.py`
- Moldy frontend 中有专门用于 `write_todos` 的 UI。
  - `frontend/src/components/chat/tool-ui/plan-tool-ui.tsx:52-55`
  - `frontend/src/lib/chat/tool-ui-registry.ts:31-47`
- main chat 使用 `thread_id = conversation_id` 和 Postgres checkpointer，因此在同一个 conversation 内，todo state 可以保存在 checkpoint 中。
  - `backend/app/agent_runtime/executor.py:789-797`

不足之处：

- plan 不是可以通过产品设置开关的功能。它作为 DeepAgents built-in 始终存在，而 `todo_list` middleware 设置会在 runtime 中被过滤。
  - `backend/app/agent_runtime/executor.py:667-673`
- UI 只展示 `write_todos` tool call，没有通过单独 API/side panel 读取当前 todo state 的结构。
- SSE 中没有 `tool_call_id`，因此重复 plan update 与 result 的匹配较脆弱。
- 由于 subagent 连接没有传入 runtime，用户创建的 child agent 的 plan 还没有达到按 parent/child 结构拆分运行的阶段。

结论：

- 如果问“有没有 DeepAgents plan 工具？”，答案是有。
- 如果问“是否已经把计划状态作为 Moldy 产品功能稳定地管理/查询/恢复？”，答案还是否定的。

#### Memory

当前的“memory”基于 DeepAgents `MemoryMiddleware`，只实现了非常薄的一层能力。

已生效的部分：

- 存在 `agent_id` 时，会将 `/agents/{agent_id}/AGENTS.md` 作为 memory source 传入。
  - `backend/app/agent_runtime/executor.py:768-772`
- DeepAgents 在有 `memory` 参数时会添加 `MemoryMiddleware`。
  - `deepagents/graph.py:718-727`
- `MemoryMiddleware` 会从 backend 读取 source file，并以 `<agent_memory>` block 注入 system prompt。
  - installed `deepagents/middleware/memory.py:290-349`
- Moldy 会创建 agent memory directory。
  - `backend/app/agent_runtime/executor.py:769-771`

不足之处：

- 不会创建 `AGENTS.md` 文件本身。如果文件不存在，DeepAgents 会无报错地 skip，并在 prompt 中加入 `(No memory loaded)`。
- memory write 依赖模型通过 `edit_file` 直接修改文件。但 file permission/HITL 策略尚未整理完成。
- 不使用 `StoreBackend`/`CompositeBackend`，而是使用全局 `FilesystemBackend(root_dir=data)`。
- 没有 memory UI、audit、user approval、schedule mode memory write policy。
- 如果 state 中已经有 `memory_contents`，MemoryMiddleware 不会重新加载。即使同一 checkpoint thread 中的 memory file 被外部修改，也难以保证每个 turn 都重新加载最新文件。

结论：

- 已具备“读取 AGENTS.md 并放入 prompt 的最小连接”。
- 更准确的判断是，“长期记忆产品功能”尚未实现。

### 2.5 `langfuse-trace-debugger-plan.md` 验证

这份 plan 与当前基于 `message_events` 的 SSE trace 有明确的互补关系。Moldy 内部 trace 适合 stream resume/share chip 渲染，而 Langfuse 更适合调试 LangChain/LangGraph/DeepAgents 内部 span、LLM call、tool call、latency waterfall。

有效的判断：

- 当前 `message_events` 会按 assistant turn 保存 SSE event trace。
  - `backend/app/models/message_event.py:18-72`
  - `backend/app/services/trace_storage.py:60-181`
- stream run id 已经被用作 turn correlation key。
  - 生成：`backend/app/routers/conversations.py:319-330`
  - partial flush: `backend/app/routers/conversations.py:334-357`
  - finalize: `backend/app/routers/conversations.py:360-398`
- 目前还没有 Langfuse runtime integration dependency。不过用户已在实际 `backend/.env` 中加入下列 key，repo 中的 `backend/.env.example`/`Settings` 也已统一为同名。
  - `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_BASE_URL`
  - `backend/pyproject.toml`
  - `backend/.env.example`
  - `backend/app/config.py`
- Langfuse SDK v3 + LangChain callback 的方向与官方文档一致。
  - 官方文档也给出 `from langfuse.langchain import CallbackHandler` 与 `config={"callbacks": [handler]}` 的用法。
  - SDK v3 self-hosted 的版本要求也与 plan 中 `>=3.125.0` 的说明一致。
- 将 trace 单位定义为“Langfuse trace = 1 次 assistant turn”、“Langfuse session = 1 个 conversation”，与当前 Moldy run_id/conversation_id 结构高度匹配。

额外发现的问题：

- 现有 `/api/conversations/{conversation_id}/traces` endpoint 没有 `get_current_user` 和 ownership 校验。
  - `backend/app/routers/conversations.py:486-502`
  - 当前只调用 `chat_service.get_conversation()`。
  - trace event 可能包含 tool args/results、user content、file/skill output，因此应在接入 Langfuse debugger 之前优先修复。
- 如果直接开启 Langfuse callback，prompt、user input、tool args/result 可能被发送到外部 trace backend。除当前 SSE event redaction 外，还需要独立的 external trace redaction/capture policy。
- 给 `message_events` 增加 correlation 列是正确方向，但要先验证 `external_trace_id` 应采用 SDK 生成的 id，还是强制使用 deterministic `run_id`。
- Agent Prism 具有 alpha 属性，因此不应直接强耦合到 core chat UI，而应隔离到 adapter/debug module。

改进方案：

- 短期 P0：
  - 为现有 `/api/conversations/{conversation_id}/traces` 添加 `CurrentUser` dependency 与 `get_owned_conversation()` guard
  - 明确区分 share page 的 trace 暴露与 authenticated debug trace API
- P1:
  - 添加 `LANGFUSE_ENABLED`、key/base URL env 和 `langfuse>=3.8,<4.0` dependency
  - 不要把 callback factory 直接散布在 `executor.py` 中，而是隔离到 `observability/langfuse.py` 这类小型 adapter
  - 向 LangGraph config 注入 callback/metadata/tags
  - 在 `message_events` 中添加 `external_trace_provider`、`external_trace_id`、`external_trace_url`
  - 在 backend proxy API 中验证 conversation ownership 和 trace-session membership
- P1/P2:
  - 将 Agent Prism POC 隔离到 debug route/module
  - Langfuse 故障时提供 `message_events` fallback UI
  - 通过 env 控制 input/output capture、redaction、sample rate

## 3. 按最终优先级整理的详细 backlog

本节是执行顺序的 source of truth。后面的“各领域详细依据”是用于保留各项源码证据与背景的 reference bank。

### 1. existing trace endpoint access control

优先级：

- P0

为什么要先做：

- 当前 `/api/conversations/{conversation_id}/traces` 在没有 `get_current_user` 的情况下只调用 `chat_service.get_conversation()`。
- `message_events` 中可能包含 user content、tool args/result、skill output、部分 file content。
- 接入 Langfuse debugger 后 trace 表面积会进一步扩大，因此应先关闭现有 trace endpoint 的权限缺口。

立即要做：

- 在 `backend/app/routers/conversations.py` 的 trace endpoint 中添加 `CurrentUser = Depends(get_current_user)`
- 将 `chat_service.get_conversation()` 替换为 `get_owned_conversation()` 或等价的 ownership guard
- 分离用于 public share page 的 trace shape 与 authenticated debug trace shape
- 添加 cross-user/unauthenticated trace access regression test

完成标准：

- 无法通过其他用户的 `conversation_id` 查询 trace event。
- 未认证请求无法获得 trace。
- share page 只接收 chip 渲染所需的最小 trace。

### 2. middleware model credential boundary

优先级：

- P0

为什么要先做：

- 在 user-facing agent runtime 中，middleware model 目前可能使用 system/env credential 创建。
- main model credential 策略相对严格，但 middleware model resolution 可能成为绕过路径。
- 这里同时涉及成本/安全/tenant isolation 问题。

立即要做：

- 从 user conversation/trigger runtime 中移除 `provider_api_keys=env_provider_keys()` 的传递，或拆分为 system flow 专用
- 添加 `create_chat_model(..., allow_env_fallback=False)` 选项
- 在 `_resolve_middleware_model_params()` 中拒绝没有 user-owned credential 的 middleware model
- 只允许 builder/assistant/system flow 使用 explicit env/system fallback

完成标准：

- user agent middleware model 不再通过 env/system credential 创建。
- credential 缺失时不会静默 fallback，而是返回明确且 user-actionable 的 error。

### 3. HITL/ask_user 标准 interrupt 接线

优先级：

- P0

为什么要先做：

- 这是审批、自然语言追问、subagent HITL 继承的共同 wire。
- 当前 `ask_user` 在 `interrupt_on` 计算之后添加，并且通过 manual `HumanInTheLoopMiddleware` 注入，导致失去 DeepAgents top-level 继承路径。
- 必须先把这一点理顺，tool risk policy 与 trigger guard 才能建立在同一套标准上。

立即要做：

- 在计算 interrupt policy 之前添加 `ask_user_tool`
- 移除 manual `HumanInTheLoopMiddleware` instance append
- 通过 `build_agent(..., interrupt_on=interrupt_on ...)` 使用 DeepAgents top-level path
- 在 native `ask_user.py` fallback 中，只提取 standard resume payload 的 `respond.message`
- 将 `streaming.py` native adapter 固定为 `review_configs[].action_name` 标准 shape
- 添加 frontend standard interrupt mapper/coordinator

完成标准：

- 即使没有 HITL 设置，对话模式下的 `ask_user` 也会以 `respond` decision resume。
- 默认 `general-purpose` subagent 也会继承 top-level HITL policy。
- multi-action interrupt 会保留 decision 数组的长度和顺序，并一次性 resume。

### 4. tool risk policy 与 trigger guard

优先级：

- P0

为什么要先做：

- trigger/invoke mode 因用户不在场而关闭 HITL，但当前没有针对高风险工具的替代策略。
- Gmail/Calendar/webhook/skill execution 等外部 mutation 可能在定时执行中未经审批直接发出。

立即要做：

- 为 registry/builtin/MCP/skill tool 添加 `risk_level` 或 `requires_approval` metadata
- 根据 risk metadata，而不是 tool name heuristic，生成 default HITL policy
- 在 trigger/invoke mode 下默认阻止 `external_mutation`、`code_execution`
- 在 trigger run 中保存 blocked reason 并在 UI 展示

完成标准：

- 对话模式中的 mutation/code execution 不会在未经审批时执行。
- trigger mode 下不会自动执行高风险工具。
- read-only tool 会继续执行，不需要不必要的审批。

### 5. filesystem permissions/CompositeBackend

优先级：

- P0

为什么要先做：

- 当前 DeepAgents file tools 都指向同一个 `backend/data` root。
- `virtual_mode=True` 只是缓解 path escape，并不是 user/agent/conversation ownership boundary。
- 这是隔离 memory、skill、conversation outputs 的基础。

立即要做：

- 添加 `build_agent(..., permissions=...)`
- 添加 agent/thread/user scoped permission builder
- 最小策略：允许 current thread skill runtime read、current conversation output read/write、own agent memory policy-bound read/write，其余 `/skills/**`、`/agents/**`、`/runtime/**` deny
- 中期通过 `CompositeBackend` 拆分 temporary workspace、skills、outputs、memory route

完成标准：

- agent A 无法读取或修改 agent B 的 memory/conversation/skill。
- 只能 read selected skill。
- built-in `write_file`/`edit_file` 同时遵循 permission 与 HITL 策略。

### 6. execute_in_skill containment/sandbox

优先级：

- P0

为什么要先做：

- 当前 `execute_in_skill` 绕过 DeepAgents sandbox model，执行 host subprocess。
- `curl` 与 credential env injection 同时存在，因此 egress/secret exfiltration 风险较高。

立即要做：

- 短期：将 `execute_in_skill` 改为必须 HITL 或 deny-by-default
- 移除对 `curl` 的允许，或替换为 allowlist proxy tool
- 添加 stdout/stderr size limit、process group kill、concurrency limit
- 中期：迁移到 Docker/firecracker/isolated worker 等 sandbox
- 长期：评估整合为基于 sandbox backend 的 DeepAgents built-in `execute`

完成标准：

- skill script 无法读取或写入 selected skill root 与 output mount 之外的位置。
- network egress 按 policy 阻止。
- 即使存在 credential env，也不会通过 stdout/stderr 与 external egress 泄漏。

### 7. MCP runtime credential/transport parity

优先级：

- P0

为什么要先做：

- 在 discovery 中成功的 MCP，到了 runtime 可能因为 raw headers/no interpolation/forced transport 而失败。
- stdio 在 discovery 中存在，但可能在 runtime 缺失，降低产品可信度。

立即要做：

- 添加 discovery/runtime 共用 connection builder
- 在 runtime 使用 `build_headers()`/`build_env_vars()` 或共用 helper
- 将 `transport`、`url`、`command`、`args`、`env_vars`、`headers`、decrypted credentials 传入 runtime config
- 支持 stdio runtime，或在 UI 中明确显示 runtime unsupported

完成标准：

- discovery 中成功的 credential-bound header/env 会以相同方式应用到 runtime call。
- runtime transport 与 discovery 保持一致。
- unhealthy MCP server 会快速以可解释的 error 失败。

### 8. sub-agent runtime 接入

优先级：

- P0

为什么排在第八：

- 虽然是核心功能，但如果在建立安全边界之前开启，child agent 可能放大 file/tool/credential surface。
- 需要先建立 HITL top-level inheritance 与 permission boundary，才能安全启用。

立即要做：

- 添加 `AgentConfig.subagents`
- 添加 child agent runtime assembly helper
- 添加 `build_agent(..., subagents=...)`
- 实现每个 child agent 的 tools/skills/model/permissions/HITL inheritance 策略
- 从 depth 1 开始，并阻止 multi-hop cycle

完成标准：

- 连接到 parent 的 child agent name 会显示为 `task` tool 的 available subagent。
- child prompt/tool/model 会实际被使用。
- child agent 也无法越过 top-level HITL/permission boundary。

### 9. event stream/tool_call_id

优先级：

- P1

为什么放在这里：

- 要让 tool result、plan update、subagent trace、Langfuse correlation 稳定对应，需要基于 id 的 event。
- 当前 frontend 会把普通 tool result 绑定到最后一个 tool call。

立即要做：

- 在 SSE `tool_call_start`/`tool_call_result` 中添加 `tool_call_id`
- 在 backend 保留 `tc.get("id")` 与 ToolMessage `tool_call_id`
- 将 frontend result matching 从 last call heuristic 改为基于 id
- 评估将 subagent event projection 扩展到 `agent_path`、`parent_tool_call_id`、`subagent_name`

完成标准：

- 即使连续调用同一个 tool，result 也会绑定到正确的 card。
- subagent tool calls 会与 parent tool calls 区分。
- share trace chip/right rail/debug trace 使用同一套 id 体系。

### 10. streaming error observability

优先级：

- P1

为什么放在这里：

- 当前 streaming path 即使 emit 了 error SSE，也可能在 hook/trace 中看起来像成功。
- 为保证 Langfuse debugger 和内部 trace 的可信度，需要先做好 error status propagation。

立即要做：

- 让 `stream_agent_response()` 通过 typed result 或 `error_sink` 传递是否发生 error
- 修改 `_run_agent_stream()`，准确区分 hook failure/post success
- 在 `message_events.status`、trace sink、external trace metadata 中反映失败状态

完成标准：

- 用户看到的 streaming error 在 backend observability 中也会记录为 failed。
- schedule/invoke/streaming path 对失败的语义保持一致。

### 11. Langfuse trace debugger POC

优先级：

- P1

为什么排在第十一：

- 虽然需要，但必须先处理现有 trace endpoint access control、event id、streaming error status，debugger 才能既安全又准确。
- 保留 `message_events`，Langfuse 用于补强 LangGraph/LLM/tool span waterfall。

立即要做：

- 添加 `langfuse>=3.8,<4.0` dependency
- 添加 `observability/langfuse.py` adapter
- 使用 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`、`LANGFUSE_ENABLED` settings
- 向 LangGraph config 注入 `CallbackHandler`、metadata、tags
- 在 `message_events` 中添加 external trace correlation 列
- 将 backend debug proxy API 与 Agent Prism POC 隔离到 debug module

完成标准：

- Langfuse trace 按 assistant turn 单位生成。
- `conversation_id` 会归入 Langfuse session。
- Moldy run id 与 Langfuse trace id 建立 1:1 关联。
- Langfuse 故障时 Moldy chat 执行不会失败，并显示 `message_events` fallback。

## 4. 各领域详细依据

以下内容是按主题汇总原因与源码依据的 reference bank。执行顺序遵循上文第 3、8、10 章的优先级。

### P0-1. existing trace endpoint 没有 access control

当前状态（截至 2026-05-30 审计时）：

- `/api/conversations/{conversation_id}/traces` endpoint 没有 `get_current_user` dependency。
  - `backend/app/routers/conversations.py:486-502`
- ownership 校验也没有使用 `get_owned_conversation()`，只调用 `chat_service.get_conversation()`。
  - `backend/app/routers/conversations.py:499-502`
- `MessageEvent.events` 中包含 SSE event sequence，可能包括 tool args/result 和 user/assistant content。
  - `backend/app/models/message_event.py:38-40`

为什么重要：

trace 虽然是调试数据，但实际上混有对话正文、tool input/output、skill 执行结果等敏感数据。接入 Langfuse debugger 后 debug surface 会进一步扩大，因此必须先关闭现有 internal trace endpoint 的 auth/ownership 缺口。

改进方案：

- 为 endpoint 添加 `user: CurrentUser = Depends(get_current_user)`
- 使用 `chat_service.get_owned_conversation(db, conversation_id, user.id)` 或等价 ownership guard
- 分离 public share page 的 chip 渲染 trace 与 authenticated debug trace API
- 添加 cross-user/anonymous access regression test

优先级：

- P0

### P0-8. UI/DB 中的 sub-agent 并未真正作为 DeepAgents subagent 运行

当前状态：

- `Agent` 模型拥有 `sub_agent_links`。
  - `backend/app/models/agent.py:80-86`
- 创建/修改 API 会保存 `sub_agent_ids`。
  - `backend/app/services/agent_service.py:273-278`
  - `backend/app/services/agent_service.py:331-342`
- frontend 的 payload 也会放入 `sub_agent_ids`。
  - `frontend/src/components/agent/visual-settings/visual-settings-flow.tsx:306-321`
- 响应 DTO 中也显示 `sub_agents`。
  - `backend/app/routers/agents.py:80-88`
- 但 runtime `AgentConfig` 中没有 subagent 字段。
  - `backend/app/agent_runtime/executor.py:157-199`
- `build_agent()` 没有向 `create_deep_agent()` 传入 `subagents`。
  - `backend/app/agent_runtime/executor.py:360-387`
- `create_deep_agent()` 的调用处也在没有 `subagents` 的情况下执行。
  - `backend/app/agent_runtime/executor.py:781-794`

为什么重要：

用户在 UI 中设置“这个 agent 可以委托给那个 agent”，但实际 DeepAgents `task` tool 中只会看到默认 `general-purpose` subagent。也就是说，产品核心功能目前只被保存，并没有真正执行。

改进方案：

- 在 `AgentConfig` 中添加 `subagents: list[dict] | None`
- 在 `chat_service.get_owned_conversation_with_agent()` 和 `get_agent_with_tools()` 中连同 child agent runtime 配置一起加载
- 将每个 child agent 的下列内容转换为 DeepAgents `SubAgent` dict
  - `name`
  - `description`
  - `system_prompt`
  - `model`
  - `tools`
  - `skills`
  - `middleware`
  - `interrupt_on`
  - `permissions`
- 阻止循环引用
  - 已经阻止 parent == child，但还需要单独阻止 multi-hop cycle
  - 优先只允许 depth 1 更安全
- subagent name 生成 provider-safe canonical name
  - 例如：`agent_<slug>_<8chars>`
- 添加测试
  - 用 `create_deep_agent` mock 验证是否传入 `subagents`
  - 验证 parent/child tool set 是否分离
  - 验证 child prompt 是否反映到 task 执行中

优先级：

- P0

### P0-5. 在没有 DeepAgents `permissions` 的情况下，整个 `backend/data` 都暴露给 file tool

当前状态：

- 所有 agent 都把同一个 data root 用作 backend。
  - `backend/app/agent_runtime/executor.py:719`
- `build_agent()` wrapper 不接收 `permissions` 参数。
  - `backend/app/agent_runtime/executor.py:360-387`
- 已安装的 DeepAgents 0.6.1 中，`create_deep_agent()` 支持 `permissions`。
- 按 DeepAgents 文档/源码，没有 permission rule 时允许 file call。
- Memory path 会开放为 `/agents/{agent_id}/AGENTS.md`。
  - `backend/app/agent_runtime/executor.py:768-772`
- Skill runtime 虽按 per-thread mount，但 canonical skill storage 也位于同一个 data root 下。
  - canonical: `data/skills/<uuid>`
  - runtime: `data/runtime/<thread_id>/skills/<slug>`

为什么重要：

`virtual_mode=True` 是防止 `../` escape 的机制，并不是 app-level ownership 策略。按当前结构，模型可以尝试 `ls("/")`、`read_file("/agents/...")`、`read_file("/skills/...")`、`write_file("/agents/...")` 等操作。即使不知道 UUID 会提高难度，也不能把它视为安全边界。

按 LangChain/DeepAgents 标准：

- DeepAgents 通过 `permissions` 控制 built-in filesystem tools。
- 推荐使用 `CompositeBackend` 分离 persistent memory 与工作文件。
- 如果要使用基于 Store 的长期记忆，必须明确指定 `store`。

改进方案：

- 添加 `build_agent(..., permissions=...)` 参数
- 在 `_prepare_agent()` 中按 agent/thread/user 生成 permission rule
- 最小默认策略示例：
  - allow read: `/runtime/{thread_id}/skills/**`
  - allow read/write: `/conversations/{thread_id}/**`
  - allow read/write: `/agents/{agent_id}/AGENTS.md` only if memory write policy allows
  - deny read/write: `/skills/**`
  - deny read/write: `/agents/**`
  - deny read/write: `/runtime/**` except current thread
- 重构 `CompositeBackend`
  - default: `StateBackend` for temporary workspace
  - skills route: read-only filesystem copy
  - conversation outputs route: conversation-scoped filesystem
  - memory route: StoreBackend or DB-backed backend
- permission regression tests
  - agent A cannot read agent B memory
  - conversation A cannot read conversation B outputs
  - 只允许 read selected skill

优先级：

- P0

### P0-6. `execute_in_skill` 绕过 DeepAgents sandbox 模型，在 host 上执行

当前状态：

- DeepAgents 0.6.1 的 built-in `execute` 在不是 sandbox backend 时不会执行。
- 当前 `FilesystemBackend` 不是 `SandboxBackendProtocol`。
- Moldy 另建 `execute_in_skill` tool，通过 `asyncio.create_subprocess_exec()` 执行 host process。
  - `backend/app/agent_runtime/executor.py:236-357`
- 允许的 executable：
  - `python`
  - `curl`
  - `backend/app/agent_runtime/executor.py:126-140`
- credential env injection 也已加入。
  - `backend/app/agent_runtime/executor.py:281-294`
- 虽然做了 stdout/stderr redaction，但没有 OS-level filesystem/network sandbox。
  - `backend/app/agent_runtime/executor.py:337-345`

为什么重要：

仅检查 script path 是否位于 skill runtime root 下并不够。Python script 以服务器权限运行，因此无法在 OS 层面阻止读取绝对路径文件、发起网络请求、长时间占用 CPU/内存、调用内部服务。允许 `curl` 又会在存在 credential env 的情况下进一步增大 egress 风险。

改进方案：

- 短期：
  - 将 `execute_in_skill` 自动执行默认设为 off，或强制 HITL
  - 移除对 `curl` 的允许，或替换为 allowlist 的 proxy tool
  - 除 timeout 外，增加 stdout/stderr size limit、process group kill、concurrency limit
  - 执行前只允许 `execution_profile.support_level` 为 `ready_python` 的 skill
- 中期：
  - 引入 sandbox backend
  - 在 Docker/firecracker/isolated worker 中选择一种
  - 只提供 read-only skill mount + writable output mount
  - 采用 network default deny、egress allowlist 策略
- 长期：
  - 与 sandbox backend 一起使用 DeepAgents built-in `execute`，并移除 custom runner

优先级：

- P0

### P0-3. HITL/ask_user 标准 interrupt wire 接线错误，导致重要工具与用户响应遗漏

当前状态：

- auto `interrupt_on` 只会针对 `langchain_tools` 名称中包含 write/send/delete/update/execute 等词的项生成。
  - `backend/app/agent_runtime/executor.py:675-696`
- 这项计算发生在添加 skill tool 之前。
  - auto 计算：`backend/app/agent_runtime/executor.py:680-696`
  - 添加 `execute_in_skill`：`backend/app/agent_runtime/executor.py:721-739`
- ask_user 也在 auto wrap 计算之后添加。
  - wrap 尝试：`backend/app/agent_runtime/executor.py:703-706`
  - 添加 ask_user：`backend/app/agent_runtime/executor.py:773-776`
- `ask_user` 只会在已有 `interrupt_on` 时加入标准 `respond` 策略。
  - `backend/app/agent_runtime/executor.py:703-706`
- DeepAgents built-in `write_file`、`edit_file` 不在 `langchain_tools` 中，因此不属于 auto 计算对象。
- `build_agent()` 通过 `interrupt_on=None` 关闭 DeepAgents 自动 HITL 注入。
  - `backend/app/agent_runtime/executor.py:786-789`
- 由于直接放入 `HumanInTheLoopMiddleware`，无法使用 DeepAgents top-level `interrupt_on` 的 subagent 继承路径。
- native `ask_user` fallback 不会从 resume payload 提取 `respond.message`，而是把整个 dict 字符串化。
  - `backend/app/agent_runtime/tools/ask_user.py:29-36`
- native ask_user interrupt adapter 使用 `tool_name`，而不是标准 `review_configs[].action_name`。
  - `backend/app/agent_runtime/streaming.py:111-116`
- 普通对话页面没有传入 `onStandardInterrupt`，因此 standard interrupt payload 不会真正合成为 card。
  - `frontend/src/app/agents/[agentId]/conversations/[conversationId]/page.tsx:120-128`

为什么重要：

风险最高的 file write/edit、skill execution、mutation tools 可能被默认 HITL 漏掉。尤其像 P0-2 那样缺少 file permissions 时，file write/edit 更加关键。此外，如果 `ask_user` 未按标准 `respond` decision 处理，模型可能收到的不是用户回答，而是 `{"decisions": [...]}` dict 字符串，标准审批/响应 card 也可能不会出现在 UI 中。

改进方案：

- 在所有 tool assembly 完成后再计算 `interrupt_on`。
- 对话模式下先添加 `ask_user_tool`，随后无论是否配置 HITL middleware，都 merge `ask_user: {"allowed_decisions": ["respond"]}`。
- 明确包含 DeepAgents built-in tool names。
  - `write_file`
  - `edit_file`
  - `execute`
  - 如有需要包含 `task`
- `execute_in_skill` 默认应属于 approve/reject 对象。
- 为 Gmail send、Calendar create/update/delete、Google Chat webhook 等 mutation registry tools 添加 risk metadata，并据此 metadata 决定 HITL。
- 不要直接创建 `HumanInTheLoopMiddleware`，而是传入 `build_agent(... interrupt_on=interrupt_on ...)`。该路径会同时处理 DeepAgents 默认 `general-purpose` subagent 与 declarative subagent 的继承。
- `ask_user.py` fallback 从 `{"decisions": [{"type": "respond", "message": "..."}]}` 中只提取 message。
- `streaming.py` native adapter 只使用 `review_configs[].action_name = "ask_user"`。
- frontend 添加类似 `standardInterruptToToolCalls()` 的纯 mapping 与 multi-action decision coordinator。
- 没有 explicit config 时的 default：

```python
interrupt_on = {
    "write_file": {"allowed_decisions": ["approve", "reject"]},
    "edit_file": {"allowed_decisions": ["approve", "edit", "reject"]},
    "execute": {"allowed_decisions": ["approve", "reject"]},
    "execute_in_skill": {"allowed_decisions": ["approve", "reject"]},
}
```

测试：

- 验证只添加 human_in_the_loop middleware 时，`write_file`、`edit_file`、`execute_in_skill` 是否也会被 gate
- 如果存在 explicit `interrupt_on`，以明确策略优先
- 验证即使没有 HITL 设置，对话模式下 `ask_user` 是否也会进入标准 `respond` policy
- 验证 trigger mode 下是否同时移除 `ask_user` 和 `interrupt_on`
- 验证 ask_user native fallback 是否只从标准 resume payload 返回 message
- 验证 standard interrupt payload 中 multi-action decision 的数量/顺序是否保留

优先级：

- P0

### P0-4. trigger/schedule 执行会关闭 HITL，但没有替代 risk policy

当前状态：

- trigger mode 中会强制 `interrupt_on = None`。
  - `backend/app/agent_runtime/executor.py:698-701`
- ask_user tool 也会在 trigger mode 中排除。
  - `backend/app/agent_runtime/executor.py:773-776`
- 这对避免 hang 是必要的，但并没有解决 mutation tool 自动执行的问题。

为什么重要：

调度执行需要比有人盯着的聊天更严格的策略。Gmail 发送、Calendar 创建、外部 webhook 调用、skill subprocess 等操作可能在定时执行中未经审批直接发出。

改进方案：

- 添加用于 schedule/channel 执行的 tool risk policy
  - `read_only`：自动允许
  - `write_internal`：在 pre-approved 时允许
  - `external_mutation`：默认阻止或进入 approval inbox
  - `code_execution`：默认阻止
- 创建/修改 trigger 时，如存在高风险工具则在 UI 警告
- 添加 async approval inbox
  - schedule run 在需要 approval 时暂停
  - 通知 owner
  - 到期时 auto reject
- 在 trigger run status 中添加 `waiting_approval`

优先级：

- P0

### P0-2. user agent middleware model 可以使用 system/env credential

当前状态：

- user conversation runtime 会传入 `provider_api_keys=env_provider_keys()`。
  - `backend/app/routers/conversations.py:128`
  - trigger 也相同：`backend/app/agent_runtime/trigger_executor.py:194`
- `_resolve_middleware_model_params()` 会预先通过 `create_chat_model()` 解析 middleware params 中的 `model`/`fallback_model` 字符串。
  - `backend/app/agent_runtime/executor.py:547-566`
- `create_chat_model()` 在没有 `api_key` 时会使用 `_ENV_FALLBACK`。
  - `backend/app/agent_runtime/model_factory.py:139-140`
- `_ENV_FALLBACK` 的注释写明它用于内部 caller，但当前 user agent middleware model resolution 也会走这条路径。
  - `backend/app/agent_runtime/model_factory.py:51-59`

为什么重要：

ADR-016 之后，user-facing agent chat 应使用 owner-registered credential 执行。main model 由 `resolve_llm_api_key_for_agent()` 强制保证这一点，但 middleware 如果需要单独的 model，仍有使用 operator/system/env key 的空间。

改进方案：

- 在 user agent runtime 中，不要向 `provider_api_keys` 放入 system/env fallback。
- middleware model params 限制为以下之一：
  - 复用 main model
  - 仅允许明确指定 user-owned credential 的 model
  - 只在 system flow(builder/assistant) 中允许 system resolver
- 拆分 `create_chat_model(..., allow_env_fallback=False)` 选项。
- `_resolve_middleware_model_params()` 在禁止 fallback 的模式下若 `api_key=None`，立即报错。

优先级：

- P0

### P0-7. MCP discovery 与 runtime 的 credential/transport 处理不一致

当前状态：

- discovery/probe 路径通过 `resolve_deep()` 执行 headers/env vars credential interpolation。
  - `backend/app/mcp/client.py:32-64`
  - `backend/app/mcp/discovery.py:31-43`
- runtime config 会原样传递 server headers。
  - `backend/app/services/chat_service.py:625-640`
- executor 直接使用 `mcp_transport_headers`，不会执行 credential interpolation。
  - `backend/app/agent_runtime/executor.py:469-489`
- config 中虽然放入 `"credentials": mcp_credentials`，但 executor 的 `_build_mcp_tools()` 只看 `auth_config`，实际上被忽略。
  - `backend/app/services/chat_service.py:637`
  - `backend/app/agent_runtime/executor.py:494-504`
- `stdio` MCP 在 discovery 中受支持，但 runtime 中如果没有 `server.url` 就会被跳过。
  - `backend/app/services/chat_service.py:611-612`

为什么重要：

UI 中“连接/发现成功”的 MCP tool，在实际 agent runtime 中可能认证失败，甚至完全缺失。尤其是在产品看起来同时支持 remote MCP 和 stdio MCP 的情况下，这会严重影响可信度。

改进方案：

- 让 discovery 与 runtime 使用同一个 connection builder。
- 向 runtime config 传入以下全部内容。
  - `transport`
  - `url`
  - `command`
  - `args`
  - `env_vars`
  - `headers`
  - decrypted credentials
- 在 runtime `_build_mcp_tools()` 中使用 `build_headers()`/`build_env_vars()` 或共用 helper
- 实现 `stdio` runtime 支持，或在 UI 中明确显示“discovery only, runtime unsupported”
- 评估 MCP client/session caching 或 lazy wrapper。

优先级：

- P0

## 5. P1：功能可用，但可信度/性能/可运营性不足的事项

### P1-1. MCP tool loading 每个 turn 都会重复网络 discovery

当前状态：

- `_prepare_agent()` 每次执行都会调用 `_build_mcp_tools()`。
  - `backend/app/agent_runtime/executor.py:662-664`
- `_build_mcp_tools()` 会调用 `MultiServerMCPClient(...).get_tools()`。
  - `backend/app/agent_runtime/executor.py:511-520`
- DB 中已经保存 `mcp_tools.input_schema` 与 `last_seen_at`。
  - discovery path: `backend/app/mcp/discovery.py:82-110`

为什么重要：

如果 MCP server 较慢或位于外部网络，首 token 前 latency 会增大。连接失败时整个 agent build 都会变慢，绑定越多 MCP tool 的 agent，瓶颈越严重。

改进方案：

- runtime tool wrapper 基于 DB schema 立即创建，真正 call 时再打开 client。
- 为每个 server 建立 client/session pool。
- 对 health_status 为 unhealthy 的 server，用快速失败 stub 替代。
- tool schema cache invalidation 在 discovery/update 时处理。

优先级：

- P1

### P1-2. skill runtime copytree 每个 turn 都在 event loop 中同步执行

当前状态：

- `_prepare_agent()` 会直接调用 `build_skill_runtime_context()`。
  - `backend/app/agent_runtime/executor.py:728`
- `build_skill_runtime_context()` 内部会同步执行 `mkdir`、`shutil.rmtree`、`shutil.copyfile`、`shutil.copytree`。
  - `backend/app/marketplace/skill_runtime.py:173-192`
  - `backend/app/marketplace/skill_runtime.py:248-261`
- helper docstring 写明 caller 如有需要应使用 `asyncio.to_thread` 包裹，但当前 caller 没有这样做。
  - `backend/app/marketplace/skill_runtime.py:161-164`

为什么重要：

绑定大型 `.skill` package 或多个 skill 的 agent，会在 agent build 期间阻塞 event loop。同一 thread 每个 turn 都删除 target dir 并重新 copy，也会产生大量不必要 IO。

改进方案：

- 在 `_prepare_agent()` 中使用 `await asyncio.to_thread(build_skill_runtime_context, ...)`
- 基于 content_hash，对已 materialized 的 skill 执行 skip
- target refresh 使用 atomic temp dir + rename
- 在 runtime 也应用 max package size 和 file count 限制
- cleanup job retention 与 active run 状态一并考虑

优先级：

- P1

### P1-3. 没有充分利用 DeepAgents event stream 结构

当前状态：

- `stream_agent_response()` 只使用 `agent.astream(..., stream_mode="messages")`。
  - `backend/app/agent_runtime/streaming.py:273-278`
- tool call start 通过解析 message chunk 中的 `tool_calls` 生成。
  - `backend/app/agent_runtime/streaming.py:326-354`
- tool result 只看 `msg.type == "tool"`。
  - `backend/app/agent_runtime/streaming.py:356-368`
- SSE type 中没有 `tool_call_id`。
  - `frontend/src/lib/types/index.ts:323-328`
- frontend 会把普通 tool result 绑定到最后一个 tool call。
  - `frontend/src/lib/chat/use-chat-runtime.ts:431-442`

为什么重要：

连续调用同一个 tool，或夹杂 subagent 内部 tool call 时，result 可能绑定到错误的 card。DeepAgents 的 subagent lifecycle、nested path、parent/child relation 也会在 UI 中丢失。

改进方案：

- 评估使用 `astream_events` 或 DeepAgents 官方 event projection
- 扩展 SSE schema
  - `tool_call_id`
  - `parent_tool_call_id`
  - `agent_path`
  - `subagent_name`
  - `run_id`
  - `status`
- backend 保留 `tc.get("id")` 和 ToolMessage `tool_call_id` 后 emit
- frontend 不再按最后一个 tool call，而是按 `tool_call_id` 匹配 result
- share trace chip 与 right rail 也使用相同 id

优先级：

- P1

### P1-4. model fallback 只能捕获 model construction 失败，无法捕获实际 LLM 调用失败

当前状态：

- executor 的 `_build_model_with_fallback()` 会对 `create_chat_model()` 调用做 try/except。
  - `backend/app/agent_runtime/executor.py:570-617`
- `create_chat_model()` 大多只是创建 SDK wrapper 对象，真正 API 调用发生在 streaming/invoke 阶段。
  - `backend/app/agent_runtime/model_factory.py:121-161`
- 单独的 `create_chat_model_with_fallback()` 也明确写着“we don't probe the model on every request”。
  - `backend/app/agent_runtime/model_factory.py:435-445`
- fallback chain 只有 model provider/name/base_url，credential resolving 默认复用 primary key。
  - `backend/app/routers/conversations.py:145-184`
  - `backend/app/agent_runtime/trigger_executor.py:30-62`

为什么重要：

429、500、provider outage、auth error 等真正需要 fallback 的情况，多数发生在 LLM 调用阶段。按当前结构，即使 UI 有 fallback，也很可能无法充分恢复 user-visible runtime failure。

改进方案：

- 将 LangChain model fallback primitive 或 middleware 应用到实际 model runnable。
- 明确 fallback model 的 credential 策略。
  - 只允许 same provider/same key
  - 或为每个 fallback model resolve user-owned credential
- 在 streaming path 的 trace/event 中记录 fallback 发生。
- tests:
  - 验证 primary `astream` 抛出 429 时是否会继续切换到 fallback model stream
  - 验证 fallback provider 不同时，credential 缺失 error 是否明确

优先级：

- P1

### P1-5. memory 虽开放为一个文件，但没有产品级长期记忆策略

当前状态：

- 如果存在 agent id，会把 `/agents/{agent_id}/AGENTS.md` 作为 memory source 传入。
  - `backend/app/agent_runtime/executor.py:768-772`
- DeepAgents `MemoryMiddleware` 会把 memory file 加载进 system prompt。
  - `deepagents/graph.py:718-727`
  - installed `deepagents/middleware/memory.py:290-349`
- 当前代码只创建 agent memory directory，不创建 `AGENTS.md` 文件。
  - `backend/app/agent_runtime/executor.py:769-771`
- 没有文件创建 lifecycle、write approval、memory UI、namespace policy。
- `store` 虽存在于 `build_agent()`，但实际 user agent 没有传入。
  - `backend/app/agent_runtime/executor.py:360-387`

为什么重要：

长期记忆应该是用户能理解并控制的产品功能。当前它只以 hidden file 形式运行，与 file write 权限结合后，模型可能在未经用户批准的情况下修改 memory。反过来，如果 `AGENTS.md` 不存在或模型没有创建 memory 文件，用户可能以为 memory 已开启，实际却接近 `(No memory loaded)` 状态。

改进方案：

- 明确 memory write policy
  - off / chat-approved / schedule-disabled / auto
- 决定是在 agent 创建时生成空 `AGENTS.md`，还是在第一次 memory write 时创建。
- 添加 AGENTS.md management UI
- 评估引入 StoreBackend 或 DB-backed Store
- 设计 per-user/per-agent namespace
- 为 schedule/channel 执行添加 memory write approval 策略
- 定义 memory reload 策略
  - 同一 conversation checkpoint 中如果已有 `memory_contents`，DeepAgents 会 skip reload，因此需要明确从外部 UI 修改 memory 后，在什么条件下会反映到新 run。

优先级：

- P1

### P1-6. streaming error 不会被记录为 hook failure

当前状态：

- `stream_agent_response()` 内部会捕获 agent stream exception 并 emit SSE `error`。
  - `backend/app/agent_runtime/streaming.py:383-389`
- 该 exception 不会传播到 `_run_agent_stream()` 外部。
  - `backend/app/agent_runtime/executor.py:917-942`
- 因此 hook framework 可能记录成 post success，而不是失败。

为什么重要：

用户虽然看到 error，但 backend audit/usage/observability 中可能看起来像成功。schedule/invoke path 会传播 exception，与 streaming path 不一致。

改进方案：

- 让 `stream_agent_response()` 通过 `error_sink` 记录是否发生 error，或以 typed result 返回 exception
- 让 `_run_agent_stream()` 准确区分 hook failure/post
- 在 trace_storage 中也记录 turn status

优先级：

- P1

### P1-7. assistant fixer agent 意外拥有 DeepAgents built-in tools

当前状态：

- assistant agent 使用普通 runtime 的 `build_agent()`。
  - `backend/app/agent_runtime/assistant/assistant_agent.py:84-91`
- 即使传入 `middleware=[]`，DeepAgents built-in tool suite 仍会以 additive 方式加入。
- 按 DeepAgents 0.6.1 source，built-ins：
  - `write_todos`
  - `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
  - `execute` 只会在 sandbox backend 中真正执行
  - `task`

为什么重要：

assistant fixer 的目的，是读取 DB 设置并通过受限 write tools 修改。混入文件/任务工具会扩大行为范围，也会让 UI/测试预期的工具表面与实际 tool surface 不一致。

改进方案：

- 将 assistant 拆分为 LangChain `create_agent`，或者
- 通过 DeepAgents HarnessProfile 的 `excluded_tools` 明确移除 built-in tools，或者
- 将 assistant 的 `permissions` 设为 deny-all，并从产品层面决定是否允许使用 `task`。

优先级：

- P1

## 6. P2：维护性/UX/文档一致性事项

### P2-1. middleware catalog 与 assistant catalog 不一致

当前状态：

- public `/api/middlewares` 会排除 auto-injected middleware。
  - `backend/app/routers/agents.py:244-250`
  - `backend/app/agent_runtime/middleware_registry.py:464-480`
- assistant read tool 会原样展示整个 `MIDDLEWARE_REGISTRY`。
  - `backend/app/agent_runtime/assistant/tools/read_tools.py:143-154`
- assistant write tool 只要在 registry 中就会保存，但 executor 又会过滤 `DEEPAGENT_BUILTIN_TYPES`。
  - `backend/app/agent_runtime/assistant/tools/write_tools.py:193-220`
  - `backend/app/agent_runtime/executor.py:667-673`

改进方案：

- assistant 也使用 `get_middleware_registry(exclude_builtin=True)`
- auto-injected 项只显示为“始终包含”
- 分离 user-configurable middleware 与 provider/internal middleware

优先级：

- P2

### P2-2. Anthropic prompt caching middleware 可能重复

当前状态：

- DeepAgents 0.6.1 会无条件在 tail stack 添加 `AnthropicPromptCachingMiddleware`。
- Moldy 在 provider 为 anthropic 时，也会通过 `get_provider_middleware()` 直接添加同一个 middleware。
  - `backend/app/agent_runtime/middleware_registry.py:414-427`
- 同时，`anthropic_prompt_caching` 又被归类为 auto-injected type。
  - `backend/app/agent_runtime/middleware_registry.py:430-440`

改进方案：

- 从 provider middleware 中移除 `anthropic_prompt_caching`
- 只对像 OpenAI moderation 这样 DeepAgents 不会自动添加的 middleware 保留 provider auto
- 添加 runtime middleware stack snapshot test

优先级：

- P2

### P2-3. `recursion_limit` 设置工具没有真正反映到 runtime

当前状态：

- assistant write tool 会保存 `model_params["recursion_limit"]`。
  - `backend/app/agent_runtime/assistant/tools/write_tools.py:631-649`
- read tool 也会显示该值。
  - `backend/app/agent_runtime/assistant/tools/read_tools.py:263-271`
- 但 `_prepare_agent()` 的 LangGraph config 中只有 `thread_id` 和 optional `checkpoint_id`。
  - `backend/app/agent_runtime/executor.py:796-803`
- DeepAgents 会在 compiled graph 上默认挂载 `recursion_limit=9999` config。

改进方案：

- 将 `cfg.model_params.get("recursion_limit")` 放入 LangGraph config top-level。
- 或者决定使用 DeepAgents 默认值，并移除 assistant 工具/文档中的相关项。

优先级：

- P2

### P2-4. docs/PRD/marketplace spec 落后于当前代码

当前状态：

- `AGENTS.md`：文档称最新 migration 为 M39，但代码已到 M50。
- `docs/PRD.md`：仍保留 PoC/mock auth 描述。
- `docs/marketplace-resources-prd.md` 与 spec：写着 broad `/skills/` mount 仍是当前问题，但 runtime 已改为 per-thread mount。

解决状态（2026-06-07）：

- `AGENTS.md`, `CLAUDE.md`, `README.md`, `README_KO.md`, `docs/ARCHITECTURE.md`,
  `docs/PRD.md`, `TASKS.md`, `docs/design-docs/index.md`,
  已按当前源码更新 `docs/marketplace-resources-prd.md`。

改进方案：

- 按代码更新 `docs/ARCHITECTURE.md`、`PRD.md`、marketplace docs
- 添加“resolved since M47/M50”之类 changelog 标记
- 单独维护 DeepAgents runtime 状态表

优先级：

- P2

## 7. 当前做得较好的部分

以下结构值得保留。

- `create_deep_agent()` 调用已集中到 `build_agent()`。
  - `backend/app/agent_runtime/executor.py:360-387`
- 使用 conversation id 作为 LangGraph `thread_id` 的方向是正确的。
  - `backend/app/agent_runtime/executor.py:796-803`
- 通过 Postgres checkpointer singleton 已具备 HITL/resume 基础。
  - `backend/app/agent_runtime/checkpointer.py`
- DeepAgents `write_todos` plan tool 会自动注入，frontend 也有专用 Plan card。
  - `frontend/src/components/chat/tool-ui/plan-tool-ui.tsx`
- skill broad mount 问题已通过 per-thread copytree 与 prompt rewrite 得到较大改善。
  - `backend/app/marketplace/skill_runtime.py:232-268`
  - `backend/app/agent_runtime/executor.py:736-766`
- 已有把 memory source 传入 `create_deep_agent(memory=...)` 的最小连接。
  - `backend/app/agent_runtime/executor.py:768-792`
- schedule run history 已在附件文档编写之后实现。
  - `backend/app/models/agent_trigger_run.py`
  - `frontend/src/app/schedules/page.tsx:411-469`
- trigger ownership 与 schema 一致性也比附件文档描述时更完善。
  - `backend/app/routers/triggers.py:119-143`
  - `backend/app/services/trigger_service.py:182-239`

## 8. 推荐实施顺序

### Milestone 0: Existing trace endpoint access control

目标：在接入 Langfuse debugger 前，先关闭现有 trace endpoint 的信息暴露可能性。

1. 为 `/api/conversations/{conversation_id}/traces` 添加 `CurrentUser = Depends(get_current_user)`
2. 使用 `get_owned_conversation()` 或等价 ownership guard，替代 `chat_service.get_conversation()`
3. 分离 share page trace 暴露与 authenticated debug trace API 的响应 shape
4. 添加 trace event redaction regression test

完成标准：

- 无法通过其他用户的 `conversation_id` 查询 trace event。
- unauthenticated request 无法获得 trace。
- public share page 只接收预期用于 chip 渲染的最小 trace。

### Milestone 1: Credential boundary quick fix

目标：先关闭用户执行中混入 operator/system/env key 的路径。

1. 从 user-facing conversation/trigger runtime 中移除 `provider_api_keys=env_provider_keys()` 的传递，或拆分为 system flow 专用
2. 添加 `create_chat_model(..., allow_env_fallback=False)` 选项
3. 修改 `_resolve_middleware_model_params()`，拒绝没有 user-owned credential 的 middleware model
4. 只允许 builder/assistant 等 system flow 明确使用 env/system fallback

完成标准：

- user agent 的 middleware model 不会通过 env/system credential 创建。
- main model 与 middleware model credential 策略通过测试分离。
- credential 缺失时不会静默 fallback，而是给出 user-actionable error。

### Milestone 2: HITL and ask_user standardization

1. 在计算 interrupt policy 前添加 `ask_user_tool`
2. 移除 manual `HumanInTheLoopMiddleware` instance
3. 通过 `build_agent(..., interrupt_on=interrupt_on ...)` 使用 DeepAgents top-level path
4. 添加 native `ask_user.py` fallback resume parser
5. 将 `streaming.py` native adapter 固定为 `action_name` 标准 shape
6. 添加 frontend standard interrupt mapper/coordinator

完成标准：

- 即使没有 HITL 设置，对话模式下的 `ask_user` 也会以 `respond` decision resume。
- 高风险工具 approval 与自然语言追问使用同一个标准 interrupt wire。
- 默认 `general-purpose` subagent 也会继承 top-level HITL policy。
- multi-action interrupt 会保留 decision 数组的长度和顺序，并一次性 resume。

### Milestone 3: Tool risk policy and trigger guard

1. 为 registry/builtin/MCP/skill tool 添加 `risk_level` 或 `requires_approval` metadata
2. 基于 risk metadata，而不是 tool name heuristic，生成 default HITL policy
3. 在 trigger/invoke mode 下默认阻止 `external_mutation`、`code_execution`
4. 在 trigger run 中记录 blocked reason，并在 UI 显示原因

完成标准：

- Gmail send、Calendar create/update/delete、webhook、`execute_in_skill` 在对话模式下不会未经审批执行。
- trigger mode 下不会自动执行高风险工具。
- 简单 read-only tool 会继续运行，不需要不必要的审批。

### Milestone 4: Filesystem permissions and skill containment

1. 添加 `build_agent(..., permissions=...)`
2. 添加 agent/thread/user scoped permission builder
3. 添加 built-in file tool access regression tests
4. `execute_in_skill` HITL default gate
5. 移除 `curl`，或改造成 allowlist proxy

完成标准：

- agent A 无法读取 agent B 的 memory/conversation/skill。
- 只能读取 selected skill。
- `write_file`/`edit_file`/`execute_in_skill` 不会未经审批执行。

### Milestone 5: MCP runtime parity and external credential correctness

1. 建立 discovery/runtime 共用 connection builder
2. 接入 runtime credential interpolation
3. 决定是否支持 stdio runtime
4. MCP tool wrapper caching/lazy call

完成标准：

- discovery 中成功的 credential-bound header/env 在 runtime call 中也会以相同方式应用。
- stdio server 要么得到 runtime 支持，要么在 UI 中明确阻止。
- MCP 连接失败不会过度增加首 token latency。

### Milestone 6: Sub-agent runtime correctness

1. 添加 `AgentConfig.subagents`
2. 添加 child agent runtime assembly helper
3. 添加 `build_agent(..., subagents=...)`
4. 实现每个 child agent 的 tools/skills/model/permissions/HITL inheritance 策略
5. 添加 subagent runtime tests

完成标准：

- 连接到 parent 的 child agent name 会显示为 `task` tool 的 available subagent。
- child prompt/tool/model 会实际被使用。
- parent 与 child 的 tool 权限不会混在一起。
- child agent 也无法越过 top-level HITL/permission boundary。

### Milestone 7: Event streaming and trace fidelity

1. 在 SSE 中添加 `tool_call_id`
2. 将 frontend result matching 改为基于 id
3. 评估 DeepAgents subagent event projection
4. 在 trace_sink 中保存 agent path/tool lifecycle

完成标准：

- 即使连续调用同一个 tool，结果也会绑定到正确的 card。
- subagent start/end/error 会与 parent run 区分。
- share trace chip/right rail 使用同一套 id 体系。

### Milestone 8: Streaming error observability

1. 为 `stream_agent_response` 添加 `error_sink` 或 typed result
2. 在 `_run_agent_stream` 中分离 hook success/failure 记录
3. 在 `message_events.status` 与 trace metadata 中反映 failed/error 状态
4. 添加统一 stream/invoke/trigger 失败 semantics 的测试

完成标准：

- streaming error 在 `message_events` 与 trace/hook 中会记录为失败，而不是成功。
- scheduler/invoke/stream 执行的失败状态可以用相同方式查询。
- 在接入 Langfuse 之前，内部 run failure metadata 会先达到可信状态。

### Milestone 9: Langfuse trace debugger POC

1. 确认 `langfuse>=3.8,<4.0` dependency 与 `LANGFUSE_*` settings wiring
2. 添加 `observability/langfuse.py` adapter
3. 向 LangGraph config 注入 `CallbackHandler`、metadata、tags
4. 为 `message_events` 添加 external trace correlation 列
5. 添加 backend debug proxy API
6. 在 conversation debug route 或 drawer 中接入 Agent Prism POC

完成标准：

- Langfuse trace 按 assistant turn 单位生成。
- `conversation_id` 会归入 Langfuse session。
- Moldy run id 与 Langfuse trace id 建立 1:1 关联。
- 无法通过 debug API 查询其他用户的 trace。
- Langfuse 故障时 Moldy chat 执行不会失败。

### Milestone 10: Runtime performance and reliability

1. MCP tool wrapper cache/lazy call
2. 将 skill runtime copytree 改为 `asyncio.to_thread` + content_hash cache
3. 将 real model fallback 从 construction-time 改为 invoke/stream-time fallback

完成标准：

- 即使 MCP 很慢，也不会过度增加首 token latency。
- 大型 skill package 不会阻塞 event loop。
- primary model 出现 runtime error 时，trace 中会记录是否发生 fallback。

### Milestone 11: Memory and plan productization

1. 定义 memory write policy
2. 决定 `AGENTS.md` 的创建/缺失/reload 策略
3. 评估 StoreBackend 或 DB-backed memory route
4. 添加 memory management UI/audit
5. 设计 Todo state 查询/side panel 或 trace integration

完成标准：

- memory 不再是“隐藏文件”，而会成为用户能够理解和控制的功能。
- 无法读取或修改其他 agent/conversation 的 memory。
- plan state 除 tool card 外也能稳定查询。

### Milestone 12: Automatic run product surface

1. schedule/channel tool risk policy
2. async approval inbox model
3. trigger run `waiting_approval` status
4. 设计 channel delivery target
5. 引入 agent identity mode

完成标准：

- 自动执行中的 external mutation/code execution 会默认阻止或进入 approval pending。
- 用户可以之后批准/拒绝 pending approval。
- schedule/channel 以哪种 credential identity 执行会保持明确。

## 9. 验证检查表

### Subagents

- 创建 parent A 与 child B。
- 为 B 设置与 A 不同的 system prompt 和 tool set。
- 将 B 连接到 A。
- 要求 A 委托给 B。
- 确认 `task` call 是否使用 B 的 canonical name。
- 通过 trace 确认是否只使用 B 的 prompt/tool/model。

### Filesystem and permissions

- 确认 `read_file("/")` 是否不会显示允许路径之外的目录。
- 确认 `read_file("/skills/<uuid>/SKILL.md")` 是否被阻止。
- 确认是否只允许 `read_file("/runtime/<current_thread>/skills/<slug>/SKILL.md")`。
- 确认 `write_file("/agents/<other_agent>/AGENTS.md")` 是否被阻止。
- 确认 `edit_file` 是否遵循相同策略。

### Skill execution

- 使用未选择的 skill slug 调用 `execute_in_skill` 时会被拒绝。
- selected skill script 遵守 timeout/size/concurrency 限制。
- 即使 credential env 被输出到 stdout/stderr，也会被 redaction。
- Python script 被隔离到无法读取 host absolute path 的 sandbox。
- network egress 会按 policy 阻止。

### HITL

- 在只添加 human_in_the_loop middleware 的 agent 中，`write_file` 会触发 interrupt。
- `execute_in_skill` 会触发 interrupt。
- Gmail send/Calendar create 等 mutation tool 会触发 interrupt。
- 即使没有 HITL middleware 设置，`ask_user` 也会以 `respond` decision 触发 interrupt。
- native `ask_user` fallback 会从 `{"decisions": [{"type": "respond", "message": "..."}]}` 中只返回 message。
- 标准 interrupt payload 使用 `review_configs[].action_name`。
- 在普通对话页面中，standard interrupt payload 会渲染为 `ask_user`/approval card。
- multi-action interrupt 会先收集全部 decision，再只 resume 一次。
- trigger mode 下高风险工具不会自动执行，而是按 policy 被阻止/进入 approval pending。

### Plan / TodoList

- 请求长任务时会出现 `write_todos` tool call。
- `write_todos` result 会渲染为 Plan card。
- 验证同一 conversation 的下一 turn 中 graph state 的 `todos` 是否保留。
- 重复 plan update 会基于 SSE `tool_call_id` 匹配到正确 card。

### Memory

- 新 agent 的 `/agents/{agent_id}/AGENTS.md` 创建/缺失策略保持明确。
- `AGENTS.md` 中保存的内容会进入下一次 model call 的 `<agent_memory>`。
- 无法读取或修改其他 agent 的 memory file。
- 从外部 UI 修改 memory 后，下一 run 会按已验证的 reload 策略反映修改。
- schedule/channel 执行中的 memory write 会按 policy 被阻止或进入审批等待。

### MCP

- header interpolation credential 会应用到 runtime call。
- env var interpolation credential 会应用到 stdio runtime。
- 多次调用同一 MCP server 的同一 tool 时，latency 不会过高。
- server 为 unhealthy 状态时，会快速返回可解释的 stub error。

### Streaming

- tool_call_start 与 tool_call_result 拥有相同 `tool_call_id`。
- 即使连续调用同一个 tool，result 也会正确绑定。
- subagent tool calls 会与 parent tool calls 区分。
- streaming error 会记录到 hook failure/trace status。

### Langfuse Debugger

- Langfuse disabled 状态下，chat/resume/edit/regenerate 与现有行为一致。
- Langfuse enabled 状态下，每个 assistant turn 会生成 1 个 trace。
- trace metadata 中包含 user/conversation/agent/run/checkpoint/source。
- debug trace list/detail API 会验证 conversation ownership。
- Langfuse API 故障时会显示基于 `message_events` 的 fallback。
- capture input/output off、redaction on、sample rate 设置分别正常生效。

## 10. 最终优先级表

执行顺序 1-11 是本次审计的核心改进顺序。第 12 项之后，是建立 correctness/security 边界后再推进的后续性能/产品化事项。

| 执行顺序 | 优先级 | 项目 | 原因 | 主要文件 |
|---:|---|---|---|---|
| 1 | P0 | existing trace endpoint access control | 当前 `/api/conversations/{conversation_id}/traces` 可能在没有 auth/ownership 的情况下返回 SSE trace，因此必须在 Langfuse 之前关闭。 | `conversations.py`, `trace_storage.py` |
| 2 | P0 | middleware model credential boundary | 用户执行中混入 system/env key 属于认证/成本/隔离问题，应最优先关闭。 | `executor.py`, `model_factory.py`, `conversations.py`, `trigger_executor.py` |
| 3 | P0 | HITL/ask_user 标准 interrupt 接线 | 是 approval、ask_user、subagent inheritance 的共同 wire，也是后续高风险工具策略的基础。 | `executor.py`, `ask_user.py`, `streaming.py`, `use-chat-runtime.ts` |
| 4 | P0 | 基于 tool risk 的 HITL policy 与 trigger guard | 当前 trigger 因无人在线而关闭 HITL，但没有高风险工具替代策略。应优先防止自动执行事故。 | `executor.py`, tool registry, `trigger_service.py` |
| 5 | P0 | filesystem permissions/CompositeBackend | DeepAgents file tools 当前看到全局 `data` root，需要先建立 memory/skill/conversation 隔离基础。 | `executor.py`, `skill_runtime.py` |
| 6 | P0 | `execute_in_skill` containment/sandbox | 短期移除 gate/curl，再迁移到 sandbox/worker。credential env 与 host subprocess 的组合风险最高。 | `executor.py`, marketplace skill runtime |
| 7 | P0 | MCP runtime credential/transport parity | discovery 中成功的 MCP 可能在 runtime 因认证/transport mismatch 失败，或漏掉 raw secret interpolation。 | `chat_service.py`, `executor.py`, `mcp/client.py` |
| 8 | P0 | sub-agent runtime 接入 | 虽是核心功能，但应在安全边界后开启，避免 child agent 放大 tool/permission surface。 | `executor.py`, `chat_service.py`, `agent_service.py` |
| 9 | P1 | DeepAgents event stream/tool_call_id | 要让 tool result、plan update、subagent trace 稳定对应，需要基于 id 的 event。 | `streaming.py`, `use-chat-runtime.ts` |
| 10 | P1 | streaming error observability | 降低用户看到 error、backend 却记录成成功的运营风险。 | `streaming.py`, hooks/trace |
| 11 | P1 | Langfuse trace debugger POC | 在保留内部 SSE trace 的同时，用外部 observability 补强 LangGraph/LLM/tool span waterfall。 | `executor.py`, `message_event.py`, debug API/UI |
| 12 | P1 | MCP tool loading cache/lazy call | correctness 之后，降低 first-token latency 与 MCP 故障传播。 | `executor.py`, MCP runtime |
| 13 | P1 | skill copytree async/cache | 减少大型 skill package 阻塞 event loop 的性能瓶颈。 | `skill_runtime.py`, `executor.py` |
| 14 | P1 | real model fallback | 让 fallback UI 与实际 runtime 失败恢复保持一致。 | `executor.py`, `model_factory.py` |
| 15 | P1 | memory product policy | 已有最小连接，但没有用户控制/approval/store/reload 策略。应在 FS 隔离之后产品化。 | `executor.py`, memory UI |
| 16 | P1 | plan product state | 已有 `write_todos` tool，但没有产品级查询/side panel/trace。应在 event id 整理后处理。 | chat UI, trace/right rail |
| 17 | P1 | assistant runtime separation | 解决 fixer agent 意外获得 DeepAgents built-ins 的问题。 | `assistant_agent.py`, `executor.py` |
| 18 | P2 | middleware catalog 整理 | 分离用户可配置项与 auto/internal 项。 | `middleware_registry.py`, assistant read/write tools |
| 19 | P2 | 移除 provider middleware 重复 | 降低 Anthropic prompt caching 重复的可能性。 | `middleware_registry.py` |
| 20 | P2 | 修复 recursion_limit no-op | 设置值未真正反映到 runtime，属于 UX 一致性问题。 | assistant tools, `executor.py` |
| 21 | P2 | 文档更新 | 减少代码与 PRD/AGENTS/marketplace docs 之间的状态差异。 | `AGENTS.md`, `docs/PRD.md`, marketplace docs |

## 11. 一句话结论

当前 Moldy 选择“基于 DeepAgents”的方向是正确的，但还没有达到“按 Moldy 的权限/credential/subagent/skill/调度产品模型组装好 DeepAgents harness”的状态。重新排序后的最优先事项是 existing trace endpoint access control、credential boundary、HITL/ask_user 标准化、trigger risk guard、filesystem permission、skill execution containment。Langfuse debugger 有必要，但最稳妥的顺序是先整理现有 trace API 权限与 event id/correlation，再接入。
