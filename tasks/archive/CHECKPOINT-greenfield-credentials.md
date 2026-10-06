# CHECKPOINT — Credential/Tools/Skills Greenfield Rewrite

**Plan**：`PLAN.md`（根目录），`/Users/chester/.claude/plans/plan-md-poc-lexical-bumblebee.md`
**Branch**：`feature/greenfield-credentials`（计划）
**Base**: `main @ 8d42ae1`
**PO**: Satya
**开始**：2026-04-29
**PR 单位**：单一 PR（每个 milestone 单独 commit）

---

## 决策事项 (不可变)

1. Cipher：HKDF-SHA256(info=`b'moldy-encryption-v1'`)，单 blob Base64（`[version 1B][salt 32B][authTag 16B][ciphertext]`），multi-key 标识使用独立 `credentials.key_id` column。
2. LLM model：保留 `models`（删除 api_key_encrypted），新增 `agents.llm_credential_id` FK，废弃 `llm_providers`。
3. 单一 PR。
4. Vault provider 实际实现（HVAC SDK，feature flag）。

---

## M0: governance + docs/ 初始化（Pichai DRI）

- [ ] `docs/ARCHITECTURE.md` 反映新 domain（credentials/tools/mcp/skills）
- [ ] `docs/design-docs/ADR-009-greenfield-credentials.md`（记录 greenfield 决策）
- [ ] 更新 `docs/design-docs/index.md` index
- [ ] `tasks/deletion-analysis.md`（由 Bezos 编写，确认废弃目标）
- 验证：`ls docs/ARCHITECTURE.md docs/design-docs/ADR-009-*.md tasks/deletion-analysis.md`
- done-when：4 个文件存在，ADR 正文编写完成
- 状态：done (2026-04-29)

## M1: branding 验证 + Cipher V2（Pichai + Bezos DRI）

- [ ] `scripts/check_branding.py`（检查已配置的禁止标识符、package prefix、asset SHA-256 blacklist）
- [ ] `backend/app/security/cipher.py` (info=`moldy-encryption-v1`)
- [ ] `backend/app/security/key_provider.py`（active key + verification keys）
- [ ] `backend/app/config.py` `encryption_keys: list[str]`（为空则启动失败）
- [ ] `backend/.env.example` `ENCRYPTION_KEYS` 示例
- [ ] `backend/tests/test_cipher.py`（round-trip, 多 key, key ID, corruption 验证）
- [ ] `backend/tests/test_branding.py`（直接调用 script）
- 验证：
  ```
  python scripts/check_branding.py
  cd backend && uv run pytest tests/test_cipher.py tests/test_branding.py -v
  ```
- done-when：branding 0 条，cipher 所有 case PASS
- 状态：done (2026-04-29, 24 tests PASS)

## M2: Credential domain + Vault + router（Jensen DRI）

- [ ] `backend/app/models/{credential,credential_audit_log,credential_default}.py`（新 schema）
- [ ] `backend/app/credentials/{field,domain,interpolation,authenticate,registry,oauth2_base,tester}.py`
- [ ] `backend/app/credentials/external_secrets/{base,env_provider,vault_provider,proxy}.py`（HVAC 实现）
- [ ] `backend/app/credentials/definitions/*.py` × 11
- [ ] `backend/app/routers/credentials.py`（重写，包含 OAuth2 route）
- [ ] `backend/tests/test_{credentials,oauth2,tester,external_secrets}.py`
- 验证：`cd backend && uv run pytest tests/test_credentials.py tests/test_oauth2.py tests/test_tester.py tests/test_external_secrets.py -v`
- done-when：CRUD/Test/OAuth2 mock refresh/Vault env_provider 通过
- 状态：done (2026-04-29, 44 新增 tests + 24 回归 tests = 68 PASS)

## M3: Tools 重定义 + MCP server（Jensen DRI）

- [ ] `backend/app/models/{tool,mcp_server,mcp_tool}.py`（新 schema）
- [ ] `backend/app/tools/{domain,registry,runner,parameters}.py`
- [ ] `backend/app/tools/definitions/*.py` × 6 (http_request, naver_search, google_search, gmail_send, google_calendar_event, google_chat_message)
- [ ] `backend/app/mcp/{domain,client,discovery,oauth}.py`
- [ ] `backend/app/routers/{tools,mcp}.py`
- [ ] `backend/tests/test_{tools,mcp}.py`
- 验证：`cd backend && uv run pytest tests/test_tools.py tests/test_mcp.py -v`
- done-when：tool catalog/实例化/HTTP 调用/MCP discover 通过
- 状态：done (2026-04-29, 29 新增 + 68 回归 = 97 PASS)

## M4: Skills + migration m13 + seed（Jensen + Pichai DRI）

- [ ] 重写 `backend/app/models/skill.py`（新增 content_hash, size_bytes, version 等）
- [ ] `backend/app/skills/{service,packager,inspector,runtime}.py`
- [ ] 重写 `backend/app/routers/skills.py`
- [ ] `backend/alembic/versions/m13_greenfield_credentials.py` (DROP+CREATE+ALTER agents.llm_credential_id, downgrade NotImplementedError)
- [ ] `backend/app/seed/bootstrap_from_env.py`（env → 自动创建 mock_user Credential）
- [ ] `backend/tests/test_skills.py`
- 验证：
  ```
  docker-compose down -v && docker-compose up -d postgres
  cd backend && uv run alembic upgrade head
  uv run pytest tests/test_skills.py tests/test_seed.py tests/test_migration_m18.py -v
  ```
- done-when：clean migration 成功，seed 正常，skills 测试通过
- 状态：done (2026-04-29, 31 新增 + 97 回归 = 128 PASS，alembic upgrade head 计划经用户确认后执行)
- 备注：migration 文件名因 m13 已被占用，命名为 `m18_greenfield_credentials`。down_revision=m17_add_agent_subagents。

## M5: agent_runtime rewire + key rotation cron（Jensen + Bezos DRI）

- [ ] 全面重写 `backend/app/services/chat_service.py`（build_tools_config + get_agent_with_tools）
- [ ] rewire `backend/app/agent_runtime/{executor,tool_factory,model_factory,trigger_executor,creation_agent,mcp_client}.py`（同时修复 trigger_executor L44-46 prefetch bug）
- [ ] `backend/app/scheduler.py` 注册 `rotate_credentials_to_active_key` job
- [ ] 废弃：`services/{encryption,credential_service,credential_registry,connection_service}.py`, `models/connection.py`, `routers/connections.py`, `agent_runtime/{naver_tools,google_tools,google_workspace_tools,env_var_resolver}.py`, `seed/prebuilt_connections.py`, `scripts/google_oauth_setup.py`
- [ ] 全量回归测试
- 验证：`cd backend && uv run pytest tests/ -v && uv run ruff check .`
- done-when：全部 PASS，ruff clean，chat + trigger + MCP 场景 OK
- 状态：done (2026-04-29, 480 backend tests PASS，新建 test_chat_integration.py / test_rotation.py 6 条 PASS，branding 0 条，ruff clean)

## M6: frontend（Tim Cook + Zuckerberg DRI）

**Tim Cook**（design system）：
- [ ] `frontend/src/components/ui/data-table.tsx`
- [ ] `frontend/src/components/shared/{status-chip,icon,empty-state,dynamic-fields-form}.tsx`

**Zuckerberg**（page / component / API）：
- [ ] `frontend/src/app/{credentials,mcp-servers,tools,skills}/page.tsx`
- [ ] `frontend/src/components/{credential,tool,mcp,skill}/*.tsx`
- [ ] `frontend/src/lib/{api,hooks,types}/{credentials,tools,mcp,skills}*.ts`
- [ ] 整理 `frontend/src/components/layout/sidebar.tsx` navigation（移除 Connections）
- [ ] rewire `frontend/src/app/agents/*` 的 tool·skill 选择 UI 到新 hooks/api
- [ ] `frontend/e2e/{credentials,tools-catalog,mcp-server-wizard,skills-management}.spec.ts`
- [ ] 废弃：`app/connections/`, `components/{tool,connection,skill}/` 旧 folder，旧 api/hooks 文件
- 验证：
  ```
  cd frontend && pnpm lint && pnpm build
  pnpm exec playwright test
  ```
- done-when：build 成功，E2E 4 个通过
- 状态：done (2026-04-29, frontend pnpm build PASS / pnpm lint clean（1 个 informational warn）/ branding 0 条。E2E specs 4 个已编写完成，Playwright 执行交由用户)

---

## M7: model catalog + discovery（LiteLLM + 自有 filtering）

**DRI**：Jensen (Backend) + Tim Cook/Zuckerberg (Frontend) + Bezos (验证)
**原因**：M5 将 `models` table 缩减为 read-only，但新增 model 只能通过修改 seed code + restart → 不实用。通过 List/Custom ID 两种模式 + LiteLLM enrichment，使 UI 可添加/管理 model。

### 借用模式
- model 选择提供 List（discovery）+ Custom ID（直接输入）两种模式
- 同时暴露官方 host whitelist / compatible endpoint
- provider-specific filter rule 单一入口（provider）
- **OpenRouter pricing 优先** + **LiteLLM catalog fallback** + **manual override**
- **multi-provider Gateway 定义**：OpenAI Compatible / OpenRouter（可选：Vercel AI Gateway）

### 后端
- [ ] 恢复 `app/services/model_metadata.py`（LiteLLM enrich，借用旧代码）
- [ ] 新建 `app/services/model_filtering.py` — `should_include_model(provider, model_id, is_custom_api)`
- [ ] 重写 `app/services/model_discovery.py` — Credential-based dispatch + isCustomAPI 分支（Credential）
- [ ] `app/credentials/definitions/` 新增定义：`openrouter`, `openai_compatible`（vercel_ai_gateway 后续）
- [ ] 增强 `app/routers/models.py`：新增 POST/PATCH/DELETE，Source badge（litellm/openrouter/manual）
- [ ] 增强 `app/routers/credentials.py`：`POST /api/credentials/{id}/discover-models`
- [ ] 增强 `app/schemas/model.py`：`DiscoveredModel`, `source` field
- [ ] 新建 `tests/test_model_discovery.py`, `test_model_metadata.py`, `test_model_filtering.py`

### frontend
- [ ] 新建 `frontend/src/app/models/page.tsx` — DataTable + source badge
- [ ] 新建 `frontend/src/components/model/model-add-dialog.tsx` — Tab Discover/Custom ID
- [ ] 新建 `frontend/src/components/model/model-edit-dialog.tsx` — pricing override
- [ ] 新建 `frontend/src/components/model/model-discover-panel.tsx` — Credential 选择 + result list + multi-select
- [ ] `frontend/src/components/layout/app-sidebar.tsx` — 增加 Models 项
- [ ] 升级 `frontend/src/components/model/model-select.tsx` — List/Custom ID 两种模式
- [ ] 增强 `frontend/src/lib/api/models.ts`, `lib/hooks/use-models.ts`, `lib/types/model.ts`
- [ ] 新建 `frontend/e2e/models-discover.spec.ts`

### 验证
```bash
cd backend && uv run pytest tests/test_model_*.py -v && uv run pytest tests/ -v && uv run ruff check .
cd frontend && pnpm lint && pnpm build
python scripts/check_branding.py
```
- done-when：model discovery 可用，OpenRouter pricing 自动，LiteLLM fallback，Custom ID 直接输入，user pricing override，480+ tests PASS，branding 0 条
- 状态：backend done (2026-04-29, 63 新增 + 480 回归 = 543 PASS，ruff clean，branding 0 条，m19 upgrade/downgrade/upgrade round-trip OK against PG 5433)
- 备注：migration 文件名为 `m19_add_models_source.py`（down_revision=m18_greenfield_credentials，ADD COLUMN nullable，支持 drop downgrade）。frontend/M7 产物由其他负责人（Tim Cook/Zuckerberg）进行中。

---

## M8: model Test + Curl 生成 + MCP Registry（借用 LiteLLM）

**DRI**：Jensen (Backend) + Tim Cook/Zuckerberg (Frontend)
**原因**：立即验证已注册/新 model 是否真正可调用（Credential test ≠ Model test）。MCP server 可从 GitHub/Linear/Jira/Slack/Notion catalog 1-click 添加。

### 借用模式（LiteLLM）
- **`POST /health/test_connection`**：单 model 验证（LangChain ainvoke + usage_metadata）
- **`model_connection_test.tsx`**：自动执行 + raw req/resp + Curl 命令 + Clean error
- **`mcp_registry.json`**：预注册 MCP server catalog（GitHub/Jira/Linear/Slack/Notion）

### 后端
- [x] 新建 `services/model_test.py` — `run_model_test()`, clean-error regex, classify, masked curl
- [x] 新建 `services/mcp_registry.py` — JSON lazy loader
- [x] 新建 `data/mcp_server_registry.json` — 5 种（github, linear, jira, slack, notion）
- [x] `agent_runtime/model_factory.create_chat_model_for_test()` (max_tokens=10, temp=0)
- [x] `schemas/model.py`: ModelTestPreviewRequest/ModelTestResponse
- [x] `schemas/mcp.py`: McpRegistryEntry, McpServerCreateFromRegistry
- [x] `routers/models.py`: POST /test, POST /test-preview
- [x] `routers/mcp.py`: GET /api/mcp-server-types, POST /api/mcp-servers/from-registry
- [x] `tests/test_model_test.py` (27), `test_mcp_registry.py` (11)

### frontend
- [x] `components/model/model-connection-test.tsx` — autoStart + Show Details (Request/Response/Curl) + Copy
- [x] `components/model/model-test-dialog.tsx`（row action）+ `model-test-bulk-dialog.tsx`（bulk）
- [x] 集成 5 处：row Test / multi-select Test Selected / ModelAddDialog Custom ID / ModelEditDialog / ModelSelect Custom ID
- [x] `components/mcp/mcp-server-wizard.tsx` — Step 1 增加 From Registry/Manual tab
- [x] `components/ui/data-table.tsx` — 支持 enableRowSelection, toolbar
- [x] 增强 lib/{api,hooks,types}/{model,mcp}
- [x] `e2e/model-test.spec.ts` + `e2e/mcp-registry.spec.ts` (3/3 PASS)

### 验证
```bash
cd backend && uv run pytest tests/test_model_test.py tests/test_mcp_registry.py -v   # 38 PASS
uv run pytest tests/ -v   # 581 PASS（38 新增 + 543 回归）
uv run ruff check .       # clean
cd ../frontend && pnpm lint && pnpm build && pnpm exec playwright test e2e/model-test.spec.ts e2e/mcp-registry.spec.ts
python scripts/check_branding.py   # 0 条
```
- done-when：38 新增 PASS + 回归 0，e2e PASS，branding 0 条
- 状态：done (2026-04-30, 38 新增 + 543 回归 = 581 PASS，e2e 3/3 PASS，build PASS)

---

## M9: Hook/Middleware 框架 + Health Check + History（计划中）

**DRI**: 詹森
**为什么**: 通过 pre/post-call hook 一致应用 Spend/权限/审计等 cross-cutting concerns + 定期验证已注册的模型/MCP 是否存活 + 时间序列 history。

### 范围（借鉴 LiteLLM）
- 新增 `app/hooks/` — `CustomHook` 基类 + `HookRegistry` 分发器 + `LoggingHook`/`AuditHook` 内置
- 在 `executor.py`/`tool_factory`/`mcp_client` 调用点集成 hook（failure isolation try/except）
- 新增 `models/health_check_history.py` — target_kind, target_id, status, latency_ms, error_kind/message, checked_at
- 新增 `services/health_check.py` — 执行 model + MCP health check + DB 记录（`check_model`/`check_mcp_server`/`check_all_active`）
- `scheduler.py` — `health_check_all_active` 每日 cron 任务（`settings.health_check_cron` 默认 `"0 4 * * *"`）
- 新增 `alembic/versions/m20_add_health_check_history.py` — dialect-aware UUID/timestamp + 索引 + reversible downgrade
- 新增 `routers/health.py` — GET /api/health/{models,mcp-servers,history}, POST /api/health/check
- 前端：模型/MCP 页面增加 status 列 + 点击行时显示 history 图表（后续）
- 状态: backend done (2026-04-29, 22 新增 + 581 回归 = 603 PASS, ruff clean, branding 0项, m20 upgrade/downgrade/upgrade roundtrip PG 5433 OK)

## M10: Spend Queue + Dashboard + Model Fallback

**DRI**: 詹森 (backend) + 扎克伯格/蒂姆·库克 (frontend)
**为什么**: 成本追踪准确度/性能 + 运营可见性 + 稳定性。

### 范围（借鉴 LiteLLM）
- `services/spend_writer.py` — DailySpendUpdateQueue (asyncio.create_task + Redis 缓冲可选 + batch flush)
- 6个 daily aggregate 表 (user/agent/model/credential/team[后续]/tag[后续])
- 加强 `app/usage/` 页面 — 自制 SVG 图表 (line/bar) + 时间/模型/智能体筛选
- `models/agent.py`: 新增 `model_fallback_list: list[UUID]` + 迁移 m22
- `model_factory`: try/except 链 (primary fail → fallback)

### Frontend（扎克伯格/蒂姆·库克 done, 2026-04-29）
- 新增 `lib/types/usage.ts` — `UsageDailyEntry`, `UsageDailyParams`, `UsageTargetKind`, `UsageGroupBy`, `UsageMetric`
- 加强 `lib/api/usage.ts` — `usageApi.daily()` + `getDailyAggregate()`
- 加强 `lib/hooks/use-usage.ts` — `useDailyAggregate(params)` (cache key = params 对象)
- `lib/types/index.ts` — 新增 `Agent.model_fallback_ids?: string[] | null`, `AgentCreate/UpdateRequest.model_fallback_ids`
- 全面重写 `app/usage/page.tsx` — 4 Summary cards (本月费用/令牌/请求/平均) + 筛选栏(7d/30d/90d/Custom + User/Agent/Model + Date/Target + cost/tokens/requests metric) + 自制 SVG line/bar chart + raw 表格 + CSV 下载 + EmptyState
- 新增 `components/usage/{spend-line-chart,spend-bar-chart,format}.tsx` — 自制 SVG (借鉴 M9 health-history-chart 模式, viewBox + path/area, status-coloured points)。图表库新增依赖 0项。
- 加强 `app/agents/[agentId]/settings/_components/dialogs/model-dialog.tsx` — Fallback Models 区域 (details + 用上/下按钮调整顺序, 未引入 dnd-kit)。最多5个。重复警告。PATCH 时包含 `model_fallback_ids`。
- `app/agents/[agentId]/settings/_components/form-mode/{section-model,form-mode}.tsx` — fallback prop chain + section-model 增加 `+N fallback` 徽章
- `components/agent/agent-card.tsx` — Primary 模型旁增加 `+N fallback` 徽章（仅存在时）
- `app/agents/[agentId]/settings/page.tsx` — 新增 fallbackIds state + isDirty + save 时传递 model_fallback_ids
- `messages/ko.json` — 新增 `usage.filters/metric/summary/fallback`, `agent.card.fallbackTitle`, `usage.fallback.*`
- `playwright.config.ts` — 可通过 `PW_SKIP_BACKEND=1` 环境变量 skip backend webServer（用于 fully-mocked spec）
- 新增 `e2e/spend-dashboard.spec.ts` — 3 个场景 (summary cards + line/bar 切换 + CSV 启用 + empty state)
- 新增 `e2e/model-fallback.spec.ts` — 进入 settings → ModelDialog → Fallback 区域 → +Add → Save → 捕获并验证 PATCH body 的 `model_fallback_ids`
- 验证: `pnpm lint` clean, `pnpm build` PASS, `python scripts/check_branding.py` 0项, `PW_SKIP_BACKEND=1 pnpm exec playwright test e2e/spend-dashboard.spec.ts e2e/model-fallback.spec.ts` 4/4 PASS
- 发现问题: 本地 PG (port 5432) 停留在 m17_add_agent_subagents，因此 backend(m22 head) 启动时出现 `column models.max_output_tokens does not exist` 错误。PoC 阶段需要应用 `alembic upgrade head`（属于数据丢失操作，需用户确认后执行）。
- 状态: frontend done (扎克伯格/蒂姆·库克, 2026-04-29)。backend done (詹森, 2026-04-29)。

### Backend（詹森 done, 2026-04-29）
- 新增 `models/{daily_spend_user,daily_spend_agent,daily_spend_model}.py` — Numeric(20,8) cost, unique (date, target_id), CASCADE on FK target。
- `alembic/versions/m21_add_daily_spend_aggregates.py` — 3个表 + 索引 (down_revision=m20)。dialect-aware, idempotent helpers, reversible。
- `alembic/versions/m22_add_agent_model_fallback.py` — `agents.model_fallback_list JSON NULLABLE` (down_revision=m21). reversible.
- 新增 `services/spend_writer.py` — `SpendEntry` dataclass + `DailySpendUpdateQueue` (基于 asyncio.Queue + 后台 drain task + flush_interval/batch_size 触发器 + dialect-aware ON CONFLICT UPSERT, 同时支持 PG/SQLite, 包含 application-level fallback)。模块全局 `spend_queue` 单例。
- 新增 `hooks/builtin/spend_hook.py` — 在 `agent_invoke` post hook 中调用 `spend_queue.add()`。failure isolation (try/except + warning)。
- 加强 `hooks/{__init__,builtin/__init__}.py` — 注册 `SpendHook`。
- `main.py` lifespan — `spend_queue.start()` (进入 lifespan 时) + `spend_queue.stop()` (graceful shutdown — 剩余 flush 后 cancel)。
- `agent_runtime/streaming.py` — 在 `stream_agent_response` 增加 `usage_sink: dict | None`，流结束时将 `prompt_tokens/completion_tokens/estimated_cost` surface 到 callback dict。
- `agent_runtime/executor.py` — 新增 `_build_model_with_fallback(cfg)` helper (executor-side, DB-free 链 walk + recoverable error 分支)。通过 `_hook_result_from_usage()` helper 将 streaming-captured usage → `HookResult.tokens_in/out/cost_usd` 映射。新增 `AgentConfig.model_fallback_chain` 字段。
- `agent_runtime/model_factory.py` — 新增 `create_chat_model_with_fallback(agent, db, ...)`。尝试 primary → recoverable 错误时 walk fallback 链。每次尝试记录 audit log `fallback` action (`success: bool`, `provider`, `model_name`, `model_id`, `error`)。`_is_fallback_recoverable(exc)` 分类器 (401/403/404/408/409/429/5xx + TimeoutError/HTTPError/ConnectionError)。
- `routers/conversations.py` + `agent_runtime/trigger_executor.py` — 通过 `_resolve_fallback_chain(db, fallback_list)` helper 将 `agent.model_fallback_list` (UUID strings) → 链 dict 列表预先解析后注入 `AgentConfig.model_fallback_chain`。缺失的 model row silent drop。
- `models/agent.py` — 新增 `model_fallback_list: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)`。
- `schemas/agent.py` — 在 `AgentCreate/Update/Response` 增加 `model_fallback_ids: list[uuid.UUID] | None` (Response 是 default factory empty list)。
- `services/agent_service.py` — 新增 `_validate_model_fallback_ids()` (existence check)，在 create/update 中验证 + JSON 序列化 (str(uuid))。
- `routers/agents.py` — 在 `_agent_to_response()` 中将 `model_fallback_list` (str list) → `model_fallback_ids` (UUID list) 转换。错误 entry silent drop。
- 新增 `services/usage_aggregate.py` — `get_daily_spend(target_kind, target_id, from_date, to_date, group_by)`。tenancy: user 轴直接 FK, agent 轴 `Agent.user_id` join, model 轴 (per-model 表是 cross-user) 通过 `DailySpendAgent → Agent` join 仅汇总*当前用户 contribution*。`group_by=target` 时自动 fill user/agent/model 各自 label。
- 加强 `routers/usage.py` — 新增 `GET /api/usage/daily?target_kind=&target_id=&from=&to=&group_by=`。
- `NOTICES.md` — 在 LiteLLM 借鉴表中新增 `spend_writer.py` (DailySpendUpdateQueue), `usage_aggregate.py` (daily aggregate read API), `create_chat_model_with_fallback` (router fallback walk) 行 + 加强正文段落。
- 测试:
  - `test_spend_writer.py` (8) — flush_batch / ON CONFLICT 累计 / target 缺失时 axis skip / loop interval / stop drain / queue full degrade / distinct dates / Decimal precision
  - `test_usage_aggregate.py` (6) — user 轴时间序列 / agent 轴 group_by=target label / model 轴 agent join scope / window 筛选 / target_id 筛选 / cross-tenant isolation
  - `test_model_fallback.py` (9) — recoverable classifier 3种 / executor chain (primary→fallback / 全部失败 / unrecoverable / no chain) / `create_chat_model_with_fallback` audit (成功+失败) / no chain
  - `test_migration_m21.py` (4) + `test_migration_m22.py` (4) — module imports / metadata / round-trip / idempotent
  - 更新 `test_hooks.py` — 验证 `register_default_hooks_idempotent` 包含 spend_hook
- 验证：
  - `uv run pytest tests/ -v`: **634 PASS** (31 新增 + 603 回归)。
  - `uv run ruff check .`: clean.
  - `python scripts/check_branding.py`: 0项。
  - PG 5433 round-trip: m20 → m21 → m22 → downgrade -2 → upgrade head 全部成功。在容器中确认存在 `daily_spend_*` 3个表 + `agents.model_fallback_list` 列。

---

## Gate 政策

- **品牌 0项**: 未通过 `python scripts/check_branding.py` 不可 merge
- **数据丢失操作** (docker volume 删除, m13 alembic upgrade): 用户确认后执行
- **3次失败**: escalation 给萨提亚 → 重新拆分 story 或缩小 scope
- **每个 milestone 提交**: 每个 milestone 完成时 1 个 commit

---

# CHECKPOINT — UI Refactor (Sprint 1~4)

**Plan**: `~/.claude/plans/buzzing-prancing-cloud.md`
**Started**: 2026-05-01
**PO**: 萨提亚 / DRI(设计): 蒂姆·库克 / DRI(实现): 扎克伯格 / DRI(验证): 贝索斯
**Scope**: 仅 frontend/。无 backend 变更。

## M-UI1: Sprint 1 — 设计 token + DialogShell + Sheet→Dialog 转换 + UI 基础整备
- [ ] `src/app/globals.css` `--primary`/`--ring` emerald 映射 + 新增 `--primary-strong`
- [ ] `src/components/ui/{input,textarea,select,button,checkbox}.tsx` 放宽 focus-visible (移除 border-ring, ring-3→ring-2)
- [ ] `src/components/ui/dialog.tsx`/`sheet.tsx` 基础 tone 整备 (rounded-2xl, ring-border/60, X 按钮, backdrop)
- [ ] `src/lib/design-tokens.ts` (DIALOG_SIZE 5级 + DIALOG_HEIGHT 3级)
- [ ] `src/lib/constants/{model,timing,usage}.ts`
- [ ] `src/components/shared/dialog-shell.tsx` (Header/Body/Footer/Sidebar slot, 强制视觉规范)
- [ ] `src/components/shared/{page-shell,error-state,delete-confirm-inline,form-footer}.tsx`
- [ ] `src/components/shared/base-detail-dialog.tsx`
- [ ] 4种 Sheet→Dialog 转换: 新增 credential/skill/tool/mcp `*-detail-dialog.tsx` + 替换调用处 + 删除现有 `*-detail-sheet.tsx`
- 验证: `cd frontend && pnpm lint && pnpm build` (TS 错误 0, 构建成功)
- done-when: 上述8项 + Sheet 残留使用处 = 仅移动端 sidebar + 对话列表 2处
- 状态: pending

## M-UI2: Sprint 2 — 页面迁移 + raw color token 化 + i18n
- [ ] 5个 page.tsx (tools/models/skills/mcp-servers/credentials) → PageShell + isError 分支
- [ ] raw `bg-emerald-*` 等 58次 → `bg-primary`/`text-primary-strong` 等 token
- [ ] 4处韩文 + 4处英文 header → next-intl message
- 验证: `pnpm lint && pnpm build`
- done-when: 5个页面中 `flex flex-1 flex-col gap-6 ... p-6` inline 0处
- 状态: pending

## M-UI3: Sprint 3 — 智能体表单 RHF + Zod
- [ ] `app/agents/[agentId]/settings/page.tsx` (518行, useState 21个) → RHF + Zod
- [ ] `app/agents/new/manual/page.tsx` 复用相同 schema
- 验证: `pnpm build` + visual regression (保存/Dirty/取消行为)
- done-when: useState 21→1 (form), 删除手动 dirty 195行
- 状态: pending

## M-UI4: Sprint 4 — 性能 (bundle/rerender/Suspense)
- [ ] `app/agents/[agentId]/visual-settings/page.tsx` xyflow `next/dynamic`
- [ ] `components/chat/markdown-content.tsx` syntax-highlighter lazy
- [ ] `components/agent/visual-settings/visual-settings-flow.tsx` 拆分 useEffect + hoist initialNodes
- [ ] 修复 `components/chat/assistant-thread.tsx:289` key
- [ ] 引入 Suspense 边界 (聊天/visual-settings/usage)
- 验证: `pnpm build` chunk 大小比较 + visual regression
- done-when: visual-settings chunk 小于 main route, key 反模式 0项
- 状态: pending
