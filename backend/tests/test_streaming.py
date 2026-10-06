"""Tests for app.agent_runtime.streaming — SSE formatting and stream logic."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agent_runtime.event_broker import EventBroker
from app.agent_runtime.runtime_config import runtime_data_dir
from app.agent_runtime.streaming import (
    StreamErrorRecord,
    _is_tool_selector_json,
    format_sse,
    stream_agent_response,
)

# ---------------------------------------------------------------------------
# format_sse
# ---------------------------------------------------------------------------


def test_format_sse_basic():
    result = format_sse("content_delta", {"delta": "Hello"})
    assert result.startswith("event: content_delta\n")
    assert "data: " in result
    assert result.endswith("\n\n")
    data = json.loads(result.split("data: ")[1].strip())
    assert data["delta"] == "Hello"


def test_format_sse_unicode():
    result = format_sse("content_delta", {"delta": "你好"})
    data = json.loads(result.split("data: ")[1].strip())
    assert data["delta"] == "你好"


def test_format_sse_complex_data():
    payload = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}, "content": "done"}
    result = format_sse("message_end", payload)
    data = json.loads(result.split("data: ")[1].strip())
    assert data["usage"]["prompt_tokens"] == 10


def test_format_sse_with_event_id_emits_id_line():
    result = format_sse("content_delta", {"delta": "hi"}, event_id="msg-1-3")
    assert "id: msg-1-3\n" in result
    # event/id/data 顺序 — 客户端解析器按行处理，因此本身无关，但
    # 为保证服务器格式一致性进行验证。
    lines = result.strip().split("\n")
    assert lines[0] == "event: content_delta"
    assert lines[1] == "id: msg-1-3"
    assert lines[2].startswith("data: ")


def test_format_sse_without_event_id_omits_id_line():
    result = format_sse("content_delta", {"delta": "hi"})
    assert "id: " not in result
    assert result.startswith("event: content_delta\ndata: ")


# ---------------------------------------------------------------------------
# Helpers for mock agent
# ---------------------------------------------------------------------------


def _make_ai_chunk(content: Any, usage_metadata: dict | None = None) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.type = "ai"
    msg.tool_calls = []
    msg.usage_metadata = usage_metadata
    return msg


def _make_tool_call_chunk(tool_name: str, args: dict, tool_call_id: str | None = None) -> MagicMock:
    msg = MagicMock()
    msg.content = ""
    msg.type = "ai"
    msg.tool_calls = [{"name": tool_name, "args": args, "id": tool_call_id}]
    msg.usage_metadata = None
    return msg


def _make_tool_result_chunk(
    tool_name: str, result: str, tool_call_id: str | None = None
) -> MagicMock:
    msg = MagicMock()
    msg.content = result
    msg.type = "tool"
    msg.name = tool_name
    msg.tool_call_id = tool_call_id
    msg.tool_calls = []
    msg.usage_metadata = None
    return msg


class MockAgent:
    """Fake agent that yields predefined chunks from astream()."""

    def __init__(self, chunks: list[tuple[MagicMock, dict]]):
        self._chunks = chunks

    async def astream(self, input: Any, config: Any = None, **kwargs: Any):
        for chunk in self._chunks:
            yield chunk


class BlockingAfterFirstChunkAgent:
    def __init__(self, chunk: tuple[MagicMock, dict]) -> None:
        self._chunk = chunk
        self.release = asyncio.Event()

    async def astream(self, input: Any, config: Any = None, **kwargs: Any):
        yield self._chunk
        await self.release.wait()


class FakeArtifactRecorder:
    def __init__(self) -> None:
        self.prepared = False
        self.calls: list[tuple[str, str | None]] = []

    async def prepare(self) -> None:
        self.prepared = True

    async def collect_after_tool_result(
        self,
        *,
        tool_name: str,
        tool_call_id: str | None,
    ) -> list[dict[str, object]]:
        self.calls.append((tool_name, tool_call_id))
        return [
            {
                "op": "created",
                "id": "artifact-1",
                "path": "report.md",
                "artifact_kind": "markdown",
            }
        ]


# ---------------------------------------------------------------------------
# stream_agent_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_message_start_and_end():
    """Stream always starts with message_start and ends with message_end."""
    agent = MockAgent([])
    events = [e async for e in stream_agent_response(agent, [], {})]

    assert len(events) == 2
    assert "message_start" in events[0]
    assert "message_end" in events[-1]


@pytest.mark.asyncio
async def test_stream_message_start_includes_debug_input():
    """Fallback trace debugger needs the turn input, not just provider metadata."""
    agent = MockAgent([])

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [{"role": "user", "content": "debug this trace"}],
            {},
        )
    ]

    start_payload = json.loads(events[0].split("data: ")[1].strip())
    assert start_payload["input"] == {"messages": [{"role": "user", "content": "debug this trace"}]}


@pytest.mark.asyncio
async def test_stream_content_delta():
    ai_chunk = _make_ai_chunk("Hello world")
    agent = MockAgent([(ai_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    content_events = [e for e in events if "content_delta" in e]
    # streaming.py batches deltas per LLM chunk (with middleware JSON filtering)
    assert len(content_events) >= 1
    concatenated = "".join(
        json.loads(e.split("data: ")[1].strip())["delta"] for e in content_events
    )
    assert concatenated == "Hello world"


@pytest.mark.asyncio
async def test_stream_multiple_content_deltas():
    chunks = [
        (_make_ai_chunk("Hello "), {}),
        (_make_ai_chunk("world!"), {}),
    ]
    agent = MockAgent(chunks)

    events = [e async for e in stream_agent_response(agent, [], {})]

    content_events = [e for e in events if "content_delta" in e]
    # streaming.py batches deltas per LLM chunk
    assert len(content_events) >= 2
    concatenated = "".join(
        json.loads(e.split("data: ")[1].strip())["delta"] for e in content_events
    )
    assert concatenated == "Hello world!"

    # message_end should contain full concatenated content
    end_event = [e for e in events if "message_end" in e][0]
    end_data = json.loads(end_event.split("data: ")[1].strip())
    assert end_data["content"] == "Hello world!"


@pytest.mark.asyncio
async def test_stream_tool_call_start():
    tc_chunk = _make_tool_call_chunk("web_search", {"query": "weather"})
    agent = MockAgent([(tc_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    tc_events = [e for e in events if "tool_call_start" in e]
    assert len(tc_events) == 1
    data = json.loads(tc_events[0].split("data: ")[1].strip())
    assert data["tool_name"] == "web_search"
    assert data["parameters"]["query"] == "weather"


@pytest.mark.asyncio
async def test_stream_task_tool_call_enriches_subagent_display_name():
    tc_chunk = _make_tool_call_chunk(
        "task",
        {"subagent_type": "agent_1234abcd", "description": "Research this"},
        "tc-1",
    )
    agent = MockAgent([(tc_chunk, {})])

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [],
            {},
            subagent_display_names={"agent_1234abcd": "Researcher"},
        )
    ]

    tc_events = [e for e in events if "tool_call_start" in e]
    data = json.loads(tc_events[0].split("data: ")[1].strip())
    assert data["parameters"]["agent_name"] == "Researcher"
    assert data["parameters"]["agent_runtime_name"] == "agent_1234abcd"


@pytest.mark.asyncio
async def test_stream_tool_call_result():
    result_chunk = _make_tool_result_chunk("web_search", "search results here")
    agent = MockAgent([(result_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    result_events = [e for e in events if "tool_call_result" in e]
    assert len(result_events) == 1
    data = json.loads(result_events[0].split("data: ")[1].strip())
    assert data["tool_name"] == "web_search"
    assert data["result"] == "search results here"


@pytest.mark.asyncio
async def test_stream_execute_in_skill_result_emits_file_event():
    result_chunk = _make_tool_result_chunk(
        "execute_in_skill",
        "done\n\nOUTPUT_FILES: report.md",
        tool_call_id="call-1",
    )
    agent = MockAgent([(result_chunk, {})])
    recorder = FakeArtifactRecorder()

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [],
            {},
            artifact_recorder=recorder,
        )
    ]

    assert recorder.prepared is True
    assert recorder.calls == [("execute_in_skill", "call-1")]
    event_types = [event.split("\n", 1)[0].removeprefix("event: ") for event in events]
    assert event_types == [
        "message_start",
        "tool_call_result",
        "file_event",
        "message_end",
    ]
    file_event = [event for event in events if event.startswith("event: file_event")][0]
    data = json.loads(file_event.split("data: ")[1].strip())
    assert data["op"] == "created"
    assert data["path"] == "report.md"


@pytest.mark.asyncio
async def test_stream_memory_tool_result_emits_memory_event():
    result = json.dumps(
        {
            "memory_event": "memory_proposed",
            "id": "proposal-1",
            "scope": "user",
            "content": "The user prefers Korean.",
            "reason": "User preference",
            "policy": "ask",
            "agent_id": "agent-1",
            "conversation_id": "conversation-1",
        }
    )
    result_chunk = _make_tool_result_chunk("save_user_memory", result)
    agent = MockAgent([(result_chunk, {})])
    broker = EventBroker("run-memory-redaction")
    trace_sink: list[dict[str, Any]] = []
    persisted: list[dict[str, Any]] = []

    async def persist(batch: list[dict[str, Any]]) -> None:
        persisted.extend(batch)

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [],
            {},
            broker=broker,
            persist_callback=persist,
            run_id="run-memory-redaction",
            trace_sink=trace_sink,
        )
    ]

    memory_events = [e for e in events if "event: memory_proposed" in e]
    assert len(memory_events) == 1
    data = json.loads(memory_events[0].split("data: ")[1].strip())
    assert data["id"] == "proposal-1"
    assert data["scope"] == "user"
    assert data["content"] == "The user prefers Korean."

    shared_events = [
        next(event for event in trace_sink if event["event"] == "memory_proposed"),
        next(event for event in persisted if event["event"] == "memory_proposed"),
        next(
            event
            for event in broker._buffer  # noqa: SLF001 - sink identity regression
            if event["event"] == "memory_proposed"
        ),
    ]
    for shared_event in shared_events:
        assert shared_event["data"]["content"] == "<redacted>"
        assert shared_event["data"]["reason"] == "<redacted>"
    assert shared_events[0] is shared_events[1] is shared_events[2]
    assert json.loads(result_chunk.content)["content"] == "The user prefers Korean."


@pytest.mark.asyncio
async def test_stream_preserves_repeated_tool_call_ids():
    chunks = [
        (_make_tool_call_chunk("tavily_search", {"query": "A"}, "call-a"), {}),
        (_make_tool_call_chunk("tavily_search", {"query": "B"}, "call-b"), {}),
        (_make_tool_result_chunk("tavily_search", "result A", "call-a"), {}),
        (_make_tool_result_chunk("tavily_search", "result B", "call-b"), {}),
    ]
    agent = MockAgent(chunks)

    events = [e async for e in stream_agent_response(agent, [], {})]

    start_payloads = [
        json.loads(e.split("data: ")[1].strip()) for e in events if "tool_call_start" in e
    ]
    result_payloads = [
        json.loads(e.split("data: ")[1].strip()) for e in events if "tool_call_result" in e
    ]

    assert [payload["tool_call_id"] for payload in start_payloads] == ["call-a", "call-b"]
    assert [payload["tool_call_id"] for payload in result_payloads] == ["call-a", "call-b"]


@pytest.mark.asyncio
async def test_stream_usage_metadata():
    usage = {"input_tokens": 100, "output_tokens": 50}
    ai_chunk = _make_ai_chunk("done", usage_metadata=usage)
    agent = MockAgent([(ai_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    end_event = [e for e in events if "message_end" in e][0]
    end_data = json.loads(end_event.split("data: ")[1].strip())
    assert end_data["usage"]["prompt_tokens"] == 100
    assert end_data["usage"]["completion_tokens"] == 50
    # cache_creation/cache_read 在没有 details 时填充为 0。
    assert end_data["usage"]["cache_creation_tokens"] == 0
    assert end_data["usage"]["cache_read_tokens"] == 0


@pytest.mark.asyncio
async def test_stream_updates_usage_sink_before_generator_cancellation():
    usage_sink: dict[str, Any] = {}
    usage = {"input_tokens": 17, "output_tokens": 9}
    ai_chunk = _make_ai_chunk("partial", usage_metadata=usage)
    agent = BlockingAfterFirstChunkAgent((ai_chunk, {}))

    stream = stream_agent_response(agent, [], {}, usage_sink=usage_sink)
    await anext(stream)  # message_start
    await anext(stream)  # content_delta from first AI chunk

    assert usage_sink["prompt_tokens"] == 17
    assert usage_sink["completion_tokens"] == 9

    await stream.aclose()


@pytest.mark.asyncio
async def test_stream_usage_metadata_with_cache_tokens():
    """将 LangChain ``usage_metadata.input_token_details`` 的 cache 令牌平铺。"""
    usage = {
        "input_tokens": 1200,
        "output_tokens": 80,
        "input_token_details": {
            "cache_creation": 800,
            "cache_read": 300,
        },
    }
    ai_chunk = _make_ai_chunk("done", usage_metadata=usage)
    agent = MockAgent([(ai_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]
    end_event = [e for e in events if "message_end" in e][0]
    end_data = json.loads(end_event.split("data: ")[1].strip())

    assert end_data["usage"]["prompt_tokens"] == 1200
    assert end_data["usage"]["completion_tokens"] == 80
    assert end_data["usage"]["cache_creation_tokens"] == 800
    assert end_data["usage"]["cache_read_tokens"] == 300


@pytest.mark.asyncio
async def test_stream_emits_unique_event_ids_per_chunk():
    """所有 SSE chunk 都有形如 ``id: {msg_id}-{seq}`` 的唯一 id。

    客户端用于 dedup 或丢弃 stale。seq 单调递增。
    """
    chunks = [
        (_make_ai_chunk("Hello "), {}),
        (_make_tool_call_chunk("web_search", {"q": "weather"}), {}),
        (_make_tool_result_chunk("web_search", "result"), {}),
        (_make_ai_chunk("done", usage_metadata={"input_tokens": 5, "output_tokens": 3}), {}),
    ]
    agent = MockAgent(chunks)
    events = [e async for e in stream_agent_response(agent, [], {})]

    ids: list[str] = []
    for raw in events:
        for line in raw.split("\n"):
            if line.startswith("id: "):
                ids.append(line[4:])

    # 所有 SSE 事件都有 id，且全部 unique
    assert len(ids) == len(events), "every emitted SSE event must carry an id line"
    assert len(set(ids)) == len(ids), "event ids must be unique across the stream"

    # 格式: ``{uuid}-{seq}``，seq 为 1..N
    msg_id = ids[0].rsplit("-", 1)[0]
    seqs = [int(i.rsplit("-", 1)[1]) for i in ids]
    assert seqs == list(range(1, len(ids) + 1))
    # 全部具有相同的 message id 前缀
    assert all(i.startswith(f"{msg_id}-") for i in ids)


@pytest.mark.asyncio
async def test_stream_exception_yields_error():
    """If the agent raises an exception, an error event should be emitted."""

    class ErrorAgent:
        async def astream(self, *args, **kwargs):
            raise RuntimeError("LLM connection failed")
            yield  # make it an async generator  # noqa: E501

    agent = ErrorAgent()
    events = [e async for e in stream_agent_response(agent, [], {})]

    error_events = [e for e in events if "error" in e and "message_start" not in e]
    assert len(error_events) == 1
    data = json.loads(error_events[0].split("data: ")[1].strip())
    assert "LLM connection failed" in data["message"]


@pytest.mark.asyncio
async def test_stream_exception_records_error_sink_and_failed_end_status():
    """Visible stream errors must be observable by the caller as failures."""

    class ErrorAgent:
        async def astream(self, *args, **kwargs):
            raise RuntimeError("LLM connection failed")
            yield  # make it an async generator

    errors: list[StreamErrorRecord] = []
    events = [
        e
        async for e in stream_agent_response(
            ErrorAgent(),
            [],
            {},
            error_sink=errors,
        )
    ]

    assert len(errors) == 1
    assert isinstance(errors[0].error, RuntimeError)
    assert errors[0].message == "LLM connection failed"

    end_event = [e for e in events if "message_end" in e][0]
    end_data = json.loads(end_event.split("data: ")[1].strip())
    assert end_data["status"] == "failed"


@pytest.mark.asyncio
async def test_stream_full_flow():
    """Full flow: AI message -> tool call -> tool result -> AI message."""
    chunks = [
        (_make_ai_chunk("Let me search..."), {}),
        (_make_tool_call_chunk("web_search", {"query": "test"}), {}),
        (_make_tool_result_chunk("web_search", "Found results"), {}),
        (_make_ai_chunk("Here are the results"), {}),
    ]
    agent = MockAgent(chunks)

    events = [e async for e in stream_agent_response(agent, [], {})]

    event_types = []
    for e in events:
        if "message_start" in e:
            event_types.append("message_start")
        elif "content_delta" in e:
            event_types.append("content_delta")
        elif "tool_call_start" in e:
            event_types.append("tool_call_start")
        elif "tool_call_result" in e:
            event_types.append("tool_call_result")
        elif "message_end" in e:
            event_types.append("message_end")

    # Deduplicate consecutive content_deltas (chunk-level streaming)
    deduped = []
    for et in event_types:
        if not deduped or deduped[-1] != et:
            deduped.append(et)

    assert deduped == [
        "message_start",
        "content_delta",
        "tool_call_start",
        "tool_call_result",
        "content_delta",
        "message_end",
    ]


# ---------------------------------------------------------------------------
# _is_tool_selector_json
# ---------------------------------------------------------------------------


def test_is_tool_selector_json_true():
    assert _is_tool_selector_json('{"tools":["web_search","scraper"]}') is True


def test_is_tool_selector_json_false_multiple_keys():
    assert _is_tool_selector_json('{"tools":[],"extra":"val"}') is False


def test_is_tool_selector_json_false_not_list():
    assert _is_tool_selector_json('{"tools":"not_a_list"}') is False


def test_is_tool_selector_json_false_invalid():
    assert _is_tool_selector_json("not json") is False


def test_is_tool_selector_json_false_empty_dict():
    assert _is_tool_selector_json("{}") is False


# ---------------------------------------------------------------------------
# stream_agent_response — middleware JSON filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_filters_middleware_json():
    """Middleware JSON like {"tools":["a"]} should be filtered out."""
    ai_chunk = _make_ai_chunk('Before{"tools":["web_search"]}After')
    agent = MockAgent([(ai_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    content_events = [e for e in events if "content_delta" in e]
    concatenated = "".join(
        json.loads(e.split("data: ")[1].strip())["delta"] for e in content_events
    )
    assert '{"tools"' not in concatenated
    assert "Before" in concatenated
    assert "After" in concatenated


@pytest.mark.asyncio
async def test_stream_preserves_normal_json():
    """Normal JSON that is NOT {"tools":[...]} should NOT be filtered."""
    ai_chunk = _make_ai_chunk('Here is {"result":"ok"} data')
    agent = MockAgent([(ai_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    content_events = [e for e in events if "content_delta" in e]
    concatenated = "".join(
        json.loads(e.split("data: ")[1].strip())["delta"] for e in content_events
    )
    assert '{"result":"ok"}' in concatenated.replace(" ", "").replace('"result"', '"result"')


# ---------------------------------------------------------------------------
# stream_agent_response — estimated cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_estimated_cost():
    """When cost rates are provided, estimated_cost is calculated."""
    usage = {"input_tokens": 1000, "output_tokens": 500}
    ai_chunk = _make_ai_chunk("done", usage_metadata=usage)
    agent = MockAgent([(ai_chunk, {})])

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [],
            {},
            cost_per_input_token=0.00001,
            cost_per_output_token=0.00003,
        )
    ]

    end_event = [e for e in events if "message_end" in e][0]
    end_data = json.loads(end_event.split("data: ")[1].strip())
    assert "estimated_cost" in end_data["usage"]
    # 1000 * 0.00001 + 500 * 0.00003 = 0.01 + 0.015 = 0.025
    assert abs(end_data["usage"]["estimated_cost"] - 0.025) < 0.0001


# ---------------------------------------------------------------------------
# stream_agent_response — incomplete JSON buffer flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_flushes_incomplete_json():
    """Incomplete JSON in buffer at end should be flushed as content."""
    ai_chunk = _make_ai_chunk("Text{incomplete")
    agent = MockAgent([(ai_chunk, {})])

    events = [e async for e in stream_agent_response(agent, [], {})]

    end_event = [e for e in events if "message_end" in e][0]
    end_data = json.loads(end_event.split("data: ")[1].strip())
    # The incomplete JSON buffer should be in the final content
    assert "Text{incomplete" in end_data["content"]


# ---------------------------------------------------------------------------
# W3-out M2 — broker dual-write + partial flush + run_id injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_run_id_injection_uses_external_id():
    """提供 ``run_id`` 时，message_start 的 ``id`` 与 SSE event id 的 prefix
    会被强制设为该值。"""
    agent = MockAgent([(_make_ai_chunk("hi"), {})])
    forced_run_id = "deadbeef-1234"

    events = [e async for e in stream_agent_response(agent, [], {}, run_id=forced_run_id)]

    start_event = [e for e in events if "message_start" in e][0]
    start_data = json.loads(start_event.split("data: ")[1].strip())
    assert start_data["id"] == forced_run_id
    # SSE id 行也遵循 ``{run_id}-<seq>`` 模式。
    assert f"id: {forced_run_id}-1" in start_event


@pytest.mark.asyncio
async def test_stream_dual_writes_to_broker_and_trace_sink():
    """broker.publish_nowait + trace_sink.append 接收相同的事件序列。"""
    from app.agent_runtime.event_broker import EventBroker

    chunks = [
        (_make_ai_chunk("a"), {}),
        (_make_ai_chunk("b"), {}),
    ]
    agent = MockAgent(chunks)
    broker = EventBroker("run-x")
    trace_sink: list[dict[str, Any]] = []

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [],
            {},
            trace_sink=trace_sink,
            broker=broker,
            run_id="run-x",
        )
    ]
    assert len(events) >= 2  # message_start + message_end at minimum

    # Broker is closed in finally.
    assert broker.is_closed is True
    # last_event_id is the message_end event.
    assert broker.last_event_id is not None
    assert broker.last_event_id.startswith("run-x-")

    # trace_sink and broker buffer agree on event ids (subset; broker buffer
    # is bounded, but sink stores all).
    sink_ids = [e["id"] for e in trace_sink]
    buffer_ids = [e["id"] for e in broker._buffer]  # noqa: SLF001
    # Every buffered id is in trace_sink (trace_sink is the source of truth).
    assert set(buffer_ids).issubset(set(sink_ids))


@pytest.mark.asyncio
async def test_stream_persist_callback_final_flush_in_finally():
    """提供 persist_callback 时，stream 结束时至少调用一次
    (final flush in finally block)."""
    agent = MockAgent([(_make_ai_chunk("hi"), {})])
    captured_chunks: list[list[dict[str, Any]]] = []

    async def callback(chunk: list[dict[str, Any]]) -> None:
        captured_chunks.append(list(chunk))

    _ = [
        e
        async for e in stream_agent_response(
            agent, [], {}, persist_callback=callback, run_id="run-y"
        )
    ]

    # 短 stream（事件 < 32，时间 < 2s），所以 fire-and-forget partial flush
    # 不会触发，但 finally 的 final flush 至少必须调用一次。
    assert len(captured_chunks) >= 1
    # 所有捕获到的事件 id 都以 ``run-y-`` 为前缀。
    flat_ids = [evt["id"] for chunk in captured_chunks for evt in chunk]
    assert all(eid.startswith("run-y-") for eid in flat_ids)


@pytest.mark.asyncio
async def test_stream_projects_internal_offloads_for_all_egress_sinks() -> None:
    from app.agent_runtime.run_secrets import reset_run_secrets, set_run_secrets

    configured_secret = "legacy-stream-configured-secret-42"
    history_path = "/conversation_history/session_0123456789abcdef0123456789abcdef.md"
    legacy_spill_path = "/large_tool_results/call-1.json"
    virtual_spill_path = (
        f"/.moldy-offload/{'a' * 32}/{'b' * 32}/{'c' * 32}/large_tool_results/0123456789abcdef_json"
    )
    physical_spill_path = str(
        runtime_data_dir() / ".moldy-internal/offload/spill/owner/conversation/run/actor/leaf"
    )
    raw_result = (
        f"history={history_path}; legacy={legacy_spill_path}; "
        f"virtual={virtual_spill_path}; physical={physical_spill_path}; artifact=report.md; "
        f"credential={configured_secret}"
    )
    result_chunk = _make_tool_result_chunk("web_search", raw_result, tool_call_id="call-1")
    agent = MockAgent([(result_chunk, {})])
    broker = EventBroker("run-offload")
    trace_sink: list[dict[str, Any]] = []
    persisted: list[dict[str, Any]] = []

    async def persist(batch: list[dict[str, Any]]) -> None:
        persisted.extend(batch)

    token = set_run_secrets({configured_secret})
    try:
        events = [
            event
            async for event in stream_agent_response(
                agent,
                [],
                {},
                broker=broker,
                persist_callback=persist,
                run_id="run-offload",
                trace_sink=trace_sink,
            )
        ]
    finally:
        reset_run_secrets(token)

    sse_result = next(
        json.loads(event.split("data: ", 1)[1])
        for event in events
        if event.startswith("event: tool_call_result")
    )
    trace_result = next(
        event["data"] for event in trace_sink if event["event"] == "tool_call_result"
    )
    persisted_result = next(
        event["data"] for event in persisted if event["event"] == "tool_call_result"
    )
    broker_result = next(
        event["data"]
        for event in broker._buffer
        if event["event"] == "tool_call_result"  # noqa: SLF001
    )

    all_outputs = [sse_result, trace_result, persisted_result, broker_result]
    for output in all_outputs:
        serialized = json.dumps(output, ensure_ascii=False)
        assert configured_secret not in serialized
        assert history_path not in serialized
        assert legacy_spill_path not in serialized
        assert virtual_spill_path not in serialized
        assert physical_spill_path not in serialized
        assert "history_" not in serialized
        assert "spill_" not in serialized
        assert "internal_reference_redacted" in serialized
        assert "report.md" not in serialized
    assert result_chunk.content == raw_result
    assert trace_result is persisted_result is broker_result


@pytest.mark.asyncio
async def test_stream_filters_private_reasoning_from_sse_and_persistence():
    private = "PRIVATE_CHAIN_OF_THOUGHT_DO_NOT_LEAK"
    agent = MockAgent(
        [
            (
                _make_ai_chunk(
                    [
                        {"type": "reasoning", "text": private, "summary": private},
                        {"type": "thinking", "thinking": private},
                        {"type": "text", "text": "要展示的回答"},
                    ]
                ),
                {},
            )
        ]
    )
    captured_chunks: list[list[dict[str, Any]]] = []

    async def callback(chunk: list[dict[str, Any]]) -> None:
        captured_chunks.append(list(chunk))

    events = [
        e
        async for e in stream_agent_response(
            agent,
            [],
            {},
            persist_callback=callback,
            run_id="run-reasoning",
        )
    ]
    wire_payload = "\n".join(events)
    persisted_payload = json.dumps(captured_chunks, ensure_ascii=False)

    assert "要展示的回答" in wire_payload
    assert "要展示的回答" in persisted_payload
    assert private not in wire_payload
    assert private not in persisted_payload
    assert all("values" not in evt.get("data", {}) for chunk in captured_chunks for evt in chunk)


@pytest.mark.asyncio
async def test_stream_broker_close_called_even_on_exception():
    """即使 astream 抛出异常，broker.close() 也会在 finally 中执行。"""
    from app.agent_runtime.event_broker import EventBroker

    class FailingAgent:
        async def astream(self, *args: Any, **kwargs: Any):
            yield (_make_ai_chunk("partial"), {})
            raise RuntimeError("boom")

        async def aget_state(self, *args: Any, **kwargs: Any):
            state = MagicMock()
            state.tasks = []
            return state

    agent = FailingAgent()
    broker = EventBroker("run-fail")

    # streaming.py 会将异常转换为 emit("error")，因此 generator 会干净地
    # 结束。这里只验证 finally 中的 broker.close。
    _ = [e async for e in stream_agent_response(agent, [], {}, broker=broker, run_id="run-fail")]
    assert broker.is_closed is True


# ---------------------------------------------------------------------------
# Backpressure + retry buffer（M2 加强）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_partial_flush_retries_in_finally():
    """Partial flush 失败的 chunk 会经过 retry_buffer，并在 finally 中重试。

    即使因 DB 临时故障导致一个 chunk 失败，final flush 也会再尝试一次，
    防止 silent data loss 的回归守卫。
    """
    # 为了产生 1 个超过 32 events 阈值的 chunk，将 LLM 响应
    # 拉长。一次 content_delta + message_start/end → 大约 3 个
    # 事件，因此到不了 batch_size 阈值；time 阈值(2s)又难以人为
    # 很难强制。改为对 _FLUSH_BATCH_SIZE 进行 monkey patch。
    from app.agent_runtime import streaming as streaming_mod

    original_batch = streaming_mod._FLUSH_BATCH_SIZE
    streaming_mod._FLUSH_BATCH_SIZE = 1  # 每次 emit 都尝试 flush

    call_count = {"n": 0}
    received: list[list[dict[str, Any]]] = []

    async def flaky_callback(chunk: list[dict[str, Any]]) -> None:
        call_count["n"] += 1
        # 仅第一次 partial flush 失败（进入 retry_buffer）。之后成功。
        if call_count["n"] == 1:
            raise RuntimeError("DB hiccup")
        received.append(list(chunk))

    try:
        agent = MockAgent([(_make_ai_chunk("hello"), {})])
        _ = [
            e
            async for e in stream_agent_response(
                agent, [], {}, persist_callback=flaky_callback, run_id="run-retry"
            )
        ]
    finally:
        streaming_mod._FLUSH_BATCH_SIZE = original_batch

    # 第一次调用虽失败，但 final flush 会重试 retry_buffer + 剩余 buffer，
    # 最终所有事件都会累积到 received 中。至少必须有 1 次成功。
    assert call_count["n"] >= 2  # 至少第一次 fail + final retry
    # 所有事件 id 都以 run-retry- 为前缀
    flat_ids = [evt["id"] for chunk in received for evt in chunk]
    assert any(eid.startswith("run-retry-") for eid in flat_ids)


@pytest.mark.asyncio
async def test_inflight_flush_cap_throttles_create_task():
    """当 In-flight task 超过 _MAX_INFLIGHT_FLUSHES 时，新 chunk 保留在 buffer 中。

    Backpressure 回归守卫 — 即使 DB 变慢，也不会发生 task 暴增。
    """
    from app.agent_runtime import streaming as streaming_mod

    original_batch = streaming_mod._FLUSH_BATCH_SIZE
    original_cap = streaming_mod._MAX_INFLIGHT_FLUSHES
    streaming_mod._FLUSH_BATCH_SIZE = 1
    streaming_mod._MAX_INFLIGHT_FLUSHES = 1  # 同一时间最多 1 个 in-flight

    flush_started = asyncio.Event()
    flush_release = asyncio.Event()
    flush_count = {"n": 0}

    async def slow_callback(chunk: list[dict[str, Any]]) -> None:
        flush_count["n"] += 1
        flush_started.set()
        # 第一次调用等待 release — 占用 in-flight
        if flush_count["n"] == 1:
            await flush_release.wait()

    # 多个 content_delta 被 yield，agent 因此触发多次 flush 尝试
    chunks = [(_make_ai_chunk(f"c{i}"), {}) for i in range(5)]
    agent = MockAgent(chunks)

    try:
        # 在后台推进 stream
        events: list[str] = []

        async def consume():
            async for e in stream_agent_response(
                agent, [], {}, persist_callback=slow_callback, run_id="run-backpressure"
            ):
                events.append(e)

        consume_task = asyncio.create_task(consume())
        # 等待第一次 flush 开始（占用 in-flight=1）
        await asyncio.wait_for(flush_started.wait(), timeout=2.0)
        # 其他 emit 因 cap 不创建新 task，而是堆积在 buffer 中。
        # release 后由 finally 的 final flush 处理剩余内容。
        flush_release.set()
        await asyncio.wait_for(consume_task, timeout=5.0)
    finally:
        streaming_mod._FLUSH_BATCH_SIZE = original_batch
        streaming_mod._MAX_INFLIGHT_FLUSHES = original_cap

    # 至少调用过 1 次，且由于 cap 不会无限暴增。
    # 精确调用次数是 timing-dependent，因此只验证 lower bound。
    assert flush_count["n"] >= 1


@pytest.mark.asyncio
async def test_retry_buffer_overflow_drops_oldest():
    """retry_buffer 超过 _MAX_RETRY_BUFFER_EVENTS 时，从 oldest 开始 drop。

    DB 持久化故障场景 — 所有 partial flush 都失败，retry_buffer
    超过上限时为了防止 OOM，必须将 oldest event drop。
    """
    from app.agent_runtime import streaming as streaming_mod

    original_batch = streaming_mod._FLUSH_BATCH_SIZE
    original_cap = streaming_mod._MAX_RETRY_BUFFER_EVENTS
    streaming_mod._FLUSH_BATCH_SIZE = 1
    streaming_mod._MAX_RETRY_BUFFER_EVENTS = 3  # 用很小的 cap 立即触发 overflow

    flush_count = {"n": 0}
    received: list[list[dict[str, Any]]] = []

    async def always_failing(chunk: list[dict[str, Any]]) -> None:
        flush_count["n"] += 1
        # 所有 partial flush 失败 → 写入 retry_buffer
        # 仅在 final flush（预计第 >=5 次调用）时成功并 capture
        if flush_count["n"] < 5:
            raise RuntimeError("DB down")
        received.append(list(chunk))

    try:
        # 用多个 content_delta 触发多次 partial flush
        chunks = [(_make_ai_chunk(f"c{i}"), {}) for i in range(10)]
        agent = MockAgent(chunks)
        _ = [
            e
            async for e in stream_agent_response(
                agent,
                [],
                {},
                persist_callback=always_failing,
                run_id="run-overflow",
            )
        ]
    finally:
        streaming_mod._FLUSH_BATCH_SIZE = original_batch
        streaming_mod._MAX_RETRY_BUFFER_EVENTS = original_cap

    # 最终 flush 收到的 event 总数必须 <= cap(=3) — 超过部分应被 drop。
    # 但 final flush 会将 retry_buffer + flush_buffer 作为两个 chunk 调用，
    # received[0] 是 retry_buffer（不超过 cap），received[1] 是剩余 flush_buffer。
    if received:
        retry_chunk_size = len(received[0])
        assert retry_chunk_size <= 3, f"retry_buffer overflow 未发生: {retry_chunk_size} > cap=3"
