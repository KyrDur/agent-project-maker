# 删除分析报告 — Backlog E M4 · CUSTOM Connection 整合

**负责人**：贝索斯（QA/DRI）
**Scope**：exec-plan §4 M4 — `tool.credential_id` → `tool.connection_id` 路径迁移（仅 CUSTOM）
**原则**：禁止 drive-by。到 M6 为止保留 legacy fallback。不触碰 M5 范围（custom-auth-dialog / mcp-server-auth-dialog / `/connections` 页面 CUSTOM section）。
**先例**：M3 贝索斯分析文档（`tasks/archive/progress-backlog-e-m3.txt` 的 `[2026-04-18T08:45]` 项）— PREBUILT 同样分为 3 类（立即删除 1 / 简化 6 / 暂缓 12）。M4 范围更窄。

---

## TL;DR

- **可立即删除：0 项。** M4 是在现有路径（credential_id）之上增加新路径（connection）的扩展迁移阶段。因为 scope 协议要求 legacy fallback（`tool.connection_id IS NULL AND tool.credential_id IS NOT NULL`）保留到 M6，所以 CUSTOM 中没有可拆除代码。
- **简化：3 项** — S3/S4 实现时自然吸收的结构性建议。不拆成单独 PR。
- **暂缓（移交 M6）：5 项** — `_resolve_legacy_tool_auth` 的 CUSTOM 路径、drop `tool.credential_id`/`tool.auth_config` 列、`PATCH /tools/{id}/auth-config` 的 `credential_id` 处理、`ToolCustomCreate.credential_id` 字段、`useUpdateToolAuthConfig` hook。
- **移交 M5（仅记录现状）：3 项** — `custom-auth-dialog.tsx`、`mcp-server-auth-dialog.tsx`、`/connections` 页面 CUSTOM section。

---

## 1. 可立即删除

**无。**

**原因**：
- ADR-008 §11 + scope 协议（2026-04-18）— `tool.connection_id IS NULL AND tool.credential_id IS NOT NULL` 路径必须在 M6 cleanup 前有效。M3 进入前创建的 CUSTOM tool 会处于该状态，m11 backfill 失败或 rollback 的 row 也通过此路径在 runtime 恢复。
- `tool.auth_config`（inline secret）路径也为 CUSTOM 以外的 legacy 数据保留。M4 删除会破坏现有用户的 tool 执行。

**含义**：
> M4 不是 "删除"，而是**新增路径 + 指定优先级**。实际删除工作在 M6 中统一执行。

---

## 2. 简化建议

### [S-1] chat_service.py — CUSTOM 分支对称 helper（Jensen S3 中实现）

**当前**（`chat_service.py:393-396`）：
```python
else:
    # CUSTOM / BUILTIN 等其余项。在 M4 将 CUSTOM 迁移为经由 connection 之前
    # 保持现有 semantic（credential → auth_config → {}）。
    cred_auth = _resolve_legacy_tool_auth(tool)
```

**建议**：
- 新建 module-private helper `_resolve_custom_auth(tool) -> dict[str, Any]` — 与 `_resolve_prebuilt_auth`（M3）**结构对称**。
- 分支顺序：
  1. `tool.connection_id IS NOT NULL AND tool.connection IS NOT NULL` → ownership guard → `conn.status != 'active'` 或 `conn.credential IS NULL` → `ToolConfigError`（fail-closed）→ credential 解密
  2. `tool.connection_id IS NULL` → `_resolve_legacy_tool_auth(tool)`（tolerance 到 M6）
- 与 PREBUILT 不同，**不存在** "connection 无 = env fallback" 路径 — CUSTOM 没有 env。必须在 helper docstring 中明确这一 semantic 差异。
- `build_tools_config` 的 `elif tool.type == ToolType.CUSTOM:` 分支缩成 `_resolve_custom_auth(tool)` 1 行 → 从 CUSTOM/BUILTIN 混合 `else` 分支中取出 CUSTOM，提升为明确 elif。

**效果**：`_resolve_legacy_tool_auth` 保留到 M6，但其定位从 CUSTOM 的 "正常路径" 明确变成 "迁移 tolerance"。M6 中可同时删除 `_resolve_custom_auth` 内 legacy 分支和 `_resolve_legacy_tool_auth` 本身。

### [S-2] frontend add-tool-dialog.tsx — 将 find-or-create 封装在 dialog 内（Zuckerberg S4 中实现）

**当前**（`add-tool-dialog.tsx:50, 97`）：
```tsx
const [customCredentialId, setCustomCredentialId] = useState<string>(CREDENTIAL_NONE)
// ...
...(customCredentialId !== CREDENTIAL_NONE ? { credential_id: customCredentialId } : {}),
```

**建议**：
- `customCredentialId` state 保持为 dialog **内部状态**（UX 不变 — user 选择 credential 或新建）。
- Submit 时通过 `useConnections({ type: 'custom', provider_name: 'custom_api_key' })` 查找绑定到该 credential 的 connection，若没有则 POST — 只将该 `connection_id` 放入 tool POST body。
- **不把** `credential_id` 放入 body — 新创建 tool row 从一开始就统一为 connection-only。Legacy 路径被隔离为**只覆盖现有 row**。
- find-or-create 失败时 tool 创建也中断（防 orphan connection 移交 M5 — scope 协议）。

**效果**：新的 CUSTOM tool 无需走 m11 backfill，从一开始就拥有 connection。`_resolve_custom_auth` 的 legacy 分支真正只保留为 "迁移残留"。

### [S-3] Legacy 路径 log / warning（可选 — S3/S5 判断是否实现）

**当前**：`_resolve_legacy_tool_auth` 静默工作。M3 中也是如此。

**建议**：
- 进入 `_resolve_custom_auth` 的 legacy 分支时，用 `logger.debug` 记录 1 次 tool_id（DEBUG level，因此 prod 无噪音）。
- 在 M6 cleanup 前可度量 "实际有多少 CUSTOM tool 走 legacy 路径" → 作为判断 drop 时点的依据。

**效果**：可选。Jensen S3 推进时若负担过大可省略。M5/M6 再加也不迟。

---

## 3. 暂缓（移交 M6 cleanup）

虽是删除对象，但 M4 PR 中**不触碰**。只记录依据 + 删除时点。

### [H-1] `chat_service._resolve_legacy_tool_auth` 的 CUSTOM 路径

- **位置**：`backend/app/services/chat_service.py:302-315`
- **当前角色**：对 `tool.connection_id IS NULL AND tool.credential_id IS NOT NULL` 的 CUSTOM tool 进行 credential 解密。
- **删除时点**：M6 — m11 backfill 迁移所有 CUSTOM row 后 + 通过运营计量确认 legacy 路径 trigger 为 0 后。
- **删除方法**：从 `_resolve_custom_auth` 删除 legacy 分支 + `_resolve_legacy_tool_auth` 在 PREBUILT `provider_name IS NULL` coverage 消失后删除文件本身。

### [H-2] `tools.credential_id` 列 + `Tool.credential` ORM relationship

- **位置**：`backend/app/models/tool.py`（省略 line 查询 — 禁止修改文件）
- **当前角色**：CUSTOM + PREBUILT legacy bind。以 M3 为基准，PREBUILT 已完全迁移到 connection。M4 中 CUSTOM 也迁移。
- **删除时点**：M6 — 确认 connection-only 运营后 drop + 同时删除 legacy_tool_auth helper。

### [H-3] `tools.auth_config` 列（inline secret）

- **位置**：`backend/app/models/tool.py`, `ToolCustomCreate.auth_config`（`schemas/tool.py:45`）, `ToolAuthConfigUpdate.auth_config`（`schemas/tool.py:50`）
- **当前角色**："无 credential 时 tool 创建后立即 inline auth" legacy。M3 前用户 scenario。
- **删除时点**：M6。但在 ORM column drop 前需要数据 audit — 确认 prod 中是否存在 `auth_config IS NOT NULL AND credential_id IS NULL` row。

### [H-4] `PATCH /api/tools/{tool_id}/auth-config` endpoint 的 `credential_id` 处理

- **位置**：`backend/app/routers/tools.py:115-128` + `backend/app/services/tool_service.py:249+` `update_tool_auth_config`
- **当前角色**：3 个 auth dialog（prebuilt/custom/MCP server）**共同使用**的 credential rebind endpoint。
- **当前状态**：M3 中 PREBUILT dialog 已通过 `useConnections` POST/PATCH 绕开 — 此 endpoint 的 PREBUILT 调用在 M3 中已接近 0（参见 M3 Zuckerberg 工作）。
- **M4 影响**：S4 中将 `add-tool-dialog` Custom tab 改为 find-or-create connection 后，**新建路径不再经过此 endpoint**。现有 tool 的 credential rebind 仍通过 `custom-auth-dialog`（移交 M5）路径调用此 endpoint。
- **删除时点**：M5（替换 custom-auth-dialog）+ M6（替换 MCP dialog）完成后 — 3 个 dialog 全部迁移为经由 connection 后，此 endpoint 本身变成 dead code。Endpoint DELETE 在 M6。

### [H-5] `ToolCustomCreate.credential_id` 字段（`schemas/tool.py:46`）

- **当前角色**：POST /tools/custom 时直接绑定 credential。
- **S4 中**：客户端改为 body 中**不发送**。Server schema 保留到 M6（向后兼容）。
- **删除时点**：M6 — 与 `Tool.credential_id` 列 drop 同步。

---

## 4. 移交 M5（仅记录现状）

**超出 M4 scope**。不触碰。以下是进入 M5 时参考用的现状 snapshot。

### [L-1] `frontend/src/components/tool/custom-auth-dialog.tsx`（109 行）

- **当前角色**：对现有 CUSTOM tool 进行 credential rebind。`useUpdateToolAuthConfig` → `PATCH /tools/{id}/auth-config`。
- **第 16、33 行**：`useUpdateToolAuthConfig` import + call。
- **第 36 行**：`useState<string>(tool.credential_id ?? CREDENTIAL_NONE)` — 直接依赖 `tool.credential_id`。
- **第 40-45 行**：save 时传 `{ authConfig: {}, credentialId }`（始终清空 inline auth + 更新 credential_id）。
- **M5 替换方向**：复用 `ConnectionBindingDialog`（M3 新建）shell。credential → connection find-or-create → `tool.connection_id` PATCH 或 `Connection.credential_id` PATCH。
- **注意**：到 M5 为止，该 dialog 继续通过 **legacy 路径工作**。M4 的 backend 变更**不得破坏**该 dialog（由 Jensen S3 的 `_resolve_custom_auth` 保持 legacy 分支 tolerance 来覆盖）。

### [L-2] `frontend/src/components/tool/mcp-server-auth-dialog.tsx`

- **当前角色**：MCP server credential rebind。经由相同的 `PATCH /tools/{id}/auth-config` endpoint（推测 — 文件未验证，M5 中确认）。
- **M4 影响**：完全没有。MCP 在 M2 中 runtime 已经经由 connection 工作。只有 Dialog 仍使用 legacy API。
- **M5 替换方向**：复用 `ConnectionBindingDialog` shell。

### [L-3] `/connections` 页面 CUSTOM section

- **当前状态**：保留 `CredentialCard` 列表（保留到 M5 — M3 Zuckerberg 决定）。M3 只新增 PREBUILT section。
- **M4 影响**：CUSTOM tool 会拥有 connection，但 `/connections` 页面的 CUSTOM section 仍是 credential 中心视图。UX 一致性问题在 M5 中通过沿用 PrebuiltConnectionSection 模式新增 `CustomConnectionSection` 解决。

---

## 5. 分析文档验证 checklist（供 Satya S6 gate 参考）

- [x] 已读取全部 4 个分析对象文件：`chat_service.py`, `routers/tools.py`, `add-tool-dialog.tsx`, `custom-auth-dialog.tsx`
- [x] 辅助确认：`services/tool_service.py` CUSTOM 路径、`schemas/tool.py` credential_id/auth_config 字段
- [x] 区分 3 类（立即/简化/暂缓）+ M5 移交现状
- [x] 遵守禁止 drive-by — 实际修改 0 项，仅新建分析文档
- [x] 记录 M6 precedent — H-1~H-5 各自明确删除时点 + 方法
- [x] 遵守 scope 协议 — custom-auth-dialog、mcp-server-auth-dialog、`/connections` CUSTOM section 未修改

---

## 6. 需要传达给团队成员的事前事实（进入 S2~S5 前共享）

> 下方只摘要与 Jensen S3 / Zuckerberg S4 / Pichai S2 相关的信息。实际文件边界遵循 `progress.txt` 表格。

1. **Pichai S2（Alembic m11）** — 按 `progress.txt` "Alembic m11 详细设计" 已足够。分析文档无额外指示。`(user_id, credential_id)` dedup + `M11_SEED_MARKER = "[m11-auto-seed]"` + `m11_custom_connection` 22 字符 revision ID 全部按约定执行。
2. **Jensen S3（新建 `_resolve_custom_auth`）** — [S-1] 建议：PREBUILT 对称结构。PREBUILT 的 "无 connection = env fallback" vs CUSTOM 的 "无 connection = legacy fallback" semantic 差异必须写入 docstring。将 `build_tools_config` 的混合 `else:` 分支拆为 `elif tool.type == CUSTOM:` + `else: _resolve_legacy_tool_auth(tool)`（BUILTIN 专用），可让 M6 cleanup 更直观。
3. **Zuckerberg S4（add-tool-dialog Custom tab）** — [S-2] 建议：Submit 时 find-or-create connection → body 禁止 `credential_id`，只传 `connection_id`。确认 `ToolCreateRequest.connection_id?` 字段是否已存在于 `frontend/src/lib/types/index.ts`（M2 已加到 Tool，但 Create request schema 可能遗漏 — 若缺失由 Zuckerberg 在 S4 增加）。`useConnections` hook 是 M3 Zuckerberg 产物。
4. **贝索斯 S5（本人）** — 测试 scenario 按 CHECKPOINT.md S5 checklist 原样。分析文档 [S-3] log 计量是可选项，因此测试中也可省略。只有 `_resolve_custom_auth` helper 实际创建后，才能应用 `inspect.getsource` 源码 contract guard，因此在 S3 完成后进入。Alembic m11 往返按 M9/M10 precedent，在 aiosqlite 中用 `inspect.getsource` guard，PG 实际往返放到 S6 integration gate。
