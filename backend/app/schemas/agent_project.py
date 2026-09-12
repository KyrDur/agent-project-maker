from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    format_rule: Literal["json_object", "json_array"] | None = None


class MockToolBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(default="Frozen evaluation mock", max_length=1000)
    result: Any = None
    error: str | None = Field(default=None, max_length=500)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=10000)
    context: list[CaseContext] = Field(default_factory=list, max_length=10)
    expected: CaseExpected = Field(default_factory=CaseExpected)
    tags: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True
    mock_tool_data: dict[str, MockToolBehavior] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def bounded_mocks(self) -> Self:
        import json
        import re

        if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", key) for key in self.mock_tool_data):
            raise ValueError("Invalid mock tool name")
        if len(json.dumps(self.model_dump(mode="json"))) > 100000:
            raise ValueError("Case is too large")
        return self


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
    rubric_json: dict[str, Any] | None = None


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
    comparison_json: dict[str, Any] | None = None


class EvalGenerationRequest(BaseModel):
    version_id: uuid.UUID


class EvalMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["llm_judge", "deterministic"]
    weight: float = Field(gt=0, le=1, allow_inf_nan=False)
    criteria: str = Field(min_length=1, max_length=2000)


SCENARIOS = (
    "normal",
    "missing_information",
    "ambiguous",
    "tool_failure",
    "edge_case",
    "hallucination",
)
METRICS = {
    "task_completion",
    "tool_correctness",
    "groundedness",
    "format_compliance",
    "business_quality",
}


class EvalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: list[EvalMetric] = Field(min_length=3, max_length=5)
    pass_threshold: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_metrics(self) -> Self:
        names = [metric.name for metric in self.metrics]
        if (
            len(set(names)) != len(names)
            or len(set(names) - METRICS) > 1
            or len(set(names) & METRICS) < 3
        ):
            raise ValueError("Duplicate or excess custom metrics")
        if abs(sum(metric.weight for metric in self.metrics) - 1) > 0.001:
            raise ValueError("Weights must sum to one")
        for metric in self.metrics:
            expected = "deterministic" if metric.name == "tool_correctness" else "llm_judge"
            if metric.name != "format_compliance" and metric.type != expected:
                raise ValueError("Invalid metric type")
        return self


class JudgeScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    passed: bool
    reason: str = Field(min_length=1, max_length=2000)
