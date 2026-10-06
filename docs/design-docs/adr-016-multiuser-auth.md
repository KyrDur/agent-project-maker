# ADR-016 — 引入多用户认证（HttpOnly Cookie + JWT + super_user）

## 1. Status & Date

- **Status**: Accepted
- **Date**: 2026-05-09
- **Supersedes / Relates**: ADR-009（Credentials 绿地方案 — 影响新增 `is_system`），ADR-013（Service-side LLM Key — 每用户 credential 优先级策略）
- **Branch**: `feature/multiuser-auth`
- **Plan source**: `~/.claude/plans/replicated-crunching-lark.md`

---

## 2. Context

natural-mold 在 PoC 阶段以单一 Mock User（`00000000-0000-0000-0000-000000000001`, `demo@moldy.dev`）运行。数据模型已经基于 `user_id` FK 按多用户前提设计，因此**后端隔离基础设施约完成 70%**，但以下五个冲突点仍阻碍真正的多用户运营。

### 2.1 5 个主要冲突点

1. **缺少认证系统** — `backend/app/dependencies.py:get_current_user()` 直接从环境变量返回 mock user。完全没有 token/session 概念。
2. **前端认证基础设施完全缺失** — `/login`·`/register` route、`middleware.ts`、API client token 附加、CSRF 处理均不存在。
3. **系统资源依赖 mock-user** — `backend/app/seed/bootstrap_from_env.py:bootstrap_credentials_from_env` 以 `user_id=mock_user_id` 创建 credential → 所有用户都会用 operator 密钥调用 LLM（成本失控 + 安全事故）。
4. **Google OAuth refresh_token 是全局环境变量** — 所有用户共享 `settings.google_oauth_refresh_token` 中的单一 token。无法做到 per-user 隔离。
5. **ON DELETE 策略不一致** — `agents`, `builder_sessions`, `agent_triggers` 的 `user_id` FK 未指定 ondelete（PostgreSQL default = NO ACTION）。而 `tools`, `credentials`, `daily_spend_users` 使用 CASCADE。删除用户时行为不一致。

### 2.2 目标

在 3 周内实现 production-ready 的多用户 MVP，同时在设计阶段预留未来扩展为**个人 → 团队 → 室 → 公司**四级 workspace 的 hook。当前只实现 User 级 tenancy，代码签名与列命名保持面向未来。

---

## 3. Decision

### 3.1 核心决策表

| 项目 | 选择 | 依据 |
|------|------|------|
| Token 存储 | **HttpOnly Cookie (Access + Refresh) + CSRF Token in JSON body** | 抗 XSS，成熟模式，JS 无法直接访问 token |
| 算法 | **JWT HS256** | 标准方案，单后端环境无需非对称密钥 |
| Access TTL | **60 分钟** | 保持较短，通过 refresh 轮换 |
| Refresh TTL | **30 天**（基于 DB whitelist 轮换） | 不使用 Redis — `refresh_tokens` 表 |
| 密码哈希 | **bcrypt (passlib CryptContext)** | 安全、成熟。服务端单一哈希 |
| 权限模型 | **单一 `is_super_user` boolean 标志** | 简化 MVP，未来可扩展 RBAC |
| Tenancy 单位 | **User 级（MVP）** + **Workspace 扩展 hook** | 统一让 service layer 接收 user 对象 |
| 认证方式 | **仅 Email + Password** | OAuth 登录放到 Phase 2 |
| 首位注册者 | **自动设为 super_user** (`ALLOW_FIRST_USER_AS_ADMIN=true`) | 简化 bootstrap |
| System credentials 可见性 | **仅 super_user**（查询/使用/管理均如此） | 阻止成本失控 + 安全风险。普通用户必须注册自己的密钥 |
| Mock user | **移除**（通过迁移脚本把 ownership 转给新的 super_user） | 移除所有单用户 bootstrap 代码 |

### 3.2 未采用方案

- **localStorage + Bearer token**：存在 XSS 暴露风险 → 拒绝。
- **MVP 包含 OAuth 登录**：SMTP/邮箱验证基础设施未准备，工期压力 → 延后到 Phase 2。
- **RBAC（角色表）**：对 MVP 过度设计 → 单一 `is_super_user` 标志足够。
- **Redis whitelist**：简化基础设施 → 使用基于 DB 的 `refresh_tokens` 表。
- **启用邮箱验证/密码重置**：SMTP 未准备 → Phase 2。但列先行加入。

---

## 4. Data Model Specs

### 4.1 `users` 表新增列

| 列 | 类型 | NULL | Default | 备注 |
|------|------|------|---------|------|
| `hashed_password` | `VARCHAR(255)` | YES | NULL | bcrypt hash。为 OAuth-only 用户预留 nullable |
| `is_active` | `BOOLEAN` | NO | `TRUE` | 禁用后阻止登录 |
| `is_super_user` | `BOOLEAN` | NO | `FALSE` | 仅首位注册者自动 TRUE |
| `last_login_at` | `TIMESTAMPTZ` | YES | NULL | 登录成功时更新 |
| `last_login_ip` | `VARCHAR(45)` | YES | NULL | IPv6 max 长度 |
| `failed_login_attempts` | `INTEGER` | NO | `0` | 达到 5 次时锁定 |
| `locked_until` | `TIMESTAMPTZ` | YES | NULL | 锁定到期时间（15 分钟后） |
| `email_verified_at` | `TIMESTAMPTZ` | YES | NULL | Phase 2 启用。MVP 始终为 NULL |
| `email_verify_token` | `VARCHAR(64)` | YES | NULL | sparse index. Phase 2 |
| `email_verify_expires_at` | `TIMESTAMPTZ` | YES | NULL | Phase 2 |
| `password_reset_token` | `VARCHAR(64)` | YES | NULL | sparse index. Phase 2 |
| `password_reset_expires_at` | `TIMESTAMPTZ` | YES | NULL | Phase 2 |

索引：
- `ix_users_email` (UNIQUE, 已存在) — 保留。
- `ix_users_email_verify_token` (sparse, WHERE token IS NOT NULL) — Phase 2 使用。
- `ix_users_password_reset_token` (sparse, WHERE token IS NOT NULL) — Phase 2 使用。

### 4.2 `refresh_tokens` 表（新增）

```sql
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,         -- SHA-256 hex of refresh JWT jti
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,             -- 轮换时立即撤销
    user_agent TEXT NULL,
    ip VARCHAR(45) NULL
);
CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens(token_hash);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX ix_refresh_tokens_active
    ON refresh_tokens(user_id, expires_at)
    WHERE revoked_at IS NULL;
```

轮换策略：
- 调用 `/auth/refresh` 时，将现有 row 设置 `revoked_at = NOW()` + 发放新 row。轮换时以 `old.replaced_by_id = new.id` 连接 chain（m37）。
- 已经 `revoked_at IS NOT NULL` 的 token 再次进入时，分为两种情况：
  - **Race（标签页竞争）** — 存在 `replaced_by_id` + 替代项 active + `revoked_at` 在 `settings.refresh_rotation_grace_seconds`（默认 10s）以内 + 原 row 的 user-agent 与当前请求一致 → 从替代项再次轮换并发放新 token（延长 chain）。不批量撤销。保护两个标签页同时 `/refresh` 的场景（2026-05-18 回归 guard）。
  - **Replay（疑似真实攻击）** — 其他所有情况（不同 UA、超过 grace、替代项也已撤销等）→ 批量 revoke 该 user 的所有 active refresh。`UPDATE refresh_tokens SET revoked_at=NOW() WHERE user_id=:uid AND revoked_at IS NULL`。
- 过期 row 由 cron 执行 GC：在 `settings.refresh_token_gc_cron`（默认每天 05:00 UTC）运行 `DELETE FROM refresh_tokens WHERE expires_at < NOW() - settings.refresh_token_gc_retention_days days`。默认 retention 1d，因此刚过期的 token 仍可分类为 replay。`replaced_by_id` 自引用 FK 使用 `ON DELETE SET NULL`，删除 chain 中间 row 也安全。实现：`app/services/refresh_token_gc.py`, `app/scheduler.py::register_refresh_token_gc_job`。
- 轮换时先用 Postgres `SELECT ... FOR UPDATE` lock row，再 mutation。如果两个竞争者同时 rotate 同一 chain head，较晚一方在锁释放后发现 revoked 状态，并沿 chain 前进到下一 hop（最多 `_MAX_CHAIN_FOLLOW` 次）。结果：所有新 leg 都 linearly linked 到单一 chain，不存在 orphan active row。SQLite 测试环境不支持 lock，因此并发回归只能在 Postgres 集成测试中验证。实现：`auth_service._lock_row` + `rotate_refresh` chain-walk 循环。

### 4.3 `oauth_accounts` 表（仅预留 Phase 2 — 当前不创建）

> **MVP 不创建此表。** 以下内容是为了在 Phase 2 新增时避免名称·结构冲突而预先确定。

```sql
-- 计划在 Phase 2 添加。不包含在 m22_multiuser_auth.py 中。
CREATE TABLE oauth_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,           -- 'google', 'github', ...
    provider_user_id VARCHAR(255) NOT NULL,  -- provider 内部 user id
    email VARCHAR(255) NULL,
    access_token_encrypted TEXT NULL,        -- Cipher V2
    refresh_token_encrypted TEXT NULL,       -- Cipher V2
    token_expires_at TIMESTAMPTZ NULL,
    scope TEXT NULL,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);
```

设计约定：
- 登录用 OAuth 与工具用（`google_workspace_tools.py`）以**分离的 client** 运行。
- Router prefix 为 `/api/auth/oauth/{provider}/start|callback`。
- 允许 `User.hashed_password = NULL` + 仅存在 `oauth_accounts` row 的用户（= OAuth-only）。

### 4.4 新增 `tools.is_system` / `credentials.is_system` 列

| 表 | 列 | 类型 | NULL | Default |
|--------|------|------|------|---------|
| `tools` | `is_system` | `BOOLEAN` | NO | `FALSE` |
| `credentials` | `is_system` | `BOOLEAN` | NO | `FALSE` |

CHECK constraint（两个表相同）：

```sql
ALTER TABLE tools ADD CONSTRAINT ck_tools_system_user_null
    CHECK ((is_system = FALSE) OR (user_id IS NULL));
ALTER TABLE credentials ADD CONSTRAINT ck_credentials_system_user_null
    CHECK ((is_system = FALSE) OR (user_id IS NULL));
```

→ 当 `is_system=TRUE` 时必须 `user_id IS NULL`。把现有 `user_id IS NULL` 约定转换为显式 boolean。

### 4.5 FK ON DELETE 策略矩阵

| 表 | 列 | 当前 | 修改后 | 依据 |
|--------|------|------|---------|------|
| `agents` | `user_id` | unspecified (= NO ACTION) | **CASCADE** | 用户注销时批量清理自己的 agent |
| `builder_sessions` | `user_id` | unspecified | **CASCADE** | 同上 |
| `agent_triggers` | `user_id` | unspecified | **CASCADE** | 同上 |
| `tools` | `user_id` | CASCADE | 保持 | OK |
| `credentials` | `user_id` | CASCADE | 保持 | OK |
| `daily_spend_users` | `user_id` | CASCADE | 保持 | OK |
| `refresh_tokens` | `user_id` |（新增）| **CASCADE** | 删除用户时清理 token |
| `oauth_accounts` | `user_id` | (Phase 2) | **CASCADE** | Phase 2 |

**注意**：LangGraph `PostgresSaver` 的 `checkpoints*` 表没有 `user_id` FK → 不会 CASCADE。`user_service.delete_user` 必须按 conversation 调用 `checkpointer.delete_thread()`（参见 Phase 6）。

### 4.6 迁移文件

- `backend/alembic/versions/m22_multiuser_auth.py`（新增）。
- 顺序：① 新增 `users` 列 → ② 新建 `refresh_tokens` → ③ 新增 `tools.is_system` / `credentials.is_system` + CHECK → ④ drop+recreate `agents`/`builder_sessions`/`agent_triggers` FK（CASCADE）→ ⑤ 数据回填（mock user → super_user，`user_id IS NULL` 的 tools/credentials → `is_system=TRUE`）。
- 本次迁移**不创建** `oauth_accounts`。

---

## 5. API Contract

### 5.1 Endpoint 规范

#### POST `/api/auth/register`

| 项目 | 值 |
|------|----|
| 认证 | 无 |
| Rate limit | 每 IP 5 次/小时 |
| Request body | `{"email": "user@example.com", "password": "min8chars", "name": "Display Name"}` |
| Validation | email RFC5322, password ≥ 8 字符, name 1–80 字符 |
| 200/201 | `201 Created` |
| Response body | `{"user": {"id": UUID, "email": str, "name": str, "is_super_user": bool, "created_at": ISO8601}, "csrf_token": str}` |
| Set-Cookie (3) | `moldy_at` (HttpOnly, Secure*, SameSite=Lax, Path=/, Max-Age=3600), `moldy_rt` (HttpOnly, Secure*, SameSite=Lax, Path=/, Max-Age=2592000), `moldy_csrf` (Secure*, SameSite=Lax, Path=/, Max-Age=3600 — JS 可读取，用于 double-submit) |
| 副作用 | 若 DB 中 `users.count()=0`，赋予 `is_super_user=TRUE` 后创建。自动登录（发放 3 种 token） |
| 错误 | `409 email_already_exists`, `422 validation_error`, `429 too_many_requests` |

\* `Secure` 取决于 `settings.cookie_secure`（dev=false, prod=true）。

#### POST `/api/auth/login`

| 项目 | 值 |
|------|----|
| 认证 | 无 |
| Rate limit | 每 IP+email 10 次/分钟 |
| Request body | `{"email": str, "password": str}` |
| 200 | `{"user": {...}, "csrf_token": str}` + 3 个 Set-Cookie |
| 副作用 | 成功时更新 `last_login_at`, `last_login_ip`，`failed_login_attempts=0`。失败时 `failed_login_attempts++`，达到 5 次时 `locked_until = NOW + 15min` |
| 错误 | `401 invalid_credentials`, `423 account_locked`（locked_until 未过期时）, `403 account_inactive` (is_active=false), `429 too_many_requests` |

#### POST `/api/auth/logout`

| 项目 | 值 |
|------|----|
| 认证 | required (access cookie) + CSRF |
| 200 | `{"ok": true}` |
| 副作用 | 当前 refresh token row 的 `revoked_at = NOW()`。Clear-Cookie：清除 3 个 Cookie (Max-Age=0) |
| 错误 | `401 not_authenticated`, `403 csrf_mismatch` |

#### POST `/api/auth/refresh`

| 项目 | 值 |
|------|----|
| 认证 | 必须有 refresh cookie (`moldy_rt`) |
| CSRF | **不需要**（仅凭 cookie 轮换 — 无 body） |
| Rate limit | 每 IP 30 次/分钟 |
| Request body |（无）|
| 200 | `{"csrf_token": str}` + 3 个新的 Set-Cookie |
| 副作用 | revoke 现有 refresh row + 发放新的 access/refresh/csrf。检测到 Replay 时批量撤销该 user 的所有 refresh 后返回 401 |
| 错误 | `401 invalid_refresh`（过期/revoked/replay） |

#### GET `/api/auth/me`

| 项目 | 值 |
|------|----|
| 认证 | required |
| CSRF | 不需要 (GET) |
| 200 | `{"user": {"id": UUID, "email": str, "name": str, "is_super_user": bool, "is_active": bool, "created_at": ISO8601, "last_login_at": ISO8601 \| null}}` |
| 错误 | `401 not_authenticated` |

### 5.2 错误标准

| HTTP | 代码 | 含义 |
|------|------|------|
| 401 | `not_authenticated`, `invalid_credentials`, `invalid_refresh` | token/凭据不匹配 |
| 403 | `csrf_mismatch`, `account_inactive`, `forbidden` | 授权失败 |
| 409 | `email_already_exists` | 重复 |
| 422 | `validation_error` | Pydantic 验证失败 |
| 423 | `account_locked` | 失败 5 次后锁定（包含 Retry-After header） |
| 429 | `too_many_requests` | rate limit |

响应 body 格式（所有错误通用）：
```json
{ "detail": { "code": "invalid_credentials", "message": "Email or password is incorrect." } }
```

---

## 6. Authorization Pattern

### 6.1 Dependency 签名

`backend/app/dependencies.py`:

```python
@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    name: str
    is_super_user: bool = False
    # 未来：workspace_id: UUID | None = None

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """从 access cookie 或 Authorization header 提取 token → JWT decode → 查询 User。
    失败时返回 401 not_authenticated。停用的 user 返回 401。"""

async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser | None:
    """用于 share endpoint 等允许 anonymous 的场景。即使无 token 或 token 错误也返回 None。"""

async def require_super_user(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """若 is_super_user=False，则返回 403 forbidden。"""

async def verify_csrf(request: Request) -> None:
    """若 method 为 GET/HEAD/OPTIONS 则立即通过。
    否则验证 X-CSRF-Token header == moldy_csrf cookie（double-submit）。
    不匹配时返回 403 csrf_mismatch。"""
```

### 6.2 Router 应用规则

- 所有 domain router：`Depends(get_current_user)` + `Depends(verify_csrf)`（仅 mutation）。
- `templates`, `models` 的 create/update/delete：替换为 `Depends(require_super_user)`。
- `health`, `/api/auth/login|register|refresh`, `shares/{token}/...`：无认证 dependency。
- `verify_csrf` 对 `/api/auth/refresh`（cookie 轮换）、`/api/auth/login|register`（发放 CSRF 之前）、`shares/{token}/...`（公开 link）豁免。

---

## 7. Workspace 扩展蓝图

本 ADR 只实现 **User 级 tenancy**，但为尽量降低未来引入 Workspace/Org 时的迁移成本，明确以下步骤。

### 7.1 未来迁移 6 个步骤

1. **新建 `workspaces` 表** — `(id, name, type ENUM('personal','team','division','company'), owner_user_id, parent_workspace_id NULL, created_at)`。
2. **为所有 user 自动创建 personal workspace** — backfill script。`name = "{user.name}'s workspace"`, `type='personal'`, `owner_user_id=user.id`。
3. **新增 `workspace_members` + 在资源表中增加 `workspace_id` 列** — 初始均允许 `NULL`。
4. **回填** — 根据每行 `user_id` 查询 personal workspace → 填充 `workspace_id` → 转为 NOT NULL。
5. **扩展权限模型** — `assert_can_read(resource, user, workspace)` 检查 workspace membership + role。`is_super_user` 保持 global admin 含义。
6. **UI 增加 workspace switcher** — 在侧边栏顶部增加 workspace dropdown，切换时 invalidate 所有 query。

### 7.2 当前要做的事（本 ADR 的适用范围）

- 新编写的 service layer 函数**必须统一签名，接收 user 对象（或 `CurrentUser`）作为参数**：`list_agents(db, user)`, `get_owned_agent(db, agent_id, user)`。这样未来只需把 `owner=TenantContext(user, workspace)` 替换为单一参数即可。
- `user_id` 列名**保持不变**（含义：“primary owner”）。避免 rename 成本。
- Router 中允许直接使用 `user.id`，但权限验证逻辑尽可能统一放到 service layer。

当前**不创建**新的表/列。

---

## 8. Consequences

### 8.1 Pros

- **确保隔离**：达到 production-ready 的隔离，User A 无法访问 User B 的资源。
- **成本安全**：System credential 仅限 super_user → 普通用户无法使用 operator LLM 密钥调用。
- **扩展 hook**：统一 service layer 接收 user 对象的签名 → 引入 Workspace 时只扩展签名。
- **标准模式**：HttpOnly cookie + CSRF + bcrypt + JWT — 符合 OWASP 建议。

### 8.2 Cons

- **新用户 onboarding 复杂度增加**：如果不注册自己的 LLM credential 就无法聊天。首次注册后的引导 modal/redirect UX 必须实现（Phase 7 处理）。
- **未实现邮箱验证**：MVP 中使用假邮箱也可注册。在 Phase 2 启用 SMTP + 验证 token 前，需要通过 operator 仅允许可信 domain 等方式运营。
- **缺少 OAuth**：没有 Google/GitHub 登录。Phase 2 前用户需自行管理密码。
- **移除 Mock user 带来一次性迁移成本**：需要运行脚本，把现有 PoC 数据迁移给首位 super_user。

### 8.3 Trade-offs

- **不使用 Redis** vs **DB whitelist**：Redis 更快，但优先简化基础设施。`refresh_tokens` 索引足以提供性能。
- **单一 `is_super_user` 标志** vs **RBAC 表**：优先简化 MVP。未来新增时 boolean → role enum 会产生一次迁移成本。
- **CSRF double-submit** vs **synchronizer token**：double-submit 是 stateless（服务端无需存储）→ 简化运营。

### 8.4 Risks & Mitigations

| 风险 | 严重度 | 缓解措施 |
|--------|--------|--------|
| Mock user → 新 super_user 迁移过程中数据丢失 | 高 | 编写带 transaction + dry-run 选项的 `backend/scripts/migrate_mock_to_real_user.py`。在 staging 验证 1 次后再应用到 production |
| 首位注册者被外部攻击者抢先占用并获得 super_user 权限 | **非常高** | (a) production 部署时 operator 立即注册，(b) 注册后立即改为 `ALLOW_FIRST_USER_AS_ADMIN=false`，(c) 或 production 直接通过 SQL 授权。`.env.example` 中明确警告 |
| Refresh token replay 攻击 | 中 | 轮换时 revoke 旧 token。检测到已 revoked token 再次使用时，批量撤销该 user 所有 refresh（强制重新登录） |
| 新用户未注册 LLM credential → 首次聊天失败 → 流失 | 中 | 注册后 onboarding modal + 创建第一个 agent 时若未注册 credential，则 redirect 到注册页面（Phase 7） |
| Cookie SameSite 配置错误导致 OAuth callback（Phase 2）失败 | 低（Phase 2 问题） | dev=lax，prod 若 same-origin 则 lax 也可。Phase 2 增加 OAuth 时评估 partitioned cookie |
| 其他 user 猜中 thread_id 并访问 LangGraph checkpoint | 低（UUID v4） | 在 router 层保持 conversation ownership 验证（已实现）。后续考虑为 thread_id 加 user_id prefix |
| 5 次失败锁定因用户忘记密码而产生 false positive | 低 | `locked_until = NOW + 15min`，避免永久锁定。Phase 2 启用密码重置后根本解决 |

---

## Appendix A — 验证清单

- [ ] `uv run alembic upgrade head` → `users` 新列、`refresh_tokens` 表、`tools.is_system`, `credentials.is_system` 全部存在。
- [ ] `uv run alembic downgrade -1 && uv run alembic upgrade head` 成功（idempotent）。
- [ ] 首位注册者 `is_super_user=TRUE`，第二位注册者 `is_super_user=FALSE`（直接查 DB）。
- [ ] User A 登录后查询 User B 资源 → 全部 404。
- [ ] 普通 user 未注册自己的 LLM credential 时，LLM 调用返回明确错误信息（"Add your own API key…"）。
- [ ] super_user 可以查询/管理 system credential。普通 user 被拒绝。
- [ ] Refresh token replay → 撤销全部 token + 401。
- [ ] Production: `cookie_secure=true`, `cors_allowed_origins` 限制为生产 domain, `JWT_SECRET` ≥ 32 字节随机值。
