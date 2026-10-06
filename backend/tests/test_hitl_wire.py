"""HiTL wire format 回归保护。

A. ``Decision`` Pydantic 验证
B. ``ResumeRequest``（decisions 必填）Pydantic 验证
C. ``POST /api/conversations/{id}/messages/resume`` router → 标准 dict payload
D. ``stream_agent_response`` ``GraphInterrupt`` catch 时只 emit 标准 chunk
   - 标准 middleware HITLRequest shape：原样 emit
   - 自有 ``ask_user.py`` native interrupt：适配为标准 ``respond`` action
   - ``aget_state`` 失败 fallback：空标准 chunk

middleware 实例化保护在独立文件 ``test_hitl_middleware.py`` 中。
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.agent_runtime import event_names
from app.agent_runtime.streaming import _interrupt_to_standard_chunk, stream_agent_response
from app.agent_runtime.tools.ask_user import ask_user
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.message_event import MessageEvent
from app.models.model import Model
from app.models.user import User
from app.routers.conversation_agent_protocol_resume import (
    ResumePayload,
    SubmittedInterruptResponse,
)
from app.routers.conversation_agent_protocol_resume_redaction import (
    RedactedResumeArgsUnavailable,
    _restore_redacted_response,
    restore_redacted_resume_payload,
)
from app.routers.conversation_messages import _is_pending_interrupt
from app.schemas.conversation import Decision, ResumeRequest
from tests.conftest import TEST_USER_ID, TestSession

# ---------------------------------------------------------------------------
# A. Decision Pydantic 验证
# ---------------------------------------------------------------------------


class TestDecisionSchema:
    def test_approve_minimal_valid(self):
        d = Decision(type="approve")
        assert d.type == "approve"
        assert d.edited_action is None
        assert d.message is None

    def test_edit_requires_edited_action(self):
        with pytest.raises(ValidationError, match="edited_action"):
            Decision(type="edit")

    def test_edit_with_edited_action_valid(self):
        d = Decision(
            type="edit",
            edited_action={"name": "send_email", "args": {"to": "x@y"}},
        )
        assert d.edited_action is not None

    def test_respond_requires_message(self):
        with pytest.raises(ValidationError, match="message"):
            Decision(type="respond")

    def test_respond_with_message_valid(self):
        d = Decision(type="respond", message="hello")
        assert d.message == "hello"

    def test_reject_message_is_optional(self):
        # 即使没有 message 也 OK（middleware 会生成默认消息）。
        d = Decision(type="reject")
        assert d.type == "reject"
        d2 = Decision(type="reject", message="reason")
        assert d2.message == "reason"

    def test_type_literal_rejects_unknown(self):
        with pytest.raises(ValidationError):
            Decision(type="unknown")  # type: ignore[arg-type]

    def test_model_dump_excludes_none_for_typed_dict_compat(self):
        d = Decision(type="approve")
        dumped = d.model_dump(exclude_none=True)
        # LangChain HITLResponse TypedDict 为 NotRequired — 排除 None key。
        assert dumped == {"type": "approve"}


# ---------------------------------------------------------------------------
# B. ResumeRequest 仅标准格式
# ---------------------------------------------------------------------------


class TestResumeRequestSchema:
    def test_decisions_required(self):
        """缺少 ``decisions`` 字段时返回 422。"""
        with pytest.raises(ValidationError, match="decisions"):
            ResumeRequest()  # type: ignore[call-arg]

    def test_decisions_valid(self):
        req = ResumeRequest(decisions=[Decision(type="approve")])
        assert len(req.decisions) == 1


# ---------------------------------------------------------------------------
# C. Router payload — POST /messages/resume
# ---------------------------------------------------------------------------


async def _seed_user_agent_conv() -> uuid.UUID:
    async with TestSession() as db:
        user = User(id=TEST_USER_ID, email="test@test.com", name="Test")
        db.add(user)
        model = Model(provider="openai", model_name="gpt-4o", display_name="GPT-4o")
        db.add(model)
        await db.flush()
        agent = Agent(
            user_id=user.id,
            name="HiTL Agent",
            system_prompt="Hi",
            model_id=model.id,
        )
        db.add(agent)
        await db.flush()
        conv = Conversation(agent_id=agent.id, title="Resume Test")
        db.add(conv)
        await db.commit()
        return conv.id


async def _seed_legacy_pending_interrupt(conv_id: uuid.UUID) -> None:
    assistant_msg_id = str(uuid.uuid4())
    async with TestSession() as db:
        db.add(
            MessageEvent(
                conversation_id=conv_id,
                assistant_msg_id=assistant_msg_id,
                events=[
                    {
                        "id": f"{assistant_msg_id}-start",
                        "event": event_names.MESSAGE_START,
                        "data": {"id": assistant_msg_id, "role": "assistant"},
                    },
                    {
                        "id": f"{assistant_msg_id}-interrupt",
                        "event": event_names.INTERRUPT,
                        "data": {"actions": [{"name": "send_email"}]},
                    },
                ],
                last_event_id=f"{assistant_msg_id}-interrupt",
                status="completed",
            )
        )
        await db.commit()


def test_pending_interrupt_detector_accepts_protocol_input_requested() -> None:
    events = [
        {
            "id": "run-v3:protocol:00000001",
            "method": "input.requested",
            "data": {
                "interrupt_id": "interrupt-v3",
                "payload": {"action_requests": [{"name": "write_file", "args": {}}]},
            },
        },
        {
            "id": "run-v3:protocol:00000002",
            "method": "lifecycle",
            "data": {"event": "interrupted"},
        },
    ]

    assert _is_pending_interrupt(events)


def _capture_resume_payload() -> tuple[list[Any], Any]:
    captured: list[Any] = []

    async def fake_stream(*args, **kwargs):
        captured.append(args)
        captured.append(kwargs)
        yield 'event: message_end\ndata: {"content": "ok", "usage": {}}\n\n'

    return captured, fake_stream


class TestResumeRouterPayload:
    @pytest.mark.asyncio
    async def test_decisions_passed_through_as_command_resume_payload(self, client: AsyncClient):
        conv_id = await _seed_user_agent_conv()
        await _seed_legacy_pending_interrupt(conv_id)
        captured, fake = _capture_resume_payload()

        with patch("app.routers.conversation_messages.resume_agent_stream", side_effect=fake):
            resp = await client.post(
                f"/api/conversations/{conv_id}/messages/resume",
                json={
                    "decisions": [
                        {"type": "approve"},
                        {
                            "type": "edit",
                            "edited_action": {
                                "name": "send_email",
                                "args": {"to": "x@y", "subject": "hi"},
                            },
                        },
                    ]
                },
            )

        assert resp.status_code == 200
        payload = captured[0][1]
        assert payload == {
            "decisions": [
                {"type": "approve"},
                {
                    "type": "edit",
                    "edited_action": {
                        "name": "send_email",
                        "args": {"to": "x@y", "subject": "hi"},
                    },
                },
            ]
        }

    @pytest.mark.asyncio
    async def test_respond_decision_serialized(self, client: AsyncClient):
        conv_id = await _seed_user_agent_conv()
        await _seed_legacy_pending_interrupt(conv_id)
        captured, fake = _capture_resume_payload()

        with patch("app.routers.conversation_messages.resume_agent_stream", side_effect=fake):
            resp = await client.post(
                f"/api/conversations/{conv_id}/messages/resume",
                json={"decisions": [{"type": "respond", "message": "yes"}]},
            )

        assert resp.status_code == 200
        payload = captured[0][1]
        assert payload == {"decisions": [{"type": "respond", "message": "yes"}]}

    @pytest.mark.asyncio
    async def test_empty_body_returns_422(self, client: AsyncClient):
        conv_id = await _seed_user_agent_conv()
        resp = await client.post(
            f"/api/conversations/{conv_id}/messages/resume",
            json={},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_legacy_response_field_rejected_422(self, client: AsyncClient):
        """legacy ``response`` 字段为 unknown — Pydantic 默认 ignore。没有
        ``decisions`` 时返回 422。
        """
        conv_id = await _seed_user_agent_conv()
        resp = await client.post(
            f"/api/conversations/{conv_id}/messages/resume",
            json={"response": "legacy form"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# D. Streaming — 只 emit 标准 chunk
# ---------------------------------------------------------------------------


def _make_intr(ns: str, value: Any) -> MagicMock:
    intr = MagicMock()
    intr.ns = ns
    intr.value = value
    return intr


def _make_state_with_interrupts(interrupts: list[MagicMock]) -> MagicMock:
    state = MagicMock()
    task = MagicMock()
    task.interrupts = interrupts
    state.tasks = [task]
    return state


class _InterruptingAgent:
    def __init__(self, state: MagicMock | Exception):
        self._state = state

    async def astream(self, *args, **kwargs):
        from langgraph.errors import GraphInterrupt

        if False:
            yield  # pragma: no cover
        raise GraphInterrupt([])

    async def aget_state(self, config: Any):
        if isinstance(self._state, Exception):
            raise self._state
        return self._state


def _parse_interrupt_events(events: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in events:
        if "event: interrupt\n" not in raw:
            continue
        for line in raw.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: ") :]))
    return out


class TestInterruptToStandardChunk:
    """``_interrupt_to_standard_chunk`` 单元验证。"""

    def test_standard_hitl_request_passthrough(self):
        intr_value = {
            "action_requests": [{"name": "send_email", "args": {"to": "x@y"}}],
            "review_configs": [{"action_name": "send_email", "allowed_decisions": ["approve"]}],
        }
        chunk = _interrupt_to_standard_chunk("ns-1", intr_value)
        assert chunk is not None
        assert chunk["interrupt_id"] == "ns-1"
        assert chunk["action_requests"] == intr_value["action_requests"]
        assert chunk["review_configs"] == intr_value["review_configs"]

    def test_ask_user_native_adapted_to_respond_action(self):
        """自有 ``ask_user.py`` interrupt → 适配为标准 ``respond`` action。"""
        intr_value = {
            "type": "ask_user",
            "question": "你想要哪个选项？",
            "options": ["A", "B"],
        }
        chunk = _interrupt_to_standard_chunk("ns-ask-1", intr_value)
        assert chunk is not None
        assert chunk["interrupt_id"] == "ns-ask-1"
        assert len(chunk["action_requests"]) == 1
        action = chunk["action_requests"][0]
        assert action["name"] == "ask_user"
        assert action["args"] == {"question": "你想要哪个选项？", "options": ["A", "B"]}
        review = chunk["review_configs"][0]
        assert review["action_name"] == "ask_user"
        assert "tool_name" not in review
        assert review["allowed_decisions"] == ["respond"]

    def test_ask_user_native_preserves_extended_question_flow_args(self):
        """native ask_user v2 payload 将 mode/questions/title 原样传给 frontend。"""
        intr_value = {
            "type": "ask_user",
            "mode": "question_flow",
            "title": "确认 agent 设置",
            "questions": [
                {
                    "id": "tone",
                    "label": "回答语气",
                    "type": "single_select",
                    "options": [
                        {"id": "concise", "label": "简洁明了"},
                        {"id": "detailed", "label": "详细"},
                    ],
                    "required": True,
                }
            ],
        }

        chunk = _interrupt_to_standard_chunk("ns-flow-1", intr_value)

        assert chunk is not None
        assert chunk["action_requests"][0]["args"] == {
            "mode": "question_flow",
            "title": "确认 agent 设置",
            "questions": intr_value["questions"],
        }

    def test_ask_user_native_preserves_option_list_args(self):
        """native ask_user option_list payload 保留 min/max 选择限制。"""
        intr_value = {
            "type": "ask_user",
            "mode": "option_list",
            "title": "请选择要使用的 tool",
            "minSelections": 1,
            "maxSelections": 3,
            "options": [{"id": "web", "label": "Web Search", "description": "搜索最新信息"}],
        }

        chunk = _interrupt_to_standard_chunk("ns-options-1", intr_value)

        assert chunk is not None
        assert chunk["action_requests"][0]["args"] == {
            "mode": "option_list",
            "title": "请选择要使用的 tool",
            "minSelections": 1,
            "maxSelections": 3,
            "options": intr_value["options"],
        }

    def test_unknown_shape_returns_none(self):
        """未知 dict shape 会 skip（None）。"""
        assert _interrupt_to_standard_chunk("ns", {"random": "stuff"}) is None
        assert _interrupt_to_standard_chunk("ns", None) is None


class TestStreamingStandardEmit:
    """``stream_agent_response`` 的 INTERRUPT chunk 只 emit 标准格式。"""

    @pytest.mark.asyncio
    async def test_standard_chunk_only_for_hitl_request(self):
        """标准 middleware HITLRequest shape → 只 emit 1个标准 chunk。"""
        intr_value = {
            "action_requests": [
                {
                    "name": "send_email",
                    "args": {"to": "x@y"},
                    "description": "Send confirmation",
                }
            ],
            "review_configs": [
                {
                    "action_name": "send_email",
                    "allowed_decisions": ["approve", "edit", "reject", "respond"],
                }
            ],
        }
        state = _make_state_with_interrupts([_make_intr("ns-42", intr_value)])
        agent = _InterruptingAgent(state)

        events = [e async for e in stream_agent_response(agent, [], {})]
        intrs = _parse_interrupt_events(events)

        assert len(intrs) == 1, "仅 emit 标准格式（无 legacy chunk）"
        std = intrs[0]
        assert "action_requests" in std and "review_configs" in std
        assert "value" not in std, "不再 emit legacy 'value' key"
        assert std["interrupt_id"] == "ns-42"

    @pytest.mark.asyncio
    async def test_ask_user_native_emits_adapted_standard_chunk(self):
        """自有 ask_user interrupt 也适配为标准 wire，仅 emit 单个 chunk。"""
        intr_value = {"type": "ask_user", "question": "Choose?", "options": ["a", "b"]}
        state = _make_state_with_interrupts([_make_intr("ns-ask-1", intr_value)])
        agent = _InterruptingAgent(state)

        events = [e async for e in stream_agent_response(agent, [], {})]
        intrs = _parse_interrupt_events(events)

        assert len(intrs) == 1, "ask_user 也只 emit 标准 chunk"
        chunk = intrs[0]
        assert "action_requests" in chunk
        assert chunk["action_requests"][0]["name"] == "ask_user"
        assert chunk["review_configs"][0]["action_name"] == "ask_user"
        assert "tool_name" not in chunk["review_configs"][0]
        assert chunk["interrupt_id"] == "ns-ask-1"

    @pytest.mark.asyncio
    async def test_unknown_shape_emits_no_chunk(self):
        """既非标准 shape 也非 ask_user 的 dict 不 emit chunk（skip）。"""
        intr_value = {"random": "stuff"}
        state = _make_state_with_interrupts([_make_intr("ns-x", intr_value)])
        agent = _InterruptingAgent(state)

        events = [e async for e in stream_agent_response(agent, [], {})]
        intrs = _parse_interrupt_events(events)

        assert len(intrs) == 0

    @pytest.mark.asyncio
    async def test_fallback_empty_standard_chunk_when_aget_state_fails(self):
        """``aget_state`` 失败 + ``was_interrupted=True`` → 空标准 chunk。"""
        agent = _InterruptingAgent(RuntimeError("aget_state boom"))

        events = [e async for e in stream_agent_response(agent, [], {})]
        intrs = _parse_interrupt_events(events)

        assert len(intrs) == 1
        chunk = intrs[0]
        assert chunk["interrupt_id"] == ""
        assert chunk["action_requests"] == []
        assert chunk["review_configs"] == []
        assert "value" not in chunk


class TestAskUserFallbackResumeParser:
    """native ask_user fallback 不会把标准 resume payload 原样暴露给 model。"""

    def test_ask_user_returns_respond_message_from_standard_resume_payload(self):
        with patch(
            "app.agent_runtime.tools.ask_user.interrupt",
            return_value={"decisions": [{"type": "respond", "message": "选项 A"}]},
        ):
            assert ask_user.invoke({"question": "哪一个？"}) == "选项 A"

    def test_ask_user_falls_back_to_string_response(self):
        with patch("app.agent_runtime.tools.ask_user.interrupt", return_value="选项 B"):
            assert ask_user.invoke({"question": "哪一个？"}) == "选项 B"

    def test_ask_user_accepts_question_flow_payload(self):
        with patch("app.agent_runtime.tools.ask_user.interrupt", return_value="完成") as intr:
            assert (
                ask_user.invoke(
                    {
                        "mode": "question_flow",
                        "title": "确认 agent 设置",
                        "questions": [
                            {
                                "id": "tone",
                                "label": "回答语气",
                                "type": "single_select",
                                "options": [{"id": "concise", "label": "简洁明了"}],
                            }
                        ],
                    }
                )
                == "完成"
            )

        payload = intr.call_args.args[0]
        assert payload["type"] == "ask_user"
        assert payload["mode"] == "question_flow"
        assert payload["title"] == "确认 agent 设置"
        assert payload["questions"][0]["id"] == "tone"


# ---------------------------------------------------------------------------
# E. edit-by-index — backend 用 pending action index 填充 edited_action.name
# ---------------------------------------------------------------------------


class TestEditByIndexNameFill:
    """即使 frontend 不知道 tool name（省略 name），backend 也会按 index
    匹配 pending action，并权威填充 ``edited_action.name``。因为 langchain
    ``HumanInTheLoopMiddleware`` 会按 positional index 匹配 decision↔action，
    并用 hard subscript 读取 ``edited_action["name"]``。
    """

    def test_name_filled_for_edit_without_name(self):
        response = {"decisions": [{"type": "edit", "edited_action": {"args": {"command": "new"}}}]}
        raw_actions = [{"name": "execute_in_skill", "args": {"command": "old"}}]

        restored = _restore_redacted_response(response, raw_actions)

        edited = restored["decisions"][0]["edited_action"]
        assert edited["name"] == "execute_in_skill"
        assert edited["args"]["command"] == "new"

    def test_name_overwritten_authoritatively(self):
        # 即使 frontend 发送错误 name（或 stale），backend index 也具有权威性。
        response = {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {"name": "WRONG", "args": {"command": "new"}},
                }
            ]
        }
        raw_actions = [{"name": "execute_in_skill", "args": {"command": "old"}}]

        restored = _restore_redacted_response(response, raw_actions)

        assert restored["decisions"][0]["edited_action"]["name"] == "execute_in_skill"

    def test_multi_action_edit_names_filled_by_index(self):
        response = {
            "decisions": [
                {"type": "edit", "edited_action": {"args": {"path": "a.md"}}},
                {"type": "edit", "edited_action": {"args": {"to": "x@y"}}},
            ]
        }
        raw_actions = [
            {"name": "write_file", "args": {"path": "old.md"}},
            {"name": "send_email", "args": {"to": "old@y"}},
        ]

        restored = _restore_redacted_response(response, raw_actions)

        assert restored["decisions"][0]["edited_action"]["name"] == "write_file"
        assert restored["decisions"][0]["edited_action"]["args"]["path"] == "a.md"
        assert restored["decisions"][1]["edited_action"]["name"] == "send_email"
        assert restored["decisions"][1]["edited_action"]["args"]["to"] == "x@y"

    def test_redacted_secret_restored_and_name_filled(self):
        # secret 字段从 frontend 以 <redacted> 锁定传来，backend 会从 checkpoint
        # 原值恢复，同时填充 name。
        response = {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {
                        "args": {"command": "node updated.cjs", "api_key": "<redacted>"}
                    },
                }
            ]
        }
        raw_actions = [
            {
                "name": "execute_in_skill",
                "args": {"command": "node create.cjs", "api_key": "raw-secret"},
            }
        ]

        restored = _restore_redacted_response(response, raw_actions)

        edited = restored["decisions"][0]["edited_action"]
        assert edited["name"] == "execute_in_skill"
        assert edited["args"]["command"] == "node updated.cjs"
        assert edited["args"]["api_key"] == "raw-secret"

    def test_non_edit_decisions_pass_through_unchanged(self):
        response = {
            "decisions": [
                {"type": "approve"},
                {"type": "reject", "message": "no"},
            ]
        }
        raw_actions = [
            {"name": "write_file", "args": {}},
            {"name": "send_email", "args": {}},
        ]

        restored = _restore_redacted_response(response, raw_actions)

        assert restored["decisions"] == [
            {"type": "approve"},
            {"type": "reject", "message": "no"},
        ]

    def test_name_falls_back_to_client_value_without_matching_raw_action(self):
        # 防御：若没有 raw action（匹配失败），按现有行为保留 frontend name。
        response = {
            "decisions": [
                {"type": "edit", "edited_action": {"name": "client_name", "args": {"x": 1}}}
            ]
        }

        restored = _restore_redacted_response(response, [])

        assert restored["decisions"][0]["edited_action"]["name"] == "client_name"
        assert restored["decisions"][0]["edited_action"]["args"]["x"] == 1

    def test_name_less_edit_without_raw_action_fails_closed(self):
        # frontend 省略 name（期望 backend 按 index 填充）但又没有匹配的 raw action 时，
        # 缺 name 的 edited_action 会在 langchain 中因 hard subscript 崩溃，因此
        # 不应放行，必须 fail-closed。
        response = {"decisions": [{"type": "edit", "edited_action": {"args": {"command": "new"}}}]}

        with pytest.raises(RedactedResumeArgsUnavailable):
            _restore_redacted_response(response, [])


class TestRestoreResumePayloadEditGate:
    """``restore_redacted_resume_payload`` 的 early-return gate 无论是否有 redacted，
    只要存在 edit decision 都必须走 index 解析路径（需要填充 name）。
    非 edit（approve/reject/respond）resume 仍直接 short-circuit。
    """

    @pytest.mark.asyncio
    async def test_fills_name_for_edit_without_redacted_placeholder(self):
        response = {"decisions": [{"type": "edit", "edited_action": {"args": {"command": "new"}}}]}
        resume = ResumePayload(
            input_payload={"intr-1": response},
            interrupt_id="intr-1",
            submitted=(SubmittedInterruptResponse("intr-1", (), response),),
        )

        with patch(
            "app.routers.conversation_agent_protocol_resume_redaction"
            "._raw_pending_actions_by_interrupt",
            new=AsyncMock(
                return_value={"intr-1": [{"name": "execute_in_skill", "args": {"command": "old"}}]}
            ),
        ):
            restored = await restore_redacted_resume_payload(
                conversation=MagicMock(),
                resume=resume,
                pending_interrupts=[],
            )

        decision = restored["intr-1"]["decisions"][0]
        assert decision["edited_action"]["name"] == "execute_in_skill"
        assert decision["edited_action"]["args"]["command"] == "new"

    @pytest.mark.asyncio
    async def test_non_edit_resume_short_circuits_without_checkpointer(self):
        response = {"decisions": [{"type": "approve"}]}
        resume = ResumePayload(
            input_payload={"intr-1": response},
            interrupt_id="intr-1",
            submitted=(SubmittedInterruptResponse("intr-1", (), response),),
        )
        raw_mock = AsyncMock(return_value={})

        with patch(
            "app.routers.conversation_agent_protocol_resume_redaction"
            "._raw_pending_actions_by_interrupt",
            new=raw_mock,
        ):
            restored = await restore_redacted_resume_payload(
                conversation=MagicMock(),
                resume=resume,
                pending_interrupts=[],
            )

        assert restored == {"intr-1": response}
        raw_mock.assert_not_called()
