"""Resolve only the current user's private model selections."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credentials
from app.models.user_llm_setting import UserLlmSetting
from app.services.system_credential_resolver import (
    ResolvedSystemModel,
    SystemModelNotConfiguredError,
)


async def get_setting(db: AsyncSession, user_id: uuid.UUID, role: str) -> UserLlmSetting | None:
    return await db.scalar(
        select(UserLlmSetting).where(UserLlmSetting.user_id == user_id, UserLlmSetting.role == role)
    )


async def private_credential(db: AsyncSession, user_id: uuid.UUID, credential_id: uuid.UUID):
    credential = await credentials.get_for_user(db, credential_id, user_id)
    if credential is None or credential.is_system or credential.user_id != user_id:
        return None
    return credential


async def resolve_user_model(
    db: AsyncSession, role: str, user_id: uuid.UUID
) -> ResolvedSystemModel:
    setting = await get_setting(db, user_id, role)
    if setting is None:
        raise SystemModelNotConfiguredError(role)
    credential = (
        await private_credential(db, user_id, setting.credential_id)
        if setting.credential_id
        else None
    )
    if credential is None or credential.status != "active" or not setting.model_name:
        raise SystemModelNotConfiguredError(role)
    payload = await credentials.decrypt_with_external(credential.data_encrypted)
    key = payload.get("api_key") or payload.get("token")
    if not key:
        raise SystemModelNotConfiguredError(role)
    return ResolvedSystemModel(
        provider=credential.definition_key,
        model_name=setting.model_name,
        api_key=str(key),
        base_url=payload.get("base_url"),
    )
