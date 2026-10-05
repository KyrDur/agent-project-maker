"""Temporal context helpers for date-sensitive agent answers."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent_runtime.temporal import (
    build_temporal_context_prompt,
    resolve_relative_date_expression,
)
from app.agent_runtime.tool_factory import create_builtin_tool
from tests.tool_helpers import tool_coroutine

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_temporal_context_prompt_includes_today_and_this_weekend() -> None:
    now = datetime(2026, 5, 29, 11, 33, tzinfo=SHANGHAI)

    prompt = build_temporal_context_prompt(now=now)

    assert "当前基准日期" in prompt
    assert "2026-05-29" in prompt
    assert "星期五" in prompt
    assert "Asia/Shanghai" in prompt
    assert "11点时段" in prompt
    assert "11:33" not in prompt
    assert "11:33:00" not in prompt
    assert "本周末：2026-05-30(星期六) ~ 2026-05-31(星期日)" in prompt
    assert "相对日期" in prompt
    assert "精确到分钟" in prompt


def test_resolve_relative_date_expression_this_weekend() -> None:
    now = datetime(2026, 5, 29, 11, 33, tzinfo=SHANGHAI)

    result = resolve_relative_date_expression("本周末", now=now)

    assert result["success"] is True
    assert result["label"] == "本周末"
    assert result["start_date"] == "2026-05-30"
    assert result["end_date"] == "2026-05-31"
    assert result["weekday_start"] == "星期六"
    assert result["weekday_end"] == "星期日"


def test_resolve_relative_date_expression_next_wednesday() -> None:
    now = datetime(2026, 5, 29, 11, 33, tzinfo=SHANGHAI)

    result = resolve_relative_date_expression("下周三的约会", now=now)

    assert result["success"] is True
    assert result["label"] == "下周 星期三"
    assert result["start_date"] == "2026-06-03"
    assert result["end_date"] == "2026-06-03"
    assert result["weekday_start"] == "星期三"


def test_resolve_relative_date_expression_recent_news_window() -> None:
    now = datetime(2026, 5, 29, 11, 33, tzinfo=SHANGHAI)

    result = resolve_relative_date_expression("最近的科技新闻", now=now)

    assert result["success"] is True
    assert result["label"] == "过去 7 天"
    assert result["start_date"] == "2026-05-23"
    assert result["end_date"] == "2026-05-29"
    assert result["timezone"] == "Asia/Shanghai"


def test_resolve_relative_date_expression_recent_schedule_does_not_match_sunday() -> None:
    now = datetime(2026, 5, 29, 11, 33, tzinfo=SHANGHAI)

    result = resolve_relative_date_expression("最近的日程", now=now)

    assert result["success"] is True
    assert result["label"] == "过去 7 天"
    assert result["start_date"] == "2026-05-23"
    assert result["end_date"] == "2026-05-29"


@pytest.mark.asyncio
async def test_resolve_relative_date_builtin_tool_returns_json() -> None:
    tool = create_builtin_tool("builtin:resolve_relative_date")

    assert tool is not None
    result = await tool_coroutine(tool)(
        expression="下周三",
        reference_date="2026-05-29T11:33:00+08:00",
    )

    data = json.loads(result)
    assert data["success"] is True
    assert data["start_date"] == "2026-06-03"
    assert data["weekday_start"] == "星期三"


@pytest.mark.parametrize(
    ("expression", "expected_start", "expected_end"),
    [
        ("下周三", "2026-06-03", "2026-06-03"),
        ("下星期三", "2026-06-03", "2026-06-03"),
        ("下周末", "2026-06-06", "2026-06-07"),
        ("上周末", "2026-05-23", "2026-05-24"),
        ("星期天", "2026-05-31", "2026-05-31"),
        ("本周三", "2026-05-27", "2026-05-27"),
    ],
)
def test_chinese_week_expressions_preserve_calendar_range(
    expression: str, expected_start: str, expected_end: str
) -> None:
    now = datetime(2026, 5, 29, 11, 33, tzinfo=SHANGHAI)
    result = resolve_relative_date_expression(expression, now=now)
    assert result["success"] is True
    assert result["start_date"] == expected_start
    assert result["end_date"] == expected_end
