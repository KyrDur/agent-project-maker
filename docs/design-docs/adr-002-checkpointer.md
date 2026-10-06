# ADR-002：基于 Checkpointer 的对话管理

## 状态：已批准

## 背景

当前 Moldy 的对话消息保存在 `messages` table 中。每次请求都会：
1. 将用户消息保存到 DB（`save_message`）
2. 从 DB 查询完整 history（`list_messages`）
3. 转换为 LangChain message 并传给 agent
4. 将 agent 响应再次保存到 DB（`save_message`）

该方式的问题：
- **双重管理**：DB 与 agent 内部状态分离，可能出现不一致
- **每次请求都加载完整 history**：每次都从 DB 读取并转换 N 条 message
- **tool_calls 丢失**：`save_message` 只保存 assistant 响应的 `content`，导致 tool call history 丢失
- **LangGraph 功能受限**：没有 checkpointer 时无法使用 time-travel、state 恢复等高级功能

M1 已切换到 `create_deep_agent`，因此引入 LangGraph `AsyncPostgresSaver` checkpointer，将对话状态管理交给 framework。

---

## 决定

### 1. AsyncPostgresSaver 初始化 pattern

#### module 位置：`backend/app/agent_runtime/checkpointer.py`（新增）

以 module-level singleton 管理。在 `main.py` lifespan 中初始化/清理。

```python
# backend/app/agent_runtime/checkpointer.py

from __future__ import annotations

import logging
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


async def init_checkpointer(conn_string: str) -> None:
    """app 启动时初始化 checkpointer。由 lifespan 调用。"""
    global _pool, _checkpointer
    _pool = AsyncConnectionPool(conninfo=conn_string)
    await _pool.open()
    _checkpointer = AsyncPostgresSaver(conn=_pool)
    await _checkpointer.setup()  # 自动创建 checkpoint table
    logger.info("Checkpointer initialized (PostgreSQL)")


async def shutdown_checkpointer() -> None:
    """app 关闭时清理 connection pool。由 lifespan 调用。"""
    global _pool, _checkpointer
    if _pool:
        await _pool.close()
    _pool = None
    _checkpointer = None
    logger.info("Checkpointer shut down")


def get_checkpointer() -> AsyncPostgresSaver:
    """返回 checkpointer singleton。初始化前调用时抛出 RuntimeError。"""
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Call init_checkpointer() first.")
    return _checkpointer
```

#### 为什么使用 singleton

- `executor.py` 与 `trigger_executor.py` 都需要访问 checkpointer
- `trigger_executor.py` 在 APScheduler context 中执行，无法访问 `request.app.state`
- module-level singleton 最简单，也能为所有 caller 提供相同访问方式

#### lifespan 集成（main.py）

```python
from app.agent_runtime.checkpointer import init_checkpointer, shutdown_checkpointer

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ... 现有 seed 逻辑 ...

    # Checkpointer 初始化 —— 从 database_url 中移除 asyncpg driver prefix
    checkpointer_url = settings.database_url.replace("+asyncpg", "")
    await init_checkpointer(checkpointer_url)

    # ... 现有 scheduler 逻辑 ...
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    await shutdown_checkpointer()
```

#### Connection string 转换

| 用途 | 格式 | 示例 |
|------|------|------|
| SQLAlchemy async | `postgresql+asyncpg://` | `settings.database_url` |
| Alembic sync | `postgresql://` | `settings.database_url_sync` |
| **psycopg v3 (checkpointer)** | `postgresql://` | `settings.database_url.replace("+asyncpg", "")` |

从 `database_url` 中移除 `+asyncpg` 后派生。无需新增单独设置变量（DRY）。

#### 添加 dependency

```bash
uv add langgraph-checkpoint-postgres
# → 包含 psycopg[pool]（自动安装 psycopg_pool）
```

#### executor.py 接入

```python
# executor.py —— 调用 build_agent() 时传入 checkpointer
from app.agent_runtime.checkpointer import get_checkpointer

agent = build_agent(
    model,
    langchain_tools,
    system_prompt,
    middleware=middleware or None,
    checkpointer=get_checkpointer(),  # NEW
    name=f"agent_{thread_id[:8]}",
)
```

`build_agent()` 已支持 `checkpointer` 参数（M1 中新增，executor.py:34）。

---

### 2. message 转换逻辑

#### 核心 flow 变化

**Before (M1):**
```
POST /messages
  1. save_message(user)          → DB INSERT
  2. list_messages()             → DB SELECT（完整 history）
  3. convert_to_langchain_messages(full_history)
  4. agent.astream({messages: full_history})
  5. save_message(assistant)     → DB INSERT
```

**After (M2):**
```
POST /messages
  1. maybe_set_auto_title()      → DB UPDATE（条件式）
  2. agent.astream({messages: [new_user_msg]})
     → checkpointer 自动加载之前的 history
     → checkpointer 自动保存新 state（user + assistant）
  （不再调用 save_message）
```

**核心**：有 checkpointer 后，`messages_history` 只传入**新消息**，不再传完整 history。checkpointer 会自动恢复之前的 state，并自动保存新的 state。

#### message 查询：GET /conversations/{id}/messages

直接从 checkpointer 读取 state，并转换为 `MessageResponse` 格式。

```python
# message_utils.py —— 新增 function

from langchain_core.messages import (
    AIMessage, HumanMessage, ToolMessage, BaseMessage
)

_TYPE_TO_ROLE = {"human": "user", "ai": "assistant", "tool": "tool"}


def langchain_messages_to_response(
    messages: list[BaseMessage],
    conversation_id: uuid.UUID,
    base_timestamp: datetime | None = None,
) -> list[MessageResponse]:
    """将 LangChain BaseMessage list 转换为 MessageResponse list。

    Args:
        messages：从 checkpointer 提取的 message list
        conversation_id：对话 ID
        base_timestamp：基准 timestamp（如无则使用 conversation.created_at）
    """
    results = []
    base_ts = base_timestamp or datetime.utcnow()

    for idx, msg in enumerate(messages):
        role = _TYPE_TO_ROLE.get(msg.type, msg.type)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)

        results.append(MessageResponse(
            id=uuid.UUID(msg.id) if msg.id else uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=getattr(msg, "tool_calls", None) or None,
            tool_call_id=getattr(msg, "tool_call_id", None),
            created_at=base_ts + timedelta(milliseconds=idx),  # synthetic timestamp
        ))

    return results
```

#### 为什么放在 `message_utils.py`

- 与现有 `convert_to_langchain_messages()`（dict → BaseMessage）位置**对称**
- 同属 BaseMessage ↔ app format 转换领域
- 无需新建文件

#### `created_at` 处理策略

LangChain `BaseMessage` 没有 timestamp。选项：

| 选项 | 优点 | 缺点 |
|------|------|------|
| A. nullable | schema 诚实 | 需要修改 frontend |
| B. 合成时间戳 | 前端无需变更 | 不是准确时间 |
| C. checkpoint metadata | 准确 | 每个 checkpoint 1 个（不是每条消息一个） |

**选择：B — 合成时间戳**

以 `conversation.created_at` 为 base，按消息索引每条增加 1ms。前端只要保证顺序即可，实际时间仅供参考。前端代码零改动。

#### 从 checkpointer 提取消息

```python
# conversations.py — GET /messages 端点

from app.agent_runtime.checkpointer import get_checkpointer
from app.agent_runtime.message_utils import langchain_messages_to_response

async def list_messages(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conv = await chat_service.get_conversation(db, conversation_id)
    if not conv:
        raise NotFoundError(...)

    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": str(conversation_id)}}
    checkpoint_tuple = await checkpointer.aget_tuple(config)

    if not checkpoint_tuple:
        return []  # 还没有消息

    messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    return langchain_messages_to_response(messages, conversation_id, conv.created_at)
```

**`aget_tuple()` 返回结构：**
```python
CheckpointTuple(
    config={"configurable": {"thread_id": "..."}},
    checkpoint={
        "channel_values": {"messages": [HumanMessage(...), AIMessage(...), ...]},
        "channel_versions": {...},
    },
    metadata={"created_at": "...", "step": N},
    parent_config=...,
)
```

`channel_values.messages` 是反序列化后的 `BaseMessage` 列表。无需单独编译 graph 即可轻量查询。

---

### 3. 移动 auto-title 逻辑

#### 当前位置

位于 `chat_service.save_message()` 内部（第 92-102 行）。删除 `save_message()` 时会一并消失。

#### 新位置：`chat_service.py` 独立函数

```python
# chat_service.py — 新增函数

async def maybe_set_auto_title(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    content: str,
) -> None:
    """在第一条用户消息时自动设置对话标题。

    仅当 Conversation.title 为默认值（'新对话'）时执行 UPDATE。
    如果标题已设置则 no-op（由 WHERE 条件保证）。
    """
    title = content.strip().replace("\n", " ")
    if len(title) > 40:
        title = title[:37] + "..."
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.title == "新对话")
        .values(title=title)
    )
    await db.commit()
```

#### 调用位置：`conversations.py` POST 端点

```python
# conversations.py — send_message()

async def send_message(...):
    conv = await chat_service.get_conversation(db, conversation_id)
    ...
    # auto-title（从 save_message 中拆分）
    await chat_service.maybe_set_auto_title(db, conversation_id, data.content)

    agent = await chat_service.get_agent_with_tools(db, conv.agent_id, user.id)
    ...
    # checkpointer 保存消息 → 无需调用 save_message
    async def generate():
        async for chunk in execute_agent_stream(
            ...,
            messages_history=[{"role": "user", "content": data.content}],  # 仅新消息
            thread_id=str(conversation_id),
            ...
        ):
            yield chunk
        # 移除 save_message(assistant) 调用 — checkpointer 自动保存

    return StreamingResponse(generate(), ...)
```

#### 为什么在 router 中调用

- auto-title 是 UI metadata 更新 — 更偏展示层而非业务逻辑
- 不属于 `execute_agent_stream()` 的职责（与 agent 执行无关）
- router 持有 request context，因此放在这里更自然

#### 同步修改 trigger_executor.py（S4 scope）

`trigger_executor.py` 也在 2 处调用 `save_message()`（L43, L84）。虽然属于 M4 scope，但删除 `save_message()` 后会产生编译错误，因此**必须在 S4 同步修改**。

```python
# trigger_executor.py — 当前（变更前）
await chat_service.save_message(db, conv.id, "user", trigger.input_message)   # L43
...
await chat_service.save_message(db, conv.id, "assistant", full_content)       # L84
```

```python
# trigger_executor.py — 变更后
# L43：删除 save_message — checkpointer 自动保存 user 消息
# L84：删除 save_message — checkpointer 自动保存 assistant 消息
# 无需 auto-title：trigger 已通过 title=f"自动执行: {now_str}" 创建（L40）
```

**核心**：trigger_executor 会以 `title="自动执行: ..."` 创建对话，因此无需调用 `maybe_set_auto_title()`（不满足 WHERE 条件 `title == "新对话"`）。

`messages_history` 已经以 `[{"role": "user", "content": trigger.input_message}]`（L50）只传递新消息，因此无需修改。

---

### 4. 删除对话时清理 checkpointer

#### 需要清理的表（LangGraph 自动创建）

| 表 | 内容 |
|--------|------|
| `checkpoints` | checkpoint 状态快照 |
| `checkpoint_blobs` | 序列化的 channel 数据 |
| `checkpoint_writes` | 待处理写入 |

均通过 `thread_id` 列标识 thread。

#### 工具函数：`checkpointer.py`

```python
# checkpointer.py — 新增函数

async def delete_thread(thread_id: str) -> None:
    """删除 thread 的全部 checkpoint 数据。"""
    if _pool is None:
        return
    async with _pool.connection() as conn:
        await conn.execute(
            "DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,)
        )
        await conn.execute(
            "DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,)
        )
        await conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,)
        )
```

#### 调用位置：`conversations.py` DELETE 端点

```python
# conversations.py — delete_conversation()

from app.agent_runtime.checkpointer import delete_thread

async def delete_conversation(...):
    conv = await chat_service.get_conversation(db, conversation_id)
    ...
    await delete_thread(str(conversation_id))        # 清理 checkpoint
    await chat_service.delete_conversation(db, conv)  # 删除 conversations 表记录
```

**顺序很重要**：先删除 checkpoint → 再删除 conversations 表记录。即使删除 conversations 失败，也不会留下 orphan checkpoint。

---

## execute_agent_stream() 签名变更

### 参数含义变更（签名保持不变）

```python
async def execute_agent_stream(
    provider: str,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
    system_prompt: str,
    tools_config: list[dict[str, Any]],
    messages_history: list[dict[str, str]],  # 含义变更：完整历史 → 仅新消息
    thread_id: str,
    model_params: dict[str, Any] | None = None,
    middleware_configs: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[str, None]:
```

**变更事项：**
- `messages_history`：完整对话历史 → **仅新用户消息**（1 个 dict）
- checkpointer 自动恢复之前的历史
- `trigger_executor.py` 也应用相同模式（仅传递新消息）

内部变更：
```python
# executor.py 内部

agent = build_agent(
    model,
    langchain_tools,
    system_prompt,
    middleware=middleware or None,
    checkpointer=get_checkpointer(),  # NEW
    name=f"agent_{thread_id[:8]}",
)
```

外部调用方（`conversations.py`, `trigger_executor.py`）签名不变。

---

## DB 迁移计划

### token_usages FK 变更

```sql
-- Before
ALTER TABLE token_usages DROP CONSTRAINT fk_token_usages_message_id;
ALTER TABLE token_usages DROP COLUMN message_id;

-- After
ALTER TABLE token_usages ADD COLUMN conversation_id UUID REFERENCES conversations(id);
```

### 移除 messages 表

```sql
DROP TABLE messages;
```

### Alembic 迁移顺序

1. 在 `token_usages` 中新增 `conversation_id` 列（nullable）
2. 迁移既有数据：`message_id` → `conversation_id`（通过 JOIN 填充）
3. 移除 `token_usages.message_id` 列
4. DROP `messages` 表
5. 将 `token_usages.conversation_id` 改为 NOT NULL

> **参考**：由于处于 PoC 阶段，既有数据迁移为可选。`alembic downgrade` 会重新创建 messages 表，但不会恢复数据。

---

## 替代方案

### 方案 A：全面切换到 Checkpointer（选择）

- **优点**：消除消息双重管理，利用 LangGraph 功能（time-travel、state 恢复），简化代码
- **缺点**：依赖 checkpoint 内部结构，需要合成 `created_at`

### 方案 B：Checkpointer + Messages 表并行（否决）

- **优点**：尽量减少现有 API 变更，保留准确时间戳
- **缺点**：无法解决双重管理问题，存在不一致风险，增加代码复杂度

### 方案 C：保留 Messages 表 + 不使用 Checkpointer（否决）

- **优点**：无需变更
- **缺点**：tool_calls 丢失问题未解决，无法使用 LangGraph 高级功能，每次请求都要加载完整历史

---

## 变更文件摘要

| 文件 | 变更类型 | 详情 |
|------|-----------|------|
| `agent_runtime/checkpointer.py` | **新增** | AsyncPostgresSaver 单例 + init/shutdown + delete_thread |
| `main.py` | **修改** | 在 lifespan 中初始化/清理 checkpointer |
| `executor.py` | **修改** | 向 build_agent() 传入 `checkpointer=get_checkpointer()` |
| `routers/conversations.py` | **修改** | GET/messages → 查询 checkpointer，POST/messages → 移除 save_message，DELETE → delete_thread |
| `services/chat_service.py` | **修改** | 删除 `save_message()`、`list_messages()`，新增 `maybe_set_auto_title()`，变更 `save_token_usage()` FK |
| `agent_runtime/message_utils.py` | **修改** | 新增 `langchain_messages_to_response()` |
| `agent_runtime/trigger_executor.py` | **修改** | 移除 2 处 `save_message()`（L43, L84），改为由 checkpointer 自动保存 |
| `models/conversation.py` | **修改** | 移除 `Message` 类 |
| `models/token_usage.py` | **修改** | `message_id` → `conversation_id` FK |
| `schemas/conversation.py` | **修改** | 保留 `MessageResponse.created_at`（合成时间戳） |
| `alembic/versions/` | **新增** | DROP messages + 变更 token_usages FK |
| `pyproject.toml` | **修改** | 新增 `langgraph-checkpoint-postgres` |

### 保留的 module（不变）

| 文件 | 原因 |
|------|------|
| `streaming.py` | `astream()` 输入输出不变 — checkpointer 在 agent 内部工作 |
| `model_factory.py` | 与 LLM 创建无关 |
| `tool_factory.py` | 与工具创建无关 |
| `middleware_registry.py` | 与 middleware 无关 |

---

## 结果

- **移除代码**：删除 `save_message()`、`list_messages()`；移除 messages 模型/表
- **简化**：消息保存/查询委托给 LangGraph 框架
- **功能扩展**：可实现 time-travel、state 恢复、conversation forking（未来）
- **性能**：移除每次请求对完整历史的 DB 查询 — 由 checkpointer 内部优化
- **风险**：依赖 `aget_tuple()` 内部结构 — 可能随 LangGraph 版本升级而变化。通过封装到 `message_utils.py` 的转换函数中，将影响范围降至最低
- **依赖**：新增 `langgraph-checkpoint-postgres` + `psycopg[pool]`

---

## 核心数据流（M2 之后）

```
POST /api/conversations/{id}/messages
│
├─ 1. maybe_set_auto_title(content)                [chat_service → DB]
├─ 2. get_agent_with_tools(agent_id)               [chat_service → DB]
├─ 3. build_effective_prompt(agent)                 [chat_service]
├─ 4. build_tools_config(agent, conversation_id)    [chat_service]
│
├─ 5. execute_agent_stream(                         [executor.py]
│       ...,
│       messages_history=[{role: "user", content}],  ← 仅新消息
│       thread_id=str(conversation_id),
│       ...)
│    │
│    ├─ 5a. create_chat_model()                     [model_factory]
│    ├─ 5b. create_*_tool() × N                     [tool_factory]
│    ├─ 5c. build_middleware_instances()             [middleware_registry]
│    ├─ 5d. build_agent(checkpointer=saver)         [executor → deep agent]
│    ├─ 5e. checkpointer auto-loads 之前的历史
│    └─ 5f. stream_agent_response()                 [streaming → SSE]
│           → checkpointer auto-saves 新状态
│
└─ 6. StreamingResponse → Frontend (SSE)


GET /api/conversations/{id}/messages
│
├─ 1. checkpointer.aget_tuple(thread_id)            [checkpointer.py]
├─ 2. checkpoint.channel_values.messages             [list[BaseMessage]]
├─ 3. langchain_messages_to_response()               [message_utils.py]
└─ 4. → list[MessageResponse]


DELETE /api/conversations/{id}
│
├─ 1. delete_thread(thread_id)                       [checkpointer.py → SQL]
└─ 2. delete_conversation(conv)                      [chat_service → DB cascade]
```
