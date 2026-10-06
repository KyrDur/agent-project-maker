"""``app.agent_runtime.builder_v3.nodes._helpers.build_approval_result`` 回归保护。

Phase 3/4 自身 self-loop 期间，上一轮推荐（tools/middlewares）必须重新作为 LLM 推荐器
输入使用 — 准确反映用户限定表达（"只要这些"）。
旧实现会将 list 字段 clear 为 ``[]``，导致 LLM 重新 fresh-reasoning，
形成回归。
"""

from __future__ import annotations

from app.agent_runtime.builder_v3.nodes._helpers import build_approval_result


def _state_with_tools() -> dict:
    return {"tools": [{"tool_name": "x", "kind": "skill"}]}


def test_revision_preserves_tools_list():
    """修改请求时，结果 dict 不包含 ``tools`` 字段 — 保留现有 state。"""
    result = build_approval_result(
        state=_state_with_tools(),  # type: ignore[arg-type]
        approved=False,
        revision="我觉得只要这些就够了",
        pending_tc_id="tc-1",
        tool_name="recommendation_approval",
        phase_id=3,
        next_phase=4,
        completion_message="ok",
        revision_default="再来一次",
        clear_field="tools",
    )
    # 结果中不应有 tools key — LangGraph TypedDict 未包含 = 保留现有 state
    assert "tools" not in result
    assert result["last_revision_message"] == "我觉得只要这些就够了"


def test_revision_preserves_middlewares_list():
    """phase4 middlewares 也同样保留（限定表达处理保持一致）。"""
    result = build_approval_result(
        state={"middlewares": [{"middleware_name": "y"}]},  # type: ignore[arg-type]
        approved=False,
        revision="去掉 A",
        pending_tc_id="tc-2",
        tool_name="recommendation_approval",
        phase_id=4,
        next_phase=5,
        completion_message="ok",
        revision_default="再来一次",
        clear_field="middlewares",
    )
    assert "middlewares" not in result
    assert result["last_revision_message"] == "去掉 A"


def test_revision_clears_text_field():
    """文本字段（system_prompt）为了强制重新生成而 clear 为 ``None``。"""
    result = build_approval_result(
        state={"system_prompt": "old prompt"},  # type: ignore[arg-type]
        approved=False,
        revision="重新写一下",
        pending_tc_id="tc-3",
        tool_name="prompt_approval",
        phase_id=5,
        next_phase=6,
        completion_message="ok",
        revision_default="再来一次",
        clear_field="system_prompt",
    )
    assert result["system_prompt"] is None


def test_approval_advances_phase():
    """批准时前进到 next_phase + 清空 revision message。"""
    result = build_approval_result(
        state={},  # type: ignore[arg-type]
        approved=True,
        revision="",
        pending_tc_id="tc-4",
        tool_name="recommendation_approval",
        phase_id=3,
        next_phase=4,
        completion_message="next",
        revision_default="再来一次",
        clear_field="tools",
    )
    assert result["current_phase"] == 4
    assert result["last_revision_message"] is None
    assert "tools" not in result  # 批准时也保留 list 字段
