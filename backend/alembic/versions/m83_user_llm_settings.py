"""Private project model roles."""

import sqlalchemy as sa

from alembic import op

revision = "m83_user_llm_settings"
down_revision = "m82_eval_focus_checkpoint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_llm_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("credential_id", sa.Uuid(), sa.ForeignKey("credentials.id", ondelete="SET NULL")),
        sa.Column("model_name", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "role", name="uq_user_llm_role"),
        sa.CheckConstraint(
            "role IN ('builder', 'evaluation_generator', 'judge_optimizer')",
            name="ck_user_llm_role",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_llm_settings")
