from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.schemas.artifact import ArtifactSummary
from app.schemas.conversation_run import ConversationRunResponse


def _utc_iso(dt: datetime) -> str:
    """将 timezone-naive datetime 序列化为 UTC ISO 字符串（Z suffix）。

    后端使用 `datetime.now(UTC).replace(tzinfo=None)` 保存 datetime，
    因此值是 UTC，但 tzinfo 为空。Pydantic 默认序列化发送时不带 'Z'，
    会导致 JS `new Date(s)` 将其解释为本地时间。
    """
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


UtcDatetime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str, when_used="json")]


ConversationSort = Literal["updated", "created"]


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    title: str | None
    is_pinned: bool
    unread_count: int = 0
    last_read_at: UtcDatetime | None = None
    last_unread_at: UtcDatetime | None = None
    last_activity_source: str = "user"
    active_run: ConversationRunResponse | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = {"from_attributes": True}


class ConversationListEnvelope(BaseModel):
    items: list[ConversationResponse]
    next_cursor: str | None = None
    has_more: bool = False


class ConversationAgentBrief(BaseModel):
    id: uuid.UUID
    name: str
    image_url: str | None = None


class ConversationWithAgentResponse(ConversationResponse):
    agent: ConversationAgentBrief


class ConversationWithAgentListEnvelope(BaseModel):
    items: list[ConversationWithAgentResponse]
    next_cursor: str | None = None
    has_more: bool = False


class Decision(BaseModel):
    """针对单个 tool_call 的人工 decision。

    与 LangChain ``HumanInTheLoopMiddleware`` 的 ``HITLResponse.decisions[i]``
    shape 相同（1:1 匹配）。router 校验后通过 ``model_dump(exclude_none=True)``
    序列化为 dict，并以 ``Command(resume={"decisions": [dict, ...]})`` 发送
    （LangChain 中间件接收 ``NotRequired`` TypedDict）。

    - ``approve``：无额外字段。
    - ``edit``：必须提供 ``edited_action={"name": str, "args": dict}``。
    - ``reject``：``message`` 可选（没有时中间件生成默认消息）。
    - ``respond``：``message`` 必填（synthetic ToolMessage content）。
    """

    type: Literal["approve", "edit", "reject", "respond"]
    edited_action: dict[str, Any] | None = None  # type=edit 时必填
    message: str | None = None  # type=respond 时必填，type=reject 时可选

    @model_validator(mode="after")
    def _validate_payload_for_type(self) -> Decision:
        if self.type == "edit" and self.edited_action is None:
            raise ValueError("Decision(type='edit') requires 'edited_action'")
        if self.type == "respond" and self.message is None:
            raise ValueError("Decision(type='respond') requires 'message'")
        return self


class ResumeRequest(BaseModel):
    """HiTL resume 请求。兼容 LangChain ``HITLResponse`` 的标准 wire."""

    decisions: list[Decision]


class MessageAttachmentRef(BaseModel):
    """Frontend → backend reference: link an existing upload row to a message.

    Only the upload id is needed; the row already carries the URL/mime/size
    and is reused when echoed back via ``MessageResponse.attachments``.
    """

    id: uuid.UUID


class MessageAttachmentBrief(BaseModel):
    """Inline attachment metadata exposed alongside ``MessageResponse``.

    The frontend renders thumbnails / download cards from this. Only the
    fields needed for preview are surfaced — full row goes through
    ``/api/uploads/{id}``.
    """

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    url: str

    model_config = {"from_attributes": True}


class FileItem(BaseModel):
    """Unified conversation file-list entry (D12): generated artifact OR sent
    attachment, normalized to one shape.

    ``GET /api/conversations/{id}/files`` merges generated artifacts and sent
    attachments into a single created_at-sorted stream. ``source`` tags the
    origin and ``editable`` is false for attachments (read-only, D5). Both
    surfaces dispatch through the same frontend preview registry via
    ``mime_type`` / ``extension`` / ``preview_url`` (unsupported → download
    fallback).
    """

    source: Literal["generated", "attached"]
    id: str
    name: str
    mime_type: str
    extension: str | None = None
    # artifact_kind for generated files; None for attachments.
    kind: str | None = None
    size_bytes: int | None = None
    preview_url: str
    download_url: str
    # attached → the user message; generated → the assistant_msg_id.
    message_id: str | None = None
    created_at: UtcDatetime
    editable: bool


class MessageCreate(BaseModel):
    content: str
    # Optional list of upload ids that should be attached to this message.
    # The router links them by patching ``MessageAttachment.message_id`` after
    # the LangGraph stream stamps the assistant message.
    attachments: list[MessageAttachmentRef] | None = None


class MessageFeedbackBrief(BaseModel):
    """Current user's feedback on a message (None if unrated)."""

    rating: str  # 'up' | 'down'


class TokenUsageBreakdown(BaseModel):
    """W7 — 按消息拆分 4 类 token（扁平化 LangChain ``usage_metadata``）。

    LangChain 通过 ``input_token_details`` 区分 cache_creation/cache_read
    并传递。由于客户端 hover popover 会直接引用，因此序列化为扁平的 4 个字段 + cost
    形式。若所有字段都为 0，则响应中该位置返回 ``null``，客户端
    直接跳过渲染。
    """

    prompt_tokens: int
    completion_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    estimated_cost: float | None = None
    # streaming timing metric（TTFT / 总生成时间(ms) / 输出 tok/s）。live-only —
    # 不持久化到 checkpointer，因此刷新后为 None. 与 token/cost 一起
    # 走相同 SSE/转换路径（兼容 assistant-ui ``useMessageTiming`` 的概念）。
    ttft_ms: float | None = None
    generation_ms: float | None = None
    tokens_per_second: float | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    created_at: UtcDatetime
    feedback: MessageFeedbackBrief | None = None
    attachments: list[MessageAttachmentBrief] | None = None
    artifacts: list[ArtifactSummary] | None = None
    # W7 — 仅在 assistant 消息中填充。user/tool 消息或 LangChain
    # 未 emit ``usage_metadata`` 的 chunk 为 ``None``。
    usage: TokenUsageBreakdown | None = None
    # M-CHAT1b — parent message id in the branch tree. ``None`` for the root
    # (first message). Frontend uses this to build assistant-ui's
    # ``messageRepository`` so BranchPicker auto-detects siblings.
    parent_id: uuid.UUID | None = None
    # checkpoint id this message was first emitted from. Frontend sends this
    # back via ``/switch-branch`` when the user picks a sibling so the next
    # turn forks from the right point.
    branch_checkpoint_id: str | None = None
    # sibling message ids (1-based BranchPicker counts derive from this list).
    # Empty list when there are no siblings. Active message id is included.
    siblings: list[uuid.UUID] = []
    # Per-sibling checkpoint ids — same order as ``siblings``. Frontend posts
    # the chosen sibling's checkpoint_id to ``/switch-branch`` to flip the
    # active branch. Empty when ``siblings`` is empty.
    sibling_checkpoint_ids: list[str] = []
    # M-CHAT1b HOTFIX2 — explicit (0-based) position of *this* message in the
    # sibling list, so the frontend can render ``<branch_index+1 / branch_total>``
    # without indexOf'ing the active id (which mis-fired when sibling order
    # didn't match the picker's left-right semantics). ``None`` when this
    # message has no siblings.
    branch_index: int | None = None
    branch_total: int | None = None


class MessagesEnvelope(BaseModel):
    """Wrapped message-list response.

    The plain ``list[MessageResponse]`` shape was used pre-M-CHAT1b. We now
    wrap it with branch metadata so the frontend can build a tree view; the
    list field name stays ``messages`` to match assistant-ui's external store
    adapter expectations.
    """

    messages: list[MessageResponse]
    active_run: ConversationRunResponse | None = None
    # 最新 run（不区分状态）。``active_run`` 不报告 terminal run，
    # 因此刷新/refetch 后无法得知最后一个 turn 是否被取消（canceled/canceling）。
    # 消息由 checkpointer 派生，无法匹配 run ↔ message id，
    # 因此前端用该字段 durable 渲染“被遗弃” notice。
    latest_run: ConversationRunResponse | None = None
    active_tip_message_id: uuid.UUID | None = None
    active_checkpoint_id: str | None = None
    # W7-4 — conversation 维度累计 cost（USD）。消息级不追踪 model_id，
    # 因此无法填充 ``MessageResponse.usage.estimated_cost``；
    # 但 ``token_usages`` 表会按 turn 累积 cost，因此汇总后发到 envelope 中。
    # 这样客户端 Composer token bar 在刷新后仍可显示 cost。
    total_estimated_cost: float = 0.0


class EditMessageRequest(BaseModel):
    """Edit a previous user message and re-run from there.

    ``message_id`` identifies the user message being replaced. Backend rewinds
    to the checkpoint just before it and forks a new branch with the edited
    content.
    """

    message_id: uuid.UUID
    new_content: str


class RegenerateMessageRequest(BaseModel):
    """Regenerate an assistant message in place.

    If ``message_id`` is omitted the backend regenerates the latest assistant
    turn. Otherwise the named assistant message is replaced (its parent user
    message is replayed).
    """

    message_id: uuid.UUID | None = None


class SwitchBranchRequest(BaseModel):
    """Flip the active branch by checkpoint id.

    The backend can't truly "switch heads" in LangGraph (re-invocation is the
    only way to advance the timeline) so this endpoint just records the
    user's choice; subsequent edits will fork from this checkpoint.
    """

    checkpoint_id: str


class TraceEvent(BaseModel):
    """Single persisted event captured during one assistant turn.

    Legacy rows store ``{"id", "event", "data"}``; LangGraph v3 rows store
    protocol events such as ``{"id", "method", "namespace", "data", "seq"}``.
    Public share and trace readers must be dual-read while both shapes exist.
    """

    id: str | None = None
    event: str | None = None
    method: str | None = None
    data: Any | None = None
    namespace: list[str] | None = None
    params: dict[str, Any] | None = None
    seq: int | None = None
    event_id: str | None = None
    upstream_event_id: str | None = None
    run_id: str | None = None
    thread_id: str | None = None
    timestamp: str | None = None
    checkpoint_id: str | None = None
    checkpoint_ns: str | None = None

    model_config = ConfigDict(extra="allow")


class TurnTraceResponse(BaseModel):
    """One assistant turn's trace — events array + bookkeeping.

    Used by W6 (shared page chip rendering) and the future W3-out resume
    endpoint to read the full event sequence.

    ``linked_message_ids``：本 turn 暴露的 assistant 消息的 parsed UUID
    （与 ``MessageResponse.id`` 格式相同）。若为空数组/None，frontend
    fallback 到 chronological turn 顺序。
    """

    assistant_msg_id: str
    events: list[TraceEvent]
    last_event_id: str | None
    linked_message_ids: list[str] | None = None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None

    model_config = {"from_attributes": True}


class DebugTraceSpan(BaseModel):
    id: str
    parent_id: str | None = None
    name: str
    kind: str
    status: str
    started_at: UtcDatetime | None = None
    ended_at: UtcDatetime | None = None
    duration_ms: int | None = None
    input: Any | None = None
    output: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DebugTraceSummary(BaseModel):
    trace_id: str
    provider: str
    name: str
    status: str
    source: str | None = None
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    duration_ms: int | None = None
    total_tokens: int | None = None
    moldy_run_id: str
    langfuse_url: str | None = None
    fallback: bool = False
    fallback_reason: str | None = None


class DebugTraceListResponse(BaseModel):
    conversation_id: uuid.UUID
    langfuse_enabled: bool
    traces: list[DebugTraceSummary]
    fallback_reason: str | None = None


class DebugTraceDetailResponse(BaseModel):
    conversation_id: uuid.UUID
    trace: DebugTraceSummary
    spans: list[DebugTraceSpan]
    raw: list[dict[str, Any]] | dict[str, Any] | None = None
    fallback_reason: str | None = None
