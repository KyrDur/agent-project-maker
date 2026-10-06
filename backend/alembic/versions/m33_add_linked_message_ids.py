"""M33: ``message_events.linked_message_ids`` — 按 turn 保存 langchain msg id。

Revision ID: m33_add_linked_message_ids
Revises: m32_add_message_events
Create Date: 2026-05-03

W6 准确度改进 — 在每个 turn 的 trace 中，同时保存该 turn 生成的 assistant 消息的
parsed UUID（与 ``MessageResponse.id`` 格式相同）。共享页面中的
chip 映射因此可以从依赖 turn 顺序改为直接匹配。

现有 row 为 NULL，frontend 在 NULL/空数组时按 turn 顺序回退。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m33_add_linked_message_ids"
down_revision = "m32_add_message_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_events",
        sa.Column("linked_message_ids", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_events", "linked_message_ids")
