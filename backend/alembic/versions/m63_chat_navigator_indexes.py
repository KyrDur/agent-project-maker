"""M63: chat navigator keyset pagination indexes.

添加包含 source 列的复合索引，并删除 2 个 M53 conversations 索引。
原先使用这些被删除索引的查询都包含 source equality 条件，或者
仅靠 leading agent_id 列就足够，因此可由新索引替代（ORDER BY DESC
可通过 ASC 索引的 backward scan 覆盖，因此方向无关）。

不带 source 条件、仅依赖 leading agent_id 的查询，是 agent_service.py 中的聚合
共 3 处（list_agents, list_agent_summaries, get_agent）。新
索引宽度从 2→4 列，这些查询的扫描 I/O 可能略有增加，但
agent_id prefix 匹配仍然有效。
"""

from __future__ import annotations

from alembic import op

revision = "m63_chat_navigator_indexes"
down_revision = "m62_blueprint_cred_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_agent_source_pinned_updated_id",
        "conversations",
        ["agent_id", "source", "is_pinned", "updated_at", "id"],
    )
    op.create_index(
        "ix_conversations_agent_source_pinned_created_id",
        "conversations",
        ["agent_id", "source", "is_pinned", "created_at", "id"],
    )
    op.create_index(
        "ix_conversations_agent_source_updated_id",
        "conversations",
        ["agent_id", "source", "updated_at", "id"],
    )
    op.create_index(
        "ix_conversations_agent_source_created_id",
        "conversations",
        ["agent_id", "source", "created_at", "id"],
    )
    op.create_index(
        "ix_conversations_source_updated_id_agent",
        "conversations",
        ["source", "updated_at", "id", "agent_id"],
    )
    op.create_index(
        "ix_conversations_source_created_id_agent",
        "conversations",
        ["source", "created_at", "id", "agent_id"],
    )
    op.create_index("ix_agents_user_id_id", "agents", ["user_id", "id"])
    # 使用这些索引的查询要么包含 source equality，要么仅用 leading agent_id 就足够
    # — 全部由新索引替代
    op.drop_index("ix_conversations_agent_pinned_updated_id", table_name="conversations")
    op.drop_index("ix_conversations_agent_updated", table_name="conversations")


def downgrade() -> None:
    op.create_index(
        "ix_conversations_agent_updated",
        "conversations",
        ["agent_id", "updated_at"],
    )
    op.create_index(
        "ix_conversations_agent_pinned_updated_id",
        "conversations",
        ["agent_id", "is_pinned", "updated_at", "id"],
    )
    op.drop_index("ix_agents_user_id_id", table_name="agents")
    op.drop_index("ix_conversations_source_created_id_agent", table_name="conversations")
    op.drop_index("ix_conversations_source_updated_id_agent", table_name="conversations")
    op.drop_index("ix_conversations_agent_source_created_id", table_name="conversations")
    op.drop_index("ix_conversations_agent_source_updated_id", table_name="conversations")
    op.drop_index(
        "ix_conversations_agent_source_pinned_created_id",
        table_name="conversations",
    )
    op.drop_index(
        "ix_conversations_agent_source_pinned_updated_id",
        table_name="conversations",
    )
