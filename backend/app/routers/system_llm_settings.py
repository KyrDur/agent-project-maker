"""Authenticated personal model settings (legacy URL retained)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credential_service
from app.dependencies import (
    CurrentUser,
    get_current_user,
    get_db,
    verify_csrf,
)
from app.models.system_llm_setting import (
    SYSTEM_LLM_ROLES,
    VISIBLE_SYSTEM_LLM_ROLES,
)
from app.models.user_llm_setting import UserLlmSetting
from app.schemas.model import ModelTestResponse
from app.schemas.system_llm_setting import (
    SystemLlmSettingOut,
    SystemLlmSettingUpdate,
    SystemLlmTestRequest,
)
from app.services import audit_service
from app.services.model_test import run_model_test

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system-llm-settings", tags=["system-llm-settings"])

# Credential definition_keys that are valid LLM providers for a system slot.
# (ADR-019 — openai / anthropic / openrouter / litellm-style openai_compatible)
_LLM_DEFINITION_KEYS = frozenset(
    {
        "deepseek",
        "moonshot",
        "openai",
        "zhipu_glm",
        "openrouter",
        "openai_compatible",
        "anthropic",
    }
)

# Unified message for any invalid credential selection. Distinguishing
# "missing" from "wrong type" only in the server log avoids leaking which
# system credentials exist (enumeration oracle, security.md).
_INVALID_CREDENTIAL_DETAIL = "credential_id must reference an active personal LLM credential"

_PROVIDER_MISMATCH_DETAIL = (
    "credential_id must reference a personal credential for the selected provider"
)


async def _load_valid_system_llm_credential(
    db: AsyncSession, credential_id: uuid.UUID, user_id: uuid.UUID
):
    cred = await credential_service.get_for_user(db, credential_id, user_id)
    if cred is None or cred.status != "active":
        logger.info(
            "Rejected personal LLM credential %s: not an active owned credential",
            credential_id,
        )
        raise HTTPException(status_code=404, detail=_INVALID_CREDENTIAL_DETAIL)
    if cred.definition_key not in _LLM_DEFINITION_KEYS:
        logger.info(
            "Rejected personal LLM credential %s: definition_key %r not an LLM provider",
            credential_id,
            cred.definition_key,
        )
        raise HTTPException(status_code=422, detail=_INVALID_CREDENTIAL_DETAIL)
    return cred


async def _build_out(db: AsyncSession, setting: UserLlmSetting) -> SystemLlmSettingOut:
    """Materialize a settings row into the API shape.

    ``provider`` comes from ``credential.definition_key`` (no decrypt).
    ``base_url`` requires a decrypt; at most one per configured role (3 roles
    total) so there is no N+1 concern. Decryption failures degrade to NULL
    rather than failing the whole list.
    """

    cred = None
    credential_name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    key_available = False

    if setting.credential_id is not None:
        cred = await credential_service.get_for_user(db, setting.credential_id, setting.user_id)
        if cred is not None:
            credential_name = cred.name
            provider = cred.definition_key
            try:
                payload = await credential_service.decrypt_with_external(cred.data_encrypted)
                key_available = bool(payload.get("api_key") or payload.get("token"))
                raw = payload.get("base_url")
                base_url = str(raw) if raw else None
            except Exception:  # noqa: BLE001
                logger.exception("System LLM credential %s decryption failed", cred.id)

    configured = (
        cred is not None
        and provider is not None
        and cred.status == "active"
        and bool(setting.model_name)
        and key_available
    )
    return SystemLlmSettingOut(
        role=setting.role,
        credential_id=setting.credential_id,
        credential_name=credential_name,
        provider=provider,
        base_url=base_url,
        model_name=setting.model_name,
        configured=configured,
        updated_at=setting.updated_at,
    )


@router.get("", response_model=list[SystemLlmSettingOut])
async def list_system_llm_settings(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[SystemLlmSettingOut]:
    """Current user’s role slots."""
    result = await db.execute(select(UserLlmSetting).where(UserLlmSetting.user_id == user.id))
    by_role = {s.role: s for s in result.scalars().all()}
    out: list[SystemLlmSettingOut] = []
    for role in SYSTEM_LLM_ROLES:
        setting = by_role.get(role)
        if setting is None:
            # Seed missing (e.g. legacy DB) — self-heal so the screen renders.
            setting = UserLlmSetting(user_id=user.id, role=role)
            db.add(setting)
            await db.flush()
        if role in VISIBLE_SYSTEM_LLM_ROLES:
            out.append(await _build_out(db, setting))
    return out


@router.get("/readiness")
async def system_llm_readiness(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, object]]:
    """Public authenticated readiness view without credential metadata."""

    from app.services.system_credential_resolver import (
        SystemModelNotConfiguredError,
        resolve_system_model,
    )

    rows: list[dict[str, object]] = []
    for role in VISIBLE_SYSTEM_LLM_ROLES:
        if role == "image":
            continue
        try:
            resolved = await resolve_system_model(db, role, user.id)
        except SystemModelNotConfiguredError:
            rows.append({"role": role, "configured": False, "provider": None, "model_name": None})
        else:
            rows.append(
                {
                    "role": role,
                    "configured": True,
                    "provider": resolved.provider,
                    "model_name": resolved.model_name,
                }
            )
    return rows


@router.post("/test", response_model=ModelTestResponse)
async def test_system_llm_selection(
    payload: SystemLlmTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> ModelTestResponse:
    """Test the current user’s selected provider, credential and model."""

    cred = await _load_valid_system_llm_credential(db, payload.credential_id, user.id)
    if cred.definition_key != payload.provider:
        raise HTTPException(status_code=422, detail=_PROVIDER_MISMATCH_DETAIL)

    data = await credential_service.decrypt_with_external(cred.data_encrypted)
    result = await run_model_test(
        provider=payload.provider,
        model_name=payload.model_name,
        base_url=None,
        credential_data=data,
    )
    body = result.to_dict()

    client = request.client.host if request.client else None
    await credential_service.write_audit_log(
        db,
        credential_id=cred.id,
        actor_user_id=user.id,
        action="test",
        source="system_llm_settings",
        ip=client,
        user_agent=request.headers.get("user-agent"),
        error=None if result.success else (result.error.message if result.error else None),
        metadata={
            "success": result.success,
            "provider": payload.provider,
            "model_name": payload.model_name,
        },
    )
    await db.commit()
    return ModelTestResponse(**body)


@router.put("/{role}", response_model=SystemLlmSettingOut)
async def update_system_llm_setting(
    role: str,
    payload: SystemLlmSettingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> SystemLlmSettingOut:
    """Select (or clear) the current user’s credential/model for a role."""
    if role not in SYSTEM_LLM_ROLES:
        raise HTTPException(status_code=404, detail="unknown system LLM role")

    if payload.credential_id is not None:
        await _load_valid_system_llm_credential(db, payload.credential_id, user.id)

    result = await db.execute(
        select(UserLlmSetting).where(UserLlmSetting.role == role, UserLlmSetting.user_id == user.id)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = UserLlmSetting(user_id=user.id, role=role)
        db.add(setting)

    setting.credential_id = payload.credential_id
    setting.model_name = payload.model_name
    await db.commit()
    await db.refresh(setting)
    out = await _build_out(db, setting)
    await audit_service.record_event(
        db,
        actor_type="user",
        actor_user_id=user.id,
        actor_email_snapshot=user.email,
        owner_user_id=user.id,
        owner_email_snapshot=user.email,
        action="system_llm_setting.update",
        target_type="system_llm_setting",
        target_id=role,
        target_name_snapshot=role,
        target_owner_user_id=user.id,
        outcome="success",
        request=request,
        metadata={
            "role": role,
            "configured": out.configured,
            "credential_bound": out.credential_id is not None,
            "provider": out.provider,
            "model_name": out.model_name,
        },
    )
    await db.commit()
    return out


__all__ = ["router"]
