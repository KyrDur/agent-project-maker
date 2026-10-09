"""Artifact schemas follow the accepted Phase 3A design."""
from typing import Any, Literal
from uuid import uuid4
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, model_validator
from evaluation.models import EvaluationCase, CaseResult, Status

def uid():
    return str(uuid4())

def now():
    return datetime.now(timezone.utc).isoformat()

class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1"
    created_at: str = Field(default_factory=now)

class IntentCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    message: str = Field(min_length=1)
    expected_intent: str
    context: dict[str, Any] = Field(default_factory=dict)

class EvalSet(Artifact):
    hash_protocol_version: str = "1"
    eval_set_id: str = Field(default_factory=uid)
    eval_set_version: int = Field(default=1, ge=1)
    eval_set_hash: str
    case_snapshot: list[EvaluationCase]
    intent_case_snapshot: list[IntentCase] = Field(default_factory=list)
    pass_criteria_snapshot: dict
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [c.case_id for c in self.case_snapshot + self.intent_case_snapshot]
        if len(ids) != len(set(ids)) or not ids:
            raise ValueError("EvalSet needs unique stable case IDs and at least one case")
        return self

    @property
    def snapshot(self):
        return self.model_dump()

class Run(Artifact):
    run_id: str = Field(default_factory=uid)
    provider_session_id: str | None = None
    provider_configuration_snapshot: dict = Field(default_factory=dict)
    provider_readiness_snapshot: dict = Field(default_factory=dict)
    provider_observations: list[dict] = Field(default_factory=list)
    provider_call_count: int = 0
    run_type: Literal["BASELINE", "RETEST"]
    parent_run_id: str | None = None
    decision_id: str | None = None
    applied_change_ids: list[str] = Field(default_factory=list)
    eval_set_id: str
    eval_set_hash: str
    eval_set_snapshot: dict
    evaluation_config_snapshot: dict
    evaluation_protocol_snapshot: dict
    evaluation_protocol_hash: str
    agent_config_snapshot: dict
    inference_config_snapshot: dict
    skill_version: dict
    prompt_version: dict
    knowledge_version: dict
    routing_config_version: dict
    runtime_policy_snapshot: dict
    runtime_start_snapshot: dict
    runtime_end_check: dict = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    status: Literal["CREATED", "RUNNING", "COMPLETE", "PARTIAL", "FAILED"] = "CREATED"
    execution_order: list[str]
    case_results: list[CaseResult] = Field(default_factory=list)
    intent_metrics: dict = Field(default_factory=dict)
    intent_sample_results: list[dict] = Field(default_factory=list)
    artifact_hash: str | None = None
    metadata: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    sampling_mode: Literal["single_run"] = "single_run"

class Decision(Artifact):
    decision_id: str = Field(default_factory=uid)
    related_run_id: str
    selected_case_ids: list[str]
    root_cause_suggestion: str | None = None
    strategy_suggestion: str | None = None
    user_confirmed_root_cause: str | None = None
    root_cause_reason: str = ""
    alternatives: list[dict] = Field(default_factory=list)
    selected_strategy: str | None = None
    selection_reason: str = ""
    expected_benefit: str = ""
    possible_side_effects: str = ""
    status: Literal["DRAFT", "CONFIRMED"] = "DRAFT"
    confirmed_by: str | None = None
    confirmed_at: str | None = None

    @model_validator(mode="after")
    def confirmation(self):
        if self.status == "CONFIRMED" and not all(v and v.strip() for v in (
            self.user_confirmed_root_cause, self.root_cause_reason, self.selected_strategy,
            self.selection_reason, self.confirmed_by, self.confirmed_at)):
            raise ValueError("Explicit user confirmation with reasons is required")
        return self

class Change(Artifact):
    change_id: str = Field(default_factory=uid)
    decision_id: str
    baseline_run_id: str
    change_type: Literal["SKILL_RULE", "PROMPT", "KNOWLEDGE"]
    affected_component: str
    change_scope: str = "ONE_SKILL_RULE_BODY"
    declared_diff: list[dict] = Field(default_factory=list)
    observed_diff: list[dict] = Field(default_factory=list)
    before_snapshot: dict
    before_hash: str
    after_snapshot: dict
    after_hash: str
    implemented_status: Literal["PROPOSED", "APPLYING", "APPLIED", "FAILED", "NOOP", "UNSUPPORTED"] = "PROPOSED"
    applied_at: str | None = None
    verified_effective_version: str | None = None
    rollback_status: Literal["NOT_REQUESTED", "ROLLING_BACK", "ROLLED_BACK", "FAILED"] = "NOT_REQUESTED"
    rollback_at: str | None = None
    application_evidence: dict = Field(default_factory=dict)
    error: str | None = None

class ReviewRecord(Artifact):
    review_id: str = Field(default_factory=uid)
    run_id: str
    case_id: str
    revision: int = Field(ge=1)
    human_final_status: Status
    human_reason: str = Field(min_length=1)
    reviewed_at: str = Field(default_factory=now)
    reviewer: str = Field(min_length=1)
    hard_rule_override: bool
    original_status: Status
    original_reason: str

class Comparison(Artifact):
    comparison_id: str = Field(default_factory=uid)
    baseline_run_id: str
    retest_run_id: str
    protocol_version: str = "1"
    comparable: bool
    comparability_reasons: list[str]
    comparison_completeness: Literal["FULL", "PARTIAL"]
    completeness_reasons: list[str] = Field(default_factory=list)
    expected_case_count: int
    matched_case_count: int
    attributable: bool
    single_recorded_change: bool = False
    runtime_scope: str = ""
    attribution_status: Literal["SINGLE_CHANGE_ELIGIBLE", "MULTI_CHANGE", "MULTI_COMPONENT_CHANGE",
                               "NO_CHANGE", "UNRECORDED_CHANGE", "INSUFFICIENT_EVIDENCE", "NOT_COMPARABLE"]
    attribution_warnings: list[str]
    observed_config_diff: list[dict]
    applied_change_ids: list[str]
    review_revision_a: int
    review_revision_b: int
    status_source: Literal["EFFECTIVE"] = "EFFECTIVE"
    case_comparisons: list[dict]
    group_metrics: dict

    @property
    def direct_comparison(self):
        return self.comparable
