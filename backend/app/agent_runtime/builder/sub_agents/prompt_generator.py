"""阶段 5：根据确认过的需求和能力生成智能体指令。"""

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
    "根据确认过的需求和能力生成 Markdown 智能体指令，"
    "包含 Role、Tool Guidelines、Workflow、Constraints；仅返回正文。"
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
        if t.content:
            lines.append("Frozen Skill body:\n" + t.content)
        if t.input_schema:
            import json

            lines.append("Simulation input contract:\n" + json.dumps(t.input_schema))
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


# 用于提示词验证的核心标题（与 builder/prompts/prompt_generator.md 的必需章节同步）
_REQUIRED_HEADINGS = ("## Role", "## Tool Guidelines", "## Workflow", "## Constraints")


def _has_required_sections(text: str) -> bool:
    """检查生成的提示词是否包含核心标题。"""
    return all(heading in text for heading in _REQUIRED_HEADINGS)


async def generate_system_prompt(
    intent: AgentCreationIntent,
    tools: list[ToolRecommendation],
    middlewares: list[MiddlewareRecommendation],
) -> str:
    """生成系统提示词；返回内容无效或模型调用失败时抛出错误。"""
    description = _build_task_description(intent, tools, middlewares)

    result = await invoke_for_text(SYSTEM_PROMPT, description, min_length=300)
    if result is not None and _has_required_sections(result):
        return result

    raise ValueError("builder_prompt_generation_invalid")
