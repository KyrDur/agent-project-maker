from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.model import Model

logger = logging.getLogger(__name__)

E2E_SCRIPTED_PROVIDER = "e2e_scripted"
E2E_SCRIPTED_MODEL_NAME = "document-artifact-scripted"
E2E_SCRIPTED_DISPLAY_NAME = "E2E Scripted Document Model"


async def seed_e2e_scripted_model(db: AsyncSession) -> Model | None:
    if settings.app_env == "production":
        logger.warning("skip seed_e2e_scripted_model: production environment")
        return None
    if not settings.e2e_scripted_model_enabled:
        return None

    model = (
        await db.execute(
            select(Model)
            .where(Model.provider == E2E_SCRIPTED_PROVIDER)
            .where(Model.model_name == E2E_SCRIPTED_MODEL_NAME)
            .limit(1)
        )
    ).scalar_one_or_none()

    if model is None:
        model = Model(
            provider=E2E_SCRIPTED_PROVIDER,
            model_name=E2E_SCRIPTED_MODEL_NAME,
            display_name=E2E_SCRIPTED_DISPLAY_NAME,
            is_default=False,
            is_visible=True,
            cost_per_input_token=Decimal("0"),
            cost_per_output_token=Decimal("0"),
            supports_function_calling=True,
            input_modalities=["text"],
            output_modalities=["text"],
            source="manual",
        )
        db.add(model)
        await db.flush()
        logger.info("seed_e2e_scripted_model: created %s", E2E_SCRIPTED_MODEL_NAME)
        await _seed_scripted_system_llm(db)
        await _seed_scripted_personal_llm(db)
        return model

    model.display_name = E2E_SCRIPTED_DISPLAY_NAME
    model.is_visible = True
    model.supports_function_calling = True
    model.input_modalities = ["text"]
    model.output_modalities = ["text"]
    model.source = "manual"
    await db.flush()
    logger.info("seed_e2e_scripted_model: refreshed %s", E2E_SCRIPTED_MODEL_NAME)
    await _seed_scripted_system_llm(db)
    await _seed_scripted_personal_llm(db)
    return model


E2E_SCRIPTED_SYSTEM_CREDENTIAL_NAME = "[e2e] Scripted System LLM"


async def _seed_scripted_system_llm(db: AsyncSession) -> None:
    """用于 Skill Builder 聊天 E2E 的 System LLM(text_primary) seed。

    Builder 聊天的 hidden Agent 会在 runtime 中通过 ``resolve_system_model('text_primary')``
    重新解析模型（ADR-019）— 如果 throwaway E2E stack 中该 slot 为空，
    Builder 会被 409 阻止，因此预置指向 scripted 模型的 system credential + 配置。
    **不要修改已经设置的 text_primary**（不覆盖真实 LiteLLM
    配置（seed_e2e_llm）或 operator 的选择）。
    """

    from app.credentials import service as credential_service
    from app.models.system_llm_setting import SystemLlmSetting

    existing = (
        await db.execute(
            select(SystemLlmSetting).where(SystemLlmSetting.role == "text_primary").limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.credential_id is not None and existing.model_name:
        return

    from app.models.credential import Credential

    credential = (
        await db.execute(
            select(Credential)
            .where(Credential.name == E2E_SCRIPTED_SYSTEM_CREDENTIAL_NAME)
            .limit(1)
        )
    ).scalar_one_or_none()
    if credential is None:
        credential = await credential_service.create(
            db,
            user_id=None,
            definition_key=E2E_SCRIPTED_PROVIDER,
            name=E2E_SCRIPTED_SYSTEM_CREDENTIAL_NAME,
            data={"api_key": "e2e-scripted"},
            is_system=True,
            source="seed",
        )

    if existing is None:
        db.add(
            SystemLlmSetting(
                role="text_primary",
                credential_id=credential.id,
                model_name=E2E_SCRIPTED_MODEL_NAME,
            )
        )
    else:
        existing.credential_id = credential.id
        existing.model_name = E2E_SCRIPTED_MODEL_NAME
    await db.flush()
    logger.info("seed_e2e_scripted_model: text_primary → scripted model (E2E)")


__all__ = [
    "E2E_SCRIPTED_DISPLAY_NAME",
    "E2E_SCRIPTED_MODEL_NAME",
    "E2E_SCRIPTED_PROVIDER",
    "E2E_SCRIPTED_SYSTEM_CREDENTIAL_NAME",
    "seed_e2e_scripted_model",
]


async def _seed_scripted_personal_llm(db: AsyncSession) -> None:
    from app.credentials import service as credential_service
    from app.models.credential import Credential
    from app.models.user import User
    from app.models.user_llm_setting import UserLlmSetting

    user = (
        await db.execute(select(User).where(User.email == settings.e2e_user_email))
    ).scalar_one_or_none()
    if user is None:
        return
    name = "[e2e] Scripted personal model"
    cred = (
        await db.execute(
            select(Credential).where(
                Credential.user_id == user.id,
                Credential.is_system.is_(False),
                Credential.name == name,
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        cred = await credential_service.create(
            db,
            user_id=user.id,
            definition_key=E2E_SCRIPTED_PROVIDER,
            name=name,
            data={"api_key": "e2e-scripted"},
            source="seed",
        )
    for role in ("builder", "evaluation_generator", "judge_optimizer", "text_primary"):
        row = (
            await db.execute(
                select(UserLlmSetting).where(
                    UserLlmSetting.user_id == user.id,
                    UserLlmSetting.role == role,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                UserLlmSetting(
                    user_id=user.id,
                    role=role,
                    credential_id=cred.id,
                    model_name=E2E_SCRIPTED_MODEL_NAME,
                )
            )
    await db.flush()
