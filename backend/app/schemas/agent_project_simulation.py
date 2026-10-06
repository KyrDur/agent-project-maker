"""模拟聊天接口；场景及模型配置只来自服务器冻结记录。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    version_id: uuid.UUID
    scenario_id: uuid.UUID | None = None


class SimulationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: uuid.UUID
    content: str = Field(min_length=1, max_length=10000)


class SimulationReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID


class SimulationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_id: uuid.UUID
    scenario_id: uuid.UUID
    state_json: dict[str, Any]
    messages_json: list[dict[str, Any]]
    turns_json: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
