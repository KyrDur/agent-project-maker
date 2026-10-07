"""Re-evaluate the first three historical snapshots in one new, real-model scope.

Never changes their old datasets, results or scores. Developer acceptance only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.callbacks import BaseCallbackHandler
from sqlalchemy import select
from validate_agent_project_live import Budget

from app.agent_runtime import model_factory
from app.agent_runtime.llm_user_context import llm_user_id
from app.database import async_session
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProject, AgentProjectEvalRun
from app.schemas.agent_project import EvalRunCreate, ProjectDecision
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_practice as practice
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services.agent_project_preflight import preflight_case


def fingerprint(run):
    return canonical_json_hash(
        {
            "cases": run.cases_snapshot_json,
            "results": run.results_json,
            "metrics": run.metrics_json,
            "comparison": run.comparison_json,
        }
    )


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "acceptance.json"
    receipt = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "mode": "live_personal_models",
            "author": "codex_development_acceptance",
            "scope": "new_v3_contract",
            "runs": [],
        }
    )
    budget = Budget(args.budget, args.output / "call-budget.json")
    original = model_factory.create_chat_model

    def factory(*a, **kw):
        model = original(*a, **kw)
        callbacks: list[BaseCallbackHandler] = (
            list(model.callbacks) if isinstance(model.callbacks, list) else []
        )
        model.callbacks = [*callbacks, budget]
        return model

    model_factory.create_chat_model = factory

    def save():
        receipt["actual_model_invocations"] = budget.count
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))

    token = None
    try:
        async with async_session() as db:
            project = await db.get(AgentProject, uuid.UUID(args.project_id))
            if project is None:
                raise ValueError("project_not_found")
            owner, aid, pid = project.user_id, project.agent_id, project.id
            versions = [
                SimpleNamespace(
                    id=v.id,
                    version_number=v.version_number,
                    snapshot_json=deepcopy(v.snapshot_json),
                )
                for v in sorted(
                    await projects.list_versions(db, aid, owner),
                    key=lambda item: item.version_number,
                )[:3]
            ]
            if len(versions) != 3:
                raise ValueError("three_historical_snapshots_required")
            old = (
                await db.scalars(
                    select(AgentProjectEvalRun).where(AgentProjectEvalRun.project_id == pid)
                )
            ).all()
            if "historical_fingerprints" not in receipt:
                receipt["historical_fingerprints"] = {str(r.id): fingerprint(r) for r in old}
                save()
            token = llm_user_id.set(owner)
            if not receipt.get("dataset_id"):
                for attempt in range(3):
                    try:
                        await semantic.generate(db, aid, owner, versions[0].id)
                        break
                    except Exception as exc:
                        receipt.setdefault("generation_failures", []).append(
                            {
                                "stage": "plan",
                                "attempt": attempt + 1,
                                "error": getattr(exc, "code", type(exc).__name__),
                            }
                        )
                        save()
                else:
                    raise RuntimeError("new_plan_not_accepted")
                for attempt in range(3):
                    try:
                        dataset = await semantic.generate(
                            db, aid, owner, versions[0].id, cases=True
                        )
                        await evaluation.judge_set(db, aid, owner, dataset.id)
                        receipt["dataset_id"] = str(dataset.id)
                        save()
                        break
                    except Exception as exc:
                        receipt.setdefault("generation_failures", []).append(
                            {
                                "stage": "cases",
                                "attempt": attempt + 1,
                                "error": getattr(exc, "code", type(exc).__name__),
                            }
                        )
                        save()
                else:
                    raise RuntimeError("new_cases_not_accepted")
            dataset_id = uuid.UUID(receipt["dataset_id"])
            if args.run_attempt > 1 and receipt.get("frozen_plan"):
                from app.services.agent_project_preflight import EXECUTION_PROTOCOL

                receipt.setdefault("initial_frozen_plan", deepcopy(receipt["frozen_plan"]))
                receipt["frozen_plan"] = {
                    **deepcopy(receipt["initial_frozen_plan"]),
                    "execution_protocol": deepcopy(EXECUTION_PROTOCOL),
                    "acceptance_attempt": args.run_attempt,
                }
                save()
            for index, version in enumerate(versions):
                recorded = next(
                    (
                        r
                        for r in receipt["runs"]
                        if r["version_id"] == str(version.id)
                        and r.get("attempt", 1) == args.run_attempt
                    ),
                    None,
                )
                if recorded and recorded["status"] in {"completed", "failed"}:
                    continue
                request_id = uuid.uuid5(
                    dataset_id,
                    f"historical-snapshot:{version.id}"
                    + (f":attempt-{args.run_attempt}" if args.run_attempt > 1 else ""),
                )
                if index == 0 and not receipt.get("frozen_plan"):
                    current_project = await projects.require_project(db, aid, owner)
                    stages: list[tuple[Literal["requirements", "capabilities"], str]] = [
                        ("requirements", "沿用项目已保存需求，在新评分范围复验历史快照。"),
                        ("capabilities", "沿用历史快照的冻结能力，仅运行模拟工具和文本 Skill。"),
                    ]
                    for stage, choice in stages:
                        if not any(
                            d.get("stage") == stage
                            and d.get("version_id") == str(version.id)
                            and d.get("requirements_hash")
                            == practice.requirements_hash(current_project)
                            for d in current_project.decisions_json or []
                        ):
                            current_project = await practice.record_decision(
                                db,
                                aid,
                                owner,
                                ProjectDecision(
                                    stage=stage,
                                    choice=choice,
                                    reason=(
                                        "【Codex 开发验收演示，非用户本人撰写】"
                                        "使用已授权的新口径复验；"
                                        "不补造个人贡献或修改历史成绩。"
                                    ),
                                    version_id=version.id,
                                ),
                            )
                    run = await evaluation.create_run(
                        db,
                        aid,
                        owner,
                        EvalRunCreate(
                            request_id=request_id, version_id=version.id, eval_set_id=dataset_id
                        ),
                    )
                    receipt["frozen_plan"] = deepcopy(run.comparison_json)
                    receipt["frozen_cases"] = deepcopy(run.cases_snapshot_json)
                    save()
                else:
                    for case in receipt["frozen_cases"]:
                        preflight_case(version.snapshot_json["agent"], case)
                    existing = await db.scalar(
                        select(AgentProjectEvalRun).where(
                            AgentProjectEvalRun.project_id == pid,
                            AgentProjectEvalRun.request_id == request_id,
                        )
                    )
                    candidate_plan = deepcopy(receipt["frozen_plan"])
                    if index:
                        previous = next(
                            r
                            for r in receipt["runs"]
                            if r["version_number"] == version.version_number - 1
                            and r.get("attempt", 1) == args.run_attempt
                        )
                        candidate_plan["regression"] = {
                            "source_run_id": previous["id"],
                            "acceptance_source": "historical_snapshot_retest",
                        }
                    run = existing or await evaluation.insert_frozen_run(
                        db,
                        pid,
                        version.id,
                        dataset_id,
                        request_id,
                        receipt["frozen_cases"],
                        candidate_plan,
                    )
                await evaluation.execute_run(run.id, aid, owner)
                await db.refresh(run)
                row = {
                    "id": str(run.id),
                    "version_id": str(version.id),
                    "version_number": version.version_number,
                    "status": run.status,
                    "metrics": run.metrics_json,
                    "results": run.results_json,
                    "plan": run.comparison_json,
                    "attempt": args.run_attempt,
                }
                receipt["runs"] = [r for r in receipt["runs"] if r["id"] != str(run.id)] + [row]
                save()
                print(
                    f"V{version.version_number}: {run.status}, "
                    f"{(run.metrics_json or {}).get('passed')}/"
                    f"{(run.metrics_json or {}).get('total')}",
                    flush=True,
                )
            unchanged = []
            for rid, saved in receipt["historical_fingerprints"].items():
                original_run = await db.get(AgentProjectEvalRun, uuid.UUID(rid))
                unchanged.append(original_run is not None and fingerprint(original_run) == saved)
            receipt["historical_integrity"] = all(unchanged)
            current = [r for r in receipt["runs"] if r.get("attempt", 1) == args.run_attempt]
            receipt["status"] = (
                "completed"
                if len(current) == 3 and all(r["status"] == "completed" for r in current)
                else "incomplete"
            )
    except Exception as exc:
        receipt.update(
            status="incomplete",
            error=getattr(
                exc, "code", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            ),
        )
    finally:
        if token is not None:
            llm_user_id.reset(token)
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-attempt", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--budget", type=int, default=176)
    parser.add_argument(
        "--output", type=Path, default=Path("../output/quality-revision-20261007/historical-rerun")
    )
    asyncio.run(main(parser.parse_args()))
