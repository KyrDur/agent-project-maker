"""Phase 1 — 项目初始化（无需 LLM）。

emit 进入消息 + 进度状态卡 + 进入下一 phase。
"""

from __future__ import annotations

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_phase_complete,
    get_last_user_text,
    make_tool_card,
)
from app.agent_runtime.builder_v3.state import BuilderState, initial_todos
from app.agent_runtime.builder_v3.todos import (
    PHASE_TIMELINE_TOOL,
    mark_completed_through,
    update_phase_status,
)


async def phase1_init(state: BuilderState) -> dict:
    """首次进入：emit 欢迎消息 + 8-phase 进度状态卡。"""
    user_request = state.get("user_request") or get_last_user_text(state)

    todos = state.get("todos") or initial_todos()

    # 进入：Phase 1 in_progress
    in_progress_todos = update_phase_status(todos, 1, "in_progress")
    intro_msgs, _ = make_tool_card(
        PHASE_TIMELINE_TOOL,
        {"todos": [dict(t) for t in in_progress_todos]},
        intro_text=(tr("we_ll_make_you_an_b8b04a")),
    )

    # 工作 — 简单的 path 字符串（不实际创建文件，仅用于元数据）
    project_path = f"agent_builds/{state.get('session_id', 'session')}"

    # 完成消息 + 更新卡片
    complete_msgs = build_phase_complete(
        1,
        in_progress_todos,
        tr("phase_completed_project_initialization_completed_eb79d9"),
    )
    final_todos = mark_completed_through(in_progress_todos, 1)

    return {
        "messages": intro_msgs + complete_msgs,
        "todos": final_todos,
        "user_request": user_request,
        "project_path": project_path,
        "current_phase": 2,
    }
