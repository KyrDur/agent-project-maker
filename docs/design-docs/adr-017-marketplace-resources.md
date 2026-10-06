# ADR-017 — Marketplace Resources（Skill / MCP / Agent 共享层，Phase 1: Skill）

## 1. Status & Date

- **Status**: Proposed
- **Date**: 2026-05-18
- **Owner**: Pichai（Sundar Pichai, TTH Architect）
- **Source documents**:
  - `docs/marketplace-resources-prd.md` v0.2
  - `docs/marketplace-resources-spec.md` v0.1
- **Branch**: `worktree-marketplace-resources`
- **Relates / Depends on**:
  - ADR-007（`credentials.field_keys` cache）— 复用规避 N+1 的模式
  - ADR-009（Credential 绿地方案）— 复用 Cipher V2 + `is_system` + CHECK constraint 模式
  - ADR-013（Service-side LLM Key）— 复用每用户 credential 优先级策略
  - ADR-016（多用户认证）— `get_current_user` / `require_super_user` / `verify_csrf` dependency，system credential 隔离策略
- **Supersedes**: 无

---

## 2. Context

### 2.1 为什么需要 Marketplace（PRD §1~2 摘要）

natural-mold 已通过 ADR-016 应用多用户认证，Agent / MCP server / Skill / Credential / Tool 均作为用户所有资源隔离。下一阶段需要的是**用户之间的共享 layer**和**operator 提供的 built-in catalog**。

尤其是 `NomaDamas/k-skill` 仓库，它是一组面向韩国业务/生活自动化的 skill，很适合作为 natural-mold 的 built-in catalog，但必须在不 hard fork 的情况下，把特定 upstream commit snapshot 作为 catalog version 引入。

### 2.2 当前代码状态中识别出的缺口（PRD §2）

PRD v0.2 废弃了 v0.1 的错误假设（“需要引入新的 subprocess runner”），并通过深入代码分析确认了以下内容。

| # | 缺口 | 代码位置 |
|---|--------|-----------|
| G1 | Skill 无法与其他用户共享 — `Skill.user_id` NOT NULL + service 强制按 `user_id` 过滤 | `models/skill.py`, `skills/service.py` |
| G2 | 缺少通用 marketplace 模型（item/version/installation/acl/publication） | `models/` |
| G3 | Skill 缺少 marketplace 追踪列（`source_*`, `origin_*`, `is_dirty`） | `models/skill.py` |
| G4 | `AgentSkillLink` 没有 override 槽位（缺少 `config` 列） | `models/skill.py` |
| G5 | Broad skill mount — agent 只要有一个 skill，就会暴露完整 `skills=["/skills/"]` | `agent_runtime/executor.py:544-571` |
| G6 | `execute_in_skill` env 未注入 credential（只有 PATH/PYTHONPATH/HOME/SKILL_OUTPUT_DIR/OUTPUTS_DIR） | `agent_runtime/executor.py:113-195` |
| G7 | `packager.py` 缺少 secret scan（只检查 symlink/zip-slip/null-byte/50MB） | `skills/packager.py` |
| G8 | 缺少 k-skill 所需的 credential definition（现有 13 个中缺少 8 个韩国型 definition） | `credentials/definitions/` |
| G9 | log/SSE/tool result 中未对 mapped env 值应用 redact | `streaming.py`, `executor.py` |

已具备的基础设施（复用对象）：deepagents + `execute_in_skill` subprocess runner、FilesystemBackend、Cipher V2、field_keys cache、13 个 credential definition、`require_super_user`/`verify_csrf`、ENV→system credential bootstrap。

### 2.3 Phase 1 范围（PRD §14, Spec §0）

Phase 1 **仅限 Skill marketplace**。MCP/Agent marketplace 在 Phase 2/3 以相同模型扩展（Phase 1 先准备表/schema，install/publish flow 暂不实现）。

```
m40~m43 数据模型
  → Slice A: Read Catalog（列表/详情 API、访问矩阵）
  → Slice B: Install（用户所有的 skill copy + binding）
  → Slice C: Publish + Secret Scan (immutable version + ACL)
  → Slice D: Credential Definitions + Binding API
  → Slice E: Runtime selected-skill mount + credential env injection + redaction（**安全 critical**）
  → Slice F: k-skill importer（仅 super_user CLI）
  → Slice G: Marketplace UI (Frontend)
```

---

## 3. Decision

### 3.1 7 个核心决策（PRD Decision Summary + Spec §0.1）

| # | 项目 | 选择 | 依据 |
|---|------|------|------|
| D-01 | **Marketplace 资源范围** | Agent / MCP / Skill（Tool 非目标） | Tool 是 `tools/registry.py` 中由 operator 通过代码定义的内存 `ToolDefinition` 资产 — 用户不会创建或共享 |
| D-02 | **Phase 拆分** | Phase 1 = Skill, Phase 2 = MCP, Phase 3 = Agent | Skill 闭环最完整且即时价值最大。数据模型从一开始就容纳三种资源 |
| D-03 | **Skill runtime baseline** | 在现有 deepagents + `execute_in_skill` subprocess runner 上只补齐三个缺口：(a) selected-skill mount，(b) credential env injection，(c) redaction | 不引入新 runner。废弃 v0.1 假设 |
| D-04 | **Alembic 拆分** | 按 slice 拆成 m40~m43（拒绝单一大型迁移） | rollback/review 单位更小。m40 catalog tables, m41 skills 列, m42 agent_skills.config, m43 skill_credential_bindings |
| D-05 | **Agent-Skill credential override** | Option A — `agent_skills.config` JSON 字段 | 与当前 link model 对齐。避免大规模规范化迁移。`scope='agent_skill'` row 保留到未来规范化时使用 |
| D-06 | **Runtime mount 隔离** | Option A — per-thread `copytree`，只把选中的 skill 复制到 `data/runtime/<thread_id>/skills/<slug>/` | symlink 有写入风险。broad `/skills/` 会泄露同一用户未选择的 skill。thread_id 与 LangGraph checkpoint key 相同，兼容 SSE resume（ADR-011） |
| D-07 | **引入 k-skill 的方式** | clone GitHub `NomaDamas/k-skill` → 通过 super_user CLI（`uv run python -m app.scripts.sync_k_skill`）把特定 commit snapshot 注册为 system marketplace item。拒绝 git submodule | 不修改 upstream 代码。仅 CLI — 不在 web UI 暴露 |
| D-08 | **Public publish 策略** | 分离 published 与 listed。初始 `is_listed=False`，仅 super_user 可切换 | 任何人都能 publish，但 catalog 暴露由 operator gate。`is_listed=False` 的 public item 与 unlisted 效果相同（可通过直接 ID/slug 访问） |
| D-09 | **未授权访问响应** | 所有未授权 detail/install 统一返回 404（`marketplace_install_forbidden` 等） | 防止 enumeration oracle — 不暴露 private/restricted 是否存在 |
| D-10 | **Credential 处理** | 继续复用中央 `credentials` 表 + Cipher V2 + field_keys cache + `is_system` 隔离。为 k-skill 新增 8 个 definition | 复用 ADR-007/009 基础设施。只新增 binding/requirement 模型（`skill_credential_bindings`） |
| D-11 | **Visibility 模型** | `private / restricted / public / unlisted / system` | 保留原始决策 |
| D-12 | **Installed resource ownership** | marketplace access 不直接授予资源 access。安装始终创建 `current_user` 所有的 row | 保持现有 ownership check。system item 不直接连接 agent |
| D-13 | **Version immutability** | `marketplace_versions.payload/storage_path/content_hash` 在 publish 后不可修改。metadata typo 只改 item-level metadata | 简化 update 比较/audit |
| D-14 | **缺少 Required credential 时安装** | 允许 `install_missing_credentials='needs_setup'`。Runtime 中 fail-fast（`marketplace_credential_required` 409） | 用户可先从 catalog 获取资源，再稍后连接 credential |

> 备注：D-01~D-14 是完整决策表。PRD/Spec 中“7 个核心决策”的摘要指 **D-01~D-07**，D-08~D-14 是这些决策直接派生的政策细节。

### 3.2 数据模型摘要（Spec §3）

新增 6 个 domain entity（5 个 marketplace 表 + 1 个 credential binding 表）+ 扩展 skills/agent_skills 列。

| Entity | 表 | 迁移 | 作用 |
|--------|--------|--------------|------|
| MarketplaceItem | `marketplace_items` | m40 | 可共享的 logical item（resource_type + owner + visibility + is_listed + latest_version） |
| MarketplaceItemACL | `marketplace_item_acl` | m40 | restricted visibility 的 user 级 ACL（view/install/manage） |
| MarketplaceVersion | `marketplace_versions` | m40 | immutable snapshot (payload + content_hash + credential_requirements + execution_profile) |
| MarketplaceInstallation | `marketplace_installations` | m40 | 安装记录（user → item → version → installed_skill_id） |
| MarketplacePublicationLink | `marketplace_publication_links` | m40 | 我的资源 ↔ 我 publish 的 item 反向引用（按 resource_type UNIQUE） |
| Skill（扩展） | `skills` ALTER | m41 | 新增 12 列：is_system, source_kind, source_marketplace_item_id, source_marketplace_version_id, source_commit, credential_requirements, execution_profile, origin_kind, origin_user_id, origin_marketplace_item_id, origin_marketplace_version_id, is_dirty |
| AgentSkillLink（扩展） | `agent_skills` ALTER | m42 | 新增 `config JSON` 列（agent-skill credential override） |
| SkillCredentialBinding | `skill_credential_bindings` | m43 | (skill_id, user_id, requirement_key, credential_id) — Phase 1 仅 `scope='skill'` |

Circular FK 处理（m40 内）：`marketplace_items.latest_version_id` → `marketplace_versions.id` 在 items/versions 都创建后通过 `ALTER TABLE ... ADD CONSTRAINT` 添加。

详细列/CHECK constraint/INDEX 参见 Spec §3.2~§3.10。

### 3.3 模块边界摘要（Spec §11）

新增目录：`backend/app/marketplace/`

```
marketplace/
├── __init__.py
├── access.py                # can_view_item / can_install_item / can_manage_item (Slice A)
├── schemas.py               # Pydantic 模型（Spec §10.8）
├── service.py               # catalog list/detail (Slice A)
├── install_service.py       # install/update flow (Slice B)
├── publish_service.py       # publish flow (Slice C)
├── origin_service.py        # 派生 origin/publication summary + mark_installation_dirty
├── secret_scan.py           # SECRET_FILE_PATTERNS + SECRET_CONTENT_PATTERNS (Slice C/F)
├── redaction.py             # redact_credential_values / redact_keys (Slice E)
├── credential_requirements.py  # mapping / validation / env injection plan (Slice D/E)
└── k_skill_importer.py      # upstream sync 调用部分（Slice F）

backend/app/scripts/sync_k_skill.py    # super_user CLI 入口
backend/app/routers/marketplace.py     # 新增 router
backend/app/models/marketplace.py      # 单文件包含 5 个表 ORM
```

### 3.4 安全决策（Spec §13, PRD §12）

- **Secret scan**：`secret_scan.py` 在 publish + import + `routers/skills.py:upload` 三处调用（回归 guard）。`packager.py` 本身不改，由调用方 wrap。
- **Credential safety**：API 响应绝不暴露 decrypted value。Runtime env injection 只写入 mapped env var（例如 `KSKILL_SRT_ID`），不注入其他 env。
- **Redaction**：用 `redact_credential_values` 把 mapped env value 替换为 `<redacted:ENV_NAME>`。用 `redact_keys` 把匹配 `password|api_key|secret|token|access_key|refresh_token` 模式的 key 值替换为 `<redacted>`。调用位置：`_create_skill_execute_tool` 返回值、`streaming.py` tool_call_result payload、exception detail、raw log statement 全部。
- **System credential 隔离**：`/api/system-credentials` 继续仅限 super_user。不在 marketplace 暴露。Hosted proxy 标记为 system dependency。
- **Enumeration oracle**：未授权 detail/install 全部 404（CLAUDE.md 原则）。

### 3.5 Runtime 修改摘要（Spec §8, §9）

`executor.py` 的两个修改点：

1. **进入 `build_agent` 时**：准备 per-thread runtime root
   ```text
   data/runtime/<thread_id>/skills/<slug>/  ← copytree(skill.storage_path, ..., symlinks=False)
   skills_sources = [f"/runtime/{thread_id}/skills/"]
   ```
2. **`_create_skill_execute_tool` 签名**：扩展为 `(output_dir, thread_id, skill_descriptors)`。函数内部：
   - 验证 slug → descriptor 映射（不存在则返回 `"Error: skill not attached to this agent"`）
   - 用 `is_relative_to` 验证 descriptor.storage_path 位于 runtime_root 下
   - 遍历 descriptor.credential_bindings 并注入 `env[env_name] = decrypted[field]`
   - subprocess 执行结果/exception 使用 `redact_credential_values` 遮罩

`build_skills_for_agent`（`skills/runtime.py`）扩展为返回 `SkillRuntimeDescriptor` 列表（id, slug, original_storage_path, storage_path, credential_bindings: dict[str, ResolvedCredential]）。

`ResolvedCredential` 是 in-memory only 数据类 — 禁止 JSON 序列化/日志输出。

### 3.6 Cleanup 策略

- Conversation 结束时 best-effort 删除 `data/runtime/<thread_id>/`。
- 服务器启动时在 lifespan 中 GC 超过 1 小时的 runtime root。
- 强制终止/crash 残留由 retention job 清理。

---

## 4. Rejected Alternatives (Spec §0.2)

| 拒绝方案 | 拒绝理由 |
|--------|-----------|
| 仅在现有 `skills` 增加 `is_builtin`, `visibility` | version/update/install 历史变模糊，user-owned 与 catalog 混在一起 |
| Marketplace item 直接在 runtime 执行（不安装） | upstream/owner 变更会立即影响用户执行。credential binding 变复杂 |
| 直接以 git submodule 引用 k-skill | runtime 与 upstream layout 强耦合。缺少 immutable snapshot |
| 引入新的 skill runner（非 subprocess） | 已有 `execute_in_skill` subprocess runner 正常工作。只需在其上补安全缺口 |
| 基于 symlink 的 mount | 写入可能流回原始资源。同一用户的其他 skill 也可能被 LLM 通过 `read_file` 读取 |
| 单一大型 m40 迁移 | rollback/review 负担大。按 slice 拆分迁移更安全 |
| 包含 Tool marketplace | Tool 是 operator 通过代码定义的资产（`tools/registry.py`），用户不会创建或共享。如果未来需要单独 PRD 再重新评估 |
| localStorage + Bearer token / 基于 Redis 的 refresh | ADR-016 已决定 HttpOnly Cookie + DB whitelist。Marketplace 构建在此之上 |

---

## 5. Consequences

### 5.1 Positive

- 通过**单一 catalog 模型**可用相同模式扩展 Skill/MCP/Agent 三种资源。Phase 2/3 无需重新设计 schema。
- 通过 **Immutable version + content_hash** 简化安装 audit 与 update 比较。dirty 追踪也更清晰。
- 通过 **per-thread mount** 隔离同一用户未选择的 skill。这是 Phase 1 最大的安全改进。
- 通过 **Credential env injection**，不再有把 secret 写进 SKILL.md 正文的动机。结合 secret_scan，从 publish 环节双向阻断 secret leak。
- 通过 **`is_listed` gate**，任何人都能 publish，但仅由 operator 控制 catalog 暴露。把 moderation 负担维持在一定水平。
- **k-skill 仅 CLI**，除 super_user 外无法触发 sync。把 upstream layout 变更的爆炸半径限制在 operator。
- **与 ADR-016 不冲突**：原样复用 `get_current_user` / `require_super_user` / `verify_csrf` / system credential 隔离策略。

### 5.2 Negative / Trade-offs

- **per-thread copytree 成本**：含大型 package skill（~50MB 限制）的每个 conversation 都会产生磁盘 I/O 与 retention job 负担。→ mitigation：GC 超过 1 小时的 stale 数据 + conversation 结束时立即 cleanup。
- **`agent_skills.config` JSON**：与规范化 `skill_credential_bindings` 重叠的 override 槽位。保留预留列，Phase 2 可用 `scope='agent_skill'` 规范化。当前 JSON 路径更快。
- **Circular FK（items↔versions）**：在 m40 内通过 ALTER 处理。rollback 时需按逆序 drop。
- **`is_listed=False` public item 的处理**：与 unlisted 效果相同（可通过直接 link install），用户可能会混淆两种状态。→ mitigation：publication badge 使用 `Published · Public · Unlisted (pending listing)` 等区分文本。
- **k-skill upstream layout 变更风险**：必须 mirror validate-skills.sh exclusion；frontmatter schema 变化时 sync 会失败。→ mitigation：单个 skill validation 失败不会中断整个 sync。结果报告包含失败列表。
- **Secret scan false positive**：包含合法 PEM-like 内容的 skill 会被阻止 publish。→ mitigation：向用户返回明确的 finding path/pattern + 提供运营指南。
- **缺少 `is_dirty` 追踪的代价**：如果 skill content 修改的 4 个 endpoint（`PUT /content`, `PATCH /skill`, files `PUT|POST|DELETE`）遗漏调用 `mark_installation_dirty`，就会导致 update 冲突检测失败。→ mitigation：把 `origin_service.mark_installation_dirty` 设为单一入口，并在 4 个 endpoint 全部 best-effort 调用。

### 5.3 对其他 ADR 的影响

| ADR | 关系 | 影响 |
|-----|------|------|
| ADR-001 (Deep Agent 引擎) | depends-on | 保持 `create_deep_agent` 的 `skills=[...]`/`backend=FilesystemBackend(virtual_mode=True)` 接口。仅把 mount root 改为 per-thread — 引擎本身不变 |
| ADR-003 (Skills + Memory) | extends | 现有 `build_skills_for_agent` 只返回 `to_runtime_dict()` 列表。本 ADR 扩展为 `SkillRuntimeDescriptor`（包含 credential_bindings + per-thread storage_path）。prompt.py 无需修改 |
| ADR-007 (`field_keys` cache) | reuses | 新增 8 个 credential definition 也按相同方式自动填充 `field_keys`。无改动 |
| ADR-009 (Credential 绿地方案) | reuses | 将 Cipher V2 + `is_system` + CHECK constraint 模式也应用于 marketplace domain（`marketplace_items.is_system`, `marketplace_publication_links` 等） |
| ADR-011 (SSE Stream Resume) | compatible | `thread_id` 与 LangGraph checkpoint key 相同，因此 resume 时复用同一 runtime root |
| ADR-012 (HiTL Middleware) | neutral | marketplace 与 HiTL 流程正交。install/publish 为同步 REST |
| ADR-013 (Service-side LLM Key) | reuses | 沿用 user credential 优先级策略（用户密钥 → system 密钥）。marketplace skill credential 也只能绑定用户 owned credential |
| ADR-016 (多用户认证) | depends-on | 原样复用 `get_current_user` / `require_super_user` / `verify_csrf` / system credential 隔离 / `is_super_user` 单一标志。所有 marketplace mutation 均受 CSRF 保护 |

### 5.4 后续 ADR 预告

- **Phase 2 MCP marketplace**：`marketplace_items.resource_type='mcp'`, `marketplace_versions.payload_kind='mcp_template'` 的实际 install flow。本 ADR 已准备 schema。
- **Phase 3 Agent marketplace**：`payload_kind='agent_spec'` install flow + skill/MCP 引用 resolution。
- **Phase 4 Curation/Moderation**：评分/评论/排名/搜索算法。不在当前 ADR 范围内。
- **Workspace 扩展（ADR-016 §7 后续）**：当 `user_id` → `TenantContext` 修改签名时，marketplace ownership 列也按相同方式迁移。本 ADR 假设 user 级 ownership。

---

## 6. References

- **源文档**：`docs/marketplace-resources-prd.md` v0.2, `docs/marketplace-resources-spec.md` v0.1
- **相关 ADR**：
  - [ADR-007 — Credentials field_keys cache 列](adr-007-credentials-field-keys-cache.md)
  - [ADR-009 — Credential / Tools / Skills 绿地重写](adr-009-greenfield-credentials.md)
  - [ADR-013 — Service-side LLM Key from Credentials](adr-013-service-llm-key-from-credentials.md)
  - [ADR-016 — 多用户认证](adr-016-multiuser-auth.md)
- **外部参考**（仅借鉴 UI/结构，禁止复制代码/UI）：
  - Cal.com App Store — 显示 install 状态，app package 结构
  - Dify Marketplace — 按 resource type 浏览 + 区分安装 source
  - Open VSX Registry — versioned extension registry，web UI 与 publish CLI 分离
  - `NomaDamas/k-skill` GitHub — Phase 1 built-in catalog 来源
- **模块契约辅助文档**：`docs/design-docs/marketplace-module-contracts.md`（M1-S2 产物）
