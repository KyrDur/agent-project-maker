# CHECKPOINT — backlog E M6 · Cleanup（backend drop + legacy 删除）

**分支**：`feature/backlog-e-m6`
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m6`
**base**：main @ `ad8c0fd`（PR #58 merge — M5 UI 集成 + F 吸收）
**ADR 参考**：`docs/design-docs/adr-008-connection-entity.md`
**执行计划参考**：`docs/exec-plans/active/backlog-e-connection-refactor.md`（§5 M6）
**团队**：Bezos（deletion analysis + 回归）+ Pichai（migration 设计）+ Jensen（backend 实现）+ Zuckerberg（frontend type/API thin cleanup）— Satya lead

---

## scope 共识 (2026-04-21，用户批准 — 2 次缩减)

**缩减原因**：Bezos S1 分析确认 `connection-binding-dialog.tsx:479` 仍在实时调用 `useUpdateMCPServer`。M5 有意将 option D 推迟到 M6，但用户决定把 option D 再拆到 M6.1 → 无法 drop `mcp_servers` 相关内容 → M6 **仅 drop auth_config/credential_id/agent_tools.config**。

| 项目 | 决策 |
|------|------|
| M6 scope | **缩减 cleanup** — drop `tools.auth_config` + `tools.credential_id` + `agent_tools.config`。MCP 相关暂缓 |
| drop `mcp_servers` table | **暂缓 → M6.1**（需 option D 前置） |
| drop `tools.mcp_server_id` | **暂缓 → M6.1** |
| `credential_service.resolve_server_auth` | **保留** — MCP 路径仍在使用 |
| `chat_service` MCP legacy fallback | **保留** — 仍需要 MCP resolve |
| `chat_service` CUSTOM bridge override | **删除** — 随 `tool.credential_id` drop 一并处理 |
| `chat_service` `merged_auth` agent_tools.config merge | **删除** |
| option D (PATCH tools connection_id) | 暂缓 → M6.1 |
| M5.5 (agent_tools.connection_id override) | M6.1 之后 |
| 新增 frontend 功能 / redesign | 禁止 |

---

## M6 删除目标（缩减 scope locked）

**DB schema (m12)**
- drop `tools.auth_config` column
- drop `tools.credential_id` column + FK
- drop `agent_tools.config` column

**DB schema（M6 保留）**
- `tools.mcp_server_id` (live via MCPServer CRUD)
- `mcp_servers` table
- `fk_tools_mcp_server_id`

**backend code 删除**
- `chat_service.py` CUSTOM bridge override（tool.credential_id != connection.credential_id 分支）
- `chat_service.py` `merged_auth = {**cred_auth, **(link.config or {})}` → 仅保留 `cred_auth`
- 从 `chat_service.py` `_resolve_legacy_tool_auth` 删除 CUSTOM 分支 → fail-closed ToolConfigError。MCP/BUILTIN 分支保留（mcp 暂缓）— 若按 S1 指引可以整体删除则移除
- `schemas/agent.py` `ToolConfigEntry` / `tool_configs` / `agent_config`（frontend dead transmit）
- `agent_service.py` tool_configs 处理 block
- `agent_runtime/assistant/tools/write_tools.py` `update_tool_config` + `read_tools.py` config 返回
- `schemas/tool.py` `ToolResponse.auth_config` + `_mask_auth_config`
- `models/tool.py` `Tool.auth_config` / `Tool.credential_id` / `Tool.credential` relationship / `AgentToolLink.config`

**backend code 保留（M6.1 处理）**
- `credential_service.resolve_server_auth()` + 调用处
- `chat_service.py` MCP legacy fallback block
- `tool_service.py` MCPServer CRUD 4 种
- `routers/tools.py` `/api/tools/mcp-server*` 4 个 endpoint
- `schemas/tool.py` `MCPServerCreate`/`MCPServerResponse` + `ToolResponse.mcp_server_id`
- `models/tool.py` `MCPServer` class + `Tool.mcp_server`/`mcp_server_id`

**frontend thin cleanup**
- `lib/api/tools.ts` 的 `updateAuthConfig` 中删除 `auth_config`/`credential_id` 传递（函数本身是否 dead 由 S4 判断）
- `lib/types/*.ts` 中从 `Tool` 删除 `auth_config`/`credential_id`，从 `AgentTool` 删除 `config`
- `Tool.mcp_server_id` type **保留**（live）
- MCP 相关 hook（`useUpdateMCPServer` 等）**保留**
- 引用处仅删除 or type-narrow

---

## S0: M5 archive + 新 progress state 初始化 [Satya] — 完成

- [x] M5 progress.txt/CHECKPOINT.md/AUDIT.log → `tasks/archive/*-backlog-e-m5.*`
- [x] 初始化新的 CHECKPOINT.md, progress.txt, AUDIT.log

## S1: deletion analysis（Bezos）[blockedBy: S0]

- [ ] 编写 `tasks/deletion-analysis-e-m6.md`
  - 精确确认删除目标到**文件:行**级别
  - 分类为**删除(D) / 简化(S) / 保留(K)** tag
  - 确定 `agent_tools.config` merge 逻辑（`chat_service.py:445`）处理方案：
    - 再确认 `tools_config` 注入路径是否使用该 field
    - 若正在使用，则提出替代路径 or scope 缩减建议
  - 区分测试文件"整体删除" vs "仅删除 legacy 场景"
- [ ] **阻止 scope creep**：明确 option D / UI refactor / M5.5 变更 0 条
- 验证：报告存在，注明文件:行，禁止 drive-by

## S2: m12 migration 设计（Pichai）[blockedBy: S0]

- [ ] 编写 `docs/design-docs/m6-cleanup-migration-spec.md`
  - upgrade 顺序：FK drop → column drop → table drop
  - downgrade strategy：明确**仅恢复结构，数据不可恢复**
  - pre-check query：`SELECT count(*) FROM tools WHERE credential_id IS NOT NULL AND connection_id IS NULL` → 期望 0
  - model layer 变更 spec
- [ ] m12 revision ID convention: `m12_drop_legacy_columns`
- 验证：设计文档存在，Jensen 阅读后可直接实现

## S3: backend legacy code 删除（Jensen）[blockedBy: S1, S2]

- [ ] 新建 `backend/alembic/versions/m12_drop_legacy_columns.py`
- [ ] `models/tool.py`：删除 MCPServer class + Tool legacy FK/关系 + AgentToolLink.config
- [ ] `services/credential_service.py`：删除 `resolve_server_auth()`
- [ ] `services/chat_service.py`：删除 MCP legacy fallback / CUSTOM bridge override / agent_tools.config merge
- [ ] `services/tool_service.py`：删除 MCPServer CRUD 4 种
- [ ] `routers/tools.py`：删除 `/api/tools/mcp-server*` 4 个 endpoint
- [ ] `schemas/tool.py`：删除 MCPServerCreate/Response + ToolResponse legacy field + `_mask_auth_config`
- [ ] `agent_runtime/`：清理 legacy field 引用
- [ ] 测试：仅删除 MCP legacy 场景（保留 connection path 测试）
- 验证：`uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` PASS，ruff PASS，pytest PASS（允许数量减少后 0 regression）

## S4: frontend dead API/type 删除（Zuckerberg）[blockedBy: S3 schema 决定]

- [ ] `lib/api/tools.ts`：删除 MCPServer CRUD 4 种 + updateAuthConfig legacy field
- [ ] `lib/types/*.ts`：删除 Tool/AgentTool legacy field
- [ ] type 引用处：仅**删除** build error 暴露的位置（禁止新增逻辑）
- [ ] 不要处理 `use-chat-runtime.ts:74` 的 streamError unused warning（现有 debt）
- 验证：`pnpm lint`（除现有 1 条外 0），`pnpm build` PASS

## S5: 集成验证 + manual 回归（Bezos）[blockedBy: S3, S4]

- [ ] `tasks/manual-e2e-e-m6.md` 5 个场景
  1. PREBUILT connection → Naver tool → agent 执行
  2. CUSTOM connection → user tool → agent 执行
  3. MCP connection → MCP tool → agent 执行
  4. 禁用 Connection → fail-closed error
  5. 直接查 DB：`SELECT * FROM mcp_servers` → relation does not exist
- [ ] pytest / ruff / pnpm lint / pnpm build 全部 PASS
- 验证：全绿，manual E2E 5/5 PASS

## S6: HANDOFF.md + 单一 commit（Satya）[blockedBy: S5]

- [ ] HANDOFF.md 反映 M6 状态（更新 M5.5 / M6.1 roadmap）
- [ ] 再确认全量 verify
- [ ] 单一 commit → push 交由用户

---

## 风险

1. `agent_tools.config` merge 逻辑 — S1 必须再次确认实际使用情况
2. FK drop 顺序错误 — 确认 credential_id/mcp_server_id FK ondelete
3. pre-check 数据缺失 — 若存在 `credential_id IS NOT NULL AND connection_id IS NULL` row，则 migration 失败
4. 测试删除过多 — 禁止损失 connection path 回归覆盖
5. frontend type cascade — grep 所有引用处后删除
6. downgrade 不可恢复 — 在 production guide 中明确

---

## 验证命令

```bash
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1 && uv run alembic upgrade head
uv run ruff check .
uv run pytest

cd ../frontend
pnpm lint
pnpm build

# schema 验证（production PostgreSQL）
psql -U moldy -d moldy -c "\d tools"
psql -U moldy -d moldy -c "\d agent_tools"
psql -U moldy -d moldy -c "SELECT to_regclass('mcp_servers')"

# legacy 痕迹 grep（期望 0）
rg "mcp_server_id|auth_config|resolve_server_auth" backend/app/
rg "MCPServer|register_mcp_server" backend/app/
```
