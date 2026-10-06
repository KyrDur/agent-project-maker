# CHECKPOINT — Backlog E M3 · PREBUILT per-user Connection

**分支**: `feature/prebuilt-per-user-connection`
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m3`
**base**: main @ `b34125d` (PR #54 merge — M2 完成)
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**: `docs/exec-plans/active/backlog-e-connection-refactor.md` (§4 M3)
**团队**: 皮查伊(Alembic m10 + 模型) + 詹森(chat_service PREBUILT 分支) + 扎克伯格(frontend dialog 重新布线) + 贝索斯(回归 + QA) — 萨提亚 lead

---

## scope 共识 (2026-04-18)

| 项目 | 决策 |
|------|------|
| scope | Backend + 全部 dialog 重新布线（提前部分 M5） |
| env fallback | 保留 (ADR-008 §11) — 没有 connection 时使用 settings.* 值 |
| mock user seed | 在 Alembic m10 数据迁移中自动 seed |
| Tool-Provider 映射 | 新增 `tools.provider_name` 列（仅 PREBUILT NOT NULL，其余 NULL） |
| `tools.credential_id` | 在 PREBUILT 中忽略（legacy fallback 保留到 M6） |

---

## S0: docs/ 结构确认 [done]

- [x] main 中存在 docs/、ADR-008、exec-plan
- 验证：`ls docs/design-docs/adr-008-connection-entity.md docs/exec-plans/active/backlog-e-connection-refactor.md`

## S1: deletion analysis（Bezos）[blockedBy: S0]

- [ ] 识别 M3 scope legacy 代码: `tools.credential_id` PREBUILT 路径, 3个 auth-dialog 重复
- [ ] `tasks/deletion-analysis-e-m3.md` 报告（立即删除 / 简化 / 暂缓到 M6）
- 验证：报告存在，遵守禁止 drive-by

## S2: Alembic m10 + tools.provider_name + Connection seed (皮查伊) [blockedBy: S0]

- [ ] `backend/alembic/versions/m10_prebuilt_connection_migration.py`
  - upgrade: 新增 `tools.provider_name` VARCHAR(50) nullable 列
  - upgrade: 将现有 PREBUILT tools 的 name → provider_name 映射 backfill
    - `Naver *` → `naver`
    - `Google Search`, `Google Image`, `Google News` → `google_search`
    - `Gmail *`, `Google Calendar *` → `google_workspace`
    - `Google Chat *` → `google_chat`
  - upgrade: mock user env 值(settings.naver_*, google_*) → credential → 自动 seed default connection
    - 若已存在同 provider 的 credential+default connection 则 skip（idempotent）
    - env 值为空则 seed skip
  - downgrade: 反向删除迁移创建的 connections(is_default=true AND user_id=mock) + credentials，并 drop provider_name 列
- [ ] `backend/app/models/tool.py` — 新增 `provider_name` Mapped 列
- [ ] `backend/app/seed/default_tools.py` — 新 PREBUILT tool seed 包含 `provider_name`
- 验证: alembic roundtrip PASS, pytest 585+ 回归 0, 验证新 mock user seed

## S3: chat_service PREBUILT 分支 + connection_service helper (詹森) [blockedBy: S2]

- [ ] 重写 `backend/app/services/chat_service.py:254-260` PREBUILT 分支
  - 新增: `tool.type == PREBUILT AND tool.provider_name` → connection query helper
    - default connection 优先 (user_id + type='prebuilt' + provider_name + is_default=true)
    - 若存在: `resolve_credential_data(conn.credential)` → cred_auth
    - 若不存在: env fallback (`cred_auth = {}` → 保持现有 settings.* 路径)
  - Legacy fallback: `tool.type == PREBUILT AND tool.provider_name IS NULL` → 现有 credential_id 路径（迁移 tolerance）
  - CUSTOM 分支保持现有 `tool.credential_id` 路径（M4 对象）
- [ ] `backend/app/services/connection_service.py` — 新增 `get_default_connection(db, user_id, type, provider_name)` helper (sync select → selectinload(credential))
- [ ] 扩展 `get_agent_with_tools` 预加载 user default connection（防止 N+1）
- [ ] Cross-tenant guard: 复用已实现的 `assert_connection_ownership` / `assert_credential_ownership`
- 验证: ruff PASS, 现有 PREBUILT 测试回归 0

## S4: Frontend dialog 重新布线 + /connections PREBUILT UI (扎克伯格) [blockedBy: S2] — DONE

- [x] 新增通用 shell `frontend/src/components/connection/connection-binding-dialog.tsx` — `{type:'prebuilt', providerName, toolName?, open, onOpenChange, onSaved?}` props。`useConnections({type, provider_name})` → 有现有 default connection 时 PATCH，没有则 POST(is_default=true)。复用 CredentialSelect + CredentialFormDialog。React 19 "render 中 setState + guard" 模式 hydration。
- [x] `frontend/src/components/tool/prebuilt-auth-dialog.tsx` → 缩减为 thin adapter。删除 detectProvider heuristic，useUpdateToolAuthConfig 调用 0。使用 `tool.provider_name`。为 null 时通过 TooltipProvider+disabled trigger 提示 `legacyUnavailable`。
- [x] `frontend/src/app/connections/page.tsx` — 新增 PrebuiltConnectionSection（保留现有 Credential 列表）。4个 provider 卡片 + 显示 default connection + "添加连接"按钮 → ConnectionBindingDialog。
- [x] 新增 `frontend/src/lib/api/connections.ts`（确认 M1 不存在），新增 `frontend/src/lib/hooks/use-connections.ts`（scope-wide invalidation）。在 `frontend/src/lib/types/index.ts` 增加 `Tool.provider_name`, ConnectionType/Status/McpAuthType/McpTransport, Connection, ConnectionCreateRequest, ConnectionUpdateRequest。
- [x] `messages/ko.json` — 新增 `connections.bindingDialog.*`, `connections.prebuiltSection.*`, `tool.authDialog.legacyUnavailable`。
- [~] custom-auth-dialog / mcp-server-auth-dialog — 按 S1 分析报告"禁止 drive-by"原则 scope out。延后到 M4(custom)/M5(mcp)。
- 验证: pnpm lint PASS (0 errors, 仅 pre-existing streamError warning), pnpm build PASS (typecheck + 14 static routes)。
- blocker（S5/S6 前需处理）: 在 `ToolResponse` schema 增加 `provider_name: str | None = None` — `backend/app/schemas/tool.py:64`。模型已有但 Pydantic serialization 遗漏 → runtime tool.provider_name=undefined → PrebuiltAuthDialog 全部落到 legacyUnavailable。需要1行 hotfix。

## S5: 回归 + 新增测试（Bezos）[blockedBy: S3, S4]

- [ ] 新增 `tests/test_connection_prebuilt_resolve.py`
  - 用2个 mock user 分别持有不同 connection 执行同一 PREBUILT tool → 验证各自 credential 应用
  - 验证没有 default connection 时仍保留 env fallback
  - 验证 legacy fallback(provider_name IS NULL)
- [ ] 更新 `tests/test_tools_router_extended.py`, `tests/test_naver_tool.py` 等现有 PREBUILT 测试回归
- [ ] Alembic m10 数据完整性测试（mock user seed idempotent）
- 验证: 保持 `uv run pytest` 585+ + 新增 PASS

## S6: 集成 + commit（Satya）[blockedBy: S5]

- [ ] 全量 verify: ruff + pytest + alembic roundtrip + pnpm build + /codex:review
- [ ] 更新 HANDOFF.md
- [ ] 单一 commit → PR

---

## 风险（M3 要点）

1. **tool.provider_name backfill 遗漏** — 现有 PREBUILT tool 中如果 name pattern 超出预期会保持 NULL，仅 legacy fallback 工作。解决: 迁移时对映射失败 row 输出 WARN log + 测试验证所有 seed tool 都有 provider_name。
2. **mock user seed 竞争** — 迁移中若同 provider 已有 connection 则 skip。采用"存在检查 + insert only"而非 upsert 模式。
3. **env fallback 路径回归** — 没有 connection 时 `cred_auth = {}`，现有 `settings.naver_*` 模式（build_naver_search_tool 内部）应继续工作。必须集成测试。
4. **Frontend ConnectionBindingDialog 集成难度** — 一次替换3个 dialog 回归风险。并行实现后一次替换。
5. **CUSTOM 不在 M3 scope 内** — 不要修改。`tool.credential_id` CUSTOM 路径将在 M4 迁移。
