"""Add personal LLM selections without copying operator keys to users."""

import sqlalchemy as sa

from alembic import op

revision = "m84_user_llm_settings"
down_revision = "m83_project_practice"
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
        sa.UniqueConstraint("user_id", "role", name="uq_user_llm_settings_user_role"),
        sa.CheckConstraint(
            "role IN ('builder', 'evaluation_generator', 'judge_optimizer', "
            "'text_primary', 'text_fallback', 'image')",
            name="ck_user_llm_settings_role",
        ),
    )
    op.create_index("ix_user_llm_settings_user_id", "user_llm_settings", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_llm_settings")
