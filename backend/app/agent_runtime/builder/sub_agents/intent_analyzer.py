"""Phase 2 — 의도 분석 서브에이전트.

사용자의 자연어 요청을 AgentCreationIntent JSON으로 변환한다.
"""

from __future__ import annotations

import logging

from app.agent_runtime.builder.sub_agents.helpers import invoke_with_json_retry, load_prompt
from app.agent_runtime.builder_i18n import tr
from app.schemas.builder import AgentCreationIntent

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    "당신은 AI 에이전트 생성을 위한 의도 분석 전문가입니다. "
    "사용자의 자연어 요청을 AgentCreationIntent JSON으로 변환합니다. "
    "JSON 외 다른 텍스트를 포함하지 않습니다."
)

SYSTEM_PROMPT = load_prompt("intent_analyzer.md") or _FALLBACK_PROMPT


def _build_task_description(user_request: str) -> str:
    return tr("user_requested_v_please_collect_a2ff0e", v0=f"{user_request}")


async def analyze_intent(user_request: str) -> AgentCreationIntent:
    """사용자 요청을 분석하여 AgentCreationIntent를 반환한다.

    파싱 실패 시 1회 재시도 후 기본 Intent를 반환한다.
    """
    description = _build_task_description(user_request)

    try:
        data = await invoke_with_json_retry(SYSTEM_PROMPT, description)
        return AgentCreationIntent(**data)
    except (ValueError, TypeError) as exc:
        logger.error("Intent parsing failed after retries: %s, using fallback", exc)

    # fallback
    return AgentCreationIntent(
        agent_name="Custom Agent",
        agent_description=tr("agent_created_upon_user_request_d1f519", v0=f"{user_request}"),
        primary_task_type=tr("perform_common_tasks_136765"),
        identity_mode="per_user",
        use_cases=[tr("handling_user_requests_b68392")],
        required_capabilities=[tr("normal_conversation_fb5742")],
    )

