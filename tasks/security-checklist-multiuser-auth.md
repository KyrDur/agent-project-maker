# Security Checklist — ADR-016 Multi-user Auth

验证日期：2026-05-09
验证者：bezos（S7 集成验证）
分支：`feature/multiuser-auth`

---

## 1. Cookie 安全

| 项目 | 状态 | 备注 |
|------|------|------|
| Access cookie `httponly=True` | PASS | `app/auth/cookies.py:52` |
| Refresh cookie `httponly=True` | PASS | `app/auth/cookies.py:57` |
| CSRF cookie `httponly=False` | PASS | double-submit 模式，JS read 必需 — 有意设置 |
| `cookie_secure` config 开关 | PASS | dev=False（HTTP），prod=True 必须由运维设置（`config.py:120`） |
| `cookie_samesite` 默认 `lax` | PASS | 阻断 cross-origin POST |
| Cookie max_age == JWT exp | PASS | 防止僵尸状态（`cookies.py:52`） |

**运维操作必需**：在 `.env` 设置 `COOKIE_SECURE=true` + 合适的 `COOKIE_DOMAIN`。若未设置，即使在 HTTPS 环境中也会缺少 `Secure` flag。

---

## 2. CORS

| 项目 | 状态 | 备注 |
|------|------|------|
| `allow_origins` 不是 wildcard | PASS | `main.py:226` 显式 域（`localhost:3000`） |
| `allow_credentials=True` | PASS | cookie flow 必需 |
| `expose_headers` 最小化 | PASS | 仅 `X-Run-Id`, `X-Resume-Mode` |

**运维操作必需**：生产部署时将 `main.py:226` 的 hard-coded origins 改为基于 `settings.cors_allow_origins` 环境变量 — 当前写死 dev origin，如果生产 域 不同将无法工作（或需要新 代码 PR）。

---

## 3. JWT

| 项目 | 状态 | 备注 |
|------|------|------|
| `JWT_SECRET` 环境变量独立 | PASS | `config.py:110`，代码硬编码 X |
| Dev fallback (ephemeral) 警告 日志 | PASS | `auth/jwt.py:58-64` WARNING 日志 |
| HS256 算法 | PASS | 单后端 → 对称密钥 OK |
| 令牌 type 区分（`access`/`refresh`/`csrf`） | PASS | decode 时验证 `expected_type` |
| Refresh 令牌保存 SHA-256 hash | PASS | DB leak 时令牌本身暴露 X |
| Required claims (`exp`, `iat`, `sub`, `type`, `jti`) | PASS | `decode_token` `options.require` |

**运维操作必需**：生产环境 deploy 前，将 `JWT_SECRET` 设置为至少 32 byte 的随机环境变量（`openssl rand -base64 48`）。若未设置，每次进程重启都会使所有会话失效。

---

## 4. Rate Limiting

| 项目 | 状态 | 备注 |
|------|------|------|
| `/register` rate limit | PASS | `5/hour` (`routers/auth.py:53`) |
| `/login` rate limit | PASS | `10/minute` (`routers/auth.py:81`) |
| `/refresh` rate limit | PASS | `30/minute` (`routers/auth.py:128`) |
| `/logout` rate limit | NONE | 注销 abuse 攻击面小 — 可接受 |
| Public share endpoint | PASS | `60/minute` per IP |

**运维建议**：`slowapi` 的 in-memory storage 在多 工作进程 环境中会按 工作进程 分开计数。生产建议改为 Redis 后端。

---

## 5. Password / 账号保护

| 项目 | 状态 | 备注 |
|------|------|------|
| bcrypt cost factor 12 | PASS | `auth/password.py:31`（OWASP 2023 建议） |
| 使用 `passlib` CryptContext | PASS | 支持 算法 swap 的结构 |
| 缓解 Timing attack（dummy verify） | PASS | unknown email 也会调用 verify（`auth_service.py:107`） |
| Min password length 8 | PASS | `schemas/auth.py:15` |
| Failed login counter | PARTIAL | **BUG**：计数器增加未 commit（escalation 1） |
| Account lockout（5 次 → 15 分钟） | PARTIAL | **BUG**：同一 root cause 导致 lockout 不工作（escalation 1） |

---

## 6. Refresh Token 安全

| 项目 | 状态 | 备注 |
|------|------|------|
| Refresh rotation on each use | PASS | 正常路径已验证（test_auth_refresh） |
| Replay 401 响应 | PASS | 立即拒绝 |
| Replay 时 mass-revoke 活跃令牌 | PARTIAL | **BUG**：AppError 前 revoke 未 commit（escalation 2） |
| DB whitelist 验证（`token_hash`） | PASS | unique index，scalar 查询 |
| Expiry 验证（`expires_at <= now`） | PASS | 401 invalid_refresh |

---

## 7. CSRF

| 项目 | 状态 | 备注 |
|------|------|------|
| Double-submit（header == cookie） | PASS | 7/7 测试通过 |
| Bootstrap endpoints exempt | PASS | register/login/refresh — 用户不存在 |
| GET/HEAD/OPTIONS exempt | PASS | safe methods |
| Cross-account CSRF token 拒绝 | PASS | `sub` claim 与 user.id 比较 |
| Garbage token 拒绝 | PASS | InvalidTokenError → 403 |

---

## 8. 权限分离（RBAC）

| 项目 | 状态 | 备注 |
|------|------|------|
| `require_super_user` gate | PASS | 6 个 端点（system-credentials × 5, models POST/PATCH/DELETE × 3） |
| 普通 user 访问 system credential | PASS | 403（测试验证） |
| 普通 user 执行 model mutation | PASS | 403（测试验证） |
| First user 自动 super_user | PASS | `allow_first_user_as_admin` 开关 |

**运维操作必需**：运维账号注册后立即在 `.env` 将 `ALLOW_FIRST_USER_AS_ADMIN=false`。若不修改，一旦因事故导致 DB 为空，下一个注册用户会成为 super_user。

---

## 9. Multi-user Isolation Matrix (10/10 PASS)

| 场景 | 结果 | 响应 |
|----------|------|------|
| User B → User A's agent GET | PASS | 404（not 403，阻断 enumeration oracle） |
| User B → User A's agent PUT/DELETE | PASS | 404 |
| Agent list per-user filter | PASS | B 是空列表 |
| User B → User A's trigger PUT/DELETE | PASS | 404 |
| 普通 user → /api/system-credentials GET | PASS | 403 |
| 普通 user → /api/system-credentials POST | PASS | 403 |
| Super_user → /api/system-credentials GET | PASS | 200 |
| 普通 user → /api/models POST | PASS | 403 |
| User B → User A's agent usage | PASS | 404 或空 aggregate |
| User B → User A's conversation PATCH/DELETE | PASS | 404 |

---

## 10. User Deletion / Cleanup (8/8 PASS)

- LangGraph thread 删除 per conversation: PASS
- 保留其他 user 的 thread：PASS
- Active refresh tokens revoke: PASS
- Checkpointer unavailable 时也执行 refresh revoke：PASS
- 删除 User row → agent CASCADE：PASS
- 保留 System credential（`user_id=NULL`）：PASS
- RefreshToken FK CASCADE: PASS
- Unknown user_id no-op: PASS

---

## OWASP Top 10 自检

| 类别 | 结果 | 备注 |
|----------|------|------|
| A01 Broken Access Control | PASS | super_user 防护 + service-level owner filter |
| A02 Cryptographic Failures | PASS | bcrypt cost 12, JWT HS256, refresh token hash storage |
| A03 Injection | PASS | SQLAlchemy ORM（无 raw SQL） |
| A04 Insecure Design | NOTE | Audit log 只有 `actor_user_id` — 没有行为本身的 immutable trail（Phase 2 后续） |
| A05 Security Misconfiguration | RISK | `cookie_secure`/`cors_allow_origins` 依赖运维设置（见上文 部分 1, 2 的运维 操作） |
| A06 Vulnerable Components | DEFER | dependency scan 是单独 CI 问题 |
| A07 Auth Failures | **PARTIAL** | replay defense + lockout 都有 commit 漏掉的 错误（escalation 1, 2） |
| A08 Software Integrity Failures | PASS | JWT signature 验证，CHECK constraint |
| A09 Logging Failures | PASS | `logger.warning` on replay, `actor_user_id` audit |
| A10 SSRF | N/A | 未识别出用户可直接 触发器 server-side URL fetch 的路径 |

---

## ESCALATION 项（萨提亚 → 代码 owner）

### Escalation 1 — Login failure 计数器 未 提交（CRITICAL）

**症状**：`auth_service.authenticate` 在密码错误时调用 `record_login_failure(db, user)` 后立即 raise `AppError`。路由器 只在 success path 调用 `db.commit()`，因此 计数器 增加会 回滚。

**影响**：`failed_login_attempts` 永久为 0 → 5 次 lockout 实际不工作。可无限 brute-force。

**修改位置**：`backend/app/routers/auth.py` `login_endpoint` 或 `services/user_service.py` `record_login_failure`。

**建议 fix**：让 `record_login_failure` 在独立 short-lived session 中执行，或在 路由器 中用 `try/except AppError` 包裹，commit 后再 re-raise。

**测试**：`tests/test_auth_login.py::test_wrong_password_returns_401_and_increments_counter`（xfail strict）。修复后移除 `xfail` 装饰器。

### Escalation 2 — Refresh replay mass-revoke 未 提交（CRITICAL）

**症状**：`auth_service.rotate_refresh` 检测到 replay 时发出 `_revoke_all_active(db, user_id)` UPDATE 后 raise `AppError`。路由器 漏 commit，导致 mass-revoke 回滚。

**影响**：即使被盗 refresh token 泄漏，victim 的 active 会话 也不会自动失效。ADR-016 §5.2 的核心安全决定被架空。

**修改位置**：同上（在 `auth_service.rotate_refresh` 内 `await db.commit()` 后 raise，或由 路由器 处理）。

**测试**：`tests/test_auth_refresh.py::test_refresh_replay_revokes_all_active`（xfail strict）。

---

## 运维 deploy 前必做 3 项

1. **将 `JWT_SECRET` 设置为至少 32 byte 的随机环境变量。** 若未设置，使用 ephemeral 键 时 令牌 会在每次重启后失效。
2. **设置 `COOKIE_SECURE=true` + 明确 `COOKIE_DOMAIN`。** 即使在 HTTPS 环境中，未设置也会导致 cookie 缺少 `Secure` flag，暴露于 MITM。
3. **合并 上述 2 项 ESCALATION 修复 + 移除 `xfail` 装饰器 后确认回归测试通过。** 若未修复就 deploy，brute-force/refresh 令牌 被盗防御会失效。

补充建议：
- 首个运维账号注册后立即将 `.env` 中 `ALLOW_FIRST_USER_AS_ADMIN=false`，关闭 开关。
- 将 `main.py:226` 的 `allow_origins` 改为基于环境变量（当前 硬编码 dev origin）。
- 将 `slowapi` rate-limit storage 改为 Redis（多 工作进程 环境）。
