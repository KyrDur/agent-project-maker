"""M13: drop mcp_servers + tools.mcp_server_id（M6.1 选项 D 后续）

Revision ID: m13_drop_mcp_legacy
Revises: m12_drop_legacy_columns
Create Date: 2026-04-24

M9 中已将数据从 mcp_servers → connections 迁移，M6.1 中通过 PATCH /api/tools/{id}
（选项 D）允许用户直接绑定 connection_id。此次迁移将
永久移除过渡期保留的 legacy 表/列/FK。

顺序（与 FK 依赖方向相反）：
1) tools.mcp_server_id（自动命名 FK = `tools_mcp_server_id_fkey`）→ drop
2) tools.mcp_server_id 列 → drop
3) mcp_servers.credential_id FK (`fk_mcp_servers_credential_id`) → drop
4) mcp_servers 表 → drop

## pre-check
- legacy_invariants.collect_legacy_checks 添加 m13 invariant
  ("MCP tools with legacy mcp_server_id but no connection_id (dead after M6.1)")。
- 若 preflight 不为 0，则 abort。若有 m9 回填遗漏 row，先回填 connection_id 后再重试。

## downgrade
仅恢复结构。数据永久丢失。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import exc as sa_exc

from alembic import op

revision = "m13_drop_mcp_legacy"
down_revision = "m12_drop_legacy_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _assert_no_stale_legacy_rows()

    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # 1) drop tools.mcp_server_id FK + 列
    if not is_sqlite:
        op.drop_constraint("tools_mcp_server_id_fkey", "tools", type_="foreignkey")
    op.drop_column("tools", "mcp_server_id")

    # 2) drop mcp_servers.credential_id FK（由 m6_add_credentials add）
    if not is_sqlite:
        op.drop_constraint("fk_mcp_servers_credential_id", "mcp_servers", type_="foreignkey")

    # 3) drop mcp_servers 表
    op.drop_table("mcp_servers")


def _assert_no_stale_legacy_rows() -> None:
    """tools.mcp_server_id IS NOT NULL AND connection_id IS NULL → abort.

    若仍存在 m9 mapping 遗漏 row，drop 后 chat runtime 会 fail-closed。
    legacy_invariants 已包含 m13 invariant，因此这里只委托调用。
    """
    from app.services.legacy_invariants import collect_legacy_checks

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def column_exists(table: str, column: str) -> bool:
        try:
            return column in {c["name"] for c in inspector.get_columns(table)}
        except sa_exc.NoSuchTableError:
            return False

    checks = collect_legacy_checks(bind.dialect.name, column_exists)

    errors: list[str] = []
    for label, sql in checks:
        try:
            count = bind.execute(sa.text(sql)).scalar() or 0
        except Exception:  # noqa: BLE001
            # 对于表已消失的 sqlite 场景等 — 继续下一项检查。
            continue
        if count:
            errors.append(f"  - {label}: {count} row(s)")
    if errors:
        raise RuntimeError(
            "M13 preflight failed — stale legacy rows detected. "
            "Migration aborted to prevent permanent data loss. "
            "Resolve the following before retrying:\n" + "\n".join(errors)
        )


def downgrade() -> None:
    # downgrade: structure only — DATA LOSS IS PERMANENT.
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("auth_type", sa.String(length=20), nullable=False),
        sa.Column("auth_config", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_mcp_servers_credential_id",
        "mcp_servers",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "tools",
        sa.Column("mcp_server_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "tools_mcp_server_id_fkey",
        "tools",
        "mcp_servers",
        ["mcp_server_id"],
        ["id"],
    )
