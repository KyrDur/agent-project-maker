"""Phase 8 — 최종 승인 + 빌드 (propose + wait 2-노드 패턴).

phase8_propose: draft_approval ToolMessage emit + dict 반환
phase8_build_wait: interrupt → 승인 시 Agent 생성 후 END, 수정 시 router로
"""

from __future__ import annotations

import logging
import uuid

from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from sqlalchemy import select

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_phase_complete,
    close_pending_tool_card,
    ensure_todos,
    make_pending_tool_card,
)
from app.agent_runtime.builder_v3.state import BuilderState
from app.database import async_session as async_session_factory
from app.models.builder_session import BuilderSession
from app.schemas.builder import BuilderStatus

logger = logging.getLogger(__name__)


async def _confirm_and_create_agent(state: BuilderState) -> tuple[str | None, str | None]:
    """builder_session.status=PREVIEW에서 Agent 생성까지 처리.

    Returns:
        (agent_id, error_message). 성공 시 agent_id만, 실패 시 error만 채워짐.
    """
    session_id_str = state.get("session_id", "")
    if not session_id_str:
        return None, tr("session_id_none_3e17d0")
    try:
        sid = uuid.UUID(session_id_str)
    except ValueError:
        return None, tr("invalid_session_id_a70fd8")

    from app.services.builder_service import claim_for_confirming, confirm_build

    try:
        async with async_session_factory() as db:
            stmt = select(BuilderSession).where(BuilderSession.id == sid)
            session = (await db.execute(stmt)).scalar_one_or_none()
            if not session:
                return None, tr("session_not_found_49c021")

            if session.status == BuilderStatus.COMPLETED and session.agent_id:
                return str(session.agent_id), None

            if session.status != BuilderStatus.PREVIEW:
                return None, tr("session_state_is_not_preview_2f4bb5", v0=f"{session.status}")

            claimed = await claim_for_confirming(db, sid, session.user_id)
            if not claimed:
                return None, tr("another_request_is_being_processed_5e0780")

            session = (await db.execute(stmt)).scalar_one_or_none()
            if not session:
                return None, tr("your_session_has_disappeared_ac033a")
            agent = await confirm_build(db, session)
            if not agent:
                return None, tr("agent_creation_failed_37b0f1")
            return str(agent.id), None
    except Exception:  # pragma: no cover
        logger.exception("Phase 8 confirm failed")
        return None, tr("agent_creation_failed_472967")


async def _persist_error(state: BuilderState, error_message: str) -> None:
    """builder_session.error_message + status=FAILED 기록 (frontend가 표시할 수 있도록)."""
    session_id_str = state.get("session_id", "")
    if not session_id_str:
        return
    try:
        sid = uuid.UUID(session_id_str)
    except ValueError:
        return
    try:
        async with async_session_factory() as db:
            stmt = select(BuilderSession).where(BuilderSession.id == sid)
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row:
                row.error_message = error_message
                row.status = BuilderStatus.FAILED
                await db.commit()
    except Exception:  # pragma: no cover
        logger.warning("Phase 8 error persist failed", exc_info=True)


# ---------------------------------------------------------------------------
# Node: phase8_propose
# ---------------------------------------------------------------------------


async def phase8_propose(state: BuilderState) -> dict:
    """draft_approval ToolMessage emit + dict 반환 (interrupt 없음)."""
    draft = state.get("draft_config") or {}
    image_url = state.get("image_url") or draft.get("image_url")

    msgs, tool_call_id = make_pending_tool_card(
        "draft_approval",
        {
            "phase": 8,
            "title": tr("final_confirmation_01f780"),
            "draft": draft,
            "image_url": image_url,
            "summary": tr("would_you_like_to_create_1a0964"),
        },
        intro_text=tr("please_check_the_settings_below_9119d0"),
    )

    return {"messages": msgs, "pending_tool_call_id": tool_call_id}


# ---------------------------------------------------------------------------
# Node: phase8_build_wait
# ---------------------------------------------------------------------------


async def phase8_build_wait(state: BuilderState) -> dict:
    """interrupt → 승인 시 Agent 생성, 수정 시 last_revision_message만 set. 라우팅은 graph."""
    response = interrupt(
        {
            "type": "approval",
            "phase": 8,
            "kind": "final",
            "draft": state.get("draft_config") or {},
        }
    )

    approved = False
    revision = ""
    if isinstance(response, dict):
        approved = bool(response.get("approved"))
        revision = response.get("revision_message") or response.get("message") or ""
    elif isinstance(response, str):
        revision = response

    pending_tc_id = state.get("pending_tool_call_id")

    if approved:
        agent_id, error = await _confirm_and_create_agent(state)
        if agent_id:
            close_msgs = close_pending_tool_card(
                pending_tc_id, "draft_approval", tr("approved_4131b9")
            )
            complete_msgs = build_phase_complete(
                8,
                ensure_todos(state),
                tr("phase_completed_agent_has_been_441141"),
            )
            return {
                "messages": [*close_msgs, *complete_msgs],
                "completed": True,
                "agent_id": agent_id,
                "pending_tool_call_id": None,
            }
        # 생성 실패 — 사용자에게 명시적으로 노출
        err_text = error or tr("agent_creation_failed_472967")
        await _persist_error(state, err_text)
        close_msgs = close_pending_tool_card(
            pending_tc_id, "draft_approval", tr("failure_v_d3b58d", v0=f"{err_text}")
        )
        return {
            "messages": [
                *close_msgs,
                AIMessage(content=(tr("agent_creation_failed_cause_v_77c822", v0=f"{err_text}"))),
            ],
            "error_message": err_text,
            "pending_tool_call_id": None,
        }

    # 수정요청
    revision_text = revision or tr("modification_request_a33895")
    close_msgs = close_pending_tool_card(
        pending_tc_id, "draft_approval", tr("edit_request_v_bc1316", v0=f"{revision_text}")
    )
    return {
        "messages": close_msgs,
        "last_revision_message": revision_text,
        "pending_tool_call_id": None,
    }
