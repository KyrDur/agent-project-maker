"""Persist model identity, never API keys, for reproducible judging."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credentials
from app.services.agent_project_executor import SnapshotExecutionUnavailable


async def pin_judge(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from app.services.user_llm_settings import get_setting, private_credential

    setting = await get_setting(db, user_id, "judge_optimizer")
    if setting is None or not setting.credential_id or not setting.model_name:
        raise SnapshotExecutionUnavailable("evaluation_judge_not_configured")
    cred = await private_credential(db, user_id, setting.credential_id)
    if cred is None or cred.status != "active":
        raise SnapshotExecutionUnavailable("evaluation_judge_not_configured")
    payload = await credentials.decrypt_with_external(cred.data_encrypted)
    return {
        "role": "evaluator",
        "provider": cred.definition_key,
        "model_name": setting.model_name,
        "base_url": payload.get("base_url"),
        "credential_id": str(cred.id),
        "model_params": {"temperature": 0},
        "pinned": True,
        "user_id": str(user_id),
    }


async def resolve_pinned_judge(
    db: AsyncSession, pin: dict[str, Any], user_id: uuid.UUID
) -> tuple[Any, str]:
    from app.agent_runtime.model_factory import create_chat_model

    if not pin.get("pinned"):
        raise SnapshotExecutionUnavailable("evaluation_judge_pin_required")
    from app.services.user_llm_settings import private_credential

    if pin.get("user_id") != str(user_id):
        raise SnapshotExecutionUnavailable("evaluation_judge_credential_unavailable")
    cred = await private_credential(db, user_id, uuid.UUID(pin["credential_id"]))
    if cred is None or cred.status != "active" or cred.definition_key != pin["provider"]:
        raise SnapshotExecutionUnavailable("evaluation_judge_credential_unavailable")
    payload = await credentials.decrypt_with_external(cred.data_encrypted)
    if payload.get("base_url") != pin.get("base_url"):
        raise SnapshotExecutionUnavailable("evaluation_judge_endpoint_changed")
    key = str(payload.get("api_key") or payload.get("token") or "")
    if not key:
        raise SnapshotExecutionUnavailable("evaluation_judge_credential_unavailable")
    return create_chat_model(
        pin["provider"],
        pin["model_name"],
        api_key=key,
        base_url=pin.get("base_url"),
        allow_env_fallback=False,
        **pin.get("model_params", {}),
    ), key
