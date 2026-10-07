"""Builder 服务 — 会话管理、v3 消息流、confirm 逻辑。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_runtime.builder_i18n import get_locale, localized_stream, tr
from app.agent_runtime.identity import AGENT_IDENTITY_PER_USER, validate_identity_mode
from app.agent_runtime.middleware_registry import get_middleware_registry
from app.agent_runtime.streaming import format_sse
from app.database import async_session as async_session_factory
from app.models.agent import Agent
from app.models.builder_session import BuilderSession
from app.models.mcp_server import McpServer
from app.models.mcp_tool import AgentMcpToolLink, McpTool
from app.models.model import Model
from app.models.skill import AgentSkillLink, Skill
from app.models.tool import AgentToolLink, Tool
from app.schemas.builder import BuilderStatus
from app.schemas.conversation import Decision
from app.services.tool_service import get_tools_catalog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resume wire 适配器（router-only）— ADR-012
# ---------------------------------------------------------------------------


def decisions_to_builder_response(decisions: list[Decision]) -> Any:
    """标准 ``Decision[]`` → builder graph 期望的 native shape。

    builder v3 wait 节点处理 dict|str 响应
    （``parse_approval_response``、phase6 ``image_choice``/``image_approval``）。
    frontend 只保留标准 ``Decision[]`` wire，而转换为 builder native shape
    的责任由 router 边界的本 helper 以单一职责承担。

    Mapping:
    - ``approve`` → ``{"approved": True}``
    - ``reject`` → ``{"approved": False, "revision_message": message or ""}``
    - ``respond`` → ``message or ""`` (string)
    - ``edit`` → ``{"approved": True}`` (builder 不使用 edit args)
    - empty list → ``None``
    """
    if not decisions:
        return None
    first = decisions[0]
    if first.type == "approve":
        return {"approved": True}
    if first.type == "reject":
        return {"approved": False, "revision_message": first.message or ""}
    if first.type == "respond":
        return first.message or ""
    if first.type == "edit":
        # builder 不使用 edit — approve fallback（graph 行为相同）
        return {"approved": True}
    return None


# ---------------------------------------------------------------------------
# 会话 CRUD
# ---------------------------------------------------------------------------


async def create_session(db: AsyncSession, user_id: uuid.UUID, user_request: str) -> BuilderSession:
    """创建构建会话。"""
    session = BuilderSession(
        user_id=user_id,
        user_request=user_request,
        status=BuilderStatus.BUILDING,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> BuilderSession | None:
    result = await db.execute(
        select(BuilderSession).where(
            BuilderSession.id == session_id,
            BuilderSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 原子状态转换（防止重复进入）
# ---------------------------------------------------------------------------


async def claim_for_confirming(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """PREVIEW → CONFIRMING 原子转换。成功则返回 True。

    即使同时收到多个 confirm 请求，也只会有一个成功。
    """
    result = await db.execute(
        update(BuilderSession)
        .where(
            BuilderSession.id == session_id,
            BuilderSession.user_id == user_id,
            BuilderSession.status == BuilderStatus.PREVIEW,
        )
        .values(status=BuilderStatus.CONFIRMING)
    )
    await db.commit()
    return result.rowcount == 1  # type: ignore[return-value]


async def get_agent_by_id(db: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    """按 ID 查询 Agent（用于幂等 confirm 返回）。"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 查询目录（用于动态注入子 Agent，AD-7）
# ---------------------------------------------------------------------------


def _get_middlewares_catalog() -> list[dict[str, Any]]:
    """查询可用的中间件目录。

    排除 deepagents 自动添加的内置中间件，
    防止重复添加导致错误。
    """
    from app.catalog_i18n import middleware_display
    from app.services.builder_runtime_readiness import BUILDER_MIDDLEWARE_TYPES

    return [
        middleware_display(item, get_locale())
        for item in get_middleware_registry(exclude_builtin=True)
        if item["type"] in BUILDER_MIDDLEWARE_TYPES
    ]


# ---------------------------------------------------------------------------
# 查询模型（用于 v3 节点动态注入）
# ---------------------------------------------------------------------------


async def _get_default_model_name(db: AsyncSession, user_id: uuid.UUID | None = None) -> str:
    from app.services.builder_runtime_readiness import usable_bindings

    bindings = await usable_bindings(db, user_id) if user_id else []
    if len(bindings) == 1:
        model = bindings[0].model
        return f"{model.provider}:{model.model_name}"
    return ""


# ---------------------------------------------------------------------------
# 构建确认（confirm）— 复用 confirm_creation 逻辑
# ---------------------------------------------------------------------------


async def confirm_build(
    db: AsyncSession, session: BuilderSession, *, model_id: str | None = None
) -> Agent | None:
    """构建确认：基于 draft_config 创建实际 Agent。

    复用 agent_creation_service.confirm_creation() 的工具/模型匹配逻辑。
    发生异常时将会话回滚到 PREVIEW，防止卡死在 CONFIRMING。
    """
    await db.refresh(session, with_for_update=True)
    if session.status == BuilderStatus.COMPLETED and session.agent_id:
        return await get_agent_by_id(db, session.agent_id)
    config = session.draft_config
    if not config:
        return None

    created_skill_ids: list[uuid.UUID] = []
    consistency_review = None
    try:
        requirements = (session.intent or {}).get("project_requirements")
        if requirements:
            from app.exceptions import AppError
            from app.services.builder_consistency import draft_tools, review_configuration

            review_tools = await draft_tools(
                db, session.user_id, config, session.tools_result or []
            )
            consistency_review = await review_configuration(
                db,
                session.user_id,
                requirements,
                {
                    "system_prompt": config.get("system_prompt"),
                    "review_tools": [t.model_dump() for t in review_tools],
                },
                config.get("consistency_review"),
            )
            history = list(config.get("consistency_reviews") or [])
            if consistency_review is not config.get("consistency_review"):
                history.append(consistency_review)
            config = {
                **config,
                "consistency_review": consistency_review,
                "consistency_reviews": history,
            }
            session.draft_config = config
            if consistency_review["status"] != "approved":
                code = (
                    "builder_consistency_rejected"
                    if consistency_review["status"] == "rejected"
                    else "builder_consistency_unavailable"
                )
                raise AppError(code=code, message=tr(code), status=422)
        selected_model_id = model_id or config.get("runtime_model_id")
        runtime_source = config.get("runtime_model_source")
        binding = await _resolve_confirm_runtime_binding(
            db,
            session.user_id,
            str(selected_model_id) if selected_model_id else None,
            runtime_source=runtime_source if isinstance(runtime_source, str) else None,
        )
        model = binding.model

        # 条目匹配 — 按名称对 Tool / McpTool / Skill 做 3-way 分离查询
        tools_to_link, mcp_tools_to_link, skills_to_link = await _resolve_tools(
            db, session.user_id, config.get("tools", [])
        )
        from app.skills.service import create_text_skill

        for draft in config.get("generated_skills", []):
            skill_id = uuid.uuid5(session.id, "generated-skill:" + draft["tool_name"])
            was_present = await db.get(Skill, skill_id)
            if not was_present:
                created_skill_ids.append(skill_id)
            skill = await create_text_skill(
                db,
                user_id=session.user_id,
                name=draft["tool_name"],
                slug=draft["tool_name"],
                description=draft.get("description"),
                content=draft["content"],
                version="1",
                skill_id=skill_id,
            )
            skills_to_link.append(skill)
        resolved_names = {
            item.name.lower() for item in [*tools_to_link, *mcp_tools_to_link, *skills_to_link]
        }
        if any(name.lower() not in resolved_names for name in config.get("tools", [])):
            from app.exceptions import AppError

            raise AppError(
                code="builder_tool_unavailable", message=tr("builder_tool_unavailable"), status=422
            )

        from app.services.builder_runtime_readiness import validate_tools

        await validate_tools(db, session.user_id, tools_to_link)

        from app.services.agent_project_executor import snapshot_middlewares

        snapshot_middlewares(
            {
                "middleware_configs": [
                    {"type": name, "params": {}} for name in config.get("middlewares", [])
                ]
            }
        )
        # 创建 Agent
        agent = Agent(
            user_id=session.user_id,
            name=config.get("name") or tr("new_agent_265674"),
            description=config.get("description", ""),
            system_prompt=config.get("system_prompt", ""),
            model_id=model.id,
            llm_credential_id=binding.credential.id,
            identity_mode=validate_identity_mode(
                config.get("identity_mode") or AGENT_IDENTITY_PER_USER
            ),
            middleware_configs=[
                {"type": mw_name, "params": {}} for mw_name in config.get("middlewares", [])
            ],
        )
        agent.tool_links = [AgentToolLink(tool_id=t.id) for t in tools_to_link]
        agent.mcp_tool_links = [AgentMcpToolLink(mcp_tool_id=mt.id) for mt in mcp_tools_to_link]
        agent.skill_links = [AgentSkillLink(skill_id=s.id) for s in skills_to_link]
        db.add(agent)
        await db.flush()  # 为分配 agent.id 需要 flush

        session.status = BuilderStatus.COMPLETED
        session.agent_id = agent.id

        from app.services import agent_project_service, builder_project_lifecycle

        await agent_project_service.create_project(db, agent.id, session.user_id)
        builder_project_lifecycle.schedule(agent.id, session.user_id)
        await db.refresh(agent, ["model", "tool_links"])

        # 图片处理：phase7_save 始终显式 set draft_config["image_url"]。
        #   truthy → 将临时文件移动到 Agent 目录
        #   None/falsy → 用户在 phase6 中显式 skip
        image_url = (config or {}).get("image_url")
        if image_url:
            await _transfer_builder_image(session, agent, image_url)
            # 将 agent.image_path 的更改反映到 DB
            await db.commit()
            await db.refresh(agent)

        # 图片生成 commit 后关系会 expire，因此通过 selectinload 重新加载
        result = await db.execute(
            select(Agent)
            .where(Agent.id == agent.id)
            .options(
                selectinload(Agent.model),
                selectinload(Agent.llm_credential),
                selectinload(Agent.tool_links).selectinload(AgentToolLink.tool),
                selectinload(Agent.mcp_tool_links).selectinload(AgentMcpToolLink.mcp_tool),
                selectinload(Agent.skill_links).selectinload(AgentSkillLink.skill),
            )
        )
        return result.scalar_one()
    except Exception:
        # 防止 CONFIRMING 卡死：发生异常时回滚到 PREVIEW
        await db.rollback()
        await db.refresh(session)
        if session.status == BuilderStatus.COMPLETED and session.agent_id:
            logger.exception("Post-build work failed; preserving completed Agent and Project")
            return await get_agent_by_id(db, session.agent_id)
        # 只清理本次尚未提交的生成文件；不删除已有指南或已完成的 Agent。
        import shutil

        from app.skills.service import _skill_root

        for skill_id in created_skill_ids:
            if await db.get(Skill, skill_id) is None:
                shutil.rmtree(_skill_root(skill_id), ignore_errors=True)
        session.status = BuilderStatus.PREVIEW
        if consistency_review is not None:
            session.draft_config = {
                **(session.draft_config or {}),
                "consistency_review": consistency_review,
                "consistency_reviews": config.get("consistency_reviews", []),
            }
        await db.commit()
        raise


async def get_builder_personal_bindings(
    db: AsyncSession,
    user_id: uuid.UUID,
):
    """Expose personal Builder runtime bindings through the service facade."""

    from app.services.builder_runtime_readiness import usable_bindings

    return await usable_bindings(db, user_id)


async def get_builder_system_runtime(db: AsyncSession, user_id: uuid.UUID | None = None):
    """Return the owner-selected Builder runtime as a model/credential binding."""

    from app.credentials import service as credential_service
    from app.exceptions import AppError
    from app.services.builder_runtime_readiness import RuntimeBinding
    from app.services.system_credential_resolver import (
        SystemModelNotConfiguredError,
        get_effective_setting,
    )

    try:
        _, setting = await get_effective_setting(db, "builder", user_id)
    except SystemModelNotConfiguredError:
        setting = None
    if setting is None or setting.credential_id is None or not setting.model_name:
        raise AppError(
            code="builder_runtime_setup",
            message=tr("builder_runtime_setup"),
            status=422,
        )
    credential = await credential_service.get_for_user(db, setting.credential_id, setting.user_id)
    if credential is None or credential.status != "active":
        raise AppError(
            code="builder_runtime_setup",
            message=tr("builder_runtime_setup"),
            status=422,
        )

    payload = await credential_service.decrypt_with_external(credential.data_encrypted)
    if not (payload.get("api_key") or payload.get("token")):
        raise AppError(
            code="builder_runtime_setup", message=tr("builder_runtime_setup"), status=422
        )
    base_url = payload.get("base_url") or None
    result = await db.execute(
        select(Model).where(
            Model.provider == credential.definition_key,
            Model.model_name == setting.model_name,
            Model.base_url == base_url,
        )
    )
    model = result.scalars().first()
    if model is None:
        model = Model(
            provider=credential.definition_key,
            model_name=setting.model_name,
            display_name=setting.model_name,
            base_url=base_url,
            is_visible=True,
        )
        db.add(model)
        await db.flush()
    return RuntimeBinding(model=model, credential=credential)


async def _resolve_confirm_runtime_binding(
    db: AsyncSession,
    user_id: uuid.UUID,
    selected_model_id: str | None,
    *,
    runtime_source: str | None,
):
    from app.exceptions import AppError
    from app.services.builder_runtime_readiness import require_binding

    if runtime_source == "system_builder":
        return await get_builder_system_runtime(db, user_id)
    try:
        return await require_binding(db, user_id, selected_model_id)
    except AppError:
        if selected_model_id:
            raise
        return await get_builder_system_runtime(db, user_id)


async def _resolve_tools(
    db: AsyncSession,
    user_id: uuid.UUID,
    tool_names: list[str],
) -> tuple[list[Tool], list[McpTool], list[Skill]]:
    """名称列表 → (Tool, McpTool, Skill) 3-way 分离返回。

    Builder phase3 目录（``get_tools_catalog``）会展示 ``Tool`` + ``McpTool`` +
    ``Skill``，因此 phase8 confirm 也必须匹配这三张表。

    匹配优先级为 ``Tool > McpTool > Skill``。若多个表中存在同名项，
    选择注册更明确的一侧（Tool 优先）。``McpTool`` 使用
    ``McpServer.user_id`` ownership 过滤，``Skill`` 使用 ``Skill.user_id``
    ownership 过滤，以阻止 cross-user 链接。
    """
    if not tool_names:
        return [], [], []
    lower_names = [n.lower() for n in tool_names]

    tool_result = await db.execute(
        select(Tool).where(
            Tool.visible_to(user_id),
            func.lower(Tool.name).in_(lower_names),
        )
    )
    tools = list(tool_result.scalars().all())
    matched = {t.name.lower() for t in tools}

    remaining = [n for n in lower_names if n not in matched]
    if not remaining:
        return tools, [], []

    mcp_result = await db.execute(
        select(McpTool)
        .join(McpServer, McpServer.id == McpTool.server_id)
        .where(
            McpServer.user_id == user_id,
            func.lower(McpTool.name).in_(remaining),
        )
    )
    mcp_tools = list(mcp_result.scalars().all())
    matched.update(mt.name.lower() for mt in mcp_tools)

    remaining = [n for n in remaining if n not in matched]
    if not remaining:
        return tools, mcp_tools, []

    skill_result = await db.execute(
        select(Skill).where(
            Skill.user_id == user_id,
            func.lower(Skill.name).in_(remaining),
        )
    )
    skills = list(skill_result.scalars().all())
    return tools, mcp_tools, skills


# ---------------------------------------------------------------------------
# Builder v3 — 基于 StateGraph 的消息流式传输
# ---------------------------------------------------------------------------


def _transfer_builder_image_sync(
    session_id: uuid.UUID,
    agent_id: uuid.UUID,
    public_url: str,
) -> str | None:
    """Sync I/O — copy file + cleanup builder temp dir. 通过 asyncio.to_thread 调用。

    Returns: agent.image_path 值（None 表示失败）。
    """
    import shutil
    from pathlib import Path

    from app.agent_runtime.builder_v3.image_gen import resolve_local_path
    from app.services.agent_image_paths import agent_image_dir

    filename = Path(public_url).name
    src = resolve_local_path(str(session_id), filename)
    if not src:
        logger.warning("Builder image source not found: %s", public_url)
        return None

    dest_dir = agent_image_dir() / str(agent_id)
    dest = dest_dir / f"avatar{src.suffix}"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # 直接 copy — 文件消失时按 FileNotFoundError 处理（TOCTOU 防护）
        shutil.copy(src, dest)
    except FileNotFoundError:
        logger.warning("Builder image disappeared before copy: %s", src)
        return None
    except Exception:
        logger.warning("Builder image transfer failed", exc_info=True)
        return None

    # Cleanup: builder temp dir 清理（失败也忽略）
    builder_dir = src.parent
    if builder_dir.name == str(session_id):
        shutil.rmtree(builder_dir, ignore_errors=True)

    return str(dest)


async def _transfer_builder_image(
    session: BuilderSession,
    agent: Agent,
    public_url: str,
) -> None:
    """Phase 6 临时图片 → 复制到 Agent 目录（async wrapper）。

    即使失败也保留 Agent 创建结果。
    """
    result = await asyncio.to_thread(_transfer_builder_image_sync, session.id, agent.id, public_url)
    if result:
        agent.image_path = result


@localized_stream
async def run_v3_message_stream(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    content: str,
    *,
    locale: str = "zh-CN",
) -> AsyncGenerator[str, None]:
    """通过 Builder v3 StateGraph 流式传输消息。

    - 第一条消息：从 inject 目录/模型/会话信息的 full state 开始
    - 后续消息：只追加 messages（state 从 checkpoint 恢复）
    """
    from langchain_core.messages import HumanMessage

    from app.agent_runtime.builder_v3.graph import compile_graph
    from app.agent_runtime.builder_v3.state import initial_todos
    from app.agent_runtime.checkpointer import get_checkpointer
    from app.agent_runtime.streaming import stream_agent_response

    async with async_session_factory() as db:
        catalog = await get_tools_catalog(db, user_id)
        text_skill_ids = {
            str(skill_id)
            for skill_id in await db.scalars(
                select(Skill.id).where(Skill.user_id == user_id, Skill.kind == "text")
            )
        }
        tools_catalog = [
            item
            for item in catalog
            if item.get("kind") == "skill" and item.get("id") in text_skill_ids
        ]
        default_model_name = await _get_default_model_name(db, user_id)
        middlewares_catalog = _get_middlewares_catalog()

    checkpointer = get_checkpointer()
    graph_compiled = compile_graph(checkpointer)
    config: dict[str, Any] = {
        "configurable": {"thread_id": str(session_id), "ui_locale": get_locale()}
    }

    state_snapshot = await graph_compiled.aget_state(config)
    is_first = not state_snapshot.values

    if is_first:
        graph_input: Any = {
            "messages": [HumanMessage(content=content)],
            "user_id": str(user_id),
            "session_id": str(session_id),
            "user_request": content,
            "tools_catalog": tools_catalog,
            "middlewares_catalog": middlewares_catalog,
            "default_model_name": default_model_name,
            "current_phase": 1,
            "todos": initial_todos(),
        }
    else:
        graph_input = [HumanMessage(content=content)]

    from app.agent_runtime.builder_v3.consistency_context import builder_consistency_scope
    from app.services.builder_consistency import BuilderReviewService

    with builder_consistency_scope(BuilderReviewService(async_session_factory)):
        async for chunk in stream_agent_response(graph_compiled, graph_input, config):
            yield chunk


class StaleInterruptError(Exception):
    """resume 与当前 paused interrupt 不匹配（点击了 stale 卡片）。"""


@localized_stream
async def run_v3_resume_stream(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    response: Any,
    interrupt_id: str | None = None,
    *,
    locale: str = "zh-CN",
) -> AsyncGenerator[str, None]:
    """接收 interrupt 响应并通过 Command(resume=...) 恢复 graph。

    若提供 interrupt_id，则与当前 paused interrupt 的 ns 比较，阻止 stale 卡片导致的
    误用。若为 None，则 skip 验证（backward compatibility）。
    """
    from langgraph.types import Command

    from app.agent_runtime.builder_v3.graph import compile_graph
    from app.agent_runtime.checkpointer import get_checkpointer
    from app.agent_runtime.streaming import stream_agent_response

    checkpointer = get_checkpointer()
    graph_compiled = compile_graph(checkpointer)
    config: dict[str, Any] = {
        "configurable": {"thread_id": str(session_id), "ui_locale": get_locale()}
    }

    # interrupt_id stale 验证
    if interrupt_id:
        try:
            state = await graph_compiled.aget_state(config)
            current_ids: list[str] = []
            for task in state.tasks or []:
                for intr in task.interrupts or []:
                    current_ids.append(str(getattr(intr, "ns", "")))
            if current_ids and interrupt_id not in current_ids:
                # stale interrupt — 告知用户，graph 不恢复
                logger.warning(
                    "Stale interrupt resume rejected. expected=%s got=%s",
                    current_ids,
                    interrupt_id,
                )
                yield format_sse("message_start", {"id": "stale", "role": "assistant"})
                yield format_sse(
                    "error",
                    {"message": (tr("this_card_has_already_been_adc634"))},
                )
                yield format_sse("message_end", {"usage": {}, "content": ""})
                return
        except Exception:  # pragma: no cover
            logger.warning("interrupt_id validation failed", exc_info=True)

    from app.agent_runtime.builder_v3.consistency_context import builder_consistency_scope
    from app.services.builder_consistency import BuilderReviewService

    with builder_consistency_scope(BuilderReviewService(async_session_factory)):
        async for chunk in stream_agent_response(graph_compiled, Command(resume=response), config):
            yield chunk
