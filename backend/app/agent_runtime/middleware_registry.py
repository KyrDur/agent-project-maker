"""Middleware registry for AI agent middleware configuration.

Defines 22 middleware types that can be attached to agents.
Actual langchain.agents.middleware imports are deferred — if the package
is not yet installed, build_middleware_instances() returns an empty list.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry: 22 middleware definitions
# ---------------------------------------------------------------------------

MIDDLEWARE_REGISTRY: dict[str, dict[str, Any]] = {
    # ---- context (3) ----
    "summarization": {
        "name": "SummarizationMiddleware",
        "display_name": "对话自动摘要",
        "description": "达到 token 上限时自动摘要对话历史",
        "category": "context",
        "config_schema": {
            "trigger": {
                "type": "tuple",
                "default": ["tokens", 4000],
                "description": "摘要触发条件 (tokens/messages, 值)",
            },
            "keep": {
                "type": "tuple",
                "default": ["messages", 20],
                "description": "摘要时保留的消息数量",
            },
            "model": {
                "type": "string",
                "default": "openai:gpt-5.4-mini",
                "description": "用于摘要的模型",
            },
        },
        "provider_specific": None,
    },
    "context_editing": {
        "name": "ContextEditingMiddleware",
        "display_name": "上下文清理",
        "description": "清理旧的工具结果以管理上下文窗口",
        "category": "context",
        "config_schema": {},
        "provider_specific": None,
    },
    "filesystem": {
        "name": "FilesystemMiddleware",
        "display_name": "文件系统访问",
        "description": "为 Agent 提供文件读取/写入/编辑工具",
        "category": "context",
        "config_schema": {},
        "provider_specific": None,
    },
    # ---- planning (2) ----
    "todo_list": {
        "name": "TodoListMiddleware",
        "display_name": "任务规划与追踪",
        "description": "Agent 规划复杂任务并追踪进度",
        "category": "planning",
        "config_schema": {},
        "provider_specific": None,
    },
    "subagent": {
        "name": "SubAgentMiddleware",
        "display_name": "子 Agent 委派",
        "description": "将任务委派给专业子 Agent，以分工处理复杂任务",
        "category": "planning",
        "config_schema": {},
        "provider_specific": None,
    },
    # ---- safety (3) ----
    "human_in_the_loop": {
        "name": "HumanInTheLoopMiddleware",
        "display_name": "用户审批门控",
        "description": "执行危险工具前请求用户批准",
        "category": "safety",
        "config_schema": {
            "interrupt_on": {
                "type": "object",
                "default": {},
                "description": "需要审批的工具列表（工具名: true）",
            },
        },
        "provider_specific": None,
    },
    "pii": {
        "name": "PIIMiddleware",
        "display_name": "PII 保护",
        "description": "检测并掩码个人身份信息（邮箱、信用卡、IP 等）",
        "category": "safety",
        # langchain 1.3 PIIMiddleware 只接受单个 pii_type 值（之前会自动进行多类型检测）。
        # 默认使用 ``email``，需要检测多种类型的用户可多次注册该中间件。
        "config_schema": {
            "pii_type": {
                "type": "string",
                "default": "email",
                "description": "要检测的 PII 类型 (email | credit_card | ip | mac_address | url)",
            },
            "strategy": {
                "type": "string",
                "default": "redact",
                "description": "检测后的处理方式 (block | redact | mask | hash)",
            },
        },
        "provider_specific": None,
    },
    "shell_tool": {
        "name": "ShellToolMiddleware",
        "display_name": "Shell 命令执行",
        "description": "为 Agent 提供持久化 Shell 会话",
        "category": "safety",
        "config_schema": {},
        "provider_specific": None,
    },
    # ---- reliability (7) ----
    "llm_tool_selector": {
        "name": "LLMToolSelectorMiddleware",
        "display_name": "工具自动选择",
        "description": "LLM 仅选择相关工具以提升准确率",
        "category": "reliability",
        "config_schema": {},
        "provider_specific": None,
    },
    "model_call_limit": {
        "name": "ModelCallLimitMiddleware",
        "display_name": "模型调用限制",
        "description": "限制 LLM 调用次数以防止无限循环",
        "category": "reliability",
        "config_schema": {
            "thread_limit": {
                "type": "integer",
                "default": 100,
                "description": "每线程最大模型调用次数",
            },
            "run_limit": {
                "type": "integer",
                "default": 5,
                "description": "每次运行最大模型调用次数",
            },
            "exit_behavior": {
                "type": "string",
                "default": "end",
                "description": "超出限制时的行为 (end/error)",
            },
        },
        "provider_specific": None,
    },
    "tool_retry": {
        "name": "ToolRetryMiddleware",
        "display_name": "工具重试",
        "description": "工具失败时使用指数退避自动重试",
        "category": "reliability",
        "config_schema": {
            "max_retries": {
                "type": "integer",
                "default": 3,
                "description": "最大重试次数",
            },
        },
        "provider_specific": None,
    },
    "tool_call_limit": {
        "name": "ToolCallLimitMiddleware",
        "display_name": "工具调用限制",
        "description": "限制工具调用次数",
        "category": "reliability",
        "config_schema": {
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "最大工具调用次数",
            },
        },
        "provider_specific": None,
    },
    "model_fallback": {
        "name": "ModelFallbackMiddleware",
        "display_name": "模型自动切换",
        "description": "主模型失败时自动切换到备用模型",
        "category": "reliability",
        "config_schema": {
            "fallback_model": {
                "type": "string",
                "default": "openai:gpt-5.4",
                "description": "备用模型标识符",
            },
        },
        "provider_specific": None,
    },
    "model_retry": {
        "name": "ModelRetryMiddleware",
        "display_name": "模型调用重试",
        "description": "LLM 调用失败时使用指数退避重试",
        "category": "reliability",
        "config_schema": {
            "max_retries": {
                "type": "integer",
                "default": 2,
                "description": "最大重试次数",
            },
        },
        "provider_specific": None,
    },
    "file_search": {
        "name": "FilesystemFileSearchMiddleware",
        "display_name": "搜索文件",
        "description": "在大型文档中提供 glob/grep 搜索功能",
        "category": "reliability",
        "config_schema": {},
        "provider_specific": None,
    },
    "llm_tool_emulator": {
        "name": "LLMToolEmulator",
        "display_name": "工具模拟器",
        "description": "使用 LLM 模拟工具执行（用于测试）",
        "category": "reliability",
        "config_schema": {},
        "provider_specific": None,
    },
    # ---- provider-specific (6) ----
    "anthropic_prompt_caching": {
        "name": "AnthropicPromptCachingMiddleware",
        "display_name": "Anthropic 提示词缓存",
        "description": "缓存系统提示词，最高可节省 75% 成本",
        "category": "provider",
        "config_schema": {},
        "provider_specific": "anthropic",
    },
    "anthropic_memory": {
        "name": "StateClaudeMemoryMiddleware",
        "display_name": "Anthropic 持久记忆",
        "description": "使用 Anthropic 的持久记忆功能",
        "category": "provider",
        "config_schema": {},
        "provider_specific": "anthropic",
    },
    "anthropic_bash_tool": {
        "name": "ClaudeBashToolMiddleware",
        "display_name": "Anthropic Bash 工具",
        "description": "在 Claude 模型中支持执行 Bash 命令",
        "category": "provider",
        "config_schema": {},
        "provider_specific": "anthropic",
    },
    "anthropic_file_search": {
        "name": "StateFileSearchMiddleware",
        "display_name": "Anthropic 文件搜索",
        "description": "在 Claude 模型中支持大型文档搜索",
        "category": "provider",
        "config_schema": {},
        "provider_specific": "anthropic",
    },
    "anthropic_text_editor": {
        "name": "StateClaudeTextEditorMiddleware",
        "display_name": "Anthropic 文本编辑器",
        "description": "在 Claude 模型中支持文本编辑工具",
        "category": "provider",
        "config_schema": {},
        "provider_specific": "anthropic",
    },
    "openai_moderation": {
        "name": "OpenAIModerationMiddleware",
        "display_name": "OpenAI 内容审核",
        "description": "在 GPT 模型中检查内容安全性",
        "category": "provider",
        "config_schema": {},
        "provider_specific": "openai",
    },
}

# Map middleware type key → class name for dynamic import
_CLASS_MAP: dict[str, str] = {k: v["name"] for k, v in MIDDLEWARE_REGISTRY.items()}

_MODULE_MAP: dict[str, str] = {
    "anthropic_prompt_caching": "langchain_anthropic.middleware",
    "anthropic_memory": "langchain_anthropic.middleware",
    "anthropic_bash_tool": "langchain_anthropic.middleware",
    "anthropic_file_search": "langchain_anthropic.middleware",
    "anthropic_text_editor": "langchain_anthropic.middleware",
    "openai_moderation": "langchain_openai.middleware",
}


def _patched_llm_tool_selector_class() -> type | None:
    """Return a patched LLMToolSelectorMiddleware that normalizes response format.

    ADR-004: deepagents 不会在内部处理 {"const": "name"} 规范化。
    GPT-4o + llm_tool_selector 组合在没有补丁时会出错。需要保留。

    GPT-4o sometimes returns {"const": "tool_name"} objects instead of plain
    "tool_name" strings when using structured output with const schemas.
    This subclass normalizes both formats before processing.
    """
    try:
        from langchain.agents.middleware import LLMToolSelectorMiddleware
    except (ImportError, ModuleNotFoundError):
        return None

    class PatchedLLMToolSelectorMiddleware(LLMToolSelectorMiddleware):
        def _process_selection_response(
            self,
            response: dict[str, Any],
            available_tools: list[Any],
            valid_tool_names: list[str],
            request: Any,
        ) -> list[Any]:
            # Normalize {"const": "name"} objects to plain "name" strings
            if "tools" in response:
                normalized = []
                for item in response["tools"]:
                    if isinstance(item, dict) and "const" in item:
                        normalized.append(item["const"])
                    elif isinstance(item, str):
                        normalized.append(item)
                    else:
                        normalized.append(str(item))
                response = {**response, "tools": normalized}
            return super()._process_selection_response(  # type: ignore[misc]
                response, available_tools, valid_tool_names, request
            )

    return PatchedLLMToolSelectorMiddleware


def _resolve_middleware_class(middleware_type: str) -> type | None:
    """Attempt to import a middleware class from its owning package.

    Returns None if the package is not installed or the class is unavailable.
    """
    # Use patched version for llm_tool_selector
    if middleware_type == "llm_tool_selector":
        return _patched_llm_tool_selector_class()

    class_name = _CLASS_MAP.get(middleware_type)
    if not class_name:
        return None
    try:
        import importlib

        module = importlib.import_module(
            _MODULE_MAP.get(middleware_type, "langchain.agents.middleware")
        )
        return getattr(module, class_name, None)
    except (ImportError, ModuleNotFoundError):
        return None


def _coerce_tuple_params(params: dict[str, Any], config_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert list values back to tuples for parameters declared as tuple type."""
    result = dict(params)
    for key, schema in config_schema.items():
        if schema.get("type") == "tuple" and key in result and isinstance(result[key], list):
            result[key] = tuple(result[key])
    return result


def build_middleware_instances(middleware_configs: list[dict[str, Any]]) -> list:
    """Build middleware instances from a list of config dicts.

    Each dict must have:
      - "type": middleware registry key (e.g. "summarization")
      - "params": optional dict of constructor kwargs

    Returns a list of middleware instances. If langchain.agents.middleware
    is not importable, returns an empty list.
    """
    instances: list = []
    for config in middleware_configs:
        middleware_type = config.get("type", "")
        params = config.get("params", {})

        registry_entry = MIDDLEWARE_REGISTRY.get(middleware_type)
        if not registry_entry:
            logger.warning("Unknown middleware type: %s", middleware_type)
            continue

        cls = _resolve_middleware_class(middleware_type)
        if cls is None:
            logger.warning(
                "Middleware class for '%s' not available. Skipping.",
                middleware_type,
            )
            continue

        coerced = _coerce_tuple_params(params, registry_entry.get("config_schema", {}))
        # 适配 langchain 1.3 中间件签名变更：
        # config_schema 中存在 default，但 params 中缺失的键用 default 补齐。
        # ``ModelCallLimitMiddleware`` 必须提供 thread_limit/run_limit 中的至少一个，
        # 并且 ``PIIMiddleware`` 的 ``pii_type`` 是 positional required。
        for key, schema in registry_entry.get("config_schema", {}).items():
            if key not in coerced and "default" in schema:
                coerced[key] = schema["default"]

        if middleware_type == "tool_call_limit" and "limit" in coerced:
            coerced.setdefault("run_limit", coerced.pop("limit"))

        # tool_retry: GraphInterrupt 是正常的 HiTL 信号，因此
        # 不进行重试并 re-raise，使图暂停正常向上传播
        if middleware_type == "tool_retry":
            from langgraph.errors import GraphInterrupt

            def _on_failure_reraise_interrupt(exc: Exception) -> str:
                if isinstance(exc, GraphInterrupt):
                    raise exc
                return f"Tool failed after retries: {exc}"

            coerced.setdefault(
                "retry_on",
                lambda exc: not isinstance(exc, GraphInterrupt),
            )
            coerced.setdefault("on_failure", _on_failure_reraise_interrupt)

        try:
            instances.append(cls(**coerced))
        except Exception:
            logger.exception("Failed to instantiate middleware '%s'", middleware_type)
    return instances


def get_provider_middleware(provider: str) -> list:
    """Return auto-applied middleware instances for a given model provider.

    E.g. Anthropic models automatically get prompt caching middleware.
    Returns an empty list if the middleware classes are not importable.
    """
    provider_map: dict[str, list[str]] = {
        # DeepAgents injects Anthropic prompt caching itself.
        "anthropic": [],
        "openai": ["openai_moderation"],
    }
    types = provider_map.get(provider, [])
    if not types:
        return []
    return build_middleware_instances([{"type": t, "params": {}} for t in types])


# deepagents/create_deep_agent() 自动添加的中间件类型。
# 如果在用户设置中重复添加会触发 AssertionError，因此在目录/执行时排除。
DEEPAGENT_AUTO_INJECTED_TYPES: frozenset[str] = frozenset(
    {
        "filesystem",
        "subagent",
        "summarization",
        "anthropic_prompt_caching",
    }
)


# 从 Deep Agents 0.7 开始，TodoListMiddleware 不再默认注入。Moldy 会
# 在 build_agent() 中直接注入现有 todo stream 协议和不含 delete 的 filesystem 表面。
# 这些类型不得通过用户设置重新实例化，并且在目录的
# ``exclude_builtin`` 视图中也会隐藏。
MOLDY_COMPAT_INJECTED_TYPES: frozenset[str] = frozenset(
    {
        "todo_list",
        "filesystem",
    }
)


# 本 set 中的条目绕过 ``build_middleware_instances`` 路径。executor 会
# 读取逐工具策略并转换为 DeepAgents top-level ``interrupt_on``，
# 由 create_deep_agent() 构建标准 HumanInTheLoopMiddleware 路径。
# 用户从目录中添加后会进入 ``cfg.middleware_configs``，但
# build 阶段会排除它们，以避免重复实例化。
EXPLICITLY_INSTANTIATED_TYPES: frozenset[str] = frozenset(
    {
        "human_in_the_loop",
        "model_fallback",
    }
)


# Build 阶段排除的所有类型 — deepagents auto + Moldy compat + explicit。
# ``_prepare_agent`` 的 ``filtered_mw`` 会从用户 ``middleware_configs`` 中
# 移除本 set 的条目。auto-injected 由 deepagents 处理，explicit 由 executor
# 作为 top-level 设置处理，因此目的是避免 build 时重复实例化。
DEEPAGENT_BUILTIN_TYPES: frozenset[str] = (
    DEEPAGENT_AUTO_INJECTED_TYPES | MOLDY_COMPAT_INJECTED_TYPES | EXPLICITLY_INSTANTIATED_TYPES
)


def get_middleware_registry(*, exclude_builtin: bool = False) -> list[dict[str, Any]]:
    """Return the middleware catalog.

    Each entry includes type key plus all metadata (name, display_name,
    description, category, config_schema, provider_specific).

    Args:
        exclude_builtin: True 时，目录中会排除 deepagents 自动添加的类型，以及 Moldy
            为兼容目的在 build_agent() 中直接注入的类型。
            像 ``human_in_the_loop`` 这样，必须由用户定义逐工具 ``interrupt_on``
            策略才能工作的 explicit 类型仍会显示 — executor 会
            读取用户设置并作为 top-level 策略传递。
    """
    return [
        {"type": key, **entry}
        for key, entry in MIDDLEWARE_REGISTRY.items()
        if not exclude_builtin
        or key not in (DEEPAGENT_AUTO_INJECTED_TYPES | MOLDY_COMPAT_INJECTED_TYPES)
    ]
