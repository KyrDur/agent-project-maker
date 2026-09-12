from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    agent_id: uuid.UUID
    builder_session_id: uuid.UUID | None
    title: str
    requirements_json: dict[str, Any] | None
    eval_spec_json: dict[str, Any] | None
    report_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class AgentProjectVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    version_number: int
    parent_version_id: uuid.UUID | None
    status: Literal["original", "candidate", "accepted", "rejected"]
    change_summary: str | None
    config_hash: str | None
    created_at: datetime


class AgentProjectVersionResponse(AgentProjectVersionSummary):
    snapshot_json: dict[str, Any]


class VersionCreate(BaseModel):
    request_id: uuid.UUID
    change_summary: str | None = Field(default=None, max_length=1000)


class VersionCreated(BaseModel):
    outcome: Literal["created", "unchanged", "replayed"]
    version: AgentProjectVersionResponse


class CaseContext(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=10000)


class CaseExpected(BaseModel):
    answer: str | None = Field(default=None, max_length=10000)
    exact_answer: str | None = Field(default=None, max_length=10000)
    required_tools: list[str] = Field(default_factory=list, max_length=30)
    forbidden_tools: list[str] = Field(default_factory=list, max_length=30)
    handoff: str | None = Field(default=None, max_length=100)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=10000)
    context: list[CaseContext] = Field(default_factory=list, max_length=10)
    expected: CaseExpected = Field(default_factory=CaseExpected)
    tags: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True


class EvalSetWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cases: list[EvaluationCase] = Field(default_factory=list, max_length=20)


class EvalSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    cases_json: list[dict[str, Any]]
    frozen: bool
    created_at: datetime


class EvalRunCreate(BaseModel):
    request_id: uuid.UUID
    version_id: uuid.UUID
    eval_set_id: uuid.UUID


class EvalRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    version_id: uuid.UUID
    eval_set_id: uuid.UUID
    status: Literal["pending", "running", "completed", "failed"]
    dataset_hash: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    metrics_json: dict[str, Any] | None
    results_json: list[dict[str, Any]] | None
    pass_rate: float | None
