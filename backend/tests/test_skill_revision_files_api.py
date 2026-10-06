"""版本快照文件 API (Phase 2 — 版本 diff/源查看)。

zip 不解压到磁盘，内容查询仅允许与枚举路径**精确匹配** —
验证 traversal/二进制/2MB 超限/pruned 全部返回 404(fail-closed) 的契约。
"""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.skill import Skill
from app.models.skill_revision import SkillRevision
from app.services import skill_revision_service
from app.skills import service as skill_service
from tests.conftest import TEST_USER_ID

pytestmark = pytest.mark.asyncio

OTHER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000bb")

_BODY = "Use when summarizing meeting notes."


def _skill_content() -> str:
    return (
        "---\n"
        "name: notes\n"
        'description: "Use when summarizing notes into action items."\n'
        "---\n\n"
        f"{_BODY}\n"
    )


@pytest.fixture(autouse=True)
def _tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_root", str(tmp_path))


async def _make_skill_with_revision(db: AsyncSession) -> tuple[Skill, SkillRevision]:
    skill = await skill_service.create_text_skill(
        db,
        user_id=TEST_USER_ID,
        name="Notes",
        slug="notes",
        description="Use when summarizing notes.",
        content=_skill_content(),
    )
    revision = await skill_revision_service.create_revision_for_skill(
        db,
        skill=skill,
        user_id=TEST_USER_ID,
        operation="create",
        changelog_summary="Initial version",
    )
    await db.commit()
    return skill, revision


def _rewrite_snapshot(revision: SkillRevision, entries: dict[str, bytes]) -> None:
    """将快照 zip 替换为任意内容 — 用于组装二进制/上限用例。"""

    path = Path(settings.data_root) / revision.object_key
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            archive.writestr(name, content)


async def test_files_lists_snapshot_entries(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    skill, revision = await _make_skill_with_revision(db)

    response = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshot_pruned"] is False
    assert [entry["path"] for entry in body["files"]] == ["SKILL.md"]
    assert body["files"][0]["is_binary"] is False
    assert body["files"][0]["size"] > 0


async def test_file_content_exact_match_only(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    skill, revision = await _make_skill_with_revision(db)
    base = f"/api/skills/{skill.id}/revisions/{revision.id}/files/content"

    ok = await client.get(base, params={"path": "SKILL.md"})
    assert ok.status_code == 200, ok.text
    assert _BODY in ok.json()["content"]
    assert ok.json()["path"] == "SKILL.md"

    for bad_path in ("../SKILL.md", "missing.md", "SKILL.md/"):
        missing = await client.get(base, params={"path": bad_path})
        assert missing.status_code == 404, bad_path


async def test_binary_entry_marked_and_content_blocked(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(
        revision,
        {
            "SKILL.md": _skill_content().encode("utf-8"),
            "assets/logo.png": b"\x89PNG\x00\x00binary-bytes",
        },
    )

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    by_path = {entry["path"]: entry for entry in files.json()["files"]}
    assert by_path["assets/logo.png"]["is_binary"] is True
    assert by_path["SKILL.md"]["is_binary"] is False

    blocked = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "assets/logo.png"},
    )
    assert blocked.status_code == 404


async def test_oversize_entry_content_blocked(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(
        revision,
        {"big.md": b"a" * (2 * 1024 * 1024 + 1)},
    )

    blocked = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "big.md"},
    )
    assert blocked.status_code == 404


async def test_missing_snapshot_zip_treated_as_pruned_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """无 pruned 标志且只丢失 zip 的快照 — 采用 pruned 契约而非 500（评审 R）。"""

    skill, revision = await _make_skill_with_revision(db)
    (Path(settings.data_root) / revision.object_key).unlink()

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    assert files.json() == {"snapshot_pruned": True, "files": []}

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "SKILL.md"},
    )
    assert content.status_code == 404


async def test_pruned_snapshot_explicit_and_content_404(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    skill, revision = await _make_skill_with_revision(db)
    revision.metadata_json = {"snapshot_pruned": True}
    await db.commit()

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    assert files.json() == {"snapshot_pruned": True, "files": []}

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "SKILL.md"},
    )
    assert content.status_code == 404


async def test_binary_sniff_boundary_contract(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """锁定 8KB sniff 不对称契约 — 首个空字节位于 8KB 之后的文件会在列表中
    显示为文本(is_binary=False)，但 content 通过全量检查返回 404(fail-closed)。
    若有人把 content 检查'统一'为 head-sniff，此测试会变红。"""

    skill, revision = await _make_skill_with_revision(db)
    late_null = b"a" * 9000 + b"\x00" + b"b" * 10
    _rewrite_snapshot(revision, {"late-null.md": late_null})

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    entry = files.json()["files"][0]
    assert entry["path"] == "late-null.md"
    assert entry["is_binary"] is False  # head 8KB 中没有空字节

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "late-null.md"},
    )
    assert content.status_code == 404  # 全量检查为 fail-closed


async def test_exact_display_cap_is_served(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """恰好 2MB 的文件返回 200 — 若上限比较从 > 回归为 >=，测试变红。"""

    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(revision, {"exact.md": b"a" * (2 * 1024 * 1024)})

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "exact.md"},
    )
    assert content.status_code == 200, content.text
    assert len(content.json()["content"]) == 2 * 1024 * 1024


async def test_rollback_pruned_snapshot_conflict_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """pruned/zip 丢失版本 rollback 返回显式 409 — 与 files/content 对称。"""

    skill, revision = await _make_skill_with_revision(db)
    revision.metadata_json = {"snapshot_pruned": True}
    await db.commit()

    pruned = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert pruned.status_code == 409, pruned.text
    assert pruned.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"

    revision.metadata_json = {}
    await db.commit()
    (Path(settings.data_root) / revision.object_key).unlink()

    missing = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert missing.status_code == 409, missing.text


async def test_corrupt_snapshot_zip_treated_as_unavailable_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """因中断写入等造成的损坏 zip — 与丢失采用相同契约（禁止 500，R5）。"""

    skill, revision = await _make_skill_with_revision(db)
    (Path(settings.data_root) / revision.object_key).write_bytes(b"not-a-zip")

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    assert files.json() == {"snapshot_pruned": True, "files": []}

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "SKILL.md"},
    )
    assert content.status_code == 404

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


def _corrupt_member_bytes(path: Path) -> None:
    """保留 central directory，仅损坏第一个成员的压缩数据 — 组装
    open 成功但在 read(CRC/zlib) 时失败的类型 (R6)。"""

    data = bytearray(path.read_bytes())
    # local header 30B + filename('SKILL.md'=8B) 之后是压缩流。
    for offset in range(40, 46):
        data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


async def test_member_level_corruption_treated_as_unavailable_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """成员字节损坏(Bad CRC/zlib) — 即使通过 open 检查，也与丢失采用相同契约 (R6)。"""

    skill, revision = await _make_skill_with_revision(db)
    _corrupt_member_bytes(Path(settings.data_root) / revision.object_key)

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    assert files.json() == {"snapshot_pruned": True, "files": []}

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": "SKILL.md"},
    )
    assert content.status_code == 404

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


async def test_snapshot_invalid_frontmatter_rollback_conflict_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """frontmatter 契约之前的旧版 SKILL.md 快照 rollback — 与兄弟情况
    （丢失/损坏/SKILL.md 缺失）统一为 409，磁盘无修改 (R6)。"""

    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(revision, {"SKILL.md": b"no frontmatter at all"})

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


async def test_snapshot_malformed_yaml_rollback_conflict_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """损坏的 YAML frontmatter — frontmatter.loads 的 ParserError 不属于 ValueError
    系列，因此曾与 frontmatter 缺失(409)产生不同响应 (R7)。"""

    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(revision, {"SKILL.md": b"---\nname: [unclosed\n---\nbody\n"})

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


async def test_snapshot_non_string_yaml_key_rollback_conflict_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """non-string 顶层 YAML 键(`on:`) — frontmatter 的 Post(**kw) 会抛出 TypeError，
    穿过 (ValueError, YAMLError) tuple。通过 parse_skill_md leaf
    标准化为与兄弟类别相同的 409 (R8)。"""

    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(
        revision,
        {"SKILL.md": b"---\non: pushed\nname: x\ndescription: y\n---\nbody\n"},
    )

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


async def test_snapshot_non_utf8_rollback_conflict_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """CRC 正常但非 UTF-8 的 SKILL.md — decode 在 zip read 之外失败，
    若不单独处理会返回 500（读取 API 则以 errors='replace' 提供服务，存在不对称，R7）。"""

    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(revision, {"SKILL.md": b"\xff\xfe not utf-8 bytes"})

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


async def test_overlong_entry_path_excluded_from_files_list(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """超过 content Query 上限(4096)的条目也从列表中排除 — 通过共享常量封闭
    “列表可见但无法打开”的不对称 (R6)。"""

    skill, revision = await _make_skill_with_revision(db)
    overlong = "/".join(["deep"] * 900) + "/leaf.md"  # 4500字符+
    assert len(overlong) > 4096
    _rewrite_snapshot(revision, {"SKILL.md": b"ok", overlong: b"unreachable"})

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    assert [entry["path"] for entry in files.json()["files"]] == ["SKILL.md"]


async def test_snapshot_without_skill_md_rollback_conflict_not_500(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """缺少 SKILL.md 的快照 rollback — 通过变更前验证返回 409 (R5)。"""

    skill, revision = await _make_skill_with_revision(db)
    _rewrite_snapshot(revision, {"notes.md": b"no skill md"})

    rollback = await client.post(f"/api/skills/{skill.id}/revisions/{revision.id}/rollback")
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["error"]["code"] == "SKILL_REVISION_SNAPSHOT_UNAVAILABLE"


async def test_long_entry_path_content_served(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """超过 500 字符的嵌套路径也与列表对称地提供服务 — 防止“列表可见但
    content 因 422 无法打开”的不对称 (R5)。"""

    skill, revision = await _make_skill_with_revision(db)
    long_path = "/".join(["deep"] * 130) + "/leaf.md"  # 650字符+
    assert len(long_path) > 500
    _rewrite_snapshot(revision, {long_path: b"deep content"})

    files = await client.get(f"/api/skills/{skill.id}/revisions/{revision.id}/files")
    assert files.status_code == 200, files.text
    assert files.json()["files"][0]["path"] == long_path

    content = await client.get(
        f"/api/skills/{skill.id}/revisions/{revision.id}/files/content",
        params={"path": long_path},
    )
    assert content.status_code == 200, content.text
    assert content.json()["content"] == "deep content"


async def test_foreign_skill_revision_files_404(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """其他用户的技能无论是否存在都返回 404 — enumeration-safe。"""

    foreign_skill = Skill(
        id=uuid.uuid4(),
        user_id=OTHER_USER_ID,
        name="foreign",
        slug="foreign",
        description=None,
        kind="text",
        storage_path=None,
        content_hash=None,
        size_bytes=0,
        version=None,
        package_metadata=None,
        used_by_count=0,
    )
    db.add(foreign_skill)
    await db.flush()
    foreign_revision = SkillRevision(
        skill_id=foreign_skill.id,
        user_id=OTHER_USER_ID,
        revision_number=1,
        operation="create",
        storage_provider="local",
        object_key=f"skill-revisions/{foreign_skill.id}/r1/skill.zip",
        size_bytes=0,
        file_count=0,
        metadata_json={},
    )
    db.add(foreign_revision)
    await db.commit()

    files = await client.get(
        f"/api/skills/{foreign_skill.id}/revisions/{foreign_revision.id}/files"
    )
    assert files.status_code == 404
    content = await client.get(
        f"/api/skills/{foreign_skill.id}/revisions/{foreign_revision.id}/files/content",
        params={"path": "SKILL.md"},
    )
    assert content.status_code == 404
