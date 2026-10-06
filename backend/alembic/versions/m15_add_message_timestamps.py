"""M15: conversations.message_timestamps (JSON) — 按消息 idx 持久化 timestamp。

Revision ID: m15_add_message_timestamps
Revises: m14_uniq_mcp_tool_per_conn
Create Date: 2026-04-28

LangChain BaseMessage 没有 timestamp 元数据，因此 list_messages 响应每次调用都会
用 `base_ts + idx*1ms` 重新赋予消息时间。结果是每发送一条新消息，
旧消息的时间也会一起变化，产生异常行为。

该列永久保存 (idx → ISO timestamp) 映射，使消息第一次出现在 list 中时
获得的 timestamp 此后不再变化。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m15_add_message_timestamps"
down_revision = "m14_uniq_mcp_tool_per_conn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "message_timestamps",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "message_timestamps")
