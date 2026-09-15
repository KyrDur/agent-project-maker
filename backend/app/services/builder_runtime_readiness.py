"""Personal runtime bindings for Builder. Never consult operator credentials."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.credential_resolution import _decrypt_api_key
from app.credentials.service import PROVIDER_TO_DEFINITION_KEY
from app.exceptions import AppError
from app.models.credential import Credential
from app.models.model import Model
from app.models.tool import Tool


@dataclass(frozen=True)
class RuntimeBinding:
    model: Model
    credential: Credential


def compatible(model: Model, credential: Credential, user_id: uuid.UUID) -> bool:
    return (
        credential.user_id == user_id
        and not credential.is_system
        and credential.status == "active"
        and credential.definition_key == PROVIDER_TO_DEFINITION_KEY.get(model.provider)
    )


async def usable_bindings(db: AsyncSession, user_id: uuid.UUID) -> list[RuntimeBinding]:
    credentials = list(
        await db.scalars(
            select(Credential)
            .where(
                Credential.user_id == user_id,
                Credential.is_system.is_(False),
                Credential.status == "active",
            )
            .order_by(Credential.created_at.desc(), Credential.id)
        )
    )
    usable = [c for c in credentials if await _decrypt_api_key(c)]
    models = await db.scalars(select(Model).where(Model.is_visible.is_(True)).order_by(Model.id))
    result = []
    for model in models:
        matches = [c for c in usable if compatible(model, c, user_id)]
        if matches:
            preferred = next(
                (c for c in matches if c.id == model.default_credential_id), matches[0]
            )
            result.append(RuntimeBinding(model, preferred))
    return result


async def require_binding(
    db: AsyncSession, user_id: uuid.UUID, selected: str | None
) -> RuntimeBinding:
    bindings = await usable_bindings(db, user_id)
    if selected:
        binding = next((b for b in bindings if str(b.model.id) == selected), None)
        if binding:
            return binding
        code = "builder_runtime_model_unavailable"
    elif len(bindings) == 1:
        return bindings[0]
    else:
        code = "builder_runtime_setup" if not bindings else "builder_runtime_choose"
    raise AppError(code=code, message=tr(code), status=422)


async def validate_tools(db: AsyncSession, user_id: uuid.UUID, tools: Sequence[Tool]) -> None:
    from app.credentials.service import decrypt_with_external, get_for_user
    from app.tools.registry import registry

    for tool in tools:
        definition = registry.get(tool.definition_key)
        if definition is None or not tool.enabled:
            raise AppError(
                code="builder_tool_unavailable", message=tr("builder_tool_unavailable"), status=422
            )
        if definition.credential_definition_keys:
            credential = (
                await get_for_user(db, tool.credential_id, user_id) if tool.credential_id else None
            )
            if (
                credential is None
                or credential.status != "active"
                or credential.definition_key not in definition.credential_definition_keys
            ):
                raise AppError(
                    code="builder_tool_credential",
                    message=tr("builder_tool_credential"),
                    status=422,
                )
            try:
                payload = await decrypt_with_external(credential.data_encrypted)
                if not payload:
                    raise ValueError("empty credential")
            except Exception as exc:
                raise AppError(
                    code="builder_tool_credential",
                    message=tr("builder_tool_credential"),
                    status=422,
                ) from exc


# These middleware constructors need neither another model nor live filesystem/tool access.
# The full Settings catalog remains available for manual configuration.
BUILDER_MIDDLEWARE_TYPES = frozenset(
    {
        "context_editing",
        "pii",
        "model_call_limit",
        "tool_call_limit",
        "tool_retry",
        "model_retry",
    }
)
