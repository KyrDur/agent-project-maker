"""Centralized SSE event name constants.

W3-out 轨道中发现 — ``streaming.py`` emit 的事件名称与
``routers/conversations.py`` 的验证逻辑（``_is_pending_interrupt`` /
``_replay_resume_generator``）分别定义成了不同的魔法字符串，
如果一侧 rename，可能发生 silent breakage（例如 ``"interrupt"``
→ ``"hitl_pause"`` 变更时，resume endpoint 的 409 阻断会 silently no-op）。

本模块是单一 source of truth — emit 侧与验证侧都 import 它。
新增 SSE 事件时，在这里注册常量。
"""

from __future__ import annotations

from typing import Final

# Producer side — ``streaming.py`` 的 emit 闭包发布的标准事件。
MESSAGE_START: Final = "message_start"
CONTENT_DELTA: Final = "content_delta"
MESSAGE_END: Final = "message_end"
ERROR: Final = "error"
INTERRUPT: Final = "interrupt"
# wire format 为 ``tool_call_start`` / ``tool_call_result``（与 frontend
# ``SSEEventType`` 一致）。最初编写时误设为 ``tool_call`` / ``tool_result``，
# 因而成为 dead constant — 在轨道结束时的 cross-file audit 中发现。
TOOL_CALL_START: Final = "tool_call_start"
TOOL_CALL_RESULT: Final = "tool_call_result"
FILE_EVENT: Final = "file_event"
# Auto-compaction side-channel (dev-plan-context-compaction-marker.md). Emitted as
# a ``custom`` protocol event (``name="moldy.compaction"``) carrying ``{state}`` —
# ``running`` while deepagents summarizes older messages, ``done`` once the
# ``_summarization_event`` is committed. The public done payload carries only
# an opaque ``history_id`` plus ``cutoff_index``; internal paths never cross wire.
COMPACTION: Final = "moldy.compaction"
# Generative UI side-channel (chat-generative-ui-dev-plan §2.1). Emitted as a
# ``custom`` protocol event (``name="moldy.ui_data"``) carrying a typed
# ``{type, props}`` payload the frontend renders via an allowlist registry. Shares
# the ``custom`` channel with FILE_EVENT; consumers disambiguate by custom name.
UI_DATA_EVENT: Final = "moldy.ui_data"
# Subagent display-name side-channel (chat-subagent-streaming-visibility-plan G10).
# Emitted once at stream head as a ``custom`` protocol event
# (``name="moldy.subagent_names"``) carrying ``{names: {runtime_name: display_name}}``.
# The v3 path streams deepagents ``task`` tool calls whose ``subagent_type`` is the
# runtime name (``agent_<8hex>``); the frontend SDK uses that verbatim as the card
# title. Rather than rewrite the checkpoint-backed ``subagent_type`` (which drives
# execution + namespace binding), we ship the runtime_name→display_name map so the
# frontend can substitute a human-readable name at the display layer only. Stable
# event id dedupes on replay/reload (same contract as COMPACTION).
SUBAGENT_NAMES: Final = "moldy.subagent_names"
# Memory recall side-channel (W2-3). Emitted once at stream head as a ``custom``
# protocol event (``name="moldy.memory_recalled"``) carrying
# ``{memories: [{id, scope, content}]}`` — the long-term memory briefs injected
# into this run's system prompt. Stable event id (``<run_id>:memory_recalled``)
# dedupes on replay/reload (same contract as SUBAGENT_NAMES).
MEMORY_RECALLED: Final = "moldy.memory_recalled"
# Skill builder chat rail（技能工作室 phase 1，AD-5）。Two ``custom`` events:
# ``moldy.skill_draft`` — stream-head 1 次，stable id ``<run_id>:skill_draft``,
# 草稿状态摘要（会话 id/模式/slug/文件路径·大小/变更数 — 禁止包含文件内容）。
# ``moldy.skill_validation`` — ``validate_skill``/``finalize_skill`` 工具结果
# projection（memory_event_projection 模式），保持现有 validation_result schema 不变。
SKILL_DRAFT: Final = "moldy.skill_draft"
SKILL_VALIDATION: Final = "moldy.skill_validation"
MEMORY_PROPOSED: Final = "memory_proposed"
MEMORY_SAVED: Final = "memory_saved"
MEMORY_REJECTED: Final = "memory_rejected"
MEMORY_DELETED: Final = "memory_deleted"

# Resume-only — W3-out M3 GET endpoint 在 broker 已失效、只剩 streaming
# row 时发布。client 收到此事件后会停止自动重试。
STALE: Final = "stale"
