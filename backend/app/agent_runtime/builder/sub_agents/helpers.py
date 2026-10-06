"""子智能体通用辅助函数 — LLM JSON retry + fence strip.

提取 4 个子智能体(intent_analyzer, tool_recommender, middleware_recommender,
prompt_generator)共享的模式。

发生 API 错误(429, 529 等)时最多重试 2 次；失败后抛出错误，不替换模型。
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent_runtime.builder_i18n import localize, localized_prompt
from app.agent_runtime.llm_user_context import llm_user_id
from app.agent_runtime.model_factory import create_chat_model
from app.database import async_session
from app.services.system_credential_resolver import (
    ResolvedSystemModel,
    SystemModelNotConfiguredError,
    resolve_system_model,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 提示词文件加载器
# ---------------------------------------------------------------------------

# __file__ = backend/app/agent_runtime/builder/sub_agents/helpers.py
# .parent = sub_agents/, .parent.parent = builder/ (prompts/ 目录位于此处)
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@functools.cache
def load_prompt(filename: str) -> str | None:
    """从 builder/prompts/ 目录加载提示词文件（已缓存）。

    如果文件不存在则返回 None，使调用方使用 fallback。
    """
    path = _PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Prompt file not found: %s, using fallback", path)
        return None


# API 错误中可重试的状态码
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_API_MAX_RETRIES = 2
_API_RETRY_DELAY = 2.0  # seconds
_API_CALL_TIMEOUT_SECONDS = 20.0


def strip_code_fences(text: str) -> str:
    """移除 Markdown 代码围栏(```…```)。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


# 按用户与角色缓存实际解析的个人模型配置。配置或凭据变化后重新构建模型，
# 避免跨用户复用，也避免将旧配置固定在模块级单例中。
_MODEL_CACHE: dict[tuple[str, str], tuple[ResolvedSystemModel, BaseChatModel]] = {}


async def _resolve_cached_model(role: str) -> BaseChatModel:
    """Resolve + build (or reuse) the chat model for a system ``role``.

    Raises ``SystemModelNotConfiguredError`` when the role is unconfigured.
    """
    async with async_session() as db:
        resolved = await resolve_system_model(db, role)
    cache_key = (str(llm_user_id.get()), role)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None and cached[0] == resolved:
        return cached[1]
    model = create_chat_model(
        resolved.provider,
        resolved.model_name,
        api_key=resolved.api_key,
        allow_env_fallback=False,
        base_url=resolved.base_url,
        timeout=_API_CALL_TIMEOUT_SECONDS,
        max_retries=0,
    )
    _MODEL_CACHE[cache_key] = (resolved, model)
    return model


async def _get_builder_model() -> BaseChatModel:
    """Builder primary model (system role ``builder``)."""
    return await _resolve_cached_model("builder")


async def _get_fallback_model() -> BaseChatModel | None:
    """Builder fallback model (system role ``text_fallback``). None if unset."""
    try:
        return await _resolve_cached_model("text_fallback")
    except SystemModelNotConfiguredError:
        return None


def _is_retryable(exc: Exception) -> bool:
    """判断是否为可重试的 API 错误。"""
    status = getattr(exc, "status_code", None)
    if status and status in _RETRYABLE_STATUS_CODES:
        return True
    exc_name = type(exc).__name__.lower()
    return any(k in exc_name for k in ("overloaded", "ratelimit", "timeout"))


async def _invoke_with_api_retry(
    model: BaseChatModel,
    messages: list,
    *,
    fallback: BaseChatModel | None = None,
) -> Any:
    """调用 LLM；可重试的 API 错误会在同一模型上重试，失败后抛出错误。

    添加 `builder:internal` tag，使上层 streaming.py 能够从用户界面 stream 中
    排除 sub-LLM 响应 chunk。
    """
    last_exc: Exception | None = None
    invoke_config: RunnableConfig = {"tags": ["builder:internal"]}

    for attempt in range(_API_MAX_RETRIES):
        try:
            return await asyncio.wait_for(
                model.ainvoke(messages, config=invoke_config),
                timeout=_API_CALL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_exc = exc
            logger.warning(
                "API call failed (attempt %d/%d): %s",
                attempt + 1,
                _API_MAX_RETRIES,
                exc,
            )
            if attempt < _API_MAX_RETRIES - 1:
                await asyncio.sleep(_API_RETRY_DELAY * (attempt + 1))

    raise last_exc  # type: ignore[misc]


async def invoke_with_json_retry(
    system_prompt: str,
    task_description: str,
    *,
    retry_suffix: str = "system_previous_response_was_not_86eef4",
    max_retries: int = 2,
) -> Any:
    """调用 LLM 并尝试解析 JSON。失败时重试。

    API 错误(429, 529 等)会在同一模型上自动重试，不切换到其他角色。
    JSON 解析失败时修改提示词后重试。

    Args:
        system_prompt: 系统提示词
        task_description: 用户消息（重试时添加 suffix）
        retry_suffix: 解析失败时添加到 task_description 的字符串
        max_retries: 最大尝试次数

    Returns:
        解析后的 JSON 对象（dict 或 list）

    Raises:
        ValueError: 解析失败达到 max_retries 次时
    """
    system_prompt = localized_prompt(system_prompt)
    model = await _get_builder_model()
    fallback = None
    description = task_description

    for attempt in range(max_retries):
        response = await _invoke_with_api_retry(
            model,
            [
                {"role": "system", "content": system_prompt},
                HumanMessage(content=description),
            ],
            fallback=fallback,
        )
        content = response.content
        try:
            text = strip_code_fences(content).lstrip()
            # 某些模型(LiteLLM gateway 等)会在 JSON 对象后附加说明文本
            # 。使用 raw_decode 只解析第一个 JSON 值，并忽略后续 extra data
            # ，防止因 "Extra data: line N" 导致解析失败。
            obj, _ = json.JSONDecoder().raw_decode(text)
            return obj
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("JSON parsing failed (attempt %d): %s", attempt + 1, exc)
            if attempt < max_retries - 1:
                description += localize(retry_suffix)

    raise ValueError(f"JSON parsing failed after {max_retries} attempts")


async def invoke_for_text(
    system_prompt: str,
    task_description: str,
    *,
    min_length: int = 500,
    retry_suffix_template: str = "system_previous_response_was_too_0a29d4",
    max_retries: int = 2,
) -> str | None:
    """调用 LLM 并返回文本响应。过短时重试。

    API 错误(429, 529 等)会在同一模型上自动重试，不切换到其他角色。

    Args:
        system_prompt: 系统提示词
        task_description: 用户消息
        min_length: 最小响应长度（低于或等于该值时重试）
        retry_suffix_template: 重试时添加的字符串（替换 {char_count}）
        max_retries: 最大尝试次数

    Returns:
        文本响应。超过 max_retries 时为 None。
    """
    system_prompt = localized_prompt(system_prompt)
    model = await _get_builder_model()
    fallback = None
    description = task_description

    for attempt in range(max_retries):
        response = await _invoke_with_api_retry(
            model,
            [
                {"role": "system", "content": system_prompt},
                HumanMessage(content=description),
            ],
            fallback=fallback,
        )
        prompt_text = response.content.strip()

        char_count = len(prompt_text)
        if char_count < min_length:
            logger.warning(
                "Generated text too short (%d chars, attempt %d)",
                char_count,
                attempt + 1,
            )
            if attempt < max_retries - 1:
                description += localize(retry_suffix_template).format(char_count=char_count)
                continue
        return prompt_text

    return None
