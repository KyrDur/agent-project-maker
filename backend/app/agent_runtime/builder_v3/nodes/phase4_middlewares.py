"""Phase 4 — 미들웨어 추천 (generate + approval 2-노드 패턴)."""

from __future__ import annotations

import logging

from langgraph.types import interrupt

from app.agent_runtime.builder.sub_agents.middleware_recommender import (
    recommend_middlewares,
)
from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.constants import ToolNames
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_approval_result,
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


async def phase4_recommend_middlewares(state: BuilderState) -> dict:
    intent_dict = state.get("intent") or {}
    catalog = state.get("middlewares_catalog") or []
    tools_data = state.get("tools") or []
    revision = state.get("last_revision_message")

    if not intent_dict:
        return {
            "current_phase": 4,
            "error_message": tr("phase_the_intent_before_entering_da6fdb"),
        }

    intent_obj = AgentCreationIntent(**intent_dict)
    tools_objs = [ToolRecommendation(**t) for t in tools_data]

    if revision:
        merged = AgentCreationIntent(**intent_dict)
        merged.constraints = list(merged.constraints) + [
            tr("request_for_modification_v_82d2ec", v0=f"{revision}")
        ]
        intent_obj = merged

    try:
        mw_objs: list[MiddlewareRecommendation] = await recommend_middlewares(
            intent_obj, tools_objs, catalog
        )
    except Exception:  # pragma: no cover
        logger.exception("Middleware recommendation failed")
        mw_objs = []

    mw_data = [m.model_dump(mode="json") for m in mw_objs]
    summary_text = (
        tr("we_recommend_v_middleware_after_f725b4", v0=f"{len(mw_data)}")
        if mw_data
        else tr("there_is_no_recommended_middleware_763ee0")
    )

    msgs, tool_call_id = make_pending_tool_card(
        ToolNames.RECOMMENDATION_APPROVAL,
        {
            "phase": 4,
            "title": tr("middleware_recommendations_b55f76"),
            "items": mw_data,
            "summary": summary_text,
            "item_kind": "middleware",
        },
        intro_text=tr("now_i_will_recommend_middleware_588d3f"),
    )

    return {
        "messages": msgs,
        "middlewares": mw_data,
        "last_revision_message": None,
        "current_phase": 4,
        "pending_tool_call_id": tool_call_id,
    }


async def phase4_approval(state: BuilderState) -> dict:
    response = interrupt(
        {
            "type": "approval",
            "phase": 4,
            "title": tr("middleware_recommendation_approval_3d5436"),
        }
    )

    approved, revision = parse_approval_response(response)
    return build_approval_result(
        state=state,
        approved=approved,
        revision=revision,
        pending_tc_id=state.get("pending_tool_call_id"),
        tool_name=ToolNames.RECOMMENDATION_APPROVAL,
        phase_id=4,
        next_phase=5,
        completion_message=(tr("phase_completed_middleware_recommendation_approved_744bda")),
        revision_default=tr("please_recommend_other_middleware_ac0a8f"),
        clear_field="middlewares",
    )
