# Multi-User Auth — 代码 review 结果

**对象**：`feature/multiuser-auth`（uncommitted，76 files vs main 52fd954）
**范围**：ADR-016 backend/frontend/scripts/tests
**reviewer**：Claude Code（senior reviewer agent）
**日期**：2026-05-08

---

## 优点

1. **transaction boundary 与 ADR-016 §5 完全一致**。`auth_service.authenticate` 的 failure counter commit（line 131）、`rotate_refresh` 的 replay mass-revoke commit（line 220）都通过 comment 明确意图，且 ESCALATION 后续 fix 已准确反映。

2. **隔离 oracle 一致性**。`credential_service.list_for_user`/`get_for_user` 强制 `is_system=False`，router 的 `_load_owned` 对 ownership/不存在两种情况均返回同样 404（line 105）。防止 enumeration oracle。

3. **DB invariant 在 m36 中编码为 CHECK constraint**。`(is_system=false) OR (user_id IS NULL)` — 即使发生 application bug，也由 DB 阻止。credential service 的 `create()` 也用 ValueError 预先验证相同 invariant。

4. **Refresh token security model 稳健**。DB 仅存 SHA-256 hash（line 31），partial index `WHERE revoked_at IS NULL`（m36 line 199），replay 检测 → mass-revoke 均与 ADR-016 §4.2 匹配。

5. **CSRF double-submit + sub 一致性验证**（`dependencies.py:142-165`）。不仅比较 header==cookie，还验证 JWT type=csrf + sub=user.id 一致 — 阻止 forwarded cookie attack。

6. **test coverage 覆盖隔离矩阵**。login（5 类）、refresh（6 类 — 包含 replay/expired/unknown）、CSRF（7 类 — 包含 wrong subject）、multiuser_isolation 311 行、user_cleanup 267 行。足以作为 regression guard。

---

## Critical 问题

**无。** ESCALATION 2 项后续 fix 均已准确反映，未发现同类潜在 bug（其他函数 transaction boundary 遗漏）。

regression review：
- `register` → 在 `register_endpoint` commit 1 次（router line 70）。失败时 rollback 正常。
- `revoke_refresh` → flush only（service line 265），router commit（auth.py:122）。正常。
- `_revoke_all_active` → caller `rotate_refresh` 负责 commit。正常。
- `record_login_success` → flush only，router commit。正常。

---

## High 问题

### H1. CSRF header 比较不是 constant-time（信息泄漏风险低）
- 文件：`backend/app/dependencies.py:158`
- 问题：直接比较 `header != cookie`。两者都是 attacker-controlled JWT，真正 gate 是 JWT signature 验证，因此实质 oracle 不存在。但按 security code convention 推荐 `secrets.compare_digest`。
- 建议：
  ```python
  import secrets
  if not header or not cookie or not secrets.compare_digest(header, cookie):
      raise AppError(code="csrf_mismatch", ...)
  ```
- 优先级：merge 后 follow-up 即可。

### H2. OAuth2 callback 无 CSRF 验证，依据 cookie 决定 user_id
- 文件：`backend/app/routers/credentials.py:552-602`
- 问题：`oauth2_callback` 信任 `_OAUTH_STATE` 的 `user_id` 来更新 credential。state token 为 32-byte random，不可猜且外部 IdP 会 echo state，因此实际安全。但以 `actor_user_id=cred.user_id` 写 audit（line 596）— state 被篡改时（低概率）可能写入错误 user 的 credential。
- 建议：state 验证后增加检查 `pending["user_id"]` 与 `cred.user_id` 是否一致。
- 优先级：已明确为 PoC-grade，因此可 merge，运营 migration 前再次确认。

### H3. `templates.py` 无认证 guard
- 文件：`backend/app/routers/templates.py:17-29`
- 问题：所有 template 均 unauthenticated。如果 seed data 本来就是有意公开则 OK，但也可能是 ADR-016 §6.1 — "现有 router 保持可编译" 的 unintended consequence。
- 需确认：若有意公开，在 ADR/HANDOFF 明确。若无意，新增 `get_current_user`。

### H4. register router 在 register 失败时未 commit（理论上无害）
- 文件：`backend/app/routers/auth.py:67-70`
- 问题：`auth_service.register` 创建 user 后只 flush，若不 raise 则由 router 的 `db.commit()`（line 70）处理。但当 `register` 自身 raise `email_already_exists` 时不会调用 commit，transaction 保持 dangling — FastAPI dependency 会在 generator finalize 时 rollback，因此实际 safe。显式 commit/rollback 更稳健。
- 建议：register service 本身保持 flush only，commit 由 router 负责 — 当前即可。无需修改。

---

## Minor 改进

### M1. `_resolve_secret` 的 ephemeral key 是 module-level cache
- 文件：`backend/app/auth/jwt.py:51-67`
- 问题：以 function attribute cache。multi-process（gunicorn workers）环境中每个 worker 有不同 ephemeral key — 用户在 worker A 登录后被路由到 worker B 会 401。已有 WARNING log，因此问题已知。
- 建议：WARNING log 增加 "do not run multiple workers without JWT_SECRET"。

### M2. `RefreshToken.created_at` 与 `issued_at` 重复
- 文件：`backend/app/models/refresh_token.py:34, 50`
- 问题：两个 column 都是 `now()` server_default。若意图不同则重复。
- 建议：移除一个，或明确不同含义（例如 `created_at` 是 row 创建，`issued_at` 是 token 签发 — 明确 rotate 时是否更新）。

### M3. `cleanup_user_resources` 的 datetime 是 naive
- 文件：`backend/app/services/user_service.py:166`
- 问题：`datetime.now(UTC).replace(tzinfo=None)` — DB 为 `DateTime(timezone=True)`。SQLAlchemy 会自动转换，但其他位置（`auth_service.py:179`）使用 tz-aware。建议统一为 tz-aware。

### M4. Frontend `proxy.ts` 仅验证 cookie 是否存在
- 文件：`frontend/src/proxy.ts:24`
- 问题：只看 `moldy_rt` cookie 是否存在。过期 cookie 也能通过 redirect — 到 `/login` 后 `/me` 401 再 redirect 的 UX 不够友好。但 browser 不会发送过期 cookie，因此实际影响很小。
- 用 comment 明确意图（line 17 "Cookie-based gate"）即可。

### M5. `client.ts` 的 `sessionExpiredFired` 1 秒 reset 可能有 race
- 文件：`frontend/src/lib/api/client.ts:81-83`
- 问题：1 秒后将 `sessionExpiredFired = false` reset。在此期间并发大量 request 401 → refresh 失败 → 因不会再次调用同一 handler，所以当前行为 OK。但依赖 setTimeout 较 fragile。
- 建议：在 handler 内 unmount/navigation 完成后显式 reset 的 callback 模式更稳健。

### M6. `LoginForm`/`RegisterForm` 输入长度限制与 backend Pydantic 部分一致
- 文件：`frontend/src/components/auth/RegisterForm.tsx:80`（`maxLength={80}`）vs `backend/app/schemas/auth.py:16`（`max_length=100`）
- 问题：name 80 vs 100 — 不是威胁，但 frontend 更严格，用户无法输入到 100 字符。建议统一 backend 100。

### M7. Migration script `--delete-source` 后缺少 LangGraph checkpoint 清理
- 文件：`backend/scripts/migrate_mock_to_real_user.py:138-144`
- 问题：通过 raw SQL DELETE source user — 未调用 `cleanup_user_resources`。因此 mock user 的 conversation checkpoint 会留在 LangGraph DB。conversation 本身会随 agents CASCADE 删除 → orphan checkpoint。
- 建议：在 `_delete_source` 前调用 `user_service.cleanup_user_resources(db, source)`。或使用 `delete_user`。

---

## 安全自查（OWASP）

- **A01 Broken Access Control**：✓ — 所有 router 都有 `get_current_user` + ownership 验证（`get_for_user`, `get_owned_conversation`）。super_user 分支一致应用于 model catalog/system credentials。tool_factory 阻止 system credential 泄漏（line 192-200）。
- **A02 Cryptographic Failures**：✓ — bcrypt rounds=12（OWASP 2023），要求 HS256 + 32-byte secret，refresh token 存储 SHA-256 hash。仅 dev ephemeral key 是有意 fallback。
- **A03 Injection**：✓ — 所有 query 都使用 SQLAlchemy parameterized。`migrate_mock_to_real_user.py` 的 `text(f"... {table} {column}")`（line 117-129）虽为 f-string，但仅来自 whitelist（`_REASSIGN_TABLES`），因此安全。
- **A05 Security Misconfiguration**：✓ — `cookie_secure=False` 是 dev default，production 必须改为 `true`（config.py:120 comment）。需在 HANDOFF 明确。
- **A07 Identification and Authentication Failures**：✓ — 失败 5 次锁定 15 分钟，refresh rotation + replay → mass-revoke，JWT type 验证，统一 "invalid_credentials" message 防止 enumeration（`authenticate` line 105-112）。
- **A08 Software and Data Integrity Failures**：✓ — JWT signature 验证，refresh token DB whitelist（伪造 token 因 hash 不存在被拒绝）。
- **A09 Logging Failures**：仅 comment — 检测 replay 时 WARNING（auth_service:211），super_user 自动提升 INFO（line 82）。正常登录无 audit row — 仅记录 `last_login_at`。运营中追踪 brute force 可能需要单独 audit table。（Phase 2 reservation）
- **A10 SSRF**：不适用 — auth flow 无外部 fetch。OAuth2 callback 仅处理 IdP 发送的 code，无 attacker URL fetch。

---

## regression 可能性（ESCALATION 同类 grep）

`grep -B3 "raise AppError" auth_service.py | grep "commit"` — transaction boundary commit 出现在 raise 前的两个位置，均是预期 fix：
- line 131 (authenticate failed counter)
- line 220 (refresh replay mass-revoke)

其他 service 文件中 grep "raise … 前 commit 遗漏" 模式：
- `user_service.py`：所有 mutator 均 flush only — router 负责 commit。正常。
- `credentials/service.py`：相同模式，audit_log 始终依赖 router commit。正常。

**无同类潜在 bug。** ESCALATION fix 已准确应用在核心两处，其他函数本来就是 router-level commit 模式，因此无问题。

---

## 最终判定

### **CONDITIONAL GO**

**依据**：
- Critical 问题 0 项。ESCALATION 2 项后续 fix 验证完成。
- High 4 项 — 都不足以阻塞 merge，但运营前需再次确认。
  - H2 加强 OAuth callback state 验证（明确为 PoC-grade）
  - H3 确认 templates 认证政策意图
- OWASP 安全自查全部通过。
- test coverage（1102 LoC across 6 files）覆盖 isolation matrix + replay + CSRF 强制。

**merge 条件**：
1. H3（templates router 认证政策）在 ADR/HANDOFF 明确 — confirm 是有意公开。
2. M7（migration script 缺少 LangGraph cleanup）登记 follow-up ticket。
3. 运营部署前通过 `cookie_secure=true`, `JWT_SECRET`（>=32 bytes）, `allow_first_user_as_admin=false` checklist。

**Follow-up（单独 PR）**：
- 应用 H1 `secrets.compare_digest`
- H2 OAuth callback state user_id 一致性验证
- M1 加强 multi-worker WARNING message
- M5 改进 sessionExpired race 模式
- M6 统一 LoginForm/RegisterForm maxLength
