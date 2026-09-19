"""Recoverable Builder -> V1 -> fixed benchmark -> baseline orchestration.

Progress uses existing project JSON. Dataset/request IDs are deterministic.
A PostgreSQL session advisory lock survives service-level commits and releases
on worker disconnect. Page reconnects can resume without duplicating records.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, engine
from app.models.agent_project import AgentProject
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
_local_locks: dict[uuid.UUID, asyncio.Lock] = {}


@asynccontextmanager
async def exclusive(agent_id: uuid.UUID) -> AsyncIterator[bool]:
    if engine.dialect.name != "postgresql":
        async with _local_locks.setdefault(agent_id, asyncio.Lock()):
            yield True
        return
    key = int.from_bytes(agent_id.bytes[:8], "big", signed=True)
    async with engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


async def progress(
    db: AsyncSession,
    project: AgentProject,
    stage: str,
    *,
    error: str | None = None,
    run_id: uuid.UUID | None = None,
) -> None:
    await db.refresh(project, ["requirements_json"])
    project.requirements_json = {
        **(project.requirements_json or {}),
        "bootstrap": {"stage": stage, "error": error, "run_id": str(run_id) if run_id else None},
    }
    await db.commit()


async def bootstrap(agent_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with exclusive(agent_id) as acquired:
        if not acquired:
            return
        async with async_session() as db:
            project = await projects.create_project(db, agent_id, user_id)
            if not project.builder_session_id:
                return  # Automatic baseline is limited to Builder-origin projects.
            if (project.requirements_json or {}).get("bootstrap", {}).get("stage") == "results":
                return
            stage = "v1"
            try:
                versions = await projects.list_versions(db, agent_id, user_id)
                v1 = next(v for v in versions if v.version_number == 1)
                stage = "plan"
                await progress(db, project, stage)
                if not project.eval_spec_json:
                    await semantic.generate(db, agent_id, user_id, v1.id)
                stage = "focus"
                await progress(db, project, stage)
                # Final product flow pauses here: the user must choose evaluation
                # focus areas before the formal 20-case benchmark is generated.
                return
            except Exception as exc:
                await db.rollback()
                logger.exception("Builder project bootstrap failed at %s", stage)
                # Stable code only; provider responses and credentials never enter progress.
                code = getattr(exc, "code", "builder_baseline_unavailable")
                await progress(db, project, stage, error=code)


def schedule(agent_id: uuid.UUID, user_id: uuid.UUID) -> None:
    task = asyncio.create_task(bootstrap(agent_id, user_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
