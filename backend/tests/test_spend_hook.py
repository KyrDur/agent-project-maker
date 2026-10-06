"""SpendHook 回归测试 — durable chat run lifecycle P5.2。

cancel 的 run usage 处理契约：
- cancel 前已 emit 的 usage 会进入 spend 队列并计入成本统计。
- usage 报告前就取消的 run 不会让 hook crash，而是静默 skip。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.hooks.base import HookContext, HookKind, HookResult
from app.hooks.builtin.spend_hook import SpendHook
from app.services.spend_writer import SpendEntry, spend_queue


def _ctx(kind: HookKind = "agent_invoke") -> HookContext:
    return HookContext(
        request_id="req-spend-1",
        kind=kind,
        user_id=uuid.uuid4(),
        started_at=datetime.now(UTC),
        agent_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_spend_hook_skips_canceled_run_without_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """usage 报告前取消的 run — 不 crash，也不写入空 row。"""
    added: list[SpendEntry] = []
    monkeypatch.setattr(spend_queue, "add", added.append)

    await SpendHook().async_post_call_hook(_ctx(), HookResult(duration_ms=10))

    assert added == []


@pytest.mark.asyncio
async def test_spend_hook_enqueues_usage_emitted_before_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cancel 前一刻已 emit 的 usage 会原样进入成本统计队列。"""
    added: list[SpendEntry] = []
    monkeypatch.setattr(spend_queue, "add", added.append)

    await SpendHook().async_post_call_hook(
        _ctx(),
        HookResult(duration_ms=10, tokens_in=120, tokens_out=45, cost_usd=0.0021),
    )

    assert len(added) == 1
    entry = added[0]
    assert entry.tokens_in == 120
    assert entry.tokens_out == 45
    assert float(entry.cost_usd) == pytest.approx(0.0021)


@pytest.mark.asyncio
async def test_spend_hook_ignores_non_agent_invoke_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[SpendEntry] = []
    monkeypatch.setattr(spend_queue, "add", added.append)

    await SpendHook().async_post_call_hook(
        _ctx(kind="tool_call"),
        HookResult(duration_ms=10, tokens_in=10, tokens_out=10, cost_usd=0.01),
    )

    assert added == []
