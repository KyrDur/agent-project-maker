# Moldy — AI Agent Builder

<!-- project-current-source: migration=m77_side_chat_link; deepagents=0.7.11; ruff=0.16.5; refreshed=2026-09-10 -->

一个无需代码即可创建、聊天并调度 AI Agent 的 Web 应用。
**已根据 ADR-016 完成多用户认证**（JWT + super_user）。运营者（super_user）与普通用户的权限已分离。

---

## 技术栈

| 层级 | 技术 | 版本 |
|--------|------|------|
| Frontend | Next.js (App Router) + React + TailwindCSS v4 + shadcn/ui | Next 16, React 19 |
| 状态管理 | TanStack Query（服务端）、Jotai（客户端） | |
| Backend | FastAPI + SQLAlchemy (async) + Alembic | FastAPI 0.115+, SA 2.0+ |
| AI Runtime | LangChain 1.x + LangGraph 1.x + **deepagents** 0.7.11 + LangSmith | 基于 `create_deep_agent` |
| 认证 | JWT (HS256) + HttpOnly Cookie + CSRF double-submit | ADR-016 |
| 加密 | Cipher V2 — HKDF-SHA256 + AES-256-GCM, multi-key rotation | ADR-009 |
| DB | PostgreSQL 16 (docker-compose) | |
| 调度器 | APScheduler 3.x | |
| 包管理器 | uv (backend), pnpm (frontend) | |
| 运行时版本 | Python 3.12（uv 自动安装）、Node 22（`.node-version`） | |
| 后端开发工具 | Ruff `ruff>=0.16.5,<0.17.0` (lock: 0.16.5) | |

---

## 项目结构

```
natural-mold/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app factory + lifespan（seed、scheduler、checkpointer）
│   │   ├── config.py            # pydantic-settings（基于 .env）
│   │   ├── database.py          # async engine + session
│   │   ├── dependencies.py      # get_db, get_current_user, require_super_user, verify_csrf
│   │   ├── scheduler.py         # APScheduler singleton（MCP health polling、refresh token GC 等）
│   │   ├── models/              # SQLAlchemy ORM (user, agent, skill, mcp_server, credential, ...)
│   │   ├── schemas/             # Pydantic request/response schema
│   │   ├── routers/             # FastAPI router（agents, tools, skills, mcp, credentials, auth, ...）
│   │   ├── services/            # 业务逻辑层
│   │   ├── auth/                # ADR-016 多用户认证（JWT, refresh token rotation, CSRF）
│   │   ├── security/            # Cipher V2 (HKDF-SHA256 + AES-256-GCM, multi-key rotation)
│   │   ├── credentials/         # 凭据系统
│   │   │   ├── definitions/     # 定义 22 种 credential type（LLM、搜索、MCP、k-skill 系列等）
│   │   │   ├── service.py       # CRUD + field_keys 缓存（ADR-007）
│   │   │   ├── interpolation.py # {{$credentials.x}} 插值（resolve_deep）
│   │   │   └── external_secrets/ # Vault/ENV resolver（基于 feature flag）
│   │   ├── skills/              # Skill 系统（text + .skill package）
│   │   │   ├── service.py       # CRUD + 文件系统（data/skills/<id>/）
│   │   │   ├── packager.py      # .skill ZIP extract（防御 symlink/zip-slip/null-byte）
│   │   │   ├── inspector.py     # SKILL.md frontmatter parse
│   │   │   ├── runtime.py       # build_skills_for_agent (AgentSkillLink → descriptor)
│   │   │   └── prompt.py        # build_skills_prompt（通知 LLM 存在 skill）
│   │   ├── mcp/                 # MCP 集成
│   │   │   ├── client.py        # connect_and_list (transports: stdio/sse/streamable_http)
│   │   │   └── discovery.py     # 发现 tool + credential 插值 + last_seen_at upsert
│   │   ├── agent_runtime/       # AI 执行引擎（基于 deepagents）
│   │   │   ├── executor.py      # compatibility facade (runtime split exports)
│   │   │   ├── runtime_config.py # AgentConfig + RuntimeComponents
│   │   │   ├── runtime_component_builder.py # 组装 model/tools/skills/memory/subagents
│   │   │   ├── agent_stream_runner.py # stream/invoke 执行 + hooks/Langfuse
│   │   │   ├── skill_executor.py # execute_in_skill subprocess runner
│   │   │   ├── mcp_tool_loader.py # MCP runtime tool loading
│   │   │   ├── model_factory.py # LLM 实例 + GPT-5/Anthropic quirks（ADR-014）
│   │   │   ├── tool_factory.py  # builtin/registry/MCP 工具构建器
│   │   │   ├── middleware_registry.py # 22 个 middleware 目录（区分 auto/explicit/provider）
│   │   │   ├── streaming.py     # LangGraph → SSE（W3-out 部分 flush）
│   │   │   ├── checkpointer.py  # AsyncPostgresSaver
│   │   │   ├── credential_resolution.py # LLM credential 三阶段优先级（ADR-013）
│   │   │   ├── builder_v3/      # 对话式 Agent 创建图
│   │   │   ├── assistant/       # Assistant panel agent/tools
│   │   │   ├── mcp_client.py    # MCP wrapper（委托给 app.mcp.client）
│   │   │   ├── trigger_executor.py # 调度 trigger 执行（invoke 模式，禁用 HiTL）
│   │   │   ├── naver_tools.py   # Naver 搜索 API 工具
│   │   │   ├── google_tools.py  # Google Custom Search 工具
│   │   │   └── google_workspace_tools.py # Gmail, Calendar, Chat Webhook
│   │   └── seed/                # seed 数据（model、template、system tool、bootstrap_from_env）
│   ├── alembic/                 # DB migration（head: m77_side_chat_link）
│   ├── tests/                   # pytest (aiosqlite in-memory)
│   ├── scripts/                 # 工具脚本（migrate_mock_to_real_user, google_oauth_setup, ...）
│   ├── pyproject.toml
│   └── .env.example             # 环境变量模板
│
├── frontend/                    # Next.js 16 + React 19 (App Router)
│   ├── src/
│   │   ├── app/                 # route（/, /agents, /tools, /skills, /mcp-servers, /credentials, /usage）
│   │   ├── components/          # ui (shadcn), layout, agent, chat, tool, shared
│   │   ├── lib/                 # api, hooks (TanStack Query), stores (Jotai), sse, types
│   │   └── hooks/
│   ├── package.json
│   └── AGENTS.md                # Next.js 16 注意事项
│
├── docs/
│   ├── PRD.md                   # 产品需求定义文档
│   ├── PRD-screens.md           # 各页面 wireframe
│   ├── ARCHITECTURE.md          # 系统架构
│   ├── design-docs/             # ADR + 设计规格（ADR-001~014、ADR-016~021 等）
│   ├── tool-setup-guide.md      # 预构建工具 API key 设置指南
│   └── marketplace-resources-prd.md # Agent/MCP/Skill marketplace PRD + 实现状态
│
├── docker-compose.yml           # PostgreSQL + Backend + Frontend
├── TASKS.md                     # 任务列表
└── .node-version                # 固定 Node 22（兼容 nvm/fnm/asdf；Python 由 uv 管理）
```

---

## 本地开发环境设置

### 前置要求

- 安装 [uv](https://docs.astral.sh/uv/)（自动配置 Python 3.12 + backend 依赖）
- Node.js 22 + [pnpm](https://pnpm.io/)（frontend；`.node-version` 固定为 `22`）
- Docker Desktop（用于 PostgreSQL）

### 在 git worktree 中工作时

`backend/.env` 位于 `.gitignore` 中，因此每个 worktree 都需要单独的文件，但 ground
truth 必须始终以 main checkout 中唯一的 `backend/.env` 为准（必须使用相同的 PG DB +
相同的 `ENCRYPTION_KEYS`，现有 credential 才能正常解密；共享 `JWT_SECRET` 后
session 也会共享）。进入 worktree 后仅执行一次：

```bash
bash scripts/worktree-setup.sh
```

脚本是幂等的——检查 `backend/.env` 是否为指向 main `.env` 的 symlink，
若不存在则创建。另外，为避免 `uvicorn --reload` 在 publish/install 时因
`data/` 目录变化自动触发 reload，还会输出建议加入 `--reload-dir app` 的
提示。

#### worktree E2E seed / env 同步

即使 `backend/.env.example` 新增了变量，也不会自动同步到已经存在的 main checkout
`backend/.env`。由于 worktree 通过 symlink 共享 main `backend/.env`，
若要在新 worktree 中直接运行 Playwright E2E，应先确认 main
`backend/.env` 中存在以下值：

```dotenv
E2E_SEED_USER_ENABLED=true
E2E_USER_EMAIL=playwright-e2e@moldy.dev
E2E_USER_PASSWORD=correct horse battery staple 42
E2E_USER_NAME=E2E User
```

在 dev 环境启动 backend 时，`seed_e2e_user` 会在 DB 中将上述账户创建或更新为 super_user。
在 `APP_ENV=production` 中，即使 `E2E_SEED_USER_ENABLED=true` 也会
始终跳过。frontend E2E 优先使用 `frontend/.env.local` 中的 `E2E_USER_*` 值，
为兼容现有配置，也会 fallback 到原有的 `E2E_EMAIL` / `E2E_PASSWORD`，
并读取这些值。

#### E2E 端口/DB 隔离（throwaway stack）

如果默认端口（3000/8001/5432）已被其他项目占用，则使用 throwaway stack 隔离运行：

```bash
# 1) scripted throwaway Postgres（例如：host 5433，DB 名必须带 lane prefix）
docker run -d --name moldy-e2e-scripted-pg -p 5433:5432 \
  -e POSTGRES_DB=moldy_e2e_scripted_local -e POSTGRES_USER=moldy -e POSTGRES_PASSWORD=moldy postgres:16-alpine
until docker exec moldy-e2e-scripted-pg pg_isready -U moldy -d moldy_e2e_scripted_local; do sleep 1; done

# 2) migration——仅直接作用于 throwaway DB（禁止作用于共享/main DB）
(cd backend && \
  DATABASE_URL='postgresql+asyncpg://moldy:moldy@localhost:5433/moldy_e2e_scripted_local' \
  uv run alembic upgrade head)

# 3) 执行 E2E（playwright webServer 自行启动 backend+frontend）
(cd frontend && \
  E2E_FRONTEND_PORT=3100 E2E_BACKEND_PORT=8101 \
  DATABASE_URL='postgresql+asyncpg://moldy:moldy@localhost:5433/moldy_e2e_scripted_local' \
  DATABASE_URL_SYNC='postgresql://moldy:moldy@localhost:5433/moldy_e2e_scripted_local' \
  RATE_LIMIT_ENABLED=false E2E_TEST_HELPERS_ENABLED=true \
  pnpm exec playwright test e2e/<spec>.spec.ts)
```

注意：

- `DATABASE_URL_SYNC` 是**独立配置**，不会从 `DATABASE_URL` 派生。
  （`backend/app/config.py`）。LangGraph checkpointer 使用该值，因此**两者都**
  必须 override。只修改其中一个时，checkpointer 会继续指向原有 DB，
  导致 backend 因 PoolTimeout 启动失败。
- E2E lane 要求使用 `DATABASE_URL=postgresql+asyncpg://...`、
  `DATABASE_URL_SYNC=postgresql://...` 格式，且两者必须指向相同的 host/port/database。
  scripted 默认端口为 `3100/8101`，live 默认端口为 `3200/8201`。
  DB 名必须分别采用 `moldy_e2e_scripted`/`moldy_e2e_scripted_*`、
  `moldy_e2e_live`/`moldy_e2e_live_*` 格式。live 模式需要
  在同时设置 `E2E_LLM_BASE_URL`、`E2E_LLM_API_KEY`、`E2E_LLM_MODEL` 后
  通过 `pnpm test:e2e:live` 执行。
- checkpointer 的 psycopg `AsyncConnectionPool` 通过 `CHECKPOINTER_POOL_MIN_SIZE`
  / `CHECKPOINTER_POOL_MAX_SIZE` 调整（默认 1/10）。当慢速 streaming run 或
  evaluation run 大量并发时，整个 backend 可能被串行化，甚至使无关请求也发生 timeout。
  `--repeat-each` stress 失败可能源于这个共享 pool/DB 的负载，
  应通过与 origin/main 对照执行来区分判断。

#### E2E 截图 / 图像产物规则

当被要求使用 Codex 内置浏览器执行 E2E 时，实际 UI 操作与验证应在内置浏览器中
完成。但内置浏览器的 screenshot API 可能因 `Page.captureScreenshot`
timeout、空图像或损坏图像而失败。此时验证本身继续使用内置
浏览器进行，仅最终共享用的图像文件可在相同 local dev server 和相同
E2E 账户下使用 Playwright/Chrome 截图 fallback。若使用了 fallback，
必须在最终报告中注明。

E2E 期间生成的 screenshot、video、trace、raw capture 不得散落在 repo root，
始终集中到以下路径：

```text
output/e2e-captures/<YYYYMMDD>-<feature>/
```

`output/` 已包含在 `.gitignore` 中，因此这些产物不要 commit。不要像过去那样
把 `memory-e2e-*.png`、`*.raw` 等临时文件留在 repo root。向用户
交付图像前，必须通过 `file output/e2e-captures/.../*.png` 确认确实是 PNG
并检查分辨率，再用 `view_image` 直接打开确认文本/卡片没有被裁切或损坏。
在截图 security/secret 验证页面时，不要使用真实 secret，
应使用明确的 dummy value；如果最终图像中出现不必要的 dummy secret 字符串，
则重新截图。

继续实现 Tavily/Deep Research 时也遵循相同原则。
`TAVILY_API_KEY` 不是 per-user credential，而是 backend hosted key，应放在 main
`backend/.env` 中。详细计划以
`docs/superpowers/plans/2026-05-31-deep-research-tavily.md` 为准。

#### worktree dev server 端口/CORS 规则

在 worktree 中启动 backend/frontend dev server 时，必须将 **frontend port、
backend port、CORS origin、`NEXT_PUBLIC_API_BASE_URL` 作为一组对应配置。**
若不遵守此规则，浏览器中的 CORS、HttpOnly cookie、CSRF、
API base URL 会彼此错位，看起来像是 login/request/DB connection 出现故障。

默认建议一次只运行一个 worktree，并使用固定端口：

```bash
# backend
cd backend
uv run uvicorn app.main:app --reload --port 8001 --reload-dir app

# frontend
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 pnpm dev -- --port 3000
```

如果必须同时运行多个 worktree，应为每个 worktree 明确指定一对端口。
例如 frontend 使用 `3010`、backend 使用 `8010` 时：

```bash
# backend
cd backend
CORS_ALLOWED_ORIGINS=http://localhost:3010,http://127.0.0.1:3010 \
  uv run uvicorn app.main:app --reload --port 8010 --reload-dir app

# frontend
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8010 pnpm dev -- --port 3010
```

Agent 在 worktree 中运行或诊断 dev server 时，首先确认以下事项：

- 已执行 `bash scripts/worktree-setup.sh`，并确认 `backend/.env` 与 `backend/data`
  是指向 main checkout 的 symlink
- main `backend/.env` 中存在 E2E seed 值（`E2E_SEED_USER_ENABLED`、`E2E_USER_EMAIL`、
  `E2E_USER_PASSWORD`、`E2E_USER_NAME`）
- 如果是 Deep Research/Tavily 工作，确认 main `backend/.env` 中存在 `TAVILY_API_KEY`
- frontend 实际运行的 origin 已包含在 backend 的 `CORS_ALLOWED_ORIGINS` 中
- frontend 的 `NEXT_PUBLIC_API_BASE_URL` 指向实际 backend port
- 不要沿用 Next.js 因端口冲突自动选择的随机端口，应通过 `pnpm dev -- --port <port>` 固定端口
- 即使多个 backend 同时连接到同一 DB，也会按
  `SCHEDULER_LEADERSHIP_POLL_SECONDS` 周期重新验证 PostgreSQL advisory-lock leader。若 leader 连接中断，
  则停止原 scheduler，由其他 backend 自动接管；通过 non-leader 修改的 trigger 也
  会由 leader 按相同周期重新协调

### 1. 运行时准备

- Python 3.12 — 执行 `uv sync`（第 3 步）时自动下载，因此无需单独安装
- Node 22 — 通过系统包、nvm、fnm 等安装（`.node-version` 固定为 `22`）

### 2. 启动 DB

```bash
docker-compose up -d postgres
# PostgreSQL: localhost:5432, user=moldy, pass=moldy, db=moldy
```

### 3. Backend

```bash
cd backend
cp .env.example .env  # 设置 API key + ENCRYPTION_KEYS / JWT_SECRET
uv sync               # 安装依赖（自动创建 .venv）
uv run alembic upgrade head   # DB migration（head: m77_side_chat_link）
uv run uvicorn app.main:app --reload --port 8001
# → http://localhost:8001/docs (Swagger UI)
# 启动时自动插入 seed 数据（model、template、ENV → system credentials bootstrap）
```

### 4. Frontend

```bash
cd frontend
pnpm install
pnpm dev
# → http://localhost:3000
# Backend URL: NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 (.env.local)
```

### 5. 测试

```bash
cd backend
uv run pytest               # 全量测试（aiosqlite in-memory，无需 DB）
uv run pytest tests/test_agents.py  # 单个文件
uv run ruff check .         # lint
```

需要快速执行全量测试时，不修改默认配置，临时使用 pytest-xdist。
低配置环境/CI 建议从 `-n 4` 开始，高配置本地环境可提高到 `-n 8`。
`-n auto` 可能创建过多 worker，反而变慢。

```bash
cd backend
uv run --with pytest-xdist pytest -q -n 4
```

```bash
cd frontend
pnpm build                  # 类型检查 + build
pnpm lint                   # ESLint
pnpm lint:design-system     # Moldy UI surface/radius/shadow/token guard
```

---

## 架构模式

### Backend: Router → Service → Model

```
Router (routers/)      → HTTP endpoint、request/response 转换、权限 guard
Service (services/)    → 业务逻辑、DB query
Model (models/)        → SQLAlchemy ORM
Schema (schemas/)      → Pydantic 输入/输出 schema
```

- 所有 DB 访问均为 async（`AsyncSession`）
- 依赖注入：`Depends(get_db)`, `Depends(get_current_user)`, `Depends(require_super_user)`, `Depends(verify_csrf)`
- 认证：JWT(HS256) + HttpOnly Cookie（`moldy_at`, `moldy_rt`, `moldy_csrf`）。也支持 `Authorization: Bearer` header
- 权限模型：`is_super_user` boolean（RBAC 扩展留待后续）。系统资源（`is_system=True`, `user_id IS NULL`）仅允许 super_user 管理

### Backend: AI Runtime (agent_runtime/)

```
executor.py                → compatibility facade（重新导出拆分后的模块）
runtime_config.py          → AgentConfig + RuntimeComponents
runtime_component_builder  → model/tools/skills/memory/subagents + 准备 create_deep_agent
agent_stream_runner        → 执行 stream/invoke、hooks、Langfuse context
skill_executor             → execute_in_skill subprocess runner
mcp_tool_loader            → MCP runtime tool loading
model_factory              → 按 provider 创建 LLM 实例（OpenAI/Anthropic/Google/OpenRouter/openai_compatible）
tool_factory               → builtin/registry 工具构建器 + shared HTTP client
middleware_registry        → 22 个 middleware（deepagents auto-injected vs 显式实例）
streaming                  → LangGraph event → SSE + trace/artifact/usage capture
checkpointer               → AsyncPostgresSaver（按 thread_id 持久化状态）
credential_resolution      → LLM credential 优先级（直接 binding > model 默认 > provider 单一匹配）
trigger_executor           → 调度 trigger（invoke 模式，禁用 ask_user/HiTL）
```

- 工具类型：`builtin:*`（web_search, web_scraper, current_datetime）、`registry`（基于 Tool model 的 definition_key）、`mcp`（AgentMcpToolLink）
- Skill 系统：仅将选中的 skill 暴露到 `/runtime/<thread_id>/.../skills/` 虚拟路径。LLM 会先通过 `read_file` 读取 `SKILL.md` 并遵循其中指示。
- Skill subprocess 执行：**`execute_in_skill` 工具**位于 `skill_executor.py`，采用 Python script allowlist、timeout、output dir、credential env injection、redaction 约定。
- Generated file 规则：引导 user-visible 文件写入 `/conversations/<thread_id>/...` 下，并通过 `conversation_artifacts` 建立索引。

### Frontend: API Client → TanStack Query → Component

```
lib/api/        → fetch wrapper（按 domain 分文件）
lib/hooks/      → 对 useMutation、useQuery 的封装
lib/stores/     → Jotai atoms（chat message、sidebar 状态等）
lib/sse/        → 基于 EventSource 的 SSE streaming
lib/types/      → 与 Backend schema 1:1 对应的 TS type
```

- Server state（API 数据）→ TanStack Query
- Client state（UI 本地状态）→ Jotai
- SSE streaming：实时接收 chat response

### Next.js 16 注意事项

> **本项目使用 Next.js 16。** API/约定可能与旧版 Next.js 不同。
> 编写代码前必须查看 `frontend/node_modules/next/dist/docs/` 中的指南。

---

## DB schema（核心表）

| 表 | 说明 |
|--------|------|
| `users` | 用户（hashed_password, is_active, is_super_user, login tracking, lockout） |
| `refresh_tokens` | JWT refresh token whitelist (rotation + replay detection) |
| `agents` | AI Agent（system_prompt, model_id, llm_credential_id, model_fallback_list） |
| `agent_tools` | Agent-工具关联 |
| `agent_skills` | Agent-skill 关联 + `config`（credential binding override） |
| `agent_mcp_tools` | Agent-MCP 工具关联 |
| `agent_subagents` | parent agent → child agent delegation |
| `agent_triggers`, `agent_trigger_runs` | 调度 trigger 与执行历史 |
| `models` | LLM model 定义（provider, model_id, default_credential_id） |
| `tools` | 工具（definition_key, parameters, credential_id, `is_system`） |
| `skills` | Skill (kind=text|package, storage_path, content_hash, version, package_metadata) |
| `mcp_servers` | MCP server（transport, url/command, env_vars, headers, credential_id, `is_system`, health_status） |
| `mcp_tools` | 从 MCP server 发现的工具（input_schema, enabled, last_seen_at） |
| `credentials` | 凭据（definition_key, data_encrypted, key_id, field_keys, `is_system`） |
| `conversations` | 对话 session + active branch checkpoint |
| `message_events`, `message_event_chunks` | SSE event stream、streaming resume、trace correlation |
| `message_attachments`, `message_feedback` | 附件/反馈 |
| `conversation_artifacts`, `artifact_versions` | 生成文件 artifact 与版本 |
| `share_links` | 对话共享链接（M30/M31） |
| `token_usages` | token 用量追踪 |
| `templates` | Agent 模板 |
| `builder_sessions` | 对话式 Agent 创建 session（原 agent_creation_sessions） |
| `marketplace_*` | marketplace item/version/ACL/installation/publication/binding |
| `memory_*` | user/agent memory settings, records, proposals |
| `agent_deployments`, `agent_api_*` | 外部 Agent API deployment/key/thread/run |
| `audit_events`, `daily_spend_*`, `health_check_history` | 审计、费用汇总、health history |
| `system_llm_settings` | 按 Builder/Assistant/Image role 设置 system model |

migration：`backend/alembic/versions/`（Alembic）。最新 head 为 `m77_side_chat_link`。

带有 `is_system` flag 的表共有约束：`CHECK ((is_system = false) OR (user_id IS NULL))`。系统资源的 user_id 必须为 NULL。

---

## 环境变量

参见 `backend/.env.example`。实现最小运行所需的 key：

| 变量 | 必需 | 说明 |
|------|------|------|
| `DATABASE_URL` | O | PostgreSQL async URL |
| `ENCRYPTION_KEYS` | O | Cipher V2 master key（HKDF info=`moldy-encryption-v1`）。以逗号分隔的 64-char hex，第一个为 active key。支持多 key rotation |
| `JWT_SECRET` | O | JWT HS256 signing key（ADR-016） |
| LLM key（`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` 等） | X（可选） | 建议在 UI Credentials 中注册（ADR-013）。若 ENV 中存在，则 dev 环境 bootstrap 为 system credential，production 跳过 |
| `E2E_SEED_USER_ENABLED`, `E2E_USER_EMAIL`, `E2E_USER_PASSWORD`, `E2E_USER_NAME` | X | 本地 Playwright E2E 使用的 dummy super_user seed。在 `APP_ENV=production` 中始终跳过 |
| `TAVILY_API_KEY` | X | Tavily hosted search / Deep Research 计划使用的 backend key。不要作为 per-user credential 配置 |
| 其余（Naver、Google 等） | X | 仅在使用相应工具时需要 |

从 ENV 自动生成的 `is_system=True` credentials 在 production 环境中跳过自动创建，由 super_user 直接管理。

---

## 凭据系统（ADR-007/009/013）

- **Cipher V2**（`app/security/cipher.py`）：HKDF-SHA256 → AES-256-GCM。Blob 结构 `[ver 1B | salt 32B | tag 16B | ciphertext]`，Base64 编码
- **Multi-key rotation**：通过 `credentials.key_id` 识别 active key，解密时尝试所有 candidate key。APScheduler 每周执行一次 `rotate_credentials_to_active_key`
- **field_keys 缓存**（ADR-007）：避免 list API 中的 N+1 解密。仅将 key 名存入 JSON column
- **definition_key 注册**：在 `app/credentials/definitions/__init__.py` 中注册 22 种（LLM、Google/Naver、HTTP、MCP secret/OAuth2、SRT/KTX/Forest Trip/KIPRIS/DART/ODsay/Coupang/K-Skill Proxy 等）
- **LLM credential 优先级**（ADR-013）：ENV fallback → system credentials → user credentials
- **外部 secret resolver**（`external_secrets/`）：通过 `__external__:<provider>:<ref>` marker 动态解析 Vault/ENV（feature flag）
- **系统 credential 分离**（M36, M39）：`is_system=True && user_id IS NULL`。普通用户无法通过 `/api/credentials` 查看，使用仅限 super_user 的 system credential 页面/API 管理

---

## 内置工具系统

系统工具（`is_system=True`）在 server 启动时自动 seed。

| 工具 | 类型 | 所需 key |
|------|------|---------|
| Web Search (DuckDuckGo) | builtin:web_search | 无 |
| Web Scraper | builtin:web_scraper | 无 |
| Current DateTime | builtin:current_datetime | 无（Seoul TZ） |
| Naver 搜索（5 种） | registry | naver_search credential |
| Google 搜索（3 种） | registry | google_search credential |
| Google Chat Webhook | registry | URL credential |
| Gmail（2 种） | registry | google_workspace_oauth2 |
| Calendar（3 种） | registry | google_workspace_oauth2 |

未设置 server key 的工具可为每个 Agent 单独提供 credential。工具目录（`ToolDefinition`）由运营者通过代码在**基于内存的 registry**（`app/tools/registry.py`）中定义。

---

## 开发约定

### Git

- commit message：`<type>(<scope>): <subject>`（英文、祈使式）
- branch：`feature/{task-name}`, `fix/{issue}`, `refactor/{target}`
- 禁止直接 commit 到 main；在 feature branch 工作后 merge
- 创建 PR 时，如果 GitHub connector 返回 `Resource not accessible by integration` / 403，
  不要重复调用相同 connector。本 repo 中 connector GitHub
  App 可能权限不足，而 `git push` 与 `gh pr create` 可使用用户的 `gh`
  认证权限正常工作。此时使用 `gh pr create --draft --base main
  --head <branch>` fallback，并在最终报告中注明使用了 fallback

### Backend

- 必须提供 type hint（函数 signature、return type）
- async/await pattern、`select()` 语句
- linter：Ruff `ruff>=0.16.5,<0.17.0`（lock: 0.16.5, line-length=100, target=py312）
- 测试：pytest + aiosqlite in-memory（无需 PostgreSQL）
- 新增 table 时必须提供 Alembic migration
- Ownership 验证：防止 enumeration oracle——对外统一“无此资源”（404）与“无权限”（403）的响应

### Frontend

- TypeScript strict mode
- 优先使用 React 19 Server Components，尽量减少 `'use client'`
- UI：优先使用 shadcn/ui component
- 所有用户可见的静态文本都必须通过 `next-intl` message（`frontend/messages/*.json`）渲染，不得直接 hardcode 在 TS/TSX 中
- Moldy 的默认产品语言为简体中文，因此新 copy 应先自然地添加到现有 `frontend/messages/zh-CN.json`，并必须同步将相同 key path 添加到 `frontend/messages/en.json` 的恰当英文版本
- 添加/修改 UI copy 后运行 `cd frontend && pnpm lint:i18n`。如需连英文/ASCII 静态文本也一并检查，可使用 `pnpm lint:i18n:strict`；但现有 Agent Prism/代码片段仍有误报，因此失败时应将真正的用户可见文案迁移到 i18n，并将 guard 调整得更窄
- 禁止 any → 使用 unknown + type guard
- 尽量避免 barrel export（index.ts）
- Moldy 设计系统 guard：新增 UI 工作后运行 `cd frontend && pnpm lint:design-system`
- 产品页面中禁止直接使用 `rounded-xl/2xl/3xl`、`shadow-sm/md/lg/xl/2xl`、`shadow-[...]`、raw hex utility（`bg-[#...]` 等）、`text-[...]`、`outline-none`、`transition-all`。迁移到 `moldy-card`、`moldy-panel`、`moldy-popover`、`moldy-skeleton-card`、`moldy-status-*`、`moldy-muted-panel` 等公共 class/token
- 任意 `style={...}` 仅在 dynamic layout/library API 时允许，并应在 `frontend/scripts/check-design-system.mjs` allowlist 中同时记录理由与狭窄的 context regex
- 当前允许的 inline style 例外仅包括 tree depth indentation、syntax highlighter theme、usage bar width、resource grid columns、Agent Prism trace/timeline layout、phase progress ratio

---

## ADR 索引

| ID | 标题 | 核心 |
|----|------|------|
| ADR-001 | Deep Agent Engine | 统一使用 `create_deep_agent`，MCP 使用 `MultiServerMCPClient` |
| ADR-002 | Checkpointer | LangGraph `AsyncPostgresSaver` |
| ADR-003 | Skills Memory | skill 系统 + memory 设计 |
| ADR-004 | M4 Cleanup | 整理 migration |
| ADR-005 | Builder Assistant | 用于对话式创建 Agent 的 meta Agent |
| ADR-006 | Assistant UI Runtime | UI 执行策略 |
| ADR-007 | Credentials field_keys Cache | 避免 list API N+1 解密 |
| ADR-008 | Connection Entity | MCP/credential 关联模型 |
| ADR-009 | Greenfield Credentials | Cipher V2, multi-key rotation |
| ADR-010 | UI Tokens / Dialog Shell | 设计 token |
| ADR-011 | SSE Stream Resume | 恢复 streaming |
| ADR-012 | HiTL Middleware Migration | 避免 deepagents 自动注入，新增显式实例 |
| ADR-013 | Service LLM Key from Credentials | ENV > system > user 优先级 |
| ADR-014 | Chat Model Factory Strategy | 分离 GPT-5 / Anthropic quirk |
| ADR-016 | Multi-user Auth | JWT + HttpOnly + refresh rotation + super_user |
| ADR-017 | Marketplace Resources | Skill/MCP/Agent 共享层，Phase 1 Skill |
| ADR-018 | Relative Storage Path | 稳定 worktree 之间的 data 路径 |
| ADR-019 | System LLM Settings | 按 role 选择 model + 注入 base_url |
| ADR-020 | Chat Run AG-UI Adapter | LangGraph v3 run/stream protocol adapter |
| ADR-021 | Value-Based Trace Redaction | 基于值的 trace secret masking |
| ADR-022 | Runtime Policy Lifecycle | versioned agent policy, immutable conversation snapshot, run provenance |

各 ADR 正文位于 `docs/design-docs/`。

---

## 当前状态摘要

- **Backend**：Alembic source head 为 `m77_side_chat_link`（各环境需要 migration）。已包含多用户认证、marketplace skill publish/install、System LLM settings、schedule productization、Agent API、memory controls、audit events、generated artifacts、credential OAuth states、conversation runs、agent blueprints、chat navigation indexes、subagent runtime、executor split、skill usage and feedback、conversation runtime policy snapshot。
- **Frontend**：多用户 login/signup UI、MCP server 管理、Skill/Credential/Marketplace 管理、chat SSE streaming、artifact preview/right rail/library、memory/settings、Agent API settings、trigger scheduling、Builder wizard。
- **已实现**：MCP/Agent marketplace 发布·安装及公共 wizard、assistant-ui 0.15.18、输入 queue·执行指标·MCP Apps·固定摘要（M73~M76）、Pyright basic-mode 错误 0 和阻断 CI。尚未实现直接注入当前 run 的 Steer。
- **下一步**：E2E 覆盖范围·执行结果在 `docs/e2e-coverage.md` 中管理。外部 OAuth 与
  复杂 marketplace 安装组合、无障碍·键盘·性能验证留待后续。
- 详细 task 状态参见 `TASKS.md`
- 功能规格参见 `docs/PRD.md` + `docs/PRD-screens.md`
