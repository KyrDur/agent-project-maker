"""Developer counterexamples for requirement/Skill conflicts; no paid model calls."""

import hashlib
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from app.exceptions import AppError
from app.models.agent import Agent
from app.schemas.builder import BuilderStatus, ToolRecommendation
from app.services import builder_consistency as consistency
from app.services.builder_service import confirm_build, create_session
from tests.conftest import TEST_USER_ID
from tests.test_builder_service import _seed_user

REQUIREMENTS = {
    "goal": "将工作记录写成周报",
    "inputs": "用户提供的工作记录",
    "deliverables": "本周完成、风险、下周计划、待确认四段",
    "business_rules": "只写草稿，不发送，不编造事实",
    "success_conditions": "缺少信息时明确追问",
}
CONFIG = {
    "system_prompt": "只写四段周报草稿；缺少信息时追问，不发送，不编造事实。",
    "review_tools": [
        {
            "tool_name": "weekly",
            "kind": "generated_skill",
            "description": "周报指南",
            "content": "只输出本周完成、风险、下周计划三段。",
        }
    ],
}


def review(sources, conflict=False):
    return {
        "reviewed_sources": [k for k in sources if not k.startswith("requirements/")],
        "requirement_reviews": [
            {
                "field": field,
                "supported": not (conflict and field == "deliverables"),
                "reason": "三段指南与四段需求冲突"
                if conflict and field == "deliverables"
                else "一致",
                "evidence": [
                    {"reference": "requirements/" + field, "quote": text},
                    {"reference": "system_prompt", "quote": sources["system_prompt"]},
                    *(
                        [
                            {
                                "reference": "skills/weekly/content",
                                "quote": sources["skills/weekly/content"],
                            }
                        ]
                        if conflict and field == "deliverables"
                        else []
                    ),
                ],
            }
            for field, text in REQUIREMENTS.items()
        ],
    }


@pytest.fixture
def fixed_judge(monkeypatch):
    calls = []

    async def roles(*args):
        return {"judge_optimizer": {"model_name": "fixed-test", "credential_id": "dummy"}}

    async def judge(*args):
        payload = args[-1]
        calls.append(payload)
        return review(payload["builder_consistency_sources"], conflict=True)

    monkeypatch.setattr(consistency, "role_configurations", roles)
    monkeypatch.setattr(consistency, "json_call", judge)
    return calls


@pytest.mark.asyncio
async def test_shared_skill_body_reaches_prompt_generation(db, monkeypatch):
    from types import SimpleNamespace

    from app.agent_runtime.builder.sub_agents.prompt_generator import _format_tools
    from app.services import builder_service

    async def resolve(*args):
        return (
            [],
            [],
            [SimpleNamespace(name="weekly", content_hash=hashlib.sha256(b"three").hexdigest())],
        )

    async def content(*args):
        return "three"

    monkeypatch.setattr(builder_service, "_resolve_tools", resolve)
    monkeypatch.setattr(consistency, "read_text_content", content)
    items = await consistency.generation_tools(
        db,
        TEST_USER_ID,
        [
            ToolRecommendation(
                tool_name="weekly", kind="skill", description="metadata", reason="chosen"
            )
        ],
    )
    assert "three" in _format_tools(items)


@pytest.mark.asyncio
async def test_four_section_requirement_rejects_three_section_skill(db, fixed_judge):
    report = await consistency.review_configuration(db, TEST_USER_ID, REQUIREMENTS, CONFIG)
    assert report["status"] == "rejected"
    assert report["requirement_reviews"][2]["supported"] is False
    assert "三段" in fixed_judge[0]["builder_consistency_sources"]["skills/weekly/content"]


@pytest.mark.parametrize(
    "invalid", ["missing_field", "missing_skill", "fake_quote", "missing_requirement"]
)
def test_missing_or_invented_review_evidence_is_an_error(invalid):
    sources = consistency.review_sources(REQUIREMENTS, CONFIG)
    raw = review(sources)
    if invalid == "missing_field":
        raw["requirement_reviews"].pop()
    elif invalid == "missing_skill":
        raw["reviewed_sources"].remove("skills/weekly/content")
    elif invalid == "fake_quote":
        raw["requirement_reviews"][0]["evidence"][1]["quote"] = "不存在的证据"
    else:
        raw["requirement_reviews"][0]["evidence"][0]["reference"] = "requirements/inputs"
    with pytest.raises(ValueError, match="Incomplete|reviewed|evidence"):
        consistency.validate_review(raw, sources)


@pytest.mark.asyncio
async def test_confirmation_blocks_creation_and_preserves_conflict(db, fixed_judge):
    await _seed_user(db)
    await db.commit()
    session = await create_session(db, TEST_USER_ID, "周报")
    session.intent = {"project_requirements": REQUIREMENTS}
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "system_prompt": CONFIG["system_prompt"],
        "generated_skills": [{**CONFIG["review_tools"][0], "reason": "用户选择"}],
    }
    await db.commit()
    with pytest.raises(AppError) as failure:
        await confirm_build(db, session)
    assert failure.value.code == "builder_consistency_rejected"
    assert await db.scalar(select(func.count()).select_from(Agent)) == 0
    assert session.agent_id is None
    assert session.status == BuilderStatus.PREVIEW
    saved = session.draft_config
    assert saved is not None
    assert saved["consistency_review"]["status"] == "rejected"
    assert saved["generated_skills"][0]["content"] == CONFIG["review_tools"][0]["content"]


@pytest.mark.asyncio
async def test_approval_cache_invalidates_after_content_change(db, fixed_judge, monkeypatch):
    async def judge(*args):
        fixed_judge.append(args[-1])
        return review(args[-1]["builder_consistency_sources"])

    monkeypatch.setattr(consistency, "json_call", judge)
    report = await consistency.review_configuration(db, TEST_USER_ID, REQUIREMENTS, CONFIG)
    await consistency.review_configuration(db, TEST_USER_ID, REQUIREMENTS, CONFIG, report)
    assert len(fixed_judge) == 1
    changed = deepcopy(CONFIG)
    changed["review_tools"][0]["content"] += "自动发送。"
    await consistency.review_configuration(db, TEST_USER_ID, REQUIREMENTS, changed, report)
    assert len(fixed_judge) == 2


@pytest.mark.asyncio
async def test_judge_unavailable_never_approves(db, fixed_judge, monkeypatch):
    async def judge(*args):
        raise RuntimeError("provider error")

    monkeypatch.setattr(consistency, "json_call", judge)
    report = await consistency.review_configuration(db, TEST_USER_ID, REQUIREMENTS, CONFIG)
    assert report["status"] == "error"
    assert report["error"] == "builder_consistency_unavailable"


@pytest.mark.asyncio
async def test_skill_conflict_retries_capabilities_before_prompt_approval(monkeypatch):
    from app.agent_runtime.builder_v3.consistency_context import builder_consistency_scope
    from app.agent_runtime.builder_v3.nodes import phase5_prompt
    from app.agent_runtime.builder_v3.nodes.failure_retry import failure_wait

    sources = consistency.review_sources(REQUIREMENTS, CONFIG)
    report = {"status": "rejected", **review(sources, conflict=True)}

    class FixedReview:
        async def prepare_tools(self, owner, tools):
            return tools

        async def review(self, owner, requirements, prompt, tools):
            return report

    async def prompt(*args):
        return CONFIG["system_prompt"]

    monkeypatch.setattr(phase5_prompt, "generate_system_prompt", prompt)
    with builder_consistency_scope(FixedReview()):
        result = await phase5_prompt.phase5_generate_prompt(
            {
                "user_id": str(TEST_USER_ID),
                "intent": {
                    "agent_name": "周报",
                    "agent_description": "写周报草稿",
                    "primary_task_type": "写作",
                    "use_cases": ["整理工作记录"],
                    "project_requirements": REQUIREMENTS,
                },
            }
        )
    assert result["current_phase"] == 3
    assert result["consistency_reviews"] == [report]
    assert "三段" in result["last_revision_message"]
    assert result["error_message"]
    assert "pending_tool_call_id" not in result
    monkeypatch.setattr(
        "app.agent_runtime.builder_v3.nodes.failure_retry.interrupt", lambda _: True
    )
    assert failure_wait({"current_phase": result["current_phase"]}).goto == "phase3_recommend_tools"
