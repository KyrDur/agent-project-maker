"""ask_user — 向用户提问并等待响应的工具。

使用 LangGraph interrupt() 暂停图执行，
收到用户响应后通过 Command(resume=) 恢复。
"""

from typing import Any, Literal

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field, model_validator


class AskUserOption(BaseModel):
    """Serializable option item for ask_user v2 payloads."""

    id: str | None = None
    label: str
    description: str | None = None
    disabled: bool | None = None


class AskUserQuestion(BaseModel):
    """One step in a question_flow payload."""

    id: str | None = None
    label: str | None = None
    question: str | None = None
    type: Literal["single_select", "multi_select", "text"] | None = None
    options: list[str | AskUserOption] | None = None
    required: bool | None = None


class AskUserInput(BaseModel):
    """Backward-compatible schema for the canonical ask_user tool."""

    question: str | None = None
    options: list[str | AskUserOption] | None = None
    mode: Literal["question_flow", "option_list"] | None = None
    title: str | None = None
    questions: list[AskUserQuestion] | None = None
    minSelections: int | None = Field(default=None, ge=0)  # noqa: N815 — tool schema wire contract
    maxSelections: int | None = Field(default=None, ge=1)  # noqa: N815 — tool schema wire contract

    @model_validator(mode="after")
    def _validate_shape(self) -> "AskUserInput":
        if self.mode is None and not self.question:
            raise ValueError("ask_user requires question when mode is omitted")
        if self.mode == "question_flow" and not self.questions:
            raise ValueError("question_flow mode requires questions")
        if self.mode == "option_list" and not self.options:
            raise ValueError("option_list mode requires options")
        if (
            self.minSelections is not None
            and self.maxSelections is not None
            and self.minSelections > self.maxSelections
        ):
            raise ValueError("minSelections cannot be greater than maxSelections")
        return self


def _extract_respond_message(response: object) -> str:
    """Return the user's message from LangChain's standard HITL resume shape."""

    if isinstance(response, dict):
        decisions = response.get("decisions")
        if isinstance(decisions, list):
            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                if decision.get("type") == "respond":
                    message = decision.get("message")
                    if isinstance(message, str):
                        return message
                    if message is not None:
                        return str(message)
    return str(response)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items() if item is not None}
    return value


def _build_interrupt_payload(
    *,
    question: str | None,
    options: list[str | AskUserOption] | None,
    mode: Literal["question_flow", "option_list"] | None,
    title: str | None,
    questions: list[AskUserQuestion] | None,
    minSelections: int | None,  # noqa: N803 — mirrors tool schema wire contract
    maxSelections: int | None,  # noqa: N803 — mirrors tool schema wire contract
) -> dict[str, Any]:
    if mode is None:
        return {
            "type": "ask_user",
            "question": question or "",
            "options": _to_jsonable(options or []),
        }

    payload: dict[str, Any] = {"type": "ask_user", "mode": mode}
    for key, value in {
        "title": title,
        "question": question,
        "questions": questions,
        "options": options,
        "minSelections": minSelections,
        "maxSelections": maxSelections,
    }.items():
        if value is not None:
            payload[key] = _to_jsonable(value)
    return payload


@tool(args_schema=AskUserInput)
def ask_user(
    question: str | None = None,
    options: list[str | AskUserOption] | None = None,
    mode: Literal["question_flow", "option_list"] | None = None,
    title: str | None = None,
    questions: list[AskUserQuestion] | None = None,
    minSelections: int | None = None,  # noqa: N803 — mirrors tool schema wire contract
    maxSelections: int | None = None,  # noqa: N803 — mirrors tool schema wire contract
) -> str:
    """向用户提问并等待响应。

    仅在以下情况下使用：
    - 用户请求含糊，存在 2 种以上解释时
    - 执行重要任务前需要最终确认时
    - 需要在多个选项中确认用户偏好时

    以下情况下不要使用：
    - 回答一般问题时（直接回答）
    - 已有足够信息时
    - 简单问候或闲聊

    Args:
        question: 向用户显示的单个问题 (legacy)
        options: 选项列表 (legacy 或 option_list)
        mode: question_flow 或 option_list 渲染模式
        title: 扩展模式卡片标题
        questions: question_flow 步骤列表
        minSelections: option_list 最少选择数
        maxSelections: option_list 最多选择数
    """
    response = interrupt(
        _build_interrupt_payload(
            question=question,
            options=options,
            mode=mode,
            title=title,
            questions=questions,
            minSelections=minSelections,
            maxSelections=maxSelections,
        )
    )
    return _extract_respond_message(response)
