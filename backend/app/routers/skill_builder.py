from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.error_codes import (
    invalid_skill_package,
    session_confirming,
    skill_builder_session_not_ready,
    skill_builder_source_conflict,
    skill_file_not_found,
    skill_not_found,
    system_llm_not_configured,
)
from app.routers.skill_builder_audit import (
    confirm_audit_metadata,
    record_current_revision_create_audit,
)
from app.routers.skill_builder_support import (
    completed_skill,
    get_session_or_404,
    record_builder_audit,
    record_secret_scan_blocked_if_needed,
    require_system_llm,
)
from app.routers.skill_router_support import serialize_skill
from app.schemas.skill import SkillResponse
from app.schemas.skill_builder import (
    SkillBuilderFileContentResponse,
    SkillBuilderFileEntry,
    SkillBuilderFilesResponse,
    SkillBuilderMode,
    SkillBuilderSessionBrief,
    SkillBuilderSessionResponse,
    SkillBuilderStartRequest,
    SkillBuilderStatus,
    SkillDraftPackage,
)
from app.services import (
    chat_service,
    skill_builder_service,
    skill_draft_workspace,
)
from app.services.skill_builder_errors import (
    SkillBuilderConflictError,
    SkillBuilderSourceSkillNotFound,
    SkillBuilderValidationError,
)
from app.services.skill_builder_hidden_agent import get_or_create_skill_builder_agent
from app.services.system_credential_resolver import SystemModelNotConfiguredError
from app.skills import service as skill_service
from app.skills.validator import validate_draft_package

router = APIRouter(prefix="/api/skill-builder", tags=["skill-builder"])


def _session_response(
    session: object, *, agent_id: uuid.UUID | None
) -> SkillBuilderSessionResponse:
    response = SkillBuilderSessionResponse.model_validate(session)
    if agent_id is not None:
        # ``agent_id`` 不是 ORM 属性，而是从对话反向引用派生的值 — 校验后注入。
        response = response.model_copy(update={"agent_id": agent_id})
    return response


@router.post("", response_model=SkillBuilderSessionResponse, status_code=201)
async def start_skill_builder(
    data: SkillBuilderStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> SkillBuilderSessionResponse:
    """启动 Builder 聊天会话（v2，规范 AD-6）。

    hidden Builder Agent lazy-seed → session row → 草稿工作区 →
    创建 draft conversation，并返回 ``{session, agent_id, conversation_id}``。
    前端使用该值进入 ``/skills/builder/[sessionId]``。
    """

    await require_system_llm(db, user=user, request=request)
    try:
        session = await skill_builder_service.create_session(
            db,
            user_id=user.id,
            user_request=data.user_request,
            mode=data.mode,
            source_skill_id=data.source_skill_id,
        )
    except SkillBuilderSourceSkillNotFound as exc:
        raise skill_not_found() from exc
    try:
        agent = await get_or_create_skill_builder_agent(db, user.id)
    except SystemModelNotConfiguredError as exc:
        # 当模型 catalog 为空、无法填充 seed 所需 FK 时 — 与 gate 使用相同 contract。
        raise system_llm_not_configured() from exc
    # source="draft" — 复用现有 draft contract，发送第一条消息时 promote。
    # navigator 暴露仍由 runtime_profile filter 在 promote 后继续阻止。
    conversation = await chat_service.create_conversation(db, agent.id, source="draft")
    workspace_path = skill_draft_workspace.create_workspace(session.id)
    if session.source_skill_id is not None:
        # improve 模式 — 将原始 Skill 文件复制（seed）到工作区。
        # 所有权已由 create_session 校验。
        source_skill = await skill_service.get_skill(db, session.source_skill_id, user.id)
        if source_skill is not None:
            workspace_path = skill_draft_workspace.seed_workspace_from_skill(
                source_skill, session.id
            )
    await skill_builder_service.attach_chat_runtime(
        db,
        session,
        conversation_id=conversation.id,
        draft_workspace_path=workspace_path,
    )
    await record_builder_audit(
        db,
        user=user,
        request=request,
        action="skill_builder.session_create",
        session_id=session.id,
        mode=data.mode.value,
        source_skill_id=data.source_skill_id,
        conversation_id=str(conversation.id),
        agent_id=str(agent.id),
    )
    await db.commit()
    await db.refresh(session)
    return _session_response(session, agent_id=agent.id)


@router.get("", response_model=list[SkillBuilderSessionBrief])
async def list_skill_builder_sessions(
    skill_id: uuid.UUID | None = Query(None),
    status: SkillBuilderStatus | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[SkillBuilderSessionBrief]:
    """用户的 Builder 会话列表（Studio Builder tab/index，Phase 2）。

    ``skill_id`` 同时匹配 improve 原始项和 create 产物（finalized）—
    可一次性查询“该 Skill 的 Builder 历史”。按 updated_at 降序。
    """

    sessions = await skill_builder_service.list_sessions(
        db,
        user_id=user.id,
        skill_id=skill_id,
        status=status.value if status is not None else None,
        limit=limit,
    )
    return [SkillBuilderSessionBrief.model_validate(session) for session in sessions]


@router.get("/{session_id}", response_model=SkillBuilderSessionResponse)
async def get_skill_builder_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SkillBuilderSessionResponse:
    session = await get_session_or_404(db, session_id=session_id, user=user)
    agent_id = await skill_builder_service.resolve_session_agent_id(db, session)
    return _session_response(session, agent_id=agent_id)


@router.get("/{session_id}/files", response_model=SkillBuilderFilesResponse)
async def list_skill_builder_files(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SkillBuilderFilesResponse:
    """草稿工作区文件列表（rail source view，M7）。

    基于 stat 枚举，使用与 adapter 相同的 filter（排除 ``inputs/``、binary skip），
    因此不会读取整个工作区的字节内容（R2 perf），也不会直接处理磁盘路径，
    不存在 traversal 暴露面。
    """

    session = await get_session_or_404(db, session_id=session_id, user=user)
    if not session.draft_workspace_path:
        return SkillBuilderFilesResponse(files=[])
    entries = skill_draft_workspace.list_draft_file_entries(session.draft_workspace_path)
    return SkillBuilderFilesResponse(
        files=[
            SkillBuilderFileEntry(path=path, size=size, role=role) for path, size, role in entries
        ]
    )


@router.get("/{session_id}/files/content", response_model=SkillBuilderFileContentResponse)
async def get_skill_builder_file_content(
    session_id: uuid.UUID,
    path: str = Query(..., min_length=1, max_length=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SkillBuilderFileContentResponse:
    """查询草稿文件内容（仅 owner，rail source viewer）。

    请求 path 必须与 adapter 枚举出的规范化路径**完全一致** —
    因为没有磁盘 resolve，所以 ``../`` 一类 traversal 会因匹配失败（404）结束。
    """

    session = await get_session_or_404(db, session_id=session_id, user=user)
    if not session.draft_workspace_path:
        raise skill_file_not_found()
    match = skill_draft_workspace.load_draft_file_content(session.draft_workspace_path, path)
    if match is None:
        raise skill_file_not_found()
    return SkillBuilderFileContentResponse(path=match.path, role=match.role, content=match.content)


@router.post("/{session_id}/validate", response_model=SkillBuilderSessionResponse)
async def validate_skill_builder_draft(
    session_id: uuid.UUID,
    draft: SkillDraftPackage,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> SkillBuilderSessionResponse:
    session = await get_session_or_404(db, session_id=session_id, user=user)
    await skill_builder_service.save_draft_package(
        db,
        session,
        draft=draft.model_dump(mode="json"),
    )
    result = validate_draft_package(
        files=draft.files,
        credential_requirements=draft.credential_requirements,
        execution_profile=draft.execution_profile,
    )
    await skill_builder_service.save_validation_result(db, session, result=result)
    if result["error_count"] > 0:
        await record_builder_audit(
            db,
            user=user,
            request=request,
            action="skill_builder.validation_failed",
            session_id=session.id,
            mode=session.mode,
            error_count=result["error_count"],
        )
        await record_secret_scan_blocked_if_needed(
            db,
            user=user,
            request=request,
            session=session,
            validation_result=result,
        )
    await db.commit()
    await db.refresh(session)
    return SkillBuilderSessionResponse.model_validate(session)


@router.post("/{session_id}/confirm", response_model=SkillResponse, status_code=201)
async def confirm_skill_builder_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> SkillResponse:
    session = await get_session_or_404(db, session_id=session_id, user=user)
    existing = await completed_skill(db, session=session, user=user)
    if existing is not None:
        # bare model_validate 会跳过 used_by_count（始终为 0 的列）、health 等 enrichment —
        # 与其他 SkillResponse 路径一致，应经过 serializer。
        return await serialize_skill(db, existing, user)
    if session.status == SkillBuilderStatus.CONFIRMING.value:
        raise session_confirming()
    if session.status != SkillBuilderStatus.REVIEW.value:
        raise skill_builder_session_not_ready()

    claimed = await skill_builder_service.claim_for_confirming(db, session.id, user.id)
    if not claimed:
        raise session_confirming()
    session = await get_session_or_404(db, session_id=session_id, user=user)
    try:
        skill = await skill_builder_service.confirm_session(db, session, user_id=user.id)
    except SkillBuilderConflictError as exc:
        await record_builder_audit(
            db,
            user=user,
            request=request,
            action="skill_builder.apply_conflict",
            session_id=session.id,
            mode=session.mode,
            source_skill_id=session.source_skill_id,
            old_hash=exc.base_content_hash,
            new_hash=exc.current_content_hash,
            outcome="denied",
        )
        await db.commit()
        raise skill_builder_source_conflict() from exc
    except SkillBuilderSourceSkillNotFound as exc:
        await db.rollback()
        raise skill_not_found() from exc
    except SkillBuilderValidationError as exc:
        await record_secret_scan_blocked_if_needed(
            db,
            user=user,
            request=request,
            session=session,
            validation_result=exc.result,
        )
        await db.commit()
        raise invalid_skill_package("skill builder draft validation failed") from exc

    await record_builder_audit(
        db,
        user=user,
        request=request,
        action=_confirm_action(session.mode),
        session_id=session.id,
        mode=session.mode,
        source_skill_id=session.source_skill_id,
        **confirm_audit_metadata(session, skill),
    )
    await record_current_revision_create_audit(
        db,
        user=user,
        request=request,
        skill=skill,
    )
    await db.commit()
    await db.refresh(skill)
    return await serialize_skill(db, skill, user)


def _confirm_action(mode: str) -> str:
    if mode == SkillBuilderMode.IMPROVE.value:
        return "skill_builder.apply_improvement"
    return "skill_builder.confirm_create"
