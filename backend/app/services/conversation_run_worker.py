from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any, Literal, cast

from sqlalchemy.exc import SQLAlchemyError

from app.agent_runtime import event_names
from app.agent_runtime.checkpointer import get_checkpointer
from app.agent_runtime.event_broker import BrokeredEvent, EventBroker
from app.agent_runtime.protocol_redaction import REDACTED_SENSITIVE_FIELD
from app.agent_runtime.run_metrics import RunMetricsAccumulator
from app.agent_runtime.run_metrics_baseline import (
    baseline_completed_tool_call_source_identities,
    baseline_message_identities,
)
from app.agent_runtime.run_metrics_types import TerminalRunState
from app.agent_runtime.runtime_config import AgentConfig
from app.agent_runtime.stream_error_messages import public_stream_error_message
from app.config import settings
from app.dependencies import CurrentUser
from app.marketplace.redaction import replace_secret_values
from app.models.conversation import Conversation
from app.models.conversation_run import ConversationRun
from app.services import conversation_run_service, thread_branch_service
from app.services import conversation_stream_service as stream_service
from app.services.conversation_audit_service import record_conversation_run_audit
from app.services.conversation_run_interrupts import (
    has_interrupt_events,
    interrupt_id_from_events,
)
from app.services.conversation_run_metrics_service import persist_run_metrics_and_usage
from app.services.conversation_run_terminal_delivery import OwnerTerminalDelivery
from app.services.conversation_stream_service import StreamCtx

logger = logging.getLogger(__name__)

AgentStreamExecutor = Callable[..., AsyncGenerator[str, None]]
async_session = None
CancelReason = Literal["stop", "steer", "shutdown"]
_CANCEL_POLL_SECONDS = 0.25


class RunTaskAlreadyRegisteredError(RuntimeError):
    pass


def _session_factory():
    return async_session or stream_service.async_session


def _effective_terminal_status(
    run: ConversationRun,
    proposed_status: TerminalRunState,
    *,
    cancellation_ack_worker_id: str | None,
    allow_workerless_cancellation_ack: bool,
) -> TerminalRunState:
    owner_ack = (
        cancellation_ack_worker_id is not None
        and run.worker_instance_id == cancellation_ack_worker_id
    )
    workerless_ack = allow_workerless_cancellation_ack and run.worker_instance_id is None
    if proposed_status != "stale" and run.status == "canceling" and (owner_ack or workerless_ack):
        return "canceled"
    return proposed_status


class RunTaskRegistry:
    def __init__(self, *, worker_instance_id: str | None = None) -> None:
        self.worker_instance_id = worker_instance_id or f"worker-{uuid.uuid4().hex[:16]}"
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._cancel_reasons: dict[uuid.UUID, CancelReason] = {}

    def start(self, run_id: uuid.UUID, task: asyncio.Task[None]) -> None:
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            task.cancel()
            raise RunTaskAlreadyRegisteredError(f"run task already exists: {run_id}")
        self._tasks[run_id] = task

        def _discard(done_task: asyncio.Task[None]) -> None:
            self.discard(run_id)
            with contextlib.suppress(asyncio.CancelledError):
                exc = done_task.exception()
                if exc is not None:
                    logger.error(
                        "conversation run task crashed run_id=%s",
                        run_id,
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )

        task.add_done_callback(_discard)

    def get(self, run_id: uuid.UUID) -> asyncio.Task[None] | None:
        return self._tasks.get(run_id)

    def active_run_ids(self) -> set[uuid.UUID]:
        return {run_id for run_id, task in self._tasks.items() if not task.done()}

    def cancel(self, run_id: uuid.UUID) -> bool:
        return self.request_cancel(run_id, reason="stop")

    def request_cancel(self, run_id: uuid.UUID, *, reason: CancelReason) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        self._cancel_reasons[run_id] = reason
        task.cancel()
        return True

    def cancel_reason(self, run_id: uuid.UUID) -> CancelReason | None:
        return self._cancel_reasons.get(run_id)

    def discard(self, run_id: uuid.UUID) -> None:
        self._tasks.pop(run_id, None)
        self._cancel_reasons.pop(run_id, None)

    async def shutdown(self, timeout_seconds: float = 10.0) -> None:
        items = [(run_id, task) for run_id, task in self._tasks.items() if not task.done()]
        try:
            await _persist_shutdown_intent([run_id for run_id, _task in items])
        except SQLAlchemyError:
            logger.exception("failed to persist conversation run shutdown intent")
        for run_id, task in items:
            self._cancel_reasons[run_id] = "shutdown"
            task.cancel()
        tasks = [task for _, task in items]
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "timed out waiting for %d conversation run task(s) during shutdown",
                    len(tasks),
                )
        self._tasks.clear()
        self._cancel_reasons.clear()


_registry = RunTaskRegistry()


def get_run_task_registry() -> RunTaskRegistry:
    return _registry


def reset_run_task_registry_for_tests(registry: RunTaskRegistry | None = None) -> None:
    global _registry
    _registry = registry or RunTaskRegistry()


def _parse_sse_chunk(chunk: str) -> list[tuple[str, str | None, dict[str, Any]]]:
    events: list[tuple[str, str | None, dict[str, Any]]] = []
    for block in chunk.split("\n\n"):
        event_name: str | None = None
        event_id: str | None = None
        data_lines: list[str] = []
        for raw_line in block.splitlines():
            if raw_line.startswith("event:"):
                event_name = raw_line[len("event:") :].strip()
            elif raw_line.startswith("id:"):
                event_id = raw_line[len("id:") :].strip()
            elif raw_line.startswith("data:"):
                data_lines.append(raw_line[len("data:") :].strip())
        if not event_name:
            continue
        raw_data = "\n".join(data_lines).strip()
        try:
            data = json.loads(raw_data) if raw_data else {}
        except json.JSONDecodeError:
            data = {"raw": raw_data}
        if isinstance(data, dict):
            events.append((event_name, event_id or None, data))
    return events


def _publish_yielded_chunk_if_needed(
    ctx: StreamCtx,
    chunk: str,
    compat_seq: int,
    emitted_events: list[dict[str, Any]] | None = None,
    *,
    broker: EventBroker | OwnerTerminalDelivery | None = None,
) -> int:
    target_broker = broker or ctx.broker
    for event_name, event_id, data in _parse_sse_chunk(chunk):
        if event_id:
            resolved_id = event_id
        else:
            compat_seq += 1
            resolved_id = f"{ctx.run_id}-compat-{compat_seq}"
        if target_broker.last_event_id == resolved_id:
            continue
        event: BrokeredEvent = {"id": resolved_id, "event": event_name, "data": data}
        target_broker.publish_nowait(event)
        if emitted_events is not None:
            emitted_events.append(dict(event))
    return compat_seq


async def start_conversation_run(
    *,
    run_id: uuid.UUID,
    conversation_id: uuid.UUID,
    cfg: AgentConfig,
    user: CurrentUser,
    input_payload: Any,
    moldy_source: str,
    executor_fn: AgentStreamExecutor,
    registry: RunTaskRegistry | None = None,
    attachment_ids: list[uuid.UUID] | None = None,
) -> StreamCtx:
    registry = registry or get_run_task_registry()
    ctx = stream_service.prepare_stream_context(conversation_id, run_id=str(run_id))
    task = asyncio.create_task(
        _run_conversation(
            run_id=run_id,
            conversation_id=conversation_id,
            cfg=cfg,
            user=user,
            input_payload=input_payload,
            moldy_source=moldy_source,
            executor_fn=executor_fn,
            ctx=ctx,
            registry=registry,
            attachment_ids=attachment_ids,
        ),
        name=f"conversation-run-{run_id}",
    )
    registry.start(run_id, task)
    return ctx


async def _transition(
    run_id: uuid.UUID,
    status: TerminalRunState,
    *,
    worker_instance_id: str | None = None,
    interrupt_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    cancellation_ack_worker_id: str | None = None,
    allow_workerless_cancellation_ack: bool = False,
    run_metrics: RunMetricsAccumulator,
    model_name: str,
    terminal_event_for_status: Callable[[TerminalRunState], dict[str, Any]] | None = None,
) -> tuple[ConversationRun | None, TerminalRunState]:
    async with _session_factory()() as session:
        run = await session.get(ConversationRun, run_id, with_for_update=True)
        if run is None:
            return None, status
        effective_status = _effective_terminal_status(
            run,
            status,
            cancellation_ack_worker_id=cancellation_ack_worker_id,
            allow_workerless_cancellation_ack=allow_workerless_cancellation_ack,
        )
        try:
            metrics_snapshot = run_metrics.finalize(effective_status)
            terminal_event = (
                terminal_event_for_status(effective_status)
                if terminal_event_for_status is not None
                else None
            )
            if terminal_event is not None or effective_status == "canceled":
                await conversation_run_service.finalize_run_outputs_for_status(
                    session,
                    run,
                    effective_status,
                    append_terminal_event=terminal_event is None,
                    terminal_event=terminal_event,
                )
            await conversation_run_service.transition_run(
                session,
                run,
                effective_status,
                worker_instance_id=worker_instance_id,
                interrupt_id=interrupt_id,
                error_code=error_code,
                error_message=error_message,
                cancellation_ack_worker_id=cancellation_ack_worker_id,
                allow_workerless_cancellation_ack=allow_workerless_cancellation_ack,
            )
            await persist_run_metrics_and_usage(
                session,
                run=run,
                snapshot=metrics_snapshot,
                model_name=model_name,
            )
            await session.commit()
        except ValueError:
            await session.rollback()
            logger.exception(
                "invalid conversation run transition run_id=%s status=%s",
                run_id,
                effective_status,
            )
            raise
        return run, effective_status


async def _transition_to_running(
    run_id: uuid.UUID,
    *,
    worker_instance_id: str,
) -> tuple[ConversationRun | None, bool]:
    """尝试 ``queued -> running`` 转换。返回 ``(run, started)``。

    cancel API 可能在 worker 启动前已提交 ``queued -> canceling``，或 sweep
    可能先将其送到 terminal。此时若无条件转换，``ValueError`` 会被
    误分类为 runtime failure（canceled 看起来像 failed），因此在 row lock 下
    同时进行状态判断与转换，无法启动的原因由调用方根据当前
    status 分支处理。
    """
    async with _session_factory()() as session:
        run = await session.get(ConversationRun, run_id, with_for_update=True)
        if run is None:
            return None, False
        if run.status != "queued":
            return run, False
        await conversation_run_service.transition_run(
            session,
            run,
            "running",
            worker_instance_id=worker_instance_id,
        )
        await session.commit()
        return run, True


def _heartbeat_interval_seconds() -> float:
    return max(1.0, min(30.0, settings.chat_run_stale_after_seconds / 3))


async def _heartbeat_until_terminal(run_id: uuid.UUID, registry: RunTaskRegistry) -> None:
    interval = _heartbeat_interval_seconds()
    next_heartbeat = time.monotonic()
    while True:
        await asyncio.sleep(_CANCEL_POLL_SECONDS)
        async with _session_factory()() as session:
            run = await session.get(ConversationRun, run_id)
            if run is None or not run.is_active:
                return
            if run is not None and run.status == "canceling":
                reason = (
                    cast(CancelReason, run.cancel_reason)
                    if run.cancel_reason in {"stop", "steer", "shutdown"}
                    else "stop"
                )
                registry.request_cancel(run_id, reason=reason)
                return
            if time.monotonic() >= next_heartbeat:
                alive = await conversation_run_service.heartbeat_run(session, run_id)
                await session.commit()
                if not alive:
                    return
                next_heartbeat = time.monotonic() + interval


async def _persist_shutdown_intent(run_ids: list[uuid.UUID]) -> None:
    if not run_ids:
        return
    async with _session_factory()() as session:
        for run_id in run_ids:
            run = await session.get(ConversationRun, run_id, with_for_update=True)
            if run is not None and run.status in {"queued", "running"}:
                await conversation_run_service.request_cancel_run(
                    session,
                    run,
                    reason="shutdown",
                )
        await session.commit()


def _redact_run_error_message(text: str, secret_values: set[str]) -> str | None:
    """对失败 run 的 error_message 做基于值的脱敏后整理为存储内容。

    若注入 run 的 credential 值被 echo 到异常文本中，则用 exact-substring
    替换遮蔽（ADR-021 / CLAUDE.md redaction 规则）。run-secret ContextVar
    在流结束时已经 reset，因此显式传入 cfg.secret_values。
    """
    masked = replace_secret_values(
        text, secret_values, placeholder=REDACTED_SENSITIVE_FIELD
    ).strip()[:1000]
    return masked or None


async def _publish_error(ctx: StreamCtx, message: str) -> None:
    compat_seq = 0
    parsed_events: list[dict[str, Any]] = []
    for chunk in stream_service.error_sse_pair(message):
        compat_seq = _publish_yielded_chunk_if_needed(
            ctx,
            chunk,
            compat_seq,
            parsed_events,
        )
    if parsed_events:
        await ctx.persist_cb(parsed_events)
        ctx.trace_sink.extend(parsed_events)


async def _publish_message_end(ctx: StreamCtx, *, status: str) -> None:
    event_id = f"{ctx.run_id}-{status}"
    # cancel 后 CancelledError 若再次到达，可能将同一个 terminal event 重复
    # publish/persist 两次 — 若与上一个 event 的 id 相同则 no-op。
    if ctx.broker.last_event_id == event_id:
        return
    event: BrokeredEvent = {
        "id": event_id,
        "event": event_names.MESSAGE_END,
        "data": {"usage": {}, "content": "", "status": status},
    }
    ctx.broker.publish_nowait(event)
    persisted_event: dict[str, Any] = dict(event)
    await ctx.persist_cb([persisted_event])
    ctx.trace_sink.append(persisted_event)


async def _publish_stale(ctx: StreamCtx, *, reason: str) -> None:
    event_id = f"{ctx.run_id}-stale"
    event: BrokeredEvent = {
        "id": event_id,
        "event": event_names.STALE,
        "data": {
            "reason": reason,
            "run_id": ctx.run_id,
            "last_event_id": ctx.broker.last_event_id,
        },
    }
    ctx.broker.publish_nowait(event)
    persisted_event: dict[str, Any] = dict(event)
    await ctx.persist_cb([persisted_event])
    ctx.trace_sink.append(persisted_event)


def _audit_action_for_terminal_status(status: conversation_run_service.RunStatus) -> str | None:
    if status == "completed":
        return "conversation.run_complete"
    if status == "canceled":
        return "conversation.run_canceled"
    if status == "interrupted":
        return "conversation.run_interrupted"
    if status == "stale":
        return "conversation.run_stale"
    if status == "failed":
        return "conversation.run_failed"
    return None


async def _record_run_audit(
    *,
    action: str,
    run: ConversationRun,
    user: CurrentUser,
    status: str | None = None,
) -> None:
    async with _session_factory()() as session:
        await record_conversation_run_audit(
            session,
            action=action,
            run=run,
            user=user,
            status=status,
        )
        await session.commit()


async def _activate_latest_branch_leaf_if_needed(
    *,
    conversation_id: uuid.UUID,
    moldy_source: str,
    final_status: conversation_run_service.RunStatus,
) -> None:
    if final_status != "completed" or moldy_source not in {"edit", "regenerate"}:
        return
    try:
        tree = await thread_branch_service.build_message_tree(
            get_checkpointer(),
            str(conversation_id),
            active_checkpoint_id=None,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to resolve latest branch leaf after %s run conversation_id=%s",
            moldy_source,
            conversation_id,
            exc_info=True,
        )
        return
    if not tree.active_checkpoint_id:
        return

    async with _session_factory()() as session:
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        if conversation is None:
            return
        conversation.active_branch_checkpoint_id = tree.active_checkpoint_id
        await session.commit()


def _trace_status_for_run(
    status: conversation_run_service.RunStatus,
) -> Literal["completed", "failed"]:
    if status in {"completed", "interrupted", "canceled"}:
        return "completed"
    return "failed"


async def _backfill_turn_attachments(
    conversation_id: uuid.UUID, attachment_ids: list[uuid.UUID]
) -> None:
    """Stamp this send's uploads with the turn's user message id (M1).

    Runs once at finalize, after the turn's HumanMessage is in the checkpoint,
    in its own session so it can't poison the run-teardown transaction.
    """

    from app.services import chat_service

    async with _session_factory()() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            return
        message_id = await chat_service.resolve_turn_user_message_id(session, conversation)
        if not message_id:
            return
        await chat_service.link_attachments_to_message(
            session, attachment_ids=attachment_ids, message_id=message_id
        )
        await session.commit()


async def _prepare_run_metrics(
    *,
    conversation_id: uuid.UUID,
    cfg: AgentConfig,
    started_at: float,
) -> RunMetricsAccumulator:
    """Capture the exact pre-input assistant IDs used to exclude checkpoint replay."""
    try:
        async with _session_factory()() as session:
            conversation = await session.get(Conversation, conversation_id)
            active_checkpoint_id = (
                getattr(cfg, "checkpoint_id", None)
                if getattr(cfg, "checkpoint_id", None) is not None
                else conversation.active_branch_checkpoint_id
                if conversation is not None
                else None
            )
        tree = await thread_branch_service.build_message_tree(
            get_checkpointer(),
            str(conversation_id),
            active_checkpoint_id=active_checkpoint_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "run metrics checkpoint baseline unavailable conversation_id=%s",
            conversation_id,
            exc_info=True,
        )
        return RunMetricsAccumulator(
            started_at=started_at,
            complete_event_capture=False,
            observe_protocol_events=False,
        )
    baseline_messages = tuple(node.message for node in tree.nodes)
    return RunMetricsAccumulator(
        started_at=started_at,
        baseline_message_identities=baseline_message_identities(baseline_messages),
        baseline_completed_tool_call_source_identities=(
            baseline_completed_tool_call_source_identities(baseline_messages)
        ),
    )


async def _run_conversation(
    *,
    run_id: uuid.UUID,
    conversation_id: uuid.UUID,
    cfg: AgentConfig,
    user: CurrentUser,
    input_payload: Any,
    moldy_source: str,
    executor_fn: AgentStreamExecutor,
    ctx: StreamCtx,
    registry: RunTaskRegistry,
    attachment_ids: list[uuid.UUID] | None = None,
) -> None:
    metrics_started_at = time.monotonic()
    run_metrics = RunMetricsAccumulator(started_at=metrics_started_at)
    final_status: TerminalRunState = "completed"
    failure: Exception | None = None
    error_code: str | None = None
    error_message: str | None = None
    interrupt_id: str | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    compat_seq = 0
    # worker 无法启动 run 时（已消失/已 terminal），会跳过 finally 中的
    # trace finalize + terminal 转换 — 这是为了不对已由其他路径结束的 run
    # 再次 finalize。
    finalize_needed = True
    workerless_cancel_before_start = False
    executor_exhausted_normally = False
    terminal_delivery = OwnerTerminalDelivery(
        run_id=ctx.run_id,
        broker=ctx.broker,
        persist_callback=ctx.persist_cb,
        trace_sink=ctx.trace_sink,
    )
    try:
        run, started = await _transition_to_running(
            run_id,
            worker_instance_id=registry.worker_instance_id,
        )
        if run is None:
            logger.warning("conversation run vanished before worker start run_id=%s", run_id)
            finalize_needed = False
            return
        if not started:
            if run.status == "canceling" and run.worker_instance_id is None:
                # Stop 请求在 worker 启动前（queued）到达 — 不执行直接以 canceled
                # 结束。不会将 running 转换失败误分类为 failed。
                final_status = "canceled"
                workerless_cancel_before_start = True
                await _publish_message_end(ctx, status="canceled")
            else:
                logger.warning(
                    "conversation run not startable run_id=%s status=%s",
                    run_id,
                    run.status,
                )
                finalize_needed = False
            return
        await _record_run_audit(
            action="conversation.run_start",
            run=run,
            user=user,
            status="running",
        )
        heartbeat_task = asyncio.create_task(
            _heartbeat_until_terminal(run_id, registry),
            name=f"conversation-run-heartbeat-{run_id}",
        )
        run_metrics = await _prepare_run_metrics(
            conversation_id=conversation_id,
            cfg=cfg,
            started_at=metrics_started_at,
        )

        stream_kwargs = ctx.as_stream_kwargs()
        stream_kwargs["broker"] = terminal_delivery
        stream_kwargs["persist_callback"] = terminal_delivery.persist
        stream_kwargs["run_metrics"] = run_metrics
        stream_kwargs["artifact_recorder"] = stream_service.build_artifact_recorder(
            conversation_id=conversation_id,
            cfg=cfg,
            user=user,
            run_id=ctx.run_id,
        )
        async for chunk in executor_fn(
            cfg,
            input_payload,
            moldy_source=moldy_source,
            **stream_kwargs,
        ):
            compat_seq = _publish_yielded_chunk_if_needed(
                ctx,
                chunk,
                compat_seq,
                broker=terminal_delivery,
            )
        executor_exhausted_normally = True

        if ctx.has_stream_error():
            final_status = "failed"
            # 流过程中失败不会以异常传播，而是记录到 error_sink
            # （在 streaming.py 中通过 public_stream_error_message 做第一次 blocklist 脱敏）。
            # 再次应用基于注入 run 的 credential 值的脱敏，使聊天错误
            # 气泡能安全显示具体原因，而非 fallback（G2 retry）。
            # _run_metadata 仅在 failed 时暴露该值。
            error_code = "stream_error"
            error_message = _redact_run_error_message(
                ctx.error_sink[0].message or "", cfg.secret_values
            )
        elif has_interrupt_events(ctx.trace_sink):
            final_status = "interrupted"
            interrupt_id = interrupt_id_from_events(ctx.trace_sink)
    except asyncio.CancelledError:
        cancel_reason = registry.cancel_reason(run_id)
        if cancel_reason == "shutdown":
            final_status = "stale"
            error_code = "worker_shutdown"
            error_message = "Application shutdown canceled the run before completion."
            await _publish_stale(ctx, reason="worker_shutdown")
        else:
            final_status = "canceled"
            await _publish_message_end(ctx, status="canceled")
    except Exception as exc:
        final_status = "failed"
        failure = exc
        error_code = "runtime_error"
        # 流外异常（credential 解析/checkpointer/DB 等）尚未经过任何脱敏。
        # 通过 public_stream_error_message（blocklist）+ 基于值
        # （cfg.secret_values）的两阶段脱敏，防止注入的 credential 值泄露。
        # 但文件路径/DB 主机等内部拓扑无法通过这两阶段完全遮蔽，因此
        # runtime_error 的 error_message 不显示在聊天气泡中（_run_metadata
        # 只暴露 stream_error）。脱敏后的详情仅保留在 GET /runs/{id} 运维路径中，
        # 原始异常仅保留在服务器日志（logger.exception）中。
        error_message = _redact_run_error_message(
            public_stream_error_message(exc), cfg.secret_values
        )
        logger.exception("conversation run worker failed run_id=%s", run_id)
        await _publish_error(ctx, "Agent 执行过程中发生错误。")
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        if executor_exhausted_normally:
            terminal_delivery.remove_staged_terminal_from_trace()

        async def _finalize_trace_for_status(
            effective_status: TerminalRunState,
        ) -> None:
            try:
                await stream_service.finalize_trace(
                    conversation_id,
                    ctx.run_id,
                    ctx.trace_sink,
                    ctx.msg_id_sink,
                    ctx.langfuse_sink,
                    success=effective_status == "completed",
                    status=_trace_status_for_run(effective_status),
                    run_status=effective_status,
                )
            except Exception:
                logger.exception("conversation run trace finalization failed run_id=%s", run_id)

        async def _finalize_run_status() -> TerminalRunState:
            try:
                final_run, effective_status = await _transition(
                    run_id,
                    final_status,
                    error_code=error_code,
                    error_message=error_message,
                    interrupt_id=interrupt_id,
                    cancellation_ack_worker_id=registry.worker_instance_id,
                    allow_workerless_cancellation_ack=workerless_cancel_before_start,
                    run_metrics=run_metrics,
                    model_name=getattr(cfg, "model_name", "unknown"),
                    terminal_event_for_status=(
                        lambda status: terminal_delivery.terminal_events_for_status(status)[1]
                    )
                    if executor_exhausted_normally
                    else None,
                )
                if final_run is not None and executor_exhausted_normally:
                    live_terminal, persisted_terminal = (
                        terminal_delivery.terminal_events_for_status(effective_status)
                    )
                    terminal_delivery.publish_terminal(live_terminal, persisted_terminal)
                action = _audit_action_for_terminal_status(effective_status)
                if final_run is not None and action is not None:
                    await _record_run_audit(
                        action=action,
                        run=final_run,
                        user=user,
                        status=effective_status,
                    )
                await _activate_latest_branch_leaf_if_needed(
                    conversation_id=conversation_id,
                    moldy_source=moldy_source,
                    final_status=effective_status,
                )
            except Exception:
                logger.exception("conversation run status finalization failed run_id=%s", run_id)
                return final_status
            return effective_status

        if finalize_needed:
            effective_status = final_status
            # Interrupted runs still commit before trace finalization so resume can
            # find the parent. Other runs keep trace first; a late cancellation is
            # reconciled inside the subsequent locked transition before queue dispatch.
            if final_status == "interrupted":
                effective_status = await _finalize_run_status()

            await _finalize_trace_for_status(effective_status)

            if final_status != "interrupted":
                await _finalize_run_status()

            if attachment_ids:
                # M1 — stamp this send's uploads with the user message id the read
                # path will compute. Runs AFTER branch activation so it resolves
                # against the SAME active_branch_checkpoint_id the read path uses
                # (an edit/regenerate run forks a new leaf that's activated just
                # above; resolving before activation would walk the stale branch
                # and mis-link). Best-effort: a failure leaves message_id NULL
                # (orphan GC reaps it later) rather than breaking run teardown.
                try:
                    await _backfill_turn_attachments(conversation_id, attachment_ids)
                except Exception:
                    logger.exception("attachment message_id backfill failed run_id=%s", run_id)

        ctx.broker.close(error=failure)
        registry.discard(run_id)
        if finalize_needed:
            from app.services.conversation_run_queue_worker import (
                dispatch_next_for_conversation,
            )

            await dispatch_next_for_conversation(conversation_id)


__all__ = [
    "RunTaskRegistry",
    "RunTaskAlreadyRegisteredError",
    "get_run_task_registry",
    "reset_run_task_registry_for_tests",
    "start_conversation_run",
]
