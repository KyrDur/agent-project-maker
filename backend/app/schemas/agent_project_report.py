"""Read-only reports backed by historical evaluation runs."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportFailure(BaseModel):
    case_id: str
    name: str
    reasons: list[str]


class EvaluationReport(BaseModel):
    version_id: uuid.UUID
    eval_set_id: uuid.UUID
    evaluation_run_id: uuid.UUID
    status: str
    score: float | None
    metrics: dict[str, float]
    total: int
    passed: int
    bad_case_count: int
    bad_cases: list[ReportFailure]
    optimization_suggestions: list[str]
    comparison_key: str | None
    created_at: datetime
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    source_run_id: str | None = None


class EvaluationReports(BaseModel):
    reports: list[EvaluationReport]
    best_run_ids: dict[str, uuid.UUID]
    active: bool
