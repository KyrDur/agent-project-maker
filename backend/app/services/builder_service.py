"""Builder 서비스 — 세션 관리, v3 메시지 스트리밍, confirm 로직."""

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
# Resume wire 어댑터 (router-only) — ADR-012
# ---------------------------------------------------------------------------


def decisions_to_builder_response(decisions: list[Decision]) -> Any:
    """표준 ``Decision[]`` → builder graph 가 기대하는 native shape.

    builder v3 wait 노드들은 dict|str 응답을 처리한다
    (``parse_approval_response``, phase6 ``image_choice``/``image_approval``).
    frontend 는 표준 ``Decision[]`` wire 만 유지하고, builder native shape 으로
    의 변환 책임은 router 경계의 본 helper 가 단일 책임으로 흡수한다.

    Mapping:
    - ``approve`` → ``{"approved": True}``
    - ``reject`` → ``{"approved": False, "revision_message": message or ""}``
    - ``respond`` → ``message or ""`` (string)
    - ``edit`` → ``{"approved": True}`` (builder 는 edit args 를 사용하지 않음)
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
        # builder edit 미사용 — approve fallback (graph 행동은 동일)
        return {"approved": True}
    return None


# ---------------------------------------------------------------------------
# 세션 CRUD
# ---------------------------------------------------------------------------


async def create_session(db: AsyncSession, user_id: uuid.UUID, user_request: str) -> BuilderSession:
    """빌드 세션을 생성한다."""
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
# 원자적 상태 전환 (재진입 방지)
# ---------------------------------------------------------------------------


async def claim_for_confirming(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """PREVIEW → CONFIRMING 원자적 전환. 성공하면 True.

    동시 confirm 요청이 오더라도 하나만 성공한다.
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
    """Agent를 ID로 조회한다 (멱등 confirm 반환용)."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 카탈로그 조회 (서브에이전트 동적 주입용, AD-7)
# ---------------------------------------------------------------------------


def _get_middlewares_catalog() -> list[dict[str, Any]]:
    """사용 가능한 미들웨어 카탈로그를 조회한다.

    deepagents가 자동 추가하는 빌트인 미들웨어는 제외하여
    중복 추가로 인한 오류를 방지한다.
    """
    from app.catalog_i18n import middleware_display
    from app.services.builder_runtime_readiness import BUILDER_MIDDLEWARE_TYPES

    return [
        middleware_display(item, get_locale())
        for item in get_middleware_registry(exclude_builtin=True)
        if item["type"] in BUILDER_MIDDLEWARE_TYPES
    ]


# ---------------------------------------------------------------------------
# 모델 조회 (v3 노드 동적 주입용)
# ---------------------------------------------------------------------------


async def _get_default_model_name(db: AsyncSession, user_id: uuid.UUID | None = None) -> str:
    from app.services.builder_runtime_readiness import usable_bindings

    bindings = await usable_bindings(db, user_id) if user_id else []
    if len(bindings) == 1:
        model = bindings[0].model
        return f"{model.provider}:{model.model_name}"
    return ""


# ---------------------------------------------------------------------------
# 빌드 확인 (confirm) — confirm_creation 로직 재사용
# ---------------------------------------------------------------------------


async def confirm_build(
    db: AsyncSession, session: BuilderSession, *, model_id: str | None = None
) -> Agent | None:
    """빌드 확인: draft_config를 기반으로 실제 Agent를 생성한다.

    agent_creation_service.confirm_creation()의 도구/모델 매칭 로직을 재사용.
    예외 발생 시 세션을 PREVIEW로 롤백하여 CONFIRMING 고착을 방지한다.
    """
    await db.refresh(session, with_for_update=True)
    if session.status == BuilderStatus.COMPLETED and session.agent_id:
        return await get_agent_by_id(db, session.agent_id)
    config = session.draft_config
    if not config:
        return None

    try:
        selected_model_id = model_id or config.get("runtime_model_id")
        runtime_source = config.get("runtime_model_source")
        binding = await _resolve_confirm_runtime_binding(
            db,
            session.user_id,
            str(selected_model_id) if selected_model_id else None,
            runtime_source=runtime_source if isinstance(runtime_source, str) else None,
        )
        model = binding.model

        # 항목 매칭 — 이름으로 Tool / McpTool / Skill 3-way 분리 조회
        tools_to_link, mcp_tools_to_link, skills_to_link = await _resolve_tools(
            db, session.user_id, config.get("tools", [])
        )
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
        # 에이전트 생성
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
        await db.flush()  # agent.id 할당을 위해 flush 필요

        session.status = BuilderStatus.COMPLETED
        session.agent_id = agent.id

        from app.services import agent_project_service, builder_project_lifecycle

        await agent_project_service.create_project(db, agent.id, session.user_id)
        builder_project_lifecycle.schedule(agent.id, session.user_id)
        await db.refresh(agent, ["model", "tool_links"])

        # 이미지 처리: phase7_save가 draft_config["image_url"]을 항상 명시적으로 set.
        #   truthy → 임시 파일을 Agent 디렉토리로 이동
        #   None/falsy → 사용자가 phase6에서 명시적 skip
        image_url = (config or {}).get("image_url")
        if image_url:
            await _transfer_builder_image(session, agent, image_url)
            # agent.image_path 변경을 DB에 반영
            await db.commit()
            await db.refresh(agent)

        # 이미지 생성이 commit하면 관계가 expire되므로 selectinload로 재로드
        result = await db.execute(
            select(Agent)
            .where(Agent.id == agent.id)
            .options(
                selectinload(Agent.model),
                selectinload(Agent.tool_links).selectinload(AgentToolLink.tool),
                selectinload(Agent.mcp_tool_links).selectinload(AgentMcpToolLink.mcp_tool),
                selectinload(Agent.skill_links).selectinload(AgentSkillLink.skill),
            )
        )
        return result.scalar_one()
    except Exception:
        # CONFIRMING 고착 방지: 예외 발생 시 PREVIEW로 롤백
        await db.rollback()
        await db.refresh(session)
        if session.status == BuilderStatus.COMPLETED and session.agent_id:
            logger.exception("Post-build work failed; preserving completed Agent and Project")
            return await get_agent_by_id(db, session.agent_id)
        session.status = BuilderStatus.PREVIEW
        await db.commit()
        raise


async def get_builder_personal_bindings(
    db: AsyncSession,
    user_id: uuid.UUID,
):
    """Expose personal Builder runtime bindings through the service facade."""

    from app.services.builder_runtime_readiness import usable_bindings

    return await usable_bindings(db, user_id)


async def get_builder_system_runtime(db: AsyncSession):
    """Return the operator-selected Builder runtime as a model/credential binding."""

    from app.credentials import service as credential_service
    from app.exceptions import AppError
    from app.services.builder_runtime_readiness import RuntimeBinding
    from app.services.system_credential_resolver import get_effective_setting

    _, setting = await get_effective_setting(db, "builder")
    if setting is None or setting.credential_id is None or not setting.model_name:
        raise AppError(
            code="builder_runtime_setup",
            message=tr("builder_runtime_setup"),
            status=422,
        )
    credential = await credential_service.get_system(db, setting.credential_id)
    if credential is None:
        raise AppError(
            code="builder_runtime_setup",
            message=tr("builder_runtime_setup"),
            status=422,
        )

    result = await db.execute(
        select(Model).where(
            Model.provider == credential.definition_key,
            Model.model_name == setting.model_name,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        model = Model(
            provider=credential.definition_key,
            model_name=setting.model_name,
            display_name=setting.model_name,
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
        return await get_builder_system_runtime(db)
    try:
        return await require_binding(db, user_id, selected_model_id)
    except AppError:
        if selected_model_id:
            raise
        return await get_builder_system_runtime(db)


async def _resolve_tools(
    db: AsyncSession,
    user_id: uuid.UUID,
    tool_names: list[str],
) -> tuple[list[Tool], list[McpTool], list[Skill]]:
    """이름 목록 → (Tool, McpTool, Skill) 3-way 분리 반환.

    Builder phase3 카탈로그 (``get_tools_catalog``) 는 ``Tool`` + ``McpTool`` +
    ``Skill`` 모두 노출하므로 phase8 confirm 도 세 테이블을 모두 매칭해야 한다.

    매칭 우선순위는 ``Tool > McpTool > Skill``. 같은 이름이 여러 테이블에
    있으면 더 명시적으로 등록된 쪽 (Tool 우선) 을 선택. ``McpTool`` 은
    ``McpServer.user_id`` ownership 필터, ``Skill`` 은 ``Skill.user_id``
    ownership 필터로 cross-user 링킹 차단.
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
# Builder v3 — StateGraph 기반 메시지 스트리밍
# ---------------------------------------------------------------------------


def _transfer_builder_image_sync(
    session_id: uuid.UUID,
    agent_id: uuid.UUID,
    public_url: str,
) -> str | None:
    """Sync I/O — copy file + cleanup builder temp dir. asyncio.to_thread로 호출.

    Returns: agent.image_path 값 (None이면 실패).
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
        # 직접 copy — 파일 사라지면 FileNotFoundError로 처리 (TOCTOU 방어)
        shutil.copy(src, dest)
    except FileNotFoundError:
        logger.warning("Builder image disappeared before copy: %s", src)
        return None
    except Exception:
        logger.warning("Builder image transfer failed", exc_info=True)
        return None

    # Cleanup: builder temp dir 정리 (실패해도 무시)
    builder_dir = src.parent
    if builder_dir.name == str(session_id):
        shutil.rmtree(builder_dir, ignore_errors=True)

    return str(dest)


async def _transfer_builder_image(
    session: BuilderSession,
    agent: Agent,
    public_url: str,
) -> None:
    """Phase 6 임시 이미지 → Agent 디렉토리 복사 (async wrapper).

    실패해도 Agent 생성은 유지한다.
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
    """Builder v3 StateGraph로 메시지를 스트리밍한다.

    - 첫 메시지: 카탈로그/모델/세션 정보를 inject한 full state로 시작
    - 후속 메시지: messages만 추가 (state는 checkpoint에서 복원)
    """
    from langchain_core.messages import HumanMessage

    from app.agent_runtime.builder_v3.graph import compile_graph
    from app.agent_runtime.builder_v3.state import initial_todos
    from app.agent_runtime.checkpointer import get_checkpointer
    from app.agent_runtime.streaming import stream_agent_response

    async with async_session_factory() as db:
        tools_catalog = await get_tools_catalog(db, user_id)
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

    async for chunk in stream_agent_response(graph_compiled, graph_input, config):
        yield chunk


class StaleInterruptError(Exception):
    """resume이 현재 paused interrupt와 매칭되지 않음 (stale 카드 클릭)."""


@localized_stream
async def run_v3_resume_stream(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    response: Any,
    interrupt_id: str | None = None,
    *,
    locale: str = "zh-CN",
) -> AsyncGenerator[str, None]:
    """interrupt 응답을 받아 Command(resume=...)로 그래프를 재개한다.

    interrupt_id가 제공되면 현재 paused interrupt의 ns와 비교하여 stale 카드로 인한
    오용을 차단한다. None이면 검증 skip (backward compatibility).
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

    # interrupt_id stale 검증
    if interrupt_id:
        try:
            state = await graph_compiled.aget_state(config)
            current_ids: list[str] = []
            for task in state.tasks or []:
                for intr in task.interrupts or []:
                    current_ids.append(str(getattr(intr, "ns", "")))
            if current_ids and interrupt_id not in current_ids:
                # stale interrupt — 사용자에게 알리고 graph는 재개하지 않음
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

    async for chunk in stream_agent_response(graph_compiled, Command(resume=response), config):
        yield chunk
