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
| B. 합성 타임스탬프 | 프론트엔드 변경 없음 | 정확한 시간 아님 |
| C. checkpoint metadata | 정확함 | checkpoint당 1개 (메시지별 없음) |

**선택: B — 합성 타임스탬프**

`conversation.created_at`을 base로, 메시지 인덱스에 1ms씩 더한다. 프론트엔드는 순서만 보장되면 되고, 실제 시각은 참고용이다. 프론트엔드 코드 변경 제로.

#### checkpointer에서 메시지 추출

```python
# conversations.py — GET /messages 엔드포인트

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
        return []  # 아직 메시지 없음

    messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    return langchain_messages_to_response(messages, conversation_id, conv.created_at)
```

**`aget_tuple()` 반환 구조:**
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

`channel_values.messages`는 역직렬화된 `BaseMessage` 리스트. 별도 graph 컴파일 없이 경량 조회 가능.

---

### 3. auto-title 로직 이동

#### 현재 위치

`chat_service.save_message()` 내부 (라인 92-102). `save_message()` 삭제 시 함께 사라짐.

#### 새 위치: `chat_service.py` 독립 함수

```python
# chat_service.py — 신규 함수

async def maybe_set_auto_title(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    content: str,
) -> None:
    """첫 사용자 메시지일 때 대화 제목을 자동 설정.

    Conversation.title이 기본값('새 대화')인 경우에만 UPDATE 실행.
    이미 제목이 설정된 경우 no-op (WHERE 조건으로 보장).
    """
    title = content.strip().replace("\n", " ")
    if len(title) > 40:
        title = title[:37] + "..."
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.title == "새 대화")
        .values(title=title)
    )
    await db.commit()
```

#### 호출 위치: `conversations.py` POST 엔드포인트

```python
# conversations.py — send_message()

async def send_message(...):
    conv = await chat_service.get_conversation(db, conversation_id)
    ...
    # auto-title (save_message에서 분리)
    await chat_service.maybe_set_auto_title(db, conversation_id, data.content)

    agent = await chat_service.get_agent_with_tools(db, conv.agent_id, user.id)
    ...
    # checkpointer가 메시지 저장 → save_message 호출 불필요
    async def generate():
        async for chunk in execute_agent_stream(
            ...,
            messages_history=[{"role": "user", "content": data.content}],  # 새 메시지만
            thread_id=str(conversation_id),
            ...
        ):
            yield chunk
        # save_message(assistant) 호출 제거 — checkpointer가 자동 저장

    return StreamingResponse(generate(), ...)
```

#### 왜 router에서 호출하는가

- auto-title은 UI 메타데이터 업데이트 — 비즈니스 로직보다 프레젠테이션
- `execute_agent_stream()`의 관심사가 아님 (에이전트 실행에 무관)
- router가 request context를 가지고 있으므로 자연스러운 위치

#### trigger_executor.py 동시 수정 (S4 scope)

`trigger_executor.py`도 `save_message()`를 2곳에서 호출한다 (L43, L84). M4 scope이지만 `save_message()` 제거 시 컴파일 에러가 발생하므로 **S4에서 동시 수정 필수**.

```python
# trigger_executor.py — 현재 (변경 전)
await chat_service.save_message(db, conv.id, "user", trigger.input_message)   # L43
...
await chat_service.save_message(db, conv.id, "assistant", full_content)       # L84
```

```python
# trigger_executor.py — 변경 후
# L43: save_message 삭제 — checkpointer가 user 메시지 자동 저장
# L84: save_message 삭제 — checkpointer가 assistant 메시지 자동 저장
# auto-title 불필요: trigger는 이미 title=f"자동 실행: {now_str}"로 생성 (L40)
```

**핵심**: trigger_executor는 `title="자동 실행: ..."` 으로 대화를 생성하므로 `maybe_set_auto_title()` 호출이 필요 없음 (WHERE 조건 `title == "새 대화"`에 해당하지 않음).

`messages_history`는 이미 `[{"role": "user", "content": trigger.input_message}]` (L50)로 새 메시지만 전달하고 있어 변경 불필요.

---

### 4. 대화 삭제 시 checkpointer 정리

#### 정리 대상 테이블 (LangGraph 자동 생성)

| 테이블 | 내용 |
|--------|------|
| `checkpoints` | 체크포인트 상태 스냅샷 |
| `checkpoint_blobs` | 직렬화된 channel 데이터 |
| `checkpoint_writes` | 보류 중인 쓰기 |

모두 `thread_id` 컬럼으로 thread를 식별한다.

#### 유틸리티 함수: `checkpointer.py`

```python
# checkpointer.py — 추가 함수

async def delete_thread(thread_id: str) -> None:
    """thread의 모든 checkpoint 데이터를 삭제."""
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

#### 호출 위치: `conversations.py` DELETE 엔드포인트

```python
# conversations.py — delete_conversation()

from app.agent_runtime.checkpointer import delete_thread

async def delete_conversation(...):
    conv = await chat_service.get_conversation(db, conversation_id)
    ...
    await delete_thread(str(conversation_id))        # checkpoint 정리
    await chat_service.delete_conversation(db, conv)  # conversations 테이블 삭제
```

**순서 중요**: checkpoint 먼저 삭제 → conversations 테이블 삭제. conversations 삭제가 실패해도 orphan checkpoint가 남지 않음.

---

## execute_agent_stream() 시그니처 변경

### 파라미터 의미 변경 (시그니처 유지)

```python
async def execute_agent_stream(
    provider: str,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
    system_prompt: str,
    tools_config: list[dict[str, Any]],
    messages_history: list[dict[str, str]],  # 의미 변경: 전체 히스토리 → 새 메시지만
    thread_id: str,
    model_params: dict[str, Any] | None = None,
    middleware_configs: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[str, None]:
```

**变更事项：**
- `messages_history`: 전체 대화 히스토리 → **새 사용자 메시지만** (1개 dict)
- checkpointer가 이전 히스토리를 자동 복원
- `trigger_executor.py`도 동일 패턴 적용 (새 메시지만 전달)

내부 변경:
```python
# executor.py 내부

agent = build_agent(
    model,
    langchain_tools,
    system_prompt,
    middleware=middleware or None,
    checkpointer=get_checkpointer(),  # NEW
    name=f"agent_{thread_id[:8]}",
)
```

외부 호출자(`conversations.py`, `trigger_executor.py`) 시그니처 변경 없음.

---

## DB 마이그레이션 계획

### token_usages FK 변경

```sql
-- Before
ALTER TABLE token_usages DROP CONSTRAINT fk_token_usages_message_id;
ALTER TABLE token_usages DROP COLUMN message_id;

-- After
ALTER TABLE token_usages ADD COLUMN conversation_id UUID REFERENCES conversations(id);
```

### messages 테이블 제거

```sql
DROP TABLE messages;
```

### Alembic 마이그레이션 순서

1. `token_usages`에 `conversation_id` 컬럼 추가 (nullable)
2. 기존 데이터 마이그레이션: `message_id` → `conversation_id` (JOIN으로 채움)
3. `token_usages.message_id` 컬럼 제거
4. `messages` 테이블 DROP
5. `token_usages.conversation_id`를 NOT NULL로 변경

> **참고**: PoC 단계이므로 기존 데이터 마이그레이션은 선택적. `alembic downgrade`는 messages 테이블을 재생성하되 데이터는 복원하지 않음.

---

## 替代方案

### 옵션 A: Checkpointer 전면 전환 (선택)

- **장점**: 메시지 이중 관리 제거, LangGraph 기능(time-travel, state 복원) 활용, 코드 단순화
- **단점**: checkpoint 내부 구조 의존, `created_at` 합성 필요

### 옵션 B: Checkpointer + Messages 테이블 병행 (기각)

- **장점**: 기존 API 변경 최소화, 정확한 타임스탬프 유지
- **단점**: 이중 관리 문제 해결 안 됨, 불일치 리스크, 코드 복잡도 증가

### 옵션 C: Messages 테이블 유지 + Checkpointer 없음 (기각)

- **장점**: 변경 없음
- **단점**: tool_calls 손실 문제 미해결, LangGraph 고급 기능 사용 불가, 매 요청 전체 히스토리 로딩

---

## 变更文件摘要

| 文件 | 变更类型 | 详情 |
|------|-----------|------|
| `agent_runtime/checkpointer.py` | **신규** | AsyncPostgresSaver 싱글턴 + init/shutdown + delete_thread |
| `main.py` | **수정** | lifespan에서 checkpointer 초기화/정리 |
| `executor.py` | **수정** | build_agent()에 `checkpointer=get_checkpointer()` 전달 |
| `routers/conversations.py` | **수정** | GET/messages → checkpointer 조회, POST/messages → save_message 제거, DELETE → delete_thread |
| `services/chat_service.py` | **수정** | `save_message()` 삭제, `list_messages()` 삭제, `maybe_set_auto_title()` 신규, `save_token_usage()` FK 변경 |
| `agent_runtime/message_utils.py` | **수정** | `langchain_messages_to_response()` 추가 |
| `agent_runtime/trigger_executor.py` | **수정** | `save_message()` 2곳 제거 (L43, L84). checkpointer 자동 저장으로 대체 |
| `models/conversation.py` | **수정** | `Message` 클래스 제거 |
| `models/token_usage.py` | **수정** | `message_id` → `conversation_id` FK |
| `schemas/conversation.py` | **수정** | `MessageResponse.created_at` 유지 (합성 타임스탬프) |
| `alembic/versions/` | **신규** | messages DROP + token_usages FK 변경 |
| `pyproject.toml` | **수정** | `langgraph-checkpoint-postgres` 추가 |

### 保留的 module（不变）

| 文件 | 原因 |
|------|------|
| `streaming.py` | `astream()` 입출력 동일 — checkpointer는 agent 내부에서 동작 |
| `model_factory.py` | LLM 생성 무관 |
| `tool_factory.py` | 도구 생성 무관 |
| `middleware_registry.py` | 미들웨어 무관 |

---

## 结果

- **코드 제거**: `save_message()`, `list_messages()` 삭제. messages 모델/테이블 제거
- **단순화**: 메시지 저장/조회가 LangGraph 프레임워크에 위임됨
- **기능 확장**: time-travel, state 복원, conversation forking 가능 (향후)
- **성능**: 매 요청 전체 히스토리 DB 조회 제거 — checkpointer가 내부 최적화
- **리스크**: `aget_tuple()` 내부 구조 의존 — LangGraph 버전 업에 따라 변경 가능. 이를 `message_utils.py`의 변환 함수로 캡슐화하여 영향 범위 최소화
- **의존성**: `langgraph-checkpoint-postgres` + `psycopg[pool]` 추가

---

## 핵심 데이터 흐름 (M2 이후)

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
│       messages_history=[{role: "user", content}],  ← 새 메시지만
│       thread_id=str(conversation_id),
│       ...)
│    │
│    ├─ 5a. create_chat_model()                     [model_factory]
│    ├─ 5b. create_*_tool() × N                     [tool_factory]
│    ├─ 5c. build_middleware_instances()             [middleware_registry]
│    ├─ 5d. build_agent(checkpointer=saver)         [executor → deep agent]
│    ├─ 5e. checkpointer auto-loads 이전 히스토리
│    └─ 5f. stream_agent_response()                 [streaming → SSE]
│           → checkpointer auto-saves 새 상태
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
