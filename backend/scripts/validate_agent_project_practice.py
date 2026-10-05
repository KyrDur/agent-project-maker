"""Reproduce twelve controlled experiments and export their actual stored evidence.

Run from backend: python scripts/validate_agent_project_practice.py
No provider API calls. Each experiment uses a new in-memory SQLite database.
"""

from __future__ import annotations

import asyncio
import json
import sys
from inspect import unwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.models.agent_project import AgentProjectEvalRun  # noqa: E402
from app.services import agent_project_portfolio as portfolio  # noqa: E402
from app.services.agent_project_materials import interview  # noqa: E402
from app.services.agent_project_portfolio_export import export_zip  # noqa: E402
from tests import test_agent_project_practice as controlled  # noqa: E402


async def main() -> None:
    output = BACKEND.parent / "output/agent-project-practice-validation"
    output.mkdir(parents=True, exist_ok=True)
    experiments = []
    for kind in ("writing", "support", "knowledge", "dialogue"):
        for score, outcome in ((0.9, "improved"), (0.3, "unchanged"), (0.2, "regressed")):
            fixture = unwrap(controlled.db)()
            db = await anext(fixture)
            patch = pytest.MonkeyPatch()
            try:
                agent = await unwrap(controlled.setup_project)(db, patch)
                await controlled.test_four_categories_v1_v2_materials(db, agent, patch, kind, score)
                report = await portfolio.report(db, agent.id, controlled.TEST_USER_ID)
                resume = await portfolio.resume(db, agent.id, controlled.TEST_USER_ID, "ai_product")
                questions = await interview(db, agent.id, controlled.TEST_USER_ID)
                runs = list(
                    (
                        await db.scalars(
                            select(AgentProjectEvalRun).order_by(
                                AgentProjectEvalRun.created_at, AgentProjectEvalRun.id
                            )
                        )
                    ).all()
                )
                folder = output / f"{kind}-{outcome}"
                folder.mkdir(exist_ok=True)
                files = {
                    "report": report,
                    "resume": resume,
                    "interview": questions,
                    "runs": [
                        {
                            "id": str(r.id),
                            "version_id": str(r.version_id),
                            "cases": r.cases_snapshot_json,
                            "results": r.results_json,
                            "metrics": r.metrics_json,
                            "frozen_experiment": r.comparison_json,
                        }
                        for r in runs
                    ],
                }
                for name, value in files.items():
                    (folder / f"{name}.json").write_text(
                        json.dumps(value, ensure_ascii=False, indent=2)
                    )
                (folder / "report.md").write_text(report["markdown"])
                (folder / "materials.zip").write_bytes(
                    await export_zip(db, agent.id, controlled.TEST_USER_ID)
                )
                experiments.append(
                    {
                        "category": kind,
                        "outcome": outcome,
                        "evidence_hash": report["evidence_hash"],
                        "results": report["evidence"]["results"],
                        "artifact_directory": folder.name,
                    }
                )
            finally:
                patch.undo()
                await fixture.aclose()
    receipt = {
        "mode": "controlled_fixed_response",
        "real_provider_calls": 0,
        "database": "isolated SQLite per experiment",
        "experiments": experiments,
        "limitation": "Validates workflow and evidence; does not measure actual model ability.",
    }
    (output / "validation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(f"Validated {len(experiments)} controlled experiments; artifacts: {output}")


if __name__ == "__main__":
    asyncio.run(main())
