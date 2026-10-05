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
    """카탈로그를 텍스트로 포맷한다 — ``Tool`` / ``McpTool`` / ``Skill`` 모두 포함.

    LLM 이 종류를 인지해 적절한 ``kind`` 를 응답에 포함할 수 있도록 ``[kind]``
    prefix 를 붙인다.
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
        # 수정 메시지는 LLM 추론을 override 하는 절대 지시. 원래 intent 보다
        # 우선하며, 수치/한정 표현 (e.g. "이것만", "X 빼고") 은 정확히 반영.
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
    """Intent 기반으로 항목 (Tool / McpTool / Skill / planned) 을 추천한다.

    파싱 실패 시 빈 리스트. 카탈로그에 없는 이름이거나 (이름, kind) 조합이
    카탈로그와 다르면 silent drop 한다. 단, ``planned`` 는 아직 연결되지 않은
    mock-ready 인터페이스이므로 안전한 이름을 가진 항목을 허용한다.

    ``previous_recommendations`` + ``revision_message`` 가 함께 주어지면
    수정 컨텍스트를 LLM 에 전달 — 사용자가 "이것만 / X 빼고" 같은 한정
    표현을 쓸 때 정확히 반영하도록 프롬프트에 절대 우선 섹션 삽입.
    """
    description = _build_task_description(
        intent,
        tools_catalog,
        previous_recommendations=previous_recommendations,
        revision_message=revision_message,
    )

    # 카탈로그 (이름 → 정규 kind) 인덱스. LLM 이 kind 를 누락하거나 잘못 답하면
    # 카탈로그 값으로 정정해 confirm 단계가 올바른 테이블을 매칭하도록 한다.
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
                # LLM 이 답한 kind 보다 카탈로그 정답 우선 — 환각 방지
                if canonical_kind != "skill":
                    raise ValueError("Only simulated tools and text skills are supported")
                item["kind"] = canonical_kind
            recommendations.append(ToolRecommendation(**item))
        return recommendations
    except (ValueError, TypeError) as exc:
        logger.error("Tool recommendation failed after retries: %s", exc)
        raise ValueError("builder_capability_generation_invalid") from exc
