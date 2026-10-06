# ADR-001：替换 Deep Agent 引擎

## 状态：已提议

## 背景

Moldy 的 AI agent 执行引擎目前通过两条路径创建 agent：

1. `langchain.agents.create_agent` —— 支持 middleware，ImportError 时 fallback
2. `langgraph.prebuilt.create_react_agent` —— fallback，忽略 middleware

MCP 工具在 `mcp_client.py` 中自行实现 HTTP/StreamableHTTP 协议并调用。
该结构的问题：

- **双路径**：create_agent / create_react_agent fallback 导致行为难以预测
- **MCP 自行实现**：协议变化时需要自行维护
- **工具名称冲突**：在 chat_service.py 中手动维护去重逻辑

引入 `deepagents` package 的 `create_deep_agent()` 与 `langchain-mcp-adapters` 的 `MultiServerMCPClient`，统一为单一路径。

---

## 决定

### 1. `build_agent()` → 替换为 `create_deep_agent()`

**当前签名**（`executor.py:27-57`）：
```python
def build_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    middleware: list | None = None,
) -> Any:
    # 尝试 create_agent → ImportError 时 fallback 到 create_react_agent
```

**新签名**：
```python
def build_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    middleware: list | None = None,
    checkpointer: Checkpointer | None = None,
) -> CompiledStateGraph:
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware or [],
        checkpointer=checkpointer,
    )
```

**变更事项：**
- 移除 `create_agent` + `create_react_agent` 双路径
- 单独调用 `create_deep_agent`
- 添加 `checkpointer` 参数（集成 LangGraph checkpoint）
- 明确返回类型为 `CompiledStateGraph`（与现有 interface 相同）
- `middleware` 默认处理为空 list（移除 None 分支）

### 2. MCP 工具生成：`create_mcp_tool()` → `MultiServerMCPClient`

**当前方式**（`executor.py:93-104`, `tool_factory.py:319+`）：
```python
# executor.py —— 为每个 MCP 工具分别调用 create_mcp_tool()
elif tc.get("type") == "mcp" and tc.get("mcp_server_url"):
    tool = create_mcp_tool(name, description, mcp_server_url, mcp_tool_name, auth_config, ...)
    langchain_tools.append(tool)
```

每个 MCP 工具通过单独 HTTP call 执行。`call_mcp_tool()` 每次调用都会打开并关闭 `streamablehttp_client()` session。

**新方式**：
```python
# executor.py —— 在 execute_agent_stream() 内
mcp_servers = {}
for tc in tools_config:
    if tc.get("type") == "mcp" and tc.get("mcp_server_url"):
        server_url = tc["mcp_server_url"]
        headers = _auth_config_to_headers(tc.get("auth_config"))
        server_key = _url_to_server_key(server_url)
        mcp_servers[server_key] = {
            "transport": "streamable_http",
            "url": server_url,
            "headers": headers,
        }

if mcp_servers:
    from langchain_mcp_adapters import MultiServerMCPClient

    async with MultiServerMCPClient(mcp_servers, tool_name_prefix=True) as client:
        mcp_tools = await client.get_tools()
        langchain_tools.extend(mcp_tools)
```

**变更事项：**
- 移除 `create_mcp_tool()` —— 无需逐个创建工具
- 移除 `_build_args_schema()` —— `get_tools()` 自动生成 schema
- 移除 `call_mcp_tool()` —— 工具执行由 LangChain Tool interface 自动处理
- `tool_name_prefix=True` —— 按服务器添加 prefix，自动解决名称冲突
- 需要将 `auth_config` 转换为 HTTP `headers` 的 helper

### 3. 移除 `chat_service.py` 中的 MCP 名称去重逻辑

**当前**（`chat_service.py:201-214`）：
```python
# Disambiguate duplicate MCP tool names by adding server prefix
name_counts: dict[str, int] = {}
for tc in tools_config:
    if tc.get("type") == "mcp":
        ...
```

**变更**：删除整个 block。`MultiServerMCPClient` 的 `tool_name_prefix=True` 提供相同功能。

### 4. `execute_agent_stream()` 签名 —— 不变

```python
async def execute_agent_stream(
    provider, model_name, api_key, base_url,
    system_prompt, tools_config, messages_history, thread_id,
    model_params=None, middleware_configs=None,
) -> AsyncGenerator[str, None]:
```

对外部 caller（`conversations.py`, `trigger_executor.py`）无影响，仅修改内部实现。

---

## 替代方案

### Option A：全面替换为 create_deep_agent（选择）

- **优点**：单一路径、原生支持 middleware、集成 checkpointer、简化代码
- **缺点**：增加 deepagents package dependency，API 变化时需要跟进

### Option B：只升级 create_agent（驳回）

- **优点**：变更最小
- **缺点**：create_react_agent fallback 仍存在，MCP 自行实现保留，middleware 集成不完整

### Option C：直接使用 LangGraph functional API（驳回）

- **优点**：灵活性最大
- **缺点**：boilerplate 大幅增加，需要手动集成 middleware

---

## 变更文件摘要

| 文件 | 变更类型 | 详情 |
|------|-----------|------|
| `executor.py` | **修改** | `build_agent()` 内部 → `create_deep_agent()`。MCP tool loop → `MultiServerMCPClient` async context。 |
| `tool_factory.py` | **删除（部分）** | 移除 `create_mcp_tool()`、`_build_args_schema()`。保留 builtin/prebuilt/custom。 |
| `mcp_client.py` | **删除（部分）** | 移除 `call_mcp_tool()`、`_extract_text()`。保留 `test_mcp_connection()`、`list_mcp_tools()`（用于 MCP 服务器注册 UI）。 |
| `chat_service.py` | **删除（部分）** | 删除 MCP 名称去重 block（~14 行）。 |
| `pyproject.toml` | **修改** | 添加 `deepagents`、`langchain-mcp-adapters` dependency。 |

### 保留的 module（不变）

| 文件 | 原因 |
|------|------|
| `streaming.py` | `create_deep_agent` 也返回 `CompiledStateGraph` → `astream()` 相同 |
| `model_factory.py` | LLM instance 创建与 engine 无关 |
| `middleware_registry.py` | 原样传入 `create_deep_agent` 的 `middleware` 参数 |
| `message_utils.py` | message format 转换——与 engine 无关 |
| `trigger_executor.py` | 保持 `execute_agent_stream()` 签名 |
| `conversations.py` | 保持 `execute_agent_stream()` 签名 |

---

## 新 helper function（executor.py 内部）

```python
def _auth_config_to_headers(auth_config: dict | None) -> dict[str, str]:
    """将 auth_config 转换为 HTTP header。
    
    支持 pattern：
    - {"api_key": "..."} → {"Authorization": "Bearer ..."}
    - {"jwt_token": "..."} → {"Authorization": "Bearer ..."}
    - {"headers": {...}} → 原样返回
    """
    if not auth_config:
        return {}
    if "headers" in auth_config:
        return auth_config["headers"]
    token = auth_config.get("api_key") or auth_config.get("jwt_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _url_to_server_key(url: str) -> str:
    """将 MCP 服务器 URL 转换为唯一 key。"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc.replace(".", "_").replace(":", "_")
```

---

## execute_agent_stream() 新内部结构

```python
async def execute_agent_stream(...) -> AsyncGenerator[str, None]:
    model = create_chat_model(provider, model_name, api_key, base_url, **(model_params or {}))

    langchain_tools: list[BaseTool] = []
    mcp_servers: dict[str, dict] = {}

    for tc in tools_config:
        match tc.get("type"):
            case "builtin":
                langchain_tools.append(create_builtin_tool(tc["name"]))
            case "prebuilt":
                langchain_tools.append(create_prebuilt_tool(tc["name"], auth_config=tc.get("auth_config")))
            case "custom" if tc.get("api_url"):
                langchain_tools.append(create_tool_from_db(...))
            case "mcp" if tc.get("mcp_server_url"):
                # MCP 工具按服务器收集 → 通过 MultiServerMCPClient 批量生成
                server_key = _url_to_server_key(tc["mcp_server_url"])
                mcp_servers[server_key] = {
                    "transport": "streamable_http",
                    "url": tc["mcp_server_url"],
                    "headers": _auth_config_to_headers(tc.get("auth_config")),
                }
            case "skill_package":
                langchain_tools.extend(create_skill_tools(...))

    middleware = build_middleware_instances(middleware_configs or [])
    middleware += get_provider_middleware(provider)

    # 存在 MCP 工具时，在 async context 内执行 agent
    if mcp_servers:
        from langchain_mcp_adapters import MultiServerMCPClient

        async with MultiServerMCPClient(mcp_servers, tool_name_prefix=True) as client:
            mcp_tools = await client.get_tools()
            langchain_tools.extend(mcp_tools)
            agent = build_agent(model, langchain_tools, system_prompt, middleware=middleware or None)
            lc_messages = convert_to_langchain_messages(messages_history)
            config = {"configurable": {"thread_id": thread_id}}
            async for chunk in stream_agent_response(agent, lc_messages, config):
                yield chunk
    else:
        agent = build_agent(model, langchain_tools, system_prompt, middleware=middleware or None)
        lc_messages = convert_to_langchain_messages(messages_history)
        config = {"configurable": {"thread_id": thread_id}}
        async for chunk in stream_agent_response(agent, lc_messages, config):
            yield chunk
```

**核心**：`MultiServerMCPClient` 是 async context manager，只在存在 MCP 工具时激活。agent 执行必须在 context 内完成，才能保持 MCP 连接。

---

## 结果

- **简化**：agent 创建路径 2 条 → 1 条
- **MCP 稳定性**：自行实现 → 官方 adapter、connection pooling、自动 schema
- **名称冲突**：手动去重逻辑 → `tool_name_prefix` 自动处理
- **代码删除量**：删除 ~100 行（`create_mcp_tool`、`_build_args_schema`、`call_mcp_tool`、去重 block）
- **外部 API 无变更**：保持 `execute_agent_stream()` 签名
- **风险**：需要确认 `deepagents` package 稳定性，以及 `MultiServerMCPClient` 的 streamable_http 支持
