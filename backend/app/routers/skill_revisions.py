from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.error_codes import (
    skill_file_not_found,
    skill_not_found,
    skill_revision_not_found,
    skill_revision_snapshot_unavailable,
)
from app.models.skill import Skill
from app.models.skill_revision import SkillRevision
from app.routers.skill_router_support import serialize_skill
from app.schemas.skill_revision import (
    SkillRevisionDetail,
    SkillRevisionFileContentResponse,
    SkillRevisionFileEntry,
    SkillRevisionFilesResponse,
    SkillRevisionSummary,
    SkillRollbackResponse,
)
from app.services import audit_service, skill_revision_audit, skill_revision_service
from app.skills import service as skill_service

router = APIRouter(prefix="/api/skills/{skill_id}/revisions", tags=["skill-revisions"])


@router.get("", response_model=list[SkillRevisionSummary])
async def list_skill_revisions(
    skill_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[SkillRevisionSummary]:
    # revision 列表 — 按最新顺序设置上限（与 sibling session 列表相同的 bounded contract）。
    # 每次保存/回滚都会增加 revision，因此无限返回会膨胀为数百行响应和 DOM。
    skill = await _load_skill_or_404(db, skill_id=skill_id, user=user)
    revisions = await skill_revision_service.list_revisions(
        db, skill=skill, user_id=user.id, limit=limit
    )
    return [SkillRevisionSummary.model_validate(revision) for revision in revisions]


@router.get("/{revision_id}", response_model=SkillRevisionDetail)
async def get_skill_revision(
    skill_id: uuid.UUID,
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SkillRevisionDetail:
    skill = await _load_skill_or_404(db, skill_id=skill_id, user=user)
    revision = await skill_revision_service.get_revision(
        db,
        skill=skill,
        user_id=user.id,
        revision_id=revision_id,
    )
    if revision is None:
        raise skill_revision_not_found()
    return SkillRevisionDetail.model_validate(revision)


@router.get("/{revision_id}/files", response_model=SkillRevisionFilesResponse)
async def list_skill_revision_files(
    skill_id: uuid.UUID,
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SkillRevisionFilesResponse:
    """revision snapshot zip 的文件列表（版本 diff/源代码查看，Phase 2）。

    不解压磁盘内容，只读取 zip 元数据 + head sniff。对于 pruned snapshot，
    返回显式 flag 表明无法提供文件。
    """

    revision = await _load_revision_or_404(
        db, skill_id=skill_id, revision_id=revision_id, user=user
    )
    if skill_revision_service.snapshot_pruned(revision):
        return SkillRevisionFilesResponse(snapshot_pruned=True, files=[])
    entries = await skill_revision_service.list_revision_files(revision)
    if entries is None:
        # snapshot 未标记 pruned 但 zip 丢失时，按 pruned contract 处理，不返回 500。
        return SkillRevisionFilesResponse(snapshot_pruned=True, files=[])
    return SkillRevisionFilesResponse(
        snapshot_pruned=False,
        files=[
            SkillRevisionFileEntry(path=path, size=size, is_binary=is_binary)
            for path, size, is_binary in entries
        ],
    )


@router.get("/{revision_id}/files/content", response_model=SkillRevisionFileContentResponse)
async def get_skill_revision_file_content(
    skill_id: uuid.UUID,
    revision_id: uuid.UUID,
    # 上限与列表 filter 共用同一个常量 — 如果不对称，就会出现列表中可见但
    # 内容因 422 无法打开的文件（R5/R6）。由于按精确匹配查询，从安全角度
    # 无需长度 cap，只保留 DoS 卫生上限。
    path: str = Query(
        ..., min_length=1, max_length=skill_revision_service.MAX_REVISION_FILE_PATH_CHARS
    ),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SkillRevisionFileContentResponse:
    """revision snapshot 中的单个文件文本（仅 owner）。

    请求 path 必须与 zip 枚举路径**完全一致** — traversal 会因匹配
    失败（404）结束。binary、超过 2MB、pruned 也都返回 404（fail-closed）。
    """

    revision = await _load_revision_or_404(
        db, skill_id=skill_id, revision_id=revision_id, user=user
    )
    if skill_revision_service.snapshot_pruned(revision):
        raise skill_file_not_found()
    content = await skill_revision_service.load_revision_file_content(revision, path)
    if content is None:
        raise skill_file_not_found()
    return SkillRevisionFileContentResponse(path=path, content=content)


@router.post("/{revision_id}/rollback", response_model=SkillRollbackResponse)
async def rollback_skill_revision(
    skill_id: uuid.UUID,
    revision_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> SkillRollbackResponse:
    skill = await _load_skill_or_404(db, skill_id=skill_id, user=user)
    revision = await skill_revision_service.get_revision(
        db,
        skill=skill,
        user_id=user.id,
        revision_id=revision_id,
    )
    if revision is None:
        raise skill_revision_not_found()
    try:
        restored = await skill_revision_service.rollback_to_revision(
            db,
            skill=skill,
            user_id=user.id,
            revision=revision,
            changelog_summary=f"Rolled back to revision {revision.revision_number}.",
        )
    except (
        skill_revision_service.SkillRevisionRollbackUnsupported,
        skill_revision_service.SkillRevisionSnapshotMissing,
    ) as exc:
        # pruned flag、zip 丢失/损坏都统一为与 files API 相同的“snapshot unavailable”
        # contract。仅 SnapshotMissing 由 service 在**变更前**抛出 —
        # 如果把变更后的 FileNotFoundError 也统一吞成 409，部分变更就会
        # 被隐藏在“什么都没发生”的响应之后（R5, validate-then-mutate）。
        raise skill_revision_snapshot_unavailable() from exc
    await skill_revision_audit.record_revision_create_audit(
        db,
        user=user,
        request=request,
        revision=restored,
    )
    await _record_revision_rollback_audit(
        db,
        user=user,
        request=request,
        skill_id=skill.id,
        restored_revision_id=revision.id,
        new_revision_id=restored.id,
        old_hash=revision.content_hash,
        new_hash=skill.content_hash,
    )
    await db.commit()
    await db.refresh(skill)
    await db.refresh(restored)
    return SkillRollbackResponse(
        # 使用 serializer 替代 bare model_validate — 对齐 used_by_count/health enrichment。
        skill=await serialize_skill(db, skill, user),
        revision=SkillRevisionSummary.model_validate(restored),
    )


async def _load_skill_or_404(
    db: AsyncSession,
    *,
    skill_id: uuid.UUID,
    user: CurrentUser,
) -> Skill:
    skill = await skill_service.get_skill(db, skill_id, user.id)
    if skill is None:
        raise skill_not_found()
    return skill


async def _load_revision_or_404(
    db: AsyncSession,
    *,
    skill_id: uuid.UUID,
    revision_id: uuid.UUID,
    user: CurrentUser,
) -> SkillRevision:
    skill = await _load_skill_or_404(db, skill_id=skill_id, user=user)
    revision = await skill_revision_service.get_revision(
        db,
        skill=skill,
        user_id=user.id,
        revision_id=revision_id,
    )
    if revision is None:
        raise skill_revision_not_found()
    return revision


async def _record_revision_rollback_audit(
    db: AsyncSession,
    *,
    user: CurrentUser,
    request: Request,
    skill_id: uuid.UUID,
    restored_revision_id: uuid.UUID,
    new_revision_id: uuid.UUID,
    old_hash: str | None,
    new_hash: str | None,
) -> None:
    await audit_service.record_self_event(
        db,
        user,
        action="skill_revision.rollback",
        target_type="skill",
        target_id=skill_id,
        request=request,
        metadata={
            "restored_revision_id": str(restored_revision_id),
            "new_revision_id": str(new_revision_id),
            "old_hash": old_hash,
            "new_hash": new_hash,
        },
    )
