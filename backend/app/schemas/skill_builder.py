from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type SkillDraftFileRole = Literal["skill", "script", "reference", "asset", "metadata", "eval"]


class SkillBuilderMode(StrEnum):
    CREATE = "create"
    IMPROVE = "improve"


class SkillBuilderStatus(StrEnum):
    # v2 状态机：active → confirming → completed（+abandoned = GC 对象）。
    ACTIVE = "active"
    ABANDONED = "abandoned"
    # 旧 one-pass flow 的 legacy 值 — 为兼容已有 row 保留。
    COLLECTING = "collecting"
    DRAFTING = "drafting"
    REVIEW = "review"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SkillBuilderStartRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: SkillBuilderMode = SkillBuilderMode.CREATE
    user_request: str = Field(..., min_length=1, max_length=4000)
    source_skill_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_source_skill_for_improve(self) -> Self:
        if self.mode is SkillBuilderMode.IMPROVE and self.source_skill_id is None:
            raise PydanticCustomError(
                "source_skill_required",
                "source_skill_id is required in improve mode",
            )
        return self


class SkillDraftFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str = Field(..., min_length=1, max_length=500)
    content: str
    media_type: str = "text/plain"
    role: SkillDraftFileRole = "skill"


class SkillBuilderFileEntry(BaseModel):
    """草稿工作区文件摘要（rail source view，M7）— 不含内容。"""

    model_config = ConfigDict(frozen=True)

    path: str
    size: int
    role: str


class SkillBuilderFilesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: list[SkillBuilderFileEntry]


class SkillBuilderFileContentResponse(BaseModel):
    """草稿文件内容（仅 owner 可查询 — rail source viewer）。"""

    model_config = ConfigDict(frozen=True)

    path: str
    role: str
    content: str


class SkillDraftPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1, max_length=160)
    slug: str = Field(..., min_length=1, max_length=160)
    description: str = Field(..., min_length=1, max_length=1000)
    files: list[SkillDraftFile] = Field(default_factory=list)
    credential_requirements: list[dict[str, JsonValue]] = Field(default_factory=list)
    execution_profile: dict[str, JsonValue] = Field(default_factory=dict)
    validation_issues: list[dict[str, JsonValue]] = Field(default_factory=list)
    compatibility_result: dict[str, JsonValue] | None = None
    changelog_draft: dict[str, JsonValue] | None = None
    evals: dict[str, JsonValue] | None = None
    benchmark: dict[str, JsonValue] | None = None


class SkillBuilderSessionBrief(BaseModel):
    """用于会话列表的轻量响应 — 排除 draft/snapshot 等较重的 JSON 列。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    mode: SkillBuilderMode
    status: SkillBuilderStatus
    user_request: str
    source_skill_id: uuid.UUID | None = None
    finalized_skill_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class SkillBuilderSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID
    user_request: str
    mode: SkillBuilderMode
    status: SkillBuilderStatus
    current_phase: int
    source_skill_id: uuid.UUID | None = None
    base_skill_version: str | None = None
    base_content_hash: str | None = None
    base_snapshot: dict[str, JsonValue] | None = None
    messages: list[JsonValue] | None = None
    intent: dict[str, JsonValue] | None = None
    draft_package: dict[str, JsonValue] | None = None
    validation_result: dict[str, JsonValue] | None = None
    compatibility_result: dict[str, JsonValue] | None = None
    changelog_draft: dict[str, JsonValue] | None = None
    eval_result: dict[str, JsonValue] | None = None
    trigger_eval_result: dict[str, JsonValue] | None = None
    finalized_skill_id: uuid.UUID | None = None
    # v2（Builder 聊天）：Builder 对话/hidden Agent 标识符。conversation_id 从 session
    # 列中读取，agent_id 由 router 从对话反向引用填充（不是 ORM 属性）。
    conversation_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
