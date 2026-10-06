"""compute_usage_timing 单元测试（TTFT / 总时间 / tok-s）。

``compute_usage_timing`` 内部用 ``time.monotonic()`` 获取 now，
因此输入时间必须以实际 monotonic 基准的相对值锚定，generation/tok-s 才会
得到现实值（若使用固定常量，与 now 相差数千秒，tok-s 会被四舍五入为 0）。
"""

from __future__ import annotations

import time

import pytest

from app.agent_runtime.usage_timing import compute_usage_timing


def test_includes_ttft_and_tokens_per_second_when_available() -> None:
    now = time.monotonic()
    # 开始于1.0s前，首 token 于0.5s前 → TTFT 500ms，生成 ~1s，tok/s ~ 50/0.5 = 100。
    timing = compute_usage_timing(
        started_at=now - 1.0, first_token_at=now - 0.5, completion_tokens=50
    )
    # TTFT = (first - started) 与 now 无关，必须准确。
    assert timing["ttft_ms"] == pytest.approx(500.0, abs=1.0)
    assert timing["generation_ms"] == pytest.approx(1000.0, abs=50.0)
    assert timing["tokens_per_second"] == pytest.approx(100.0, rel=0.2)


def test_omits_ttft_when_no_first_token() -> None:
    now = time.monotonic()
    timing = compute_usage_timing(started_at=now - 0.5, first_token_at=None, completion_tokens=0)
    assert "ttft_ms" not in timing
    assert timing["generation_ms"] > 0  # 总时间始终测量


def test_omits_tokens_per_second_when_no_completion() -> None:
    now = time.monotonic()
    timing = compute_usage_timing(
        started_at=now - 1.0, first_token_at=now - 0.9, completion_tokens=0
    )
    assert "tokens_per_second" not in timing
    assert timing["ttft_ms"] == pytest.approx(100.0, abs=1.0)
