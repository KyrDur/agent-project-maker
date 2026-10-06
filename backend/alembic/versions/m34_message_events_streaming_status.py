"""M34: ``message_events.status`` + ``updated_at`` — W3-out streaming lifecycle.

Revision ID: m34_message_events_streaming_status
Revises: m33_add_linked_message_ids
Create Date: 2026-05-03

W3-out M2 — 跟踪引入 partial flush 后的 turn 状态。

Schema 变更
- ``status VARCHAR(20) NOT NULL DEFAULT 'completed'`` + CHECK 约束
  (``status IN ('streaming','completed','failed')``).
  CHECK 保持 alembic-friendly，并在 SQLite/Postgres 两端行为一致（PG ENUM 的
  in-flight ALTER 成本高且 SQLite 不支持，因此避开）。
- ``updated_at TIMESTAMP NOT NULL DEFAULT now()`` — 每次 partial flush 更新。
- ``idx_message_events_status (conversation_id, status)`` — in-flight turn
  优化查询（M3 GET resume）。

现有 row 安全性
- 添加 ``DEFAULT 'completed' NOT NULL`` 在 PG 11+ 中仅涉及元数据变更
  （无需表 rewrite）。现有 m33 之前的 row 会填充为 ``status='completed'``，
  ``updated_at=now()``，与 W6 / 现有 trace 查询代码兼容。

Production note
- 应用于大型生产表时，应将索引改为 ``CREATE INDEX CONCURRENTLY``
  以避免锁。alembic transactional context 不支持 CONCURRENTLY，
  因此这里使用普通 CREATE INDEX。建议在生产流程中单独处理。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m34_message_events_status"
down_revision = "m33_add_linked_message_ids"
branch_labels = None
depends_on = None


_STATUS_VALUES = ("streaming", "completed", "failed")
_CHECK_NAME = "ck_message_events_status"
_INDEX_NAME = "idx_message_events_status"


def _now_default() -> sa.TextClause:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PG: native ALTER TABLE — fast default（仅元数据）+ CHECK 约束 +
        # CONCURRENTLY index。必须通过 autocommit_block 暂时结束事务，
        # 才允许 CREATE INDEX CONCURRENTLY。
        op.add_column(
            "message_events",
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'completed'"),
            ),
        )
        op.add_column(
            "message_events",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=_now_default(),
            ),
        )
        op.create_check_constraint(
            _CHECK_NAME,
            "message_events",
            sa.column("status").in_(_STATUS_VALUES),
        )
        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
                    "ON message_events (conversation_id, status)"
                )
            )
    else:
        # SQLite：ALTER TABLE 仅 native 支持 ADD COLUMN。CHECK 约束和
        # 部分 nullable 列添加通过 ``batch_alter_table`` 的 copy-and-move
        # 绕过。索引使用普通 create_index（不支持 CONCURRENTLY）。
        with op.batch_alter_table("message_events") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "status",
                    sa.String(20),
                    nullable=False,
                    server_default=sa.text("'completed'"),
                )
            )
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=False),
                    nullable=False,
                    server_default=_now_default(),
                )
            )
            batch_op.create_check_constraint(
                _CHECK_NAME,
                sa.column("status").in_(_STATUS_VALUES),
            )
        op.create_index(
            _INDEX_NAME,
            "message_events",
            ["conversation_id", "status"],
        )


def downgrade() -> None:
    """Downgrade — drops status, updated_at, CHECK, and index.

    ⚠️ NON-RECOVERABLE DATA LOSS：仍处于 'streaming'/'failed' 状态的 row，
    其状态信息会永久丢失。在已合入 partial flush 的生产环境中
    调用此 downgrade，会使这些 row 的 status 消失，导致 W3-out resume
    路径中的 stale 标记分支失效。建议采用 forward-only 运维。

    SQLite 兼容：``op.drop_constraint`` 与 ``op.drop_column`` 通过
    ``batch_alter_table`` 绕过 SQLite 的 ALTER TABLE 限制。PG 使用 native
    ALTER。
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}"))
        op.drop_constraint(_CHECK_NAME, "message_events", type_="check")
        op.drop_column("message_events", "updated_at")
        op.drop_column("message_events", "status")
    else:
        # SQLite 不支持 ALTER TABLE DROP CONSTRAINT / DROP COLUMN，
        # 因此用 batch_alter_table 重建表。索引不支持 CONCURRENTLY，
        # 所以使用普通 drop。
        op.drop_index(_INDEX_NAME, table_name="message_events")
        with op.batch_alter_table("message_events") as batch_op:
            batch_op.drop_constraint(_CHECK_NAME, type_="check")
            batch_op.drop_column("updated_at")
            batch_op.drop_column("status")
