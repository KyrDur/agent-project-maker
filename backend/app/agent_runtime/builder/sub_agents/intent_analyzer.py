"""阶段 2：把用户自然语言需求转换为结构化 AgentCreationIntent。"""

from __future__ import annotations

import logging

from app.agent_runtime.builder.sub_agents.helpers import invoke_with_json_retry, load_prompt
from app.agent_runtime.builder_i18n import tr
from app.schemas.builder import AgentCreationIntent

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    "你是智能体需求分析专家。仅返回 AgentCreationIntent JSON；未知规则明确标记为待确认的模拟假设。"
)

SYSTEM_PROMPT = load_prompt("intent_analyzer.md") or _FALLBACK_PROMPT


def _build_task_description(user_request: str) -> str:
    return tr("user_requested_v_please_collect_a2ff0e", v0=f"{user_request}")


async def analyze_intent(user_request: str) -> AgentCreationIntent:
    """分析用户请求并返回 AgentCreationIntent。

    解析失败后暂停阶段，允许用户重试。
    """
    description = _build_task_description(user_request)

    data = await invoke_with_json_retry(SYSTEM_PROMPT, description)
    return AgentCreationIntent(**data)
