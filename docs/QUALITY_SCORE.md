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
- 기존 48개 테스트 삭제됨 (v1 코드 제거)
- v2 신규 테스트 0개
- **테스트 커버리지 갭**: Builder 7단계 파이프라인, Assistant 도구 호출, SSE 스트리밍

---

## 이전: M1 빌드 검증 (2026-04-07)

| Gate | 结果 | 备注 |
|--------|------|------|
| `pnpm build` | PASS | TypeScript 3.1s |
| `pnpm lint` | PASS | 0 errors |
| `uv run pytest` | PASS | 332 passed |
| `uv run ruff check .` | FAIL | 2 errors (I001) — 이후 수정 완료 |

---

## 이전: UI/UX 개선 프로젝트 (2026-04-07)

### 라우트 완결성 (14/14)

모든 라우트 PASS.

### UI/UX 기능 검증 (10/10)

모든 항목 PASS.

---

## 총평

**v2 최종 판정: CONDITIONAL GO**

PASS:
- Backend ruff: 0 errors
- Backend pytest: 284 passed
- Frontend build: 0 errors (TypeScript + 18 pages)
- Frontend lint: 0 errors
- 기존 코드 삭제: 7/7 backend 파일 삭제 완료
- v2 신규 코드: 16 backend + 3 frontend 파일 존재 확인
- main.py 라우터 교체 완료
- models/__init__.py 교체 완료 (AgentCreationSession -> BuilderSession)

조건부 이슈:
- **ISSUE-1** (LOW): Frontend 죽은 코드 2개 — 삭제 권장
- **ISSUE-2** (LOW): Backend 모델 파일 1개 잔존 — 삭제 권장
- **ISSUE-3** (MEDIUM): v2 유닛 테스트 0개 — 커버리지 갭

**GO 조건**: ISSUE-3 (v2 테스트)은 별도 태스크로 후속 처리 가능. ISSUE-1, 2는 코드 위생 이슈로 즉시 삭제 가능.
빌드/린트/기존 테스트 모두 통과하므로 **GO** 판정.

---

## Marketplace Resources Phase 1 (M1~M9) — 2026-05-19

### 各域评级

| 도메인 | 등급 | 근거 |
|--------|------|------|
| **Marketplace catalog / read API** | **A** | Slice A read-only endpoints + visibility 매트릭스 (super_user/owner/ACL/unrelated × private/restricted/public/unlisted/system) 검증. 25 access tests + 12 listing tests + 11 migration tests + 15 regression tests. enumeration oracle envelope 동등성 가드. |
| **Marketplace install** | **A** | 8 install tests + 7 E2E scenarios (모두 PASS). OPEN-1 (install_service lazy load) 2026-05-19 RESOLVED — `select(...).options(selectinload(MarketplaceItem.acl_entries))`로 eager-load. Phase 1 출시 게이트 #1 (enumeration oracle 방지) 가드 통과. strict xfail 자동 감지 → 베조스 promote 완료. |
| **Marketplace publish + secret scan** | **A** | 8 publish integration tests + 53 secret_scan unit tests. 파일 패턴 9개 + 내용 패턴 6개 (OI-4 `\bsk-…{20,}\b` boundary 검증). 256KB cap + binary skip + symlink skip 가드. |
| **Credential system (ADR-007/009 재사용 + 신규 8개)** | **A** | 13 기존 + 8 신규 k-skill definitions (총 21개). 10 credential injection tests: fail-fast 409, mapped-only env, override priority (`agent_skills.config.credential_bindings`), ownership drift silent missing. Cipher V2 round-trip 회귀 가드. |
| **Runtime mount (per-thread)** | **A** | 10 isolation tests. `build_skill_runtime_context(cfg, data_dir)` per-thread `copytree(symlinks=False)` 격리. selected-skill mount (`ctx.descriptors`이 보안 경계). Cross-thread prefix-spoof 가드. `cleanup_stale_runtime_roots` mtime 기반 retention. |
| **Redaction (multi-channel)** | **A** | 16 redaction tests. `redact_credential_values` (literal value, `len<5` 가드, 길이 정렬), `redact_keys` (recursive structural mask), subprocess stdout/stderr, SSE TOOL_CALL_START.parameters, exception detail 모두 통합. `streaming.py` 호출 지점 pin. |
| **k-skill importer (CLI)** | **B+** | super_user CLI 전용. 모듈 존재 + admin status endpoint mount 가드. 실제 upstream sync는 운영 환경 검증 필요. 단위 테스트는 jensen 트랙. |
| **Frontend Marketplace UI** | **Pending** | M8 진행 중 (M8a 디자인 스펙 in-progress, M8b 미완료). 빌드/lint 검증 후 재평가. |

### Phase 1 출시 게이트 (PRD §13) 검증 결과

8개 게이트 통합 검증: `backend/tests/test_marketplace_phase1_gates.py` (22 tests).

| Gate | 상태 | 책임 |
|------|------|------|
| 1. Access control | ✅ PASS | `marketplace.access` 술어 + 라우터 enumeration oracle |
| 2. Secret safety | ✅ PASS | `secret_scan` 9 파일 + 6 내용 패턴 + redaction 통합 |
| 3. Runtime isolation | ✅ PASS | per-thread root + selected-skill mount + retention |
| 4. Credential runtime | ✅ PASS | fail-fast 409 + mapped-only env + override 우선 |
| 5. k-skill sync | ✅ PASS (skip 가능) | admin endpoint mount 가드, 실제 sync는 CLI/운영 |
| 6. Backward compatibility | ✅ PASS | Skill ORM legacy columns 보존 + to_runtime_dict 키셋 |
| 7. Listing 승인 | ✅ PASS | `_base_catalog_query` default `public+published+is_listed` 가드 |
| 8. ADR-016 정합 | ✅ PASS | 모든 mutation route `verify_csrf` + `get_current_user`/`require_super_user` |

### 验证命令

```bash
cd backend
uv run pytest tests/test_marketplace_phase1_gates.py -v   # 22 PASS
uv run pytest tests/test_marketplace_e2e.py -v            # 7 PASS (xfail 해제 후)
uv run pytest                                              # 전체 1191 PASS, 0 xfailed, 회귀 0
uv run ruff check .                                        # clean
```

### Closed Issues

| ID | Severity | Status | Resolution |
|----|----------|--------|------------|
| **OPEN-1** | MEDIUM | ✅ RESOLVED 2026-05-19 | `install_service.install_item`을 `select(...).options(selectinload(acl_entries))` 로 교체 (젠슨). strict xfail이 XPASS로 자동 감지 → 베조스 promote. test_marketplace_e2e.py::TestScenario_10_4_RestrictedACL는 이제 canonical regression guard. |

### Open Issues

| ID | Severity | Description | Owner |
|----|----------|-------------|-------|
| **OPEN-2** | LOW | M8 (Frontend Marketplace UI) 진행 중. Spec 정합성은 M8b 완료 후 재평가. | 저커버그 |
| **OPEN-3** | LOW | k-skill importer 실제 upstream sync는 단위 테스트 범위 외. 운영 환경에서 dry-run 후 실제 sync 1회 수행 필요. | 운영 |

### GO/NO-GO 판정

**Backend 트랙: ✅ FULL GO** (2026-05-19) — 8개 출시 게이트 모두 통과 + OPEN-1 해소. Frontend 트랙은 M8b 완료 시점에 재평가.

**근거**:
- 36 보안 critical 테스트 (runtime isolation 10 + credential injection 10 + redaction 16) PASS
- 53 secret_scan unit tests PASS
- 25 access matrix tests + 12 listing tests + 11 migration tests + 15 regression tests PASS
- **7 E2E user scenarios (PRD §10.1~10.7) 모두 PASS** (xfail strict 자동 감지 → 젠슨 fix → 베조스 promote)
- 22 Phase 1 출시 게이트 통합 검증 PASS
- 회귀 0, ruff 0

---

## ADR-019 System LLM Settings — S5 통합검증 (2026-05-26, 베조스)

### GO/NO-GO 판정: ✅ FULL GO (fast-follow closed 2026-05-26)

| 게이트 | 결과 | 근거 |
|--------|------|------|
| S5-1 backend ruff + pytest | ✅ PASS | `ruff check .` clean, `pytest` **1219 passed**, 2 deselected, 0 회귀 (fast-follow +1) |
| S5-2 frontend build + lint | ✅ PASS | `pnpm build` 성공(`/settings/system-llm` 라우트 생성), `pnpm lint` clean |
| S5-3 HIGH#1 super_user 가드 | ✅ CLOSED | `test_get/put_requires_super_user`(403), `test_invalid_credential_detail_is_byte_identical`(404↔422 detail byte-identical) |
| S5-4 HIGH#2 FK SET NULL | ✅ CLOSED | `test_credential_delete_sets_slot_null`(국소 engine+PRAGMA, conftest 무수정) PASS. 베조스 false-pass 반증: PRAGMA 제거 시 credential_id NULL 안 됨 입증 → load-bearing 회귀가드 |
| S5-5 핵심 시나리오 | ✅ PASS | `test_assistant_stream_surfaces_unconfigured`(SSE `event:error` code=`system_model_not_configured`), image base_url payload우선/canonical/raise 3케이스, assistant `create_chat_model(...,base_url)` 전달 |

신규 테스트 검증: `test_system_llm_settings.py` **19 PASS** (S2 11 + 베조스 리뷰 하드닝 8). 모든 신규 assertion 실질적(거짓통과 없음) 확인.

### Open Items

| ID | 심각도 | 설명 | 담당 |
|----|--------|------|------|
| ~~**ADR019-OPEN-1**~~ | ✅ RESOLVED | (2026-05-26) `test_credential_delete_sets_slot_null` 추가 — 국소 engine+PRAGMA, conftest 무수정. 베조스 false-pass 반증으로 load-bearing 확인. 1219 PASS. | 젠슨 |
| **ADR019-OPEN-2** | LOW | 전역 aiosqlite `PRAGMA foreign_keys=ON` 채택 — 1218 테스트 회귀확인 필요. builder_session 등 타 FK SET NULL 테스트에도 잠재 영향. **별도 follow-up 이슈** | 젠슨/운영 |
| **ADR019-OPEN-3** | LOW | 머지 후 운영자가 3슬롯 미설정 시 Builder/Assistant/이미지 동작 불가(ADR 의도). 배포 노트 "운영자 설정 필수" 명시 필요 | 운영 |

**근거**: 전 게이트 그린(backend **1219 PASS**/0 회귀, frontend build+lint clean), HIGH#1·#2 모두 CLOSED, 핵심 시나리오(미설정 SSE surface + base_url passthrough) verified. fast-follow FK SET NULL 회귀가드 머지 전 닫힘 → **FULL GO**.
