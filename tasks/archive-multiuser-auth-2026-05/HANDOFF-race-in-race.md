# HANDOFF — #2b race-in-race fix 完成

**Branch**: `fix/refresh-token-race-in-race` (PR 未创建)
**Date**: 2026-05-18
**最新 commit**: `de61260` [refactor] is_postgres helper + 将初始 SELECT 整合为 FOR UPDATE
**Status**: ✅ #2b 实现 + simplify 完成，等待创建 PR

---

## 上一会话完成

### PR 合并完成
- #154 — Refresh-token race fix
- #155 — 生产环境启动安全 setup 验证
- #156 — RefreshToken GC nightly cron
- #157 — Frontend auth simplify 合集 (#7-12)
- #158 — next/navigation 全局 mock (#12a)
- #159 — csrfStore 整合 (#12b)

### #2b — race-in-race chain divergence 加强 (等待 PR)
- `_lock_select(stmt, db)`: 应用 Postgres `SELECT FOR UPDATE` 的 helper (SQLite no-op)
- `rotate_refresh`: chain-walk loop (`_MAX_CHAIN_FOLLOW=5`) — 加锁后重新验证 → live/race/replay 分支。锁竞争失败的一侧沿 chain 前进 1 hop 后重试 → 无 orphan active row
- 添加 `is_postgres(db)` helper (app/database.py)，移除 spend_writer 重复
- 将初始 SELECT 与 FOR UPDATE 整合 → hot path RTT 减少 1 次
- 新增测试: chain depth limit 模拟 (monkeypatch cycle)
- ADR-016 §4.2 明确 lock policy + chain-walk 行为
- 2 个 commit: `c4953a9` 功能, `de61260` simplify

---

## 剩余任务

### 🟢 后续工作 (可暂缓)
2c. **GC DELETE batch 处理** — `ctid IN ... LIMIT N` loop。**S. 检测到运营 backlog 时。**
**🆕 oauth2_base 可能缺少 FOR UPDATE** — `backend/app/credentials/oauth2_base.py:5` 注释中明确 "caller 负责 SELECT FOR UPDATE"，但实际实现尚未确认。OAuth token 并发 refresh 可能未串行化。simplify review 中发现。**S. 调查 + 加强。**
**🆕 streaming.py 基于类型的分支整理** — 将 `msg.type in (...)` 字符串检查部分替换为 `isinstance(msg, AIMessageChunk)` 等基于类型的方式。分支数量等同，可读性/类型安全性↑。影响: `streaming.py` ~行 289-360。**XS.**

### 🟢 deepagents 0.6 后续 track
~~3. `stream_events(version="v3")` migration~~ — **废弃 (2026-05-18)**。`streaming.py:273` 已使用 LangGraph 官方推荐的 `astream(stream_mode="messages")`，v3 为 beta + 对未使用 callback event 的代码无收益 + 分支数等同。依据: `langchain_core/runnables/base.py:1495` (v3 仅 BaseChatModel/CompiledGraph，experimental)。可能的小整理拆分到上面的 🆕 项。
3. **`_collect_checkpoints` Phase 2 并行化** — `asyncio.gather` + semaphore。**M.**
4. **评估引入 CodeInterpreterMiddleware**。**M.**
5. **将 WittyLoadingMessage workaround 正式化** — 追踪 assistant-ui remount 原因。**M.**

### 🟣 Phase 2 (长期，单独 track)
13. **Google OAuth 登录** — **L.**
14. **电子邮件验证 + 密码重置** — **L.**

---

## 已知限制

- **race-in-race 真实并发验证** — SQLite 测试环境限制。需要单独 Postgres 集成测试 (ADR-016 §4.2 中已明确)。
- **GC batch 未拆分** — retention=1d 正常运营时无影响。

---

## 相关文件

| 区域 | 文件 |
|------|------|
| 认证 (#1 PR #154) | `backend/app/services/auth_service.py`, `backend/app/models/refresh_token.py`, `backend/alembic/versions/m37_*.py` |
| 运营验证 (#2 PR #155) | `backend/app/security/production_check.py`, `backend/app/main.py` (lifespan), `docs/operator-setup.md` |
| GC (#2a PR #156) | `backend/app/services/refresh_token_gc.py`, `backend/app/scheduler.py` (`_register_cron_job`), `backend/alembic/versions/m38_*.py` |
| Frontend simplify (#7-12 PR #157) | `frontend/src/lib/api/errors.ts`, `frontend/src/lib/auth/session-gate.ts`, `frontend/src/lib/api/client.ts`, `frontend/src/lib/sse/parse-sse.ts`, `backend/alembic/versions/m39_*.py` |
| Test mocks (#12a PR #158) | `frontend/tests/setup.ts`, 3 个 override 文件 |
| csrfStore (#12b PR #159) | `frontend/src/lib/auth/csrf.ts`, 4 consumer |
| race-in-race (#2b) | `backend/app/services/auth_service.py` (chain-walk + `_lock_select`), `backend/app/database.py` (`is_postgres`), `backend/app/services/spend_writer.py` |
| policy 文档 | `docs/design-docs/adr-016-multiuser-auth.md` |

---

## 最后状态

- 验证: backend **972 PASS** / ruff clean, frontend **286 PASS** / lint clean / build OK
- working tree: 干净 (`fix/refresh-token-race-in-race` 分支, 2-commit)
- 生产 Postgres: m37 + m38 + m39 migration 已应用
- **推荐下一项**: 🟢 调查 oauth2_base FOR UPDATE (S, 紧接上一个 PR) 或 deepagents track #3 (`_collect_checkpoints` 并行化, M)

开始新会话:
1. 读取此文件
2. 创建 + 合并 PR
3. 通过 `/sync` 返回 main
4. 选择下一项工作
