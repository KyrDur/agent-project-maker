# CHECKPOINT — backlog E M4 · CUSTOM Connection 集成

**分支**：`feature/custom-connection-migration`
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m4`
**base**：main @ `44a39c6`（PR #55 merge — M3 完成）
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**：`docs/exec-plans/active/backlog-e-connection-refactor.md`（§4 M4）
**团队**：Pichai（Alembic m11 + model）+ Jensen（chat_service CUSTOM 分支 + connection_service CUSTOM helper）+ Zuckerberg（add-tool-dialog Custom tab rewire）+ Bezos（deletion analysis + 回归 + 新增测试）— Satya lead

---

## scope 共识 (2026-04-18)

| 项目 | 决策 |
|------|------|
| scope | 与 exec-plan §4 M4 完全一致（backend + 仅 add-tool-dialog Custom tab） |
| Legacy fallback | 保留到 M6 — `tool.connection_id IS NULL AND tool.credential_id` 存在时走原路径 |
| M5 范围（custom-auth-dialog 替换 / agent_tools.connection_id override） | 延后 — M4 不提前做 |
| CUSTOM Connection 形态 | `type='custom'`, `provider_name='custom_api_key'`（credential_registry），1 credential = 1 connection，N tools → 可共享 1 connection |
| migration policy（m11） | 对现有 `tools.credential_id IS NOT NULL AND type='custom'` row 每个都 idempotent 创建 connection + 设置 `tool.connection_id` FK。多个 tool 共用 1 个 credential 时复用同一 connection |

---

## S0: docs/ 结构确认 [done]

- [x] main 中存在 docs/、ADR-008、exec-plan
- [x] 已将 M3 progress.txt / CHECKPOINT.md 移到 tasks/archive/
- 验证：`ls tasks/archive/progress-backlog-e-m3.txt tasks/archive/checkpoint-backlog-e-m3.md`

## S1: deletion analysis（Bezos）[blockedBy: S0]

- [ ] 识别 M4 scope legacy code：CUSTOM 中经 `tool.credential_id` 的路径、`add-tool-dialog` custom tab 的 credential binding、`tools` router 中 CUSTOM credential update 路径
- [ ] `tasks/deletion-analysis-e-m4.md`（立即删除 / 简化 / 暂缓到 M6）
- 验证：报告存在，遵守禁止 drive-by

## S2: Alembic m11 + CUSTOM connection backfill（Pichai）[blockedBy: S0]

- [ ] `backend/alembic/versions/m11_custom_credential_migration.py`
  - revision ID：`m11_custom_connection`（≤32 字符，缩写 — 吸取 M3 PG VARCHAR(32) 经验）
  - `down_revision = "m10_prebuilt_connection"`
  - upgrade：CUSTOM 工具 migration backfill
    - 目标：`tools.type = 'custom' AND tools.credential_id IS NOT NULL AND tools.connection_id IS NULL`
    - 每个 (user_id, credential_id) tuple 创建 1 个 connection（`type='custom'`, `provider_name='custom_api_key'`, `display_name=credential.name`, `is_default=true`, `status='active'`, 设置 `credential_id` FK）
    - 多个引用同一 credential 的 CUSTOM tool 共用同一 connection（idempotent：如果已存在 `(user_id, type='custom', credential_id)` connection 则复用）
    - 设置对应 tool rows 的 `tool.connection_id` FK
    - 在 display_name 前加 `M11_SEED_MARKER = "[m11-auto-seed]"` prefix 供 downgrade 识别
  - downgrade：仅删除通过 `[m11-auto-seed]` marker 识别出的 connection（保护手动创建项）+ 清除对应 tool 的 connection_id FK
  - **注意**：不 drop `tool.credential_id`（legacy fallback 保留到 M6）。`tool.auth_config` 也保留
- [ ] **无需修改**：`app/models/tool.py` 的 `connection_id`/`connection` 已在 M2 添加 — 仅确认
- 验证：alembic round-trip PASS，pytest 614+ 回归 0，验证 idempotent rerun

## S3: 重写 chat_service CUSTOM 分支 + connection_service CUSTOM helper（Jensen）[blockedBy: S2]

- [ ] 重写 `backend/app/services/chat_service.py:393-396` CUSTOM else 分支
  - 新优先级：`tool.type == CUSTOM`
    1. `tool.connection_id IS NOT NULL AND tool.connection IS NOT NULL` → ownership guard（`assert_connection_ownership` + `assert_credential_ownership`）→ credential 解密。若 `tool.connection.status != 'active'` 或 `credential IS NULL` → `ToolConfigError`（与 PREBUILT M3 相同 fail-closed policy）
    2. Legacy fallback：`tool.connection_id IS NULL` → `_resolve_legacy_tool_auth(tool)`（保留现路径）— tolerance 到 M6
  - 新增 module-private helper：`_resolve_custom_auth(tool) -> dict[str, Any]`（M3 的 `_resolve_prebuilt_auth` 模式对称，private）
- [ ] `backend/app/services/connection_service.py` — 如确有需要则增加 CUSTOM helper（PREBUILT bulk helper 不可复用 — CUSTOM 是 tool 级 FK，已有 `selectinload(Tool.connection).selectinload(Connection.credential)` 解决。**很可能不需要**额外 helper，由 Jensen 判断）
- [ ] `get_agent_with_tools` 的 `selectinload(Tool.connection).selectinload(Connection.credential)` chain 已在 M2 配好 — **无需修改**
- 验证：ruff PASS，pytest 614+ 回归 0

## S4: frontend add-tool-dialog Custom tab rewire（Zuckerberg）[blockedBy: S2]

- [ ] `frontend/src/components/tool/add-tool-dialog.tsx` Custom tab
  - 当前行为：user 直接选择 credential → 保存到 `tool.credential_id`
  - 新行为：user 选择 credential → 若没有则通过 `CredentialFormDialog` 创建 → find-or-create 绑定该 credential 的 CUSTOM connection（`useConnections({type:'custom', provider_name:'custom_api_key'})` + 按 credential_id filter）→ 创建 tool 时包含 `connection_id`
  - Legacy fallback 兼容：现有基于 `credential_id` 的 tool 继续显示（直到 M6 drop）
- [ ] `frontend/src/lib/api/tools.ts` / `frontend/src/lib/types/index.ts` — `Tool.connection_id` 已在 M2 添加。确认 `ToolCreateRequest` 传递 `connection_id?` field，缺失则新增
- [ ] i18n `messages/ko.json` — 增强 `tool.addDialog.custom.*` message（connection 创建 UX）
- [ ] **scope out**：替换 `custom-auth-dialog.tsx`（M5）、替换 `mcp-server-auth-dialog.tsx`（M5）、`/connections` 页面 CUSTOM section（M5）。遵守 S1 分析的"禁止 drive-by"原则
- 验证：pnpm lint PASS，pnpm build PASS

## S5: 回归 + 新增测试（Bezos）[blockedBy: S3, S4]

- [ ] 新增 `tests/test_connection_custom_resolve.py`
  - user_A/B 隔离：在同一 CUSTOM tool 定义下，分别走各自 connection.credential（CUSTOM 不是共享 row，而是 tool 级，因此验证 per-tool user_id 隔离）
  - connection_id 存在且 active + 有 credential → 正常解密
  - connection_id 存在且 status='disabled' → `ToolConfigError`
  - connection_id 存在且 credential=NULL → `ToolConfigError`
  - connection_id=NULL（legacy）+ credential_id → 保持现有路径
  - connection_id=NULL + credential_id=NULL + auth_config → 返回 inline auth
  - ownership mismatch (connection.user_id ≠ credential.user_id) → `ToolConfigError`
- [ ] `tests/test_tools_router_extended.py` — 回归验证 CUSTOM tool response 中 `connection_id` field
- [ ] Alembic m11 idempotent + downgrade guard（M9/M10 precedent：`inspect.getsource` helper source contract）
- 验证：`uv run pytest` 保持 614+ + 新增 PASS

## S6: 集成 + commit（Satya）[blockedBy: S5]

- [ ] 全量 verify：ruff + pytest + alembic round-trip + pnpm lint + pnpm build
- [ ] /codex:review
- [ ] 更新 HANDOFF.md（M4 完成，下一个 = M5）
- [ ] 单一 commit → PR

---

## 风险（M4 要点）

1. **credential 共用 → connection 1 个** — 多个 CUSTOM tool 引用同一 credential 时，必须共享 1 connection，而不是 N connection。m11 必须按 `(user_id, credential_id)` dedup。
2. **带 `user_id` 的 CUSTOM row** — CUSTOM tool 的 `user_id NOT NULL`（不像 PREBUILT 那样 `is_system=True` 共享 row）。ownership guard 实际生效。
3. **Legacy fallback 路径回归** — `tool.connection_id IS NULL AND credential_id IS NOT NULL` 场景对应 M3 前创建的 CUSTOM tool。必须测试。
4. **add-tool-dialog Custom tab UX** — find-or-create 模式按 React Query invalidation timing + 无 optimistic update 基准实现。复用 Zuckerberg M3 模式。
5. **m11 revision ID 32 字符限制** — PG alembic_version VARCHAR(32)。`m11_custom_connection`（21 字符）OK。
6. **禁止 M5 drive-by** — 绝对不要改 custom-auth-dialog.tsx / mcp-server-auth-dialog.tsx / `/connections` 页面。

---

## 验证命令

```bash
cd backend
uv run ruff check .
uv run pytest tests/test_connection_custom_resolve.py -v
uv run pytest                           # 保持 614+
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head             # round-trip PASS

cd ../frontend
pnpm lint
pnpm build
```
