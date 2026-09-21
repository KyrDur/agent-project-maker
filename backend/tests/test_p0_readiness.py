"""Personal credential gates and first-party locale contracts; no paid API calls."""

from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_runtime.builder_i18n import locale_scope
from app.agent_runtime.builder_v3.nodes import phase8_build
from app.agent_runtime.middleware_registry import get_middleware_registry
from app.catalog_i18n import middleware_display, template_display
from app.credentials.service import encrypt_data
from app.dependencies import CurrentUser
from app.exceptions import AppError
from app.models.credential import Credential
from app.models.model import Model
from app.models.system_llm_setting import SystemLlmSetting
from app.models.user import User
from app.seed.default_templates import DEFAULT_TEMPLATES
from app.services import builder_runtime_readiness as readiness
from app.services import builder_service
from tests import test_agent_projects as project_fixtures

TEST_USER_ID = project_fixtures.TEST_USER_ID
db = project_fixtures.db

HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")


@pytest.mark.asyncio
async def test_builder_refresh_snapshot_is_owned_and_read_only(db, monkeypatch):
    from unittest.mock import AsyncMock

    from langchain_core.messages import AIMessage, HumanMessage

    from app.agent_runtime import checkpointer
    from app.agent_runtime.builder_v3 import graph
    from app.routers.builder import get_builder_snapshot

    db.add(User(id=TEST_USER_ID, name="P0", email="p0@example.test"))
    await db.commit()
    session = await builder_service.create_session(db, TEST_USER_ID, "整理周报")
    reader = AsyncMock(
        return_value=SimpleNamespace(
            values={
                "messages": [HumanMessage(content="整理周报"), AIMessage(content="智能体设置确认")]
            },
            tasks=[SimpleNamespace(interrupts=[SimpleNamespace(id="pending-choice")])],
        )
    )
    monkeypatch.setattr(checkpointer, "get_checkpointer", lambda: None)
    monkeypatch.setattr(graph, "compile_graph", lambda _: SimpleNamespace(aget_state=reader))
    payload = await get_builder_snapshot(
        session.id, db, CurrentUser(TEST_USER_ID, "p0@example.test", "P0")
    )
    assert payload["interrupt_id"] == "pending-choice"
    assert [m["content"] for m in payload["messages"]] == ["整理周报", "智能体设置确认"]
    assert not HANGUL.search(json.dumps(payload["messages"], ensure_ascii=False))
    with pytest.raises(AppError):
        await get_builder_snapshot(
            session.id, db, CurrentUser(uuid.uuid4(), "other@example.test", "Other")
        )
    assert reader.await_count == 1  # Unauthorized requests never read checkpoints.


@pytest.fixture
def encrypted(monkeypatch):
    from app.config import settings
    from app.security import key_provider

    monkeypatch.setattr(settings, "encryption_keys", "22" * 32)
    key_provider.reset_cache()
    yield encrypt_data({"api_key": "p0-dummy"})
    key_provider.reset_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2])
async def test_zero_one_multiple_personal_runtime_models(db, encrypted, monkeypatch, count):
    blob, key, fields = encrypted
    db.add(User(id=TEST_USER_ID, name="P0", email="p0@example.test"))
    # An operator model/key must never become a personal binding.
    db.add(
        Credential(
            user_id=None,
            is_system=True,
            name="Operator",
            definition_key="anthropic",
            data_encrypted=blob,
            key_id=key,
            field_keys=fields,
            status="active",
        )
    )
    db.add(
        Model(
            provider="anthropic",
            model_name="claude-sonnet-4-6",
            display_name="Claude",
            is_default=True,
        )
    )
    if count:
        db.add(
            Credential(
                user_id=TEST_USER_ID,
                is_system=False,
                name="Personal",
                definition_key="openai",
                data_encrypted=blob,
                key_id=key,
                field_keys=fields,
                status="active",
            )
        )
    for index in range(count):
        db.add(
            Model(provider="openai", model_name=f"fake-{index}", display_name=f"Personal {index}")
        )
    await db.commit()
    assert len(await readiness.usable_bindings(db, TEST_USER_ID)) == count
    if count == 1:
        binding = await readiness.require_binding(db, TEST_USER_ID, None)
        assert binding.credential.user_id == TEST_USER_ID and not binding.credential.is_system
    else:
        with pytest.raises(AppError) as caught:
            await readiness.require_binding(db, TEST_USER_ID, None)
        assert caught.value.code == (
            "builder_runtime_setup" if not count else "builder_runtime_choose"
        )
    session = await builder_service.create_session(db, TEST_USER_ID, "Build")
    monkeypatch.setattr(
        phase8_build, "async_session_factory", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    with locale_scope("zh-CN"):
        result = await phase8_build.phase8_propose({"session_id": str(session.id)})
    if count == 1:
        assert result["runtime_model_id"] and result["runtime_setup_payload"] is None
    else:
        payload = result["runtime_setup_payload"]
        assert not HANGUL.search(json.dumps(payload, ensure_ascii=False))
        assert len(payload["questions"][0]["options"]) == max(count, 1)
        assert not result["runtime_model_id"]


def test_provider_and_ownership_compatibility():
    model = Model(provider="anthropic")
    credential = Credential(
        user_id=TEST_USER_ID, is_system=False, status="active", definition_key="openai"
    )
    assert not readiness.compatible(model, credential, TEST_USER_ID)
    credential.definition_key = "anthropic"
    assert readiness.compatible(model, credential, TEST_USER_ID)
    credential.is_system = True
    assert not readiness.compatible(model, credential, TEST_USER_ID)
    credential.is_system = False
    assert not readiness.compatible(model, credential, uuid.uuid4())


@pytest.mark.asyncio
async def test_confirmation_commits_one_agent_project_and_immutable_v1(db, encrypted, monkeypatch):
    from sqlalchemy import func, select

    from app.models.agent import Agent
    from app.models.agent_project import AgentProject, AgentProjectVersion
    from app.services import builder_project_lifecycle

    blob, key, fields = encrypted
    db.add(User(id=TEST_USER_ID, name="P0", email="p0@example.test"))
    credential = Credential(
        user_id=TEST_USER_ID,
        name="Personal",
        definition_key="openai",
        data_encrypted=blob,
        key_id=key,
        field_keys=fields,
        status="active",
        is_system=False,
    )
    db.add(credential)
    model = Model(provider="openai", model_name="fake", display_name="Personal")
    db.add(model)
    await db.commit()
    session = await builder_service.create_session(db, TEST_USER_ID, "Build")
    session.draft_config = {
        "name": "助手",
        "system_prompt": "Be helpful",
        "tools": [],
        "middlewares": [],
    }
    await db.commit()
    scheduled = []
    monkeypatch.setattr(builder_project_lifecycle, "schedule", lambda *args: scheduled.append(args))
    first = await builder_service.confirm_build(db, session)
    second = await builder_service.confirm_build(db, session)
    assert first is not None and second is not None
    assert first.id == second.id and first.llm_credential_id == credential.id
    assert len(scheduled) == 1
    for table in (Agent, AgentProject, AgentProjectVersion):
        assert await db.scalar(select(func.count()).select_from(table)) == 1
    version = await db.scalar(select(AgentProjectVersion))
    assert version.version_number == 1
    assert version.snapshot_json["agent"]["model"]["id"] == str(model.id)
    version.snapshot_json = {"changed": True}
    with pytest.raises(ValueError, match="immutable"):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_confirm_build_uses_runtime_model_id_from_draft(db, encrypted, monkeypatch):
    from app.services import builder_project_lifecycle

    blob, key, fields = encrypted
    db.add(User(id=TEST_USER_ID, name="P0", email="p0@example.test"))
    openai_credential = Credential(
        user_id=TEST_USER_ID,
        name="OpenAI Personal",
        definition_key="openai",
        data_encrypted=blob,
        key_id=key,
        field_keys=fields,
        status="active",
        is_system=False,
    )
    anthropic_credential = Credential(
        user_id=TEST_USER_ID,
        name="Anthropic Personal",
        definition_key="anthropic",
        data_encrypted=blob,
        key_id=key,
        field_keys=fields,
        status="active",
        is_system=False,
    )
    db.add_all([openai_credential, anthropic_credential])
    selected_model = Model(provider="openai", model_name="gpt-4o", display_name="GPT-4o")
    other_model = Model(
        provider="anthropic", model_name="claude-sonnet-4-6", display_name="Claude Sonnet 4.6"
    )
    db.add_all([other_model, selected_model])
    await db.commit()
    session = await builder_service.create_session(db, TEST_USER_ID, "Build")
    session.status = builder_service.BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "日报助手",
        "description": "整理每天的日程和提醒。",
        "system_prompt": "请根据用户日程生成简洁日报。",
        "tools": [],
        "middlewares": [],
        "runtime_model_id": str(selected_model.id),
    }
    await db.commit()
    monkeypatch.setattr(builder_project_lifecycle, "schedule", lambda *args: None)

    agent = await builder_service.confirm_build(db, session)

    assert agent is not None
    assert agent.model_id == selected_model.id
    assert agent.llm_credential_id == openai_credential.id


@pytest.mark.asyncio
async def test_phase8_and_confirm_use_builder_system_runtime(db, encrypted, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import selectinload

    from app.agent_runtime.credential_resolution import resolve_llm_api_key_for_agent
    from app.models.agent import Agent
    from app.services import builder_project_lifecycle

    blob, key, fields = encrypted
    db.add(User(id=TEST_USER_ID, name="P0", email="p0@example.test"))
    system_credential = Credential(
        user_id=None,
        name="Builder DeepSeek",
        definition_key="deepseek",
        data_encrypted=blob,
        key_id=key,
        field_keys=fields,
        status="active",
        is_system=True,
    )
    db.add(system_credential)
    await db.flush()
    db.add(
        SystemLlmSetting(
            role="builder",
            credential_id=system_credential.id,
            model_name="deepseek-chat",
        )
    )
    await db.commit()
    session = await builder_service.create_session(db, TEST_USER_ID, "Build")
    session.status = builder_service.BuilderStatus.PREVIEW
    session.draft_config = {
        "name": "日报助手",
        "description": "整理每天的日程和提醒。",
        "system_prompt": "请根据用户日程生成简洁日报。",
        "tools": [],
        "middlewares": [],
    }
    await db.commit()
    monkeypatch.setattr(
        phase8_build, "async_session_factory", async_sessionmaker(db.bind, expire_on_commit=False)
    )

    result = await phase8_build.phase8_propose(
        {"session_id": str(session.id), "draft_config": session.draft_config}
    )

    assert result["runtime_setup_payload"] is None
    assert result["draft_config"]["model_name"] == "deepseek:deepseek-chat"
    assert result["draft_config"]["runtime_model_source"] == "system_builder"

    session.status = builder_service.BuilderStatus.CONFIRMING
    await db.commit()
    monkeypatch.setattr(builder_project_lifecycle, "schedule", lambda *args: None)
    agent = await builder_service.confirm_build(db, session)

    assert agent is not None
    assert agent.model is not None
    assert agent.model.provider == "deepseek"
    assert agent.model.model_name == "deepseek-chat"
    assert agent.llm_credential_id == system_credential.id
    reloaded = (
        await db.execute(
            select(Agent)
            .where(Agent.id == agent.id)
            .options(selectinload(Agent.model), selectinload(Agent.llm_credential))
        )
    ).scalar_one()
    assert await resolve_llm_api_key_for_agent(db, reloaded) == "p0-dummy"


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_first_party_catalog_locale_and_external_content(locale):
    from datetime import datetime

    for seed in DEFAULT_TEMPLATES:
        row = SimpleNamespace(
            **seed, id=uuid.uuid4(), created_at=datetime(2026, 1, 1), recommended_model_id=None
        )
        display = template_display(row, locale)
        assert display.content_key and display.category_key
        assert not HANGUL.search(json.dumps(display.model_dump(mode="json"), ensure_ascii=False))
        external = SimpleNamespace(**{**vars(row), "system_prompt": "외부 사용자 콘텐츠"})
        assert template_display(external, locale).name == row.name
    for item in get_middleware_registry():
        translated = middleware_display(item, locale)
        assert translated["type"] == item["type"] and translated["name"] == item["name"]
        assert not HANGUL.search(json.dumps(translated, ensure_ascii=False))
