"""Assistant 읽기 도구 — Safe 도구 (DB 수정 없음).

도구 목록:
1. get_agent_config
2. get_model_config
3. list_available_tools
4. list_available_middlewares
5. list_available_subagents
6. list_available_skills
7. list_available_models
8. get_agent_required_secrets
9. get_user_secrets
10. get_chat_openers
11. get_recursion_limit
12. list_permanent_files
13. get_file_content
14. search_system_prompt
15. list_cron_schedules
16. get_cron_schedule
"""

from __future__ import annotations

import json
import uuid

from langchain_core.tools import StructuredTool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.assistant.tools.helpers import get_agent_with_eager_load
from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.middleware_registry import MIDDLEWARE_REGISTRY
from app.database import async_session as async_session_factory
from app.models.agent import AGENT_RUNTIME_PROFILE_STANDARD, Agent
from app.models.agent_trigger import AgentTrigger
from app.models.model import Model
from app.models.skill import Skill
from app.services.tool_service import get_tools_catalog


def build_read_tools(
    db: AsyncSession,  # noqa: ARG001 — kept for interface compatibility
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[StructuredTool]:
    """Assistant 읽기 도구 16개를 생성한다.

    각 도구는 호출 시마다 fresh DB 세션을 생성하여 사용한다.
    LangGraph 에이전트의 도구 실행은 빌드 시점의 클로저 DB 세션이
    이미 닫혀 있을 수 있으므로, 매 호출마다 새 세션을 열어야 안전하다.
    """

    # ------ helpers ------

    async def _get_agent() -> Agent | None:
        async with async_session_factory() as session:
            return await get_agent_with_eager_load(session, agent_id, user_id)

    # ------ 1. get_agent_config ------

    async def get_agent_config() -> str:
        """현재 에이전트의 전체 설정을 조회합니다."""
        agent = await _get_agent()
        if not agent:
            return tr("agent_not_found_1a3985")
        tools_info = [
            {
                "name": link.tool.name,
                "description": link.tool.description,
                "type": link.tool.definition_key,
            }
            for link in agent.tool_links
        ]
        mw_info = []
        for mc in agent.middleware_configs or []:
            mtype = mc.get("type", "")
            reg = MIDDLEWARE_REGISTRY.get(mtype, {})
            mw_info.append(
                {
                    "type": mtype,
                    "display_name": reg.get("display_name", mtype),
                    "params": mc.get("params", {}),
                }
            )
        return json.dumps(
            {
                "agent_id": str(agent.id),
                "runtime_name": agent.runtime_name,
                "identity_mode": agent.identity_mode,
                "name": agent.name,
                "description": agent.description,
                "system_prompt": agent.system_prompt,
                "model_name": (
                    f"{agent.model.provider}:{agent.model.model_name}" if agent.model else "unknown"
                ),
                "model_params": agent.model_params,
                "opener_questions": agent.opener_questions or [],
                "tools": tools_info,
                "middlewares": mw_info,
                "skills": [
                    {"name": link.skill.name, "description": link.skill.description}
                    for link in agent.skill_links
                ],
                "sub_agents": [
                    {
                        "id": str(link.sub_agent_id),
                        "name": link.sub_agent.name,
                        "description": link.sub_agent.description,
                    }
                    for link in agent.sub_agent_links
                ],
            },
            ensure_ascii=False,
            indent=2,
        )

    # ------ 2. get_model_config ------

    async def get_model_config() -> str:
        """현재 에이전트의 모델 설정을 조회합니다."""
        agent = await _get_agent()
        if not agent:
            return tr("agent_not_found_1a3985")
        return json.dumps(
            {
                "model_name": (
                    f"{agent.model.provider}:{agent.model.model_name}" if agent.model else "unknown"
                ),
                "display_name": agent.model.display_name if agent.model else "",
                "model_params": agent.model_params or {},
            },
            ensure_ascii=False,
        )

    # ------ 3. list_available_tools ------

    async def list_available_tools() -> str:
        """시스템에서 사용 가능한 도구 목록을 조회합니다."""
        async with async_session_factory() as session:
            items = await get_tools_catalog(session, user_id)
            return json.dumps(items, ensure_ascii=False, indent=2)

    # ------ 5. list_available_middlewares ------

    async def list_available_middlewares() -> str:
        """시스템에서 사용 가능한 미들웨어 목록을 조회합니다."""
        items = [
            {
                "type": key,
                "display_name": entry["display_name"],
                "description": entry["description"],
                "category": entry["category"],
            }
            for key, entry in MIDDLEWARE_REGISTRY.items()
        ]
        return json.dumps(items, ensure_ascii=False, indent=2)

    # ------ 6. list_available_subagents ------

    async def list_available_subagents() -> str:
        """서브에이전트로 사용 가능한 에이전트 목록을 조회합니다."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Agent.id, Agent.name, Agent.description, Agent.model_id).where(
                    Agent.user_id == user_id,
                    Agent.id != agent_id,
                    # 히든 런타임 에이전트는 서브에이전트 후보에서 제외.
                    Agent.runtime_profile == AGENT_RUNTIME_PROFILE_STANDARD,
                )
            )
            rows = result.all()
            # model display_name은 별도 쿼리로 가져온다
            model_ids = {r.model_id for r in rows if r.model_id}
            model_names: dict[str, str] = {}
            if model_ids:
                model_result = await session.execute(
                    select(Model.id, Model.display_name).where(Model.id.in_(model_ids))
                )
                model_names = {r.id: r.display_name for r in model_result.all()}
            items = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "description": r.description,
                    "model": model_names.get(r.model_id, ""),
                }
                for r in rows
            ]
            return json.dumps(items, ensure_ascii=False, indent=2)

    # ------ 6-2. list_available_skills ------

    async def list_available_skills() -> str:
        """사용 가능한 스킬 목록을 조회합니다."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Skill).where(Skill.user_id == user_id).order_by(Skill.name)
            )
            skills = result.scalars().all()
            items = [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "description": s.description,
                }
                for s in skills
            ]
            return json.dumps(items, ensure_ascii=False, indent=2)

    # ------ 7. list_available_models ------

    async def list_available_models() -> str:
        """사용 가능한 모델 목록을 조회합니다."""
        async with async_session_factory() as session:
            result = await session.execute(select(Model))
            models = result.scalars().all()
            items = [
                {
                    "id": str(m.id),
                    "display_name": m.display_name,
                    "provider": m.provider,
                    "model_name": m.model_name,
                }
                for m in models
            ]
            return json.dumps(items, ensure_ascii=False, indent=2)

    # ------ 8. get_agent_required_secrets ------

    async def get_agent_required_secrets() -> str:
        """에이전트에 필요한 API 키 목록을 조회합니다."""
        # PoC: 도구 타입별 필요 키 반환
        agent = await _get_agent()
        if not agent:
            return tr("agent_not_found_1a3985")
        required: set[str] = set()
        for link in agent.tool_links:
            if "naver" in link.tool.name.lower():
                required.update(["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"])
            if "google" in link.tool.name.lower():
                required.update(["GOOGLE_API_KEY", "GOOGLE_CSE_ID"])
        return json.dumps(
            {
                "required": sorted(required),
                "registered": [],  # PoC: 시크릿 스토어 미구현
                "missing": sorted(required),
            },
            ensure_ascii=False,
        )

    # ------ 9. get_user_secrets ------

    async def get_user_secrets() -> str:
        """사용자가 등록한 시크릿 목록을 조회합니다."""
        # PoC: 시크릿 스토어 미구현
        return json.dumps({"secrets": []}, ensure_ascii=False)

    # ------ 10. get_chat_openers ------

    async def get_chat_openers() -> str:  # noqa: D401
        """현재 에이전트의 채팅 시작 질문 목록을 조회합니다."""
        agent = await _get_agent()
        if not agent:
            return tr("agent_not_found_1a3985")
        openers = agent.opener_questions or []
        return json.dumps({"chat_openers": openers}, ensure_ascii=False)

    # ------ 11. get_recursion_limit ------

    async def get_recursion_limit() -> str:
        """현재 에이전트의 재귀 한도를 조회합니다."""
        agent = await _get_agent()
        if not agent:
            return tr("agent_not_found_1a3985")
        limit = (agent.model_params or {}).get("recursion_limit", 25)
        return json.dumps({"recursion_limit": limit}, ensure_ascii=False)

    # ------ 12. list_permanent_files ------

    async def list_permanent_files() -> str:
        """에이전트에 업로드된 영구 파일 목록을 조회합니다."""
        # PoC: 파일 업로드 미구현
        return json.dumps({"files": []}, ensure_ascii=False)

    # ------ 13. get_file_content ------

    async def get_file_content(file_id: str) -> str:
        """파일 내용을 미리봅니다.

        Args:
            file_id: 파일 고유 ID
        """
        return tr("file_v_not_found_62501a", v0=f"{file_id}")

    # ------ 14. search_system_prompt ------

    async def search_system_prompt(keyword: str) -> str:
        """시스템 프롬프트에서 키워드를 검색합니다.

        Args:
            keyword: 검색할 키워드
        """
        agent = await _get_agent()
        if not agent:
            return tr("agent_not_found_1a3985")
        prompt = agent.system_prompt or ""
        matches = []
        for i, line in enumerate(prompt.split("\n"), 1):
            if keyword.lower() in line.lower():
                matches.append({"text": line.strip(), "line_number": i})
        return json.dumps(
            {
                "found": len(matches) > 0,
                "matches": matches,
            },
            ensure_ascii=False,
        )

    # ------ 15. list_cron_schedules ------

    def _serialize_schedule_for_assistant(t: AgentTrigger) -> dict[str, object]:
        return {
            "id": str(t.id),
            "name": t.name,
            "type": t.trigger_type,
            "schedule": t.schedule_config,
            "message": t.input_message,
            "status": t.status,
            "timezone": t.timezone,
            "conversation_policy": t.conversation_policy,
            "result_conversation_id": (
                str(t.schedule_conversation_id) if t.schedule_conversation_id else None
            ),
            "target_conversation_id": (
                str(t.target_conversation_id) if t.target_conversation_id else None
            ),
            "last_status": t.last_status,
            "recent_status": t.last_status,
            "last_error": t.last_error,
            "last_run_at": str(t.last_run_at) if t.last_run_at else None,
            "next_run_at": str(t.next_run_at) if t.next_run_at else None,
            "run_count": t.run_count,
            "failure_count": t.failure_count,
            "max_runs": t.max_runs,
            "end_at": str(t.end_at) if t.end_at else None,
            "auto_pause_after_failures": t.auto_pause_after_failures,
        }

    async def list_cron_schedules() -> str:
        """에이전트의 크론 스케줄 목록을 조회합니다."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(AgentTrigger).where(
                    AgentTrigger.agent_id == agent_id,
                    AgentTrigger.user_id == user_id,
                )
            )
            triggers = result.scalars().all()
            items = [_serialize_schedule_for_assistant(t) for t in triggers]
            return json.dumps(items, ensure_ascii=False, indent=2)

    # ------ 16. get_cron_schedule ------

    async def get_cron_schedule(schedule_id: str) -> str:
        """특정 크론 스케줄의 상세 정보를 조회합니다.

        Args:
            schedule_id: 스케줄 UUID
        """
        try:
            sid = uuid.UUID(schedule_id)
        except ValueError:
            return tr("invalid_schedule_id_22d6bb")
        async with async_session_factory() as session:
            result = await session.execute(
                select(AgentTrigger).where(
                    AgentTrigger.id == sid,
                    AgentTrigger.agent_id == agent_id,
                    AgentTrigger.user_id == user_id,
                )
            )
            t = result.scalar_one_or_none()
            if not t:
                return tr("schedule_not_found_0a71df")
            return json.dumps(
                _serialize_schedule_for_assistant(t),
                ensure_ascii=False,
            )

    # ------ Build tools list ------

    return [
        StructuredTool.from_function(
            coroutine=get_agent_config,
            name="get_agent_config",
            description=tr("view_the_current_agent_s_1dae0d"),
        ),
        StructuredTool.from_function(
            coroutine=get_model_config,
            name="get_model_config",
            description=tr("view_model_settings_for_current_687d31"),
        ),
        StructuredTool.from_function(
            coroutine=list_available_tools,
            name="list_available_tools",
            description=tr("view_the_list_of_tools_3d2b81"),
        ),
        StructuredTool.from_function(
            coroutine=list_available_middlewares,
            name="list_available_middlewares",
            description=tr("check_the_list_of_middleware_ad2a12"),
        ),
        StructuredTool.from_function(
            coroutine=list_available_subagents,
            name="list_available_subagents",
            description=tr("view_the_list_of_agents_9b0d5a"),
        ),
        StructuredTool.from_function(
            coroutine=list_available_skills,
            name="list_available_skills",
            description=tr("view_list_of_available_skills_503636"),
        ),
        StructuredTool.from_function(
            coroutine=list_available_models,
            name="list_available_models",
            description=tr("view_list_of_available_llm_55c935"),
        ),
        StructuredTool.from_function(
            coroutine=get_agent_required_secrets,
            name="get_agent_required_secrets",
            description=tr("query_the_list_of_api_aca24b"),
        ),
        StructuredTool.from_function(
            coroutine=get_user_secrets,
            name="get_user_secrets",
            description=tr("view_the_list_of_secrets_513559"),
        ),
        StructuredTool.from_function(
            coroutine=get_chat_openers,
            name="get_chat_openers",
            description=tr("view_list_of_chat_start_57af9e"),
        ),
        StructuredTool.from_function(
            coroutine=get_recursion_limit,
            name="get_recursion_limit",
            description=tr("query_the_current_agent_s_e600c0"),
        ),
        StructuredTool.from_function(
            coroutine=list_permanent_files,
            name="list_permanent_files",
            description=tr("view_list_of_persistent_files_f39ccf"),
        ),
        StructuredTool.from_function(
            coroutine=get_file_content,
            name="get_file_content",
            description=tr("preview_file_contents_b26951"),
        ),
        StructuredTool.from_function(
            coroutine=search_system_prompt,
            name="search_system_prompt",
            description=tr("search_for_keywords_from_the_e48060"),
        ),
        StructuredTool.from_function(
            coroutine=list_cron_schedules,
            name="list_cron_schedules",
            description=tr("view_the_agent_s_cron_d4e26d"),
        ),
        StructuredTool.from_function(
            coroutine=get_cron_schedule,
            name="get_cron_schedule",
            description=tr("view_detailed_information_of_a_8d2e23"),
        ),
    ]
