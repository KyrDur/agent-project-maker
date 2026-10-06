"""Follow-up suggestion endpoint (composer ghost text).

POST-per-run（前端的 run 结束 hook 调用 1 次）— 由于不是 polling 路径，
checkpointer tail 查询成本限制为每个 run 1 次。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, owned_conversation, verify_csrf
from app.models.conversation import Conversation
from app.services.followup_service import generate_followup_suggestion

router = APIRouter(tags=["conversations"])


class FollowupSuggestionResponse(BaseModel):
    suggestion: str | None


@router.post(
    "/api/conversations/{conversation_id}/followup-suggestion",
    response_model=FollowupSuggestionResponse,
)
async def create_followup_suggestion(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
    conversation: Conversation = Depends(owned_conversation),
) -> FollowupSuggestionResponse:
    suggestion = await generate_followup_suggestion(db, conversation, user.id)
    return FollowupSuggestionResponse(suggestion=suggestion)
