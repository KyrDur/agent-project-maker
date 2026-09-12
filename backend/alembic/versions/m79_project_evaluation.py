"""Request deduplication and frozen evaluation inputs for agent projects."""

import sqlalchemy as sa

from alembic import op

revision = "m79_project_evaluation"
down_revision = "m78_agent_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_project_versions") as batch:
        batch.add_column(sa.Column("request_id", sa.Uuid(), nullable=True))
        batch.create_unique_constraint("uq_project_version_scope", ["project_id", "id"])
        batch.create_unique_constraint("uq_project_version_request", ["project_id", "request_id"])
    with op.batch_alter_table("agent_project_eval_sets") as batch:
        batch.create_unique_constraint("uq_project_eval_set_scope", ["project_id", "id"])
    with op.batch_alter_table("agent_project_eval_runs") as batch:
        batch.create_foreign_key(
            "fk_eval_run_version_scope",
            "agent_project_versions",
            ["project_id", "version_id"],
            ["project_id", "id"],
        )
        batch.create_foreign_key(
            "fk_eval_run_set_scope",
            "agent_project_eval_sets",
            ["project_id", "eval_set_id"],
            ["project_id", "id"],
        )
        batch.add_column(sa.Column("request_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("cases_snapshot_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("dataset_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch.create_unique_constraint("uq_project_eval_run_request", ["project_id", "request_id"])
        batch.create_check_constraint(
            "ck_project_eval_run_status", "status IN ('pending', 'running', 'completed', 'failed')"
        )
    _sqlite_version_guard()


def _sqlite_version_guard() -> None:
    # SQLite batch table recreation drops its trigger; PostgreSQL ALTER preserves it.
    if op.get_bind().dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS agent_project_versions_immutable
            BEFORE UPDATE ON agent_project_versions BEGIN
                SELECT RAISE(ABORT, 'Agent project versions are immutable');
            END
        """)


def downgrade() -> None:
    with op.batch_alter_table("agent_project_eval_runs") as batch:
        batch.drop_constraint("fk_eval_run_version_scope", type_="foreignkey")
        batch.drop_constraint("fk_eval_run_set_scope", type_="foreignkey")
        batch.drop_constraint("ck_project_eval_run_status", type_="check")
        batch.drop_constraint("uq_project_eval_run_request", type_="unique")
        for column in ("error", "started_at", "dataset_hash", "cases_snapshot_json", "request_id"):
            batch.drop_column(column)
    with op.batch_alter_table("agent_project_eval_sets") as batch:
        batch.drop_constraint("uq_project_eval_set_scope", type_="unique")
    with op.batch_alter_table("agent_project_versions") as batch:
        batch.drop_constraint("uq_project_version_scope", type_="unique")
        batch.drop_constraint("uq_project_version_request", type_="unique")
        batch.drop_column("request_id")
    _sqlite_version_guard()
