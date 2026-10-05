"""进度状态卡（Todo）辅助函数。

每个 phase 节点进入/完成时调用，更新 BuilderState.todos，
并通过 ToolMessage emit，使前端使用 PhaseTimelineToolUI 渲染。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolMessage

from app.agent_runtime.builder_v3.constants import ToolNames
from app.agent_runtime.builder_v3.state import (
    PHASE_DEFINITIONS,
    BuilderState,
    PhaseTodo,
    get_phase_name,
    initial_todos,
)

# 用于将进度状态卡显示为 ToolMessage 的虚假工具名称。
PHASE_TIMELINE_TOOL = ToolNames.PHASE_TIMELINE


def update_phase_status(
    todos: list[PhaseTodo] | None, phase_id: int, status: str
) -> list[PhaseTodo]:
    """返回更新单个 phase status 后的新 todos 列表（不可变）。"""
    base: list[PhaseTodo] = (
        [cast(PhaseTodo, {**t, "name": get_phase_name(t["id"])}) for t in todos]
        if todos
        else initial_todos()
    )
    new_todos: list[PhaseTodo] = []
    for t in base:
        if t["id"] == phase_id:
            new_todos.append(cast(PhaseTodo, {**t, "status": status}))
        else:
            new_todos.append(t)
    return new_todos


def mark_completed_through(todos: list[PhaseTodo] | None, phase_id: int) -> list[PhaseTodo]:
    """返回将 1..phase_id 标记为 completed、并让 phase_id+1 保持 pending（默认值）的 todos。"""
    base: list[PhaseTodo] = (
        [cast(PhaseTodo, {**t, "name": get_phase_name(t["id"])}) for t in todos]
        if todos
        else initial_todos()
    )
    new_todos: list[PhaseTodo] = []
    for t in base:
        if t["id"] <= phase_id:
            new_todos.append(cast(PhaseTodo, {**t, "status": "completed"}))
        else:
            new_todos.append(t)
    return new_todos


def build_timeline_messages(
    state: BuilderState,
    *,
    intro_text: str | None = None,
) -> tuple[list[Any], list[PhaseTodo]]:
    """生成 Tool call (assistant) + tool result (timeline) 消息对。

    assistant-ui 通过 tool_call_id 匹配 tool 消息，因此始终一起 emit 两条消息。

    Returns:
        (messages, updated_todos): messages 通过 add_messages reducer 累积
    """
    todos = [
        {**t, "name": get_phase_name(t["id"])} for t in (state.get("todos") or initial_todos())
    ]
    tool_call_id = str(uuid.uuid4())

    ai_msg = AIMessage(
        content=intro_text or "",
        tool_calls=[
            {
                "id": tool_call_id,
                "name": PHASE_TIMELINE_TOOL,
                "args": {"todos": [dict(t) for t in todos]},
            }
        ],
    )
    tool_msg = ToolMessage(
        content=json.dumps({"todos": [dict(t) for t in todos]}, ensure_ascii=False),
        tool_call_id=tool_call_id,
        name=PHASE_TIMELINE_TOOL,
    )
    return [ai_msg, tool_msg], cast(list[PhaseTodo], todos)


def get_phase_meta(phase_id: int) -> dict[str, Any]:
    for p in PHASE_DEFINITIONS:
        if p["id"] == phase_id:
            return {**p, "name": get_phase_name(phase_id)}
    return {"id": phase_id, "name": f"Phase {phase_id}"}
