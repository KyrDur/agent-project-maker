"""Per-user 隐藏 skill builder Agent lazy-seed（规范 AD-1）。

``runtime_profile='skill_builder'`` Agent row 在首次进入 builder 时创建。
面向用户的表面（列表/摘要/导航器/每日聚合等）通过 ``runtime_profile ==
'standard'`` 过滤隐藏该 row，PUT/DELETE 返回 enumeration-safe 404。

``model_id`` 只是 seed 时用于满足 FK 的引用值 — 运行时分支始终
通过 ``resolve_system_model(db, 'text_primary')`` 重新解析（ADR-019, M3）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AGENT_RUNTIME_PROFILE_SKILL_BUILDER, Agent
from app.models.model import Model
from app.services.system_credential_resolver import (
    SystemModelNotConfiguredError,
    resolve_system_model,
)

SKILL_BUILDER_AGENT_NAME = "技能培养者"

# 运行时会在 skill_builder profile 分支中替换为专用 prompt.md（M3），
# 因此 row 的 system_prompt 只是执行时不使用的占位符。
_PLACEHOLDER_PROMPT = (
    "Moldy hidden skill-builder agent. The runtime replaces this prompt "
    "for runtime_profile='skill_builder'; this stored value is never used."
)


async def get_or_create_skill_builder_agent(db: AsyncSession, user_id: uuid.UUID) -> Agent:
    """返回用户的隐藏 builder Agent（不存在则创建，仅 flush）。"""

    result = await db.execute(
        select(Agent)
        .where(
            Agent.user_id == user_id,
            Agent.runtime_profile == AGENT_RUNTIME_PROFILE_SKILL_BUILDER,
        )
        # 即使并发 seed 产生重复，也通过确定性排序始终选择同一个 row。
        .order_by(Agent.created_at.asc(), Agent.id.asc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    resolved = await resolve_system_model(db, "builder", user_id)
    agent = Agent(
        user_id=user_id,
        name=SKILL_BUILDER_AGENT_NAME,
        description="skill builder chat 专用隐藏 Agent",
        system_prompt=_PLACEHOLDER_PROMPT,
        model_id=await _seed_model_id(db, resolved.model_name),
        runtime_profile=AGENT_RUNTIME_PROFILE_SKILL_BUILDER,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _seed_model_id(db: AsyncSession, model_name: str) -> uuid.UUID:
    """用于满足 FK 的 model id — 优先选择与系统模型相同的 ``model_name``，否则取目录第一行。"""

    result = await db.execute(select(Model.id).where(Model.model_name == model_name).limit(1))
    model_id = result.scalar_one_or_none()
    if model_id is not None:
        return model_id
    result = await db.execute(
        select(Model.id).order_by(Model.created_at.asc(), Model.id.asc()).limit(1)
    )
    model_id = result.scalar_one_or_none()
    if model_id is None:
        # 若模型目录为空，System LLM setup 实质上未完成 —
        # 统一收敛到现有 SYSTEM_LLM_NOT_CONFIGURED 契约。
        raise SystemModelNotConfiguredError("builder")
    return model_id
