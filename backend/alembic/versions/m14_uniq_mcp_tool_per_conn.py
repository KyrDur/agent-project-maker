"""M14: partial unique index — (user_id, connection_id, name) WHERE type='mcp'

Revision ID: m14_uniq_mcp_tool_per_conn
Revises: m13_drop_mcp_legacy
Create Date: 2026-04-25

`POST /api/connections/{id}/discover-tools` 按 user_id × connection × name 维度
承诺 idempotency，但两个并发请求若针对同一 name 都在 existing snapshot 中
read-after-snapshot 未命中，就可能生成重复 Tool row（Codex
adversarial Finding）。应用层防护（IntegrityError catch + savepoint）将该
partial unique index 作为最终安全网。

范围：仅适用于 type='mcp' 的行 — PREBUILT/CUSTOM/BUILTIN 的 connection_id
可以为 NULL，name 也可以自由重复。

PostgreSQL/SQLite 均支持 partial unique index（SQLite 3.8+）。

## Pre-check 策略（运维安全网）
M6.1 之前没有 unique 防护，因此 dev/stg 环境中可能残留 (user, connection, name)
重复 mcp tool row。本次迁移**不会 silent dedupe**
**不会执行** — 因为 `agent_tools.tool_id` 使用 ON DELETE CASCADE，任意 dedupe 会连同 agent
绑定一起 silently 丢失。运维人员必须明确清理后重新执行。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m14_uniq_mcp_tool_per_conn"
down_revision = "m13_drop_mcp_legacy"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_mcp_tools_user_connection_name"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Pre-check：若存在重复则 fail-fast。silent DELETE 会通过 agent_tools.tool_id
    # 的 ON DELETE CASCADE 连同 agent 绑定一起删除，因此危险。
    # 引导运维人员 manual repair 后重新执行。
    dup_groups = bind.execute(
        sa.text(
            """
            SELECT user_id, connection_id, name, COUNT(*) AS cnt
            FROM tools
            WHERE type = 'mcp'
              AND user_id IS NOT NULL
              AND connection_id IS NOT NULL
            GROUP BY user_id, connection_id, name
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """
        )
    ).fetchall()
    if dup_groups:
        sample = "\n".join(
            f"  - user={row[0]} conn={row[1]} name={row[2]!r}: {row[3]} rows" for row in dup_groups
        )
        raise RuntimeError(
            "M14 preflight failed — duplicate (user_id, connection_id, name) MCP "
            "tool rows detected. Resolve manually before retrying.\n"
            "agent_tools.tool_id is ON DELETE CASCADE, so silent dedupe would "
            "drop agent bindings to the deleted rows. Required steps:\n"
            "1) Pick the canonical Tool id per (user, connection, name) group.\n"
            "2) UPDATE agent_tools SET tool_id=<canonical> WHERE tool_id IN <duplicates>.\n"
            "3) DELETE FROM tools WHERE id IN <duplicates>.\n"
            "4) Re-run alembic upgrade.\n"
            f"Sample groups (top 5):\n{sample}"
        )

    # partial unique index — 仅适用于 type='mcp' 的行
    if dialect == "postgresql":
        op.create_index(
            INDEX_NAME,
            "tools",
            ["user_id", "connection_id", "name"],
            unique=True,
            postgresql_where=sa.text("type = 'mcp'"),
        )
    elif dialect == "sqlite":
        # SQLAlchemy 2.x：不支持 sqlite_where 参数。使用 raw DDL。
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX {INDEX_NAME} "
                "ON tools (user_id, connection_id, name) "
                "WHERE type = 'mcp'"
            )
        )
    else:
        # 未知 dialect — 安全起见使用普通 unique index（应用于所有行）
        op.create_index(
            INDEX_NAME,
            "tools",
            ["user_id", "connection_id", "name"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="tools")
