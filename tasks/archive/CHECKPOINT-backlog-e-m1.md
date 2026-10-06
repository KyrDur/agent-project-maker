# CHECKPOINT — backlog E M1 · Connection table + CRUD API

**分支**：`feature/connections-table`
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m1`
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**：`docs/exec-plans/active/backlog-e-connection-refactor.md`
**开始**：2026-04-18
**团队**：Pichai（architect）+ Jensen（实现）+ Bezos（QA）— Satya lead

---

## S0: docs/ 结构确认

- [x] 已存在 `docs/`, `docs/design-docs/`, `docs/exec-plans/active/` 结构
- [x] ADR-008 已存在（已 merge 到 main）
- 验证：`ls docs/ARCHITECTURE.md docs/design-docs/index.md docs/design-docs/adr-008-connection-entity.md`
- done-when：3 个文件全部存在
- 状态：**done**（预先存在）

## S1: deletion analysis（Bezos）

- [ ] 识别 M1 scope 中可删除/简化候选（禁止 drive-by）
- [ ] 编写 `tasks/deletion-analysis-e-m1.md` 报告
- 验证：报告存在 + 结论明确为"删除 X 条，简化 Y 条，暂缓 Z 条"格式
- done-when：Satya 批准
- 状态: pending
- 负责人：Bezos

## S2: Connection model + schema + Validator（Pichai）

- [ ] 新建 `backend/app/models/connection.py` — ADR-008 §1 schema（user_id NOT NULL, type/provider_name/display_name/credential_id/extra_config/is_default/status/created_at/updated_at，index `(user_id, type, provider_name)`）
- [ ] 新建 `backend/app/schemas/connection.py` — `ConnectionCreate`, `ConnectionUpdate`, `ConnectionResponse`
  - `provider_name` validator：type='prebuilt' 时限制为 credential_registry enum 5 种，否则为英文/数字/下划线字符串
  - MCP validator：`extra_config.url` 必填
- [ ] 在 `backend/app/models/__init__.py` export Connection
- 验证：`cd backend && uv run ruff check app/models/connection.py app/schemas/connection.py && uv run python -c "from app.models import Connection; from app.schemas.connection import ConnectionCreate"`
- done-when：ruff PASS + 无 import cycle
- 状态: pending
- 负责人：Pichai
- blockedBy: S0

## S3: Service + Router + Migration（Jensen）

- [ ] `backend/alembic/versions/m8_add_connections.py` — upgrade：创建 table + index，downgrade：drop
- [ ] `backend/app/services/connection_service.py` — CRUD + `is_default` 原子 toggle（同一 user_id+type+provider_name scope 内清除原 default）
- [ ] `backend/app/routers/connections.py` — `GET /api/connections`, `GET /api/connections/{id}`, `POST /api/connections`, `PATCH /api/connections/{id}`, `DELETE /api/connections/{id}`（全部按 `get_current_user` filter）
- [ ] `backend/app/main.py` — 注册 router
- 验证：`cd backend && uv run ruff check . && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- done-when：round-trip PASS，ruff PASS
- 状态: pending
- 负责人：Jensen
- blockedBy: S2

## S4: 测试（Bezos）

- [ ] 新建 `backend/tests/test_connections.py` — ADR-008 §M1 的 8 个测试场景：
  1. CRUD 基础（credential 连接 + NULL）
  2. MCP validator（没有 extra_config.url 时 422）
  3. PREBUILT validator（non-enum provider_name 时 422）
  4. 自动设置 is_default（第一个 connection）
  5. is_default toggle 原子性（自动取消原 default）
  6. 防 IDOR（user_A 访问 user_B resource 时 404）
  7. credential ON DELETE SET NULL
  8. extra_config 类型不匹配（给 PREBUILT 时 warning/ignore）
- [ ] 全量回归 pytest PASS（保持 545+）
- 验证：`cd backend && uv run pytest tests/test_connections.py -v && uv run pytest`
- done-when：新增 8 场景通过 + 现有回归 0
- 状态: pending
- 负责人：Bezos
- blockedBy: S3

## S5: 集成 + commit（Satya）

- [ ] 全量 verify：ruff + pytest + alembic round-trip PASS
- [ ] 更新 HANDOFF.md
- [ ] 单一 commit
- 验证：`git log --oneline feature/connections-table ^main`
- done-when：commit 存在，verify PASS
- 状态: pending
- 负责人：Satya
- blockedBy: S4
