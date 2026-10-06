"""builder_sessions.agent_id FK ON DELETE SET NULL

现有 FK 没有 ondelete 策略 → 删除 agent 时会产生 ForeignKeyViolationError。
会话是构建流程的审计轨迹，因此不会与 agent 一起 cascade delete，
只断开 reference。

Revision ID: m35_builder_session_fk_setnull
Revises: m34_message_events_status
Create Date: 2026-05-08
"""

from alembic import op

revision = "m35_builder_session_fk_setnull"
down_revision = "m34_message_events_status"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "builder_sessions_agent_id_fkey"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "builder_sessions", type_="foreignkey")
    op.create_foreign_key(
        CONSTRAINT_NAME,
        "builder_sessions",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "builder_sessions", type_="foreignkey")
    op.create_foreign_key(
        CONSTRAINT_NAME,
        "builder_sessions",
        "agents",
        ["agent_id"],
        ["id"],
    )
