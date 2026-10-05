"""模型候选/回退/重试判定 — 从 ``runtime_component_builder`` 拆分（BE-S10）。

Patch-contract: 测试会 patch ``runtime_component_builder.create_chat_model``。
本模块函数通过 builder 模块进行 call-time import 来查找 ``create_chat_model``，
从而保证该 patch 继续有效（BE-S8 recorder→facade 模式）。若改为直接 top-level import，
会绕过 patch。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.agent_runtime.runtime_config import AgentConfig
from app.exceptions import AppError

logger = logging.getLogger(__name__)


class MiddlewareModelCredentialRequiredError(AppError):
    """Raised when middleware model config has no user-owned provider key."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            code="middleware_model_credential_required",
            message=(
                f"尚未注册可供中间件模型({provider})使用的您自己的 LLM API key。"
                "/credentials 页面中注册对应 provider 的 key，或修改中间件模型设置。"
                "请进行修改。"
            ),
            status=422,
        )


_MIDDLEWARE_MODEL_FIELDS = frozenset({"model", "fallback_model"})


def _resolve_middleware_model_params(
    configs: list[dict[str, Any]],
    provider_api_keys: dict[str, str | None],
) -> list[dict[str, Any]]:
    """预先将中间件 config 的 model 字符串解析为 BaseChatModel 对象。

    User-facing agent runtime must not fall through to env/system credentials.
    The caller provides only user-owned provider keys; missing keys become a
    clear 422 error before LangChain model construction.
    """
    # Call-time facade lookup: 测试会 patch runtime_component_builder.create_chat_model，
    # 因此必须经由 builder 模块查找，patch 才能生效（monkeypatch 透明性）。
    from app.agent_runtime.runtime_component_builder import create_chat_model

    resolved = []
    for config in configs:
        params = dict(config.get("params", {}))
        for field_name in _MIDDLEWARE_MODEL_FIELDS:
            val = params.get(field_name)
            if isinstance(val, str) and ":" in val:
                prov, mname = val.split(":", 1)
                api_key = provider_api_keys.get(prov)
                if not api_key:
                    raise MiddlewareModelCredentialRequiredError(prov)
                params[field_name] = create_chat_model(
                    prov,
                    mname,
                    api_key=api_key,
                    allow_env_fallback=False,
                )
        resolved.append({**config, "params": params})
    return resolved


def _model_constructor_params(cfg: AgentConfig) -> dict[str, Any]:
    params = dict(cfg.model_params or {})
    params.pop("recursion_limit", None)
    # Forward the model context limit so ``create_chat_model`` injects it into
    # ``model.profile`` (auto-summarization threshold = single source of truth).
    if cfg.context_window:
        params["context_window"] = cfg.context_window
    return params


def _model_chain(cfg: AgentConfig) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = [
        {
            "provider": cfg.provider,
            "model_name": cfg.model_name,
            "base_url": cfg.base_url,
        }
    ]
    chain.extend(cfg.model_fallback_chain or [])
    return chain


def _build_model_candidates(cfg: AgentConfig) -> list[BaseChatModel]:
    """Construct the primary chat model, walking ``model_fallback_chain``
    when the primary raises a recoverable error.

    This mirrors :func:`app.agent_runtime.model_factory.create_chat_model_with_fallback`
    but operates on the pre-resolved chain in ``AgentConfig`` so the executor
    can stay synchronous and DB-free. The chain entries are resolved by the
    caller (chat_service / trigger_executor) which has the DB session.
    """

    from app.agent_runtime.model_factory import _is_fallback_recoverable

    # Call-time facade lookup: 测试会 patch runtime_component_builder.create_chat_model，
    # 因此必须经由 builder 模块查找，patch 才能生效（monkeypatch 透明性）。
    from app.agent_runtime.runtime_component_builder import create_chat_model

    last_error: BaseException | None = None
    candidates: list[BaseChatModel] = []
    params = _model_constructor_params(cfg)
    chain = _model_chain(cfg)

    for idx, entry in enumerate(chain):
        try:
            candidates.append(
                create_chat_model(
                    entry["provider"],
                    entry["model_name"],
                    cfg.api_key,
                    entry.get("base_url"),
                    **params,
                )
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not candidates:
                if idx == len(chain) - 1 or not _is_fallback_recoverable(exc):
                    raise
                logger.info(
                    "model %s/%s failed; trying fallback (%d remaining)",
                    entry["provider"],
                    entry["model_name"],
                    len(chain) - idx - 1,
                )
                continue
            logger.warning(
                "fallback model %s/%s could not be constructed; runtime fallback will skip it",
                entry["provider"],
                entry["model_name"],
                exc_info=True,
            )

    if candidates:
        return candidates
    assert last_error is not None  # noqa: S101 — loop invariant (type narrowing)
    raise last_error


def _build_model_with_fallback(cfg: AgentConfig) -> BaseChatModel:
    """Backward-compatible helper that returns the first constructible candidate."""

    return _build_model_candidates(cfg)[0]


def _is_retryable_model_error(exc: Exception) -> bool:
    from app.agent_runtime.model_factory import _is_fallback_recoverable

    if _is_fallback_recoverable(exc):
        return True
    return isinstance(exc, ValueError) and "No generations found in stream" in str(exc)
