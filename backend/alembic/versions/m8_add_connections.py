"""M8: add connections table (parallel run, no existing code touched)

Revision ID: m8_add_connections
Revises: m7_add_credential_field_keys
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m8_add_connections"
down_revision = "m7_add_credential_field_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("extra_config", sa.JSON(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credentials.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connections_user_type_provider",
        "connections",
        ["user_id", "type", "provider_name"],
    )
    # Partial unique index — 在 DB 层强制"每个 scope 最多 1 个 default"不变量。
    # 应用层 count+clear+insert 模式在并发请求下可能发生 race（Codex adversarial
    # P2：两个请求同时以 default=true insert → 两者都保留为 default）。
    # SQLite 3.8+ / PostgreSQL 均支持 partial unique index。
    op.create_index(
        "uq_connections_one_default_per_scope",
        "connections",
        ["user_id", "type", "provider_name"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    # IF EXISTS：即使是在旧版 m8 未创建 partial unique index 的 DB 中，
    # 也能安全 downgrade（只防御新增索引）。本表/索引
    # 从一开始就成对管理，因此按默认方式 drop。
    op.execute("DROP INDEX IF EXISTS uq_connections_one_default_per_scope")
    op.drop_index("ix_connections_user_type_provider", table_name="connections")
    op.drop_table("connections")
