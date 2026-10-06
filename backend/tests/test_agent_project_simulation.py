"""模拟聊天的持久状态、请求幂等及正式实验隔离。"""

import uuid
from copy import deepcopy

import pytest

from app.exceptions import AppError
from app.schemas.agent_project import EvalSetWrite, EvaluationCase
from app.schemas.agent_project_simulation import SimulationCreate, SimulationMessage
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_practice as practice
from app.services import agent_project_service as projects
from app.services import agent_project_simulation as simulation
from app.services.agent_project_executor import SnapshotExecutionUnavailable
from tests import test_agent_project_phase2 as phase2
from tests.test_agent_projects import TEST_USER_ID

db = phase2.db
client = phase2.client
setup_project = phase2.setup_project


@pytest.fixture
async def chat_fixture(db, setup_project, monkeypatch):
    agent = setup_project
    project = await projects.require_project(db, agent.id, TEST_USER_ID)
    version = (await projects.list_versions(db, agent.id, TEST_USER_ID))[0]
    dataset = await evaluation.write_set(
        db,
        agent.id,
        TEST_USER_ID,
        EvalSetWrite(
            name="Chat isolation",
            cases=[
                EvaluationCase.model_validate(
                    {
                        "name": "Normal",
                        "input": "hello",
                        "tags": ["normal"],
                        "initial_state": {"orders": {"one": {"status": "pending"}}},
                        "expected": {"exact_answer": "done"},
                    }
                )
            ],
        ),
        rubric={"requirements_hash": practice.requirements_hash(project)},
    )
    dataset.frozen = True
    await db.commit()
    calls = []

    async def execute(_db, _snapshot, case, _owner):
        calls.append(deepcopy(case))
        state = deepcopy(case["initial_state"])
        state["orders"]["one"]["status"] = case["input"]
        return {
            "output": "done",
            "final_state": state,
            "termination_reason": "completed",
            "tool_trace": [{"name": "update_order", "call_number": len(calls), "result": state}],
        }

    monkeypatch.setattr(simulation, "execute_snapshot", execute)
    return agent, version, dataset, calls


@pytest.mark.asyncio
async def test_persistent_chat_idempotence_reset_and_isolation(db, chat_fixture):
    agent, version, dataset, calls = chat_fixture
    original = deepcopy(dataset.cases_json)
    create = SimulationCreate(request_id=uuid.uuid4(), version_id=version.id)
    chat = await simulation.create(db, agent.id, TEST_USER_ID, create)
    assert (await simulation.create(db, agent.id, TEST_USER_ID, create)).id == chat.id
    message = SimulationMessage(request_id=uuid.uuid4(), content="cancelled")
    await simulation.send(db, agent.id, TEST_USER_ID, chat.id, message)
    replay = await simulation.send(db, agent.id, TEST_USER_ID, chat.id, message)
    assert len(calls) == 1 and len(replay.turns_json) == 1
    restored = await simulation.get(db, agent.id, TEST_USER_ID, chat.id)
    assert restored.state_json["orders"]["one"]["status"] == "cancelled"
    await simulation.send(
        db,
        agent.id,
        TEST_USER_ID,
        chat.id,
        SimulationMessage(request_id=uuid.uuid4(), content="refunded"),
    )
    assert calls[-1]["initial_state"]["orders"]["one"]["status"] == "cancelled"
    assert calls[-1]["_conversation_messages"] and calls[-1]["_call_counts"]["update_order"] == 1
    reset_id = uuid.uuid4()
    reset = await simulation.reset(db, agent.id, TEST_USER_ID, chat.id, reset_id)
    assert reset.id != chat.id and reset.turns_json == []
    assert reset.state_json["orders"]["one"]["status"] == "pending"
    assert (await simulation.reset(db, agent.id, TEST_USER_ID, chat.id, reset_id)).id == reset.id
    await db.refresh(dataset)
    assert dataset.cases_json == original
    assert await evaluation.list_runs(db, agent.id, TEST_USER_ID) == []
    with pytest.raises(AppError, match="simulation_request_conflict"):
        await simulation.send(
            db,
            agent.id,
            TEST_USER_ID,
            chat.id,
            SimulationMessage(request_id=message.request_id, content="other"),
        )
    with pytest.raises(AppError):
        await simulation.get(db, agent.id, uuid.uuid4(), chat.id)


@pytest.mark.asyncio
async def test_chat_failure_keeps_partial_evidence(db, chat_fixture, monkeypatch):
    agent, version, _, _ = chat_fixture
    chat = await simulation.create(
        db, agent.id, TEST_USER_ID, SimulationCreate(request_id=uuid.uuid4(), version_id=version.id)
    )

    async def failed(*_args):
        raise SnapshotExecutionUnavailable(
            "model_call_limit",
            evidence={
                "tool_trace": [{"name": "update_order", "result": "pending"}],
                "model_calls": [{"model": "test-model", "output": "partial"}],
                "final_state": {"orders": {"one": {"status": "retry"}}},
            },
        )

    monkeypatch.setattr(simulation, "execute_snapshot", failed)
    row = await simulation.send(
        db,
        agent.id,
        TEST_USER_ID,
        chat.id,
        SimulationMessage(request_id=uuid.uuid4(), content="hello"),
    )
    assert row.turns_json[0]["evidence"]["termination_reason"] == "model_call_limit"
    assert row.turns_json[0]["evidence"]["model_calls"][0]["output"] == "partial"
    assert row.state_json["orders"]["one"]["status"] == "retry"


@pytest.mark.asyncio
async def test_text_skill_body_is_frozen_and_does_not_read_later_file(
    db, setup_project, tmp_path, monkeypatch
):
    import hashlib

    from app.config import settings
    from app.models.skill import AgentSkillLink
    from app.services.agent_project_mock_tools import frozen_skill_prompt
    from app.skills.service import create_text_skill, update_text_content

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    body = (
        "---\nname: evidence-guide\ndescription: 依据检查指南\n---\n\n"
        "仅使用给定事实，缺少信息时说明边界。"
    )
    skill_id = uuid.uuid4()
    skill = await create_text_skill(
        db,
        user_id=TEST_USER_ID,
        name="evidence-guide",
        slug="evidence-guide",
        description="依据检查指南",
        content=body,
        version="1",
        skill_id=skill_id,
    )
    assert (
        await create_text_skill(
            db,
            user_id=TEST_USER_ID,
            name="evidence-guide",
            slug="evidence-guide",
            description="依据检查指南",
            content=body,
            version="1",
            skill_id=skill_id,
        )
    ).id == skill.id
    db.add(AgentSkillLink(agent_id=setup_project.id, skill_id=skill.id))
    await db.commit()
    frozen = await projects.build_snapshot(db, setup_project)
    assert frozen["agent"]["skill_links"][0]["content"] == body
    assert (
        frozen["agent"]["skill_links"][0]["content_hash"]
        == hashlib.sha256(body.encode()).hexdigest()
    )
    await update_text_content(db, skill=skill, content=body.replace("给定事实", "后来修改的内容"))
    text, limitations = frozen_skill_prompt(frozen["agent"])
    assert body in text and "后来修改的内容" not in text and limitations == []
