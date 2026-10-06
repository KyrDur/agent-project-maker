# Deletion Analysis — Multi-User Auth (Musk Step 2)

> Goal：在多用户转换前，识别所有可删除/简化代码。仅分析/文档，不修改代码。
>
> 分析对象 branch：`feature/multiuser-auth` · 参考 plan：`~/.claude/plans/replicated-crunching-lark.md`
>
> ⚠️ `tasks/deletion-analysis.md` 是其他 session 产出物 — 不要改动。

---

## 1. Mock User 痕迹全量调查

搜索命令：
```bash
grep -rn "mock_user" backend/app/
grep -rn "00000000-0000-0000-0000-000000000001" backend/
grep -rni "mock\|MOCK_USER\|DEMO_USER" backend/.env.example backend/app/
```

| # | 位置 | 代码摘要 | 处理方案 |
|---|------|-----------|-----------|
| 1 | `backend/app/config.py:31-34` | `mock_user_id`, `mock_user_email`, `mock_user_name` 3 个 Settings 字段 | **删除** — 多用户转换后无意义。替换为 JWT 设置。 |
| 2 | `backend/app/dependencies.py:11-29` | `CurrentUser` dataclass + `get_current_user()` 从 settings 返回 mock | **重写** — 向 `CurrentUser` 增加 `is_super_user: bool=False` 字段。`get_current_user` 全面替换为 cookie/Authorization → JWT decode → DB lookup。新增 `get_current_user_optional`, `require_super_user`（plan 2.4）。 |
| 3 | `backend/app/main.py:96-141`（lifespan seed block） | `mock_user_id = uuid.UUID(settings.mock_user_id)` → User row upsert → `bootstrap_credentials_from_env(db, mock_user_id)` | **删除** — 删除 Mock user upsert block（96-108）。`bootstrap_credentials_from_env(db, mock_user_id)` 调用改为 **`bootstrap_system_credentials(db)`（`is_system=True`, `user_id=NULL`）**（plan 4.1/4.2）。其他 seed（default models, templates, env_fallback sync）是 global，保留。 |
| 4 | `backend/.env.example` | （验证结果）**已经没有 mock section** — 未暴露 `MOCK_USER_*` 环境变量（仅存在 config.py default） | **无变更**（env.example 侧）。但 plan 10.1 新增 key（`JWT_SECRET`, `COOKIE_*`, `ALLOW_FIRST_USER_AS_ADMIN`）是另一个工作项。 |
| 5 | `backend/app/seed/bootstrap_from_env.py:1-159` | 从 module docstring 起就基于 mock_user 前提。signature 使用 `bootstrap_credentials_from_env(db, user_id: uuid.UUID)`。line 105-156 创建 user-bound credential。 | **重写** — 函数名改为 `bootstrap_system_credentials(db)`，移除 `user_id` parameter。改为 `credential_service.create(db, user_id=None, is_system=True, ...)`。现有 `Credential.user_id NOT NULL` constraint（model line 26-28, m18 line 146-148）需 migration 改为 nullable。docstring/SEED_NAME_PREFIX（`"[env]"`）可保留。 |
| 6 | `backend/app/routers/credentials.py:248` | docstring `"All operator system credentials. PoC: no role gate (mock user)."` | **重写** — 更新 docstring + router 新增 `Depends(require_super_user)`（`list_system_credentials`, `create_system_credential`, `get_system_credential`, `update_system_credential`, `delete_system_credential` 5 个全部）。 |
| 7 | `backend/tests/conftest.py:36` | `TEST_USER_ID = uuid.UUID("00000000-...0001")` | **保留（原因）** — 测试 fixture。与 Mock user UUID 偶然相同但含义不同（`TEST_USER_ID`）。新增 multi-user test 时扩展为 `TEST_USER_A_ID`/`TEST_USER_B_ID`。现有单用户测试原样保留。 |
| 8 | `backend/tests/test_credentials_llm_sync.py:430` | `assert TEST_USER_ID == uuid.UUID("00000000-...0001")` | **保留（原因）** — 与上面 #7 相同的测试常量。无需修改。 |
| 9 | `backend/tests/test_seed.py:1` | docstring `"bootstrap_credentials_from_env — env → mock_user Credential seed."` | **重写** — 函数改为 `bootstrap_system_credentials` 后，测试本身也替换为验证 `is_system=True`。 |

**删除后 LOC 估算**：config.py -4，dependencies.py +25/-7，main.py -10，bootstrap_from_env.py +5/-15，credentials.py +5（super_user guard）。净 **约 -30 LOC + 语义简化**。

---

## 2. FK ON DELETE 政策矩阵

搜索命令：
```bash
grep -rn "user_id" backend/app/models/ | grep -v "__pycache__"
grep -n "ondelete" backend/alembic/versions/aa5b4cc59ddb_initial_tables.py backend/alembic/versions/m18_greenfield_credentials.py
```

| table | column | model 位置 | 当前 ondelete | 变更后 | 是否需要 migration |
|--------|------|-----------|---------------|---------|-------------------|
| `agents` | `user_id` | `agent.py:23` | **未指定**（initial m1, line 96-99） | **CASCADE** | 是 — drop+recreate FK |
| `builder_sessions` | `user_id` | `builder_session.py:19` | **未指定** | **CASCADE** | 是 — drop+recreate FK（m35 仅处理 `agent_id`） |
| `agent_triggers` | `user_id` | `agent_trigger.py:19` | **未指定** | **CASCADE** | 是 — drop+recreate FK |
| `agent_creation_sessions` | `user_id` | （legacy?） | **未指定**（initial line 70-73） | **CASCADE** 或检查 table 本身 — 看起来已被 `builder_sessions` 替代 | 是（若 legacy table 仍残留，也检查 drop） |
| `tools` | `user_id` | `tool.py:51-52` | **CASCADE**（m18 line 245-248, nullable） | 保留 — 新增 `is_system` column 时检查一致性 | 否 |
| `credentials` | `user_id` | `credential.py:26-28` | **CASCADE**（m18 line 146-148, NOT NULL） | **允许 NULL + CASCADE** — `is_system=True` row 必须 user_id NULL | 是 — nullable 变更 +（可选）CHECK constraint `(is_system=true AND user_id IS NULL) OR (is_system=false AND user_id IS NOT NULL)` |
| `credential_audit_logs` | `actor_user_id` | （m18 line 180-182） | **SET NULL** | 保留 | 否 |
| `daily_spend_users` | `user_id` | `daily_spend_user.py:34-35` | **CASCADE** | 保留 | 否 |
| `share_links` | `created_by` | `share_link.py:32` | **CASCADE** | 保留 | 否 |
| `mcp_servers` | `user_id` | `mcp_server.py:44-45` | **CASCADE** | 保留 — 已存在 `is_system` column（m26, model line 84） | 否 |
| `skills` | `user_id` | （m18 line 320-322） | **CASCADE** | 保留 | 否 |
| `message_feedback` | `user_id` | （单独 m27） | （需确认） | 建议 CASCADE | （确认） |
| `message_attachments` | `user_id` | （m28） | （需确认） | 建议 CASCADE | （确认） |
| **新增** `refresh_tokens` | `user_id` | （plan 1.3） | — | **CASCADE**（创建时即设置） | 是 — 新建 m22 |
| **Phase 2** `oauth_accounts` | `user_id` | — | — | CASCADE | (Phase 2) |

**核心 migration 工作**（Alembic m22 或后续 m36）：
1. `agents.user_id`, `builder_sessions.user_id`, `agent_triggers.user_id` → CASCADE
2. `credentials.user_id` → 改为 nullable（保持 CASCADE）
3. 新建 `refresh_tokens` table
4. （可选）确认 `agent_creation_sessions` table 是否未使用后 drop

---

## 3. 各 router 授权 audit

搜索命令：
```bash
grep -n "^@router\|user.id\|require_super\|get_current_user" backend/app/routers/*.py
```

| router | GET endpoint user filter | mutation user filter | 缺失验证 | 优先级 |
|--------|---------------------------|---------------------|-------------|----------|
| `agents.py` | OK（`agent_service.list_agents(db, user.id)`, `get_agent(db, id, user.id)`） | OK（所有 endpoint 都通过 `agent_service.get_agent(..., user.id)` 验证 owner） | 无 | — |
| `conversations.py` | OK（`get_owned_conversation` 对 enumeration-oracle 安全） | OK | 无 — chat_service join 模式优秀 | — |
| `tools.py` | OK（`_load_owned`） | OK | 无 | — |
| `credentials.py`（owner CRUD） | OK（每 row `_load_owned`） | OK | 无 — 包含 audit log | — |
| `credentials.py`（system CRUD `/api/system-credentials/*`） | **缺失** — `list_system_credentials`（line 244）向所有认证用户暴露 system credential，`_load_system`（line 232）无 super_user guard | **缺失** — `create/update/delete_system_credential`（255/294/320）允许普通 user | **5 个 endpoint 全部新增 `Depends(require_super_user)`**。存在成本暴涨 + key 泄漏风险 | 🔴 **HIGH** |
| `builder.py` | OK（`builder_service.get_session(db, id, user.id)`） | OK | 无 | — |
| `triggers.py` | OK（`trigger_service.get_trigger`） | OK | 无 | — |
| `usage.py` | OK（直接 filter `DailySpendUser.user_id` + Agent join） | —（read-only） | 无 | — |
| `feedback.py` | OK（`MessageFeedback.user_id == user.id`） | OK | 无 | — |
| `mcp.py` | OK（`McpServer.user_id == user.id`） | OK | 需检查 `is_system` MCP server fallback 政策（是否只有 super_user 可修改？） | 🟡 MEDIUM |
| `skills.py` | OK（`skill_service.get_skill(db, id, user.id)`） | OK | 无 | — |
| `uploads.py` | OK（`user_id=user.id`） | OK | 无 | — |
| `assistant.py` | OK（`agent_service.get_agent(db, agent_id, user.id)`） | OK | 无 | — |
| `health.py` | OK（`McpServer.user_id == user.id`） | OK | 无 | — |
| `templates.py` | global OK（read-only — line 16-29） | **N/A** — create/update/delete endpoint 本身**不存在** | plan 5.1 假定新增 super_user-only POST，但当前 router 没有。新增时加 guard 即可 | 🟢 LOW（实现时 add） |
| `models.py` | global OK（line 52-70）— 所有用户使用同一 catalog | **缺失** — `create_model`（72）, `update_model`（121）, `delete_model`（150）允许普通 user。catalog 是 global resource | **新增 `Depends(require_super_user)`**（POST/PATCH/DELETE 3 个） | 🔴 **HIGH** |
| `shares.py` | owner：通过 `_require_owned_conversation` OK / public（`/api/shares/{token}`）：无需认证 OK | `create_share`（78）/`revoke_share`（93）— owner 验证 OK | 无 — 实现良好 | — |

**立即处理候选（HIGH）**：
1. `credentials.py` system credential router 5 个 → 新增 `require_super_user`
2. `models.py` catalog mutation 3 个 → 新增 `require_super_user`
3. **所有 mutation 统一应用 `Depends(verify_csrf)`**（router prefix 或 middleware）

---

## 4. 种子数据的 user 依赖性

搜索命令：
```bash
ls backend/app/seed/
grep -n "user_id\|mock_user_id" backend/app/seed/*.py
```

| 种子位置 | user 依赖性 | 是否需要变更 |
|-----------|-------------|-----------|
| `backend/app/seed/default_models.py` (DEFAULT_MODELS) | **无** — 全局 catalog（`models` 表，无 user_id） | 无需变更 |
| `backend/app/seed/default_templates.py` (DEFAULT_TEMPLATES) | **无** — 全局（`templates` 表，无 user_id） | 无需变更 |
| `backend/app/seed/bootstrap_from_env.py` | **依赖 mock_user_id**：签名 `bootstrap_credentials_from_env(db, user_id)` 第 105-149 行。调用方（`main.py:134`）传入 mock_user_id。函数内部验证 user 存在后创建 user-owned credential | **需要变更** — 将签名改为 `bootstrap_system_credentials(db)`，`is_system=True, user_id=None`。移除 user 验证块。与 plan 4.2/4.3 精确对应 |
| `backend/app/main.py:131-141`（在 lifespan 中调用） | 传入 mock_user_id | 改为调用 `bootstrap_system_credentials(db)` |
| `backend/app/main.py:146-155` (`sync_env_fallback_from_credentials`) | 不依赖 user | 无需变更 |
| 系统工具（`is_system=True` Tool rows） | 自动 种子 — 在 `tool_factory` 内置 注册表 中按 `user_id IS NULL` 处理 | 无需变更（已经是全局） |

**核心**：所有 种子 **要么已经是全局**，要么**只有 bootstrap_from_env 一处依赖 user**。只要把这一处改为 system credential，种子 领域对 mock-user 的依赖就会变为 0。

---

## 5. 隔离违规可能性（安全分析）

### 5.1 LangGraph Checkpoint thread_id 隔离

- `backend/app/agent_runtime/checkpointer.py:51-58` — 存在 `delete_thread(thread_id)` 函数。
- `executor.py:579` — `config = {"configurable": {"thread_id": cfg.thread_id}}`（原样使用 `conversation_id`）。
- **风险**：`thread_id` 是 **UUID v4**，因此实际上几乎无法 brute-force，但如果在路由器之外直接调用 thread 的路径（e.g. trigger 执行 — `trigger_executor.py`）漏掉 user owner 验证，就可能发生 cross-user 泄漏。
- **当前安全措施**：路由器中的 `chat_service.get_owned_conversation` join 很强。但 **user 删除时没有 LangGraph checkpoint cascade** — 存在 orphan thread 累积风险（plan 6.1 中通过新增 `cleanup_user_resources` 解决）。

### 5.2 Tool factory cross-user credential leak

- `tool_factory.py:217` — `user_uuid = _safe_uuid(tool_config.get("user_id"))`（由 caller 注入）。chat_service 的 `build_tools_config` 中传入 `user_id=str(agent.user_id)`（`chat_service.py:586`）。
- **泄漏路径**：如果某个 caller 没有注入 `user_id`，`_build_tool_hook_context` 会返回 `None` → spend tracking 缺失 + audit hole。**这本身不是泄漏，但会丢失隔离信号**。
- **潜在违规**：`system_credential_resolver.py`（`is_system=True` credential lookup）也可能在普通 user 的工具调用中工作。plan 4.2 定义的"仅限 super_user"策略尚未写死在代码里 → **需要新增独立 防护 函数**（`assert_can_use_system_credential(user)`）。

### 5.3 Conversation join 模式

- `chat_service.get_owned_conversation`（line 91-105）— `Conversation` ⨝ `Agent` on `Agent.user_id == user_id` 单次 SELECT。优化很好。
- **验证结果**：`Conversation` 表本身没有 `user_id`（`conversation.py`）。隔离通过 **Agent 1-hop** 完成。删除 Agent 时 Conversation 也应 cascade — 当前 `agents.id` FK 似乎没有显式指定 ondelete CASCADE（initial migration line 125-128）。**需要确认**。

### 5.4 Daily spend aggregation 隔离

- `usage_aggregate.py:104-179` — user axis 直接做 column 过滤，agent/model axis 通过 Agent.user_id join。模式很干净，没有隔离违规。

### 5.5 Builder session FK 一致性

- `builder_session.py:19` — `user_id ForeignKey("users.id")` 未显式指定 ondelete。`agent_id` 已在 m35 中按 SET NULL 处理。**user 注销时 builder_session row 可能变成孤儿** → 统一为 CASCADE。

---

## 6. 删除候选（Musk Step 2 — 显式简化）

明确**删除后可以简化**的代码：

| # | 对象 | 位置 | LOC 估算 | 简化效果 |
|---|------|------|----------|-------------|
| 1 | `mock_user_id`/`mock_user_email`/`mock_user_name` Settings 字段 | `config.py:31-34` | -4 | 彻底移除"Mock user (PoC: no auth)"概念 |
| 2 | `get_current_user` mock 返回部分 | `dependencies.py:23-29` | -7 | 全面替换为基于 JWT。mock 分支消失 |
| 3 | `main.py` lifespan 中的 mock user upsert 块 | `main.py:96-108` | -13 | 可移除 startup 代码 13 行 + import 1 行（`User`）（需确认 import 的其他使用处） |
| 4 | `bootstrap_credentials_from_env` 的 user 验证块 | `bootstrap_from_env.py:120-126` | -7 | 转为 system credential 后不再需要 |
| 5 | `bootstrap_credentials_from_env` 的 `user_id` 参数 + `Credential.user_id == user_id` 过滤 | `bootstrap_from_env.py:105-156` | -3 | 简化签名 |
| 6 | `routers/credentials.py:248` docstring `"PoC: no role gate (mock user)."` | line 248 | -1 | 语义更明确 |
| 7 | `agent_creation_sessions` 表（legacy，**dead**） | initial migration line 61-75 | -15（迁移 drop） | **已确认**：`grep -rn "agent_creation_sessions\|AgentCreationSession" backend/app/` 为 0 项。已被 `builder_sessions` 完全替代。**可以 drop** — 在 m22 或后续迁移中添加 `op.drop_table("agent_creation_sessions")`。 |
| 8 | `Settings.google_oauth_refresh_token`（`config.py:29`）全局使用处 | `agent_runtime/google_workspace_tools.py`（需确认） | -? | 若将全局 令牌 转为按用户 credential，可移除 settings 字段 |

**预计 LOC 总减少量**：仅移除 Mock 痕迹 = **约 35 LOC**。若 drop `agent_creation_sessions` legacy 表则再减少 +50~100 LOC。语义上的简化效果大于 LOC — 一旦"Mock User"这一单用户假设消失，路由授权 audit、种子 策略、工具 credential 优先级都会整理成一致模型。

---

## 7. 验证命令汇总

下一会话复现/扩展本分析时使用：

```bash
# 1. Mock user 痕迹 — 全部应为 0 项，才算完成多用户转换
grep -rn "mock_user" backend/app/
grep -rn "00000000-0000-0000-0000-000000000001" backend/
grep -rni "mock\|MOCK_USER\|DEMO_USER" backend/.env.example backend/app/

# 2. FK ondelete 策略矩阵
grep -rn "user_id" backend/app/models/ | grep -v "__pycache__"
grep -n "ondelete" backend/alembic/versions/aa5b4cc59ddb_initial_tables.py
grep -n "ondelete" backend/alembic/versions/m18_greenfield_credentials.py
grep -n "ForeignKey.*users" backend/app/models/*.py

# 3. 路由授权 audit
grep -n "^@router\|user.id\|require_super\|get_current_user" backend/app/routers/*.py
grep -rn "require_super\|is_super_user" backend/app/  # 新增后验证

# 4. 种子数据 user 依赖性
grep -n "user_id\|mock_user_id" backend/app/seed/*.py
grep -rn "bootstrap_credentials_from_env\|bootstrap_system_credentials" backend/

# 5. 隔离违规可能性
grep -n "thread_id\|user_id" backend/app/agent_runtime/checkpointer.py
grep -n "user_id\|owner\|is_system\|require_super" backend/app/agent_runtime/tool_factory.py
grep -n "get_owned_conversation\|Agent.user_id" backend/app/services/chat_service.py
grep -n "user_id\|is_system" backend/app/services/system_credential_resolver.py

# 6. 删除候选 — 检查 legacy table 使用处
grep -rn "agent_creation_sessions\|AgentCreationSession" backend/app/
grep -rn "google_oauth_refresh_token\|GOOGLE_OAUTH_REFRESH_TOKEN" backend/

# 7. is_super_user / 认证新基础设施（引入后验证）
grep -rn "is_super_user\|hashed_password\|RefreshToken" backend/app/
grep -rn "verify_csrf\|require_super_user\|get_current_user_optional" backend/app/

# 8. 识别缺少 CSRF 的 mutation（引入后）
grep -n "@router\.\(post\|put\|patch\|delete\)" backend/app/routers/*.py | grep -v "auth\|verify_csrf"
```

---

## 附录 A — 优先级摘要（詹森最先处理）

1. 🔴 **系统 credential super_user 防护**（`routers/credentials.py:243-336`）— 成本失控/密钥泄漏风险。plan 4.2/5.1。
2. 🔴 **模型 目录 mutation super_user 防护**（`routers/models.py:72/121/150`）— 保护全局资源。
3. 🔴 **将 `Credential.user_id` 迁移 为 nullable** — 是让 `is_system=True` row 不依赖 user 的前提。没有这个，plan 4.1 的 `bootstrap_system_credentials` 无法工作。
4. 🟡 **`agents/builder_sessions/agent_triggers` user_id FK ondelete=CASCADE** — user 注销时清理 孤儿 row。
5. 🟡 **全面重写 `get_current_user`** + 在 `dependencies.py` 中新增 `require_super_user`/`get_current_user_optional`/`verify_csrf`。
6. 🟢 **移除 `main.py` mock user 块 + 重写 `bootstrap_credentials_from_env`** — 必须等上面 1~5 完成后才能安全进行。
