# natural-mold Marketplace Resources Technical Spec

> 编写日期: 2026-05-18
> 版本: v0.1 (historical implementation spec)
> 相关文档: `docs/marketplace-resources-prd.md` v0.3, ADR-007/009/013/016/017/018
> 实现范围: Phase 1 — Skill marketplace foundation + 新 credential definitions + selected-skill runtime mount + credential env injection + k-skill built-in importer
> 状态: 截至 2026-06-07，Phase 1 的核心 backend/runtime/frontend 实现已完成。
> 本文档的 line number 与"当前代码状态"表述以 2026-05-18 baseline 为准。
> 最新状态优先参考 `docs/marketplace-resources-prd.md` 的 "2026-06-07 Current Implementation Status" 和
> `docs/ARCHITECTURE.md`。

## 0. Design Posture

该 spec 是基于 PRD v0.2 决定与 2026-05-18 代码深入分析，明确实现单元的 historical execution spec。核心顺序:

```
数据模型 (m40-m43)
  → 读取 catalog (slice A)
  → skill install (slice B)
  → skill publish + secret scan (slice C)
  → credential requirements / binding (slice D)
  → runtime selected-skill mount + credential injection + redaction (slice E)
  → k-skill importer (slice F)
  → MCP/Agent marketplace (slice G — Phase 2/3, 超出本 spec 范围)
```

### 0.1 用户决策确认事项

| 项目 | 决策 |
|------|------|
| SPEC 范围 | Phase 1 全部纳入本文档 (单一 SPEC) |
| Alembic 拆分 | 按 slice 分成多个 migration (m40-m43+) |
| Agent-Skill override | Option A — `agent_skills.config` JSON 字段 |
| Runtime mount 方式 | Option A — 通过 per-thread `copytree` 做数据隔离 |
| k-skill source | GitHub `NomaDamas/k-skill` git clone |
| public publish 策略 | 分离 published vs listed (由 super_user toggle `is_listed`) |

### 0.2 被 Reject 的替代方案

| Approach | 拒绝理由 |
|----------|-----------|
| 只给现有 `skills` 添加 `is_builtin`, `visibility` | version/update/install 历史会模糊，user-owned 与 catalog 混在一起 |
| 直接在 runtime 执行 Marketplace item | upstream/owner 变更会立即影响用户执行，credential binding 复杂 |
| 通过 git submodule 直接引用 k-skill | runtime 与 upstream layout 强耦合 |
| 引入新 skill runner | `execute_in_skill` subprocess runner 已在运行 — 在其上补齐 security gap 即可 |
| 基于 symlink mount | 写入可能流回原始数据 |
| 单一大型 m40 迁移 | rollback/review 负担大。按 slice 拆分迁移更安全 |

## 1. 2026-05-18 baseline 代码状态 (当时已验证事实)

### 1.1 Installed Resource Tables

| Domain | Table | Ownership |
|--------|-------|-----------|
| Agent | `agents` | `Agent.user_id` (FK CASCADE) |
| MCP | `mcp_servers`, `mcp_tools` | `McpServer.user_id`, M26 添加 `is_system`/`health_status` |
| Skill | `skills`, `agent_skills` | `Skill.user_id` (NOT NULL)。`AgentSkillLink` 只有 (agent_id, skill_id) PK — **无 `config` 字段** |
| Credential | `credentials` | `Credential.user_id`, `is_system` + CHECK(`is_system=false OR user_id IS NULL`) |

### 1.2 Skill Runtime (当前代码状态)

`backend/app/agent_runtime/executor.py`:

- line 19-20: `from deepagents import create_deep_agent` + `from deepagents.backends import FilesystemBackend`
- line 113-195: `_create_skill_execute_tool(output_dir, thread_id)` — 定义 `execute_in_skill` 工具 (StructuredTool)
- line 126: `resolved = (_DATA_DIR / skill_directory.strip("/")).resolve()` — broad 路径验证
- line 131: `if not args or args[0] != "python": return "Error: only python commands are allowed."`
- line 144-150: env dict 只有 `PATH`, `PYTHONPATH`, `HOME`, `SKILL_OUTPUT_DIR`, `OUTPUTS_DIR` (**未注入 credential**)
- line 160: 30 秒 timeout
- line 213-225: `create_deep_agent(model, tools, system_prompt, middleware, interrupt_on=None, checkpointer, store, backend, skills, memory, name)`
- line 544: `backend = FilesystemBackend(root_dir=str(_DATA_DIR), virtual_mode=True)`
- line 546-571: agent 只要有任意 skill，就以 `skills=["/skills/"]` broad mount

`backend/app/skills/runtime.py:build_skills_for_agent`: 仅将 `AgentSkillLink` → 转换为 `to_runtime_dict()` list。`to_runtime_dict()` 只返回 `{id, name, slug, kind, storage_path, description}` (无 body)。

`backend/app/skills/prompt.py:build_skills_prompt`: 通过 `## Available Skills` 文本指示 LLM 使用 read_file。正文由 LLM 直接读取 `/skills/<slug>/SKILL.md`。

### 1.3 Credential System (可复用)

- `app/security/cipher.py`: Cipher V2 (HKDF-SHA256 + AES-256-GCM, info=`moldy-encryption-v1`)
- `app/credentials/definitions/`: 注册 13 个 definition (2026-05-18 实测) (不含 k-skill 用)
- `app/credentials/interpolation.py:resolve_deep`: `={{ $credentials.x }}` interpolation (MCP 使用)
- `app/credentials/external_secrets.py`: Vault/ENV 动态 resolver (feature flag)
- `credentials.field_keys` JSON (ADR-007): 避免 list API N+1
- `credentials.is_system` + CHECK constraint
- ENV → system credential bootstrap (`seed/bootstrap_from_env.py`)

### 1.4 Auth (复用)

- `app/dependencies.py:get_current_user, require_super_user, verify_csrf`
- JWT HS256 + HttpOnly Cookie + refresh rotation + CSRF double-submit (ADR-016)
- 已移除 Mock user 痕迹 (m36 + `migrate_mock_to_real_user.py`)

### 1.5 Schema gap (实现对象)

- `Skill` 缺少 `is_system`, `source_kind`, `source_marketplace_item_id`, `source_marketplace_version_id`, `source_commit`, `credential_requirements`, `execution_profile`, `origin_kind`, `origin_user_id`, `origin_marketplace_item_id`, `origin_marketplace_version_id`, `is_dirty` column
- `AgentSkillLink.config` 字段缺失
- `packager.py` 缺少 secret scan
- 缺少 `app/marketplace/` module
- 缺少 `app/scripts/sync_k_skill.py`
- 缺少 k-skill 相关 credential definition(`srt_account` 等)

## 2. 设计原则

1. Marketplace item/version 是发布原本。
2. Installed resource 是用户账户中的执行 copy。
3. Published version immutable。
4. Credential value 不包含在 marketplace payload 中。
5. 分离 Credential requirement 与 credential binding。
6. Built-in k-skill 作为 system marketplace item 处理。
7. Upstream repository 是 read-only source。
8. 安装/更新是用户明确操作。
9. Runtime 中暴露的 skill 目录只包含 agent 所选择的。
10. Credential 只注入 `execute_in_skill` subprocess env，并在 log/SSE/tool result 中 redact。

### 2.1 Decision Log

| ID | Decision | Consequence |
|----|----------|-------------|
| D1 | `marketplace_versions` immutable | 简化 update 比较/audit，metadata 修改仅在 item-level |
| D2 | installed resource 必须拥有 `user_id` | 保持现有 ownership check，不把 system item 直接连接到 agent |
| D3 | Phase 1 credential override 使用 `agent_skills.config` JSON (Option A) | migration 小，与当前 link model 一致 |
| D4 | k-skill credential mapping 以 curated map 为 source of truth | regex 仅作为 review signal |
| D5 | broad `/skills/` mount 替换为 per-thread copytree (Option A) | 数据完全隔离，需要 retention policy |
| D6 | 缺少 required credential 的 install 允许 `needs_setup` | 用户可先从 catalog 获取，之后再连接 credential。Runtime 中 fail-fast |
| D7 | 撤回 restricted ACL 只阻止新 install | 已安装 copy 继续归用户所有 |
| D8 | installed resource API 包含 `origin_summary` 和 `publication_summary` | 在 `/skills`, `/mcp-servers`, agent dashboard 中一致展示 |
| D9 | public publish 从 `is_listed=False` 开始，仅 super_user 可 toggle | catalog 展示 gate |
| D10 | secret_scan 同时用于 publish + import | packager 本身不额外验证，由 caller wrap |
| D11 | runtime root 为 per-thread，conversation 结束时 cleanup | 与 LangGraph thread lifecycle 结合 |
| D12 | k-skill importer 仅限 super_user CLI，不暴露 web UI | 只有运营者可触发 sync |

### 2.2 Scope Boundaries

**Phase 1 (本 spec) 包含**:
- marketplace tables (item/version/installation/acl/publication_links/credential_bindings)
- 扩展 skills column + 添加 agent_skills.config
- skill catalog list/detail API
- skill install/update API
- skill publish API + secret scan
- skill credential requirements + binding API
- selected-skill runtime mount + credential env injection + redaction
- k-skill built-in importer (CLI)
- 新增 credential definitions (srt_account 等 8 个)
- Marketplace UI (仅 skill)

**Phase 1 排除 (移到 Phase 2/3)**:
- MCP/Agent marketplace 实际 install (只准备 schema)
- payment/ranking/review
- auto-merge of dirty installed resources
- organization/team ACL
- full script sandbox (维持当前 allowlist + 30 秒 timeout)

## 3. Data Model

### 3.1 migration 拆分

| ID | 文件 | 内容 |
|----|------|------|
| m40 | `m40_marketplace_tables.py` | `marketplace_items`, `marketplace_item_acl`, `marketplace_versions`, `marketplace_installations`, `marketplace_publication_links` |
| m41 | `m41_skills_marketplace_columns.py` | 给 `skills` 添加 12 个 column + backfill |
| m42 | `m42_agent_skills_config.py` | 添加 `agent_skills.config` JSON column |
| m43 | `m43_skill_credential_bindings.py` | `skill_credential_bindings` 表 |

每个 migration 必须可独立 rollback。但 m41 依赖 m40(FK)，m43 依赖 m41(使用 skills column)。

### 3.2 `marketplace_items` (m40)

```sql
CREATE TABLE marketplace_items (
  id UUID PRIMARY KEY,
  resource_type VARCHAR(20) NOT NULL,
  owner_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
  is_system BOOLEAN NOT NULL DEFAULT FALSE,
  is_listed BOOLEAN NOT NULL DEFAULT FALSE,

  name VARCHAR(200) NOT NULL,
  slug VARCHAR(220) NOT NULL,
  description TEXT NULL,
  icon_url TEXT NULL,

  visibility VARCHAR(20) NOT NULL DEFAULT 'private',
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  moderation_status VARCHAR(20) NOT NULL DEFAULT 'approved',

  source_kind VARCHAR(40) NULL,
  source_url TEXT NULL,
  source_external_id VARCHAR(240) NULL,

  latest_version_id UUID NULL,
  tags JSON NULL,
  categories JSON NULL,
  locale VARCHAR(20) NULL,
  metadata JSON NULL,

  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  published_at TIMESTAMP NULL,

  CONSTRAINT ck_marketplace_resource_type CHECK (resource_type IN ('agent', 'mcp', 'skill')),
  CONSTRAINT ck_marketplace_visibility CHECK (visibility IN ('private', 'restricted', 'public', 'unlisted', 'system')),
  CONSTRAINT ck_marketplace_status CHECK (status IN ('draft', 'published', 'deprecated', 'disabled')),
  CONSTRAINT ck_marketplace_system_owner CHECK ((is_system = false) OR (owner_user_id IS NULL))
);

CREATE UNIQUE INDEX uq_marketplace_items_system_slug
  ON marketplace_items(resource_type, slug) WHERE is_system = true;
CREATE UNIQUE INDEX uq_marketplace_items_owner_slug
  ON marketplace_items(owner_user_id, resource_type, slug) WHERE owner_user_id IS NOT NULL;
CREATE INDEX ix_marketplace_items_listed ON marketplace_items(is_listed, visibility, status);
```

- `source_kind`: `user`, `k-skill`, `import`, `system_seed`
- `source_external_id`: 对 k-skill 来说是 upstream skill name
- `is_listed`: 仅 super_user 可 toggle，默认 False
- `latest_version_id` FK 在 m40 内创建 versions 表后通过 ALTER 添加 (规避 circular FK，参见 §3.8)

### 3.3 `marketplace_item_acl` (m40)

```sql
CREATE TABLE marketplace_item_acl (
  item_id UUID NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permission VARCHAR(20) NOT NULL DEFAULT 'install',
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (item_id, user_id),
  CONSTRAINT ck_marketplace_acl_permission CHECK (permission IN ('view', 'install', 'manage'))
);
```

### 3.4 `marketplace_versions` (m40)

```sql
CREATE TABLE marketplace_versions (
  id UUID PRIMARY KEY,
  item_id UUID NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
  version_label VARCHAR(80) NOT NULL,
  version_number INTEGER NOT NULL,

  resource_type VARCHAR(20) NOT NULL,
  payload_kind VARCHAR(40) NOT NULL,
  payload JSON NOT NULL,
  storage_path VARCHAR(500) NULL,
  content_hash VARCHAR(64) NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,

  credential_requirements JSON NULL,
  dependency_requirements JSON NULL,
  execution_profile JSON NULL,
  release_notes TEXT NULL,

  source_commit VARCHAR(80) NULL,
  source_ref VARCHAR(120) NULL,
  source_path TEXT NULL,

  created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMP NOT NULL,

  CONSTRAINT ck_marketplace_version_resource_type CHECK (resource_type IN ('agent', 'mcp', 'skill')),
  CONSTRAINT ck_marketplace_payload_kind CHECK (payload_kind IN ('skill_package', 'agent_spec', 'mcp_template'))
);

CREATE UNIQUE INDEX uq_marketplace_versions_item_number ON marketplace_versions(item_id, version_number);
CREATE INDEX ix_marketplace_versions_content_hash ON marketplace_versions(content_hash);
```

Version immutability:

- 不提供针对 `payload`, `storage_path`, `content_hash` 的 update endpoint
- metadata typo 修复只能通过新 version 或 item-level metadata update

### 3.5 `marketplace_installations` (m40)

```sql
CREATE TABLE marketplace_installations (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id UUID NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
  version_id UUID NOT NULL REFERENCES marketplace_versions(id) ON DELETE RESTRICT,
  resource_type VARCHAR(20) NOT NULL,

  installed_agent_id UUID NULL REFERENCES agents(id) ON DELETE CASCADE,
  installed_mcp_server_id UUID NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  installed_skill_id UUID NULL REFERENCES skills(id) ON DELETE CASCADE,

  install_status VARCHAR(30) NOT NULL DEFAULT 'active',
  is_dirty BOOLEAN NOT NULL DEFAULT FALSE,
  installed_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,

  CONSTRAINT ck_marketplace_install_resource_target CHECK (
    (resource_type = 'agent' AND installed_agent_id IS NOT NULL AND installed_mcp_server_id IS NULL AND installed_skill_id IS NULL)
    OR
    (resource_type = 'mcp' AND installed_agent_id IS NULL AND installed_mcp_server_id IS NOT NULL AND installed_skill_id IS NULL)
    OR
    (resource_type = 'skill' AND installed_agent_id IS NULL AND installed_mcp_server_id IS NULL AND installed_skill_id IS NOT NULL)
  ),
  CONSTRAINT ck_marketplace_install_status CHECK (install_status IN ('active', 'needs_setup', 'disabled', 'uninstalled'))
);

CREATE INDEX ix_marketplace_install_user_item ON marketplace_installations(user_id, item_id);
CREATE INDEX ix_marketplace_install_user_resource ON marketplace_installations(user_id, resource_type);
```

### 3.6 `marketplace_publication_links` (m40)

```sql
CREATE TABLE marketplace_publication_links (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id UUID NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
  resource_type VARCHAR(20) NOT NULL,

  source_agent_id UUID NULL REFERENCES agents(id) ON DELETE CASCADE,
  source_mcp_server_id UUID NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  source_skill_id UUID NULL REFERENCES skills(id) ON DELETE CASCADE,

  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,

  CONSTRAINT ck_pub_link_resource_type CHECK (resource_type IN ('agent', 'mcp', 'skill')),
  CONSTRAINT ck_pub_link_target CHECK (
    (resource_type = 'agent' AND source_agent_id IS NOT NULL AND source_mcp_server_id IS NULL AND source_skill_id IS NULL)
    OR
    (resource_type = 'mcp' AND source_agent_id IS NULL AND source_mcp_server_id IS NOT NULL AND source_skill_id IS NULL)
    OR
    (resource_type = 'skill' AND source_agent_id IS NULL AND source_mcp_server_id IS NULL AND source_skill_id IS NOT NULL)
  )
);

CREATE UNIQUE INDEX uq_pub_link_item ON marketplace_publication_links(item_id);
CREATE INDEX ix_pub_link_resource ON marketplace_publication_links(user_id, resource_type);
```

### 3.7 扩展 `skills` column (m41)

```sql
ALTER TABLE skills ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE skills ADD COLUMN source_kind VARCHAR(40) NULL;
ALTER TABLE skills ADD COLUMN source_marketplace_item_id UUID NULL REFERENCES marketplace_items(id) ON DELETE SET NULL;
ALTER TABLE skills ADD COLUMN source_marketplace_version_id UUID NULL REFERENCES marketplace_versions(id) ON DELETE SET NULL;
ALTER TABLE skills ADD COLUMN source_commit VARCHAR(80) NULL;
ALTER TABLE skills ADD COLUMN credential_requirements JSON NULL;
ALTER TABLE skills ADD COLUMN execution_profile JSON NULL;
ALTER TABLE skills ADD COLUMN origin_kind VARCHAR(40) NOT NULL DEFAULT 'created_by_me';
ALTER TABLE skills ADD COLUMN origin_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE skills ADD COLUMN origin_marketplace_item_id UUID NULL REFERENCES marketplace_items(id) ON DELETE SET NULL;
ALTER TABLE skills ADD COLUMN origin_marketplace_version_id UUID NULL REFERENCES marketplace_versions(id) ON DELETE SET NULL;
ALTER TABLE skills ADD COLUMN is_dirty BOOLEAN NOT NULL DEFAULT FALSE;
```

Backfill:

- 所有现有 row: `source_kind='user'`, `is_system=FALSE`
- text skill: `origin_kind='created_by_me'`
- package skill: `origin_kind='imported_by_me'`

与 System credential 不同，从 system 导入的 skill 的 user_id 也保留为安装者(D2)。`is_system=TRUE` 只用于从 system marketplace item seed 的 skill 本身，在普通用户流程中几乎不使用。

### 3.8 `agent_skills.config` (m42)

```sql
ALTER TABLE agent_skills ADD COLUMN config JSON NULL;
```

保存示例:

```json
{
  "credential_bindings": {
    "srt_account": "11111111-1111-1111-1111-111111111111"
  }
}
```

runtime 将此 override 优先于 `skill_credential_bindings` 默认值。

### 3.9 `skill_credential_bindings` (m43)

```sql
CREATE TABLE skill_credential_bindings (
  id UUID PRIMARY KEY,
  skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  requirement_key VARCHAR(120) NOT NULL,
  credential_id UUID NOT NULL REFERENCES credentials(id) ON DELETE RESTRICT,
  scope VARCHAR(20) NOT NULL DEFAULT 'skill',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,

  CONSTRAINT ck_skill_credential_binding_scope CHECK (scope IN ('skill', 'agent_skill')),
  UNIQUE (skill_id, user_id, requirement_key, scope)
);
```

`scope='agent_skill'` 为规范化 migration 时点预留。Phase 1 只使用 `scope='skill'`，agent-skill override 通过 `agent_skills.config` 处理。

### 3.10 Referential integrity 处理

`marketplace_items.latest_version_id` 引用 `marketplace_versions.id` 的 circular FK 在 m40 内处理:

1. 创建不带 FK 的 `marketplace_items`
2. 创建 `marketplace_versions`
3. `ALTER TABLE marketplace_items ADD CONSTRAINT fk_latest_version FOREIGN KEY (latest_version_id) REFERENCES marketplace_versions(id) ON DELETE SET NULL`

### 3.11 Lifecycle state model

Item:

```text
draft → published → deprecated → disabled
  ↓        ↓
disabled  published (metadata changes only)
```

- 只有 `published` 可 install
- `deprecated` 仅在 `metadata.allow_deprecated_install=true` 时可安装 (默认 false)
- `disabled` 同时阻止 listing/install
- item metadata 可修改，version payload immutable

Installation:

```text
active ↔ needs_setup → active
   ↓                ↓
uninstalled    uninstalled
   or             or
disabled       disabled
```

- `needs_setup`: 安装副本已存在，但 required credential binding 未完成
- `disabled`: 阻止 runtime，安装副本保留用于 inspection/export
- `uninstalled`: marketplace link 禁用。实际 resource 仅在 `delete_resource=true` 时删除

## 4. Credential Definitions

在 `backend/app/credentials/definitions/` 目录新增以下 module。遵循现有 `__init__.py` 的自动注册 pattern(import time)。

| module 文件 | definition_key | Fields | Used by |
|----------|----------------|--------|---------|
| `srt_account.py` | `srt_account` | `username`, `password` | `srt-booking` |
| `ktx_account.py` | `ktx_account` | `username`, `password` | `ktx-booking` |
| `foresttrip_account.py` | `foresttrip_account` | `username`, `password` | `foresttrip-vacancy` |
| `kipris_plus_api.py` | `kipris_plus_api` | `api_key` | `korean-patent-search` |
| `dart_api.py` | `dart_api` | `api_key` | `k-dart` |
| `odsay_api.py` | `odsay_api` | `api_key` | `korean-transit-route` |
| `coupang_partners.py` | `coupang_partners` | `access_key`, `secret_key` | `coupang-product-search` (optional) |
| `k_skill_proxy.py` | `k_skill_proxy` | `base_url`, optional `api_key` | hosted proxy skills |

每个 module 定义 `CredentialDefinition` instance，并在 `__init__.py` register。注册后自动兼容 `field_keys` cache(ADR-007)。

Hosted proxy dependency 表示(version metadata):

```json
{
  "kind": "hosted_proxy",
  "default_base_url": "https://k-skill-proxy.nomadamas.org",
  "user_configurable_base_url": true
}
```

## 5. k-skill Importer (Slice F)

### 5.1 Settings

添加到 `backend/app/config.py`:

```python
k_skill_upstream_url: str = "https://github.com/NomaDamas/k-skill.git"
k_skill_upstream_ref: str = "main"
k_skill_sync_dir: str = "./data/upstreams/k-skill"
k_skill_builtin_storage_dir: str = "./data/marketplace/k-skill"
```

### 5.2 CLI

新文件 `backend/app/scripts/sync_k_skill.py`:

```bash
uv run python -m app.scripts.sync_k_skill --ref main
uv run python -m app.scripts.sync_k_skill --ref 80303f5 --dry-run
uv run python -m app.scripts.sync_k_skill --ref 80303f5 --only korean-spell-check,srt-booking
```

CLI 选项:

- `--ref`: commit SHA 或 branch (默认 `settings.k_skill_upstream_ref`)
- `--dry-run`: 只输出变更/创建 count，不修改 DB/filesystem
- `--only`: 以逗号分隔的 skill name (用于调试)
- `--keep-deprecated`: 对消失的 upstream skill 保持现状，而不是标记为 `deprecated`

### 5.3 Discovery

mirror `scripts/validate-skills.sh` exclusion (`.git`, `.github`, `.codex`, `.claude`, `.omx`, `.ouroboros`, `.changeset`, `.cursor`, `.vscode`, `.sisyphus`, `.idea`, `docs`, `dist`, `node_modules`, `packages`, `python-packages`, `scripts`, `examples`)。

Valid skill 条件:

- 目录位于 repo root 直属下一层
- 存在 `SKILL.md`
- 存在 frontmatter + 存在 `name`, `description` key
- frontmatter `name` 与目录名一致

### 5.4 Packaging

每个 skill 目录处理顺序:

1. 复制到临时 staging 目录
2. 拒绝 Secret-like 文件 (`secret_scan.py` 参照): `.env`, `*.pem`, `*.key`, `*.p12`, `cookies*`, `token*`, `secrets.env`
3. build `.skill` zip (top-level `<skill-name>/`)
4. 用 `app.skills.packager.extract_package()` 验证 (复用)
5. 将 extract 结果保存到 `data/marketplace/k-skill/<skill-name>/<source_commit>/`

### 5.5 Metadata 提取

从 Frontmatter 中:

- `name`, `description`, `license`
- `metadata.category`, `metadata.locale`, `metadata.phase`

Computed:

- `content_hash`: package canonical contents 的 SHA-256
- `source_commit`, `source_path`
- `has_scripts`: 是否存在 `scripts/*.py`
- `file_count`, `size_bytes`
- `execution_profile`: 参照 §5.7
- `credential_requirements`: §5.6 curated map

### 5.6 Credential Requirement Mapping

新文件 `backend/app/marketplace/k_skill_requirements.py`:

```python
K_SKILL_REQUIREMENT_MAP: dict[str, list[dict]] = {
    "srt-booking": [{
        "key": "srt_account",
        "definition_key": "srt_account",
        "required": True,
        "label": "SRT account",
        "description": "SRT 登录 credential",
        "fields": ["username", "password"],
        "env_map": {"username": "KSKILL_SRT_ID", "password": "KSKILL_SRT_PASSWORD"},
        "injection": "env",
        "scope": "user",
    }],
    "ktx-booking": [...],
    "korean-patent-search": [...],
    "k-dart": [...],
    "korean-transit-route": [...],
    "foresttrip-vacancy": [...],
    "coupang-product-search": [...],  # optional=True
    # ... more
}

REGEX_HINTS = [
    re.compile(r"KSKILL_[A-Z_]+"),
    re.compile(r"API[_-]KEY"),
    # ...
]
```

Regex hint 只输出为 `detected_env_vars` review signal，不自动生成 requirement。

### 5.7 Execution Profile

```json
{
  "support_level": "ready_python",
  "runners": ["python"],
  "requires_network": true,
  "requires_browser": false,
  "requires_local_app": false,
  "requires_manual_login": false,
  "notes": []
}
```

Support levels: `ready_python`, `proxy_http`, `node_package`, `browser_or_local`, `manual_only`, `disabled`.

### 5.8 Sync Idempotency

- `content_hash` 相同 → 不创建新 version
- package hash 相同 + 仅 metadata 变更 → 只 update item-level metadata
- package hash 变更 → 以 `version_number = max + 1` 创建新 version
- 消失的 upstream skill → item `status=deprecated` (`--keep-deprecated` 可规避)
- 单个 skill validation 失败不会中断整个 sync。结果报告包含失败列表

### 5.9 First-wave 推荐 (由 super_user toggle listed)

| Group | Examples |
|-------|----------|
| Ready/no credential | `korean-spell-check` |
| Hosted proxy | `seoul-density` 类 |
| Required credential clear schema | `srt-booking`, `ktx-booking`, `korean-patent-search`, `k-dart` |

Hold back (保持 unlisted):

- KakaoTalk 自动化 (local app/session)
- 需要浏览器登录的 skill
- Node/npm/npx skill (无 runner)
- 已废弃的 upstream skill (`blue-ribbon-nearby` 等)

## 6. Publish Flow (Slice C)

### 6.1 Endpoint

```http
POST /api/marketplace/items/from-skill/{skill_id}
```

Body:

```json
{
  "item_id": "optional-existing-item",
  "visibility": "restricted",
  "name": "Korean Spell Check",
  "description": "韩语句子检查",
  "tags": ["korean", "writing"],
  "categories": ["writing"],
  "release_notes": "Initial shared version",
  "credential_requirements": [],
  "acl_user_ids": ["uuid"]
}
```

### 6.2 Server 行为

1. 通过 `skill_id` + `current_user.id` 加载 skill (ownership)
2. Package 验证:
   - text skill: 打包为单个 `SKILL.md` 文件
   - package skill: 复制 storage_path
3. **Secret scan** (`backend/app/marketplace/secret_scan.py` 新增)
4. 无 Item 时创建，有则确认 ownership
5. 创建新 immutable version (比较 content_hash)
6. update item `latest_version_id`
7. restricted 时创建 ACL row
8. update `marketplace_publication_links`
9. Audit log: `marketplace.publish`

### 6.3 Visibility 规则

- `public` publish: 从 `is_listed=False` 开始
- `restricted` publish: `acl_user_ids` 至少 1 人
- `private` publish: 与 ACL/listing 无关

## 7. Install Flow (Slice B)

### 7.1 Endpoint

```http
POST /api/marketplace/items/{item_id}/install
```

Body:

```json
{
  "version_id": null,
  "name_override": "SRT 预约",
  "credential_bindings": {
    "srt_account": "credential-uuid"
  },
  "install_missing_credentials": "needs_setup",
  "install_mode": "reuse_or_update"
}
```

### 7.2 Server 行为

1. Item visibility access check (`can_install_item`)
2. resolve Version (没有则 latest)
3. 验证 Credential bindings:
   - `credential.user_id == current_user.id`
   - `credential.definition_key == requirement.definition_key`
   - 拒绝 system credential (D2/§8)
4. 创建 Installed resource — transaction 顺序 (§7.3):
   - skill: package extract → 临时目录
   - mcp/agent: 在 Phase 2/3 (Phase 1 未实现)
5. 创建 `marketplace_installations` row
6. 创建 `skill_credential_bindings` row (如有)
7. Required 未解决时 `install_status='needs_setup'`
8. Audit log: `marketplace.install`

### 7.3 Transaction + Filesystem 处理

1. Access/binding validation
2. 将 package extract 到 Temp 目录 (`data/skills/.staging/<install_id>/`)
3. 在 DB transaction 内创建 `skills` + `marketplace_installations` row
4. 将 Temp 目录 move 到最终路径(`data/skills/<skill_id>/`)
5. DB commit

失败处理:

- DB commit 失败 → best-effort 删除目录 + 对用户只显示 generic error (不暴露路径/credential)
- Filesystem move 失败 → DB rollback
- Cleanup 失败 → 只记录 log (不暴露用户路径/credential)

### 7.4 Install Modes

| Mode | Behavior |
|------|----------|
| `reuse_or_update` (default) | 已安装时返回该 installation + refresh state，否则新建 |
| `new_copy` | 始终新建 installation |
| `overwrite_existing` | 仅在明确请求时覆盖现有项 |

### 7.5 填充 Installed Skill row

```python
skill.user_id = current_user.id
skill.kind = "package"  # k-skill 始终为 package
skill.source_kind = item.source_kind  # "k-skill" or "user" or "import"
skill.source_marketplace_item_id = item.id
skill.source_marketplace_version_id = version.id
skill.source_commit = version.source_commit
skill.credential_requirements = version.credential_requirements
skill.execution_profile = version.execution_profile
skill.origin_kind = _derive_origin(item, current_user)
skill.origin_marketplace_item_id = item.id
skill.origin_marketplace_version_id = version.id
```

`_derive_origin()` mapping:

| item state | origin_kind |
|------------|-------------|
| `is_system=True` + `source_kind='k-skill'` | `built_in_k_skill` |
| `is_system=True` + `source_kind='system_seed'` | `system_seed` |
| `visibility='restricted'`, owner != current_user | `shared_with_me` (origin_user_id = owner) |
| `visibility='public'`, owner != current_user | `community` |
| owner == current_user (重新安装) | `imported_by_me` |

## 8. Runtime Credential Injection (Slice E)

### 8.1 当前代码 gap

`executor.py:113-195` 的 `_create_skill_execute_tool` env dict:

```python
env = {
    "PATH": "/usr/bin:/usr/local/bin",
    "PYTHONPATH": str(resolved),
    "HOME": str(resolved),
    "SKILL_OUTPUT_DIR": out,
    "OUTPUTS_DIR": out,
}
```

无 Credential。

### 8.2 Required change

在 Agent runtime build 时生成以下 descriptor (`build_skills_for_agent` 扩展):

```python
@dataclass
class SkillRuntimeDescriptor:
    id: UUID
    slug: str
    storage_path: Path  # per-thread runtime root 下
    credential_bindings: dict[str, ResolvedCredential]

@dataclass
class ResolvedCredential:
    credential_id: UUID
    definition_key: str
    env_map: dict[str, str]
    decrypted: dict[str, Any]  # in-memory only, never serialized
```

将 `_create_skill_execute_tool` signature 改为 `_create_skill_execute_tool(output_dir, thread_id, skill_descriptors)`。

在 `execute_in_skill` 函数中:

1. 从 `skill_directory` 参数提取 slug
2. slug 不在 `skill_descriptors` 中 → `"Error: skill not attached to this agent"`
3. resolve 到对应 descriptor 的 `storage_path`
4. build env dict:

```python
env = {
    "PATH": "/usr/bin:/usr/local/bin",
    "PYTHONPATH": str(resolved),
    "HOME": str(resolved),
    "SKILL_OUTPUT_DIR": out,
    "OUTPUTS_DIR": out,
}
for req_key, resolved_cred in descriptor.credential_bindings.items():
    for field, env_name in resolved_cred.env_map.items():
        env[env_name] = resolved_cred.decrypted[field]
```

5. 执行 subprocess (保持现有逻辑)

### 8.3 Missing credential 处理

在 Agent 执行开始阶段检查 attached skill 中 `marketplace_installations.install_status == 'needs_setup'` 的项，如有缺失 required credential 的 skill 则以 error abort:

```text
Error: skill 'srt-booking' requires credential 'srt_account'. Connect it in Skill settings.
```

用 `marketplace_credential_required` error code 表示，frontend 显示设置 CTA。

### 8.4 Override 优先级

1. `agent_skills.config.credential_bindings.<key>`
2. 从 `skill_credential_bindings` 获取 `(skill_id, user_id, key, scope='skill')`
3. 如无则 `needs_setup`

### 8.5 Redaction Contract

新建 `backend/app/marketplace/redaction.py`:

```python
SENSITIVE_KEY_PATTERN = re.compile(r"(password|api_key|secret|token|access_key|refresh_token)", re.I)

def redact_credential_values(text: str, mapped_env_vars: dict[str, str]) -> str:
    for env_name, value in mapped_env_vars.items():
        if value and len(value) > 4:
            text = text.replace(value, f"<redacted:{env_name}>")
    return text

def redact_keys(payload: dict | list) -> dict | list:
    # 深度优先遍历，将匹配 SENSITIVE_KEY_PATTERN 的 key 的 value 替换为 "<redacted>"
    ...
```

调用位置:

- `_create_skill_execute_tool` 返回文本加工
- `streaming.py` 的 tool_call_result payload
- exception detail 转换
- 所有 raw log statement

## 9. Skill Mounting Fix (Slice E, Option A)

### 9.1 当前问题

`executor.py:546-571` 以 `skills=["/skills/"]` 进行 broad mount。其他用户的 skill 会被 ownership 阻止，但同一用户未选择的 skill 可通过 `read_file('/skills/<other>/...')` 访问。

### 9.2 Required behavior

Runtime root: `data/runtime/<thread_id>/skills/<slug>/`

构建阶段（调用 `executor.py:build_agent` 前）:

```python
runtime_skills_root = _DATA_DIR / "runtime" / cfg.thread_id / "skills"
runtime_skills_root.mkdir(parents=True, exist_ok=True)
for descriptor in cfg.skill_descriptors:
    target = runtime_skills_root / descriptor.slug
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(descriptor.original_storage_path, target, symlinks=False)
    descriptor.storage_path = target

skills_sources = [f"/runtime/{cfg.thread_id}/skills/"]
backend = FilesystemBackend(root_dir=str(_DATA_DIR), virtual_mode=True)
```

`_create_skill_execute_tool` 的路径校验:

```python
runtime_root = _DATA_DIR / "runtime" / thread_id / "skills"
resolved = (runtime_root / Path(skill_directory).name).resolve()
if not resolved.is_relative_to(runtime_root.resolve()):
    return "Error: invalid skill directory"
```

### 9.3 Cleanup 策略

- Conversation 结束时移除 `data/runtime/<thread_id>/`
- 服务器启动时对 stale runtime root 进行垃圾回收（在 `startup` lifespan 中删除超过 1 小时的 thread root）
- 强制终止/crash 后残留目录由 retention job 清理

### 9.4 Streaming/SSE 兼容

`thread_id` 与 LangGraph checkpoint key 相同。SSE resume(ADR-011) 时复用同一个 root。branch 分支不创建单独 root，共享同一个 thread root。

## 10. API Surface

新增路由 `backend/app/routers/marketplace.py`。所有 endpoint 使用 `Depends(get_current_user)`，状态变更使用 `Depends(verify_csrf)` (ADR-016)。

### 10.1 Catalog

```http
GET /api/marketplace/items
```

Query: `resource_type`, `q`, `visibility`, `category`, `locale`, `credential_status`, `installed`, `install_state`, `source`, `support_level`, `source_kind`, `is_listed`

Default filter（非 super_user 时）: `is_listed=True OR visibility=system OR owner=current_user OR ACL`。

### 10.2 Detail

```http
GET /api/marketplace/items/{item_id}
GET /api/marketplace/items/{item_id}/versions
GET /api/marketplace/versions/{version_id}
```

### 10.3 Install / Update / Delete

```http
POST   /api/marketplace/items/{item_id}/install
POST   /api/marketplace/installations/{installation_id}/update
DELETE /api/marketplace/installations/{installation_id}
```

Update body:

```json
{ "strategy": "overwrite" }
```

策略: `overwrite`, `install_new_copy`, `keep_current`。`is_dirty=True` 时要求显式 strategy。

### 10.4 Publish / Manage

```http
POST   /api/marketplace/items/from-skill/{skill_id}
POST   /api/marketplace/items/{item_id}/versions/from-skill/{skill_id}
PATCH  /api/marketplace/items/{item_id}
POST   /api/marketplace/items/{item_id}/acl
DELETE /api/marketplace/items/{item_id}/acl/{user_id}
POST   /api/marketplace/items/{item_id}/disable
GET    /api/marketplace/publication-status
```

### 10.5 Admin (super_user)

```http
POST  /api/marketplace/admin/items/{item_id}/listed   # 切换 is_listed
POST  /api/marketplace/admin/items/{item_id}/disable
POST  /api/marketplace/admin/k-skill/sync             # 查询 CLI 结果 status（执行通过 CLI）
GET   /api/marketplace/admin/moderation               # is_listed=False && visibility='public' 列表
```

全部使用 `Depends(require_super_user)` + CSRF。

### 10.6 Skill Credential Bindings

```http
GET    /api/skills/{skill_id}/credential-requirements
GET    /api/skills/{skill_id}/credential-bindings
PUT    /api/skills/{skill_id}/credential-bindings/{requirement_key}
DELETE /api/skills/{skill_id}/credential-bindings/{requirement_key}
```

PUT body:

```json
{ "credential_id": "uuid" }
```

验证：

- skill ownership (`Skill.user_id == current_user.id`)
- requirement key 存在
- credential ownership + `definition_key` 一致
- 拒绝 system credential

### 10.7 Error Codes（结构化）

使用现有响应模式 `{ "detail": { "code": "...", "message": "..." } }`。

| Code | HTTP | When |
|------|------|------|
| `marketplace_item_not_found` | 404 | Item 不存在或无 view 权限 |
| `marketplace_version_not_found` | 404 | Version 不存在 |
| `marketplace_install_forbidden` | 404 | 无 Install 权限（防止 enumeration） |
| `marketplace_manage_forbidden` | 403 | 可 view 但不可 manage |
| `marketplace_item_disabled` | 409 | 尝试 install Disabled item |
| `marketplace_invalid_visibility` | 400 | Visibility 转换 invalid |
| `marketplace_acl_required` | 400 | restricted 无 ACL |
| `marketplace_invalid_package` | 400 | Package extract/validate 失败 |
| `marketplace_secret_detected` | 400 | 被 secret_scan 拒绝 |
| `marketplace_credential_required` | 409 | 缺少 Required credential（install/run） |
| `marketplace_credential_mismatch` | 400 | definition_key 不一致 |
| `marketplace_dirty_installation` | 409 | Dirty 状态下 update 未提供 strategy |

### 10.8 Pydantic schema

`backend/app/marketplace/schemas.py`:

```python
class MarketplaceVersionSummary(BaseModel):
    id: UUID
    version_label: str
    version_number: int
    content_hash: str
    source_commit: str | None = None
    created_at: datetime

class CredentialRequirementOut(BaseModel):
    key: str
    definition_key: str
    required: bool
    label: str
    description: str | None = None
    fields: list[str]
    injection: Literal["env", "config"]
    scope: Literal["user", "system_dependency", "manual"]

class CredentialSummaryOut(BaseModel):
    status: Literal["none", "optional", "required", "hosted_proxy", "manual_login"]
    required_count: int = 0
    optional_count: int = 0
    missing_required_count: int = 0

class ResourceOriginSummaryOut(BaseModel):
    kind: Literal["created_by_me", "imported_by_me", "built_in_k_skill", "shared_with_me", "community", "system_seed"]
    label: str
    source_name: str | None = None
    source_user_id: UUID | None = None
    marketplace_item_id: UUID | None = None
    marketplace_version_id: UUID | None = None

class ResourcePublicationSummaryOut(BaseModel):
    state: Literal["not_published", "draft", "published_private", "published_restricted", "published_public_listed", "published_public_unlisted", "published_unlisted", "disabled"]
    item_id: UUID | None = None
    visibility: Literal["private", "restricted", "public", "unlisted", "system"] | None = None
    status: Literal["draft", "published", "deprecated", "disabled"] | None = None
    is_listed: bool = False
    latest_version_id: UUID | None = None
    version_number: int | None = None
    shared_user_count: int = 0

class MarketplaceInstallationSummary(BaseModel):
    installed: bool
    installation_id: UUID | None = None
    installed_resource_id: UUID | None = None
    status: Literal["active", "needs_setup", "disabled", "uninstalled"] | None = None
    update_available: bool = False
    dirty: bool = False

class MarketplaceItemOut(BaseModel):
    id: UUID
    resource_type: Literal["agent", "mcp", "skill"]
    name: str
    slug: str
    description: str | None
    visibility: str
    status: str
    is_system: bool
    is_listed: bool
    latest_version: MarketplaceVersionSummary | None
    credential_summary: CredentialSummaryOut
    execution_profile: dict[str, Any] | None = None
    origin_summary: ResourceOriginSummaryOut | None = None
    publication_summary: ResourcePublicationSummaryOut
    installation: MarketplaceInstallationSummary

class InstallMarketplaceItemIn(BaseModel):
    version_id: UUID | None = None
    name_override: str | None = None
    credential_bindings: dict[str, UUID] = Field(default_factory=dict)
    install_missing_credentials: Literal["reject", "needs_setup"] = "needs_setup"
    install_mode: Literal["reuse_or_update", "new_copy", "overwrite_existing"] = "reuse_or_update"

class UpdateMarketplaceInstallationIn(BaseModel):
    strategy: Literal["overwrite", "install_new_copy", "keep_current"]

class PublishSkillIn(BaseModel):
    item_id: UUID | None = None
    visibility: Literal["private", "restricted", "public", "unlisted"]
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    release_notes: str | None = None
    credential_requirements: list[CredentialRequirementIn] = Field(default_factory=list)
    acl_user_ids: list[UUID] = Field(default_factory=list)
```

在 Skill/MCP/Agent 现有 detail 响应中也嵌入 `origin_summary`, `publication_summary`。

### 10.9 Dirty State helper

`backend/app/marketplace/origin_service.py:mark_installation_dirty`:

```python
async def mark_installation_dirty(db, *, resource_type: str, resource_id: UUID) -> None:
    stmt = (
        update(MarketplaceInstallation)
        .where(MarketplaceInstallation.resource_type == resource_type)
        .where(or_(
            MarketplaceInstallation.installed_agent_id == resource_id,
            MarketplaceInstallation.installed_mcp_server_id == resource_id,
            MarketplaceInstallation.installed_skill_id == resource_id,
        ))
        .values(is_dirty=True, updated_at=utcnow())
    )
    await db.execute(stmt)
    # 同时也 set skills.is_dirty
```

调用位置（skill content/file 变更）:

- `PUT /api/skills/{id}/content`
- `PATCH /api/skills/{id}`
- `PUT|POST|DELETE /api/skills/{id}/files/{path}`

Best-effort: 即使没有 installation row 也不 fail。

## 11. Backend Service Modules

新增文件夹 `backend/app/marketplace/`:

```
marketplace/
├── __init__.py
├── access.py             # can_view_item / can_install_item / can_manage_item
├── schemas.py            # Pydantic model (§10.8)
├── service.py            # catalog list/detail
├── install_service.py    # install/update flow
├── publish_service.py    # publish flow
├── origin_service.py     # 派生 origin/publication summary
├── secret_scan.py        # 检查 secret-like 文件/模式
├── redaction.py          # redact_credential_values, redact_keys
├── credential_requirements.py  # mapping / validation / env injection plan
└── k_skill_importer.py   # upstream sync（由 CLI 调用）
```

新增路由: `backend/app/routers/marketplace.py`。

新增 model: `backend/app/models/marketplace.py`（单个文件包含 5 个表的 ORM）。

## 12. Access Control (Slice A)

`access.py`:

```python
async def can_view_item(db, item: MarketplaceItem, user: CurrentUser) -> bool
async def can_install_item(db, item: MarketplaceItem, user: CurrentUser) -> bool
async def can_manage_item(db, item: MarketplaceItem, user: CurrentUser) -> bool
```

规则:

- super_user: 可 view/manage 所有 item。不可解密 user credential
- owner: 可 view/install/manage 自己的 item
- public/system: 所有登录用户可 view/install。目录搜索仅限 `is_listed=True`
- unlisted: 可通过直接 id view/install，不出现在搜索结果中
- restricted: 需要 ACL
- disabled: 仅 owner/super_user 可 view，任何人都不可 install
- 未授权 detail/install: 404（防止 enumeration）

### 12.1 Access Matrix

| Actor | List | Detail | Install | Manage | Disable | Listed toggle |
|-------|------|--------|---------|--------|---------|---------------|
| Owner | own | own | own | own | own | no |
| ACL view | restricted only | yes | no | no | no | no |
| ACL install | restricted only | yes | yes | no | no | no |
| ACL manage | restricted only | yes | yes | metadata/version/ACL except owner removal | no | no |
| Any logged-in | public(listed)/system | public/system/unlisted | public/system/unlisted | no | no | no |
| super_user | all | all | system/public if desired | all | all | yes |

### 12.2 Installed Resource Ownership

Marketplace access never grants direct access to installed resources owned by another user.

- 安装始终创建当前用户所有的 row
- Installation update: `marketplace_installations.user_id == current_user.id`
- Skill content 编辑: `skills.user_id == current_user.id`
- Credential binding: `skills.user_id == current_user.id` AND `credentials.user_id == current_user.id`
- Runtime 执行: 通过 agent ownership 路径加载 skill（不经过 marketplace visibility）

## 13. Security

### 13.1 Secret Scan

`backend/app/marketplace/secret_scan.py`:

```python
SECRET_FILE_PATTERNS = [
    re.compile(r"^\.env(\..+)?$"),
    re.compile(r"^secrets\.env$"),
    re.compile(r".*\.pem$"),
    re.compile(r".*\.key$"),
    re.compile(r".*\.p12$"),
    re.compile(r"^cookies.*$"),
    re.compile(r"^token.*$"),
]

SECRET_CONTENT_PATTERNS = [
    # OI-4 (M1-S1 贝索斯): 必须使用 word boundary — 否则正常
    # docstring/示例中的 "sk-example" 等 placeholder 也会被拦截，产生 false-positive
    # 并导致用户被阻止。将最小长度提高到 20，以区分 placeholder 和真实 key。
    re.compile(rb"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(rb"-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"),
    re.compile(rb"AWS_SECRET_ACCESS_KEY"),
    re.compile(rb"GOOGLE_APPLICATION_CREDENTIALS"),
]

def scan_package(extracted_dir: Path) -> list[SecretFinding]:
    # 遍历文件树、匹配模式，发现时返回 finding 列表
    ...

class SecretFinding(BaseModel):
    path: str
    kind: Literal["filename", "content"]
    pattern: str
```

调用位置:

- `publish_service.py`: publish 时 fail
- `k_skill_importer.py`: import 时仅 skip 对应 skill（整体 sync 继续）
- `routers/skills.py:upload`（上传 `.skill` ZIP）: 也适用于新增 import（回归保护）

### 13.2 Credential Safety

- API 响应绝不暴露 decrypted value
- Runtime env injection 仅注入 mapped env var（不注入其他 env）
- 使用 Redaction helper 统一 log/SSE/tool result
- Audit log（新增 audit_events 模块或现有 logger）:

| Action | Actor | Metadata |
|--------|-------|----------|
| `marketplace.publish` | owner/super_user | item_id, version_id, resource_type, visibility |
| `marketplace.install` | installer | item_id, version_id, installed_resource_id |
| `marketplace.update_installation` | installer | installation_id, from_version_id, to_version_id, strategy |
| `marketplace.disable` | super_user/owner | item_id, reason |
| `marketplace.listed_toggle` | super_user | item_id, is_listed |
| `skill_credential.bind` | skill owner | skill_id, requirement_key, credential_id |
| `skill_credential.use` | runtime | skill_id, agent_id, requirement_key（不含值） |

### 13.3 System Credential 隔离

- System credential 不是 user skill credential 的快捷路径
- Hosted proxy 标记为 system dependency，不作为用户 binding 暴露
- `/api/system-credentials` 仅限 super_user（保留现有 ADR-016）

## 14. Testing Plan

### 14.1 Unit

- `access.py`: view/install/manage 规则矩阵全部覆盖
- ACL view/install/manage
- 创建 Immutable version（重试时结果相同）
- Install creates user-owned skill
- Credential requirement validation
- Binding rejects 其他用户的 credential
- Binding rejects 错误的 definition_key
- `secret_scan` rejects `.env`, PEM, sk- 模式
- k-skill discovery excludes non-skill dirs
- k-skill importer maps requirements（仅 curated map 通过，regex hint 输出到 review）
- Origin summary derivation (created/imported/built-in/shared/community)
- Publication summary derivation
- Redaction helper: env value, sensitive keys

### 14.2 Integration

- Publish skill → User B 安装 → 执行
- Restricted item invisible to non-ACL user
- Public item invisible from default catalog when `is_listed=False`
- Public item visible after super_user toggles `is_listed=True`
- Built-in install creates `skills` row with source references and `origin_kind='built_in_k_skill'`
- Required credential missing → installation `needs_setup`
- Bound credential injected into subprocess env（仅 mapped env var）
- Wrong credential not injected
- `/api/skills` includes origin/publication summaries
- Marketplace filters（installed/not installed/needs setup/update available）准确

### 14.3 Regression

- 现有 `/api/skills` 回归通过
- Agent 设置中选择 skill 的回归
- Package upload 回归
- MCP credential flow 回归
- System credential super_user 保护回归
- `not_published` 状态的现有资源页面正常使用

### 14.4 E2E

1. User A 创建 package skill
2. User A 以 restricted（对象: User B）方式 publish
3. User C 看不到 item
4. User B 执行 install
5. User B 将 skill 连接到 agent
6. Chat runtime 使用 installed skill 正文

Credential E2E:

1. 安装 Built-in `srt-booking`（无 credential）→ `needs_setup`
2. User 创建 `srt_account` credential
3. User 将 credential 绑定到 skill
4. Runtime 中 `KSKILL_SRT_ID`/`PASSWORD` 被注入 subprocess env（不直接暴露）
5. 在 log/SSE/tool result 中对值进行 redact

### 14.5 Permission test matrix

测试用户至少 4 名:

| User | Role |
|------|------|
| A | publisher/owner |
| B | restricted ACL target |
| C | unrelated authenticated user |
| Admin | super_user |

Assertions:

- A 可 publish private/restricted/public skill
- B 仅可 view/install ACL 中包含的 restricted item
- C 访问 restricted item 返回 404
- C 可 view public/system item
- Admin 可 disable public/system，可 listed toggle
- Disabled item 不允许 B/C 新 install
- 即使 A 修改 item metadata，也保留 B 的 installed copy

### 14.6 Runtime Isolation Tests

创建 Skill A, Skill B。Agent 仅 attach A。

- Runtime skills root 中仅存在 A
- `execute_in_skill("skill-a", ...)` 成功
- `execute_in_skill("skill-b", ...)` → "not attached" 结构化 error
- Prompt-visible `/skills/` instruction 中不暴露 B
- 即使 LLM 尝试 `read_file('/skills/skill-b/...')`，backend 也会阻止

### 14.7 Secret Safety Tests

- 包含 `.env` 的 package publish 失败
- 包含 `-----BEGIN PRIVATE KEY-----` 的 publish 失败
- Catalog list response 不包含 payload 文件内容
- Detail response 不暴露其他用户的 credential_id
- Credential decrypt 后 raise 的 exception 不包含 mapped env value

## 15. Migration Plan

### 15.1 顺序

1. **m40** `m40_marketplace_tables.py`: marketplace 5 个表 + circular FK 处理
2. **m41** `m41_skills_marketplace_columns.py`: skills 新增 12 个 column + backfill
3. **m42** `m42_agent_skills_config.py`: `agent_skills.config` JSON column
4. **m43** `m43_skill_credential_bindings.py`: `skill_credential_bindings` 表
5.（单独 PR）新增 8 个 credential definition import
6.（单独 PR）`secret_scan.py`, `redaction.py`, `access.py` 模块
7.（单独 PR）`app/marketplace/service.py` + 路由 read endpoint (Slice A)
8.（单独 PR）Slice B install
9.（单独 PR）Slice C publish + secret scan integration
10.（单独 PR）Slice D credential requirement/binding
11.（单独 PR）Slice E runtime mount + injection（安全影响较大）
12.（单独 PR）Slice F k-skill importer + CLI
13.（单独 PR）前端 Marketplace UI

### 15.2 Backfill

在 m41 中:

- 所有现有 skills: `is_system=FALSE`, `source_kind='user'`
- text skill (`kind='text'`): `origin_kind='created_by_me'`
- package skill (`kind='package'`): `origin_kind='imported_by_me'`
- 其他 origin/source column: NULL

### 15.3 Rollback

- 为每个 migration 实现 downgrade（可恢复到未使用 Marketplace 的状态）
- drop column 时警告数据丢失
- m42/m43 rollback 时 `agent_skills.config`/`skill_credential_bindings` 数据会消失
- m41 rollback 时 origin column 数据丢失

### 15.4 Feature Flags

`backend/app/config.py`:

```python
marketplace_enabled: bool = False
k_skill_builtin_sync_enabled: bool = False
skill_runtime_credential_injection_enabled: bool = False  # Slice E gating
```

- `marketplace_enabled=False`: 路由未注册或 503
- `k_skill_builtin_sync_enabled=False`: CLI 拒绝
- `skill_runtime_credential_injection_enabled=False`: 保持现有 broad mount（Slice E 未部署状态）

部署各 Slice 时逐步 enable。

## 16. Implementation Slices

### Slice A — Data + Read Catalog

- m40-m43 migration
- ORM model（`models/marketplace.py`, `models/skill.py` column）
- `access.py`, `origin_service.py`, `schemas.py`
- `GET /api/marketplace/items`, detail, version endpoint
- 在现有 `/api/skills`, `/api/mcp-servers` 响应中新增 origin/publication summary
- 无 Install/publish

验证：

- migration upgrade/downgrade
- Catalog 响应遵守 access 规则（private/restricted/public/system 场景）
- Existing skill list 显示 `not_published` summary

### Slice B — Skill Install

- `install_service.py`
- `POST /api/marketplace/items/{id}/install`
- `POST /api/marketplace/installations/{id}/update`
- `DELETE /api/marketplace/installations/{id}`
- 在 Installed skill row 中填充 source metadata
- 处理 `install_mode`

验证：

- 安装创建 user-owned skills row
- Installation row 跟踪 item/version/resource IDs
- 重复 install 严格遵循 `install_mode`

### Slice C — Skill Publish + Secret Scan

- `publish_service.py`, `secret_scan.py`
- `POST /api/marketplace/items/from-skill/{skill_id}`
- `POST /api/marketplace/items/{item_id}/versions/from-skill/{skill_id}`
- ACL 管理 API
- 创建 `marketplace_publication_links`
- Installed skill detail 显示 published 状态

验证：

- Publish 会 strip private data
- Secret scan rejects `.env`/PEM
- Restricted ACL 控制
- Immutable version
- API summary 准确显示 `Published · Restricted/Public/Unlisted`

### Slice D — Credential Requirements + Bindings

- import 新增 8 个 credential definition
- `credential_requirements.py`
- `GET|PUT|DELETE /api/skills/{id}/credential-bindings/...`
- 在 Install 流程中集成 binding wizard
- Frontend setup UX

验证：

- 拒绝错误 owner 的 credential
- 拒绝错误的 definition_key
- `needs_setup` 状态准确暴露在 catalog/detail/install 响应中

### Slice E — Runtime Mount + Credential Injection（安全 critical）

- `executor.py:build_agent` patch（per-thread copytree）
- 修改 `_create_skill_execute_tool` signature + env injection
- 集成 `redaction.py`
- Cleanup job (stale runtime root)
- Fail-fast: missing required credential

验证：

- 无法访问未选择的 skill
- Decrypted credential 仅暴露给 subprocess env
- log/SSE/tool result redaction
- Missing credential → `marketplace_credential_required` error

### Slice F — k-skill Importer

- `k_skill_importer.py`, `k_skill_requirements.py`
- `scripts/sync_k_skill.py` CLI
- Dry-run / partial sync
- Execution profile 分类
- Idempotent sync（比较 content_hash）

验证：

- Dry-run 报告 create/update/deprecate 计数
- 对同一 commit 再次执行时不产生新 version
- 单个 invalid skill 不会中断整个 sync
- Secret scan failure 仅 skip 对应 skill

### Slice G — Frontend UX

- Marketplace 页面（`/marketplace`, `/marketplace/installed`）
- Install wizard (4 steps)
- Publish wizard (5 steps)
- 增强 Installed resource page（origin/publication badges）
- Admin moderation 页面（super_user）

验证：

- Catalog 筛选/搜索/排序
- Install 后可在 agent 设置中选择 skill
- Publish wizard 显示 secret scan 结果
- 卡片 CTA 状态映射准确

## 17. Acceptance Criteria

Phase 1 完成条件:

- super_user 执行 k-skill sync → 创建 system skill item 目录
- 普通用户将 built-in skill 安装到自己的账户
- Installed skill list/detail 显示 origin 和 publication 状态
- 将 Owned skill 以 restricted/public/unlisted/private 方式 publish
- 仅 Restricted 目标用户可 install
- 非目标用户看不到 item（404）
- Required credential skill 在未 binding 时阻止执行
- Binding 使用中央 `credentials` 并校验 ownership/type
- Runtime 仅暴露已选择的 skill
- Mapped env var 仅注入 subprocess env，并在 log/SSE/tool result 中 redact
- Public publish 在切换为 `is_listed=True` 前不会出现在目录默认搜索中
- 现有 skill upload/edit/delete 回归通过

### Definition of Done by Feature Area

| Area | Done means |
|------|------------|
| Catalog | 可访问 item 的 list/detail 包含筛选、install state、credential summary、execution profile |
| Install | Skill install 创建 user-owned copy + installation link + 可选 credential binding |
| Publish | User skill publish 创建 immutable version，strip secret，并强制 visibility/ACL |
| Credentials | Definition、install setup、binding API、runtime injection、redaction 测试通过 |
| k-skill | Importer 可 dry-run/sync + 在 pinned commit 上 idempotent |
| Runtime | 仅 mount Selected skill，missing credential 在 command 执行前 fail |
| Frontend | Marketplace list/detail/install/publish flow 无需了解 JSON 即可使用 |

## 18. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Credential leak through marketplace package | Critical | secret_scan, strip fields, immutable review, no decrypted data in payload |
| Runtime exposes all skills | High | Per-thread runtime root + execute_in_skill slug 校验 |
| Upstream k-skill 恶意变更 | High | Sync 仅允许 super_user CLI，source commit pin，secret scan，support level |
| 不支持 Node/npm skills | Medium | 通过 Execution profile 向用户明确说明 |
| Public spam | Medium | super_user disable，`is_listed` gate，moderation_status，publish rate limit |
| Dirty installed skill update overwrite | Medium | `is_dirty` flag, no auto-update |
| Per-thread runtime root 磁盘使用 | Low | Cleanup job，短 retention，disk 监控 |
| Marketplace version FK + circular | Low | 在 m40 中通过后续 ALTER 处理 |

## 19. Implementation Handoff Order

在新 session 中开始实现此 spec 时的推荐顺序:

1. Slice A migration (m40) + ORM
2. Slice A catalog API (read-only)
3. Slice B install（手动将一个文本 skill 注册为 marketplace item 并验证 install）
4. Slice D credential definitions + binding API
5. Slice E **runtime mount + credential injection**（安全 critical，单独 PR/review）
6. Slice C publish + secret_scan
7. Slice F k-skill importer
8. Slice G frontend（可并行进行）

Slice E 是 marketplace 整体价值的基础安全 gate，因此拆分为单独 PR；runtime isolation test 和 secret safety test 全部通过后再 merge 到 main。

---

## 20. 参考

- PRD: `docs/marketplace-resources-prd.md` v0.2
- 原始 spec（Moldy 主仓）: `/Users/chester/dev/natural-mold/docs/maketplace/marketplace-resources-spec.md` v0.3
- ADR-007 / 009 / 013 / 016
- Key 代码位置:
  - `backend/app/agent_runtime/executor.py:113-195` (`_create_skill_execute_tool`)
  - `backend/app/agent_runtime/executor.py:213-225`（调用 `create_deep_agent`）
  - `backend/app/agent_runtime/executor.py:544-571` (FilesystemBackend + skills mount)
  - `backend/app/skills/service.py:46-51` (`_storage_root`)
  - `backend/app/skills/service.py:389-404` (`to_runtime_dict`)
  - `backend/app/skills/packager.py:59-93` (zip validation)
  - `backend/app/skills/prompt.py:27-50` (`build_skills_prompt`)
  - `backend/app/credentials/definitions/__init__.py:22-37`（自动注册 registry）
  - `backend/app/dependencies.py` (`get_current_user`, `require_super_user`, `verify_csrf`)
