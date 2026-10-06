"""独立的项目模拟聊天会话。历史快照不回填。"""

import sqlalchemy as sa

from alembic import op

revision = "m85_project_simulation"
down_revision = "m84_user_llm_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_project_simulations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("agent_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("agent_project_versions.id"), nullable=False
        ),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        *[
            sa.Column(name, sa.JSON(), nullable=False)
            for name in (
                "config_json",
                "scenario_json",
                "state_json",
                "messages_json",
                "turns_json",
            )
        ],
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "request_id", name="uq_simulation_request"),
        sa.ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["agent_project_versions.project_id", "agent_project_versions.id"],
            name="fk_simulation_version_scope",
        ),
    )
    op.create_index(
        "ix_agent_project_simulations_project_id", "agent_project_simulations", ["project_id"]
    )
    op.create_index(
        "ix_agent_project_simulations_user_id", "agent_project_simulations", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("agent_project_simulations")
