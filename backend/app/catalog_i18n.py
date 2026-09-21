"""Stable first-party catalog keys with a read-only adapter for legacy seed rows."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import cache
from pathlib import Path

from app.agent_runtime.builder_i18n import normalize_locale
from app.schemas.template import TemplateResponse
from app.seed.default_templates import DEFAULT_TEMPLATES

TEMPLATE_KEYS = (
    "email_assistant",
    "daily_brief",
    "web_researcher",
    "data_collector",
    "naver_news",
    "shopping_compare",
    "openwiki",
    "local_search",
)
CATEGORY_KEYS = {
    "生产力": "productivity",
    "数据": "data",
    "开发": "development",
    "生活": "lifestyle",
    "通信": "communication",
}


@cache
def catalog(locale: str):
    return json.loads(
        (
            Path(__file__).with_name("catalog_locales") / f"{normalize_locale(locale)}.json"
        ).read_text(encoding="utf-8")
    )


def template_display(row, locale: str):
    result = TemplateResponse.model_validate(row)
    # Only exact bundled seed content is first-party. Never translate external/user content.
    key = next(
        (
            key
            for key, seed in zip(TEMPLATE_KEYS, DEFAULT_TEMPLATES, strict=True)
            if row.name == seed["name"] and row.system_prompt == seed["system_prompt"]
        ),
        None,
    )
    if key is None:
        return result
    copy = catalog(locale)
    return result.model_copy(
        update={
            **copy["templates"][key],
            "content_key": key,
            "category_key": CATEGORY_KEYS.get(row.category, row.category),
            "category": copy["categories"].get(CATEGORY_KEYS.get(row.category), row.category),
        }
    )


def middleware_display(item: dict, locale: str) -> dict:
    result = deepcopy(item)
    result.update(catalog(locale)["middlewares"].get(item["type"], {}))
    if normalize_locale(locale) in ("zh-CN", "en"):
        # Field identifiers stay intact; localized field copy is separate from schema data.
        for key, field in result.get("config_schema", {}).items():
            field["description"] = key.replace("_", " ")
    return result
