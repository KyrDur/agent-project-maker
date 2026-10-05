"""阶段 3：生成能力建议，等待用户确认或修改。"""

from __future__ import annotations

import json
import logging

from langgraph.types import interrupt

from app.agent_runtime.builder.sub_agents.tool_recommender import recommend_tools
from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.constants import ToolNames
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_approval_result,
    make_pending_tool_card,
    parse_approval_response,
)
from app.agent_runtime.builder_v3.nodes.phase2_intent import _complete_confirmed_intent
from app.agent_runtime.builder_v3.state import BuilderState
from app.schemas.builder import AgentCreationIntent, ToolRecommendation

logger = logging.getLogger(__name__)


async def phase3_recommend_tools(state: BuilderState) -> dict:
    """结合需求和上一轮修改意见生成可确认的能力方案。"""
    intent_dict = state.get("intent") or {}
    catalog = state.get("tools_catalog") or []
    revision = state.get("last_revision_message")
    previous = state.get("tools") or []

    completed_intent = _complete_confirmed_intent(intent_dict, state) if intent_dict else {}
    intent_obj = AgentCreationIntent(**completed_intent) if completed_intent else None

    if not intent_obj:
        return {
            "current_phase": 3,
            "error_message": tr("the_intent_before_entering_phase_2e6619"),
        }

    try:
        tool_objs: list[ToolRecommendation] = await recommend_tools(
            intent_obj,
            catalog,
            previous_recommendations=previous if revision else None,
            revision_message=revision,
        )
    except Exception:  # pragma: no cover
        logger.exception("Tool recommendation failed")
        return {"current_phase": 3, "error_message": tr("generation_failed_retry")}

    tools_data = [t.model_dump(mode="json") for t in tool_objs]
    summary_text = (
        tr("v_tools_are_recommended_after_15f7dc", v0=f"{len(tools_data)}")
        if tools_data
        else tr("there_are_no_recommended_tools_1de525")
    )

    msgs, tool_call_id = make_pending_tool_card(
        ToolNames.RECOMMENDATION_APPROVAL,
        {
            "phase": 3,
            "title": tr("tool_recommendations_19ce61"),
            "items": tools_data,
            "summary": summary_text,
            "item_kind": "tool",
        },
        intro_text=tr("now_let_s_get_some_d00d56"),
    )

    return {
        "messages": msgs,
        "intent": intent_obj.model_dump(mode="json"),
        "tools": tools_data,
        "last_revision_message": None,
        "error_message": None,
        "current_phase": 3,
        "pending_tool_call_id": tool_call_id,
    }


async def phase3_approval(state: BuilderState) -> dict:
    """保存能力选择理由和用户编辑的文本指南。"""
    response = interrupt(
        {
            "type": "approval",
            "phase": 3,
            "title": tr("approval_of_tool_recommendations_0f0e41"),
        }
    )

    approved, revision = parse_approval_response(response)
    result = build_approval_result(
        state=state,
        approved=approved,
        revision=revision,
        pending_tc_id=state.get("pending_tool_call_id"),
        tool_name=ToolNames.RECOMMENDATION_APPROVAL,
        phase_id=3,
        next_phase=4,
        completion_message=(tr("phase_completed_tool_recommendation_approved_01d3a6")),
        revision_default=tr("please_recommend_another_tool_4a42a8"),
        clear_field="tools",
    )

    if approved:
        payload = response
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        reason = str(payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
        if not reason:
            return {
                **result,
                "last_revision_message": tr("capabilities_reason"),
                "capability_reason": None,
            }
        edited = payload.get("skill_contents", {})
        tools = [dict(t) for t in state.get("tools") or []]
        from app.skills.inspector import parse_skill_md

        try:
            for item in tools:
                if item.get("kind") == "generated_skill" and item["tool_name"] in edited:
                    content = str(edited[item["tool_name"]])
                    if not content or len(content) > 20000:
                        raise ValueError("builder_skill_content_invalid")
                    parse_skill_md(content, require_metadata=True)
                    item["content"] = content
        except (ValueError, TypeError, KeyError):
            return {
                **result,
                "last_revision_message": tr("generation_failed_retry"),
                "capability_reason": None,
                "tools": tools,
            }
        result.update(capability_reason=reason, tools=tools)
    return result
