from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import partial
from typing import Any, assert_never

from anyio.to_thread import run_sync
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.skill_builder_session import SkillBuilderSession
from app.schemas.skill_builder import SkillBuilderMode, SkillBuilderStatus, SkillDraftPackage
from app.services import skill_revision_mutations, skill_revision_service
from app.services.skill_builder_changelog import build_revision_changelog
from app.services.skill_builder_errors import (
    SkillBuilderConflictError,
    SkillBuilderSourceSkillNotFound,
    SkillBuilderValidationError,
)
from app.services.skill_builder_evaluations import (
    extract_builder_evaluation_payload,
    persist_builder_evaluation_records,
)
from app.services.skill_builder_package_storage import package_metadata, replace_skill_storage
from app.services.skill_builder_slug import unique_skill_slug
from app.services.skill_locks import lock_skill_for_mutation
from app.skills import service as skill_service
from app.skills.package_builder import build_skill_zip_bytes
from app.skills.validator import validate_draft_package


def _draft_zip_bytes(
    session: SkillBuilderSession,
    draft: SkillDraftPackage,
    *,
    slug: str,
    zip_from_workspace: bool,
) -> bytes:
    """选择用于确认的 zip 源（Phase 1.5）。

    builder chat finalize 路径（``zip_from_workspace=True``）以工作区磁盘为
    source of truth — 将 text 适配器（``draft.files``）无法承载的二进制 asset
    按原字节包含。REST ``/confirm`` 的契约是客户端发布的
    ``draft_package``，因此保留现有 text zip 路径（工作区磁盘
    可能与已发布草稿不同）。
    """

    from app.services import skill_draft_workspace as workspace

    if zip_from_workspace and session.draft_workspace_path:
        return workspace.build_workspace_zip_bytes(session.draft_workspace_path, slug=slug)
    return build_skill_zip_bytes(slug=slug, files=draft.files)


async def _merge_workspace_binary_secret_issues(
    validation_result: dict[str, Any],
    storage_path: str,
    *,
    known_paths: set[str],
) -> None:
    """将会被写入磁盘 zip、但未被 text 适配器扫描捕获的文件（如含空字节）的
    secret 检测合并到验证结果 — 现有 gate 契约（SECRET_DETECTED、
    ``secret_scan_blocked`` 审计）继续照常工作（Phase 1.5 review gap）。

    扫描涉及磁盘遍历 + IO，因此与 zip 构建对称地在线程中执行。
    ``known_paths`` 从已经在内存中的 ``draft.files`` 派生 — 不重复
    full-read 工作区（R2 review）。
    """

    from app.services import skill_draft_workspace as workspace

    extra = await run_sync(
        partial(workspace.binary_secret_scan_issues, storage_path, known_paths=known_paths)
    )
    if not extra:
        return
    validation_result["issues"] = [*(validation_result.get("issues") or []), *extra]
    validation_result["error_count"] = int(validation_result.get("error_count") or 0) + len(extra)
    validation_result["valid"] = False


async def confirm_builder_session(
    db: AsyncSession,
    session: SkillBuilderSession,
    *,
    user_id: uuid.UUID,
    zip_from_workspace: bool = False,
) -> Skill:
    draft = _parse_draft(session.draft_package)
    validation_result = validate_draft_package(
        files=draft.files,
        credential_requirements=draft.credential_requirements,
        execution_profile=draft.execution_profile,
    )
    if zip_from_workspace and session.draft_workspace_path:
        # 磁盘 zip 路径还会包含适配器外文件，因此扫描覆盖范围要与 zip 源
        # 对齐 — 堵住通过空字节文件绕过 secret scan 的缺口。
        await _merge_workspace_binary_secret_issues(
            validation_result,
            session.draft_workspace_path,
            known_paths={f.path for f in draft.files},
        )
    if validation_result["error_count"] > 0:
        session.validation_result = validation_result
        session.status = SkillBuilderStatus.REVIEW.value
        await db.flush()
        raise SkillBuilderValidationError(validation_result)

    session.validation_result = validation_result
    session.compatibility_result = validation_result.get("compatibility_result")
    try:
        evaluation_payload = extract_builder_evaluation_payload(draft, session.eval_result)
    except SkillBuilderValidationError as exc:
        session.validation_result = exc.result
        session.status = SkillBuilderStatus.REVIEW.value
        await db.flush()
        raise

    mode = SkillBuilderMode(session.mode)
    match mode:
        case SkillBuilderMode.CREATE:
            skill = await _confirm_create(
                db,
                session=session,
                draft=draft,
                user_id=user_id,
                zip_from_workspace=zip_from_workspace,
            )
        case SkillBuilderMode.IMPROVE:
            skill = await _confirm_improve(
                db,
                session=session,
                draft=draft,
                user_id=user_id,
                zip_from_workspace=zip_from_workspace,
            )
        case unreachable:
            assert_never(unreachable)

    await persist_builder_evaluation_records(
        db,
        user_id=user_id,
        skill=skill,
        payload=evaluation_payload,
    )
    session.status = SkillBuilderStatus.COMPLETED.value
    session.finalized_skill_id = skill.id
    session.updated_at = skill.last_modified_at
    await db.flush()
    return skill


async def _confirm_create(
    db: AsyncSession,
    *,
    session: SkillBuilderSession,
    draft: SkillDraftPackage,
    user_id: uuid.UUID,
    zip_from_workspace: bool,
) -> Skill:
    changelog = build_revision_changelog(
        mode=SkillBuilderMode.CREATE,
        base_snapshot=session.base_snapshot,
        draft=draft,
        provided=session.changelog_draft,
    )
    slug = await unique_skill_slug(db, user_id=user_id, requested=draft.slug)
    # zip 构建涉及磁盘遍历 + 压缩，因此不在事件循环中运行
    # （与 improve 的 replace_skill_storage offload 对称）。
    zip_bytes = await run_sync(
        partial(_draft_zip_bytes, session, draft, slug=slug, zip_from_workspace=zip_from_workspace)
    )
    skill = await skill_service.create_package_skill(
        db,
        user_id=user_id,
        zip_bytes=zip_bytes,
        name_override=draft.name,
        slug_override=slug,
    )
    skill.credential_requirements = list(draft.credential_requirements) or None
    skill.execution_profile = dict(draft.execution_profile) or None
    skill.source_kind = "user"
    skill.origin_kind = "created_by_me"
    await skill_revision_service.create_revision_for_skill(
        db,
        skill=skill,
        user_id=user_id,
        operation="builder_create",
        source_session_id=session.id,
        compatibility_result=session.compatibility_result,
        changelog_summary=changelog.summary,
        changelog_items=changelog.items,
    )
    return skill


async def _confirm_improve(
    db: AsyncSession,
    *,
    session: SkillBuilderSession,
    draft: SkillDraftPackage,
    user_id: uuid.UUID,
    zip_from_workspace: bool,
) -> Skill:
    skill = await _load_source_skill(db, session=session, user_id=user_id)
    skill = await lock_skill_for_mutation(db, skill=skill)
    if skill.content_hash != session.base_content_hash:
        session.status = SkillBuilderStatus.REVIEW.value
        session.error_message = "SOURCE_SKILL_CHANGED"
        await db.flush()
        raise SkillBuilderConflictError(
            base_content_hash=session.base_content_hash,
            current_content_hash=skill.content_hash,
        )

    revision_parent = await skill_revision_mutations.prepare_mutation_parent(
        db,
        skill=skill,
        user_id=user_id,
    )
    changelog = build_revision_changelog(
        mode=SkillBuilderMode.IMPROVE,
        base_snapshot=session.base_snapshot,
        draft=draft,
        provided=session.changelog_draft,
    )
    slug = await unique_skill_slug(
        db,
        user_id=user_id,
        requested=draft.slug,
        exclude_skill_id=skill.id,
    )
    zip_bytes = await run_sync(
        partial(_draft_zip_bytes, session, draft, slug=slug, zip_from_workspace=zip_from_workspace)
    )
    replacement = await run_sync(
        partial(
            replace_skill_storage,
            skill_id=skill.id,
            current_kind=skill.kind,
            current_storage_path=skill.storage_path,
            zip_bytes=zip_bytes,
        )
    )
    skill.name = draft.name
    skill.slug = slug
    skill.description = replacement.info.description or draft.description
    skill.kind = "package"
    skill.storage_path = replacement.storage_path
    skill.content_hash = replacement.content_hash
    skill.size_bytes = replacement.info.total_bytes
    skill.version = replacement.info.version
    skill.package_metadata = package_metadata(replacement.info, skill.name)
    skill.credential_requirements = list(draft.credential_requirements) or None
    skill.execution_profile = dict(draft.execution_profile) or None
    skill.is_dirty = True
    skill.last_modified_at = _now()
    await db.flush()
    await skill_revision_service.create_revision_for_skill(
        db,
        skill=skill,
        user_id=user_id,
        operation="builder_improvement",
        source_session_id=session.id,
        parent_revision_id=revision_parent.parent_revision_id,
        compatibility_result=session.compatibility_result,
        changelog_summary=changelog.summary,
        changelog_items=changelog.items,
    )
    return skill


async def _load_source_skill(
    db: AsyncSession,
    *,
    session: SkillBuilderSession,
    user_id: uuid.UUID,
) -> Skill:
    if session.source_skill_id is None:
        raise SkillBuilderSourceSkillNotFound("source skill is required")
    skill = await skill_service.get_skill(db, session.source_skill_id, user_id)
    if skill is None:
        raise SkillBuilderSourceSkillNotFound("source skill not found")
    return skill


def _parse_draft(raw: dict[str, Any] | None) -> SkillDraftPackage:
    if raw is None:
        raise SkillBuilderValidationError(
            _draft_error_result("DRAFT_PACKAGE_MISSING", "Draft package is required.")
        )
    try:
        return SkillDraftPackage.model_validate(raw)
    except ValidationError as exc:
        raise SkillBuilderValidationError(
            _draft_error_result("DRAFT_PACKAGE_INVALID", str(exc))
        ) from exc


def _draft_error_result(code: str, message: str) -> dict[str, Any]:
    return {
        "valid": False,
        "error_count": 1,
        "warning_count": 0,
        "info_count": 0,
        "issues": [{"code": code, "severity": "error", "path": None, "message": message}],
    }


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
