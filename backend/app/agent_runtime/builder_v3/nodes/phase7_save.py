"""Phase 7 — 保存智能体设置（自动，无需 LLM）。

组装 draft_config → 保存到 DB(builder_session) → status=PREVIEW。
emit DraftConfigCard ToolMessage + 自动进入 Phase 8。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_phase_complete,
    ensure_todos,
    make_tool_card,
)
from app.agent_runtime.builder_v3.state import BuilderState
from app.database import async_session as async_session_factory
from app.models.builder_session import BuilderSession
from app.schemas.builder import (
    AgentCreationIntent,
    BuilderStatus,
    DraftAgentConfig,
    MiddlewareRecommendation,
    ToolRecommendation,
)

logger = logging.getLogger(__name__)


def _build_draft(state: BuilderState) -> DraftAgentConfig:
    intent_dict = state.get("intent") or {}
    intent = AgentCreationIntent(**intent_dict)
    tools = [ToolRecommendation(**t) for t in state.get("tools") or []]
    mws = [MiddlewareRecommendation(**m) for m in state.get("middlewares") or []]
    planned_tools = [item.model_dump(mode="json") for item in tools if item.kind == "planned"]
    return DraftAgentConfig(
        name=intent.agent_name,
        description=intent.agent_description,
        system_prompt=state.get("system_prompt") or "",
        consistency_review=state.get("consistency_review"),
        consistency_reviews=state.get("consistency_reviews") or [],
        tools=[t.tool_name for t in tools if t.kind not in {"planned", "generated_skill"}],
        planned_tools=planned_tools,
        generated_skills=[t.model_dump(mode="json") for t in tools if t.kind == "generated_skill"],
        capability_reason=state.get("capability_reason"),
        middlewares=[m.middleware_name for m in mws],
        model_name=state.get("default_model_name", ""),
        primary_task_type=intent.primary_task_type,
        use_cases=list(intent.use_cases),
        identity_mode=intent.identity_mode,
    )


async def _persist_session(
    session_id: str,
    draft: DraftAgentConfig,
    image_url: str | None,
    current_phase: int,
    tools: list[dict[str, Any]],
    middlewares: list[dict[str, Any]],
    intent: dict[str, Any] | None = None,
) -> None:
    """将 phase 结果保存到 builder_session，并切换为 status=PREVIEW。"""
    if not session_id:
        raise ValueError("builder_session_missing")
    try:
        sid = uuid.UUID(session_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("builder_session_invalid") from exc

    try:
        async with async_session_factory() as db:
            stmt = select(BuilderSession).where(BuilderSession.id == sid)
            row = (await db.execute(stmt)).scalar_one_or_none()
            if not row:
                raise ValueError("builder_session_missing")
            payload: dict[str, Any] = draft.model_dump(mode="json")
            # 始终显式 set image_url — None 表示用户在 phase6 中 skip。
            payload["image_url"] = image_url
            row.intent = intent
            row.draft_config = payload
            row.system_prompt = draft.system_prompt
            # 保存 ToolRecommendation/MiddlewareRecommendation 完整对象
            # （BuilderSessionResponse 模式要求 description/reason 必填）
            row.tools_result = list(tools)
            row.middlewares_result = list(middlewares)
            row.current_phase = current_phase
            row.status = BuilderStatus.PREVIEW
            await db.commit()
    except Exception:  # pragma: no cover
        logger.warning("Phase 7 persist failed", exc_info=True)
        raise


async def phase7_save(state: BuilderState) -> dict:
    try:
        draft = _build_draft(state)
        draft_dict: dict[str, Any] = draft.model_dump(mode="json")
        # 始终显式 set image_url — None 表示用户在 phase6 中 skip。
        draft_dict["image_url"] = state.get("image_url")

        await _persist_session(
            state.get("session_id", ""),
            draft,
            state.get("image_url"),
            7,
            list(state.get("tools") or []),
            list(state.get("middlewares") or []),
            state.get("intent"),
        )
    except Exception:
        logger.exception("Builder draft persistence failed")
        return {"current_phase": 7, "error_message": tr("generation_failed_retry")}

    msgs, _ = make_tool_card(
        "draft_config_card",
        {
            "phase": 7,
            "title": tr("preview_agent_settings_5d80e9"),
            "draft": draft_dict,
            "image_url": state.get("image_url"),
        },
        intro_text=tr("we_ve_put_all_the_dee8a9"),
    )

    complete_msgs = build_phase_complete(
        7,
        ensure_todos(state),
        tr("phase_completed_settings_saved_completed_614679"),
    )

    return {
        "messages": list(msgs) + list(complete_msgs),
        "draft_config": draft_dict,
        "current_phase": 8,
    }
