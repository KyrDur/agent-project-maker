"""M17: agent_subagents — 智能体自引用 join 表（子智能体委派）。

Revision ID: m17_add_agent_subagents
Revises: m16_add_opener_questions
Create Date: 2026-04-29

允许智能体将其他智能体作为 "子代理" 调用的自引用
many-to-many 关系表。parent_agent_id / sub_agent_id 均引用 agents.id。

- PK: (parent_agent_id, sub_agent_id) 复合键（防止重复 link）
- INDEX: 仅 parent_agent_id（经常从 parent 查询 sub）
- CHECK 约束：parent_agent_id != sub_agent_id（reject 自身；与 service 层双重防护）
- ON DELETE CASCADE：删除 agent 时自动清理 link
- position: ordering（用于 UI 排序）
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m17_add_agent_subagents"
down_revision = "m16_add_opener_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_subagents",
        sa.Column(
            "parent_agent_id",
            sa.UUID(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "sub_agent_id",
            sa.UUID(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "parent_agent_id != sub_agent_id",
            name="ck_agent_subagents_no_self",
        ),
    )
    op.create_index(
        "ix_agent_subagents_parent_agent_id",
        "agent_subagents",
        ["parent_agent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_subagents_parent_agent_id", table_name="agent_subagents")
    op.drop_table("agent_subagents")
