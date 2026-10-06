# ADR-020: Chat Run AG-UI Adapter

Status: Accepted<br>
Date: 2026-06-11

## Context

`docs/superpowers/plans/2026-06-10-durable-chat-run-lifecycle.md` 的 P6 是在未来将聊天通信迁移到 AG-UI 时，提前建立 migration seam，避免与当前实现中的 durable run lifecycle 冲突。

当前 Moldy 聊天已在以下契约上稳定：

- Primary POST stream: `/api/conversations/{conversation_id}/messages`
- Durable attach stream: `/api/conversations/{conversation_id}/runs/{run_id}/stream`
- 存储事件：`message_events.events`
- 运行状态：`conversation_runs`
- 前端 consumer：`useChatRuntime` 中的 Moldy `SSEEvent` switch

根据 2026-06-11 对 AG-UI 官方文档的确认：

- `@ag-ui/core` 提供事件驱动架构与 core event type。官方 overview 指引安装 `npm install @ag-ui/core`。<br>
  Source: <https://docs.ag-ui.com/sdk/js/core/overview>
- `@ag-ui/client` 提供 frontend/client 连接以及 `AbstractAgent`, `HttpAgent`, middleware。官方 overview 指引安装 `npm install @ag-ui/client`。<br>
  Source: <https://docs.ag-ui.com/sdk/js/client/overview>
- Core event type 包括 `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`, `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`, `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT`, `CUSTOM` 等。<br>
  Source: <https://docs.ag-ui.com/sdk/js/core/events>
- 官方 middleware 指南把将现有协议转换为 AG-UI event 的 bridge 方式描述为推荐用例。<br>
  Source: <https://docs.ag-ui.com/quickstart/middleware>

## Decision

P6 不立即把 AG-UI SDK 引入为 production dependency。先在 backend 添加把 Moldy SSE event 转为 AG-UI core event shape 的 adapter endpoint；frontend 通过 feature flag 消费该 endpoint，再转换回现有 `SSEEvent`。

做出该决策的原因：

- 当前聊天稳定性的核心在 `conversation_runs` 与 `message_events`。若 AG-UI 迁移绕过这个 durable lifecycle，刷新/会话切换/取消恢复能力会再次不稳定。
- AG-UI event 契约并不能把当前 Moldy UI 需要的 usage/status/artifact/memory/interrupt 信息全部 1:1 放进标准字段。为无损迁移，在 `rawEvent` 与 `CUSTOM.value.payload` 中保留 Moldy payload。
- 更安全的做法是在下一阶段整理完整 primary POST protocol、abort contract、message snapshot/store contract 后再加入 AG-UI SDK dependency。

## Backend Contract

新 endpoint：

```text
GET /api/conversations/{conversation_id}/runs/{run_id}/ag-ui-stream
```

Headers:

```text
X-Run-Id: {run_id}
X-Resume-Mode: live | replay | stale
X-Stream-Protocol: ag_ui
```

Resume:

- 同时支持 `last_event_id` query 与 `Last-Event-ID` header。
- AG-UI event id 格式为 `{moldy_source_event_id}:ag:{index}`。
- 即使一个 Moldy event 被拆成多个 AG-UI event，DB replay 也会以 AG-UI event id 为粒度准确续接。
- Live broker attach 中，如果 source event 仍在 broker buffer，则按 AG-UI event id 精确续接；若已超出 buffer，则 degrade 为按现有 source event attach。

## Event Mapping

| Moldy SSE | AG-UI |
|---|---|
| `message_start` | `RUN_STARTED` + `TEXT_MESSAGE_START` |
| `content_delta` | `TEXT_MESSAGE_CONTENT` |
| `message_end(status=completed/canceled)` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |
| `message_end(status=failed)` | `TEXT_MESSAGE_END` + `RUN_ERROR` |
| `error` | `RUN_ERROR` |
| `tool_call_start` | `TOOL_CALL_START` + `TOOL_CALL_ARGS` + `TOOL_CALL_END` |
| `tool_call_result` | `TOOL_CALL_RESULT` |
| `file_event` | `CUSTOM(name="moldy.file_event")` |
| `memory_*` | `CUSTOM(name="moldy.memory_*")` |
| `interrupt` | `CUSTOM(name="moldy.interrupt")` |
| `stale` | `CUSTOM(name="moldy.stale")` |

## Frontend Contract

Feature flag:

```dotenv
NEXT_PUBLIC_CHAT_STREAM_PROTOCOL=moldy_sse  # default
NEXT_PUBLIC_CHAT_STREAM_PROTOCOL=ag_ui
```

当 flag 为 `ag_ui` 时，`streamResumeAttach` 调用 `/ag-ui-stream`。接收到的 AG-UI event 通过 `agUiEventToMoldyEvents` 转成现有 Moldy `SSEEvent`。因此无需重写 `useChatRuntime` 的 rendering、artifact、interrupt、stale、usage、cancel handling。

P6 的范围是 durable attach/resume stream。Primary POST stream 本身迁移为 AG-UI request/response 放到单独 phase。

## Consequences

Positive:

- 即使开始 AG-UI 迁移，也原样复用 durable run lifecycle、取消、stale、replay、artifact finalization。
- AG-UI event id 与 Moldy source event id 的关系明确，因此可 trace/debug。
- feature flag off 时，现有 UI 行为完全相同。

Tradeoffs:

- 因不直接使用 AG-UI SDK，runtime schema validation 由自有测试保证。
- Primary POST stream 仍是 Moldy SSE。AG-UI flag 先从刷新/会话切换/网络重连 attach 路径验证。
- 对被 Live broker buffer 挤出的 AG-UI id，degrade 为按 source event 处理。DB replay 仍保持 AG-UI id 粒度精度。
- 如果连 source event 也超出 buffer，先 emit `stale(reason="broker_gap")` marker，再 replay buffer 剩余全部内容（与 Moldy `/stream` 相同 degrade）。此时若长 turn 中连 `message_start` 都已从 buffer evict，replay 可能没有 `TEXT_MESSAGE_START` — Moldy client 会无条件累积 `content_delta`，因此无影响；但标准 AG-UI client 可能丢弃没有 START 的 CONTENT。在把 AG-UI flag 暴露给标准 client 前，应评估在 gap 时注入合成 `TEXT_MESSAGE_START`。

## Verification

P6 gate:

- Backend adapter unit test：按 Moldy event 验证 AG-UI mapping 与 split-event resume。
- Backend router test: live broker `/ag-ui-stream`, terminal replay `/ag-ui-stream`.
- Frontend adapter unit test：把 AG-UI event 还原为现有 Moldy `SSEEvent`。
- Frontend stream attach unit test: `NEXT_PUBLIC_CHAT_STREAM_PROTOCOL` flag delegation.
- E2E：分别以 `moldy_sse` 与 `ag_ui` 两种 protocol 通过 chat run lifecycle spec。
