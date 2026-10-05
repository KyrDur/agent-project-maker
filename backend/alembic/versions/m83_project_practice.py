"""Persist authored practice decisions and completion separately from quality."""

import sqlalchemy as sa

from alembic import op

revision = "m83_project_practice"
down_revision = "m82_eval_focus_checkpoint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_projects", sa.Column("decisions_json", sa.JSON(), nullable=True))
    op.add_column("agent_projects", sa.Column("completion_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_projects", "completion_json")
    op.drop_column("agent_projects", "decisions_json")
