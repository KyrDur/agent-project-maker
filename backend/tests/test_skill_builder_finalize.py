"""finalize_skill 编排 (M5, 规范 AD-3)。

创建/改进/SOURCE_SKILL_CHANGED/secret scan 阻断/slug 冲突/包含二进制 asset
(Phase 1.5 磁盘 zip)/幂等 + 审计事件(confirm_create/apply_improvement/
apply_conflict/secret_scan_blocked/skill_revision.create) + 完成深链载荷。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_event import AuditEvent
from app.models.skill import Skill
from app.models.skill_builder_session import SkillBuilderSession
from app.models.skill_revision import SkillRevision
from app.services import skill_draft_workspace as workspace
from app.services.skill_builder_finalize import finalize_draft_session
from tests.conftest import TEST_USER_ID
from tests.skill_builder_test_helpers import configure_system_llm

pytestmark = pytest.mark.asyncio

BASE = "/api/skill-builder"


@pytest.fixture(autouse=True)
def _tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_root", str(tmp_path))


def _skill_md(name: str = "notes", body: str = "Use when summarizing meeting notes.") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        'description: "Use when summarizing notes into action items."\n'
        "---\n\n"
        f"{body}\n"
    )


async def _make_create_session(
    db: AsyncSession, *, skill_md: str | None = None
) -> SkillBuilderSession:
    session = SkillBuilderSession(
        user_id=TEST_USER_ID,
        user_request="会议纪要技能",
        status="active",
    )
    db.add(session)
    await db.flush()
    path = workspace.create_workspace(session.id)
    root = workspace.resolve_workspace_dir(path)
    (root / "SKILL.md").write_text(skill_md or _skill_md(), encoding="utf-8")
    session.draft_workspace_path = path
    await db.commit()
    return session


async def _audit_actions(db: AsyncSession) -> set[str]:
    result = await db.execute(select(AuditEvent.action))
    return {row[0] for row in result.all()}


# ---------------------------------------------------------------------------
# 创建 (create)
# ---------------------------------------------------------------------------


async def test_finalize_create_produces_skill_revision_and_deeplink(
    db: AsyncSession,
) -> None:
    session = await _make_create_session(db)

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert "error_code" not in result, result
    assert result["slug"] == "notes"
    assert result["deeplink"] == f"/skills/{result['skill_id']}/source"
    assert result["validation_result"]["valid"] is True

    skill = await db.get(Skill, uuid.UUID(result["skill_id"]))
    assert skill is not None
    assert skill.kind == "package"
    assert skill.user_id == TEST_USER_ID

    revision = await db.scalar(select(SkillRevision).where(SkillRevision.skill_id == skill.id))
    assert revision is not None
    assert revision.operation == "builder_create"
    assert revision.source_session_id == session.id

    await db.refresh(session)
    assert session.status == "completed"
    assert session.finalized_skill_id == skill.id

    actions = await _audit_actions(db)
    assert "skill_builder.confirm_create" in actions
    assert "skill_revision.create" in actions


async def test_finalize_is_idempotent_after_completion(db: AsyncSession) -> None:
    session = await _make_create_session(db)

    first = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)
    second = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert second["skill_id"] == first["skill_id"]


async def test_finalize_create_resolves_slug_conflict(db: AsyncSession) -> None:
    from app.skills import service as skill_service

    await skill_service.create_text_skill(
        db,
        user_id=TEST_USER_ID,
        name="Notes",
        slug="notes",
        description="Use when summarizing notes.",
        content=_skill_md(),
    )
    await db.commit()
    session = await _make_create_session(db)

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert "error_code" not in result, result
    assert result["slug"] != "notes"
    assert result["slug"].startswith("notes")


async def test_finalize_blocks_secret_bearing_draft(db: AsyncSession) -> None:
    secret_body = "Use when summarizing meeting notes.\n\nexport AWS_SECRET_ACCESS_KEY=abc123\n"
    session = await _make_create_session(db, skill_md=_skill_md(body=secret_body))

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert result["error_code"] == "VALIDATION_FAILED"
    codes = {issue["code"] for issue in result["validation_result"]["issues"]}
    assert "SECRET_DETECTED" in codes
    assert "skill_builder.secret_scan_blocked" in await _audit_actions(db)
    # 确认失败 — 不会生成 skills row。
    assert await db.scalar(select(Skill.id)) is None


PNG_BYTES = b"\x89PNG\x00\x00binary"


async def test_finalize_create_includes_binary_asset(db: AsyncSession) -> None:
    """Phase 1.5 — 基于磁盘的 zip 绕过 text 适配器以保留二进制。"""

    from app.storage.paths import resolve_data_path

    session = await _make_create_session(db)
    root = workspace.resolve_workspace_dir(session.draft_workspace_path or "")
    (root / "assets").mkdir()
    (root / "assets" / "logo.png").write_bytes(PNG_BYTES)
    # inputs/（测试输入）不是包内容 — 用于确认 export 排除。
    (root / "inputs").mkdir()
    (root / "inputs" / "example.csv").write_text("a,b\n", encoding="utf-8")

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert "error_code" not in result, result
    skill = await db.get(Skill, uuid.UUID(result["skill_id"]))
    assert skill is not None
    stored_root = resolve_data_path(skill.storage_path or "")
    assert (stored_root / "assets" / "logo.png").read_bytes() == PNG_BYTES
    assert not (stored_root / "inputs").exists()


async def test_finalize_blocks_secret_smuggled_in_null_byte_file(db: AsyncSession) -> None:
    """前置空字节的文件会被 text 适配器（验证扫描源）排除，
    但会进入磁盘 zip — 工作区辅助扫描必须补上这个缺口
    (Phase 1.5 评审)。"""

    session = await _make_create_session(db)
    root = workspace.resolve_workspace_dir(session.draft_workspace_path or "")
    (root / "config.txt").write_bytes(b"\x00export AWS_SECRET_ACCESS_KEY=abc123\n")

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert result["error_code"] == "VALIDATION_FAILED"
    codes = {issue["code"] for issue in result["validation_result"]["issues"]}
    assert "SECRET_DETECTED" in codes
    assert "skill_builder.secret_scan_blocked" in await _audit_actions(db)
    assert await db.scalar(select(Skill.id)) is None


async def test_finalize_returns_package_invalid_and_releases_claim(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """zip 提取守卫（大小上限）失败时，以 PACKAGE_INVALID 传递原因并释放 claim，
    使重试能够 self-heal（与 SOURCE_SKILL_NOT_FOUND 路径对称）。"""

    session = await _make_create_session(db)
    root = workspace.resolve_workspace_dir(session.draft_workspace_path or "")
    (root / "assets").mkdir()
    (root / "assets" / "big.bin").write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(settings, "skill_max_package_bytes", 1024)

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert result["error_code"] == "PACKAGE_INVALID"
    await db.refresh(session)
    assert session.status == "review"  # CONFIRMING 锁必须已释放。

    # 重试不会被 CONFIRMING 门槛阻断。
    second = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)
    assert second["error_code"] == "PACKAGE_INVALID"


# ---------------------------------------------------------------------------
# 改进 (improve) — 使用通过 start v2 初始化的会话
# ---------------------------------------------------------------------------


async def _start_improve_session(
    client: AsyncClient, db: AsyncSession
) -> tuple[SkillBuilderSession, Skill]:
    from app.skills import service as skill_service

    await configure_system_llm(db)
    source = await skill_service.create_text_skill(
        db,
        user_id=TEST_USER_ID,
        name="Notes",
        slug="notes",
        description="Use when summarizing notes.",
        content=_skill_md(),
    )
    await db.commit()

    start = await client.post(
        BASE,
        json={
            "mode": "improve",
            "source_skill_id": str(source.id),
            "user_request": "更准确一些",
        },
    )
    assert start.status_code == 201, start.text
    session = await db.get(SkillBuilderSession, uuid.UUID(start.json()["id"]))
    assert session is not None
    return session, source


async def test_finalize_improve_replaces_storage_and_creates_revision(
    client: AsyncClient, db: AsyncSession
) -> None:
    session, source = await _start_improve_session(client, db)
    root = workspace.resolve_workspace_dir(session.draft_workspace_path or "")
    (root / "SKILL.md").write_text(
        _skill_md(body="Use when summarizing meeting notes. Improved."),
        encoding="utf-8",
    )

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert "error_code" not in result, result
    assert result["skill_id"] == str(source.id)
    assert result["mode"] == "improve"

    await db.refresh(source)
    assert source.kind == "package"

    revision = await db.scalar(
        select(SkillRevision)
        .where(SkillRevision.skill_id == source.id)
        .order_by(SkillRevision.revision_number.desc())
    )
    assert revision is not None
    assert revision.operation == "builder_improvement"
    assert "skill_builder.apply_improvement" in await _audit_actions(db)


async def test_finalize_improve_preserves_seeded_binary_asset(
    client: AsyncClient, db: AsyncSession
) -> None:
    """improve 初始化原始项中的二进制 asset 在 finalize 后仍保留 (Phase 1.5)。

    简报验证场景 — 初始化一个带 asset（图片）的 package 技能后只修改文本，
    即使再确认，基于磁盘的 zip 也会原样带上 asset。
    """

    import io
    import zipfile

    from app.skills import service as skill_service
    from app.storage.paths import resolve_data_path

    await configure_system_llm(db)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("notes/SKILL.md", _skill_md())
        zf.writestr("notes/assets/logo.png", PNG_BYTES)
    source = await skill_service.create_package_skill(
        db, user_id=TEST_USER_ID, zip_bytes=buffer.getvalue()
    )
    await db.commit()

    start = await client.post(
        BASE,
        json={
            "mode": "improve",
            "source_skill_id": str(source.id),
            "user_request": "更准确一些",
        },
    )
    assert start.status_code == 201, start.text
    session = await db.get(SkillBuilderSession, uuid.UUID(start.json()["id"]))
    assert session is not None
    root = workspace.resolve_workspace_dir(session.draft_workspace_path or "")
    assert (root / "assets" / "logo.png").read_bytes() == PNG_BYTES  # 确认初始化
    (root / "SKILL.md").write_text(
        _skill_md(body="Use when summarizing meeting notes. Improved."),
        encoding="utf-8",
    )

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert "error_code" not in result, result
    await db.refresh(source)
    stored_root = resolve_data_path(source.storage_path or "")
    assert (stored_root / "assets" / "logo.png").read_bytes() == PNG_BYTES


async def test_finalize_improve_conflicts_when_source_changed(
    client: AsyncClient, db: AsyncSession
) -> None:
    session, source = await _start_improve_session(client, db)
    # 复现会话打开期间原始项被修改的情况。
    source.content_hash = "0" * 64
    await db.commit()

    result = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    assert result["error_code"] == "SOURCE_SKILL_CHANGED"
    assert "skill_builder.apply_conflict" in await _audit_actions(db)
    await db.refresh(session)
    assert session.status == "review"
    assert session.finalized_skill_id is None


# ---------------------------------------------------------------------------
# 工具暴露 + HITL 策略（始终显示审批卡，不允许会话同意）
# ---------------------------------------------------------------------------


async def test_finalize_tool_requires_approval_and_never_session_consent() -> None:
    from unittest.mock import MagicMock, patch

    from app.agent_runtime import runtime_component_builder as rcb
    from app.agent_runtime.runtime_config import AgentConfig
    from app.agent_runtime.skill_builder.tools import SESSION_CONSENT_ELIGIBLE_TOOLS

    session_id = uuid.uuid4()
    cfg = AgentConfig(
        provider="openai",
        model_name="gpt-5.4",
        api_key="sk-test",
        base_url=None,
        system_prompt="placeholder",
        tools_config=[],
        thread_id="thread-finalize",
        agent_id="agent-finalize",
        user_id=str(TEST_USER_ID),
        runtime_profile="skill_builder",
        skill_builder_session_id=str(session_id),
        draft_workspace_path=f"skill-drafts/{session_id}",
        # 即使存在 test_skill_draft 同意，也必须保留 finalize_skill 卡片。
        skill_builder_consented_tools=["test_skill_draft"],
    )

    with patch.object(rcb, "create_chat_model", return_value=MagicMock()):
        components = await rcb._prepare_runtime_components(
            cfg,
            is_trigger_mode=False,
            include_ask_user=True,
            include_agent_memory_file=True,
        )

    tool_names = {t.name for t in components.tools}
    assert "finalize_skill" in tool_names

    interrupt_on = components.interrupt_on or {}
    assert interrupt_on["finalize_skill"] == {"allowed_decisions": ["approve", "reject"]}
    assert "test_skill_draft" not in interrupt_on
    assert "finalize_skill" not in SESSION_CONSENT_ELIGIBLE_TOOLS


async def test_finalize_releases_claim_on_source_skill_not_found(
    client: AsyncClient, db: AsyncSession
) -> None:
    """R 后续回归（复查发现）：claim 独立提交 CONFIRMING 后，
    若因 SOURCE_SKILL_NOT_FOUND 失败，必须回到 REVIEW — 否则
    CONFIRMING 门槛会以"另一个 finalize 正在进行"的错误消息
    一直阻断重试直到 abandon 时限（14天）。"""

    from app.services.skill_builder_finalize import finalize_draft_session
    from app.skills import service as skill_service

    session, source = await _start_improve_session(client, db)
    assert session.draft_workspace_path is not None

    # 删除会话引用的原始技能，复现 post-claim 失败。
    await skill_service.delete_skill(db, source)
    await db.commit()

    first = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)
    assert first["error_code"] == "SOURCE_SKILL_NOT_FOUND"

    await db.refresh(session)
    assert session.status == "review"  # CONFIRMING 锁必须已释放。

    # 重试不会被 CONFIRMING 门槛阻断，并会再次报告同一错误(self-heal)。
    second = await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)
    assert second["error_code"] == "SOURCE_SKILL_NOT_FOUND"


async def test_finalize_releases_claim_when_cancelled(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """第 3 次评审回归：运行取消(CancelledError)属于 BaseException，因此会穿过工具/服务的
    Exception 捕获 — 若 claim 释放未通过 shield 完成，
    CONFIRMING 会一直锁到 abandon 时限。"""

    import asyncio as _asyncio

    from app.services import skill_builder_service as sbs
    from app.services.skill_builder_finalize import finalize_draft_session

    session, _source = await _start_improve_session(client, db)

    async def cancelled_confirm(*_args, **_kwargs):
        raise _asyncio.CancelledError()

    monkeypatch.setattr(sbs, "confirm_session", cancelled_confirm)

    with pytest.raises(_asyncio.CancelledError):
        await finalize_draft_session(db, session_id=session.id, user_id=TEST_USER_ID)

    await db.refresh(session)
    assert session.status == "review"  # 必须释放锁，以便可以重试。
