# ADR-004：M4 清理 — Creation Agent + Trigger + Streaming

## 状态：已批准

## 背景

M1-M3 已完成 deep agent 引擎迁移。M4 将清理剩余代码并统一使用同一引擎。

3 类清理对象：
1. **creation_agent.py** — 直接调用 `model.ainvoke()`，未使用 deep agent。
2. **trigger_executor.py** — 调用 `execute_agent_stream()` 后解析 SSE。实际上不需要 streaming，却发生 SSE 编码/解码往返。
3. **streaming.py / middleware_registry.py** — 判断 middleware JSON 过滤器和 PatchedLLMToolSelectorMiddleware 在迁移到 deep agent 后是否仍有必要。

---

## 决策 1：creation_agent → 迁移到 create_deep_agent

### 选择：迁移但保持最小变更（不使用 checkpointer）

```python
# Before (creation_agent.py)
model = create_chat_model("openai", "gpt-4o")
lc_messages = convert_to_langchain_messages(messages)
response = await model.ainvoke(lc_messages)
content = response.content

# After
from app.agent_runtime.executor import build_agent

model = create_chat_model("openai", "gpt-4o")
agent = build_agent(model, tools=[], system_prompt=system_content)
lc_messages = convert_to_langchain_messages(history + [user_msg])
result = await agent.ainvoke({"messages": lc_messages})
content = result["messages"][-1].content
```

**设计决策：**

| 项目 | 决策 | 原因 |
|------|------|------|
| 工具 | `tools=[]`（空列表） | 不使用工具。create_deep_agent 通过 `tools or []` 处理，允许空列表 |
| Checkpointer | **不使用**（None） | 对话历史由 `agent_creation_sessions.conversation_history` DB JSON 字段管理。引入 checkpointer 需要修改 creation session 数据模型 → 增加不必要复杂性 |
| 调用方式 | `agent.ainvoke()` | 不需要 SSE streaming，一次性接收完整响应 |
| 消息传递 | 每次调用传递完整历史 | 无 checkpointer 时将历史传给 agent。system_prompt 作为 create_deep_agent 参数单独传递 |
| JSON 解析 | **保持现有** | `extract_json_from_markdown()` + `strip_json_blocks()`。使用 `response_format` 需要修改前端 → 对 PoC 过重 |
| Backend/Skills/Memory | 不使用 | creation agent 不需要文件系统访问 |

**依据：**
- **统一引擎**：所有 LLM 调用都经过 `create_deep_agent` 路径。可自动应用 middleware（prompt caching、moderation）。
- **最小变更**：不引入 checkpointer，因此无需修改现有 DB schema 和服务逻辑（agent_creation_service.py）。
- **未来扩展**：以后需要增加工具（如浏览模板）时，只需传入 `tools=[...]`。

**变更文件：**

| 文件 | 变更 |
|------|------|
| `creation_agent.py` | `model.ainvoke()` → `build_agent()` + `agent.ainvoke()` |
| `agent_creation_service.py` | 无变更（interface 相同） |

### 方案分析

**方案 A：使用 Checkpointer**
- 使用 creation_session_id 作为 thread_id，将历史保存到 checkpointer
- 优点：可移除 DB JSON 字段，实现完全统一
- 缺点：需要修改 agent_creation_sessions 表 schema，大幅修改 agent_creation_service.py，且 creation session 与普通 conversation 的 checkpointer 会混杂
- 判断：收益不足以抵消成本 → 否决

**方案 B：保持现状（直接调用 model.ainvoke）**
- 优点：无需变更，最简单
- 缺点：这是唯一不使用 create_deep_agent 的 LLM 调用路径，无法应用 middleware
- 判断：无法实现“统一引擎”目标 → 否决

**方案 C：通过 response_format 结构化输出**
- 使用 `create_deep_agent(response_format=CreationResponse)`
- 优点：可移除 JSON 解析逻辑，类型安全
- 缺点：当前前端期望字符串 content + 独立 JSON 字段。需要定义 Pydantic 模型并修改前端
- 判断：超出 M4 scope → 后续事项

---

## 决策 2：trigger_executor → 迁移到 direct invoke

### 选择：提取 `_prepare_agent()` + 新增 `execute_agent_invoke()`（方案 A+C 混合）

**当前问题：**
```python
# trigger_executor.py — 当前
async for chunk in execute_agent_stream(...):
    for line in chunk.strip().split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])    # SSE 解码
            if "delta" in data:
                full_content += data["delta"]
```

在不需要 streaming 的情况下，却发生 SSE 编码（streaming.py）→ SSE 解码（trigger_executor.py）的往返。

**变更后结构：**

```python
# executor.py

async def _prepare_agent(
    provider, model_name, api_key, base_url,
    system_prompt, tools_config, messages_history, thread_id,
    model_params, middleware_configs, agent_skills, agent_id,
) -> tuple[Any, list, dict]:
    """构建 + 配置 agent，供 stream/invoke 共用。"""
    model = create_chat_model(provider, model_name, api_key, base_url, **(model_params or {}))
    langchain_tools = ...   # 现有工具构建逻辑
    mcp_tools = ...         # 构建 MCP 工具
    middleware = ...         # 构建 middleware
    backend = ...            # FilesystemBackend
    skills_sources = ...     # skills source
    memory_sources = ...     # memory source
    agent = build_agent(model, langchain_tools, system_prompt, ...)
    lc_messages = convert_to_langchain_messages(messages_history)
    config = {"configurable": {"thread_id": thread_id}}
    return agent, lc_messages, config


async def execute_agent_stream(...) -> AsyncGenerator[str, None]:
    """Streaming 执行（用于聊天）。"""
    agent, lc_messages, config = await _prepare_agent(...)
    async for chunk in stream_agent_response(agent, lc_messages, config):
        yield chunk


async def execute_agent_invoke(...) -> str:
    """非 streaming 执行（用于 trigger）。仅返回最终响应文本。"""
    agent, lc_messages, config = await _prepare_agent(...)
    result = await agent.ainvoke({"messages": lc_messages}, config=config)
    messages = result.get("messages", [])
    if messages and hasattr(messages[-1], "content"):
        return messages[-1].content
    return ""
```

```python
# trigger_executor.py — 变更后
from app.agent_runtime.executor import execute_agent_invoke

full_content = await execute_agent_invoke(
    provider=agent.model.provider,
    model_name=agent.model.model_name,
    ...
)
```

**设计决策：**

| 项目 | 决策 | 原因 |
|------|------|------|
| 共用方式 | 提取 `_prepare_agent()` 内部函数 | 工具/middleware/backend 构建逻辑约 ~50 行，消除重复 |
| 调用方式 | `agent.ainvoke()` | CompiledStateGraph 完整支持 invoke/ainvoke。trigger 只需要结果 |
| 返回类型 | `str`（最终 content） | trigger 只需要完整响应文本，不需要消息 metadata |
| `execute_agent_stream` | 保持签名 | 现有调用方（conversations.py）无需变更 |

**依据：**
- **移除 SSE 往返**：无需编码/解码 → 简化代码 + 轻微性能提升
- **代码共享**：通过 `_prepare_agent()` 统一 agent 构建逻辑，未来更容易增加其他执行模式（batch 等）
- **简化 trigger_executor**：SSE 解析约 ~15 行 → 变成 1 行函数调用

**变更文件：**

| 文件 | 变更 |
|------|------|
| `executor.py` | 提取 `_prepare_agent()`，新增 `execute_agent_invoke()`，重构 `execute_agent_stream()` 内部 |
| `trigger_executor.py` | 将 `execute_agent_stream()` 改为调用 `execute_agent_invoke()`，移除 SSE 解析 |

### 方案分析

**方案 A：仅提取 _prepare_agent()（不新增 invoke 函数）**
- trigger_executor 直接调用 `_prepare_agent()` + `agent.ainvoke()`
- 缺点：trigger_executor 需要了解 executor 内部结构（agent state format、message extraction）
- 判断：封装不足 → 否决

**方案 B：trigger_executor 独立实现**
- 在 trigger_executor 内部自行实现工具/middleware 构建
- 缺点：约 ~50 行代码重复
- 判断：违反 DRY → 否决

**方案 C：仅新增 execute_agent_invoke()（不重构）**
- 与 execute_agent_stream() 分开复制完整 setup 代码
- 缺点：重复 → 增加维护负担
- 判断：否决（与 A 结合后采纳）

---

## 决策 3：清理 streaming/middleware

### 选择：两者都保留

#### 3-1. streaming.py — 保留 middleware JSON 过滤器

**调查结果：**
- `PatchToolCallsMiddleware` 只实现 `before_agent()` hook（修补消息历史中的 dangling tool call）
- **不会过滤 stream 事件** — 没有 `wrap_model_call()` 或 streaming 后处理
- 因此，如果 `LLMToolSelectorMiddleware` 生成 `{"tools": ["tool1", "tool2"]}` JSON 作为模型响应，它会直接暴露在 stream 中

**决策**：保留 streaming.py 的 `_is_tool_selector_json()` + character-by-character buffering 过滤器。

```python
# streaming.py — 保留对象
def _is_tool_selector_json(text: str) -> bool:
    """检测 LLMToolSelectorMiddleware 输出。PatchToolCallsMiddleware
    不做 stream 过滤，因此仍需要此过滤器。"""
```

#### 3-2. middleware_registry.py — 保留 PatchedLLMToolSelectorMiddleware

**调查结果：**
- GPT-4o 在 structured output 中返回 `{"const": "tool_name"}` 对象的问题属于 GPT-4o 特有行为
- deepagents 只是以 `tools or []` 传递工具 schema，不会在内部处理选择响应规范化
- `LLMToolSelectorMiddleware._process_selection_response()` 只期望字符串，因此传入 dict 会报错

**决策**：保留 `PatchedLLMToolSelectorMiddleware`。

```python
# middleware_registry.py — 保留对象
class PatchedLLMToolSelectorMiddleware(LLMToolSelectorMiddleware):
    """将 GPT-4o 的 {"const": "name"} 形式规范化为字符串。
    deepagents 内部未处理。保留至上游 langchain 包修复为止。"""
```

### 保留原因摘要

| 组件 | 保留原因 | 重新评估时点 |
|----------|----------|------------|
| `_is_tool_selector_json()` + buffering | PatchToolCallsMiddleware 不过滤 stream | deepagents 内置 stream filtering 时 |
| `PatchedLLMToolSelectorMiddleware` | GPT-4o `{"const": "name"}` 问题未修复 | langchain 或 deepagents 内置规范化时 |

### 唯一变更：新增代码注释

在现有代码中通过注释明确保留原因，便于未来重新评估（代码逻辑不变）。

---

## 结果

### 正面影响
- **统一引擎**：creation_agent 也使用 `create_deep_agent` 路径。项目内所有 LLM 调用统一到单一引擎。
- **移除 SSE 往返**：trigger_executor 直接调用 `ainvoke()`。移除约 ~15 行 SSE 解析代码。
- **代码共享**：通过 `_prepare_agent()` 统一 agent 构建逻辑。
- **安全清理**：streaming/middleware 根据调查结果保留，避免内部 JSON 暴露给用户的 regression。

### 负面影响
- **creation_agent 开销**：简单 LLM 调用也会增加 graph 编译成本。实际体感影响很小，但确实存在技术开销。
- **middleware 代码残留**：streaming.py 过滤器和 PatchedLLMToolSelectorMiddleware 会继续作为 workaround 存在，需要维护到上游包修复为止。

### 后续事项（M4 之后）
- [ ] 评估在 creation_agent 中引入 `response_format`（配合前端变更）
- [ ] deepagents 增加 stream filtering 功能后移除 streaming.py 过滤器
- [ ] langchain LLMToolSelectorMiddleware 修复 `{"const"}` 处理后移除 patch
- [ ] 为 creation_agent 增加工具（模板搜索、skill catalog 浏览等）
