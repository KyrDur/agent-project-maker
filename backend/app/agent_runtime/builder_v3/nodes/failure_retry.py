"""阶段失败后暂停；重试只重跑失败阶段，保留已确认的内容。"""

from langgraph.types import Command, interrupt

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.nodes._helpers import (
    close_pending_tool_card,
    make_pending_tool_card,
)
from app.agent_runtime.builder_v3.state import BuilderState


def failure_propose(state: BuilderState) -> dict:
    messages, call_id = make_pending_tool_card(
        "recommendation_approval",
        {
            "phase": state.get("current_phase", 2),
            "title": tr("generation_failed_retry"),
            "items": [],
            "item_kind": "tool",
            "retry_only": True,
            "summary": state.get("error_message") or tr("generation_failed_retry"),
        },
    )
    return {"messages": messages, "pending_tool_call_id": call_id}


def failure_wait(state: BuilderState) -> Command:
    interrupt({"type": "approval", "title": tr("generation_failed_retry")})
    target = {
        2: "phase2_analyze_intent",
        3: "phase3_recommend_tools",
        4: "phase4_recommend_middlewares",
        5: "phase5_generate_prompt",
        7: "phase7_save",
    }[state.get("current_phase", 2)]
    return Command(
        goto=target,
        update={
            "error_message": None,
            "pending_tool_call_id": None,
            "messages": close_pending_tool_card(
                state.get("pending_tool_call_id"), "recommendation_approval", tr("generation_retry")
            ),
        },
    )
