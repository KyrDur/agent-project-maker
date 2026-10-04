"""Student contribution/provenance and P1 reliability contracts, no live providers."""

# pyright: reportArgumentType=false
# pyright: reportOptionalMemberAccess=false
# pyright: reportOptionalSubscript=false
from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash
from app.models.agent_project import AgentProjectEvalRun
from app.schemas.agent_project_learning import (
    BriefConfirm,
    BriefGenerate,
    CaseReview,
    HoldoutGenerate,
    RepeatRequest,
    ValidationRequest,
)
from app.services import agent_project_learning as learning
from app.services import agent_project_reliability as reliability
from app.services import agent_project_service as projects
from app.services.agent_project_optimization import terminal_semantic
from tests import test_agent_project_phase4 as phase4
from tests.test_agent_project_phase3 import plan

db = phase4.db
client = phase4.client
experiment = phase4.experiment
USER = phase4.TEST_USER_ID
CONTENT = {
    "audience": "Students",
    "problem": "Answer questions from course evidence",
    "workflow": "Read evidence, verify and answer",
    "success_criteria": ["Cite supplied evidence", "Say when information is missing"],
}


@pytest.fixture
async def student(db, experiment, monkeypatch):
    ex = experiment
    ex.dataset.rubric_json = {
        **plan(),
        "version_id": str(ex.version.id),
        "config_hash": ex.version.config_hash,
        "purpose": "development",
        "business_contract": {"content": CONTENT},
        "capability_profile": {"capabilities": ["conversation"]},
    }
    await db.commit()

    async def generate(*args):
        return deepcopy(CONTENT)

    monkeypatch.setattr(learning, "json_call", generate)
    return ex


@pytest.mark.asyncio
async def test_confirm_records_edits_invalidates_plan_and_preserves_version(db, student):
    ex = student
    frozen = deepcopy(ex.version.snapshot_json)
    draft = await learning.generate_brief(
        db, ex.agent.id, USER, BriefGenerate(version_id=ex.version.id)
    )
    assert not (ex.project.requirements_json or {}).get("learning_brief")
    changed = {**CONTENT, "problem": "Answer course questions and flag missing evidence"}
    result = await learning.confirm_brief(
        db,
        ex.agent.id,
        USER,
        BriefConfirm(version_id=ex.version.id, draft_hash=draft["draft_hash"], content=changed),
    )
    assert result["contribution"] == "user_edited"
    assert ex.project.eval_spec_json is None
    assert ex.version.snapshot_json == frozen
    assert ex.dataset.frozen
    await learning.confirm_brief(
        db,
        ex.agent.id,
        USER,
        BriefConfirm(version_id=ex.version.id, draft_hash=draft["draft_hash"], content=changed),
    )
    assert len(ex.project.requirements_json["brief_history"]) == 1


@pytest.mark.asyncio
async def test_stale_brief_and_foreign_project_rejected_before_model(db, student, monkeypatch):
    ex = student
    draft = await learning.generate_brief(
        db, ex.agent.id, USER, BriefGenerate(version_id=ex.version.id)
    )
    with pytest.raises(AppError, match="learning_draft_changed"):
        await learning.confirm_brief(
            db,
            ex.agent.id,
            USER,
            BriefConfirm(version_id=ex.version.id, draft_hash="0" * 64, content=CONTENT),
        )

    async def unexpected(*args):
        pytest.fail("Foreign user must not invoke models")

    monkeypatch.setattr(learning, "json_call", unexpected)
    with pytest.raises(AppError):
        await learning.generate_brief(
            db, ex.agent.id, uuid.uuid4(), BriefGenerate(version_id=ex.version.id)
        )
    assert draft["status"] == "draft"


@pytest.mark.asyncio
async def test_interview_refs_validated_cached_and_invalidated_by_judgment(
    db, student, monkeypatch
):
    ex = student
    calls = []

    async def answer(*args):
        payload = args[-1]
        calls.append(payload)
        return {
            "short_intro": "Platform supported my project.",
            "long_intro": "Mock tests only.",
            "answers": [
                {
                    "topic": topic,
                    "answer": "Not verified beyond the recorded test.",
                    "evidence_refs": ["project", "boundaries"],
                }
                for topic in ["contribution", "failure", "decision", "results", "next_step"]
            ],
        }

    monkeypatch.setattr(learning, "json_call", answer)
    request = BriefGenerate(version_id=ex.version.id)
    material = await learning.interview(db, ex.agent.id, USER, request)
    assert material["status"] == "ai_draft"
    assert material["evidence"]["boundaries"]["production_verified"] is False
    assert material["evidence_hash"] == canonical_json_hash(material["evidence"])
    assert await learning.interview(db, ex.agent.id, USER, request) == material
    assert len(calls) == 1
    result = ex.run.results_json[0]
    await learning.review_case(
        db,
        ex.agent.id,
        USER,
        ex.run.id,
        uuid.UUID(result["case_id"]),
        CaseReview(passed=False, reason="The source citation is missing."),
    )
    updated = await learning.interview(db, ex.agent.id, USER, request)
    assert updated["evidence_hash"] != material["evidence_hash"]
    assert len(calls) == 2
    assert (await reliability.summary(db, ex.agent.id, USER, ex.version.id))["calibration"][
        "disagreements"
    ] == 1


@pytest.mark.asyncio
async def test_fabricated_interview_references_never_saved(db, student, monkeypatch):
    async def invalid(*args):
        return {
            "short_intro": "Draft",
            "long_intro": "Draft",
            "answers": [
                {"topic": topic, "answer": "Draft", "evidence_refs": ["invented_run"]}
                for topic in ["contribution", "failure", "decision", "results", "next_step"]
            ],
        }

    monkeypatch.setattr(learning, "json_call", invalid)
    with pytest.raises(AppError, match="learning_interview_invalid_evidence"):
        await learning.interview(
            db, student.agent.id, USER, BriefGenerate(version_id=student.version.id)
        )
    assert not (student.project.report_json or {}).get("learning_interviews")


@pytest.mark.asyncio
async def test_repeat_is_atomic_replayable_and_pins_same_inputs_and_judge(db, student):
    ex = student
    request = RepeatRequest(request_id=uuid.uuid4(), repetitions=3)
    rows = await reliability.repeat(db, ex.agent.id, USER, ex.run.id, request)
    assert len(rows) == 3
    replay = await reliability.repeat(db, ex.agent.id, USER, ex.run.id, request)
    assert [r.id for r in rows] == [r.id for r in replay]
    for row in rows:
        assert row.dataset_hash == ex.run.dataset_hash
        assert row.cases_snapshot_json == ex.run.cases_snapshot_json
        assert row.comparison_json["roles"] == ex.run.comparison_json["roles"]
        assert "proposals" not in row.comparison_json
    with pytest.raises(AppError, match="evaluation_request_conflict"):
        await reliability.repeat(
            db,
            ex.agent.id,
            USER,
            ex.run.id,
            RepeatRequest(request_id=request.request_id, repetitions=2),
        )


def reserved_cases():
    return {
        "name": "New reserved cases",
        "cases": [
            {
                "id": str(uuid.uuid4()),
                "name": f"Case {i}",
                "input": f"New course question {i}",
                "expected": {"answer": "Only answer using the supplied course note."},
                "tags": ["conversation"],
                "mock_tool_data": {},
            }
            for i in range(20)
        ],
    }


@pytest.mark.asyncio
async def test_reserved_generation_uses_baseline_contract_and_freezes_cases(
    db, student, monkeypatch
):
    ex = student
    calls = []

    async def cases(*args):
        calls.append(args[-1])
        return reserved_cases()

    monkeypatch.setattr(reliability, "json_call", cases)
    request = HoldoutGenerate(development_set_id=ex.dataset.id, request_id=uuid.uuid4())
    dataset = await reliability.generate_holdout(db, ex.agent.id, USER, request)
    assert dataset.frozen and dataset.quality_report_json["status"] == "approved"
    assert dataset.rubric_json["purpose"] == "holdout"
    assert "failures" not in calls[0] and "candidate_snapshot" not in calls[0]
    assert calls[0]["business_contract"] == {"content": CONTENT}
    assert (await reliability.generate_holdout(db, ex.agent.id, USER, request)).id == dataset.id
    assert len(calls) == 1
    with pytest.raises(AppError):
        await phase4.evaluation.write_set(
            db, ex.agent.id, USER, phase4.EvalSetWrite.model_validate(reserved_cases()), dataset.id
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", ["development", "within_set"])
async def test_reserved_overlap_rejected(db, student, monkeypatch, duplicate):
    data = reserved_cases()
    if duplicate == "development":
        data["cases"][0]["input"] = "  SUMMARIZE   THE PROJECT. "
    else:
        data["cases"][1]["input"] = data["cases"][0]["input"]

    async def cases(*args):
        return data

    monkeypatch.setattr(reliability, "json_call", cases)
    with pytest.raises(AppError, match="reliability_holdout_overlap"):
        await reliability.generate_holdout(
            db,
            student.agent.id,
            USER,
            HoldoutGenerate(development_set_id=student.dataset.id, request_id=uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_paired_validation_exactly_six_runs_same_judge_and_not_optimizer_input(
    db, student, monkeypatch
):
    ex = student

    async def cases(*args):
        return reserved_cases()

    monkeypatch.setattr(reliability, "json_call", cases)
    dataset = await reliability.generate_holdout(
        db,
        ex.agent.id,
        USER,
        HoldoutGenerate(development_set_id=ex.dataset.id, request_id=uuid.uuid4()),
    )
    candidate = await projects.append_snapshot_version(
        db,
        ex.project,
        deepcopy(ex.version.snapshot_json),
        parent_id=ex.version.id,
        request_id=uuid.uuid4(),
        summary="Test candidate",
    )
    await db.commit()
    request = ValidationRequest(
        request_id=uuid.uuid4(),
        repetitions=3,
        baseline_run_id=ex.run.id,
        candidate_version_id=candidate.id,
        holdout_set_id=dataset.id,
    )
    rows = await reliability.validate(db, ex.agent.id, USER, request)
    assert len(rows) == 6 and len({r.id for r in rows}) == 6
    assert len([r for r in rows if r.version_id == candidate.id]) == 3
    assert len({canonical_json_hash(r.comparison_json["roles"]["judge"]) for r in rows}) == 1
    assert len({r.dataset_hash for r in rows}) == 1
    assert all(r.comparison_json["purpose"] == "holdout" for r in rows)
    assert [r.id for r in await reliability.validate(db, ex.agent.id, USER, request)] == [
        r.id for r in rows
    ]
    for row in rows:
        with pytest.raises(AppError, match="reliability_holdout_not_for_optimization"):
            terminal_semantic(row)
    stored = list(
        (
            await db.scalars(
                select(AgentProjectEvalRun).where(AgentProjectEvalRun.eval_set_id == dataset.id)
            )
        ).all()
    )
    assert len(stored) == 6  # no extra anchor consumes model quota
    report = await reliability.summary(db, ex.agent.id, USER, candidate.id)
    assert report["trials"][0]["kind"] == "validation"
    assert all(v["mean"] is None for v in report["trials"][0]["versions"].values())


@pytest.mark.asyncio
async def test_descriptive_spread_and_incomplete_exclusion(student):
    source = student.run
    rows = [deepcopy(source) for _ in range(3)]
    rows[-1].status = "failed"
    result = reliability.summarize_runs(rows)
    assert result["scheduled"] == 3 and result["completed"] == 2 and result["incomplete"] == 1
    assert result["mean"] == 0.75 and result["stddev"] == 0
    rows[-1].status = "pending"
    rows[-1].metrics_json = {"total": 20}
    assert reliability.summarize_runs(rows)["mean"] == 0.75
    rows[1].dataset_hash = "different"
    assert reliability.summarize_runs(rows)["mean"] is None


@pytest.mark.asyncio
async def test_router_validation_masks_request_and_ownership(client, student):
    path = f"/api/agents/{student.agent.id}/project"
    bad = await client.post(
        f"{path}/learning/brief/confirm",
        json={
            "version_id": str(student.version.id),
            "draft_hash": "0" * 64,
            "content": {**CONTENT, "success_criteria": [""]},
        },
    )
    assert bad.status_code == 422 and "Answer questions" not in bad.text
    response = await client.post(
        f"{path}/eval-runs/{uuid.uuid4()}/repeat",
        json={"request_id": str(uuid.uuid4()), "repetitions": 3},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reliability_report_uses_numeric_records_without_private_review_reasons(db, student):
    from app.services import agent_project_portfolio as portfolio

    ex = student
    await reliability.repeat(
        db, ex.agent.id, USER, ex.run.id, RepeatRequest(request_id=uuid.uuid4(), repetitions=2)
    )
    await learning.review_case(
        db,
        ex.agent.id,
        USER,
        ex.run.id,
        uuid.UUID(ex.run.results_json[0]["case_id"]),
        CaseReview(passed=False, reason="private-student-review-marker"),
    )
    original_results = deepcopy(ex.run.results_json)
    report = await portfolio.report(db, ex.agent.id, USER)
    assert report["evidence"]["reliability"][0]["calibration"]["reviewed"] == 1
    assert report["evidence"]["reliability"][0]["calibration"]["disagreements"] == 1
    assert report["sections"][-1]["title"] == "额外验证与评分复核"
    assert "private-student-review-marker" not in str(report)
    assert ex.run.results_json == original_results
    assert report["evidence"]["results"]["best_version"] == 1


@pytest.mark.asyncio
async def test_validation_rolls_back_anchor_when_batch_creation_fails(db, student, monkeypatch):
    ex = student

    async def cases(*args):
        return reserved_cases()

    monkeypatch.setattr(reliability, "json_call", cases)
    dataset = await reliability.generate_holdout(
        db,
        ex.agent.id,
        USER,
        HoldoutGenerate(development_set_id=ex.dataset.id, request_id=uuid.uuid4()),
    )
    candidate = await projects.append_snapshot_version(
        db,
        ex.project,
        deepcopy(ex.version.snapshot_json),
        parent_id=ex.version.id,
        request_id=uuid.uuid4(),
        summary="Test candidate",
    )
    await db.commit()
    dataset_id, agent_id, baseline_id, candidate_id = (
        dataset.id,
        ex.agent.id,
        ex.run.id,
        candidate.id,
    )

    async def unavailable(*args):
        raise RuntimeError("simulated batch failure before commit")

    monkeypatch.setattr(reliability, "create_trials", unavailable)
    with pytest.raises(RuntimeError, match="simulated batch failure"):
        await reliability.validate(
            db,
            agent_id,
            USER,
            ValidationRequest(
                request_id=uuid.uuid4(),
                repetitions=3,
                baseline_run_id=baseline_id,
                candidate_version_id=candidate_id,
                holdout_set_id=dataset_id,
            ),
        )
    await db.rollback()
    assert not list(
        (
            await db.scalars(
                select(AgentProjectEvalRun).where(AgentProjectEvalRun.eval_set_id == dataset_id)
            )
        ).all()
    )
