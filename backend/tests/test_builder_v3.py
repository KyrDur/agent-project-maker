"""Builder v3 单元测试。

- 验证 graph topology 可达性
- 验证 BuilderState/Todos helper
- image_gen public_url/resolve_local_path round-trip
- 集成：graph.astream end-to-end（mocked LLMs）
"""

from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent_runtime.builder_v3 import image_gen
from app.agent_runtime.builder_v3.graph import build_graph, get_node_targets
from app.agent_runtime.builder_v3.state import (
    PHASE_DEFINITIONS,
    initial_todos,
)
from app.agent_runtime.builder_v3.todos import (
    PHASE_TIMELINE_TOOL,
    build_timeline_messages,
    mark_completed_through,
    update_phase_status,
)

# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------


def test_phase_definitions_count():
    assert len(PHASE_DEFINITIONS) == 8
    assert [p["id"] for p in PHASE_DEFINITIONS] == list(range(1, 9))


def test_initial_todos_all_pending():
    todos = initial_todos()
    assert len(todos) == 8
    assert all(t["status"] == "pending" for t in todos)


# ---------------------------------------------------------------------------
# Todos helpers
# ---------------------------------------------------------------------------


def test_update_phase_status_only_changes_target():
    todos = initial_todos()
    new = update_phase_status(todos, 3, "in_progress")
    assert new[2]["status"] == "in_progress"
    # 其他 phase 无变化
    assert all(t["status"] == "pending" for i, t in enumerate(new) if i != 2)
    # 原始值不变
    assert all(t["status"] == "pending" for t in todos)


def test_mark_completed_through():
    todos = initial_todos()
    new = mark_completed_through(todos, 4)
    statuses = [t["status"] for t in new]
    assert statuses[:4] == ["completed"] * 4
    assert all(s == "pending" for s in statuses[4:])


def test_build_timeline_messages_returns_pair():
    state = {"todos": initial_todos()}
    msgs, todos = build_timeline_messages(state, intro_text="hi")  # type: ignore[arg-type]
    assert len(msgs) == 2  # AIMessage + ToolMessage
    assert msgs[0].tool_calls[0]["name"] == PHASE_TIMELINE_TOOL  # type: ignore[attr-defined]
    assert msgs[1].name == PHASE_TIMELINE_TOOL  # type: ignore[attr-defined]
    assert len(todos) == 8


# ---------------------------------------------------------------------------
# Graph topology
# ---------------------------------------------------------------------------


def test_graph_compiles():
    g = build_graph()
    compiled = g.compile()  # in-memory, no checkpointer
    assert compiled is not None


def test_graph_contains_all_phases():
    """8-phase 节点 + router 全部注册（包含 propose+wait 拆分模式）。"""
    g = build_graph()
    expected = {
        "phase1_init",
        "phase2_analyze_intent",
        "phase2_intent_wait",
        "phase3_recommend_tools",
        "phase3_approval",
        "phase4_recommend_middlewares",
        "phase4_approval",
        "phase5_generate_prompt",
        "phase5_approval",
        "phase6_choice_propose",
        "phase6_choice_wait",
        "phase6_image_generate",
        "phase6_image_approval",
        "phase7_save",
        "phase8_propose",
        "phase8_build_wait",
        "router",
    }
    actual = set(g.nodes.keys())
    assert expected <= actual


def test_node_targets_topology_consistent():
    """每个节点可能的 next 节点都必须存在于实际 graph 节点集合内。"""
    targets = get_node_targets()
    g = build_graph()
    valid_nodes = set(g.nodes.keys()) | {"__end__"}

    for source, dests in targets.items():
        assert source in g.nodes
        for dest in dests:
            # END 是 langgraph 常量（按 str 比较时为 "__end__"）
            assert dest in valid_nodes or str(dest) == "__end__"


def test_phase_order_enforced_by_topology():
    """到达 Phase 8 时必须经过 Phase 1-7（拓扑验证）。

    沿 graph 正向 edge 追踪 — 要到达 phase8_build_wait，无论哪条路径都必须经过1~7节点。
    """
    targets = get_node_targets()

    # 可到达 Phase 1 的 source 节点（router 不直接前往）
    sources_to_phase1 = [src for src, dests in targets.items() if "phase1_init" in dests]
    assert sources_to_phase1 == []

    # phase8_build_wait 可选 next：router 或 END
    assert "router" in targets["phase8_build_wait"]
    # router 只分支到拆分节点（phase2_analyze_intent 等）
    assert "phase2_analyze_intent" in targets["router"]
    assert "phase6_choice_propose" in targets["router"]


# ---------------------------------------------------------------------------
# Image gen helpers (no actual API call)
# ---------------------------------------------------------------------------


def test_image_public_url_format():
    url = image_gen.public_url_for("session-abc", "test.png")
    assert url == "/api/builder/session-abc/image/test.png"


def test_image_resolve_path_traversal_safe():
    # 不存在的文件 → None
    result = image_gen.resolve_local_path("session-abc", "../../etc/passwd")
    assert result is None


def test_build_default_prompt_includes_metadata():
    prompt = image_gen.build_default_prompt(
        agent_name="搜索机器人",
        agent_description="互联网搜索自动化",
        primary_task_type="默认标题",
    )
    assert "搜索机器人" in prompt
    assert "互联网搜索" in prompt or "默认标题" in prompt


# ---------------------------------------------------------------------------
# Integration: graph.astream end-to-end (mocked LLMs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase2_to_phase3_with_intent_confirmed_via_resume(monkeypatch):
    """Phase 2 ask_user → resume → intent_confirmed=True → 到达 Phase 3。

    LLM 调用通过 monkeypatch mock。验证 interrupt → Command(resume) 流程。
    """
    from app.agent_runtime.builder_v3 import graph as graph_module
    from app.agent_runtime.builder_v3.nodes import phase2_intent
    from app.schemas.builder import AgentCreationIntent

    # mock analyze_intent → 空 fallback intent（名称 fallback 标签）
    fake_intent = AgentCreationIntent(
        agent_name="自定义智能体",
        agent_description="根据用户请求创建的 agent: x",
        primary_task_type="x",
        use_cases=["x"],
        project_requirements={
            "goal": "测试任务",
            "inputs": "模拟输入",
            "deliverables": "回复",
            "business_rules": "仅模拟",
            "success_conditions": "符合给定信息",
        },
    )

    async def _fake_analyze(req: str):
        return fake_intent

    async def _fake_suggest(req: str):
        return ["选项 A", "选项 B", "选项 C"]

    monkeypatch.setattr(phase2_intent, "analyze_intent", _fake_analyze)
    monkeypatch.setattr(phase2_intent, "_suggest_name_options", _fake_suggest)

    # Phase 3 的 LLM 也 mock — 返回空 tool 推荐列表（目的在于验证停在 interrupt）
    from app.agent_runtime.builder_v3.nodes import phase3_tools

    async def _fake_recommend_tools(intent, catalog):
        return []

    monkeypatch.setattr(phase3_tools, "recommend_tools", _fake_recommend_tools)

    saver = InMemorySaver()
    compiled = graph_module.compile_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": "test-thread-1"}}

    initial = {
        "messages": [],
        "user_request": "测试请求",
        "session_id": "test-session-1",
        "current_phase": 1,
        "tools_catalog": [],
        "middlewares_catalog": [],
        "default_model_name": "",
    }

    # 第一次调用 → phase1 → phase2_analyze_intent → phase2_intent_wait → interrupt
    result = await compiled.ainvoke(initial, config=config)
    assert "__interrupt__" in result
    interrupts = result["__interrupt__"]
    assert any(
        (intr.value.get("type") if isinstance(intr.value, dict) else None) == "ask_user"
        for intr in interrupts
    )

    # resume — 用户选择 "选项 A"
    result2 = await compiled.ainvoke(
        Command(
            resume=json.dumps(
                {
                    "mode": "question_flow",
                    "answers": {"agent_name": ["选项 A"], "requirements_reason": ["测试所需"]},
                }
            )
        ),
        config=config,
    )
    assert "__interrupt__" in result2  # phase 3 approval 再次 interrupt
    # 验证 state
    state = await compiled.aget_state(config)
    assert state.values.get("intent_confirmed") is True
    assert state.values["intent"]["agent_name"] == "选项 A"
    # phase 3 tool recommendation card 应已 emit
    msgs = state.values.get("messages") or []
    has_recommendation = any(
        any(
            tc.get("name") == "recommendation_approval"
            for tc in (getattr(m, "tool_calls", None) or [])
        )
        for m in msgs
    )
    assert has_recommendation, "Phase 3 recommendation_approval card 应被 emit"


@pytest.mark.asyncio
async def test_phase2_question_flow_payload_and_structured_resume(monkeypatch):
    """Phase 2 ask_user v2 提供3个以上问题，并将 JSON 响应反映到 intent。"""
    from app.agent_runtime.builder_v3 import graph as graph_module
    from app.agent_runtime.builder_v3.nodes import phase2_intent
    from app.schemas.builder import AgentCreationIntent

    fake_intent = AgentCreationIntent(
        agent_name="研究 agent",
        agent_description="调查并整理资料的 agent",
        primary_task_type="资料调查",
        use_cases=["资料调查"],
        project_requirements={
            "goal": "调查资料",
            "inputs": "给定资料",
            "deliverables": "总结",
            "business_rules": "不虚构事实",
            "success_conditions": "准确总结",
        },
    )

    async def _fake_analyze(req: str):
        return fake_intent

    async def _fake_suggest(req: str):
        return ["研究机器人", "调查助手", "资料摘要员"]

    monkeypatch.setattr(phase2_intent, "analyze_intent", _fake_analyze)
    monkeypatch.setattr(phase2_intent, "_suggest_name_options", _fake_suggest)

    from app.agent_runtime.builder_v3.nodes import phase3_tools

    async def _fake_recommend_tools(intent, catalog):
        return []

    monkeypatch.setattr(phase3_tools, "recommend_tools", _fake_recommend_tools)

    saver = InMemorySaver()
    compiled = graph_module.compile_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": "test-thread-question-flow"}}

    result = await compiled.ainvoke(
        {
            "messages": [],
            "user_request": "帮我创建调查 agent",
            "session_id": "test-session-question-flow",
            "current_phase": 1,
            "tools_catalog": [],
            "middlewares_catalog": [],
            "default_model_name": "",
        },
        config=config,
    )

    interrupt_payload = next(
        intr.value for intr in result["__interrupt__"] if isinstance(intr.value, dict)
    )
    assert interrupt_payload["type"] == "ask_user"
    assert interrupt_payload["mode"] == "question_flow"
    assert len(interrupt_payload["questions"]) == 9
    assert not any(q["id"] == "identity_mode" for q in interrupt_payload["questions"])

    response = {
        "mode": "question_flow",
        "answers": {
            "agent_name": ["研究机器人"],
            "requirements_reason": ["只基于给定资料验证总结"],
            "response_tone": ["professional"],
            "output_style": ["detailed"],
        },
        "labels": {
            "agent_name": "研究机器人",
            "response_tone": "专业严谨",
            "output_style": "详细说明",
        },
    }
    await compiled.ainvoke(Command(resume=json.dumps(response, ensure_ascii=False)), config=config)

    state = await compiled.aget_state(config)
    assert state.values.get("intent_confirmed") is True
    assert state.values["intent"]["agent_name"] == "研究机器人"
    assert state.values["intent"]["response_tone"] == "专业严谨"
    assert state.values["intent"]["output_style"] == "详细说明"
    assert state.values["intent"]["identity_mode"] == "per_user"


def test_phase2_confirmed_intent_completion_fills_required_fields():
    from app.agent_runtime.builder_v3.nodes.phase2_intent import _complete_confirmed_intent

    result = _complete_confirmed_intent(
        {"agent_name": "周报助手", "identity_mode": "per_user"},
        {"user_request": "帮我做一个每天写周报的agent"},
    )

    assert result["agent_name"] == "周报助手"
    assert result["agent_description"]
    assert result["primary_task_type"] == "帮我做一个每天写周报的agent"
    assert result["use_cases"] == ["帮我做一个每天写周报的agent"]


@pytest.mark.asyncio
async def test_phase3_completes_legacy_partial_intent(monkeypatch):
    from app.agent_runtime.builder_v3.nodes import phase3_tools

    observed = {}

    async def _fake_recommend_tools(intent, catalog, **kwargs):
        del catalog, kwargs
        observed["intent"] = intent
        return []

    monkeypatch.setattr(phase3_tools, "recommend_tools", _fake_recommend_tools)

    result = await phase3_tools.phase3_recommend_tools(
        {
            "intent": {"agent_name": "周报助手", "identity_mode": "per_user"},
            "user_request": "帮我做一个每天写周报的agent",
            "tools_catalog": [],
            "todos": [],
        }
    )

    assert observed["intent"].agent_description
    assert observed["intent"].primary_task_type == "帮我做一个每天写周报的agent"
    assert result["intent"]["use_cases"] == ["帮我做一个每天写周报的agent"]


def test_phase7_draft_copies_identity_mode():
    from app.agent_runtime.builder_v3.nodes.phase7_save import _build_draft

    draft = _build_draft(
        {
            "intent": {
                "agent_name": "Research Agent",
                "agent_description": "调查资料的 agent",
                "primary_task_type": "资料调查",
                "use_cases": ["资料调查"],
                "identity_mode": "fixed",
            },
            "tools": [],
            "middlewares": [],
            "system_prompt": "You research.",
            "default_model_name": "GPT-4o",
        }
    )

    assert draft.identity_mode == "fixed"


def test_phase7_draft_separates_planned_tools_from_real_links():
    from app.agent_runtime.builder_v3.nodes.phase7_save import _build_draft

    draft = _build_draft(
        {
            "intent": {
                "agent_name": "Research Agent",
                "agent_description": "Researches documents.",
                "primary_task_type": "Research",
                "use_cases": ["Research"],
                "identity_mode": "per_user",
            },
            "tools": [
                {
                    "tool_name": "search_feishu",
                    "description": "Search Feishu",
                    "reason": "Evaluate first with a mock",
                    "kind": "planned",
                },
                {
                    "tool_name": "web_search",
                    "description": "Search the web",
                    "reason": "Use the connected catalog tool",
                    "kind": "tool",
                },
            ],
            "middlewares": [],
            "system_prompt": "You research.",
            "default_model_name": "GPT-4o",
        }
    )

    assert draft.tools == ["web_search"]
    assert [item["tool_name"] for item in draft.planned_tools] == ["search_feishu"]


def test_phase8_error_routes_to_end_not_router():
    """phase8_build_wait 中 confirm 失败（error_message set）时应前往 END。

    仅单元测试 routing 函数。
    """
    from langgraph.graph import END

    from app.agent_runtime.builder_v3.graph import _route_after_phase8_build_wait

    # 批准 + 创建成功
    assert _route_after_phase8_build_wait({"completed": True}) == END
    # 发生 error
    assert _route_after_phase8_build_wait({"error_message": "fail"}) == END
    # 修改请求
    assert _route_after_phase8_build_wait({"completed": False}) == "router"
    assert _route_after_phase8_build_wait({}) == "router"


def test_route_after_approval_factory():
    """验证 phase 3/4/5 approval routing factory。"""
    from app.agent_runtime.builder_v3.graph import _route_after_approval

    route = _route_after_approval("phase4", "phase3_recommend")
    assert route({"last_revision_message": "再来一次"}) == "phase3_recommend"
    assert route({"last_revision_message": None}) == "phase4"
    assert route({}) == "phase4"
