# M6.1 手动 E2E 场景

**作者**：贝索斯 (QA DRI)
**编写日期**: 2026-04-25（新增 M7 场景：2026-04-25）
**分支**: `feature/backlog-e-m6-1`（8 commits: M2 `10c55dc` / M3 `7d3fef0` / M4 `87b173e` / M5 `b24ef1b` / M7 `0dc1610` + `5e872e2` / docs `1c04481` + `b40e399`）
**对象**: `tool.connection_id` single source of truth + MCP legacy drop + 恢复 MCP 新增注册（M7）

## 准备工作

```bash
# 检查 DB 状态（预期已应用 m13）
docker exec natural-mold-postgres-1 psql -U moldy -d moldy -c "SELECT to_regclass('mcp_servers');"
# → NULL (table dropped)

docker exec natural-mold-postgres-1 psql -U moldy -d moldy -c "\d tools" | grep -c mcp_server_id
# → 0

# 启动 Backend + Frontend
cd backend && uv run uvicorn app.main:app --reload --port 8001 &
cd frontend && pnpm dev &
# http://localhost:3000
```

---

## 场景 1: CUSTOM first-bind（M4 核心流程）

**目标**: 即使创建 CUSTOM tool 时没有 connection_id，之后也可在 Binding dialog 中选择 credential 进行 self-serve 修复。

**前提**:
- CUSTOM tool 创建在**当前路径中要求 connection_id required**（schemas/tool.py L31）— 此场景针对既有 fail-closed tool 或 drive-by 创建的 tool，通过 Binding dialog 修复。
- 为测试直接创建 tool row：`psql -c "INSERT INTO tools (id, user_id, type, name, created_at) VALUES (gen_random_uuid(), (SELECT id FROM users LIMIT 1), 'custom', 'Test First-Bind', now());"`

**步骤**：
1. `/tools` 页面 → "Test First-Bind" tool 卡片显示为"无连接"状态
2. 点击 Binding 按钮 → 打开 Credential Select dialog（`<CustomBody>`）
3. 选择现有 credential OR "创建新 credential" → 保存
4. 检查 Network 标签页：
   - (a) `POST /api/connections` OR `GET /api/connections?type=custom` → 复用现有 connection / 新建（useFindOrCreateCustomConnection, ADR-008 N:1）
   - (b) `PATCH /api/tools/{tool_id}` body: `{"connection_id": "<new-conn-id>"}` → 200
5. Dialog close，更新 tool 卡片状态为"已连接"（invalidateQueries `['tools']`）
6. 将该 tool 绑定到 agent 后执行聊天 → CUSTOM tool call 成功

**Pass 标准**:
- ✅ `PATCH /api/tools/{id}` 仅以 `{connection_id}` 单一字段调用
- ✅ tool.connection_id 反映在响应中
- ✅ UI 中 `needsOptionDFirstBind` alert/guard **不再显示**（M4 中已移除）
- ✅ 聊天执行时 runtime 通过 `tool.connection.credential` 路径 decrypt（chat_service `_resolve_custom_auth`）

**Fail 标准**:
- ❌ PATCH 响应为 400/422/404
- ❌ tool.connection_id 仍为 null
- ❌ agent 执行时出现 `ToolConfigError: has no connection_id`

---

## 场景 2: MCP credential rotate（M5 核心流程）

**目标**: 使用 `ConnectionBindingDialog type="mcp"` 更换现有 MCP tool 的 credential。M5 中移除 `useUpdateMCPServer` 后统一走 `useUpdateConnection` 单一路径。

**前提**: 至少存在 1 个现有 MCP connection + tool。dev DB 当前为 0 个（Hancom-GW 已删除）。此场景用于确认**代码路径有效性** → 通过 staging 环境 or seed 数据覆盖。

**替代验证（本地）**: 直接 seed
```sql
INSERT INTO credentials (id, user_id, name, credential_type, provider_name, data_encrypted, field_keys, created_at)
VALUES (gen_random_uuid(), (SELECT id FROM users LIMIT 1), 'test-mcp-cred', 'key-value', 'mcp_custom', '...'::bytea, '["api_key"]', now());
INSERT INTO connections (id, user_id, type, provider_name, display_name, credential_id, extra_config, status, is_default, created_at, updated_at)
VALUES (gen_random_uuid(), (SELECT id FROM users LIMIT 1), 'mcp', 'mcp_custom', 'Test MCP', '<cred-id>', '{"url":"https://example.com/mcp","auth_type":"bearer","env_vars":{"API_KEY":"{{api_key}}"}}', 'active', false, now(), now());
INSERT INTO tools (id, user_id, type, name, connection_id, created_at)
VALUES (gen_random_uuid(), (SELECT id FROM users LIMIT 1), 'mcp', 'test_mcp_tool', '<conn-id>', now());
```

**步骤**：
1. `/tools` → 展开 MCP 分组区域的"Test MCP"卡片
2. Binding 按钮 → 打开 `<McpBody>` dialog
3. 在 credential select 中切换到其他 credential → 保存
4. Network 标签页：
   - `PATCH /api/connections/{conn_id}` body: `{"credential_id": "<new-cred-id>", "status": "active"}` → 200
   - **没有**调用 `useUpdateMCPServer`（M5 中已移除）
5. Dialog close，更新卡片 credential label
6. agent 聊天 → 执行 MCP tool → runtime 使用新 credential

**Pass 标准**:
- ✅ Network 中 `PATCH /api/tools/mcp-servers/*` 调用 **0 项**
- ✅ `PATCH /api/connections/{id}` 单次调用
- ✅ 响应后卡片显示新 credential 名称
- ✅ runtime 使用新 credential 值（解密 `connection.credential.data_encrypted`）

**Fail 标准**:
- ❌ 尝试调用 `/api/tools/mcp-servers/*` 路由 → 404（M3 中已移除）
- ❌ runtime 使用之前的 credential 值（遗漏 invalidation）

---

## 场景 3: 阻止 PREBUILT PATCH（M2 security invariant）

**目标**: 对 PREBUILT tool 调用 `PATCH /api/tools/{id}` → 400。验证保持 `(user_id, provider_name)` SOT。

**步骤**（直接 curl）：
```bash
# 查询 PREBUILT tool id
PREBUILT_ID=$(docker exec natural-mold-postgres-1 psql -U moldy -d moldy -tAc \
  "SELECT id FROM tools WHERE type='prebuilt' AND is_system=true LIMIT 1;")

# 先创建一个 CUSTOM connection 并获取其 id
CUSTOM_CONN_ID=$(docker exec natural-mold-postgres-1 psql -U moldy -d moldy -tAc \
  "SELECT id FROM connections WHERE type='custom' LIMIT 1;")

# 尝试 PATCH
curl -sS -X PATCH "http://localhost:8001/api/tools/$PREBUILT_ID" \
  -H "Content-Type: application/json" \
  -d "{\"connection_id\": \"$CUSTOM_CONN_ID\"}" \
  -w "\nHTTP %{http_code}\n"
```

**Pass 标准**:
- ✅ HTTP 400
- ✅ response body: `{"detail": "PREBUILT tools use (user_id, provider_name) scoped connections..."}`（英文 detail）
- ✅ 再次确认 DB：`SELECT connection_id FROM tools WHERE id='$PREBUILT_ID'` → 仍为 NULL

**Fail 标准**:
- ❌ HTTP 200（PATCH 通过）
- ❌ PREBUILT tool 被写入 connection_id

---

## 场景 4: 阻止 IDOR（M2 security invariant）

**目标**: 将用户 B 的 connection_id PATCH 到用户 A 的 tool → 404（防止 info leak）。

**步骤**：
```bash
# 用户 A 的 tool
USER_A_TOOL=$(docker exec natural-mold-postgres-1 psql -U moldy -d moldy -tAc \
  "SELECT id FROM tools WHERE type='custom' AND user_id=(SELECT id FROM users ORDER BY created_at LIMIT 1) LIMIT 1;")

# 用户 B 的 connection（不同 user_id）
USER_B_CONN=$(docker exec natural-mold-postgres-1 psql -U moldy -d moldy -tAc \
  "SELECT c.id FROM connections c WHERE c.user_id <> (SELECT id FROM users ORDER BY created_at LIMIT 1) AND c.type='custom' LIMIT 1;")

# 尝试 PATCH（当前 API 是 mock user — 虽无实际 auth context，但 service layer 按 user 过滤）
curl -sS -X PATCH "http://localhost:8001/api/tools/$USER_A_TOOL" \
  -H "Content-Type: application/json" \
  -d "{\"connection_id\": \"$USER_B_CONN\"}" \
  -w "\nHTTP %{http_code}\n"
```

**Pass 标准**:
- ✅ HTTP 404（Connection not found — 存在但属于其他用户）
- ✅ response detail **不**暴露其为"其他用户 connection"（防止信息泄露）
- ✅ DB：tool.connection_id 无变化

**Fail 标准**:
- ❌ HTTP 200（允许 cross-tenant PATCH）
- ❌ response 中出现"this connection belongs to another user"之类的明确提示

**自动化覆盖**: `tests/test_tools.py::test_patch_tool_connection_id_other_user_connection_404`（包含在 baseline 621 PASS 中）。

---

## 场景 5: 直接验证 DB（M3 schema invariant）

**目标**: 确认应用 m13 后 schema 中 `tools.mcp_server_id` + `mcp_servers` 完全移除，并确认 FK 名称/存在性。

**步骤**：
```bash
# (1) 不存在 tools.mcp_server_id 列
docker exec natural-mold-postgres-1 psql -U moldy -d moldy -c "\d tools" | grep mcp_server_id
# 预期：（不匹配任何行）

# (2) 不存在 mcp_servers 表
docker exec natural-mold-postgres-1 psql -U moldy -d moldy -c "SELECT to_regclass('mcp_servers');"
# 预期：to_regclass = NULL

# (3) 再次确认 FK 组成
docker exec natural-mold-postgres-1 psql -U moldy -d moldy -c \
  "SELECT conname FROM pg_constraint WHERE conrelid='tools'::regclass AND contype='f' ORDER BY conname;"
# 预期：fk_tools_connection_id + tools_user_id_fkey 共 2 项。不存在 tools_mcp_server_id_fkey。

# (4) alembic head
cd backend && uv run alembic current
# 预期：m13_drop_mcp_legacy (head)

# (5) round-trip（可选 — 已在 M6 执行）
uv run alembic downgrade -1 && uv run alembic upgrade head
# 预期：无错误，最终 head=m13
```

**Pass 标准**: 上述 5 个步骤全部符合预期值。

**Fail 标准**:
- ❌ 仍存在 `mcp_server_id` 列
- ❌ 存在 `mcp_servers` 表（to_regclass != NULL）
- ❌ 仍存在 `tools_mcp_server_id_fkey` constraint
- ❌ alembic head 为 m12（未应用 upgrade）

---

## 场景 6: 新增注册 MCP 服务器 + 自动 discovery（M7）

**目标**: `/tools` → "添加工具" → MCP 标签页 → 输入 URL → 验证自动执行 connection 创建 + tool discovery。

**前提**:
- 测试用 MCP 服务器 URL。公开服务器只要有响应即可。认证 MCP 使用 credential
  创建后使用（e.g. Hancom-GW：credential 的 `api_key` 字段填 JWT token + header
  名称 `GW_JWT_TOKEN`）。
- 同时支持公开 / 认证两种情况。

**添加认证 MCP 的步骤**:
- 在"认证"区域选择 credential → Credential 字段自动 default（`api_key`）
- 输入 header 名称（服务器实际接收的 header 名称，e.g. `GW_JWT_TOKEN`）
- 注册时 backend `extra_config.env_vars = {<header>: ${credential.<field>}}`
  保存为模板 → discovery probe 和 chat runtime 使用同一 header 调用

**步骤**：
1. `/tools` 页面 → 顶部"添加工具"按钮 → 打开 AddToolDialog
2. 在顶部 Tabs 选择 **"MCP 服务器"** 标签页（默认值）
3. 输入显示名称 + 服务器 URL
4. 确认显示提示文案"当前版本仅支持公开 MCP 服务器（无认证）..."
5. 点击"注册并探索工具"按钮
6. 检查 Network 标签页：
   - (a) `POST /api/connections` body: `{type: "mcp", provider_name: "<slug>", display_name, extra_config: {url, auth_type: "none"}}` → 201
   - (b) `POST /api/connections/{id}/discover-tools` → 200 with `{connection_id, server_info, items}`
7. 显示 toast"N 个工具已新导入（保留现有 0 个）"
8. dialog 自动关闭
9. `/tools` 页面显示新的 MCP 分组卡片 + 工具。`/connections` MCP 区域也显示新卡片（只读）
10. DB 实测：
    ```sql
    SELECT COUNT(*) FROM tools WHERE connection_id = '<new-conn-id>' AND type = 'mcp';
    -- 预期：与 items.length 值一致
    ```

**Pass 标准**:
- ✅ AddToolDialog 的 MCP 标签页默认激活（defaultValue="mcp"）
- ✅ 创建 connection 201
- ✅ discovery 200 + items 数组
- ✅ tools 记录 upsert（基于 user_id × connection_id × name 幂等）
- ✅ 再次执行时 items[].status 全部为"existing"（无重复创建）
- ✅ `/connections` McpSection 中没有"添加连接"按钮（只读）

**Fail 标准**:
- ❌ AddToolDialog 中未显示 MCP 标签页
- ❌ discovery 502（probe 失败 — 确认是否为公开服务器）
- ❌ 再次执行时 tool 重复创建（幂等性破坏）
- ❌ `/connections` McpSection 中仍有"添加连接"按钮

**自动化覆盖**: `tests/test_connection_discover_tools.py` 8 项全部 PASS（success/idempotent/IDOR/non-mcp/no-url/502/malformed/404）。

---

## 执行记录

| 场景 | 执行者 | 执行日期 | 结果 | 备注 |
|---------|-------|-------|------|-----|
| 1. CUSTOM first-bind | 贝索斯 | 2026-04-25 | **代码路径 ✅ / 手动执行 ⏳** | pytest `test_patch_tool_connection_id_custom_success` 等 9 项自动化覆盖。实际浏览器点击由 PR reviewer 执行 |
| 2. MCP credential rotate | 贝索斯 | 2026-04-25 | **代码路径 ✅ / 手动执行 ⏳** | dev DB 中 MCP tool 0 项 → 提供 seed SQL。PR reviewer 在 staging 验证 |
| 3. 阻止 PREBUILT PATCH | 贝索斯 | 2026-04-25 | **✅ 自动化 PASS** | `tests/test_tools.py::test_patch_tool_connection_id_prebuilt_400` |
| 4. 阻止 IDOR | 贝索斯 | 2026-04-25 | **✅ 自动化 PASS** | `tests/test_tools.py::test_patch_tool_connection_id_other_user_connection_404` |
| 5. DB 直接验证 | 贝索斯 | 2026-04-25 | **✅ PASS** | m12 → m13 → m12 → m13 round-trip + `\d tools` + `to_regclass` 实测 |
| 6. 新增注册 MCP + discovery（M7） | Satya | 2026-04-25 | **代码路径 ✅ / 手动执行 ⏳** | pytest `test_connection_discover_tools.py` 8 项 PASS。浏览器实际点击由 PR reviewer 使用公开 MCP URL 执行 |

---

## 未执行手动 E2E 场景的风险评估

1、2 需要**检查到浏览器 DOM/Network 标签页**的视觉回归 — 在贝索斯（QA subagent）范围内，能用 Bash/grep 自动化的部分已全部通过。建议浏览器点击验证由 PR reviewer 或 staging 环境执行。风险较低：

- UI 逻辑：M4/M5 Zuckerberg 的 `pnpm build`（14 pages）+ lint clean + 代码 grep 0 残留，已完成编译级验证。
- Runtime 逻辑：pytest 621 PASS（M2 baseline 633 → 移除 12 个 MCP-only tests = 621，包含新增 9 个 PATCH tests）。
- Scheme 逻辑：通过 alembic round-trip + `\d tools` + `to_regclass` 实测完成 1-way door 验证。

**结论**: 自动化场景 3/4/5 PASS，1/2 按代码路径标准 PASS，浏览器手动确认委托到 staging/PR review 阶段。
