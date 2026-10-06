from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent_runtime.event_broker import EventBroker
from app.agent_runtime.langgraph_streaming import stream_agent_response_langgraph
from app.agent_runtime.streaming import StreamErrorRecord
from tests.agent_runtime.langgraph_streaming_fixtures import (
    ErrorAgent,
    FallbackAgent,
    MidStreamAttributeErrorAgent,
    ProtocolAgent,
    StateBackedProtocolAgent,
    sse_payload,
)


@pytest.mark.asyncio
async def test_langgraph_streaming_projects_usage_metadata_to_custom_event() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {
            "namespace": [],
            "data": {
                "id": "assistant-usage-1",
                "type": "AIMessageChunk",
                "content": "done",
                "usage_metadata": {
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "input_token_details": {
                        "cache_creation": 2,
                        "cache_read": 3,
                    },
                },
            },
        },
        "seq": 1,
        "event_id": "usage-upstream-1",
    }
    usage_sink: dict[str, Any] = {}
    agent = ProtocolAgent([raw_event])

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-usage"}},
            cost_per_input_token=0.01,
            cost_per_output_token=0.02,
            usage_sink=usage_sink,
            run_id="run-usage",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert [payload["method"] for payload in payloads] == [
        "lifecycle",
        "messages",
        "custom",
        "lifecycle",
    ]
    assert payloads[0]["params"]["data"] == {"event": "running"}
    usage_event_data = payloads[2]["params"]["data"]
    assert usage_event_data["name"] == "usage"
    usage_payload = usage_event_data["payload"]
    # 核心 usage（token/费用）键必须完全一致。
    for key, value in {
        "assistant_msg_id": "assistant-usage-1",
        "run_id": "run-usage",
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "cache_creation_tokens": 2,
        "cache_read_tokens": 3,
        "estimated_cost": 0.22,
    }.items():
        assert usage_payload[key] == value
    # streaming timing 也包含在 usage payload 中（值基于 monotonic，具有不确定性，因此
    # 只验证存在性/类型）。messages 事件早于 usage，因此 TTFT 也会测量。
    assert isinstance(usage_payload["generation_ms"], float)
    assert isinstance(usage_payload["tokens_per_second"], float)
    assert isinstance(usage_payload["ttft_ms"], float)
    assert payloads[3]["params"]["data"] == {"event": "completed"}
    for key, value in {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "cache_creation_tokens": 2,
        "cache_read_tokens": 3,
        "estimated_cost": 0.22,
    }.items():
        assert usage_sink[key] == value
    for key in ("ttft_ms", "generation_ms", "tokens_per_second"):
        assert usage_sink[key] == usage_payload[key]


@pytest.mark.asyncio
async def test_langgraph_streaming_emits_subagent_display_names_at_head() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "hi"}},
        "seq": 1,
        "event_id": "upstream-1",
    }
    agent = ProtocolAgent([raw_event])

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-names"}},
            run_id="run-names",
            subagent_display_names={"agent_12345678": "研究机器人"},
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    # The display-name map rides a custom event right after ``running`` so the
    # frontend has the runtime_name -> display_name mapping before any task pill.
    assert [payload["method"] for payload in payloads] == [
        "lifecycle",
        "custom",
        "messages",
        "lifecycle",
    ]
    assert payloads[0]["params"]["data"] == {"event": "running"}
    names_event = payloads[1]["params"]["data"]
    assert names_event["name"] == "moldy.subagent_names"
    assert names_event["payload"] == {"names": {"agent_12345678": "研究机器人"}}


@pytest.mark.asyncio
async def test_langgraph_streaming_emits_memory_recalled_at_head() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "hi"}},
        "seq": 1,
        "event_id": "upstream-1",
    }
    agent = ProtocolAgent([raw_event])
    briefs = [
        {"id": "m1", "scope": "user", "content": "偏好用韩语回答"},
        {"id": "m2", "scope": "agent", "content": "报告整理成表格"},
    ]

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-memory"}},
            run_id="run-memory",
            recalled_memories=briefs,
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    # recalled brief 在 running 后立即以 custom 事件发出 — 可在首个 token 前显示 chip。
    assert [payload["method"] for payload in payloads] == [
        "lifecycle",
        "custom",
        "messages",
        "lifecycle",
    ]
    recalled_event = payloads[1]["params"]["data"]
    assert recalled_event["name"] == "moldy.memory_recalled"
    assert recalled_event["payload"] == {"memories": briefs}
    # replay/reload dedup — stable event id 合约（与 subagent_names 相同）。
    assert payloads[1]["event_id"] == "run-memory:memory_recalled"


@pytest.mark.asyncio
async def test_langgraph_streaming_persists_masked_memory_but_streams_content() -> None:
    """BE-P5(b) 回归保护 — 即使 persist 复用 wire redaction 结果，W2-3
    合约仍保持：live wire 中会传递记忆内容，而进入 message_events 的
    persist buffer 中只保留 ``<redacted>``。"""
    agent = ProtocolAgent([])
    persisted: list[list[dict[str, Any]]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-memory-persist"}},
            persist_callback=persist,
            run_id="run-memory-persist",
            recalled_memories=[{"id": "m1", "scope": "user", "content": "偏好用韩语回答"}],
        )
    ]

    assert "偏好用韩语回答" in "".join(chunks)
    stored = [event for batch in persisted for event in batch]
    recalled = [
        event
        for event in stored
        if event["method"] == "custom" and event["data"].get("name") == "moldy.memory_recalled"
    ]
    assert len(recalled) == 1
    assert recalled[0]["data"]["payload"]["memories"] == [
        {"id": "m1", "scope": "user", "content": "<redacted>"}
    ]


@pytest.mark.asyncio
async def test_langgraph_streaming_failed_partial_flush_recovers_in_order() -> None:
    """BE-P5(e) — fire-and-forget partial flush 失败不会杀死 stream，
    失败的 chunk 会恢复到 buffer 前部，并在之后/最终 flush 中按原顺序
    重试（丢失0，重复0，seq 单调）。"""
    raw_events = [
        {
            "type": "event",
            "method": "messages",
            "params": {"namespace": [], "data": {"chunk": f"tok-{i}"}},
            "seq": i + 1,
            "event_id": f"upstream-{i + 1}",
        }
        for i in range(40)  # 超过 _FLUSH_BATCH_SIZE(32) → stream 中发生 flush
    ]
    agent = ProtocolAgent(raw_events)
    successful: list[list[dict[str, Any]]] = []
    fail_first = {"armed": True}

    async def persist(events: list[dict[str, Any]]) -> None:
        if fail_first["armed"]:
            fail_first["armed"] = False
            raise RuntimeError("transient DB failure")
        successful.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-flush-retry"}},
            persist_callback=persist,
            run_id="run-flush-retry",
        )
    ]

    assert fail_first["armed"] is False, "第一个 flush 失败路径必须实际执行"
    payloads = [sse_payload(chunk) for chunk in chunks]
    assert payloads[-1]["method"] == "lifecycle"
    assert payloads[-1]["params"]["data"] == {"event": "completed"}

    stored = [event for batch in successful for event in batch]
    stored_ids = [event["id"] for event in stored]
    assert len(stored_ids) == len(set(stored_ids)), "禁止因重试产生重复 persist"
    assert len(stored) == len(chunks), "包括失败 chunk 在内的所有事件最终都应 persist"
    seqs = [event["seq"] for event in stored]
    assert seqs == sorted(seqs), "失败 chunk 恢复到 buffer 前部并保持顺序"


@pytest.mark.asyncio
async def test_langgraph_streaming_survives_total_persist_failure() -> None:
    """即使 persist 一直失败，live SSE stream 也会完整跑完 — DB 故障
    不阻塞用户响应，丢失只记录在 log 中（与 legacy 合约相同）。"""
    raw_events = [
        {
            "type": "event",
            "method": "messages",
            "params": {"namespace": [], "data": {"chunk": f"tok-{i}"}},
            "seq": i + 1,
            "event_id": f"upstream-{i + 1}",
        }
        for i in range(40)
    ]
    agent = ProtocolAgent(raw_events)

    async def persist(_events: list[dict[str, Any]]) -> None:
        raise RuntimeError("persistent DB outage")

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-flush-outage"}},
            persist_callback=persist,
            run_id="run-flush-outage",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert len(payloads) == 42  # lifecycle running + 40 messages + lifecycle completed
    assert payloads[-1]["params"]["data"] == {"event": "completed"}


@pytest.mark.asyncio
async def test_langgraph_streaming_orders_names_before_memory_recalled() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "hi"}},
        "seq": 1,
        "event_id": "upstream-1",
    }
    agent = ProtocolAgent([raw_event])

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-both"}},
            run_id="run-both",
            subagent_display_names={"agent_12345678": "研究机器人"},
            recalled_memories=[{"id": "m1", "scope": "user", "content": "注释"}],
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    custom_names = [
        payload["params"]["data"]["name"] for payload in payloads if payload["method"] == "custom"
    ]
    assert custom_names == ["moldy.subagent_names", "moldy.memory_recalled"]


@pytest.mark.asyncio
async def test_langgraph_streaming_omits_memory_recalled_when_absent() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "hi"}},
        "seq": 1,
        "event_id": "upstream-1",
    }
    agent = ProtocolAgent([raw_event])

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-no-memory"}},
            run_id="run-no-memory",
            recalled_memories=[],
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert all(
        payload["params"]["data"].get("name") != "moldy.memory_recalled"
        for payload in payloads
        if payload["method"] == "custom"
    )


@pytest.mark.asyncio
async def test_langgraph_streaming_omits_subagent_names_when_absent() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "hi"}},
        "seq": 1,
        "event_id": "upstream-1",
    }
    agent = ProtocolAgent([raw_event])

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-none"}},
            run_id="run-none",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert [payload["method"] for payload in payloads] == [
        "lifecycle",
        "messages",
        "lifecycle",
    ]
    assert all(
        payload["params"]["data"].get("name") != "moldy.subagent_names"
        for payload in payloads
        if payload["method"] == "custom"
    )


@pytest.mark.asyncio
async def test_langgraph_streaming_emits_protocol_sse_and_dual_writes() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "hello"}},
        "seq": 1,
        "event_id": "upstream-1",
    }
    raw_interrupt_event = {
        "type": "event",
        "method": "values",
        "params": {
            "namespace": ["tools:call-1"],
            "data": {"__interrupt__": [{"id": "intr-1", "value": {"question": "approve?"}}]},
        },
        "seq": 2,
        "event_id": "upstream-2",
    }
    agent = ProtocolAgent([raw_event, raw_interrupt_event])
    broker = EventBroker("run-1")
    persisted: list[list[dict[str, Any]]] = []
    trace_sink: list[dict[str, Any]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            [{"role": "user", "content": "hello"}],
            {"configurable": {"thread_id": "thread-1"}},
            broker=broker,
            persist_callback=persist,
            run_id="run-1",
            trace_sink=trace_sink,
        )
    ]

    assert agent.inputs == [{"messages": [{"role": "user", "content": "hello"}]}]
    payloads = [sse_payload(chunk) for chunk in chunks]
    assert len(chunks) == 5
    assert chunks[1].startswith("id: upstream-1\nevent: message\n")
    assert payloads[0]["method"] == "lifecycle"
    assert payloads[0]["params"]["data"] == {"event": "running"}
    assert payloads[1]["method"] == "messages"
    assert payloads[3]["method"] == "input.requested"
    assert payloads[4]["params"]["data"] == {"event": "interrupted"}
    assert persisted[0][1]["method"] == "messages"
    assert persisted[0][1]["upstream_event_id"] == "upstream-1"
    assert persisted[0][3]["method"] == "input.requested"
    assert persisted[0][3]["data"]["interrupt_id"] == "intr-1"
    assert persisted[0][4]["method"] == "lifecycle"
    assert trace_sink[3]["method"] == "input.requested"

    sequences = [payload["seq"] for payload in payloads]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))

    replayed = [event async for event in broker.subscribe()]
    assert replayed[1]["id"] == "upstream-1"
    assert replayed[0]["event"] == "message"
    assert replayed[1]["data"]["method"] == "messages"
    assert replayed[3]["data"]["method"] == "input.requested"
    assert replayed[4]["data"]["method"] == "lifecycle"


@pytest.mark.asyncio
async def test_langgraph_streaming_persists_compact_values_snapshots() -> None:
    raw_event = {
        "type": "event",
        "method": "values",
        "params": {
            "namespace": [],
            "data": {
                "messages": [
                    {
                        "id": "msg-1",
                        "type": "ai",
                        "content": "large assistant text that belongs in the checkpoint",
                        "additional_kwargs": {"reasoning": "private chain"},
                    }
                ],
                "todos": [{"id": "todo-1", "content": "ship v3", "status": "in_progress"}],
            },
        },
        "seq": 1,
        "event_id": "values-1",
    }
    agent = ProtocolAgent([raw_event])
    persisted: list[list[dict[str, Any]]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-values"}},
            persist_callback=persist,
            run_id="run-values",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    live_values = [payload for payload in payloads if payload["method"] == "values"][0]
    assert live_values["params"]["data"]["messages"][0]["content"] == (
        "large assistant text that belongs in the checkpoint"
    )

    persisted_values = [event for event in persisted[0] if event["method"] == "values"][0]
    assert persisted_values["data"] == {
        "messages": [{"id": "msg-1", "type": "ai"}],
        "todos": [{"id": "todo-1", "content": "ship v3", "status": "in_progress"}],
    }


@pytest.mark.asyncio
async def test_langgraph_streaming_emits_state_pending_interrupt_before_persist_and_close() -> None:
    raw_event = {
        "type": "event",
        "method": "messages",
        "params": {"namespace": [], "data": {"chunk": "waiting"}},
        "seq": 1,
        "event_id": "upstream-waiting",
    }
    long_interrupt_id = "intr-" + ("x" * 120)
    state = SimpleNamespace(
        interrupts=[
            SimpleNamespace(
                id=long_interrupt_id,
                value={
                    "action_requests": [
                        {"name": "execute_in_skill", "args": {"command": "make-docx"}}
                    ],
                    "review_configs": [
                        {
                            "action_name": "execute_in_skill",
                            "allowed_decisions": ["approve", "reject"],
                        }
                    ],
                },
            )
        ]
    )
    agent = StateBackedProtocolAgent([raw_event], state)
    broker = EventBroker("123e4567-e89b-12d3-a456-426614174000")
    persisted: list[list[dict[str, Any]]] = []
    trace_sink: list[dict[str, Any]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-state-hitl"}},
            broker=broker,
            persist_callback=persist,
            run_id="123e4567-e89b-12d3-a456-426614174000",
            trace_sink=trace_sink,
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    input_requested = [payload for payload in payloads if payload["method"] == "input.requested"]
    assert len(input_requested) == 1
    event_id = input_requested[0]["event_id"]
    assert event_id == "123e4567-e89b-12d3-a456-426614174000:input:00000002:0"
    assert len(event_id) <= 80
    assert input_requested[0]["params"]["data"]["interrupt_id"] == long_interrupt_id

    assert persisted[0][-2]["method"] == "input.requested"
    assert persisted[0][-2]["upstream_event_id"] == event_id
    assert persisted[0][-1]["method"] == "lifecycle"
    assert persisted[0][-1]["data"] == {"event": "interrupted"}
    assert trace_sink[-2]["method"] == "input.requested"
    assert trace_sink[-1]["data"] == {"event": "interrupted"}

    replayed = [event async for event in broker.subscribe()]
    assert replayed[-2]["id"] == event_id
    assert replayed[-2]["data"]["method"] == "input.requested"
    assert replayed[-1]["data"]["method"] == "lifecycle"
    assert broker.last_event_id == replayed[-1]["id"]


@pytest.mark.asyncio
async def test_langgraph_streaming_replaces_empty_input_requested_with_state_payload() -> None:
    raw_events = [
        {
            "type": "event",
            "method": "messages",
            "params": {"namespace": [], "data": {"chunk": "waiting"}},
            "seq": 1,
            "event_id": "upstream-waiting",
        },
        {
            "type": "event",
            "method": "input.requested",
            "params": {"namespace": [], "data": {}},
            "seq": 2,
            "event_id": "empty-input-requested",
        },
    ]
    state = SimpleNamespace(
        interrupts=[
            SimpleNamespace(
                id="intr-ask-user",
                value={
                    "action_requests": [
                        {
                            "name": "ask_user",
                            "args": {
                                "mode": "option_list",
                                "title": "水果选择",
                                "options": ["苹果", "梨", "葡萄"],
                                "minSelections": 1,
                                "maxSelections": 1,
                            },
                        }
                    ],
                    "review_configs": [
                        {"action_name": "ask_user", "allowed_decisions": ["respond"]}
                    ],
                },
            )
        ]
    )
    persisted: list[list[dict[str, Any]]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            StateBackedProtocolAgent(raw_events, state),
            {"messages": []},
            {"configurable": {"thread_id": "thread-empty-input"}},
            persist_callback=persist,
            run_id="run-empty-input",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    input_requested = [payload for payload in payloads if payload["method"] == "input.requested"]
    assert len(input_requested) == 1
    assert input_requested[0]["event_id"] != "empty-input-requested"
    data = input_requested[0]["params"]["data"]
    assert data["interrupt_id"] == "intr-ask-user"
    assert data["payload"]["action_requests"][0]["name"] == "ask_user"
    assert data["payload"]["action_requests"][0]["args"]["options"] == ["苹果", "梨", "葡萄"]
    assert payloads[-1]["params"]["data"] == {"event": "interrupted"}

    persisted_events = [event for batch in persisted for event in batch]
    persisted_input = [event for event in persisted_events if event["method"] == "input.requested"]
    assert len(persisted_input) == 1
    assert persisted_input[0]["upstream_event_id"] != "empty-input-requested"
    assert persisted_input[0]["data"]["interrupt_id"] == "intr-ask-user"


@pytest.mark.asyncio
async def test_langgraph_streaming_redacts_synthesized_tool_args_before_persist() -> None:
    raw_event = {
        "type": "event",
        "method": "values",
        "params": {
            "namespace": [],
            "data": {
                "messages": [
                    {
                        "type": "ai",
                        "tool_calls": [
                            {
                                "id": "call-secret",
                                "name": "danger_tool",
                                "args": {"api_key": "SECRET_VALUE", "query": "safe"},
                            }
                        ],
                    }
                ]
            },
        },
        "seq": 1,
        "event_id": "values-with-secret",
    }
    persisted: list[list[dict[str, Any]]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            ProtocolAgent([raw_event]),
            {"messages": []},
            {"configurable": {"thread_id": "thread-secret"}},
            persist_callback=persist,
            run_id="run-secret",
        )
    ]

    assert chunks
    payloads = [sse_payload(chunk) for chunk in chunks]
    wire_tool_event = next(payload for payload in payloads if payload.get("method") == "tools")
    assert wire_tool_event["params"]["data"]["args"] == {"api_key": "<redacted>", "query": "safe"}
    assert "SECRET_VALUE" not in repr(payloads)
    stored = [event for batch in persisted for event in batch]
    tool_event = next(event for event in stored if event.get("method") == "tools")
    assert tool_event["data"]["args"] == {"api_key": "<redacted>", "query": "safe"}
    assert "SECRET_VALUE" not in repr(stored)


@pytest.mark.asyncio
async def test_langgraph_streaming_flushes_protocol_events_before_finalization() -> None:
    raw_events = [
        {
            "type": "event",
            "method": "custom",
            "params": {"namespace": [], "data": {"name": "progress", "payload": {"index": index}}},
            "seq": index,
            "event_id": f"progress-{index}",
        }
        for index in range(1, 40)
    ]
    persisted_batches: list[list[dict[str, Any]]] = []

    async def persist(events: list[dict[str, Any]]) -> None:
        persisted_batches.append(events)

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            ProtocolAgent(raw_events),
            {"messages": []},
            {"configurable": {"thread_id": "thread-flush"}},
            persist_callback=persist,
            run_id="run-flush",
        )
    ]

    assert chunks
    assert len(persisted_batches) >= 2
    assert len(persisted_batches[0]) >= 32
    assert sum(len(batch) for batch in persisted_batches) == len(chunks)


@pytest.mark.asyncio
async def test_langgraph_streaming_falls_back_to_stream_modes() -> None:
    agent = FallbackAgent([("values", {"messages": [], "todos": []})])

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-2"}},
            run_id="run-2",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert [payload["method"] for payload in payloads] == ["lifecycle", "values", "lifecycle"]
    payload = payloads[1]
    assert payload["method"] == "values"
    assert payload["params"]["data"] == {"messages": [], "todos": []}


@pytest.mark.asyncio
async def test_langgraph_streaming_does_not_fallback_after_v3_events_started() -> None:
    agent = MidStreamAttributeErrorAgent()
    errors: list[StreamErrorRecord] = []

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            agent,
            {"messages": []},
            {"configurable": {"thread_id": "thread-midstream"}},
            error_sink=errors,
            run_id="run-midstream",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert [payload["method"] for payload in payloads] == [
        "lifecycle",
        "messages",
        "lifecycle",
        "error",
    ]
    assert payloads[1]["params"]["data"] == {"chunk": "started"}
    assert payloads[2]["params"]["data"]["event"] == "failed"
    assert agent.fallback_calls == 0
    assert errors[0].message == "adapter bug after stream opened"


@pytest.mark.asyncio
async def test_langgraph_streaming_reports_stream_errors() -> None:
    errors: list[StreamErrorRecord] = []

    chunks = [
        chunk
        async for chunk in stream_agent_response_langgraph(
            ErrorAgent(),
            None,
            {"configurable": {"thread_id": "thread-3"}},
            error_sink=errors,
            run_id="run-3",
        )
    ]

    payloads = [sse_payload(chunk) for chunk in chunks]
    assert [payload["method"] for payload in payloads] == ["lifecycle", "lifecycle", "error"]
    assert payloads[1]["params"]["data"] == {
        "event": "failed",
        "error": {"message": "stream failed"},
    }
    assert payloads[2]["params"]["data"] == {"message": "stream failed"}
    assert errors[0].message == "stream failed"
