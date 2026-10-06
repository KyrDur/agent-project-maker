# M6 m12 Cleanup Migration Spec

**Revision ID**: `m12_drop_legacy_columns`
**down_revision**: `m11_custom_connection` (文件名 `m11_custom_credential_migration.py` 内部 `revision = "m11_custom_connection"`)
**作者**: Pichai (TTH silo architect)
**日期**: 2026-04-21
**ADR 参照**: [ADR-008 Connection Entity](./adr-008-connection-entity.md) §4, §6

---

## 1. 目标

M4/M5 期间迁移到 Connection 实体后已变 dead 的**legacy 列/table/fallback**全部移除，将 `tools.connection_id` 路径确立为 **single source of truth**。

### 非目标
- 选项 D (在 PATCH /api/tools/{id} 中添加 connection_id 字段) — M6.1 独立 PR
- `agent_tools.connection_id` override — M5.5 独立 PR
- frontend 新功能/重设计 — 禁止

---

## 2. 移除对象

### 2.1 列 (drop)

| 表 | 列 | 原 FK/类型 | 创建位置 |
|--------|------|--------------|-----------|
| `tools` | `mcp_server_id` | FK → `mcp_servers.id`, Uuid nullable | `aa5b4cc59ddb` (initial) — **创建时无名称** |
| `tools` | `auth_config` | JSON nullable (明文, M9 中迁移到 connections.extra_config.env_vars) | `aa5b4cc59ddb` (initial) |
| `tools` | `credential_id` | FK → `credentials.id` ON DELETE SET NULL | `m6_add_credentials` → constraint 名称 `fk_tools_credential_id` |
| `agent_tools` | `config` | JSON nullable | `b4e1a2f3c5d7_add_agent_tools_config` |

### 2.2 表 (drop)

| 表 | 备注 |
|--------|------|
| `mcp_servers` | M9 中已复制到 `connections(type='mcp')`。引用该表的 FK: `tools.mcp_server_id`(计划 drop)、`mcp_servers.user_id`(随表消失)、`mcp_servers.credential_id`(随表消失) |

### 2.3 依赖性检查结果 (S2 事前调查)

- **其他引用 `mcp_servers` 作为 FK 的表**: 只有 `tools.mcp_server_id` **一个**。`connections` 不引用 `mcp_servers` (独立复制后，link 仅通过 `tools.connection_id`)。因此按 `tools.mcp_server_id` drop → `mcp_servers` drop 顺序安全。
- **`connections` 表定义中是否有 mcp 相关列**: 无。`connections` 仅以 FK 方式引用 `credentials`(`ondelete=SET NULL`)。MCP URL/auth 仅存在于 `extra_config.env_vars` JSON 中，没有 schema FK。
- **migration chain 顺序确认**: `aa5b4cc59ddb` → ... → `m6_add_credentials`(fk_tools_credential_id) → `m7_add_credential_field_keys` → `m8_add_connections` → `m9_migrate_mcp_to_connections`(fk_tools_connection_id + tools.connection_id) → `m10_prebuilt_connection` → `m11_custom_connection` → **`m12_drop_legacy_columns`** (新增)。

---

## 3. upgrade 顺序 (重要)

PostgreSQL 中 DDL 在 transaction 内执行，因此中途失败时 Alembic 会自动 rollback。即便如此，也必须严格遵守依赖顺序:

```
1) FK constraint drop (tools)
   - fk_tools_mcp_server_id            # initial 中无名创建 → PG 默认名 "tools_mcp_server_id_fkey"
   - fk_tools_credential_id            # m6 中显式创建的名称
2) drop tools 列
   - tools.mcp_server_id
   - tools.auth_config
   - tools.credential_id
3) agent_tools.config drop
4) drop mcp_servers 表
   (mcp_servers 内部的 fk_mcp_servers_credential_id / user_id FK 会由 drop_table 自动清理)
5) orphan index cleanup — 当前 scope 无 (tools.mcp_server_id / auth_config / credential_id 无独立 index，agent_tools.config 也无)
```

### 3.1 FK 名称实体确认 (禁止猜测)

| FK | 名称 | 依据 |
|----|------|------|
| `tools.mcp_server_id → mcp_servers.id` | **`tools_mcp_server_id_fkey`** (PostgreSQL 自动) | `aa5b4cc59ddb` line 145-148 中以无名 `sa.ForeignKeyConstraint([...])` 创建。PG 按 `<table>_<col>_fkey` convention 自动命名 |
| `tools.credential_id → credentials.id` | **`fk_tools_credential_id`** | `m6_add_credentials.py` line 38-45 中通过 `op.create_foreign_key("fk_tools_credential_id", ...)` |

**生产部署前务必**:
```sql
\d tools
-- 或
SELECT conname FROM pg_constraint
WHERE conrelid = 'tools'::regclass AND contype = 'f';
```
用以再次确认实际名称后，再确定 m12 文件中的 drop_constraint 名称。以防其他环境被手动 rename。

### 3.2 aiosqlite 测试兼容

- aiosqlite in-memory 测试由 `conftest.py` 根据模型定义创建表，因此一般不会在测试中执行 m12 本身 (不运行 `upgrade head`，而使用基于模型的 `create_all`)。
- m9/m10/m11 precedent: alembic round-trip 验证**仅在 docker PostgreSQL 中**执行。
- 不需要 `op.batch_alter_table` 的 drop。tools/agent_tools 在 PostgreSQL 中简单使用 `op.drop_column`/`op.drop_constraint` 即可。

---

## 4. downgrade 策略

**不可逆**: 此 migration 会**永久删除**列和表。downgrade **只恢复 schema 结构**，无法恢复原始数据。

### 4.1 downgrade 实现要求

1. 重新创建 `mcp_servers` 表 (空表，无原始数据) — 列定义必须与 initial migration 一致
2. 重新创建 `tools.mcp_server_id` 列 + FK(`tools_mcp_server_id_fkey`) (默认 NULL)
3. 重新创建 `tools.auth_config` JSON nullable
4. 重新创建 `tools.credential_id` 列 + FK(`fk_tools_credential_id`)
5. 重新创建 `agent_tools.config` JSON nullable
6. 重新创建 `mcp_servers.credential_id` 列 + FK(`fk_mcp_servers_credential_id`) (m6 中曾创建)

### 4.2 明确注释

downgrade 函数顶部必须包含以下注释:
```python
# downgrade: structure only — DATA LOSS IS PERMANENT.
# tools.mcp_server_id / auth_config / credential_id, agent_tools.config,
# mcp_servers 表的原始数据不会恢复。
# 若生产环境需要 rollback，请使用 DB snapshot 恢复，而非 alembic downgrade。
```

### 4.3 downgrade 顺序 (逆序)

```
1) 重新创建 mcp_servers 表 (与 initial 列定义一致，空状态)
2) 重新创建 mcp_servers.credential_id 列 + fk_mcp_servers_credential_id
3) 重新创建 agent_tools.config 列
4) 重新创建 tools.auth_config 列
5) 重新创建 tools.credential_id 列 + fk_tools_credential_id
6) 重新创建 tools.mcp_server_id 列 + tools_mcp_server_id_fkey
```

---

## 5. 生产 migration 指南

### 5.1 pre-check 查询 (BEFORE `alembic upgrade`)

在生产 PG 中**执行全部**以下查询并确认结果后再继续:

```sql
-- (A) 检查 M4/M5 迁移遗漏的 CUSTOM tool — 必须为 0
--     m11 应已按 (user_id, credential_id) 创建 connection
SELECT COUNT(*) AS stale_custom_tools
FROM tools
WHERE type = 'custom'
  AND credential_id IS NOT NULL
  AND connection_id IS NULL;
-- 预期: 0
-- 若不为 0 → 重跑 m11 或手动 mapping 后再继续

-- (B) 检查 dead mcp_server_id 引用 — 必须为 0
--     m9 应已将所有 mcp_server_id 映射为 connection_id
SELECT COUNT(*) AS stale_mcp_tools
FROM tools
WHERE mcp_server_id IS NOT NULL
  AND connection_id IS NULL;
-- 预期: 0
-- 若不为 0 → 存在 m9 因 credential_auth_recoverable=False 跳过的 MCP server (m9 line 183-228 fallthrough)
--            → 恢复 credential.field_keys 后重跑 m9，或手动重新绑定对应 tool

-- (C) 确认 agent_tools.config 实际使用情况 (S1 Bezos 分析 input)
SELECT COUNT(*) AS non_empty_agent_tool_configs
FROM agent_tools
WHERE config IS NOT NULL
  AND config::text <> '{}'
  AND config::text <> 'null';
-- 预期: S1 删除分析允许的水平。若有值，先确认 S1 报告中 chat_service.py:445 merge 逻辑如何使用该值，再决定 drop。

-- (D) 参考: mcp_servers row 数
SELECT COUNT(*) FROM mcp_servers;
-- 记录用。M9 中应已复制等量 connection。
```

### 5.2 执行 upgrade

```bash
cd backend
uv run alembic upgrade head   # 应用 m12
# 确认
psql -U moldy -d moldy -c "\d tools"
psql -U moldy -d moldy -c "\d agent_tools"
psql -U moldy -d moldy -c "SELECT to_regclass('mcp_servers');"  # 预期 NULL
```

### 5.3 round-trip 验证 (dev/stg)

```bash
uv run alembic upgrade head
uv run alembic downgrade -1   # m12 downgrade (恢复结构, 无数据)
uv run alembic upgrade head   # 重新应用
```

### 5.4 rollback 场景

| 情况 | 应对 |
|------|------|
| `alembic upgrade` 中失败 | PostgreSQL DDL 为 transactional — 自动 rollback。分析原因后重试。 |
| upgrade 完成后发现 runtime 问题 | `alembic downgrade -1` **仅恢复 schema**。原始数据永久丢失。**恢复 DB snapshot 才是正确做法**。 |
| aiosqlite 测试环境 | m12 在未先运行 `upgrade head` 的环境中只执行 drop 会失败。测试使用基于模型定义的 `create_all`，因此实际不会走此路径 (现有 precedent)。 |

---

## 6. 模型层变更 spec (S3 Jensen 指南)

### 6.1 `backend/app/models/tool.py`

**1) 完整删除 `MCPServer` class** (当前 line 35-59):
- 整个 class 定义 + `__tablename__ = "mcp_servers"`
- `tools` relationship (mcp_server → tools back_populates)
- `credential` relationship

**2) 从 `Tool` 模型中删除**:
- `mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mcp_servers.id"))` (line 72)
- `auth_config: Mapped[dict | None] = mapped_column(JSON)` (line 82)
- `credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)` (line 83-85)
- `mcp_server: Mapped[MCPServer | None] = relationship(back_populates="tools")` (line 92)
- `credential: Mapped[Credential | None] = relationship(foreign_keys=[credential_id], lazy="joined")` (line 96-98)

**3) 从 `AgentToolLink` 中删除**:
- `config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)` (line 30)

**4) `Tool.auth_type` 字段** **保留** — auth_type 在 PREBUILT/CUSTOM 区分等 runtime 中仍在使用。M6 scope 仅为 auth_config / credential_id / mcp_server_id。

### 6.2 import 影响范围 (grep 必须)

S3 实现时用以下 grep 全量确认使用位置:
```bash
# 模型 import
rg "from app.models.tool import .*MCPServer" backend/
rg "from app.models import .*MCPServer" backend/

# 列引用
rg "\.mcp_server_id" backend/
rg "\.auth_config" backend/
rg "\.credential_id" backend/app/models/ backend/app/services/ backend/app/routers/ backend/app/agent_runtime/
rg "link\.config|AgentToolLink.*config" backend/

# 表名引用
rg '"mcp_servers"|\bmcp_servers\b' backend/
```

### 6.3 schemas/tool.py 连锁修改

整理 ToolResponse 字段 (必须与 S1 Bezos 报告交叉验证):
- 删除 `_mask_auth_config` method
- 删除 `ToolResponse.auth_config` / `ToolResponse.credential_id` / `ToolResponse.mcp_server_id` 字段
- 完整删除 `MCPServerCreate` / `MCPServerResponse` schema
- 删除 `AgentToolResponse.config` 字段 (API 响应一致性)

frontend `lib/types/` 中也会残留同样 dead 字段 → 由 S4 Zuckerberg 负责。

---

## 7. 测试 guidance

### 7.1 migration 自身测试
- 若存在则扩展 `backend/tests/test_migrations.py` — m12 round-trip 静态验证 (m11 precedent: 使用 `inspect.getsource` 确认 upgrade/downgrade 函数正文契约)
- aiosqlite 的 FK cascade 行为可能与 PG 不同，但**conftest.py 使用基于模型的 create_all**，因此 m12 drop 的列/表自然不存在 → pytest 会自动适配模型变更

### 7.2 功能回归测试
- MCP legacy 场景测试(例如 `test_tool_service_mcp_legacy.py` 类) **删除** — 替换为 connection 路径测试 (S5 Bezos 负责)
- 删除 CUSTOM bridge override 测试 (从 chat_service 中移除对应代码)
- PREBUILT env fallback 测试 **保留** (与 CUSTOM/MCP 的不对称是有意设计，HANDOFF.md invariant)

### 7.3 实际 PG 验证 (必需)
在 docker-compose PostgreSQL 中完整执行 `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` round-trip PASS。

---

## 8. 给 Jensen 的具体指示

### 8.1 m12 文件模板

文件: `backend/alembic/versions/m12_drop_legacy_columns.py`

```python
"""M12: drop legacy columns/tables after connection entity migration

Revision ID: m12_drop_legacy_columns
Revises: m11_custom_connection
Create Date: 2026-04-21

ADR-008 §4 / §6 实施完成 — 在 M4/M5 迁移到 Connection 实体后
删除已 dead 的 legacy 列/表。tools.connection_id 成为 single
source of truth。

## 移除对象
- tools.mcp_server_id (FK: tools_mcp_server_id_fkey, PG 默认名)
- tools.auth_config
- tools.credential_id (FK: fk_tools_credential_id)
- agent_tools.config
- 整个 mcp_servers 表 (m9 中已复制到 connections)

## pre-check (生产环境必需)
应用前先确认 docs/design-docs/m6-cleanup-migration-spec.md §5.1 的 3 个查询结果为 0/0/允许水平。

## downgrade
仅恢复结构，数据永久丢失。生产 rollback 使用 DB snapshot 恢复。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "m12_drop_legacy_columns"
down_revision = "m11_custom_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) FK drop (tools)
    # tools.mcp_server_id FK 由 initial migration 无名创建，因此使用 PG 默认名。
    # 部署前必须通过 `\d tools` 再次确认实际名称。
    op.drop_constraint("tools_mcp_server_id_fkey", "tools", type_="foreignkey")
    op.drop_constraint("fk_tools_credential_id", "tools", type_="foreignkey")

    # 2) drop tools legacy 列
    op.drop_column("tools", "mcp_server_id")
    op.drop_column("tools", "auth_config")
    op.drop_column("tools", "credential_id")

    # 3) agent_tools.config drop
    op.drop_column("agent_tools", "config")

    # 4) drop mcp_servers 表 (内部 FK 由 drop_table 自动清理)
    op.drop_table("mcp_servers")


def downgrade() -> None:
    # downgrade: structure only — DATA LOSS IS PERMANENT.
    # tools.mcp_server_id / auth_config / credential_id, agent_tools.config,
    # mcp_servers 表的原始数据不会恢复。
    # 若生产环境需要 rollback，请使用 DB snapshot 恢复，而非 alembic downgrade。

    # 逆序: mcp_servers → agent_tools.config → tools.auth_config →
    # tools.credential_id → tools.mcp_server_id

    # 1) 重新创建 mcp_servers (initial + m6 列合并版, 空表)
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("auth_type", sa.String(length=20), nullable=False),
        sa.Column("auth_config", sa.JSON(), nullable=True),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credentials.id"],
            name="fk_mcp_servers_credential_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2) 恢复 agent_tools.config
    op.add_column(
        "agent_tools",
        sa.Column("config", sa.JSON(), nullable=True),
    )

    # 3) 恢复 tools.auth_config
    op.add_column(
        "tools",
        sa.Column("auth_config", sa.JSON(), nullable=True),
    )

    # 4) 恢复 tools.credential_id + FK
    op.add_column(
        "tools",
        sa.Column("credential_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tools_credential_id",
        "tools",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5) 恢复 tools.mcp_server_id + FK (与 initial 相同，以无名方式创建，使
    #    PG 默认名 tools_mcp_server_id_fkey 被重新赋予)
    op.add_column(
        "tools",
        sa.Column("mcp_server_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        None,  # PG 默认名 fallback
        "tools",
        "mcp_servers",
        ["mcp_server_id"],
        ["id"],
    )
```

### 8.2 FK 实际名称复核流程

Jensen 开始实现时，在启动 docker-compose PostgreSQL 的状态下:

```bash
cd backend
docker-compose up -d postgres
uv run alembic upgrade head  # 应用到 m11

# 实测 FK 名称
psql postgresql://moldy:moldy@localhost:5432/moldy -c "\
  SELECT conname, pg_get_constraintdef(oid) \
  FROM pg_constraint \
  WHERE conrelid = 'tools'::regclass AND contype = 'f';"
```

预期输出:
```
 conname                   | pg_get_constraintdef
 tools_user_id_fkey        | FOREIGN KEY (user_id) REFERENCES users(id)
 tools_mcp_server_id_fkey  | FOREIGN KEY (mcp_server_id) REFERENCES mcp_servers(id)
 fk_tools_credential_id    | FOREIGN KEY (credential_id) REFERENCES credentials(id) ON DELETE SET NULL
 fk_tools_connection_id    | FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE SET NULL
```

若不是 `tools_mcp_server_id_fkey`，修改 m12 文件中的 `drop_constraint` 名称。

### 8.3 实现 checklist (Jensen self-verify)

1. [ ] 创建 `m12_drop_legacy_columns.py` + 写入实测 FK 名称
2. [ ] `backend/app/models/tool.py` — 删除 MCPServer class + Tool.mcp_server_id/auth_config/credential_id + 2 种 relationship + AgentToolLink.config
3. [ ] `backend/app/schemas/tool.py` — 删除 _mask_auth_config + MCPServer schema + ToolResponse.{auth_config,credential_id,mcp_server_id} + AgentToolResponse.config
4. [ ] `backend/app/services/` — 删除 resolve_server_auth + MCPServer CRUD + chat_service legacy fallback (按 S1 Bezos 报告具体 line 参照)
5. [ ] `backend/app/routers/tools.py` — 删除 4 个 /api/tools/mcp-server* endpoint
6. [ ] `backend/app/agent_runtime/` — 整理 legacy 字段引用
7. [ ] 删除/修改测试 — 按 S1 分类删除 MCP legacy 场景文件，保留 connection path
8. [ ] `rg "mcp_server_id|auth_config|resolve_server_auth|MCPServer|register_mcp_server" backend/app/` → 0
9. [ ] round-trip: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` PASS (docker PG)
10. [ ] `uv run ruff check .` PASS
11. [ ] `uv run pytest` PASS (允许减少后 0 regression)

---

## 9. 风险 & 缓解

| # | 风险 | 缓解 |
|---|--------|------|
| R1 | `tools_mcp_server_id_fkey` 名称可能因环境而不同 | 通过 8.2 流程强制部署前实测 |
| R2 | `agent_tools.config` 中仍有实际使用数据导致功能回归 | §5.1 (C) pre-check + 与 S1 Bezos 报告交叉验证 — 若非空则 S1/S2/S3 共同复审 |
| R3 | m9 中因 `credential_auth_recoverable=False` 跳过的 MCP server 仍存在，导致 m12 后 dangling | §5.1 (B) pre-check 必须执行，若不为 0 则先重跑 m9 |
| R4 | downgrade 后才发现数据丢失 | §4.2 明确注释 + §5.4 rollback 指南 — 正确做法是恢复 DB snapshot |
| R5 | aiosqlite 测试中仍有对 drop 对象模型的引用导致 import error | 通过 S3 6.2 grep checklist 全量清理 |
| R6 | PostgreSQL DDL 为 transactional，中途失败虽会自动 rollback，但若 `op.drop_table` 引用 dangling FK 仍可能失败 | 严格遵守 §3 顺序 (FK drop → column drop → table drop) |

---

## 10. 完成条件 (done-when)

1. 创建 `backend/alembic/versions/m12_drop_legacy_columns.py`，确认 `down_revision = "m11_custom_connection"`
2. `uv run alembic upgrade head` PASS (docker PG), round-trip PASS
3. `psql \d tools` — 无 `mcp_server_id`, `auth_config`, `credential_id`
4. `psql \d agent_tools` — 无 `config`
5. `psql -c "SELECT to_regclass('mcp_servers')"` — NULL
6. `rg "mcp_server_id|auth_config|resolve_server_auth|MCPServer" backend/app/` — 0
7. `uv run pytest` PASS (允许减少后 0 regression)
8. `uv run ruff check .` PASS
