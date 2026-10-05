from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from app.agent_runtime.runtime_policy import LEGACY_RUNTIME_POLICY, ResolvedRuntimePolicy
from app.config import settings

_configured_data_root = Path(settings.data_root)
_DATA_DIR = (
    _configured_data_root
    if _configured_data_root.is_absolute()
    else Path(__file__).resolve().parents[2] / _configured_data_root
)


def runtime_data_dir() -> Path:
    """Return the current agent-runtime data root.

    Tests patch ``_DATA_DIR`` per isolated lane, so callers intentionally read
    it through this function at operation time rather than import time.
    """

    return _DATA_DIR


@dataclass
class AgentConfig:
    """Agent 执行所需的设置集合。简化 executor 共用函数的签名。

    Multi-user (ADR-016 §6) — 生产入口点(``routers/conversations.py``,
    ``trigger_executor``)必须始终同时填充 ``agent_id`` 和 ``user_id``。
    ``__post_init__`` 会在只设置其中一个时（尤其是存在 ``agent_id``
    但 ``user_id`` 为空的情况）立即用 ``ValueError`` 拦截，避免
    hook framework / 权限追踪 silently 降为 None。
    DB-free 单元测试在两个字段都为空时仍按原方式通过。
    """

    provider: str
    model_name: str
    api_key: str | None
    base_url: str | None
    system_prompt: str
    tools_config: list[dict[str, Any]]
    thread_id: str
    # Additive public-facade field. Keep it keyword-only so legacy callers that
    # pass ``model_params`` (and later fields) positionally retain their exact
    # argument mapping.
    runtime_policy: ResolvedRuntimePolicy = field(
        default=LEGACY_RUNTIME_POLICY,
        kw_only=True,
    )
    model_params: dict[str, Any] | None = None
    middleware_configs: list[dict[str, Any]] | None = None
    agent_skills: list[dict[str, Any]] | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    provider_api_keys: dict[str, str | None] | None = None
    cost_per_input_token: float | None = None
    cost_per_output_token: float | None = None
    # Single source of truth for the model context limit (``models.context_window``).
    # Forwarded into the LangChain ``model.profile`` so deepagents' auto
    # SummarizationMiddleware triggers at ``0.85 × context_window`` — the same
    # number the chat context gauge reads. ``None`` keeps deepagents' own
    # profile/170k fallback (backward compatible for internal sub-agents).
    context_window: int | None = None
    # Hook framework correlation — populated by router/trigger executor.
    # NOTE: 设置 ``agent_id`` 后，也必须设置 ``user_id``
    # （``__post_init__`` guard）。不匹配则 ValueError。
    user_id: str | None = None
    model_id: str | None = None
    llm_credential_id: str | None = None
    agent_owner_user_id: str | None = None
    caller_user_id: str | None = None
    credential_subject_user_id: str | None = None
    identity_mode: str | None = None
    agent_runtime_name: str | None = None
    subagents_config: list[dict[str, Any]] | None = None
    subagent_display_names: dict[str, str] | None = None
    # W2-3 memory recall visibility — briefs of the long-term memory records
    # injected into this run's system prompt. Populated by the component
    # builder (``_load_memory_context``) during prepare, then shipped once per
    # run as the ``moldy.memory_recalled`` stream-head event (same contract as
    # ``subagent_display_names``). ``None``/empty → no event.
    recalled_memories: list[dict[str, Any]] | None = None
    # Skill Studio phase 1（AD-1/AD-2/AD-5）— 若值不是 ``standard``，
    # ``_prepare_runtime_components`` 会走专用分支（Builder 提示词/工具/草稿
    # mount）。``resolve_agent_context`` 从 Agent.runtime_profile
    # 读取并填充。
    runtime_profile: str = "standard"
    # Builder session 上下文 — 通过 conversation_id 反向引用解析出的 session 标识符与
    # ADR-018 相对 workspace 路径。供工具 closure/权限 mount 使用。
    skill_builder_session_id: str | None = None
    draft_workspace_path: str | None = None
    # AD-5 ``moldy.skill_draft`` stream-head payload（recalled_memories 协议）。
    # 不携带文件内容 — 仅摘要（路径/大小/变更数）（§6-7）。
    skill_draft_brief: dict[str, Any] | None = None
    # AD-4 scoped consent — 本 session 中允许无需审批卡即可执行的工具名。
    # ``resolve_agent_context`` 读取 session.tool_consents，并按**当前草稿的
    # requires_network 状态重新验证后**填充。prepare 分支会从 interrupt
    # 策略中排除。finalize_skill 绝不包含在内。
    skill_builder_consented_tools: list[str] | None = None
    # AD-4 — 在审批卡中显示 "留出本次会议的剩余时间" 选项的工具名。
    # eligible − consented −（若草稿 requires_network 则全部排除）。
    # runner 会在 interrupt wire 的 review_configs 中以 ``session_consent_eligible``
    # flag 进行注释（langchain ReviewConfig 不会保留额外键，因此
    # 由我们的 wire 层注入）。
    skill_builder_consent_offer_tools: list[str] | None = None
    # Optional ordered fallback chain. Each entry is
    # ``{"provider": str, "model_name": str, "base_url": str | None,
    #   "model_id": str | None}`` and is tried in order when the primary
    # ``create_chat_model`` raises a recoverable error. Resolved by the
    # caller (chat_service / trigger_executor) so the executor stays free of
    # DB dependencies.
    model_fallback_chain: list[dict[str, Any]] | None = None
    # M-CHAT1b — when set, agent runs are forked off this LangGraph checkpoint
    # (used by edit / regenerate to branch off an earlier message instead of
    # appending to the thread tip).
    checkpoint_id: str | None = None
    # ADR-021 — plaintext secret values injected into this run (LLM api_key,
    # tool/MCP credentials, transport headers). Gathered eagerly by
    # ``conversation_stream_service`` and seeded into the run-scoped redaction
    # ContextVar by ``_run_agent_stream``; skill credentials union in lazily.
    # ``default_factory=set`` keeps it per-instance mutable (never shared) and
    # DB-free unit tests get an empty set with unchanged behaviour.
    secret_values: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        # ADR-016 §6 — 生产 callsite（``conversations`` router、
        # ``trigger_executor``）会同时填充 ``agent_id`` + ``user_id``。
        # 如果在只填充一侧的状态下调用 hook framework，权限追踪会
        # silently 降为 None，导致无法追踪“是谁的调用”。
        # 立即 fail-fast。
        if self.agent_id and not self.user_id:
            raise ValueError(
                "AgentConfig.user_id is required when agent_id is set "
                "(production callsite forgot to propagate authenticated user)."
            )


@dataclass
class RuntimeComponents:
    model_candidates: list[BaseChatModel]
    model: BaseChatModel
    tools: list[BaseTool]
    middleware: list[Any]
    system_prompt: str
    skills_sources: list[str] | None
    backend: Any | None
    memory_sources: list[str] | None
    permissions: list[FilesystemPermission]
    interrupt_on: dict[str, Any] | None
