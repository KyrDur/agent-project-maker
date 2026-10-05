from __future__ import annotations

import io
import zipfile
from collections.abc import Collection, Sequence
from pathlib import Path, PurePosixPath

from app.config import settings
from app.schemas.skill_builder import SkillDraftFile
from app.skills.packager import PackageError
from app.skills.service import slugify

EXCLUDED_EXPORT_DIRS = frozenset({"evals"})


def normalize_draft_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/").lstrip("/")
    pure = PurePosixPath(cleaned)
    if not cleaned or ".." in pure.parts or "\x00" in cleaned:
        raise ValueError(f"invalid draft file path: {path!r}")
    return pure.as_posix()


def build_skill_zip_bytes(
    *,
    slug: str,
    files: Sequence[SkillDraftFile],
    include_evals: bool = False,
) -> bytes:
    folder = slugify(slug)
    by_path: dict[str, SkillDraftFile] = {}
    for draft_file in files:
        rel_path = normalize_draft_path(draft_file.path)
        top_level = rel_path.split("/", 1)[0]
        if not include_evals and top_level in EXCLUDED_EXPORT_DIRS:
            continue
        by_path[rel_path] = draft_file
    if "SKILL.md" not in by_path:
        raise ValueError("draft package must include SKILL.md")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel_path in sorted(by_path):
            archive.writestr(f"{folder}/{rel_path}", by_path[rel_path].content)
    return buffer.getvalue()


def build_skill_zip_bytes_from_dir(
    *,
    slug: str,
    root: Path,
    include_evals: bool = False,
    exclude_top_dirs: Collection[str] = (),
) -> bytes:
    """磁盘目录 → ``.skill`` zip — 文件按原字节写入。

    text 适配器（``SkillDraftFile.content``）无法表达二进制，
    导致 finalize 时 asset 曾被静默遗漏（Phase 1.5）— 此路径直接以磁盘
    为 zip 源，从而保留二进制。排除 symlink，并通过
    ``normalize_draft_path`` 防护路径。最终安全网仍由
    ``extract_package`` 的 zip-slip/symlink/size guard 再次验证。

    大小上限在遍历时累计 ``st_size``，并在**读取前**检查 —
    ``extract_package`` 的 guard 是在 zip 已全部构建进内存后才检查，
    因此若这里不 fail-fast，超大工作区会在触发上限前
    无限占用内存。
    """

    folder = slugify(slug)
    excluded = set(exclude_top_dirs)
    if not include_evals:
        excluded |= EXCLUDED_EXPORT_DIRS
    entries: dict[str, Path] = {}
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel_path = normalize_draft_path(path.relative_to(root).as_posix())
        if rel_path.split("/", 1)[0] in excluded:
            continue
        total_bytes += path.stat().st_size
        if total_bytes > settings.skill_max_package_bytes:
            raise PackageError(
                f"package too large: {total_bytes} bytes so far "
                f"(max {settings.skill_max_package_bytes})"
            )
        entries[rel_path] = path
    if "SKILL.md" not in entries:
        raise ValueError("draft package must include SKILL.md")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel_path in sorted(entries):
            archive.writestr(f"{folder}/{rel_path}", entries[rel_path].read_bytes())
    return buffer.getvalue()
