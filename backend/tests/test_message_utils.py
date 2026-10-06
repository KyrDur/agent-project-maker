from __future__ import annotations

import uuid
from typing import cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.ai import UsageMetadata

from app.agent_runtime.message_utils import (
    content_to_text,
    convert_to_langchain_messages,
    extract_json_from_markdown,
    langchain_messages_to_response,
    strip_json_blocks,
)
from app.agent_runtime.offload_storage_types import OffloadKind, logical_offload_id


class TestConvertToLangchainMessages:
    def test_system_message(self):
        msgs = convert_to_langchain_messages([{"role": "system", "content": "You are helpful."}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], SystemMessage)
        assert msgs[0].content == "You are helpful."

    def test_user_message(self):
        msgs = convert_to_langchain_messages([{"role": "user", "content": "Hello"}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        assert msgs[0].content == "Hello"

    def test_assistant_message(self):
        msgs = convert_to_langchain_messages([{"role": "assistant", "content": "Hi there"}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], AIMessage)
        assert msgs[0].content == "Hi there"

    def test_mixed_roles(self):
        msgs = convert_to_langchain_messages(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "usr"},
                {"role": "assistant", "content": "asst"},
            ]
        )
        assert len(msgs) == 3
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert isinstance(msgs[2], AIMessage)

    def test_unknown_role_skipped(self):
        msgs = convert_to_langchain_messages(
            [
                {"role": "unknown", "content": "???"},
                {"role": "user", "content": "Hello"},
            ]
        )
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)

    def test_empty_list(self):
        msgs = convert_to_langchain_messages([])
        assert msgs == []


class TestExtractJsonFromMarkdown:
    def test_single_json_block(self):
        content = 'Here is data:\n```json\n{"name": "Agent", "model": "gpt-4o"}\n```'
        result = extract_json_from_markdown(content)
        assert result == {"name": "Agent", "model": "gpt-4o"}

    def test_multiple_json_blocks_merged(self):
        content = '```json\n{"name": "Agent"}\n```\nSome text\n```json\n{"model": "gpt-4o"}\n```'
        result = extract_json_from_markdown(content)
        assert result == {"name": "Agent", "model": "gpt-4o"}

    def test_invalid_json_skipped(self):
        content = '```json\n{invalid json}\n```\n```json\n{"valid": true}\n```'
        result = extract_json_from_markdown(content)
        assert result == {"valid": True}

    def test_all_invalid_json_returns_none(self):
        content = "```json\n{broken\n```"
        result = extract_json_from_markdown(content)
        assert result is None

    def test_no_json_blocks_returns_none(self):
        content = "Just some plain text without any code blocks."
        result = extract_json_from_markdown(content)
        assert result is None

    def test_empty_string(self):
        result = extract_json_from_markdown("")
        assert result is None


class TestLangchainMessagesToResponse:
    """验证 Anthropic 返回 list-of-blocks content 时，响应转换是否只提取 text。

    防回归：此前实现使用 `str(list)` 序列化，导致 raw dict repr 暴露给用户。
    """

    def test_string_content_passthrough(self):
        conv_id = uuid.uuid4()
        result = langchain_messages_to_response([AIMessage(content="你好")], conv_id)
        assert len(result) == 1
        assert result[0].role == "assistant"
        assert result[0].content == "你好"

    def test_anthropic_list_content_text_blocks_only(self):
        """仅对 text 块 concat。忽略 tool_use 块（通过 tool_calls 单独暴露）。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(
            content=[
                {"type": "text", "text": "我来搜索一下员工信息！", "index": 0},
                {
                    "type": "tool_use",
                    "id": "toolu_01ABC",
                    "name": "search_employees",
                    "input": {"query": "李尚允"},
                    "index": 1,
                },
            ]
        )
        result = langchain_messages_to_response([msg], conv_id)
        assert result[0].content == "我来搜索一下员工信息！"

    def test_anthropic_multi_text_blocks_concatenated(self):
        conv_id = uuid.uuid4()
        msg = AIMessage(
            content=[
                {"type": "text", "text": "李尚允的团队信息：\n"},
                {"type": "text", "text": "- 所属：产品技术团队"},
            ]
        )
        result = langchain_messages_to_response([msg], conv_id)
        assert result[0].content == "李尚允的团队信息：\n- 所属：产品技术团队"

    def test_private_reasoning_blocks_are_not_displayed(self):
        private = "PRIVATE_CHAIN_OF_THOUGHT_DO_NOT_LEAK"
        content = [
            {"type": "reasoning", "text": private, "summary": private},
            {"type": "thinking", "thinking": private},
            {"type": "reasoning_content", "reasoning": private},
            {"type": "text", "text": "展示给用户的回答"},
        ]

        assert content_to_text(content) == "展示给用户的回答"
        assert private not in content_to_text(content)
        assert content_to_text({"type": "reasoning", "text": private}) == ""

    def test_empty_list_content(self):
        conv_id = uuid.uuid4()
        msg = AIMessage(content=[])
        result = langchain_messages_to_response([msg], conv_id)
        assert result[0].content == ""

    def test_list_content_with_only_tool_use(self):
        """仅含 tool_use 的响应（无辅助文本）为空字符串。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_01XYZ",
                    "name": "search_employees",
                    "input": {},
                }
            ]
        )
        result = langchain_messages_to_response([msg], conv_id)
        assert result[0].content == ""

    def test_text_block_without_text_field_skipped(self):
        """没有 text 键或其值不是 string 时跳过。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(
            content=[
                {"type": "text"},  # no text
                {"type": "text", "text": None},  # null
                {"type": "text", "text": "健康"},
            ]
        )
        result = langchain_messages_to_response([msg], conv_id)
        assert result[0].content == "健康"

    def test_tool_message_string_content(self):
        conv_id = uuid.uuid4()
        msg = ToolMessage(content="结果", tool_call_id="toolu_1")
        result = langchain_messages_to_response([msg], conv_id)
        assert result[0].role == "tool"
        assert result[0].content == "结果"
        assert result[0].tool_call_id == "toolu_1"

    def test_tool_message_projects_exact_large_result_pointer_without_mutating_source(self):
        conv_id = uuid.uuid4()
        tool_call_id = "call_a_b_c"
        path = "/large_tool_results/call_a_b_c"
        content = (
            f"Tool result too large, the result of this tool call {tool_call_id} was saved in the "
            f"filesystem at this path: {path}\n\n"
        )
        msg = ToolMessage(content=content, tool_call_id=tool_call_id)

        [response] = langchain_messages_to_response([msg], conv_id)

        assert response.content == content.replace(
            path, logical_offload_id(OffloadKind.SPILL, path)
        )
        assert path not in response.content
        assert msg.content == content

    def test_human_summary_projects_history_path_and_unknown_marker_fails_closed(self):
        conv_id = uuid.uuid4()
        history_path = "/conversation_history/session_0123456789abcdef0123456789abcdef.md"
        raw_summary = f"Summary persisted at {history_path}"
        unknown_internal = "/private/.moldy-internal/offload/history/secret"
        summary = HumanMessage(content=raw_summary)
        unknown = HumanMessage(content=f"Do not expose {unknown_internal}")

        responses = langchain_messages_to_response([summary, unknown], conv_id)

        assert responses[0].content == raw_summary.replace(
            history_path, logical_offload_id(OffloadKind.HISTORY, history_path)
        )
        assert history_path not in responses[0].content
        assert responses[1].content == "internal_reference_redacted"
        assert summary.content == raw_summary
        assert unknown.content == f"Do not expose {unknown_internal}"

    def test_message_response_projects_tool_call_payload_without_mutating_source(self):
        conv_id = uuid.uuid4()
        path = "/large_tool_results/call_a_b_c"
        msg = AIMessage(
            content="tool request",
            tool_calls=[
                {
                    "name": "read_large_result",
                    "args": {"offload_path": path, "spill_id": "spoofed"},
                    "id": "call_a_b_c",
                    "type": "tool_call",
                }
            ],
        )

        [response] = langchain_messages_to_response([msg], conv_id)

        assert response.tool_calls == [
            {
                "name": "read_large_result",
                "args": {"spill_id": logical_offload_id(OffloadKind.SPILL, path)},
                "id": "call_a_b_c",
                "type": "tool_call",
            }
        ]
        assert msg.tool_calls[0]["args"]["offload_path"] == path


class TestUsageExtraction:
    """W7 — AIMessage.usage_metadata 会平铺到 MessageResponse.usage。"""

    def test_ai_message_with_usage_metadata(self):
        conv_id = uuid.uuid4()
        msg = AIMessage(content="hi")
        msg.usage_metadata = cast(
            UsageMetadata,
            {
                "input_tokens": 1200,
                "output_tokens": 80,
                "input_token_details": {"cache_creation": 800, "cache_read": 300},
            },
        )
        [resp] = langchain_messages_to_response([msg], conv_id)
        assert resp.usage is not None
        assert resp.usage.prompt_tokens == 1200
        assert resp.usage.completion_tokens == 80
        assert resp.usage.cache_creation_tokens == 800
        assert resp.usage.cache_read_tokens == 300

    def test_ai_message_without_cache_details(self):
        """若无 ``input_token_details``，cache_* 填充为 0。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(content="hi")
        msg.usage_metadata = cast(UsageMetadata, {"input_tokens": 100, "output_tokens": 50})
        [resp] = langchain_messages_to_response([msg], conv_id)
        assert resp.usage is not None
        assert resp.usage.prompt_tokens == 100
        assert resp.usage.completion_tokens == 50
        assert resp.usage.cache_creation_tokens == 0
        assert resp.usage.cache_read_tokens == 0

    def test_user_message_has_no_usage(self):
        conv_id = uuid.uuid4()
        msg = HumanMessage(content="hi")
        [resp] = langchain_messages_to_response([msg], conv_id)
        assert resp.usage is None

    def test_ai_message_with_zero_tokens_has_no_usage(self):
        """所有字段均为 0 时返回 ``None`` — 客户端不会渲染 hover 弹出框本身。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(content="")
        msg.usage_metadata = cast(UsageMetadata, {"input_tokens": 0, "output_tokens": 0})
        [resp] = langchain_messages_to_response([msg], conv_id)
        assert resp.usage is None

    def test_estimated_cost_calculated_from_model_pricing(self):
        """W7-4 — 若提供 agent.model 单价，则计算 cost 并写入响应。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(content="hi")
        msg.usage_metadata = cast(UsageMetadata, {"input_tokens": 1000, "output_tokens": 500})
        [resp] = langchain_messages_to_response(
            [msg],
            conv_id,
            cost_per_input_token=3e-6,  # $3 / 1M tokens
            cost_per_output_token=15e-6,  # $15 / 1M tokens
        )
        assert resp.usage is not None
        # 1000 * 3e-6 + 500 * 15e-6 = 0.003 + 0.0075 = 0.0105
        assert resp.usage.estimated_cost == pytest.approx(0.0105, rel=1e-9)

    def test_estimated_cost_none_when_no_pricing(self):
        """单价为 None 时不填充 cost（envelope 汇总为 0）。"""
        conv_id = uuid.uuid4()
        msg = AIMessage(content="hi")
        msg.usage_metadata = cast(UsageMetadata, {"input_tokens": 100, "output_tokens": 50})
        [resp] = langchain_messages_to_response([msg], conv_id)
        assert resp.usage is not None
        assert resp.usage.estimated_cost is None


class TestStripJsonBlocks:
    def test_removes_json_blocks(self):
        content = 'Before\n```json\n{"key": "value"}\n```\nAfter'
        result = strip_json_blocks(content)
        assert result == "Before\n\nAfter"

    def test_removes_multiple_blocks(self):
        content = 'Start\n```json\n{"a": 1}\n```\nMiddle\n```json\n{"b": 2}\n```\nEnd'
        result = strip_json_blocks(content)
        assert "json" not in result
        assert "Start" in result
        assert "Middle" in result
        assert "End" in result

    def test_no_blocks_returns_original(self):
        content = "No code blocks here."
        result = strip_json_blocks(content)
        assert result == "No code blocks here."
