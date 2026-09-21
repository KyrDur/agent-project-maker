# pyright: reportArgumentType=false
# pyright: reportOptionalSubscript=false

import uuid
from copy import deepcopy
from datetime import timedelta

import pytest

from app.models.agent_project import AgentProjectEvalRun, utcnow
from app.schemas.agent_project import EvalRunCreate, EvalSetWrite, VersionCreate
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_optimization as optimization
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services.agent_project_report import report_for_run
from tests import test_agent_project_phase2 as phase2
from tests import test_agent_project_phase3 as phase3
from tests import test_agent_projects as phase1

db = phase1.db
client = phase1.client
setup_project = phase2.setup_project


def run_record(project_id, version_id, set_id, score=0.5, **kwargs):
    now = utcnow()
    return AgentProjectEvalRun(
        id=uuid.uuid4(),
        project_id=project_id,
        version_id=version_id,
        eval_set_id=set_id,
        status="completed",
        pass_rate=score,
        created_at=now,
        completed_at=now,
        dataset_hash="frozen-data",
        cases_snapshot_json=[{"id": "a"}, {"id": "b"}],
        metrics_json={
            "total": 2,
            "passed": 1,
            "failed": 1,
            "errored": 0,
            "scoring": "semantic_v1",
            "metric_scores": {"task_completion": {"score": 0.85, "evaluated_cases": 2}},
        },
        results_json=[
            {"case_id": "a", "name": "Pass", "status": "passed"},
            {
                "case_id": "b",
                "name": "Failure",
                "status": "failed",
                "metric_scores": {
                    "task_completion": {"score": 0.2, "passed": False, "reason": "Missing answer"}
                },
            },
        ],
        comparison_json={
            "eval_spec": {"pass_threshold": 0.7},
            "roles": {"judge": {"model_name": "test"}},
        },
        **kwargs,
    )


def test_report_uses_frozen_results_without_mutation():
    run = run_record(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    before = deepcopy(run.results_json)
    report = report_for_run(run)
    assert report.score == 0.5
    assert report.metrics == {"task_completion": 0.85}
    assert report.bad_case_count == 1
    assert report.bad_cases[0].reasons == ["Missing answer"]
    assert run.results_json == before
    run.bad_cases_json = [
        {
            "case_id": "b",
            "root_cause": "Unclear instructions",
            "suggested_fix": "Clarify answer requirements",
        }
    ]
    analyzed = report_for_run(run)
    assert analyzed.bad_cases[0].reasons == ["Unclear instructions"]
    assert analyzed.optimization_suggestions == ["Clarify answer requirements"]
    assert analyzed.score == report.score


@pytest.mark.parametrize("change", ["failed", "partial", "no_completion"])
def test_invalid_runs_have_no_quality_score(change):
    run = run_record(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    if change == "failed":
        run.status = "failed"
    elif change == "partial":
        run.results_json = run.results_json[:1]
    else:
        run.completed_at = None
    assert report_for_run(run).score is None


@pytest.mark.parametrize("change", ["dataset", "rubric", "judge"])
def test_comparison_requires_same_frozen_criteria(change):
    run = run_record(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    before = report_for_run(run).comparison_key
    if change == "dataset":
        run.dataset_hash = "other-data"
    elif change == "rubric":
        run.comparison_json["eval_spec"]["pass_threshold"] = 0.8
    else:
        run.comparison_json["roles"]["judge"]["model_name"] = "other-judge"
    assert report_for_run(run).comparison_key != before


@pytest.mark.asyncio
async def test_history_best_ties_and_ownership(client, db, setup_project):
    agent = setup_project
    user_id = phase1.TEST_USER_ID
    project = await projects.require_project(db, agent.id, user_id)
    v1 = (await projects.list_versions(db, agent.id, user_id))[0]
    dataset = await phase2.dataset(db, agent)
    agent.system_prompt = "Improved instructions"
    await db.commit()
    v2 = (
        await projects.create_version(db, agent.id, user_id, VersionCreate(request_id=uuid.uuid4()))
    ).version
    original_snapshot = deepcopy(v1.snapshot_json)
    first = run_record(project.id, v1.id, dataset.id, 0)
    second = run_record(project.id, v2.id, dataset.id, 1)
    tie = run_record(project.id, v1.id, dataset.id, 1)
    tie.created_at = second.created_at + timedelta(seconds=1)
    failed = run_record(project.id, v1.id, dataset.id, 1)
    failed.status = "failed"
    db.add_all([first, second, tie, failed])
    await db.commit()
    path = f"/api/agents/{agent.id}/project/evaluation-reports"
    response = await client.get(path)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["reports"]) == 4
    assert list(payload["best_run_ids"].values()) == [str(second.id)]
    assert payload["active"] is False
    assert (await client.get(path)).json() == payload
    assert v1.snapshot_json == original_snapshot
    assert first.pass_rate == 0
    assert (
        await client.get(f"/api/agents/{uuid.uuid4()}/project/evaluation-reports")
    ).status_code == 404
    _, _, other = await phase1.seed_agent(db, user_id=uuid.uuid4())
    await db.commit()
    await projects.create_project(db, other.id, other.user_id)
    assert (
        await client.get(f"/api/agents/{other.id}/project/evaluation-reports")
    ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("semantic_scoring", [False, True])
async def test_evaluation_to_report_to_new_version_loop(
    client,
    db,
    setup_project,
    monkeypatch,
    semantic_scoring,
):
    agent = setup_project
    user_id = phase1.TEST_USER_ID
    v1 = (await projects.list_versions(db, agent.id, user_id))[0]
    dataset = await evaluation.write_set(
        db,
        agent.id,
        user_id,
        EvalSetWrite(
            name="Demo",
            cases=[
                {
                    "name": "Answer",
                    "input": "Hello",
                    "expected": {"answer": "Hello back", "exact_answer": "Hello back"},
                }
            ],
        ),
        rubric=phase3.plan() if semantic_scoring else None,
    )
    await evaluation.judge_set(db, agent.id, user_id, dataset.id)
    assert dataset.quality_report_json["status"] == "approved"

    async def execute(_db, snapshot, _case, _user):
        return {
            "output": "Hello back" if snapshot["agent"]["system_prompt"] == "Improved" else "Wrong",
            "tool_calls": [],
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)

    async def judge(_db, _snapshot, _user, _role, _instruction, payload):
        passed = payload["actual_output"] == "Hello back"
        return {
            "metric_scores": {
                metric["name"]: {
                    "score": 0.9 if passed else 0.2,
                    "passed": passed,
                    "reason": "Observed answer",
                }
                for metric in payload["metrics"]
            }
        }

    monkeypatch.setattr(semantic, "json_call", judge)
    first = await evaluation.create_run(
        db,
        agent.id,
        user_id,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=v1.id, eval_set_id=dataset.id),
    )
    path = f"/api/agents/{agent.id}/project/evaluation-reports"
    assert (await client.get(path)).json()["active"] is True
    await evaluation.execute_run(first.id, agent.id, user_id)
    before = (await client.get(path)).json()["reports"][0]
    assert before["score"] == 0
    assert before["bad_case_count"] == 1
    if semantic_scoring:
        assert before["metrics"]["task_completion"] == 0.2
        case_id = dataset.cases_json[0]["id"]

        async def analyze(*_args):
            return {
                "analyses": [
                    {
                        "case_id": case_id,
                        "category": "instruction_issue",
                        "root_cause": "Answer requirement unclear",
                        "evidence": ["/actual_output"],
                        "recommended_target": "instructions",
                        "suggested_fix": "Clarify instructions",
                    }
                ],
                "groups": [
                    {
                        "case_ids": [case_id],
                        "category": "instruction_issue",
                        "root_cause": "Answer requirement unclear",
                        "target": "instructions",
                        "proposed_change": "Clarify instructions",
                    }
                ],
            }

        monkeypatch.setattr(optimization, "json_call", analyze)
        await optimization.analyze(db, agent.id, user_id, first.id)
        before = (await client.get(path)).json()["reports"][0]
        assert before["optimization_suggestions"] == ["Clarify instructions"]
        assert before["score"] == 0
    assert dataset.frozen
    agent.system_prompt = "Improved"
    await db.commit()
    v2 = (
        await projects.create_version(db, agent.id, user_id, VersionCreate(request_id=uuid.uuid4()))
    ).version
    second = await evaluation.create_run(
        db,
        agent.id,
        user_id,
        EvalRunCreate(request_id=uuid.uuid4(), version_id=v2.id, eval_set_id=dataset.id),
    )
    await evaluation.execute_run(second.id, agent.id, user_id)
    payload = (await client.get(path)).json()
    assert payload["reports"][0]["score"] == 1
    assert payload["reports"][1] == before
    assert payload["best_run_ids"][before["comparison_key"]] == str(second.id)
    assert payload["active"] is False
    assert v1.snapshot_json["agent"]["system_prompt"] == "Be helpful"
