from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.schemas.skill_builder import SkillDraftFile
from app.skills.package_builder import (
    build_skill_zip_bytes,
    build_skill_zip_bytes_from_dir,
    normalize_draft_path,
)
from app.skills.packager import extract_package


def _skill_md(name: str = "demo") -> str:
    return f'---\nname: {name}\ndescription: "demo skill"\nversion: "1.0.0"\n---\n\n# Demo\n'


def _draft_file(path: str, content: str) -> SkillDraftFile:
    return SkillDraftFile(path=path, content=content)


def _zip_names(zip_bytes: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return set(zf.namelist())


def test_build_skill_zip_bytes_imports_through_existing_packager(tmp_path: Path) -> None:
    zip_bytes = build_skill_zip_bytes(
        slug="Demo Skill",
        files=[
            _draft_file("SKILL.md", _skill_md()),
            _draft_file("scripts/run.py", "print('ok')\n"),
            _draft_file("references/guide.md", "Use carefully.\n"),
        ],
    )

    info = extract_package(zip_bytes, tmp_path / "skill")

    assert info.name == "demo"
    assert info.files == ["SKILL.md", "references/guide.md", "scripts/run.py"]


def test_build_skill_zip_bytes_requires_skill_md() -> None:
    with pytest.raises(ValueError, match="SKILL.md"):
        build_skill_zip_bytes(
            slug="demo",
            files=[_draft_file("references/guide.md", "hello")],
        )


def test_normalize_draft_path_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="invalid draft file path"):
        normalize_draft_path("../secret.txt")


def test_build_skill_zip_bytes_excludes_evals_by_default() -> None:
    zip_bytes = build_skill_zip_bytes(
        slug="demo",
        files=[
            _draft_file("SKILL.md", _skill_md()),
            _draft_file("evals/evals.json", "{}"),
        ],
    )

    assert _zip_names(zip_bytes) == {"demo/SKILL.md"}


def test_build_skill_zip_bytes_can_include_evals() -> None:
    zip_bytes = build_skill_zip_bytes(
        slug="demo",
        files=[
            _draft_file("SKILL.md", _skill_md()),
            _draft_file("evals/evals.json", "{}"),
        ],
        include_evals=True,
    )

    assert _zip_names(zip_bytes) == {"demo/SKILL.md", "demo/evals/evals.json"}


def test_build_skill_zip_bytes_normalizes_paths_and_slug() -> None:
    zip_bytes = build_skill_zip_bytes(
        slug="Demo Skill!",
        files=[
            _draft_file("/SKILL.md", _skill_md()),
            _draft_file("references\\guide.md", "hello"),
        ],
    )

    assert _zip_names(zip_bytes) == {
        "demo-skill/SKILL.md",
        "demo-skill/references/guide.md",
    }


# ---------------------------------------------------------------------------
# 基于磁盘的 zip (Phase 1.5 — 保留二进制 asset)
# ---------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00binary-payload"


def _make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "assets").mkdir(parents=True)
    (root / "evals").mkdir()
    (root / "inputs").mkdir()
    (root / "SKILL.md").write_text(_skill_md(), encoding="utf-8")
    (root / "assets" / "logo.png").write_bytes(PNG_BYTES)
    (root / "evals" / "evals.json").write_text("{}", encoding="utf-8")
    (root / "inputs" / "example.csv").write_text("a,b\n", encoding="utf-8")
    return root


def test_build_skill_zip_bytes_from_dir_preserves_binary_bytes(tmp_path: Path) -> None:
    root = _make_workspace(tmp_path)

    zip_bytes = build_skill_zip_bytes_from_dir(
        slug="demo",
        root=root,
        exclude_top_dirs=("inputs",),
    )

    assert _zip_names(zip_bytes) == {"demo/SKILL.md", "demo/assets/logo.png"}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        assert zf.read("demo/assets/logo.png") == PNG_BYTES

    # 必须原样通过现有 packager 守卫（zip-slip/size 再验证路径）。
    info = extract_package(zip_bytes, tmp_path / "extracted")
    assert info.files == ["SKILL.md", "assets/logo.png"]
    assert (tmp_path / "extracted" / "assets" / "logo.png").read_bytes() == PNG_BYTES


def test_build_skill_zip_bytes_from_dir_requires_skill_md(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    (root / "references").mkdir(parents=True)
    (root / "references" / "guide.md").write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="SKILL.md"):
        build_skill_zip_bytes_from_dir(slug="demo", root=root)


def test_build_skill_zip_bytes_from_dir_skips_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "SKILL.md").write_text(_skill_md(), encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "leak.txt").symlink_to(outside)

    zip_bytes = build_skill_zip_bytes_from_dir(slug="demo", root=root)

    assert _zip_names(zip_bytes) == {"demo/SKILL.md"}


def test_build_skill_zip_bytes_from_dir_skips_directory_symlinks(tmp_path: Path) -> None:
    """rglob 不跟随目录 symlink 的保证依赖 Python 版本行为，
    （3.12 默认 no-follow）因此用回归测试锁定 — 防止外部树泄漏。"""

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "SKILL.md").write_text(_skill_md(), encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "leakdir").symlink_to(outside_dir, target_is_directory=True)

    zip_bytes = build_skill_zip_bytes_from_dir(slug="demo", root=root)

    assert _zip_names(zip_bytes) == {"demo/SKILL.md"}


def test_build_skill_zip_bytes_from_dir_fails_fast_on_oversized_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """大小上限必须在读取文件前（累计 st_size 时）触发 — 提取阶段的守卫
    在 zip 已经创建到内存之后才触发，太晚。"""

    from app.config import settings
    from app.skills.packager import PackageError

    root = _make_workspace(tmp_path)
    (root / "assets" / "big.bin").write_bytes(b"x" * 4096)
    monkeypatch.setattr(settings, "skill_max_package_bytes", 1024)

    with pytest.raises(PackageError, match="package too large"):
        build_skill_zip_bytes_from_dir(slug="demo", root=root, exclude_top_dirs=("inputs",))


def test_build_skill_zip_bytes_from_dir_can_include_evals(tmp_path: Path) -> None:
    root = _make_workspace(tmp_path)

    zip_bytes = build_skill_zip_bytes_from_dir(
        slug="demo",
        root=root,
        include_evals=True,
        exclude_top_dirs=("inputs",),
    )

    assert "demo/evals/evals.json" in _zip_names(zip_bytes)
