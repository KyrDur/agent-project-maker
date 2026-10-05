"""阶段 4：根据需求和能力，从目录中推荐运行中间件。"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agent_runtime.builder.sub_agents.helpers import invoke_with_json_retry, load_prompt
from app.agent_runtime.builder_i18n import tr
from app.schemas.builder import (
    AgentCreationIntent,
    MiddlewareRecommendation,
    ToolRecommendation,
)

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    "分析 AgentCreationIntent 和能力列表，"
    "只推荐目录里的必要中间件，仅返回 JSON 数组；无需中间件时返回空数组。"
)

SYSTEM_PROMPT = load_prompt("middleware_recommender.md") or _FALLBACK_PROMPT


def _format_catalog(middlewares_catalog: list[dict[str, Any]]) -> str:
    if not middlewares_catalog:
        return tr("no_middleware_available_21dc6a")
    lines: list[str] = []
    for m in middlewares_catalog:
        mtype = m.get("type", "")
        name = m.get("name", "")
        desc = m.get("description", "")
        category = m.get("category", "")
        provider = m.get("provider_specific")
        suffix = f" [provider: {provider}]" if provider else ""
        lines.append(f"- {mtype} ({name}, {category}): {desc}{suffix}")
    return "\n".join(lines)


def _build_task_description(
    intent: AgentCreationIntent,
    tools: list[ToolRecommendation],
    middlewares_catalog: list[dict[str, Any]],
) -> str:
    tool_names = [t.tool_name for t in tools]
    catalog_text = _format_catalog(middlewares_catalog)
    return tr(
        "please_analyze_the_following_information_8a7b7a",
        v0=f"{intent.model_dump_json(indent=2)}",
        v1=f"{json.dumps(tool_names, ensure_ascii=False)}",
        v2=f"{catalog_text}",
    )


async def recommend_middlewares(
    intent: AgentCreationIntent,
    tools: list[ToolRecommendation],
    middlewares_catalog: list[dict[str, Any]],
) -> list[MiddlewareRecommendation]:
    """基于 Intent + 工具推荐中间件。"""
    description = _build_task_description(intent, tools, middlewares_catalog)

    valid_types = {m.get("type", "").lower() for m in middlewares_catalog}

    try:
        raw_list = await invoke_with_json_retry(
            SYSTEM_PROMPT,
            description,
            retry_suffix=(tr("system_the_previous_response_was_3900ee")),
        )
        if not isinstance(raw_list, list):
            raise ValueError("Expected JSON array")

        recommendations: list[MiddlewareRecommendation] = []
        for item in raw_list:
            name = item.get("middleware_name", "")
            if name.lower() in valid_types:
                recommendations.append(MiddlewareRecommendation(**item))
            else:
                logger.warning("Filtered out non-existent middleware: %s", name)
        return recommendations
    except (ValueError, TypeError) as exc:
        logger.error("Middleware recommendation failed after retries: %s", exc)
        raise ValueError("builder_middleware_generation_invalid") from exc
