"""Builder router — v3 Chat UI 集成 (POST /messages, /messages/resume, GET /image)。"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder_i18n import BuilderLocale, locale_scope, normalize_locale
from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.error_codes import (
    agent_creation_failed,
    image_not_found,
    no_draft_config,
    session_confirming,
    session_not_found,
    session_not_preview,
)
from app.exceptions import AppError, ValidationError
from app.routers.agents import _agent_to_response
from app.schemas.agent import AgentResponse
from app.schemas.builder import BuilderSessionResponse, BuilderStartRequest, BuilderStatus
from app.schemas.conversation import Decision
from app.services import builder_service


class BuilderMessageRequest(BaseModel):
    """Builder v3 — 消息发送请求。"""

    locale: BuilderLocale | None = None
    content: str = Field(..., min_length=1, max_length=4000)


class BuilderResumeRequest(BaseModel):
    """Builder v3 — interrupt 响应请求。标准 HiTL wire (ADR-012)。

    仅接受标准 ``decisions: list[Decision]``（clean break — extra
    field 返回 422）。router 通过 ``decisions_to_builder_response`` adapter
    转换为 builder graph 期待的 native shape (dict | str)。

    Decision → builder native 转换：
    - ``approve``                   → ``{"approved": True}``      (approval phase)
    - ``reject(message)``           → ``{"approved": False, "revision_message": ...}``
    - ``respond(message)``          → ``"..."``                    (ask_user / image_*)
    - ``edit(edited_action)``       → ``{"approved": True}``       (builder 不使用 edit)
    """

    model_config = {"extra": "forbid"}

    locale: BuilderLocale | None = None
    decisions: list[Decision] = Field(..., min_length=1, description="标准 HiTL decisions")
    display_text: str | None = Field(None, max_length=200)
    # SSE interrupt event 的 interrupt_id（用于阻止 stale 卡片响应）
    interrupt_id: str | None = Field(None, max_length=200)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/builder", tags=["builder"])


@router.post("", response_model=BuilderSessionResponse, status_code=201)
async def start_build(
    data: BuilderStartRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """启动 Build Session。"""
    return await builder_service.create_session(db, user.id, data.user_request)


@router.get("/{session_id}", response_model=BuilderSessionResponse)
async def get_build_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """查询 Build Session 状态。"""
    session = await builder_service.get_session(db, session_id, user.id)
    if not session:
        raise session_not_found()
    return session


@router.post(
    "/{session_id}/confirm",
    response_model=AgentResponse,
    status_code=201,
)
async def confirm_build(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """确认 Build 并创建实际 Agent。

    保证幂等性：
    - COMPLETED + 有 agent_id → 返回现有 Agent（防止重复创建）
    - CONFIRMING → 409（其他请求处理中）
    - PREVIEW → 原子切换到 CONFIRMING 后创建 Agent
    """
    session = await builder_service.get_session(db, session_id, user.id)
    if not session:
        raise session_not_found()

    # 幂等：若 Session 已完成，则返回现有 Agent
    if session.status == BuilderStatus.COMPLETED and session.agent_id:
        existing_agent = await builder_service.get_agent_by_id(db, session.agent_id)
        if existing_agent:
            return _agent_to_response(existing_agent)

    # 防止并发请求：若已是 CONFIRMING，则返回 409
    if session.status == BuilderStatus.CONFIRMING:
        raise session_confirming()

    if session.status != BuilderStatus.PREVIEW:
        raise session_not_preview()
    if not session.draft_config:
        raise no_draft_config()

    # 原子 PREVIEW → CONFIRMING 切换
    claimed = await builder_service.claim_for_confirming(db, session_id, user.id)
    if not claimed:
        raise session_confirming()

    # 重新加载 Session（状态切换后的 fresh 状态）
    session = await builder_service.get_session(db, session_id, user.id)
    if not session:
        raise session_not_found()

    try:
        with locale_scope(request.cookies.get("moldy_locale")):
            agent = await builder_service.confirm_build(db, session)
    except AppError:
        raise
    except ValueError as exc:
        raise ValidationError("MODEL_NOT_FOUND", str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected error during confirm_build for session %s",
            session_id,
        )
        raise agent_creation_failed() from exc

    if not agent:
        raise agent_creation_failed("无法创建 Agent")
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# Builder v3 — Chat UI 集成 endpoint
# ---------------------------------------------------------------------------

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/{session_id}/messages")
async def post_message(
    session_id: uuid.UUID,
    payload: BuilderMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Builder v3 — 发送用户消息并接收 SSE stream。

    第一条消息：从头执行 graph（从 Phase 1 开始）。
    后续消息：如果 graph 正在进行，仅追加 messages。
    """
    session = await builder_service.get_session(db, session_id, user.id)
    if not session:
        raise session_not_found()

    return StreamingResponse(
        builder_service.run_v3_message_stream(
            session_id=session.id,
            user_id=session.user_id,
            content=payload.content,
            locale=normalize_locale(payload.locale or request.cookies.get("moldy_locale")),
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/{session_id}/messages/resume")
async def resume_message(
    session_id: uuid.UUID,
    payload: BuilderResumeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Builder v3 — 传递 interrupt 响应并恢复 graph。"""
    session = await builder_service.get_session(db, session_id, user.id)
    if not session:
        raise session_not_found()

    response = builder_service.decisions_to_builder_response(payload.decisions)
    return StreamingResponse(
        builder_service.run_v3_resume_stream(
            session_id=session.id,
            user_id=session.user_id,
            response=response,
            interrupt_id=payload.interrupt_id,
            locale=normalize_locale(payload.locale or request.cookies.get("moldy_locale")),
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/{session_id}/image/{filename}")
async def serve_builder_image(
    session_id: uuid.UUID,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """提供 Phase 6 生成的临时图像预览。

    仅 Session owner 可访问（阻止访问其他用户的 builder 图像）。
    """
    from app.agent_runtime.builder_v3.image_gen import resolve_local_path

    session = await builder_service.get_session(db, session_id, user.id)
    if not session:
        raise session_not_found()

    path = resolve_local_path(str(session_id), filename)
    if not path:
        raise image_not_found()

    return FileResponse(path)


@router.get("/{session_id}/snapshot")
async def get_builder_snapshot(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.agent_runtime.builder_v3.graph import compile_graph
    from app.agent_runtime.checkpointer import get_checkpointer
    from app.agent_runtime.message_utils import content_to_text

    session = await builder_service.get_session(db, session_id, user.id)
    if session is None:
        raise session_not_found()
    state = await compile_graph(get_checkpointer()).aget_state(
        {"configurable": {"thread_id": str(session_id)}}
    )
    messages = []
    for index, message in enumerate(state.values.get("messages", [])):
        role = {"human": "user", "ai": "assistant", "tool": "tool"}.get(message.type)
        if role is None:
            continue
        messages.append(
            {
                "id": message.id or str(uuid.uuid5(session_id, str(index))),
                "conversation_id": str(session_id),
                "role": role,
                "content": content_to_text(message.content),
                "tool_calls": getattr(message, "tool_calls", None),
                "tool_call_id": getattr(message, "tool_call_id", None),
                "created_at": session.updated_at.isoformat(),
            }
        )
    interrupts = [item for task in state.tasks for item in task.interrupts]
    return {
        "messages": messages,
        "interrupt_id": interrupts[0].id if interrupts else None,
        "status": session.status,
        "agent_id": session.agent_id,
    }
