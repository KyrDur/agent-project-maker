"""Builder chat 系统提示词 loader（assistant_agent._load_system_prompt 模式）。"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"

_FALLBACK_PROMPT = (
    "You are Moldy's Skill Builder. Edit the skill draft files under {workspace}/ "
    "incrementally with the filesystem tools (edit_file for existing files), run "
    "validate_skill after meaningful edits, and never store secrets in package files. "
    "Respond in Simplified Chinese (zh-CN) unless the user explicitly requests another language."
)


@functools.cache
def _load_template() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Skill builder prompt file not found: %s, using fallback", _PROMPT_PATH)
        return _FALLBACK_PROMPT


def load_skill_builder_prompt(workspace_path: str) -> str:
    """将 ``{workspace}`` placeholder 替换为 session 虚拟 mount 路径后返回。"""

    virtual = "/" + workspace_path.strip("/") if workspace_path else "/skill-drafts"
    return _load_template().replace("{workspace}", virtual)


__all__ = ["load_skill_builder_prompt"]
