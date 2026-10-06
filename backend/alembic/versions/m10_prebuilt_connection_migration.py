"""M10: tools.provider_name（仅用于架构 + 回填）

Revision ID: m10_prebuilt_connection
Revises: m9_migrate_mcp_to_connections
Create Date: 2026-04-18

落实 ADR-008 §4 — 为通过 per-user connection 解析 PREBUILT 工具而进行的
架构变更 + 仅负责现有 PREBUILT tool 的 provider_name 回填。

## upgrade
1. 添加 `tools.provider_name` VARCHAR(50) nullable 列（SQLite 使用 batch_alter_table）
2. 按现有 PREBUILT tools 的 name 模式执行回填
   - `Naver *` → `naver`
   - `Google Search`, `Google Image Search`, `Google News Search` → `google_search`
   - `Gmail *`, `Calendar *` → `google_workspace`
   - `Google Chat *` → `google_chat`
   - 其余 `type='prebuilt'` row 记录 WARN 日志 + 保持 NULL（需要手动修复）

## env → credential → default connection 的初始化不在此处执行
mock user 在 app.main lifespan 阶段才创建，因此执行 migration 时尚不存在，
seed 会始终 silent skip，而 Alembic 会将 revision 标记为 applied，导致重试路径
消失并产生 split-brain（Codex adversarial P1）。初始化由
`app.seed.prebuilt_connections.seed_mock_user_prebuilt_connections` 在 lifespan seed
块中于 mock user 创建**之后立即**在每次启动时 idempotent 执行。

## downgrade
- 反向删除 display_name/name 中包含 `M10_SEED_MARKER` 的 connection/credential
  （lifespan seed 使用此前缀，因此架构回滚时会一并清理）。
- drop `tools.provider_name` 列（batch_alter_table，兼容 SQLite）。
- 不回滚 PREBUILT tool 的回填（列消失后会自然消失）。
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision = "m10_prebuilt_connection"
down_revision = "m9_migrate_mcp_to_connections"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.m10")

# 用于在 downgrade 时识别 lifespan seed 创建的 credential/connection 行。
# 用户通过 UI 创建的行没有标记，因此予以保留。
M10_SEED_MARKER = "[m10-auto-seed]"


def _backfill_provider_name(bind) -> None:
    """现有 PREBUILT tools 的 name 模式 → provider_name 回填。"""
    mapping = [
        ("naver", "name LIKE 'Naver %'"),
        (
            "google_search",
            "name IN ('Google Search', 'Google Image Search', 'Google News Search')",
        ),
        (
            "google_workspace",
            "(name LIKE 'Gmail %' OR name LIKE 'Calendar %')",
        ),
        ("google_chat", "name LIKE 'Google Chat %'"),
    ]
    for provider, where in mapping:
        bind.execute(
            sa.text(
                f"UPDATE tools SET provider_name = :p "
                f"WHERE type = 'prebuilt' AND provider_name IS NULL AND {where}"
            ),
            {"p": provider},
        )

    # 映射失败 row 警告 — 若保持 NULL，则运行时 legacy fallback 路径仍会工作（tolerance）。
    leftovers = bind.execute(
        sa.text("SELECT id, name FROM tools WHERE type = 'prebuilt' AND provider_name IS NULL")
    ).fetchall()
    for row in leftovers:
        logger.warning(
            "m10: PREBUILT tool id=%s name=%r has no provider_name mapping — "
            "staying on legacy credential_id/env fallback path. "
            "Update app.seed.default_tools with provider_name and rerun m10.",
            row[0],
            row[1],
        )


def upgrade() -> None:
    # 1) 添加 tools.provider_name 列 — 为兼容 SQLite 使用 batch_alter_table
    with op.batch_alter_table("tools") as batch_op:
        batch_op.add_column(sa.Column("provider_name", sa.String(length=50), nullable=True))

    bind = op.get_bind()

    # 2) 对现有 PREBUILT tools 执行回填 — name 模式 → provider_name
    _backfill_provider_name(bind)

    # env → credential → connection 的初始化由 app.seed.prebuilt_connections 在 lifespan 中
    # 执行（mock user 在 lifespan 中创建，因此 migration 阶段尚不存在）。


def downgrade() -> None:
    bind = op.get_bind()

    # 只反向删除 m10 创建的 connection — 仅筛选 display_name 中含标记的行。
    # 用户通过 UI 创建的 connection/credential 没有标记，因此保留。
    marker_like = f"{M10_SEED_MARKER}%"
    bind.execute(
        sa.text("DELETE FROM connections WHERE type = 'prebuilt' AND display_name LIKE :m"),
        {"m": marker_like},
    )
    bind.execute(
        sa.text("DELETE FROM credentials WHERE name LIKE :m"),
        {"m": marker_like},
    )

    # drop provider_name 列 — 为兼容 SQLite 使用 batch_alter_table
    with op.batch_alter_table("tools") as batch_op:
        batch_op.drop_column("provider_name")
