## M1 删除分析报告

> 分析日期：2026-04-05
> 分析对象：SPEC.md M1 milestone — 依赖关系 + engine 替换（基础）

---

### 可立即删除（M1 scope）

#### 1. `create_mcp_tool()` — tool_factory.py:319-346

将 MCP server tool 手动包装为 LangChain StructuredTool 的函数。
由 `langchain-mcp-adapters` 的 `load_mcp_tools()` 替代。

- **引用代码：**
  - `executor.py:94` — `from app.agent_runtime.tool_factory import create_mcp_tool` (lazy import)
  - `executor.py:96-103` — 调用 `create_mcp_tool()`（type == "mcp" 分支）
- **测试引用：** 无（测试中没有直接 import）

#### 2. `_build_args_schema()` — tool_factory.py:298-316

JSON Schema → Pydantic model 转换。仅在 `create_mcp_tool()` 内使用。

- **引用代码：**
  - `tool_factory.py:339` — 在 `create_mcp_tool()` 内调用
- **测试引用：** 无
- **备注：** 因为是 `create_mcp_tool()` 的内部依赖，所以一起删除

#### 3. `call_mcp_tool()` — mcp_client.py:106-120

在 MCP server 上执行 tool 的函数。由 `langchain-mcp-adapters` adapter 替代。

- **引用代码：**
  - `tool_factory.py:328` — `from app.agent_runtime.mcp_client import call_mcp_tool` (lazy import)
  - `tool_factory.py:334` — 在 `create_mcp_tool()` 内部 closure 中调用
- **测试引用：** 无
- **备注：** 删除 `create_mcp_tool()` 后所有引用都会消失

#### 4. `_extract_text()` — mcp_client.py:76-82

仅由 `call_mcp_tool()` 内部使用的 helper 函数。从 CallToolResult.content 提取 text。

- **引用代码：**
  - `mcp_client.py:115` — 在 `call_mcp_tool()` 内调用
- **备注：** 删除 `call_mcp_tool()` 后不再有使用处。一起删除

#### 5. MCP 名称加工/重复检测逻辑 — chat_service.py:201-214

给重复的 MCP tool 名添加 server host 前缀的逻辑。
`langchain-mcp-adapters` 会处理 tool 名管理，因此不再需要。

- **引用代码：** `build_tools_config()` 内部逻辑（无外部引用）
- **影响范围：**
  - `chat_service.py:195-198` — 设置 MCP tool 的 `mcp_server_url`, `mcp_tool_name`（整个 type == "mcp" 分支）
  - `chat_service.py:201-214` — 基于 name_counts 的重复检测 + urlparse 重命名
- **测试引用：** 无（无直接测试）

#### 6. `create_react_agent` fallback 逻辑 — executor.py:27-57

整个 `build_agent()` 函数。尝试 `create_agent` → 失败时 fallback 到 `create_react_agent`。
将完全替换为 `create_deep_agent`，因此该函数本身需要重写。

- **引用代码：**
  - `executor.py:9` — `from langgraph.prebuilt import create_react_agent` (import)
  - `executor.py:120` — 调用 `build_agent()`
- **测试引用：**
  - `test_executor.py:14` — `@patch("app.agent_runtime.executor.create_react_agent")`
  - `test_executor.py:30` — `@patch("app.agent_runtime.executor.create_react_agent")`
  - `test_executor.py:15-27` — `test_build_agent_calls_langgraph`
  - `test_executor.py:31-38` — `test_build_agent_returns_agent`

#### 7. executor.py MCP tool 分支 — executor.py:93-104

`execute_agent_stream()` 内 type == "mcp" 分支。lazy import + 调用 `create_mcp_tool()`。

- **引用代码：** `execute_agent_stream()` 内部（无外部引用）
- **备注：** 将 MCP tool 创建改为 `langchain-mcp-adapters` 时，需要重写整个分支

---

### 删除时需要修改的代码

| 文件:行 | 当前引用 | 修改方式 |
|-----------|----------|----------|
| `executor.py:9` | `from langgraph.prebuilt import create_react_agent` | 删除（替换为 create_deep_agent import） |
| `executor.py:18-21` | `from app.agent_runtime.tool_factory import create_builtin_tool, create_prebuilt_tool, create_tool_from_db` | 删除 `create_mcp_tool` import（目前已是 lazy import，因此无影响） |
| `executor.py:27-57` | 整个 `build_agent()` 函数 | 重写为调用 `create_deep_agent()` |
| `executor.py:93-104` | type == "mcp" 分支 | 基于 `langchain-mcp-adapters` 重写 |
| `executor.py:105-114` | type == "skill_package" 分支 | 计划在 M3 删除。M1 中保留 |
| `chat_service.py:195-198` | MCP tool 的 `mcp_server_url`, `mcp_tool_name` 设置 | 按新的 MCP tool 处理方式修改（adapter 直接使用 URL） |
| `chat_service.py:201-214` | MCP 名称重复检测逻辑 | 全部删除（由 adapter 处理） |
| `chat_service.py:210` | `from urllib.parse import urlparse`（lazy import） | 删除重复检测逻辑时一并移除 |
| `test_executor.py:14-38` | 2 个 `build_agent()` 测试 | 按 `create_deep_agent` 重写 |
| `test_executor.py:394` | MCP tool config mock | 需要更新测试 |
| `conversations.py:109` | `save_message()` 调用 | M2 scope（M1 中保留） |
| `conversations.py:115` | `list_messages()` 调用 | M2 scope（M1 中保留） |
| `conversations.py:147` | `save_message()` 调用 | M2 scope（M1 中保留） |
| `trigger_executor.py:43,84` | `save_message()` 调用 | M2 scope（M1 中保留） |

---

### 安全删除顺序

1. **`_build_args_schema()`**（tool_factory.py:298-316）— 仅在 `create_mcp_tool()` 内使用。可安全优先删除
2. **`call_mcp_tool()` + `_extract_text()`**（mcp_client.py:76-120）— 仅在 `create_mcp_tool()` 内引用。可在删除 `create_mcp_tool()` 前先移除
3. **`create_mcp_tool()`**（tool_factory.py:319-346）— 删除上述两个依赖后可安全删除
4. **executor.py type == "mcp" 分支**（executor.py:93-104）— 删除 `create_mcp_tool()` 后，把此分支替换为 langchain-mcp-adapters
5. **chat_service.py MCP 名称加工/重复检测**（chat_service.py:195-214 内 MCP 相关部分）— executor.py 替换后删除
6. **`build_agent()` 函数 + create_react_agent import**（executor.py:9, 27-57）— 重写为 `create_deep_agent()`。这是核心替换，因此在整理 MCP 后执行

> **原则：** 从叶子（leaf）到树干依次删除。先删无引用项，避免中途产生 broken reference。

---

### 必须保留的代码（注意！）

| 函数/文件 | 位置 | 保留原因 |
|-----------|------|----------|
| `test_mcp_connection()` | mcp_client.py:10-73 | 用于 MCP server 注册 UI 的连接测试。由 `routers/tools.py:64` import |
| `list_mcp_tools()` | mcp_client.py:85-103 | 用于 MCP server tool discovery UI。由 `services/tool_service.py:59` import |
| `create_builtin_tool()` | tool_factory.py:164-169 | 创建 builtin tool（DuckDuckGo, Scraper, DateTime）。基于 Python，不能由 MCP 替代 |
| `create_prebuilt_tool()` | tool_factory.py:269-295 | 创建 prebuilt API tool（Naver, Google）。基于 Python，不能由 MCP 替代 |
| `create_tool_from_db()` | tool_factory.py:134-150 | 创建 custom HTTP tool。用户自定义 tool 需要 |
| `_build_http_tool_func()` | tool_factory.py:100-131 | `create_tool_from_db()` 的内部依赖 |
| `_BUILTIN_BUILDERS` | tool_factory.py:157-161 | `create_builtin_tool()` 内部 registry |
| `_PREBUILT_REGISTRY` | tool_factory.py:179-266 | `create_prebuilt_tool()` 内部 registry |
| `build_effective_prompt()` | chat_service.py:169-175 | 到 M3 为止用于注入 skill。M1 中保留 |
| `build_tools_config()` | chat_service.py:178-232 | 构建 tool config。只修改 MCP 相关部分，函数本身保留 |
| `save_message()` | chat_service.py:73-104 | M2 scope。M1 中保留 |
| `list_messages()` | chat_service.py:61-70 | M2 scope。M1 中保留 |
| `model_factory.py` | 整个文件 | 创建 LLM instance。无变更 |
| `streaming.py` | 整个文件 | SSE 转换。无变更 |
| `message_utils.py` | 整个文件 | 消息转换 utility |
| `middleware_registry.py` | 整个文件 | 构建 middleware。传给 create_deep_agent |

---

### 需要评估删除（M1 scope 外）

| 项目 | 文件 | 原因 | 风险 |
|------|------|------|--------|
| `TokenTrackingCallback` | token_tracker.py | production code 中未使用（仅存在测试）。FR-7 计划用 astream() usage_metadata 替代 | 低 — M4 判断 |
| `skill_tool_factory.py` | 整个文件 | 计划在 M3 用 `create_deep_agent(skills=[...])` 替代 | M3 scope |
| `skill_executor.py` | 整个文件 | 计划在 M3 用 deep agent FilesystemMiddleware 替代 | M3 scope |
| executor.py type == "skill_package" 分支 | executor.py:105-114 | 计划在 M3 删除 | M3 scope |
| `build_effective_prompt()` skill 注入 | chat_service.py:169-175 | 计划在 M3 删除 | M3 scope |
| `build_tools_config()` skill_package 分支 | chat_service.py:216-230 | 计划在 M3 删除 | M3 scope |
| `creation_agent.py` | 整个文件 | 计划在 M4 改为基于 create_deep_agent | M4 scope |
| `fix_agent.py` | 整个文件 | 可在 M4 改为基于 create_deep_agent | M4 scope，优先级低 |
| `save_message()`, `list_messages()` | chat_service.py:61-104 | M2 切换到 checkpointer 时删除/替换 | M2 scope |
| `trigger_executor.py` save_message 调用 | trigger_executor.py:43,84 | M2+M4 中改为 deep agent invoke() | M2/M4 scope |

---

### 简化建议

| 项目 | 当前 | 建议 | milestone |
|------|------|------|---------|
| MCP tool 创建路径 | `chat_service.build_tools_config()` → 创建 MCP config dict → `executor.py` → `create_mcp_tool()` → `call_mcp_tool()`（3 层包装） | `executor.py` → 直接调用 `langchain-mcp-adapters` `load_mcp_tools()`（1 层） | M1 |
| `build_agent()` 函数 | try create_agent → except → create_react_agent（fallback pattern） | 直接调用 `create_deep_agent()`（无 fallback） | M1 |
| `mcp_client.py` 文件大小 | 3 个函数（120 lines） | 2 个函数（103 lines）— 删除 `call_mcp_tool()` + `_extract_text()` 后 | M1 |
| `tool_factory.py` 文件大小 | builtin + prebuilt + custom + MCP（347 lines） | 仅 builtin + prebuilt + custom（296 lines）— 删除 MCP 相关 51 lines | M1 |

---

### 删除影响摘要

| 删除对象 | production code 引用 | 测试引用 | 安全度 |
|-----------|-------------------|------------|--------|
| `_build_args_schema()` | `tool_factory.py` 内部 1 处 | 无 | 安全 |
| `create_mcp_tool()` | `executor.py` 1 处（lazy import） | 无 | 安全（重写 executor 时） |
| `call_mcp_tool()` | `tool_factory.py` 内部 1 处 | 无 | 安全 |
| `_extract_text()` | `mcp_client.py` 内部 1 处 | 无 | 安全 |
| MCP 名称加工逻辑 | `chat_service.py` 内部 | 无 | 安全 |
| 重写 `build_agent()` | `executor.py` 内部 1 处 | `test_executor.py` 2 处 | 需要重写测试 |
| `create_react_agent` import | `executor.py:9` | `test_executor.py` 2 处 | 需要重写测试 |
