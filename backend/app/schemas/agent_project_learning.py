from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BriefContent(BaseModel):
    audience: str = Field(min_length=1, max_length=500)
    problem: str = Field(min_length=1, max_length=1000)
    workflow: str = Field(min_length=1, max_length=1500)
    success_criteria: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        min_length=2, max_length=6
    )


class BriefGenerate(BaseModel):
    version_id: uuid.UUID
    locale: Literal["zh-CN", "en"] = "zh-CN"


class BriefConfirm(BaseModel):
    version_id: uuid.UUID
    draft_hash: str = Field(min_length=64, max_length=64)
    content: BriefContent


class CaseReview(BaseModel):
    passed: bool
    reason: str = Field(min_length=1, max_length=1000)


class InterviewAnswer(BaseModel):
    topic: Literal["contribution", "failure", "decision", "results", "next_step"]
    answer: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class InterviewDraft(BaseModel):
    short_intro: str = Field(min_length=1, max_length=1200)
    long_intro: str = Field(min_length=1, max_length=3500)
    answers: list[InterviewAnswer] = Field(min_length=5, max_length=5)


class HoldoutGenerate(BaseModel):
    development_set_id: uuid.UUID
    request_id: uuid.UUID


class RepeatRequest(BaseModel):
    request_id: uuid.UUID
    repetitions: int = Field(default=3, ge=2, le=5)


class ValidationRequest(RepeatRequest):
    baseline_run_id: uuid.UUID
    candidate_version_id: uuid.UUID
    holdout_set_id: uuid.UUID
