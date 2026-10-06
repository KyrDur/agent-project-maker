# Deep Agent 引擎全面替换规格书

## 概览

将 natural-mold(Moldy) 项目的 AI 智能体执行引擎从 `langchain.agents.create_agent` 替换为 `deepagents.create_deep_agent`。同时用 `langchain-mcp-adapters` 替代 MCP 直接实现，并将对话管理迁移到 LangGraph checkpointer。

## 目标

- [ ] create_agent → create_deep_agent 替换
- [ ] MCP 直接实现 → langchain-mcp-adapters 替换
- [ ] DB 消息管理 → LangGraph PostgresSaver checkpointer 替换
- [ ] skill 手动加载 → 通过 deep agent skills 参数自动加载
- [ ] 尽可能移除自研代码（利用标准 framework）
- [ ] 现有 DB 数据全部初始化（干净开始）

## 技术 stack 变更

| 项目 | Before | After |
|------|--------|-------|
| 智能体引擎 | `langchain.agents.create_agent` | `deepagents.create_deep_agent` |
| MCP client | httpx 直接实现 (`mcp_client.py`) | `langchain-mcp-adapters` |
| MCP→工具转换 | 手动包装 `create_mcp_tool()` | 自动转换 `load_mcp_tools()` |
| 对话状态 | DB messages 表 | LangGraph `PostgresSaver` |
| skill 加载 | 手动 `skill_tool_factory.py` | 自动 `create_deep_agent(skills=[...])` |
| skill 执行 | 手动 `skill_executor.py` | deep agent `FilesystemMiddleware` |
| memory | 无 | deep agent memory（基于 AGENTS.md 文件） |
| 自动摘要 | 无（可通过 middleware 选择） | deep agent 内置 `SummarizationMiddleware` |

## 决策事项（访谈结果）

| 项目 | 决策 |
|------|------|
| 对话存储 | 全面使用 Checkpointer。conversations 表仅保留 metadata(title, pinned)。移除 messages 表 |
| 自动追加工具 | 默认启用 + 通过 system prompt 控制不必要调用 |
| token 追踪 | 改为按 conversation(thread) 单位。移除 message_id FK |
| trigger/scheduler | 保留 APScheduler。仅将 trigger_executor.py 改为 deep agent invoke() |
| memory 存储 | 文件基础 (data/agents/{agent_id}/AGENTS.md)。deep agent 默认方式 |
| UI 设置 | 最少化。deep agent 功能由 backend 自动处理。保留现有 middleware 设置 UI |
| Creation agent | 替换为 deep agent |
| Checkpointer DB | 与当前 PostgreSQL 同一实例 |
| Builtin/prebuilt 工具 | 保留 tool_factory.py。仅移除 MCP 代码 |
| 实现顺序 | 分阶段验证 (M1→M2→M3→M4) |

## 详细要求

### 功能性要求

#### FR-1: 替换 create_deep_agent 引擎
- 将 `executor.py` 的 `build_agent()` 函数替换为 `create_deep_agent()`
- 返回类型相同 (CompiledStateGraph) → 无需修改 `astream()` 调用
- 原有 middleware 参数原样传递（兼容 langchain 官方22种）
- 移除 `create_react_agent` fallback 逻辑

#### FR-2: 引入 langchain-mcp-adapters
- 将 MCP 工具创建替换为 `load_mcp_tools()` 或 `MultiServerMCPClient`
- 工具名称、description、parameters_schema 按 MCP 服务器原始值传递
- 将 auth_config 转换为 HTTP headers 后传递
- 仅筛选连接到智能体的特定工具（按 tool_name）

#### FR-3: 基于 Checkpointer 的对话管理
- 使用 `PostgresSaver` 作为 checkpointer（当前 PostgreSQL 实例）
- 使用 conversation_id 作为 thread_id
- 修改 frontend 获取消息的 API:
  - 当前: `GET /api/conversations/{id}/messages` → DB query
  - 修改后: 从 checkpointer 获取 state 并提取 messages
- conversations 表: 仅保留 title, is_pinned, agent_id 等 metadata
- messages 表: 移除

#### FR-4: skill 自动加载
- 通过 `create_deep_agent(skills=[skill_dir1, skill_dir2, ...])` 参数传递
- 从 DB 的 agent_skills 收集 skill.storage_path 列表后传递
- 移除 skill_tool_factory.py, skill_executor.py
- SKILL.md 的 progressive disclosure 由 deep agent 自动处理

#### FR-5: memory（长期记忆）
- 每个智能体基于 `data/agents/{agent_id}/AGENTS.md` 文件
- 通过 deep agent 的 memory 参数传递
- 智能体自动记住跨对话学习内容

#### FR-6: 自动添加工具管理
- deep agent 自动添加的工具: ls, read_file, write_file, edit_file, glob, grep, write_todos
- 所有智能体默认启用
- 在 system prompt 中包含工具指南，防止不必要调用
- LLMToolSelectorMiddleware 支持工具选择筛选

#### FR-7: token 使用量追踪
- 保留 token_usages 表
- message_id FK → 改为 conversation_id + 基于 timestamp
- 从 astream() 的 usage_metadata 实时提取

#### FR-8: trigger 联动
- 保留 APScheduler
- 在 trigger_executor.py 中改为调用 `create_deep_agent` → `invoke()`
- trigger 执行结果也自动保存到 checkpointer

#### FR-9: 替换 Creation Agent
- 将 creation_agent.py 改为基于 create_deep_agent
- 统一引擎

### 非功能性要求

#### NFR-1: 性能
- MCP 工具加载: 通过 session 复用最小化连接开销
- checkpointer: 使用 PostgreSQL async 连接
- 自动摘要: context window 达到85%时自动压缩

#### NFR-2: 兼容性
- frontend: 保持 SSE event 格式(message_start, content_delta, tool_call_start, tool_call_result, message_end)
- REST API: 保持 endpoint 结构 (/api/agents/*, /api/conversations/*)
- middleware: 原样使用 langchain 官方22种

#### NFR-3: 安全
- 保持 MCP auth_config 加密（现有 ENCRYPTION_KEY）
- deep agent FilesystemMiddleware: 限制只能访问 skill 目录
- execute 工具: 仅允许执行 skill script（sandbox 限制）

## DB schema 变更

### 保留的表
- users
- models
- templates
- mcp_servers
- tools
- agents（保持 middleware_configs, model_params 结构）
- agent_tools（包含 config JSON）
- skills
- agent_skills
- agent_triggers
- agent_creation_sessions

### 修改的表

#### token_usages — FK 变更
```sql
-- Before
message_id UUID FK → messages.id

-- After
conversation_id UUID FK → conversations.id  (移除 message_id)
```

### 移除的表
- messages（由 checkpointer 替代）

### 自动创建的表 (PostgresSaver)
- checkpoint（由 LangGraph 自动创建）
- checkpoint_blobs
- checkpoint_writes

## 移除的代码

| 文件 | 移除对象 | 原因 |
|------|---------|------|
| `tool_factory.py` | `create_mcp_tool()`, `_build_args_schema()` | 由 langchain-mcp-adapters 替代 |
| `mcp_client.py` | `call_mcp_tool()` | adapter 负责工具执行 |
| `skill_tool_factory.py` | 整个文件 | create_deep_agent 负责 skill 加载 |
| `skill_executor.py` | 整个文件 | 由 deep agent FilesystemMiddleware 替代 |
| `chat_service.py` | `build_effective_prompt()` skill 注入部分, MCP 名称处理, 重复检测 | 由 deep agent/adapter 处理 |
| `chat_service.py` | `save_message()`, `list_messages()` | 由 checkpointer 替代 |
| `streaming.py` | middleware JSON filter（可选） | 切换到 deep agent 后测试再判断 |
| `middleware_registry.py` | `PatchedLLMToolSelectorMiddleware`（可选） | 切换到 deep agent 后测试再判断 |
| `executor.py` | `create_react_agent` fallback 逻辑 | 始终使用 create_deep_agent |

## 保留的代码

| 文件 | 保留对象 | 原因 |
|------|---------|------|
| `mcp_client.py` | `test_mcp_connection()`, `list_mcp_tools()` | MCP 服务器注册 UI 使用 |
| `tool_factory.py` | builtin/prebuilt/custom 工具创建 | 基于 Python 代码，无法由 MCP 替代 |
| `model_factory.py` | 全部 | 模型创建方式相同 |
| `message_utils.py` | 全部 | 用于转换从 checkpointer 获取的消息 |
| `streaming.py` | SSE 转换逻辑 | astream() API 相同，保持 SSE 格式 |
| `middleware_registry.py` | middleware registry, build_middleware_instances | 作为 deep agent middleware 参数传递 |

## API 变更

### 无变更
- `GET /api/agents` — 智能体列表
- `POST /api/agents` — 创建智能体
- `GET /api/agents/{id}` — 智能体详情
- `PUT /api/agents/{id}` — 修改智能体
- `GET /api/agents/{id}/conversations` — 对话列表
- `POST /api/agents/{id}/conversations` — 创建对话
- `POST /api/conversations/{id}/messages` — 发送消息 (SSE streaming)
- `PATCH /api/conversations/{id}` — 修改对话
- `DELETE /api/conversations/{id}` — 删除对话
- 全部工具相关 API

### 仅修改内部实现
- `GET /api/conversations/{id}/messages` — DB query → 从 checkpointer 提取 state
- `POST /api/conversations/{id}/messages` — execute_agent_stream() → deep agent astream()

## Milestone

### M1: 依赖 + 引擎替换（基础）
- [ ] `uv add deepagents langchain-mcp-adapters`
- [ ] `executor.py`: `build_agent()` → 替换为 `create_deep_agent()`
- [ ] `executor.py`: 将 MCP 工具创建替换为 `langchain-mcp-adapters`
- [ ] `tool_factory.py`: 移除 `create_mcp_tool()`, `_build_args_schema()`
- [ ] `mcp_client.py`: 移除 `call_mcp_tool()`
- [ ] `chat_service.py`: 移除 MCP 名称加工/重复检测逻辑
- [ ] 验证: 测试现有智能体能否正常调用 MCP 工具
- [ ] 验证: 测试 builtin/prebuilt 工具是否正常运行

### M2: Checkpointer 迁移
- [ ] 设置 `PostgresSaver`（复用当前 PostgreSQL 连接）
- [ ] 传递 `create_deep_agent(checkpointer=saver)`
- [ ] `conversations.py`: 将消息查询 API 改为从 checkpointer 提取 state
- [ ] `conversations.py`: 从消息发送 API 移除手动 save_message()
- [ ] `chat_service.py`: 移除 `save_message()`, `list_messages()` 或替换为 checkpointer wrapper
- [ ] DB 迁移: 移除 messages 表, 修改 token_usages FK
- [ ] 验证: 测试创建对话 → 发送消息 → 查询 history 全流程

### M3: skill + memory 迁移
- [ ] 通过 `create_deep_agent(skills=[...])` 参数传递 skill 目录
- [ ] 移除 `skill_tool_factory.py`, `skill_executor.py`
- [ ] `chat_service.py`: 从 `build_effective_prompt()` 移除 skill 注入逻辑
- [ ] 通过 `create_deep_agent(memory=[...])` 参数传递 memory 路径
- [ ] 设置 `data/agents/{agent_id}/` 目录结构
- [ ] 验证: "李尚允的座位在哪里？" → 自动加载 skill → 执行 mark_seat.py + 图像

### M4: 整理 + Creation Agent
- [ ] 将 `creation_agent.py` 替换为基于 create_deep_agent
- [ ] 将 `trigger_executor.py` 替换为 deep agent invoke()
- [ ] 最终整理不必要的代码/文件
- [ ] 测试后判断 streaming.py middleware filter 是否仍需要
- [ ] 测试后判断 middleware_registry.py patch 是否仍需要
- [ ] 全量 E2E 测试
- [ ] 整理 DB seed 数据

## 开放问题 / 需要决策

1. **deep agent 的 FilesystemMiddleware 如何限制 skill 目录** — 出于安全必须阻止访问整个文件系统。需要查看实际代码确认是否可通过 backend 设置控制。

2. **streaming.py 的 middleware JSON filter 在 deep agent 中是否仍需要** — create_deep_agent 包含内置 PatchToolCallsMiddleware，因此现有 content leak 问题可能已解决。M4 测试。

3. **auto-added SummarizationMiddleware 与用户设置 summarization 重复** — 如果用户在智能体设置中单独启用 summarization middleware，则会与 deep agent 内置功能双重应用。需要防重复逻辑。

4. **从 checkpointer 获取消息的准确 API** — 需要确认通过 `PostgresSaver.aget_tuple(config)` 等获取 state 并提取 `state["messages"]` 的准确实现。

---

> 规格书已完成。请在新 session 中使用以下命令开始实现:
> ```
> 读取 SPEC.md 并开始实现
> ```
>
> 实现完成后验证:
> ```
> /spec-verify
> ```
