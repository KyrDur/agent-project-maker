from __future__ import annotations

import re

from app.agent_runtime.builder_i18n import locale_scope, tr

_PROVIDER_ERROR_MARKERS = (
    "Budget has been exceeded",
    "budget_exceeded",
    "Max budget",
    "Current cost",
    "Team=",
    "BadRequestError",
    "RateLimitError",
    "AuthenticationError",
    "PermissionDeniedError",
    "openai.",
    "anthropic",
    "google.api",
)

_SECRETISH_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|authorization|bearer)"
)

_DEFAULT_MODEL_ERROR_MESSAGE = (
    "모델 제공자 요청이 실패했습니다. 모델 설정, 자격증명, 사용량 한도를 확인해주세요."
)


def public_stream_error_message(error: Exception, *, locale: str | None = None) -> str:
    raw = str(error).strip()
    if locale is not None:
        # Builder/Assistant opt in; ordinary chat error handling stays unchanged.
        provider_error = _SECRETISH_RE.search(raw) or any(
            marker in raw for marker in _PROVIDER_ERROR_MARKERS
        )
        with locale_scope(locale):
            return tr("stream_model_error" if provider_error else "stream_generation_error")

    if not raw:
        return "응답 생성 중 오류가 발생했습니다."

    if _SECRETISH_RE.search(raw) or any(marker in raw for marker in _PROVIDER_ERROR_MARKERS):
        return _DEFAULT_MODEL_ERROR_MESSAGE

    return raw


__all__ = ["public_stream_error_message"]
