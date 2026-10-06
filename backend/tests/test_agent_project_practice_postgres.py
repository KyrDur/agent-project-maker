"""Opt-in m83 roundtrip on an explicitly disposable PostgreSQL database."""

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.agent_project import AgentProject, AgentProjectVersion, utcnow
from tests.test_agent_projects import seed_agent


@pytest.mark.asyncio
async def test_m83_postgres_legacy_roundtrip():
    dsn = os.environ.get("PRACTICE_POSTGRES_URL")
    if not dsn:
        pytest.skip("PRACTICE_POSTGRES_URL must name a disposable practice migration database")
    url = make_url(dsn)
    assert url.drivername == "postgresql+asyncpg"
    assert url.database and url.database.startswith("moldy_e2e_scripted_practice_migration")
    assert url.host in {"localhost", "127.0.0.1"}
    environment = {**os.environ, "DATABASE_URL": dsn}

    def migrate(direction, revision):
        subprocess.run(
            [sys.executable, "-m", "alembic", direction, revision],
            cwd=Path(__file__).parents[1],
            env=environment,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "head")
    migrate("downgrade", "m82_eval_focus_checkpoint")
    engine = create_async_engine(dsn)
    project_id, version_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            user, _, agent = await seed_agent(db, user_id=uuid.uuid4())
            await db.execute(
                insert(cast(Table, AgentProject.__table__)).values(
                    id=project_id,
                    user_id=user.id,
                    agent_id=agent.id,
                    title="Legacy practice",
                    requirements_json={"goal": "Historical goal"},
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            await db.execute(
                insert(cast(Table, AgentProjectVersion.__table__)).values(
                    id=version_id,
                    project_id=project_id,
                    version_number=1,
                    status="original",
                    snapshot_json={"legacy": "unchanged"},
                    created_at=utcnow(),
                )
            )
            await db.execute(
                text(
                    "UPDATE system_llm_settings SET model_name = 'legacy-operator-model' "
                    "WHERE role = 'image'"
                )
            )
            await db.commit()
        migrate("upgrade", "head")
        migrate("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM user_llm_settings")) == 0
            assert (
                await connection.scalar(
                    text("SELECT model_name FROM system_llm_settings WHERE role = 'image'")
                )
                == "legacy-operator-model"
            )
            legacy = (
                (
                    await connection.execute(
                        select(AgentProject.__table__).where(AgentProject.id == project_id)
                    )
                )
                .mappings()
                .one()
            )
            assert legacy["decisions_json"] is None and legacy["completion_json"] is None
            assert legacy["requirements_json"] == {"goal": "Historical goal"}
            version = await connection.scalar(
                select(AgentProjectVersion.snapshot_json).where(
                    AgentProjectVersion.id == version_id
                )
            )
            assert version == {"legacy": "unchanged"}
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="immutable"):
                await connection.execute(
                    text("UPDATE agent_project_versions SET snapshot_json = '{}' WHERE id = :id"),
                    {"id": version_id},
                )
            await connection.rollback()
        migrate("downgrade", "m82_eval_focus_checkpoint")
        migrate("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(
                select(AgentProjectVersion.snapshot_json).where(
                    AgentProjectVersion.id == version_id
                )
            ) == {"legacy": "unchanged"}
    finally:
        await engine.dispose()
