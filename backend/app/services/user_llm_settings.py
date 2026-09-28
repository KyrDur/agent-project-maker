"""Resolve only the current user's private model selections."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credentials
from app.models.agent_project import utcnow
from app.models.user import User
from app.models.user_llm_setting import USER_LLM_ROLES as _USER_LLM_ROLES
from app.models.user_llm_setting import UserLlmSetting
from app.schemas.system_llm_setting import SystemLlmSettingOut
from app.services.system_credential_resolver import (
    ResolvedSystemModel,
    SystemModelNotConfiguredError,
)

USER_LLM_ROLES = _USER_LLM_ROLES


async def get_setting(db: AsyncSession, user_id: uuid.UUID, role: str) -> UserLlmSetting | None:
    return await db.scalar(
        select(UserLlmSetting).where(UserLlmSetting.user_id == user_id, UserLlmSetting.role == role)
    )


async def private_credential(db: AsyncSession, user_id: uuid.UUID, credential_id: uuid.UUID):
    credential = await credentials.get_for_user(db, credential_id, user_id)
    if credential is None or credential.is_system or credential.user_id != user_id:
        return None
    return credential


async def setting_output(db: AsyncSession, user_id: uuid.UUID, role: str) -> SystemLlmSettingOut:
    setting = await get_setting(db, user_id, role)
    cred = (
        await private_credential(db, user_id, setting.credential_id)
        if setting and setting.credential_id
        else None
    )
    return SystemLlmSettingOut(
        role=role,
        credential_id=cred.id if cred else None,
        credential_name=cred.name if cred else None,
        provider=cred.definition_key if cred else None,
        model_name=setting.model_name if setting else None,
        configured=bool(cred and cred.status == "active" and setting and setting.model_name),
        updated_at=setting.updated_at if setting else utcnow(),
    )


async def save_setting(
    db: AsyncSession,
    user_id: uuid.UUID,
    role: str,
    credential_id: uuid.UUID | None,
    model_name: str | None,
) -> None:
    """Serialize first-time setup and subsequent changes for one user."""

    await db.execute(select(User).where(User.id == user_id).with_for_update())
    setting = await get_setting(db, user_id, role)
    if setting is None:
        setting = UserLlmSetting(user_id=user_id, role=role)
        db.add(setting)
    setting.credential_id = credential_id
    setting.model_name = model_name.strip() if model_name else None
    await db.commit()


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
