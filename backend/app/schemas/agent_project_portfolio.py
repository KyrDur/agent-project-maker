"""Portfolio requests contain no model prompts or metric overrides."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: Literal["ai_product"] = "ai_product"


class CaseSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=2)
