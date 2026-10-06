"""Persistence and presentation of a user's model role settings."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credential_service
from app.models.system_llm_setting import SYSTEM_LLM_ROLES, VISIBLE_SYSTEM_LLM_ROLES
from app.models.user_llm_setting import UserLlmSetting
from app.schemas.system_llm_setting import SystemLlmSettingOut, SystemLlmSettingUpdate

logger = logging.getLogger(__name__)


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


async def list_settings(db: AsyncSession, user_id: uuid.UUID) -> list[SystemLlmSettingOut]:
    result = await db.execute(select(UserLlmSetting).where(UserLlmSetting.user_id == user_id))
    by_role = {setting.role: setting for setting in result.scalars().all()}
    out = []
    for role in SYSTEM_LLM_ROLES:
        setting = by_role.get(role)
        if setting is None:
            setting = UserLlmSetting(user_id=user_id, role=role)
            db.add(setting)
            await db.flush()
        if role in VISIBLE_SYSTEM_LLM_ROLES:
            out.append(await _build_out(db, setting))
    return out


async def update_setting(
    db: AsyncSession, user_id: uuid.UUID, role: str, payload: SystemLlmSettingUpdate
) -> SystemLlmSettingOut:
    result = await db.execute(
        select(UserLlmSetting).where(UserLlmSetting.role == role, UserLlmSetting.user_id == user_id)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = UserLlmSetting(user_id=user_id, role=role)
        db.add(setting)
    setting.credential_id = payload.credential_id
    setting.model_name = payload.model_name
    await db.commit()
    await db.refresh(setting)
    return await _build_out(db, setting)
