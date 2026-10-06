from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    decisions_json: list[dict[str, Any]] | None = None
    completion_json: dict[str, Any] | None = None
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
    created_from: dict[str, str] | None = None


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


class ProjectRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1, max_length=4000)
    inputs: str = Field(min_length=1, max_length=4000)
    deliverables: str = Field(min_length=1, max_length=4000)
    business_rules: str = Field(min_length=1, max_length=4000)
    success_conditions: str = Field(min_length=1, max_length=4000)


class ProjectDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stage: Literal["requirements", "capabilities", "case_review", "optimization"]
    choice: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)
    version_id: uuid.UUID
    eval_set_id: uuid.UUID | None = None
    case_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class StateAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$"
    )
    value: Any


class ToolAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CaseExpected(BaseModel):
    max_characters: int | None = Field(default=None, ge=1, le=10000)
    state: list[StateAssertion] = Field(default_factory=list, max_length=20)
    tool_arguments: list[ToolAssertion] = Field(default_factory=list, max_length=20)
    necessary_order: list[str] = Field(default_factory=list, max_length=30)
    answer: str | None = Field(default=None, max_length=10000)
    exact_answer: str | None = Field(default=None, max_length=10000)
    attempted_tools: list[str] = Field(default_factory=list, max_length=30)
    required_tools: list[str] = Field(default_factory=list, max_length=30)
    forbidden_tools: list[str] = Field(default_factory=list, max_length=30)
    handoff: str | None = Field(default=None, max_length=100)
    format_rule: Literal["json_object", "json_array"] | None = None


class MockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = Field(default=None, max_length=500)


class MockToolBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(default="Frozen evaluation mock", max_length=1000)
    result: Any = None
    error: str | None = Field(default=None, max_length=500)
    responses: list[MockResponse] = Field(default_factory=list, max_length=50)
    fail_on_calls: list[int] = Field(default_factory=list, max_length=20)
    operation: Literal["static", "query", "update"] = "static"
    collection: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    match_fields: list[str] = Field(default_factory=list, max_length=20)
    update_fields: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_operation(self) -> Self:
        if any(n < 1 for n in self.fail_on_calls):
            raise ValueError("Call numbers start at one")
        if self.operation != "static" and (not self.collection or not self.match_fields):
            raise ValueError("State operations need a collection and match fields")
        if self.operation == "update" and not self.update_fields:
            raise ValueError("Updates need explicit writable fields")
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_type: Literal["normal", "edge", "failure"] = "normal"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    source: Literal["ai_generated", "imported", "official_benchmark"] = "ai_generated"
    initial_state: dict[str, Any] = Field(default_factory=dict)
    judgment_basis: str | None = Field(default=None, max_length=4000)
    expected_behavior: dict[str, Any] | None = None
    metric_applicability: dict[str, list[str]] | None = None
    metric_applicability_reasons: dict[str, str] = Field(default_factory=dict)
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
    evaluation_focus_json: list[dict[str, Any]] | None = None
    evaluation_focus_reason: str | None = None
    cases_json: list[dict[str, Any]]
    frozen: bool
    quality_report_json: dict[str, Any] | None = None
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
    bad_cases_json: list[dict[str, Any]] | None = None


class EvalGenerationRequest(BaseModel):
    version_id: uuid.UUID


class EvalCaseGenerationRequest(EvalGenerationRequest):
    evaluation_focus: list[str] | None = Field(default=None, min_length=2, max_length=8)
    evaluation_focus_reason: str | None = Field(default=None, max_length=1000)


class RequirementReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    field: Literal["goal", "inputs", "deliverables", "business_rules", "success_conditions"]
    quote: str = Field(min_length=1, max_length=4000)


class ScoringCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=1000)
    requirement_refs: list[RequirementReference] = Field(min_length=1, max_length=5)
    fail: str = Field(min_length=1, max_length=1000)
    partial: str = Field(min_length=1, max_length=1000)
    full: str = Field(min_length=1, max_length=1000)
    critical: bool = False


class EvalMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["llm_judge", "deterministic"]
    weight: float = Field(gt=0, le=1, allow_inf_nan=False)
    criteria: str = Field(min_length=1, max_length=2000)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    requirement_refs: list[RequirementReference] = Field(default_factory=list, max_length=5)
    scoring_mode: Literal["legacy", "all_checks", "criterion_mean"] = "legacy"
    scoring_criteria: list[ScoringCriterion] = Field(default_factory=list, max_length=8)


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
    capability_profile: dict[str, Any] = Field(default_factory=dict)
    rubric_version: Literal[1, 2] = 1
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
            if self.rubric_version == 2:
                if not metric.display_name or not metric.description or not metric.requirement_refs:
                    raise ValueError("Missing metric explanation or requirement source")
                mode = "all_checks" if metric.type == "deterministic" else "criterion_mean"
                if metric.scoring_mode != mode:
                    raise ValueError("Scoring method must match execution")
                ids = [c.id for c in metric.scoring_criteria]
                if metric.type == "llm_judge" and (not ids or len(set(ids)) != len(ids)):
                    raise ValueError("Missing or duplicate scoring criteria")
                if metric.type == "deterministic" and ids:
                    raise ValueError("Deterministic rules come from program assertions")
        return self


class CriterionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reference: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=4000)


class CriterionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    criterion_id: str
    level: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=2000)
    evidence: list[CriterionEvidence] = Field(min_length=1, max_length=5)

    @field_validator("level", mode="before")
    @classmethod
    def numeric_level(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Level must be a number, not a boolean or string")
        if value not in {0, 0.5, 1}:
            raise ValueError("Level must be exactly 0, 0.5 or 1")
        return value


class RubricRuleReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    reference: str
    supported: bool
    reason: str = Field(min_length=1, max_length=2000)


class JudgeScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    passed: bool
    reason: str = Field(min_length=1, max_length=2000)


class ProjectCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    analysis: str = Field(default="", max_length=10000)
