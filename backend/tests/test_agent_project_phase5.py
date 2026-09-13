"""Stored controlled experiments drive every portfolio claim. No live provider."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from copy import deepcopy

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_db
from app.exception_handlers import register_exception_handlers
from app.exceptions import AppError
from app.routers.agent_projects import public_router
from app.services import agent_project_portfolio as portfolio
from app.services.agent_project_portfolio_export import export_zip
from tests import test_agent_project_phase4 as phase4

db = phase4.db
client = phase4.client
experiment = phase4.experiment
USER = phase4.TEST_USER_ID


@pytest.fixture
async def completed(db, experiment, monkeypatch):
    ex = experiment
    monkeypatch.setattr(phase4.optimization, "json_call", phase4.controlled_optimizer)
    await phase4.optimization.start(db, ex.agent.id, USER, ex.run.id, uuid.uuid4())
    await phase4.optimization.execute_optimization(ex.agent.id, USER, ex.run.id)
    await db.refresh(ex.project)
    assert ex.project.report_json["optimization"]["state"] == "completed"
    return ex


@pytest.mark.asyncio
async def test_real_report_best_rejected_journey_and_limitations(client, db, completed):
    ex = completed
    response = await client.post(f"/api/agents/{ex.agent.id}/project/report/generate")
    assert response.status_code == 200
    report = response.json()
    data = report["evidence"]
    assert len(report["sections"]) == 7
    assert data["results"]["best_version"] == 2
    assert data["results"]["baseline"]["pass_rate"] == 0.75
    assert data["results"]["best"]["pass_rate"] == 0.9
    assert data["results"]["metric_deltas"]["task_completion"] == pytest.approx(0.105)
    assert [v["decision"] for v in data["versions"]] == ["original", "accepted", "rejected"]
    assert [v["evaluation"]["pass_rate"] for v in data["versions"]] == [0.75, 0.9, 0.85]
    assert data["versions"][1]["comparison"]["fixed_cases"] == 4
    assert data["versions"][1]["comparison"]["regressed_cases"] == 1
    assert data["bad_cases"]["analyzed_count"] == 5
    assert data["bad_cases"]["groups"][0]["root_cause"]
    assert "mock" in report["markdown"] and "production" in report["markdown"]
    assert "unverified" in report["markdown"]
    await db.refresh(ex.project)
    assert ex.project.report_json["portfolio_report"]["evidence_hash"] == report["evidence_hash"]
    assert ex.project.report_json["optimization"]["best_version_id"]
    # Live edits and current rubric edits must not overwrite measured evidence.
    ex.project.eval_spec_json = {"invented": 99}
    await db.commit()
    again = await portfolio.report(db, ex.agent.id, USER)
    assert again["evidence"]["eval_spec"] == report["evidence"]["eval_spec"]


@pytest.mark.asyncio
async def test_unavailable_never_fabricated(db, experiment):
    ex = experiment
    ex.run.status, ex.run.completed_at = "running", None
    await db.commit()
    report = await portfolio.report(db, ex.agent.id, USER)
    assert report["evidence"]["results"] == {
        "best_version": None,
        "baseline": None,
        "best": None,
        "metric_deltas": {},
    }
    assert "Unavailable" in report["markdown"]
    assert "90.0%" not in report["markdown"]
    resume = await portfolio.resume(db, ex.agent.id, USER, "product")
    assert len(resume["bullets"]) == 1
    assert "%" not in " ".join(resume["bullets"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("style", "start"),
    [
        ("ai_product", "Developed an evidence-based"),
        ("product", "Documented an Agent project's"),
        ("engineering", "Documented immutable"),
    ],
)
async def test_resume_styles_only_real_numbers(client, db, completed, style, start):
    path = f"/api/agents/{completed.agent.id}/project/resume/generate"
    response = await client.post(path, json={"style": style})
    assert response.status_code == 200
    data = response.json()
    assert data["style"] == style and 1 <= len(data["bullets"]) <= 3
    assert data["bullets"][0].startswith(start)
    text = " ".join(data["bullets"])
    assert "20-case" in text and "75.0%" in text and "90.0%" in text
    assert "85.0%" not in text and "revenue" not in text
    assert "unvalidated" in text
    assert (await client.post(path, json={"style": style})).json() == data
    assert (await client.post(path, json={"style": style, "metrics": 100})).status_code == 422


@pytest.mark.asyncio
async def test_share_public_no_sources_revoke_and_fixed_snapshot(client, db, completed):
    ex = completed
    ex.run.results_json = [
        {
            **r,
            "tool_calls": [{"name": "search", "result": "PRIVATE_FEISHU_CONTENT"}],
            "thinking": "HIDDEN_CHAIN",
        }
        for r in ex.run.results_json
    ]
    await db.commit()
    app = FastAPI()
    app.include_router(public_router)
    register_exception_handlers(app)

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    path = f"/api/agents/{ex.agent.id}/project/share"
    shared = (await client.post(path)).json()
    assert (await client.post(path)).json() == shared
    public_path = shared["path"].replace("/shared/projects/", "/api/project-shares/")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as public:
        response = await public.get(public_path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "PRIVATE_FEISHU_CONTENT" not in response.text
        assert "HIDDEN_CHAIN" not in response.text
        assert "credential" not in response.text.lower()
        assert "root_cause" not in response.text
        original = response.json()
        ex.project.title = "Updated private project"
        await db.commit()
        assert (await public.get(public_path)).json() == original
        assert (await client.delete(path)).json() == {"path": None}
        assert (await public.get(public_path)).status_code == 404
        recreated = (await client.post(path)).json()
        assert recreated["path"] != shared["path"]
        assert (await public.get(public_path)).status_code == 404
        assert (await public.post(public_path)).status_code == 405


@pytest.mark.asyncio
async def test_export_structure_frozen_skills_results_and_no_live_mutation(db, completed):
    ex = completed
    live = ex.agent.system_prompt
    blob = await export_zip(db, ex.agent.id, USER)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = set(archive.namelist())
        assert {
            f"agent-project/{name}"
            for name in [
                "README.md",
                "agent.json",
                "instructions.md",
                "eval_spec.json",
                "eval_results.json",
                "report/project_report.md",
                "skills/README.md",
                "skills/skill-1/SKILL.md",
                "versions/v1/agent.json",
                "versions/v2/diff.json",
                "versions/v3/agent.json",
            ]
        } <= names
        readme = archive.read("agent-project/README.md").decode()
        assert "75.0%" in readme and "90.0%" in readme and "85.0%" in readme
        assert "## Limitations" in readme and "## Tools & Skills" in readme
        instructions = archive.read("agent-project/instructions.md").decode()
        assert "Retrieve sources before answering." in instructions
        assert "Verify every requested section" not in instructions  # V3 rejected
        exported = json.loads(archive.read("agent-project/agent.json"))
        assert "model" in exported and "llm_credential_id" not in exported
        assert (
            "Separate facts from assumptions."
            in archive.read("agent-project/skills/skill-1/SKILL.md").decode()
        )
        assert all(".." not in name and not name.startswith("/") for name in names)
    await db.refresh(ex.agent)
    assert ex.agent.system_prompt == live


@pytest.mark.asyncio
async def test_owner_scope_and_export_endpoint(client, db, experiment):
    ex = experiment
    with pytest.raises(AppError):
        await portfolio.report(db, ex.agent.id, uuid.uuid4())
    with pytest.raises(AppError):
        await portfolio.share(db, ex.agent.id, uuid.uuid4())
    response = await client.get(f"/api/agents/{ex.agent.id}/project/export")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert zipfile.is_zipfile(io.BytesIO(response.content))


@pytest.mark.asyncio
async def test_secrets_paths_hidden_data_and_missing_skills(db, experiment, monkeypatch):
    ex = experiment
    # Frozen snapshot fixture can be replaced before persistence in production; here simulate
    # historical snapshots through the read boundary without defeating the immutable DB trigger.
    versions = await phase4.projects.list_versions(db, ex.agent.id, USER)
    saved = deepcopy(versions[0].snapshot_json)
    config = saved["agent"]
    config.update(
        system_prompt="Use sk-" + "x" * 40 + " at D:\\private\\config.txt",
        credential_id="secret-id",
        headers={"Authorization": "Bearer PRIVATE"},
    )
    config["skill_links"] = [{"slug": "missing", "storage_path": "D:\\private\\skills"}]
    safe = portfolio.architecture(saved, text=True)
    text = json.dumps(safe)
    assert "x" * 40 not in text and "config.txt" not in text and "secret-id" not in text
    assert "storage_path" not in text and "credential" not in text
    assert safe["skills"][0]["historical_content_available"] is False
    assert portfolio.sanitize({"thinking": "hidden", "api_key": "PRIVATE"}) == {}
    assert "hidden" not in portfolio.sanitize("<think>hidden</think>Visible")
    assert "PRIVATE_DATA" not in portfolio.remove_sources("Copied PRIVATE_DATA", ["PRIVATE_DATA"])
    # Select actual V1 as baseline best but omit missing Skill text through allowlist projection.
    ex.project.report_json = {
        "optimization": {
            "best_run_id": str(ex.run.id),
            "best_version_id": str(ex.version.id),
            "root_run_id": str(ex.run.id),
            "rounds": [],
        }
    }
    await db.commit()
    original = portfolio.architecture

    def missing_architecture(snapshot, *, text=False):
        return original(saved, text=text)

    monkeypatch.setattr(portfolio, "architecture", missing_architecture)
    report = await portfolio.report(db, ex.agent.id, USER)
    assert "Historical Skill content is unavailable" in report["markdown"]
    assert "x" * 40 not in json.dumps(report) and "secret-id" not in json.dumps(report)
    shared = await portfolio.share(db, ex.agent.id, USER)
    public = await portfolio.public_share(db, ex.project.id, shared["path"].split("/")[-1])
    assert "x" * 40 not in json.dumps(public) and "secret-id" not in json.dumps(public)
    with zipfile.ZipFile(io.BytesIO(await export_zip(db, ex.agent.id, USER))) as archive:
        all_text = "\n".join(archive.read(name).decode() for name in archive.namelist())
        assert "x" * 40 not in all_text and "secret-id" not in all_text
        assert (
            "Historical content unavailable"
            in archive.read("agent-project/skills/README.md").decode()
        )


@pytest.mark.asyncio
async def test_report_cache_is_not_trusted_as_evidence(db, experiment):
    ex = experiment
    ex.project.report_json = {"portfolio_report": {"markdown": "100% accuracy; 100000 users"}}
    await db.commit()
    report = await portfolio.report(db, ex.agent.id, USER)
    assert "100000" not in report["markdown"] and "100% accuracy" not in report["markdown"]


@pytest.mark.asyncio
async def test_missing_metric_not_backfilled_from_other_runs(db, completed):
    ex = completed
    run = await phase4.evaluation.get_run(
        db, ex.agent.id, USER, uuid.UUID(ex.project.report_json["optimization"]["best_run_id"])
    )
    metrics = deepcopy(run.metrics_json)
    metrics["metric_scores"].pop("task_completion")
    run.metrics_json = metrics
    await db.commit()
    data = await portfolio.evidence(db, ex.agent.id, USER)
    assert "task_completion" not in data["results"]["metric_deltas"]
