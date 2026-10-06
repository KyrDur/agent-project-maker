# Marketplace Module Contracts (M1-S2)

> 编写日期: 2026-05-18
> 作者: Pichai (TTH Architect)
> 相关 ADR: [ADR-017 — Marketplace Resources](adr-017-marketplace-resources.md)
> 来源: `docs/marketplace-resources-spec.md` v0.1 §10.8, §11
> 目的: 将 backend marketplace domain 的 (a) module 职责 + import 方向、(b) ORM class signature(列/relationship/index)、(c) 核心 Pydantic schema 契约明确文档化，以 unblock Jensen(M2 Slice A~F 实现者)。

---

## 1. Module 边界 (`backend/app/marketplace/`)

新增 folder 共 11 个 module。每个 module 只负责一种职责，import 方向仅允许明确指定的单向关系。

| # | module | 职责 | 使用处 (import 方向) |
|---|------|------|----------------------|
| 1 | `__init__.py` | package marker。不 re-export public symbol (禁止 barrel export)。 | — |
| 2 | `access.py` | 权限矩阵。`can_view_item`, `can_install_item`, `can_manage_item`。**禁止副作用** — 仅 pure function + DB read。 | `service`, `install_service`, `publish_service`, `routers/marketplace` |
| 3 | `schemas.py` | Pydantic v2 输入输出 schema (§3 参见)。禁止直接暴露 DB object。 | 所有 service, `routers/marketplace`, `routers/skills` (origin/publication summary embed) |
| 4 | `service.py` | Catalog list/detail 业务逻辑。filter/sort/pagination。 | `routers/marketplace` |
| 5 | `install_service.py` | install/update/uninstall flow。transaction 边界 + filesystem move。处理 `install_mode`。 | `routers/marketplace` |
| 6 | `publish_service.py` | publish flow。创建 immutable version + ACL upsert + 更新 publication_links。**必须先调用 `secret_scan.scan_package`**。 | `routers/marketplace`, `routers/skills` (间接: upload 仅使用 `secret_scan`) |
| 7 | `origin_service.py` | `derive_origin_summary`, `derive_publication_summary`, `derive_installation_summary`, `derive_credential_summary`, `mark_installation_dirty`。installed resource ↔ marketplace 双向 derivation。 | `service`, `install_service`, `publish_service`, `routers/skills`, `routers/mcp_servers`, `routers/agents` |
| 8 | `secret_scan.py` | `SECRET_FILE_PATTERNS`, `SECRET_CONTENT_PATTERNS`, `scan_package(extracted_dir) -> list[SecretFinding]`。**pure function** — 无 DB 依赖。 | `publish_service`, `install_service`(import 用), `k_skill_importer`, `routers/skills` (upload 回归 guard) |
| 9 | `redaction.py` | `redact_credential_values(text, mapped_env_vars)`, `redact_keys(payload)`。**pure function**。 | `agent_runtime/executor`, `agent_runtime/streaming`, 所有 service layer 的 exception 转换, raw logger formatter |
| 10 | `credential_requirements.py` | requirement mapping + validation + **runtime env injection plan**。`resolve_credential_bindings(db, skill, user, agent_skill_config) -> dict[str, ResolvedCredential]`。 | `install_service`, `agent_runtime/executor` (Slice E), `routers/skills` (credential-bindings endpoints) |
| 11 | `k_skill_importer.py` | upstream sync 主体 (git fetch, discovery, packaging, metadata 提取, upsert)。由 CLI 入口调用。**import 时无副作用**。 | `scripts/sync_k_skill` |

### 1.1 Module 依赖图

```text
                  ┌──────────────────────────────────────────┐
                  │              schemas.py                  │
                  │  (Pydantic — 所有 service 的输入输出契约) │
                  └──────────────────────────────────────────┘
                          ▲   ▲   ▲   ▲   ▲   ▲
                          │   │   │   │   │   │
       ┌──────────────────┘   │   │   │   │   └────────────────────┐
       │                      │   │   │   │                        │
       │                      │   │   │   └──┐                     │
       │                      │   │   │      │                     │
   access.py            origin_service.py    │              credential_requirements.py
       ▲     ▲                ▲              │                     ▲
       │     │                │              │                     │
       │     └────────────────┤              │                     │
       │                      │              │                     │
   service.py          install_service.py    publish_service.py    │
                              ▲                  ▲                 │
                              │                  │                 │
                              │              secret_scan.py        │
                              │                  ▲                 │
                              │                  │                 │
                              └──────────────────┘                 │
                                                                   │
                              k_skill_importer.py ──▶ secret_scan ─┘
                                                  └──▶ credential_requirements

      redaction.py  ◀── (agent_runtime/executor, streaming, service exception 转换)
```

**import 方向规则**:

1. `schemas.py` 不 import marketplace 内任何 module (leaf)。仅 Pydantic + `datetime`/`uuid`/`typing` + `models.marketplace` type hint。
2. `access.py`, `secret_scan.py`, `redaction.py` 不 import marketplace 内其他 module (leaf 或 utility)。
3. `service.py`, `install_service.py`, `publish_service.py`, `k_skill_importer.py` 可自由 import 上述 leaf。**禁止彼此 cross-import** (例如 install_service 不 import publish_service)。
4. `routers/marketplace.py` 仅 import 4 种 service。也可直接 import `models.marketplace`, `schemas.py`。
5. `agent_runtime/` 仅 import `redaction.py` 和 `credential_requirements.py`。禁止绕过 service layer。
6. `origin_service.py` 同时依赖 `models/marketplace`, `models/skill`，因此在 `routers/skills`/`routers/mcp_servers`/`routers/agents` 中直接使用。service 也可调用。

### 1.2 新增 router / model / script

| 路径 | 职责 |
|------|------|
| `backend/app/routers/marketplace.py` | marketplace router (Spec §10.1~§10.7)。`Depends(get_current_user)` + 所有 mutation 使用 `Depends(verify_csrf)`。admin 额外使用 `Depends(require_super_user)` |
| `backend/app/models/marketplace.py` | 6 个 ORM class (§2 参见)。单文件 |
| `backend/app/scripts/sync_k_skill.py` | super_user CLI 入口 (`python -m app.scripts.sync_k_skill ...`)。argparse + 调用 `k_skill_importer.sync_upstream(...)`。**DB session 由 CLI 自行创建** (不依赖 router) |

### 1.3 现有 module 变更影响

| 文件 | 变更 |
|------|------|
| `models/skill.py` | 向 `Skill` 添加 12 个列 (m41)。向 `AgentSkillLink` 添加 `config: Mapped[dict \| None]` (m42) |
| `routers/skills.py` | 添加 `/api/skills/{id}/credential-requirements`, `/credential-bindings[/{key}]` 4 个 endpoint。`upload` endpoint 调用 `secret_scan.scan_package`。响应 embed `origin_summary`/`publication_summary` (`origin_service` 调用) |
| `routers/mcp_servers.py` | 响应中仅 embed `origin_summary`/`publication_summary` (Phase 1 尚未实现 MCP marketplace install) |
| `routers/agents.py` | 响应中仅 embed `origin_summary`/`publication_summary` (Phase 1 尚未实现 Agent marketplace install) |
| `agent_runtime/executor.py` | `build_agent`: per-thread copytree + 修改 skills_sources。`_create_skill_execute_tool`: signature + env injection + redaction wrap (Slice E) |
| `agent_runtime/streaming.py` | 对 tool_call_result payload 应用 `redaction.redact_keys` |
| `skills/runtime.py:build_skills_for_agent` | 扩展为返回 `SkillRuntimeDescriptor` 列表 (id, slug, original_storage_path, storage_path, credential_bindings) |
| `skills/service.py` | 在 content/files/PATCH 4 个 endpoint 中 best-effort 调用 `origin_service.mark_installation_dirty` |
| `credentials/definitions/__init__.py` | import 新增 8 个定义 (自动 register) |
| `config.py` | 添加 `k_skill_upstream_url`, `k_skill_upstream_ref`, `k_skill_sync_dir`, `k_skill_builtin_storage_dir` |

---

## 2. ORM 契约 — `backend/app/models/marketplace.py`

`SkillCredentialBinding` 语义上属于 marketplace domain，但与 `skills` 强耦合，因此一并放在本文件中 (共 6 个 class)。所有 class 均采用 SQLAlchemy 2.0 declarative + async + `mapped_column` 模式(与 ADR-016/-009 相同)。

### 2.1 公共 import header (参考用)

```python
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import User
```

### 2.2 `MarketplaceItem`

表: `marketplace_items` (m40)。

| 列 | 类型 | NULL | 默认 | 备注 |
|------|------|------|------|------|
| `id` | `Mapped[UUID]` `PG_UUID(as_uuid=True)` PK | NO | `uuid4` | |
| `resource_type` | `Mapped[str]` `String(20)` | NO | — | CHECK `('agent','mcp','skill')` |
| `owner_user_id` | `Mapped[UUID \| None]` FK `users.id` ON DELETE SET NULL | YES | NULL | system item 为 NULL |
| `is_system` | `Mapped[bool]` `Boolean` | NO | FALSE | |
| `is_listed` | `Mapped[bool]` `Boolean` | NO | FALSE | super_user toggle |
| `name` | `Mapped[str]` `String(200)` | NO | — | |
| `slug` | `Mapped[str]` `String(220)` | NO | — | |
| `description` | `Mapped[str \| None]` `Text` | YES | NULL | |
| `icon_url` | `Mapped[str \| None]` `Text` | YES | NULL | |
| `visibility` | `Mapped[str]` `String(20)` | NO | `'private'` | CHECK `('private','restricted','public','unlisted','system')` |
| `status` | `Mapped[str]` `String(20)` | NO | `'draft'` | CHECK `('draft','published','deprecated','disabled')` |
| `moderation_status` | `Mapped[str]` `String(20)` | NO | `'approved'` | 运营者可见状态 |
| `source_kind` | `Mapped[str \| None]` `String(40)` | YES | NULL | `'user' \| 'k-skill' \| 'import' \| 'system_seed'` |
| `source_url` | `Mapped[str \| None]` `Text` | YES | NULL | |
| `source_external_id` | `Mapped[str \| None]` `String(240)` | YES | NULL | k-skill upstream name |
| `latest_version_id` | `Mapped[UUID \| None]` FK `marketplace_versions.id` ON DELETE SET NULL | YES | NULL | circular FK — m40 中通过 ALTER 添加 |
| `tags` | `Mapped[list \| None]` `JSON` | YES | NULL | |
| `categories` | `Mapped[list \| None]` `JSON` | YES | NULL | |
| `locale` | `Mapped[str \| None]` `String(20)` | YES | NULL | |
| `metadata_json` | `Mapped[dict \| None]` `JSON` | YES | NULL | 列名为 `metadata` (为避开保留字，attribute 推荐用 `metadata_json`) |
| `created_at` | `Mapped[datetime]` `DateTime(timezone=True)` | NO | `now()` | |
| `updated_at` | `Mapped[datetime]` `DateTime(timezone=True)` | NO | `now()` | `onupdate=now()` |
| `published_at` | `Mapped[datetime \| None]` | YES | NULL | |

**Constraints**:
- `ck_marketplace_resource_type CHECK (resource_type IN ('agent','mcp','skill'))`
- `ck_marketplace_visibility CHECK (visibility IN ('private','restricted','public','unlisted','system'))`
- `ck_marketplace_status CHECK (status IN ('draft','published','deprecated','disabled'))`
- `ck_marketplace_system_owner CHECK ((is_system = false) OR (owner_user_id IS NULL))`

**Indexes**:
- `uq_marketplace_items_system_slug UNIQUE (resource_type, slug) WHERE is_system = true` (partial)
- `uq_marketplace_items_owner_slug UNIQUE (owner_user_id, resource_type, slug) WHERE owner_user_id IS NOT NULL` (partial)
- `ix_marketplace_items_listed (is_listed, visibility, status)`

**Relationships**:
- `owner: Mapped[User | None] = relationship(User, foreign_keys=[owner_user_id])`
- `versions: Mapped[list[MarketplaceVersion]] = relationship("MarketplaceVersion", back_populates="item", foreign_keys="MarketplaceVersion.item_id", cascade="all, delete-orphan")`
- `latest_version: Mapped[MarketplaceVersion | None] = relationship("MarketplaceVersion", foreign_keys=[latest_version_id], post_update=True)` — 通过 `post_update=True` 处理 circular FK
- `acl_entries: Mapped[list[MarketplaceItemACL]] = relationship("MarketplaceItemACL", back_populates="item", cascade="all, delete-orphan")`
- `installations: Mapped[list[MarketplaceInstallation]] = relationship("MarketplaceInstallation", back_populates="item", cascade="all, delete-orphan")`
- `publication_links: Mapped[list[MarketplacePublicationLink]] = relationship("MarketplacePublicationLink", back_populates="item", cascade="all, delete-orphan")`

### 2.3 `MarketplaceItemACL`

表: `marketplace_item_acl` (m40)。composite PK。

| 列 | 类型 | NULL | 默认 | 备注 |
|------|------|------|------|------|
| `item_id` | `Mapped[UUID]` FK `marketplace_items.id` ON DELETE CASCADE | NO | — | PK part |
| `user_id` | `Mapped[UUID]` FK `users.id` ON DELETE CASCADE | NO | — | PK part |
| `permission` | `Mapped[str]` `String(20)` | NO | `'install'` | CHECK `('view','install','manage')` |
| `created_at` | `Mapped[datetime]` `DateTime(timezone=True)` | NO | `now()` | |

**Constraints**: `PRIMARY KEY (item_id, user_id)`, `ck_marketplace_acl_permission`.

**Relationships**:
- `item: Mapped[MarketplaceItem] = relationship(back_populates="acl_entries")`
- `user: Mapped[User] = relationship(User)`

### 2.4 `MarketplaceVersion`

表: `marketplace_versions` (m40)。**immutable** — service layer 禁止 update。

| 列 | 类型 | NULL | 默认 | 备注 |
|------|------|------|------|------|
| `id` | `Mapped[UUID]` PK | NO | `uuid4` | |
| `item_id` | `Mapped[UUID]` FK `marketplace_items.id` ON DELETE CASCADE | NO | — | |
| `version_label` | `Mapped[str]` `String(80)` | NO | — | 用户显示用 (例如 `0.1.0`) |
| `version_number` | `Mapped[int]` `Integer` | NO | — | 每个 item monotonic 增长 |
| `resource_type` | `Mapped[str]` `String(20)` | NO | — | CHECK `('agent','mcp','skill')` |
| `payload_kind` | `Mapped[str]` `String(40)` | NO | — | CHECK `('skill_package','agent_spec','mcp_template')` |
| `payload` | `Mapped[dict]` `JSON` | NO | — | 按 resource_type 的结构 (skill_package: storage meta / agent_spec: agent JSON / mcp_template: server config) |
| `storage_path` | `Mapped[str \| None]` `String(500)` | YES | NULL | filesystem snapshot 路径 (仅 skill 使用) |
| `content_hash` | `Mapped[str]` `String(64)` | NO | — | SHA-256 hex |
| `size_bytes` | `Mapped[int]` `Integer` | NO | 0 | |
| `credential_requirements` | `Mapped[list \| None]` `JSON` | YES | NULL | `[CredentialRequirementOut.model_dump()]` |
| `dependency_requirements` | `Mapped[list \| None]` `JSON` | YES | NULL | future use |
| `execution_profile` | `Mapped[dict \| None]` `JSON` | YES | NULL | `{support_level, runners, requires_*}` |
| `release_notes` | `Mapped[str \| None]` `Text` | YES | NULL | |
| `source_commit` | `Mapped[str \| None]` `String(80)` | YES | NULL | k-skill upstream commit |
| `source_ref` | `Mapped[str \| None]` `String(120)` | YES | NULL | branch/tag |
| `source_path` | `Mapped[str \| None]` `Text` | YES | NULL | upstream 中的 path |
| `created_by` | `Mapped[UUID \| None]` FK `users.id` ON DELETE SET NULL | YES | NULL | |
| `created_at` | `Mapped[datetime]` | NO | `now()` | |

**Constraints**:
- `ck_marketplace_version_resource_type`
- `ck_marketplace_payload_kind`

**Indexes**:
- `uq_marketplace_versions_item_number UNIQUE (item_id, version_number)`
- `ix_marketplace_versions_content_hash (content_hash)`

**Relationships**:
- `item: Mapped[MarketplaceItem] = relationship(back_populates="versions", foreign_keys=[item_id])`
- `installations: Mapped[list[MarketplaceInstallation]] = relationship(back_populates="version", foreign_keys="MarketplaceInstallation.version_id")`
- `created_by_user: Mapped[User | None] = relationship(User, foreign_keys=[created_by])`

### 2.5 `MarketplaceInstallation`

表: `marketplace_installations` (m40)。

| 列 | 类型 | NULL | 默认 | 备注 |
|------|------|------|------|------|
| `id` | `Mapped[UUID]` PK | NO | `uuid4` | |
| `user_id` | `Mapped[UUID]` FK `users.id` ON DELETE CASCADE | NO | — | 安装者 |
| `item_id` | `Mapped[UUID]` FK `marketplace_items.id` ON DELETE CASCADE | NO | — | |
| `version_id` | `Mapped[UUID]` FK `marketplace_versions.id` ON DELETE **RESTRICT** | NO | — | 删除 version 时保护 installation |
| `resource_type` | `Mapped[str]` `String(20)` | NO | — | |
| `installed_agent_id` | `Mapped[UUID \| None]` FK `agents.id` ON DELETE CASCADE | YES | NULL | |
| `installed_mcp_server_id` | `Mapped[UUID \| None]` FK `mcp_servers.id` ON DELETE CASCADE | YES | NULL | |
| `installed_skill_id` | `Mapped[UUID \| None]` FK `skills.id` ON DELETE CASCADE | YES | NULL | |
| `install_status` | `Mapped[str]` `String(30)` | NO | `'active'` | CHECK `('active','needs_setup','disabled','uninstalled')` |
| `is_dirty` | `Mapped[bool]` `Boolean` | NO | FALSE | |
| `installed_at` | `Mapped[datetime]` | NO | `now()` | |
| `updated_at` | `Mapped[datetime]` | NO | `now()` | `onupdate=now()` |

**Constraints**:
- `ck_marketplace_install_resource_target` — 按 `resource_type` 恰好一个 `installed_*_id` 为 NOT NULL (完全遵循 Spec §3.5)
- `ck_marketplace_install_status`

**Indexes**:
- `ix_marketplace_install_user_item (user_id, item_id)`
- `ix_marketplace_install_user_resource (user_id, resource_type)`

**Relationships**:
- `item: Mapped[MarketplaceItem] = relationship(back_populates="installations", foreign_keys=[item_id])`
- `version: Mapped[MarketplaceVersion] = relationship(back_populates="installations", foreign_keys=[version_id])`
- `user: Mapped[User] = relationship(User, foreign_keys=[user_id])`
- `installed_skill: Mapped["Skill | None"] = relationship("Skill", foreign_keys=[installed_skill_id])` — `agents`/`mcp_servers` 同样模式

### 2.6 `MarketplacePublicationLink`

表: `marketplace_publication_links` (m40)。我的 resource ↔ 我 publish 的 item 反向引用。

| 列 | 类型 | NULL | 默认 | 备注 |
|------|------|------|------|------|
| `id` | `Mapped[UUID]` PK | NO | `uuid4` | |
| `user_id` | `Mapped[UUID]` FK `users.id` ON DELETE CASCADE | NO | — | publisher |
| `item_id` | `Mapped[UUID]` FK `marketplace_items.id` ON DELETE CASCADE | NO | — | |
| `resource_type` | `Mapped[str]` `String(20)` | NO | — | |
| `source_agent_id` | `Mapped[UUID \| None]` FK `agents.id` ON DELETE CASCADE | YES | NULL | |
| `source_mcp_server_id` | `Mapped[UUID \| None]` FK `mcp_servers.id` ON DELETE CASCADE | YES | NULL | |
| `source_skill_id` | `Mapped[UUID \| None]` FK `skills.id` ON DELETE CASCADE | YES | NULL | |
| `created_at` | `Mapped[datetime]` | NO | `now()` | |
| `updated_at` | `Mapped[datetime]` | NO | `now()` | `onupdate=now()` |

**Constraints**:
- `ck_pub_link_resource_type`
- `ck_pub_link_target` — 按 resource_type 恰好一个 source_*_id NOT NULL

**Indexes**:
- `uq_pub_link_item UNIQUE (item_id)` — 每 1 个 item 对应 1 个 publication link
- `ix_pub_link_resource (user_id, resource_type)`

**Relationships**:
- `item: Mapped[MarketplaceItem] = relationship(back_populates="publication_links")`
- `user: Mapped[User] = relationship(User, foreign_keys=[user_id])`

### 2.7 `SkillCredentialBinding`

表: `skill_credential_bindings` (m43)。属于 Marketplace domain，但与 `skills` 强耦合 → 放在 `models/marketplace.py`。

| 列 | 类型 | NULL | 默认 | 备注 |
|------|------|------|------|------|
| `id` | `Mapped[UUID]` PK | NO | `uuid4` | |
| `skill_id` | `Mapped[UUID]` FK `skills.id` ON DELETE CASCADE | NO | — | |
| `user_id` | `Mapped[UUID]` FK `users.id` ON DELETE CASCADE | NO | — | |
| `requirement_key` | `Mapped[str]` `String(120)` | NO | — | version.credential_requirements 中的 `key` |
| `credential_id` | `Mapped[UUID]` FK `credentials.id` ON DELETE **RESTRICT** | NO | — | 保护 binding |
| `scope` | `Mapped[str]` `String(20)` | NO | `'skill'` | CHECK `('skill','agent_skill')` — Phase 1 仅使用 `'skill'` |
| `created_at` | `Mapped[datetime]` | NO | `now()` | |
| `updated_at` | `Mapped[datetime]` | NO | `now()` | `onupdate=now()` |

**Constraints**:
- `ck_skill_credential_binding_scope`
- `UNIQUE (skill_id, user_id, requirement_key, scope)`

**Relationships**:
- `skill: Mapped["Skill"] = relationship("Skill")` — 建议向 `Skill.credential_bindings` 添加 back_populates
- `credential: Mapped["Credential"] = relationship("Credential")`
- `user: Mapped[User] = relationship(User)`

### 2.8 扩展 `Skill` / `AgentSkillLink` (`models/skill.py` 修改)

向 `Skill` 添加的列全部以 `mapped_column(..., nullable=...)` 形式定义。m41 backfill: 现有 row 为 `source_kind='user'`，text skill 为 `origin_kind='created_by_me'`，package skill 为 `origin_kind='imported_by_me'`。

| 列 | 类型 | NULL | 默认 |
|------|------|------|------|
| `is_system` | `Boolean` | NO | FALSE |
| `source_kind` | `String(40)` | YES | NULL |
| `source_marketplace_item_id` | `PG_UUID` FK `marketplace_items.id` SET NULL | YES | NULL |
| `source_marketplace_version_id` | `PG_UUID` FK `marketplace_versions.id` SET NULL | YES | NULL |
| `source_commit` | `String(80)` | YES | NULL |
| `credential_requirements` | `JSON` | YES | NULL |
| `execution_profile` | `JSON` | YES | NULL |
| `origin_kind` | `String(40)` | NO | `'created_by_me'` |
| `origin_user_id` | `PG_UUID` FK `users.id` SET NULL | YES | NULL |
| `origin_marketplace_item_id` | `PG_UUID` FK `marketplace_items.id` SET NULL | YES | NULL |
| `origin_marketplace_version_id` | `PG_UUID` FK `marketplace_versions.id` SET NULL | YES | NULL |
| `is_dirty` | `Boolean` | NO | FALSE |

向 `AgentSkillLink` 添加:

| 列 | 类型 | NULL | 默认 |
|------|------|------|------|
| `config` | `JSON` | YES | NULL |

保存示例: `{"credential_bindings": {"srt_account": "<credential-uuid>"}}`。

---

## 3. 核心 Pydantic schema 契约 (`backend/app/marketplace/schemas.py`)

完全遵循 Spec §10.8。Pydantic v2 (`model_config = ConfigDict(from_attributes=True)` 允许 ORM 转换)。所有时间均为 `datetime` (假定 UTC)。

### 3.1 `MarketplaceItemOut` — Catalog/Detail 响应

```python
class MarketplaceItemOut(BaseModel):
    id: UUID
    resource_type: Literal["agent", "mcp", "skill"]
    name: str
    slug: str
    description: str | None
    visibility: Literal["private", "restricted", "public", "unlisted", "system"]
    status: Literal["draft", "published", "deprecated", "disabled"]
    is_system: bool
    is_listed: bool
    latest_version: MarketplaceVersionSummary | None
    credential_summary: CredentialSummaryOut
    execution_profile: dict[str, Any] | None = None
    origin_summary: ResourceOriginSummaryOut | None = None
    publication_summary: ResourcePublicationSummaryOut
    installation: MarketplaceInstallationSummary
    model_config = ConfigDict(from_attributes=True)
```

- `latest_version` 为 item.latest_version → `MarketplaceVersionSummary.model_validate(...)`。
- `credential_summary`, `installation` 为调用 `origin_service.derive_*` 的结果。
- `origin_summary` 是从 owner 视角的来源 — list 响应允许 null，detail 中填充。
- `publication_summary` 在所有响应中填充 (item-level)。

### 3.2 `ResourceOriginSummaryOut`

```python
class ResourceOriginSummaryOut(BaseModel):
    kind: Literal[
        "created_by_me", "imported_by_me", "built_in_k_skill",
        "shared_with_me", "community", "system_seed",
    ]
    label: str
    source_name: str | None = None
    source_user_id: UUID | None = None
    marketplace_item_id: UUID | None = None
    marketplace_version_id: UUID | None = None
```

derivation 规则 (Spec §7.5 + PRD §6):

| 条件 | kind |
|------|------|
| `skills.is_system=True AND skills.source_kind='k-skill'` | `built_in_k_skill` |
| `skills.is_system=True AND skills.source_kind='system_seed'` | `system_seed` |
| `skills.source_kind in ('user','import')` AND `origin_user_id != current_user AND item.visibility='restricted'` | `shared_with_me` |
| `skills.source_kind in ('user','import')` AND `origin_user_id != current_user AND item.visibility='public'` | `community` |
| `origin_user_id == current_user AND source_marketplace_item_id IS NOT NULL` | `imported_by_me` |
| `source_marketplace_item_id IS NULL` (直接创建) | `created_by_me` |

### 3.3 `ResourcePublicationSummaryOut`

```python
class ResourcePublicationSummaryOut(BaseModel):
    state: Literal[
        "not_published", "draft",
        "published_private", "published_restricted",
        "published_public_listed", "published_public_unlisted",
        "published_unlisted", "disabled",
    ]
    item_id: UUID | None = None
    visibility: Literal["private", "restricted", "public", "unlisted", "system"] | None = None
    status: Literal["draft", "published", "deprecated", "disabled"] | None = None
    is_listed: bool = False
    latest_version_id: UUID | None = None
    version_number: int | None = None
    shared_user_count: int = 0
```

state derivation 是 publication_link → item.status × item.visibility × item.is_listed 的决策表。

| item 状态 | state |
|-----------|-------|
| 无 | `not_published` |
| `status='draft'` | `draft` |
| `status='disabled'` | `disabled` |
| `status='published'` AND `visibility='private'` | `published_private` |
| `status='published'` AND `visibility='restricted'` | `published_restricted` |
| `status='published'` AND `visibility='public'` AND `is_listed=true` | `published_public_listed` |
| `status='published'` AND `visibility='public'` AND `is_listed=false` | `published_public_unlisted` |
| `status='published'` AND `visibility='unlisted'` | `published_unlisted` |

`shared_user_count` 为 `marketplace_item_acl` row count。

### 3.4 `MarketplaceInstallationSummary`

```python
class MarketplaceInstallationSummary(BaseModel):
    installed: bool
    installation_id: UUID | None = None
    installed_resource_id: UUID | None = None  # installed_skill_id / installed_agent_id / installed_mcp_server_id
    status: Literal["active", "needs_setup", "disabled", "uninstalled"] | None = None
    update_available: bool = False
    dirty: bool = False
```

derivation 输入: `(current_user, item, latest_version, installation_row?)`。`update_available = installation.version_id != item.latest_version_id`。`dirty` 为 installation.is_dirty 与 installed_skill.is_dirty 的 OR。

### 3.5 `CredentialRequirementOut`

```python
class CredentialRequirementOut(BaseModel):
    key: str                       # version.credential_requirements 内 unique
    definition_key: str            # credentials.definitions 中注册的 key (例如 'srt_account')
    required: bool
    label: str
    description: str | None = None
    fields: list[str]              # ['username', 'password']
    injection: Literal["env", "config"]   # Phase 1 仅使用 'env'
    scope: Literal["user", "system_dependency", "manual"]
```

- `scope='user'`: 需要普通用户 credential。
- `scope='system_dependency'`: hosted_proxy 等 system credential。无需用户 binding。
- `scope='manual'`: 用户在外部直接登录 (kakaotalk-mac 等)。不使用 credential。

Publish/k-skill import 输入用 `CredentialRequirementIn` 为相同字段 + 添加 `env_map: dict[str, str]` (用户 publish 时 env_map 为可选)。

### 3.6 `InstallMarketplaceItemIn`

```python
class InstallMarketplaceItemIn(BaseModel):
    version_id: UUID | None = None
    name_override: str | None = None
    credential_bindings: dict[str, UUID] = Field(default_factory=dict)  # {requirement_key: credential_id}
    install_missing_credentials: Literal["reject", "needs_setup"] = "needs_setup"
    install_mode: Literal["reuse_or_update", "new_copy", "overwrite_existing"] = "reuse_or_update"
```

### 3.7 `PublishSkillIn`

```python
class PublishSkillIn(BaseModel):
    item_id: UUID | None = None      # 新 item 时为 None，新 version 时为现有 item id
    visibility: Literal["private", "restricted", "public", "unlisted"]
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    release_notes: str | None = None
    credential_requirements: list[CredentialRequirementIn] = Field(default_factory=list)
    acl_user_ids: list[UUID] = Field(default_factory=list)  # restricted 时至少 1 人

    @model_validator(mode="after")
    def _validate_acl(self) -> "PublishSkillIn":
        if self.visibility == "restricted" and not self.acl_user_ids:
            raise ValueError("marketplace_acl_required")
        return self
```

### 3.8 辅助 schema (参考)

```python
class MarketplaceVersionSummary(BaseModel):
    id: UUID
    version_label: str
    version_number: int
    content_hash: str
    source_commit: str | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class CredentialSummaryOut(BaseModel):
    status: Literal["none", "optional", "required", "hosted_proxy", "manual_login"]
    required_count: int = 0
    optional_count: int = 0
    missing_required_count: int = 0

class UpdateMarketplaceInstallationIn(BaseModel):
    strategy: Literal["overwrite", "install_new_copy", "keep_current"]

class CredentialRequirementIn(BaseModel):
    key: str
    definition_key: str
    required: bool = True
    label: str
    description: str | None = None
    fields: list[str]
    injection: Literal["env", "config"] = "env"
    scope: Literal["user", "system_dependency", "manual"] = "user"
    env_map: dict[str, str] | None = None
```

### 3.9 响应 embed — `routers/skills.py`

向现有 skill detail/list 响应添加两个字段:

```python
class SkillOut(BaseModel):  # 现有 + 扩展
    # ... existing fields ...
    origin_summary: ResourceOriginSummaryOut
    publication_summary: ResourcePublicationSummaryOut
```

list 响应为避免 N+1，以一次 query join publication_links + latest installations + acl_count (origin_service.bulk_derive_*)。

`routers/mcp_servers.py`, `routers/agents.py` 也添加相同两个字段 (只有 publication 有意义，origin 始终填 `created_by_me` — Phase 1 未实现 install)。

---

## 4. 验证 checklist (进入 M2~M6 前)

Jensen 必须原样实现本文档 §2.2~§2.8 的 ORM signature，不得更改 §3 Pydantic schema 字段名/类型。如需更改，应向 Satya ESCALATION，先修改本文档。

- [ ] `models/marketplace.py` 中 6 个 class 全部存在 (`MarketplaceItem`, `MarketplaceItemACL`, `MarketplaceVersion`, `MarketplaceInstallation`, `MarketplacePublicationLink`, `SkillCredentialBinding`)
- [ ] 11 个 CHECK constraint 全部声明在 `__table_args__`
- [ ] 2 个 partial unique index(`marketplace_items`) 以 `Index(..., postgresql_where=...)` 声明
- [ ] `marketplace_items.latest_version_id` FK 以 `post_update=True` relationship + m40 ALTER 模式实现
- [ ] `marketplace_installations.version_id` 与 `skill_credential_bindings.credential_id` 为 ON DELETE **RESTRICT**
- [ ] 已添加 `models/skill.py` 的 12 个新列 + `AgentSkillLink.config` 列
- [ ] `app/marketplace/` 中存在 11 个 module 文件 (空文件也 OK)
- [ ] `schemas.py` 所有 class 的字段名/类型与 Spec §10.8 一致
- [ ] `__init__.py` 为空 (禁止 barrel export)
- [ ] `routers/marketplace.py` 所有 mutation 应用 `Depends(verify_csrf)`
- [ ] admin router 应用 `Depends(require_super_user)`

若本文档与 ADR-017 的决策冲突，以 ADR-017 为准。若与 Spec 冲突，以 Spec 为准 (source of truth)。
