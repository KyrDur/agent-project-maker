"""Add agent project storage and immutable configuration versions."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m78_agent_projects"
down_revision = "m77_side_chat_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "builder_session_id",
            sa.Uuid(),
            sa.ForeignKey("builder_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("requirements_json", sa.JSON()),
        sa.Column("eval_spec_json", sa.JSON()),
        sa.Column("report_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "agent_project_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("agent_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), sa.ForeignKey("agent_project_versions.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.Text()),
        sa.Column("config_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "version_number", name="uq_agent_project_version_number"),
        sa.CheckConstraint("version_number > 0", name="ck_agent_project_version_positive"),
        sa.CheckConstraint(
            "status IN ('original', 'candidate', 'accepted', 'rejected')",
            name="ck_agent_project_version_status",
        ),
    )
    op.create_table(
        "agent_project_eval_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("agent_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("rubric_json", sa.JSON()),
        sa.Column("cases_json", sa.JSON(), nullable=False),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_agent_project_eval_sets_project_id", "agent_project_eval_sets", ["project_id"]
    )
    op.create_table(
        "agent_project_eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("agent_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("agent_project_versions.id"), nullable=False
        ),
        sa.Column(
            "eval_set_id", sa.Uuid(), sa.ForeignKey("agent_project_eval_sets.id"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("results_json", sa.JSON()),
        sa.Column("metrics_json", sa.JSON()),
        sa.Column("pass_rate", sa.Float()),
        sa.Column("bad_cases_json", sa.JSON()),
        sa.Column("comparison_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index(
        "ix_agent_project_eval_runs_project_id", "agent_project_eval_runs", ["project_id"]
    )
    # Protect snapshots even from bulk SQL updates that bypass ORM events.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_agent_project_version_update() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Agent project versions are immutable';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER agent_project_versions_immutable
            BEFORE UPDATE ON agent_project_versions
            FOR EACH ROW EXECUTE FUNCTION prevent_agent_project_version_update()
        """)
    elif op.get_bind().dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER agent_project_versions_immutable
            BEFORE UPDATE ON agent_project_versions BEGIN
                SELECT RAISE(ABORT, 'Agent project versions are immutable');
            END
        """)


def downgrade() -> None:
    op.drop_table("agent_project_eval_runs")
    op.drop_table("agent_project_eval_sets")
    op.drop_table("agent_project_versions")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION prevent_agent_project_version_update()")
    op.drop_table("agent_projects")
