"""builder chat finalize 编排（M5，规范 AD-3）。

``finalize_skill`` 工具在批准后调用。最大程度复用 v1 confirm 流程：
工作区 → ``SkillDraftPackage`` → ``save_draft_package``(REVIEW) →
``claim_for_confirming`` → ``confirm_builder_session``（重新验证 + secret
scan + 创建/改进 + revision + 收集 eval）。审计词汇也沿用 v1
（``skill_builder.confirm_create``/``apply_improvement``/``apply_conflict``/
``secret_scan_blocked`` + ``skill_revision.create``）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import CurrentUser
from app.models.skill_builder_session import SkillBuilderSession
from app.models.user import User
from app.routers.skill_builder_audit import (
    confirm_audit_metadata,
    secret_scan_audit_metadata,
)
from app.schemas.skill_builder import SkillBuilderMode, SkillBuilderStatus
from app.services import audit_service, skill_builder_service
from app.services import skill_draft_workspace as workspace
from app.services.skill_builder_errors import (
    SkillBuilderConflictError,
    SkillBuilderSourceSkillNotFound,
    SkillBuilderValidationError,
)
from app.services.skill_revision_audit import record_revision_create_audit
from app.skills.packager import PackageError

logger = logging.getLogger(__name__)

# Phase 2 Studio 路由 — legacy `?detailId=` 会由前端服务器 redirect 吸收，
# 但新 payload 直接指向正式路由。
SKILL_DETAIL_DEEPLINK = "/skills/{skill_id}/source"


async def finalize_draft_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """执行完整 finalize 流程 — 返回作为工具结果使用的 dict（包含 commit）。

    成功：``{skill_id, slug, name, content_hash, deeplink, validation_result}``。
    失败：``{error_code, message, ...}`` — Agent 向用户说明。
    """

    session = await skill_builder_service.get_session(db, session_id, user_id)
    if session is None:
        return _error("SESSION_NOT_FOUND", "builder session not found")

    # 幂等：若会话已确认，则原样返回现有 skill 信息。
    if (
        session.status == SkillBuilderStatus.COMPLETED.value
        and session.finalized_skill_id is not None
    ):
        from app.skills import service as skill_service

        existing = await skill_service.get_skill(db, session.finalized_skill_id, user_id)
        if existing is not None:
            return _success(session, existing)

    if not session.draft_workspace_path:
        return _error("DRAFT_WORKSPACE_MISSING", "draft workspace is not attached")

    # 与 REST /confirm 相同的状态 gate（R2）— save_draft_package 会
    # 无条件重置状态为 REVIEW，因此若没有 gate，并发 finalize B 的 save 会把 A 的
    # CONFIRMING claim 回退，导致可以重复 confirm（run mutex 可
    # 缓解，但工具路径本身也必须关闭）。
    if session.status == SkillBuilderStatus.CONFIRMING.value:
        return _error("SESSION_CONFIRMING", "another finalize is already in progress")

    # 二进制 asset 由 confirm 阶段基于磁盘的 zip（build_workspace_zip_bytes）
    # 原样承载（Phase 1.5）— draft_package（text 适配器）仅用于验证/元数据。
    draft = workspace.build_draft_package(session.draft_workspace_path)
    await skill_builder_service.save_draft_package(db, session, draft=draft.model_dump(mode="json"))
    await db.commit()

    claimed = await skill_builder_service.claim_for_confirming(db, session.id, user_id)
    if not claimed:
        return _error("SESSION_CONFIRMING", "another finalize is already in progress")

    session = await skill_builder_service.get_session(db, session_id, user_id)
    if session is None:
        return _error("SESSION_NOT_FOUND", "builder session not found")

    actor = await _actor_for(db, user_id)
    try:
        # zip_from_workspace=True — builder chat 路径以工作区磁盘为 source of
        # truth，因此生成包含二进制 asset 的 zip（Phase 1.5）。REST /confirm
        # 保持已发布 draft_package 契约，因此不开启此 flag。
        skill = await skill_builder_service.confirm_session(
            db, session, user_id=user_id, zip_from_workspace=True
        )
    except SkillBuilderConflictError as exc:
        await _record_audit(
            db,
            actor=actor,
            action="skill_builder.apply_conflict",
            session=session,
            outcome="denied",
            metadata={
                "old_hash": exc.base_content_hash,
                "new_hash": exc.current_content_hash,
            },
        )
        await db.commit()
        return _error(
            "SOURCE_SKILL_CHANGED",
            "the source skill changed while this session was open; "
            "start a new improve session from the latest version",
        )
    except SkillBuilderValidationError as exc:
        if secret_scan_audit_metadata(exc.result) is not None:
            await _record_audit(
                db,
                actor=actor,
                action="skill_builder.secret_scan_blocked",
                session=session,
                outcome="denied",
                metadata=dict(secret_scan_audit_metadata(exc.result) or {}),
            )
        await db.commit()
        return {
            "error_code": "VALIDATION_FAILED",
            "message": "draft validation failed; fix the reported issues and retry",
            "session_id": str(session.id),
            "validation_result": exc.result,
        }
    except SkillBuilderSourceSkillNotFound:
        # claim 独立 commit CONFIRMING 后的失败 — 必须与 conflict/validation 路径
        # 对称地恢复为 REVIEW，重试才能 self-heal（仅 rollback 无法撤销已经
        # commit 的 CONFIRMING，否则 CONFIRMING gate 会永久阻止重试）。
        await db.rollback()
        await _release_confirming_claim(db, session_id, user_id)
        return _error("SOURCE_SKILL_NOT_FOUND", "source skill not found")
    except PackageError as exc:
        # zip 提取 guard（大小/文件数/路径防护）失败 — 由于加入了二进制 asset，
        # 包大小超限已成为现实（Phase 1.5）。与上述路径对称地释放 claim，
        # 将原因原样传递，使 Agent 可缩减文件后重试。
        await db.rollback()
        await _release_confirming_claim(db, session_id, user_id)
        return _error("PACKAGE_INVALID", str(exc))
    except asyncio.CancelledError:
        # run 取消（stop）属于 BaseException，因此会穿过下方 Exception catch 与工具路径的
        # 广域 catch — 但必须通过 shield 完成 claim 释放，并
        # 重新传播，以防 CONFIRMING 锁残留（使用独立会话，因此与请求会话
        # teardown 无关，会一直 commit 到完成）。
        with contextlib.suppress(Exception):
            await asyncio.shield(_release_confirming_claim(db, session_id, user_id))
        raise
    except Exception:
        # 意外失败（transient DB 错误等）也要释放 claim，避免会话
        # 卡在虚假的"另一个 finalize 正在进行"状态。
        await db.rollback()
        await _release_confirming_claim(db, session_id, user_id)
        raise

    await _record_audit(
        db,
        actor=actor,
        action=(
            "skill_builder.apply_improvement"
            if session.mode == SkillBuilderMode.IMPROVE.value
            else "skill_builder.confirm_create"
        ),
        session=session,
        outcome="success",
        metadata=dict(confirm_audit_metadata(session, skill)),
    )
    if skill.current_revision_id is not None:
        from app.models.skill_revision import SkillRevision

        revision = await db.get(SkillRevision, skill.current_revision_id)
        if revision is not None:
            await record_revision_create_audit(
                db,
                user=actor,
                request=None,  # type: ignore[arg-type] — 工具路径：没有 HTTP request
                revision=revision,
            )
    await db.commit()
    await db.refresh(skill)
    return _success(session, skill)


def _success(session: SkillBuilderSession, skill: Any) -> dict[str, Any]:
    return {
        "session_id": str(session.id),
        "skill_id": str(skill.id),
        "slug": skill.slug,
        "name": skill.name,
        "content_hash": skill.content_hash,
        "version": skill.version,
        "mode": session.mode,
        # 完成卡片 deeplink（规范 5.1 — 在 Phase 2 升级为 Studio 路由）。
        "deeplink": SKILL_DETAIL_DEEPLINK.format(skill_id=skill.id),
        "validation_result": session.validation_result,
    }


async def _release_confirming_claim(
    _db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """post-claim 失败时 CONFIRMING → REVIEW 恢复（best-effort self-heal）。

    打开独立会话 — 即使取消（shield）路径中请求会话已 teardown，也能完成恢复
    commit；且条件 UPDATE（与 claim 对称）是原子的。调用方会话保持
    rollback 状态。
    """

    try:
        async with async_session() as fresh:
            await fresh.execute(
                update(SkillBuilderSession)
                .where(
                    SkillBuilderSession.id == session_id,
                    SkillBuilderSession.user_id == user_id,
                    SkillBuilderSession.status == SkillBuilderStatus.CONFIRMING.value,
                )
                .values(status=SkillBuilderStatus.REVIEW.value)
            )
            await fresh.commit()
    except Exception:
        logger.exception("failed to release confirming claim session=%s", session_id)


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error_code": code, "message": message}


async def _actor_for(db: AsyncSession, user_id: uuid.UUID) -> CurrentUser:
    user = await db.get(User, user_id)
    email = user.email if user is not None else ""
    name = user.name if user is not None else ""
    return CurrentUser(id=user_id, email=email, name=name)


async def _record_audit(
    db: AsyncSession,
    *,
    actor: CurrentUser,
    action: str,
    session: SkillBuilderSession,
    outcome: str,
    metadata: dict[str, Any],
) -> None:
    await audit_service.record_self_event(
        db,
        actor,
        action=action,
        target_type="skill_builder_session",
        target_id=session.id,
        outcome=outcome,
        metadata={
            "session_id": str(session.id),
            "mode": session.mode,
            "source_skill_id": (str(session.source_skill_id) if session.source_skill_id else None),
            **metadata,
        },
    )
