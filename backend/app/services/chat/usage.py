"""Token usage persistence and model pricing lookup.

BE-S1 split from ``app.services.chat_service`` — pure move, no behavior
change. The ``_select`` alias is kept from the original deferred import so
the moved body stays byte-identical.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select as _select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.model import Model
from app.models.token_usage import TokenUsage


async def _resolve_agent_model_pricing(
    db: AsyncSession, conversation: Conversation
) -> tuple[float | None, float | None]:
    """W7-4 — 查询 conversation.agent.model 的 ``cost_per_*_token`` 单价。

    Decimal → float 转换。若 Agent/Model row 已消失或单价为 NULL，
    返回 ``(None, None)``。调用方（``langchain_messages_to_response``）收到 None
    时不填充 ``estimated_cost``。
    """
    result = await db.execute(
        _select(Model.cost_per_input_token, Model.cost_per_output_token)
        .join(Agent, Agent.model_id == Model.id)
        .where(Agent.id == conversation.agent_id)
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None, None
    cost_in, cost_out = row
    return (
        float(cost_in) if cost_in is not None else None,
        float(cost_out) if cost_out is not None else None,
    )


async def save_token_usage(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    agent_id: uuid.UUID,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    estimated_cost: float | None = None,
    run_id: uuid.UUID | None = None,
    commit: bool = True,
) -> TokenUsage:
    values = {
        "conversation_id": conversation_id,
        "agent_id": agent_id,
        "model_name": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "run_id": run_id,
    }
    if run_id is None:
        usage = TokenUsage(**values)
        db.add(usage)
        await db.flush()
    else:
        dialect_name = db.get_bind().dialect.name
        statement = (
            postgresql_insert(TokenUsage)
            if dialect_name == "postgresql"
            else sqlite_insert(TokenUsage)
        ).values(values)
        await db.execute(statement.on_conflict_do_nothing(index_elements=["run_id"]))
        usage = (
            await db.execute(_select(TokenUsage).where(TokenUsage.run_id == run_id))
        ).scalar_one()
    if commit:
        await db.commit()
    return usage
