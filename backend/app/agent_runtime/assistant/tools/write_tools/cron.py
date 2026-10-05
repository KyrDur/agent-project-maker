"""Assistant 写入工具 — 定时计划组（create/update/delete/enable/disable）。"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.assistant.tools.write_tools.context import WriteToolContext
from app.agent_runtime.builder_i18n import tr
from app.models.agent_trigger import AgentTrigger
from app.schemas.trigger import TriggerCreate, TriggerUpdate
from app.services import trigger_service


def _format_trigger_candidate(trigger: AgentTrigger) -> str:
    return tr(
        "id_v_name_v_status_e6ee46",
        v0=f"{trigger.id}",
        v1=f"{trigger.name}",
        v2=f"{trigger.status}",
        v3=f"{trigger.next_run_at or tr('not_yet_decided_35a478')}",
    )


async def _resolve_trigger_for_write(
    ctx: WriteToolContext,
    session: AsyncSession,
    schedule_id: str | None = None,
    schedule_name: str | None = None,
) -> tuple[AgentTrigger | None, str | None]:
    if schedule_id:
        try:
            sid = uuid.UUID(schedule_id)
        except ValueError:
            return None, tr("invalid_schedule_id_22d6bb")
        result = await session.execute(
            select(AgentTrigger).where(
                AgentTrigger.id == sid,
                AgentTrigger.agent_id == ctx.agent_id,
                AgentTrigger.user_id == ctx.user_id,
            )
        )
        trigger = result.scalar_one_or_none()
        if not trigger:
            return None, tr("schedule_not_found_0a71df")
        return trigger, None

    if not schedule_name:
        return None, tr("requires_schedule_id_or_schedule_a052ed")

    result = await session.execute(
        select(AgentTrigger)
        .where(
            AgentTrigger.agent_id == ctx.agent_id,
            AgentTrigger.user_id == ctx.user_id,
            AgentTrigger.name == schedule_name,
        )
        .order_by(AgentTrigger.created_at.desc())
    )
    matches = list(result.scalars().all())
    if not matches:
        return None, tr("schedule_not_found_0a71df")
    if len(matches) > 1:
        candidates = "\n".join(_format_trigger_candidate(trigger) for trigger in matches)
        return (
            None,
            (
                tr(
                    "there_are_multiple_schedules_with_5c0ade",
                    v0=f"{schedule_name}",
                    v1=f"{candidates}",
                )
            ),
        )
    return matches[0], None


def build_cron_tools(ctx: WriteToolContext) -> list[StructuredTool]:
    """创建 5 个定时计划工具。"""

    # ------ 14. create_cron_schedule ------

    async def create_cron_schedule(
        schedule_type: str,
        message: str,
        name: str | None = None,
        cron_expression: str | None = None,
        interval_minutes: int | None = None,
        scheduled_at: str | None = None,
        timezone: str | None = None,
        conversation_policy: str | None = None,
        target_conversation_id: str | None = None,
        max_runs: int | None = None,
        end_at: str | None = None,
        auto_pause_after_failures: int | None = None,
    ) -> str:
        """创建定时计划。

        Args:
            schedule_type: "recurring", "cron", "interval" 或 "one_time"
            message: 执行时传递的消息
            name: 计划名称
            cron_expression: 重复计划的 cron 表达式（recurring/cron 时必填）
            interval_minutes: 间隔分钟数（interval 时必填）
            scheduled_at: 单次执行时间 ISO 8601（one_time 时必填）
            timezone: IANA timezone（默认 Asia/Seoul）
            conversation_policy: 结果保存策略（默认 schedule_thread）
            target_conversation_id: selected_conversation 策略使用的对话 ID
            max_runs: 最大成功执行次数
            end_at: 结束时间 ISO 8601
            auto_pause_after_failures: 连续失败自动暂停阈值
        """
        normalized_type = schedule_type.strip().lower()
        trigger_type = "cron" if normalized_type in {"recurring", "cron"} else normalized_type
        schedule_config: dict[str, Any] = {}
        if trigger_type == "cron":
            if not cron_expression:
                return tr("a_recurring_schedule_requires_cron_91026d")
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                return tr("invalid_cron_expression_v_five_d4ae76", v0=f"{cron_expression}")
            schedule_config = {"cron_expression": cron_expression}
        elif trigger_type == "interval":
            if interval_minutes is None:
                return tr("interval_schedules_require_interval_minutes_d45185")
            schedule_config = {"interval_minutes": interval_minutes}
        elif trigger_type == "one_time":
            if not scheduled_at:
                return tr("scheduled_at_is_required_for_4ef5ae")
            schedule_config = {"scheduled_at": scheduled_at}
        else:
            return tr("schedule_type_must_be_recurring_3c9b07")

        async with ctx.session_factory() as session:
            try:
                trigger = await trigger_service.create_trigger(
                    session,
                    ctx.agent_id,
                    ctx.user_id,
                    TriggerCreate.model_validate(
                        {
                            "name": name,
                            "trigger_type": trigger_type,
                            "schedule_config": schedule_config,
                            "input_message": message,
                            "timezone": timezone or "Asia/Seoul",
                            "conversation_policy": conversation_policy or "schedule_thread",
                            "target_conversation_id": target_conversation_id,
                            "max_runs": max_runs,
                            "end_at": end_at,
                            "auto_pause_after_failures": auto_pause_after_failures,
                        }
                    ),
                )
            except ValueError as exc:
                return tr("schedule_settings_are_incorrect_v_667184", v0=f"{exc}")
            return tr(
                "schedule_creation_completed_id_v_28fe85",
                v0=f"{trigger.id}",
                v1=f"{trigger.next_run_at or tr('not_yet_decided_35a478')}",
            )

    # ------ 15. update_cron_schedule ------

    async def update_cron_schedule(
        schedule_id: str | None = None,
        schedule_name: str | None = None,
        cron_expression: str | None = None,
        interval_minutes: int | None = None,
        scheduled_at: str | None = None,
        message: str | None = None,
        name: str | None = None,
        timezone: str | None = None,
        conversation_policy: str | None = None,
        target_conversation_id: str | None = None,
        status: str | None = None,
        max_runs: int | None = None,
        end_at: str | None = None,
        auto_pause_after_failures: int | None = None,
    ) -> str:
        """修改定时计划。

        Args:
            schedule_id: 计划 UUID
            schedule_name: 计划名称（存在同名项时需要 ID）
            cron_expression: 新 cron 表达式
            interval_minutes: 新 interval 分钟数
            scheduled_at: 新单次执行时间
            message: 新执行消息
            name: 新计划名称
            timezone: 新 timezone
            conversation_policy: 新结果保存策略
            target_conversation_id: selected_conversation 策略使用的对话 ID
            status: 新状态
            max_runs: 新最大成功执行次数
            end_at: 新结束时间 ISO 8601
            auto_pause_after_failures: 新连续失败自动暂停阈值
        """
        async with ctx.session_factory() as session:
            trigger, error = await _resolve_trigger_for_write(
                ctx, session, schedule_id, schedule_name
            )
            if error or not trigger:
                return error or tr("schedule_not_found_0a71df")

            update_payload: dict[str, Any] = {}
            if cron_expression:
                update_payload["trigger_type"] = "cron"
                update_payload["schedule_config"] = {"cron_expression": cron_expression}
            if interval_minutes is not None:
                update_payload["trigger_type"] = "interval"
                update_payload["schedule_config"] = {"interval_minutes": interval_minutes}
            if scheduled_at:
                update_payload["trigger_type"] = "one_time"
                update_payload["schedule_config"] = {"scheduled_at": scheduled_at}
            if message:
                update_payload["input_message"] = message
            if name is not None:
                update_payload["name"] = name
            if timezone is not None:
                update_payload["timezone"] = timezone
            if conversation_policy is not None:
                update_payload["conversation_policy"] = conversation_policy
            if target_conversation_id is not None:
                update_payload["target_conversation_id"] = target_conversation_id
            if status is not None:
                update_payload["status"] = status
            if max_runs is not None:
                update_payload["max_runs"] = max_runs
            if end_at is not None:
                update_payload["end_at"] = end_at
            if auto_pause_after_failures is not None:
                update_payload["auto_pause_after_failures"] = auto_pause_after_failures
            try:
                update = TriggerUpdate.model_validate(update_payload)
                await trigger_service.update_trigger(session, trigger, update)
            except ValueError as exc:
                return tr("schedule_settings_are_incorrect_v_667184", v0=f"{exc}")
            return tr("schedule_modification_completed_7469cd")

    # ------ 16. delete_cron_schedule ------

    async def delete_cron_schedule(
        schedule_id: str | None = None,
        schedule_name: str | None = None,
    ) -> str:
        """删除定时计划。

        Args:
            schedule_id: 计划 UUID
            schedule_name: 计划名称
        """
        async with ctx.session_factory() as session:
            trigger, error = await _resolve_trigger_for_write(
                ctx, session, schedule_id, schedule_name
            )
            if error or not trigger:
                return error or tr("schedule_not_found_0a71df")
            await trigger_service.delete_trigger(session, trigger)
            return tr("schedule_deletion_completed_ec007b")

    # ------ 17. enable_cron_schedule ------

    async def enable_cron_schedule(
        schedule_id: str | None = None,
        schedule_name: str | None = None,
    ) -> str:
        """启用定时计划。

        Args:
            schedule_id: 计划 UUID
            schedule_name: 计划名称
        """
        async with ctx.session_factory() as session:
            trigger, error = await _resolve_trigger_for_write(
                ctx, session, schedule_id, schedule_name
            )
            if error or not trigger:
                return error or tr("schedule_not_found_0a71df")
            try:
                await trigger_service.update_trigger(
                    session,
                    trigger,
                    TriggerUpdate(status="active"),
                )
            except ValueError as exc:
                return tr("schedule_settings_are_incorrect_v_667184", v0=f"{exc}")
            return tr("schedule_activation_complete_60fc1e")

    # ------ 18. disable_cron_schedule ------

    async def disable_cron_schedule(
        schedule_id: str | None = None,
        schedule_name: str | None = None,
    ) -> str:
        """禁用定时计划。

        Args:
            schedule_id: 计划 UUID
            schedule_name: 计划名称
        """
        async with ctx.session_factory() as session:
            trigger, error = await _resolve_trigger_for_write(
                ctx, session, schedule_id, schedule_name
            )
            if error or not trigger:
                return error or tr("schedule_not_found_0a71df")
            await trigger_service.update_trigger(session, trigger, TriggerUpdate(status="paused"))
            return tr("schedule_deactivation_complete_b3350d")

    return [
        StructuredTool.from_function(
            coroutine=create_cron_schedule,
            name="create_cron_schedule",
            description=tr("create_cron_schedule_recurring_or_727ffd"),
        ),
        StructuredTool.from_function(
            coroutine=update_cron_schedule,
            name="update_cron_schedule",
            description=tr("edit_cron_schedule_cb2488"),
        ),
        StructuredTool.from_function(
            coroutine=delete_cron_schedule,
            name="delete_cron_schedule",
            description=tr("delete_cron_schedule_070739"),
        ),
        StructuredTool.from_function(
            coroutine=enable_cron_schedule,
            name="enable_cron_schedule",
            description=tr("activate_cron_schedule_6593d0"),
        ),
        StructuredTool.from_function(
            coroutine=disable_cron_schedule,
            name="disable_cron_schedule",
            description=tr("disable_cron_schedule_730ada"),
        ),
    ]
