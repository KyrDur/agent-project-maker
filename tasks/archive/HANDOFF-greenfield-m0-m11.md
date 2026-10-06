# HANDOFF — Credential/Tools/Skills/Models Greenfield 重写 + 运营基础设施

**项目**: natural-mold(Moldy) — Credential·Tools·Skills·Models Greenfield + Hook + Health + Spend + Fallback
**分支**: `feature/greenfield-credentials`
**工作日**: 2026-04-29 ~ 2026-04-30 (2 session, 11 milestone)
**团队**: 萨提亚(PO) + 皮查伊 + 詹森 + 贝索斯 + 蒂姆·库克 + 扎克伯格 (TTH silo)
**参考**: `PLAN.md`, `CHECKPOINT.md`, `docs/design-docs/adr-009-greenfield-credentials.md`

## Milestone 进展 (M0~M10)

| | 内容 | 新增 tests | 累计 PASS |
|---|---|:---:|:---:|
| M0 | 治理 + ADR-009 | — | — |
| M1 | 品牌验证 + Cipher V2 | 24 | 24 |
| M2 | Credential domain + Vault | 44 | 68 |
| M3 | Tools 12个 + MCP 服务器 | 29 | 97 |
| M4 | Skills 重写 + alembic m18 | 31 | 128 |
| M5 | agent_runtime 重新布线 + 密钥轮换 cron | 6 + 删除旧 21 | 480 |
| M6 | 前端 (设计系统 + 4页 + E2E) | E2E 4 | — |
| M7 | 模型目录 + Discovery (LiteLLM + 自有筛选) | 63 | 543 |
| M8 | 模型 Test + Curl + MCP Registry | 38 + e2e 3 | 581 |
| M9 | Hook 框架 + Health Check + History | 22 + e2e 2 | 603 |
| M10 | Spend Queue + Aggregate API + Model Fallback + Dashboard | 31 + e2e 4 | **634** |

---

## 1. 变更摘要

### 后端
- **Cipher V2**: AES-256-GCM + HKDF-SHA256 (info=`moldy-encryption-v1`), 单一 blob Base64, 多密钥识别 `credentials.key_id`
- **新增 Credential domain** (`app/credentials/`): field/domain/interpolation/authenticate/registry/oauth2_base/tester/service + external_secrets/{base,env_provider,vault_provider(HVAC),proxy} + 11个定义
- **新增 Tools domain** (`app/tools/`): ToolDefinition 单一路径 + 12个工具定义 (HTTP Request 1 + Naver 5 + Google 搜索 3 + Gmail/Calendar/Chat 3)
- **新增 MCP domain** (`app/mcp/`): client + discovery + oauth (env_vars interpolation 委托)
- **Skills 重写** (`app/skills/`): kind(text|package) + content_hash + package_metadata + zip-slip 防御
- **agent_runtime 重新布线**: chat_service.build_tools_config 单一路径, model_factory 解密 llm_credential, 修复 trigger_executor prefetch bug
- **密钥轮换 cron**: APScheduler job + audit log `rotate`
- **迁移 m18**: 所有相关表 DROP+CREATE, agents.llm_credential_id ADD, downgrade NotImplementedError

### frontend
- **设计系统**: data-table (TanStack Table), status-chip, icon (Lucide), dynamic-fields-form (8种 renderer), empty-state
- **新增/重写4个页面**: credentials, tools(Catalog/Manage tab), mcp-servers(4-step wizard), skills
- **sidebar 整理**: 移除 Connections, 新增 MCP Servers
- **agents UI 重新布线**: 将工具·技能选择替换为新的 hooks/types

### License / 品牌
- **scripts/check_branding.py**: 检查已配置的禁用标识符、package prefix、资源 SHA-256 blacklist 的 CI gate

---

## 2. 架构决策 (ADR-009)

| # | 决策 | 依据 |
|---|---|---|
| 1 | 废除 Connection 双轨制 | Tool 直接 `credential_id` FK, 认证单一路径 |
| 2 | Cipher V2 | HKDF-SHA256 + AES-256-GCM, `moldy-encryption-v1` |
| 3 | LLM 模型整合 | 保留 `models` + `agents.llm_credential_id`, 废弃 `llm_providers` |
| 4 | OAuth2 自动 refresh | preAuthentication 模式, `SELECT ... FOR UPDATE` 并发 |
| 5 | External Secrets (Vault) | HVAC SDK 实现, feature flag 默认 off |
| 6 | 自动密钥轮换 | APScheduler 每周1次, 用活动密钥重新加密 + audit |
| 7 | 单一 PR + 按 milestone 提交 | 避免 dual 系统, 提升 review 可读性 |
| 8 | m18 单一迁移 | dev DB 可废弃 OK (PoC), downgrade NotImplementedError |

---

## 3. 已删除项 (Musk Step 2)

### Backend (21 prod + 21 tests)
- `services/{encryption, credential_service, credential_registry, connection_service, provider_service, model_discovery, skill_service, env_var_resolver, legacy_invariants}.py`
- `agent_runtime/{naver_tools, google_tools, google_workspace_tools, google_auth, env_var_resolver}.py`
- `models/{connection, llm_provider}.py`
- `routers/{connections, providers}.py`
- `schemas/{connection, llm_provider}.py`
- `seed/{prebuilt_connections, default_tools, default_providers}.py`
- `scripts/google_oauth_setup.py`
- 旧测试 21个 (test_connections, test_connection_*_resolve, 旧 test_tools, 旧 test_tool_factory 等)

### Frontend (~24)
- `app/{connections, models}/page.tsx`
- 整个 `components/{connection, model}/` 文件夹
- `components/tool/` 的旧文件 (add-tool-dialog, credential-form-dialog, credential-select, mcp-server-group-card)
- `lib/api/{connections, providers, models, middlewares}.ts` (旧)
- `lib/hooks/use-{connections, providers, models, middlewares}.ts` (旧)

---

## 4. 验证结果（最终）

| Gate | 结果 | 备注 |
|---|:---:|---|
| `python scripts/check_branding.py` | PASS | 0 violations |
| `cd backend && uv run pytest tests/` | PASS | **480 passed**, 1 deselected, 1 warning (TestRequestSpec 无害) |
| `cd backend && uv run ruff check .` | PASS | 0 errors |
| `cd frontend && pnpm lint` | PASS | 0 errors, 1 informational warn |
| `cd frontend && pnpm build` | PASS | 16 routes |
| `alembic upgrade head` | DEFERRED | 用户确认后执行（data-loss 操作） |
| Playwright E2E | DEFERRED | 已编写4个 specs, 需要启动 backend |

---

## 5. Ralph Loop 统计

- 总 story (S0~S18): **19个**
- 1次通过: **18个** (S0~S17)
- 重试后通过: **1个** (M5 ruff 4项由萨提亚直接整理)
- escalation: **0项**
- milestone 划分: M0~M6 (6个), 全部 gate PASS

---

## 6. 剩余工作 / 后续

### 立即（PR merge 前）
- [ ] **用户确认后执行**: `docker-compose down -v && docker-compose up -d postgres && cd backend && uv run alembic upgrade head` (废弃 dev DB → 应用 m18~m22)
- [ ] **用户执行**: `cd backend && uv run uvicorn app.main:app --reload --port 8001` 后执行 `cd frontend && pnpm exec playwright test`
- [ ] **依赖 License 检查1次** (外部分发时 — 确认公开依赖适用性)

### 单独 ticket（后续）
- [ ] `agent_mcp_servers` link table — 将 MCP 工具直接连接到智能体
- [ ] OAuth2 callback state Redis/DB backing (当前 in-process map)
- [ ] `TestRequestSpec` → `CredentialTestSpec` rename (pytest collection warning)
- [ ] 新增 Vault AppRole/JWT 认证
- [ ] 支持 OAuth2 PKCE
- [ ] 加强 interpolation sandbox
- [ ] Skills package sandbox 执行
- [ ] **Health check history 保留清理 cron** (`health_check_history_retention_days=90` 仅新增了列)
- [ ] **扩展 mcp_server_registry.json**: Discord, Confluence, Asana, Trello 等
- [ ] **Spend dashboard CSV 下载** (router 增加 export endpoint)
- [ ] **Model Fallback 拖拽排序** (当前只有上/下箭头)
- [ ] **Vercel AI Gateway Credential 定义** (M7 后续决定)
- [ ] **Hook 注册 admin UI** — 用户可直接 hook on/off
- [ ] **Object Permission 中心化** (LiteLLM 模式 — 转为多租户时)

---

## 7. 学到的经验（摘自 progress.txt）

### M2 — Credential domain
- aiosqlite 不会自动 enforce FK CASCADE — 仅在 PostgreSQL 环境验证
- OAuth2 state 为 in-process map (仅限 PoC)，多进程时需要 backing

### M3 — Tools + MCP
- 旧 `assistant`/`builder` 路径 import 旧 `ToolType/ToolResponse` → 通过保留 alias 保持 import-time 兼容，M5 统一废弃
- MCP stdio transport 不支持 probe — 仅 discovery sse/streamable_http

### M4 — Skills + 迁移
- 迁移编号 m13 已占用 → 命名为 **m18** (现有 m13~m17 均已使用 — 初始探索遗漏)
- `LLMProvider` 因 services 依赖保留模型文件 (M5 统一删除)。仅移除 back_populates 防止 mapper 冲突

### M5 — agent_runtime 重新布线
- 废弃 chat_service `_default_connection_map` → 通过单一路径确保一致性
- 将 trigger_executor.py L44-46 prefetch bug 统一到新的单一入口并修复
- 批量删除旧代码 21 prod + 21 tests，减少 ~3,000 LOC

### M6 — Frontend
- TanStack Table v8 + React 19 react-hooks/incompatible-library warning 无害 (informational)
- E2E 使用 page.route mocking 模式 — backend 启动后可重新指向 live API

---

## 8. Commit history

```
1e1df7f [feat] M6: Frontend Greenfield (设计系统 + 4页 + E2E)
4cfdd2b [refactor] M5: agent_runtime 重新布线 + 密钥轮换 cron + 旧代码清理
ca0d58c [feat] M4: Skills 重写 + m18 迁移 + bootstrap seed
f02b537 [feat] M3: Tools 重定义 + MCP 服务器 domain
f9ee447 [feat] M2: Credential domain + Vault + router
b87664e [chore] M0+M1: 治理 + 品牌验证 + Cipher V2
```

---

## 9. PR 编写指南

```bash
gh pr create \
  --base main \
  --title "Credential / Tools / Skills Greenfield 重写" \
  --body-file HANDOFF.md
```

**标签**: `breaking-change`, `database-migration`, `frontend`, `backend`, `security`
**Reviewer**: backend 1人 + frontend 1人 + security 1人（如可能）

---

**判定**: **GO** — 可合并为单一 PR。6个 milestone 全部 gate PASS, 480 backend tests + frontend build PASS, branding 0项。

**END OF HANDOFF**
