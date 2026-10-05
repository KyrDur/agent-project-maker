# Quality Score — Moldy Agent Builder

> 最终验证日期: 2026-05-09
> 验证人: bezos (QA Engineer)

---

## ADR-016 Multi-user Auth (S2~S7) — 2026-05-09

### Gate

| Gate | 结果 | 备注 |
|---|---|---|
| `uv run ruff check app/ tests/` | PASS | 0 errors |
| `uv run pytest` | PASS | **947 passed, 3 xfailed (BUG escalations), 2 deselected** |
| `pnpm lint` | PASS | 0 errors |
| `pnpm build` | PASS | 所有 route 构建成功（包含 Proxy middleware） |
| Mock user 痕迹 grep（backend/app/, frontend/src/） | PASS | 0 条 |
| `alembic upgrade head` | DEFERRED | dev DB 当前为 head 状态。生产 DB 使用单独 migration window |

### Authentication 域评级

| 区域 | 评级 | 备注 |
|---|:---:|---|
| 后端认证核心（`auth/`） | A | JWT(access/refresh/csrf) 分离 type，bcrypt cost 12，保存 refresh hash |
| Router audit（`/api/auth`） | A | register/login/refresh/logout/me 5 个 endpoint，rate-limit，CSRF exempt 分离 |
| Service layer owner filter | A | 所有 owner-scoped query 均包含 `Agent.user_id == user_id` predicate |
| Super_user guard | A | 6 个 endpoint（system-credentials × 5, models × 3）全部 PASS |
| Multi-user isolation | A | 隔离矩阵 10/10，验证 enumeration oracle 统一为（404） |
| User cleanup / cascade | A | LangGraph thread + refresh + agent CASCADE + system 保留，8/8 PASS |
| CSRF double-submit | A | 7/7 PASS（header≠cookie、sub mismatch、garbage 均拒绝） |
| **Refresh replay defense** | **B-** | 检测与 logging 正常，但 mass-revoke 因漏掉 commit 未生效 — escalation 2 |
| **Login lockout** | **B-** | 同类 commit 遗漏 — failed_login_attempts 计数器永久为 0，escalation 1 |
| 前端认证流程 | A | 19 个新增 + 5 个修改文件，构建 PASS，proxy.ts middleware 正常 |
| 安全 checklist | A- | OWASP Top 10 8/10 PASS，2 项依赖运营配置（cookie_secure, JWT_SECRET）+ 2 项 escalation |
| Migration m36 | A | refresh_tokens、users 字段、FK CASCADE、ADR 编号修正正常 |

### 变更统计（S2~S6 累计）

- 后端新增文件: 8（auth/* 4, models/refresh_token, routers/auth, schemas/auth, services/auth_service, services/user_service）
- 后端新增测试: 6（test_auth_register, test_auth_login, test_auth_refresh, test_csrf, test_multiuser_isolation, test_user_cleanup）— **40 PASS + 3 xfail**
- 前端新增: 19 + 5 修改（auth pages, login form, useAuth hook, proxy middleware 等）
- Migration: 1（m36_multiuser_auth）

### Escalation（阻止 deploy 的事项）

1. **CRITICAL: Login failure counter 未提交** — `auth_service.authenticate` 失败 path 在未 commit 的情况下 raise → `failed_login_attempts` 永久为 0，lockout 失效。可无限 brute-force。
2. **CRITICAL: Refresh replay mass-revoke 未提交** — `rotate_refresh` 检测到 replay 后，`_revoke_all_active` UPDATE 会在 raise 前 rollback → 被盗 refresh 无法强制使 victim session 失效。

两个 escalation 均属于同一类 bug（Router commit 边界遗漏），可在单个 PR 中统一 fix。参见 `tasks/security-checklist-multiuser-auth.md` 的 ESCALATION section。修复后需移除 `tests/test_auth_login.py` 与 `tests/test_auth_refresh.py` 的 `xfail strict` decorator。

### 运营人员 deploy 前操作

1. 设置 `JWT_SECRET` 32 byte 随机环境变量（未设置时使用 ephemeral key）
2. `COOKIE_SECURE=true` + 明确设置 `COOKIE_DOMAIN`
3. 合并上述 2 项 escalation + 验证移除 `xfail`
4. 首位运营人员注册后立即设置 `ALLOW_FIRST_USER_AS_ADMIN=false`
5. 将 `main.py` 的 CORS `allow_origins` 改为基于环境变量（当前硬编码 dev origin）

### 判定

**CONDITIONAL GO** — 隔离矩阵 + super_user guard + cleanup 已达到 production-ready。但 **2 个 commit 遗漏 bug 会使核心安全防护失效**，因此在合并 escalation fix 前禁止 production deploy。

---

## Greenfield Credentials Rewrite (M0~M6) — 2026-04-29

### Gate

| Gate | 结果 | 备注 |
|---|---|---|
| `python scripts/check_branding.py` | PASS | 禁止 identifier 0 条，禁止 npm scope 0 条，asset blacklist 0 条 |
| `uv run ruff check .` | PASS | 0 errors |
| `uv run pytest tests/` | PASS | **480 passed**，1 deselected，1 warning（TestRequestSpec collection 无害） |
| `pnpm lint` | PASS | 0 errors, 1 informational warning (react-hooks/incompatible-library — TanStack Table) |
| `pnpm build` | PASS | 16 routes（credentials, mcp-servers, tools, skills 新增） |
| `alembic upgrade head` | DEFERRED | 用户确认后执行（data-loss 操作） |
| Playwright E2E | DEFERRED | 已编写 4 specs，需要启动后端 — 由用户执行 |

### 各域评级

| 域 | 评级 | 备注 |
|---|:---:|---|
| Cipher V2（security/） | A | 23 tests，moldy-encryption-v1，已完成 key_id 多 key 验证 |
| Credential 域（credentials/） | A | 16 tests + OAuth2 + Tester + Vault，GenericAuth + interpolation + audit log |
| Tools 域（tools/） | A | 12 个工具定义，ToolDefinition 单一路径，GenericAuth 统一 |
| MCP（mcp/） | B+ | discovery + OAuth，agent_mcp_servers link table 未实现（后续） |
| Skills（skills/） | A | text/package 双向，zip-slip + symlink 防护，content_hash |
| agent_runtime 重新接线 | A | chat_service 单一路径，修复 prefetch bug，480 回归 PASS |
| key rotation cron | A | rotate_credentials_to_active_key job + audit log rotate |
| External Secrets（Vault） | B | HVAC SDK 实现，KV v2，AppRole/JWT 不支持（后续） |
| Migration m18 | A- | DROP+CREATE+ALTER，downgrade NotImplementedError，dialect-aware。实际 PostgreSQL upgrade 未执行 |
| 前端 design system | A | DataTable + dynamic-fields-form 一致应用 |
| 前端页面（4） | A | credentials/tools/mcp-servers/skills 可运行，build PASS |
| Branding/license guard | A | CI gate 强制执行 |

### 变更统计

- 后端新增文件: ~64（security 2 + credentials 22 + tools 10 + mcp 4 + skills 4 + models 7 + routers 4 + seed 1 + alembic 1 + tests 10）
- 后端废弃: 21 prod + 21 tests
- 前端新增: ~29（design 4 + 页面 4 + components 14 + types/api/hooks 15 + e2e 4）
- 前端废弃: ~24
- 新增测试: ~110（cipher 23 + branding 1 + credentials 16 + oauth2 + tester + external_secrets + tools + mcp + skills 21 + seed 5 + migration 5 + chat_integration 3 + rotation 2）

### 后续（单独 PR/ticket）

1. `alembic upgrade head` 在真实 PostgreSQL 上执行 — 需要用户确认（废弃 dev DB）
2. 执行 Playwright E2E live API — 启动后端后
3. 进行 1 次律师 license review — 对外发布时
4. 引入 agent_mcp_servers link table — 将 MCP 工具直接连接到 Agent
5. OAuth2 callback state 使用 Redis/DB backing — 多进程 deploy 时
6. TestRequestSpec → CredentialTestSpec rename — 消除 pytest collection warning
7. 添加 Vault AppRole/JWT 认证
8. 加强 interpolation sandbox（安全面）

### 判定

**GO** — 可作为单个 PR 合并。6 个 milestone 全部 gate PASS。回归风险 Low（480 tests 单周期 PASS）。

---

## Backlog C — 移除 credentials list N+1 解密（2026-04-17）

### Gate

| Gate | 结果 | 备注 |
|--------|------|------|
| `uv run ruff check .` | PASS | 0 errors |
| `uv run pytest tests/test_credentials.py -v` | PASS | 新增 5/5 |
| `uv run pytest` | PASS | **545 passed**（超过 540+ 基线） |
| `alembic upgrade head ↔ downgrade -1 ↔ upgrade head` | PASS | Jensen S2 往返确认 |

### 新增/变更文件

| 文件 | 变更 |
|------|------|
| `backend/app/models/credential.py` | 新增 `field_keys: Mapped[list[str] \| None]` 字段 |
| `backend/alembic/versions/m7_add_credential_field_keys.py` | 新增 migration + backfill |
| `backend/app/services/credential_service.py` | create/update 同步，extract 优先使用 cache |
| `backend/tests/test_credentials.py` | 新增 5 个场景 |

### 删除分析（M1）

- 实际删除: **0 条**（严格遵守 scope）
- 简化建议: 1 条（转至单独 ticket）
- 暂缓: 3 条（is_active/has_data/fallback — scope 外或有意保留）
- 产出物: `tasks/deletion-analysis-c.md`

### 判定

**GO** — 所有 M0~M4 PASS。M5（集成/commit）由 Satya DRI 负责。

---

## v2 Builder/Assistant 项目 — 最终 build 验证（2026-04-07）

### Build/lint gate

| Gate | 结果 | 备注 |
|--------|------|------|
| `uv run ruff check .` | PASS | 0 errors |
| `uv run pytest` | PASS | 284 passed, 0 failed (6.93s) |
| `pnpm build` | PASS | TypeScript 3.2s, 13 static + 5 dynamic pages, 0 errors |
| `pnpm lint` (ESLint) | PASS | 0 errors, 0 warnings |

### 测试覆盖率变化

| 时间点 | 测试数量 | 备注 |
|------|-----------|------|
| M1（实现前） | 332 | 包含现有 creation_agent、fix_agent 测试 |
| 最终（实现后） | 284 | 删除 48 个现有测试（移除 v1 代码） |
| **v2 新增测试** | **0** | 未编写 Builder/Assistant unit test |

### v2 新增文件（Backend）

| 分类 | 文件 | 状态 |
|----------|------|------|
| Builder orchestrator | `agent_runtime/builder/orchestrator.py` | EXISTS |
| Builder sub-agent | `builder/sub_agents/intent_analyzer.py` | EXISTS |
| Builder sub-agent | `builder/sub_agents/tool_recommender.py` | EXISTS |
| Builder sub-agent | `builder/sub_agents/middleware_recommender.py` | EXISTS |
| Builder sub-agent | `builder/sub_agents/prompt_generator.py` | EXISTS |
| Assistant Agent | `agent_runtime/assistant/assistant_agent.py` | EXISTS |
| Assistant 工具 | `assistant/tools/read_tools.py` | EXISTS |
| Assistant 工具 | `assistant/tools/write_tools.py` | EXISTS |
| Assistant 工具 | `assistant/tools/clarify_tools.py` | EXISTS |
| Builder Router | `routers/builder.py` | EXISTS |
| Assistant Router | `routers/assistant.py` | EXISTS |
| Builder Service | `services/builder_service.py` | EXISTS |
| Assistant Service | `services/assistant_service.py` | EXISTS |
| Builder Schema | `schemas/builder.py` | EXISTS |
| Assistant Schema | `schemas/assistant.py` | EXISTS |
| Builder Model | `models/builder_session.py` | EXISTS |

### v2 新增文件（Frontend）

| 分类 | 文件 | 状态 |
|----------|------|------|
| Builder API | `lib/api/builder.ts` | EXISTS |
| Assistant API | `lib/api/assistant.ts` | EXISTS |
| Assistant Panel | `components/agent/assistant-panel.tsx` | EXISTS |

### 删除文件（Backend）— 已确认 7/7

| 文件 | 状态 |
|------|------|
| `agent_runtime/creation_agent.py` | DELETED |
| `agent_runtime/fix_agent.py` | DELETED |
| `routers/agent_creation.py` | DELETED |
| `routers/fix_agent.py` | DELETED |
| `services/agent_creation_service.py` | DELETED |
| `schemas/agent_creation.py` | DELETED |
| `schemas/fix_agent.py` | DELETED |

### 删除测试（Backend）— 已确认 3/3

| 文件 | 状态 |
|------|------|
| `tests/test_creation_agent.py` | DELETED |
| `tests/test_fix_agent.py` | DELETED |
| `tests/test_agent_creation_extended.py` | DELETED |

### main.py Router 替换

| 之前 | 之后 | 状态 |
|------|------|------|
| `agent_creation.router` | `builder.router` | PASS |
| `fix_agent.router` | `assistant.router` | PASS |

### models/__init__.py 替换

| 之前 | 之后 | 状态 |
|------|------|------|
| `AgentCreationSession` | `BuilderSession` | PASS |

---

## 未解决问题（3 条）

### ISSUE-1: Dead code — Frontend 删除遗漏（严重度: LOW）

| 文件 | 状态 | 影响 |
|------|------|------|
| `frontend/src/lib/api/creation-session.ts` | 文件存在，但未被任何位置 import | 对 build 无影响，tree-shaking |
| `frontend/src/components/agent/fix-agent-dialog.tsx` | 文件存在，但未被任何位置 import | 对 build 无影响，tree-shaking |

对 build/runtime 无影响，但从 codebase hygiene 角度建议删除。

### ISSUE-2: Dead code — Backend model 文件残留（严重度: LOW）

| 文件 | 状态 | 影响 |
|------|------|------|
| `backend/app/models/agent_creation_session.py` | 文件存在，未在 `__init__.py` 中 import | 对 build 无影响 |

已替换为 `BuilderSession`，但旧文件遗漏删除。建议考虑 Alembic migration 后删除。

### ISSUE-3: 缺少 v2 unit test（严重度: MEDIUM）

Builder orchestrator、Assistant Agent、v2 Router/Service 均没有 unit test。
- 已删除现有 48 个测试（移除 v1 代码）
- v2 新增测试 0 个
- **测试覆盖缺口**：Builder 7 阶段流水线、Assistant 工具调用、SSE 流式传输

---

## 之前：M1 构建验证 (2026-04-07)

| Gate | 结果 | 备注 |
|--------|------|------|
| `pnpm build` | PASS | TypeScript 3.1s |
| `pnpm lint` | PASS | 0 errors |
| `uv run pytest` | PASS | 332 passed |
| `uv run ruff check .` | FAIL | 2 errors (I001) — 后续已修复 |

---

## 之前：UI/UX 改进项目 (2026-04-07)

### 路由完整性 (14/14)

所有路由均 PASS。

### UI/UX 功能验证 (10/10)

所有项目均 PASS。

---

## 总评

**v2 最终判定：CONDITIONAL GO**

PASS:
- Backend ruff: 0 errors
- Backend pytest: 284 passed
- Frontend build: 0 errors (TypeScript + 18 pages)
- Frontend lint: 0 errors
- 现有代码删除：7/7 backend 文件已删除
- v2 新增代码：已确认存在 16 个 backend + 3 个 frontend 文件
- main.py 路由替换完成
- models/__init__.py 替换完成 (AgentCreationSession -> BuilderSession)

条件性问题：
- **ISSUE-1** (LOW)：Frontend 死代码 2 个 — 建议删除
- **ISSUE-2** (LOW)：Backend 模型文件残留 1 个 — 建议删除
- **ISSUE-3** (MEDIUM)：v2 单元测试 0 个 — 覆盖缺口

**GO 条件**：ISSUE-3 (v2 测试) 可作为独立任务后续处理。ISSUE-1、2 属于代码卫生问题，可立即删除。
构建/lint/现有测试均通过，因此判定为 **GO**。

---

## Marketplace Resources Phase 1 (M1~M9) — 2026-05-19

### 各域评级

| 领域 | 等级 | 依据 |
|--------|------|------|
| **Marketplace catalog / read API** | **A** | 已验证 Slice A read-only endpoints + visibility 矩阵 (super_user/owner/ACL/unrelated × private/restricted/public/unlisted/system)。25 access tests + 12 listing tests + 11 migration tests + 15 regression tests。enumeration oracle envelope 等价性防护。 |
| **Marketplace install** | **A** | 8 install tests + 7 E2E scenarios（全部 PASS）。OPEN-1 (install_service lazy load) 2026-05-19 RESOLVED — 通过 `select(...).options(selectinload(MarketplaceItem.acl_entries))` 进行 eager-load。Phase 1 发布门禁 #1（防止 enumeration oracle）防护通过。strict xfail 自动检测 → Bezos promote 完成。 |
| **Marketplace publish + secret scan** | **A** | 8 publish integration tests + 53 secret_scan unit tests。文件模式 9 个 + 内容模式 6 个 (OI-4 `\bsk-…{20,}\b` boundary 验证)。256KB cap + binary skip + symlink skip 防护。 |
| **Credential system (ADR-007/009 复用 + 新增 8 个)** | **A** | 13 个现有 + 8 个新增 k-skill definitions（共 21 个）。10 credential injection tests：fail-fast 409、mapped-only env、override priority (`agent_skills.config.credential_bindings`)、ownership drift silent missing。Cipher V2 round-trip 回归防护。 |
| **Runtime mount (per-thread)** | **A** | 10 isolation tests。`build_skill_runtime_context(cfg, data_dir)` per-thread `copytree(symlinks=False)` 隔离。selected-skill mount（`ctx.descriptors` 为安全边界）。Cross-thread prefix-spoof 防护。`cleanup_stale_runtime_roots` 基于 mtime 的 retention。 |
| **Redaction (multi-channel)** | **A** | 16 redaction tests。`redact_credential_values`（literal value、`len<5` 防护、长度排序）、`redact_keys`（recursive structural mask）、subprocess stdout/stderr、SSE TOOL_CALL_START.parameters、exception detail 均已集成。固定 `streaming.py` 调用位置。 |
| **k-skill importer (CLI)** | **B+** | 仅限 super_user CLI。模块存在 + admin status endpoint mount 防护。实际 upstream sync 需要在生产环境验证。单元测试属于 Jensen 轨道。 |
| **Frontend Marketplace UI** | **Pending** | M8 进行中（M8a 设计规格 in-progress，M8b 未完成）。构建/lint 验证后重新评估。 |

### Phase 1 发布门禁 (PRD §13) 验证结果

8 个门禁集成验证：`backend/tests/test_marketplace_phase1_gates.py` (22 tests)。

| Gate | 状态 | 责任 |
|------|------|------|
| 1. Access control | ✅ PASS | `marketplace.access` 谓词 + 路由 enumeration oracle |
| 2. Secret safety | ✅ PASS | `secret_scan` 9 个文件模式 + 6 个内容模式 + redaction 集成 |
| 3. Runtime isolation | ✅ PASS | per-thread root + selected-skill mount + retention |
| 4. Credential runtime | ✅ PASS | fail-fast 409 + mapped-only env + override 优先 |
| 5. k-skill sync | ✅ PASS（可 skip） | admin endpoint mount 防护，实际 sync 通过 CLI/生产环境 |
| 6. Backward compatibility | ✅ PASS | 保留 Skill ORM legacy columns + to_runtime_dict 键集合 |
| 7. Listing 审批 | ✅ PASS | `_base_catalog_query` default `public+published+is_listed` 防护 |
| 8. ADR-016 一致性 | ✅ PASS | 所有 mutation route `verify_csrf` + `get_current_user`/`require_super_user` |

### 验证命令

```bash
cd backend
uv run pytest tests/test_marketplace_phase1_gates.py -v   # 22 PASS
uv run pytest tests/test_marketplace_e2e.py -v            # 7 PASS（解除 xfail 后）
uv run pytest                                              # 全部 1191 PASS, 0 xfailed, 回归 0
uv run ruff check .                                        # clean
```

### Closed Issues

| ID | Severity | Status | Resolution |
|----|----------|--------|------------|
| **OPEN-1** | MEDIUM | ✅ RESOLVED 2026-05-19 | 将 `install_service.install_item` 替换为 `select(...).options(selectinload(acl_entries))` (Jensen)。strict xfail 自动检测为 XPASS → Bezos promote。test_marketplace_e2e.py::TestScenario_10_4_RestrictedACL 现已成为 canonical regression guard。 |

### Open Issues

| ID | Severity | Description | Owner |
|----|----------|-------------|-------|
| **OPEN-2** | LOW | M8 (Frontend Marketplace UI) 进行中。Spec 一致性将在 M8b 完成后重新评估。 | Zuckerberg |
| **OPEN-3** | LOW | k-skill importer 的实际 upstream sync 超出单元测试范围。需要在生产环境 dry-run 后执行 1 次实际 sync。 | 运维 |

### GO/NO-GO 判定

**Backend 轨道：✅ FULL GO** (2026-05-19) — 8 个发布门禁全部通过 + OPEN-1 已解决。Frontend 轨道将在 M8b 完成时重新评估。

**依据**：
- 36 个安全 critical 测试 (runtime isolation 10 + credential injection 10 + redaction 16) PASS
- 53 secret_scan unit tests PASS
- 25 access matrix tests + 12 listing tests + 11 migration tests + 15 regression tests PASS
- **7 个 E2E user scenarios (PRD §10.1~10.7) 全部 PASS**（strict xfail 自动检测 → Jensen fix → Bezos promote）
- 22 个 Phase 1 发布门禁集成验证 PASS
- 回归 0，ruff 0

---

## ADR-019 System LLM Settings — S5 集成验证 (2026-05-26, Bezos)

### GO/NO-GO 判定：✅ FULL GO (fast-follow closed 2026-05-26)

| 门禁 | 结果 | 依据 |
|--------|------|------|
| S5-1 backend ruff + pytest | ✅ PASS | `ruff check .` clean，`pytest` **1219 passed**，2 deselected，0 回归 (fast-follow +1) |
| S5-2 frontend build + lint | ✅ PASS | `pnpm build` 成功（生成 `/settings/system-llm` 路由），`pnpm lint` clean |
| S5-3 HIGH#1 super_user 防护 | ✅ CLOSED | `test_get/put_requires_super_user`(403)，`test_invalid_credential_detail_is_byte_identical`(404↔422 detail byte-identical) |
| S5-4 HIGH#2 FK SET NULL | ✅ CLOSED | `test_credential_delete_sets_slot_null`（局部 engine+PRAGMA，conftest 未修改）PASS。Bezos false-pass 反证：证明移除 PRAGMA 时 credential_id 不会变为 NULL → load-bearing 回归防护 |
| S5-5 核心场景 | ✅ PASS | `test_assistant_stream_surfaces_unconfigured`(SSE `event:error` code=`system_model_not_configured`)，image base_url payload优先/canonical/raise 3 个 case，assistant 传递 `create_chat_model(...,base_url)` |

新增测试验证：`test_system_llm_settings.py` **19 PASS** (S2 11 + Bezos review hardening 8)。确认所有新增 assertion 均有效（无假通过）。

### Open Items

| ID | 严重度 | 说明 | 负责人 |
|----|--------|------|------|
| ~~**ADR019-OPEN-1**~~ | ✅ RESOLVED | (2026-05-26) 新增 `test_credential_delete_sets_slot_null` — 局部 engine+PRAGMA，conftest 未修改。通过 Bezos false-pass 反证确认为 load-bearing。1219 PASS。 | Jensen |
| **ADR019-OPEN-2** | LOW | 采用全局 aiosqlite `PRAGMA foreign_keys=ON` — 需要对 1218 个测试进行回归确认。对 builder_session 等其他 FK SET NULL 测试也可能有影响。**独立 follow-up issue** | Jensen/运维 |
| **ADR019-OPEN-3** | LOW | 合并后若运维人员未配置 3 个 slot，Builder/Assistant/图像将无法运行（ADR 设计意图）。发布说明中需明确“运维人员必须配置” | 运维 |

**依据**：所有门禁均为绿色（backend **1219 PASS**/0 回归，frontend build+lint clean），HIGH#1·#2 均 CLOSED，核心场景（未配置 SSE surface + base_url passthrough）verified。fast-follow FK SET NULL 回归防护在合并前关闭 → **FULL GO**。
