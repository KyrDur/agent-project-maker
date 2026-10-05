"""Skill Builder chat 专用工具（spec AD-3）。

全部复用现有函数 — 验证使用 ``validate_draft_package``（+兼容性），评测生成使用
``select_eval_template``/``generate_eval_cases``。草稿文件编辑本身由
deepagents 标准 FS 工具（``write_file``/``edit_file``）负责，这里的工具
将草稿目录作为 adapter 读取。

DB 访问通过**session factory closure**传入，避免把 request-scoped session
固定到长生命周期 stream 中（memory 工具先例）。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.skill_builder.eval_case_generator import generate_eval_cases
from app.agent_runtime.skill_builder.eval_schema import (
    SkillEvalFile,
    SkillEvalSchemaError,
    parse_evals_json,
)
from app.agent_runtime.skill_builder.eval_templates import select_eval_template
from app.models.skill_builder_session import SkillBuilderSession
from app.services import skill_draft_workspace
from app.skills.validator import validate_draft_package
from app.tools.risk import ToolRiskLevel, attach_tool_risk, risk_metadata_dict

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

EVALS_FILE_PATH = "evals/evals.json"

# AD-4 — 允许 session consent（"留出本次会议的剩余时间"）的工具。finalize_skill
# 绝对禁止包含（始终显示审批卡）；requires_network 草稿会在 runtime 再次
# 被阻止（``skill_draft_workspace.draft_requires_network``）。
SESSION_CONSENT_ELIGIBLE_TOOLS = frozenset({"test_skill_draft"})


class _NoArgs(BaseModel):
    """用于无参数工具的空 schema。"""


class _GenerateEvalsInput(BaseModel):
    intent: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Optional one-line description of what the skill should do. "
            "Defaults to the session's original user request."
        ),
    )


class _TestSkillDraftInput(BaseModel):
    command: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description=(
            "Shell command to run inside the draft skill sandbox (e.g. "
            "'python scripts/run.py inputs/example.csv'). Only the allowlisted "
            "interpreters permitted by the skill execution policy will run."
        ),
    )


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_skill_builder_tools(
    *,
    session_id: str,
    workspace_path: str,
    session_factory: SessionFactory,
    user_id: str | None = None,
    agent_id: str | None = None,
    credential_subject_user_id: str | None = None,
    include_runtime_tools: bool = False,
    consented_tools: Sequence[str] | None = None,
) -> list[BaseTool]:
    """绑定到 Builder session 的工具列表。

    ``include_runtime_tools=True`` 时，同时附加 ``test_skill_draft``（保存前草稿
    sandbox 执行，CODE_EXECUTION risk）和 ``finalize_skill``（确认 — 始终需要审批
    卡）— 仅用于 runtime 分支。DB-free caller（测试等）
    默认只获取 validate/generate。
    """

    try:
        session_uuid = uuid.UUID(session_id)
    except (TypeError, ValueError):
        logger.warning("skill builder tools skipped — bad session id: %r", session_id)
        return []

    async def _load_session(db: AsyncSession) -> SkillBuilderSession | None:
        result = await db.execute(
            select(SkillBuilderSession).where(SkillBuilderSession.id == session_uuid)
        )
        return result.scalar_one_or_none()

    async def validate_skill() -> str:
        """验证草稿并返回结果（只读 + 将结果保存到 session）。"""

        try:
            files = skill_draft_workspace.load_draft_files(workspace_path)
            result = validate_draft_package(files=files)
        except Exception:  # noqa: BLE001 — 工具错误以文本形式传递给模型
            logger.exception("validate_skill failed (session=%s)", session_id)
            return _json_dumps(
                {"error": "validation failed unexpectedly; check draft files and retry"}
            )
        async with session_factory() as db:
            session = await _load_session(db)
            if session is not None:
                session.validation_result = result
                compatibility = result.get("compatibility_result")
                if isinstance(compatibility, dict):
                    session.compatibility_result = compatibility
                await db.commit()
        return _json_dumps({"session_id": session_id, **result})

    async def generate_evals(intent: str | None = None) -> str:
        """生成评测 case，并写入草稿的 ``evals/evals.json``。"""

        effective_intent = (intent or "").strip()
        if not effective_intent:
            async with session_factory() as db:
                session = await _load_session(db)
                effective_intent = (session.user_request if session else "") or "general task"

        skill_md = next(
            (
                f
                for f in skill_draft_workspace.load_draft_files(workspace_path)
                if f.path == "SKILL.md"
            ),
            None,
        )
        template = select_eval_template(
            intent=effective_intent,
            draft_package={"skill_md": skill_md.content} if skill_md else None,
        )
        cases = generate_eval_cases(intent=effective_intent, template=template)
        eval_file = SkillEvalFile(name=template.label, evals=cases)
        content = json.dumps(eval_file.model_dump(mode="json"), ensure_ascii=False, indent=2)
        try:
            parse_evals_json(content)  # schema guard — 写入前进行 round-trip 验证
        except SkillEvalSchemaError:
            logger.exception("generate_evals produced invalid schema (session=%s)", session_id)
            return _json_dumps({"error": "generated evals failed schema validation"})

        target = skill_draft_workspace.resolve_workspace_dir(workspace_path) / EVALS_FILE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return _json_dumps(
            {
                "session_id": session_id,
                "path": EVALS_FILE_PATH,
                "template_key": template.key,
                "case_count": len(cases),
            }
        )

    async def test_skill_draft(command: str) -> str:
        """在 Skill sandbox 中执行草稿（保存前测试，AD-3）。"""

        from app.agent_runtime.skill_builder.eval_runner import run_eval_skill_command
        from app.config import settings
        from app.marketplace.skill_runtime import build_skill_runtime_context

        # session consent fail-closed 重新验证（R2）：consent 仅适用于 run 开始时
        # “requires_network 为否的草稿”，但若 Agent 在同一 turn 内
        # 向 agents/moldy.yaml 添加 requires_network，就会在没有审批卡的情况下打开网络
        # sandbox — 因此在执行时重新读取 profile 并阻止。
        if "test_skill_draft" in (consented_tools or ()) and (
            skill_draft_workspace.draft_requires_network(workspace_path)
        ):
            return (
                "Error: the draft now requires network access (agents/moldy.yaml), "
                "which cannot run under a session consent. Ask the user to run the "
                "test again so it goes through an explicit approval card."
            )
        files = skill_draft_workspace.load_draft_files(workspace_path)
        slug = skill_draft_workspace.draft_slug(files)
        execution_profile = skill_draft_workspace.draft_execution_profile(workspace_path)
        # fabricated descriptor — 不需要 DB row（skill_evaluation_worker_state 先例）。
        # 通过 ``agent_runtime_name=None`` 强制使用 non-agent runtime 根布局，
        # 使其与 run_eval_skill_command 的 slug 路径一致。将 thread_id 固定到 session
        # 后，重新执行会通过 wipe+copy 复用同一 mount，并由基于 mtime 的
        # runtime-root GC 自动清理。
        sandbox_thread_id = f"skill-draft-{session_id}"
        fabricated_cfg = SimpleNamespace(
            thread_id=sandbox_thread_id,
            agent_runtime_name=None,
            agent_skills=[
                {
                    "id": session_id,
                    "slug": slug,
                    "name": slug,
                    "description": "skill draft under test",
                    "storage_path": workspace_path,
                    "execution_profile": execution_profile,
                }
            ],
            credential_subject_user_id=credential_subject_user_id,
            user_id=user_id,
            agent_id=agent_id,
        )
        try:
            data_dir = Path(settings.data_root)
            ctx = build_skill_runtime_context(
                fabricated_cfg,  # type: ignore[arg-type] — duck-typed cfg（先例相同）
                data_dir=data_dir,
                output_root=data_dir / "skill-draft-runs",
            )
            ctx.audit_kind = "skill_builder.draft_test"
            ctx.run_id = session_id
            return await run_eval_skill_command(ctx, skill_slug=slug, command=command)
        except Exception:  # noqa: BLE001 — 工具错误以文本形式传递给模型
            logger.exception("test_skill_draft failed (session=%s)", session_id)
            return "Error: draft test execution failed unexpectedly."

    tools: list[BaseTool] = [
        StructuredTool.from_function(
            coroutine=validate_skill,
            name="validate_skill",
            description=(
                "Validate the current skill draft (SKILL.md metadata, references, "
                "scripts, secrets, portable compatibility). Read-only. Run this after "
                "meaningful edits and before proposing finalization."
            ),
            args_schema=_NoArgs,
        ),
        StructuredTool.from_function(
            coroutine=generate_evals,
            name="generate_evals",
            description=(
                "Generate evaluation cases for the draft and write them to "
                "evals/evals.json inside the draft workspace. Optionally pass a short "
                "intent description; defaults to the session's original request."
            ),
            args_schema=_GenerateEvalsInput,
        ),
    ]

    async def finalize_skill() -> str:
        """确认草稿 — 重新执行验证→secret scan→skills row+revision（M5）。"""

        from app.services.skill_builder_finalize import finalize_draft_session

        if user_id is None:
            return _json_dumps({"error_code": "USER_REQUIRED", "message": "no user context"})
        try:
            owner_uuid = uuid.UUID(user_id)
        except (TypeError, ValueError):
            return _json_dumps({"error_code": "USER_REQUIRED", "message": "bad user context"})
        try:
            async with session_factory() as db:
                result = await finalize_draft_session(
                    db, session_id=session_uuid, user_id=owner_uuid
                )
        except Exception:  # noqa: BLE001 — 工具错误以文本形式传递给模型
            logger.exception("finalize_skill failed (session=%s)", session_id)
            return _json_dumps(
                {"error_code": "FINALIZE_FAILED", "message": "finalize failed unexpectedly"}
            )
        return _json_dumps(result)

    if include_runtime_tools:
        sandbox_tool = StructuredTool.from_function(
            coroutine=test_skill_draft,
            name="test_skill_draft",
            description=(
                "Run a command against the CURRENT draft in the skill sandbox "
                "(unsaved state). Use it to try the skill on the user's examples "
                "(files under inputs/). Requires user approval before running."
            ),
            args_schema=_TestSkillDraftInput,
        )
        # AD-4 — 与 execute_in_skill 相同的 CODE_EXECUTION 风险元数据。默认
        # interrupt 策略会根据该元数据生成审批卡。
        attach_tool_risk(
            sandbox_tool,
            risk_metadata_dict(
                ToolRiskLevel.CODE_EXECUTION,
                allowed_decisions=("approve", "reject"),
                trigger_safe=False,
                reason="test_skill_draft runs draft skill code in the sandbox",
            ),
        )
        tools.append(sandbox_tool)

        finalize_tool = StructuredTool.from_function(
            coroutine=finalize_skill,
            name="finalize_skill",
            description=(
                "Finalize the draft into a real saved skill (re-validates, secret "
                "scan, creates or replaces the skill + revision). Always requires "
                "the user's explicit approval; never call it speculatively."
            ),
            args_schema=_NoArgs,
        )
        # AD-4 — 始终显示审批卡（不可 session consent；SESSION_CONSENT_ELIGIBLE_TOOLS
        # 中绝不包含）。
        attach_tool_risk(
            finalize_tool,
            risk_metadata_dict(
                ToolRiskLevel.WRITE_INTERNAL,
                requires_approval=True,
                allowed_decisions=("approve", "reject"),
                trigger_safe=False,
                reason="finalize_skill persists the draft as a real skill revision",
            ),
        )
        tools.append(finalize_tool)
    return tools


__all__ = ["EVALS_FILE_PATH", "build_skill_builder_tools"]
