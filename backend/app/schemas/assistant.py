"""Assistant v2 schemas — Agent 配置修改助手的消息/事件。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.builder_i18n import BuilderLocale
from app.schemas.conversation import Decision

# ---------------------------------------------------------------------------
# Assistant 请求/响应
# ---------------------------------------------------------------------------


class AssistantMessageRequest(BaseModel):
    """POST /api/agents/{agent_id}/assistant/message — 消息请求。"""

    locale: BuilderLocale | None = None
    content: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = Field(
        default=None,
        description="客户端生成的会话 ID（crypto.randomUUID）。 "
        "相同 session_id 保持同一对话；没有时使用基于 agent_id 的默认值。",
    )


class AssistantResumeRequest(BaseModel):
    locale: BuilderLocale | None = None
    decisions: list[Decision] = Field(..., min_length=1)
    session_id: str | None = None
    display_text: str | None = None
    interrupt_id: str | None = None


class AssistantMessageResponse(BaseModel):
    """Assistant 消息响应（SSE message_end 事件的最终数据）。"""

    role: str = "assistant"
    content: str
    tool_calls: list[AssistantToolCallResult] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)


class AssistantToolCallResult(BaseModel):
    """Assistant 执行的单个工具调用结果摘要。"""

    tool_name: str
    success: bool = True
    summary: str = ""


# ---------------------------------------------------------------------------
# Assistant 工具输入/输出 schema
# ---------------------------------------------------------------------------


class AgentConfigSnapshot(BaseModel):
    """get_agent_config 工具返回值 — Agent 当前配置快照。"""

    agent_id: uuid.UUID
    name: str
    description: str | None = None
    system_prompt: str
    model_name: str
    model_params: dict[str, Any] | None = None
    tools: list[AgentToolInfo] = Field(default_factory=list)
    middlewares: list[AgentMiddlewareInfo] = Field(default_factory=list)
    skills: list[AgentSkillInfo] = Field(default_factory=list)


class AgentToolInfo(BaseModel):
    """与 Agent 连接的工具摘要信息。"""

    name: str
    description: str | None = None
    tool_type: str = ""  # builtin, prebuilt, custom, mcp
    config: dict[str, Any] = Field(default_factory=dict)


class AgentMiddlewareInfo(BaseModel):
    """与 Agent 连接的中间件摘要信息。"""

    type: str
    display_name: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class AgentSkillInfo(BaseModel):
    """与 Agent 连接的 Skill 摘要信息。"""

    name: str
    description: str | None = None


# ---------------------------------------------------------------------------
# 工具 catalog 查询结果
# ---------------------------------------------------------------------------


class AvailableToolItem(BaseModel):
    """list_available_tools 工具返回值中的单个条目。"""

    name: str
    description: str | None = None
    tool_type: str
    required_secrets: list[str] = Field(default_factory=list)


class AvailableMiddlewareItem(BaseModel):
    """list_available_middlewares 工具返回值中的单个条目。"""

    name: str
    display_name: str
    description: str
    category: str
    config_schema: dict[str, Any] = Field(default_factory=dict)


class AvailableModelItem(BaseModel):
    """list_available_models 工具返回值中的单个条目。"""

    id: uuid.UUID
    display_name: str
    provider: str
    model_id: str


# ---------------------------------------------------------------------------
# 资源添加/删除工具输入
# ---------------------------------------------------------------------------


class AddResourceInput(BaseModel):
    """add_tool_to_agent / add_middleware_to_agent 等的输入。"""

    names: list[str] = Field(..., min_length=1)


class RemoveResourceInput(BaseModel):
    """remove_tool_from_agent / remove_middleware_from_agent 等的输入。"""

    names: list[str] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# 系统 prompt 修改工具输入
# ---------------------------------------------------------------------------


class EditSystemPromptInput(BaseModel):
    """edit_system_prompt 工具输入。"""

    old_string: str = Field(..., min_length=1)
    new_string: str  # 空字符串 = 删除
    replace_all: bool = False


class UpdateSystemPromptInput(BaseModel):
    """update_system_prompt 工具输入。"""

    new_system_prompt: str = Field(..., min_length=1)


class SearchSystemPromptInput(BaseModel):
    """search_system_prompt 工具输入。"""

    keyword: str = Field(..., min_length=1)


class SearchSystemPromptResult(BaseModel):
    """search_system_prompt 工具输出。"""

    found: bool
    matches: list[PromptSearchMatch] = Field(default_factory=list)


class PromptSearchMatch(BaseModel):
    """prompt 中的关键词匹配结果。"""

    text: str  # 匹配到的文本（包含前后 context）
    line_number: int = 0


# ---------------------------------------------------------------------------
# 模型配置工具
# ---------------------------------------------------------------------------


class UpdateModelConfigInput(BaseModel):
    """update_model_config 工具输入。"""

    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None


# ---------------------------------------------------------------------------
# cron schedule 工具
# ---------------------------------------------------------------------------


class CronScheduleInput(BaseModel):
    """create_cron_schedule 工具输入。"""

    schedule_type: str = Field(..., pattern="^(recurring|one_time)$")
    cron_expression: str | None = None  # recurring 时必填
    scheduled_at: str | None = None  # one_time 时必填（ISO 8601）
    timezone: str = "Asia/Seoul"
    message: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Clarifying Question 工具
# ---------------------------------------------------------------------------


class AskClarifyingQuestionInput(BaseModel):
    """ask_clarifying_question 工具输入。"""

    question: str
    option_1: str
    option_2: str
    option_3: str


class ClarifyingQuestionOutput(BaseModel):
    """ask_clarifying_question 工具输出（显示在前端）。"""

    question: str
    options: list[str]  # 3 个选项 + "直接输入"


# ---------------------------------------------------------------------------
# Secrets 检查工具
# ---------------------------------------------------------------------------


class RequiredSecretsResult(BaseModel):
    """get_agent_required_secrets 工具输出。"""

    required: list[str]
    registered: list[str]
    missing: list[str]


# 解决 Pydantic v2 forward reference
SearchSystemPromptResult.model_rebuild()
