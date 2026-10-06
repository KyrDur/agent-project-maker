"""M5: add llm_providers table and models.provider_id + meta columns

Revision ID: m5_add_llm_providers
Revises: m2_remove_messages
Create Date: 2026-04-06
"""

import sqlalchemy as sa

from alembic import op

revision = "m5_add_llm_providers"
down_revision = "m2_remove_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 创建 llm_providers 表
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. 向 models 添加 provider_id、context_window、modalities 列
    op.add_column("models", sa.Column("provider_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_models_provider_id",
        "models",
        "llm_providers",
        ["provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("models", sa.Column("context_window", sa.Integer(), nullable=True))
    op.add_column("models", sa.Column("input_modalities", sa.JSON(), nullable=True))
    op.add_column("models", sa.Column("output_modalities", sa.JSON(), nullable=True))

    # 3. 扩展 model_name/display_name 长度（100 → 200）
    op.alter_column("models", "model_name", type_=sa.String(200), existing_type=sa.String(100))
    op.alter_column("models", "display_name", type_=sa.String(200), existing_type=sa.String(100))

    # 4. 迁移现有 models → llm_providers 数据
    op.execute(
        """
        INSERT INTO llm_providers
            (id, name, provider_type, base_url, api_key_encrypted, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            CASE
                WHEN provider = 'openai' THEN 'OpenAI'
                WHEN provider = 'anthropic' THEN 'Anthropic'
                WHEN provider = 'google' THEN 'Google'
                ELSE initcap(provider)
            END,
            provider,
            base_url,
            api_key_encrypted,
            now(),
            now()
        FROM (
            SELECT DISTINCT provider, api_key_encrypted, base_url
            FROM models
            WHERE provider IS NOT NULL
        ) sub
        ON CONFLICT DO NOTHING
        """
    )

    # 5. 将 models.provider_id UPDATE 为匹配的 llm_provider id
    op.execute(
        """
        UPDATE models m
        SET provider_id = lp.id
        FROM llm_providers lp
        WHERE m.provider = lp.provider_type
          AND (m.base_url IS NOT DISTINCT FROM lp.base_url)
          AND (m.api_key_encrypted IS NOT DISTINCT FROM lp.api_key_encrypted)
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_models_provider_id", "models", type_="foreignkey")
    op.drop_column("models", "output_modalities")
    op.drop_column("models", "input_modalities")
    op.drop_column("models", "context_window")
    op.drop_column("models", "provider_id")
    op.alter_column("models", "model_name", type_=sa.String(100), existing_type=sa.String(200))
    op.alter_column("models", "display_name", type_=sa.String(100), existing_type=sa.String(200))
    op.drop_table("llm_providers")
