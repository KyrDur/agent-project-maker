"""skill 草稿工作区文件系统服务（规范 AD-2）。

每个会话创建 ``data/skill-drafts/<session_id>/`` 物理目录，运行时将其
挂载到虚拟路径 ``/skill-drafts/<session_id>/``。所有路径都遵循
ADR-018 相对路径契约（``storage/paths``）。

职责：创建 / seed（复制 improve 源）/ 附件→``inputs/`` 复制 /
目录→``SkillDraftFile`` 适配 / GC（基于会话状态）。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.skill_builder_session import SkillBuilderSession
from app.schemas.skill_builder import SkillDraftFile, SkillDraftFileRole
from app.skills.display_limits import DISPLAY_TEXT_SNIFF_BYTES, MAX_DISPLAY_TEXT_BYTES
from app.storage.paths import ensure_relative, resolve_data_path

if TYPE_CHECKING:
    from app.models.message_attachment import MessageAttachment
    from app.models.skill import Skill
    from app.schemas.skill_builder import SkillDraftPackage

logger = logging.getLogger(__name__)

SKILL_DRAFTS_ROOT = "skill-drafts"

# 用户测试输入专用目录 — 不是 skill 包内容，因此在适配器
# （验证/zip 收集）中排除。
INPUTS_DIR = "inputs"

# GC 可删除的会话状态（规范 AD-2）：保留 active/confirming。
GC_DELETABLE_STATUSES = ("completed", "abandoned")

# 适配器从单个文件读取的最大字节数 — 防止验证输入激增。
# 显示层上限的单一正本是 app.skills.display_limits — 与 revision viewer lockstep。
_MAX_ADAPTER_FILE_BYTES = MAX_DISPLAY_TEXT_BYTES


def workspace_storage_path(session_id: uuid.UUID) -> str:
    """相对于 data_root 的会话工作区路径（ADR-018）。"""

    return ensure_relative(f"{SKILL_DRAFTS_ROOT}/{session_id}")


def resolve_workspace_dir(storage_path: str) -> Path:
    """``draft_workspace_path`` 列值 → 绝对路径。"""

    return resolve_data_path(storage_path)


def create_workspace(session_id: uuid.UUID) -> str:
    """创建工作区目录并返回相对 storage path（幂等）。"""

    storage_path = workspace_storage_path(session_id)
    resolve_data_path(storage_path).mkdir(parents=True, exist_ok=True)
    return storage_path


def seed_workspace_from_skill(skill: Skill, session_id: uuid.UUID) -> str:
    """improve 模式 seed — 将源 skill 文件**复制**到工作区。

    遵循 skill mount 的 materialize 先例（``skill_runtime._materialize_skill``）：
    text-kind 为单个 ``SKILL.md`` 文件，package-kind 使用 ``copytree``。
    ``symlinks=False`` — 草稿编辑不能反向影响共享源。
    若源在磁盘上不存在，则警告后从空工作区开始（不判为失败，以便对话中
    Agent 可通过 base_snapshot 说明情况）。
    """

    storage_path = workspace_storage_path(session_id)
    target = resolve_data_path(storage_path)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not skill.storage_path:
        logger.warning("skill draft seed skipped — source path missing: skill=%s", skill.slug)
        target.mkdir(parents=True, exist_ok=True)
        return storage_path

    src = resolve_data_path(skill.storage_path)
    if not src.exists():
        logger.warning(
            "skill draft seed skipped — source missing: skill=%s path=%s",
            skill.slug,
            src,
        )
        target.mkdir(parents=True, exist_ok=True)
        return storage_path
    if src.is_file():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target / "SKILL.md")
    else:
        shutil.copytree(src, target, symlinks=False)
    return storage_path


def copy_attachments_to_inputs(
    storage_path: str,
    attachments: Sequence[MessageAttachment],
) -> list[str]:
    """将对话附件 blob **复制**到 ``<workspace>/inputs/``（禁止 mount，§6-3）。

    返回：已复制的相对路径（``inputs/<名称>``）列表。文件名来自用户输入，
    因此移除路径组件以阻止 traversal，冲突时追加序号。若 blob
    不存在则跳过（允许与 orphan GC 竞争）。
    """

    inputs_dir = resolve_workspace_dir(storage_path) / INPUTS_DIR
    inputs_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for attachment in attachments:
        src = resolve_data_path(attachment.storage_path)
        if not src.is_file():
            logger.warning(
                "attachment copy skipped — blob missing: attachment=%s path=%s",
                attachment.id,
                src,
            )
            continue
        # 文件名 sanitize：移除路径组件（阻止 traversal）+ 防止空名称。
        safe_name = Path(attachment.filename).name or f"attachment-{attachment.id}"
        destination = inputs_dir / safe_name
        counter = 1
        while destination.exists():
            destination = inputs_dir / f"{Path(safe_name).stem}-{counter}{Path(safe_name).suffix}"
            counter += 1
        shutil.copyfile(src, destination)
        copied.append(f"{INPUTS_DIR}/{destination.name}")
    return copied


def load_draft_files(storage_path: str) -> list[SkillDraftFile]:
    """工作区目录 → ``SkillDraftFile`` 列表适配器（text-only）。

    validate 与 finalize 的**验证/元数据**输入契约（规范 AD-3）。
    ``inputs/``（测试输入）不是包内容，因此排除。二进制（含空字节）
    会 skip，其余用 ``errors="replace"`` 解码（遵循 snapshot loader
    先例）。最终 zip 收集由 ``build_workspace_zip_bytes``（基于磁盘）
    负责，因此即使二进制 asset 不在这里，也会包含在包中。
    """

    root = resolve_workspace_dir(storage_path)
    if not root.is_dir():
        return []
    files: list[SkillDraftFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.split("/", 1)[0] == INPUTS_DIR:
            continue
        raw = path.read_bytes()[:_MAX_ADAPTER_FILE_BYTES]
        if b"\x00" in raw:
            logger.debug("draft adapter skipped binary file: %s", relative)
            continue
        files.append(
            SkillDraftFile(
                path=relative,
                content=raw.decode("utf-8", errors="replace"),
                role=role_for_path(relative),
            )
        )
    return files


_BINARY_SNIFF_BYTES = DISPLAY_TEXT_SNIFF_BYTES


def _iter_draft_paths(storage_path: str):
    """使用与适配器相同的过滤器（排除 inputs/、排除 symlink、二进制 sniff skip）
    遍历 (relative_path, disk_path) — **不会读取全部内容**。

    为避免文件列表/单文件查询 API 每次请求都加载整个工作区字节，
    （R2 perf）二进制判断仅限前 8KB sniff。需要全量判断的
    validate/finalize 路径继续使用现有 ``load_draft_files``。

    契约注意：若病态文件的第一个空字节出现在 8KB 之后，这里（列表）仍会显示，
    但 ``load_draft_file_content``（全量重判）会以 None→404 排除 — 显示
    层有意向 fail-closed 方向分化。最终保存（finalize）由
    ``build_workspace_zip_bytes`` 直接从磁盘生成 zip，因此会包含二进制文件
    （Phase 1.5）。
    """

    root = resolve_workspace_dir(storage_path)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.split("/", 1)[0] == INPUTS_DIR:
            continue
        try:
            with path.open("rb") as handle:
                sniff = handle.read(_BINARY_SNIFF_BYTES)
        except OSError:
            continue
        if b"\x00" in sniff:
            continue
        yield relative, path


def list_draft_file_entries(storage_path: str) -> list[tuple[str, int, str]]:
    """文件列表元数据 — (path, size, role)。基于 ``st_size``（不读内容）。"""

    entries: list[tuple[str, int, str]] = []
    for relative, path in _iter_draft_paths(storage_path):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        entries.append((relative, min(size, _MAX_ADAPTER_FILE_BYTES), role_for_path(relative)))
    return entries


def load_draft_file_content(storage_path: str, relative_path: str) -> SkillDraftFile | None:
    """单个文件内容 — 仅当请求路径与枚举路径**完全一致**时读取该文件，
    （traversal 匹配失败 = None，与适配器契约相同）。"""

    for relative, path in _iter_draft_paths(storage_path):
        if relative != relative_path:
            continue
        raw = path.read_bytes()[:_MAX_ADAPTER_FILE_BYTES]
        if b"\x00" in raw:
            return None
        return SkillDraftFile(
            path=relative,
            content=raw.decode("utf-8", errors="replace"),
            role=role_for_path(relative),
        )
    return None


DRAFT_FALLBACK_SLUG = "draft"
_SAFE_SLUG_RE_STR = r"[a-z0-9][a-z0-9_-]{0,63}"


def draft_slug(files: Sequence[SkillDraftFile]) -> str:
    """SKILL.md frontmatter ``name`` → sanitize 后的 slug（失败时为 'draft'）。

    这是 LLM 生成的值，因此严格 sanitize — sandbox materialize 会复制到
    ``runtime_root / slug``，若混入路径组件会造成 traversal。
    """

    import re

    skill_md = next((f for f in files if f.path == "SKILL.md"), None)
    if skill_md is None:
        return DRAFT_FALLBACK_SLUG
    from app.skills.inspector import SkillMetadataError, parse_skill_md

    try:
        parsed = parse_skill_md(skill_md.content, require_metadata=True)
    except SkillMetadataError:
        return DRAFT_FALLBACK_SLUG
    raw = str(parsed["metadata"].get("name") or "").strip().lower()
    match = re.fullmatch(_SAFE_SLUG_RE_STR, raw)
    return match.group(0) if match else DRAFT_FALLBACK_SLUG


def build_draft_package(storage_path: str) -> SkillDraftPackage:
    """工作区目录 → ``SkillDraftPackage``（finalize 输入，M5）。

    name/description 来自 SKILL.md frontmatter，credential_requirements/
    execution_profile 从 ``agents/moldy.yaml`` 派生。解析失败时填入
    占位符，让 confirm 的包验证报告准确的问题。
    """

    from app.schemas.skill_builder import SkillDraftPackage
    from app.skills.inspector import SkillMetadataError, parse_skill_md
    from app.skills.moldy_metadata import (
        credential_requirements_from_metadata,
        execution_profile_from_metadata,
        load_moldy_metadata,
    )

    files = load_draft_files(storage_path)
    name = "Draft Skill"
    description = "(missing SKILL.md description)"
    skill_md = next((f for f in files if f.path == "SKILL.md"), None)
    if skill_md is not None:
        try:
            parsed = parse_skill_md(skill_md.content, require_metadata=True)
            metadata = parsed["metadata"]
            name = str(metadata.get("name") or name)
            description = str(metadata.get("description") or description)
        except SkillMetadataError:
            pass

    moldy_metadata, _issues = load_moldy_metadata({f.path: f for f in files})
    return SkillDraftPackage(
        name=name[:160],
        slug=draft_slug(files),
        description=description[:1000],
        files=files,
        credential_requirements=[
            dict(item) for item in credential_requirements_from_metadata(moldy_metadata)
        ],
        execution_profile=dict(execution_profile_from_metadata(moldy_metadata)),
    )


def build_workspace_zip_bytes(storage_path: str, *, slug: str) -> bytes:
    """工作区磁盘 → ``.skill`` zip（finalize 输入，Phase 1.5）。

    绕过 text 适配器（``load_draft_files``），按原字节保留二进制 asset。
    ``inputs/``（测试输入）与 ``evals/`` 和 text zip 路径一样
    从 export 中排除。
    """

    from app.skills.package_builder import build_skill_zip_bytes_from_dir

    return build_skill_zip_bytes_from_dir(
        slug=slug,
        root=resolve_workspace_dir(storage_path),
        exclude_top_dirs=(INPUTS_DIR,),
    )


def binary_secret_scan_issues(
    storage_path: str, *, known_paths: Collection[str]
) -> list[dict[str, Any]]:
    """对 text 适配器 skip 的（= 未进入验证扫描的）文件执行 secret scan。

    finalize 的 secret 扫描由 ``validate_draft_package`` 将适配器文件
    重建到 tempdir 后运行 — 前置空字节的文件会被适配器 skip，从而
    绕过扫描，但仍原样进入基于磁盘的 zip（Phase 1.5 review gap）。
    在会进入 zip 的范围内（排除 ``inputs/``·``evals/``），只把适配器外文件
    复制到 tempdir，再重新应用 ``scan_package``（文件名模式 + bytes 正则）。
    返回 shape 与 validator 的 SECRET_DETECTED issue 相同。

    成本契约（R2 review）：``known_paths`` 由调用方从已在内存中的适配器
    结果（``draft.files``）派生并传入 — 若在这里再次调用 ``load_draft_files``，
    会重复 full-read 工作区。复制也仅限 content scanner 会读取的
    head（``_MAX_CONTENT_SCAN_BYTES``）— 禁止全量复制大型 asset。
    因为涉及磁盘遍历 + IO，async 调用方应 offload 到线程。
    """

    root = resolve_workspace_dir(storage_path)
    if not root.is_dir():
        return []
    from app.marketplace.secret_scan import _MAX_CONTENT_SCAN_BYTES, scan_package
    from app.skills.package_builder import EXCLUDED_EXPORT_DIRS

    excluded = set(EXCLUDED_EXPORT_DIRS) | {INPUTS_DIR}
    known = set(known_paths)
    issues: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        copied = False
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if relative.split("/", 1)[0] in excluded or relative in known:
                continue
            target = temp_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            # head-only 复制 — filename scanner 只看名称，content scanner 只看 head
            # 因此（secret_scan._check_content）复制更多内容只是浪费。
            with path.open("rb") as source, target.open("wb") as sink:
                sink.write(source.read(_MAX_CONTENT_SCAN_BYTES))
            copied = True
        if not copied:
            return []
        for finding in scan_package(temp_root):
            issues.append(
                {
                    "code": "SECRET_DETECTED",
                    "severity": "error",
                    "path": finding.path,
                    "message": f"Potential secret detected by {finding.kind} scanner.",
                    "finding_kind": finding.kind,
                }
            )
    return issues


def draft_execution_profile(storage_path: str) -> dict[str, object]:
    """草稿的 execution_profile（以 ``agents/moldy.yaml`` 为准，不存在则为 {}）。"""

    files = load_draft_files(storage_path)
    by_path = {f.path: f for f in files}
    from app.skills.moldy_metadata import (
        execution_profile_from_metadata,
        load_moldy_metadata,
    )

    metadata, _issues = load_moldy_metadata(by_path)
    return dict(execution_profile_from_metadata(metadata))


def draft_requires_network(storage_path: str) -> bool:
    """会话同意资格 gate（AD-4 边界）— 每次重新评估当前草稿状态。

    记录同意后，草稿仍可能变为 ``requires_network: true``，因此在
    记录同意时和应用策略时**两边**都必须检查此函数。
    """

    return bool(draft_execution_profile(storage_path).get("requires_network"))


async def copy_conversation_attachments_to_inputs(
    db: AsyncSession,
    *,
    storage_path: str,
    attachment_ids: Sequence[uuid.UUID],
    user_id: uuid.UUID,
) -> list[str]:
    """run 开始时将刚关联的附件复制到 ``inputs/``（包含所有权过滤）。"""

    if not attachment_ids:
        return []
    from app.models.message_attachment import MessageAttachment

    result = await db.execute(
        select(MessageAttachment).where(
            MessageAttachment.id.in_(list(attachment_ids)),
            MessageAttachment.user_id == user_id,
        )
    )
    return copy_attachments_to_inputs(storage_path, list(result.scalars()))


def build_skill_draft_brief(session: SkillBuilderSession) -> dict[str, object]:
    """``moldy.skill_draft`` stream-head payload（AD-5）。

    只承载摘要 — 会话 id/模式/slug/文件路径·大小/相对 base 的变更数。
    **绝不**承载文件内容（§6-7；内容只能通过工具结果/FS 读取）。
    """

    files = load_draft_files(session.draft_workspace_path) if session.draft_workspace_path else []
    base_files: dict[str, str] = {}
    base_snapshot = session.base_snapshot or {}
    raw_files = base_snapshot.get("files")
    if isinstance(raw_files, list):
        for raw in raw_files:
            if not isinstance(raw, dict):
                continue
            raw_path = raw.get("path")
            if isinstance(raw_path, str):
                base_files[raw_path] = str(raw.get("content") or "")

    current_paths = {f.path for f in files}
    changed = sum(1 for f in files if f.path not in base_files or base_files[f.path] != f.content)
    deleted = len(set(base_files) - current_paths)

    slug: str | None = None
    skill_md = next((f for f in files if f.path == "SKILL.md"), None)
    if skill_md is not None:
        from app.skills.inspector import SkillMetadataError, parse_skill_md

        try:
            parsed = parse_skill_md(skill_md.content, require_metadata=True)
            raw_slug = parsed["metadata"].get("name")
            slug = str(raw_slug) if raw_slug else None
        except SkillMetadataError:
            slug = None

    # 验证 rail 状态卡片摘要（M7 — mockup "所需凭据" 行）。
    from app.skills.moldy_metadata import (
        credential_requirements_from_metadata,
        load_moldy_metadata,
    )

    metadata, _issues = load_moldy_metadata({f.path: f for f in files})
    credential_requirement_count = len(credential_requirements_from_metadata(metadata))

    return {
        "session_id": str(session.id),
        "mode": session.mode,
        "slug": slug,
        "file_count": len(files),
        "files": [{"path": f.path, "size": len(f.content)} for f in files[:100]],
        "changed_count": changed + deleted,
        "credential_requirement_count": credential_requirement_count,
    }


async def gc_stale_draft_workspaces(db: AsyncSession, *, retention_hours: int) -> int:
    """清理已完成/已放弃会话的工作区，以及没有会话的 orphan 目录。

    依据的不是 mtime，而是**会话状态**（规范 AD-2）：``active``/``confirming``
    会话在 abandon 时间窗（``skill_draft_abandon_days``，默认 14 天）内
    会保留（即使关闭浏览器几天后回来也能恢复）。若对话丢失，或未完成会话
    超过时间窗，则转换为 ``abandoned``，在下一轮清理中回收
    （R2 — 若没有转换路径，流失会话会永久泄漏）。
    只有 ``completed``/``abandoned`` 在 ``updated_at`` 超过 retention 后才删除，
    并清空 ``draft_workspace_path``。没有 session row 的目录（commit 失败
    残留等）按目录 mtime 删除。执行到 commit（用于 cron 调用）。
    """

    if retention_hours <= 0:
        raise ValueError(f"retention_hours must be >= 1, got {retention_hours}")

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=retention_hours)
    removed = 0

    await _mark_dead_sessions_abandoned(db, cutoff=cutoff)

    result = await db.execute(
        select(SkillBuilderSession).where(
            SkillBuilderSession.status.in_(GC_DELETABLE_STATUSES),
            SkillBuilderSession.updated_at < cutoff,
            SkillBuilderSession.draft_workspace_path.is_not(None),
        )
    )
    for session in result.scalars():
        workspace = resolve_data_path(session.draft_workspace_path or "")
        if workspace.is_dir():
            shutil.rmtree(workspace, ignore_errors=True)
        session.draft_workspace_path = None
        removed += 1
    await db.commit()

    removed += await _gc_orphan_workspace_dirs(db, cutoff=cutoff)
    if removed:
        logger.info("skill draft workspace GC removed %d workspace(s)", removed)
    return removed


async def _mark_dead_sessions_abandoned(db: AsyncSession, *, cutoff: datetime) -> int:
    """将死亡/流失的 v2 会话转换为 ``abandoned``，使其成为状态 GC 的回收对象。

    若只声明 ``abandoned`` 而没有转换路径，GC_DELETABLE_STATUSES 一半会
    成为死规则（R2 review）— 这里是唯一转换点。只转换两类：

    1. **死亡会话** — draft-conversation GC 删除对话，使 ``conversation_id``
       通过 SET NULL 断开的未完成会话（不可恢复）。应用相同 retention cutoff
       （保护刚创建后尚未 attach 的时间窗）。
    2. **长期流失会话** — 对话仍存在，但在 ``skill_draft_abandon_days``
       （默认 14 天）内无活动的未完成会话。保留 active 会话原则（AD-2），
       只防止无限期泄漏。

    为不触碰 v1 legacy 行（无工作区），使用
    ``draft_workspace_path IS NOT NULL`` 缩小范围。
    """

    # 语义上的"禁止重复标记" = 与可删除状态相同的集合 — 复用以防 divergence。
    terminal = GC_DELETABLE_STATUSES
    dead_clause = and_(
        SkillBuilderSession.conversation_id.is_(None),
        SkillBuilderSession.updated_at < cutoff,
    )
    # abandon_days <= 0 表示禁用 idle 规则（只要对话还在就永久保留）—
    # 若强制 max(1)，运维想设 0（关闭）时会变成 1 天。
    if settings.skill_draft_abandon_days > 0:
        abandon_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            days=settings.skill_draft_abandon_days
        )
        stale_clause = or_(dead_clause, SkillBuilderSession.updated_at < abandon_cutoff)
    else:
        stale_clause = dead_clause
    result = await db.execute(
        select(SkillBuilderSession).where(
            SkillBuilderSession.status.not_in(terminal),
            SkillBuilderSession.draft_workspace_path.is_not(None),
            stale_clause,
        )
    )
    marked = 0
    for session in result.scalars():
        session.status = "abandoned"
        marked += 1
    if marked:
        await db.flush()
        logger.info("skill draft GC marked %d dead/stale session(s) abandoned", marked)
    return marked


async def _gc_orphan_workspace_dirs(db: AsyncSession, *, cutoff: datetime) -> int:
    """删除没有 session row 的 ``skill-drafts/`` 子目录（基于 mtime）。"""

    drafts_root = resolve_data_path(SKILL_DRAFTS_ROOT)
    if not drafts_root.is_dir():
        return 0
    removed = 0
    cutoff_ts = cutoff.replace(tzinfo=UTC).timestamp()
    for entry in drafts_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            session_id = uuid.UUID(entry.name)
        except ValueError:
            session_id = None
        if session_id is not None:
            exists = await db.scalar(
                select(SkillBuilderSession.id).where(SkillBuilderSession.id == session_id)
            )
            if exists is not None:
                continue  # 活着的会话 — 由基于状态的 GC 负责。
        try:
            if entry.stat().st_mtime > cutoff_ts:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        except OSError:
            logger.exception("orphan draft workspace GC failed for entry=%s", entry)
    return removed


def role_for_path(path: str) -> SkillDraftFileRole:
    """草稿文件路径 → SkillDraftFile.role（正本 — snapshot loader 也委托它）。"""

    if path == "SKILL.md":
        return "skill"
    if path.startswith("scripts/"):
        return "script"
    if path.startswith("references/"):
        return "reference"
    if path.startswith("assets/"):
        return "asset"
    if path.startswith("agents/"):
        return "metadata"
    if path.startswith("evals/"):
        return "eval"
    return "asset"
