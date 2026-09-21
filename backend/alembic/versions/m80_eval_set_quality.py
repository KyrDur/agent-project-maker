"""Add quality report storage for Agent Project EvalSets."""

import sqlalchemy as sa

from alembic import op

revision = "m80_eval_set_quality"
down_revision = "m79_project_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_project_eval_sets",
        sa.Column("quality_report_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_project_eval_sets", "quality_report_json")
