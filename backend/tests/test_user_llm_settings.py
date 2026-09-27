import uuid

import pytest

from app.credentials import service as credentials
from app.exceptions import AppError
from app.models.system_llm_setting import SystemLlmSetting
from app.models.user import User
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from app.services.agent_project_model_pins import pin_judge, resolve_pinned_judge
from app.services.builder_service import get_builder_system_runtime
from app.services.system_credential_resolver import SystemModelNotConfiguredError
from app.services.user_llm_settings import resolve_user_model
from tests.conftest import TEST_USER_ID

pytestmark = pytest.mark.asyncio
BASE = "/api/user-llm-settings"


async def test_platform_configuration_cannot_supply_private_roles(db):
    platform = await credentials.create(
        db,
        user_id=None,
        definition_key="openai",
        name="Operator key",
        data={"api_key": "operator-only-key"},
        is_system=True,
    )
    for role in ("builder", "evaluation_generator", "judge_optimizer"):
        db.add(SystemLlmSetting(role=role, credential_id=platform.id, model_name="operator-model"))
    await db.commit()

    for role in ("builder", "evaluation_generator", "judge_optimizer"):
        with pytest.raises(SystemModelNotConfiguredError):
            await resolve_user_model(db, role, TEST_USER_ID)
    with pytest.raises(AppError) as exc:
        await get_builder_system_runtime(db, TEST_USER_ID)
    assert exc.value.code == "builder_runtime_setup"
    with pytest.raises(SnapshotExecutionUnavailable, match="judge_not_configured"):
        await pin_judge(db, TEST_USER_ID)


async def test_private_roles_do_not_require_admin_and_reject_other_users(client, db, test_app):
    from app.dependencies import CurrentUser, get_current_user

    previous = test_app.dependency_overrides[get_current_user]
    test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=TEST_USER_ID, name="Regular user", email="test@test.com", is_super_user=False
    )
    try:
        other = User(email="other-model-owner@test.com", name="Other")
        db.add(other)
        await db.flush()
        own = await credentials.create(
            db,
            user_id=TEST_USER_ID,
            definition_key="openai",
            name="Mine",
            data={"api_key": "private-test-key"},
        )
        foreign = await credentials.create(
            db,
            user_id=other.id,
            definition_key="openai",
            name="Other",
            data={"api_key": "other-test-key"},
        )
        await db.commit()
        assert (await client.get(BASE)).status_code == 200
        assert (await client.get("/api/system-llm-settings")).status_code == 403
        for credential_id in [foreign.id, uuid.uuid4()]:
            response = await client.put(
                f"{BASE}/builder",
                json={"credential_id": str(credential_id), "model_name": "private-model"},
            )
            assert response.status_code == 404
            assert "api_key" not in response.text
        for role in ("builder", "evaluation_generator", "judge_optimizer"):
            response = await client.put(
                f"{BASE}/{role}", json={"credential_id": str(own.id), "model_name": "private-model"}
            )
            assert response.status_code == 200, response.text
            assert response.json()["configured"]
            model = await resolve_user_model(db, role, TEST_USER_ID)
            assert model.model_name == "private-model"
            assert model.api_key == "private-test-key"
        readiness = await client.get(f"{BASE}/readiness")
        assert all(row["configured"] for row in readiness.json())
        assert "private-test-key" not in readiness.text
        with pytest.raises(SystemModelNotConfiguredError):
            await resolve_user_model(db, "builder", other.id)
    finally:
        test_app.dependency_overrides[get_current_user] = previous


async def test_private_judge_pin_is_owned_and_does_not_follow_selection(client, db, monkeypatch):
    own = await credentials.create(
        db,
        user_id=TEST_USER_ID,
        definition_key="openai",
        name="Mine",
        data={"api_key": "private-test-key"},
    )
    await db.commit()
    await client.put(
        f"{BASE}/judge_optimizer", json={"credential_id": str(own.id), "model_name": "frozen-model"}
    )
    pin = await pin_judge(db, TEST_USER_ID)
    await client.put(
        f"{BASE}/judge_optimizer", json={"credential_id": str(own.id), "model_name": "new-model"}
    )
    calls = []
    monkeypatch.setattr(
        "app.agent_runtime.model_factory.create_chat_model",
        lambda *args, **kwargs: calls.append(args),
    )
    await resolve_pinned_judge(db, pin, TEST_USER_ID)
    assert calls == [("openai", "frozen-model")]
    with pytest.raises(SnapshotExecutionUnavailable):
        await resolve_pinned_judge(db, pin, uuid.uuid4())
    own.status = "inactive"
    await db.commit()
    with pytest.raises(SystemModelNotConfiguredError):
        await resolve_user_model(db, "judge_optimizer", TEST_USER_ID)
