# 删除分析报告 — Backlog E M1（Connections 表 + CRUD API）

**分支**：`feature/connections-table`
**作者**：贝索斯（QA）
**编写日期**：2026-04-18
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**Scope 定义**：M1 的目标仅是在 **parallel run** 状态下新增 `connections` 表。对现有系统（chat_service, executor, tools, mcp_servers）影响度为 0。实际删除现有代码由 M6 `m12_drop_legacy_columns` 负责。

---

## 分析原则

以 ADR-008 §迁移策略（M1~M6 migration 表）+ `progress.txt` 文件边界为依据，识别 M1 中可 "删除或简化" 的项目。M1 是仅新增专用 milestone，因此**禁止 drive-by 删除**。发现的 legacy 资产全部拆分到后续 milestone ticket。

---

## 可立即删除

**0 项。**

M1 scope（新建 `connections` 表 + CRUD API + 新测试）只涉及新增，不引用或替换现有文件。因此本 PR 中不存在可安全删除的代码。

---

## 需要评估删除（移交后续 milestone）

以下项目随着 **connection 引入，长期会变得重复·不必要**，但这些资产已在 ADR-008 §迁移策略中约定从 M2 以后逐步删除。M1 中不触碰。

1. **`backend/app/models/tool.py:34-57` — 整个 `MCPServer` 表**
   - ADR-008 §迁移策略 M2（`m9_migrate_mcp_to_connections`）：各 row → 迁移至 `connections(type='mcp', extra_config={url,auth_type,headers,env_vars,...})`。`url`, `auth_type`, `auth_config`, `credential_id` 全部迁移到 connection。
   - 实际 drop：**M6**（`m12_drop_legacy_columns`）。M1 中保持 read-only。
   - 建议：**超出 M1 scope。** 不要触碰。

2. **`backend/app/models/tool.py:75-77` — `Tool.credential_id` FK**
   - ADR-008 §迁移策略 M4（`m11_migrate_custom_credentials`）：现有 CUSTOM 工具的 `tool.credential_id` → 1 credential = 1 connection 迁移，多个工具以 N:1 共享。
   - 实际 drop：**M6**。
   - 建议：**超出 M1 scope。**

3. **`backend/app/models/tool.py:67` — `Tool.mcp_server_id` FK**
   - ADR-008 §迁移策略 M2 中新增 `Tool.connection_id` 列，并基于 `mcp_server_id` 映射后，在 M6 中 drop。
   - 建议：**超出 M1 scope。**

4. **`backend/app/models/tool.py:73-74` — `Tool.auth_type`, `Tool.auth_config`**
   - PREBUILT/CUSTOM 工具的 inline auth 设置。引入 connection 后会从解析路径中删除（ADR §3, §迁移策略 M6 drop 列表）。
   - 建议：**超出 M1 scope。**

5. **`backend/app/models/tool.py:16-31` — `AgentToolLink.config` JSON**
   - ADR-008 §3 末句："`agent_tools.config`（现有 JSON）在 M6 中 drop"。由 `agent_tools.connection_id`（M2 新增）替代。
   - 建议：**超出 M1 scope。**

6. **Frontend 3 个 auth dialog**（`prebuilt-auth-dialog`, `custom-auth-dialog`, `mcp-server-auth-dialog`）
   - ADR §结果 "UI 整合"：1 个 `ConnectionBindingDialog` + context prop 在 M5 中吸收（Backlog F）。
   - 建议：**超出 M1 scope。** 在 M5 ticket 中处理。

7. **`backend/app/services/credential_service.py:110-119` — `resolve_server_auth`**
   - 当前：`MCPServer` → credential 或 inline auth_config 的优先级解析 helper。
   - 切换为经由 connection 解析后（M2）会逐步成为 dead path。但 M2 迁移期间 legacy 路径仍共存，因此**至少保留到 M2 完成后** — 最终删除与 M6 legacy drop 同步。
   - 建议：**超出 M1 scope。** 纳入 M6 cleanup checklist。

8. **`backend/app/services/credential_service.py:122-142` — `get_usage_count` 的 `tool_count` / `mcp_server_count`**
   - 引入 connection 后，从用户角度看 "在哪里使用" 更自然的是按 connection usage 重新计算。但在 legacy 列于 M6 drop 前，这两个 count 仍有意义。
   - 建议：**超出 M1 scope。** M5/M6 中新增 `connection_count` 后重新设计。

---

## 简化建议

1. **`connections.provider_name` validator — 复用 `CREDENTIAL_PROVIDERS`（给 Pichai 的指南）**
   - 建议：在 `backend/app/schemas/connection.py` 的 `ConnectionCreate` `provider_name` Pydantic validator 中，对 `type='prebuilt'` 分支用 `set(CREDENTIAL_PROVIDERS.keys())` 检查。**不要单独定义**字符串 enum。
   - 依据：`credential_registry.py:11` 的 `CREDENTIAL_PROVIDERS` dict 已经是真实标准（SOT）。如果复制 connection 专用 enum，就会出现两处都要维护 5 种类型的 drift 风险。
   - 措施：由 Pichai 在 S2 中直接 import — `from app.services.credential_registry import CREDENTIAL_PROVIDERS`。

2. **MCP `extra_config` validator — 仅强制 ADR 明确字段（给 Pichai 的指南）**
   - 建议：`extra_config` 只强制 `url`, `auth_type` required。`headers`, `env_vars`, `transport`, `timeout` optional。**M1 中不要实现模板解析（`${credential.xxx}`）**（ADR §2 最后一段 — "在 M2 MCP 执行路径中执行"）。
   - 依据：M1 scope 是 "只允许 schema"。如果现在加入模板解析逻辑，在 M2 执行路径变更时会产生去重成本。
   - 措施：Pichai 在 `extra_config` validator 中只检查类型/必需 key。禁止 runtime 解析。

3. **`ConnectionResponse` 禁止返回 decrypted 数据（Pichai/Jensen 共通）**
   - 建议：`ConnectionResponse` 只暴露 `credential_id: UUID | None`。credential 本体（`data`）在现有 `CredentialResponse` 中已遵循不暴露原则（`credential_service._to_response` 不调用 `resolve_credential_data`）。Connection 也遵循相同原则。
   - 依据：ADR-008 §安全 — "client response 中不暴露实际 secret value"。`extra_config.env_vars` 也原样返回模板值（M1 中不解析 = 安全）。
   - 措施：Pichai 定义 `ConnectionResponse` 时禁止 embed credential object。仅 id。

4. **测试隔离 — 禁止修改现有 `test_credentials.py` / `test_tools.py`（贝索斯本人指南）**
   - 建议：S4 `test_connections.py` 仅新建一个文件。现有 regression suite（545+）完全不修改。
   - 依据：M1 是 parallel run，因此现有行为 semantic 变化为 0 — 如果现有测试失败，本身就是 regression 信号。通过修改现有测试来让其 PASS 会掩盖 regression。
   - 措施：S4 实现时 `tests/conftest.py`, `tests/test_credentials.py` 等只读。IDOR 模式仅作参考。

5. **Alembic `m8_add_connections` downgrade 完整性（给 Jensen 的指南）**
   - 建议：`downgrade()` 中按 index drop → table drop 顺序。为兼容 SQLite，index drop 明确使用 `op.drop_index(..., table_name="connections")`。
   - 依据：Backlog C progress.txt 学习 — SQLite 中需要明确 `op.batch_alter_table`/`drop_index`。必须往返验证（`upgrade → downgrade → upgrade`）。
   - 措施：Jensen 在 S3 编写时同时测试 upgrade/downgrade，并确认通过 CHECKPOINT 验证命令。

---

## 暂缓 / 超出 scope（记录用）

查看了以下项目，但**明确分类为超出 M1 scope**并移交：

- 整个 `backend/app/routers/credentials.py` — 与引入 connection 无关，不变。
- `backend/app/models/credential.py` — credential 本身原样保留（ADR §决定）。`user_id`, 加密, field_keys cache（ADR-007）全部继续存在。
- `backend/app/services/credential_registry.py` — **必须保留**。connection validator 将此 dict 作为 SOT 引用（参见上方简化建议 #1）。
- `backend/app/services/credential_service.py:45-54` 的函数内部 import — Backlog C 报告中建议 "由 Jensen 在 M3 移到顶部"，但这次 E-M1 scope 也不包含。不要触碰。
- Frontend `/connections` 页面、`tool-configs-dialog` 等 — M5 UI 整合范围。

---

## 结论

| 分类 | 数量 | 备注 |
|------|------|------|
| **立即删除** | **0 项** | M1 仅用于新增 |
| **简化建议** | **5 项** | 全部为 S2/S3/S4 新文件编写指南 — 不修改现有代码 |
| **暂缓（后续 milestone）** | **8 项** | M2 2 项（MCPServer, Tool.mcp_server_id）, M4 1 项（Tool.credential_id）, M5 1 项（Frontend dialog）, M6 4 项（Tool.auth_type/auth_config, AgentToolLink.config, resolve_server_auth, get_usage_count 重新设计） |

**贝索斯判断**：M1 是 "只新增" milestone，现有 legacy 资产的删除计划已记录在 ADR-008 §迁移策略中。如果在本 PR 中触碰 legacy，就会破坏 parallel run 原则并失去 rollback 能力。**禁止 Drive-by，遵守 Minimal Impact 原则。**

简化 5 项全部是**新文件编写指南**，用于预先对齐 Pichai（S2）、Jensen（S3）以及我自己的 S4 实现，避免 drift/重复/安全问题。
