"""Pydantic schemas for share links + public conversation views.

Owner-facing endpoints expose ``ShareLinkResponse`` (token + lifecycle
metadata). Public visitor endpoints expose ``SharedConversationView``
(read-only conversation snapshot — agent identity, title, messages) which
deliberately omits ownership / debug fields so the public surface stays
minimal.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.schemas.conversation import MessageResponse, TurnTraceResponse, UtcDatetime


class ShareLinkResponse(BaseModel):
    """Owner-facing share link metadata (returned on create / fetch)."""

    id: uuid.UUID
    share_token: str
    conversation_id: uuid.UUID
    created_at: UtcDatetime
    revoked_at: UtcDatetime | None = None

    model_config = {"from_attributes": True}


class SharedAgentBrief(BaseModel):
    """Minimal agent identity for the public share header."""

    name: str
    description: str | None = None
    image_url: str | None = None


class SharedConversationView(BaseModel):
    """Public read-only conversation snapshot returned by ``/api/shares/{token}``.

    ``traces``（W6）：按 turn 的 SSE event 序列。用于公开页面渲染工具/Skill chip。
    若为空数组，则表示该对话没有 trace（在 W5 merge 之前创建）。
    """

    share_token: str
    conversation_title: str | None = None
    conversation_created_at: UtcDatetime
    agent: SharedAgentBrief
    messages: list[MessageResponse]
    traces: list[TurnTraceResponse] = []
    shared_at: UtcDatetime
