"""Portfolio requests contain no model prompts or metric overrides."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: Literal["ai_product", "product", "engineering"] = "ai_product"
