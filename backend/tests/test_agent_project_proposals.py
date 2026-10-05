"""Customer-service lifecycle through real services, with controlled provider responses."""

# pyright: reportArgumentType=false
# pyright: reportOptionalSubscript=false

import uuid
from copy import deepcopy

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.schemas.agent_project import EvalSetWrite
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_optimization as optimization
from app.services import agent_project_proposals as proposals
from app.services import agent_project_semantic as semantic
from app.services import agent_project_service as projects
from app.services import builder_project_lifecycle as lifecycle
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from tests import test_agent_project_phase3 as phase3
from tests import test_agent_projects as phase1

db = phase1.db
client = phase1.client
USER = phase1.TEST_USER_ID


@pytest.fixture
async def refund_project(db, client, monkeypatch):
    _, _, agent = await phase1.seed_agent(db)
    agent.name = "Customer Service Agent"
    agent.system_prompt = "Help customers with the refund workflow."
    await db.commit()
    project = await projects.create_project(db, agent.id, USER)
    from app.services import agent_project_llm
    from tests.project_practice_helpers import author_practice, fixed_examinee, fixed_judge

    monkeypatch.setattr(agent_project_llm, "resolve_system_model", fixed_judge)
    monkeypatch.setattr(agent_project_llm, "resolve_examinee_model", fixed_examinee)
    await author_practice(db, agent, USER)
    v1 = (await projects.list_versions(db, agent.id, USER))[0]
    spec = phase3.plan()
    spec["capability_profile"] = {"capabilities": ["workflow"]}
    dataset = await evaluation.write_set(
        db,
        agent.id,
        USER,
        EvalSetWrite(
            name="Refund workflow",
            cases=[
                {
                    "name": "Greeting",
                    "input": "Hello",
                    "expected": {"answer": "Greet politely"},
                    "tags": ["workflow"],
                },
                {
                    "name": "Refund verification",
                    "input": "Refund my order",
                    "expected": {"answer": "Verify identity and order before refund"},
                    "tags": ["workflow"],
                },
            ],
        ),
        rubric=spec,
    )
    monkeypatch.setattr(
        evaluation, "async_session", async_sessionmaker(db.bind, expire_on_commit=False)
    )

    async def execute(_db, snapshot, case, _user):
        good = (
            case["name"] == "Greeting"
            or "Verify identity and order" in snapshot["agent"]["system_prompt"]
        )
        return {
            "output": "Verified response" if good else "Refund without verification",
            "tool_calls": [],
        }

    async def judge(_db, _snapshot, _user, _role, _instruction, payload):
        good = payload["actual_output"] == "Verified response"
        return {
            "metric_scores": {
                m["name"]: {
                    "score": 0.9 if good else 0.2,
                    "passed": good,
                    "reason": "Refund verification evidence",
                }
                for m in payload["metrics"]
            }
        }

    case_id = dataset.cases_json[1]["id"]

    async def analyze(*_args):
        return {
            "analyses": [
                {
                    "case_id": case_id,
                    "category": "instruction_issue",
                    "root_cause": "Verification workflow missing",
                    "evidence": ["/actual_output"],
                    "recommended_target": "instructions",
                    "suggested_fix": "Verify identity and order before refund",
                }
            ],
            "groups": [
                {
                    "case_ids": [case_id],
                    "category": "instruction_issue",
                    "root_cause": "Verification workflow missing",
                    "target": "instructions",
                    "proposed_change": "Add verification workflow",
                }
            ],
        }

    async def propose(_db, _snapshot, _user, _role, _instruction, payload):
        assert payload["bad_cases"] and payload["judge_results"]
        assert payload["capability_profile"]["capabilities"] == ["workflow"]
        return {
            "proposals": [
                {
                    "title": "Add refund verification gate",
                    "what_changes": "Add an identity and order verification step before refunds.",
                    "why_it_may_work": (
                        "The failed case shows the workflow lacks an explicit verification gate."
                    ),
                    "benefits": ["Improves refund safety"],
                    "risks": ["May add one clarification turn"],
                    "targeted_case_ids": [str(case_id)],
                    "affected_capabilities": ["workflow"],
                    "changes": [
                        {
                            "group_index": 0,
                            "target": "instructions",
                            "operation": "append",
                            "content": "Verify identity and order before refund.",
                            "reason": "Add missing verification workflow",
                        }
                    ],
                },
                {
                    "title": "Make verification outcome explicit",
                    "what_changes": (
                        "Require verification before refund and record the result in the response."
                    ),
                    "why_it_may_work": (
                        "An explicit outcome makes the safety condition harder to skip."
                    ),
                    "benefits": ["Makes the workflow auditable"],
                    "risks": ["Response may be slightly longer"],
                    "targeted_case_ids": [str(case_id)],
                    "affected_capabilities": ["workflow"],
                    "changes": [
                        {
                            "group_index": 0,
                            "target": "instructions",
                            "operation": "append",
                            "content": (
                                "Verify identity and order before refund. "
                                "Record the verification result."
                            ),
                            "reason": "Make verification outcome explicit",
                        }
                    ],
                },
            ],
        }

    monkeypatch.setattr(evaluation, "execute_snapshot", execute)
    monkeypatch.setattr(semantic, "json_call", judge)
    monkeypatch.setattr(optimization, "json_call", analyze)
    monkeypatch.setattr(proposals, "json_call", propose)
    await author_practice(db, agent, USER, dataset.id)
    path = f"/api/agents/{agent.id}/project"
    assert (await client.post(f"{path}/eval-sets/{dataset.id}/quality")).json()[
        "quality_report_json"
    ]["status"] == "approved"
    response = await client.post(
        f"{path}/eval-runs",
        json={
            "request_id": str(uuid.uuid4()),
            "version_id": str(v1.id),
            "eval_set_id": str(dataset.id),
        },
    )
    assert response.status_code == 202
    run = await evaluation.get_run(db, agent.id, USER, uuid.UUID(response.json()["id"]))
    assert run.pass_rate == 0.5
    return agent, project, v1, dataset, run, path


@pytest.mark.asyncio
async def test_proposal_review_regression_best_and_immutable_history(client, db, refund_project):
    agent, project, v1, dataset, run, path = refund_project
    before_snapshot, before_results = deepcopy(v1.snapshot_json), deepcopy(run.results_json)
    frozen_cases, frozen_plan = deepcopy(run.cases_snapshot_json), deepcopy(run.comparison_json)
    endpoint = f"{path}/eval-runs/{run.id}/proposals"
    request = {"request_id": str(uuid.uuid4())}
    proposal = (await client.post(endpoint, json=request)).json()
    assert proposal["status"] == "pending" and proposal["version_id"] is None
    assert len(await projects.list_versions(db, agent.id, USER)) == 1
    assert proposal["diffs"][0]["before"] == before_snapshot["agent"]["system_prompt"]
    assert (await client.post(endpoint, json=request)).json() == proposal
    proposal_path = f"{endpoint}/{proposal['id']}"
    assert (await client.post(proposal_path + "/regression", json=request)).status_code == 409
    rejected = (
        await client.post(
            proposal_path + "/decision",
            json={"decision": "rejected", "decision_reason": "Choose a different bounded approach"},
        )
    ).json()
    assert rejected["status"] == "rejected"
    assert (
        await client.post(
            proposal_path + "/decision",
            json={
                "decision": "accepted",
                "decision_reason": "Addresses the observed verification gap",
            },
        )
    ).status_code == 409
    assert len(await projects.list_versions(db, agent.id, USER)) == 1
    second = (await client.post(endpoint, json={"request_id": str(uuid.uuid4())})).json()
    proposal_path = f"{endpoint}/{second['id']}"
    accepted = (
        await client.post(
            proposal_path + "/decision",
            json={
                "decision": "accepted",
                "decision_reason": "Addresses the observed verification gap",
            },
        )
    ).json()
    assert accepted["status"] == "accepted"
    assert (
        await client.post(
            proposal_path + "/decision",
            json={
                "decision": "accepted",
                "decision_reason": "Addresses the observed verification gap",
            },
        )
    ).json() == accepted
    versions = (await client.get(path + "/versions")).json()
    assert len(versions) == 2
    assert versions[0]["created_from"]["optimization_proposal_id"] == second["id"]
    assert versions[0]["parent_version_id"] == str(v1.id)
    assert agent.system_prompt == before_snapshot["agent"]["system_prompt"]
    # A new live project plan must not leak into regression's frozen scoring rule.
    project.eval_spec_json = {"pass_threshold": 0.99}
    await db.commit()
    regression_request = {"request_id": str(uuid.uuid4())}
    response = await client.post(proposal_path + "/regression", json=regression_request)
    assert response.status_code == 202
    regression = await evaluation.get_run(db, agent.id, USER, uuid.UUID(response.json()["id"]))
    assert regression.pass_rate == 1
    assert regression.cases_snapshot_json == frozen_cases
    assert regression.comparison_json["eval_spec"] == frozen_plan["eval_spec"]
    assert (await client.post(proposal_path + "/regression", json=regression_request)).json()[
        "id"
    ] == str(regression.id)
    reports = (await client.get(path + "/evaluation-reports")).json()
    assert list(reports["best_run_ids"].values()) == [str(regression.id)]
    assert reports["reports"][0]["source_run_id"] == str(run.id)
    assert reports["reports"][0]["score"] - reports["reports"][1]["score"] == 0.5
    portfolio = (await client.get(path + "/report")).json()
    assert portfolio["evidence"]["results"]["best_version"] == 2
    assert v1.snapshot_json == before_snapshot
    await db.refresh(run)
    assert run.results_json == before_results
    statuses = [p["status"] for p in proposals.proposals(run)]
    assert statuses.count("accepted") == 1
    assert all(status == "rejected" for status in statuses if status != "accepted")
    assert (
        await client.put(f"{path}/eval-sets/{dataset.id}", json={"name": "Changed", "cases": []})
    ).status_code == 409


@pytest.mark.asyncio
async def test_invalid_proposal_and_foreign_scope_do_not_create_versions(
    client, db, refund_project, monkeypatch
):
    agent, _, _, _, run, path = refund_project

    async def invalid(*_args):
        return {"affected_capabilities": ["invented"], "changes": []}

    monkeypatch.setattr(proposals, "json_call", invalid)
    endpoint = f"{path}/eval-runs/{run.id}/proposals"
    assert (await client.post(endpoint, json={"request_id": str(uuid.uuid4())})).status_code == 422
    assert len(await projects.list_versions(db, agent.id, USER)) == 1
    _, _, other = await phase1.seed_agent(db, user_id=uuid.uuid4())
    await db.commit()
    other_path = f"/api/agents/{other.id}/project/eval-runs/{run.id}/proposals"
    assert (
        await client.post(other_path, json={"request_id": str(uuid.uuid4())})
    ).status_code == 404
    assert (
        await client.post(
            endpoint + f"/{uuid.uuid4()}/decision",
            json={
                "decision": "accepted",
                "decision_reason": "Addresses the observed verification gap",
            },
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_edit_requires_quality_recheck_and_frozen_review_is_unchanged(db, refund_project):
    agent, project, _, dataset, _, _ = refund_project
    frozen_quality = deepcopy(dataset.quality_report_json)
    project.eval_spec_json = {"capability_profile": {"capabilities": ["new-capability"]}}
    await db.commit()
    assert (
        await evaluation.judge_set(db, agent.id, USER, dataset.id)
    ).quality_report_json == frozen_quality
    editable = await evaluation.write_set(
        db,
        agent.id,
        USER,
        EvalSetWrite(
            name="Editable", cases=[{"name": "One", "input": "Hello", "expected": {"answer": "Hi"}}]
        ),
        rubric=phase3.plan(),
    )
    await evaluation.judge_set(db, agent.id, USER, editable.id)
    assert editable.quality_report_json["status"] == "approved"
    await evaluation.write_set(
        db, agent.id, USER, EvalSetWrite(name="Changed", cases=[]), editable.id
    )
    assert editable.quality_report_json is None


@pytest.mark.asyncio
async def test_no_supported_patch_cannot_be_accepted(client, db, refund_project, monkeypatch):
    agent, _, _, _, run, path = refund_project

    async def advice_only(*_args):
        return {
            "proposals": [
                {
                    "title": "No-op advice A",
                    "what_changes": "No supported snapshot change.",
                    "why_it_may_work": "It does not change the snapshot.",
                    "benefits": ["None"],
                    "risks": ["No behavior change"],
                    "targeted_case_ids": [],
                    "affected_capabilities": ["workflow"],
                    "changes": [],
                },
                {
                    "title": "No-op advice B",
                    "what_changes": "Still no supported snapshot change.",
                    "why_it_may_work": "It does not change the snapshot either.",
                    "benefits": ["None"],
                    "risks": ["No behavior change"],
                    "targeted_case_ids": [],
                    "affected_capabilities": ["workflow"],
                    "changes": [],
                },
            ]
        }

    monkeypatch.setattr(proposals, "json_call", advice_only)
    endpoint = f"{path}/eval-runs/{run.id}/proposals"
    response = await client.post(endpoint, json={"request_id": str(uuid.uuid4())})
    assert response.status_code == 422
    assert len(await projects.list_versions(db, agent.id, USER)) == 1


@pytest.mark.asyncio
async def test_builder_bootstrap_automatically_runs_validated_cases(
    db, refund_project, monkeypatch
):
    from sqlalchemy import select

    from app.models.agent_project import AgentProjectEvalRun
    from app.models.builder_session import BuilderSession

    agent, project, v1, _, _, _ = refund_project
    session = BuilderSession(user_id=USER, agent_id=agent.id, user_request="Refund assistant")
    db.add(session)
    await db.flush()
    project.builder_session_id = session.id
    project.eval_spec_json = {**phase3.plan(), "version_id": str(v1.id)}
    await db.commit()
    before_count = len(
        (
            await db.scalars(
                select(AgentProjectEvalRun).where(AgentProjectEvalRun.project_id == project.id)
            )
        ).all()
    )
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(lifecycle, "async_session", factory)
    monkeypatch.setattr(lifecycle, "engine", db.bind)

    original_generate = semantic.generate

    async def generated(
        db, agent_id, user_id, version_id, *, cases=False, dataset_id=None, **kwargs
    ):
        if not cases:
            return await original_generate(db, agent_id, user_id, version_id, **kwargs)
        from app.services.agent_project_practice import requirements_hash

        return await evaluation.write_set(
            db,
            agent_id,
            user_id,
            EvalSetWrite(
                name="Automatic test",
                cases=[
                    {
                        "name": "Automatic case",
                        "input": "hello",
                        "expected": {"exact_answer": "hello"},
                    }
                ],
            ),
            new_id=dataset_id,
            rubric={**phase3.plan(), "requirements_hash": requirements_hash(project)},
        )

    monkeypatch.setattr(semantic, "generate", generated)
    await lifecycle.bootstrap(agent.id, USER)
    await db.refresh(project, ["requirements_json"])
    assert project.requirements_json["bootstrap"]["stage"] == "results"
    assert project.requirements_json["bootstrap"]["error"] is None
    assert (
        len(
            (
                await db.scalars(
                    select(AgentProjectEvalRun).where(AgentProjectEvalRun.project_id == project.id)
                )
            ).all()
        )
        == before_count + 1
    )


@pytest.mark.asyncio
async def test_second_review_uses_v2_and_all_three_versions_are_reported(
    client, db, refund_project, monkeypatch
):
    agent, _, v1, _, run, path = refund_project
    first = (
        await client.post(
            f"{path}/eval-runs/{run.id}/proposals", json={"request_id": str(uuid.uuid4())}
        )
    ).json()
    accepted = await client.post(
        f"{path}/eval-runs/{run.id}/proposals/{first['id']}/decision",
        json={"decision": "accepted", "decision_reason": "Repair the observed verification gap"},
    )
    assert accepted.status_code == 200
    data = accepted.json()
    v2_run = await evaluation.get_run(db, agent.id, USER, uuid.UUID(data["regression_run_id"]))
    assert v2_run.status == "completed"
    first_analyzer = optimization.json_call
    async def second_analyzer(*args):
        value = await first_analyzer(*args)
        ids = [c["case_id"] for c in args[-1]["cases"]]
        value["analyses"] = [{**value["analyses"][0], "case_id": cid,
            "root_cause": "Verification evidence is not explicit", "evidence": ["/metric_scores"]}
            for cid in ids]
        value["groups"][0]["case_ids"] = ids
        return value
    monkeypatch.setattr(optimization, "json_call", second_analyzer)
    first_generator = proposals.json_call

    async def second_generator(*args):
        value = await first_generator(*args)
        for item in value["proposals"]:
            for change in item["changes"]:
                change["content"] += " Explain the verification evidence."
        return value

    monkeypatch.setattr(proposals, "json_call", second_generator)
    second = (
        await client.post(
            f"{path}/eval-runs/{v2_run.id}/proposals", json={"request_id": str(uuid.uuid4())}
        )
    ).json()
    assert "source_version_id" in second, second
    assert second["source_version_id"] == str(v2_run.version_id)
    response = await client.post(
        f"{path}/eval-runs/{v2_run.id}/proposals/{second['id']}/decision",
        json={"decision": "accepted", "decision_reason": "Make the verified outcome explicit"},
    )
    assert response.status_code == 200
    v3_run = await evaluation.get_run(
        db, agent.id, USER, uuid.UUID(response.json()["regression_run_id"])
    )
    versions = await projects.list_versions(db, agent.id, USER)
    assert [v.version_number for v in versions] == [3, 2, 1]
    assert versions[0].parent_version_id == v2_run.version_id
    assert v3_run.cases_snapshot_json == run.cases_snapshot_json
    assert (
        v3_run.comparison_json["role_configurations"] == run.comparison_json["role_configurations"]
    )
    replay = await proposals.regression(
        db, agent.id, USER, v2_run.id, uuid.UUID(second["id"]), uuid.uuid4()
    )
    assert replay.id == v3_run.id
    report = (await client.get(path + "/report")).json()["evidence"]
    assert {
        (c["source_version"], c["target_version"]) for c in report["results"]["comparisons"]
    } == {(1, 2), (2, 3), (1, 3)}
    assert report["results"]["best_version"] == 2  # 同分保留较早版本。
    assert v1.snapshot_json["agent"]["system_prompt"] == agent.system_prompt
