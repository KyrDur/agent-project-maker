"""Builder v3 resume wire 保护（ADR-012 §Phase 5）。

frontend ``decisionToBuilderResponse`` adapter retire 后，由 backend router
负责将标准 ``Decision[]`` → builder native shape (dict | str)，
作为 clean break 设计的回归保护。

验证4个维度：
1. Router contract — 标准 ``decisions`` payload 返回 200
2. Clean break 保护 — legacy ``response`` 字段返回 422（Pydantic ``extra='forbid'``）
3. Helper 映射 — ``decisions_to_builder_response`` 5种 case 单元测试
4. Phase 6 JSON.parse fallback — frontend 以 dict 意图 JSON.stringify 后的
   string，``phase6_choice_wait`` / ``phase6_image_approval`` 也能正常分支
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.builder_session import BuilderSession
from app.schemas.builder import BuilderStatus
from app.schemas.conversation import Decision
from app.services import builder_service
from tests.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _seed_session(db: AsyncSession) -> uuid.UUID:
    session = BuilderSession(
        user_id=TEST_USER_ID,
        user_request="phase5 wire 保护用 session",
        status=BuilderStatus.BUILDING,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session.id


def _capture_resume_payload():
    """捕获 run_v3_resume_stream 调用参数的 fake（SSE stream mock）。"""
    captured: list[dict] = []

    async def fake(**kwargs):
        captured.append(kwargs)
        # 空 SSE stream — 只验证通过 router
        yield "event: message_end\ndata: {}\n\n"

    return captured, fake


# ---------------------------------------------------------------------------
# A. Helper unit — decisions_to_builder_response
# ---------------------------------------------------------------------------


class TestDecisionsToBuilderResponse:
    def test_approve_maps_to_approved_dict(self):
        out = builder_service.decisions_to_builder_response([Decision(type="approve")])
        assert out == {"approved": True}

    def test_reject_with_message_carries_revision_message(self):
        out = builder_service.decisions_to_builder_response(
            [Decision(type="reject", message="重新命名")]
        )
        assert out == {"approved": False, "revision_message": "重新命名"}

    def test_reject_without_message_uses_empty_string(self):
        out = builder_service.decisions_to_builder_response([Decision(type="reject")])
        assert out == {"approved": False, "revision_message": ""}

    def test_respond_returns_message_string(self):
        out = builder_service.decisions_to_builder_response(
            [Decision(type="respond", message="选项 A")]
        )
        assert out == "选项 A"

    def test_edit_falls_back_to_approve(self):
        # builder graph 不使用 edit args — approve fallback
        out = builder_service.decisions_to_builder_response(
            [
                Decision(
                    type="edit",
                    edited_action={"name": "x", "args": {"k": "v"}},
                )
            ]
        )
        assert out == {"approved": True}

    def test_empty_list_returns_none(self):
        assert builder_service.decisions_to_builder_response([]) is None


# ---------------------------------------------------------------------------
# B. Router contract — 标准 wire vs legacy
# ---------------------------------------------------------------------------


class TestResumeRouterContract:
    @pytest.mark.asyncio
    async def test_long_authored_answers_with_bounded_display_summary(
        self, client: AsyncClient, db: AsyncSession
    ):
        session_id = await _seed_session(db)
        captured, fake = _capture_resume_payload()
        # Full answers carry the decision; display_text is only a short summary.
        authored_answer = '{"requirements_reason": "' + "Validate simulated orders. " * 100 + '"}'
        with patch("app.routers.builder.builder_service.run_v3_resume_stream", side_effect=fake):
            response = await client.post(
                f"/api/builder/{session_id}/messages/resume",
                json={
                    "decisions": [{"type": "respond", "message": authored_answer}],
                    "display_text": "s" * 199 + "…",
                    "interrupt_id": "confirmed-requirements",
                },
            )
        assert response.status_code == 200
        assert captured[0]["response"] == authored_answer
        assert captured[0]["interrupt_id"] == "confirmed-requirements"

    @pytest.mark.asyncio
    async def test_resume_accepts_standard_decisions(self, client: AsyncClient, db: AsyncSession):
        """标准 ``{decisions: [{type:'respond', message:'选项 A'}]}`` → 200 + builder
        helper 转为 string ``"选项 A"`` 后传给 graph。"""
        session_id = await _seed_session(db)
        captured, fake = _capture_resume_payload()

        with patch(
            "app.routers.builder.builder_service.run_v3_resume_stream",
            side_effect=fake,
        ):
            resp = await client.post(
                f"/api/builder/{session_id}/messages/resume",
                json={
                    "decisions": [{"type": "respond", "message": "选项 A"}],
                    "interrupt_id": "intr-uuid-1",
                },
            )

        assert resp.status_code == 200
        assert len(captured) == 1
        # 确认 Helper 已将 respond → string
        assert captured[0]["response"] == "选项 A"
        assert captured[0]["interrupt_id"] == "intr-uuid-1"

    @pytest.mark.asyncio
    async def test_resume_approve_decision_maps_to_dict(
        self, client: AsyncClient, db: AsyncSession
    ):
        """approve Decision → 转换为 ``{"approved": True}`` dict 后传递。"""
        session_id = await _seed_session(db)
        captured, fake = _capture_resume_payload()

        with patch(
            "app.routers.builder.builder_service.run_v3_resume_stream",
            side_effect=fake,
        ):
            resp = await client.post(
                f"/api/builder/{session_id}/messages/resume",
                json={"decisions": [{"type": "approve"}]},
            )

        assert resp.status_code == 200
        assert captured[0]["response"] == {"approved": True}

    @pytest.mark.asyncio
    async def test_resume_rejects_legacy_response_field_422(
        self, client: AsyncClient, db: AsyncSession
    ):
        """Phase 5 clean break — legacy ``{response: "..."}`` payload 返回 422。

        ``BuilderResumeRequest.model_config['extra'] = 'forbid'`` + ``decisions``
        强制 Field(min_length=1)。阻止未来以兼容名义重新加入 dual-shape。
        """
        session_id = await _seed_session(db)
        resp = await client.post(
            f"/api/builder/{session_id}/messages/resume",
            json={"response": "legacy"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_resume_empty_decisions_422(self, client: AsyncClient, db: AsyncSession):
        """Decisions 空数组违反 ``min_length=1`` → 422。"""
        session_id = await _seed_session(db)
        resp = await client.post(
            f"/api/builder/{session_id}/messages/resume",
            json={"decisions": []},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# C. phase6 image — JSON string fallback
# ---------------------------------------------------------------------------


class TestPhase6JsonStringFallback:
    """phase6_choice_wait / phase6_image_approval 也处理具有 dict-意图的 JSON string。

    Phase 5 router adapter 会将 ``respond`` Decision 转为 string body
    传给 builder graph，但若 frontend 将 image_choice 意图组织为 dict 后
    ``JSON.stringify``，也必须 backward-compatible 地 fallthrough 到 dict 分支
    （graph 变更0 + helper 负责规范化）。
    """

    def test_parse_choice_response_json_object_string_promotes_to_dict(self):
        """``'{"choice":"skip","prompt":"p"}'`` → dict 分支。"""
        from app.agent_runtime.builder_v3.nodes._helpers import (
            parse_choice_response,
        )

        choice, prompt = parse_choice_response('{"choice":"skip","prompt":"p"}')
        assert choice == "skip"
        assert prompt == "p"

    def test_parse_choice_response_json_with_auto_prompt_key(self):
        """image_choice card 也支持 ``auto_prompt`` key。"""
        from app.agent_runtime.builder_v3.nodes._helpers import (
            parse_choice_response,
        )

        choice, prompt = parse_choice_response('{"choice":"generate","auto_prompt":"a"}')
        assert choice == "generate"
        assert prompt == "a"

    def test_parse_choice_response_invalid_json_falls_through_to_string(self):
        """JSON.parse 失败时按普通 string 选项处理 — 保留现有行为。"""
        from app.agent_runtime.builder_v3.nodes._helpers import (
            parse_choice_response,
        )

        choice, prompt = parse_choice_response("{not-json}")
        # 错误 JSON 返回 lower() 处理后的原始 string
        assert choice == "{not-json}"
        assert prompt == ""

    def test_parse_choice_response_preserves_dict_and_plain_string(self):
        """直接输入 dict / plain string 选项 — 保留现有分支（回归保护）。"""
        from app.agent_runtime.builder_v3.nodes._helpers import (
            parse_choice_response,
        )

        # 直接输入 dict
        c1, p1 = parse_choice_response({"choice": "SKIP", "prompt": "x"})
        assert c1 == "skip"
        assert p1 == "x"

        # plain string 选项标签 — 非 JSON 形式，因此只应用 lower()
        c2, p2 = parse_choice_response("skip")
        assert c2 == "skip"
        assert p2 == ""

    def test_parse_choice_response_prompt_keys_ordering(self):
        """image_approval 使用 ``prompt_keys=("prompt",)``，忽略 ``auto_prompt``。"""
        from app.agent_runtime.builder_v3.nodes._helpers import (
            parse_choice_response,
        )

        choice, prompt = parse_choice_response(
            {"choice": "regenerate", "auto_prompt": "ignored"},
            prompt_keys=("prompt",),
        )
        assert choice == "regenerate"
        assert prompt == ""

    @pytest.mark.asyncio
    async def test_phase6_choice_wait_node_accepts_json_string(self, monkeypatch):
        """phase6_choice_wait 节点本身接收 JSON string 后进入 skip 分支。

        mocking ``langgraph.types.interrupt`` 调用并注入 JSON string 响应后，
        验证节点是否转为 image_skipped=True + current_phase=7。
        """
        from app.agent_runtime.builder_v3.nodes import phase6_image

        # monkeypatch interrupt，使其返回 JSON object string
        def _fake_interrupt(_payload):
            return '{"choice":"skip","prompt":"unused"}'

        monkeypatch.setattr(phase6_image, "interrupt", _fake_interrupt)

        state = {
            "messages": [],
            "session_id": "s1",
            "intent": {
                "agent_name": "测试",
                "agent_description": "d",
                "primary_task_type": "x",
            },
            "todos": None,
            "pending_tool_call_id": "tc-skip-json",
        }

        result = await phase6_image.phase6_choice_wait(state)  # type: ignore[arg-type]
        assert result["current_phase"] == 7
        assert result["image_skipped"] is True
        assert result["pending_tool_call_id"] is None
