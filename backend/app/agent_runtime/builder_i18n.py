"""Locale support scoped to Builder/Assistant requests, never chat history."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache, wraps
from pathlib import Path
from typing import Any, Literal

BuilderLocale = Literal["zh-CN", "en"]
DEFAULT_LOCALE: BuilderLocale = "zh-CN"
_locale: ContextVar[BuilderLocale] = ContextVar("builder_locale", default=DEFAULT_LOCALE)


def normalize_locale(value: str | None) -> BuilderLocale:
    return value if value in ("zh-CN", "en") else DEFAULT_LOCALE


def get_locale() -> BuilderLocale:
    # Runnable config reaches every node, including resumed checkpoint tasks.
    from langgraph.config import get_config

    try:
        value = get_config().get("configurable", {}).get("ui_locale")
    except RuntimeError:
        value = None
    return normalize_locale(value) if value is not None else _locale.get()


@contextmanager
def locale_scope(locale: str | None):
    token = _locale.set(normalize_locale(locale))
    try:
        yield
    finally:
        _locale.reset(token)


def localized_stream(func):
    @wraps(func)
    async def wrapped(*args, **kwargs):
        iterator = func(*args, **kwargs)
        try:
            while True:
                with locale_scope(kwargs.get("locale")):
                    try:
                        chunk = await anext(iterator)
                    except StopAsyncIteration:
                        return
                yield chunk
        finally:
            with locale_scope(kwargs.get("locale")):
                await iterator.aclose()

    return wrapped


@cache
def catalog(locale: BuilderLocale) -> dict[str, str]:
    return json.loads(
        (Path(__file__).with_name("builder_locales") / f"{locale}.json").read_text(encoding="utf-8")
    )


@cache
def source_keys() -> dict[str, str]:
    # Resolve legacy static constants only when used inside a request.
    return {value: key for key, value in catalog("zh-CN").items()}


def tr(source: str, **values: Any) -> str:
    key = source_keys().get(source, source)
    translated = catalog(get_locale()).get(key, source)
    # Substitute only our named slots, not JSON braces or text inside user values.
    return re.sub(
        r"\{(v\d+)\}", lambda m: str(values[m[1]]) if m[1] in values else m[0], translated
    )


def localize(value: Any) -> Any:
    """Localize static catalogs only; never pass stored/user-generated content here."""
    if isinstance(value, str):
        return tr(value)
    if isinstance(value, list):
        return [localize(item) for item in value]
    if isinstance(value, dict):
        return {key: localize(item) for key, item in value.items()}
    return value


def language_instruction() -> str:
    language = {"zh-CN": "Simplified Chinese", "en": "English"}[get_locale()]
    return (
        f"Active UI locale: {get_locale()}. Write all user-visible questions, option labels, "
        f"names, descriptions, explanations, status and completion messages in {language}. "
        "Use this language for newly generated content even if earlier conversation messages "
        "use another language. Honor a different language only when the user "
        "explicitly requests it. "
        "Keep JSON keys, schema field names, tool IDs, internal identifiers and code unchanged. "
        "The legacy agent_name_ko/name_ko fields carry the localized display name; their suffix "
        "does not select the output language. Keep required Markdown section headings unchanged."
    )


def localized_prompt(prompt: str) -> str:
    return localize(prompt) + "\n\n" + language_instruction()
