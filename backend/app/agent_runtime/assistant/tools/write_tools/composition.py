"""Assistant 写入工具 — 配置组（中间件/子智能体/技能 add/remove）。"""

from __future__ import annotations

import uuid

from langchain_core.tools import StructuredTool
from sqlalchemy import func, select

from app.agent_runtime.assistant.tools.write_tools.context import (
    WriteToolContext,
    get_agent_with_session,
)
from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.middleware_registry import MIDDLEWARE_REGISTRY
from app.models.agent import AGENT_RUNTIME_PROFILE_STANDARD, Agent
from app.models.agent_subagent import AgentSubAgentLink
from app.models.skill import AgentSkillLink, Skill


def build_composition_tools(ctx: WriteToolContext) -> list[StructuredTool]:
    """创建 6 个中间件/子智能体/技能配置工具。"""

    # ------ 3. add_middleware_to_agent ------

    async def add_middleware_to_agent(middleware_names: list[str]) -> str:
        """向智能体添加中间件（支持批量）。

        Args:
            middleware_names: 要添加的中间件 type 键列表
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            configs = list(agent.middleware_configs or [])
            existing = {mc.get("type", "").lower() for mc in configs}
            added = []
            for name in middleware_names:
                if name.lower() in existing:
                    continue
                if name not in MIDDLEWARE_REGISTRY:
                    continue
                configs.append({"type": name, "params": {}})
                added.append(name)

            if not added:
                return tr("there_is_no_middleware_to_282033")

            agent.middleware_configs = configs
            await session.commit()
            return tr("middleware_added_v_0215d4", v0=f"{', '.join(added)}")

    # ------ 4. remove_middleware_from_agent ------

    async def remove_middleware_from_agent(middleware_names: list[str]) -> str:
        """从智能体移除中间件（支持批量）。

        Args:
            middleware_names: 要移除的中间件 type 键列表
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            lower_names = {n.lower() for n in middleware_names}
            configs = list(agent.middleware_configs or [])
            removed = []
            new_configs = []
            for mc in configs:
                if mc.get("type", "").lower() in lower_names:
                    removed.append(mc.get("type", ""))
                else:
                    new_configs.append(mc)

            if not removed:
                return tr("no_such_middleware_v_a133a9", v0=f"{', '.join(middleware_names)}")

            agent.middleware_configs = new_configs
            await session.commit()
            return tr("middleware_removal_complete_v_3710ac", v0=f"{', '.join(removed)}")

    # ------ 5. add_subagent_to_agent ------

    async def add_subagent_to_agent(agent_ids: list[str]) -> str:
        """向智能体添加子智能体（支持批量）。

        Args:
            agent_ids: 要添加的子智能体 UUID 列表（字符串）
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            existing_ids = {link.sub_agent_id for link in agent.sub_agent_links}
            added: list[str] = []
            skipped: list[str] = []

            # 第 1 次解析：UUID 转换 + 立即分类自引用/重复项
            candidates: dict[uuid.UUID, str] = {}  # uuid → raw_id（待校验对象）
            for raw_id in agent_ids:
                try:
                    sid = uuid.UUID(raw_id)
                except (ValueError, TypeError):
                    skipped.append(tr("v_invalid_uuid_88b951", v0=f"{raw_id}"))
                    continue
                if sid == agent.id:
                    skipped.append(tr("v_self_referenced_e4701d", v0=f"{raw_id}"))
                    continue
                if sid in existing_ids:
                    skipped.append(tr("v_already_added_877a78", v0=f"{raw_id}"))
                    continue
                candidates[sid] = raw_id

            # 第 2 次批量校验：通过单个 IN 查询确认所有权（移除 N+1）
            name_by_id: dict[uuid.UUID, str] = {}
            if candidates:
                result = await session.execute(
                    select(Agent.id, Agent.name).where(
                        Agent.id.in_(candidates.keys()),
                        Agent.user_id == ctx.user_id,
                        # 隐藏运行时智能体不能连接为子智能体。
                        Agent.runtime_profile == AGENT_RUNTIME_PROFILE_STANDARD,
                    )
                )
                name_by_id = {row.id: row.name for row in result.all()}

            # 第 3 次 append（仅限校验通过项）
            next_pos = max((link.position for link in agent.sub_agent_links), default=-1) + 1
            for sid, raw_id in candidates.items():
                if sid not in name_by_id:
                    skipped.append(tr("v_not_found_38c16e", v0=f"{raw_id}"))
                    continue
                agent.sub_agent_links.append(AgentSubAgentLink(sub_agent_id=sid, position=next_pos))
                existing_ids.add(sid)
                added.append(name_by_id[sid])
                next_pos += 1

            if not added and not skipped:
                return tr("there_are_no_subagents_to_9d2716")

            if added:
                await session.commit()

            parts = []
            if added:
                parts.append(tr("added_v_e0abab", v0=f"{', '.join(added)}"))
            if skipped:
                parts.append(tr("skip_v_7a10fe", v0=f"{', '.join(skipped)}"))
            return " | ".join(parts)

    # ------ 6. remove_subagent_from_agent ------

    async def remove_subagent_from_agent(agent_ids: list[str]) -> str:
        """从智能体移除子智能体（支持批量）。

        Args:
            agent_ids: 要移除的子智能体 UUID 列表（字符串）
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            target_ids: set[uuid.UUID] = set()
            invalid: list[str] = []
            for raw_id in agent_ids:
                try:
                    target_ids.add(uuid.UUID(raw_id))
                except (ValueError, TypeError):
                    invalid.append(raw_id)

            removed: list[str] = []
            for link in list(agent.sub_agent_links):
                if link.sub_agent_id in target_ids:
                    removed.append(link.sub_agent.name)
                    await session.delete(link)

            if not removed:
                msg = tr("the_subagent_does_not_exist_532127")
                if invalid:
                    msg += tr("invalid_id_v_84b95e", v0=f"{', '.join(invalid)}")
                return msg

            await session.commit()
            result_msg = tr("subagent_removal_completed_v_868fc6", v0=f"{', '.join(removed)}")
            if invalid:
                result_msg += tr("invalid_id_skipping_v_2db2cf", v0=f"{', '.join(invalid)}")
            return result_msg

    # ------ 6-2. add_skill_to_agent ------

    async def add_skill_to_agent(skill_names: list[str]) -> str:
        """向智能体添加技能（支持批量）。

        Args:
            skill_names: 要添加的技能名称列表（匹配 Skill.name）
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            existing = {link.skill.name.lower() for link in agent.skill_links}
            lower_names = [n.lower() for n in skill_names if n.lower() not in existing]
            if not lower_names:
                return tr("all_skills_have_already_been_056dc5")

            result = await session.execute(
                select(Skill)
                .where(
                    Skill.user_id == ctx.user_id,
                    func.lower(Skill.name).in_(lower_names),
                )
                .order_by(Skill.created_at.asc())
            )
            # 存在多个同名 skill 时，只采用最先创建的 1 个（per name dedupe）
            unique_by_name: dict[str, Skill] = {}
            for s in result.scalars().all():
                key = s.name.lower()
                if key not in unique_by_name:
                    unique_by_name[key] = s
            found_skills = list(unique_by_name.values())
            if not found_skills:
                return tr("skill_not_found_v_59d909", v0=f"{', '.join(skill_names)}")

            for s in found_skills:
                agent.skill_links.append(AgentSkillLink(skill_id=s.id))
            await session.commit()

            added = [s.name for s in found_skills]
            found_lower = {s.name.lower() for s in found_skills}
            missing = [
                n for n in skill_names if n.lower() not in found_lower and n.lower() not in existing
            ]
            msg = tr("skill_added_v_966f7f", v0=f"{', '.join(added)}")
            if missing:
                msg += tr("skip_nonexistent_v_0c62ec", v0=f"{', '.join(missing)}")
            return msg

    # ------ 6-3. remove_skill_from_agent ------

    async def remove_skill_from_agent(skill_names: list[str]) -> str:
        """从智能体移除技能（支持批量）。

        Args:
            skill_names: 要移除的技能名称列表（匹配 Skill.name）
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            lower_names = {n.lower() for n in skill_names}
            removed: list[str] = []
            for link in list(agent.skill_links):
                if link.skill.name.lower() in lower_names:
                    removed.append(link.skill.name)
                    await session.delete(link)
            if not removed:
                return tr("the_skill_does_not_exist_50a929", v0=f"{', '.join(skill_names)}")

            await session.commit()
            return tr("skill_removed_v_911593", v0=f"{', '.join(removed)}")

    return [
        StructuredTool.from_function(
            coroutine=add_middleware_to_agent,
            name="add_middleware_to_agent",
            description=tr("add_middleware_deployment_to_agent_f714aa"),
        ),
        StructuredTool.from_function(
            coroutine=remove_middleware_from_agent,
            name="remove_middleware_from_agent",
            description=tr("remove_middleware_deployment_from_agent_bb3b35"),
        ),
        StructuredTool.from_function(
            coroutine=add_subagent_to_agent,
            name="add_subagent_to_agent",
            description=tr("add_subagent_placement_to_agent_bd94a3"),
        ),
        StructuredTool.from_function(
            coroutine=remove_subagent_from_agent,
            name="remove_subagent_from_agent",
            description=tr("remove_subagent_deployment_from_agent_544fb1"),
        ),
        StructuredTool.from_function(
            coroutine=add_skill_to_agent,
            name="add_skill_to_agent",
            description=tr("add_skill_placement_to_agent_6135d1"),
        ),
        StructuredTool.from_function(
            coroutine=remove_skill_from_agent,
            name="remove_skill_from_agent",
            description=tr("remove_skill_placement_from_agent_e4feaf"),
        ),
    ]
