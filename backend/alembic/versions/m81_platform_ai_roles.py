"""Add explicit platform AI role slots.

Revision ID: m81_platform_ai_roles
Revises: m80_eval_set_quality
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "m81_platform_ai_roles"
down_revision = "m80_eval_set_quality"
branch_labels = None
depends_on = None

_NEW_ROLES = ("builder", "evaluation_generator", "judge_optimizer")
_ALL_ROLES = (*_NEW_ROLES, "text_primary", "text_fallback", "image")
_OLD_ROLES = ("text_primary", "text_fallback", "image")


def _role_check(roles: tuple[str, ...]) -> str:
    return "role IN (" + ", ".join(f"'{role}'" for role in roles) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.drop_constraint(
            "ck_system_llm_settings_role",
            "system_llm_settings",
            type_="check",
        )
        op.create_check_constraint(
            "ck_system_llm_settings_role",
            "system_llm_settings",
            _role_check(_ALL_ROLES),
        )
    else:
        with op.batch_alter_table("system_llm_settings") as batch:
            batch.drop_constraint("ck_system_llm_settings_role", type_="check")
            batch.create_check_constraint(
                "ck_system_llm_settings_role",
                _role_check(_ALL_ROLES),
            )

    existing = {
        row[0]
        for row in bind.execute(sa.text("select role from system_llm_settings")).all()
    }
    rows = [
        {
            "id": uuid.uuid4(),
            "role": role,
            "credential_id": None,
            "model_name": None,
        }
        for role in _NEW_ROLES
        if role not in existing
    ]
    if rows:
        op.bulk_insert(
            sa.table(
                "system_llm_settings",
                sa.column("id", sa.Uuid()),
                sa.column("role", sa.String(40)),
                sa.column("credential_id", sa.Uuid()),
                sa.column("model_name", sa.String(200)),
            ),
            rows,
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("delete from system_llm_settings where role in :roles").bindparams(
            sa.bindparam("roles", expanding=True)
        ),
        {"roles": list(_NEW_ROLES)},
    )
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_system_llm_settings_role",
            "system_llm_settings",
            type_="check",
        )
        op.create_check_constraint(
            "ck_system_llm_settings_role",
            "system_llm_settings",
            _role_check(_OLD_ROLES),
        )
    else:
        with op.batch_alter_table("system_llm_settings") as batch:
            batch.drop_constraint("ck_system_llm_settings_role", type_="check")
            batch.create_check_constraint(
                "ck_system_llm_settings_role",
                _role_check(_OLD_ROLES),
            )
