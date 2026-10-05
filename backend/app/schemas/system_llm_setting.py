"""Pydantic schemas for System LLM settings (ADR-019)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class SystemLlmSettingOut(BaseModel):
    """A single role slot's resolved configuration for the operator screen."""

    role: str
    credential_id: uuid.UUID | None = None
    credential_name: str | None = None
    # Derived from credential.definition_key (single source of truth).
    provider: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    # True when both credential and model are selected (slot is usable).
    configured: bool = False
    updated_at: datetime


class SystemLlmSettingUpdate(BaseModel):
    """PUT body — selects (or clears) the credential/model for a role."""

    credential_id: uuid.UUID | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_selection(self):
        if (self.credential_id is None) != (self.model_name is None):
            raise ValueError("Select both credential and model, or clear both")
        if self.model_name is not None and not self.model_name.strip():
            raise ValueError("Model name cannot be blank")
        return self


class SystemLlmTestRequest(BaseModel):
    """POST body for testing one selected platform AI provider/credential/model."""

    provider: str
    credential_id: uuid.UUID
    model_name: str
