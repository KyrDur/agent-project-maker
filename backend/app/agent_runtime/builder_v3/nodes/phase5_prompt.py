"""Phase 5 — 시스템 프롬프트 작성 (generate + approval 2-노드 패턴)."""

from __future__ import annotations

import logging

from langgraph.types import interrupt

from app.agent_runtime.builder.sub_agents.prompt_generator import generate_system_prompt
from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.constants import ToolNames
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_phase_complete,
    close_pending_tool_card,
    ensure_todos,
    make_pending_tool_card,
    parse_approval_response,
)
from app.agent_runtime.builder_v3.state import BuilderState
from app.schemas.builder import (
    AgentCreationIntent,
    MiddlewareRecommendation,
    ToolRecommendation,
)

logger = logging.getLogger(__name__)


async def phase5_generate_prompt(state: BuilderState) -> dict:
    intent_dict = state.get("intent") or {}
    tools_data = state.get("tools") or []
    middlewares_data = state.get("middlewares") or []
    revision = state.get("last_revision_message")

    if not intent_dict:
        return {
            "current_phase": 5,
            "error_message": tr("phase_the_intent_before_entering_0c0e21"),
        }

    intent_obj = AgentCreationIntent(**intent_dict)
    tools_objs = [ToolRecommendation(**t) for t in tools_data]
    mw_objs = [MiddlewareRecommendation(**m) for m in middlewares_data]

    if revision:
        merged = AgentCreationIntent(**intent_dict)
        merged.agent_description = (merged.agent_description or "") + tr(
            "request_for_modification_v_f2b088", v0=f"{revision}"
        )
        intent_obj = merged

    try:
        prompt = await generate_system_prompt(intent_obj, tools_objs, mw_objs)
    except Exception:  # pragma: no cover
        logger.exception("Prompt generation failed")
        prompt = ""

    msgs, tool_call_id = make_pending_tool_card(
        ToolNames.PROMPT_APPROVAL,
        {
            "phase": 5,
            "title": tr("system_prompt_30dccb"),
            "system_prompt": prompt,
            "summary": (tr("created_the_agent_s_system_ba6541")),
        },
        intro_text=tr("now_we_will_write_a_996c21"),
    )

    return {
        "messages": msgs,
        "system_prompt": prompt,
        "last_revision_message": None,
        "current_phase": 5,
        "pending_tool_call_id": tool_call_id,
    }


async def phase5_approval(state: BuilderState) -> dict:
    response = interrupt(
        {
            "type": "approval",
            "phase": 5,
            "title": tr("system_prompts_for_approval_b0045f"),
        }
    )

    approved, revision = parse_approval_response(response)
    pending_tc_id = state.get("pending_tool_call_id")

    if approved:
        close_msgs = close_pending_tool_card(
            pending_tc_id, ToolNames.PROMPT_APPROVAL, tr("approved_4131b9")
        )
        complete_msgs = build_phase_complete(
            5,
            ensure_todos(state),
            tr("phase_completed_system_prompt_acknowledged_b1d122"),
        )
        return {
            "messages": [*close_msgs, *complete_msgs],
            "current_phase": 6,
            "last_revision_message": None,
            "pending_tool_call_id": None,
        }

    revision_text = revision or tr("please_rewrite_the_prompt_5d3386")
    close_msgs = close_pending_tool_card(
        pending_tc_id, ToolNames.PROMPT_APPROVAL, tr("edit_request_v_bc1316", v0=f"{revision_text}")
    )
    return {
        "messages": close_msgs,
        "last_revision_message": revision_text,
        "system_prompt": None,  # clear so generate re-runs
        "pending_tool_call_id": None,
    }
