from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import BaseTool, StructuredTool

from app.agent_runtime.mcp_app_runtime import (
    ResultMetaInterceptor,
    mcp_app_context,
    record_mcp_app_binding,
)
from app.mcp.apps import normalize_tool_ui_meta, tool_allows_visibility
from app.tools.risk import attach_tool_risk, mcp_tool_risk

logger = logging.getLogger(__name__)


def _auth_config_to_headers(auth_config: dict[str, str] | None) -> dict[str, str]:
    """将 auth_config 转换为 HTTP header。"""
    if not auth_config:
        return {}
    if "headers" in auth_config:
        return auth_config["headers"]  # type: ignore[return-value]  # legacy: 传入 dict 形式时
    return {}


def _url_to_server_key(url: str) -> str:
    """将 MCP server URL 转换为唯一 key（包含 host + path）。"""
    parsed = urlparse(url)
    key = parsed.netloc + parsed.path.rstrip("/")
    return key.replace(".", "_").replace(":", "_").replace("/", "_")


class _AuthInjectorInterceptor:
    """调用 MCP 工具时，将 auth_config 值自动注入 arguments。

    实现 langchain-mcp-adapters 的 ToolCallInterceptor protocol。
    在向 MCP server 发送 JSON-RPC tools/call 之前修改 request.args。
    """

    def __init__(self, tool_auth: dict[str, dict]) -> None:
        self.tool_auth = tool_auth  # tool_name → auth_config

    async def __call__(self, request: Any, handler: Any) -> Any:
        auth = self.tool_auth.get(request.name)
        if auth:
            merged = {**auth, **request.args}
            request = request.override(args=merged)
        return await handler(request)


def _hide_auth_params_from_schema(tool: BaseTool, auth_keys: set[str]) -> None:
    """从工具的 dict schema 中移除 auth parameter，对 LLM 隐藏。"""
    schema = tool.args_schema
    if not isinstance(schema, dict) or not auth_keys:
        return
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for key in auth_keys:
        props.pop(key, None)
    schema["required"] = [r for r in required if r not in auth_keys]


def _create_mcp_error_stub(name: str) -> BaseTool:
    """MCP server 连接失败时返回 error 的 stub 工具。"""

    async def _call(**kwargs: Any) -> str:
        return f"MCP tool '{name}' is temporarily unavailable. Please try again later."

    tool = StructuredTool.from_function(
        coroutine=_call,
        name=name,
        description=f"MCP tool (currently unavailable): {name}",
    )
    return attach_tool_risk(tool, mcp_tool_risk(name))


async def _build_mcp_tools(mcp_configs: list[dict]) -> list[BaseTool]:
    """使用 langchain-mcp-adapters 创建 MCP 工具。"""
    if not mcp_configs:
        return []

    from langchain_mcp_adapters.client import MultiServerMCPClient

    # 1. 按 MCP server（URL, transport headers）分组 — 即使 URL 相同，不同
    # connection 也可能使用不同 header（X-Tenant 等），因此只按 URL 分组会在多
    # 租户 MCP gateway 中导致 cross-tenant header 混淆（Codex 第 7 次
    # adversarial P2）。将 header 组合作为 key 的一部分进行隔离。
    servers: dict[str, dict] = {}
    tool_filter: dict[str, set[str]] = {}  # server_key → {tool_names}
    tool_auth: dict[str, dict] = {}  # tool_name → auth_config
    tool_configs: dict[tuple[str, str], dict] = {}  # (server_key, tool_name) → runtime config

    for tc in mcp_configs:
        url = tc["mcp_server_url"]
        tool_name = tc.get("mcp_tool_name", tc["name"])
        # transport header 优先使用 `mcp_transport_headers`（新路径，经 connection
        # 传递）。legacy auth_config["headers"] 也 fallback。
        headers = tc.get("mcp_transport_headers") or _auth_config_to_headers(tc.get("auth_config"))
        # 使用排序后的 JSON 序列化结果的 SHA256 短 hash — 即使 process 重启，相同
        # (url, headers) 组合也会生成相同的 key/name prefix，以保证 deterministic
        # 行为。`hash()` 会因 PYTHONHASHSEED 而 process-randomized，因此在 HiTL
        # resume 时 tool name 会变化（Codex 第 8 次 adversarial F2）。
        headers_digest = hashlib.sha256(
            json.dumps(headers or {}, sort_keys=True).encode()
        ).hexdigest()[:8]
        key = f"{_url_to_server_key(url)}|{headers_digest}"

        if key not in servers:
            servers[key] = {
                "transport": "streamable_http",
                "url": url,
                "headers": headers or None,
            }
            tool_filter[key] = set()

        tool_filter[key].add(tool_name)
        tool_configs[(key, tool_name)] = tc

        auth = tc.get("auth_config")
        if auth:
            tool_auth[tool_name] = auth

    # 收集 auth parameter key（需要从 schema 中隐藏）
    auth_param_keys: set[str] = set()
    for auth in tool_auth.values():
        auth_param_keys.update(auth.keys())

    # interceptor: 在 MCP tools/call 之前将 auth 值注入 arguments
    interceptors: list[Any] = [ResultMetaInterceptor()]
    if tool_auth:
        interceptors.insert(0, _AuthInjectorInterceptor(tool_auth))

    # 2. 按 server 加载 + 过滤工具 — 以 (tool, origin) 对进行追踪
    collected: list[tuple[BaseTool, str]] = []

    from app.agent_runtime.mcp_cache import MCPToolWithRetry, get_cached_mcp_tools
    from app.config import settings as _settings

    for key, config in servers.items():
        try:

            async def _load_server_tools(
                *,
                cache_key: str = key,
                server_config: dict[str, Any] = config,
            ) -> list[BaseTool]:
                client = MultiServerMCPClient(
                    {cache_key: server_config},  # type: ignore[arg-type]  # dict 与 Connection TypedDict 兼容
                    tool_interceptors=interceptors,  # type: ignore[arg-type]
                )
                return await asyncio.wait_for(
                    client.get_tools(),
                    timeout=_settings.mcp_connection_timeout,
                )

            server_tools = await get_cached_mcp_tools(
                key,
                _load_server_tools,
                ttl_seconds=max(1.0, float(_settings.mcp_connection_timeout) * 30),
            )
            needed = tool_filter[key]
            for t in server_tools:
                if t.name in needed:
                    _hide_auth_params_from_schema(t, auth_param_keys)
                    risk_config = dict(tool_configs.get((key, t.name), {}))
                    risk_config.setdefault("definition_key", "mcp")
                    risk_config.setdefault("name", t.name)
                    risk_config.setdefault("mcp_tool_name", t.name)
                    risk_config.setdefault("mcp_server_url", config.get("url"))
                    if t.description and not risk_config.get("description"):
                        risk_config["description"] = t.description
                    metadata = getattr(t, "metadata", None)
                    raw_meta = metadata.get("_meta") if isinstance(metadata, dict) else None
                    tool_ui_meta = normalize_tool_ui_meta(raw_meta)
                    if tool_ui_meta is not None and not tool_allows_visibility(
                        tool_ui_meta, "model"
                    ):
                        continue
                    app_context = mcp_app_context(
                        tool_configs.get((key, t.name)),
                        tool_ui_meta,
                    )
                    wrapped = MCPToolWithRetry(
                        t,
                        max_retries=2,
                        retry_delay=0.25,
                        timeout_seconds=float(_settings.mcp_connection_timeout),
                        mcp_app_context=app_context,
                        binding_recorder=(
                            record_mcp_app_binding if app_context is not None else None
                        ),
                    )
                    attach_tool_risk(
                        wrapped,
                        mcp_tool_risk(
                            wrapped.name,
                            metadata=metadata if isinstance(metadata, dict) else None,
                            config=risk_config,
                        ),
                    )
                    collected.append((wrapped, key))
        except Exception:
            logger.warning("MCP tool loading failed for %s", key, exc_info=True)
            for tool_name in tool_filter[key]:
                collected.append((_create_mcp_error_stub(tool_name), key))

    # 3. 重名 disambiguation — 添加 server key 作为 prefix
    name_counts: dict[str, int] = {}
    for tool, _ in collected:
        name_counts[tool.name] = name_counts.get(tool.name, 0) + 1

    if any(c > 1 for c in name_counts.values()):
        for tool, origin in collected:
            if name_counts.get(tool.name, 0) > 1:
                tool.name = f"{origin}_{tool.name}"

    return [tool for tool, _ in collected]
