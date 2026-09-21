"""Validated analysis and minimal snapshot patch contracts."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "instruction_issue",
    "skill_issue",
    "tool_selection_issue",
    "tool_description_issue",
    "output_issue",
    "external_unfixable",
]
Target = Literal["instructions", "skill_content", "tool_description", "output_instructions", "none"]


class BadCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: uuid.UUID
    category: Category
    root_cause: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(min_length=1, max_length=10)
    recommended_target: Target
    suggested_fix: str = Field(max_length=2000)


class OptimizationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    root_cause: str = Field(min_length=1, max_length=2000)
    target: Target
    proposed_change: str = Field(min_length=1, max_length=2000)


class AnalysisProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analyses: list[BadCase] = Field(max_length=20)
    groups: list[OptimizationGroup] = Field(max_length=5)


class SnapshotPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_index: int = Field(ge=0, le=4)
    target: Target
    resource_id: str | None = Field(default=None, max_length=100)
    operation: Literal["append", "replace_section", "replace_value"]
    old_content: str | None = Field(default=None, max_length=800)
    content: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=2000)


class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: list[SnapshotPatch] = Field(max_length=5)


class OptimizeRequest(BaseModel):
    request_id: uuid.UUID


class OptimizationDraft(PatchProposal):
    title: str = Field(default="Evidence-based optimization", min_length=1, max_length=120)
    what_changes: str = Field(default="", max_length=1000)
    why_it_may_work: str = Field(default="", max_length=1000)
    benefits: list[str] = Field(default_factory=list, max_length=5)
    risks: list[str] = Field(default_factory=list, max_length=5)
    targeted_case_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    affected_capabilities: list[str] = Field(min_length=1, max_length=20)


class OptimizationProposalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[OptimizationDraft] = Field(min_length=2, max_length=3)


class ProposalDecision(BaseModel):
    decision: Literal["accepted", "rejected"]
    decision_reason: str | None = Field(default=None, max_length=1000)
