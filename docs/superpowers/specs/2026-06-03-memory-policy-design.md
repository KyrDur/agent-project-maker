# Memory Policy and UX Design

编写日期：2026-06-03
更新：2026-06-04
项目：Moldy
状态：Partially Implemented Draft

## 0. 分析基准

本文档以 2026-06-04 当前 worktree
`/Users/chester/.codex/worktrees/3ed7/natural-mold` 的源代码为基准重新
分析并更新。

在 2026-06-04 19 时段实现 pass 之后，本文档以包含该 worktree 未提交更改
的状态为基准。不过，指定的文档文件本身位于
`/Users/chester/dev/ref/natural-mold` checkout。

应用的 LangChain/Deep Agents skill：

- `framework-selection`：Moldy 的长时任务、文件、skill、持久 memory 需求
  更适合 Deep Agents 层，而不是单个 LangChain agent。
- `deep-agents-memory`：长期 memory 需要显式设计 `StateBackend`/`StoreBackend`/
  `CompositeBackend` 和 `store=` 实例。

已确认的本地 runtime：

- `deepagents==0.6.1`
- `create_deep_agent()` 支持 `memory`, `permissions`, `backend`, `store`,
  `subagents`, `checkpointer` 参数。
- `deepagents.backends` 中有 `FilesystemBackend`, `StateBackend`,
  `StoreBackend`, `CompositeBackend`。
- `langgraph.store.postgres` 中有 `PostgresStore`, `AsyncPostgresStore`。

## 1. 背景

Moldy 当前通过 LangGraph `AsyncPostgresSaver` checkpointer 维护 conversation/thread
短期状态。同时向 Deep Agents `memory` 选项传入
`/agents/{agent_id}/AGENTS.md`，已有读取 agent 级文件 memory 的最小
连接。

但当前实现仍不是产品功能意义上的长期 memory。

- 没有 user 级长期 memory。
- 还没有基于 `StoreBackend`/`CompositeBackend`/LangGraph Store 的 memory。
- `build_agent()` 可以接收 `store`，但实际 chat/trigger callsite
  没有传入 `store=`。
- 会创建 `AGENTS.md` 目录，但不创建文件本身。
- 保存依赖 Deep Agents built-in `write_file`/`edit_file` 直接
  修改 `/agents/{agent_id}/AGENTS.md`。
- 没有 memory proposal、approval、audit、settings、management UI。
- 即使同一 conversation 中 memory 文件发生更改，如果 Deep Agents
  `MemoryMiddleware` 的 checkpoint state 已有 `memory_contents`，
  也可能不会重新读取。

因此要把 memory 能力明确为产品功能，让用户可以控制读/写/批准策略与
保存范围。

## 2. 当前源代码状态

| 区域 | 当前状态 | 依据/含义 |
| --- | --- | --- |
| Thread memory | 已实现 | `backend/app/agent_runtime/checkpointer.py` 初始化 `AsyncPostgresSaver` singleton，并使用 conversation id 作为 `thread_id`。 |
| User profile context | 部分实现 | `backend/app/routers/conversations.py` 的 `_with_user_display_name_context()` 将 `display_name` 注入 system prompt。这是 profile context，并非长期 memory 存储。 |
| Agent file memory | 最小实现 | `executor.py` 将 `memory_sources = ["/agents/{agent_id}/AGENTS.md"]` 传给 `create_deep_agent()`。 |
| User memory | 第 1 阶段已实现 | `memory_records` 保存 user scope，并在 `/api/memories` 和设置 UI 中管理。还不是 LangGraph Store-backed memory。 |
| Store-backed memory | 无 | 没有使用 `StoreBackend`, `CompositeBackend`, `PostgresStore`。 |
| Filesystem backend | 已实现 | 使用 `FilesystemBackend(root_dir=backend/data, virtual_mode=True)`。 |
| Filesystem permissions | 实现进行中 | `build_filesystem_permissions()` 只 allow 当前 runtime skill、当前 conversation output、自身 agent `AGENTS.md`，并 deny `/skills`, `/agents`, `/runtime`, `/conversations` tree。 |
| Skills mount | 已改进 | 不再使用 broad `/skills/`，改为 `/runtime/{thread_id}/skills/` per-thread copy。 |
| Memory write approval | 第 1 阶段已实现 | `propose_memory`, `save_user_memory`, `save_agent_memory` 应用 effective policy，并在 ask mode 下创建 `memory_proposals`。有批准/拒绝/修改后批准 API 和 card UI。 |
| Trigger mode | 已实现策略边界 | memory tool 在 `is_trigger_mode` 下使用 `trigger_memory_write_policy`。trigger write 默认值为 off，独立 trigger E2E 是后续验证项。 |
| SSE trace | 已实现 | 将 memory tool 结果转换为 `memory_proposed`, `memory_saved`, `memory_rejected`, `memory_deleted` SSE event。 |
| Memory API/UI | 第 1 阶段已实现 | 已有 `/api/memories`, `/api/me/memory-settings`, `/api/agents/{agent_id}/memory-settings`, `/api/memory-proposals/*` 和设置/聊天 card UI。 |
| Sub-agent runtime | 独立问题 | DB/UI 和 `build_agent(subagents=...)` forwarding 已有，但当前 `_resolve_agent_context()` 与 trigger 路径没有填充 `subagents_config`。与 memory 设计的直接范围不同，但判断 runtime 状态时需注意。 |

### 2.1 2026-06-04 实现反映摘要

本次实现 pass 没有立即引入 LangChain/Deep Agents 推荐结构中的 Store-backed runtime，
而是先用 DB-backed record/proposal 模型建立产品策略与 UX。
这个选择与当前 Moldy 的 Router -> Service -> Model 模式、多用户 ownership、
CSRF/JWT 认证、SSE 事件结构最匹配。

已实现的第 1 阶段范围：

- DB 模型/迁移：`user_memory_settings`, `agent_memory_settings`,
  `memory_records`, `memory_proposals`
- API: user/agent memory settings, memory CRUD, proposal create/get/approve/
  edit-and-approve/reject
- Runtime: memory prompt injection, policy-bound memory tools, explicit memory tool
  instruction prompt, trigger write policy gate
- Streaming: memory tool result -> dedicated memory SSE event
- UI：Settings > Memory 页面、agent settings memory override、chat memory proposal/
  saved/rejected card, approve/reject/edit-and-approve actions
- UX hardening：重新进入已处理 proposal 时按服务器 status 恢复，
  即使 runtime 不支持 `addResult`，也避免成功 action 被误判为失败 toast

仍然缺少的推荐结构：

- 基于 `StoreBackend`/`CompositeBackend`/`AsyncPostgresStore` 的长期 memory route
- 将 DB record materialize 为 Store markdown view 的同步层
- 现有 `/agents/{agent_id}/AGENTS.md` legacy memory migration
- trigger memory write E2E 与 proposal 过期/cleanup

## 3. 目标

1. 用户必须能够开启或关闭 memory 功能。
2. 用户必须能够选择长期 memory 保存时是否需要批准。
3. 默认策略安全地设为 `开启读取 + 保存前确认`。
4. 提供账户全局默认值，并允许按 Agent override。
5. memory 被保存或提出时，必须在聊天 UI 中明确显示。
6. 必须区分 user memory 和 agent memory。
7. 长期 memory 按 Deep Agents 推荐结构迁移到 `StoreBackend` 或
   DB-backed Store。
8. trigger/schedule 执行中考虑缺少交互式批准者，设置独立 write policy。

## 4. 非目标

第 1 阶段范围排除以下内容。

- 基于向量搜索的 semantic memory
- 自动 memory consolidation/background summarizer
- 组织/团队级 shared memory
- 与其他用户共享 memory
- 基于 memory 的推荐/个性化 dashboard
- 解决 sub-agent runtime wiring 本身

这些事项在基于 Store 的 memory foundation 稳定后作为后续功能处理。

## 5. Memory 区分

Moldy 按生命周期和访问范围区分 memory。

| 名称 | 范围 | 生命周期 | 示例 | 当前/目标存储方式 |
| --- | --- | --- | --- | --- |
| Thread memory | 单个 conversation | 该 thread | 本次对话中分析的临时上下文 | 当前：LangGraph checkpointer |
| User profile context | 用户 profile | 长期 | display name、avatar 设置 | 当前：`users` columns。与 memory 分离 |
| User memory | 用户全局 | 长期 | “我的名字是李尚允”“偏好中文回答” | 目标：LangGraph Store + DB metadata |
| Agent memory | 特定 agent | 长期 | “这个研究 Agent 先输出表格” | 当前：`/agents/{agent_id}/AGENTS.md`；目标：Store + DB metadata |

短期/长期的标准是“是否跨越 conversation/thread 持续保留”。
user/agent 的标准是“谁可以读取该 memory”。

## 6. 策略模型

### 6.1 策略优先级

Memory 策略按以下顺序决定。

```text
system default
  -> user default
    -> agent override
      -> run mode 限制(chat | trigger)
```

agent override 不能获得比 user default 更宽的权限。例如用户将
memory write 设置为 `off` 时，agent 不能以 `auto` 保存。

### 6.2 系统默认值

推荐默认值：

```text
memory_read_enabled = true
memory_write_policy = ask
allowed_scopes = both
trigger_memory_write_policy = off
```

聊天中读取已保存的 memory，但保存新的长期 memory 时询问用户。
trigger 没有交互式批准者，因此默认关闭 write。

### 6.3 用户默认设置

账户设置中提供以下选项。

```text
memory_enabled: boolean
memory_read_enabled: boolean
memory_write_policy: off | ask | auto
allowed_scopes: user | agent | both
trigger_memory_write_policy: off | auto
```

含义：

- `off`：不可保存新 memory
- `ask`：保存前需要用户批准
- `auto`：无需用户批准即可保存，但显示保存完成 UI

`trigger_memory_write_policy` 有意不提供 `ask`。schedule run 中没有
可立即回应的用户。后续如果建立 async approval inbox，
可以增加 `propose` 状态。

### 6.4 按 Agent override

Agent 设置中提供以下选项。

```text
memory_policy_override: inherit | off | ask | auto
memory_scopes_override: inherit | agent_only | user_and_agent
trigger_memory_policy_override: inherit | off | auto
```

示例:

- 普通业务 Agent：继承账户默认值
- 个人助理 Agent：聊天中自动保存
- 实验 Agent：关闭 memory
- 拥有较多 external mutation tool 的 Agent：保存前确认
- schedule Agent：trigger write off

## 7. 保存范围判断

LLM 在第 1 阶段提出 memory scope，由服务器验证策略与权限。

推荐分类：

| 输入 | 推荐 scope |
| --- | --- |
| “我的名字是李尚允” | user |
| “我偏好用中文简短回答” | user |
| “这个研究 Agent 先把搜索结果整理成表格” | agent |
| “这次对话只需要看 A 文件” | thread，不长期保存 |

重要原则：

- LangChain/Deep Agents 不会自动完美判断是 user memory 还是 agent memory。
- Moldy 必须通过 tool schema、prompt、server validation 明确 scope。
- 不允许 LLM 直接选择 `user_id`, `agent_id`, namespace。
- ask mode 下，批准 card 中应显示 scope，并允许用户修改。

## 8. Runtime 结构

### 8.1 当前结构

```text
AsyncPostgresSaver
  -> conversation/thread state

FilesystemBackend(root_dir=backend/data, virtual_mode=True)
  /runtime/{thread_id}/skills/
    -> 连接到当前 agent 的 skill copy
  /conversations/{thread_id}/
    -> runtime output
  /agents/{agent_id}/AGENTS.md
    -> 当前 agent file memory

FilesystemPermission
  allow read: selected /runtime/{thread_id}/skills/{slug}
  allow read/write: /conversations/{thread_id}
  allow read/write: /agents/{agent_id}/AGENTS.md
  deny read/write: /skills, /agents, /runtime, /conversations protected trees
```

当前结构的优点是已具备文件权限隔离。缺点是长期 memory
仍然只有一个文件，没有 Store namespace、audit、approval、user memory。

### 8.2 目标结构

```text
AsyncPostgresSaver
  -> thread/conversation state

DB-backed LangGraph Store
  -> long-term user/agent memory files

CompositeBackend
  default: StateBackend
    -> 临时工作文件

  /memories/user/
    -> StoreBackend namespace=("users", user_id, "memory")

  /memories/agent/
    -> StoreBackend namespace=("users", user_id, "agents", agent_id, "memory")

  /runtime/{thread_id}/skills/
    -> FilesystemBackend 或现有 materialized runtime route

  /conversations/{thread_id}/
    -> FilesystemBackend 或 artifact storage route
```

长期 memory 从直接把 `AGENTS.md` 文件存入 data directory 的方式
迁移为基于 LangGraph Store/PostgresStore。

### 8.3 Deep Agents integration

`StoreBackend` 需要 Store 实例。因此在 app lifespan 中
初始化 DB-backed Store singleton，并在 agent build 时把 `store=` 与
`CompositeBackend` 一起传入。

示例结构：

```python
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend


def build_memory_backend(*, user_id: str, agent_id: str, thread_id: str):
    return lambda runtime: CompositeBackend(
        default=StateBackend(runtime),
        routes={
            "/memories/user/": StoreBackend(
                store=postgres_store,
                namespace=lambda _rt: ("users", user_id, "memory"),
            ),
            "/memories/agent/": StoreBackend(
                store=postgres_store,
                namespace=lambda _rt: ("users", user_id, "agents", agent_id, "memory"),
            ),
        },
        artifacts_root=f"/conversations/{thread_id}/",
    )
```

向 `create_deep_agent()` 传入以下内容。

```python
create_deep_agent(
    ...,
    backend=build_memory_backend(...),
    store=postgres_store,
    memory=[
        "/memories/user/profile.md",
        "/memories/agent/AGENTS.md",
    ],
)
```

但 memory 保存不能只交给 LLM 的 raw `edit_file` 调用。应用应提供可追踪的
专用 memory tool。

### 8.4 MemoryMiddleware reload 注意事项

Deep Agents `MemoryMiddleware` 如果 state 中已有 `memory_contents`，则 source
不会重新读取。若同一 conversation 中发生 memory save/delete 后，希望紧接着的下一个
turn 能看到最新 memory，需要以下方案之一。

- memory 保存/删除时，使当前 thread checkpoint 的 `memory_contents` invalidate。
- 在 memory content 中加入 version key，并更新 middleware state。
- 不使用 Deep Agents `memory` 选项，改由 Moldy custom middleware 每个 turn 从 DB/Store
  读取 fresh memory view 并注入 system prompt。

第 1 阶段实现不应限制为“批准保存后从下一个新 conversation 起生效”，
建议测试到同一 conversation 的下一个 turn 也会生效。

## 9. Memory Tools

### 9.1 专用 tool

添加以下 tool。

```text
propose_memory
save_user_memory
save_agent_memory
list_memories
delete_memory
```

第 1 阶段实现优先 `propose_memory`, `save_user_memory`, `save_agent_memory`。

### 9.2 Tool 调用策略

LLM 发现值得记忆的信息时，调用以下之一。

```text
propose_memory(scope, content, reason)
save_user_memory(content, reason)
save_agent_memory(content, reason)
```

服务器计算 effective policy。

```text
off:
  不保存，并通过 tool result 返回拒绝原因

ask:
  不立即保存，生成 memory_proposed event

auto:
  立即保存并生成 memory_saved event
```

即使调用 `save_*` tool，只要服务器策略是 `ask`，也不保存，而是 degrade 为 proposal。
必须防止 LLM 通过 tool 名称绕过策略。

### 9.3 SSE 事件连接

当前 `streaming.py` 将 tool call/result emit 为 SSE，并向 `message_events` 做 partial
flush/finalize。memory tool 结果也复用这条路径。

推荐实现：

1. memory tool 向 DB 写入 `memory_proposals` 或 `memory_records` row。
2. tool result 返回 structured JSON 字符串或 typed payload。
3. `streaming.py` 检测 memory tool 的 result，额外 emit `memory_proposed`,
   额外 emit `memory_saved`、`memory_rejected` 等 dedicated SSE event。
4. 现有 `tool_call_result` 保留用于 debug/trace，或在 UI 中隐藏。

这样 live stream、resume replay、share/debug trace 都能复用相同的
`message_events` 基础。

## 10. UI/UX

### 10.1 聊天 UI：保存前确认

`ask` mode 下，在聊天时间线显示批准 card。

```text
要把这段内容保存到用户记忆吗？
“用户的名字是李尚允”

[保存] [修改] [取消]
```

agent memory 时：

```text
要把这段内容保存到此 Agent 的记忆吗？
“这个 Agent 在撰写报告时先生成表格”

[保存] [修改] [取消]
```

批准 card 中显示 scope、reason、source conversation。用户在保存前
必须能够修改 scope 和 content。

### 10.2 聊天 UI：自动保存

`auto` mode 下，保存后显示小型 system card 或 toast。

```text
已保存到记忆
“用户的名字是李尚允”
```

### 10.3 设置 UI

账户设置 > 记忆：

```text
使用记忆
读取已保存的记忆
新记忆保存方式：不保存 / 保存前确认 / 自动保存
允许保存的范围：用户记忆 / Agent 记忆 / 两者
schedule 执行期间保存：不保存 / 自动保存
```

Agent 设置 > 记忆：

```text
使用账户默认值
仅关闭此 Agent 的记忆
此 Agent 保存前确认
此 Agent 自动保存
限制保存范围：仅 Agent 记忆 / 用户+Agent 记忆
schedule 执行期间的保存策略
```

记忆管理页面：

```text
用户记忆列表
按 Agent 查看记忆列表
搜索
修改
删除
```

第 1 阶段范围中，搜索使用简单文本过滤即可。

## 11. API 设计

### 11.1 User memory settings

```text
GET /api/me/memory-settings
PATCH /api/me/memory-settings
```

### 11.2 Agent memory settings

```text
GET /api/agents/{agent_id}/memory-settings
PATCH /api/agents/{agent_id}/memory-settings
```

### 11.3 Memory CRUD

```text
GET /api/memories?scope=user
GET /api/agents/{agent_id}/memories
PATCH /api/memories/{memory_id}
DELETE /api/memories/{memory_id}
```

所有 endpoint 必须通过 `get_current_user` 和 ownership guard。
按照项目既有规则，对“不存在”和“无权限”统一外部响应。

### 11.4 Memory proposal action

```text
POST /api/memory-proposals/{proposal_id}/approve
POST /api/memory-proposals/{proposal_id}/reject
POST /api/memory-proposals/{proposal_id}/edit-and-approve
```

write endpoint 与 ADR-016 一样应用 CSRF 验证。

## 12. SSE Events

在聊天 stream 中添加以下 event。

```text
memory_proposed
memory_saved
memory_rejected
memory_deleted
```

示例 payload：

```json
{
  "id": "proposal-id",
  "scope": "user",
  "content": "用户的名字是李尚允",
  "reason": "用户明确要求记住该信息",
  "policy": "ask",
  "conversation_id": "conversation-id",
  "agent_id": "agent-id"
}
```

在 `backend/app/agent_runtime/event_names.py` 中添加常量，并在 frontend SSE type 中
添加相同名称。

## 13. 数据模型

### 13.1 user_memory_settings

用户默认设置推荐使用独立表。M55 的 `users.display_name`/avatar
columns 与 memory policy 性质不同。

```text
user_memory_settings
  user_id pk/fk users.id
  memory_enabled
  memory_read_enabled
  memory_write_policy: off | ask | auto
  allowed_scopes: user | agent | both
  trigger_memory_write_policy: off | auto
  created_at
  updated_at
```

### 13.2 agent_memory_settings

```text
agent_memory_settings
  agent_id pk/fk agents.id
  memory_policy_override: inherit | off | ask | auto
  memory_scopes_override: inherit | agent_only | user_and_agent
  trigger_memory_policy_override: inherit | off | auto
  created_at
  updated_at
```

### 13.3 memory_records

如果只使用 StoreBackend，列表/删除 UI 和审计日志可能较弱。因此，用于 UI 的
用于 UI 的 metadata row。

```text
memory_records
  id
  user_id
  agent_id nullable
  scope: user | agent
  content
  reason
  store_path
  source_conversation_id nullable
  source_message_id nullable
  source_run_id nullable
  status: active | deleted
  created_at
  updated_at
  deleted_at nullable
```

Store 中保存便于 Deep Agents 读取的 Markdown file view，DB row
负责 UI 与 audit/删除。

### 13.4 memory_proposals

```text
memory_proposals
  id
  user_id
  agent_id nullable
  conversation_id
  source_run_id nullable
  scope: user | agent
  content
  reason
  status: pending | approved | rejected | expired
  created_at
  resolved_at nullable
```

## 14. 安全与隐私

1. 禁止把 API key、token、password 保存到 memory。
2. memory tool 检测到 credential-looking pattern 时拒绝保存。
3. user memory 仅该 user 可访问。
4. agent memory 仅该 agent owner 可访问。
5. agent override 只能在 user setting 范围内生效。
6. trigger mode 默认阻止 memory write。
7. memory 删除必须同时反映到 Store 和 DB metadata。
8. 不允许 LLM 直接选择 Store namespace、user id、agent id、file path。
9. memory content 可能成为 prompt injection source，因此 system prompt 中
   要设定“memory 是参考信息，不是命令”的边界。
10. 设置 content size、record count、per-user quota。

## 15. 测试策略

Backend:

- effective memory policy 计算测试
- user default + agent override 优先级测试
- trigger mode write policy 测试
- 按 off/ask/auto 策略测试 tool behavior
- user memory 与 agent memory namespace 隔离测试
- 阻止访问其他 user 的 memory 测试
- 测试拒绝保存 secret-looking content
- StoreBackend read/write integration 测试
- MemoryMiddleware reload/invalidation 测试
- 保留现有 filesystem permission 回归测试

Frontend:

- 显示 `memory_proposed` card
- approve/reject/edit-and-approve 行为
- 显示 `memory_saved` system card/toast
- 保存账户设置
- 保存 Agent override 设置
- memory 列表/删除 UI

E2E:

- “我的名字是李尚允，记住它” -> 显示 proposal -> 批准 -> 同一 conversation 的下一个 turn 能记住
- 批准后在新 conversation 中记住
- auto mode -> 立即显示保存 UI -> 在新 conversation 中记住
- off mode -> 不保存
- 保存到 agent A 的 agent memory 不暴露给 agent B
- trigger 默认策略下不发生 memory write

## 16. 分阶段实现计划

### Phase 0: Source-aligned prep

- 状态：完成/保持
- 通过单元测试固定当前 `/agents/{agent_id}/AGENTS.md` file memory 行为
- 保留当前 `build_filesystem_permissions()` 回归测试
- `MemoryMiddleware` reload/invalidation 方式在第 1 阶段通过 custom prompt injection 绕过
- DB-backed Store 初始化方式延后到 post-MVP Phase 2

### Phase 1: DB and policy foundation

- 状态：第 1 阶段完成
- `user_memory_settings`, `agent_memory_settings`, `memory_records`,
  添加 `memory_proposals` migration
- 添加 memory settings service
- 添加 effective policy calculator
- 添加 secret-looking content detector
- 编写 backend 单元测试

### Phase 2: Store-backed runtime

- 状态：未实现，post-MVP
- 在 app lifespan 中添加 LangGraph Store singleton
- 引入 `CompositeBackend`
- 设计 user/agent memory Store namespace
- 在 `AgentConfig` 中添加 memory policy/runtime context
- 按 `/memories/*` 扩展 `build_filesystem_permissions()`
- trigger mode 下应用 memory write deny 或 policy-bound allow

### Phase 3: Memory tools and SSE

- 状态：第 1 阶段完成
- 添加 `propose_memory`, `save_user_memory`, `save_agent_memory` tool
- 应用 off/ask/auto 策略
- 添加 `memory_proposed`, `memory_saved`, `memory_rejected`, `memory_deleted` SSE event
- 添加 proposal approve/reject/edit-and-approve API

### Phase 4: Chat UI

- 状态：第 1 阶段完成
- 添加 memory proposal card
- 添加 memory saved card/toast
- 连接批准/修改/取消 action
- 验证 resume/replay 时恢复 memory event

### Phase 5: Settings and management UI

- 状态：第 1 阶段完成
- 账户 memory 设置 UI
- Agent memory override UI
- memory 列表/修改/删除 UI

### Phase 6: Migration and cleanup

- 状态：未实现
- 将现有 `/agents/{agent_id}/AGENTS.md` 文件 migration 到 Store/DB row
- migration 期间将 legacy file memory 限制为 read-only fallback
- agent/user 删除时 cleanup memory
- 移除现有 file-based memory write path，或限制为 policy-bound

## 17. 工作量估算

最小实现：

```text
DB settings + policy + memory tool + SSE + 基础 Store integration + 测试
约 1.5-2 周
```

产品质量实现：

```text
上述内容 + 聊天 UI + 设置 UI + memory 管理 UI + E2E + migration
约 3 周
```

推荐第 1 阶段发布范围：

```text
memory read 默认开启
memory write 默认 ask
trigger write 默认 off
user default + agent override
user memory + agent memory
proposal card
saved card/toast
memory 列表/删除
```

## 18. 待决事项

1. 需要决定 memory 保存 content 是保持 Markdown file 形式，还是按 record 单位 JSON
   构建。
   - 推荐：DB 按 record 单位，Store materialize 为便于 Deep Agents 读取的 Markdown view。
2. 需要决定如何让同一 conversation 中保存的 memory 立即被再次读取。
   - 推荐：先编写 memory save/delete 后 `memory_contents` state invalidation 测试。
3. 需要决定 agent override 是否可以拥有比 user default 更强的权限。
   - 推荐：user default 是上限。user 为 off 时 agent 也不可保存。
4. 需要决定是否设置 memory proposal 过期时间。
   - 推荐：24 小时后 expired。
5. 需要决定 auto save mode 下检测到敏感信息时是否 degrade 为 ask。
   - 推荐：怀疑为敏感信息时拒绝保存或 degrade 为 ask。
6. 需要决定 trigger run 中是完全禁止 memory write，还是允许 explicit opt-in auto。
   决定。
   - 推荐：第 1 阶段 off，第 2 阶段 explicit opt-in。

## 19. 最终推荐方案

Moldy 的 memory 功能按以下原则实现。

```text
默认值保持安全：
  chat 开启读取 + 保存前确认
  trigger 开启读取 + 关闭保存

策略保持灵活：
  用户默认值 + 按 Agent override
  但用户设置是上限

保存要明确：
  使用 memory 专用 tool，而不是 LLM 的 raw edit_file

展示要透明：
  在聊天 UI 中暴露 proposed/saved/rejected/deleted event

存储采用推荐结构：
  short-term 使用 AsyncPostgresSaver checkpointer
  long-term 使用 StoreBackend/PostgresStore + DB metadata

隔离继续保持现有成果：
  在 Store/CompositeBackend 结构中继续应用现有 FilesystemPermission 隔离
```

该结构既支持 ChatGPT 式 memory UX，也能在多用户/多 Agent 环境中
清晰维持权限和保存范围。
