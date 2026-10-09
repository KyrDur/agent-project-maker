"""Immutable evidence from interactive use and repeated experiments."""
from pydantic import Field
from typing import Literal
from .models import Artifact, uid
from .retrieval_models import RetrievalConfig

class ChatTurn(Artifact):
    turn_id: str = Field(default_factory=uid)
    conversation_id: str
    sequence: int
    index_id: str
    knowledge_version: int
    provider_session_id: str
    provider_configuration_snapshot: dict
    retrieval_config: RetrievalConfig
    pipeline: dict
    message: str
    context: list[dict]
    answer: str
    status: Literal['SUCCESS','FAILED']
    error: str | None = None
    retrieval: dict
    citations: list[dict]
    provider_observations: list[dict]
    provider_call_count: int
    latency_ms: float

class RepeatReport(Artifact):
    report_id: str = Field(default_factory=uid)
    source_run_id: str
    run_ids: list[str]
    repetitions: int
    summary: dict
    provider_call_count: int
    warnings: list[str]

class ExperimentConclusion(Artifact):
    conclusion_id: str = Field(default_factory=uid)
    comparison_id: str
    decision: Literal['KEEP','REVISE','REVERT']
    reason: str
    user_confirmed: Literal[True]

class InterviewAttempt(Artifact):
    attempt_id: str = Field(default_factory=uid)
    material_id: str
    question_id: str
    answer: str
    claim_ids: list[str]
    limitations: str
    checks: dict
