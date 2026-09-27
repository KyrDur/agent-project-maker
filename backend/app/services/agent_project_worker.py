"""Database-backed evaluation dispatch with bounded concurrency and expired lease recovery."""

import asyncio
import contextlib
import logging

from sqlalchemy import select, update

from app.database import async_session
from app.models.agent_project import AgentProject, AgentProjectEvalRun, utcnow

logger = logging.getLogger(__name__)


async def recover_expired(db) -> None:
    await db.execute(
        update(AgentProjectEvalRun)
        .where(
            AgentProjectEvalRun.status == "running",
            (AgentProjectEvalRun.lease_expires_at < utcnow())
            | AgentProjectEvalRun.lease_expires_at.is_(None),
        )
        .values(
            status="failed",
            error="evaluation_worker_expired",
            completed_at=utcnow(),
            lease_id=None,
            lease_expires_at=None,
        )
    )
    await db.commit()


class EvaluationWorker:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name="project-evaluation-worker")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def run(self) -> None:
        from app.services.agent_project_evaluation import execute_run

        while True:
            try:
                async with async_session() as db:
                    await recover_expired(db)
                    row = (
                        await db.execute(
                            select(
                                AgentProjectEvalRun.id, AgentProject.agent_id, AgentProject.user_id
                            )
                            .join(AgentProject, AgentProject.id == AgentProjectEvalRun.project_id)
                            .where(AgentProjectEvalRun.status == "pending")
                            .order_by(AgentProjectEvalRun.created_at)
                            .limit(1)
                        )
                    ).first()
                if row:
                    await execute_run(*row)
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Project evaluation dispatch failed; retrying after backoff")
                await asyncio.sleep(5)


evaluation_worker = EvaluationWorker()
