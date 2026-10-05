"""``validate_skill``/``finalize_skill`` 工具结果 → ``moldy.skill_validation``
projection（memory_event_projection 模式，spec AD-5）。

payload 原样携带现有 ``validation_result`` schema，使前端验证 rail
复用 v1 panel（ValidationPanel/PortableCompatibilityPanel）。
issues 仅包含 code/severity/message/path — 按验证器协议，不包含文件内容/secret 值
（SecretFinding 仅包含 path+kind，§6-7）。
"""

from __future__ import annotations

import json
from typing import Any, Final

SKILL_VALIDATION_TOOL_NAMES: Final[frozenset[str]] = frozenset({"validate_skill", "finalize_skill"})

# 被视为验证结果的最小 shape — 防止误认任意 JSON 工具结果。
_REQUIRED_KEYS: Final[frozenset[str]] = frozenset({"valid", "issues"})


def skill_validation_event_from_tool_result(
    tool_name: str,
    result: str,
) -> dict[str, Any] | None:
    """从工具结果 JSON 中提取验证 payload（否则返回 ``None``）。"""

    if tool_name not in SKILL_VALIDATION_TOOL_NAMES:
        return None
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    validation = parsed.get("validation_result")
    if not isinstance(validation, dict):
        # validate_skill 的结果 dict 本身就是 validation_result schema。
        validation = parsed
    if not set(validation) >= _REQUIRED_KEYS:
        return None
    payload: dict[str, Any] = {"tool_name": tool_name, "validation_result": validation}
    session_id = parsed.get("session_id")
    if isinstance(session_id, str):
        payload["session_id"] = session_id
    return payload
