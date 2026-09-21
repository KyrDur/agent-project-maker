"""Phase 6 — 에이전트 이미지 생성 (4-노드 패턴).

phase6_choice_propose: 1차 image_choice ToolMessage emit (또는 provider 없으면 즉시 skip)
phase6_choice_wait: interrupt → skip/generate 분기
phase6_image_generate: 이미지 생성 + 2차 image_approval ToolMessage emit
phase6_image_approval: interrupt → 확정/재생성/skip 분기
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from app.agent_runtime.builder_i18n import tr
from app.agent_runtime.builder_v3.image_gen import (
    ImageGenerationError,
    build_default_prompt,
    generate_agent_image,
    is_image_generation_available,
)
from app.agent_runtime.builder_v3.nodes._helpers import (
    build_phase_complete,
    close_pending_tool_card,
    ensure_todos,
    make_pending_tool_card,
    make_tool_card,
    parse_choice_response,
)
from app.agent_runtime.builder_v3.state import BuilderState

logger = logging.getLogger(__name__)


def _get_image_prompt_seed(state: BuilderState) -> str:
    intent = state.get("intent") or {}
    return build_default_prompt(
        agent_name=intent.get("agent_name", "Agent"),
        agent_description=intent.get("agent_description", ""),
        primary_task_type=intent.get("primary_task_type", ""),
    )


# ---------------------------------------------------------------------------
# Node: phase6_choice_propose
# ---------------------------------------------------------------------------


async def phase6_choice_propose(state: BuilderState) -> dict:
    """1차: image_choice 카드 emit. provider 없으면 image_skipped=True로 fall-through."""
    if not await is_image_generation_available():
        info_msgs, _ = make_tool_card(
            "image_choice",
            {
                "phase": 6,
                "title": tr("generate_agent_image_172ee6"),
                "available": False,
                "auto_prompt": tr("image_creation_is_disabled_openrouter_a99d28"),
            },
            intro_text=tr("image_creation_is_not_set_91eafc"),
        )
        complete_msgs = build_phase_complete(
            6,
            ensure_todos(state),
            tr("phase_completed_image_creation_skipped_347fcb"),
        )
        return {
            "messages": list(info_msgs) + list(complete_msgs),
            "image_url": None,
            "current_phase": 7,
            "image_skipped": True,
        }

    auto_prompt = _get_image_prompt_seed(state)
    msgs, tool_call_id = make_pending_tool_card(
        "image_choice",
        {
            "phase": 6,
            "title": tr("would_you_like_to_create_571561"),
            "auto_prompt": auto_prompt,
            "available": True,
            "options": [
                {"value": "skip", "label": tr("skip_3563f5")},
                {"value": "generate", "label": tr("generate_ad63ee")},
            ],
        },
        intro_text=tr("now_let_s_create_an_4b6f31"),
    )
    return {
        "messages": msgs,
        "image_skipped": False,
        "pending_tool_call_id": tool_call_id,
    }


# ---------------------------------------------------------------------------
# Node: phase6_choice_wait
# ---------------------------------------------------------------------------


async def phase6_choice_wait(state: BuilderState) -> dict:
    """interrupt → skip/generate 결정을 state에 반영. 라우팅은 graph가."""
    auto_prompt = _get_image_prompt_seed(state)

    response = interrupt(
        {
            "type": "image_choice",
            "phase": 6,
            "title": tr("would_you_like_to_create_571561"),
            "auto_prompt": auto_prompt,
            "options": [
                {"value": "skip", "label": tr("skip_3563f5")},
                {"value": "generate", "label": tr("generate_ad63ee")},
            ],
        }
    )

    choice, custom_prompt = parse_choice_response(response)

    pending_tc_id = state.get("pending_tool_call_id")

    if choice in ("skip", "跳过", "넘어가"):
        close_msgs = close_pending_tool_card(pending_tc_id, "image_choice", "skip")
        complete_msgs = build_phase_complete(
            6,
            ensure_todos(state),
            tr("phase_completed_image_creation_skipped_347fcb"),
        )
        return {
            "messages": [*close_msgs, *complete_msgs],
            "image_url": None,
            "current_phase": 7,
            "image_skipped": True,
            "pending_tool_call_id": None,
        }

    close_msgs = close_pending_tool_card(pending_tc_id, "image_choice", "generate")
    return {
        "messages": close_msgs,
        "last_revision_message": custom_prompt or auto_prompt,
        "image_skipped": False,
        "pending_tool_call_id": None,
    }


# ---------------------------------------------------------------------------
# Node: phase6_image_generate (이미지 생성 + image_approval ToolMessage emit)
# ---------------------------------------------------------------------------


async def phase6_image_generate(state: BuilderState) -> dict:
    session_id = state.get("session_id", "session")
    prompt = state.get("last_revision_message") or _get_image_prompt_seed(state)

    try:
        public_url, _local_path = await generate_agent_image(prompt=prompt, session_id=session_id)
    except ImageGenerationError as exc:
        logger.warning("Image generation failed: %s", exc)
        msgs, fail_tc_id = make_pending_tool_card(
            "image_approval",
            {
                "phase": 6,
                "title": tr("image_creation_failed_0ceb50"),
                "image_url": None,
                "prompt": prompt,
                "error": str(exc),
                "options": [
                    {"value": "regenerate", "label": tr("retry_1d9e7f")},
                    {"value": "skip", "label": tr("skip_3563f5")},
                ],
            },
            intro_text=tr("image_creation_failed_v_2b1a2f", v0=f"{exc}"),
        )
        return {
            "messages": msgs,
            "image_url": None,
            "pending_tool_call_id": fail_tc_id,
        }

    msgs, ok_tc_id = make_pending_tool_card(
        "image_approval",
        {
            "phase": 6,
            "title": tr("image_preview_eacc54"),
            "image_url": public_url,
            "prompt": prompt,
            "options": [
                {"value": "confirm", "label": tr("confirmed_568940")},
                {"value": "regenerate", "label": tr("regenerate_bd72a5")},
                {"value": "skip", "label": tr("skip_3563f5")},
            ],
        },
        intro_text=tr("your_image_has_been_created_3fe9f8"),
    )
    return {
        "messages": msgs,
        "image_url": public_url,
        "last_revision_message": None,
        "pending_tool_call_id": ok_tc_id,
    }


# ---------------------------------------------------------------------------
# Node: phase6_image_approval (interrupt + 분기)
# ---------------------------------------------------------------------------


async def phase6_image_approval(state: BuilderState) -> dict:
    """interrupt → 확정/재생성/skip 결정을 state에 반영. 라우팅은 graph가."""
    response = interrupt(
        {
            "type": "image_approval",
            "phase": 6,
            "image_url": state.get("image_url"),
        }
    )

    choice, new_prompt = parse_choice_response(response, prompt_keys=("prompt",))

    pending_tc_id = state.get("pending_tool_call_id")

    if choice in ("confirm", "确认"):
        close_msgs = close_pending_tool_card(
            pending_tc_id, "image_approval", tr("confirmed_568940")
        )
        complete_msgs = build_phase_complete(
            6,
            ensure_todos(state),
            tr("phase_completed_agent_image_confirmed_521661"),
        )
        return {
            "messages": [*close_msgs, *complete_msgs],
            "current_phase": 7,
            "image_skipped": True,
            "pending_tool_call_id": None,
        }

    if choice in ("skip", "跳过"):
        close_msgs = close_pending_tool_card(pending_tc_id, "image_approval", "skip")
        complete_msgs = build_phase_complete(
            6,
            ensure_todos(state),
            tr("phase_completed_image_creation_skipped_347fcb"),
        )
        return {
            "messages": [*close_msgs, *complete_msgs],
            "image_url": None,
            "current_phase": 7,
            "image_skipped": True,
            "pending_tool_call_id": None,
        }

    # regenerate — image_url 클리어 + last_revision_message 설정
    close_msgs = close_pending_tool_card(pending_tc_id, "image_approval", tr("regenerate_bd72a5"))
    base_prompt: Any = state.get("image_url") and _get_image_prompt_seed(state)
    target_prompt = new_prompt or base_prompt or _get_image_prompt_seed(state)
    return {
        "messages": close_msgs,
        "last_revision_message": str(target_prompt),
        "image_url": None,
        "image_skipped": False,
        "pending_tool_call_id": None,
    }

