"""Authenticated private Builder/evaluation/judge configuration."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.routers.system_llm_settings import _LLM_DEFINITION_KEYS
from app.schemas.model import ModelTestResponse
from app.schemas.system_llm_setting import (
    SystemLlmSettingOut,
    SystemLlmSettingUpdate,
    SystemLlmTestRequest,
)
from app.services import user_llm_settings as service
from app.services.model_test import run_model_test
from app.services.system_credential_resolver import SystemModelNotConfiguredError
from app.services.user_llm_settings import USER_LLM_ROLES

router = APIRouter(prefix="/api/user-llm-settings", tags=["user-llm-settings"])


async def valid_credential(db: AsyncSession, user_id: uuid.UUID, credential_id: uuid.UUID):
    cred = await service.private_credential(db, user_id, credential_id)
    if cred is None:
        raise HTTPException(404, "credential_not_found")
    if cred.status != "active" or cred.definition_key not in _LLM_DEFINITION_KEYS:
        raise HTTPException(422, "active_llm_credential_required")
    return cred


async def output(db: AsyncSession, user_id: uuid.UUID, role: str) -> SystemLlmSettingOut:
    return await service.setting_output(db, user_id, role)


@router.get("")
async def list_settings(
    db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)
) -> list[SystemLlmSettingOut]:
    return [await output(db, user.id, role) for role in USER_LLM_ROLES]


@router.get("/readiness")
async def readiness(
    db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)
) -> list[dict]:
    rows = []
    for role in USER_LLM_ROLES:
        try:
            model = await service.resolve_user_model(db, role, user.id)
            rows.append(
                {
                    "role": role,
                    "configured": True,
                    "provider": model.provider,
                    "model_name": model.model_name,
                }
            )
        except SystemModelNotConfiguredError:
            rows.append({"role": role, "configured": False, "provider": None, "model_name": None})
    return rows


@router.put("/{role}")
async def update_setting(
    role: str,
    payload: SystemLlmSettingUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> SystemLlmSettingOut:
    if role not in USER_LLM_ROLES:
        raise HTTPException(404, "unknown_role")
    if bool(payload.credential_id) != bool(payload.model_name):
        raise HTTPException(422, "credential_and_model_required")
    if payload.model_name and (not payload.model_name.strip() or len(payload.model_name) > 200):
        raise HTTPException(422, "invalid_model_name")
    if payload.credential_id:
        await valid_credential(db, user.id, payload.credential_id)
    await service.save_setting(db, user.id, role, payload.credential_id, payload.model_name)
    return await output(db, user.id, role)


@router.post("/test", response_model=ModelTestResponse)
async def test_selection(
    payload: SystemLlmTestRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> ModelTestResponse:
    from app.credentials import service as credentials

    cred = await valid_credential(db, user.id, payload.credential_id)
    if cred.definition_key != payload.provider:
        raise HTTPException(422, "provider_mismatch")
    data = await credentials.decrypt_with_external(cred.data_encrypted)
    result = await run_model_test(
        provider=payload.provider,
        model_name=payload.model_name,
        base_url=None,
        credential_data=data,
    )
    return ModelTestResponse(**result.to_dict())
