# M2 删除分析报告

> 分析日期：2026-04-06
> 分析者：bezos (QA Engineer)
> 对象：M2 — Checkpointer 切换 scope

---

## 可立即删除

### 1. `chat_service.py:list_messages()` (L61-70)
- **原因**：改为从 checkpointer 的 state["messages"] 提取
- **外部引用 3 处**：
  - `routers/conversations.py:95` — 在 `list_messages` endpoint 中调用
  - `routers/conversations.py:115` — 在 `send_message` endpoint 中加载 messages_history
  - `tests/test_chat_service.py:19` — import + 2 个测试
- **判断**：所有调用处都属于 M2 修改范围。可安全删除。

### 2. `chat_service.py:save_message()` (L73-104)
- **原因**：checkpointer 负责 message 持久化。无需手动保存。
- **外部引用 5 处**：
  - `routers/conversations.py:109` — 保存 user message
  - `routers/conversations.py:147` — 保存 assistant message
  - `agent_runtime/trigger_executor.py:43` — 保存 trigger user message
  - `agent_runtime/trigger_executor.py:84` — 保存 trigger assistant message
  - `tests/test_chat_service.py:20` — import + 5 个测试
- **⚠️ 注意**: 包含 auto-title 逻辑 (L92-102)。该逻辑需要迁移 (参见下方 "需要迁移" 部分)。

### 3. `models/conversation.py:Message` class（L35-51）
- **原因**：删除 messages table 后无需 ORM model
- **外部引用 7 处**：
  - `models/__init__.py:4` — import + `__all__` export
  - `services/chat_service.py:13` — import（在 save_message/list_messages 中使用）
  - `tests/test_conversations_router.py:12` — 在 `_seed_message()` helper 中直接创建
  - `tests/test_trigger_executor.py:13` — 在 `select(Message)` 验证查询中使用
  - `tests/test_usage_service.py:12` — 在 `_seed_usage()` helper 中为满足 FK 而创建
  - `tests/test_usage_router.py:12` — 在 `_seed_agent_with_usage()` helper 中为满足 FK 而创建
- **判断**：删除会引发较大连锁修改。整理顺序：先修改 token_usages FK → 再删除 Message。

### 4. `models/conversation.py:Conversation.messages` relationship (L30-32)
- **原因**：删除 Message class 时也需要删除 relationship
- **外部引用**：未发现代码直接访问 `conv.messages`。只有 cascade 配置。
- **判断**：可安全删除。

---

## 删除后需要修改

### 5. `routers/conversations.py:list_messages` endpoint（L84-95）
- **当前**：DB query（`chat_service.list_messages`）
- **变更**：从 checkpointer 提取 state → 以 MessageResponse 形式返回
- **修改对象**：`routers/conversations.py`，需要新增 service 函数
- **前端 API**：保留 `GET /api/conversations/{id}/messages` 路径，response shape 可能变化

### 6. `routers/conversations.py:send_message` endpoint（L98-157）
- **删除对象代码**：
  - L109: `await chat_service.save_message(db, conversation_id, "user", data.content)` — 由 checkpointer 替代
  - L115-116: `messages = await chat_service.list_messages(...)` + `messages_history` 转换 — checkpointer 自动管理 history
  - L147: `await chat_service.save_message(db, conversation_id, "assistant", full_content)` — 由 checkpointer 替代
- **保留代码**：L118-119（`build_effective_prompt`, `build_tools_config`），L121-137（SSE streaming）
- **修改对象**：`routers/conversations.py`

### 7. `agent_runtime/trigger_executor.py` (L43, L50, L84)
- **删除对象代码**：
  - L43: `await chat_service.save_message(db, conv.id, "user", trigger.input_message)` — 由 checkpointer 替代
  - L50: `messages_history = [{"role": "user", "content": trigger.input_message}]` — checkpointer 自动管理
  - L84: `await chat_service.save_message(db, conv.id, "assistant", full_content)` — 由 checkpointer 替代
- **修改对象**：`agent_runtime/trigger_executor.py` — 改为使用 deep agent invoke()（属于 M4 scope，但依赖删除 save_message）
- **⚠️ 注意**：M4 计划整体替换 trigger_executor，但 M2 删除 save_message 时 trigger_executor 也必须同时修改。

### 8. `models/token_usage.py:message_id` FK (L17)
- **当前**：`message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), nullable=False)`
- **变更**：`conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)` + 删除 `message_id`
- **修改对象**：
  - `models/token_usage.py` — FK 变更
  - `services/chat_service.py:save_token_usage()`（L107-128）— 参数 `message_id` → `conversation_id`
  - `tests/test_chat_service.py:219-228` — 修改 test_save_token_usage
  - `tests/test_usage_service.py:60-74` — 从 `_seed_usage()` helper 删除 Message 创建
  - `tests/test_usage_router.py:45-59` — 从 `_seed_agent_with_usage()` helper 删除 Message 创建

### 9. `schemas/conversation.py:MessageResponse` (L34-43)
- **当前**：从 DB Message ORM 通过 `from_attributes=True` 自动转换
- **变更**：需要修改为适配从 checkpointer state 提取的数据结构
- **可能变更的字段**：
  - `id`：checkpointer message 可能没有 UUID id → 基于 index 生成或删除
  - `tool_calls`, `tool_call_id`：需要按 LangChain message format 转换
- **前端类型**：`frontend/src/lib/types/index.ts:168-176`（`Message` interface）— 与 backend response 结构 1:1 对应。发生变更时必须同步。

### 10. `models/__init__.py` — Message export (L4, L20)
- **修改**：`from app.models.conversation import Conversation, Message` → `from app.models.conversation import Conversation`
- **修改**：从 `__all__` 删除 `"Message"`

---

## 需要迁移（不是删除）

### 11. Auto-title 逻辑（`chat_service.py:save_message` L92-102）
- **当前位置**：`save_message()` 函数内部
- **功能**: 用第一条 user message 自动生成 conversation title ("新对话" → 第一条 message 内容)
- **迁移目标**：`send_message` endpoint 或单独的 `auto_generate_title()` service 函数
- **迁移原因**：checkpointer 只保存 message。conversation metadata（title）仍需由 conversations table 管理。
- **实现建议**：
  ```python
  async def auto_generate_title(db: AsyncSession, conversation_id: uuid.UUID, content: str):
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
- **调用位置**：`conversations.py:send_message`（发送 user message 时）、`trigger_executor.py`（执行 trigger 时）

---

## 需要 Alembic migration

### 12. 需要创建新的 migration 文件
1. `token_usages` table：删除 `message_id` column + 新增 `conversation_id` FK
2. `messages` table：DROP TABLE
3. **顺序注意**：先改 token_usages FK → 再 DROP messages table（FK dependency）
4. `PostgresSaver` 自动 table（checkpoint, checkpoint_blobs, checkpoint_writes）由 LangGraph setup() 处理

---

## 测试影响

### `tests/test_chat_service.py` — 7 个测试受影响
| 测试 | 影响 | 应对 |
|--------|------|------|
| `test_list_messages_ordering` | 直接删除对象 | 删除或改写为基于 checkpointer |
| `test_list_messages_limit` | 直接删除对象 | 删除或改写为基于 checkpointer |
| `test_save_message_user_generates_title` | 迁移 auto-title 逻辑后改写 | 替换为迁移后函数的测试 |
| `test_save_message_user_long_title_truncated` | 迁移 auto-title 逻辑后改写 | 替换为迁移后函数的测试 |
| `test_save_message_assistant_no_title_change` | 迁移 auto-title 逻辑后改写 | 替换为迁移后函数的测试 |
| `test_save_token_usage` | 修改 message_id FK 后调整 | 改为 conversation_id 参数 |
|（save_message import）| 删除 import | 删除 list_messages/save_message import |

### `tests/test_conversations_router.py` — 5 个测试受影响
| 测试 | 影响 | 应对 |
|--------|------|------|
| `test_list_messages_empty` | response shape 可能变化 | 按基于 checkpointer 的 response 修改 |
| `test_list_messages_with_data` | `_seed_message()` helper 使用 Message ORM | 删除 helper，使用 checkpointer 写入 message |
| `test_list_messages_conversation_not_found` | 影响较小 | 可保留 |
| `test_send_message_saves_user_message` | 删除 save_message 后验证方式变化 | 改为从 checkpointer 确认 message |
| `test_send_message_streaming` | mock 对象可能变化 | 需要检查 |

### `tests/test_trigger_executor.py` — 3 个测试受影响
| 测试 | 影响 | 应对 |
|--------|------|------|
| `test_execute_trigger_content_parsing`（L242-270） | 使用 `select(Message)` 验证查询 | 改为基于 checkpointer 验证 |
| `test_execute_trigger_saves_user_message`（L336-361） | 使用 `select(Message)` 验证查询 | 改为基于 checkpointer 验证 |
|（Message import, L13） | 删除 import | `from app.models.conversation import Conversation`（删除 Message） |

### `tests/test_usage_service.py` — 全部测试受影响
| 测试 | 影响 | 应对 |
|--------|------|------|
| 全部（5 个） | `_seed_usage()` helper 创建 Message + 使用 message_id FK | 修改 FK 后删除 Message 创建，直接使用 conversation_id |

### `tests/test_usage_router.py` — 全部测试受影响
| 测试 | 影响 | 应对 |
|--------|------|------|
| 全部（4 个） | `_seed_agent_with_usage()` helper 创建 Message + 使用 message_id FK | 修改 FK 后删除 Message 创建，直接使用 conversation_id |

---

## 前端影响

### API response shape 可能变化
- 若 `GET /api/conversations/{id}/messages` response schema 发生变化：
  - 需要修改 `frontend/src/lib/types/index.ts:168-176`（`Message` interface）
  - `frontend/src/lib/api/conversations.ts:20-21` — API client
  - `frontend/src/lib/hooks/use-conversations.ts:17-18` — TanStack Query hook
  - `frontend/src/app/agents/[agentId]/conversations/[conversationId]/page.tsx` — chat page
- **建议**：backend 尽量转换为兼容现有 `MessageResponse` schema 的形式，以最小化前端变更

---

## 删除/修改顺序建议

1. **提取 auto-title 逻辑**（`save_message` → 单独函数）
2. **变更 token_usages FK**（`message_id` → `conversation_id`）+ Alembic migration
3. **修改 conversations router**（基于 checkpointer 的 list_messages，移除 save_message 调用）
4. **修改 trigger_executor**（移除 save_message 调用）
5. **整理 chat_service.py**（删除 `save_message`, `list_messages`）
6. **移除 Message model** + 整理 `models/__init__.py`
7. **DROP messages table** Alembic migration
8. **全面修改测试**
9. **同步前端类型**（必要时）

---

## 汇总统计

| 分类 | 项目数 |
|------|---------|
| 可立即删除 | 4 项 |
| 删除后需修改 | 6 项 |
| 需要迁移 | 1 项（auto-title） |
| 受影响的测试文件 | 5 个（约 19 个测试） |
| 受影响的前端文件 | 4 个（类型变更时） |
| Alembic migration | 1 个（token_usages FK 变更 + messages DROP） |
