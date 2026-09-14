"""Phase 5 — 프롬프트 생성 서브에이전트.

모든 정보를 종합하여 에이전트의 시스템 프롬프트(마크다운)를 작성한다.
공식 템플릿 구조를 준수한다 (기획서 Section 5.5).
"""

from __future__ import annotations

import logging

from app.agent_runtime.builder.sub_agents.helpers import invoke_for_text, load_prompt
from app.agent_runtime.builder_i18n import tr
from app.schemas.builder import (
    AgentCreationIntent,
    MiddlewareRecommendation,
    ToolRecommendation,
)

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    "모든 정보를 종합하여 에이전트의 시스템 프롬프트를 마크다운으로 작성한다. "
    "2000~5000자, 마크다운 형식만, 프롬프트 본문만 반환."
)

SYSTEM_PROMPT = load_prompt("prompt_generator.md") or _FALLBACK_PROMPT


def _format_tools(tools: list[ToolRecommendation]) -> str:
    if not tools:
        return tr("no_tools_recommended_605542")
    lines: list[str] = []
    for i, t in enumerate(tools, 1):
        lines.append(
            tr(
                "v_v_v_reason_for_5331c9",
                v0=f"{i}",
                v1=f"{t.tool_name}",
                v2=f"{t.description}",
                v3=f"{t.reason}",
            )
        )
    return "\n".join(lines)


def _format_middlewares(middlewares: list[MiddlewareRecommendation]) -> str:
    if not middlewares:
        return tr("no_middleware_recommended_483e15")
    lines: list[str] = []
    for i, m in enumerate(middlewares, 1):
        lines.append(
            tr(
                "v_v_v_reason_for_5331c9",
                v0=f"{i}",
                v1=f"{m.middleware_name}",
                v2=f"{m.description}",
                v3=f"{m.reason}",
            )
        )
    return "\n".join(lines)


def _build_task_description(
    intent: AgentCreationIntent,
    tools: list[ToolRecommendation],
    middlewares: list[MiddlewareRecommendation],
) -> str:
    return tr(
        "we_compile_all_of_the_39e7e0",
        v0=f"{intent.model_dump_json(indent=2)}",
        v1=f"{_format_tools(tools)}",
        v2=f"{_format_middlewares(middlewares)}",
    )


# 프롬프트 검증용 핵심 헤딩 (builder/prompts/prompt_generator.md의 필수 섹션과 동기화)
_REQUIRED_HEADINGS = ("## Role", "## Tool Guidelines", "## Workflow", "## Constraints")


def _has_required_sections(text: str) -> bool:
    """생성된 프롬프트에 핵심 헤딩이 포함되어 있는지 확인한다."""
    return all(heading in text for heading in _REQUIRED_HEADINGS)


async def generate_system_prompt(
    intent: AgentCreationIntent,
    tools: list[ToolRecommendation],
    middlewares: list[MiddlewareRecommendation],
) -> str:
    """시스템 프롬프트를 생성한다. 실패 시 1회 재시도 후 기본 프롬프트를 반환한다."""
    description = _build_task_description(intent, tools, middlewares)

    result = await invoke_for_text(SYSTEM_PROMPT, description, min_length=1500)
    if result is not None and _has_required_sections(result):
        return result

    # fallback — 새 8+1 섹션 구조에 맞춘 기본 프롬프트
    tool_guidelines = ""
    for t in tools:
        tool_guidelines += tr(
            "v_purpose_v_when_when_9dfb07", v0=f"{t.tool_name}", v1=f"{t.description}"
        )
    if not tool_guidelines:
        tool_guidelines = tr("there_are_no_tools_available_346f5a")

    mw_section = ""
    if middlewares:
        mw_names = [m.middleware_name for m in middlewares]
        # 레지스트리 키(todo_list) + PascalCase(TodoListMiddleware) 모두 매칭
        # "todo_list" → "todolist", "TodoListMiddleware" → "todolistmiddleware"
        normalized = [n.lower().replace("_", "") for n in mw_names]
        has_todo = any("todolist" in n for n in normalized)
        has_summarization = any("summarization" in n for n in normalized)

        mw_section = tr("middleware_middleware_in_use_v_f8c56d", v0=f"{', '.join(mw_names)}")

        if has_todo:
            mw_section += tr("job_planning_and_execution_todo_a79785")
        if has_summarization:
            mw_section += tr("summary_of_conversation_if_the_fac677")

    return tr(
        "v_role_v_language_rule_0af2a1",
        v0=f"{intent.agent_name}",
        v1=f"{intent.agent_description}",
        v2=f"{intent.primary_task_type}",
        v3=f"{tool_guidelines}",
        v4=f"{intent.response_tone}",
        v5=f"{mw_section}",
    )
