"""M46: ``models.is_visible`` — hide non-openai_compatible providers by default.

Revision ID: m46_models_is_visible
Revises: m45_system_llm_settings
Create Date: 2026-05-28

内部环境暂时只使用 ``openai_compatible`` 这一种 provider，
初始化导入的 ``anthropic`` / ``openai`` / ``google`` 模型会在模型页面和
智能体创建选择器中直接显示，造成混淆。模型 row 本身
以后可能重新启用，因此不删除，而是通过 visibility 标志隐藏。

迁移添加 ``is_visible BOOL NOT NULL DEFAULT true`` 列，并将现有
row 中 ``provider <> 'openai_compatible'`` 的记录统一设为 ``false``。
若被隐藏的 row 恰好 ``is_default=true``，则同时取消 default，
"默认模型被隐藏"这一矛盾状态被避免。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m46_models_is_visible"
down_revision = "m45_system_llm_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column(
            "is_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE models SET is_visible = false WHERE provider <> 'openai_compatible'")
    )
    # 若默认模型被隐藏，模型选择器会变空。为保证两个标志
    # 同时为 true 的状态才有效，因此一并取消 default。
    bind.execute(
        sa.text(
            "UPDATE models SET is_default = false WHERE is_default = true AND is_visible = false"
        )
    )


def downgrade() -> None:
    op.drop_column("models", "is_visible")
