"""memory 系列 custom 事件的持久化 redaction 合约（包含 W2-3 recalled 事件）。

持久化/共享表面（redact_memory=True 默认值）不得保留记忆内容，
owner live wire（redact_memory=False）则原样传递内容。
"""

from __future__ import annotations

from app.agent_runtime.protocol_redaction import REDACTED_MEMORY_FIELD, redact_protocol_data


def _recalled_event() -> dict:
    return {
        "name": "moldy.memory_recalled",
        "payload": {
            "memories": [
                {"id": "m1", "scope": "user", "content": "偏好韩语"},
                {"id": "m2", "scope": "agent", "content": "整理成表格"},
            ]
        },
    }


def test_persistence_redacts_memory_recalled_content() -> None:
    redacted = redact_protocol_data("custom", _recalled_event())

    briefs = redacted["payload"]["memories"]
    assert [brief["content"] for brief in briefs] == [
        REDACTED_MEMORY_FIELD,
        REDACTED_MEMORY_FIELD,
    ]
    # 保留 id/scope — frontend reload 时通过 memory API 重新查询恢复内容。
    assert [brief["id"] for brief in briefs] == ["m1", "m2"]
    assert [brief["scope"] for brief in briefs] == ["user", "agent"]


def test_live_wire_keeps_memory_recalled_content() -> None:
    passed = redact_protocol_data("custom", _recalled_event(), redact_memory=False)
    assert passed["payload"]["memories"][0]["content"] == "偏好韩语"


def test_memory_proposed_custom_event_still_redacted() -> None:
    event = {
        "name": "memory_proposed",
        "payload": {"id": "p1", "scope": "user", "content": "秘密偏好", "reason": "原因"},
    }
    redacted = redact_protocol_data("custom", event)
    assert redacted["payload"]["content"] == REDACTED_MEMORY_FIELD
    assert redacted["payload"]["reason"] == REDACTED_MEMORY_FIELD


def test_non_memory_custom_event_untouched() -> None:
    event = {"name": "moldy.subagent_names", "payload": {"names": {"agent_1": "研究员"}}}
    assert redact_protocol_data("custom", event) == event
