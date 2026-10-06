"""M16: agents.opener_questions (JSON nullable) — 新聊天空白页示例问题列表。

Revision ID: m16_add_opener_questions
Revises: m15_add_message_timestamps
Create Date: 2026-04-28

每个智能体可保存最多 12 个在新对话开始时展示给用户的示例问题（opener），
点击后将文本注入 composer（发送 X）。validator 在 schemas 层
处理（≤12 条，每项 1~200 字符）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m16_add_opener_questions"
down_revision = "m15_add_message_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("opener_questions", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "opener_questions")
