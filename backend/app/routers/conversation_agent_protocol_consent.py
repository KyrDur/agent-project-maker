"""处理 HITL 会话同意（Skill Builder 聊天，规范 AD-4）。

在这里消费前端随 ``input.respond`` decision 发送的扩展字段 ``scope:"session"``
("留出本次会议的剩余时间")：

1. 将同意记录到会话 row（``skill_builder_sessions.tool_consents``）中，
2. 从 decision 中**删除** ``scope`` 键，只向中间件传递标准的
   approve/reject/edit — 非标准 decision 字段会破坏 langchain
   ``HumanInTheLoopMiddleware`` 校验。

边界（AD-4）：同意对象仅限 ``SESSION_CONSENT_ELIGIBLE_TOOLS``
（``finalize_skill`` 始终显示卡片）；如果草稿 ``requires_network``，则不记录同意
— 本次批准仅单次有效。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.skill_builder.tools import SESSION_CONSENT_ELIGIBLE_TOOLS
from app.models.skill_builder_session import SkillBuilderSession
from app.routers.conversation_agent_protocol_interrupts import ThreadInterrupt
from app.routers.conversation_agent_protocol_resume import ResumePayload
from app.routers.conversation_agent_protocol_resume_redaction import _action_requests
from app.services import skill_builder_service, skill_draft_workspace

logger = logging.getLogger(__name__)


async def apply_session_consent_decisions(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    resume: ResumePayload,
    pending_interrupts: list[ThreadInterrupt],
) -> list[str]:
    """记录 ``scope:"session"`` 同意，并从 decision 中剥离 scope 键。

    **in-place** 修改 decision dict（``resume.input_payload`` 与
    ``resume.submitted`` 引用同一个 dict）。返回已记录的工具名列表
    （若不满足同意条件则返回空列表 — 本次批准仍作为标准 approve 单次执行）。
    """

    actions_by_interrupt = {
        interrupt["id"]: _action_requests(interrupt.get("value"))
        for interrupt in pending_interrupts
    }
    requested: list[str] = []
    for submitted in resume.submitted:
        response = submitted.response
        if not isinstance(response, Mapping):
            continue
        decisions = response.get("decisions")
        if not isinstance(decisions, list):
            continue
        actions = actions_by_interrupt.get(submitted.interrupt_id, [])
        for index, decision in enumerate(decisions):
            if not isinstance(decision, dict) or "scope" not in decision:
                continue
            # 无论是否为目标对象，都始终删除非标准键。
            scope = decision.pop("scope")
            if scope != "session" or decision.get("type") != "approve":
                continue
            action = actions[index] if index < len(actions) else None
            name = action.get("name") if isinstance(action, Mapping) else None
            if isinstance(name, str) and name in SESSION_CONSENT_ELIGIBLE_TOOLS:
                requested.append(name)

    if not requested:
        return []

    result = await db.execute(
        select(SkillBuilderSession)
        .where(
            SkillBuilderSession.conversation_id == conversation_id,
            SkillBuilderSession.user_id == user_id,
        )
        # 会话↔对话 1:1 并非 DB 约束，而是约定 — 为防御起见只取最新 1 条
        # 以避免 MultipleResultsFound 500（R2）。
        .order_by(SkillBuilderSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        # 如果不是 Builder 对话，同意没有意义 — 只删除 scope 即可。
        return []
    if session.draft_workspace_path and skill_draft_workspace.draft_requires_network(
        session.draft_workspace_path
    ):
        logger.info("session consent skipped — draft requires network (session=%s)", session.id)
        return []

    tool_names = sorted(set(requested))
    await skill_builder_service.record_tool_consents(db, session, tool_names=tool_names)
    return tool_names


__all__ = ["apply_session_consent_decisions"]
