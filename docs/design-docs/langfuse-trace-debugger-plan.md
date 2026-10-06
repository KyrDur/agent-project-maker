# Moldy Langfuse Trace Debugger 开发规划书

编写日期：2026-05-30

## 1. 背景

Moldy 为每个用户创建 Agent，并生成与各 Agent 的对话 session 来运行，
整体采用这种结构。当前 session URL 如下。

```text
/agents/{agent_id}/conversations/{conversation_id}
```

示例:

```text
http://127.0.0.1:3000/agents/25f1cb9f-ab05-4146-b890-a22452e3c942/conversations/42c6d343-3a3f-4119-8d0a-1459a3967776
```

Moldy 内部已有 `message_events`，按 assistant turn 单位保存 SSE event。
这些数据适合 SSE resume、共享页面的 tool/skill chip 渲染、
stream 恢复。但对于 LangChain/LangGraph/Deep Agents 的内部执行
流程、LLM 调用、tool span、middleware、retry、latency，以 waterfall 形式
进行调试时，作为 trace backend 的功能仍显不足。

因此使用 Langfuse 作为 trace 收集/存储 backend，并在 Moldy UI 中
提供基于 Agent Prism 的 trace viewer。

## 2. 当前 Langfuse 环境

- Langfuse URL: `https://langfuse-dev.apps.orca.cloud.hancom.com/`
- Langfuse version: `v3.150`
- Organization: `Protech`
- Project: `moldy`
- API key: 通过 backend env 或生产 secret 注入

Langfuse Python SDK v3 要求 self-hosted Langfuse platform `>=3.125.0`。
当前安装的 `v3.150` 适合基于 SDK v3 的集成。

## 3. 目标

1. 将 Moldy 的 user - agent - conversation 结构明确映射到 Langfuse trace。
2. 能从现有 conversation URL 内进入 trace debug 页面。
3. Moldy backend 通过 proxy 查询存储在 Langfuse 中的 trace。
4. frontend 使用 Agent Prism 渲染 span tree、waterfall、detail panel。
5. `message_events` 保持现有功能，只增加与 Langfuse trace 的 correlation。

## 4. 非目标

- 不将 Langfuse 用作 Moldy 的对话原始存储。
- 不在 browser 中暴露 Langfuse secret key。
- 不在 public share page 暴露 trace debug 信息。
- 初始版本不重新实现 Langfuse 自有 UI 的全部功能。
- 不将 Moldy core runtime 与 Agent Prism alpha API 强耦合。

## 5. 核心 ID 映射

| Moldy | Langfuse | 说明 |
| --- | --- | --- |
| `users.id` | `user_id` | 执行主体。为最小化个人信息，优先使用 UUID |
| `agents.id` | metadata `moldy_agent_id` | 按 Agent 过滤 |
| `conversations.id` | `session_id` | 对话 session。与 Moldy URL 的 conversation id 相同 |
| `message_events.assistant_msg_id` 或 stream `run_id` | trace id seed 或 metadata `moldy_run_id` | assistant turn 单位的执行 id |
| `Conversation.active_branch_checkpoint_id` | metadata `moldy_checkpoint_id` | branch/debug 追踪 |
| frontend route | metadata `moldy_route` | 返回 Moldy 页面的链接 |

推荐 trace 单位:

```text
Langfuse trace = 1 次 Moldy assistant turn
Langfuse session = 1 个 Moldy conversation
Langfuse user = 1 名 Moldy user
```

## 6. Metadata 契约

向 Langfuse callback 注入以下 metadata。

```python
metadata = {
    "langfuse_user_id": str(user_id),
    "langfuse_session_id": str(conversation_id),
    "langfuse_tags": ["moldy", "agent-chat"],
    "moldy_user_id": str(user_id),
    "moldy_agent_id": str(agent_id),
    "moldy_conversation_id": str(conversation_id),
    "moldy_run_id": run_id,
    "moldy_model_id": str(model_id) if model_id else None,
    "moldy_checkpoint_id": checkpoint_id,
    "moldy_route": f"/agents/{agent_id}/conversations/{conversation_id}",
    "moldy_source": "chat",
}
```

`moldy_source` 值:

- `chat`
- `resume`
- `edit`
- `regenerate`
- `trigger`
- `builder`

## 7. Backend 设计

### 7.1 环境变量

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://langfuse-dev.apps.orca.cloud.hancom.com/
LANGFUSE_PROJECT=moldy
```

`LANGFUSE_PROJECT` 用于人类可读的生产文档/日志。实际 project binding
由 Langfuse API key 所属的 project 决定。

### 7.2 依赖

Moldy backend 使用 Python SDK v3 系列。

```toml
langfuse>=3.8,<4.0
```

为支持 LangChain 1.x，至少使用 `3.8` 以上版本。由于 Langfuse platform 为
v3.150，初始引入阶段采用 SDK v3，而非 SDK v4。

### 7.3 Runtime hook

在 `executor.py` 中生成 LangGraph config 的位置，将 Langfuse callback
可选地注入 Langfuse callback。

```python
from langfuse.langchain import CallbackHandler

handler = CallbackHandler()

config["callbacks"] = [handler]
config["metadata"] = metadata
config["tags"] = ["moldy", f"source:{source}"]
```

保留现有 config 的 `configurable.thread_id`。

```python
config = {
    "configurable": {"thread_id": cfg.thread_id},
    "callbacks": [handler],
    "metadata": metadata,
    "tags": ["moldy", "agent-chat"],
}
```

### 7.4 Trace correlation 存储

`message_events` 继续承担现有 SSE event 存储职责。为实现 Langfuse correlation，
考虑增加以下列。

```text
external_trace_provider: "langfuse" | null
external_trace_id: string | null
external_trace_url: string | null
```

初始实现中使用 `external_trace_id = run_id` 或 deterministic trace id
进行对齐。若 Langfuse trace id 由 SDK 生成，则需验证在 finalize 时是否能够获取 trace id，
并进行存储。

### 7.5 Backend proxy API

Langfuse secret key 只能存在于 backend。frontend 仅调用 Moldy API。

```text
GET /api/conversations/{conversation_id}/debug/traces
```

行为:

1. 当前用户认证
2. 验证 `conversation_id` ownership
3. 在 Langfuse 中按 `session_id = conversation_id` 查询 trace 列表
4. 以 Moldy 使用的 summary shape 返回

响应示例:

```json
{
  "conversation_id": "42c6d343-3a3f-4119-8d0a-1459a3967776",
  "traces": [
    {
      "trace_id": "457165b4f06a19b5ba8a0830bd49e8d",
      "name": "agent.chat",
      "status": "success",
      "started_at": "2026-04-13T13:41:17Z",
      "duration_ms": 798380,
      "total_tokens": 258903,
      "moldy_run_id": "457165b4f06a19b5ba8a0830bd49e8d",
      "langfuse_url": "https://langfuse-dev.apps.orca.cloud.hancom.com/..."
    }
  ]
}
```

```text
GET /api/conversations/{conversation_id}/debug/traces/{trace_id}
```

行为:

1. 当前用户认证
2. 验证 `conversation_id` ownership
3. 验证 `trace_id` 是否属于对应 conversation/session
4. 查询 Langfuse trace observations/spans
5. 以 Agent Prism 或 Moldy Trace UI 可消费的 shape 返回

## 8. Frontend 设计

### 8.1 Route

保留现有 conversation URL。

```text
/agents/{agent_id}/conversations/{conversation_id}
```

debug 页面从同一个 session context 内进入。

推荐 deep link:

```text
/agents/{agent_id}/conversations/{conversation_id}/debug
/agents/{agent_id}/conversations/{conversation_id}/debug?traceId={trace_id}
```

初始版本在现有 conversation page 中以 side panel 或 drawer 形式添加，
后续可引入 child route。

### 8.2 页面构成

目标采用与附件图片类似的 3-pane 结构。

```text
左侧: Run 信息及过滤器
中间: Span tree / waterfall
右侧: Span 详情
```

左侧 panel:

- 执行状态
- 开始/结束时间
- 执行时长
- token/cost
- source 过滤器: chat/resume/edit/regenerate/trigger
- 个人信息/机密信息/有害信息过滤 placeholder
- 打开 Langfuse 原始页面

中间 panel:

- span 搜索
- span tree
- waterfall toggle
- workflow / LLM / tool / HTTP / MCP / skill badge
- 显示 duration
- 显示 success/error/interrupted 状态

右侧 panel:

- `Run`
- `Metadata`
- `Filtering`
- input/output tab
- model/provider 信息
- prompt/tool args/tool result
- 查看 raw JSON

### 8.3 Agent Prism 使用策略

Agent Prism 提供 Langfuse adapter 和基于 React 的 trace viewer component。
初始 POC 尽量直接使用 Agent Prism 的 viewer component。

验证项目:

- React 19 兼容性
- Moldy Tailwind v4 与 Agent Prism Tailwind v3 是否存在样式冲突
- 与 shadcn/ui token 的视觉一致性
- Agent Prism alpha API 变更可能性

风险缓解:

1. 将 Agent Prism 放在与 Moldy core component 分离的 debug module 中。
2. 在 Moldy 内部保留 adapter layer，降低 Agent Prism API 变更影响。
3. 若样式冲突较大，仅使用 data adapter，UI 用 Moldy component 重新实现。

## 9. 权限与安全

1. 普通用户只能查询自己的 conversation trace。
2. super_user 可在运营者 debug route 中允许访问全部 trace。
3. public share page 不暴露 debug trace。
4. Langfuse API secret 仅存放于 backend env/secret。
5. 不向 frontend 传递 Langfuse public/secret key。
6. credential-like key 在传输前进行 redaction。
7. system prompt、user input、tool result 是否存储由运营设置控制。

候选追加设置:

```env
LANGFUSE_CAPTURE_INPUT_OUTPUT=true
LANGFUSE_REDACTION_ENABLED=true
LANGFUSE_SAMPLE_RATE=1.0
```

## 10. 故障与 fallback

Langfuse 故障不应阻止 Moldy chat 执行。

策略:

- Langfuse callback 初始化失败时记录 warning log 后禁用 tracing
- Langfuse 传输失败时继续 agent execution
- Debug UI 查询 Langfuse 失败时，显示基于 Moldy `message_events` 的最小 trace
- 没有 `external_trace_id` 的历史对话显示为 debug unavailable 状态

## 11. 开发阶段

### Phase 1. Langfuse 收集 POC

- 添加 backend dependency
- 添加 env config
- 向 `executor.py` 注入 Langfuse CallbackHandler
- 在 Langfuse UI 中确认 user/session/metadata 是否按预期显示
- 分别确认 chat/resume/edit/regenerate 生成 trace

完成标准：

- 在 Langfuse `moldy` project 中生成 trace。
- 可按 `conversation_id` 进行 session grouping。
- `user_id`、`agent_id`、`run_id` 写入 metadata。

### Phase 2. Correlation 存储

- 向 `message_events` 添加 external trace 列
- 映射 stream `run_id` 与 Langfuse trace id
- 添加生成 trace URL 的 helper

完成标准：

- 可从 Moldy 对话 turn 跳转到 Langfuse 原始 trace。
- `message_events` 与 Langfuse trace 建立 1:1 关联。

### Phase 3. Backend Debug API

- 添加 trace list endpoint
- 添加 trace detail endpoint
- 添加 ownership 验证
- 添加 Langfuse API client wrapper

完成标准：

- 可在 conversation page 查询该 conversation 的 trace 列表。
- 无法查询其他用户的 conversation trace。

### Phase 4. Frontend Debug UI

- 在 conversation page 添加 Debug 入口
- 实现 trace list panel
- 应用 Agent Prism viewer POC
- 连接 span detail panel

完成标准：

- 可运行与附件图片类似的 3-pane trace debug 页面。
- 选择 span 时可查看 input/output/metadata。
- waterfall toggle 可用。

### Phase 5. 质量增强

- redaction 测试
- Langfuse 故障 fallback 测试
- 增强 token/cost/duration 显示
- 显示 trigger run trace
- raw JSON download 或 copy 功能

## 12. 测试计划

Backend:

- Langfuse disabled 状态下现有 chat 正常运行
- Langfuse enabled 状态下注入 callback
- ownership 验证
- trace list/detail API 权限测试
- Langfuse API failure fallback
- metadata shape regression

Frontend:

- 在 conversation route 中 Debug panel open/close
- trace list loading/error/empty
- span tree rendering
- span selection detail rendering
- mobile/desktop layout
- 处理 long prompt/tool result overflow

手动验证:

- 在 Langfuse UI 中确认 session grouping
- 比较 Moldy Debug UI 与 Langfuse 原始 trace 的 duration/token
- 确认 chat/resume/edit/regenerate/trigger source 区分

## 13. 主要风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Agent Prism alpha API 变更 | UI 维护成本增加 | 分离 adapter layer |
| Tailwind v3/v4 冲突 | 样式异常 | 隔离 debug module CSS |
| Langfuse API shape 变更 | backend proxy 失效 | 用 Langfuse client wrapper 隔离 |
| 过量保存 prompt/input | 个人信息/安全风险 | capture 设置, redaction |
| Langfuse 故障 | Debug UI 查询失败 | message_events fallback |
| trace id 不一致 | Moldy turn 与 trace 关联失败 | 基于 deterministic run_id 的 mapping |

## 14. 决策事项

1. 使用 `conversation_id` 作为 Langfuse `session_id`。
2. 使用 `user.id` 作为 Langfuse `user_id`。
3. Langfuse trace 按 assistant turn 单位生成。
4. 保留 Moldy `message_events`，只增加 Langfuse trace correlation。
5. frontend 不直接访问 Langfuse，而使用 backend proxy。
6. Agent Prism 用于初始 POC，但与 Moldy core 分离。

## 15. 参考资料

- Langfuse Sessions: https://langfuse.com/docs/observability/features/sessions
- Langfuse LangChain tracing: https://langfuse.com/integrations/frameworks/langchain
- Langfuse Python SDK v3: https://langfuse.com/docs/sdk/python/sdk-v3
- Agent Prism: https://github.com/evilmartians/agent-prism
