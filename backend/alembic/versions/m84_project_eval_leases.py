"""Lease ownership for durable project evaluation jobs."""

import sqlalchemy as sa

from alembic import op

revision = "m84_project_eval_leases"
down_revision = "m83_user_llm_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_project_eval_runs", sa.Column("lease_id", sa.Uuid()))
    op.add_column("agent_project_eval_runs", sa.Column("lease_expires_at", sa.DateTime()))
    op.create_index("ix_project_eval_dispatch", "agent_project_eval_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_project_eval_dispatch", table_name="agent_project_eval_runs")
    op.drop_column("agent_project_eval_runs", "lease_expires_at")
    op.drop_column("agent_project_eval_runs", "lease_id")
