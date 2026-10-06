"""M9: migrate mcp_servers → connections, add tools.connection_id

Revision ID: m9_migrate_mcp_to_connections
Revises: m8_add_connections
Create Date: 2026-04-18

落实 ADR-008 §6 — 将 MCP 工具的 credential/服务器配置解析路径改为经由 connection
的数据迁移。

## upgrade
1. 添加 `tools.connection_id` UUID nullable FK(connections.id) ON DELETE SET NULL
2. 将每个 `mcp_servers` row 复制为 `connections` row(type='mcp')
   - provider_name：规范化 server.name（小写/下划线）。（user_id, type）
     若 scope 内冲突，则添加 `_2`、`_3` 等 suffix
   - display_name = server.name
   - credential_id = server.credential_id（SET NULL 语义相同）
   - extra_config = {url, auth_type, headers: {}, env_vars: <server.auth_config>}
   - is_default = True（通过 suffix 避开 provider_name 冲突，因此每个 scope 1 条）
   - status = 'active' / timestamps = server.created_at
3. 对 tools.mcp_server_id IS NOT NULL 的 row → 设置为映射后的 connection_id
   （保留 `tools.mcp_server_id`。计划在 M6 迁移中 drop）

## auth_config 明文迁移策略（M2 风险 4）
ADR-008 §2 只允许 `extra_config.env_vars` 使用 `${credential.<field>}` 模板值，
但现有 `mcp_servers.auth_config` 中可能包含明文值，
因此为了数据可靠性，**仅在本迁移中**将明文原样
复制到 `extra_config.env_vars`。运行时（S3, chat_service/mcp_client）
按 template 优先 + legacy 明文 fallback 解析。新建 connection
在应用层（connection_service）执行 template-only 验证。

## downgrade
- drop `tools.connection_id` 列（tools.mcp_server_id 原样保留，
  可恢复 legacy 路径）
- 删除 `connections.type = 'mcp'` row（这里只存在迁移创建的 connection）
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "m9_migrate_mcp_to_connections"
down_revision = "m8_add_connections"
branch_labels = None
depends_on = None


_SLUG_RE = re.compile(r"[^a-z0-9_]+")
_COLLAPSE_RE = re.compile(r"_+")


def _normalize_provider_name(name: str) -> str:
    """server.name → connections.provider_name 标识转换。

    - 转为小写，将非字母数字/下划线字符替换为 `_`，连续 `_` 压缩
    - 若为空字符串，则 fallback 为 'mcp'
    - String(50) 列。为 suffix 空间（_NN），base truncate 为 45 字符
    """
    slug = _SLUG_RE.sub("_", (name or "").lower())
    slug = _COLLAPSE_RE.sub("_", slug).strip("_")
    if not slug:
        slug = "mcp"
    return slug[:45]


def upgrade() -> None:
    # 1) tools.connection_id 列 + FK
    op.add_column(
        "tools",
        sa.Column("connection_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tools_connection_id",
        "tools",
        "connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2) 迁移追踪表 — 使 downgrade 时可以只安全删除"m9 创建的 connection"
    # 并记录来源。如果在 user-facing `extra_config` 中放入 sentinel，
    # 会在 `ConnectionExtraConfig(extra="forbid")` 再验证时被拦截，
    # 导致 GET/PATCH 失效。因此拆分到独立表。
    op.create_table(
        "_m9_migrated_connections",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            nullable=False,
            primary_key=True,
        ),
    )

    # 3) mcp_servers → connections 迁移
    bind = op.get_bind()

    servers = bind.execute(
        sa.text(
            "SELECT id, user_id, name, url, auth_type, auth_config, "
            "credential_id, status, created_at "
            "FROM mcp_servers"
        )
    ).fetchall()

    if not servers:
        return

    # credential 查询 batch — 防止每个 server 产生 N+1 SELECT。仅在 auth_config 为空且
    # 存在带 credential_id 的 server 时执行。
    credential_ids_needed = {s[6] for s in servers if (not s[5]) and s[6] is not None}
    credentials_by_id: dict[uuid.UUID, tuple] = {}
    if credential_ids_needed:
        stmt = sa.text(
            "SELECT id, field_keys, data_encrypted FROM credentials WHERE id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True))
        rows = bind.execute(stmt, {"ids": list(credential_ids_needed)}).fetchall()
        credentials_by_id = {r[0]: (r[1], r[2]) for r in rows}

    # 追踪 (user_id, provider_name) scope 内冲突。现有 connections 中也可能
    # 存在相同 scope 的 row，因此预先加载。
    existing = bind.execute(
        sa.text("SELECT user_id, provider_name FROM connections WHERE type = 'mcp'")
    ).fetchall()
    taken: set[tuple[str, str]] = {(str(row[0]), row[1]) for row in existing}

    server_to_connection: dict[uuid.UUID, uuid.UUID] = {}

    for server in servers:
        server_id = server[0]
        user_id = server[1]
        name = server[2]
        url = server[3]
        auth_type = server[4] or "none"
        auth_config = server[5] or {}
        credential_id = server[6]
        status = server[7] or "active"
        created_at = server[8] or datetime.now(UTC).replace(tzinfo=None)

        # 假定 auth_config 为 dict。asyncpg + JSON 列会返回 dict，但
        # 对返回字符串的驱动情况进行防御。
        if isinstance(auth_config, str):
            try:
                auth_config = json.loads(auth_config) if auth_config else {}
            except ValueError:
                auth_config = {}
        if not isinstance(auth_config, dict):
            auth_config = {}

        base = _normalize_provider_name(name)
        provider_name = base
        suffix = 1
        while (str(user_id), provider_name) in taken:
            suffix += 1
            provider_name = f"{base}_{suffix}"[:50]
        taken.add((str(user_id), provider_name))

        # env_vars 决策逻辑（防止 auth 缺失 regression）：
        # 1) 若 mcp_servers.auth_config 为 dict，则按 legacy 明文原样迁移
        #    （运行时在 env_var_resolver 中宽容处理 + 警告）
        # 2) 对 auth_config 为空且连接 credential 的 server，为保持现有
        #    resolve_server_auth 行为，使用 credentials.field_keys
        #    （ADR-007）或通过解密 data_encrypted 推导键 → 自动生成模板
        # 3) 若既无 credential 也无 auth_config，则迁移为空 env_vars（正常）
        # 4) 若存在 credential 但无法恢复键 → 此 server **跳过 migrate
        #    **（connections row + tools.connection_id 均不创建）。现有
        #    mcp_servers row 与 tools.mcp_server_id 原样保留，运行时
        #    继续通过 legacy fallback 路径工作（Codex 第 8 次 adversarial F1）
        credential_auth_recoverable = True
        if auth_config:
            env_vars_out = auth_config
        elif credential_id:
            cred_row = credentials_by_id.get(credential_id)
            field_keys_list: list[str] | None = None
            if cred_row is not None:
                field_keys_raw = cred_row[0]
                if isinstance(field_keys_raw, str):
                    try:
                        field_keys_raw = json.loads(field_keys_raw)
                    except ValueError:
                        field_keys_raw = None
                if isinstance(field_keys_raw, list) and field_keys_raw:
                    field_keys_list = [str(k) for k in field_keys_raw]
                # else: legacy data_encrypted decrypt fallback removed in M5
                # along with ``app.services.encryption``. Surviving rows
                # without field_keys take the legacy mcp_server_id path below.

            if field_keys_list:
                env_vars_out = {k: f"${{credential.{k}}}" for k in field_keys_list}
            else:
                # 恢复失败 → 不迁移，保留 legacy path。跳过 connection 创建
                # 本身，使 tools.connection_id 不被设置。
                import logging

                logging.getLogger("alembic.m9").warning(
                    "m9: leaving MCP server %s on legacy path — credential %s "
                    "auth could not be reconstructed (NULL field_keys and "
                    "decrypt/JSON fallback failed). tools.mcp_server_id + "
                    "保留 resolve_server_auth 路径。执行 M7 backfill，或者 "
                    "重新设置 credential 后再次应用 m9 即可完成迁移。",
                    server_id,
                    credential_id,
                )
                credential_auth_recoverable = False
                env_vars_out = {}
        else:
            env_vars_out = {}

        if not credential_auth_recoverable:
            # 从 scope taken 中归还 provider_name（此 server 不创建 connection）
            taken.discard((str(user_id), provider_name))
            continue

        extra_config = {
            "url": url,
            "auth_type": auth_type,
            "headers": {},
            "env_vars": env_vars_out,
        }

        connection_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO connections ("
                "id, user_id, type, provider_name, display_name, "
                "credential_id, extra_config, is_default, status, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :user_id, 'mcp', :provider_name, :display_name, "
                ":credential_id, CAST(:extra_config AS JSON), TRUE, :status, "
                ":created_at, :updated_at"
                ")"
            ),
            {
                "id": connection_id,
                "user_id": user_id,
                "provider_name": provider_name,
                "display_name": (name or "MCP Server")[:200],
                "credential_id": credential_id,
                "extra_config": json.dumps(extra_config),
                "status": status,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        server_to_connection[server_id] = connection_id

        # 迁移追踪：记录下来，以便 downgrade 时仅精确删除该 row
        bind.execute(
            sa.text("INSERT INTO _m9_migrated_connections (connection_id) VALUES (:id)"),
            {"id": connection_id},
        )

    # 4) tools.mcp_server_id → tools.connection_id 映射
    for server_id, connection_id in server_to_connection.items():
        bind.execute(
            sa.text("UPDATE tools SET connection_id = :cid WHERE mcp_server_id = :sid"),
            {"cid": connection_id, "sid": server_id},
        )


def downgrade() -> None:
    bind = op.get_bind()

    # tools.mcp_server_id 在 upgrade 中原样保留，因此无需反向映射。
    # 仅删除 connection_id FK/列。
    op.drop_constraint("fk_tools_connection_id", "tools", type_="foreignkey")
    op.drop_column("tools", "connection_id")

    # 仅删除 upgrade 创建的 connections。由于基于 `_m9_migrated_connections`
    # 追踪表中的 row，因此用户手动创建的 type='mcp'
    # connection 会保留。之后再 drop 追踪表本身。
    # 为使已应用旧版 m9 的 DB（无追踪表）也能安全 downgrade，
    # 先检查表是否存在。
    tracking_exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = '_m9_migrated_connections'"
        )
    ).scalar()
    if tracking_exists:
        bind.execute(
            sa.text(
                "DELETE FROM connections "
                "WHERE id IN (SELECT connection_id FROM _m9_migrated_connections)"
            )
        )
        op.execute("DROP TABLE _m9_migrated_connections")
