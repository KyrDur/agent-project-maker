"""Centralized error factory functions.

Exception 实例在创建时会捕获 traceback，因此以 factory 函数而非常量提供。
"""

from app.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# NotFoundError (404)
# ---------------------------------------------------------------------------


def agent_not_found() -> NotFoundError:
    return NotFoundError("AGENT_NOT_FOUND", "找不到 Agent")


def conversation_not_found() -> NotFoundError:
    return NotFoundError("CONVERSATION_NOT_FOUND", "找不到对话")


def provider_not_found() -> NotFoundError:
    return NotFoundError("PROVIDER_NOT_FOUND", "找不到 Provider")


def tool_not_found() -> NotFoundError:
    return NotFoundError("TOOL_NOT_FOUND", "找不到工具")


def session_not_found() -> NotFoundError:
    return NotFoundError("SESSION_NOT_FOUND", "找不到 Build Session")


def trigger_not_found() -> NotFoundError:
    return NotFoundError("TRIGGER_NOT_FOUND", "找不到 Trigger")


def model_not_found() -> NotFoundError:
    return NotFoundError("MODEL_NOT_FOUND", "找不到模型")


def template_not_found() -> NotFoundError:
    return NotFoundError("TEMPLATE_NOT_FOUND", "找不到 Template")


def image_not_found() -> NotFoundError:
    return NotFoundError("IMAGE_NOT_FOUND", "找不到图像")


def image_file_not_found() -> NotFoundError:
    return NotFoundError("IMAGE_NOT_FOUND", "找不到图像文件")


def file_not_found() -> NotFoundError:
    return NotFoundError("FILE_NOT_FOUND", "找不到文件")


def skill_not_found() -> NotFoundError:
    return NotFoundError("SKILL_NOT_FOUND", "未找到技能")


def skill_file_not_found() -> NotFoundError:
    return NotFoundError("SKILL_FILE_NOT_FOUND", "找不到 Skill 文件")


def skill_revision_not_found() -> NotFoundError:
    return NotFoundError("SKILL_REVISION_NOT_FOUND", "找不到 Skill 历史记录")


def skill_revision_snapshot_unavailable() -> ConflictError:
    return ConflictError(
        "SKILL_REVISION_SNAPSHOT_UNAVAILABLE",
        "该 Revision 的 Snapshot 已被清理，无法回滚",
    )


def skill_evaluation_set_not_found() -> NotFoundError:
    return NotFoundError("SKILL_EVALUATION_SET_NOT_FOUND", "找不到 Skill Eval Set")


def skill_evaluation_run_not_found() -> NotFoundError:
    return NotFoundError("SKILL_EVALUATION_RUN_NOT_FOUND", "找不到 Skill Eval Run")


def marketplace_item_not_found() -> NotFoundError:
    """Spec §10.7 — emitted for both "doesn't exist" and "forbidden" so
    catalog enumeration via 404 vs 403 is blocked (rules/security.md).
    The branch is recorded server-side only."""
    return NotFoundError("MARKETPLACE_ITEM_NOT_FOUND", "找不到 Marketplace Item")


def marketplace_version_not_found() -> NotFoundError:
    return NotFoundError("MARKETPLACE_VERSION_NOT_FOUND", "找不到 Marketplace Version")


def credential_not_found() -> NotFoundError:
    return NotFoundError("CREDENTIAL_NOT_FOUND", "找不到 Credential")


def share_not_found() -> NotFoundError:
    return NotFoundError("SHARE_NOT_FOUND", "找不到 Share Link")


def memory_not_found() -> NotFoundError:
    return NotFoundError("MEMORY_NOT_FOUND", "找不到 Memory")


def memory_proposal_not_found() -> NotFoundError:
    return NotFoundError(
        "MEMORY_PROPOSAL_NOT_FOUND",
        "找不到 Memory Proposal",
    )


def resume_not_found() -> NotFoundError:
    return NotFoundError("RESUME_NOT_FOUND", "找不到要恢复的 Stream")


def trace_not_found() -> NotFoundError:
    return NotFoundError("TRACE_NOT_FOUND", "找不到 Trace")


def mcp_server_not_found() -> NotFoundError:
    return NotFoundError("MCP_SERVER_NOT_FOUND", "找不到 MCP Server")


def system_credential_not_found() -> NotFoundError:
    return NotFoundError("SYSTEM_CREDENTIAL_NOT_FOUND", "找不到 System Credential")


def unknown_credential_definition(key: str) -> NotFoundError:
    return NotFoundError("UNKNOWN_CREDENTIAL_DEFINITION", f"未知的 Credential 类型：{key}")


def unknown_tool_definition(key: str) -> NotFoundError:
    return NotFoundError("UNKNOWN_TOOL_DEFINITION", f"未知的工具类型：{key}")


def unknown_registry_entry(key: str) -> NotFoundError:
    return NotFoundError("UNKNOWN_REGISTRY_ENTRY", f"未知的 Registry 项：{key}")


# ---------------------------------------------------------------------------
# ValidationError (422)
# ---------------------------------------------------------------------------


def invalid_trigger_type() -> ValidationError:
    return ValidationError(
        "INVALID_TRIGGER_TYPE",
        "trigger_type 必须是 'interval'、'cron'、'one_time' 之一",
    )


def invalid_schedule_config() -> ValidationError:
    return ValidationError(
        "INVALID_SCHEDULE_CONFIG",
        "Schedule 配置不正确",
    )


def agent_identity_requires_fixed() -> ValidationError:
    return ValidationError(
        "AGENT_IDENTITY_REQUIRES_FIXED",
        "自动执行需要使用 Agent 固定 credential (fixed)",
    )


def session_not_preview() -> ValidationError:
    return ValidationError("SESSION_NOT_PREVIEW", "只能确认 Preview 状态的 Session")


def no_draft_config() -> ValidationError:
    return ValidationError("NO_DRAFT_CONFIG", "没有 Draft 配置")


def invalid_file_path() -> ValidationError:
    return ValidationError("INVALID_FILE_PATH", "文件路径无效")


def invalid_skill_package(detail: str) -> ValidationError:
    return ValidationError("INVALID_SKILL_PACKAGE", detail)


def skill_feedback_invalid(detail: str) -> ValidationError:
    return ValidationError("SKILL_FEEDBACK_INVALID", detail)


def marketplace_credential_mismatch(detail: str) -> ValidationError:
    """Spec §10.7 — credential definition_key / requirement_key mismatch
    on a binding write. 400 ``ValidationError`` keeps client-side hints
    actionable (the requirement / definition info is non-sensitive)."""
    return ValidationError("MARKETPLACE_CREDENTIAL_MISMATCH", detail)


def marketplace_invalid_package(detail: str) -> ValidationError:
    """Spec §10.7 — version payload / storage snapshot is unreadable or
    malformed (missing storage_path, missing SKILL.md, copy failure).
    400 because the user can re-publish or pick a different version."""
    return ValidationError("MARKETPLACE_INVALID_PACKAGE", detail)


def marketplace_secret_detected(detail: str) -> ValidationError:
    """Spec §13.1 — secret_scan rejected the package on publish or
    import. 400 with the finding list folded into ``detail`` so the
    operator can remediate without a second round-trip."""
    return ValidationError("MARKETPLACE_SECRET_DETECTED", detail)


def marketplace_invalid_visibility(detail: str) -> ValidationError:
    """Spec §10.7 — invalid visibility transition (e.g. trying to
    publish as ``system`` from a user route)."""
    return ValidationError("MARKETPLACE_INVALID_VISIBILITY", detail)


def marketplace_acl_required() -> ValidationError:
    """Spec §10.7 — ``visibility='restricted'`` requires at least one
    user_id in the ACL. 400 because the user can retry with valid ACL."""
    return ValidationError(
        "MARKETPLACE_ACL_REQUIRED",
        "restricted 可见性至少需要 1 名 ACL 用户",
    )


def marketplace_manage_forbidden() -> ForbiddenError:
    """Spec §10.7 — user is authenticated and *can see* the item, but
    is not its owner / super_user. 403 rather than 404 because the
    existence is already visible (item appeared in the catalog)."""
    return ForbiddenError("MARKETPLACE_MANAGE_FORBIDDEN", "没有管理权限")


def super_user_required() -> ForbiddenError:
    return ForbiddenError("SUPER_USER_REQUIRED", "需要 Operator 权限")


def credential_forbidden() -> ForbiddenError:
    return ForbiddenError("FORBIDDEN", "没有权限")


# ---------------------------------------------------------------------------
# ConflictError (409)
# ---------------------------------------------------------------------------


def session_already_claimed() -> ConflictError:
    return ConflictError(
        "SESSION_ALREADY_CLAIMED",
        "当前已在 Streaming，或不处于 Building 状态",
    )


def trigger_already_running() -> ConflictError:
    return ConflictError(
        "TRIGGER_ALREADY_RUNNING",
        "该 Schedule 已在运行。请等待执行结束后重试",
    )


def session_confirming() -> ConflictError:
    return ConflictError(
        "SESSION_CONFIRMING",
        "Agent 创建已在进行中",
    )


def resume_interrupt_pending() -> ConflictError:
    return ConflictError(
        "RESUME_INTERRUPT_PENDING",
        "正在等待 HiTL interrupt 响应 — 请通过 /messages/resume 恢复",
    )


def marketplace_credential_required(detail: str) -> ConflictError:
    """Spec §10.7 — install/runtime requires a credential that is not yet
    bound. 409 because the install/run flow can be retried after the
    user creates + binds the credential (idempotent)."""
    return ConflictError("MARKETPLACE_CREDENTIAL_REQUIRED", detail)


def system_llm_not_configured() -> ConflictError:
    return ConflictError(
        "SYSTEM_LLM_NOT_CONFIGURED",
        "请先在“我的 AI 配置”中填写自己的 API Key 并选择模型。",
    )


def skill_builder_source_conflict() -> ConflictError:
    return ConflictError(
        "SKILL_BUILDER_SOURCE_CONFLICT",
        "Skill 在 Improvement Session 开始后已发生变更",
    )


def skill_builder_session_not_ready() -> ConflictError:
    return ConflictError(
        "SKILL_BUILDER_SESSION_NOT_READY",
        "需要可供 Review 的 Skill Draft",
    )


def skill_evaluation_run_not_cancellable() -> ConflictError:
    return ConflictError(
        "SKILL_EVALUATION_RUN_NOT_CANCELLABLE",
        "当前 Eval Run 状态不可取消",
    )


def skill_evaluation_queue_full() -> ConflictError:
    return ConflictError(
        "SKILL_EVALUATION_QUEUE_FULL",
        "Skill Eval Run 队列已满",
    )


def marketplace_dirty_installation() -> ConflictError:
    """Spec §10.3 — update requires an explicit ``strategy`` when the
    installation is dirty (the user has edited the installed copy).
    The client must pick overwrite / install_new_copy / keep_current."""
    return ConflictError(
        "MARKETPLACE_DIRTY_INSTALLATION",
        "修改过的安装副本必须指定 Update Strategy",
    )


# ---------------------------------------------------------------------------
# ForbiddenError (403)
# ---------------------------------------------------------------------------


def resume_forbidden() -> ForbiddenError:
    """Reserved — 当前有意不使用。

    在 W3-out M3 阶段，stream resume 的所有权限/存在性拒绝分支
    已统一为单一 ``RESUME_NOT_FOUND`` 响应 (rules/security.md —
    防止 enumeration oracle)。未来若引入明确的 share/public link 等，
    出现“资源已公开可知，仅权限不足”的分支时，该 helper
    可作为复用候选。在此之前保持 declared-but-unused.
    """
    return ForbiddenError("RESUME_FORBIDDEN", "无法访问此对话的 Stream")


# ---------------------------------------------------------------------------
# AppError (generic / 500)
# ---------------------------------------------------------------------------


def agent_creation_failed(
    detail: str = "创建 Agent 时发生错误。请重试。",
) -> AppError:
    return AppError("AGENT_CREATION_FAILED", detail, status=500)
