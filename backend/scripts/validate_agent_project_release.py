"""Reproducible CONTROLLED portfolio demo; no provider calls or production database.

Run from backend: python scripts/validate_agent_project_release.py
Uses the Phase 4 SQLite fixture and public ASGI routes, not the live application.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import uuid
import zipfile
from collections.abc import AsyncIterator
from inspect import unwrap
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.dependencies import get_db  # noqa: E402
from app.exception_handlers import register_exception_handlers  # noqa: E402
from app.marketplace.payloads import scan_payload  # noqa: E402
from app.routers.agent_projects import public_router  # noqa: E402
from app.services import agent_project_portfolio as portfolio  # noqa: E402
from app.services.agent_project_portfolio_export import export_zip  # noqa: E402
from tests import test_agent_project_phase4 as controlled  # noqa: E402


def verify(condition: bool, message: str = "Release validation failed") -> None:
    if not condition:
        raise RuntimeError(message)


async def main() -> None:
    fixture = unwrap(controlled.db)()
    db = await anext(fixture)
    patch = pytest.MonkeyPatch()
    original_seed = controlled.phase3.phase2.seed_agent
    original_cases = controlled.phase3.generated_cases

    async def seed(*args: Any, **kwargs: Any) -> tuple[Any, Any, Any]:
        user, model, agent = await original_seed(*args, **kwargs)
        agent.name = "Weekly Report Agent (controlled demo)"
        agent.description = "Generate a weekly work report from structured work records."
        agent.system_prompt = "Write a weekly report using the supplied work records."
        return user, model, agent

    def cases() -> dict[str, Any]:
        result = original_cases()
        result["name"] = "Weekly report controlled benchmark"
        for case in result["cases"]:
            case["input"] = "Write this week's work report from the supplied records."
            case["mock_tool_data"]["search"]["result"] = [
                {"task": "Review login flow", "status": "completed", "next": "Regression test"}
            ]
        return result

    try:
        patch.setattr(controlled.phase3.phase2, "seed_agent", seed)
        patch.setattr(controlled.phase3, "generated_cases", cases)
        experiment = await unwrap(controlled.experiment)(db, patch)
        experiment.project.title = experiment.agent.name
        await db.commit()
        patch.setattr(controlled.optimization, "json_call", controlled.controlled_optimizer)
        await controlled.optimization.start(
            db, experiment.agent.id, controlled.TEST_USER_ID, experiment.run.id, uuid.uuid4()
        )
        await controlled.optimization.execute_optimization(
            experiment.agent.id, controlled.TEST_USER_ID, experiment.run.id
        )
        await db.refresh(experiment.project)
        report = await portfolio.report(db, experiment.agent.id, controlled.TEST_USER_ID, save=True)
        resume = await portfolio.resume(
            db, experiment.agent.id, controlled.TEST_USER_ID, "ai_product"
        )
        archive_bytes = await export_zip(db, experiment.agent.id, controlled.TEST_USER_ID)
        verify(report["evidence"]["results"]["best_version"] == 2)
        verify(report["evidence"]["results"]["best"]["pass_rate"] == 0.9)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = archive.namelist()
            for expected in (
                "README.md",
                "agent.json",
                "instructions.md",
                "eval_spec.json",
                "eval_results.json",
                "skills/README.md",
                "versions/v1/agent.json",
                "versions/v2/agent.json",
                "versions/v3/agent.json",
                "report/project_report.md",
            ):
                verify("agent-project/" + expected in names)
            for name in names:
                text = archive.read(name).decode("utf-8")
                verify(not scan_payload({"content": text}), f"Secret scan failed: {name}")
                verify(not re.search("(?i)\\b[A-Z]:[\\\\/]", text), f"Local path: {name}")
                verify("Review login flow" not in text, f"Raw source data: {name}")
                verify("llm_credential_id" not in text)
                if name.endswith(".json"):
                    json.loads(text)

        app = FastAPI()
        app.include_router(public_router)
        register_exception_handlers(app)

        async def database() -> AsyncIterator[Any]:
            yield db

        app.dependency_overrides[get_db] = database
        share = await portfolio.share(db, experiment.agent.id, controlled.TEST_USER_ID)
        public_path = share["path"].replace("/shared/projects/", "/api/project-shares/")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            public = await client.get(public_path)
            verify(public.status_code == 200)
            verify(not scan_payload({"content": public.text}))
            verify("Review login flow" not in public.text)
            for field in ("credential_id", "tool_calls", "mock_tool_data", "thinking"):
                verify(field not in public.text)
            verify((await client.post(public_path)).status_code == 405)
            await portfolio.share(db, experiment.agent.id, controlled.TEST_USER_ID, revoke=True)
            verify((await client.get(public_path)).status_code == 404)

        output = BACKEND.parent / "output" / "agent-project-release-demo"
        output.mkdir(parents=True, exist_ok=True)
        (output / "project_report.md").write_text(report["markdown"], encoding="utf-8")
        (output / "resume.txt").write_text("\n".join(resume["bullets"]), encoding="utf-8")
        (output / "agent-project.zip").write_bytes(archive_bytes)
        summary = {
            "mode": "controlled SQLite + ASGI; no live provider or browser",
            "versions": [75, 90, 85],
            "best_version": 2,
            "zip_scan": "passed",
            "public_read": 200,
            "public_write": 405,
            "public_read_after_revoke": 404,
            "live_provider": "not executed",
        }
        (output / "validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary))
    finally:
        patch.undo()
        await fixture.aclose()


if __name__ == "__main__":
    asyncio.run(main())
