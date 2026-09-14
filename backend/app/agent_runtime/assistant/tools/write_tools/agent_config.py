"""Assistant 쓰기 도구 — 에이전트 설정 그룹 (프롬프트/모델/메타데이터 등)."""

from __future__ import annotations

import copy

from langchain_core.tools import StructuredTool
from sqlalchemy import func, select

from app.agent_runtime.assistant.tools.write_tools.context import (
    WriteToolContext,
    get_agent_with_session,
)
from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.identity import AGENT_IDENTITY_PER_USER, validate_identity_mode
from app.models.agent_trigger import AgentTrigger
from app.services.model_service import resolve_model


def build_agent_config_tools(ctx: WriteToolContext) -> list[StructuredTool]:
    """에이전트 설정 도구 8개를 생성한다."""

    # ------ 7. edit_system_prompt ------

    async def edit_system_prompt(
        old_string: str, new_string: str, replace_all: bool = False
    ) -> str:
        """시스템 프롬프트의 일부를 수정합니다 (부분 교체).

        Args:
            old_string: 교체할 기존 텍스트
            new_string: 새 텍스트 (빈 문자열이면 삭제)
            replace_all: True면 모든 매치를 교체, False면 첫 번째만
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            prompt = agent.system_prompt or ""
            if old_string not in prompt:
                return tr("v_cannot_be_found_in_0104c0", v0=f"{old_string}")

            count = prompt.count(old_string)
            if count > 1 and not replace_all:
                return tr("v_was_found_at_location_e9f7e4", v0=f"{old_string}", v1=f"{count}")

            if replace_all:
                new_prompt = prompt.replace(old_string, new_string)
            else:
                new_prompt = prompt.replace(old_string, new_string, 1)

            agent.system_prompt = new_prompt
            await session.commit()
            return tr("system_prompt_fix_complete_a1e7f4")

    # ------ 8. update_system_prompt ------

    async def update_system_prompt(new_system_prompt: str) -> str:
        """시스템 프롬프트를 전체 교체합니다.

        Args:
            new_system_prompt: 새 시스템 프롬프트 전체 내용
        """
        if not new_system_prompt.strip():
            return tr("warning_you_are_attempting_to_cf1f71")
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")
            agent.system_prompt = new_system_prompt
            await session.commit()
            return tr("complete_system_prompt_replacement_e61f37")

    # ------ 9. update_model_config ------

    async def update_model_config(
        model_name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> str:
        """모델 설정을 변경합니다.

        Args:
            model_name: 새 모델 (provider:model_id 또는 display_name)
            temperature: 응답 창의성 (0.0~2.0)
            max_tokens: 최대 응답 토큰
            top_p: 누적 확률 샘플링
        """
        # W-8: 입력값 범위 검증
        if temperature is not None and not (0.0 <= temperature <= 2.0):
            return tr("temperature_must_be_in_the_ce44d6")
        if max_tokens is not None and max_tokens <= 0:
            return tr("max_tokens_must_be_positive_381889")
        if top_p is not None and not (0.0 <= top_p <= 1.0):
            return tr("top_p_must_be_in_37a09c")

        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            changes: list[str] = []
            if model_name:
                model = await resolve_model(session, model_name, strict=True)
                if model:
                    agent.model_id = model.id
                    changes.append(tr("model_v_0dd9d6", v0=f"{model.display_name}"))
                else:
                    return tr("model_v_not_found_a71e78", v0=f"{model_name}")

            params = dict(agent.model_params or {})
            if temperature is not None:
                params["temperature"] = temperature
                changes.append(f"temperature: {temperature}")
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
                changes.append(f"max_tokens: {max_tokens}")
            if top_p is not None:
                params["top_p"] = top_p
                changes.append(f"top_p: {top_p}")
            if params != (agent.model_params or {}):
                agent.model_params = params

            await session.commit()
            return (
                tr("model_settings_change_completed_v_b22a84", v0=f"{', '.join(changes)}")
                if changes
                else tr("no_changes_7d9feb")
            )

    # ------ 11. update_middleware_config ------

    async def update_middleware_config(middleware_name: str, params: dict) -> str:
        """미들웨어의 설정 파라미터를 변경합니다.

        Args:
            middleware_name: 미들웨어 type 키
            params: 새 파라미터 딕셔너리
        """
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")

            # W-7: deepcopy로 SQLAlchemy JSON mutation detection 보장
            configs = copy.deepcopy(list(agent.middleware_configs or []))
            for mc in configs:
                if mc.get("type", "").lower() == middleware_name.lower():
                    mc["params"] = {**mc.get("params", {}), **params}
                    agent.middleware_configs = configs
                    await session.commit()
                    return tr(
                        "v_middleware_settings_change_completed_3dae6d", v0=f"{middleware_name}"
                    )
            return tr("middleware_v_could_not_be_d3088a", v0=f"{middleware_name}")

    # ------ 12. update_chat_openers ------

    async def update_chat_openers(openers: list[str]) -> str:
        """채팅 시작 질문(오프너)을 변경합니다.

        Args:
            openers: 새 오프너 질문 목록 (최대 12개, 각 1~200자)
        """
        cleaned = [s.strip() for s in openers]
        if any(not s for s in cleaned):
            return tr("blank_questions_are_not_allowed_701302")
        if len(cleaned) > 12:
            return tr("up_to_openers_can_be_b22846")
        if any(len(s) > 200 for s in cleaned):
            return tr("each_question_cannot_exceed_characters_0612a9")
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")
            agent.opener_questions = cleaned
            await session.commit()
            return tr("opener_v_setup_completed_a623d2", v0=f"{len(cleaned)}")

    # ------ 12-2. update_agent_metadata ------

    async def update_agent_metadata(
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """에이전트의 이름과 설명을 변경합니다.

        둘 중 하나만 지정해도 됩니다. 빈 description은 설명을 비웁니다.

        Args:
            name: 새 에이전트 이름 (생략하면 변경 안 함)
            description: 새 에이전트 설명 (빈 문자열이면 설명 제거)
        """
        if name is None and description is None:
            return tr("either_name_or_description_must_4404c3")
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")
            changes: list[str] = []
            if name is not None:
                stripped = name.strip()
                if not stripped:
                    return tr("the_agent_name_cannot_be_937e8f")
                agent.name = stripped
                changes.append(tr("name_v_7ba722", v0=f"{stripped}"))
            if description is not None:
                desc = description.strip()
                agent.description = desc or None
                changes.append(
                    tr("description_empty_06a69e")
                    if not desc
                    else tr("description_v_a64bd5", v0=f"{desc[:30]}")
                )
            await session.commit()
            return tr("agent_metadata_change_completed_v_6ebcc9", v0=f"{', '.join(changes)}")

    # ------ 13. update_agent_identity_mode ------

    async def update_agent_identity_mode(identity_mode: str) -> str:
        """credential 사용 방식을 변경합니다.

        Args:
            identity_mode: "per_user" 또는 "fixed"
        """
        normalized = identity_mode.strip().lower()
        try:
            validate_identity_mode(normalized)
        except Exception:
            return tr("credential_can_only_be_used_b5e16a")

        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")
            if normalized == agent.identity_mode:
                return tr("credential_usage_method_is_already_a64812", v0=f"{normalized}")

            if normalized == AGENT_IDENTITY_PER_USER:
                active_count = await session.scalar(
                    select(func.count())
                    .select_from(AgentTrigger)
                    .where(
                        AgentTrigger.agent_id == ctx.agent_id,
                        AgentTrigger.user_id == ctx.user_id,
                        AgentTrigger.status == "active",
                    )
                )
                if active_count:
                    return tr("agents_with_active_schedules_cannot_30ae0e")

            agent.identity_mode = normalized
            await session.commit()
            return tr("credential_usage_mode_change_completed_8061c1", v0=f"{normalized}")

    # ------ 14. update_recursion_limit ------

    async def update_recursion_limit(limit: int) -> str:
        """재귀 한도를 변경합니다.

        Args:
            limit: 새 재귀 한도 (10~200)
        """
        if not 10 <= limit <= 200:
            return tr("the_recursion_limit_should_be_dc34b0")
        async with ctx.session_factory() as session:
            agent = await get_agent_with_session(ctx, session)
            if not agent:
                return tr("agent_not_found_1a3985")
            params = dict(agent.model_params or {})
            params["recursion_limit"] = limit
            agent.model_params = params
            await session.commit()
            return tr("changed_recursion_limit_to_v_f94adb", v0=f"{limit}")

    return [
        StructuredTool.from_function(
            coroutine=edit_system_prompt,
            name="edit_system_prompt",
            description=tr("partial_modification_of_system_prompt_bdd43a"),
        ),
        StructuredTool.from_function(
            coroutine=update_system_prompt,
            name="update_system_prompt",
            description=tr("complete_system_prompt_replacement_6d162b"),
        ),
        StructuredTool.from_function(
            coroutine=update_model_config,
            name="update_model_config",
            description=tr("change_model_settings_model_name_546efb"),
        ),
        StructuredTool.from_function(
            coroutine=update_middleware_config,
            name="update_middleware_config",
            description=tr("change_middleware_setting_parameters_c7f489"),
        ),
        StructuredTool.from_function(
            coroutine=update_chat_openers,
            name="update_chat_openers",
            description=tr("change_chat_start_question_opener_71b686"),
        ),
        StructuredTool.from_function(
            coroutine=update_agent_metadata,
            name="update_agent_metadata",
            description=tr("change_agent_name_description_either_718c9f"),
        ),
        StructuredTool.from_function(
            coroutine=update_agent_identity_mode,
            name="update_agent_identity_mode",
            description=tr("change_how_credential_is_used_a22354"),
        ),
        StructuredTool.from_function(
            coroutine=update_recursion_limit,
            name="update_recursion_limit",
            description=tr("change_recursion_limit_a35847"),
        ),
    ]
