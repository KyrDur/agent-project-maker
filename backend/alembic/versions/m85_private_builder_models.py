"""Scope Builder-created model descriptors to their owning user."""

import sqlalchemy as sa

from alembic import op

revision = "m85_private_builder_models"
down_revision = "m84_project_eval_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("models", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_models_owner_user", "models", "users", ["owner_user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_models_owner_user_id", "models", ["owner_user_id"])
    # Older Builder confirmations created globally visible rows without a
    # provenance column. Only claim rows with a completed personal-Builder
    # session, a model created after that session began, and no catalog pricing
    # or preferred credential. A pre-existing operator catalog row therefore
    # keeps its global meaning. The earliest matching session owns a row that
    # another account subsequently reused through the old leak.
    op.execute(
        sa.text(
            """
            UPDATE models
               SET owner_user_id = (
                   SELECT bs.user_id
                     FROM builder_sessions AS bs
                     JOIN agents AS a ON a.id = bs.agent_id
                    WHERE a.model_id = models.id
                      AND bs.draft_config ->> 'runtime_model_source' = 'system_builder'
                      AND models.created_at >= bs.created_at
                    ORDER BY bs.created_at, bs.id
                    LIMIT 1
               )
             WHERE owner_user_id IS NULL
               AND source IS NULL
               AND default_credential_id IS NULL
               AND cost_per_input_token IS NULL
               AND cost_per_output_token IS NULL
               AND EXISTS (
                   SELECT 1
                     FROM builder_sessions AS bs
                     JOIN agents AS a ON a.id = bs.agent_id
                    WHERE a.model_id = models.id
                      AND bs.draft_config ->> 'runtime_model_source' = 'system_builder'
                      AND models.created_at >= bs.created_at
               )
            """
        )
    )
    connection = op.get_bind()
    cross_owner_agents = connection.scalar(
        sa.text(
            """
            SELECT COUNT(*)
              FROM agents AS a
              JOIN models AS m ON m.id = a.model_id
             WHERE m.owner_user_id IS NOT NULL
               AND a.user_id <> m.owner_user_id
            """
        )
    )
    if cross_owner_agents:
        raise RuntimeError(
            "Legacy Builder model is bound to another user's Agent; "
            "resolve these references before applying m85"
        )


def downgrade() -> None:
    op.drop_index("ix_models_owner_user_id", table_name="models")
    op.drop_constraint("fk_models_owner_user", "models", type_="foreignkey")
    op.drop_column("models", "owner_user_id")
