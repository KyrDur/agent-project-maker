from __future__ import annotations

import shutil
import uuid
import zipfile
import zlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from anyio.to_thread import run_sync
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.skill import Skill
from app.models.skill_builder_session import JsonValue
from app.models.skill_revision import SkillRevision
from app.services.skill_locks import lock_skill_for_mutation
from app.services.skill_revision_storage import write_skill_revision_snapshot
from app.skills import service as skill_service
from app.skills.display_limits import DISPLAY_TEXT_SNIFF_BYTES, MAX_DISPLAY_TEXT_BYTES
from app.skills.inspector import parse_skill_md
from app.skills.moldy_metadata import (
    credential_requirements_from_metadata,
    execution_profile_from_metadata,
    parse_moldy_metadata_content,
)
from app.skills.package_metadata import refresh_package_metadata, sync_frontmatter
from app.skills.packager import PackageError, extract_package
from app.storage.paths import resolve_data_path

# revision 文件 path 上限 — 与 content endpoint Query 边界及列表过滤共享
# （zip entry 名称最长可达 65,535 字节；若不对称，会出现列表里有但无法打开的
# 文件，R6）。
MAX_REVISION_FILE_PATH_CHARS = 4096


async def create_revision_for_skill(
    db: AsyncSession,
    *,
    skill: Skill,
    user_id: uuid.UUID,
    operation: str,
    source_session_id: uuid.UUID | None = None,
    parent_revision_id: uuid.UUID | None = None,
    restored_from_revision_id: uuid.UUID | None = None,
    changed_files: list[JsonValue] | None = None,
    changelog_summary: str | None = None,
    changelog_items: list[JsonValue] | None = None,
    compatibility_result: dict[str, JsonValue] | None = None,
    evaluation_summary: dict[str, JsonValue] | None = None,
    metadata_json: dict[str, JsonValue] | None = None,
) -> SkillRevision:
    revision_number = await _next_revision_number(db, skill.id)
    snapshot = await write_skill_revision_snapshot(skill, revision_number=revision_number)
    revision = SkillRevision(
        skill_id=skill.id,
        user_id=user_id,
        source_session_id=source_session_id,
        parent_revision_id=parent_revision_id,
        restored_from_revision_id=restored_from_revision_id,
        revision_number=revision_number,
        operation=operation,
        skill_version=skill.version,
        content_hash=skill.content_hash,
        storage_provider=snapshot.storage_provider,
        object_key=snapshot.object_key,
        size_bytes=snapshot.size_bytes,
        file_count=snapshot.file_count,
        changed_files=changed_files,
        changelog_summary=changelog_summary,
        changelog_items=changelog_items,
        compatibility_result=compatibility_result,
        evaluation_summary=evaluation_summary,
        metadata_json=metadata_json or {},
    )
    db.add(revision)
    await db.flush()
    skill.current_revision_id = revision.id
    await db.flush()
    return revision


async def list_revisions(
    db: AsyncSession,
    *,
    skill: Skill,
    user_id: uuid.UUID,
    limit: int | None = 100,
) -> list[SkillRevision]:
    """revision 列表（最新优先）。

    ``limit=None`` 表示全量枚举 — 供 retention prune 等语义上需要无限遍历的
    消费方使用。若只看默认 100 窗口，窗口外（>第 100 个）的 revision 会永久
    漏出 prune 范围，导致 snapshot 磁盘泄漏这一潜在契约破坏（R5）。
    """
    if skill.user_id != user_id:
        return []
    stmt = (
        select(SkillRevision)
        .where(SkillRevision.skill_id == skill.id, SkillRevision.user_id == user_id)
        .order_by(desc(SkillRevision.revision_number))
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_revision(
    db: AsyncSession,
    *,
    skill: Skill,
    user_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> SkillRevision | None:
    if skill.user_id != user_id:
        return None
    result = await db.execute(
        select(SkillRevision).where(
            SkillRevision.id == revision_id,
            SkillRevision.skill_id == skill.id,
            SkillRevision.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def rollback_to_revision(
    db: AsyncSession,
    *,
    skill: Skill,
    user_id: uuid.UUID,
    revision: SkillRevision,
    changelog_summary: str | None = None,
) -> SkillRevision:
    if skill.user_id != user_id or revision.skill_id != skill.id:
        raise SkillRevisionNotFound("revision not found")
    if snapshot_pruned(revision):
        raise SkillRevisionRollbackUnsupported("revision snapshot was pruned")
    skill = await lock_skill_for_mutation(db, skill=skill)
    parent_revision_id = skill.current_revision_id
    try:
        zip_bytes = await run_sync(_read_revision_bytes, revision.object_key)
    except FileNotFoundError as exc:
        raise SkillRevisionSnapshotMissing("revision snapshot file is missing") from exc
    if skill.kind == "text":
        try:
            content = await run_sync(_read_skill_md, zip_bytes)
        except (zipfile.BadZipFile, zlib.error, KeyError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError: CRC 正常但包含非 UTF-8 字节的 snapshot —
            # decode 错误不是在 zip read，而是在这里抛出（R7）。
            raise SkillRevisionSnapshotMissing("revision snapshot is unreadable") from exc
        try:
            # update_text_content 在 write 前也会做同样解析，但仍必须在这里
            # 预验证，使"snapshot 不可用"类别（legacy frontmatter 等）与兄弟
            # case（丢失/损坏）一起收敛到相同 409，避免 500 不对称（R6）。
            # yaml.YAMLError: frontmatter.loads 的 parser 错误不属于 ValueError 系列
            # （只有 SkillMetadataError 是 ValueError）— 损坏的 YAML frontmatter
            # 不应得到与缺少 frontmatter 不同的响应（R7）。
            parse_skill_md(content, require_metadata=True)
        except (ValueError, yaml.YAMLError) as exc:
            raise SkillRevisionSnapshotMissing("revision snapshot SKILL.md is invalid") from exc
        await skill_service.update_text_content(db, skill=skill, content=content)
    else:
        if not skill.storage_path:
            raise SkillRevisionRollbackUnsupported("package skill has no storage path")
        # validate-then-mutate: 在破坏性替换（rmtree）之前验证 zip 完整性和 SKILL.md
        # 存在性。若替换后再失败，磁盘已经变化而只有 DB
        # 回滚，会产生发散，因此所有"snapshot 不可用"类别都要在这里拦截，
        # 以无变更 409 结束（R5）。
        await run_sync(_validate_package_snapshot, zip_bytes)
        await run_sync(_replace_package_files, skill.storage_path, zip_bytes)
        refresh_package_metadata(skill)
        sync_frontmatter(skill, skill_service.get_file_bytes(skill, "SKILL.md"))
        _sync_moldy_runtime_columns(skill)
        # 与兄弟 package mutation（file_service.set_skill_file）一样更新修改时间
        # — 保持列表排序（last_modified_at desc）与 UI 时间戳一致（R5）。
        # naive UTC — 与列/兄弟 _now() 使用相同约定。
        skill.last_modified_at = datetime.now(UTC).replace(tzinfo=None)
        await db.flush()
    return await create_revision_for_skill(
        db,
        skill=skill,
        user_id=user_id,
        operation="rollback",
        parent_revision_id=parent_revision_id,
        restored_from_revision_id=revision.id,
        changelog_summary=changelog_summary,
    )


async def _next_revision_number(db: AsyncSession, skill_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.max(SkillRevision.revision_number)).where(SkillRevision.skill_id == skill_id)
    )
    current = result.scalar_one_or_none()
    if current is None:
        return 1
    return int(current) + 1


def snapshot_pruned(revision: SkillRevision) -> bool:
    return bool((revision.metadata_json or {}).get("snapshot_pruned"))


async def list_revision_files(revision: SkillRevision) -> list[tuple[str, int, bool]] | None:
    """revision snapshot zip 文件列表 — (path, size, is_binary)。

    不提取到磁盘，只通过 central directory + head sniff 做随机访问读取
    （不加载全部 bytes，无 zip-slip 表面）。pruned 在调用前通过
    ``snapshot_pruned`` 过滤，**若 zip 在磁盘上不存在则返回 None**
    （没有 pruned flag 但文件丢失的 snapshot — router 与 pruned 相同处理，
    返回明确响应而不是 500）。
    """

    return await run_sync(_list_revision_files_sync, revision.object_key)


async def load_revision_file_content(revision: SkillRevision, relative_path: str) -> str | None:
    """revision snapshot 的单文件文本 — 仅当与枚举路径**完全一致**时。

    traversal 以匹配失败（None→404）结束。二进制（空字节）·超过上限·
    snapshot 丢失也返回 None — 显示层 fail-closed（与草稿 rail viewer 相同，
    上限正本为 app.skills.display_limits）。
    """

    return await run_sync(_load_revision_file_content_sync, revision.object_key, relative_path)


def _list_revision_files_sync(object_key: str) -> list[tuple[str, int, bool]] | None:
    try:
        archive = zipfile.ZipFile(_revision_snapshot_path(object_key))
    except (FileNotFoundError, zipfile.BadZipFile):
        # 不仅丢失，损坏（中断写入等）也与 pruned 使用相同契约 — 禁止 500（R5）。
        return None
    entries: list[tuple[str, int, bool]] = []
    try:
        with archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                # 与 content endpoint path 上限对称 — 不生成“列表里有但无法打开”的
                # entry（R6）。
                if len(info.filename) > MAX_REVISION_FILE_PATH_CHARS:
                    continue
                with archive.open(info) as handle:
                    sniff = handle.read(DISPLAY_TEXT_SNIFF_BYTES)
                entries.append((info.filename, info.file_size, b"\x00" in sniff))
    except (zipfile.BadZipFile, zlib.error):
        # central directory 正常但 member 字节损坏（Bad CRC 等）— 即使通过 open 时
        # 的检查，也要按同一契约处理（R6）。
        return None
    entries.sort(key=lambda entry: entry[0])
    return entries


def _load_revision_file_content_sync(object_key: str, relative_path: str) -> str | None:
    try:
        archive = zipfile.ZipFile(_revision_snapshot_path(object_key))
    except (FileNotFoundError, zipfile.BadZipFile):
        return None
    with archive:
        try:
            info = archive.getinfo(relative_path)
        except KeyError:
            return None
        if info.is_dir():
            return None
        # 不信任 header 的 file_size，而是将流读取到上限+1进行验证。
        # member 字节损坏（Bad CRC/zlib）不是在 open，而是在 read 时抛出（R6）。
        try:
            with archive.open(info) as handle:
                raw = handle.read(MAX_DISPLAY_TEXT_BYTES + 1)
        except (zipfile.BadZipFile, zlib.error):
            return None
        if len(raw) > MAX_DISPLAY_TEXT_BYTES or b"\x00" in raw:
            return None
        return raw.decode("utf-8", errors="replace")


def _sync_moldy_runtime_columns(skill: Skill) -> None:
    try:
        raw = skill_service.get_file_bytes(skill, "agents/moldy.yaml").decode("utf-8")
    except FileNotFoundError:
        metadata: dict[str, JsonValue] = {}
    else:
        parsed, _issues = parse_moldy_metadata_content(raw)
        metadata = parsed
    requirements = credential_requirements_from_metadata(metadata)
    profile = execution_profile_from_metadata(metadata)
    skill.credential_requirements = [dict(item) for item in requirements] or None
    skill.execution_profile = dict(profile) or None


class SkillRevisionNotFound(LookupError):
    pass


class SkillRevisionRollbackUnsupported(RuntimeError):
    pass


class SkillRevisionSnapshotMissing(RuntimeError):
    """snapshot 丢失/损坏 — 必须只发生在磁盘**未变更**状态下。

    router 只将该异常（+RollbackUnsupported）映射为 409。若把 mutation 之后的
    FileNotFoundError 也吞成 409，部分 mutation 会隐藏在"什么都没发生"的响应后面
    （R5）。
    """


def _revision_snapshot_path(object_key: str) -> Path:
    path = (Path(settings.data_root) / object_key).resolve()
    root = Path(settings.data_root).resolve()
    if not path.is_relative_to(root):
        raise ValueError("skill revision path escapes data root")
    return path


def _read_revision_bytes(object_key: str) -> bytes:
    return _revision_snapshot_path(object_key).read_bytes()


def _read_skill_md(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        return archive.read("SKILL.md").decode("utf-8")


def _validate_package_snapshot(zip_bytes: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
            names = set(archive.namelist())
            # 即使 central directory 正常，member 字节也可能因 bitrot/部分写入而损坏，
            # 必须通过 testzip 全量检查 CRC，避免 extract 阶段 500（R6）。
            corrupt_member = archive.testzip()
            skill_md = archive.read("SKILL.md") if "SKILL.md" in names else None
    except (zipfile.BadZipFile, zlib.error) as exc:
        raise SkillRevisionSnapshotMissing("revision snapshot zip is corrupt") from exc
    if corrupt_member is not None:
        raise SkillRevisionSnapshotMissing(
            f"revision snapshot member is corrupt: {corrupt_member!r}"
        )
    if skill_md is None:
        raise SkillRevisionSnapshotMissing("revision snapshot is missing SKILL.md")
    try:
        # mutation 前连可解析性也要验证 — extract_package 内部解析 YAML
        # 的 parser 错误不是 PackageError（只包装 SkillMetadataError），因此必须在这里
        # 拦截，才能与缺少 frontmatter 的兄弟 case 收敛到相同 409（R7）。
        parse_skill_md(skill_md, require_metadata=True)
    except (ValueError, yaml.YAMLError) as exc:
        raise SkillRevisionSnapshotMissing("revision snapshot SKILL.md is invalid") from exc


def _replace_package_files(storage_path: str, zip_bytes: bytes) -> None:
    root = resolve_data_path(storage_path)
    with TemporaryDirectory() as temp_dir:
        extracted = Path(temp_dir) / "skill"
        try:
            # 提取在 tempdir 中、且发生在 rmtree **之前** — 这里的拒绝（zip-slip/symlink/
            # 空字节、PackageError）均无 mutation，因此收敛到 409 契约（R6）。
            # yaml.YAMLError: extract 内部 SKILL.md 解析只会包装 SkillMetadataError
            # 为 PackageError — validate 已预验证，但这里继续 belt-and-braces（R7）。
            extract_package(zip_bytes, extracted)
        except (PackageError, yaml.YAMLError) as exc:
            raise SkillRevisionSnapshotMissing("revision snapshot package is invalid") from exc
        if root.exists():
            shutil.rmtree(root)
        shutil.copytree(extracted, root)
