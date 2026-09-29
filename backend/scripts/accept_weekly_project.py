"""Real-model acceptance, isolated SQLite storage and synthetic Feishu only.

Run from backend: python scripts/accept_weekly_project.py --output ../output/weekly.json
Environment: WEEKLY_LLM_API_KEY, WEEKLY_LLM_MODEL, optional WEEKLY_LLM_BASE_URL.
No persisted application database or live Feishu connection is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.credentials import service as credentials
from app.database import Base
from app.models.agent import Agent
from app.models.builder_session import BuilderSession
from app.models.model import Model
from app.models.system_llm_setting import SystemLlmSetting
from app.models.user import User
from app.schemas.agent_project import EvalRunCreate
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_proposals as proposals
from app.services import agent_project_service as projects
from app.services.agent_project_optimization_rules import compare_runs
from app.services.agent_project_weekly_example import TOOLS, dataset, rubric


def save_receipt(output: Path, value: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def run(output: Path) -> None:
    key = os.environ.get("WEEKLY_LLM_API_KEY")
    model_name = os.environ.get("WEEKLY_LLM_MODEL")
    if not key or not model_name:
        raise SystemExit("Set WEEKLY_LLM_API_KEY and WEEKLY_LLM_MODEL locally before running.")
    base_url = os.environ.get("WEEKLY_LLM_BASE_URL")
    provider = "openai_compatible" if base_url else "openai"
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    previous_factory = evaluation.async_session
    evaluation.async_session = factory
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            user = User(email="weekly-acceptance@example.invalid", name="Weekly acceptance")
            db.add(user)
            await db.flush()
            payload = {"api_key": key, **({"base_url": base_url} if base_url else {})}
            cred = await credentials.create(
                db,
                user_id=user.id,
                definition_key=provider,
                name="Acceptance examinee",
                data=payload,
            )
            judge_cred = await credentials.create(
                db,
                user_id=None,
                definition_key=provider,
                name="Acceptance judge",
                data=payload,
                is_system=True,
            )
            db.add(
                SystemLlmSetting(
                    role="judge_optimizer",
                    credential_id=judge_cred.id,
                    model_name=model_name,
                )
            )
            model = Model(
                provider=provider,
                model_name=model_name,
                display_name="Acceptance",
                base_url=base_url,
            )
            db.add(model)
            await db.flush()
            agent = Agent(
                user_id=user.id,
                name="Weekly report acceptance",
                model_id=model.id,
                llm_credential_id=cred.id,
                system_prompt=(
                    "Write evidence-based weekly reports. For speed, read only the first page "
                    "before publishing. Explain tool errors honestly."
                ),
            )
            db.add(agent)
            await db.flush()
            db.add(
                BuilderSession(
                    user_id=user.id,
                    agent_id=agent.id,
                    user_request="Weekly reports with simulated Feishu",
                    draft_config={"planned_tools": TOOLS},
                )
            )
            await db.commit()
            await projects.create_project(db, agent.id, user.id)
            version = (await projects.list_versions(db, agent.id, user.id))[0]
            tests = await evaluation.write_set(db, agent.id, user.id, dataset(), rubric=rubric())
            await evaluation.judge_set(db, agent.id, user.id, tests.id)
            baseline = await evaluation.create_run(
                db,
                agent.id,
                user.id,
                EvalRunCreate(
                    request_id=uuid.uuid4(),
                    version_id=version.id,
                    eval_set_id=tests.id,
                ),
            )
            print("Running baseline against six frozen cases...", flush=True)
            await evaluation.execute_run(baseline.id, agent.id, user.id)
            await db.refresh(baseline)
            await asyncio.to_thread(
                save_receipt,
                output,
                {
                    "stage": "baseline",
                    "status": baseline.status,
                    "results": baseline.results_json,
                    "metrics": baseline.metrics_json,
                },
            )
            print(f"Baseline: {baseline.status}, pass rate: {baseline.pass_rate}", flush=True)
            if baseline.status != "completed":
                raise RuntimeError(
                    "Baseline execution failed; inspect model connectivity/configuration."
                )
            print("Analyzing failures and generating proposals...", flush=True)
            proposal = await proposals.generate(db, agent.id, user.id, baseline.id, uuid.uuid4())
            accepted = await proposals.decide(
                db,
                agent.id,
                user.id,
                baseline.id,
                uuid.UUID(proposal["id"]),
                "accepted",
                "Acceptance script approves this isolated experimental proposal.",
            )
            regression = await proposals.regression(
                db,
                agent.id,
                user.id,
                baseline.id,
                uuid.UUID(accepted["id"]),
                uuid.uuid4(),
            )
            print("Accepted proposal; running frozen regression...", flush=True)
            await evaluation.execute_run(regression.id, agent.id, user.id)
            await db.refresh(regression)
            comparison = compare_runs(baseline, regression)
            receipt = {
                "mode": "real_model_mock_feishu",
                "model": model_name,
                "baseline_status": baseline.status,
                "regression_status": regression.status,
                "baseline_version_id": str(baseline.version_id),
                "regression_version_id": str(regression.version_id),
                "dataset_hash": baseline.dataset_hash,
                "same_frozen_cases": baseline.cases_snapshot_json == regression.cases_snapshot_json,
                "judge_pin": (baseline.comparison_json or {})["roles"]["judge"],
                "baseline": baseline.results_json,
                "regression": regression.results_json,
                "proposal": accepted,
                "comparison": comparison,
            }
            await asyncio.to_thread(save_receipt, output, receipt)
            print(f"Acceptance receipt: {output}", flush=True)
            if regression.status != "completed":
                raise RuntimeError(
                    "Regression has execution errors; receipt is not a passing acceptance."
                )
            if regression.version_id == baseline.version_id:
                raise RuntimeError("Acceptance did not create a new Agent version.")
            if comparison["decision"] != "accepted" or comparison["regressed_cases"]:
                raise RuntimeError("Optimization did not improve quality without regressions.")
    finally:
        evaluation.async_session = previous_factory
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("../output/weekly-acceptance.json"))
    asyncio.run(run(parser.parse_args().output))
