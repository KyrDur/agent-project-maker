# CHECKPOINT — Multi-User Authentication

**Project Owner**: Satya
**Branch**: `feature/multiuser-auth`
**Plan**: `~/.claude/plans/replicated-crunching-lark.md` (approved)

---

## 核心决策事项 (User-Approved)

| 项目 | 选择 |
|------|------|
| token 存储 | HttpOnly Cookie (Access + Refresh) + CSRF body token |
| 认证算法 | JWT HS256 — Access 1h, Refresh 30d (DB whitelist) |
| 密码哈希 | bcrypt (passlib) |
| 权限模型 | `is_super_user` boolean 单一 flag |
| tenancy 单位 | User-only (Workspace 扩展 hook 通过 service layer 抽象化) |
| 认证方式 | Email + Password (Google OAuth 延后到 Phase 2) |
| System credentials | super_user 专用 (查询/使用/管理全部) |
| 首位注册者 | 自动成为 super_user |

---

## M1: silo setup (S0 + 删除分析 + 架构)
- [ ] S0 (Pichai): 编写 docs/design-docs/adr-016-multiuser-auth.md
- [ ] S1 (Bezos): tasks/deletion-analysis.md — Mock User 痕迹、seed 依赖、FK policy 矩阵
- [ ] S2 (Pichai): User/RefreshToken 模型 + Alembic 迁移 m22 spec
- 验证: `test -f docs/design-docs/adr-016-multiuser-auth.md && test -f tasks/deletion-analysis.md`
- done-when: 架构决策文档化 + 删除分析报告
- 状态: pending

## M2: 后端认证核心 (Phase 1 + 2 + 3)
- [ ] Jensen: 添加 User 列、RefreshToken 模型、Tool/Credential `is_system`、整理 FK ON DELETE
- [ ] Jensen: 编写 Alembic 迁移 m22 + backfill
- [ ] Jensen: `app/auth/{password,jwt,cookies}.py` 模块
- [ ] Jensen: 重写 `dependencies.py` (JWT-based `get_current_user`, `verify_csrf`, `require_super_user`)
- [ ] Jensen: `routers/auth.py` (register, login, logout, refresh, me) + rate limiting
- [ ] Jensen: `services/{auth_service,user_service}.py`
- 验证: `cd backend && uv run pytest tests/test_auth_*.py -v && uv run ruff check . && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- done-when: 所有认证 endpoint 工作，migration reversible，测试通过
- 状态: pending

## M3: seed 整理 + router audit (Phase 4 + 5)
- [ ] Jensen: 移除 main.py 自动创建 mock user
- [ ] Jensen: bootstrap → system credentials (is_system=True)
- [ ] Jensen: credential_service.list_for_user super_user 分支
- [ ] Jensen: tool_factory policy (普通 user 拒绝 system credential)
- [ ] Jensen: templates/models mutation 添加 require_super_user
- [ ] Jensen: 所有 mutation router 添加 CSRF 验证
- 验证: `cd backend && uv run pytest tests/test_csrf.py tests/test_multiuser_isolation.py -v`
- done-when: 隔离矩阵 7 个场景全部通过
- 状态: pending

## M4: 设计 + 前端认证 (Phase 7)
- [ ] Tim Cook: 登录/注册/侧边栏设计 spec (wireframe + 组件列表)
- [ ] Zuckerberg: `(auth)` route group + login/register 页面
- [ ] Zuckerberg: `lib/auth/{csrf,session}.ts` + useAuth hook + AuthGuard
- [ ] Zuckerberg: 修改 `lib/api/client.ts` — credentials:include, CSRF, 401 auto-refresh deduplication
- [ ] Zuckerberg: `middleware.ts` — 受保护 route + login/register 双向 redirect
- [ ] Zuckerberg: 侧边栏/header user 信息 + logout
- 验证: `cd frontend && pnpm build && pnpm lint`
- done-when: build 通过 + 手动登录 flow 工作
- 状态: pending

## M5: AI runtime 整理 + migration 脚本 (Phase 6 + 8)
- [ ] Jensen: 将 AgentConfig.user_id 设为必填
- [ ] Jensen: services/user_service.cleanup_user_resources (清理 LangGraph checkpoint)
- [ ] Jensen: 编写 scripts/migrate_mock_to_real_user.py
- 验证: `cd backend && uv run pytest tests/test_user_cleanup.py -v`
- done-when: 删除用户时连 conversation/checkpoint 一并清理，migration 脚本 dry-run 成功
- 状态: pending

## M6: 集成验证 + 安全检查 (Phase 9)
- [ ] Bezos: multi-user 隔离矩阵自动测试 (7 个场景)
- [ ] Bezos: CSRF mutation 测试
- [ ] Bezos: refresh token replay 检测测试
- [ ] Bezos: 安全 checklist (cookie secure, CORS, JWT secret, OWASP)
- [ ] Bezos: 更新 tasks/lessons.md + docs/QUALITY_SCORE.md
- 验证: `cd backend && uv run pytest -v && cd ../frontend && pnpm build && pnpm lint`
- done-when: 全部测试 green + 安全检查 PASS
- 状态: pending

## M7: 运营准备 + HANDOFF (Phase 10)
- [ ] Satya: 更新 `.env.example` (JWT secret, cookie 设置等)
- [ ] Satya: 加强 CORS 生产设置
- [ ] Satya: 编写 HANDOFF.md
- [ ] Satya: 在 docs/ARCHITECTURE.md 添加 multiuser 章节
- 验证: `test -f HANDOFF.md && grep -q multiuser docs/ARCHITECTURE.md`
- done-when: 下一会话可在无上下文情况下接手
- 状态: pending

---

## 🚦 milestone 依赖图

```
M1 (setup)
 ├── M2 (后端核心) ──┐
 │                      ├── M5 (AI runtime + migration)
 ├── M3 (seed + audit) ─┤
 │                      │
 └── M4 (FE) ───────────┴── M6 (集成验证) ── M7 (运营 + HANDOFF)
```

**可并行**: M1 完成后可并行推进 M2/M3/M4 (文件边界分离)
**Critical Path**: M1 → M2 → M5 → M6 → M7
