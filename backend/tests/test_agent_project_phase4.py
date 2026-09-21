"""Controlled improvement/regression evidence; no live provider calls."""

# pyright: reportOptionalSubscript=false


from __future__ import annotations

import json
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProject, AgentProjectVersion
from app.schemas.agent_project import EvalRunCreate, EvalSetWrite
from app.schemas.agent_project_optimization import PatchProposal
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_optimization as optimization
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services.agent_project_optimization_rules import apply_patches, compare_runs
from tests import test_agent_project_phase3 as phase3

TEST_USER_ID = phase3.TEST_USER_ID
db = phase3.db
client = phase3.client
SKILL_ID = str(uuid.UUID(int=123))


@pytest.fixture
async def experiment(db, monkeypatch):
    _, _, agent = await phase3.phase2.seed_agent(db)
    await db.commit()
    await db.refresh(agent, ["sub_agent_links"])
    snapshot = await projects.build_snapshot(db, agent)
    snapshot["agent"]["skill_links"] = [
        {
            "skill_id": SKILL_ID,
            "slug": "frozen-report",
            "content": "Use facts from supplied sources.",
        }
    ]
    project = AgentProject(
        agent_id=agent.id,
        user_id=TEST_USER_ID,
        title="Controlled project",
        eval_spec_json=phase3.plan(),
    )
    db.add(project)
    await db.flush()
    version = AgentProjectVersion(
        project_id=project.id,
        version_number=1,
        status="original",
        snapshot_json=snapshot,
        config_hash=canonical_json_hash(snapshot),
    )
    db.add(version)
    await db.commit()
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(evaluation, "async_session", sessions)
    monkeypatch.setattr(optimization, "async_session", sessions)
    body = phase3.generated_cases()
    dataset = await evaluation.write_set(
        db, agent.id, TEST_USER_ID, EvalSetWrite.model_validate(body)
    )
    await evaluation.judge_set(db, agent.id, TEST_USER_ID, dataset.id)

    async def examinee(_db, saved, case, _user):
        round_number = saved.get("optimization", {}).get("round", 0)
        index = int(case["name"].split()[-1])
        passes = (
            index < 15
            if round_number == 0
            else index < 14 or 15 <= index <= 18
            if round_number == 1
            else index < 13 or 15 <= index <= 18
        )
        if round_number:
            assert "Retrieve sources before answering." in saved["agent"]["system_prompt"]
            assert "Separate facts from assumptions." in saved["agent"]["skill_links"][0]["content"]
        return {
            "output": "Supported answer" if passes else "Incomplete answer",
            "tool_calls": [{"name": "search"}],
            "handoffs": [],
        }

    async def judge(_db, _snapshot, _user, _role, _instruction, payload):
        passes = payload["actual_output"] == "Supported answer"
        return {
            "metric_scores": {
                m["name"]: {
                    "score": 0.9 if passes or m["name"] == "groundedness" else 0.2,
                    "passed": passes or m["name"] == "groundedness",
                    "reason": "Controlled observable output.",
                }
                for m in payload["metrics"]
            }
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", examinee)
    monkeypatch.setattr(semantic, "json_call", judge)
    run = await evaluation.create_run(
        db,
        agent.id,
        TEST_USER_ID,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=version.id, eval_set_id=dataset.id),
    )
    await evaluation.execute_run(run.id, agent.id, TEST_USER_ID)
    await db.refresh(run)
    assert run.pass_rate == 0.75
    return SimpleNamespace(agent=agent, project=project, version=version, run=run, dataset=dataset)


def analyzer_response(payload):
    cases = payload["cases"]
    skill_ids = [c["case_id"] for c in cases[-2:]] if len(cases) > 2 else []
    analyses = []
    for case in cases:
        skill = case["case_id"] in skill_ids
        analyses.append(
            {
                "case_id": case["case_id"],
                "category": "skill_issue" if skill else "instruction_issue",
                "root_cause": "Source handling needs clearer steps."
                if skill
                else "Retrieval is not required.",
                "evidence": ["/actual_output", "/metric_scores/task_completion/score"],
                "recommended_target": "skill_content" if skill else "instructions",
                "suggested_fix": "Apply a general source-grounding rule.",
            }
        )
    groups = []
    for target in ("instructions", "skill_content"):
        members = [item for item in analyses if item["recommended_target"] == target]
        if members:
            groups.append(
                {
                    "category": members[0]["category"],
                    "case_ids": [item["case_id"] for item in members],
                    "root_cause": members[0]["root_cause"],
                    "target": target,
                    "proposed_change": "Retrieve sources; distinguish facts from assumptions.",
                }
            )
    return {"analyses": analyses, "groups": groups}


async def controlled_optimizer(_db, _snapshot, _user, role, _instruction, payload):
    if role == "bad_case_analyzer":
        return analyzer_response(payload)
    return {
        "changes": [
            {
                "group_index": i,
                "target": group["target"],
                "resource_id": SKILL_ID if group["target"] == "skill_content" else None,
                "operation": "append",
                "content": "Separate facts from assumptions."
                if group["target"] == "skill_content"
                else (
                    "Verify every requested section before finalizing."
                    if _snapshot.get("optimization")
                    else "Retrieve sources before answering."
                ),
                "reason": group["root_cause"],
            }
            for i, group in enumerate(payload["groups"])
        ]
    }


@pytest.mark.asyncio
async def test_optimize_endpoint_requires_human_proposal_decision(
    client, db, experiment, monkeypatch
):
    ex = experiment
    monkeypatch.setattr(optimization, "json_call", controlled_optimizer)
    path = f"/api/agents/{ex.agent.id}/project"
    analysis = (await client.post(f"{path}/eval-runs/{ex.run.id}/analyze")).json()
    assert len(analysis["bad_cases"]) == 5
    assert sorted(len(g["case_ids"]) for g in analysis["groups"]) == [2, 3]
    # Deliberately alter current dataset/spec AFTER baseline submission.
    ex.dataset.cases_json = []
    ex.project.eval_spec_json = None
    await db.commit()
    response = await client.post(
        f"{path}/eval-runs/{ex.run.id}/optimize", json={"request_id": str(uuid.uuid4())}
    )
    assert response.status_code == 410
    assert "optimization_requires_user_proposal_decision" in response.text
    await db.refresh(ex.project)
    assert optimization.state_of(ex.project) is None
    assert ex.dataset.cases_json == [] and ex.project.eval_spec_json is None
    assert len(await projects.list_versions(db, ex.agent.id, TEST_USER_ID)) == 1
    ex.version.snapshot_json = {}
    with pytest.raises(ValueError, match="immutable"):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_external_errors_are_classified_without_model_or_patches(db, experiment, monkeypatch):
    ex = experiment
    results = deepcopy(ex.run.results_json)
    for result in results:
        result.update(
            status="errored",
            error_code="evaluation_judge_invalid",
            error="evaluation_judge_invalid",
        )
    ex.run.results_json = results
    ex.run.status = "failed"
    await db.commit()

    async def forbidden(*_args):
        raise AssertionError("No optimizer/model call expected")

    monkeypatch.setattr(optimization, "json_call", forbidden)
    analysis = await optimization.analyze(db, ex.agent.id, TEST_USER_ID, ex.run.id)
    assert len(analysis["bad_cases"]) == 20 and not analysis["groups"]
    assert all(item["category"] == "external_unfixable" for item in analysis["bad_cases"])
    _, schedule = await optimization.start(db, ex.agent.id, TEST_USER_ID, ex.run.id, uuid.uuid4())
    assert schedule
    await optimization.execute_optimization(ex.agent.id, TEST_USER_ID, ex.run.id)
    await db.refresh(ex.project)
    assert optimization.state_of(ex.project)["stop_reason"] == "no_fixable_cases"
    assert len(await projects.list_versions(db, ex.agent.id, TEST_USER_ID)) == 1


@pytest.mark.parametrize(
    "target", ["model_params", "credentials", "eval_spec", "cases", "runtime_policy", "system_code"]
)
def test_forbidden_patch_targets_cannot_be_parsed(target):
    with pytest.raises(ValueError, match="validation error"):
        PatchProposal.model_validate(
            {
                "changes": [
                    {
                        "group_index": 0,
                        "target": target,
                        "operation": "replace_value",
                        "content": "{}",
                        "reason": "Bad request",
                    }
                ]
            }
        )


def test_minimal_patch_and_missing_skill_deferral():
    snapshot = {
        "agent": {
            "system_prompt": "Header\nA small section\nFooter",
            "model_params": {"temperature": 0.1},
            "skill_links": [{"skill_id": SKILL_ID}],
            "tool_links": [
                {
                    "tool_id": "tool1",
                    "description": "Old description",
                    "parameters": {"private": "fixed"},
                }
            ],
        }
    }
    original = deepcopy(snapshot)
    groups = [
        {"target": t, "category": "instruction_issue"}
        for t in ("instructions", "skill_content", "tool_description")
    ]
    proposal = PatchProposal.model_validate(
        {
            "changes": [
                {
                    "group_index": 0,
                    "target": "instructions",
                    "operation": "replace_section",
                    "old_content": "A small section",
                    "content": "A clearer section",
                    "reason": "Grouped issue",
                },
                {
                    "group_index": 1,
                    "target": "skill_content",
                    "resource_id": SKILL_ID,
                    "operation": "append",
                    "content": "More steps",
                    "reason": "Skill issue",
                },
                {
                    "group_index": 2,
                    "target": "tool_description",
                    "resource_id": "tool1",
                    "operation": "replace_value",
                    "old_content": "Old description",
                    "content": "Retrieve source data",
                    "reason": "Tool issue",
                },
            ]
        }
    )
    candidate, diffs, deferred = apply_patches(snapshot, proposal, groups)
    assert snapshot == original and len(diffs) == 2
    assert candidate["agent"]["model_params"] == original["agent"]["model_params"]
    assert candidate["agent"]["tool_links"][0]["parameters"] == {"private": "fixed"}
    assert candidate["agent"]["skill_links"] == original["agent"]["skill_links"]
    assert deferred[0]["limitation"] == "historical_skill_content_unavailable"
    proposal.changes[0].old_content = original["agent"]["system_prompt"]
    with pytest.raises(ValueError, match="optimization_section_invalid"):
        apply_patches(snapshot, proposal, groups)


@pytest.mark.asyncio
async def test_analyzer_rejects_fabricated_evidence_and_foreign_scope(
    client, db, experiment, monkeypatch
):
    async def invalid(*args):
        response = analyzer_response(args[-1])
        response["analyses"][0]["evidence"] = ["/hidden_chain_of_thought"]
        return response

    monkeypatch.setattr(optimization, "json_call", invalid)
    with pytest.raises(Exception, match="optimization_analysis_failed"):
        await optimization.analyze(db, experiment.agent.id, TEST_USER_ID, experiment.run.id)
    assert experiment.run.bad_cases_json is None
    path = f"/api/agents/{uuid.uuid4()}/project/eval-runs/{experiment.run.id}"
    assert (await client.post(path + "/analyze")).status_code == 404
    assert (
        await client.post(path + "/optimize", json={"request_id": str(uuid.uuid4())})
    ).status_code == 410


@pytest.mark.asyncio
async def test_regression_rejects_changed_cases_rubric_mock_data(db, experiment):
    baseline = experiment.run
    for field in ("cases_snapshot_json", "comparison_json", "dataset_hash"):
        candidate = SimpleNamespace(
            **{
                key: deepcopy(getattr(baseline, key))
                for key in (
                    "cases_snapshot_json",
                    "comparison_json",
                    "dataset_hash",
                    "eval_set_id",
                    "results_json",
                )
            }
        )
        if field == "cases_snapshot_json":
            candidate.cases_snapshot_json[0]["mock_tool_data"] = {}
        elif field == "comparison_json":
            candidate.comparison_json["eval_spec"]["pass_threshold"] = 0.1
        else:
            candidate.dataset_hash = "different"
        with pytest.raises(ValueError, match="optimization_regression_inputs_changed"):
            compare_runs(baseline, candidate)


@pytest.mark.asyncio
async def test_optimizer_secret_redacted_before_retained_analysis(
    db, experiment, monkeypatch, caplog
):
    from langchain_core.messages import AIMessage

    from app.services import agent_project_llm as llm

    secret = "optimizer-only-private-value"

    class Model:
        async def ainvoke(self, messages, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            result = analyzer_response(payload)
            result["analyses"][0]["root_cause"] += " " + secret
            return AIMessage(content=json.dumps(result))

    async def resolve(*_args):
        return Model(), secret

    monkeypatch.setattr(llm, "resolve_model", resolve)
    result = await optimization.analyze(db, experiment.agent.id, TEST_USER_ID, experiment.run.id)
    await db.refresh(experiment.run)
    assert secret not in json.dumps(result)
    assert secret not in json.dumps(experiment.run.bad_cases_json)
    assert "<redacted>" in json.dumps(experiment.run.bad_cases_json)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_no_improvement_stops_after_one_candidate(db, experiment, monkeypatch):
    ex = experiment
    monkeypatch.setattr(optimization, "json_call", controlled_optimizer)

    async def same_results(_db, _snapshot, case, _user):
        return {
            "output": "Supported answer"
            if int(case["name"].split()[-1]) < 15
            else "Incomplete answer",
            "tool_calls": [{"name": "search"}],
            "handoffs": [],
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", same_results)
    await optimization.start(db, ex.agent.id, TEST_USER_ID, ex.run.id, uuid.uuid4())
    await optimization.execute_optimization(ex.agent.id, TEST_USER_ID, ex.run.id)
    await db.refresh(ex.project)
    state = optimization.state_of(ex.project)
    assert len(state["rounds"]) == 1 and state["rounds"][0]["decision"] == "rejected"
    assert state["best_version_id"] == str(ex.version.id)


@pytest.mark.asyncio
async def test_two_round_limit_even_when_both_rounds_improve(db, experiment, monkeypatch):
    ex = experiment
    monkeypatch.setattr(optimization, "json_call", controlled_optimizer)

    async def improve(_db, snapshot, case, _user):
        count = 17 if snapshot["optimization"]["round"] == 1 else 19
        return {
            "output": "Supported answer"
            if int(case["name"].split()[-1]) < count
            else "Incomplete answer",
            "tool_calls": [{"name": "search"}],
            "handoffs": [],
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", improve)
    await optimization.start(db, ex.agent.id, TEST_USER_ID, ex.run.id, uuid.uuid4())
    await optimization.execute_optimization(ex.agent.id, TEST_USER_ID, ex.run.id)
    await db.refresh(ex.project)
    state = optimization.state_of(ex.project)
    assert state["stop_reason"] == "two_round_limit"
    assert len(state["rounds"]) == 2 and all(r["decision"] == "accepted" for r in state["rounds"])
    assert state["best_version_id"] == state["rounds"][1]["version_id"]


@pytest.mark.asyncio
async def test_all_pass_stops_without_model_calls(db, experiment, monkeypatch):
    ex = experiment
    results = deepcopy(ex.run.results_json)
    for result in results:
        result["status"] = "passed"
    ex.run.results_json = results
    await db.commit()

    async def forbidden(*_args):
        raise AssertionError("No model invocation expected")

    monkeypatch.setattr(optimization, "json_call", forbidden)
    await optimization.start(db, ex.agent.id, TEST_USER_ID, ex.run.id, uuid.uuid4())
    await optimization.execute_optimization(ex.agent.id, TEST_USER_ID, ex.run.id)
    await db.refresh(ex.project)
    state = optimization.state_of(ex.project)
    assert state["stop_reason"] == "all_cases_pass" and not state["rounds"]


@pytest.mark.asyncio
async def test_meaningful_equal_pass_gain_and_protected_metric_regression(db, experiment):
    baseline = experiment.run
    candidate = SimpleNamespace(
        **{
            key: deepcopy(getattr(baseline, key))
            for key in (
                "cases_snapshot_json",
                "comparison_json",
                "dataset_hash",
                "eval_set_id",
                "results_json",
            )
        }
    )
    for result in candidate.results_json:
        result["metric_scores"]["task_completion"]["score"] += 0.06
    comparison = compare_runs(baseline, candidate)
    assert comparison["decision"] == "accepted" and comparison["reasons"] == [
        "semantic_metrics_improved"
    ]
    candidate.results_json[0]["metric_scores"]["groundedness"].update(passed=False, score=0.2)
    comparison = compare_runs(baseline, candidate)
    assert comparison["decision"] == "rejected"
    assert "protected_metric_regression" in comparison["reasons"]


def test_schema_does_not_allow_eval_spec_or_case_updates():
    for key in ("eval_spec", "eval_set", "model_params"):
        with pytest.raises(ValueError, match="Extra inputs"):
            PatchProposal.model_validate({"changes": [], key: {}})
