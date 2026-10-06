# Operator Setup — 生产环境设置检查清单

这是生产部署前必须通过的环境变量设置。以 `APP_ENV=production`
启动时，服务器会直接校验；若存在任何问题将**拒绝启动**
（参见 `app/security/production_check.py`）。

ADR-016 §8.4 / HANDOFF #2.

---

## 1. 必需环境变量

| 变量 | 生产值 | 生成命令 |
|------|---------|-----------|
| `APP_ENV` | `production` | — |
| `JWT_SECRET` | 32+ 字符随机字符串 | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `true` | —（必须 HTTPS） |
| `ALLOW_FIRST_USER_AS_ADMIN` | `false` | 创建管理员账户后立即设置 |
| `CORS_ALLOWED_ORIGINS` | 实际前端 origin，以逗号分隔 | 示例: `https://moldy.example.com,https://staging.moldy.example.com` |
| `ENCRYPTION_KEYS` | 64 字符 hex key（逗号分隔） | `python -c "import secrets; print(secrets.token_hex(32))"` |

可选:
- `COOKIE_DOMAIN` — 需要 subdomain 共享时（`.moldy.example.com`）
- `COOKIE_SAMESITE` — 需要 cross-site fetch 时设为 `none`（但强制 `COOKIE_SECURE=true`）

---

## 2. 生产校验

若要在部署前手动执行相同校验:

```bash
APP_ENV=production python -c "
from app.config import settings
from app.security.production_check import enforce_production_safety
enforce_production_safety(settings)
print('OK — production settings clean')
"
```

如有问题，会以可操作的消息输出哪个变量为何错误。

---

## 3. 拒绝启动示例

`APP_ENV=production` 但以 `COOKIE_SECURE=false` 尝试启动:

```
RuntimeError: Refusing to start with insecure production settings:
  - COOKIE_SECURE=false. Set true so browsers refuse to send auth
    cookies over plain HTTP.
Fix the above and restart, or set APP_ENV=dev to bypass
(local development only).
```

---

## 4. 首个管理员账户 bootstrap

仅在启用 `ALLOW_FIRST_USER_AS_ADMIN=true` 时自动提权有效。
管理员账户创建流程:

1. 临时以 `ALLOW_FIRST_USER_AS_ADMIN=true` + `APP_ENV=dev` 启动
2. 通过 `/api/auth/register` 创建 1 个管理员账户 — 自动设为 `is_super_user=true`
3. 立即以 `ALLOW_FIRST_USER_AS_ADMIN=false` + `APP_ENV=production` 重启
4. 此后注册的所有 user 均为普通用户。授予 super_user 由管理员通过 DB / admin API 手动操作

---

## 5. Migration

```bash
cd backend
uv run alembic upgrade head
```

（merge 含 schema 变更的 PR 后始终执行）

---

## 6. 相关文档

- `docs/design-docs/adr-016-multiuser-auth.md` — 认证/session 整体设计
- `backend/.env.example` — 完整变量列表 + inline 注释
- `backend/app/security/production_check.py` — 校验逻辑（single source）
