"""Builder locale contracts: payloads, LLM inputs and checkpoint resumes."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent_runtime.builder_i18n import (
    catalog,
    get_locale,
    language_instruction,
    locale_scope,
    localize,
    localized_stream,
)
from app.agent_runtime.builder_v3.graph import build_graph
from app.agent_runtime.builder_v3.nodes import phase2_intent
from app.agent_runtime.builder_v3.nodes.phase1_init import phase1_init
from app.agent_runtime.builder_v3.state import initial_todos
from app.schemas.builder import AgentCreationIntent

HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")


@pytest.mark.parametrize(
    ("locale", "title", "first"),
    [
        ("zh-CN", "智能体设置确认", "搜索智能体"),
        ("en", "Confirm Agent settings", "Search Agent"),
        ("ko", "에이전트 설정 확인", "검색 에이전트"),
    ],
)
def test_phase2_question_flow_locale(locale, title, first):
    with locale_scope(locale):
        payload = phase2_intent._build_phase2_ask_user_payload(
            phase2_intent._fallback_name_options({})
        )
        assert payload["title"] == title
        assert payload["questions"][0]["options"][0]["label"] == first
        assert [q["id"] for q in payload["questions"]] == [
            "agent_name",
            "response_tone",
            "output_style",
        ]
        assert payload["questions"][1]["options"][0]["id"] == "friendly"
        if locale != "ko":
            assert not HANGUL.search(json.dumps(payload, ensure_ascii=False))
        if locale == "zh-CN":
            assert payload["questions"][0]["label"] == "智能体名称"
            assert payload["questions"][0]["question"] == "你想给这个智能体取什么名字？"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "language"), [("zh-CN", "Simplified Chinese"), ("en", "English"), ("ko", "Korean")]
)
async def test_naming_prompt_and_failure_fallback(monkeypatch, locale, language):
    invoke = AsyncMock(side_effect=ValueError("unavailable"))
    monkeypatch.setattr(phase2_intent, "invoke_with_json_retry", invoke)
    with locale_scope(locale):
        names = await phase2_intent._suggest_name_options("Find useful web pages")
        prompt, task = invoke.call_args.args
        assert language in prompt
        assert "JSON" in prompt
        if locale != "ko":
            assert "Korean" not in prompt + task
            assert not HANGUL.search(prompt + task + json.dumps(names, ensure_ascii=False))
        assert len(names) == 3


@pytest.mark.asyncio
async def test_unrequested_korean_model_names_fall_back(monkeypatch):
    monkeypatch.setattr(
        phase2_intent, "invoke_with_json_retry", AsyncMock(return_value=["검색봇", "도우미"])
    )
    with locale_scope("zh-CN"):
        assert await phase2_intent._suggest_name_options("Search web pages") == [
            "搜索智能体",
            "助手机器人",
            "智能助手",
        ]
        assert phase2_intent._name_matches_locale("검색봇", "Please name it 검색봇")


def test_catalog_coverage_slots_and_prompt_language():
    original = catalog("ko")
    for locale in ("zh-CN", "en"):
        translated = catalog(locale)
        assert translated.keys() == original.keys()
        for key, text in translated.items():
            assert not HANGUL.search(text), key
            assert sorted(re.findall(r"\{v\d+\}", text)) == sorted(
                re.findall(r"\{v\d+\}", original[key])
            ), key
    runtime = Path(__file__).parents[1] / "app/agent_runtime"
    prompts = [*(runtime / "builder/prompts").glob("*.md"), runtime / "assistant/prompt.md"]
    for path in prompts:
        prompt = path.read_text(encoding="utf-8")
        assert not HANGUL.search(prompt), path
        assert "active UI locale" in prompt


@pytest.mark.asyncio
async def test_new_timeline_localizes_without_changing_old_state():
    with locale_scope("ko"):
        old_todos = initial_todos()
    before = json.dumps(old_todos, ensure_ascii=False)
    with locale_scope("zh-CN"):
        result = await phase1_init(
            {"todos": old_todos, "user_request": "Search", "session_id": "test"}
        )
    assert json.dumps(old_todos, ensure_ascii=False) == before
    for message in result["messages"]:
        assert not HANGUL.search(json.dumps(message.model_dump(), ensure_ascii=False))


@pytest.mark.asyncio
async def test_request_scopes_do_not_leak_across_streams():
    @localized_stream
    async def stream(*, locale):
        yield localize("검색 에이전트")
        await asyncio.sleep(0)
        yield localize("검색 에이전트")

    async def consume(locale):
        return [value async for value in stream(locale=locale)]

    results = await asyncio.gather(consume("en"), consume("ko"), consume("zh-CN"))
    assert results == [["Search Agent"] * 2, ["검색 에이전트"] * 2, ["搜索智能体"] * 2]
    assert get_locale() == "zh-CN"


@pytest.mark.asyncio
async def test_llm_retry_keeps_active_locale(monkeypatch):
    from app.agent_runtime.builder.sub_agents import helpers

    model = SimpleNamespace(
        ainvoke=AsyncMock(
            side_effect=[SimpleNamespace(content="invalid"), SimpleNamespace(content="{}")]
        )
    )
    monkeypatch.setattr(helpers, "_get_builder_model", AsyncMock(return_value=model))
    monkeypatch.setattr(helpers, "_get_fallback_model", AsyncMock(return_value=None))
    with locale_scope("zh-CN"):
        assert await helpers.invoke_with_json_retry("Return JSON.", "Describe the Agent.") == {}
    for call in model.ainvoke.call_args_list:
        messages = call.args[0]
        assert "Simplified Chinese" in messages[0]["content"]
        assert not HANGUL.search(messages[1].content)


@pytest.mark.asyncio
async def test_checkpoint_resume_uses_new_locale_without_rewriting_messages(monkeypatch):
    from app.agent_runtime.builder_v3.nodes import phase3_tools

    intent = AgentCreationIntent(
        agent_name="搜索智能体",
        agent_description="Search pages",
        primary_task_type="search",
        use_cases=["Search pages"],
        required_capabilities=["search"],
    )
    monkeypatch.setattr(phase2_intent, "analyze_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(
        phase2_intent,
        "_suggest_name_options",
        AsyncMock(return_value=["搜索智能体", "助手机器人", "智能助手"]),
    )
    monkeypatch.setattr(phase3_tools, "recommend_tools", AsyncMock(return_value=[]))
    graph = build_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "locale-resume", "ui_locale": "zh-CN"}}
    await graph.ainvoke(
        {"user_request": "Search web pages", "session_id": "locale-resume", "messages": []}, config
    )
    old = (await graph.aget_state(config)).values["messages"]
    config["configurable"]["ui_locale"] = "en"
    response = {
        "answers": {
            "agent_name": ["搜索智能体"],
            "response_tone": ["friendly"],
            "output_style": ["summary"],
        }
    }
    await graph.ainvoke(Command(resume=response), config)
    current = (await graph.aget_state(config)).values["messages"]
    assert [(m.id, m.content) for m in current[: len(old)]] == [(m.id, m.content) for m in old]
    emitted = json.dumps([m.model_dump() for m in current[len(old) :]], ensure_ascii=False)
    assert "Tool recommendations" in emitted
    assert not HANGUL.search(emitted)


def test_explicit_prompt_locale_does_not_translate_identifiers():
    with locale_scope("zh-CN"):
        rule = language_instruction()
        assert "agent_name/name" in rule
        assert "Simplified Chinese" in rule


@pytest.mark.asyncio
async def test_builder_service_message_and_resume_propagate_locale(monkeypatch):
    from uuid import uuid4

    from app.agent_runtime import checkpointer, streaming
    from app.agent_runtime.builder_v3 import graph as graph_module
    from app.services import builder_service

    fake_graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={})))
    monkeypatch.setattr(graph_module, "compile_graph", lambda _: fake_graph)
    monkeypatch.setattr(checkpointer, "get_checkpointer", lambda: None)
    monkeypatch.setattr(builder_service, "async_session_factory", AsyncMock)
    monkeypatch.setattr(builder_service, "get_tools_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(builder_service, "_get_default_model_name", AsyncMock(return_value="model"))
    monkeypatch.setattr(builder_service, "_get_middlewares_catalog", lambda: [])
    calls = []

    async def capture(graph, graph_input, config):
        calls.append((graph_input, config))
        yield localize("검색 에이전트")

    monkeypatch.setattr(streaming, "stream_agent_response", capture)
    session, user = uuid4(), uuid4()
    result = [
        c async for c in builder_service.run_v3_message_stream(session, user, "Goal", locale="en")
    ]
    assert result == ["Search Agent"]
    graph_input, config = calls[-1]
    assert config["configurable"] == {"thread_id": str(session), "ui_locale": "en"}
    assert graph_input["todos"][0]["name"] == "Project initialization"
    result = [
        c async for c in builder_service.run_v3_resume_stream(session, user, "answer", locale="ko")
    ]
    assert result == ["검색 에이전트"]
    assert calls[-1][1]["configurable"]["ui_locale"] == "ko"
    assert isinstance(calls[-1][0], Command)
    assert calls[-1][0].resume == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "other"),
    [("zh-CN", "自行输入"), ("en", "Enter your own answer"), ("ko", "직접 입력")],
)
async def test_assistant_clarifying_fallback_is_localized(locale, other):
    from app.agent_runtime.assistant.tools.clarify_tools import build_clarify_tools

    with locale_scope(locale):
        tool = build_clarify_tools()[0]
        result = json.loads(
            await tool.ainvoke(
                {"question": "Question", "option_1": "A", "option_2": "B", "option_3": "C"}
            )
        )
        assert result["options"][-1] == other
        if locale != "ko":
            assert not HANGUL.search(json.dumps(result, ensure_ascii=False))


@pytest.mark.asyncio
async def test_text_retry_uses_locale_and_preserves_character_count(monkeypatch):
    from app.agent_runtime.builder.sub_agents import helpers

    model = SimpleNamespace(
        ainvoke=AsyncMock(
            side_effect=[
                SimpleNamespace(content="短"),
                SimpleNamespace(content="完整回答"),
            ]
        )
    )
    monkeypatch.setattr(helpers, "_get_builder_model", AsyncMock(return_value=model))
    monkeypatch.setattr(helpers, "_get_fallback_model", AsyncMock(return_value=None))
    with locale_scope("zh-CN"):
        assert await helpers.invoke_for_text("Write an answer.", "Goal", min_length=3) == "完整回答"
    messages = model.ainvoke.call_args.args[0]
    assert "Simplified Chinese" in messages[0]["content"]
    assert "1" in messages[1].content
    assert "{char_count}" not in messages[1].content
    assert not HANGUL.search(messages[1].content)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "rule"),
    [
        ("zh-CN", "默认使用简体中文"),
        ("en", "Respond in English"),
        ("ko", "한국어로 응답"),
    ],
)
async def test_generated_prompt_fallback_language(monkeypatch, locale, rule):
    from app.agent_runtime.builder.sub_agents import prompt_generator

    monkeypatch.setattr(prompt_generator, "invoke_for_text", AsyncMock(return_value=None))
    with locale_scope(locale):
        intent = AgentCreationIntent(
            agent_name="Search",
            agent_description="Search pages",
            primary_task_type="search",
            use_cases=["Search pages"],
            required_capabilities=[],
        )
        result = await prompt_generator.generate_system_prompt(intent, [], [])
    assert rule in result
    assert prompt_generator._has_required_sections(result)
    if locale != "ko":
        assert not HANGUL.search(result)


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh-CN", "模型服务请求失败"),
        ("en", "The model provider request failed"),
        ("ko", "모델 제공자 요청이 실패"),
    ],
)
def test_builder_stream_errors_are_localized_without_provider_details(locale, expected):
    from app.agent_runtime.stream_error_messages import public_stream_error_message

    message = public_stream_error_message(
        RuntimeError("openai. RateLimitError secret"), locale=locale
    )
    assert expected in message
    assert "secret" not in message
    if locale != "ko":
        assert not HANGUL.search(message)
        assert not HANGUL.search(public_stream_error_message(RuntimeError("오류"), locale=locale))
    assert public_stream_error_message(RuntimeError("plain error")) == "plain error"

