from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import desc, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.skill import Skill
from app.models.skill_builder_session import SkillBuilderSession
from app.schemas.skill_builder import SkillBuilderMode, SkillBuilderStatus
from app.services.skill_builder_confirmation import confirm_builder_session
from app.services.skill_builder_errors import (
    SkillBuilderConflictError,
    SkillBuilderSourceSkillNotFound,
    SkillBuilderValidationError,
)
from app.skills import service as skill_service
from app.storage.paths import ensure_relative


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_request: str,
    mode: SkillBuilderMode = SkillBuilderMode.CREATE,
    source_skill_id: uuid.UUID | None = None,
) -> SkillBuilderSession:
    base_snapshot: dict[str, Any] | None = None
    base_skill_version: str | None = None
    base_content_hash: str | None = None
    if mode is SkillBuilderMode.IMPROVE:
        if source_skill_id is None:
            raise SkillBuilderSourceSkillNotFound("source skill is required")
        source_skill = await _get_owned_skill(db, source_skill_id, user_id)
        if source_skill is None:
            raise SkillBuilderSourceSkillNotFound("source skill not found")
        base_snapshot = await load_skill_snapshot(source_skill)
        base_skill_version = source_skill.version
        base_content_hash = source_skill.content_hash

    session = SkillBuilderSession(
        user_id=user_id,
        user_request=user_request,
        mode=mode.value,
        source_skill_id=source_skill_id if mode is SkillBuilderMode.IMPROVE else None,
        base_skill_version=base_skill_version,
        base_content_hash=base_content_hash,
        base_snapshot=base_snapshot,
        status=SkillBuilderStatus.COLLECTING.value,
    )
    db.add(session)
    await db.flush()
    return session


async def attach_chat_runtime(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    conversation_id: uuid.UUID,
    draft_workspace_path: str,
) -> SkillBuilderSession:
    """v2 启动流程 — 连接 builder 对话/工作区，并将状态提升为 ACTIVE。"""

    session.conversation_id = conversation_id
    session.draft_workspace_path = ensure_relative(draft_workspace_path)
    session.status = SkillBuilderStatus.ACTIVE.value
    session.updated_at = _now()
    await db.flush()
    return session


async def record_tool_consents(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    tool_names: list[str],
) -> SkillBuilderSession:
    """AD-4 scoped consent 记录 — 工具名 → 同意元数据（会话级）。"""

    consents = dict(session.tool_consents or {})
    granted_at = datetime.now(UTC).isoformat()
    for name in tool_names:
        consents[name] = {"scope": "session", "granted_at": granted_at}
    session.tool_consents = consents
    session.updated_at = _now()
    await db.flush()
    return session


async def resolve_session_agent_id(
    db: AsyncSession,
    session: SkillBuilderSession,
) -> uuid.UUID | None:
    """builder 对话的隐藏 Agent id（对话未连接/已删除时为 None）。"""

    if session.conversation_id is None:
        return None
    result = await db.execute(
        select(Conversation.agent_id).where(Conversation.id == session.conversation_id)
    )
    return result.scalar_one_or_none()


async def get_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SkillBuilderSession | None:
    result = await db.execute(
        select(SkillBuilderSession).where(
            SkillBuilderSession.id == session_id,
            SkillBuilderSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    skill_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[SkillBuilderSession]:
    """用户的 builder 会话列表（Studio builder tab/index，Phase 2）。

    ``skill_id`` 同时匹配 improve 源（``source_skill_id``）与 create 产物
    （``finalized_skill_id``）— 为了用一次查询获取"该 skill 的 builder 历史"
    （两侧都有索引）。若没有状态过滤器，默认排除 GC 对象
    ``abandoned`` — 对话通过 SET NULL 断开后无法恢复，不应把这类
    会话显示为可点击行（显式指定 status 时仍可查询）。
    """

    stmt = (
        select(SkillBuilderSession)
        .where(SkillBuilderSession.user_id == user_id)
        # updated_at 在事务/秒粒度可能相同，因此用 id 辅助排序截断
        # 防止边界行 flap（R5）。
        .order_by(desc(SkillBuilderSession.updated_at), desc(SkillBuilderSession.id))
        .limit(limit)
    )
    if skill_id is not None:
        stmt = stmt.where(
            or_(
                SkillBuilderSession.source_skill_id == skill_id,
                SkillBuilderSession.finalized_skill_id == skill_id,
            )
        )
    if status is not None:
        stmt = stmt.where(SkillBuilderSession.status == status)
    else:
        stmt = stmt.where(SkillBuilderSession.status != SkillBuilderStatus.ABANDONED.value)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def append_message(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    role: str,
    content: str,
) -> SkillBuilderSession:
    messages = list(session.messages or [])
    messages.append(
        {
            "role": role,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    session.messages = messages
    session.updated_at = _now()
    await db.flush()
    return session


async def save_draft_package(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    draft: dict[str, Any],
) -> SkillBuilderSession:
    session.draft_package = draft
    session.status = SkillBuilderStatus.REVIEW.value
    session.updated_at = _now()
    await db.flush()
    return session


async def save_validation_result(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    result: dict[str, Any],
) -> SkillBuilderSession:
    session.validation_result = result
    compatibility_result = result.get("compatibility_result")
    if isinstance(compatibility_result, dict):
        session.compatibility_result = compatibility_result
    session.updated_at = _now()
    await db.flush()
    return session


async def save_trigger_eval_result(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    result: Mapping[str, Any],
    draft: Mapping[str, Any],
) -> SkillBuilderSession:
    session.trigger_eval_result = dict(result)
    session.draft_package = dict(draft)
    session.updated_at = _now()
    await db.flush()
    return session


async def claim_for_confirming(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    result = cast(
        CursorResult[Any],
        await db.execute(
            update(SkillBuilderSession)
            .where(
                SkillBuilderSession.id == session_id,
                SkillBuilderSession.user_id == user_id,
                SkillBuilderSession.status == SkillBuilderStatus.REVIEW.value,
            )
            .values(status=SkillBuilderStatus.CONFIRMING.value, updated_at=_now())
        ),
    )
    await db.commit()
    return result.rowcount == 1


async def confirm_session(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    user_id: uuid.UUID,
    zip_from_workspace: bool = False,
) -> Skill:
    return await confirm_builder_session(
        db, session, user_id=user_id, zip_from_workspace=zip_from_workspace
    )


async def load_skill_snapshot(skill: Skill) -> dict[str, Any]:
    files: list[dict[str, Any]]
    if skill.kind == "text":
        content = await skill_service.read_text_content(skill)
        files = [{"path": "SKILL.md", "content": content, "role": "skill"}]
    else:
        files = []
        for file_info in skill_service.get_skill_files(skill):
            if file_info.is_dir:
                continue
            raw = skill_service.get_file_bytes(skill, file_info.path)
            files.append(
                {
                    "path": file_info.path,
                    "content": raw.decode("utf-8", errors="replace"),
                    "role": _role_for_path(file_info.path),
                }
            )
    return {
        "skill_id": str(skill.id),
        "kind": skill.kind,
        "name": skill.name,
        "slug": skill.slug,
        "description": skill.description,
        "version": skill.version,
        "content_hash": skill.content_hash,
        "credential_requirements": skill.credential_requirements or [],
        "execution_profile": skill.execution_profile or {},
        "files": files,
    }


async def _get_owned_skill(
    db: AsyncSession,
    skill_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Skill | None:
    result = await db.execute(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _role_for_path(path: str) -> str:
    # 正本是 skill_draft_workspace.role_for_path — 草稿适配器与 snapshot
    # loader 委托它使用同一套 role 规则（延迟 import：避免模块加载循环）。
    from app.services.skill_draft_workspace import role_for_path

    return role_for_path(path)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


__all__ = [
    "SkillBuilderConflictError",
    "SkillBuilderSourceSkillNotFound",
    "SkillBuilderValidationError",
    "append_message",
    "claim_for_confirming",
    "confirm_session",
    "create_session",
    "get_session",
    "list_sessions",
    "load_skill_snapshot",
    "save_draft_package",
    "save_trigger_eval_result",
    "save_validation_result",
]
