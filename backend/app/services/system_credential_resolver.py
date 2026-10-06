"""Resolve personal model roles. Legacy function names preserve caller compatibility.

Never consult operator credentials or environment keys. A request's authenticated
owner is propagated for nested builder calls; jobs can pass user_id explicitly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credential_service
from app.models.user_llm_setting import UserLlmSetting
from app.services.llm_user_context import llm_user_id

logger = logging.getLogger(__name__)

# 三个模型角色必须由用户明确配置；可以绑定同一凭据，但不得自动代用。
SYSTEM_LLM_ROLE_FALLBACKS: dict[str, tuple[str, ...]] = {}


class SystemModelNotConfiguredError(Exception):
    """Personal setup is missing; neither global settings nor environment keys apply."""

    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(
            f"System LLM role '{role}' is not configured. "
            "Configure your API key and model in AI settings."
        )


@dataclass(frozen=True)
class ResolvedSystemModel:
    """Everything needed to build a chat/image model for a system role."""

    provider: str  # credential.definition_key (anthropic|openai|openrouter|openai_compatible)
    model_name: str
    api_key: str | None
    base_url: str | None
    credential_id: uuid.UUID | None = None


async def resolve_system_api_key(
    db: AsyncSession, provider: str, user_id: uuid.UUID | None = None
) -> str | None:
    owner = user_id or llm_user_id.get()
    if owner is None:
        return None
    from app.models.credential import Credential

    cred = (
        await db.execute(
            select(Credential)
            .where(
                Credential.user_id == owner,
                Credential.is_system.is_(False),
                Credential.definition_key == provider,
                Credential.status == "active",
            )
            .order_by(Credential.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if cred is None:
        return None
    payload = await credential_service.decrypt_with_external(cred.data_encrypted)
    key = payload.get("api_key") or payload.get("token")
    return str(key) if key else None


async def get_setting(
    db: AsyncSession, role: str, user_id: uuid.UUID | None = None
) -> UserLlmSetting | None:
    """Fetch the owner-scoped selection; no owner means no access."""
    owner = user_id or llm_user_id.get()
    if owner is None:
        raise SystemModelNotConfiguredError(role)
    result = await db.execute(
        select(UserLlmSetting).where(UserLlmSetting.role == role, UserLlmSetting.user_id == owner)
    )
    return result.scalar_one_or_none()


async def get_effective_setting(
    db: AsyncSession, role: str, user_id: uuid.UUID | None = None
) -> tuple[str, UserLlmSetting | None]:
    """Fetch the configured row for ``role``, without substituting another role."""

    setting = await get_setting(db, role, user_id)
    if setting is not None and setting.credential_id is not None and setting.model_name:
        return role, setting
    for fallback_role in SYSTEM_LLM_ROLE_FALLBACKS.get(role, ()):
        fallback = await get_setting(db, fallback_role, user_id)
        if fallback is not None and fallback.credential_id is not None and fallback.model_name:
            return fallback_role, fallback
    return role, setting


async def resolve_system_model(
    db: AsyncSession, role: str, user_id: uuid.UUID | None = None
) -> ResolvedSystemModel:
    """Resolve only the selected owner's personal credential and model."""

    _, setting = await get_effective_setting(db, role, user_id)
    if setting is None or setting.credential_id is None or not setting.model_name:
        raise SystemModelNotConfiguredError(role)

    cred = await credential_service.get_for_user(db, setting.credential_id, setting.user_id)
    if cred is None or cred.status != "active":
        # Credential deleted between selection and use (SET NULL not yet
        # applied, or race). Treat as unconfigured.
        raise SystemModelNotConfiguredError(role)

    try:
        payload = await credential_service.decrypt_with_external(cred.data_encrypted)
    except Exception as exc:
        raise SystemModelNotConfiguredError(role) from exc
    api_key = payload.get("api_key") or payload.get("token")
    if not api_key:
        raise SystemModelNotConfiguredError(role)
    base_url = payload.get("base_url")
    return ResolvedSystemModel(
        credential_id=cred.id,
        provider=cred.definition_key,
        model_name=setting.model_name,
        api_key=str(api_key) if api_key else None,
        base_url=str(base_url) if base_url else None,
    )


__all__ = [
    "ResolvedSystemModel",
    "SystemModelNotConfiguredError",
    "SYSTEM_LLM_ROLE_FALLBACKS",
    "get_effective_setting",
    "get_setting",
    "resolve_system_api_key",
    "resolve_system_model",
]
