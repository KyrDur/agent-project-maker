"""M12: drop legacy tool.auth_config / tool.credential_id / agent_tools.config

Revision ID: m12_drop_legacy_columns
Revises: m11_custom_connection
Create Date: 2026-04-21

SCOPE_REDUCED_2 (2026-04-21)：M6 只 drop 三个列。
- tools.auth_config
- tools.credential_id (+ FK fk_tools_credential_id)
- agent_tools.config

mcp_servers 表 + tools.mcp_server_id 延后到 M6.1（需要先完成选项 D）。

## pre-check（生产环境必需）
确认 docs/design-docs/m6-cleanup-migration-spec.md §5.1 (A)(C) 查询后再应用。

额外预检查 — 检查 PREBUILT `provider_name IS NULL` 行：
    SELECT count(*) FROM tools WHERE type = 'prebuilt' AND provider_name IS NULL;
期望为 0。若不为 0，在移除 `_resolve_legacy_tool_auth` 后，这些行会
按 env fallback 评估，语义可能发生变化（此前返回 inline auth_config
）。可能存在 m10 映射遗漏，因此在 migration 前需要对 provider_name 执行回填
or 清理对应 row。

## downgrade
仅恢复结构，数据永久丢失。生产环境回滚应使用 DB 快照恢复。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m12_drop_legacy_columns"
down_revision = "m11_custom_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preflight：若仍有 stale legacy row，则 abort upgrade。由于 drop 会
    # 导致数据永久丢失，因此将 docstring 中的 pre-check 实现为可执行 assertion。
    _assert_no_stale_legacy_rows()

    # 1) FK drop (tools.credential_id → credentials.id)
    #    FK 名称为 m6_add_credentials.py 中明确指定的 "fk_tools_credential_id"。
    op.drop_constraint("fk_tools_credential_id", "tools", type_="foreignkey")

    # 2) drop tools legacy 列
    op.drop_column("tools", "credential_id")
    op.drop_column("tools", "auth_config")

    # 3) agent_tools.config drop
    op.drop_column("agent_tools", "config")


def _assert_no_stale_legacy_rows() -> None:
    """Abort upgrade if any row still depends on the columns we're about to drop.

    在 sqlite in-memory 测试中，conftest 会直接创建最新模型，因此
    legacy 列本身可能不存在。此时跳过检查。
    """
    from app.services.legacy_invariants import collect_legacy_checks

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def column_exists(table: str, column: str) -> bool:
        return column in {c["name"] for c in inspector.get_columns(table)}

    checks = collect_legacy_checks(bind.dialect.name, column_exists)

    errors: list[str] = []
    for label, sql in checks:
        count = bind.execute(sa.text(sql)).scalar() or 0
        if count:
            errors.append(f"  - {label}: {count} row(s)")
    if errors:
        raise RuntimeError(
            "M12 preflight failed — stale legacy rows detected. "
            "Migration aborted to prevent permanent data loss. "
            "Resolve the following before retrying:\n" + "\n".join(errors)
        )


def downgrade() -> None:
    # downgrade: structure only — DATA LOSS IS PERMANENT.
    # tools.auth_config / tools.credential_id、agent_tools.config 的原始
    # 数据不会恢复。若生产环境需要回滚，请不要使用 alembic downgrade，
    # 而应使用 DB 快照恢复。

    # 1) 恢复 agent_tools.config
    op.add_column(
        "agent_tools",
        sa.Column("config", sa.JSON(), nullable=True),
    )

    # 2) 恢复 tools.auth_config
    op.add_column(
        "tools",
        sa.Column("auth_config", sa.JSON(), nullable=True),
    )

    # 3) 恢复 tools.credential_id + FK
    op.add_column(
        "tools",
        sa.Column("credential_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tools_credential_id",
        "tools",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
