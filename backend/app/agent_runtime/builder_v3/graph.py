"""Builder v3 — StateGraph 编译。

8-phase + router。各 phase 中向用户提问的节点拆分为 propose+wait，
分别处理 ToolMessage emit 与 interrupt（LangGraph 推荐模式）。

拓扑:
    START
      ↓
    phase1_init
      ↓
    phase2_analyze_intent ↔ phase2_intent_wait (Command goto self/analyze)
      ↓ (intent_confirmed=True)
    phase3_recommend_tools → phase3_approval ↔ phase3_recommend_tools
      ↓
    phase4_recommend_middlewares → phase4_approval ↔ phase4_recommend_middlewares
      ↓
    phase5_generate_prompt → phase5_approval ↔ phase5_generate_prompt
      ↓
    phase6_choice_propose → phase6_choice_wait
      ├→ phase7_save (skip)
      └→ phase6_image_generate → phase6_image_approval
                                 ├→ phase7_save (confirm/skip)
                                 └→ phase6_image_generate (regenerate)
      ↓
    phase7_save
      ↓
    phase8_propose → phase8_build_wait
      ├→ END (approved)
      └→ router → phase2/3/4/5/6（修改请求）
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent_runtime.builder_v3.nodes.failure_retry import failure_propose, failure_wait
from app.agent_runtime.builder_v3.nodes.phase1_init import phase1_init
from app.agent_runtime.builder_v3.nodes.phase2_intent import (
    phase2_analyze_intent,
    phase2_intent_wait,
)
from app.agent_runtime.builder_v3.nodes.phase3_tools import (
    phase3_approval,
    phase3_recommend_tools,
)
from app.agent_runtime.builder_v3.nodes.phase4_middlewares import (
    phase4_approval,
    phase4_recommend_middlewares,
)
from app.agent_runtime.builder_v3.nodes.phase5_prompt import (
    phase5_approval,
    phase5_generate_prompt,
)
from app.agent_runtime.builder_v3.nodes.phase6_image import (
    phase6_choice_propose,
    phase6_choice_wait,
    phase6_image_approval,
    phase6_image_generate,
)
from app.agent_runtime.builder_v3.nodes.phase7_save import phase7_save
from app.agent_runtime.builder_v3.nodes.phase8_build import phase8_build_wait, phase8_propose
from app.agent_runtime.builder_v3.nodes.router import router
from app.agent_runtime.builder_v3.state import BuilderState

# ---------------------------------------------------------------------------
# Routing functions (conditional_edges) — named for readability
# ---------------------------------------------------------------------------


def _route_after_phase2_analyze(state: BuilderState) -> str:
    """如果 intent_confirmed=True 则进入 phase3，否则进入 ask_user wait。"""
    if state.get("error_message"):
        return "failure_propose"
    if state.get("intent_confirmed") and state.get("intent"):
        return "phase3_recommend_tools"
    return "phase2_intent_wait"


def _route_after_approval(next_phase: str, recommend_node: str):
    """phase 3/4/5 approval 节点的路由 generator。

    如果 last_revision_message 已 set，则重新进入 recommend，否则进入下一 phase。
    """

    def _route(state: BuilderState) -> str:
        if state.get("last_revision_message"):
            return recommend_node
        return next_phase

    return _route


def _route_after_phase6_choice_propose(state: BuilderState) -> str:
    return "phase7_save" if state.get("image_skipped") else "phase6_choice_wait"


def _route_after_phase6_choice_wait(state: BuilderState) -> str:
    return "phase7_save" if state.get("image_skipped") else "phase6_image_generate"


def _route_after_phase6_image_approval(state: BuilderState) -> str:
    return "phase7_save" if state.get("image_skipped") else "phase6_image_generate"


def _route_after_phase8_build_wait(state: BuilderState) -> str:
    """批准+生成成功 → END。发生错误 → END（向用户显示 error_message）。修改请求 → router。"""
    if state.get("runtime_setup_payload"):
        return "phase8_propose"
    if state.get("completed"):
        return END
    if state.get("error_message"):
        # confirm 失败等 — 不进入 router 而直接 END（frontend 显示 error）
        return END
    return "router"


def build_graph() -> StateGraph:
    """8-phase StateGraph（uncompiled）。用于测试。"""
    g: StateGraph = StateGraph(BuilderState)

    g.add_node("failure_propose", failure_propose)
    g.add_node(
        "failure_wait",
        failure_wait,
        destinations=(
            "phase2_analyze_intent",
            "phase3_recommend_tools",
            "phase4_recommend_middlewares",
            "phase5_generate_prompt",
            "phase7_save",
        ),
    )
    g.add_edge("failure_propose", "failure_wait")
    # 所有生成阶段只有成功后才能进入确认。
    # 所有节点 dict-only (Command 使用 X)。路由由 conditional_edges 决定。
    g.add_node("phase1_init", phase1_init)
    g.add_node("phase2_analyze_intent", phase2_analyze_intent)
    g.add_node("phase2_intent_wait", phase2_intent_wait)
    g.add_node("phase3_recommend_tools", phase3_recommend_tools)
    g.add_node("phase3_approval", phase3_approval)
    g.add_node("phase4_recommend_middlewares", phase4_recommend_middlewares)
    g.add_node("phase4_approval", phase4_approval)
    g.add_node("phase5_generate_prompt", phase5_generate_prompt)
    g.add_node("phase5_approval", phase5_approval)
    g.add_node("phase6_choice_propose", phase6_choice_propose)
    g.add_node("phase6_choice_wait", phase6_choice_wait)
    g.add_node("phase6_image_generate", phase6_image_generate)
    g.add_node("phase6_image_approval", phase6_image_approval)
    g.add_node("phase7_save", phase7_save)
    g.add_node("phase8_propose", phase8_propose)
    g.add_node("phase8_build_wait", phase8_build_wait)
    # router 仍使用 Command（5-way 分支）— 明确 destinations
    g.add_node(
        "router",
        router,
        destinations=(
            "phase2_analyze_intent",
            "phase3_recommend_tools",
            "phase4_recommend_middlewares",
            "phase5_generate_prompt",
            "phase6_choice_propose",
        ),
    )

    # Fixed edges
    g.add_edge(START, "phase1_init")
    g.add_edge("phase1_init", "phase2_analyze_intent")

    # Phase 2
    g.add_conditional_edges(
        "phase2_analyze_intent",
        _route_after_phase2_analyze,
        ["phase2_intent_wait", "phase3_recommend_tools", "failure_propose"],
    )
    g.add_edge("phase2_intent_wait", "phase2_analyze_intent")

    # Phase 3/4/5: approval 使用相同模式（通过 last_revision_message 重新进入 or 下一 phase）
    g.add_conditional_edges(
        "phase3_recommend_tools",
        lambda state: "failure_propose" if state.get("error_message") else "phase3_approval",
        ["failure_propose", "phase3_approval"],
    )
    g.add_conditional_edges(
        "phase3_approval",
        _route_after_approval("phase4_recommend_middlewares", "phase3_recommend_tools"),
        ["phase3_recommend_tools", "phase4_recommend_middlewares"],
    )

    g.add_conditional_edges(
        "phase4_recommend_middlewares",
        lambda state: "failure_propose" if state.get("error_message") else "phase4_approval",
        ["failure_propose", "phase4_approval"],
    )
    g.add_conditional_edges(
        "phase4_approval",
        _route_after_approval("phase5_generate_prompt", "phase4_recommend_middlewares"),
        ["phase4_recommend_middlewares", "phase5_generate_prompt"],
    )

    g.add_conditional_edges(
        "phase5_generate_prompt",
        lambda state: "failure_propose" if state.get("error_message") else "phase5_approval",
        ["failure_propose", "phase5_approval"],
    )
    g.add_conditional_edges(
        "phase5_approval",
        _route_after_approval("phase6_choice_propose", "phase5_generate_prompt"),
        ["phase5_generate_prompt", "phase6_choice_propose"],
    )

    # Phase 6
    g.add_conditional_edges(
        "phase6_choice_propose",
        _route_after_phase6_choice_propose,
        ["phase7_save", "phase6_choice_wait"],
    )
    g.add_conditional_edges(
        "phase6_choice_wait",
        _route_after_phase6_choice_wait,
        ["phase7_save", "phase6_image_generate"],
    )
    g.add_edge("phase6_image_generate", "phase6_image_approval")
    g.add_conditional_edges(
        "phase6_image_approval",
        _route_after_phase6_image_approval,
        ["phase7_save", "phase6_image_generate"],
    )

    g.add_conditional_edges(
        "phase7_save",
        lambda state: "failure_propose" if state.get("error_message") else "phase8_propose",
        ["failure_propose", "phase8_propose"],
    )
    g.add_edge("phase8_propose", "phase8_build_wait")
    # Phase 8: completed=True or error → END，修改请求 → router
    g.add_conditional_edges(
        "phase8_build_wait",
        _route_after_phase8_build_wait,
        [END, "router", "phase8_propose"],
    )

    return g


def compile_graph(checkpointer: Any | None = None) -> Any:
    """编译图。如果 checkpointer 为 None，则使用内存（用于测试）。"""
    g = build_graph()
    return g.compile(checkpointer=checkpointer)


def get_node_targets() -> dict[str, set[str]]:
    """用于验证图拓扑：各节点可能的 next 节点集合。

    在 pytest 图可达性测试中使用。
    """
    return {
        "failure_propose": {"failure_wait"},
        "failure_wait": {
            "phase2_analyze_intent",
            "phase3_recommend_tools",
            "phase5_generate_prompt",
            "phase4_recommend_middlewares",
            "phase7_save",
        },
        "phase1_init": {"phase2_analyze_intent"},
        "phase2_analyze_intent": {
            "phase2_intent_wait",
            "phase3_recommend_tools",
            "failure_propose",
        },
        "phase2_intent_wait": {"phase2_analyze_intent"},
        "phase3_recommend_tools": {"phase3_approval", "failure_propose"},
        "phase3_approval": {"phase3_recommend_tools", "phase4_recommend_middlewares"},
        "phase4_recommend_middlewares": {"phase4_approval", "failure_propose"},
        "phase4_approval": {"phase4_recommend_middlewares", "phase5_generate_prompt"},
        "phase5_generate_prompt": {"phase5_approval", "failure_propose"},
        "phase5_approval": {"phase5_generate_prompt", "phase6_choice_propose"},
        "phase6_choice_propose": {"phase6_choice_wait", "phase7_save"},
        "phase6_choice_wait": {"phase6_image_generate", "phase7_save"},
        "phase6_image_generate": {"phase6_image_approval"},
        "phase6_image_approval": {"phase6_image_generate", "phase7_save"},
        "phase7_save": {"phase8_propose", "failure_propose"},
        "phase8_propose": {"phase8_build_wait"},
        "phase8_build_wait": {"router", END},
        "router": {
            "phase2_analyze_intent",
            "phase3_recommend_tools",
            "phase4_recommend_middlewares",
            "phase5_generate_prompt",
            "phase6_choice_propose",
        },
    }
