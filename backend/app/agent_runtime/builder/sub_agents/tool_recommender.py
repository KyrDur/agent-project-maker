"""阶段 3：生成模拟工具和文本指南的能力方案。"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agent_runtime.builder.sub_agents.helpers import invoke_with_json_retry, load_prompt
from app.agent_runtime.builder_i18n import tr
from app.schemas.builder import AgentCreationIntent, ToolRecommendation

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    "分析确认需求，仅推荐模拟接口、文本指南或生成文本指南。仅返回 JSON 数组，简单任务允许空数组。"
)

SYSTEM_PROMPT = load_prompt("tool_recommender.md") or _FALLBACK_PROMPT


def _format_catalog(tools_catalog: list[dict[str, Any]]) -> str:
    """将目录格式化为文本 — 包含 ``Tool`` / ``McpTool`` / ``Skill`` 全部类型。

    为使 LLM 识别类型并在响应中包含适当的 ``kind``，添加 ``[kind]``
    prefix。
    """
    if not tools_catalog:
        return tr("no_items_available_9943cb")
    lines: list[str] = []
    for t in tools_catalog:
        name = t.get("name", "")
        desc = t.get("description", "")
        kind = t.get("kind", "tool")
        lines.append(f"- [{kind}] {name}: {desc}")
    return "\n".join(lines)


def _build_task_description(
    intent: AgentCreationIntent,
    tools_catalog: list[dict[str, Any]],
    *,
    previous_recommendations: list[dict[str, Any]] | None = None,
    revision_message: str | None = None,
) -> str:
    catalog_text = _format_catalog(tools_catalog)
    sections = [
        tr("please_analyze_the_following_agentcreationintent_0a656a"),
        "",
        f"## AgentCreationIntent\n{intent.model_dump_json(indent=2)}",
        tr("available_catalogs_v_2b7870", v0=f"{catalog_text}"),
    ]
    if previous_recommendations:
        prev_text = "\n".join(
            f"- [{p.get('kind', 'tool')}] {p.get('tool_name', '')}: {p.get('reason', '')}"
            for p in previous_recommendations
        )
        sections.append(
            tr("previous_recommendation_subject_to_modification_b22780", v0=f"{prev_text}")
        )
    if revision_message:
        # 修改消息是 override LLM 推理的绝对指令。优先于原始 intent
        # ，并准确反映数值/限定表达（e.g. "只要这个", "排除 X"）。
        sections.append(
            tr("user_modification_request_absolute_priority_0863f2", v0=f"{revision_message}")
        )
    sections.append(tr("answer_only_json_arrays_including_8e9ee6"))
    return "\n\n".join(sections)


async def recommend_tools(
    intent: AgentCreationIntent,
    tools_catalog: list[dict[str, Any]],
    *,
    previous_recommendations: list[dict[str, Any]] | None = None,
    revision_message: str | None = None,
) -> list[ToolRecommendation]:
    """基于 Intent 推荐条目（Tool / McpTool / Skill / planned）。

    解析失败或能力不可用时抛出错误。目录仅允许文本 Skill；
    ``planned`` 为模拟接口，``generated_skill`` 为生成的文本指南，
    两者必须通过名称与内容校验。

    同时提供 ``previous_recommendations`` + ``revision_message`` 时，
    将修改上下文传递给 LLM — 当用户使用 "只要这个 / 排除 X" 等限定
    表达时，在提示词中插入绝对优先章节以准确反映。
    """
    description = _build_task_description(
        intent,
        tools_catalog,
        previous_recommendations=previous_recommendations,
        revision_message=revision_message,
    )

    # 目录（名称 → 规范 kind）索引。如果 LLM 遗漏 kind 或回答错误
    # ，则用目录值纠正，使 confirm 阶段匹配正确的表。
    name_to_kind: dict[str, str] = {
        t.get("name", "").lower(): t.get("kind", "tool") for t in tools_catalog
    }

    try:
        raw_list = await invoke_with_json_retry(
            SYSTEM_PROMPT,
            description,
            retry_suffix=(tr("system_the_previous_response_was_3900ee")),
        )
        if not isinstance(raw_list, list):
            raise ValueError("Expected JSON array")

        recommendations: list[ToolRecommendation] = []
        for item in raw_list:
            if not isinstance(item, dict):
                raise ValueError("Invalid recommendation item")
            name = item.get("tool_name", "")
            canonical_kind = name_to_kind.get(name.lower())
            requested_kind = item.get("kind")
            if canonical_kind is None and requested_kind in {"planned", "generated_skill"}:
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
                    raise ValueError("Invalid simulation tool name")
                item["kind"] = requested_kind
                if requested_kind == "generated_skill":
                    from app.skills.inspector import parse_skill_md

                    parse_skill_md(str(item.get("content") or ""), require_metadata=True)
            elif canonical_kind is None:
                raise ValueError("Unavailable capability")
            else:
                # 目录正确答案优先于 LLM 回答的 kind — 防止幻觉
                if canonical_kind != "skill":
                    raise ValueError("Only simulated tools and text skills are supported")
                item["kind"] = canonical_kind
            recommendations.append(ToolRecommendation(**item))
        return recommendations
    except (ValueError, TypeError) as exc:
        logger.error("Tool recommendation failed after retries: %s", exc)
        raise ValueError("builder_capability_generation_invalid") from exc
