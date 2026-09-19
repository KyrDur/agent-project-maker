"""Add evaluation focus checkpoint metadata to Agent Project EvalSets.

Revision ID: m82_eval_focus_checkpoint
Revises: m81_platform_ai_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m82_eval_focus_checkpoint"
down_revision = "m81_platform_ai_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_project_eval_sets",
        sa.Column("evaluation_focus_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "agent_project_eval_sets",
        sa.Column("evaluation_focus_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_project_eval_sets", "evaluation_focus_reason")
    op.drop_column("agent_project_eval_sets", "evaluation_focus_json")
