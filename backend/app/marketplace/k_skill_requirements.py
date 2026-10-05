"""Curated credential requirements for k-skill imports (Spec §5.6).

The upstream ``NomaDamas/k-skill`` repo ships skills whose runtime
contracts (env var names + which definition_key to bind) aren't
machine-derivable from SKILL.md alone. This module is the *source of
truth* for that mapping — the importer consults it instead of regex-
guessing requirement keys.

``REGEX_HINTS`` is review-only: the importer logs hints discovered in
each skill's source but never auto-attaches them. New k-skill releases
that need a new credential trigger a human review + a PR to this file.

Schema mirrors ``app.marketplace.credential_requirements.CredentialRequirement``
and ``schemas.CredentialRequirementIn`` so the dicts can be fed
directly into ``MarketplaceVersion.credential_requirements`` and
``Skill.credential_requirements``.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Curated map: upstream skill name → requirement entries
# ---------------------------------------------------------------------------


def _account_req(
    key: str,
    *,
    definition_key: str,
    label: str,
    description: str,
    env_user: str,
    env_pass: str,
) -> dict[str, Any]:
    """Two-field username/password account binding. Reused for SRT /
    KTX / forest-trip whose upstream scripts read the same env shape."""

    return {
        "key": key,
        "definition_key": definition_key,
        "required": True,
        "label": label,
        "description": description,
        "fields": ["username", "password"],
        "injection": "env",
        "scope": "user",
        "env_map": {"username": env_user, "password": env_pass},
    }


def _api_key_req(
    key: str,
    *,
    definition_key: str,
    label: str,
    description: str,
    env_name: str,
    required: bool = True,
) -> dict[str, Any]:
    """Single ``api_key`` binding — covers KIPRIS, DART, ODsay."""

    return {
        "key": key,
        "definition_key": definition_key,
        "required": required,
        "label": label,
        "description": description,
        "fields": ["api_key"],
        "injection": "env",
        "scope": "user",
        "env_map": {"api_key": env_name},
    }


def _hosted_proxy_req(
    key: str,
    *,
    label: str,
    description: str,
) -> dict[str, Any]:
    """通过 Operator proxy key 的 skill — 用户无需单独注册 credential
    (PRD §9 ``hosted_proxy`` 状态)。UI 只显示 "Uses hosted proxy" chip，
    install wizard 中不显示 credential dropdown。
    """

    return {
        "key": key,
        "definition_key": "k_skill_proxy",
        "required": False,
        "label": label,
        "description": description,
        "fields": ["base_url"],
        "injection": "env",
        # ``system_dependency`` 标记 (Spec §10.8)。从用户 binding 流程中
        # 排除，并由 system credential resolver 处理。
        "scope": "system_dependency",
        "env_map": {"base_url": "KSKILL_PROXY_BASE_URL"},
    }


def _manual_login_req(
    key: str,
    *,
    label: str,
    description: str,
) -> dict[str, Any]:
    """用户必须在浏览器/本地应用中直接登录的 skill (PRD §9
    ``manual_login``)。UI 以 "Manual login required" 提示标记说明，并在 install
    wizard credential step 中 skip — 实际认证在 skill 执行时由外部
    环境完成。
    """

    return {
        "key": key,
        "definition_key": "",
        "required": False,
        "label": label,
        "description": description,
        "fields": [],
        "injection": "manual",
        "scope": "manual",
        "env_map": {},
    }


# Each entry is a list because future skills may bind more than one
# credential (e.g. Google Workspace OAuth + a project ID API key).
K_SKILL_REQUIREMENT_MAP: dict[str, list[dict[str, Any]]] = {
    # Travel / booking
    "srt-booking": [
        _account_req(
            "srt_login",
            definition_key="srt_account",
            label="SRT账户",
            description="用于 SRT 订票的会员 Credential。",
            env_user="KSKILL_SRT_ID",
            env_pass="KSKILL_SRT_PASSWORD",  # noqa: S106 — env var *name*, not a value
        ),
    ],
    "ktx-booking": [
        _account_req(
            "ktx_login",
            definition_key="ktx_account",
            label="KTX (Korail) 账户",
            description="用于 KTX 订票的 Korail 会员 Credential。",
            env_user="KSKILL_KTX_ID",
            env_pass="KSKILL_KTX_PASSWORD",  # noqa: S106 — env var *name*, not a value
        ),
    ],
    "foresttrip-vacancy": [
        _account_req(
            "foresttrip_login",
            definition_key="foresttrip_account",
            label="森林旅行账户",
            description="用于国家休养林预约查询的会员 Credential。",
            env_user="KSKILL_FORESTTRIP_ID",
            env_pass="KSKILL_FORESTTRIP_PASSWORD",  # noqa: S106 — env var *name*, not a value
        ),
    ],
    # Public-data APIs
    "korean-patent-search": [
        _api_key_req(
            "kipris_key",
            definition_key="kipris_plus_api",
            label="KIPRIS Plus API",
            description="KIPRIS Plus 服务密钥。",
            env_name="KSKILL_KIPRIS_KEY",
        ),
    ],
    "k-dart": [
        _api_key_req(
            "dart_key",
            definition_key="dart_api",
            label="DART Open API",
            description="OpenDART 认证密钥。",
            env_name="KSKILL_DART_KEY",
        ),
    ],
    "korean-transit-route": [
        _api_key_req(
            "odsay_key",
            definition_key="odsay_api",
            label="ODsay API",
            description="ODsay LAB 签发的 apiKey.",
            env_name="KSKILL_ODSAY_KEY",
        ),
    ],
    # Optional — install proceeds even when the credential is missing.
    "coupang-product-search": [
        {
            "key": "coupang_partners",
            "definition_key": "coupang_partners",
            # ``required=False`` → install never blocks. Affiliate-link
            # enrichment is skipped at runtime when the binding is absent.
            "required": False,
            "label": "Coupang Partners (optional)",
            "description": (
                "Coupang Partners Affiliate Key。未配置时搜索仍可工作，但"
                "Affiliate Link 生成功能将被禁用。"
            ),
            "fields": ["access_key", "secret_key"],
            "injection": "env",
            "scope": "user",
            "env_map": {
                "access_key": "KSKILL_COUPANG_ACCESS_KEY",
                "secret_key": "KSKILL_COUPANG_SECRET_KEY",
            },
        }
    ],
    # Hosted proxy — PRD §9 ``hosted_proxy``。使用 Operator proxy key。
    "seoul-density": [
        _hosted_proxy_req(
            "seoul_density_proxy",
            label="首尔实时人口 proxy",
            description="通过 Operator 签发的首尔开放数据广场 proxy 调用。",
        ),
    ],
    # Manual login — PRD §9 ``manual_login``。使用外部 app/browser Session。
    "kakaotalk-mac": [
        _manual_login_req(
            "kakaotalk_macos_session",
            label="KakaoTalk (macOS) Session",
            description="KakaoTalk macOS app 必须在已登录状态下运行。",
        ),
    ],
    # No credentials required.
    "korean-spell-check": [],
}


# ---------------------------------------------------------------------------
# Review-only regex hints
# ---------------------------------------------------------------------------


# When the importer scans a k-skill's source it logs hits against these
# patterns so the next manual review can spot a new credential
# requirement. **Never auto-bound** — the curated map above is the only
# authoritative source.
REGEX_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"KSKILL_[A-Z][A-Z0-9_]+", re.IGNORECASE),
    re.compile(r"API[_-]?KEY", re.IGNORECASE),
    re.compile(r"SECRET[_-]?KEY", re.IGNORECASE),
    re.compile(r"ACCESS[_-]?TOKEN", re.IGNORECASE),
    re.compile(r"os\.environ\[[\"'][A-Z_]+[\"']\]"),
)


def requirements_for(upstream_name: str) -> list[dict[str, Any]]:
    """Return the requirement entries for ``upstream_name``.

    Empty list = "no credentials". ``None`` is never returned — callers
    should not need a missing-key branch.
    """

    return list(K_SKILL_REQUIREMENT_MAP.get(upstream_name, ()))


def known_skills() -> set[str]:
    """Names that are explicitly known to the curated map. Importer
    logs a hint when a new upstream skill is encountered."""

    return set(K_SKILL_REQUIREMENT_MAP)


__all__ = [
    "K_SKILL_REQUIREMENT_MAP",
    "REGEX_HINTS",
    "known_skills",
    "requirements_for",
]
