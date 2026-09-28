import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.agent_project import utcnow
from app.schemas.agent_project import EvalRunCreate
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_service as projects
from app.services import agent_project_worker as worker
from tests import test_agent_project_phase2 as phase2

db = phase2.db
setup_project = phase2.setup_project
pytestmark = pytest.mark.asyncio


async def make_run(db, agent):
    dataset = await phase2.dataset(db, agent)
    versions = await projects.list_versions(db, agent.id, phase2.TEST_USER_ID)
    return await evaluation.create_run(
        db,
        agent.id,
        phase2.TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=versions[0].id, eval_set_id=dataset.id),
    )


async def test_cancel_fences_late_result_and_retry_keeps_frozen_inputs(
    db, setup_project, monkeypatch
):
    agent = setup_project
    row = await make_run(db, agent)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def execute(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    task = asyncio.create_task(evaluation.execute_run(row.id, agent.id, phase2.TEST_USER_ID))
    await asyncio.wait_for(started.wait(), timeout=5)
    await evaluation.cancel_run(db, agent.id, phase2.TEST_USER_ID, row.id)
    await asyncio.wait_for(task, timeout=3)
    assert cancelled.is_set()
    await db.refresh(row)
    assert row.status == "failed" and row.error == "evaluation_cancelled"
    assert not row.results_json
    request = uuid.uuid4()
    retry = await evaluation.retry_run(db, agent.id, phase2.TEST_USER_ID, row.id, request)
    replay = await evaluation.retry_run(db, agent.id, phase2.TEST_USER_ID, row.id, request)
    assert retry.id == replay.id and retry.id != row.id
    assert retry.cases_snapshot_json == row.cases_snapshot_json
    assert retry.version_id == row.version_id
    assert retry.comparison_json is not None
    assert retry.comparison_json.get("roles") == (row.comparison_json or {}).get("roles")


async def test_cancel_interrupts_in_flight_judge(db, setup_project, monkeypatch):
    agent = setup_project
    row = await make_run(db, agent)
    row.comparison_json = {"eval_spec": {"metrics": []}}
    await db.commit()
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def execute(*args):
        return {"output": "ok", "tool_calls": []}

    async def judge(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    monkeypatch.setattr("app.services.agent_project_semantic.grade_case", judge)
    task = asyncio.create_task(evaluation.execute_run(row.id, agent.id, phase2.TEST_USER_ID))
    await asyncio.wait_for(started.wait(), timeout=5)
    await evaluation.cancel_run(db, agent.id, phase2.TEST_USER_ID, row.id)
    await asyncio.wait_for(task, timeout=3)
    await db.refresh(row)
    assert cancelled.is_set()
    assert row.status == "failed" and row.error == "evaluation_cancelled"
    assert not row.results_json


async def test_recovery_expires_only_abandoned_leases(db, setup_project):
    row = await make_run(db, setup_project)
    row.status = "running"
    row.lease_id = uuid.uuid4()
    row.lease_expires_at = utcnow() + timedelta(minutes=2)
    await db.commit()
    await worker.recover_expired(db)
    await db.refresh(row)
    assert row.status == "running"
    row.lease_expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    await worker.recover_expired(db)
    await db.refresh(row)
    assert row.status == "failed" and row.error == "evaluation_worker_expired"


async def test_worker_dispatches_persisted_pending_run_after_start(db, setup_project, monkeypatch):
    row = await make_run(db, setup_project)
    monkeypatch.setattr(
        worker, "async_session", async_sessionmaker(db.bind, expire_on_commit=False)
    )

    async def execute(*args):
        return {"output": "ok", "tool_calls": []}

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    instance = worker.EvaluationWorker()
    await instance.start()
    try:
        async with asyncio.timeout(5):
            while True:
                await db.refresh(row)
                if row.status in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)
        assert row.status == "completed"
    finally:
        await instance.stop()
