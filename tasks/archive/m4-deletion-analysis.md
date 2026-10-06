# 删除分析报告 — M4

> 作者：贝索斯 (QA) | 日期：2026-04-06
> 分析范围：M4 scope（整理 + Creation Agent 替换）

---

## 可立即删除

| 项目 | 文件 | 行 | 原因 |
|------|------|------|------|
| `TokenTrackingCallback` class | `agent_runtime/token_tracker.py` | 整个文件 (9-27) | production code 中未使用。token 跟踪已由 LangGraph usage_metadata 替代。grep 引用 0 项。 |
| SSE 解析逻辑 (trigger_executor) | `agent_runtime/trigger_executor.py` | 67-77 | `execute_agent_stream()` → `build_agent()` + `invoke()` 切换后不再需要。delta 累积 + JSON 解析 11 行。 |
| `json` import (trigger_executor) | `agent_runtime/trigger_executor.py` | 3 | 删除 SSE 解析后未使用。 |
| streaming.py middleware filter | `agent_runtime/streaming.py` | 13-27, 42-76 | `_is_tool_selector_json()` + character-by-character buffering。参见下方详细判断。 |

---

## 需要修改（替换）

| 项目 | 当前 | 变更后 | 影响范围 |
|------|------|---------|----------|
| `creation_agent.py` `run_creation_conversation()` | 直接调用 `model.ainvoke()`（L151, L166） | 替换为基于 `create_deep_agent()` 的 agent | 仅修改函数内部。可保持 signature/返回形式。 |
| `trigger_executor.py` `execute_trigger()` | 消费 `execute_agent_stream()` SSE stream（L53-77） | 直接调用 `build_agent()` + `agent.invoke()` | 仅修改函数内部。删除 SSE 解析，从 invoke 结果提取 content。 |
| `trigger_executor.py` import | `from executor import execute_agent_stream`（L8） | `from executor import build_agent` | import 路径变更 |
| `creation_agent.py` import | `from model_factory import create_chat_model`（L10） | `create_deep_agent` + `create_chat_model` 组合 | 新增 import |

---

## 保留

| 项目 | 文件 | 保留原因 |
|------|------|----------|
| `CREATION_SYSTEM_PROMPT` 常量 | `creation_agent.py` L12-141 | 定义 4 阶段 agent 创建 workflow。切换 deep agent 后仍作为 system prompt 使用。 |
| JSON 提取/解析逻辑 | `creation_agent.py` L177-199 | `extract_json_from_markdown()`, `strip_json_blocks()` — response 后处理。与 agent framework 无关。 |
| `PatchedLLMToolSelectorMiddleware` | `middleware_registry.py` L269-298 | 参见下方详细判断。 |
| 整个 `middleware_registry.py` | `middleware_registry.py` | `build_middleware_instances()`, `get_provider_middleware()`, `get_middleware_registry()` — 被 executor.py, agents.py, schemas/agent.py 大量使用。 |
| `streaming.py` `format_sse()` + `stream_agent_response()` | `streaming.py` | conversations.py SSE streaming 中仍在使用。 |
| `mcp_client.py` `test_mcp_connection()`, `list_mcp_tools()` | `mcp_client.py` | UI 用于 MCP server 连接测试/tool list 查询。 |
| `config.py` 全部设置 | `config.py` | 所有设置均被积极引用。包括 M3 保留项 skill_storage_dir, skill_max_package_bytes 等。 |

---

## streaming.py middleware filter 判断

**结论：可删除（不需要）**

### 依据

1. **LLMToolSelectorMiddleware 不会由 deepagents 自动应用。** 仅当用户在 agent middleware_configs 中显式设置 `"llm_tool_selector"` 时启用。

2. **该 filter 防御的场景实际上不会发生。** LLMToolSelectorMiddleware 在 `wrap_model_call()` hook 中执行，structured output（`{"tools":[...]}`）会在内部被消费，不会暴露到 stream。

3. **deepagents 的 PatchToolCallsMiddleware 解决的是另一个问题。** 它用于修补 dangling tool call，与过滤 `{"tools":[...]}` JSON 无关。

4. **character-by-character buffering 带来性能负担。** 对所有 streaming chunk 逐字符分析，几乎没有实际收益，只增加复杂度。

### 删除范围
- `_is_tool_selector_json()` 函数（L13-27）
- character-by-character buffering 逻辑（L42-76）
- 简化 `stream_agent_response()`：直接 yield delta

---

## middleware_registry.py patch 判断

**结论：需要保留**

### 依据

1. **deepagents 内部不处理 const normalization。** PatchToolCallsMiddleware 只处理 dangling tool call。没有 GPT-4o 的 `{"const": "tool_name"}` → `"tool_name"` normalization 逻辑。

2. **langchain LLMToolSelectorMiddleware（tool_selection.py L243-244）期待 string。** 如果传入 const dict，会发生 `"Model selected invalid tools"` ValueError。

3. **用户可能会把 llm_tool_selector 与 GPT-4o 一起设置。** UI 中可选择 middleware。删除 patch 会破坏 GPT-4o + llm_tool_selector 组合。

4. **成本效益：** patch code 30 行。删除风险 > 保留成本。

### 措施
- 保留 `PatchedLLMToolSelectorMiddleware`
- 保留 `_resolve_middleware_class()` 特殊 case
- 未来 langchain 内置 const 处理后再删除

---

## seed 数据不一致

**结论：无不一致（1 个轻微类型提示问题）**

### 验证结果
- M1 删除项（create_mcp_tool 等）：seed 中引用 0 项 ✓
- M2 删除项（Message model 等）：seed 中引用 0 项 ✓
- M3 删除项（skill_executor 等）：seed 中引用 0 项 ✓
- tool seed（17 个）：全部对应 `tool_factory.py` `_BUILTIN_BUILDERS` / `_PREBUILT_REGISTRY` ✓
- model seed（3 个）：全部对应 `model_factory.py` `PROVIDER_MAP` ✓
- template seed（7 个）：引用的 tool 全部存在于 seed ✓

### 轻微问题
- `models/template.py` L20: `recommended_tools: Mapped[dict | None]` — 实际数据为 `list[str]`。schema 中也期望 `list[str] | None`。type hint 写成 `dict`，存在不一致。无功能问题（JSON column 两者都接受）。
- **建议：** 在 M4-S6 将其修改为 `Mapped[list | None]`。

---

## Dead Code 扫描结果

| 项目 | 文件 | 状态 | 措施 |
|------|------|------|------|
| `TokenTrackingCallback` | `token_tracker.py` | 未使用（grep 0 项） | **删除** |
| M1 删除函数引用 | 全部 | grep 0 项 | ✓ 整理完成 |
| M2 删除 model 引用 | 全部 | grep 0 项 | ✓ 整理完成 |
| M3 删除文件引用 | 全部 | grep 0 项 | ✓ 整理完成 |
| 未使用 import | 全部 | 未发现 | ✓ clean |
| 未使用 config 设置 | `config.py` | 未发现 | ✓ 全部被引用 |
| 未使用依赖 | `pyproject.toml` | 未发现 | ✓ 全部使用中 |
| TODO/FIXME/HACK | 全部 | 无 M1-M3 相关 | ✓ clean |

---

## 测试影响

| 测试文件 | 当前测试数 | 影响范围 | 措施 |
|------------|-------------|----------|------|
| `test_creation_agent.py` | 10 | mock 对象变更（`create_chat_model` → `create_deep_agent`） | 重写全部 10 项 |
| `test_agent_creation_extended.py` | 14 | patch 路径变更（间接影响） | 修改 patch decorator |
| `test_trigger_executor.py` | 11 | mock 对象变更（`execute_agent_stream` → `build_agent`） | 重写 7 项，保留 4 项 |
| `test_streaming.py` | — | 删除 character-by-character filter 测试 | 删除 filter 相关 assertion，简化 |
| `test_executor.py` | 14 | 无影响 | 保留 |

---

## creation_agent.py 详细分析

### 当前结构
- **单一函数：** `run_creation_conversation()`（L144-214，71 行）
- **pattern：** `create_chat_model("openai", "gpt-4o")` → `model.ainvoke(lc_messages)` → JSON 提取
- **不使用 tool：** 纯语言生成（不使用 function calling）
- **状态管理：** 从外部以 `conversation_history` list 传入（stateless）

### 外部引用图
```
run_creation_conversation()
  ← agent_creation_service.send_message() (L53)
    ← routers/agent_creation.py POST /api/agents/create-session/{id}/message (L41-54)
```

### 切换 deep agent 的影响度
- **无需修改 signature：** 可保持返回 dict 形式
- **核心变更：** L151 model 创建 + L166 ainvoke → create_deep_agent + invoke
- **保留 JSON 解析逻辑：** L177-199（与 agent framework 无关）
- **service/router 无变更：** interface 相同

---

## trigger_executor.py 详细分析

### 当前结构
- **单一函数：** `execute_trigger()`（L16-92，77 行）
- **pattern：** `execute_agent_stream(...)` async for → SSE 解析 → delta 累积
- **SSE 解析：** L67-77（11 行）— 解析 `"data: "` prefix，JSON decode，提取 delta/content

### 外部引用图
```
execute_trigger()
  ← scheduler.py add_trigger_job()（L39，APScheduler callback 注册）
```

### 切换 direct invoke 的影响度
- **删除整个 SSE 解析：** L67-77（11 行）
- **替换 pattern：** `build_agent()` + `agent.invoke({"messages": [...]}, config)` → result["messages"][-1].content
- **保留 chat_service 调用：** get_agent_with_tools, create_conversation, build_effective_prompt, build_tools_config, build_agent_skills — 全部保留
- **保留 DB 逻辑：** 更新 trigger 状态、增加 run_count

---

## 删除检查表（S7 验证用）

### 立即删除
- [ ] 删除 `token_tracker.py` 文件（或 TokenTrackingCallback class）
- [ ] 删除 `streaming.py` `_is_tool_selector_json()` 函数
- [ ] 删除 `streaming.py` character-by-character buffering 逻辑 → 替换为简单 streaming

### 替换（S3: trigger_executor）
- [ ] `trigger_executor.py` `execute_agent_stream` import → `build_agent` import
- [ ] 删除 `trigger_executor.py` `json` import
- [ ] 将 `trigger_executor.py` SSE 解析 loop（L67-77）→ 直接调用 `build_agent()` + `invoke()`
- [ ] 修改 `test_trigger_executor.py` mock 对象（7 项）：`execute_agent_stream` → `build_agent`

### 替换（S4: creation_agent）
- [ ] `creation_agent.py` `model.ainvoke()` → `create_deep_agent()` + `invoke()`
- [ ] 修改 `creation_agent.py` import
- [ ] 修改 `test_creation_agent.py` mock 对象（10 项）
- [ ] 修改 `test_agent_creation_extended.py` patch 路径

### 整理（S5: streaming/middleware）
- [ ] 删除 `streaming.py` middleware filter code（见上方立即删除项）
- [ ] 修改 `streaming.py` 测试（删除 character-by-character assertion）
- [ ] 确认保留 `PatchedLLMToolSelectorMiddleware`

### 整理（S6: seed/code）
- [ ] 修改 `models/template.py` L20 type hint：`Mapped[dict | None]` → `Mapped[list | None]`
- [ ] 确认删除 `token_tracker.py`
- [ ] 完整 ruff check 通过
- [ ] 完整 pytest 通过
