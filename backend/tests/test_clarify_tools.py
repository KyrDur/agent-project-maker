"""Tests for app.agent_runtime.assistant.tools.clarify_tools — ask_clarifying_question."""

from __future__ import annotations

import json

import pytest

from app.agent_runtime.assistant.tools.clarify_tools import build_clarify_tools


@pytest.mark.asyncio
async def test_ask_clarifying_question():
    """ask_clarifying_question returns JSON with question + 4 options."""
    tools = build_clarify_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "ask_clarifying_question"

    result = await tool.ainvoke(
        {
            "question": "你想要哪种类型的搜索？",
            "option_1": "默认标题",
            "option_2": "新闻搜索",
            "option_3": "图片搜索",
        }
    )

    data = json.loads(result)
    assert data["type"] == "clarifying_question"
    assert data["question"] == "你想要哪种类型的搜索？"
    assert len(data["options"]) == 4
    assert "默认标题" in data["options"]
    assert "新闻搜索" in data["options"]
    assert "图片搜索" in data["options"]
    assert "自行输入" in data["options"]
