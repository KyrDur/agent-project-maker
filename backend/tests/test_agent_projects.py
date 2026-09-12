from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.exception_handlers import register_exception_handlers
from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent import Agent
from app.models.agent_project import AgentProject, AgentProjectVersion
from app.models.builder_session import BuilderSession
from app.models.credential import Credential
from app.models.mcp_server import McpServer
from app.models.mcp_tool import AgentMcpToolLink, McpTool
from app.models.model import Model
from app.models.skill import AgentSkillLink, Skill
from app.models.tool import AgentToolLink, Tool
from app.models.user import User
from app.routers.agent_projects import router
from app.services import agent_project_service as service

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# Isolated router fixtures also allow --noconftest on Windows, where the full
# application's runtime imports fcntl. No runtime behavior is stubbed or changed.
@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db):
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=TEST_USER_ID, email="test@test.com", name="Test"
    )
    app.dependency_overrides[verify_csrf] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def seed_agent(db, *, user_id=TEST_USER_ID, **kwargs):
    user = await db.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=f"{user_id}@test.com", name="Test")
        db.add(user)
    model = Model(provider="openai", model_name="test", display_name="Test")
    db.add(model)
    await db.flush()
    agent = Agent(
        user_id=user_id, name="Test Agent", system_prompt="Be helpful", model_id=model.id, **kwargs
    )
    db.add(agent)
    await db.flush()
    return user, model, agent


@pytest.mark.asyncio
async def test_create_and_retrieve_project_and_original_version(client, db):
    _, model, agent = await seed_agent(db, model_params={"temperature": 0.2, "max_tokens": 500})
    session = BuilderSession(user_id=TEST_USER_ID, agent_id=agent.id, user_request="Help me")
    db.add(session)
    await db.commit()
    path = f"/api/agents/{agent.id}/project"
    before = await client.get(path)
    assert before.status_code == 200
    assert before.json() is None
    assert (await client.get(f"{path}/versions")).status_code == 404
    created = await client.post(f"{path}/create")
    assert created.status_code == 200
    project = created.json()
    assert project["user_id"] == str(TEST_USER_ID)
    assert project["agent_id"] == str(agent.id)
    assert project["builder_session_id"] == str(session.id)
    assert project["title"] == agent.name
    assert project["eval_spec_json"] is None
    assert (await client.get(path)).json() == project
    versions = (await client.get(f"{path}/versions")).json()
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["status"] == "original"
    assert "snapshot_json" not in versions[0]
    version = (await client.get(f"{path}/versions/{versions[0]['id']}")).json()
    snapshot = version["snapshot_json"]
    assert snapshot["agent"]["system_prompt"] == agent.system_prompt
    assert snapshot["agent"]["model_id"] == str(model.id)
    assert snapshot["agent"]["model"]["model_name"] == model.model_name
    assert snapshot["agent"]["model_params"] == {"temperature": 0.2, "max_tokens": 500}
    assert version["config_hash"] == canonical_json_hash(snapshot)
    agent.system_prompt = "Changed after original snapshot"
    await db.commit()
    assert (await client.post(f"{path}/create")).json()["id"] == project["id"]
    unchanged = (await client.get(f"{path}/versions/{version['id']}")).json()
    assert unchanged == version
    assert len((await client.get(f"{path}/versions")).json()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden", [False, True])
async def test_project_rejects_other_owner_and_hidden_runtime(client, db, hidden):
    _, _, agent = await seed_agent(
        db,
        user_id=TEST_USER_ID if hidden else uuid.uuid4(),
        runtime_profile="skill_builder" if hidden else "standard",
    )
    await db.commit()
    path = f"/api/agents/{agent.id}/project"
    assert (await client.post(f"{path}/create")).status_code == 404
    assert (await client.get(path)).status_code == 404
    assert (await client.get(f"{path}/versions")).status_code == 404
    assert (await client.get(f"{path}/versions/{uuid.uuid4()}")).status_code == 404
    assert (await db.scalars(select(AgentProject))).all() == []


@pytest.mark.asyncio
async def test_version_cannot_be_read_through_another_project(client, db):
    _, _, first = await seed_agent(db)
    _, _, second = await seed_agent(db)
    await db.commit()
    for agent in (first, second):
        await client.post(f"/api/agents/{agent.id}/project/create")
    version = (await client.get(f"/api/agents/{first.id}/project/versions")).json()[0]
    response = await client.get(f"/api/agents/{second.id}/project/versions/{version['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_snapshot_links_and_secrets(client, db):
    _, model, agent = await seed_agent(db)
    credential = Credential(
        user_id=TEST_USER_ID,
        definition_key="openai",
        name="Private",
        data_encrypted="never-copy-encrypted-credential",
        key_id="test",
    )
    db.add(credential)
    await db.flush()
    agent.llm_credential_id = credential.id
    model.default_credential_id = credential.id
    tool = Tool(
        user_id=TEST_USER_ID,
        definition_key="test",
        name="Tool",
        credential_id=credential.id,
        parameters={
            "limit": 5,
            "api_key": "never-copy-api-key",
            "nested": {"Authorization": "private"},
        },
    )
    revision_id = uuid.uuid4()
    skill = Skill(user_id=TEST_USER_ID, name="Skill", slug="skill", current_revision_id=revision_id)
    server = McpServer(
        user_id=TEST_USER_ID,
        name="MCP",
        transport="stdio",
        command="test",
        args=["--token", "never-copy-oauth"],
        headers={"Authorization": "never-copy-header"},
        env_vars={"SECRET": "never-copy-env"},
        credential_id=credential.id,
    )
    db.add_all([tool, skill, server])
    await db.flush()
    mcp_tool = McpTool(server_id=server.id, name="lookup", input_schema={"type": "object"})
    db.add(mcp_tool)
    await db.flush()
    db.add_all(
        [
            AgentToolLink(agent_id=agent.id, tool_id=tool.id),
            AgentSkillLink(agent_id=agent.id, skill_id=skill.id, config={"limit": 3}),
            AgentMcpToolLink(agent_id=agent.id, mcp_tool_id=mcp_tool.id),
        ]
    )
    await db.commit()
    path = f"/api/agents/{agent.id}/project"
    assert (await client.post(f"{path}/create")).status_code == 200
    version = (await client.get(f"{path}/versions")).json()[0]
    snapshot = (await client.get(f"{path}/versions/{version['id']}")).json()["snapshot_json"]
    config = snapshot["agent"]
    assert config["llm_credential_id"] == str(credential.id)
    assert config["tool_links"][0]["tool_id"] == str(tool.id)
    assert config["tool_links"][0]["parameters"]["limit"] == 5
    assert config["tool_links"][0]["parameters"]["api_key"] == "<redacted>"
    assert config["skill_links"][0]["current_revision_id"] == str(revision_id)
    assert config["skill_links"][0]["config"] == {"limit": 3}
    assert config["mcp_tool_links"][0]["server_id"] == str(server.id)
    assert "never-copy" not in json.dumps(snapshot)
    assert "data_encrypted" not in json.dumps(snapshot)


@pytest.mark.asyncio
async def test_version_is_immutable(db):
    _, _, agent = await seed_agent(db)
    await db.commit()
    project = await service.create_project(db, agent.id, TEST_USER_ID)
    version = await db.scalar(
        select(AgentProjectVersion).where(AgentProjectVersion.project_id == project.id)
    )
    version.snapshot_json = {"changed": True}
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_eval_set_storage_and_freezing(db):
    _, _, agent = await seed_agent(db)
    await db.commit()
    await service.create_project(db, agent.id, TEST_USER_ID)
    row = await service.save_eval_set(db, agent.id, TEST_USER_ID, name="Cases", cases_json=[])
    assert [r.id for r in await service.list_eval_sets(db, agent.id, TEST_USER_ID)] == [row.id]
    await service.delete_eval_set(db, agent.id, TEST_USER_ID, row.id)
    assert await service.list_eval_sets(db, agent.id, TEST_USER_ID) == []
    row = await service.save_eval_set(db, agent.id, TEST_USER_ID, name="Cases", cases_json=[])
    await service.save_eval_set(
        db,
        agent.id,
        TEST_USER_ID,
        eval_set_id=row.id,
        name="Frozen",
        cases_json=[{"input": "Hello"}],
        frozen=True,
    )
    with pytest.raises(AppError, match="frozen"):
        await service.delete_eval_set(db, agent.id, TEST_USER_ID, row.id)


def test_migration_round_trip_and_sql_immutability():
    path = Path(__file__).parents[1] / "alembic/versions/m78_agent_projects.py"
    spec = importlib.util.spec_from_file_location("agent_project_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
        assert len(inspect(connection).get_table_names()) == 4
        connection.execute(
            text("""
                INSERT INTO agent_project_versions
                (id, project_id, version_number, status, snapshot_json, created_at)
                VALUES ('version', 'project', 1, 'original', '{}', CURRENT_TIMESTAMP)
            """)
        )
        with pytest.raises(IntegrityError, match="immutable"):
            connection.execute(text("UPDATE agent_project_versions SET snapshot_json = '{}'"))
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()
