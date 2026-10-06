from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import orjson
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from app.agent_runtime import event_names
from app.agent_runtime.event_broker import BrokeredEvent, EventBroker
from app.agent_runtime.memory_event_projection import (
    MEMORY_TOOL_NAMES,
    memory_event_from_tool_result,
)
from app.agent_runtime.message_utils import content_to_text, extract_usage_breakdown
from app.agent_runtime.protocol_egress import project_and_redact_protocol_data
from app.agent_runtime.stream_error_messages import public_stream_error_message
from app.agent_runtime.usage_timing import compute_usage_timing
from app.config import settings
from app.marketplace.redaction import redact_keys

logger = logging.getLogger(__name__)


# W3-out M2 — partial flush thresholds。达到 32 events 或 2 秒时
# 以 fire-and-forget 方式调用 persist_callback。参见 plan 决策 #4。
_FLUSH_BATCH_SIZE = 32
_FLUSH_INTERVAL_SECONDS = 2.0
# Backpressure cap on in-flight partial flushes。即使 DB 变慢，也要防止 task /
# connection 激增。4 = async DB pool（通常 10~20）的保守 1/3，
# 为其他 route 的 DB 工作保留共享 pool 空间。达到上限时，新 chunk
# 原样保留在 flush_buffer 中，并在下一次阈值检查时重新检查 → in-flight
# 清空后恢复 flush。最坏情况下，由 finally 的 final flush 处理剩余内容。
_MAX_INFLIGHT_FLUSHES = 4
# retry_buffer 内存上限（events 数量）。平均 200B × 5000 = ~1MB。
# 即使因 DB 持久化故障导致一个 turn 内所有 partial flush 都失败，也可提供 OOM
# 保护。超出后从 oldest chunk 开始 drop + log（正常 turn 长度假设为 0~数百
# events，达到上限即视为异常信号）。
_MAX_RETRY_BUFFER_EVENTS = 5000


PersistCallback = Callable[[list[dict[str, Any]]], Awaitable[None]]


class ArtifactEventRecorder(Protocol):
    async def prepare(self) -> None: ...

    async def collect_after_tool_result(
        self,
        *,
        tool_name: str,
        tool_call_id: str | None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class StreamErrorRecord:
    """Typed sink record for stream-visible runtime failures."""

    error: Exception
    message: str


def format_sse(event: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    # orjson 比 stdlib json 快 3~5x，且默认禁用 ensure_ascii（直接输出 UTF-8
    # bytes）。SSE 是每个 token chunk 都会调用的 hot path。
    #
    # ``event_id``（可选）：SSE 标准 ``id:`` 字段。使 client 在重试同一 stream
    # 时可以 dedup 重复事件或丢弃 stale 事件。
    payload = orjson.dumps(data).decode()
    if event_id:
        return f"event: {event}\nid: {event_id}\ndata: {payload}\n\n"
    return f"event: {event}\ndata: {payload}\n\n"


def _message_to_trace_input(message: Any) -> dict[str, Any] | Any:
    if isinstance(message, dict):
        return {key: _trace_input_payload(value) for key, value in message.items()}

    msg_type = getattr(message, "type", None)
    content = getattr(message, "content", None)
    if isinstance(msg_type, str) and content is not None:
        payload: dict[str, Any] = {
            "role": "user" if msg_type == "human" else msg_type,
            "content": content_to_text(content),
        }
        name = getattr(message, "name", None)
        if isinstance(name, str) and name:
            payload["name"] = name
        msg_id = getattr(message, "id", None)
        if isinstance(msg_id, str) and msg_id:
            payload["id"] = msg_id
        return payload

    return _trace_input_payload(message)


def _trace_input_payload(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Command):
        return {"resume": _trace_input_payload(value.resume)}
    if isinstance(value, dict):
        return {key: _trace_input_payload(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_message_to_trace_input(item) for item in value]
    return str(value)


def _debug_input_for_message_start(actual_input: Any) -> Any:
    if actual_input is None:
        return None
    return redact_keys(_trace_input_payload(actual_input))


# Middleware-internal schema names（LLMToolSelectorMiddleware 等）— 不向 UI 暴露（X）。
_INTERNAL_TOOL_NAMES: frozenset[str] = frozenset({"ToolSelectionResponse"})
_REDACTED_MEMORY_FIELD = "<redacted>"


def sanitize_tool_call_parameters(tool_name: str, args: Any) -> Any:
    parameters = redact_keys(args)
    if tool_name not in MEMORY_TOOL_NAMES or not isinstance(parameters, dict):
        return parameters
    safe = dict(parameters)
    if "content" in safe:
        safe["content"] = _REDACTED_MEMORY_FIELD
    if safe.get("reason") is not None:
        safe["reason"] = _REDACTED_MEMORY_FIELD
    return safe


def enrich_subagent_tool_call_parameters(
    tool_name: str,
    parameters: Any,
    subagent_display_names: dict[str, str] | None,
) -> Any:
    if tool_name != "task" or not isinstance(parameters, dict):
        return parameters
    runtime_name = parameters.get("subagent_type")
    if not isinstance(runtime_name, str) or not subagent_display_names:
        return parameters
    display_name = subagent_display_names.get(runtime_name)
    if not display_name:
        return parameters
    return {
        **parameters,
        "agent_runtime_name": runtime_name,
        "agent_name": display_name,
    }


def _is_tool_selector_json(text: str) -> bool:
    """Check if text is LLMToolSelectorMiddleware output like {"tools":[...]}.

    ADR-004: PatchToolCallsMiddleware 只实现 before_agent() hook。
    因为不会过滤 stream 事件，所以仍然需要此过滤器。

    Strict: only matches when "tools" is the sole key to avoid
    false positives on legitimate agent JSON output.
    """
    try:
        parsed = json.loads(text)
        return (
            isinstance(parsed, dict)
            and set(parsed.keys()) == {"tools"}
            and isinstance(parsed["tools"], list)
        )
    except (json.JSONDecodeError, ValueError):
        return False


def _interrupt_to_standard_chunk(
    intr_id: str, intr_value: dict[str, Any] | None
) -> dict[str, Any] | None:
    """将 LangGraph interrupt value 规范化为标准 wire chunk。

    - 标准中间件 ``HITLRequest`` (action_requests/review_configs)：原样使用。
    - 自有 ``ask_user.py`` native interrupt (``{"type":"ask_user","question",
      "options"}``)：适配为标准 ``respond`` 单一 action。若标准中间件 wrap
      ask_user 工具，则自然不会到达这里（X） — 作为 fallback 安全网。
    - 其他 dict：skip（返回 None）。
    """
    if intr_value is None:
        return None
    if "action_requests" in intr_value and "review_configs" in intr_value:
        return {
            "interrupt_id": intr_id,
            "action_requests": intr_value["action_requests"],
            "review_configs": intr_value["review_configs"],
        }
    if intr_value.get("type") == "ask_user":
        args = {key: value for key, value in intr_value.items() if key != "type"}
        if "mode" not in args:
            args = {
                "question": args.get("question") or "",
                "options": args.get("options") or [],
            }
        return {
            "interrupt_id": intr_id,
            "action_requests": [
                {
                    "id": intr_id or "ask_user",
                    "name": "ask_user",
                    "args": args,
                    "type": "tool_call",
                }
            ],
            "review_configs": [
                {
                    "action_name": "ask_user",
                    "allowed_decisions": ["respond"],
                }
            ],
        }
    return None


async def stream_agent_response(
    agent: Any,
    input_: list[Any] | Command | dict[str, Any] | None,
    config: dict[str, Any],
    *,
    cost_per_input_token: float | None = None,
    cost_per_output_token: float | None = None,
    usage_sink: dict[str, Any] | None = None,
    trace_sink: list[dict[str, Any]] | None = None,
    msg_id_sink: list[str] | None = None,
    error_sink: list[StreamErrorRecord] | None = None,
    broker: EventBroker | None = None,
    persist_callback: PersistCallback | None = None,
    run_id: str | None = None,
    subagent_display_names: dict[str, str] | None = None,
    artifact_recorder: ArtifactEventRecorder | None = None,
) -> AsyncGenerator[str, None]:
    """Stream agent SSE events.

    ``usage_sink`` (optional) is populated in-place when the stream finishes
    so callers (executor, hook framework) can record the captured token /
    cost numbers without re-parsing SSE. Keys: ``prompt_tokens``,
    ``completion_tokens``, ``estimated_cost``.

    ``trace_sink`` (optional, W5) is appended to with the dict form of each
    SSE event ``{"id", "event", "data"}`` so callers can persist the full
    trace at end-of-turn without re-parsing SSE strings.

    ``broker`` (optional, W3-out M2): live stream 的 dual-write 通道。所有
    emit 都通过 ``broker.publish_nowait`` 传播，使断开的 client 通过 GET resume
    attach 后可立即继续接收 live token。finally 中执行 ``close()``。

    ``persist_callback`` (optional, W3-out M2): partial flush callback。达到 32 events
    或 2 秒时，通过 ``asyncio.create_task`` 以 fire-and-forget 方式调用（emit 的
    latency 0）。caller(router) 绑定使用 fresh DB session 调用 ``append_events`` 的
    callback。

    ``run_id`` (optional, W3-out M2): 作为 assistant_msg_id 使用的外部注入 UUID
    字符串。router 为了与 broker key + X-Run-Id header 保持一致而预先
    生成。None 时像以前一样自行生成（兼容 legacy / 单元测试）。
    """
    msg_id = run_id or str(uuid.uuid4())

    # 序列计数器 — 将 SSE id 字段按 ``{msg_id}-{seq}`` 发出，使同一 stream
    # 内可进行 dedup。seq 通过 closure 注入，仅在 emit helper 内
    # mutate。
    seq = 0
    flush_buffer: list[dict[str, Any]] = []
    last_flush_at = time.monotonic()
    background_persist_tasks: set[asyncio.Task[None]] = set()
    # Failed-chunk retry buffer — partial flush 失败后，在 final flush 中
    # 再尝试一次。作为 safety net，防止 DB 短暂故障导致 chunk silently 丢失。
    # safety net. 如果 final flush 也失败，才会发生永久丢失（log）。
    retry_buffer: list[dict[str, Any]] = []

    async def _safe_persist(chunk: list[dict[str, Any]]) -> None:
        """Background task wrapper — swallow exceptions so a DB hiccup
        doesn't kill the live stream. 失败的 chunk 保存在 retry_buffer 中，
        并在 finally 的 final flush 中再尝试一次。

        如果 retry_buffer 超过上限（``_MAX_RETRY_BUFFER_EVENTS``），
        从 oldest 开始 drop + log（丢失单个 event 的优先级
        低于维持 stream）。"""
        if persist_callback is None:
            return
        try:
            await persist_callback(chunk)
        except Exception:
            logger.exception(
                "partial flush persist_callback failed (run_id=%s) — chunk queued for final retry",
                msg_id,
            )
            retry_buffer.extend(chunk)
            if len(retry_buffer) > _MAX_RETRY_BUFFER_EVENTS:
                overflow = len(retry_buffer) - _MAX_RETRY_BUFFER_EVENTS
                del retry_buffer[:overflow]
                logger.warning(
                    "retry_buffer overflow (run_id=%s) — dropped %d oldest "
                    "events to stay under cap=%d",
                    msg_id,
                    overflow,
                    _MAX_RETRY_BUFFER_EVENTS,
                )

    def emit(event: str, data: dict[str, Any]) -> str:
        nonlocal seq, last_flush_at
        seq += 1
        event_id = f"{msg_id}-{seq}"
        # 单个 dict 实例由 trace_sink/broker/flush_buffer 共享。其结构
        # 与 ``BrokeredEvent`` TypedDict(id/event/data 3 个键)相同，因此 broker 侧
        # 无需额外转换。emit 后不会再有人 mutate，因此可安全共享
        # （review：只 allocate 1 个 dict，内存减半）。由于 pyright invariant
        # 限制，显式 cast BrokeredEvent → dict[str, Any]。
        live_data = project_and_redact_protocol_data(event, data, redact_memory=False)
        shared_data = project_and_redact_protocol_data(event, live_data)
        evt_dict: dict[str, Any] = {"id": event_id, "event": event, "data": shared_data}
        if trace_sink is not None:
            trace_sink.append(evt_dict)
        if broker is not None:
            broker.publish_nowait(cast(BrokeredEvent, evt_dict))
        if persist_callback is not None:
            flush_buffer.append(evt_dict)
            now = time.monotonic()
            # Backpressure：超过 in-flight task 上限时，不 flush 新 chunk，
            # 而是原样保留在 buffer 中。下一次 emit 时再次检查阈值 →
            # in-flight 清空后恢复 flush。最坏情况下，由 finally 的 final flush
            # 一次性处理所有剩余内容。
            should_flush = (
                len(flush_buffer) >= _FLUSH_BATCH_SIZE
                or (now - last_flush_at) >= _FLUSH_INTERVAL_SECONDS
            ) and len(background_persist_tasks) < _MAX_INFLIGHT_FLUSHES
            if should_flush:
                chunk = flush_buffer.copy()
                flush_buffer.clear()
                last_flush_at = now
                task = asyncio.create_task(_safe_persist(chunk))
                background_persist_tasks.add(task)
                task.add_done_callback(background_persist_tasks.discard)
        return format_sse(event, live_data, event_id=event_id)

    # None → LangGraph time-travel resume (no new input, just re-run from
    #   the configured checkpoint state). Used by regenerate to produce a
    #   sibling assistant turn from the same user message without duplicating
    #   that user message into the thread history.
    # Command(resume=...) → 直接传递
    # dict → 原样传递（用于 Builder v3 初始 state inject）
    # list → 包装为 {"messages": ...}
    actual_input: Any
    if input_ is None:
        actual_input = None
    elif isinstance(input_, (Command, dict)):
        actual_input = input_
    else:
        actual_input = {"messages": input_}

    full_content = ""
    was_interrupted = False
    stream_failed = False
    usage_data: dict[str, int | float] = {}
    # streaming timing — 从 message_start 前一刻到首个 content token（TTFT）+ 总生成时间。
    first_token_at: float | None = None
    # AIMessageChunk 会以 partial state 重复 emit 同一个 tool_call，因此进行 dedupe。
    emitted_tool_call_keys: set[tuple[str, str]] = set()
    # ADR-004：由于 PatchToolCallsMiddleware 不会过滤 stream，
    # 使用字符级 buffering 检测/移除中间件 JSON。
    # yield 按 LLM chunk 批处理，以减少 SSE 事件数量。
    _buf = ""
    _brace_depth = 0

    # W6 准确性 — 收集本 turn 中向外暴露的 AI 消息 raw langchain id。
    # streaming 期间同一消息会被拆成多个 chunk，因此 dedup。
    _seen_ai_msg_ids: set[str] = set()

    if artifact_recorder is not None:
        try:
            await artifact_recorder.prepare()
        except Exception:
            logger.exception("artifact recorder prepare failed (run_id=%s)", msg_id)
            artifact_recorder = None

    # W3-out M2 — 为确保 broker close + final flush + background flush join 一定
    # 执行，从 message_start emit 后立即开始，到 message_end 到达为止用 outer
    # try/finally 包裹。client disconnect 时（generator aclose）也会
    # 执行 finally，从而保证 broker.close。
    start_data: dict[str, Any] = {"id": msg_id, "role": "assistant"}
    debug_input = _debug_input_for_message_start(actual_input)
    if debug_input is not None:
        start_data["input"] = debug_input
    stream_started_at = time.monotonic()
    yield emit(event_names.MESSAGE_START, start_data)
    try:
        try:
            async for chunk in agent.astream(
                actual_input,
                config=config,
                stream_mode="messages",
            ):
                msg, metadata = chunk
                # Builder v3 sub-LLM 调用从界面 stream 中排除（在 helpers.py 中添加 tag）
                chunk_tags = (metadata or {}).get("tags") or []
                if "builder:internal" in chunk_tags:
                    continue
                # ★ Auto-compaction leak guard — deepagents summarization tokens
                # carry ``metadata.lc_source == "summarization"``. Suppress them so
                # the summary text never bleeds into the answer. The legacy path is
                # non-production, so it only suppresses (no running/done marker; that
                # is v3-only). Exact match — answer tokens have no lc_source.
                if (
                    settings.compaction_marker_enabled
                    and (metadata or {}).get("lc_source") == "summarization"
                ):
                    continue
                # LangChain ``usage_metadata`` 除了 input/output 外，还会
                # 通过 ``input_token_details`` 分别传递 cache_creation/cache_read
                # （Anthropic / OpenAI prompt caching）。在 yield content/tool 事件前
                # 在 yield 之前必须更新 sink，这样即使 user cancel/stream detach
                # 立即发生，已经到达的 usage 也会保留在 hook 路径中。
                extracted = extract_usage_breakdown(msg)
                if extracted is not None:
                    usage_data = {
                        "prompt_tokens": extracted.prompt_tokens,
                        "completion_tokens": extracted.completion_tokens,
                        "cache_creation_tokens": extracted.cache_creation_tokens,
                        "cache_read_tokens": extracted.cache_read_tokens,
                    }
                    if usage_data and (cost_per_input_token or cost_per_output_token):
                        prompt = usage_data.get("prompt_tokens", 0)
                        completion = usage_data.get("completion_tokens", 0)
                        cost = (prompt * (cost_per_input_token or 0)) + (
                            completion * (cost_per_output_token or 0)
                        )
                        usage_data["estimated_cost"] = round(cost, 8)
                    if usage_sink is not None:
                        usage_sink.update(usage_data)
                # W6：收集 AI 消息的 raw id（caller 提供 sink 时）。
                if msg_id_sink is not None and msg.type in ("ai", "AIMessageChunk"):
                    raw_id = getattr(msg, "id", None)
                    if isinstance(raw_id, str) and raw_id and raw_id not in _seen_ai_msg_ids:
                        _seen_ai_msg_ids.add(raw_id)
                        msg_id_sink.append(raw_id)
                if hasattr(msg, "content") and msg.content and msg.type in ("ai", "AIMessageChunk"):
                    # Anthropic 会以 list[dict] 形式发送 multi-block content（text + tool_use 等），
                    # 因此仅展平 text block。使用 message_utils 的共享 helper。
                    delta = content_to_text(msg.content)
                    if delta:
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                        _pending = ""
                        for ch in delta:
                            if ch == "{" and _brace_depth == 0:
                                # Flush pending text before entering JSON buffering
                                if _pending:
                                    full_content += _pending
                                    yield emit(event_names.CONTENT_DELTA, {"delta": _pending})
                                    _pending = ""
                                _brace_depth = 1
                                _buf = ch
                            elif _brace_depth > 0:
                                _buf += ch
                                if ch == "{":
                                    _brace_depth += 1
                                elif ch == "}":
                                    _brace_depth -= 1
                                    if _brace_depth == 0:
                                        # Outermost brace closed — check if middleware output
                                        if _is_tool_selector_json(_buf):
                                            _buf = ""
                                        else:
                                            full_content += _buf
                                            yield emit(event_names.CONTENT_DELTA, {"delta": _buf})
                                            _buf = ""
                            else:
                                _pending += ch
                        # Flush remaining pending text from this LLM chunk
                        if _pending:
                            full_content += _pending
                            yield emit(event_names.CONTENT_DELTA, {"delta": _pending})

                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tc_name = tc.get("name", "")
                        # 空名称（仍是 partial state）/ 中间件 internal schema 不向 UI 暴露（X）
                        if not tc_name or tc_name in _INTERNAL_TOOL_NAMES:
                            continue
                        tc_id = tc.get("id") or ""
                        # id 为空时，不将其作为 dedupe key — 防止同名但彼此不同的
                        # tool_call 因 collision 而 silently 丢失。
                        if tc_id:
                            key = (tc_name, tc_id)
                            if key in emitted_tool_call_keys:
                                continue
                            emitted_tool_call_keys.add(key)
                        parameters = sanitize_tool_call_parameters(
                            tc_name,
                            tc.get("args", {}),
                        )
                        parameters = enrich_subagent_tool_call_parameters(
                            tc_name,
                            parameters,
                            subagent_display_names,
                        )
                        start_payload = {
                            "tool_name": tc_name,
                            # ADR-017 §13.2 — heuristic key-pattern
                            # redaction (password / api_key / secret /
                            # token / access_key / refresh_token) so
                            # SSE consumers don't see secret-shaped
                            # values from any tool that accepts an
                            # auth-style argument. Skill tool already
                            # redacts its own results at the executor
                            # layer; this protects MCP/regular tools.
                            "parameters": parameters,
                        }
                        if tc_id:
                            start_payload["tool_call_id"] = tc_id
                        yield emit(event_names.TOOL_CALL_START, start_payload)

                if msg.type == "tool":
                    tool_name = msg.name if hasattr(msg, "name") else ""
                    # Internal middleware tool result 也不向 UI 暴露（X，与 start 对称）
                    if tool_name not in _INTERNAL_TOOL_NAMES:
                        result = msg.content if isinstance(msg.content, str) else str(msg.content)
                        result_payload = {"tool_name": tool_name, "result": result}
                        tool_call_id = getattr(msg, "tool_call_id", None)
                        if isinstance(tool_call_id, str) and tool_call_id:
                            result_payload["tool_call_id"] = tool_call_id
                        yield emit(event_names.TOOL_CALL_RESULT, result_payload)
                        if artifact_recorder is not None:
                            try:
                                normalized_tool_call_id = (
                                    tool_call_id if isinstance(tool_call_id, str) else None
                                )
                                artifact_events = await artifact_recorder.collect_after_tool_result(
                                    tool_name=tool_name,
                                    tool_call_id=normalized_tool_call_id,
                                )
                            except Exception:
                                logger.exception(
                                    "artifact recorder collect failed (run_id=%s, tool=%s)",
                                    msg_id,
                                    tool_name,
                                )
                                artifact_events = []
                            for payload in artifact_events:
                                yield emit(event_names.FILE_EVENT, payload)
                        memory_event = memory_event_from_tool_result(
                            tool_name,
                            result,
                        )
                        if memory_event is not None:
                            event, payload = memory_event
                            yield emit(event, payload)

        except GraphInterrupt:
            # interrupt() 导致的正常图暂停 — 不是错误
            # 在下面的 aget_state 中 emit interrupt 事件
            was_interrupted = True
        except Exception as e:
            stream_failed = True
            error_record = StreamErrorRecord(
                error=e,
                message=public_stream_error_message(
                    e, locale=config.get("configurable", {}).get("ui_locale")
                ),
            )
            if error_sink is not None:
                error_sink.append(error_record)
            yield emit(event_names.ERROR, {"message": error_record.message})

        # Flush any remaining buffer (incomplete JSON = not middleware output)
        if _buf:
            full_content += _buf

        # HiTL：检测图 state 中的 interrupt 后，以标准 wire 形式 emit。
        # 转换由 ``_interrupt_to_standard_chunk`` 这一单一入口负责
        # （包括自有 ask_user.py adapter）。fallback 发送空的标准 chunk。
        try:
            state = await agent.aget_state(config)
            if state.tasks:
                for task in state.tasks:
                    if task.interrupts:
                        for intr in task.interrupts:
                            intr_id = str(getattr(intr, "ns", ""))
                            intr_value = intr.value if isinstance(intr.value, dict) else None
                            chunk = _interrupt_to_standard_chunk(intr_id, intr_value)
                            if chunk is not None:
                                yield emit(event_names.INTERRUPT, chunk)
        except Exception:
            logger.warning("aget_state failed (interrupt check)", exc_info=True)
            if was_interrupted:
                # fallback：state 查询失败，因此无法得知准确 action。发送空的标准
                # emit chunk — frontend 会以空 action_requests 显示 fallback UI。
                yield emit(
                    event_names.INTERRUPT,
                    {
                        "interrupt_id": "",
                        "action_requests": [],
                        "review_configs": [],
                    },
                )

        # Calculate estimated cost from model pricing if available. This is
        # repeated after the stream loop for backwards compatibility with any
        # future usage source that populates ``usage_data`` outside the chunk
        # extraction path.
        if usage_data and (cost_per_input_token or cost_per_output_token):
            prompt = usage_data.get("prompt_tokens", 0)
            completion = usage_data.get("completion_tokens", 0)
            cost = (prompt * (cost_per_input_token or 0)) + (
                completion * (cost_per_output_token or 0)
            )
            usage_data["estimated_cost"] = round(cost, 8)

        # Surface captured usage to the caller (executor → hook framework).
        # timing 不供 hook 使用，因此仅在 sink 更新之后、SSE emit 之前合并。
        if usage_sink is not None and usage_data:
            usage_sink.update(usage_data)

        # 将 streaming timing（TTFT/总时间/tok-s）与 usage payload 一起发送。
        # 仅在存在 token 时（=会渲染 popover 时）才有意义，因此只在该情况下合并。
        if usage_data:
            usage_data.update(
                compute_usage_timing(
                    started_at=stream_started_at,
                    first_token_at=first_token_at,
                    completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
                )
            )

        yield emit(
            event_names.MESSAGE_END,
            {
                "usage": usage_data,
                "content": full_content,
                "status": "failed" if stream_failed else "completed",
            },
        )
    finally:
        # W3-out M2 — final flush + background flush join + broker close.
        # 必须始终执行（正常结束 / GraphInterrupt / Exception / client
        # disconnect 时的 generator aclose() 均包括）。失败时 swallow + log。
        # 顺序很重要：(1) background tasks join → 让正在进行的 partial flush
        # 完成，从而确定 retry_buffer。(2) 合并 retry_buffer + flush_buffer，
        # 一次性 final flush → 这是从 DB 临时故障导致遗漏 chunk 中恢复的最后机会。
        if background_persist_tasks:
            # 回收正在运行的 fire-and-forget tasks。此后
            # 不会再向 retry_buffer 新增内容。
            await asyncio.gather(*background_persist_tasks, return_exceptions=True)
        if persist_callback is not None and (retry_buffer or flush_buffer):
            # 先 retry → 然后处理最后仍留在 buffer 中的新 chunk。
            # 调用两次时，dedup-by-id 保证 idempotency。
            final_chunks: list[list[dict[str, Any]]] = []
            if retry_buffer:
                final_chunks.append(retry_buffer.copy())
                retry_buffer.clear()
            if flush_buffer:
                final_chunks.append(flush_buffer.copy())
                flush_buffer.clear()
            for chunk in final_chunks:
                try:
                    await persist_callback(chunk)
                except Exception:
                    logger.exception(
                        "final flush persist_callback failed "
                        "(run_id=%s) — %d events permanently lost",
                        msg_id,
                        len(chunk),
                    )
        if broker is not None:
            broker.close()
