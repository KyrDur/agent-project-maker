"""Builder v3 — frontend Tool UI 与 backend 节点共享的魔法字符串常量。

需要与 frontend `lib/chat/tool-ui-registry.ts` 同步（变更时两边都修改）。
"""

from __future__ import annotations


class ToolNames:
    """Tool UI registry 的 tool_name 常量。"""

    PHASE_TIMELINE = "phase_timeline"
    ASK_USER = "ask_user"
    RECOMMENDATION_APPROVAL = "recommendation_approval"
    PROMPT_APPROVAL = "prompt_approval"
    IMAGE_CHOICE = "image_choice"
    IMAGE_APPROVAL = "image_approval"
    DRAFT_CONFIG_CARD = "draft_config_card"
    DRAFT_APPROVAL = "draft_approval"
