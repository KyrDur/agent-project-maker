"""Router 节点 — Phase 8 出现修改请求时，分类应跳转到哪个 phase。

通过 Pydantic enum + 结构化输出，强制防止 LLM 进入错误分支。
如果模糊则 ask_user fallback。
"""

from __future__ import annotations

import logging

from langgraph.types import Command, interrupt

from app.agent_runtime.builder.sub_agents.helpers import invoke_with_json_retry
from app.agent_runtime.builder_i18n import localize, tr
from app.agent_runtime.builder_v3.state import BuilderState

logger = logging.getLogger(__name__)


_VALID_TARGETS = {
    "phase2_analyze_intent",
    "phase3_recommend_tools",
    "phase4_recommend_middlewares",
    "phase5_generate_prompt",
    "phase6_choice_propose",
}

_LABEL_TO_NODE = {
    "intent": "phase2_analyze_intent",
    "tools": "phase3_recommend_tools",
    "middlewares": "phase4_recommend_middlewares",
    "prompt": "phase5_generate_prompt",
    "image": "phase6_choice_propose",
}

_SYSTEM_PROMPT = (
    "你是智能体构建器的路由分类器。 "
    "查看用户的修改请求消息，决定重新执行哪个阶段。 "
    "响应必须仅为一个 JSON 对象，其中只包含以下 5 个标签之一:\n"
    " - intent: 修改智能体名称/描述/角色\n"
    " - tools: 修改工具推荐\n"
    " - middlewares: 修改中间件推荐\n"
    " - prompt: 修改系统提示词\n"
    " - image: 修改智能体图片\n\n"
    '响应格式: {"target": "<label>", "reason": "<简短说明>"}'
)


async def _classify_target(message: str) -> str | None:
    task = tr("user_request_v_which_steps_9cc08c", v0=f"{message}")
    try:
        result = await invoke_with_json_retry(localize(_SYSTEM_PROMPT), task, max_retries=1)
        if isinstance(result, dict):
            label = str(result.get("target") or "").strip().lower()
            return _LABEL_TO_NODE.get(label)
    except Exception:
        logger.warning("Router classification failed", exc_info=True)
    return None


async def router(state: BuilderState) -> Command:
    message = state.get("last_revision_message") or ""
    target = await _classify_target(message) if message else None

    if target and target in _VALID_TARGETS:
        return Command(
            goto=target,
            update={
                "last_router_decision": target,
                "last_revision_message": message,
            },
        )

    # 模糊 → ask_user fallback
    answer = interrupt(
        {
            "type": "ask_user",
            "question": tr("which_step_would_you_like_b0a0e5"),
            "options": [
                tr("agent_name_description_089718"),
                tr("tool_recommendations_19ce61"),
                tr("middleware_recommendations_b55f76"),
                tr("system_prompt_30dccb"),
                tr("agent_image_b1fd5a"),
            ],
        }
    )

    text = str(answer or "").lower()
    localized_targets = {
        tr("agent_name_description_089718").lower(): "phase2_analyze_intent",
        tr("tool_recommendations_19ce61").lower(): "phase3_recommend_tools",
        tr("middleware_recommendations_b55f76").lower(): "phase4_recommend_middlewares",
        tr("system_prompt_30dccb").lower(): "phase5_generate_prompt",
        tr("agent_image_b1fd5a").lower(): "phase6_choice_propose",
    }
    if text in localized_targets:
        return Command(
            goto=localized_targets[text], update={"last_router_decision": localized_targets[text]}
        )
    fallback_target = "phase3_recommend_tools"  # 最常见的情况
    if "名称" in text or "描述" in text or "intent" in text:
        fallback_target = "phase2_analyze_intent"
    elif "工具" in text or "tool" in text:
        fallback_target = "phase3_recommend_tools"
    elif "中间件" in text or "middleware" in text:
        fallback_target = "phase4_recommend_middlewares"
    elif "提示词" in text or "prompt" in text:
        fallback_target = "phase5_generate_prompt"
    elif "图片" in text or "image" in text:
        fallback_target = "phase6_choice_propose"

    return Command(
        goto=fallback_target,
        update={
            "last_router_decision": fallback_target,
        },
    )
