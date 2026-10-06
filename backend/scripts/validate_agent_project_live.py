"""Live owner-configured Builder→V1 acceptance; all approvals are Codex demos."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.callbacks import BaseCallbackHandler
from sqlalchemy import select

from app.agent_runtime import model_factory
from app.agent_runtime.builder.sub_agents import helpers
from app.agent_runtime.builder_v3.graph import compile_graph
from app.agent_runtime.checkpointer import (
    get_checkpointer,
    init_checkpointer,
    shutdown_checkpointer,
)
from app.agent_runtime.llm_user_context import llm_user_id
from app.config import settings
from app.database import async_session
from app.models.agent_project import AgentProject, AgentProjectEvalRun
from app.schemas.agent_project import EvalRunCreate
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_optimization as optimization
from app.services import agent_project_portfolio as portfolio
from app.services import agent_project_practice as practice
from app.services import agent_project_proposals as proposals
from app.services import builder_project_lifecycle, builder_service
from app.services.agent_project_llm import role_configurations
from app.services.agent_project_materials import interview_material, resume_material
from app.services.agent_project_portfolio_export import export_zip

DEMO = "【Codex 开发验收演示，非用户本人撰写】"
TASKS = {
    "写作": {
        "goal": "将用户提供的工作记录写成周报。",
        "inputs": "任务、状态、问题和下周计划的结构化记录。",
        "deliverables": "本周完成、未完成与下周计划三个段落。",
        "business_rules": "只采用提供的事实，不编造数字和收益；缺少字段时标明未提供。",
        "success_conditions": "覆盖已提供记录，正确区分完成与未完成，不增加事实。",
    },
    "客服": {
        "goal": "根据用户提供的商品和售后资料回答客服问题。",
        "inputs": "商品尺寸、材质、订单和明确的售后政策。",
        "deliverables": "有依据的答复或必要的澄清。",
        "business_rules": "不虚构政策、测量方法或业务操作；无资料时说明无法确认。",
        "success_conditions": "直接回答核心问题，信息不足时澄清，不新增事实。",
    },
    "知识问答": {
        "goal": "仅依据用户提供的项目知识片段回答问题。",
        "inputs": "项目文档片段和用户问题。",
        "deliverables": "回答并指出对应片段；无资料时说明边界。",
        "business_rules": "不联网，不将文本指南声称为检索系统，不用外部常识补造项目事实。",
        "success_conditions": "答案与提供片段一致，缺少证据时明确无法确定。",
    },
    "纯对话": {
        "goal": "与用户进行需求澄清并形成行动清单。",
        "inputs": "用户诉求、偏好与已知限制。",
        "deliverables": "简洁的澄清问题或符合限制的行动清单。",
        "business_rules": "不调用工具，不虚构用户经历和已执行操作，不要求敏感信息。",
        "success_conditions": "有信息时给出符合限制的步骤，信息不足时提出必要澄清。",
    },
}


class Budget(BaseCallbackHandler):
    raise_error = True

    def __init__(self, limit, path):
        previous = json.loads(path.read_text()) if path.exists() else {}
        self.limit, self.path, self.count = limit, path, previous.get("actual_model_invocations", 0)
        self.lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, **kwargs):
        with self.lock:
            if self.count >= self.limit:
                raise RuntimeError("live_acceptance_budget_exhausted")
            self.count += 1
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "actual_model_invocations": self.count,
                        "hard_limit": self.limit,
                        "cost": "unavailable; provider pricing not configured",
                    },
                    indent=2,
                )
            )
            temporary.replace(self.path)


async def consume(stream):
    return "".join([chunk async for chunk in stream])


async def iterate(aid, owner, folder, receipt, budget, rounds):
    """Review actual evidence; every approval is explicitly a developer demo."""
    receipt.setdefault("iterations", [])
    finished = sum(bool(x.get("candidate_run_id")) for x in receipt["iterations"])
    for _ in range(max(0, rounds - finished)):
        async with async_session() as db:
            project = await portfolio.projects.require_project(db, aid, owner)
            run = await db.scalar(
                select(AgentProjectEvalRun)
                .where(AgentProjectEvalRun.project_id == project.id)
                .order_by(AgentProjectEvalRun.created_at.desc())
                .limit(1)
            )
            if run is None or run.status not in {"completed", "failed"}:
                receipt["termination"] = "latest_experiment_not_completed"
                return
            optimization.terminal_semantic(run)
            rid = run.id
            entry: dict[str, Any] | None = next(
                (x for x in receipt["iterations"] if x["source_run_id"] == str(rid)), None
            )
            if entry is None:
                entry = {"source_run_id": str(rid), "approval_author": "codex_demo"}
                receipt["iterations"].append(entry)
            try:
                entry["analysis"] = await optimization.analyze(db, aid, owner, rid)
                if not entry["analysis"].get("groups"):
                    receipt["termination"] = "no_supported_improvement"
                    break
                required = len(run.cases_snapshot_json or []) * 2 + 2
                if budget.count + required > budget.limit:
                    receipt["termination"] = "insufficient_budget_for_complete_regression"
                    break
                first = await proposals.generate(
                    db, aid, owner, rid, uuid.uuid5(rid, "live-proposals")
                )
                run = await evaluation.get_run(db, aid, owner, rid)
                options = proposals.proposals(run)
                # Stable first valid proposal, never selected by a later score.
                chosen = next((x for x in options if x.get("status") == "accepted"), first)
                entry["proposals"] = options
                entry["choice"] = chosen["id"]
                entry["reason"] = (
                    DEMO + "按生成顺序采用首个通过约束验证的方案；仅凭当前证据，不预选回归成绩。"
                )
                accepted = await proposals.decide(
                    db, aid, owner, rid, uuid.UUID(chosen["id"]), "accepted", entry["reason"]
                )
                next_run = await proposals.regression(
                    db, aid, owner, rid, uuid.UUID(chosen["id"]), uuid.uuid5(rid, "live-regression")
                )
                next_id = next_run.id
                entry["candidate_run_id"] = str(next_id)
                entry["candidate_version_id"] = accepted.get("version_id")
            except Exception as exc:
                entry["error"] = getattr(exc, "code", type(exc).__name__)
                receipt["termination"] = "analysis_or_proposal_rejected"
                break
        (folder / "acceptance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        await evaluation.execute_run(next_id, aid, owner)
        async with async_session() as db:
            candidate = await evaluation.get_run(db, aid, owner, next_id)
            entry["candidate_status"] = candidate.status
            entry["candidate_metrics"] = candidate.metrics_json
            entry["comparison"] = (candidate.comparison_json or {}).get("comparison")
    else:
        receipt["termination"] = "configured_iteration_limit"
    async with async_session() as db:
        receipt["completion"] = await practice.completion(db, aid, owner)


async def build(category, owner, output, budget, rounds, instructions_only=False):
    folder = output / category
    folder.mkdir(exist_ok=True)
    receipt_path = folder / "acceptance.json"
    receipt = (
        json.loads(receipt_path.read_text())
        if receipt_path.exists()
        else {
            "validation_type": "live_personal_models",
            "category": category,
            "approval_author": "codex_demo",
            "steps": [],
            "requirements": TASKS[category],
            "limitations": [
                "Developer demonstration, not the user’s personal contribution.",
                "Simulated business data only; no expert or production validation.",
            ],
        }
    )

    def save():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))

    try:
        if receipt_path.exists() and receipt.get("instructions_only", False) != instructions_only:
            raise ValueError("acceptance_configuration_conflict_use_separate_output")
        receipt["instructions_only"] = instructions_only
        async with async_session() as db:
            if not receipt.get("builder_session_id"):
                request = (
                    f"创建{category}智能体，用于纯模拟项目实践。"
                    f"{json.dumps(TASKS[category], ensure_ascii=False)} "
                    "不联网、不执行脚本、不接入MCP。无需图片。"
                )
                session = await builder_service.create_session(db, owner, request)
                receipt["builder_session_id"] = str(session.id)
                save()
            sid = uuid.UUID(receipt["builder_session_id"])
            session = await builder_service.get_session(db, sid, owner)
            if session is None:
                raise ValueError("builder_session_not_found")
            request = session.user_request
        graph = compile_graph(get_checkpointer())
        config = {"configurable": {"thread_id": str(sid), "ui_locale": "zh-CN"}}
        state = await graph.aget_state(config)
        if not state.values:
            await consume(
                builder_service.run_v3_message_stream(sid, owner, request, locale="zh-CN")
            )
        for _ in range(16):
            state = await graph.aget_state(config)
            if state.values.get("completed"):
                receipt["agent_id"] = state.values["agent_id"]
                break
            interrupts = [i.value for t in state.tasks for i in t.interrupts]
            if not interrupts:
                raise RuntimeError("builder_no_pending_interrupt")
            interrupt = interrupts[0]
            phase = interrupt.get("phase", state.values.get("current_phase"))
            receipt["steps"].append({"phase": phase, "type": interrupt.get("type")})
            save()
            if interrupt.get("type") == "image_choice":
                response = "skip"
            elif interrupt.get("mode") == "question_flow":
                answers = {
                    **TASKS[category],
                    "requirements_reason": DEMO + "验证需求传递及自动评测，不代表个人理解。",
                    "agent_name": f"质量验收·{category}",
                    "response_tone": "professional",
                    "output_style": "summary",
                }
                if any(q.get("id") == "runtime_model_id" for q in interrupt.get("questions", [])):
                    options = next(
                        q["options"]
                        for q in interrupt["questions"]
                        if q["id"] == "runtime_model_id"
                    )
                    answers = {
                        "runtime_model_id": next(o["id"] for o in options if o["id"] != "retry")
                    }
                response = {"mode": "question_flow", "answers": answers}
            elif interrupt.get("type") == "approval":
                response = {
                    "approved": True,
                    "reason": DEMO + "采用本轮生成的纯模拟文本能力，继续验证；不声称生产可用。",
                }
            else:
                raise RuntimeError("builder_requires_unhandled_input")
            await consume(
                builder_service.run_v3_resume_stream(sid, owner, response, locale="zh-CN")
            )
        else:
            raise RuntimeError("builder_step_limit")
        save()
        aid = uuid.UUID(receipt["agent_id"])
        async with async_session() as db:
            agent = await portfolio.projects.owned_agent(db, aid, owner)
            session = await builder_service.get_session(db, sid, owner)
            if session is None:
                raise ValueError("builder_session_not_found")
            planned = (session.draft_config or {}).get("planned_tools")
            config = (await portfolio.projects.build_snapshot(db, agent, planned))["agent"]
            receipt["capabilities"] = {
                key: len([link for link in config.get(key, []) if link.get("enabled", True)])
                for key in ("tool_links", "mcp_tool_links", "planned_tools", "skill_links")
            }
        save()
        if instructions_only and any(receipt["capabilities"].values()):
            raise ValueError("instructions_only_capabilities_not_empty")
        # Uses the exact automatic baseline worker, not a handcrafted runtime fixture.
        await builder_project_lifecycle.bootstrap(aid, owner)
        # Another scheduled worker may own the advisory lock. Wait for its actual result.
        for _ in range(1800):
            async with async_session() as db:
                project = await portfolio.projects.require_project(db, aid, owner)
                state = (project.requirements_json or {}).get("bootstrap", {})
            if state.get("stage") == "results" or state.get("error"):
                break
            await asyncio.sleep(2)
        else:
            raise RuntimeError("automatic_baseline_wait_timeout")
        if state.get("stage") == "results" and state.get("run_id"):
            async with async_session() as db:
                prior = await evaluation.get_run(db, aid, owner, uuid.UUID(state["run_id"]))
                protocol = (prior.comparison_json or {}).get("execution_protocol") or {}
                needs_retry = (
                    prior.status == "failed"
                    and (prior.metrics_json or {}).get("errored")
                    and not protocol.get("judge_validation_retry_limit")
                )
                minimum_calls = (
                    len(prior.cases_snapshot_json or [])
                    * (prior.comparison_json or {}).get("repetitions", 1)
                    * 2
                )
                if needs_retry and budget.count + minimum_calls > budget.limit:
                    receipt["protocol_retry_skipped"] = (
                        "insufficient_budget_for_complete_protocol_rerun"
                    )
                    retry_id = None
                elif needs_retry:
                    retry = await evaluation.create_run(
                        db,
                        aid,
                        owner,
                        EvalRunCreate(
                            request_id=uuid.uuid5(prior.id, "quality-protocol-retry-v1"),
                            version_id=prior.version_id,
                            eval_set_id=prior.eval_set_id,
                            repetitions=(prior.comparison_json or {}).get("repetitions", 1),
                        ),
                    )
                    retry_id = retry.id
                    receipt["protocol_retry_run_id"] = str(retry_id)
                else:
                    retry_id = None
            if retry_id:
                save()
                await evaluation.execute_run(retry_id, aid, owner)
        if state.get("stage") == "results" and not state.get("error") and rounds:
            await iterate(aid, owner, folder, receipt, budget, rounds)
        async with async_session() as db:
            project = await portfolio.projects.require_project(db, aid, owner)
            await db.refresh(project)
            receipt["bootstrap"] = (project.requirements_json or {}).get("bootstrap")
            runs = list(
                (
                    await db.scalars(
                        select(AgentProjectEvalRun)
                        .where(AgentProjectEvalRun.project_id == project.id)
                        .order_by(AgentProjectEvalRun.created_at)
                    )
                ).all()
            )
            receipt["runs"] = [
                {
                    "id": str(r.id),
                    "version_id": str(r.version_id),
                    "status": r.status,
                    "metrics": r.metrics_json,
                    "plan": r.comparison_json,
                    "cases": r.cases_snapshot_json,
                    "results": r.results_json,
                }
                for r in runs
            ]
            report = await portfolio.report(db, aid, owner, save=True)
            (folder / "report.md").write_text(report["markdown"])
            (folder / "evidence.json").write_text(
                json.dumps(report["evidence"], ensure_ascii=False, indent=2)
            )
            (folder / "resume.json").write_text(
                json.dumps(resume_material(report["evidence"]), ensure_ascii=False, indent=2)
            )
            (folder / "interview.json").write_text(
                json.dumps(interview_material(report["evidence"]), ensure_ascii=False, indent=2)
            )
            (folder / "portfolio.zip").write_bytes(await export_zip(db, aid, owner))
            latest = runs[-1] if runs else None
            receipt["baseline_status"] = (
                "completed"
                if latest and latest.status == "completed"
                else "completed_with_errors"
                if latest
                and latest.status == "failed"
                and len(latest.results_json or [])
                == len(latest.cases_snapshot_json or [])
                * (latest.comparison_json or {}).get("repetitions", 1)
                else "incomplete"
            )
            receipt["status"] = (
                receipt.get("completion", {}).get("status", "incomplete")
                if rounds
                else receipt["baseline_status"]
            )
            if receipt["baseline_status"] != "incomplete":
                receipt.pop("error", None)
    except Exception as exc:
        receipt["status"] = "incomplete"
        receipt["error"] = getattr(exc, "code", type(exc).__name__)
    receipt["actual_model_invocations_at_finish"] = budget.count
    save()
    print(
        f"{category}: {receipt['status']}; {receipt.get('bootstrap', receipt.get('error'))}",
        flush=True,
    )


async def main(args):
    if args.instructions_only:
        if args.categories != ["纯对话"]:
            raise ValueError("instructions_only_requires_pure_dialogue_category")
        TASKS["纯对话"] = {
            **TASKS["纯对话"],
            "business_rules": TASKS["纯对话"]["business_rules"]
            + "；能力方案只使用模型指令，不创建或绑定工具、Skill 或 MCP。",
        }
    args.output.mkdir(parents=True, exist_ok=True)
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
    helpers.create_chat_model = factory
    async with async_session() as db:
        source = await db.get(AgentProject, uuid.UUID(args.project_id))
        if source is None:
            raise ValueError("project_not_found")
        owner = source.user_id
        roles = await role_configurations(db, owner)
    (args.output / "models.json").write_text(
        json.dumps(
            {k: {f: v.get(f) for f in ("provider", "model_name")} for k, v in roles.items()},
            indent=2,
        )
    )
    token = llm_user_id.set(owner)
    await init_checkpointer(settings.database_url_sync, min_size=1, max_size=5)
    try:
        semaphore = asyncio.Semaphore(args.concurrency)

        async def validate(category, rounds):
            async with semaphore:
                for _attempt in range(args.attempts if not rounds else 1):
                    await build(
                        category, owner, args.output, budget, rounds, args.instructions_only
                    )
                    receipt = json.loads((args.output / category / "acceptance.json").read_text())
                    (args.output / category / f"attempt-{budget.count}.json").write_text(
                        json.dumps(receipt, ensure_ascii=False, indent=2)
                    )
                    if (
                        receipt["status"] == "completed"
                        or (receipt.get("bootstrap") or {}).get("stage") == "results"
                    ):
                        break

        # Finish every baseline before spending the shared budget on regressions.
        await asyncio.gather(*(validate(category, 0) for category in args.categories))
        for rounds in range(1, args.iterations + 1):
            ready = []
            for category in args.categories:
                receipt = json.loads((args.output / category / "acceptance.json").read_text())
                if receipt.get("baseline_status") in {"completed", "completed_with_errors"}:
                    ready.append(category)
            await asyncio.gather(*(validate(category, rounds) for category in ready))
    finally:
        await shutdown_checkpointer()
        llm_user_id.reset(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--categories", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--attempts", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--budget", type=int, default=480)
    parser.add_argument("--iterations", type=int, choices=range(3), default=2)
    parser.add_argument("--concurrency", type=int, choices=range(1, 3), default=1)
    parser.add_argument("--instructions-only", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("../output/quality-revision-20261007/live-builder")
    )
    asyncio.run(main(parser.parse_args()))
