"""Builder v3 — BuilderState TypedDict + Phase 定义。

LangGraph StateGraph 使用的状态。messages 通过 add_messages reducer 累积，
其余字段直接覆盖（default reducer）。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.agent_runtime.builder_i18n import localize

PhaseStatus = Literal["pending", "in_progress", "completed"]
PhaseId = Literal[1, 2, 3, 4, 5, 6, 7, 8]


PHASE_DEFINITIONS: list[dict[str, Any]] = [
    {"id": 1, "name": "项目初始化", "label_en": "Project Initialization"},
    {"id": 2, "name": "用户意图分析", "label_en": "Intent Analysis"},
    {"id": 3, "name": "工具推荐", "label_en": "Tool Recommendation"},
    {"id": 4, "name": "中间件推荐", "label_en": "Middleware Recommendation"},
    {"id": 5, "name": "系统 Prompt 编写", "label_en": "System Prompt"},
    {"id": 6, "name": "Agent 图像生成", "label_en": "Agent Image"},
    {"id": 7, "name": "保存 Agent 配置", "label_en": "Save Configuration"},
    {"id": 8, "name": "构建 Agent", "label_en": "Build Agent"},
]


class PhaseTodo(TypedDict):
    """Phase 进度状态卡的单个条目。"""

    id: int
    name: str
    status: PhaseStatus


class BuilderState(TypedDict, total=False):
    capability_reason: str | None
    runtime_model_id: str | None
    runtime_setup_payload: dict[str, Any] | None
    """LangGraph StateGraph 管理的构建器会话状态。

    通过 `total=False` 将所有键设为 optional，使节点只返回部分更新也可以。
    """

    # 消息历史（assistant-ui 兼容）
    messages: Annotated[list[BaseMessage], add_messages]

    # 进度状态卡（8-phase）
    todos: list[PhaseTodo]

    # 首次用户请求（在 Phase 1 中从 messages 提取并保存）
    user_request: str

    # 目录/元数据（在 Phase 1 中注入）
    user_id: str
    session_id: str
    tools_catalog: list[dict[str, Any]]
    middlewares_catalog: list[dict[str, Any]]
    default_model_name: str
    project_path: str

    # 各 Phase 结果
    intent: dict[str, Any] | None  # Phase 2
    tools: list[dict[str, Any]]  # Phase 3 (ToolRecommendation list)
    middlewares: list[dict[str, Any]]  # Phase 4
    system_prompt: str | None  # Phase 5
    image_url: str | None  # Phase 6（None 表示无图片）
    draft_config: dict[str, Any] | None  # Phase 7

    # 当前进度位置
    current_phase: int

    # phase 3/4/5 批准循环中传递给 LLM 的修改意见
    last_revision_message: str | None

    # phase 2 是否已收到用户名称确认（再次进入时是否跳过 ask_user）
    intent_confirmed: bool
    phase2_name_options: list[str]

    # phase 6 分支信号（skip/confirm 时 True → graph 路由到 phase7）
    image_skipped: bool

    # 上一个 propose 节点 emit 的 pending tool_call id（wait 节点用于 close ToolMessage）
    pending_tool_call_id: str | None

    # phase 8 中 router 决定分支的 phase（用于调试/审计）
    last_router_decision: str | None

    # 结束信号
    completed: bool
    agent_id: str | None
    error_message: str | None


def initial_todos() -> list[PhaseTodo]:
    """8 个 phase 的初始状态（全部 pending）。"""
    return [
        {"id": p["id"], "name": p["name"], "status": "pending"} for p in localize(PHASE_DEFINITIONS)
    ]


def get_phase_name(phase_id: int) -> str:
    for p in localize(PHASE_DEFINITIONS):
        if p["id"] == phase_id:
            return str(p["name"])
    return f"Phase {phase_id}"
