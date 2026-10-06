"""Builder v3 节点通用辅助函数。

- 生成 ToolMessage 对（AIMessage + ToolMessage）— 用于 assistant-ui Tool UI
- emit 进度状态卡
- emit 文本消息
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.state import (
    BuilderState,
    PhaseTodo,
    get_phase_name,
    initial_todos,
)
from app.agent_runtime.builder_v3.todos import (
    PHASE_TIMELINE_TOOL,
    mark_completed_through,
    update_phase_status,
)


def make_tool_card(
    tool_name: str,
    args: dict[str, Any],
    *,
    intro_text: str = "",
) -> tuple[list[BaseMessage], str]:
    """创建 assistant-ui 渲染的 Tool UI 卡片（AIMessage + ToolMessage 对）。

    用于显示数据的卡片（仅需展示 phase_timeline 等结果的情况）。
    需要 HiTL 输入表单的卡片使用 ``make_pending_tool_card``。

    Returns:
        (messages, tool_call_id)
    """
    tool_call_id = str(uuid.uuid4())
    ai_msg = AIMessage(
        content=intro_text,
        tool_calls=[{"id": tool_call_id, "name": tool_name, "args": args}],
    )
    tool_msg = ToolMessage(
        content=json.dumps(args, ensure_ascii=False),
        tool_call_id=tool_call_id,
        name=tool_name,
    )
    return [ai_msg, tool_msg], tool_call_id


def make_pending_tool_card(
    tool_name: str,
    args: dict[str, Any],
    *,
    intro_text: str = "",
) -> tuple[list[BaseMessage], str]:
    """用于 HiTL 输入表单 — 仅 emit AIMessage(tool_calls)，省略 ToolMessage。

    assistant-ui 将其识别为 ``result === undefined``，从而显示输入表单（等待处理请求）
    的模式。用户响应后，在 wait 节点中
    通过 ``close_pending_tool_card`` 添加 ToolMessage，status 切换为 complete，
    使卡片不再 actionable。

    Returns:
        (messages, tool_call_id)
    """
    tool_call_id = str(uuid.uuid4())
    ai_msg = AIMessage(
        content=intro_text,
        tool_calls=[{"id": tool_call_id, "name": tool_name, "args": args}],
    )
    return [ai_msg], tool_call_id


def close_pending_tool_card(
    tool_call_id: str | None,
    tool_name: str,
    summary: str,
) -> list[BaseMessage]:
    """wait 节点处理响应后 close pending 卡片（切换为 status='complete'）。

    emit ToolMessage(tool_call_id=...)，填充 frontend 的 result。
    防止 stale 卡片再次变为 actionable。

    如果 tool_call_id 为 None，则返回空列表（no-op）。
    """
    if not tool_call_id:
        return []
    return [
        ToolMessage(
            content=summary,
            tool_call_id=tool_call_id,
            name=tool_name,
        )
    ]


def parse_approval_response(response: Any) -> tuple[bool, str]:
    """approval interrupt 响应 → 规范化为 (approved, revision_text)。

    Phase 3/4/5 wait 节点通用。
    """
    if isinstance(response, str):
        with contextlib.suppress(ValueError):
            response = json.loads(response)
    if isinstance(response, dict):
        approved = bool(response.get("approved"))
        revision = response.get("revision_message") or response.get("message") or ""
        return approved, revision
    if isinstance(response, str):
        return False, response
    return False, ""


def parse_choice_response(
    response: Any,
    *,
    prompt_keys: tuple[str, ...] = ("prompt", "auto_prompt"),
) -> tuple[str, str]:
    """phase6 image_choice/image_approval interrupt 响应 → 规范化为 (choice, prompt)。

    接受格式:
    - dict: ``{"choice": "...", "prompt"|"auto_prompt": "..."}`` (canonical)
    - str: 单个选项标签 (e.g. ``"skip"``, ``"generate"``, ``"确认"``)
    - str (JSON): ``'{"choice":"skip","prompt":"..."}'`` — frontend 以 dict
      意图执行 JSON.stringify 后的载荷，如果在 router 适配器的 ``respond`` 分支中
      以 string 形式传递，则以 backward-compatible 方式 fallthrough 到 dict 分支。

    如果 JSON.parse 结果不是 dict 或解析失败，则按普通 string 选项处理。
    """
    # JSON 字符串 fallback — 恢复原本意图为 dict、但被序列化成 string 的情况
    if isinstance(response, str):
        stripped = response.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    response = parsed
            except (json.JSONDecodeError, ValueError):
                pass  # 普通 string — 原样继续

    if isinstance(response, dict):
        choice = str(response.get("choice", "")).lower()
        prompt = ""
        for key in prompt_keys:
            value = response.get(key)
            if value:
                prompt = str(value)
                break
        return choice, prompt
    if isinstance(response, str):
        return response.lower(), ""
    return "", ""


def parse_question_flow_response(
    response: Any,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """ask_user question_flow resume 响应 → 规范化为 (answers, labels)。

    Frontend 为保持当前 ``respond(message)`` contract，将 structured
    selection 作为 JSON string 发送。Builder wait 节点恢复该值，
    legacy plain string 响应则转为空 structured 响应，以保持 backward compatibility
    。
    """
    if isinstance(response, str):
        stripped = response.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    response = parsed
            except (json.JSONDecodeError, ValueError):
                return {}, {}

    if not isinstance(response, dict) or response.get("mode") != "question_flow":
        return {}, {}

    answers_raw = response.get("answers")
    labels_raw = response.get("labels")

    answers: dict[str, list[str]] = {}
    if isinstance(answers_raw, dict):
        for key, value in answers_raw.items():
            if isinstance(value, list):
                answers[str(key)] = [str(item) for item in value if item is not None]
            elif value is not None:
                answers[str(key)] = [str(value)]

    labels: dict[str, str] = {}
    if isinstance(labels_raw, dict):
        for key, value in labels_raw.items():
            if isinstance(value, list):
                labels[str(key)] = ", ".join(str(item) for item in value if item is not None)
            elif value is not None:
                labels[str(key)] = str(value)

    return answers, labels


def build_approval_result(
    *,
    state: BuilderState,
    approved: bool,
    revision: str,
    pending_tc_id: str | None,
    tool_name: str,
    phase_id: int,
    next_phase: int,
    completion_message: str,
    revision_default: str,
    clear_field: str,
) -> dict[str, Any]:
    """将 phase 3/4/5 approval 响应转换为 dict（路由由 conditional_edges 决定）。

    批准时: completion 消息 + ``current_phase`` 前进 + 卡片 close。
    修改时: 仅 set ``last_revision_message`` + 卡片 close。**不 clear list 类型字段 (tools,
    middlewares)** — 下一次 self-loop 的推荐器将此前
    值作为 "修改对象" 上下文传给 LLM，以准确反映用户限定表达 ("只要这个"
    等)。像 ``system_prompt`` 这样的单一文本字段则
    clear 以强制重新生成。
    """
    if approved:
        close_msgs = close_pending_tool_card(pending_tc_id, tool_name, tr("approved_4131b9"))
        complete_msgs = build_phase_complete(phase_id, ensure_todos(state), completion_message)
        return {
            "messages": [*close_msgs, *complete_msgs],
            "current_phase": next_phase,
            "last_revision_message": None,
            "pending_tool_call_id": None,
        }

    revision_text = revision or revision_default
    close_msgs = close_pending_tool_card(
        pending_tc_id, tool_name, tr("edit_request_v_bc1316", v0=f"{revision_text}")
    )
    result: dict[str, Any] = {
        "messages": close_msgs,
        "last_revision_message": revision_text,
        "pending_tool_call_id": None,
    }
    # 保留列表字段（tools/middlewares）— 作为下一次推荐器 LLM 的输入。
    # 仅将文本字段（system_prompt）clear 为 None。
    if clear_field not in ("tools", "middlewares"):
        result[clear_field] = None
    return result


def build_phase_intro(phase_id: int, todos: list[PhaseTodo] | None) -> list[BaseMessage]:
    """进入 Phase 时显示的消息：进度状态卡(in_progress) + 简短问候。"""
    new_todos = update_phase_status(todos, phase_id, "in_progress")
    msgs, _ = make_tool_card(
        PHASE_TIMELINE_TOOL,
        {"todos": [dict(t) for t in new_todos]},
        intro_text=tr(
            "now_let_s_proceed_with_0dfd2f", v0=f"{phase_id}", v1=f"{get_phase_name(phase_id)}"
        ),
    )
    return msgs


def build_phase_complete(
    phase_id: int,
    todos: list[PhaseTodo] | None,
    summary_text: str,
) -> list[BaseMessage]:
    """Phase 完成时：已完成处理的进度状态卡 + 摘要消息。"""
    new_todos = mark_completed_through(todos, phase_id)
    msgs, _ = make_tool_card(
        PHASE_TIMELINE_TOOL,
        {"todos": [dict(t) for t in new_todos]},
        intro_text=summary_text,
    )
    return msgs


def _extract_text_from_content(content: Any) -> str:
    """LangChain Message.content (str | list[块]) → plain string。

    对 Anthropic multi-block content (e.g. [{"type": "text", "text": "..."}, ...])
    不做 raw stringify，而只提取文本 block。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content) if content is not None else ""


def get_last_user_text(state: BuilderState) -> str:
    """从 state.messages 获取最后一条 HumanMessage 文本。"""
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage):
            return _extract_text_from_content(msg.content)
    return ""


def ensure_todos(state: BuilderState) -> list[PhaseTodo]:
    return [{**t, "name": get_phase_name(t["id"])} for t in (state.get("todos") or initial_todos())]


def updated_todos_after(phase_id: int, todos: list[PhaseTodo] | None) -> list[PhaseTodo]:
    """Phase X 完成后的 todos：1..X completed，X+1 作为 in_progress 候选（保持 pending）。"""
    return mark_completed_through(todos, phase_id)
