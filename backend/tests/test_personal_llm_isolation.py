"""Account isolation and no administrator fallback for personal AI settings."""

import asyncio
import uuid

import pytest

from app.credentials import service as credentials
from app.models.system_llm_setting import SystemLlmSetting
from app.models.user_llm_setting import UserLlmSetting
from app.services.llm_user_context import llm_user_id
from app.services.system_credential_resolver import (
    SystemModelNotConfiguredError,
    resolve_system_model,
)
from tests.conftest import TEST_USER_ID, TestSession

pytestmark = pytest.mark.asyncio
BASE = "/api/system-llm-settings"


async def personal_key(db, owner, key):
    return await credentials.create(
        db, user_id=owner, definition_key="openai", name="Personal test key", data={"api_key": key}
    )


async def test_foreign_key_and_admin_key_cannot_be_selected(client, db):
    foreign = await personal_key(db, uuid.uuid4(), "foreign-test-only")
    admin = await credentials.create(
        db,
        user_id=None,
        is_system=True,
        definition_key="openai",
        name="Admin",
        data={"api_key": "admin-test-only"},
    )
    await db.commit()
    for cred in (foreign, admin):
        response = await client.put(
            f"{BASE}/builder", json={"credential_id": str(cred.id), "model_name": "test-model"}
        )
        assert response.status_code == 404
        response = await client.post(
            f"{BASE}/test",
            json={"provider": "openai", "credential_id": str(cred.id), "model_name": "test-model"},
        )
        assert response.status_code == 404
        assert "test-only" not in response.text


async def test_admin_configuration_does_not_make_user_ready(client, db):
    admin = await credentials.create(
        db,
        user_id=None,
        is_system=True,
        definition_key="openai",
        name="Admin",
        data={"api_key": "admin-test-only"},
    )
    db.add(SystemLlmSetting(role="text_primary", credential_id=admin.id, model_name="admin-model"))
    await db.commit()
    assert all(not row["configured"] for row in (await client.get(f"{BASE}/readiness")).json())
    with pytest.raises(SystemModelNotConfiguredError):
        await resolve_system_model(db, "builder", TEST_USER_ID)


async def test_selections_are_independent_and_no_key_is_returned(client, db):
    other = uuid.uuid4()
    key = await personal_key(db, TEST_USER_ID, "personal-secret-test-only")
    other_key = await personal_key(db, other, "foreign-secret-test-only")
    db.add(
        UserLlmSetting(
            user_id=other, role="builder", credential_id=other_key.id, model_name="other-model"
        )
    )
    await db.commit()
    response = await client.put(
        f"{BASE}/builder", json={"credential_id": str(key.id), "model_name": "my-model"}
    )
    assert response.status_code == 200
    assert "secret-test-only" not in response.text
    rows = (await client.get(BASE)).json()
    assert next(r for r in rows if r["role"] == "builder")["model_name"] == "my-model"
    assert "other-model" not in str(rows)
    assert (await resolve_system_model(db, "builder", other)).model_name == "other-model"


async def test_missing_owner_never_uses_global_configuration(db):
    token = llm_user_id.set(None)
    try:
        with pytest.raises(SystemModelNotConfiguredError):
            await resolve_system_model(db, "builder")
    finally:
        llm_user_id.reset(token)


async def test_disabled_credential_blocks_execution(client, db):
    key = await personal_key(db, TEST_USER_ID, "test-key")
    key.status = "disabled"
    db.add(
        UserLlmSetting(user_id=TEST_USER_ID, role="builder", credential_id=key.id, model_name="m")
    )
    await db.commit()
    with pytest.raises(SystemModelNotConfiguredError):
        await resolve_system_model(db, "builder", TEST_USER_ID)
    readiness = (await client.get(f"{BASE}/readiness")).json()
    assert not next(r for r in readiness if r["role"] == "builder")["configured"]


async def test_partial_or_blank_selection_is_rejected(client, db):
    key = await personal_key(db, TEST_USER_ID, "test-key")
    await db.commit()
    for payload in (
        {"credential_id": str(key.id)},
        {"model_name": "m"},
        {"credential_id": str(key.id), "model_name": " "},
    ):
        assert (await client.put(f"{BASE}/builder", json=payload)).status_code == 422


async def test_context_keeps_concurrent_users_separate(db):
    owners = [uuid.uuid4(), uuid.uuid4()]
    for index, owner in enumerate(owners):
        key = await personal_key(db, owner, f"test-key-{index}")
        db.add(
            UserLlmSetting(
                user_id=owner, role="builder", credential_id=key.id, model_name=f"model-{index}"
            )
        )
    await db.commit()

    async def resolve(owner):
        token = llm_user_id.set(owner)
        try:
            async with TestSession() as session:
                result = await resolve_system_model(session, "builder")
                return result.model_name, result.api_key
        finally:
            llm_user_id.reset(token)

    assert await asyncio.gather(*(resolve(o) for o in owners)) == [
        ("model-0", "test-key-0"),
        ("model-1", "test-key-1"),
    ]


async def test_real_auth_context_is_personal_and_resets(raw_client, db):
    from tests.conftest import register_session

    first = await register_session(
        raw_client, email="personal-first@example.com", name="First user"
    )
    first_id = uuid.UUID(first.body["user"]["id"])
    first_key = await personal_key(db, first_id, "test-first-key")
    second = await register_session(
        raw_client, email="personal-second@example.com", name="Second user"
    )
    second_id = uuid.UUID(second.body["user"]["id"])
    assert not second.body["user"]["is_super_user"]
    second_key = await personal_key(db, second_id, "test-second-key")
    await db.commit()
    for session, key, name in (
        (first, first_key, "first-model"),
        (second, second_key, "second-model"),
    ):
        session.apply(raw_client)
        response = await raw_client.put(
            f"{BASE}/builder",
            headers=session.headers(),
            json={"credential_id": str(key.id), "model_name": name},
        )
        assert response.status_code == 200, response.text
        assert (
            next(r for r in (await raw_client.get(BASE)).json() if r["role"] == "builder")[
                "model_name"
            ]
            == name
        )
        assert llm_user_id.get() is None
    response = await raw_client.put(
        f"{BASE}/builder",
        headers=second.headers(),
        json={"credential_id": str(first_key.id), "model_name": "stolen"},
    )
    assert response.status_code == 404
    assert (
        await raw_client.put(f"{BASE}/builder", json={"credential_id": None, "model_name": None})
    ).status_code == 403


async def test_builder_uses_personal_endpoint_and_binds_owned_key(db):
    from app.services.builder_service import get_builder_system_runtime

    owner = uuid.uuid4()
    cred = await credentials.create(
        db,
        user_id=owner,
        definition_key="openai_compatible",
        name="Custom endpoint",
        data={"api_key": "test-endpoint-key", "base_url": "https://personal.example.test/v1"},
    )
    db.add(
        UserLlmSetting(
            user_id=owner, role="builder", credential_id=cred.id, model_name="custom-model"
        )
    )
    await db.commit()
    binding = await get_builder_system_runtime(db, owner)
    assert binding.model.base_url == "https://personal.example.test/v1"
    assert binding.credential.id == cred.id and not binding.credential.is_system


async def test_judge_does_not_send_new_personal_key_to_old_frozen_endpoint(db, monkeypatch):
    from app.services import agent_project_llm
    from app.services.agent_project_executor import SnapshotExecutionUnavailable
    from app.services.system_credential_resolver import ResolvedSystemModel

    async def changed_endpoint(_db, _role, owner):
        assert owner == TEST_USER_ID
        return ResolvedSystemModel(
            provider="openai_compatible",
            model_name="judge",
            api_key="test-new-endpoint-key",
            base_url="https://new.example.com/v1",
        )

    def unexpected_factory(*_args, **_kwargs):
        pytest.fail("A changed endpoint must be rejected before constructing a model")

    monkeypatch.setattr(agent_project_llm, "resolve_system_model", changed_endpoint)
    monkeypatch.setattr("app.agent_runtime.model_factory.create_chat_model", unexpected_factory)
    with pytest.raises(
        SnapshotExecutionUnavailable, match="evaluation_judge_configuration_changed"
    ):
        await agent_project_llm.resolve_model(
            db,
            {
                "evaluation_roles": {
                    "judge": {
                        "provider": "openai_compatible",
                        "model_name": "judge",
                        "base_url": "https://old.example.com/v1",
                    }
                }
            },
            TEST_USER_ID,
        )


async def test_public_http_tool_can_be_created_without_authentication(db):
    from app.models.tool import Tool
    from app.services.builder_runtime_readiness import validate_tools
    from app.tools.registry import registry

    definition = registry.get("http_request")
    assert definition is not None
    assert definition.serialize()["requires_credential"] is False
    await validate_tools(db, TEST_USER_ID, [Tool(definition_key="http_request", enabled=True)])


async def test_required_tool_authentication_cannot_be_skipped(db):
    from app.exceptions import AppError
    from app.models.tool import Tool
    from app.services.builder_runtime_readiness import validate_tools

    with pytest.raises(AppError) as error:
        await validate_tools(
            db, TEST_USER_ID, [Tool(definition_key="naver_search_blog", enabled=True)]
        )
    assert error.value.code == "builder_tool_credential"


@pytest.mark.parametrize("kind", ["foreign", "wrong_type", "disabled"])
async def test_optional_http_authentication_still_validates_bound_credential(db, kind):
    from app.exceptions import AppError
    from app.models.tool import Tool
    from app.services.builder_runtime_readiness import validate_tools

    key = await credentials.create(
        db,
        user_id=uuid.uuid4() if kind == "foreign" else TEST_USER_ID,
        definition_key="openai" if kind == "wrong_type" else "http_bearer",
        name="HTTP test credential",
        data={"api_key": "test-only"} if kind == "wrong_type" else {"token": "test-only"},
    )
    if kind == "disabled":
        key.status = "disabled"
    await db.flush()
    with pytest.raises(AppError) as error:
        await validate_tools(
            db,
            TEST_USER_ID,
            [Tool(definition_key="http_request", enabled=True, credential_id=key.id)],
        )
    assert error.value.code == "builder_tool_credential"
