from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent_runtime.identity import AGENT_IDENTITY_PER_USER, validate_identity_mode
from app.agent_runtime.runtime_policy import RuntimePolicySnapshotSource, RuntimePolicyV1
from app.schemas.skill import SkillBrief as SkillBrief  # noqa: F401 — used in AgentResponse

MAX_OPENER_QUESTIONS = 12
OPENER_QUESTION_MAX_LENGTH = 200


def _validate_opener_questions(v: list[str] | None) -> list[str] | None:
    """Shared validator for opener_questions.

    - list 长度 ≤ 12
    - 每项 strip 后长度为 1~200 字符
    """
    if v is None:
        return v
    if len(v) > MAX_OPENER_QUESTIONS:
        raise ValueError(f"opener_questions can have at most {MAX_OPENER_QUESTIONS} items")
    cleaned: list[str] = []
    for idx, item in enumerate(v):
        if not isinstance(item, str):
            raise ValueError(f"opener_questions[{idx}] must be a string")
        stripped = item.strip()
        if not stripped:
            raise ValueError(f"opener_questions[{idx}] must not be empty")
        if len(stripped) > OPENER_QUESTION_MAX_LENGTH:
            raise ValueError(f"opener_questions[{idx}] must be ≤{OPENER_QUESTION_MAX_LENGTH} chars")
        cleaned.append(stripped)
    return cleaned


class MiddlewareConfigEntry(BaseModel):
    """Per-agent middleware configuration."""

    type: str
    params: dict[str, Any] = {}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        from app.agent_runtime.middleware_registry import MIDDLEWARE_REGISTRY

        if v not in MIDDLEWARE_REGISTRY:
            raise ValueError(f"Unknown middleware type: {v}")
        return v


def _validate_sub_agent_ids(v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
    """Reject duplicates. 自引用在没有 path id 的 schema 阶段无法阻止 →
    在 service 层追加校验。"""
    if v is None:
        return v
    seen: set[uuid.UUID] = set()
    for sid in v:
        if sid in seen:
            raise ValueError(f"sub_agent_ids contains duplicate: {sid}")
        seen.add(sid)
    return v


class AgentCreate(BaseModel):
    # M6: extra='forbid' — 旧版 client 如果发送 tool_configs / agent_config 等
    # 已删除字段，明确 reject. 为 422。禁止 silent drop。
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    system_prompt: str
    model_id: uuid.UUID
    tool_ids: list[uuid.UUID] = []
    mcp_tool_ids: list[uuid.UUID] = []
    skill_ids: list[uuid.UUID] = []
    sub_agent_ids: list[uuid.UUID] = Field(default_factory=list)
    middleware_configs: list[MiddlewareConfigEntry] = []
    template_id: uuid.UUID | None = None
    model_params: dict[str, Any] | None = None
    opener_questions: list[str] | None = None
    # Optional ordered list of fallback model ids — see model_factory.
    model_fallback_ids: list[uuid.UUID] | None = None
    identity_mode: str = AGENT_IDENTITY_PER_USER
    runtime_policy: RuntimePolicyV1 | None = None

    @field_validator("opener_questions")
    @classmethod
    def _validate_opener_questions(cls, v: list[str] | None) -> list[str] | None:
        return _validate_opener_questions(v)

    @field_validator("sub_agent_ids")
    @classmethod
    def _validate_sub_agent_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        # Create 不接收 None，因此 helper 结果始终是 list[UUID]。
        cleaned = _validate_sub_agent_ids(v)
        return cleaned if cleaned is not None else []

    @field_validator("identity_mode")
    @classmethod
    def _validate_identity_mode(cls, v: str) -> str:
        return validate_identity_mode(v)


class AgentUpdate(BaseModel):
    # M6: extra='forbid' — 原因与 AgentCreate 相同。
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model_id: uuid.UUID | None = None
    tool_ids: list[uuid.UUID] | None = None
    mcp_tool_ids: list[uuid.UUID] | None = None
    skill_ids: list[uuid.UUID] | None = None
    sub_agent_ids: list[uuid.UUID] | None = None
    middleware_configs: list[MiddlewareConfigEntry] | None = None
    is_favorite: bool | None = None
    model_params: dict[str, Any] | None = None
    opener_questions: list[str] | None = None
    model_fallback_ids: list[uuid.UUID] | None = None
    identity_mode: str | None = None
    runtime_policy: RuntimePolicyV1 | None = None

    @field_validator("opener_questions")
    @classmethod
    def _validate_opener_questions(cls, v: list[str] | None) -> list[str] | None:
        return _validate_opener_questions(v)

    @field_validator("sub_agent_ids")
    @classmethod
    def _validate_sub_agent_ids(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        return _validate_sub_agent_ids(v)

    @field_validator("identity_mode")
    @classmethod
    def _validate_identity_mode(cls, v: str | None) -> str | None:
        return validate_identity_mode(v) if v is not None else None


class ModelBrief(BaseModel):
    id: uuid.UUID
    display_name: str
    provider: str
    model_name: str
    # context window 上限（token）。供聊天 composer 的 context 使用量 gauge 引用。
    # 为 null 时表示模型未设置上限（gauge 禁用）。
    context_window: int | None = None

    model_config = {"from_attributes": True}


class ToolBrief(BaseModel):
    id: uuid.UUID
    name: str
    # 工具 registry 定义中的 icon_id（domain `icon_id`）。聊天工具 pill 用它选择语义 icon；
    # 如果 registry 中没有定义则为 null（前端 fallback 为 wrench）。
    icon_id: str | None = None

    model_config = {"from_attributes": True}


class McpToolBrief(BaseModel):
    """Per-server MCP tool reference for agent responses."""

    id: uuid.UUID
    name: str
    server_id: uuid.UUID
    server_name: str | None = None

    model_config = {"from_attributes": True}


class AgentBrief(BaseModel):
    """用于轻量 Agent 卡片的表示（如 subagent 列表）。"""

    id: uuid.UUID
    name: str
    description: str | None = None
    image_url: str | None = None

    model_config = {"from_attributes": True}


class AgentSummaryResponse(BaseModel):
    """Dashboard/sidebar card payload without eager-loaded nested resources."""

    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    is_favorite: bool = False
    image_url: str | None = None
    model_display_name: str | None = None
    tool_count: int = 0
    fallback_count: int = 0
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    unread_count: int = 0


class AgentResponse(BaseModel):
    id: uuid.UUID
    runtime_name: str
    identity_mode: str
    name: str
    description: str | None
    system_prompt: str
    # Optional so agents whose ``model_id`` FK target was deleted out from
    # under them (legacy data, manual cleanup, m18 wipe) still serialize.
    # The frontend renders a "no model bound" warning and prompts re-binding.
    model: ModelBrief | None = None
    llm_credential_id: uuid.UUID | None = None
    llm_credential_name: str | None = None
    llm_credential_status: str | None = None
    tools: list[ToolBrief]
    mcp_tools: list[McpToolBrief] = Field(default_factory=list)
    skills: list[SkillBrief] = []
    sub_agents: list[AgentBrief] = Field(default_factory=list)
    middleware_configs: list[dict[str, Any]] = []
    runtime_policy: RuntimePolicyV1 | None = None
    runtime_policy_effective: RuntimePolicyV1
    runtime_policy_source: RuntimePolicySnapshotSource
    status: str
    is_favorite: bool = False
    model_params: dict[str, Any] | None = None
    opener_questions: list[str] | None = None
    model_fallback_ids: list[uuid.UUID] = Field(default_factory=list)
    image_url: str | None = None
    template_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    # max(conversations.updated_at) — set by ``list_agents`` only. Single-row
    # endpoints leave it None and the frontend sidebar falls back to ``updated_at``.
    last_used_at: datetime | None = None
    unread_count: int = 0

    model_config = {"from_attributes": True}


class GenerateImageResponse(BaseModel):
    image_url: str
