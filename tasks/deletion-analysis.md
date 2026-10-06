# Deletion Analysis — Marketplace Resources Phase 1

> Author: 贝索斯 (Bezos / QA)
> Date: 2026-05-18
> Story: M1-S1
> Source: PRD v0.2 §2/§11.5b/§13, Spec v0.1 §1/§3/§4
> 验证标准：所有文件/行号引用都以 worktree HEAD（`worktree-marketplace-resources`）为基准，通过 grep 或直接 Read 确认。

> **参考**：上一会话（Greenfield Credentials, ADR-009）的 deletion-analysis 保存在 `tasks/deletion-analysis-multiuser-auth.md`、`tasks/archive-multiuser-auth-2026-05/`。本文件覆盖为 Marketplace Phase 1 专用。

---

## 0. 一句话摘要

> 市场 不是"新功能"，而是**填补已经运行中的 skill runtime 的 6 个空缺**。几乎没有要删的代码，需要补的空缺正好有 6 处。

核心结论：
- (a) `executor.py:548` broad mount `["/skills/"]` **必须**替换为 per-thread root。当前存在可访问同一用户未选中 skill 的数据隔离违规。
- (b) `executor.py:144-150` env dict **未注入 credential**。目前 srt/ktx 等 credential-required skill 处于无法执行状态（不是 silent skip，而是尚未设计）。
- (c) `packager.py` 只检查 zip-slip/symlink/null/50MB。**缺少 secret scan** — 必须在 publish/import 两侧拦截 `.env`、`*.pem`、`sk-…` 模式。
- (d) `Skill` ORM 中 marketplace 跟踪列为 0 个（m41 新增 12 个）。
- (e) `AgentSkillLink` 中 `config` 列为 0 个（m42 新增）。完全没有存储 agent-skill 级 credential override 的位置。
- (f) `credentials/definitions/` 中缺少 k-skill 用的 8 个 定义。

**Musk Step 2（删除）**：grep 结果显示真正的 dead code **没有**。legacy 一词仅用于注释/文档中的 historical context。参见后文 §2。

---

## 1. 市场 需要填补的空缺（Gap Inventory）

各项只记录通过 file_path:line_number 和 grep 验证过的事实。

### (a) Broad `/skills/` mount — 数据隔离违规 🔴 High

| | |
|---|---|
| 位置 | `backend/app/agent_runtime/executor.py:544-548` |
| 切片 映射 | **E**（Runtime selected-skill mount） |
| 验证 | `grep -n "/skills/\|FilesystemBackend\|_DATA_DIR" backend/app/agent_runtime/executor.py` |
| 回归风险 | 🔴 High — 实现错误时可能造成 conversation cross-leak、FilesystemBackend 缓存 失效 |

已确认的代码：
```python
# executor.py:544
backend = FilesystemBackend(root_dir=str(_DATA_DIR), virtual_mode=True)
# executor.py:546-548
skills_sources: list[str] | None = None
if cfg.agent_skills:
    skills_sources = ["/skills/"]
```

问题：
- `_DATA_DIR` = `backend/data/`。所有 `data/skills/<skill_id>/` 都集中在 backend root 下。
- 用 `["/skills/"]` mount 后，deep-agents Filesystem backend 会把整个 `_DATA_DIR/skills/` 暴露给 LLM 作为 `read_file` 对象。
- LLM 不仅能读取 attach 到 agent 的 skill_id，**还可以读取同一用户的其他 skill** 目录，例如 `read_file("/skills/<other-id>/SKILL.md")`。
- `_create_skill_execute_tool` 也使用同一个 broad root（line 126）：`(_DATA_DIR / skill_directory.strip("/")).resolve()` — 验证只阻止 `_DATA_DIR` 外部路径，其他 skill_id 的目录仍被允许。

验证方法（Slice E 完成时）：
- 当两个用户 A/B 共用同一个 server-side data 文件夹时，A 的 agent 应无法通过 read_file 读取 B 的 skill 目录 → `test_runtime_isolation.py::test_other_user_skill_unreachable`
- A 自己有两个 skill（S1, S2），在只 attach S1 的 agent 中执行 `read_file("/skills/<S2>/SKILL.md")` → "Error: invalid skill directory"或 not-found
- `execute_in_skill(skill_directory="/skills/<S2>/")` → "Error: invalid skill directory"

### (b) `_create_skill_execute_tool` env 未注入 credential 🔴 High

| | |
|---|---|
| 位置 | `backend/app/agent_runtime/executor.py:113-195`（尤其 line 144-150） |
| 切片 映射 | **E**（Credential env injection） |
| 验证 | 直接 Read 确认 |
| 回归风险 | 🔴 High — 必须与 redaction 配套，避免 credential plaintext 泄漏到 log/SSE/tool result/exception detail |

已确认的代码：
```python
# executor.py:144-150
env = {
    "PATH": "/usr/bin:/usr/local/bin",
    "PYTHONPATH": str(resolved),
    "HOME": str(resolved),
    "SKILL_OUTPUT_DIR": out,
    "OUTPUTS_DIR": out,
}
```

问题：
- subprocess env 中未注入 user credential 的 mapped env var（例如 `KSKILL_SRT_ID`、`KSKILL_SRT_PASSWORD`）。
- 因此 srt-booking/ktx-booking/kipris-search 等 credential-required skill 即使遵循 SKILL.md instruction，执行时也会因缺少环境变量而返回 401/None。
- `_create_skill_execute_tool` 签名只接收 `(output_dir: Path, thread_id: str)` — 没有传入 credential bundle 的通道。
- 调用处只有一个：`executor.py:551 langchain_tools.append(_create_skill_execute_tool(conv_output_dir, cfg.thread_id))`。扩展签名时只需 补丁 这一处。

验证方法：
- `test_credential_injection.py::test_required_credential_injected_to_subprocess_env`：已 binding 的 credential 对应 mapped env var 值存在于 subprocess env
- `test_credential_injection.py::test_unmapped_env_var_not_injected`：其他 skill 的 mapped var 不会暴露
- `test_credential_injection.py::test_missing_required_credential_fails_fast`：needs_setup 状态下执行时返回 `marketplace_credential_required` 错误（Spec §10.7 错误码）
- `test_redaction.py::test_log_redacts_mapped_env_value`：log/SSE/tool result/exception detail 中不暴露 plaintext

### (c) `packager.py` 缺少 secret scan 🔴 High

| | |
|---|---|
| 位置 | `backend/app/skills/packager.py`（共 175 lines） |
| 切片 映射 | **C**（Publish + secret scan）+ **B**（import 时的回归 防护） |
| 验证 | `grep -n "env\|pem\|sk-\|BEGIN PRIVATE\|secret_scan" backend/app/skills/packager.py` → 0 hits |
| 回归风险 | 🟡 Medium — 会改变既有 upload 行为。若正常 skill 触发 false-positive 会阻断用户 |

已确认事实：
- `_validate_member` 只检查 symlink、absolute path、null byte、path traversal（line 65-78）。
- `extract_package` 检查 50MB 限制（line 89-93）。
- 对 `.env`、`.env.local`、`*.pem`、`*.key`、`*.p12`、`cookies*`、`token*` 等 secret-like filename **没有检查**。
- 对 `sk-[A-Za-z0-9]`、`-----BEGIN PRIVATE KEY-----`、`AWS_SECRET_ACCESS_KEY`、`GOOGLE_APPLICATION_CREDENTIALS` 等内容模式 **没有检查**。

问题：
- 用户制作 `.skill` package 时若误把 `.env` 包进去 → 原样 marketplace publish → 其他用户 install → credential 泄漏。
- 目前 packager.py 本身没有检查，调用方（`routers/skills.py:64 upload_package_skill`）也没有 secret scan。

验证方法：
- `test_secret_scan.py::test_dotenv_in_package_rejected`：包含 `.env` 的 publish → `marketplace_secret_detected` 400（Spec §10.7）
- `test_secret_scan.py::test_pem_in_package_rejected`
- `test_secret_scan.py::test_sk_pattern_in_skill_md_rejected`
- `test_secret_scan.py::test_aws_secret_access_key_in_script_rejected`
- 回归 防护：`test_upload_existing_package_still_succeeds`：引入 secret_scan 后，既有正常 .skill 上传 仍返回 200

### (d) `Skill` 模型缺少 marketplace 跟踪列 🟡 Medium

| | |
|---|---|
| 位置 | `backend/app/models/skill.py:43-101` |
| 切片 映射 | **A**（m41） |
| 验证 | `grep -n "is_dirty\|origin_kind\|source_marketplace" backend/app/models/skill.py` → 0 hits |
| 回归风险 | 🟡 Medium — 新增 12 列后即便不改 SkillResponse / to_runtime_dict 也应继续工作，但 list API 响应体会变大 |

缺失列（PRD §6 + Spec §3.1 m41）：
1. `is_system` BOOLEAN
2. `source_kind` VARCHAR(40)
3. `source_marketplace_item_id` UUID FK
4. `source_marketplace_version_id` UUID FK
5. `source_commit` VARCHAR(80)
6. `credential_requirements` JSON
7. `execution_profile` JSON
8. `origin_kind` VARCHAR(40) DEFAULT 'created_by_me'
9. `origin_user_id` UUID FK users
10. `origin_marketplace_item_id` UUID FK
11. `origin_marketplace_version_id` UUID FK
12. `is_dirty` BOOLEAN DEFAULT FALSE

受影响调用处（必须做回归验证）：
- `app/skills/service.py:389 to_runtime_dict()` — 若不加入新列，deepagents 行为保持不变（兼容）。需要响应 键 unchanged 回归测试。
- `app/schemas/skill.py:50 SkillResponse` — 需要新增 origin_summary/publication_summary 字段（Spec §0.1 D8）。
- `app/services/chat_service.py:523 build_agent_skills()` — 无需变更。
- `app/skills/runtime.py:19 build_skills_for_agent` — 无需变更。
- 当前最新 迁移：m39。m40~m43 名称无冲突。

验证方法：
- `test_marketplace_migration.py::test_upgrade_then_downgrade_m40_m43_reversible`
- `test_marketplace_migration.py::test_existing_skill_rows_backfilled` — backfill 时填充 `origin_kind`/`is_dirty`
- `test_skills_api_unchanged_response.py::test_get_skill_still_returns_legacy_fields` — 既有 SkillResponse 响应回归 防护

### (e) `AgentSkillLink` 缺少 `config` 列 🟡 Medium

| | |
|---|---|
| 位置 | `backend/app/models/skill.py:25-40`（AgentSkillLink 不是独立文件，而是定义在 skill.py 中 — progress.txt L42 正确） |
| 切片 映射 | **A**（m42） |
| 验证 | 直接 Read 确认 — 当前只有 (agent_id, skill_id) composite PK |
| 回归风险 | 🟡 Medium — `write_tools.py:398` 的 `AgentSkillLink(skill_id=s.id)` 调用路径不受影响（作为 nullable JSON 新增） |

已确认事实：
- `AgentSkillLink` 只有 2 个 PK + `skill: Mapped[Skill] = relationship(lazy="joined")`。
- 使用处（grep `AgentSkillLink` --include="*.py"）：
  - `app/models/agent.py:77` — `skill_links: Mapped[list[AgentSkillLink]] = relationship`
  - `app/agent_runtime/assistant/tools/write_tools.py:398` — `agent.skill_links.append(AgentSkillLink(skill_id=s.id))`
  - `app/agent_runtime/assistant/tools/helpers.py:35`, `app/services/chat_service.py:473,511` — selectinload eager load
  - `app/skills/runtime.py:19 build_skills_for_agent` — iterate
- 所有使用处都只引用 `link.skill` 或两个 PK 列。新增 `config` nullable JSON 时既有调用无需变更。

问题（PRD §11.5 Binding Scope）：
- 没有位置可存储 agent-skill 级 credential override。
- 当前设计为 `agent_skills.config = {"credential_bindings": {"<requirement_key>": "<credential_id>"}}`（Spec §0.1 D3）。
- runtime override 优先级：agent-skill override > skill_credential_bindings default。

验证方法：
- `test_agent_skill_config_override.py::test_override_takes_precedence_over_default_binding`
- `test_agent_skill_config_override.py::test_no_override_falls_back_to_default`

### (f) 缺少 k-skill 用 credential definitions 🟡 Medium

| | |
|---|---|
| 位置 | `backend/app/credentials/definitions/` |
| 切片 映射 | **D**（Credential Definitions） |
| 验证 | `ls backend/app/credentials/definitions/` |
| 回归风险 | 🟢 Low — 仅新增，不影响既有 definition |

已确认事实 — 当前文件夹中有 13 个文件（不含 `__init__.py`）：
```
anthropic.py, azure_openai.py, google_genai.py, google_search.py,
google_workspace_oauth2.py, http_api_key.py, http_basic.py,
http_bearer.py, mcp_oauth2.py, naver_search.py, openai.py,
openai_compatible.py, openrouter.py
```

**⚠️ progress.txt 需要更正**：progress.txt L38、L70（PRD）写的是"14 个"，实测为 **13 个**。PRD §6 表 L68 也列出 14 个，因此表面一致 — 但 disk 上实际只有 13 个文件。`（再一个 — 需要确认）` 标记也相同。需要向萨提亚/詹森做最终报告。（Open Item #OI-1）

新增对象（PRD §8）：
1. `srt_account` — username, password (`srt-booking`)
2. `ktx_account` — username, password (`ktx-booking`)
3. `foresttrip_account` — username, password (`foresttrip-vacancy`)
4. `kipris_plus_api` — api_key (`korean-patent-search`)
5. `dart_api` — api_key (`k-dart`)
6. `odsay_api` — api_key (`korean-transit-route`)
7. `coupang_partners` — access_key, secret_key (`coupang-product-search`, **optional**)
8. `k_skill_proxy` — base_url, optional api_key (self-host proxy)

验证方法：
- `test_credential_definitions.py::test_all_k_skill_definitions_registered`：确认 import time 自动注册
- `test_credential_definitions.py::test_field_keys_cache_populated_on_create`（ADR-007 回归）

---

## 2. Musk Step 2 — 可删除项

**结论：没有可立即删除的项目。**

验证方法：全量扫描 grep `dead\|deprecated\|legacy\|TODO\|FIXME\|unused` + 确认调用处。

### 审查结果

| 候选 | 位置 | 判定 | 依据 |
|------|------|------|------|
| executor.py "legacy" 注释 | line 238, 311, 488, 614 | **保留** | 全部是说明 historical context 的注释。代码本身属于活跃路径 |
| `auth_config["headers"]` fallback | `executor.py:236-239` `_auth_config_to_headers` | **保留** | 可能仍有 M26 之前的 legacy MCP server 数据，因此保留 fallback（mcp_transport_headers 是新路径） |
| `skills/runtime.py` "legacy executor" 注释 | line 3 | **保留** | docstring 内的 historical 说明。代码本身属于当前路径 |
| `skills/service.py:3` 提及 "legacy ``content`` text column" | line 3 | **保留** | 说明 m18 greenfield 之后的 historical context |
| `_DATA_DIR` 路径验证（`executor.py:127`） | 与 broad mount 一起 补丁 的对象 | **保留（修改）** | Slice E 中会替换为 per-thread root，但函数本身保留 |
| skill_directory virtual path strip（`executor.py:126`） | 与 broad mount 一起 补丁 的对象 | **保留（修改）** | 同上 |

### 确认引入 市场 后是否可能 obsolete

- 没有独立 fallback 代码。`Skill.user_id` NOT NULL 策略保持不变（system 使用独立 `is_system=True` 标志，owner_user_id NULL 仅适用于 `marketplace_items`）。
- `is_super_user` 权限分支已在 ADR-016 中引入 — marketplace 路由器复用。
- `is_system` 模式：`mcp_servers.is_system`（M26）、`credentials.is_system`（ADR-009）已存在。`skills.is_system` 按同一模式新增。
- 既有 `seed/bootstrap_from_env.py` 是 ENV → system credential。与 marketplace 无关 — 保留。

### Step 3（简化）建议

- `_create_skill_execute_tool` 签名在 Slice E 中会扩展为 `(output_dir, thread_id, runtime_root, credential_env)` 等。为避免参数膨胀，建议用 `SkillToolContext` dataclass 封装。
- 建议将 `executor.py:546-571` 的 skill mount + prompt append 块抽取为独立 helper（`_build_skill_runtime_context`）（简化测试 + 隔离 Slice E 补丁）。

以上两个只是**建议** — 本分析报告仅限 deletion。

---

## 3. 回归风险区域（引入 m41/m42/secret_scan 时）

### 3.1 m41 — `skills` 表新增 12 列

可能受影响的位置（已完成 grep 验证）：

| 调用处 | 风险 | 验证方法 |
|--------|------|-----------|
| `app/skills/service.py:389 to_runtime_dict()` | 🟢 Low — 仅使用既有 键 | 回归测试：`test_to_runtime_dict_keys_unchanged` |
| `app/schemas/skill.py:50 SkillResponse` | 🟡 Medium — 新增 origin_summary/publication_summary 后响应 shape 扩展 | API contract 测试，frontend 影响（通知扎克伯格） |
| `app/services/chat_service.py:523 build_agent_skills()` | 🟢 Low | 无需变更 |
| `app/skills/runtime.py:19 build_skills_for_agent` | 🟢 Low | 无需变更 |
| `app/skills/prompt.py:build_skills_prompt` | 🟢 Low — 只使用 slug/description | 回归：`test_skills_prompt_block_unchanged` |
| `app/agent_runtime/assistant/tools/write_tools.py:398` | 🟢 Low — 只创建 AgentSkillLink | 无需变更 |
| 既有 skill upload 流程（`routers/skills.py:64`） | 🟡 Medium — 必须填充新列 default 值 | backfill + `test_legacy_upload_sets_origin_kind_created_by_me` |
| Alembic m18 greenfield 痕迹（`models/skill.py:9`） | 🟢 Low — 仅 docstring | 无需变更 |

**Gotcha（已记录在 progress.txt L43-44）**：m41 中执行 `origin_kind NOT NULL DEFAULT 'created_by_me'` 后，必须通过 backfill UPDATE 将 package skill 改为 `imported_by_me`。否则所有既有 package skill 都会被错误显示为"created_by_me"。

### 3.2 m42 — 新增 `AgentSkillLink.config` JSON

可能受影响的位置：

| 调用处 | 风险 |
|--------|------|
| `write_tools.py:398 AgentSkillLink(skill_id=s.id)` | 🟢 Low — `config` 是 nullable JSON，default `None` |
| `chat_service.py:473,511 selectinload(AgentSkillLink.skill)` | 🟢 Low — 新增 `config` 时查询不变，会自动填充 |
| `runtime.py:19 build_skills_for_agent` | 🟡 Medium — Slice E 中必须读取 `link.config["credential_bindings"]`，优先应用 override |
| `helpers.py:35 selectinload` | 🟢 Low |
| Agent settings PUT endpoint（skill 连接/解除） | 🟡 Medium — 需要 config 保留/替换策略（在 Slice B/D 中决定） |

### 3.3 在 `routers/skills.py:upload` 中引入 secret_scan 时

`backend/app/routers/skills.py:64` upload 端点 当前只调用 packager.py。插入 secret_scan 后预计行为变化：

- ✅ 正常 `.skill` 上传：无变化
- ⚠️ 包含 `.env` 的 包：既有 200 → 400 `marketplace_secret_detected`
- ⚠️ 包含 `*.pem` 的 包：同上
- ⚠️ SKILL.md 或 scripts/*.py 中有 `sk-…` 模式：400

回归 防护 测试（必需）：
- `test_secret_scan_upload_regression::test_legitimate_skill_still_uploads`
- `test_secret_scan_upload_regression::test_dotenv_inclusion_rejected_with_specific_error_code`
- `test_secret_scan_upload_regression::test_false_positive_rate_acceptable`（正常 docstring 中类似"sk-example"的 placeholder 应通过）

**Gotcha**：false-positive 会直接阻断用户。`sk-` 必须检查 boundary（`\bsk-[A-Za-z0-9]{20,}\b`），避免拦截 placeholder/示例。（Open Item #OI-4）

### 3.4 修改 `_create_skill_execute_tool` 签名时

影响位置（已 grep 确认）：
- `executor.py:551 langchain_tools.append(_create_skill_execute_tool(conv_output_dir, cfg.thread_id))` — 只有 1 个调用处。
- 扩展签名（例如新增 `runtime_root`、`credential_env`）时只需修改这一处。test 中没有直接调用（`grep _create_skill_execute_tool backend/tests/` → 0 hits）。

---

## 4. Phase 1 发布 门控 矩阵（PRD §13）

| Gate | 通过条件 | 负责 切片 | 验证测试 |
|------|-----------|---------------|-------------|
| **Access control** | private/restricted/public/system 权限矩阵通过，未授权访问返回 404（防止 enumeration oracle） | A (catalog), B (install) | `test_marketplace_access.py::test_owner_acl_unrelated_user_matrix`, `test_marketplace_access.py::test_unauthorized_returns_404_not_403` |
| **Secret safety** | publish/import payload、API 响应、log·SSE·tool result 中不暴露 credential value。`secret_scan.py` 阻断 `.env`/PEM/sk- 模式 | C (secret_scan), E (redaction) | `test_secret_scan.py::*`, `test_redaction.py::*`, `test_api_response_no_credential_value` |
| **Runtime isolation** | 只向 agent 暴露选中的 skill 到 per-thread root。无法访问未选 skill 目录或其他用户 skill。`execute_in_skill` 只允许 runtime root 下路径 | E | `test_runtime_isolation.py::test_unselected_skill_unreachable`, `test_runtime_isolation.py::test_cross_user_skill_unreachable`, `test_runtime_isolation.py::test_execute_in_skill_rejects_outside_runtime_root` |
| **Credential runtime** | required binding 缺失时阻断执行（`marketplace_credential_required`），存在 binding 时只注入 mapped env var。对 log·SSE·tool result 做 redact | D (binding), E (injection + redaction) | `test_credential_injection.py::test_missing_required_credential_fails_fast`, `test_credential_injection.py::test_only_mapped_env_var_injected`, `test_redaction.py::test_mapped_value_redacted_in_all_channels` |
| **k-skill sync** | dry-run 结果 = 实际 sync 结果。对同一 commit 重跑时不产生新 version。单个 skill 失败不会中断整个 sync | F (k_skill_importer) | `test_k_skill_importer.py::test_idempotent_same_commit`, `test_k_skill_importer.py::test_single_skill_failure_does_not_block_sync`, `test_k_skill_importer.py::test_dry_run_matches_real_run` |
| **Backward compatibility** | 既有 skill upload/edit/delete、agent skill 连接、`/api/skills` 响应回归通过。新增 `is_dirty` 不破坏既有编辑 UX | A (m41/m42 backfill) | `test_skills_api_regression.py::test_legacy_upload_still_works`, `test_skills_api_regression.py::test_get_skill_response_shape_preserved`, `test_agent_skill_link_creation_unchanged` |
| **Listing 审批** | public 项在 `is_listed=True` 开关前不出现在目录默认搜索。super_user 开关正常 | A (catalog filter) + admin router | `test_marketplace_listing.py::test_public_unlisted_hidden_from_default_search`, `test_marketplace_listing.py::test_super_user_can_toggle_is_listed`, `test_marketplace_listing.py::test_non_super_user_cannot_toggle_403` |
| **ADR-016 一致性** | 所有新路由器使用 `get_current_user` 或 `require_super_user`。状态变更验证 CSRF | 所有路由器 (A/B/C/D/F) | `test_marketplace_auth.py::test_every_mutation_router_has_csrf`, `test_marketplace_auth.py::test_admin_router_requires_super_user` |

### 切片 → 门控 反向索引

- **Slice A**（catalog + 数据）：Access control、Backward compatibility、Listing 审批、ADR-016
- **Slice B** (install): Access control, ADR-016
- **Slice C** (publish + secret scan): Secret safety
- **Slice D** (credential definitions + binding): Credential runtime
- **Slice E** (runtime mount + injection + redaction): Runtime isolation, Credential runtime, Secret safety
- **Slice F** (k-skill importer): k-skill sync
- **Slice G**（frontend UI）：不直接负责 门控 — 只在 e2e（M9）中验证后端 门控 是否以 frontend behavior 正确呈现

---

## 5. 核心发现（给萨提亚汇报 — 3~5 行）

1. **没有可删除代码** — 市场 是"填补工作"。6 处 `legacy` 注释全部保留为 historical context。
2. **6 个空缺已验证完成** — (a) `executor.py:544-548` broad mount 🔴，(b) `executor.py:144-150` env credential 未注入 🔴，(c) `packager.py` 缺少 secret scan 🔴，(d) `skills` 12 列为 0，(e) `agent_skills.config` 为 0，(f) k-skill 用 credential definition 为 0。
3. **progress.txt 需要更正** — 写的是 credential definitions 14 个，实测 **13 个**（anthropic, openai, google_genai, azure_openai, openrouter, openai_compatible, google_search, naver_search, google_workspace_oauth2, http_bearer, http_basic, http_api_key, mcp_oauth2）。PRD §6 表列出 14 个 — 需要达成一致。
4. **回归核心 2 项** — m41 backfill 若不把既有 package skill 标记为 `imported_by_me`，origin badge 会出错。secret_scan 若没有 `\bsk-…\b` boundary，会因 false-positive 阻断正常 docstring。
5. **8 个发布 门控 已全部映射到 Slice A~F**。每个 门控 至少识别出 2 个验证测试。G（frontend）无直接责任 — 仅在 M9 e2e 中验证。

---

## 6. 跟踪（Open Items）

| ID | 项目 | 负责人 |
|----|------|------|
| OI-1 | credential definitions 13 vs 14 — 更正 progress.txt L38/L70 + PRD §6 表 | 萨提亚/皮查伊确认 |
| OI-2 | `_create_skill_execute_tool` SkillToolContext dataclass 重构（Step 3 简化） | 詹森 — 实现 Slice E 时评估应用 |
| OI-3 | 将 `executor.py:546-571` skill mount/prompt 块拆为 `_build_skill_runtime_context`（测试隔离） | 詹森 — Slice E |
| OI-4 | secret_scan false-positive 标准（boundary regex 规格） | 詹森 — 实现 Slice C 前补充 spec |
| OI-5 | m41 backfill 策略 — 是否将 `package` kind 明确为 `imported_by_me`、`text` kind 明确为 `created_by_me` | 萨提亚/皮查伊 — 补充 Spec §3.x |

---

**End of M1-S1 deletion analysis.**
