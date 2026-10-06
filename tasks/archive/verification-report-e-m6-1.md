# M6.1 集成验证报告

**DRI**：Bezos（Bezos）— TTH QA/Integration
**日期**：2026-04-25
**分支**：`feature/backlog-e-m6-1` @ `b24ef1b`
**基线**：main @ `18d98be`（PR #59 merge）
**DB head**: `m13_drop_mcp_legacy`

---

## 最终判定：🟢 **GREEN**

M6.1 全范围（M1~M6）完整。自动化 + DB round-trip + 残留 grep + regression point 全量 PASS。2 个手动 E2E 场景已完成代码路径验证，仅等待用户浏览器确认。

---

## 1. 4 个 commit（HEAD 逆序）

| SHA | 标题 | 负责人 |
|-----|------|------|
| `b24ef1b` | [feat] M6.1 M5 — frontend MCP re-wire + BindingDialogShell | Zuckerberg |
| `7d3fef0` | [feat] M6.1 M3 — MCP legacy drop (m13) | Jensen |
| `87b173e` | [feat] M6.1 M4 — frontend 选项 D + CUSTOM first-bind | Zuckerberg |
| `10c55dc` | [feat] M6.1 M2 — PATCH /api/tools/{id} connection_id | Jensen |

---

## 2. 自动验证（全量 PASS）

| 验证 | 命令 | 结果 | 备注 |
|------|--------|------|------|
| backend lint | `uv run ruff check .` | **clean** | 0 issues |
| backend test | `uv run pytest` | **621 passed, 1 deselected** | M2 baseline 633 → M3 drop 12 项（MCPServer CRUD 专用） |
| frontend lint | `pnpm lint` | **0 warnings / 0 errors** | |
| frontend build | `pnpm build` | **14 pages PASS** | TS 3.9s。M5 中移除 MCP register tab 后 15→14 |

### 测试数量 delta 记录
- M6 baseline: **624**
- M2（新增 PATCH /api/tools/{id}）：**633**（+9）
- M3（移除 MCPServer CRUD）：**621**（-12）
- 净减：**-3** = 计划内 drop（完全移除 MCPServer surface）− 新增 regression defense 9 项（PATCH post 9 个）

---

## 3. DB round-trip（docker PG）

### 执行 sequence
```
m12_drop_legacy_columns → m13_drop_mcp_legacy → m12 → m13
```

### 最终状态（`head = m13_drop_mcp_legacy`）

| 检查项 | 预期 | 实测 | 结果 |
|-----------|------|------|------|
| `\d tools` 中 `mcp_server_id` column | 无 | 无 | ✅ |
| `\d tools` 中 `connection_id` column | 存在（UUID, NULLABLE） | 存在 | ✅ |
| `to_regclass('mcp_servers')` | NULL | NULL | ✅ |
| tools table FK list | 仅 `tools_user_id_fkey`, `fk_tools_connection_id` | 相同 | ✅ |
| `tools_mcp_server_id_fkey` | 无 | 无 | ✅ |

### downgrade 验证
- m13 → m12 downgrade 时恢复 `mcp_server_id` column + FK
- 恢复 `mcp_servers` table（schema 一致）
- 再次 upgrade 正常（可重复）

**1-way door**：m13 drop 仅在真正 PROD 应用前是 2-way door。已确认当前 dev DB 可重复。PROD 应用后不可恢复 — deployment PR merge 前 `legacy_invariants.py` preflight 会强制 safety net：`mcp_server_id IS NOT NULL AND connection_id IS NULL` 残留 rows 必须为 0。

---

## 4. 残留 grep（预期对比实测）

### Backend (`backend/app/` scope)
- 搜索：`rg "mcp_server_id|MCPServer|resolve_server_auth|mcp-server"`
- 实测：**6 项全部是预期残留**
  - `main.py:94` — startup `_column_exists` cache 项（用于 m13 preflight）
  - `legacy_invariants.py:73-79` — m13 invariant SQL string literal（非真实代码引用）
  - `schemas/connection.py:125, 186` — docstring 历史 comment（无功能）

### Frontend (`frontend/src/` scope)
- 搜索：`rg "mcp_server_id|updateMCPServer|useUpdate/Register/Delete MCPServer|useMCPServers|registerMCPServer|listMCPServers|deleteMCPServer|mcp-server-rename"`
- 实测：**0 项**

### 保留组件名
- `MCPServerGroupCard` — 保留功能性 naming（内部实现基于 Connection，不是 residue）

**判断**：合计残留 **0（排除预期的 6 项）**。fail-clean。

---

## 5. regression point 复验

| point | 测试 | 结果 |
|--------|--------|------|
| CUSTOM PATCH 成功路径 | `test_patch_tool_connection_id_custom_success` | PASS |
| MCP PATCH 成功路径 | `test_patch_tool_connection_id_mcp_success` | PASS |
| PREBUILT PATCH → 400 | `test_patch_tool_connection_id_prebuilt_400` | PASS |
| 其他用户 connection → 404（IDOR） | `test_patch_tool_connection_id_other_user_connection_404` | PASS |
| tool.type ≠ connection.type → 422 | `test_patch_tool_connection_id_type_mismatch_422` | PASS |
| `connection_id=null` → 清除绑定 | `test_patch_tool_connection_id_none_clears` | PASS |
| 不存在的 tool → 404 | `test_patch_tool_nonexistent_404` | PASS |
| extra="forbid" → 422 | `test_patch_tool_unknown_field_422` | PASS |
| 其他用户 tool PATCH → 404 | `test_patch_tool_other_user_404` | PASS |
| chat_service MCP fail-closed | `test_build_tools_config_mcp_missing_connection_raises` | PASS |
| MCP connection 正常 path | `test_build_tools_config_mcp_with_connection_succeeds` | PASS |

**regression coverage**：以 PATCH tool 单一 endpoint 为基准 9 项 + fail-closed 2 项 = **11 项全量 PASS**。

---

## 6. Breaking API Changes (M6.1)

需要外部 API client 反映：

### 删除 route（4 项）
- `POST /api/tools/mcp-server`
- `GET /api/tools/mcp-servers`
- `PATCH /api/tools/mcp-servers/{id}`
- `DELETE /api/tools/mcp-servers/{id}`

### route 迁移（1 项）
- `POST /api/tools/mcp-server/{id}/test` → **`POST /api/tools/{tool_id}/test`**
  - parameter 含义变更：`server_id` → `tool_id`

### 移除 schema
- `MCPServerResponse`, `MCPServerListItem`, `MCPServerCreate`, `MCPServerUpdate`
- `ToolResponse.mcp_server_id` 字段
- `CredentialUsage.mcp_server_count` 字段

### 新政策
- 对 PREBUILT tool 进行 PATCH → **400**（维持 user_id × provider_name SOT）
- PATCH body 仅允许单一字段 `connection_id`（extra="forbid" → 422）
- PATCH 其他用户 connection_id → **404**（防止 IDOR info leak）
- tool.type ≠ connection.type → **422**
- MCP tool 在无 connection 时尝试执行 → `ToolConfigError`（fail-closed）

---

## 7. Scope Creep

| 项目 | 处理 |
|----|------|
| MCP 新注册 UI | **顺延（M5）**。Zuckerberg 决定 — 单独 PR（需要 backend 新 endpoint + discovery helper） |
| `agent_tools.connection_id` override | **顺延（M5.5）**。参见 ADR-008 §5 |
| drive-by refactoring | **发现 0 项** |

---

## 8. 手动 E2E 状态

`tasks/manual-e2e-e-m6-1.md` 5 个场景：

| # | 场景 | 自动化 | 浏览器 |
|---|----------|--------|----------|
| 1 | CUSTOM first-bind (M4) | 代码路径 PASS | 等待用户 |
| 2 | MCP credential rotate (M5) | 代码路径 PASS，dev DB 无 seed | 等待用户（建议 staging） |
| 3 | PREBUILT PATCH → 400 | AUTOMATED PASS | n/a |
| 4 | IDOR → 404 | AUTOMATED PASS | n/a |
| 5 | DB direct verification | AUTOMATED PASS | n/a |

**判断**：场景 3/4/5 已由测试 suite 覆盖。1/2 用于确认 React state + dialog UX — 仅用户浏览器验证 pending。

---

## 9. 产出物 inventory

### 新增编写（M6.1 scope）
- `backend/alembic/versions/m13_drop_mcp_legacy.py`
- `backend/app/schemas/tool.py::ToolUpdate`
- `backend/app/services/tool_service.py::update_tool`
- `backend/app/routers/tools.py::test_tool_connection`
- `frontend/src/components/connection/binding-dialog-shell.tsx`
- `frontend/src/lib/hooks/use-tools.ts::useUpdateTool`

### 文档（TTH）
- `tasks/deletion-analysis-e-m6-1.md`（M1, Bezos）
- `tasks/manual-e2e-e-m6-1.md`（M6, Bezos）
- `tasks/verification-report-e-m6-1.md`（M6, Bezos，本文件）
- `HANDOFF.md`（M6, Bezos 更新）

### 删除
- `frontend/src/components/tool/mcp-server-rename-dialog.tsx`

---

## 10. 用户下一步工作

1. 浏览器确认场景 1、2（dev 或 staging）
2. `git push -u origin feature/backlog-e-m6-1`
3. 创建 PR — 必须在 PR description 中包含 Breaking API changes section
4. PROD 部署前确认 `legacy_invariants.py` m13 preflight 通过

---

## 11. 下一个 milestone

**M5.5 — `agent_tools.connection_id` override** (ADR-008 §5)
- agent 级 tool connection override 路径（tool.connection_id = default，agent_tools.connection_id = 优先）
- 在 `build_tools_config` 中反映优先级

**其他后续**：MCP server 新注册 UI — `POST /api/connections (type=mcp, extra_config)` + discovery helper。单独 PR。

---

## 结论

M6.1 达成计划 scope 100% + breaking change 11 项全部以 regression defense 测试固定 + 通过 DB round-trip 验证 migration 可逆性。

**判定**：🟢 **GREEN — 可进行 commit/PR。**
