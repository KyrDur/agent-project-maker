# CHECKPOINT — backlog E M2 · MCP → Connection migration（高风险）

**分支**：`feature/connection-mcp-migration`
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m2`
**base**：main @ `29678a1`（PR #53 merge）
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**：`docs/exec-plans/active/backlog-e-connection-refactor.md`（M2 section）
**团队**：Pichai（architect/migration）+ Jensen（chat_service/runtime）+ Bezos（回归 + QA）— Satya lead

---

## S0: docs/ 结构确认

- [x] main 中存在 docs/、ADR-008、exec-plan
- 验证：`ls docs/design-docs/adr-008-connection-entity.md docs/exec-plans/active/backlog-e-connection-refactor.md`
- 状态：**done**（预先存在）

## S1: deletion analysis（Bezos）

- [ ] 识别 M2 scope 中可删除的 legacy code
- [ ] `tasks/deletion-analysis-e-m2.md` 报告
- 验证：报告存在，并明确"立即删除 / 简化 / 暂缓"
- 状态: pending
- 负责人：Bezos
- blockedBy: S0

## S2: Alembic m9 + tools.connection_id（Pichai）

- [ ] `backend/alembic/versions/m9_migrate_mcp_to_connections.py`
  - upgrade：新增 `tools.connection_id` UUID nullable FK `connections.id` ON DELETE SET NULL column
  - upgrade：每个 `mcp_servers` row → `connections` row（type='mcp', provider_name=server.name, display_name=server.name, credential_id=server.credential_id, extra_config={url, auth_type, headers?, env_vars?}）
  - upgrade：将 `tools.mcp_server_id` → 映射到匹配的 `tools.connection_id`
  - downgrade：反向映射 tools.connection_id 值，删除 connections 中 type='mcp' row，drop column
- [ ] `backend/app/models/tool.py` — 新增 `connection_id` Mapped column + `connection` relationship。`mcp_server_id` 仅加 deprecate comment（drop 在 M6）
- 验证：`cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` round-trip PASS + 现有 pytest 回归 0
- 状态: pending
- 负责人：Pichai
- blockedBy: S0

## S3: 重写 chat_service MCP 分支 + env_vars template 解析（Jensen）

- [ ] 重写 `backend/app/services/chat_service.py:164-205` MCP 分支 — 通过 `tool.connection_id` → `connections`
- [ ] `backend/app/agent_runtime/` MCP 执行部分（`mcp_client.py` 或 `executor.py`）— 使用 connection.extra_config.url/auth_type/headers
- [ ] env_vars template resolver — 检测 `${credential.<field>}` 时替换为 credential.data_decrypted[field]（runtime only）
- [ ] legacy fallback：若 `tool.connection_id IS NULL AND tool.mcp_server_id IS NOT NULL`，继续使用现有 mcp_servers 路径（M3~M5 过渡期安全网）。M6 删除
- 验证：ruff + 现有 MCP 回归 PASS
- 状态: pending
- 负责人：Jensen
- blockedBy: S2

## S4: 回归 + 新增测试（Bezos）

- [ ] 更新 `tests/test_mcp_connection.py`, `tests/test_tools_router_extended.py` 回归
- [ ] 新增 `tests/test_connection_mcp_resolve.py` — 通过 connection 执行 MCP smoke + 验证 env_vars template 解析
- [ ] migration 数据完整性测试
- 验证：`uv run pytest` 回归 0（保持 572+）+ 新增 PASS
- 状态: pending
- 负责人：Bezos
- blockedBy: S3

## S5: 集成 + commit（Satya）

- [ ] 全量 verify：ruff + pytest + alembic round-trip + /codex:review
- [ ] 更新 HANDOFF.md
- [ ] 单一 commit
- 状态: pending
- blockedBy: S4

---

## 风险（M2 高风险点）

1. **数据迁移完整性**：mcp_servers row 无遗漏迁移到 connections
2. **chat_service regression**：hot path，会立即影响现有 MCP 工具执行
3. **env_vars template 一致性**：遵守 ADR-008 §2 template-only
4. **mcp_servers.auth_config 保留策略**：明文值是迁到 extra_config 还是提升为 credential，由 Pichai 判断
