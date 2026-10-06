"""Builder v2 schemas — 构建会话、AgentCreationIntent、subagent 输入/输出。"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.identity import AGENT_IDENTITY_PER_USER, validate_identity_mode

# ---------------------------------------------------------------------------
# BuilderStatus StrEnum
# ---------------------------------------------------------------------------


class BuilderStatus(enum.StrEnum):
    """构建会话状态。"""

    BUILDING = "building"
    STREAMING = "streaming"
    PREVIEW = "preview"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Builder 请求/响应
# ---------------------------------------------------------------------------


class BuilderStartRequest(BaseModel):
    """POST /api/builder/start — 启动构建会话请求。"""

    user_request: str = Field(..., min_length=1, max_length=2000)


class BuilderSessionResponse(BaseModel):
    """构建会话状态响应。"""

    id: uuid.UUID
    status: BuilderStatus
    current_phase: int = 0
    user_request: str
    intent: AgentCreationIntent | None = None
    tools_result: list[ToolRecommendation] | None = None
    middlewares_result: list[MiddlewareRecommendation] | None = None
    system_prompt: str | None = None
    draft_config: DraftAgentConfig | None = None
    agent_id: uuid.UUID | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# AgentCreationIntent（Phase 2 输出）
# ---------------------------------------------------------------------------


class AgentCreationIntent(BaseModel):
    """意图分析 subagent 的结构化输出。"""

    agent_name: str = Field(..., description="Agent name in the active output language")
    agent_description: str = Field(..., description="关于 Agent 角色与功能的详细说明（3~5 句）")
    primary_task_type: str = Field(..., description="Agent 核心任务一句话说明")
    tool_preferences: str = Field(default="", description="偏好的工具类型")
    output_style: str = Field(
        default_factory=lambda: tr("brief_summary_and_key_points_dedcfb"),
        description="输出结果形式",
    )
    response_tone: str = Field(
        default_factory=lambda: tr("friendly_and_casual_301c5f"), description="响应语气"
    )
    identity_mode: str = Field(
        default=AGENT_IDENTITY_PER_USER,
        description="credential 使用主体：per_user 或 fixed",
    )
    use_cases: list[str] = Field(
        default_factory=list, min_length=1, description="使用案例（至少 1 个）"
    )
    constraints: list[str] = Field(default_factory=list, description="约束条件")
    project_requirements: dict[str, str] | None = Field(
        default=None,
        description=(
            "Draft goal, inputs, deliverables, business_rules "
            "and success_conditions for simulation practice"
        ),
    )
    confirmation_reason: str | None = None
    required_capabilities: list[str] = Field(default_factory=list, description="所需能力")

    @field_validator("identity_mode")
    @classmethod
    def _validate_identity_mode(cls, v: str) -> str:
        return validate_identity_mode(v)


# ---------------------------------------------------------------------------
# Tool Recommendation（Phase 3 输出）
# ---------------------------------------------------------------------------


class ToolRecommendation(BaseModel):
    """Builder 工具推荐子代理的单项推荐。

    ``planned`` 表示尚未连接真实资源、但可以先在评测 mock 环境中使用的工具接口。
    这类条目不会在确认创建 Agent 时强制解析为真实 Tool/MCP/Skill。
    """

    tool_name: str
    description: str
    reason: str
    kind: Literal["tool", "mcp", "skill", "planned", "generated_skill"] = "tool"
    content: str | None = Field(default=None, max_length=20000)
    input_schema: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Middleware Recommendation（Phase 4 输出）
# ---------------------------------------------------------------------------


class MiddlewareRecommendation(BaseModel):
    """中间件推荐 subagent 的单个推荐条目。"""

    middleware_name: str
    description: str
    reason: str


# ---------------------------------------------------------------------------
# DraftAgentConfig（Phase 6-7 输出，confirm 输入）
# ---------------------------------------------------------------------------


class DraftAgentConfig(BaseModel):
    """构建 pipeline 的最终产物 — 供用户确认的 Agent 配置 preview。"""

    name: str
    description: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list, description="工具名称列表")
    planned_tools: list[dict[str, Any]] = Field(
        default_factory=list, description="尚未连接、可在评测 mock 环境中使用的工具接口"
    )
    generated_skills: list[dict[str, Any]] = Field(default_factory=list)
    capability_reason: str | None = None
    middlewares: list[str] = Field(default_factory=list, description="中间件名称列表")
    model_name: str = Field(default="")
    primary_task_type: str = ""
    use_cases: list[str] = Field(default_factory=list)
    identity_mode: str = Field(default=AGENT_IDENTITY_PER_USER)

    @field_validator("identity_mode")
    @classmethod
    def _validate_identity_mode(cls, v: str) -> str:
        return validate_identity_mode(v)


# ---------------------------------------------------------------------------
# Builder SSE 事件数据
# ---------------------------------------------------------------------------


class PhaseProgressEvent(BaseModel):
    """SSE event: phase_progress."""

    phase: int
    status: Literal["started", "completed", "failed", "warning"]
    message: str = ""


class SubAgentEvent(BaseModel):
    """SSE event: sub_agent_start / sub_agent_end."""

    phase: int
    agent_name: str
    result_summary: str = ""


class BuildPreviewEvent(BaseModel):
    """SSE event: build_preview."""

    draft_config: DraftAgentConfig


class BuildErrorEvent(BaseModel):
    """SSE event: error."""

    phase: int
    message: str
    recoverable: bool = False


# ---------------------------------------------------------------------------
# BuilderState（LangGraph 内部状态 — 实际使用 TypedDict，此处仅用于文档）
# ---------------------------------------------------------------------------


class BuilderStateSchema(BaseModel):
    """LangGraph BuilderState 的 Pydantic 镜像（用于文档/校验）。

    实际 LangGraph 使用 builder/state.py 中的 TypedDict。
    此 schema 仅用于 API 测试与文档化。
    """

    user_id: str
    user_request: str
    session_id: str = ""
    project_path: str = ""
    intent: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    middlewares: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: str = ""
    draft_config: dict[str, Any] | None = None
    agent_id: str = ""
    current_phase: int = 0
    error: str = ""
    available_tools_catalog: list[dict[str, Any]] = Field(default_factory=list)
    available_middlewares_catalog: list[dict[str, Any]] = Field(default_factory=list)
    default_model_name: str = ""


# 重建 Pydantic v2 模型（解决 forward references）
BuilderSessionResponse.model_rebuild()
