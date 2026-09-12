from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.agent_project import AgentProjectEvalRun
from app.models.tool import AgentToolLink, Tool
from app.schemas.agent_project import EvalRunCreate, EvalSetWrite, VersionCreate
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_service as projects
from app.services.agent_project_executor import SnapshotExecutionUnavailable, execute_snapshot
from tests import test_agent_projects as phase1

TEST_USER_ID = phase1.TEST_USER_ID
seed_agent = phase1.seed_agent
db = phase1.db
client = phase1.client


@pytest.fixture
async def setup_project(db, monkeypatch):
    _, _, agent = await seed_agent(db)
    await db.commit()
    await projects.create_project(db, agent.id, TEST_USER_ID)
    monkeypatch.setattr(
        evaluation, "async_session", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    return agent


async def dataset(db, agent):
    return await evaluation.write_set(
        db,
        agent.id,
        TEST_USER_ID,
        EvalSetWrite(
            name="Manual",
            cases=[
                {"name": "Greeting", "input": "Hello", "expected": {"exact_answer": "Hello back"}}
            ],
        ),
    )


@pytest.mark.asyncio
async def test_version_creation_unchanged_replay_and_history(client, db, setup_project):
    agent = setup_project
    path = f"/api/agents/{agent.id}/project"
    v1 = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    original = v1.snapshot_json
    body = {"request_id": str(uuid.uuid4())}
    assert (await client.post(f"{path}/versions", json=body)).json()["outcome"] == "unchanged"
    agent.system_prompt = "Version two"
    await db.commit()
    response = await client.post(f"{path}/versions", json=body)
    assert response.status_code == 200
    v2 = response.json()["version"]
    assert v2["version_number"] == 2
    agent.system_prompt = "Version three"
    await db.commit()
    assert (await client.post(f"{path}/versions", json=body)).json()["outcome"] == "replayed"
    third = await projects.create_version(
        db, agent.id, TEST_USER_ID, VersionCreate(request_id=uuid.uuid4())
    )
    assert third.version.version_number == 3
    assert (await projects.get_version(db, agent.id, TEST_USER_ID, v1.id)).snapshot_json == original
    assert (await client.get(f"{path}/versions/{v2['id']}")).json()["snapshot_json"]["agent"][
        "system_prompt"
    ] == "Version two"
    comparison = (
        await client.get(f"{path}/compare", params={"left": str(v1.id), "right": v2["id"]})
    ).json()
    assert comparison["changes"] == [
        {"field": "system_prompt", "before": "Be helpful", "after": "Version two"}
    ]


@pytest.mark.asyncio
async def test_removed_tool_preserves_historical_configuration(db, setup_project):
    agent = setup_project
    tool = Tool(user_id=TEST_USER_ID, definition_key="test", name="Pinned", parameters={"limit": 2})
    db.add(tool)
    await db.flush()
    link = AgentToolLink(agent_id=agent.id, tool_id=tool.id)
    db.add(link)
    await db.commit()
    v2 = await projects.create_version(
        db, agent.id, TEST_USER_ID, VersionCreate(request_id=uuid.uuid4())
    )
    await db.delete(link)
    await db.commit()
    v3 = await projects.create_version(
        db, agent.id, TEST_USER_ID, VersionCreate(request_id=uuid.uuid4())
    )
    comparison = await evaluation.compare_versions(
        db, agent.id, TEST_USER_ID, v2.version.id, v3.version.id
    )
    assert comparison["changes"][0]["removed"] == [str(tool.id)]
    assert v2.version.snapshot_json["agent"]["tool_links"][0]["parameters"] == {"limit": 2}


@pytest.mark.asyncio
async def test_dataset_management_validation_and_ownership(client, db, setup_project):
    agent = setup_project
    path = f"/api/agents/{agent.id}/project/eval-sets"
    body = {"name": "Manual", "cases": [{"name": "One", "input": "Hi"}]}
    created = await client.post(path, json=body)
    assert created.status_code == 201
    row = created.json()
    assert row["cases_json"][0]["project_id"] == row["project_id"]
    assert row["cases_json"][0]["created_at"]
    body["cases"][0]["enabled"] = False
    assert (await client.put(f"{path}/{row['id']}", json=body)).json()["cases_json"][0][
        "enabled"
    ] is False
    assert (await client.get(path)).status_code == 200
    _, _, other = await seed_agent(db, user_id=uuid.uuid4())
    await db.commit()
    assert (await client.get(f"/api/agents/{other.id}/project/eval-sets")).status_code == 404
    assert (await client.delete(f"{path}/{row['id']}")).status_code == 204
    assert (await client.get(path)).json() == []
    assert (await client.post(path, json={"name": "", "cases": []})).status_code == 422


@pytest.mark.asyncio
async def test_run_freezes_version_and_cases_and_claims_once(db, setup_project, monkeypatch):
    agent = setup_project
    cases = await dataset(db, agent)
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    body = EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=cases.id)
    run = await evaluation.create_run(db, agent.id, TEST_USER_ID, body)
    assert (await evaluation.create_run(db, agent.id, TEST_USER_ID, body)).id == run.id
    agent.system_prompt = "Live edit must not execute"
    cases.cases_json = []
    await db.commit()
    seen = []

    async def execute(_db, snapshot, case, _user):
        seen.append((snapshot["agent"]["system_prompt"], case["input"]))
        return {"output": "Hello back", "tool_calls": [], "handoffs": []}

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    result = await evaluation.get_run(db, agent.id, TEST_USER_ID, run.id)
    assert seen == [("Be helpful", "Hello")]
    assert result.status == "completed"
    assert result.metrics_json["passed"] == 1
    assert result.results_json[0]["output"] == "Hello back"
    assert result.started_at and result.completed_at
    assert result.version_id == version.id
    comparison = await evaluation.compare_versions(
        db, agent.id, TEST_USER_ID, version.id, version.id
    )
    assert comparison["same_dataset"] is True


@pytest.mark.asyncio
async def test_failed_execution_is_persisted_without_raw_exception(db, setup_project, monkeypatch):
    agent = setup_project
    cases = await dataset(db, agent)
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    run = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=cases.id),
    )

    async def failed(*_args):
        raise RuntimeError("private-provider-credential-value")

    monkeypatch.setattr(evaluation, "execute_snapshot", failed)
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    result = await evaluation.get_run(db, agent.id, TEST_USER_ID, run.id)
    assert result.status == "failed"
    assert result.metrics_json["errored"] == 1
    assert "private-provider" not in str(result.results_json)


@pytest.mark.asyncio
async def test_run_api_and_cross_project_boundaries(client, db, setup_project, monkeypatch):
    agent = setup_project
    cases = await dataset(db, agent)
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]

    async def unavailable(*_args):
        raise SnapshotExecutionUnavailable("runtime_platform_unavailable")

    monkeypatch.setattr(evaluation, "execute_snapshot", unavailable)
    path = f"/api/agents/{agent.id}/project"
    body = {
        "request_id": str(uuid.uuid4()),
        "version_id": str(version.id),
        "eval_set_id": str(cases.id),
    }
    response = await client.post(f"{path}/eval-runs", json=body)
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert (await client.get(f"{path}/eval-runs/{run_id}")).json()["status"] == "failed"
    assert len((await client.get(f"{path}/eval-runs")).json()) == 1
    _, _, other = await seed_agent(db)
    await db.commit()
    await projects.create_project(db, other.id, TEST_USER_ID)
    other_path = f"/api/agents/{other.id}/project"
    assert (await client.get(f"{other_path}/eval-runs/{run_id}")).status_code == 404
    assert (await client.post(f"{other_path}/eval-runs", json=body)).status_code == 404
    assert (
        await client.put(f"{other_path}/eval-sets/{cases.id}", json={"name": "Bad", "cases": []})
    ).status_code == 404
    assert (
        await client.get(
            f"{other_path}/compare", params={"left": str(version.id), "right": str(version.id)}
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_concurrent_version_and_run_submission(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        _, _, agent = await seed_agent(session)
        await session.commit()
        await projects.create_project(session, agent.id, TEST_USER_ID)
        cases = await dataset(session, agent)
        agent.system_prompt = "V2"
        await session.commit()
    request = VersionCreate(request_id=uuid.uuid4())

    async def create():
        async with factory() as session:
            return await projects.create_version(session, agent.id, TEST_USER_ID, request)

    versions = await asyncio.gather(create(), create())
    assert {version.version.version_number for version in versions} == {2}
    assert {version.outcome for version in versions} == {"created", "replayed"}
    request_run = EvalRunCreate(
        request_id=uuid.uuid4(), version_id=versions[0].version.id, eval_set_id=cases.id
    )

    async def submit():
        async with factory() as session:
            return await evaluation.create_run(session, agent.id, TEST_USER_ID, request_run)

    runs = await asyncio.gather(submit(), submit())
    assert runs[0].id == runs[1].id
    await engine.dispose()


@pytest.mark.parametrize(
    "field",
    [
        "tool_links",
        "skill_links",
        "mcp_tool_links",
        "sub_agent_links",
        "middleware_configs",
        "model_fallback_list",
    ],
)
@pytest.mark.asyncio
async def test_executor_rejects_unpinned_capabilities(db, field):
    with pytest.raises(SnapshotExecutionUnavailable, match="snapshot_capabilities_not_supported"):
        await execute_snapshot(
            db,
            {"schema_version": 1, "agent": {"model": {"id": "model"}, field: [{}]}},
            {},
            TEST_USER_ID,
        )


def test_structural_scoring_does_not_invent_semantic_quality():
    checks = evaluation.score_case(
        {
            "expected": {
                "answer": "For manual review",
                "required_tools": ["search"],
                "forbidden_tools": ["delete"],
                "handoff": "worker",
            }
        },
        {"output": "Answer", "tool_calls": [{"name": "search"}], "handoffs": ["worker"]},
    )
    assert all(check["passed"] for check in checks)
    assert not any(check["kind"] == "semantic" for check in checks)


def test_m79_migration_preserves_v1_and_constraints():
    migrations = []
    for name in ("m78_agent_projects", "m79_project_evaluation"):
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).parents[1] / f"alembic/versions/{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrations.append(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        for table in ("users", "agents", "builder_sessions"):
            connection.execute(sa.text(f"CREATE TABLE {table} (id CHAR(32) PRIMARY KEY)"))
        migrations[0].upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO agent_project_versions "
                "(id, project_id, version_number, status, snapshot_json, created_at) "
                "VALUES ('v1', 'p1', 1, 'original', '{}', CURRENT_TIMESTAMP)"
            )
        )
        migrations[1].upgrade()
        assert (
            connection.scalar(sa.text("SELECT snapshot_json FROM agent_project_versions")) == "{}"
        )
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            connection.execute(sa.text("UPDATE agent_project_versions SET snapshot_json = '[]'"))
        assert "uq_project_eval_run_request" in {
            c["name"]
            for c in sa.inspect(connection).get_unique_constraints("agent_project_eval_runs")
        }
        migrations[1].downgrade()
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            connection.execute(sa.text("UPDATE agent_project_versions SET snapshot_json = '[]'"))
        migrations[0].downgrade()
    engine.dispose()


@pytest.mark.asyncio
async def test_adapter_uses_snapshot_and_scrubs_resolved_secret(
    db, setup_project, monkeypatch, caplog
):
    from langchain_core.messages import AIMessage

    agent = setup_project
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    agent.system_prompt = "Current prompt must not execute"
    await db.commit()
    secret = 'private"key\\with-special-characters'
    calls = []

    class Graph:
        async def ainvoke(self, payload, options):
            assert payload["messages"][-1]["content"] == "Hi"
            assert options["callbacks"] == []
            return {
                "messages": [
                    AIMessage(
                        content=f"Answer {secret}",
                        tool_calls=[
                            {"id": "call1", "name": "write_todos", "args": {"private": secret}}
                        ],
                    )
                ]
            }

    def build(model, tools, prompt, **kwargs):
        calls.append(prompt)
        assert tools == []
        assert kwargs["checkpointer"] is None
        assert kwargs["store"] is None
        assert kwargs["memory"] is None
        return Graph()

    async def resolve(*_args):
        return secret

    replacements = {
        "app.agent_runtime.runtime_component_builder": {"build_agent": build},
        "app.agent_runtime.model_factory": {
            "create_chat_model": lambda *_args, **_kwargs: object()
        },
        "app.agent_runtime.credential_resolution": {"resolve_llm_api_key_for_agent": resolve},
    }
    for name, attributes in replacements.items():
        module = ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    result = await execute_snapshot(db, version.snapshot_json, {"input": "Hi"}, TEST_USER_ID)
    assert calls == ["Be helpful"]
    assert result["output"] == "Answer <redacted>"
    assert result["tool_calls"] == [{"name": "write_todos"}]
    assert secret not in str(result)
    assert secret not in caplog.text
    assert not db.new
    await db.refresh(agent)
    assert agent.system_prompt == "Current prompt must not execute"

    async def keyless(*_args):
        return None

    monkeypatch.setattr(
        sys.modules["app.agent_runtime.credential_resolution"],
        "resolve_llm_api_key_for_agent",
        keyless,
    )
    with pytest.raises(SnapshotExecutionUnavailable, match="snapshot_credential_unavailable"):
        await execute_snapshot(db, version.snapshot_json, {"input": "Hi"}, TEST_USER_ID)


@pytest.mark.asyncio
async def test_invalid_request_does_not_echo_sensitive_input(client, setup_project):
    response = await client.post(
        f"/api/agents/{setup_project.id}/project/eval-sets",
        json={"name": "Cases", "cases": [{"name": "Missing input", "secret": "must-not-echo"}]},
    )
    assert response.status_code == 422
    assert "must-not-echo" not in response.text


@pytest.mark.asyncio
async def test_database_rejects_cross_project_run_binding(db, setup_project):
    await db.execute(sa.text("PRAGMA foreign_keys=ON"))
    assert await db.scalar(sa.text("PRAGMA foreign_keys")) == 1
    agent = setup_project
    cases = await dataset(db, agent)
    _, _, other = await seed_agent(db)
    await db.commit()
    await projects.create_project(db, other.id, TEST_USER_ID)
    other_version = (await projects.list_versions(db, other.id, TEST_USER_ID))[0]
    row = AgentProjectEvalRun(
        project_id=cases.project_id,
        version_id=other_version.id,
        eval_set_id=cases.id,
        status="pending",
    )
    db.add(row)
    with pytest.raises(sa.exc.IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_mutations_require_csrf_and_authentication(db, setup_project, monkeypatch):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import CurrentUser, get_current_user, get_db
    from app.exception_handlers import register_exception_handlers
    from app.routers.agent_projects import router
    from app.services import audit_service

    monkeypatch.setattr(audit_service, "record_event_best_effort", AsyncMock())
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    path = f"/api/agents/{setup_project.id}/project/versions"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.post(path, json={"request_id": str(uuid.uuid4())})).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=TEST_USER_ID, email="test@test.com", name="Test"
        )
        assert (await http.post(path, json={"request_id": str(uuid.uuid4())})).status_code == 403


@pytest.mark.asyncio
async def test_case_timeout_marks_run_failed(db, setup_project, monkeypatch):
    agent = setup_project
    cases = await dataset(db, agent)
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    row = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=cases.id),
    )

    async def timeout(*_args):
        raise TimeoutError

    monkeypatch.setattr(evaluation, "execute_snapshot", timeout)
    await evaluation.execute_run(row.id, agent.id, TEST_USER_ID)
    row = await evaluation.get_run(db, agent.id, TEST_USER_ID, row.id)
    assert row.status == "failed"
    assert row.results_json[0]["error"] == "evaluation_timeout"


@pytest.mark.asyncio
async def test_stale_run_reconciliation_is_not_a_get_mutation(db, setup_project):
    from app.models.agent_project import utcnow

    agent = setup_project
    cases = await dataset(db, agent)
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    request = EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=cases.id)
    row = await evaluation.create_run(db, agent.id, TEST_USER_ID, request)
    row.created_at = utcnow() - timedelta(minutes=16)
    await db.commit()
    assert (await evaluation.get_run(db, agent.id, TEST_USER_ID, row.id)).status == "pending"
    retried = await evaluation.create_run(db, agent.id, TEST_USER_ID, request)
    assert retried.id == row.id
    assert retried.status == "failed"
    assert retried.error == "evaluation_worker_expired"
