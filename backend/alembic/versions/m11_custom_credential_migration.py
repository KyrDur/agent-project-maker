"""M11: CUSTOM tool credential → connection 迁移

Revision ID: m11_custom_connection
Revises: m10_prebuilt_connection
Create Date: 2026-04-18

落实 ADR-008 §4 M4 — 将现有 CUSTOM tools 的 `tool.credential_id` 路径
迁移为经由 `tool.connection_id → connection.credential_id`。

## upgrade
1. 识别目标：`tools.type='custom' AND credential_id IS NOT NULL AND connection_id IS NULL`
2. 以 (user_id, credential_id) 为单位进行 dedup 分组（1 credential = 1 connection, N tools）
3. 每个分组：
   - 若存在带 `[m11-auto-seed]` 标记的 connection → 复用（idempotent）
   - 否则 INSERT 新 connection（type='custom', provider_name='custom_api_key',
     display_name=f'[m11-auto-seed] {credential.name}', status='active').
     `is_default` 仅对每个 user 的 CUSTOM scope 中第一个 connection 设为 true —
     避免违反 `uq_connections_one_default_per_scope` partial unique index
     （ADR-008 §1 / §5）。后续 CUSTOM connection 均为 false。
4. 设置组内所有 tool 的 connection_id FK

## 保留（legacy fallback 保持到 M6）
- `tools.credential_id`：不 drop（保留 chat_service legacy 路径）
- `tools.auth_config`：不 drop

## downgrade
- 仅处理带 `[m11-auto-seed]%` 标记的 connection — 对引用该 connection 的
  tool，将 connection_id → NULL 反向设置 → DELETE connection
- 保留手动创建的 CUSTOM connection

## aiosqlite 测试兼容策略（M9/M10 precedent）
即使混有 PG-native 查询，实际往返也只在 PostgreSQL 上执行。
pytest 使用 `inspect.getsource` 静态验证辅助函数正文契约（目标识别 SQL、标记应用、
is_default race 防护等）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "m11_custom_connection"
down_revision = "m10_prebuilt_connection"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.m11")

# 该标记用于在 downgrade 时仅安全反向删除 m11 创建的 connection 行。
# 通过 UI 手动创建的 CUSTOM connection 没有此标记，因此保留。
M11_SEED_MARKER = "[m11-auto-seed]"


def _migrate_custom_credentials(bind) -> None:
    """CUSTOM tool 的 credential_id → connection 迁移主体。

    - (user_id, credential_id) dedup → 1 credential = 1 connection（N:1 共享）
    - idempotent：重新执行时基于标记复用现有 connection
    - 避免违反 `uq_connections_one_default_per_scope`：若每个 user 的 CUSTOM scope 中
      已存在 default，则新 connection 以 is_default=false INSERT
    """
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id, credential_id FROM tools "
            "WHERE type = 'custom' "
            "AND credential_id IS NOT NULL "
            "AND connection_id IS NULL"
        )
    ).fetchall()
    if not rows:
        return

    # 以 (user_id, credential_id) 为单位 dedup — 引用同一 credential 的多个
    # CUSTOM tool 共享一个 connection（N:1）。
    groups: dict[tuple, list[uuid.UUID]] = {}
    for tool_id, user_id, credential_id in rows:
        groups.setdefault((user_id, credential_id), []).append(tool_id)

    # 检查每个 user 的 CUSTOM scope 是否已有 default。partial unique index
    # (user_id, type='custom', provider_name='custom_api_key') WHERE
    # 作用于 is_default=true，因此同一 user 内若将 2 条以上记录设为 default
    # 执行 INSERT 会产生 IntegrityError。
    custom_default_taken: set[uuid.UUID] = set()
    pre_existing = bind.execute(
        sa.text(
            "SELECT user_id FROM connections "
            "WHERE type = 'custom' "
            "AND provider_name = 'custom_api_key' "
            "AND is_default = TRUE"
        )
    ).fetchall()
    for (uid,) in pre_existing:
        custom_default_taken.add(uid)

    now = datetime.now(UTC).replace(tzinfo=None)

    for (user_id, credential_id), tool_ids in groups.items():
        # idempotent + manual-respect 复用：如果用户已通过 M1 connection POST API
        # 预先创建了 manual CUSTOM connection，则必须复用它。
        # 如果用标记 LIKE 过滤只查找我们创建的行，manual connection 会被孤立，
        # 新的 [m11-auto-seed] 行会夺走 SOT，破坏 ADR-008 的 1-credential→
        # 1-connection 不变量（Codex 第 2 次 P1）。标记仅在 INSERT 时
        # 附加，以便 downgrade 时精确反向删除，而 lookup 则按更宽的 (user_id,
        # type, credential_id) 维度匹配。
        # 必须使用 `status = 'active'` 过滤（Codex 第 3 次 P2）：pre-m11 的 legacy tool
        # 原本通过 `tool.credential_id` 路径执行；如果同一 credential 对应
        # disabled manual connection，m11 若复用它，就会把所有 tool
        # rebind 到 disabled connection → post-m11 中因 fail-closed 导致全部无法执行
        # 回归。如果没有 active 行，则 fall-through 创建新的 [m11-auto-seed] active
        # connection（保留原有行为）。用户如何协调保留 disabled 与 seeded
        # connection 如何 reconcile，由 M5 UI 处理。
        existing = bind.execute(
            sa.text(
                "SELECT id FROM connections "
                "WHERE user_id = :uid "
                "AND type = 'custom' "
                "AND credential_id = :cid "
                "AND status = 'active' "
                "ORDER BY is_default DESC, created_at ASC "
                "LIMIT 1"
            ),
            {
                "uid": user_id,
                "cid": credential_id,
            },
        ).first()

        if existing is not None:
            connection_id = existing[0]
            logger.info(
                "m11: reused existing CUSTOM connection %s for user=%s credential=%s (%d tools)",
                connection_id,
                user_id,
                credential_id,
                len(tool_ids),
            )
        else:
            cred_row = bind.execute(
                sa.text("SELECT name FROM credentials WHERE id = :cid"),
                {"cid": credential_id},
            ).first()
            cred_name = (cred_row[0] if cred_row else "credential") or "credential"
            display_name = f"{M11_SEED_MARKER} {cred_name}"[:200]

            # 每个 user 的 CUSTOM scope 中仅第一个 default 设为 is_default=true。
            # 后续 CUSTOM connection 均为 is_default=false（避开 partial unique index）。
            is_default = user_id not in custom_default_taken
            if is_default:
                custom_default_taken.add(user_id)

            connection_id = uuid.uuid4()
            bind.execute(
                sa.text(
                    "INSERT INTO connections ("
                    "id, user_id, type, provider_name, display_name, "
                    "credential_id, extra_config, is_default, status, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :user_id, 'custom', 'custom_api_key', "
                    ":display_name, :credential_id, NULL, :is_default, "
                    "'active', :created_at, :updated_at"
                    ")"
                ),
                {
                    "id": connection_id,
                    "user_id": user_id,
                    "display_name": display_name,
                    "credential_id": credential_id,
                    "is_default": is_default,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            logger.info(
                "m11: inserted CUSTOM connection %s for user=%s credential=%s "
                "(%d tools, is_default=%s)",
                connection_id,
                user_id,
                credential_id,
                len(tool_ids),
                is_default,
            )

        # 设置组内所有 tool.connection_id FK。tool.credential_id
        # 保持不变（供 M6 前的 legacy fallback 路径使用）。在 provenance 中记录 tool_id，
        # 使 downgrade 能够对称还原（Codex adversarial 第 2 次
        # [high] #1）— 包括绑定到复用 manual connection 的 tool。
        # 此 SELECT 已仅过滤 `connection_id IS NULL` 的行，因此记录到 provenance
        # 中的 tool，其 pre-m11 状态始终为 NULL。
        for tool_id in tool_ids:
            bind.execute(
                sa.text(
                    "UPDATE tools SET connection_id = :conn_id "
                    "WHERE id = :tool_id AND connection_id IS NULL"
                ),
                {"conn_id": connection_id, "tool_id": tool_id},
            )
            bind.execute(
                sa.text(
                    "INSERT INTO _m11_tool_backfill_provenance (tool_id) "
                    "VALUES (:tool_id) "
                    "ON CONFLICT (tool_id) DO NOTHING"
                ),
                {"tool_id": tool_id},
            )


def _dedup_preexisting_custom_duplicates(bind) -> None:
    """在 CREATE UNIQUE INDEX 之前整理现有 `connections` 的 (user_id, credential_id)
    重复项（Codex adversarial 第 2 次 [high] #2）。m11 之前没有约束，
    可通过 M1 API 为同一 credential 创建多个 CUSTOM connection。

    **Fully reversible**（Codex adversarial 第 4 次 [high] #2）：
    将被删除的 duplicate 行以 full row 保存到 `_m11_dedup_connection_snapshot`，
    对被 repoint 的 tool，在 `_m11_dedup_tool_remap` 中记录 (tool_id, original_connection_id)
    。downgrade 时可从这两个表精确恢复。

    canonical 选择顺序（Codex adversarial 第 4 次 [high] #1 — health first）：
    1. status = 'active'（避免将 disabled default 选为 canonical 后把 working tool
       repoint 到 disable connection，从而规避 post-migration 故障）
    2. is_default = true（在 active 之间保留 user 预期的 default）
    3. created_at ASC（并列时选择最旧的 = 最先创建的）
    4. id ASC（确定性 tie-breaker）

    将 duplicates 的 tool.connection_id repoint 到 canonical 后 DELETE。
    agent_tools.connection_id(M5) 当前不存在，因此省略。
    """
    groups = bind.execute(
        sa.text(
            "SELECT user_id, credential_id "
            "FROM connections "
            "WHERE type = 'custom' AND credential_id IS NOT NULL "
            "GROUP BY user_id, credential_id "
            "HAVING COUNT(*) > 1"
        )
    ).fetchall()

    for user_id, credential_id in groups:
        rows = bind.execute(
            sa.text(
                "SELECT id FROM connections "
                "WHERE user_id = :uid AND type = 'custom' AND credential_id = :cid "
                "ORDER BY "
                "(CASE WHEN status = 'active' THEN 0 ELSE 1 END), "
                "is_default DESC, "
                "created_at ASC, id ASC"
            ),
            {"uid": user_id, "cid": credential_id},
        ).fetchall()
        canonical_id = rows[0][0]
        for (dup_id,) in rows[1:]:
            # Snapshot full row for downgrade restoration — 使用 INSERT ... SELECT
            # 不经过 JSON 序列化以保留 type。ON CONFLICT 保证 idempotent。
            bind.execute(
                sa.text(
                    "INSERT INTO _m11_dedup_connection_snapshot ("
                    "connection_id, user_id, type, provider_name, display_name, "
                    "credential_id, extra_config, is_default, status, "
                    "created_at, updated_at"
                    ") SELECT id, user_id, type, provider_name, display_name, "
                    "credential_id, extra_config, is_default, status, "
                    "created_at, updated_at "
                    "FROM connections WHERE id = :id "
                    "ON CONFLICT (connection_id) DO NOTHING"
                ),
                {"id": dup_id},
            )
            # Record tool remap BEFORE UPDATE — 以便 downgrade 将 tool.connection_id
            # 恢复到原始 duplicate。
            bind.execute(
                sa.text(
                    "INSERT INTO _m11_dedup_tool_remap "
                    "(tool_id, original_connection_id) "
                    "SELECT id, connection_id FROM tools "
                    "WHERE connection_id = :dup "
                    "ON CONFLICT (tool_id) DO NOTHING"
                ),
                {"dup": dup_id},
            )
            bind.execute(
                sa.text("UPDATE tools SET connection_id = :canonical WHERE connection_id = :dup"),
                {"canonical": canonical_id, "dup": dup_id},
            )
            bind.execute(
                sa.text("DELETE FROM connections WHERE id = :id"),
                {"id": dup_id},
            )
        logger.info(
            "m11: deduped %d duplicate CUSTOM connections for user=%s credential=%s → canonical=%s",
            len(rows) - 1,
            user_id,
            credential_id,
            canonical_id,
        )


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 三类 Provenance 表 — 使 downgrade 可以对称恢复。
    # （Codex adversarial 第 2/4 次 [high]）。
    #
    # - `_m11_tool_backfill_provenance`：记录 _migrate_custom_credentials set 的
    #   tool_id（pre-state = NULL）。downgrade 时恢复为 NULL。
    # - `_m11_dedup_connection_snapshot`：_dedup 删除的 duplicate connection
    #   行的 full snapshot。downgrade 时通过 INSERT 恢复。
    # - `_m11_dedup_tool_remap`：记录 _dedup repoint 的 tool 的 (tool_id,
    #   original_connection_id)。downgrade 时恢复到原始 duplicate。
    op.execute(
        "CREATE TABLE IF NOT EXISTS _m11_tool_backfill_provenance (tool_id UUID PRIMARY KEY)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS _m11_dedup_connection_snapshot ("
        "connection_id UUID PRIMARY KEY, "
        "user_id UUID NOT NULL, "
        "type VARCHAR(20) NOT NULL, "
        "provider_name VARCHAR(50), "
        "display_name VARCHAR(200) NOT NULL, "
        "credential_id UUID, "
        "extra_config JSON, "
        "is_default BOOLEAN NOT NULL, "
        "status VARCHAR(20) NOT NULL, "
        "created_at TIMESTAMP NOT NULL, "
        "updated_at TIMESTAMP NOT NULL"
        ")"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS _m11_dedup_tool_remap ("
        "tool_id UUID PRIMARY KEY, "
        "original_connection_id UUID NOT NULL"
        ")"
    )

    # 2) CUSTOM tool credential → connection 迁移。
    _migrate_custom_credentials(bind)

    # 3) 在 CREATE UNIQUE INDEX 之前删除现有 duplicate — 否则
    # 若现有数据存在重复，CREATE UNIQUE INDEX 会失败并阻塞部署
    # （Codex adversarial 第 2 次 [high] #2）。被删除的 duplicate 会保存到 snapshot +
    # tool_remap 表中，因此可在 downgrade 时完整恢复
    # （Codex adversarial 第 4 次 [high] #2）。
    _dedup_preexisting_custom_duplicates(bind)

    # 4) ADR-008 N:1 invariant — CUSTOM tool 每个 (user_id, credential_id) 仅允许 1 个
    # connection（Codex adversarial 第 1 次 [medium]）。service-level
    # get-or-create + defense-in-depth — 由 DB 阻止并发 INSERT race。
    # 通过 partial unique index 限制：type='custom' AND credential_id IS NOT NULL。
    # MCP / PREBUILT 不受此约束（允许基于 extra_config 的多个 connection）。
    # PG/SQLite 3.8+ 支持 partial index。使用 `IF NOT EXISTS` 保证重新执行 idempotent。
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_connections_custom_one_per_credential "
        "ON connections (user_id, credential_id) "
        "WHERE type = 'custom' AND credential_id IS NOT NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()

    # 0) 确保 Provenance 表存在 — 使已应用旧版 m11（provenance 逻辑之前）的
    # DB 在执行 downgrade 时也安全。若为空表，则下面的恢复
    # 步骤会 no-op，而 marker DELETE 仍会清理 [m11-auto-seed] 行。
    op.execute(
        "CREATE TABLE IF NOT EXISTS _m11_tool_backfill_provenance (tool_id UUID PRIMARY KEY)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS _m11_dedup_connection_snapshot ("
        "connection_id UUID PRIMARY KEY, "
        "user_id UUID NOT NULL, "
        "type VARCHAR(20) NOT NULL, "
        "provider_name VARCHAR(50), "
        "display_name VARCHAR(200) NOT NULL, "
        "credential_id UUID, "
        "extra_config JSON, "
        "is_default BOOLEAN NOT NULL, "
        "status VARCHAR(20) NOT NULL, "
        "created_at TIMESTAMP NOT NULL, "
        "updated_at TIMESTAMP NOT NULL"
        ")"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS _m11_dedup_tool_remap ("
        "tool_id UUID PRIMARY KEY, "
        "original_connection_id UUID NOT NULL"
        ")"
    )

    # 1) 删除 N:1 partial unique index（upgrade step 4 的逆操作）。dedup 恢复会再次
    # 产生 duplicate，因此必须先 drop。
    op.execute("DROP INDEX IF EXISTS uq_connections_custom_one_per_credential")

    # 2) 恢复 dedup 删除的 duplicate connection（upgrade step 3 的逆操作）。
    # 通过 INSERT … SELECT 在不做 JSON 序列化的情况下保留类型。ON CONFLICT 用于 idempotent。
    bind.execute(
        sa.text(
            "INSERT INTO connections ("
            "id, user_id, type, provider_name, display_name, credential_id, "
            "extra_config, is_default, status, created_at, updated_at"
            ") SELECT connection_id, user_id, type, provider_name, display_name, "
            "credential_id, extra_config, is_default, status, created_at, updated_at "
            "FROM _m11_dedup_connection_snapshot "
            "ON CONFLICT (id) DO NOTHING"
        )
    )

    # 3) 将 dedup repoint 的 tool 恢复到原始 duplicate（upgrade step 3 的逆操作）。
    # UPDATE ... FROM 仅限 PG。必须先于 backfill_provenance 的 NULL 恢复执行，
    # 才能保持两个集合 disjoint（backfill set = NULL→conn, dedup set =
    # old_conn→canonical）。如果顺序反过来，部分由 backfill-设置的 tool 若被记录到 dedup，
    # 会先被错误设为 NULL，再被 restore 覆盖，造成复杂性。
    bind.execute(
        sa.text(
            "UPDATE tools SET connection_id = r.original_connection_id "
            "FROM _m11_dedup_tool_remap r "
            "WHERE tools.id = r.tool_id"
        )
    )

    # 4) 基于 backfill provenance 将 tool.connection_id 恢复为 NULL
    # （upgrade step 2 的逆操作）。pre-m11 状态始终为 NULL（upgrade SELECT 过滤条件）。
    bind.execute(
        sa.text(
            "UPDATE tools SET connection_id = NULL "
            "WHERE id IN (SELECT tool_id FROM _m11_tool_backfill_provenance)"
        )
    )

    marker_like = f"{M11_SEED_MARKER}%"

    # 5) 删除带标记的 connection — 手动创建的记录没有标记，因此保留。
    #    reused manual connection 即使在 upgrade 中被选为 canonical 并保留下来，
    #    由于没有标记，也会被排除在 DELETE 目标之外并保留。
    bind.execute(
        sa.text(
            "DELETE FROM connections "
            "WHERE type = 'custom' "
            "AND provider_name = 'custom_api_key' "
            "AND display_name LIKE :m"
        ),
        {"m": marker_like},
    )

    # 6) drop Provenance 表（upgrade step 1 的逆操作）。
    op.execute("DROP TABLE IF EXISTS _m11_dedup_tool_remap")
    op.execute("DROP TABLE IF EXISTS _m11_dedup_connection_snapshot")
    op.execute("DROP TABLE IF EXISTS _m11_tool_backfill_provenance")
