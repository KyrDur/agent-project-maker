# Credential / Tools / Skills Greenfield 重写

## Context

natural-mold(Moldy) 当前 Credential/Connection/Tools/Skills 系统因 M6~M11 迁移累积，双轨制·多重分类问题不断叠加。渐进式重构很可能再次制造与 M11 类似的复杂度。

由于仍处 PoC 阶段允许数据丢失，因此将 Credential/Tool/Skill stack 以 Python/React 为基础的 Moldy 自有模型进行 Greenfield 重写。

## 用户决定事项（确定）

1. **Cipher 格式**: 单一 blob `[version 1B][salt 32B][authTag 16B][ciphertext]` Base64 + HKDF-SHA256(info=`'moldy-encryption-v1'`) 推导 key/IV。密钥识别使用单独列(`key_id`)。
2. **LLM 模型表**: 保留 `models`（移除 api_key_encrypted 列），新增 `agents.llm_credential_id` FK，废弃 `llm_providers` 表。LLM API key 也统一到新 Credential。
3. **PR 单位**: 单一 PR。
4. **范围**: Cipher V2 + Credential domain + OAuth2 自动 refresh + 密钥轮换 cron + **Vault provider 实现**(HVAC SDK)。

## 探索中发现的补充事项

| 项目 | 发现 |
|---|---|
| **chat_service.py** | `build_tools_config()` (L369-462) 是认证解析主体。初稿遗漏 — **需要全面重新布线**。 |
| **trigger_executor.py L44-46** | 未调用 `_load_user_default_connection_map()` — 当前 prod 潜在 bug。新系统中需要等价重建 PREBUILT default credential 预加载逻辑。 |
| **mcp_client.py + env_var_resolver.py** | `${credential.<field>}` template 解析逻辑。需要重新接到新的 Credential 系统。 |
| **迁移编号** | `m12_drop_legacy_columns.py` 已存在 — 新迁移命名为 **m13_greenfield_credentials**。 |
| **Fernet → Cipher V2 数据迁移** | PoC 所以 dev DB drop & recreate。但需要明确从 `ENCRYPTION_KEY` (Fernet) → `ENCRYPTION_KEYS` (Cipher V2) 环境变量切换。 |
| **测试依赖** | grep `tests/` 中是否直接 import `naver_tools`, `credential_service`, `connection_service` 后移除/替换。 |

## 工作顺序（单一 PR 内 milestone）

在 CHECKPOINT.md 登记以下6个 milestone，每个 milestone 验证通过后再进入下一步。所有 milestone 完成后只 merge 1次。

### M1. 品牌验证 + Cipher V2

**文件**:
- 新增 `scripts/check_branding.py` — 检查配置的禁用标识符、package prefix、资源 SHA-256 blacklist
- 新增 `backend/app/security/cipher.py` — 使用 `cryptography` library
- 新增 `backend/app/security/key_provider.py` — 多个 active/verification key 管理
- 修改 `backend/app/config.py` — 新增 `encryption_keys: list[str]`，启动时为空则失败
- 修改 `backend/.env.example` — `ENCRYPTION_KEYS` 示例
- 新增 `backend/tests/test_cipher.py` — round-trip, 多密钥, 密钥识别, 损坏验证
- 新增 `backend/tests/test_branding.py` — 调用 `check_branding.py`

**Cipher V2 准确规格**:
- KEY: 64-char hex (32 bytes)
- SALT: 32 bytes random
- IV: 12 bytes（HKDF 推导部分的最后12字节）
- AUTH_TAG: 16 bytes
- HKDF info: `b'moldy-encryption-v1'`
- 格式: Base64(`0x01` + salt + authTag + ciphertext)
- 多密钥: `key_id` 从密钥的 `sha256(key)[:8].hex()` 推导。加密时使用 active key，解密时尝试所有 key（首个成功）。存入单独列(`credentials.key_id`)用于轮换识别。

**验证**: `uv run pytest tests/test_cipher.py tests/test_branding.py -v` 通过, `python scripts/check_branding.py` 通过。

### M2. Credential domain + ORM + router + 定义目录 + Vault

**模型** — `backend/app/models/`:
- `credential.py`（重写）
  ```python
  class Credential(Base):
      id, user_id, definition_key, name
      data_encrypted: str          # Cipher V2
      key_id: str                  # active key 识别（用于轮换）
      field_keys: list[str]        # JSON, 避免解密的 cache
      is_shared: bool
      status: Literal["active", "disabled", "expired"]
      last_used_at, last_tested_at
      last_test_result: dict | None  # JSON
      created_at, updated_at
  ```
- 新增 `credential_audit_log.py`
- 新增 `credential_default.py` — `(user_id, scope_kind, scope_key, credential_id)`

**Domain** — `backend/app/credentials/`:
- `field.py` — `FieldDef`, `FieldKind` enum: `string|password|number|select|multiline|json|oauth_button|toggle|collection`。`display_options.show: dict[str, list[Any]]`（条件显示）, `type_options: { password, multiline, expirable, ... }`
- `domain.py` — `CredentialDefinition`: `key, display_name, icon_id, properties, authenticate, test, pre_authentication, extends`
- `interpolation.py` — 仅限 `={{ $credentials.<field> }}` 表达式 evaluator（有意不支持完整 JS 评估，最小化 security surface）
- `authenticate.py` — `GenericAuth(type='generic', properties={headers, qs, body, basic})` + `httpx.Auth` adapter
- `registry.py` — `CredentialRegistry` 单例, 注册/查询定义
- `oauth2_base.py` — OAuth2 base。检查带 `expirable` typeOptions 的 token 字段是否过期 → 调用 `pre_authentication()` → refresh → 重新加密后 UPDATE → audit log `refresh`。**并发 guard: 通过 SQLAlchemy `with_for_update()` 串行化**。
- `tester.py` — `CredentialTester.run(definition, decrypted)` → 执行 test request → 评估 rules → 结果 dict
- `external_secrets/base.py` — `SecretsProvider` ABC: `init/connect/get_secret/has_secret/test`
- `external_secrets/env_provider.py` — 默认（env vars）
- `external_secrets/vault_provider.py` — **HVAC SDK 实现**, feature flag `settings.external_secrets_enabled`
- `external_secrets/proxy.py` — runtime 解析 `__external__: { provider, ref }` marker

**定义** — `backend/app/credentials/definitions/`:
- `naver_search.py`, `google_search.py`, `google_workspace_oauth2.py`, `openai.py`, `anthropic.py`, `google_genai.py`, `azure_openai.py`
- `http_bearer.py`, `http_api_key.py`（header 名称用户自定义）, `http_basic.py`
- `mcp_oauth2.py`

**Router** — `backend/app/routers/credentials.py`（重写）:
- `GET /api/credential-types` — 定义目录
- `GET /api/credentials` — 列表
- `POST /api/credentials` — 创建（加密）
- `GET /api/credentials/{id}` — 单条（不返回 data，仅 field_keys）
- `PATCH /api/credentials/{id}` — 更新
- `DELETE /api/credentials/{id}`
- `POST /api/credentials/{id}/test` — 测试已保存 credential
- `POST /api/credentials/preview-test` — 用保存前的 form data 测试
- `GET /api/credentials/{id}/audit-logs` — 最近 N 条
- `POST /api/oauth2-credential/auth/{id}` — OAuth2 认证开始
- `GET /api/oauth2-credential/callback` — callback

**测试** — `backend/tests/test_credentials.py`, `test_oauth2.py`, `test_tester.py`, `test_external_secrets.py`

**验证**: 定义目录响应 / Credential CRUD / Test 调用 / OAuth2 mock refresh / Vault dev container secret 查询。

### M3. Tools 重定义 + MCP 服务器

**模型**:
- 重写 `backend/app/models/tool.py`
  ```python
  class Tool(Base):
      id, user_id, definition_key, name, description
      parameters: dict        # JSON, 用户输入值
      credential_id: UUID | None  # FK credentials, SET NULL
      enabled: bool
      last_used_at, created_at, updated_at
  ```
- 新增 `backend/app/models/mcp_server.py`
- 新增 `backend/app/models/mcp_tool.py`

**Domain** — `backend/app/tools/`:
- `domain.py` — `ToolDefinition`（简化 INodeType）: `key, display_name, icon_id, category, parameters, credential_definition_keys, runner`
- `parameters.py` — 复用 `FieldDef`
- `registry.py`
- `runner.py` — HTTP 调用 + 应用 GenericAuth（委托 Credential 系统）
- `definitions/`: `http_request.py`, `naver_search.py`, `google_search.py`, `gmail_send.py`, `google_calendar_event.py`, `google_chat_message.py`

**MCP** — `backend/app/mcp/`:
- `domain.py` — `McpServerDefinition`
- `client.py` — `langchain-mcp-adapters` wrapper。**将 `${credential.<field>}` env_vars template 解析替换为调用新的 `interpolation.py`**（废弃现有 `env_var_resolver.py`）
- `discovery.py` — tools 自动搜索
- `oauth.py` — MCP OAuth2（继承 oauth2_base）

**Router**:
- 重写 `backend/app/routers/tools.py`: `GET /api/tool-types`, `GET/POST/PATCH/DELETE /api/tools`, `POST /api/tools/{id}/run`
- 新增 `backend/app/routers/mcp.py`: `GET/POST/PATCH/DELETE /api/mcp-servers`, `POST /api/mcp-servers/{id}/test`, `POST /api/mcp-servers/{id}/discover`

**测试**: `test_tools.py`, `test_mcp.py`

**验证**: 工具目录 / 创建工具实例 / HTTP Request 工具实际调用 / MCP discover。

### M4. Skills + 迁移 m13 + seed

**Skills**:
- 重写 `backend/app/models/skill.py`: 利用现有 `type/storage_path` 列 + `content_hash, size_bytes, version, package_metadata, used_by_count, last_modified_at`
- `backend/app/skills/`: `service.py`, `packager.py` (.skill zip), `inspector.py` (解析 SKILL.md), `runtime.py`
- 重写 `backend/app/routers/skills.py`: `GET/POST /api/skills`, `GET /api/skills/{id}/files`, `GET /api/skills/{id}/files/{path}`

**迁移** — `backend/alembic/versions/m13_greenfield_credentials.py`:
- DROP: `credentials, connections, credential_audit_logs(如存在), tools, skills, models, llm_providers, mcp_servers, mcp_tools(如存在), agent_tools, agent_skills`
- CREATE 新 schema:
  - `credentials, credential_audit_logs, credential_defaults`
  - `tools, mcp_servers, mcp_tools, skills`
  - `models`（移除 api_key_encrypted 的新 schema）
  - `agent_tools`（重建, FK 指向新 schema tool）
  - `agent_skills`（重建）
- ALTER: 在 `agents` 表增加 `llm_credential_id UUID FK credentials`
- downgrade: `raise NotImplementedError("m13 is intentionally non-reversible")`

**Seed** — `backend/app/seed/`:
- 重写 `bootstrap_from_env.py` — 发现 `OPENAI_API_KEY` 等 env 时自动创建 mock_user 所有的 Credential。仅在 `settings.environment != "production"` 时运行。
- `tool_definitions.py`, `credential_definitions.py` — 若仅靠 registry 足够则省略

**移除现有 seed/script**:
- 删除 `backend/app/seed/prebuilt_connections.py`
- 删除 `backend/scripts/google_oauth_setup.py`

**验证**: `uv run alembic upgrade head` clean 重建。启动时输出 seed log。

### M5. agent_runtime 重新布线 + 密钥轮换 cron

**文件重新布线**:
- `backend/app/services/chat_service.py` — **全面重写 `build_tools_config()` + `get_agent_with_tools()`**。通过新 `tool.credential_id` 直连（废弃 default connection map）。PREBUILT/CUSTOM 分支 → 单一路径(definition + credential_id)。
- `backend/app/agent_runtime/executor.py` — 整理 import（`tool_factory` 只使用新系统）
- `backend/app/agent_runtime/tool_factory.py` — 委托新 `tools/runner.py` 简化
- `backend/app/agent_runtime/model_factory.py` — 解密 `agent.llm_credential` → 提取 API key
- `backend/app/agent_runtime/trigger_executor.py` — 调用 chat_service 新函数。**同时修复 L44-46 prefetch 遗漏 bug。**
- `backend/app/agent_runtime/creation_agent.py` — 仅跟随 chat_service 依赖
- `backend/app/agent_runtime/mcp_client.py` — 将 `${credential.<field>}` template 委托给 `app/credentials/interpolation.py`

**删除**:
- `backend/app/agent_runtime/naver_tools.py`
- `backend/app/agent_runtime/google_tools.py`
- `backend/app/agent_runtime/google_workspace_tools.py`
- `backend/app/agent_runtime/env_var_resolver.py`
- `backend/app/services/encryption.py`
- 旧 `backend/app/services/credential_service.py`
- 旧 `backend/app/services/credential_registry.py`
- `backend/app/services/connection_service.py`
- `backend/app/models/connection.py`
- `backend/app/routers/connections.py`

**密钥轮换 cron**:
- `backend/app/scheduler.py` — 在 APScheduler 注册 `rotate_credentials_to_active_key` job。每周1次（可配置）。批量重新加密所有 `key_id != active_key_id` 的 row。失败时下轮重试，audit log `rotate`。

**测试回归**:
- `backend/tests/` — 移除对 `naver_tools` 等的直接 import，fixture 更新为新结构
- `uv run pytest tests/ -v` 全部通过

**验证**: 聊天 → 工具调用 → executor 正常。手动运行 trigger 1次。手动触发 cron 后确认所有 row `key_id` 已变更。

### M6. Frontend（设计系统 → 页面）

**通用组件** — `frontend/src/components/`:
- `ui/data-table.tsx`（shadcn data-table base）— 排序/搜索/分页/filter
- `shared/status-chip.tsx` — variants: `active|auth_needed|expired|disabled|error|unknown`。自有设计 token。
- `shared/icon.tsx` — Lucide + 自有 SVG。
- `shared/empty-state.tsx`
- `shared/dynamic-fields-form.tsx` — **`FieldDef[]` → React form**:
  - 按类型 renderer: string / password(掩码+切换) / number / select / multiline / json / oauth_button / toggle / collection
  - 通过 `display_options.show` 条件 render
  - `type_options.password = true` → 始终掩码
  - `type_options.expirable = true` → 显示过期时间
  - 验证: required, regex, length
  - dirty 状态, 保存前 confirm

**Credentials 页面** — `frontend/src/app/credentials/page.tsx`:
- DataTable: 名称 / 定义(图标+名称) / 状态 chip / 最近使用 / 最近测试 / action
- 排序, 搜索, 定义 filter, 状态 filter
- 点击行 → Sheet (`credential-detail-sheet.tsx`)
- 顶部 "+ Credential" → `credential-create-modal.tsx` (Step: 定义目录 → 动态 form → Test → 保存)

**组件** — `frontend/src/components/credential/`:
- `credential-create-modal.tsx`, `credential-detail-sheet.tsx`, `credential-picker.tsx`, `credential-test-button.tsx`

**Tools 页面** — `frontend/src/app/tools/page.tsx`（重写）:
- tab: Catalog / Manage
- Catalog: category filter + card grid → 点击时打开实例创建 dialog
- Manage: DataTable

**组件** — `frontend/src/components/tool/`:
- `tool-catalog.tsx`, `tool-create-dialog.tsx`, `tool-detail-sheet.tsx`, `tool-run-panel.tsx`

**MCP 页面** — `frontend/src/app/mcp-servers/page.tsx` + `frontend/src/components/mcp/`:
- DataTable + 4-step wizard（基本信息 → 认证 → 工具搜索 → 确认）
- `mcp-server-wizard.tsx`, `mcp-server-detail-sheet.tsx`, `mcp-tool-table.tsx`

**Skills 页面** — `frontend/src/app/skills/page.tsx`（重写）+ `frontend/src/components/skill/`:
- DataTable + Grid toggle, kind badge
- `skill-detail-sheet.tsx` (text editor / package tree), `skill-upload-dialog.tsx`, `skill-package-tree.tsx`

**API client & hooks**:
- 新增 `frontend/src/lib/api/{credentials,tools,mcp,skills}.ts`
- 新增 `frontend/src/lib/hooks/{use-credentials,use-tools,use-mcp-servers,use-skills,use-credential-test}.ts`
- 新增 `frontend/src/lib/types/{credential,tool,mcp,skill}.ts`

**删除**:
- `frontend/src/app/connections/page.tsx`
- 现有整个 `frontend/src/components/{tool,connection,skill}/` 文件夹
- 旧 `frontend/src/lib/api/{tools,connections,credentials,skills}.ts` 文件
- 旧 `frontend/src/lib/hooks/use-{tools,connections,credentials,skills}*.ts` 文件

**导航**:
- 修改 `frontend/src/components/layout/sidebar.tsx` — Agents / Tools / MCP Servers / Skills / Credentials / Usage。移除 Connections 项。
- `frontend/src/app/agents/*` 工具·技能选择 UI 重新接到新的 hooks/api

**E2E**:
- 新增 `frontend/e2e/credentials.spec.ts`, `tools-catalog.spec.ts`, `mcp-server-wizard.spec.ts`, `skills-management.spec.ts`

**验证**: `pnpm build && pnpm lint && pnpm exec playwright test`

## 品牌验证（CI gate）

`scripts/check_branding.py` (M1):
- 若配置的禁用标识符 pattern 匹配源码树(`backend/`, `frontend/src`, 部分 `*.md`)则失败
- 若在 `pyproject.toml`, `package.json` 发现配置的禁用 package prefix 则失败
- 若 `frontend/public`, `frontend/src/assets` 的 SVG/PNG 文件 SHA-256 与 blacklist 一致则失败

CI pipeline:
1. `python scripts/check_branding.py`
2. `cd backend && uv run ruff check . && uv run pytest tests/ -v`
3. `cd frontend && pnpm lint && pnpm build && pnpm exec playwright test`

## 风险 & 应对

| 风险 | 应对 |
|---|---|
| 公开依赖 License | 外部分发前检查依赖 License。 |
| 品牌政策违规 | `scripts/check_branding.py` CI gate + 阻止 merge |
| OAuth refresh 并发 | 在 `oauth2_base` 中通过 `SELECT ... FOR UPDATE` 串行化 token 更新 |
| Vault 依赖 | feature flag 默认 off，fallback 到 env_provider。通过 dev container 做集成测试 |
| 聊天回归 | M5 重写 chat_service 后，优先立即通过聊天 + 工具调用 + trigger + MCP 集成场景回归测试 |
| dev DB 数据丢失 | PoC 阶段可接受。在 README 明确 m13 迁移时会初始化 |
| 单一 PR review 负担 | 将 M1~M6 milestone 各拆为独立 commit 提升 review 可读性（PR 仍只1次） |

## Verification (E2E)

```bash
# 品牌
python scripts/check_branding.py

# 后端
cd backend
uv run pytest tests/test_cipher.py tests/test_branding.py -v          # M1
uv run pytest tests/test_credentials.py tests/test_oauth2.py tests/test_tester.py tests/test_external_secrets.py -v  # M2
uv run pytest tests/test_tools.py tests/test_mcp.py -v                # M3
uv run pytest tests/test_skills.py -v                                 # M4
uv run pytest tests/ -v                                               # 全量回归

# 迁移 clean 重建
docker-compose down -v && docker-compose up -d postgres
uv run alembic upgrade head

# Frontend
cd ../frontend
pnpm lint && pnpm build
pnpm exec playwright test
```

### 手动场景（merge 前）
1. 在 build 产物中 grep 配置的禁用标识符 0项。未发现禁用资源。
2. 清空 `ENCRYPTION_KEYS` 后启动失败。
3. Credential 目录 → 选择定义 → 动态 form → Test → 保存 → DataTable 显示。
4. 注册 Google Workspace OAuth2 后模拟 token 过期 → 工具调用时自动 refresh，并在 audit log 记录 `refresh`。
5. 实例化 HTTP Request 工具 → 选择 Credential → 添加到智能体 → 在聊天中调用。
6. 通过 MCP 4-step wizard → 自动 import 工具 → "Test connection" 正常。
7. 上传 Skill package → 预览 tree/README → attach 到智能体 → deep agent 执行。
8. 将 `ENCRYPTION_KEYS=new,old` 修改后手动触发 cron → 所有 row `key_id` 变为 active key。audit log `rotate`。
9. 打开 Vault feature flag，在 dev Vault 保存 secret → 用 `__external__` marker credential 调用工具 → 正常。
10. `SELECT * FROM credential_audit_logs ORDER BY created_at DESC LIMIT 50` — 记录所有场景 event。
11. 状态 chip 在 Credentials/Tools/MCP/Skills 4个页面视觉一致。

## 核心文件路径摘要

### 新增（backend ~50, frontend ~30, script/doc 2）
- `backend/app/security/{cipher,key_provider}.py`
- `backend/app/credentials/{domain,field,authenticate,interpolation,registry,oauth2_base,tester}.py`
- `backend/app/credentials/external_secrets/{base,env_provider,vault_provider,proxy}.py`
- `backend/app/credentials/definitions/*.py` (~11)
- `backend/app/tools/{domain,registry,runner,parameters}.py` + `definitions/*.py` (~6)
- `backend/app/mcp/{domain,client,discovery,oauth}.py`
- `backend/app/skills/{service,packager,inspector,runtime}.py`
- `backend/app/models/{credential,credential_audit_log,credential_default,tool,mcp_server,mcp_tool,skill}.py`
- `backend/app/routers/{credentials,tools,mcp,skills}.py`
- `backend/app/seed/bootstrap_from_env.py`
- `backend/alembic/versions/m13_greenfield_credentials.py`
- `backend/tests/test_{cipher,credentials,oauth2,tester,external_secrets,tools,mcp,skills,branding}.py`
- `frontend/src/app/{credentials,mcp-servers,tools,skills}/page.tsx`
- `frontend/src/components/ui/data-table.tsx`
- `frontend/src/components/shared/{status-chip,icon,dynamic-fields-form,empty-state}.tsx`
- `frontend/src/components/{credential,tool,mcp,skill}/*.tsx`
- `frontend/src/lib/api/{credentials,tools,mcp,skills}.ts`
- `frontend/src/lib/hooks/use-{credentials,tools,mcp-servers,skills,credential-test}.ts`
- `frontend/src/lib/types/{credential,tool,mcp,skill}.ts`
- `frontend/e2e/{credentials,tools-catalog,mcp-server-wizard,skills-management}.spec.ts`
- `scripts/check_branding.py`
- `NOTICES.md`

### 修改
- `backend/app/main.py`, `app/config.py`, `app/scheduler.py`
- `backend/app/services/chat_service.py`（全面重写）
- `backend/app/agent_runtime/{executor,tool_factory,model_factory,trigger_executor,creation_agent,mcp_client}.py`
- `backend/.env.example`, `backend/pyproject.toml`(新增 hvac)
- `frontend/src/components/layout/sidebar.tsx`
- `frontend/src/app/agents/*`（工具·技能选择 UI）
- `frontend/package.json`

### 废弃（全部删除）
- `backend/app/services/{encryption,credential_service,credential_registry,connection_service}.py`
- `backend/app/models/connection.py`
- `backend/app/routers/connections.py`
- `backend/app/agent_runtime/{naver_tools,google_tools,google_workspace_tools,env_var_resolver}.py`
- `backend/app/agent_runtime/tool_factory.py` 的 auth 分支（吸收到重写）
- `backend/app/seed/prebuilt_connections.py`
- `backend/scripts/google_oauth_setup.py`
- `frontend/src/app/connections/page.tsx`
- 现有整个 `frontend/src/components/{tool,connection,skill}/` 文件夹
- 旧 `frontend/src/lib/api/{tools,connections,credentials,skills}.ts`
- 旧 `frontend/src/lib/hooks/use-{tools,connections,credentials,skills}*.ts`
