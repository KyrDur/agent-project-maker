"""Evaluation defaults are project heuristics, not validated optimal thresholds."""
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_QUALITY_THRESHOLD = 0.75


class QualityThresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    relevance: float = Field(default=DEFAULT_QUALITY_THRESHOLD, ge=0, le=1, allow_inf_nan=False)
    accuracy: float = Field(default=DEFAULT_QUALITY_THRESHOLD, ge=0, le=1, allow_inf_nan=False)
    completeness: float = Field(default=DEFAULT_QUALITY_THRESHOLD, ge=0, le=1, allow_inf_nan=False)
    helpfulness: float = Field(default=DEFAULT_QUALITY_THRESHOLD, ge=0, le=1, allow_inf_nan=False)


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    quality_thresholds: QualityThresholds = Field(default_factory=QualityThresholds)


DEFAULT_CONFIG = EvaluationConfig()
