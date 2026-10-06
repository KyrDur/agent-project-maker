# natural-mold Marketplace Resources PRD

> 编写日期: 2026-05-18
> 版本: v0.4 (反映 2026-09-08 source-aligned status)
> base: `/Users/chester/dev/natural-mold/docs/maketplace/marketplace-resources-prd.md` v0.3, `marketplace-resources-spec.md` v0.3
> scope: Agent / MCP / Skill 共享 marketplace + built-in k-skill catalog + credential connection UX

## Changelog

| 版本 | 日期 | 变更内容 |
|------|------|-----------|
| v0.4 | 2026-09-08 | 将 MCP/Agent publish/install 实现与通用 wizard 反映到当前状态。下方 Phase 1~4 列表是引入时的设计顺序，并非未实现清单。E2E 状态在 `e2e-coverage.md` 管理。 |
| v0.3 | 2026-06-07 | 按实际 source 更新实现状态。反映截至 M40~M44 marketplace/skill lineage/relative storage、M59 artifact 联动时点，catalog/install/update/uninstall/publish/ACL/admin listed state/secret scan/k-skill importer/skill credential binding/selected-skill runtime mount/credential env injection/redaction 已实现。剩余范围以扩展 MCP/Agent resource publish 与 E2E/运营 hardening 为主。 |
| v0.2 | 2026-05-18 | 反映 natural-mold source code 深入分析结果。修正为 **execute_in_skill subprocess runner 已经引入**(废弃此前 v0.1 的错误假设)。空缺是 (a) 无 credential env 注入, (b) broad skill mount(`/skills/`), (c) packager 无 secret scan, (d) AgentSkillLink 无 config 字段, (e) Skill model 无 source/dirty/origin 列。明确列出 14 个现有 credential definition + 需要为 k-skill 添加新 definition。与 ADR-007/009/013/016 的准确 mapping。 |
| v0.1 | 2026-05-18 | (已废弃) 初始适配版。包含多项错误假设。 |

---

## 2026-09-08 Current Implementation Status

本文档 v0.2 正文大量保留了以 2026-05-18 为基准的设计 baseline。当前
按 source 看，不仅 Skill，MCP template 与 Agent spec 的发布·安装及
通用 wizard 也已加入，因此优先信任下方状态表。

| Area | Status in source |
|------|------------------|
| Marketplace schema | Implemented in M40~M44: item/version/ACL/installation/publication/skill binding, skill lineage, `agent_skills.config`, relative storage path |
| Catalog APIs | Implemented: list/page/detail/version with visibility and install-state projection |
| Install/update/uninstall | Implemented in `backend/app/marketplace/install_service.py` and router endpoints |
| Publish/version/ACL/admin | Implemented in `publish_service.py`, secret scan, ACL replace/remove, disable, super_user listed-state actions |
| Skill credential requirements | Implemented: requirement validation, bindings, runtime credential resolution |
| Credential definitions | 22 registered definitions, including SRT/KTX/Forest Trip/KIPRIS/DART/ODsay/Coupang/K-Skill Proxy and MCP Secret |
| Runtime mount | Implemented: selected skill runtime prefix under `/runtime/<thread_id>/.../skills/`, not broad `/skills/` exposure |
| Runtime credential env | Implemented through `build_skill_runtime_context()` and `resolve_runtime_credentials()` |
| Redaction | Implemented in marketplace/runtime paths for credential-bearing skill execution |
| k-skill importer | Implemented in `k_skill_importer.py`, `k_skill_requirements.py`, and `app/scripts/sync_k_skill.py` |
| Frontend | Implemented marketplace catalog/detail/admin moderation routes and origin/publication UX surfaces |
| MCP templates | `mcp_server.py`, `install/mcp.py`: publish/version/install, requirements and secret stripping |
| Agent blueprints | `agent_spec.py`, `install/agent_blueprint.py`: spec/dependency snapshots, blueprint install and credential rebinding |
| Shared UI | `publish-wizard.tsx`, `install-wizard.tsx` support Skill/MCP/Agent; moderation is `/settings/marketplace-admin` |
| Remaining validation | External OAuth, complex dependency/update/binding combinations and operational hardening; current E2E scope is in `e2e-coverage.md` |

## Decision Summary

本 PRD 的核心决定与原文相同 — "marketplace 是发布原本，执行由安装到用户账户的 copy 负责"。根据 natural-mold 的实际代码状态，明确以下决定。

| 决定 | 选择 | 理由 |
|------|------|------|
| marketplace resource 范围 | Skill, MCP, Agent (Tool 为非目标) | Tool 是 `backend/app/tools/registry.py` 中基于内存的 `ToolDefinition`，属于由运营者通过代码定义的资产，用户不会创建或共享 |
| 阶段拆分 | Phase 1 Skill / Phase 2 MCP / Phase 3 Agent | 保持原 PRD 阶段。Skill loop 最闭环且即时价值最大 |
| Skill runtime baseline | 已实现 deepagents + `execute_in_skill` subprocess runner + selected-skill mount + credential env injection + redaction contract | 未引入新 runner，而是在扩展现有 runtime 的状态 |
| 引入 k-skill | 通过 sync job fetch GitHub `NomaDamas/k-skill` upstream → 登记为 system marketplace item | 不直接修改 upstream code，以 immutable snapshot 方式导入 |
| Public publish 策略 | 分离 published vs listed，只有 super_user 可切换 listed | 任何人都可 publish，但 catalog 展示受 operator gate 控制 |
| 认证前提 | ADR-016 多用户认证已完成状态 | 已应用 JWT(HS256) + HttpOnly Cookie + refresh rotation + super_user 权限 |
| Visibility 模型 | private / restricted / public / unlisted / system | 与原文相同 |
| Credential 处理 | 复用中央 `credentials` 表 + Cipher V2 + field_keys cache + is_system 分离 | 在 ADR-007/009 基础设施之上实现 binding/requirement model |
| 安装方式 | 将 marketplace version 复制为用户拥有的 installed resource | 保持原决定 |
| 版本策略 | published version immutable | 保持原决定 |
| 更新 | 禁止自动更新，由用户明确应用 | 保持原决定 |
| 来源显示 | 所有 installed Agent/MCP/Skill 显示 origin 与 publication state | 已实现 Skill lineage 及 MCP/Agent projection。各组合的 E2E coverage 单独管理 |

## MVP Product Bet

Phase 1 的目标是"用户选择 built-in k-skill 安装成自己的 Skill，必要时连接 credential 后挂到 agent 上执行"。该流程已实现，并已扩展到 MCP/Agent 发布·安装。当前剩余课题不是视为新实现，而是提升运营/E2E 可信度。

MVP 中必须呈现的体验:

- 在 Marketplace > Skills 中找到 built-in/system skill 并安装。
- 对需要认证的 skill，在安装前后都明确显示需要什么。
- 用户将值保存到中央 `credentials`，并连接到 skill requirement。
- 已安装 skill 像现有我的 Skill 一样连接到 agent，agent 执行时**只暴露所选 skill 的目录**，并通过 **mapped env var 将 credential 注入 subprocess**。
- 以 restricted 方式共享的 skill 只对获准用户可见。
- upstream k-skill update 显示为 update available，但不会自动应用。
- 任何人都可以 public publish，但未经 super_user 批准为 listed 的项目不会显示在搜索 catalog 中 (只能通过链接访问)。

## 1. 背景

natural-mold 已按 ADR-016 完成多用户认证，Agent / MCP server / Skill / Credential / Tool 都作为用户拥有的 resource 管理。已应用 JWT(HS256) + HttpOnly Cookie + refresh token rotation + `is_super_user` 角色。

已具备的结构 (marketplace 设计中复用):

| 区域 | module/path | 状态 |
|------|----------|------|
| Skill model | `backend/app/models/skill.py:Skill` | text/package kind, storage_path, content_hash, version, package_metadata, used_by_count |
| Skill service | `backend/app/skills/service.py` | CRUD, `to_runtime_dict`, filesystem 管理(`data/skills/<id>/`) |
| Skill packager | `backend/app/skills/packager.py` | `.skill` ZIP extract, 防止 symlink/zip-slip/null-byte, 50MB 限制 |
| Skill inspector | `backend/app/skills/inspector.py` | SKILL.md frontmatter parse, 安全文件访问 |
| Skill runtime | `backend/app/skills/runtime.py:build_skills_for_agent` + `prompt.py:build_skills_prompt` | AgentSkillLink → descriptor + 注入 LLM prompt |
| Skill 执行工具 | `backend/app/agent_runtime/skill_executor.py` | **`execute_in_skill` subprocess runner 正在运行**。Python allowlist, timeout, output dir, credential env injection, redaction contract |
| Agent runtime | `runtime_component_builder.py:build_agent` + `create_deep_agent` + `FilesystemBackend(_DATA_DIR, virtual_mode=True)` | 基于 deepagents，将所选 skill mount 到 `/runtime/<thread_id>/.../skills/` |
| MCP model | `models/mcp_server.py`, `mcp_tool.py`, `AgentMcpToolLink` | transport(stdio/sse/streamable_http), `is_system`(M26), health_status |
| MCP discovery | `app/mcp/client.py`, `app/mcp/discovery.py` | 连接 + `list_tools` + credential interpolation + last_seen_at upsert |
| MCP health polling | `app/scheduler.py:MCP_HEALTH_JOB_ID` | APScheduler 5 分钟 interval |
| Credential model | `models/credential.py` | `is_system` + CHECK constraint, key_id, field_keys cache |
| Cipher V2 | `app/security/cipher.py` | HKDF-SHA256 + AES-256-GCM, multi-key rotation, info=`moldy-encryption-v1` |
| Credential definition | `app/credentials/definitions/` | 已注册 22 个: LLM, Google/Naver, HTTP, MCP secret/OAuth2, SRT/KTX/Forest Trip/KIPRIS/DART/ODsay/Coupang/K-Skill Proxy |
| Credential interpolation | `app/credentials/interpolation.py:resolve_deep` | `={{ $credentials.x }}` (用于 MCP env_vars/headers) |
| 认证 | `app/auth/`, `app/dependencies.py` | `get_current_user`, `require_super_user`, `verify_csrf` |

PRD 中将已具备的基础设施明确为"复用"，而不是"新增引入"。

下一阶段是共享 layer，让用户创建的 Agent/MCP/Skill 可与其他用户共享，并让用户可选择性获取运营方提供的 built-in resource 使用。

尤其 `NomaDamas/k-skill` 仓库是韩国业务/生活自动化 skill 集合，适合作为 natural-mold 的 built-in skill catalog。upstream 会持续更新，因此不 hard fork，而是验证特定 upstream commit 的 skill snapshot 后作为 catalog version 导入。

## 2. 问题定义

### 2026-05-18 baseline 问题与 2026-06-07 状态

下列项目是编写 v0.2 时的 gap，目前大部分已实现完成。

| Baseline gap | 2026-06-07 source status |
|--------------|--------------------------|
| Skill 无法共享 | 已实现 Marketplace item/version/install/publish |
| 缺少通用 marketplace layer | 已实现 M40 marketplace tables + service/router |
| 缺少 built-in / 用户资产统一 UX | 已实现 Marketplace catalog/detail/admin + origin/publication summary |
| 未声明 Skill credential requirement | 已实现 `credential_requirements`, `skill_credential_bindings`, binding validation |
| AgentSkillLink 无 override 位置 | 已实现 M42 `agent_skills.config` |
| Skill 无 marketplace tracking column | 已实现 M41 skill lineage/source/origin/dirty columns |
| Broad skill mount | 已实现 selected-skill runtime mount under `/runtime/<thread_id>/.../skills/` |
| `execute_in_skill` 未注入 env credential | 已实现 runtime credential resolution + mapped env injection |
| 缺少 Secret scan | 已实现 marketplace publish/upload secret scan |
| 共享时存在 private data 泄漏风险 | 已实现 publish strip, secret scan, binding, redaction contract |

### 目标状态

- 用户可以将自己创建的 Agent/MCP/Skill 发布到 marketplace。
- 共享范围支持 private、指定用户 restricted、全体公开(listed/unlisted)、built-in/system。
- 其他用户可以将 marketplace item 安装到自己的账户。
- built-in k-skill item 由 super_user 从 upstream 同步，用户只选择安装需要的 skill。
- Skill 如需 credential，需在 marketplace 和安装页面清楚显示。
- credential 值绝不包含在 marketplace package 中，而是按用户注册到 `credentials` 并连接。
- installed resource 与原 marketplace version 关联，并显示是否有可用更新。
- agent runtime **只暴露所选 skill**，credential **仅通过 subprocess env 注入**。

## 3. 目标

1. 将 Agent, MCP, Skill 作为一个 marketplace resource model 共享。
2. 保持现有用户拥有的表(`agents`, `mcp_servers`, `skills`)作为实际安装副本。
3. 将 Marketplace item/version 作为可发布的 immutable snapshot 管理。
4. 支持公开范围与指定用户访问控制。
5. 将 Built-in k-skill 作为 system marketplace item 导入。
6. 引入 Skill credential requirements 与 user credential binding (Phase 1)。
7. 确保共享/安装/更新流程中 secret 不泄漏 (packager 添加 secret scan，publish 时 strip)。
8. `execute_in_skill` 执行时保证 selected-skill mount + credential env 注入 + redaction。

## 4. 非目标

- **Tool marketplace**: natural-mold 的工具是 `backend/app/tools/registry.py` 中基于内存的 `ToolDefinition`，由运营方通过代码定义。用户不会创建或共享。如以后需要用户自定义工具，另开 PRD。
- **引入新 skill runner**: 已有 `execute_in_skill` subprocess runner，因此不新建。Node/curl 等附加 runtime 未来另开 ADR。
- 支付·付费 marketplace
- 星级·review·ranking algorithm
- 通过外部公开 URL anonymous 执行
- 组织/团队级权限模型
- 共享 Agent 执行结果、conversation history、token usage
- Skill code sandbox 完全隔离 (Phase 1 维持当前 allowlist + 30 秒 timeout)
- 向 k-skill upstream 提交 PR 或为 natural-mold 修改 upstream code

## 5. 用户类型

| 用户 | 说明 | 主要行为 |
|--------|------|-----------|
| 普通用户 | natural-mold 账户 (`users` row, `is_super_user=False`) | 浏览 marketplace、安装 resource、发布我的 resource、指定 restricted 共享对象 |
| 创作者 | 创建并共享 Agent/MCP/Skill 的用户 | version publish, 设置公开范围, 发布更新 |
| 安装者 | 获取并使用其他用户 resource 的用户 | 连接 credential, 连接到 agent, 应用更新 |
| super_user | 运营者/管理员 (`users.is_super_user=True`) | built-in/system resource sync, public item 的 listed 批准/disable, system credential 管理, 执行 k-skill 同步 |

## 6. Resource 概念

### Installed Resource

这是实际安装到用户账户并执行的 resource。继续使用现有表。

- Agent: `agents`
- MCP: `mcp_servers`, `mcp_tools`
- Skill: `skills`

Installed resource 拥有 `user_id`。用户只能修改·删除·连接到 agent 自己的 installed resource。

Phase 1 中需添加到 `skills` 表的 column (全部 nullable, backfill):

- `is_system` (BOOLEAN DEFAULT FALSE) — 与 system seed 相同 pattern
- `source_kind` (VARCHAR 40) — `user`, `k-skill`, `import`, `system_seed`
- `source_marketplace_item_id` (UUID NULL FK)
- `source_marketplace_version_id` (UUID NULL FK)
- `source_commit` (VARCHAR 80 NULL)
- `credential_requirements` (JSON NULL) — 从 version 复制的 fast-display copy
- `execution_profile` (JSON NULL) — 从 version 复制
- `origin_kind` (VARCHAR 40 DEFAULT 'created_by_me')
- `origin_user_id` (UUID NULL FK users)
- `origin_marketplace_item_id` (UUID NULL FK)
- `origin_marketplace_version_id` (UUID NULL FK)
- `is_dirty` (BOOLEAN DEFAULT FALSE) — 追踪 installed resource 修改 (在 text content/files endpoint 中设置)

需添加到 `AgentSkillLink` 的 column:

- `config` (JSON NULL) — `{ "credential_bindings": { "<requirement_key>": "<credential_id>" } }` 形式的 agent-skill 级 override

### Marketplace Item

这是可共享的 logical item。一个 item 可有多个 version。

- `resource_type`: `agent | mcp | skill`
- 作者: 普通用户或 system (super_user)
- 公开范围: private, restricted, public, unlisted, system
- 是否在搜索 catalog 中显示: `is_listed` (仅 super_user 可 toggle)
- 包含用于搜索/catalog 展示的 metadata

### Marketplace Version

这是可安装的 immutable snapshot。

- Skill: `.skill` package snapshot 或 storage snapshot
- MCP: MCP server template + auth requirements + tool discovery hints (Phase 2)
- Agent: agent spec + tool/MCP/skill references + model preference (Phase 3)

一旦 publish 的 version 不再修改。如需变更则创建新 version。拼写错误等 metadata 修改通过 item-level metadata update 处理。

### Installation

这是用户将 marketplace version 获取到自己账户的记录。

- 追踪 source item/version
- 与已安装的 `agents.id`, `mcp_servers.id`, `skills.id` 关联
- 判断是否可更新(`update_available`)，追踪 dirty 状态(`is_dirty`)

### Resource Origin

Installed Agent/MCP/Skill 列表和详情页面必须让用户能够立即理解 resource 的来源。

| Origin | 含义 | 展示示例 |
|--------|------|-----------|
| `created_by_me` | 用户直接创建的 resource (text skill 等) | `Created by me` |
| `imported_by_me` | 用户通过文件/URL 导入的 resource (例如上传 `.skill` ZIP) | `Imported by me` |
| `built_in_k_skill` | 从 system marketplace 的 k-skill 安装的 skill | `Built-in · k-skill` |
| `shared_with_me` | 安装其他用户通过 restricted/public 共享的 resource | `Shared by {user}` |
| `community` | 安装公开 marketplace item | `Community` |
| `system_seed` | 系统 seed(`bootstrap_from_env`)默认提供的 resource | `System` |

Origin 不改变 ownership。即使显示为 `Built-in · k-skill`，安装后的 skill row 仍归安装者所有。

### Publication State

我拥有的 Agent/MCP/Skill 另有 marketplace publication 状态。

| Publication State | 含义 | 用户操作 |
|-------------------|------|-------------|
| `not_published` | 无 marketplace item | Publish |
| `draft` | 正在准备发布，仅 owner 可访问 | Continue setup |
| `published_private` | 有 marketplace item 但仅 owner 可访问 | Change visibility, New version |
| `published_restricted` | 已共享给指定用户 | Manage users, New version |
| `published_public_listed` | 公开 + 搜索可见 (通过 super_user 批准) | New version, Disable |
| `published_public_unlisted` | 已公开但不在搜索中显示 (未获 super_user 批准) | Request listing, Copy link |
| `published_unlisted` | 明确选择 unlisted (仅链接访问) | Copy link, Change visibility |
| `disabled` | super_user 停止发布 | Re-enable 或 keep disabled |

Installed resource 页面同时显示 origin badge 和 publication badge。

## 7. 公开范围

| Visibility | 含义 | 访问 |
|------------|------|------|
| `private` | 仅作者可见的 draft 或个人 item | 仅 owner view/manage |
| `restricted` | 仅指定用户可见 (ACL) | owner + ACL 对象 |
| `public` | 所有已登录用户可见 (但搜索可见性取决于 `is_listed`) | 所有用户 view/install |
| `unlisted` | 只有持有链接的用户可访问 | 不在搜索中显示 |
| `system` | 运营方提供的 built-in catalog | 所有用户 view/install, super_user manage |

`restricted` 从 user 级 ACL 开始。

### 分离 Published vs Listed

`visibility=public` 的 item 另有 `is_listed` flag。

- 默认值: `is_listed=False`
- 只有 super_user 可以 toggle `is_listed=True`
- catalog 的默认 listing(`/api/marketplace/items` 默认查询)只显示满足 `is_listed=True OR visibility=system OR owner=current_user OR ACL` 条件的项目
- `is_listed=False` 的 public item 若知道直接 ID/slug，仍可访问/安装 (效果与 unlisted 相同)
- super_user 发现不合适的 public item 时，可设 `is_listed=False` 进行 unlist，或设 `status=disabled` 禁用

### 权限策略矩阵

| Actor | private | restricted | public | unlisted | system |
|-------|---------|------------|--------|----------|--------|
| Owner | view/manage/install | view/manage/install | view/manage/install | view/manage/install | N/A |
| ACL view | no | view | N/A | no | N/A |
| ACL install | no | view/install | N/A | no | N/A |
| Any logged-in user | no | no | view(仅 listed 可搜索)/install | direct-link view/install | view/install |
| super_user | view/manage | view/manage | view/manage/list/disable | view/manage/list/disable | view/manage |

未授权用户尝试 item detail 或 install 时，默认返回 404，避免暴露 private/restricted item 是否存在 (遵循 CLAUDE.md 的 `enumeration oracle` 防护原则)。

## 8. Credential 原则

natural-mold 已按 ADR-007/009 具备 `credentials` 表 + Cipher V2 + field_keys cache。marketplace 直接复用该系统。

1. Marketplace item/version 中不保存 credential value。
2. Skill/MCP/Agent 只声明所需 credential type 和 field requirement (`credential_requirements` JSON)。
3. 用户安装时选择自己已有的 `credentials` row 或新建。
4. 执行时 runtime 解密已连接 credential，仅注入到对应 process/tool call。
5. System credential(`is_system=True`, `user_id IS NULL`)不向普通用户暴露，也不自动连接 (`/api/system-credentials` 仅限 super_user)。
6. 基于 Hosted proxy 的 skill 标记为不需要用户 credential，但区分为 operator/system dependency。

### Credential definition 状态

截至 2026-06-07，`backend/app/credentials/definitions/` 中有 22 个 definition
definition 已注册。为 k-skill requirement 计划的 definition 也已添加。

| definition_key | Fields | Used by |
|----------------|--------|---------|
| `srt_account` | `username`, `password` | `srt-booking` |
| `ktx_account` | `username`, `password` | `ktx-booking` |
| `foresttrip_account` | `username`, `password` | `foresttrip-vacancy` |
| `kipris_plus_api` | `api_key` | `korean-patent-search` |
| `dart_api` | `api_key` | `k-dart` |
| `odsay_api` | `api_key` | transit/route skills |
| `coupang_partners` | `access_key`, `secret_key` | Coupang Partners skills |
| `k_skill_proxy` | proxy credentials | hosted k-skill proxy |

保留现有 LLM/搜索/HTTP/MCP definition(openai, anthropic, google_genai, azure_openai,
openrouter, openai_compatible, google_search, naver_search,
google_workspace_oauth2, http_bearer, http_basic, http_api_key, mcp_secret,
mcp_oauth2)。

这些 definition 已注册到现有 `CredentialRegistry` singleton(import time 自动注册)。创建新 row 时会自动填充 field_keys cache(ADR-007)。

### Credential UX 原则

- Marketplace card 只显示 requirement 状态，不显示 credential value。
- 安装 wizard 先解决 required credential，但若用户选择 `稍后设置`，可以以 `needs_setup` 状态安装。
- `needs_setup` skill 可以连接到 agent，但 runtime 执行前要 fail-fast 阻止，并显示设置 CTA。
- 如果已有 compatible credential，则作为默认选项建议，但不自动保存。
- optional credential 不阻止安装，连接后可开启更丰富功能。
- manual login skill 不跳转到 Credential 保存页面，而是单独标记为需要浏览器/本地 app session 的状态。

## 9. Skill Credential Requirement

Skill 必须具有以下状态之一。

| 状态 | 含义 | UX |
|------|------|----|
| none | 无需认证 | `No credential needed` |
| optional | 有则可使用更丰富路径 | `Optional credential` |
| required | 执行前需要用户 credential | `Credential required` |
| hosted_proxy | 使用运营方 proxy key，无需用户 key | `Uses hosted proxy` |
| manual_login | 需要用户在浏览器/app 中直接登录 | `Manual login required` |

示例:

- `srt-booking`: `required`, `srt_account`
- `ktx-booking`: `required`, `ktx_account`
- `korean-patent-search`: `required`, `kipris_plus_api`
- `seoul-density`: `hosted_proxy`
- `kakaotalk-mac`: `manual_login`
- `korean-spell-check`: `none`

## 10. 主要用户场景

### 10.1 安装 built-in skill

1. 用户在 Marketplace > Skills 搜索 `korean-spell-check`。
2. card 显示 `Built-in`, `No credential needed`, `ko-KR`, `writing`。
3. 用户点击 Install。
4. natural-mold 将对应 marketplace version 安装为用户的 `skills` row (storage 为 `data/skills/<skill_id>/`)。
5. 填充 `skills.origin_kind='built_in_k_skill'`, `source_marketplace_*` column。
6. 用户在 agent 设置中选择该 skill。

### 10.2 安装 credential required skill

1. 用户尝试安装 `srt-booking`。
2. 安装页面显示 `SRT account credential required`。
3. 用户选择现有 `srt_account` credential 或新建。
4. 安装后创建 `skill_credential_bindings` row。
5. Agent 执行时 runtime 解密 binding 的 credential，并以 mapped env var(`KSKILL_SRT_ID`, `KSKILL_SRT_PASSWORD`)注入 `execute_in_skill` subprocess。

### 10.3 用户共享自己的 skill

1. 用户在 `/skills` 打开自己的 skill 详情。
2. 点击 `Publish to Marketplace`。
3. 在共享前检查页面(secret scan + 文件树 preview)确认 name, description, tags, license, credential requirements, included files。
4. visibility 选择 `public` 或 `restricted`。
5. publish 后创建 marketplace item/version (从 `is_listed=False` 开始)。
6. 其他用户 install 后获取为自己的 skill copy。

### 10.4 仅共享给指定用户

1. 创作者将 visibility 设为 `restricted`。
2. 输入允许用户的 email。
3. 创建 `marketplace_item_acl` row。
4. 只有目标用户能在 marketplace 看到并安装 item。
5. 从目标列表移除后会阻止新的安装，但已安装的 copy 保留。

### 10.5 更新 built-in k-skill

1. super_user 执行 k-skill sync job (`uv run python -m app.scripts.sync_k_skill --ref <commit>`)。
2. job fetch upstream commit 并 validate skill layout。
3. 只将发生变更的 skill 注册为新 marketplace version。
4. 现有安装者会看到 `Update available` badge。
5. 用户应用更新后，installed skill storage 替换为新的 snapshot。
6. 用户自行修改过的 installed skill 标记为 `is_dirty=True`，不会自动覆盖。

### 10.6 管理我的 resource 发布状态

1. 用户在 `/skills`, `/mcp-servers`, dashboard 中查看自己的 resource。
2. 每个 row/card 显示 origin badge 和 publication badge。
3. 用户自己创建的 resource 显示 `Not published` 或 `Published · Restricted` 等 publication badge。
4. 用户点击 `Publish` 后打开 marketplace publish wizard。
5. publish 后，现有 resource 详情中显示 marketplace 状态以及 version/update action。

### 10.7 super_user 批准 public item listed

1. super_user 在 `Marketplace > Moderation` 查看 `is_listed=False` 的 public item 列表。
2. 打开 item，确认 metadata, files, credential requirements, 作者。
3. 点击 `Approve listing` 后变为 `is_listed=True`，并出现在 catalog 默认搜索中。
4. 不合适的 item 通过 `Disable` 设为 `status=disabled` (阻止新安装)。

## 11. 功能需求

### 11.1 Marketplace Catalog

- 按 resource type 提供列表: Agent, MCP, Skill
- 搜索: name, description, tag, category, locale
- filter: resource type / install state / source / visibility / built-in/system / credential status / execution support level / category / locale
- card 展示: 名称, 说明, 作者, resource type, visibility, latest version, credential requirement summary, installed/update available 状态, listed/unlisted badge(仅 public)

Catalog 必须区分用户可立即安装的 item 和执行支持仍有限的 item。尤其即使导入全部 80 个 k-skill，也要显示 `Python ready`, `Proxy required`, `Node required`, `Manual login`, `Unsupported` 等 badge，准确管理预期。

默认 tab: `All`, `Agents`, `MCP`, `Skills`, `Installed`

按安装状态快速查看: `Not installed`, `Installed`, `Needs setup`, `Update available`, `Disabled source`

card CTA:

| 状态 | Primary CTA |
|------|-------------|
| 未安装 | Install |
| 已安装 | Installed 或 Open |
| needs setup | Set up |
| update available | Update |
| dirty + update available | Review update |
| manual/unsupported | View details |

### 11.2 Publish

- 用户可以将自己 owned resource publish 到 marketplace。
- publish 前 preview 显示会被排除的 private data 和 secret scan 结果。
- version 以 immutable 形式保存。
- 可以在同一个 item 上 publish 新 version。
- public publish 必须通过最低限度 metadata validation。
- restricted publish 的 ACL 对象必须至少 1 人。
- public publish 从 `is_listed=False` 开始。用户可向 super_user 请求 listing。
- publish 不是简单 toggle，而要经过 preview、secret scan、credential stripping、创建 immutable version 的流程。

### 11.3 Install

- 用户可以 install 自己有权限访问的 marketplace version。
- 安装结果是用户拥有的 installed resource (`skills.user_id = current_user.id`)。
- 安装时检查 credential requirements 并提供 binding wizard。
- 安装后保留 source item/version reference。
- 同一个 item 可以多次安装，但默认 UX 显示现有安装并引导 update。

### 11.4 Update

- installed resource 比 source version 旧时显示 update available。
- 用户自行修改过的 installed resource 处于 `is_dirty=True` 状态。dirty 追踪在以下 endpoint 中设置:
  - `PUT /api/skills/{id}/content`
  - `PATCH /api/skills/{id}`
  - `PUT|POST|DELETE /api/skills/{id}/files/{path}`
- dirty 状态 update 选择以下之一:
  - overwrite with latest
  - install as new copy
  - keep current
- Phase 1 不做自动 merge。

### 11.5 Credential Binding

- Marketplace version 拥有 credential requirements (`marketplace_versions.credential_requirements` JSON)。
- 安装时缺少 required credential，则变为 `needs_setup` 状态。
- 用户安装后仍可连接/替换 credential。
- Binding scope:
  - skill installation default → `skill_credential_bindings` 表
  - agent-skill override → `agent_skills.config` JSON 字段
- 若存在 agent-skill override，runtime 优先使用 override。

### 11.5b Runtime Skill Mount and Credential Injection

natural-mold 基于 deepagents，`execute_in_skill` subprocess runner 已
拆分到 `skill_executor.py`。截至 2026-06-07，Phase 1 的三项 security
强化(selected-skill mount, credential env injection, redaction contract)已经实现
完成。

1. **Selected-skill mount**: 在 per-thread virtual root 中只暴露所选 skill，并且只向 agent 传递 `/runtime/<thread_id>/.../skills/` 路径。不暴露未选择的 skill 目录以及其他用户的 skill。

2. **Credential env injection**: 加载 skill 的 credential requirement 与 user binding，解密后以 mapped env var 注入。注入对象仅限已 binding 的 requirement，并优先 agent-skill override。

3. **Redaction contract**: 在 log, SSE event, tool result, exception detail, frontend toast 中 redact mapped env var 值以及敏感 key(`password`, `api_key`, `secret`, `token`, `access_key`, `refresh_token`)的值。

这三项工作 security 影响较大，因此必须与 marketplace catalog/publish 工作分开验证。保持不引入新 subprocess runner，而是强化现有 runtime 的方向。

### 11.6 k-skill Built-in Sync

- upstream repo: `https://github.com/NomaDamas/k-skill.git`
- 运营设置:
  - `k_skill_upstream_url`: 默认 GitHub URL
  - `k_skill_upstream_ref`: 要同步的 commit 或 branch (`main` 为默认)
  - `k_skill_sync_dir`: clone upstream 的临时路径 (`./data/upstreams/k-skill`)
  - `k_skill_builtin_storage_dir`: 验证完成后的 marketplace storage 路径 (`./data/marketplace/k-skill`)
- sync job 以 read-only 方式使用 upstream。不修改 upstream code。
- 执行:
  - `uv run python -m app.scripts.sync_k_skill --ref main`
  - `uv run python -m app.scripts.sync_k_skill --ref <commit> --dry-run`
- 将每个 root skill directory upsert 为 marketplace skill item/version。
- 验证: 存在 SKILL.md，frontmatter `name` 与目录名一致等 (保持原 spec 5.2)。
- unsupported or restricted skill 仍显示在 catalog 中，但明确 execution support level (`ready_python`, `proxy_http`, `node_package`, `browser_or_local`, `manual_only`, `disabled`)。
- disabled upstream skill 显示为 `deprecated` 或 `disabled`。
- idempotent: 用相同 commit 再执行时不创建新 version (比较 content_hash)。
- 单个 skill validation 失败不会阻止整个 sync。
- credential requirement 映射以 curated map(`K_SKILL_REQUIREMENT_MAP` 等)为 source of truth。regex 仅作为 review signal。

### 11.7 运营者管理

- super_user 可以创建·sync·disable system/built-in item。
- super_user 不能解密用户 credential 或代用户连接 (仅拥有 Cipher V2 active key 访问权限，按 multi-tenant policy，其他用户 credential 在没有单独 ACL 时不可查看)。
- public item 不合适时，super_user 可设为 `disabled`。
- disabled item 阻止新安装，现有安装副本继续作为用户拥有的 copy 保留。
- super_user toggle public item 的 `is_listed` (批准/取消搜索 catalog 展示)。
- system item 显示 source URL, source commit, sync time, support level。
- 新的 `/api/marketplace/admin/*` router 通过 `Depends(require_super_user)` 保护。

### 11.8 用户通知与状态

- `installed`: 已安装
- `needs_setup`: 已安装但 required credential 未连接
- `update_available`: 存在最新 version
- `dirty`: 用户修改了安装副本，update 时可能冲突
- `disabled_source`: 原 marketplace item 已 disabled/deprecated
- `unlisted_public`: 用户 publish 的 public item 尚未获得 super_user 批准，因此不在 catalog 中展示

状态可以互相叠加。

### 11.9 Installed Resource 页面需求

`/skills`, `/mcp-servers`, agent dashboard 是独立于 marketplace 的“我的 resource”管理页面，但必须显示 marketplace 来源和发布状态。

通用展示:

- origin badge
- publication badge
- marketplace source item/version
- update available
- needs setup
- disabled/deprecated source

Skill 列表推荐 column: Name / Kind / Origin / Marketplace / Credential / Used by / Updated
MCP 列表推荐 column: Name / Transport / Origin / Marketplace / Credential / Health / Updated
Agent dashboard/card 推荐 badge: Origin / Published visibility / Shared·Installed source / Needs setup / Update available

### 11.10 Marketplace UI Reference

Marketplace UI 保持 natural-mold 现有 dashboard/table/card/dialog-shell pattern(`frontend/src/components/`)，同时参考以下开源案例。

| Reference | 参考点 |
|-----------|-------------|
| Cal.com App Store | app install 状态, app package 结构, 基于 PR/review 的 publish 流程 |
| Dify Marketplace | 按 resource type 浏览, 区分 Marketplace/GitHub/local package 安装 source |
| Open VSX Registry | versioned extension registry, web UI + publish CLI + server separation |
| shadcn/ui ecosystem | 与当前 UI stack 匹配的 compact card, filter, dialog pattern |

不整体照搬 UI。只参考 information architecture、状态展示、安装·发布流程，并适配 natural-mold 现有 sidebar, DataTable, card, dialog-shell pattern(ADR-010)。

## 12. 策略需求

### Secret Safety

- Credential data 禁止包含在 marketplace payload 中。
- `.env`, token, cookie, local secret 文件禁止包含在 package 中。
- import/publish 时检查 secret-like filenames 和 patterns (`secret_scan.py` 新 module)。
  - 文件名: `.env`, `.env.*`, `secrets.env`, `*.pem`, `*.key`, `*.p12`, `cookies*`, `token*`
  - 内容 pattern: `sk-[A-Za-z0-9]`, `-----BEGIN PRIVATE KEY-----`, `AWS_SECRET_ACCESS_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`
- MCP export 移除 credential reference，并转换为 requirement。
- runtime log·SSE event·tool result·toast 对 mapped env var 值进行 redact。
- 当前 `packager.py` 没有 secret scan，因此新增 module，并在 publish/import 双向调用。

### Access Control

- private item 仅 owner 可访问。
- restricted item 仅 owner 和 ACL 对象可访问。
- public/system item 所有登录用户均可访问(搜索可见性取决于 `is_listed`)。
- 只有 super_user 可 manage system item。
- installed resource 归安装者所有，原作者不能直接修改。
- runtime 只在 mount root 暴露 agent 所选择的 skill。
- 未授权访问返回 404(防止 enumeration oracle)。

### Mutability

- Marketplace item metadata 可由 owner 修改。
- Marketplace version payload immutable。
- Installed resource 用户可自由修改 (但会标记为 `is_dirty=True`)。
- Source version update 只能通过用户明确操作应用。

## 13. 成功指标

- built-in k-skill 中至少 10 个可从 catalog 安装
- 安装 credential required skill 时 100% 检测缺失 credential
- public/restricted/private access control 测试通过
- marketplace install 后可在现有 agent 设置中选择 skill
- shared skill publish/install E2E 成功
- credential value 不暴露在 marketplace payload/API 响应中
- agent runtime 无法访问未选择 skill 的文件/目录
- `execute_in_skill` subprocess env 中会注入 mapped env var 值，但在 log·SSE·tool result 中会 redact

### Phase 1 发布 gate

Phase 1 只有满足以下全部条件后才向用户开放。

| Gate | 通过条件 |
|------|-----------|
| Access control | 针对 private/restricted/public/system item 的 owner, ACL user, unrelated user 测试通过。未授权访问为 404 |
| Secret safety | publish/import payload, API 响应, log·SSE·tool result 中不暴露 credential value。`secret_scan.py` 阻止 `.env`/PEM/sk- pattern 等 |
| Runtime isolation | per-thread runtime root 只暴露 agent 选择的 skill。不可访问未选择 skill 目录·其他用户 skill。`execute_in_skill` 仅允许 runtime root 下路径 |
| Credential runtime | 缺少 required binding 时阻止执行(`marketplace_credential_required` error)，存在 binding 时只注入 mapped env var。log·SSE·tool result 中以 redact 后形式暴露 |
| k-skill sync | dry-run 结果和实际 sync 结果准确报告变更的 skill/version。相同 commit 再执行不创建新 version。单个 skill 失败不终止整个 sync |
| Backward compatibility | 现有 skill upload/edit/delete, agent skill 连接, `/api/skills` 响应通过回归测试。添加 `is_dirty` 不破坏现有编辑 UX |
| Listing 批准 | public item 在 toggle 为 `is_listed=True` 前不出现在 catalog 默认搜索中。super_user toggle 正常工作 |
| ADR-016 一致性 | 所有新 router 都有 `get_current_user` 或 `require_super_user` dependency。状态变更进行 CSRF 验证 |

### 可用性成功标准

- 用户能在 3 分钟内安装无需 credential 的 built-in skill 并连接到 agent。
- 安装 credential required skill 期间，不会混淆所需 credential type 和 field。
- 收到 restricted 共享的用户无需额外说明即可在 Marketplace 发现并安装 item。
- 在 update available 状态下，仅通过 UI 文案就能理解 overwrite 与 install new copy 的区别。
- super_user 可在一个页面查看未批准 public item 列表并批准/拒绝 listing。

## 14. 分阶段发布

### Phase 1: Skill Marketplace Foundation

- Marketplace item/version/install schema (Alembic migration)
- 扩展 `skills` 表 column (origin, source_marketplace_*, is_dirty, credential_requirements 等)
- 添加 `AgentSkillLink.config` 字段
- `skill_credential_bindings` 表
- 添加新的 credential definitions(`srt_account`, `ktx_account`, `kipris_plus_api` 等)
- `secret_scan.py` module
- Skill publish/install/update API
- Visibility + ACL + `is_listed`
- Credential requirements + binding API
- Built-in k-skill sync CLI + system item
- **Runtime selected-skill mount fix** (`executor.py` + `_create_skill_execute_tool`)
- **Runtime credential env injection** + redaction contract
- Marketplace Skills UI + install/publish wizard
- super_user listing 批准/disable 工具

Phase 1 排除:

- MCP/Agent marketplace 实际安装
- 支付, review, ranking
- 自动 update/merge
- 完整 script sandbox (维持当前 allowlist + 30 秒 timeout)
- 组织/团队 ACL
- subprocess runner 以外的新 runner (Node/curl 等)

### Phase 2: MCP Marketplace

- MCP server template publish/install
- MCP credential requirements (将 env_vars/headers 的 `{{$credentials.x}}` interpolation 位置转换为 marketplace requirement)
- MCP discovery result snapshot
- MCP import/export secret stripping
- 协调现有 `mcp_servers.is_system`(M26) 与 marketplace system item

### Phase 3: Agent Marketplace

- Agent spec publish/install
- Required tools/MCP/skills dependency graph
- Bundle install wizard
- Model/credential rebinding (重新解释 ADR-013 优先级)

### Phase 4: Curation and Governance

- moderation status (扩展当前 `is_listed`)
- deprecate/disable versions
- usage analytics
- user-facing update notes
- category curation (运营方推荐 collection)

## 15. Open Questions 与推荐答案

1. **public publish 是否对所有用户开放，还是需要 super_user approval?**
   → 分离 published vs listed。任何人都可以 publish，但只有 super_user 可以 toggle `is_listed=True`。已反映在本 PRD §7, §11.2, §11.7。

2. **撤回 restricted item 访问权限时，已安装 copy 是保留还是删除·禁用?**
   → 保留。撤回只阻止新安装。后续可将 revoke propagation 作为可选项添加。

3. **使用 system credential 的 hosted proxy skill 对普通用户如何限制成本?**
   → 设置单独 rate limit 并显示 system dependency。具体数值在获得运营数据后决定。

4. **Skill script execution 是否保持 Python-only，还是添加 Node/curl runner?**
   → Python subprocess runner(`execute_in_skill`) 已在运行。Phase 1 在其上添加 credential 注入和 selected-skill mount。Node/curl runner 拆分为单独 ADR。

5. **k-skill 全部 80 个是否全部显示在 catalog，还是先公开 supported subset?**
   → 全量显示 catalog，但通过 execution support level 明确预期。super_user 优先将 first-wave(Python ready / hosted proxy / required credential with clear schema)批准为 `is_listed=True`，其余保持 unlisted。

## 16. 参考资料

- 原 PRD: `/Users/chester/dev/natural-mold/docs/maketplace/marketplace-resources-prd.md` v0.3
- 原 Spec: `/Users/chester/dev/natural-mold/docs/maketplace/marketplace-resources-spec.md` v0.3 (后续编写自有 spec 时作为 base)
- ADR-007: Credentials field_keys Cache
- ADR-009: Greenfield Credentials (Cipher V2, multi-key rotation)
- ADR-013: Service-side LLM Key from Credentials
- ADR-016: Multi-user Auth
- 现有代码 module:
  - `backend/app/agent_runtime/executor.py` (尤其 `_create_skill_execute_tool` line 113-195, `build_agent` line 198+)
  - `backend/app/skills/` (service, packager, inspector, runtime, prompt)
  - `backend/app/mcp/` (client, discovery)
  - `backend/app/credentials/` (definitions, interpolation, external_secrets)
  - `backend/app/security/cipher.py`
  - `backend/app/auth/`, `backend/app/dependencies.py`
- k-skill upstream: `https://github.com/NomaDamas/k-skill`
- UI pattern 参考: Cal.com App Store, Dify Marketplace, Open VSX Registry, shadcn/ui

---

## 后续工作 (超出本 PRD 范围)

本 PRD 达成共识后，在单独 session 编写以下产物。

- `docs/marketplace-resources-spec.md`: 准确 SQL schema, Alembic migration 顺序(`m40` 之后), API endpoint signature, Pydantic model, `_create_skill_execute_tool` patch 细节, per-thread runtime root 结构, `secret_scan.py` pattern, k-skill importer module 结构, 新 credential definition Python module
- ADR: Skill runtime mount/credential injection 变更 (security 影响较大，因此单独 PR/review)。关联 ADR-001/003/012
- migration 工作: 添加 `skills` column + 添加 `agent_skills.config` + 4 个新 marketplace_* 表 (item / version / installation / acl) + `marketplace_publication_links` + `skill_credential_bindings`
