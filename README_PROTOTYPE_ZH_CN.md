<!-- project-current-source: migration=m85_project_simulation; deepagents=0.7.11; ruff=0.16.5; refreshed=2026-10-06 -->

> 这是原型项目技术说明的中文译本，保留原有日期、来源和历史设计。当前产品目标、三模型分工与验收状态请阅读 [README.md](README.md)。

<div align="center">

<img src="docs/images/moldy-mascot.webp" alt="Moldy 吉祥物" width="160">

# Moldy

**通过对话构建的 AI Agent Builder — FastAPI + LangGraph + deepagents**

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)]()
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)]()
[![React](https://img.shields.io/badge/React-19-61dafb.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)]()
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0+-purple.svg)]()
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

简体中文 · [当前项目说明](README.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

[Overview](#-overview) · [快速回答](#-快速回答) · [Quick Start](#-quick-start) · [可信依据](#-质量安全文档化信号) · [功能](#-主要功能) · [架构](#-架构)

<!-- project-prototype-source: migration=m76_pinned_conv_summaries; deepagents=0.7.11; ruff=0.16.5; refreshed=2026-09-08 -->

**最后更新：** 2026年9月5日 · **Repository:** [YooSuhwa/natural-mold](https://github.com/YooSuhwa/natural-mold) · **License:** [MIT](LICENSE)

</div>

---

## 🧐 Overview

**Moldy** 是一款只需用自然语言描述想要完成的工作，AI 就会自动配置 Agent 的
无代码 AI Agent Builder。无需编写一行代码，只通过*对话*即可组合工具、Skill、Trigger，
创建自动化工作流，并直接与创建好的 Agent 对话，或按预定日程
自动执行。

### 什么是 Moldy？

Moldy 是一款可在 Web UI 中创建、配置、对话和调度 AI Agent 的
开源 self-hostable AI Agent Builder。本项目结合了 Next.js 16 + React
19 前端、FastAPI 后端、PostgreSQL 16、LangGraph 1.x，以及 `deepagents` 的
`create_deep_agent` runtime。Moldy 面向多用户运行场景设计，
并依据 ADR-016 应用了 JWT 认证、HttpOnly cookie、CSRF double-submit 防护、
refresh token rotation，以及用于系统资源管理的 `super_user` 角色。
这个 monorepo 包含聊天流式输出、消息分支、credential 管理、MCP Server 集成、
Skill 包、Marketplace 安装、Schedule Trigger、使用量追踪等能力。

### 项目事实

| 项目 | 当前 README 基准 |
|---|---|
| 项目类型 | 开源 Web 应用及 monorepo |
| 主要使用场景 | 无代码 AI Agent 创建、聊天、调度、工具/Skill 编排 |
| Backend | FastAPI 0.115+, SQLAlchemy 2.0 async, Alembic, Python 3.12 |
| Frontend | Next.js 16, React 19, TailwindCSS v4, shadcn/ui |
| AI runtime | LangGraph 1.x + 基于 `create_deep_agent` 的 `deepagents` 0.7.11 |
| Runtime policy | Agent policy 的修改会应用于新对话，既有对话继续保留首次确定的有效 policy snapshot |
| Database | PostgreSQL 16，Alembic head 为 `m76_pinned_conv_summaries` |
| 认证 | JWT HS256、HttpOnly cookie、CSRF double-submit、refresh token rotation、`super_user` |
| License | MIT |

### 有什么不同

- **对话式 Builder** — Meta Agent 会理解用户意图，并分阶段
  并在双方达成一致后实际创建 Agent。无需填写表单，只需**描述需求
  **即可。
- **工具·Skill·MCP 统一目录** — 可在同一界面管理内置搜索/抓取器/日历/Gmail 等
  prebuilt 工具、基于 registry 的 **MCP Server**（stdio/SSE/Streamable HTTP），以及
  用户自定义 **Skill**（SKILL.md + 辅助文件）。
- **可分支对话** — 基于 LangGraph checkpointer 的 **fork & 时间旅行**，
  编辑消息或重新生成时会拆分为新分支，并可通过左右箭头比较同级响应
  。
- **HITL(Human-in-the-Loop)** — 工具调用审批、请求用户输入、澄清问题等
  interrupt pattern 通过**倒计时 + 自动延长**的 UX 处理。
- **无代码 Trigger** — 使用基于 cron · interval 的 Schedule Trigger，让 Agent 在指定
  时间自动执行，并将结果通过通知发送。
- **公开分享链接** — 一键将对话分享为 read-only 链接，任何人都可以
  无需登录追踪 Agent 的思考过程。

## ❓ 快速回答

### Moldy 能做什么？

Moldy 会把自然语言需求转化为可执行的 AI Agent。用户可以描述想要的
工作流，审阅对话式 Builder 提议的 Agent 设置，然后连接工具、
Skill、MCP 工具和 credential。之后可以在聊天中运行 Agent，或
通过 cron/interval Trigger 预约执行，同时支持可分支对话、SSE 流式输出、工具
调用审批流程、公开 read-only 分享链接，以及按用户隔离 credential。

### Moldy 面向哪些用户？

Moldy 面向不想只依赖完全 managed SaaS，而希望使用本地或 self-hosted Agent Builder 的
开发者、运营人员和内部工具团队。README 默认读者可以运行 PostgreSQL、Python
3.12、Node 22、`uv`、`pnpm`，但
产品 UI 的设计也允许不会编程的用户通过 guided setup、credential、工具、Skill、Schedule
来组装 Agent。

### Moldy 如何处理 credential 与系统权限？

Moldy 会把运营方管理的系统资源与用户级资源分开。System
credentials 与 System LLM settings 由 `super_user` 账户管理，普通用户则
在 `/credentials` 中登记个人 credential。Credential payload 使用
Cipher V2 加密，采用 HKDF-SHA256 和 AES-256-GCM；runtime 访问通过显式绑定的
通过工具、模型、MCP 和 skill binding（技能绑定）实现。

### README 中的声明可以在哪里验证？

Moldy 的架构与安全说明可以通过 repository 内部文档进行验证。
架构决策记录在 [`docs/design-docs/`](docs/design-docs/) 中，上层系统结构记录在
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 中，安全漏洞报告及部署 hardening 记录在
[`SECURITY.md`](SECURITY.md) 中。README 中的验证命令和
pre-push hook 提供了可重复执行 backend/frontend test suite 的路径。

## 🚀 Quick Start

### 前置要求

- [uv](https://docs.astral.sh/uv/) — Python 包管理器（backend 依赖·迁移 + 自动安装 Python 3.12）
- [Node.js 22](https://nodejs.org/) + [pnpm](https://pnpm.io/) — 前端 runtime + 包管理器
- [Docker](https://www.docker.com/) — 用于 PostgreSQL 16 容器
- LLM API Key — OpenAI / Anthropic / OpenRouter / OpenAI-compatible（LiteLLM 等）任选其一。无需写入 ENV，**启动后在 UI 中登记**（ADR-013）

### 本地开发

```bash
# 1. 启动 PostgreSQL
docker compose up postgres -d         # localhost:5432, moldy:moldy/moldy

# 2. Backend（uv 会自动下载 Python 3.12）
cd backend
cp .env.example .env                  # 填写 ENCRYPTION_KEYS / JWT_SECRET 等（LLM Key 在 UI 中登记）
uv sync                               # 安装依赖（+ 若无 Python 3.12 则自动下载）
uv run alembic upgrade head           # DB 迁移（head: m76_pinned_conv_summaries）
uv run uvicorn app.main:app --reload --reload-dir app --port 8001
# → http://localhost:8001/docs (Swagger UI)

# 3. Frontend（新终端，Node 22）
cd frontend
cp .env.example .env.local            # NEXT_PUBLIC_API_BASE_URL / E2E 账户默认值
pnpm install
pnpm dev
# → http://localhost:3000
```

服务器启动时会自动 seed 默认模型（GPT-5.5、Claude Sonnet 4.6、Gemini 等）、系统工具、
Agent Template、Local Playwright E2E 账户。不过，
**如果要创建和使用 Agent，必须完成下面的运营方初始设置**。

### 服务器启动后的初始设置（运营方）

LLM Key 不通过 ENV，而是在 UI 中登记；system 功能（Builder·Assistant·Image）
只有运营方手动选择要使用的模型后才会工作（ADR-013/016/019）。

1. **第一个账户 = 运营方** — 在 http://localhost:3000 注册。第一个用户会
   自动提升为 `super_user`（ADR-016，`ALLOW_FIRST_USER_AS_ADMIN=true`；
   生产环境请在创建账户后关闭）。
2. **登记 LLM credential** — 在 `/settings/system-credentials` 中登记 OpenAI ·
   Anthropic · OpenRouter · OpenAI-compatible（LiteLLM 等）Key。
3. **选择 System LLM 模型（ADR-019，必需）** — 在 `/settings/system-llm` 中
   为 `text_primary` · `text_fallback` · `image` 三个 slot 选择模型。
   选择 credential → “加载模型列表” → 选择模型。**在完成这一设置前，Builder ·
   Assistant · Image 生成不会工作**（不会静默失败，而是明确报错）。
4. **连接 Agent 使用的模型** — 在 `/models` 中给普通 Agent 要使用的模型连接 credential，
   或通过 discovery 自动登记。

之后即可通过对话式 Builder（`/agents`）创建 Agent 并聊天。普通
用户可在 `/credentials` 中登记并使用自己的 Key。

### Worktree 开发端口/CORS 规则

在 git worktree 中工作时，先运行 `bash scripts/worktree-setup.sh`，
确保 `backend/.env` 和 `backend/data` 是指向 main checkout 的 symlink。
必须共享同一个 PostgreSQL、`ENCRYPTION_KEYS`、`JWT_SECRET`，才能避免既有 credential 解密和
登录 session 失效。

backend/frontend dev server 必须将 **frontend port、backend port、CORS origin、
`NEXT_PUBLIC_API_BASE_URL` 作为一组**统一配置。默认推荐组合：

```bash
# backend
cd backend
uv run uvicorn app.main:app --reload --reload-dir app --port 8001

# frontend
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 pnpm dev -- --port 3000
```

同时启动多个 worktree 时，请明确指定端口对：

```bash
# backend (:8010)
cd backend
CORS_ALLOWED_ORIGINS=http://localhost:3010,http://127.0.0.1:3010 \
  uv run uvicorn app.main:app --reload --reload-dir app --port 8010

# frontend (:3010)
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8010 pnpm dev -- --port 3010
```

如果让 Next.js 在端口冲突时自行选择任意端口，CORS/cookie/CSRF 可能会
错位，因此请始终用 `pnpm dev -- --port <port>` 固定端口。若让多个 backend 连接同一个 DB，
APScheduler/trigger 任务可能会重复执行，因此长时间并行运行时
需要注意。

### Docker Compose 完整运行

Compose 会从 `backend/.env` 读取 secret，并在 backend container 启动前
执行 `alembic upgrade head` 完成迁移，同时将 `data/` 保存在 named volume 中。

```bash
cp backend/.env.example backend/.env  # 填写 ENCRYPTION_KEYS / JWT_SECRET
docker compose up -d                  # postgres + backend（迁移 → 启动） + frontend
# 随后请按照上面的“服务器启动后的初始设置”完成运营方 onboarding。
```

要部署到远程 host（非 localhost）吗？`NEXT_PUBLIC_API_BASE_URL` 会在 build 时
内联进 frontend bundle，因此需要在 build 前配置，并在 CORS 中允许新的 origin：

```bash
NEXT_PUBLIC_API_BASE_URL=https://api.example.com \
CORS_ALLOWED_ORIGINS=https://app.example.com \
  docker compose up -d --build
```

### 验证命令

```bash
# Backend
cd backend
uv run ruff check .                   # lint（Ruff 0.16.5）
uv run pytest                         # 单元测试（aiosqlite，无需 Postgres）
uv run pytest -m integration          # 集成测试（需要 Postgres）
cd ..
manifest=".omo/evidence/project-restart-consolidated-roadmap/local-postgres-$(date +%s).json"
bash scripts/run-isolated-postgres-tests.sh all --manifest "$manifest"
(cd backend && uv run python ../scripts/check-isolation-cleanup.py "../$manifest")
(cd backend && uv run python ../scripts/check-isolation-cleanup.py \
  --discover ../.omo/evidence/project-restart-consolidated-roadmap) # 全量测试残留资源

# Frontend
cd frontend
pnpm lint                             # ESLint
pnpm exec tsc --noEmit                # 类型检查
pnpm test --run                       # vitest (jsdom)
pnpm build                            # production build
pnpm test:e2e                         # Playwright E2E
```

## ✅ 质量·安全·文档化信号

Moldy 会把技术决策与运行风险记录在 repository 内。因此 README 中的
说明可以通过真实文档和验证命令确认，而不只是宣传文案。最强的
可信信号包括 ADR 记录、明确的安全策略、可复现的测试命令、本地运营方初始
设置流程。从 E-E-A-T 角度看，这份 README 通过 setup 细节体现实现经验，
通过架构与 ADR 链接体现专业性，通过 repository-local evidence 体现权威性，并通过安全与验证
workflow 体现可信度。

| 信号 | 依据 | 含义 |
|---|---|---|
| 架构决策 | [`docs/design-docs/`](docs/design-docs/) 包含多用户认证 ADR-016、System LLM settings ADR-019 等 | 可以追踪 runtime、认证、credential、UI 决策的原因与时间点 |
| 系统架构 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 说明了 Next.js frontend、FastAPI backend、PostgreSQL 数据层、LangGraph/deepagents runtime | 提供比 README 更详细的设计基准 |
| 安全流程 | [`SECURITY.md`](SECURITY.md) 记录了私下漏洞报告、响应目标、部署方 hardening 检查 | 明确安全报告流程与运行责任 |
| 验证 workflow | 本 README 列出了 backend lint/test、frontend lint/typecheck/test/build、integration test、Playwright E2E 命令 | 维护者和采用方可以复现相同的验证路径 |
| 运行设置 | Quick Start 将本地开发、worktree CORS 规则、Docker Compose、E2E seed auth、System LLM 设置、MCP registry 设置分开说明 | 降低 self-hosted 或 multi-worktree 开发中的歧义 |

### Playwright E2E 认证

E2E 不会在每次测试时都走登录表单，而是在 Playwright global setup 中先通过 API
创建一次登录 session，再将 `storageState` 注入到所有 browser context。
`backend/.env.example` 在本地开发中默认启用 `E2E_SEED_USER_ENABLED=true`，
backend 启动时会在 DB 中创建或更新下面这个 dummy super_user。
在 `APP_ENV=production` 下，这个 seed 会自动跳过。

```bash
E2E_USER_EMAIL=playwright-e2e@moldy.dev
E2E_USER_PASSWORD=correct horse battery staple 42
E2E_USER_NAME=E2E User
```

frontend 环境文件也使用同一组专用测试账户值：

```bash
cd frontend
cp .env.example .env.local
# 如有需要，修改 E2E_USER_EMAIL / E2E_USER_PASSWORD
pnpm test:e2e
```

推荐流程是 `login → register fallback → login → 保存 e2e/.auth/user.json`。
`frontend/e2e/.auth/` 属于生成产物，因此不要 commit。通过 API 直接
创建/修改的 E2E setup 代码必须把登录响应中的 `csrf_token`
放入 `X-CSRF-Token` header。

> **Pre-push hook**：执行 `git push` 时，`.husky/pre-push` 会自动运行 backend pytest +
> frontend vitest，防止 regression 被 push。可通过
> `git push --no-verify` 绕过（仅限 WIP branch）。

### Tavily + Deep Research

Tavily hosted search tool（`tavily_search`）已经与 Deep Research Marketplace Skill
联动。在 backend `.env` 中设置 `TAVILY_API_KEY` 后，Deep Research Skill 会
自动将 `tavily_search` **注入为 runtime tool dependency**，用户无需额外挂载工具，
也能执行基于 citation 的多步 Web Research。（设计背景：
`docs/superpowers/plans/2026-05-31-deep-research-tavily.md`)

### MCP registry 与 MCP Secret

在 `/mcp-servers` → **新建 MCP Server** 中选择 registry preset 后，transport、URL、
stdio command/env template 会自动填充，并且可以在保存前通过**工具 probe**确认实际暴露的
工具。当前 preset 包含 GitHub、Linear、Atlassian Jira、Slack、
Notion，以及本地 first-party MCP（Hancom Groupware、Hancom Mile Meeting、Hancom Org
Chart、Maepsi）。

需要认证的 first-party MCP preset，需要先在 `/credentials` 中创建 `MCP Secret` 类型的
credential，再在 wizard 的**认证** tab 中连接。Moldy 在连接/运行时会
自动把 `secret` 值放入 `X-Moldy-Credential` header 传递。注册手动 MCP Server 时，
也可以在 header 或 stdio 环境变量值中使用 `{{ $credentials.<field> }}` 形式插入已连接的
credential field。

本地 first-party MCP preset 的默认 URL 位于 `localhost:18001`~`18004` 范围。
这些 Server 不包含在 `docker compose up` 中，因此如要使用相应 preset，需要先单独启动 MCP Server
进程，再执行 probe。

## 📸 Screenshots

> 准备中。主要页面已在 `docs/PRD-screens.md` 中整理为 wireframe。

## ✨ 主要功能

<details>
<summary><b>🤖 Agent 系统</b></summary>

- **deepagents 引擎** — 在 `create_deep_agent` + LangGraph 编译后的 graph 之上
  管理消息树、分支、checkpoint
- **对话式 Builder** — Meta Agent 通过采访自然语言需求来
  提出 build 选项（`agent_runtime/creation_agent.py`）
- **Agent Template** — 通过预定义 Agent 立即开始
- **Sub-agents** — 多阶段委托（Agent 将其他 Agent 当作工具调用）
- **Middleware 系统** — 22 类 middleware 目录（context engineering、planning、
  safety, reliability, provider-specific)
- **模型 fallback chain** — primary 模型失败时自动调用替代模型（最多 5 层）

</details>

<details>
<summary><b>💬 聊天 + 分支</b></summary>

- **SSE 流式输出** — token 级实时输出、工具调用可视化。流式输出过程中
  通过 code block plain render + SSE queue O(1) 处理等方式优化长响应性能
- **IME-safe 输入框** — 在输入韩文等组合式文字时，Enter/编辑/重新生成不会破坏正在组合的
  字符串，安全同步 composer state
- **LangGraph fork** — 编辑用户消息 / 重新生成 Assistant 响应时创建新分支，
  基于 checkpoint ID 进行时间旅行
- **BranchPicker** — 使用 `<N/M>` 左右箭头比较同级响应（集成 assistant-ui）
- **HITL countdown** — 对工具审批 / 用户输入 / 澄清问题 interrupt 提供倒计时
  timer + 到期自动延长 + 紧急状态样式
- **消息 action** — 复制·编辑·重新生成·thumb feedback·删除·搜索
- **Mermaid / KaTeX / code block** — Markdown 渲染、图片 lightbox
- **附件** — 上传图片/文档后在消息中 inline 显示
- **公开分享链接** — read-only 页面（`/shared/{token}`），通过 soft delete 可立即
  失效

</details>

<details>
<summary><b>🛠️ 工具 · Skill · MCP</b></summary>

- **内置工具目录** — DuckDuckGo / Web scraper / 当前时间 / 相对日期
  解析（`resolve_relative_date`） / Tavily Search / Naver Search 5 类 / Google CSE 3 类 /
  Gmail 发送 / Google Calendar / Google Chat Webhook / HTTP 请求
- **MCP 集成** — 注册 stdio + SSE + Streamable HTTP Server，
  基于 `langchain-mcp-adapters` 的 import/export、health check polling
- **MCP registry preset** — GitHub / Linear / Jira / Slack / Notion /
  Hancom / Maepsi Server 可在 `/mcp-servers` wizard 中选择，并在保存前进行工具 probe
- **MCP Secret credential** — 将 first-party MCP Server 的 per-user secret
  自动通过 `X-Moldy-Credential` header 传递
- **Skill 系统** — 将 SKILL.md（YAML frontmatter）+ 辅助文件打包为 Skill package，
  multi-file inline editor，支持 scratch/upload/import 3 种创建方式
- **Skill runtime dependency** — Agent 运行时自动注入 Skill 声明的 tool dependency
  （例如 Deep Research → Tavily）。用户无需手动挂载工具
- **用户自定义工具** — 使用 Pydantic schema 定义工具参数

</details>

<details>
<summary><b>🔐 Credential · 模型管理</b></summary>

- **Cipher V2 加密** — HKDF-SHA256 + AES-256-GCM，单 blob Base64
- **Vault 集成** — 支持基于 `hvac` 的 external secrets
- **System / User credential 分离** — 运营方管理 vs 用户个人 Key
- **MCP Secret** — 本地 first-party MCP Server 使用的 per-user secret credential
- **韩国服务 8 类** — SRT · KTX · 韩国林业厅森林步道 · KIPRIS · DART · ODsay · Coupang Partners · K-Skill Proxy
- **模型 discovery** — 使用 credential 直接查询 LLM API，自动获取可用模型 + 价格
  + context window
- **模型 health check** — 通过周期性 probe 监控模型可用性
- **Benchmark ranking** — 显示 LMArena · LiveBench · AAIndex 分数

</details>

<details>
<summary><b>⏰ Trigger · 使用量 · 可观测性</b></summary>

- **Schedule Trigger** — 基于 APScheduler 的 cron / interval，可按 Agent 指定输入消息，
  并通过 Google Chat Webhook 通知
- **Schedule guardrail** — 最大执行次数（`max_runs`）、结束时间（`end_at`）、
  连续失败时自动暂停（`auto_pause_after_failures`）
- **对话 policy** — 可选择每次 Trigger 创建新对话 / 复用指定对话
- **执行历史** — 在 `agent_trigger_runs` 中记录每次执行的 source / 输出预览 /
  耗时 / thread·checkpoint·trace ID
- **Token 使用量追踪** — 按 Agent / 模型 / 日期统计 token + 预估成本
- **Daily spend** — 按用户 / Agent / 模型进行每日汇总
- **Tracing** — 自动发送到 LangSmith + 对接 Langfuse external trace
  （在 `message_events` 中记录 external trace provider/id/url）

</details>

<details>
<summary><b>🎨 Frontend</b></summary>

- **Next.js 16 + React 19** — 优先使用 App Router、Server Components
- **TailwindCSS v4 + shadcn/ui** — 基于 design token（`--primary-strong` emerald），
  ADR-010 Design System
- **DialogShell pattern** — 所有 dialog 统一为 token size（`md`/`lg`/`xl`/`console`），
  并为 lightbox 提供 `srOnly` header prop
- **TanStack Query** — Server state 管理（cache + invalidation）
- **Jotai** — Client state（sidebar、右侧 panel 等）
- **assistant-ui** — 聊天消息树、BranchPicker、ActionBar
- **i18n** — 基于 next-intl，默认韩语
- **响应式** — Mobile sidebar = Sheet，Desktop = SidebarProvider

</details>

<details>
<summary><b>🛒 Marketplace</b></summary>

- **Catalog** — 将 Agent / MCP Server / Skill 发布到公开 Marketplace，并可一键安装
- **原始项-安装项分离** — 安装时在用户账户中创建独立副本，与原始项更新互不影响
- **Version snapshot** — 在 `marketplace_versions` 表中管理 immutable 版本历史
- **Credential binding** — 安装时将每个 Skill 所需的 credential 映射到用户账户 Key
- **Tool dependency 显示** — 在安装 wizard 中提示 Skill 所需工具（例如 Tavily），
  并在运行时自动注入
- **Moderation** — `super_user` 在 `/settings/marketplace-admin` 中进行公开审核

</details>

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                      │
│  app/（route） → components/（UI） → lib/api,hooks,stores        │
│  ↓ fetch + SSE (EventSource)                                   │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                       Backend (FastAPI)                         │
│  routers/ → services/ → models/ (SQLAlchemy 2.0 async)         │
│                                                                 │
│  agent_runtime/                                                 │
│    ├ builder_v3/（对话式 Meta Builder — 最新）                      │
│    ├ executor.py (compat facade)                                │
│    ├ runtime_component_builder.py (models/tools/skills/memory)  │
│    ├ agent_stream_runner.py（stream/invoke 执行）                │
│    ├ streaming.py (LangGraph events → SSE + traces + artifacts) │
│    ├ mcp_tool_loader.py / skill_executor.py                     │
│    └ trigger_executor.py（Schedule → invoke）                       │
│                                                                 │
│  scheduler.py — APScheduler singleton                              │
└─────────────────────────────────────────────────────────────────┘
                  ↓                              ↓
       PostgreSQL（模型/对话/工具）      LangGraph PostgresSaver
                                        （checkpoint = 消息树）
```

### 三层结构

- **Router**（`app/routers/`）— HTTP endpoint、request/response 转换
- **Service**（`app/services/`）— 业务逻辑、DB query、transaction
- **Model** (`app/models/`) — SQLAlchemy ORM

### Frontend pattern

- API client（`lib/api/`） → TanStack Query hook（`lib/hooks/`） → component
- Chat SSE 由 `lib/sse/` 中的 EventSource wrapper 按 token 处理
- Design token 位于 `lib/design-tokens.ts` + `app/globals.css`（基于 oklch）

详细内容请参考 [`CLAUDE.md`](CLAUDE.md)（Developer Handbook）。

## 📁 项目结构

```
natural-mold/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app factory + lifespan
│   │   ├── config.py            # pydantic-settings (.env)
│   │   ├── database.py          # async engine + session
│   │   ├── dependencies.py      # get_db, get_current_user, require_super_user, verify_csrf
│   │   ├── scheduler.py         # APScheduler singleton
│   │   ├── models/              # SQLAlchemy ORM
│   │   ├── schemas/             # Pydantic schema
│   │   ├── routers/             # HTTP Router
│   │   ├── services/            # 业务逻辑
│   │   ├── credentials/         # Cipher V2 + domain
│   │   ├── agent_runtime/       # AI 执行引擎
│   │   └── seed/                # seed data
│   ├── alembic/versions/        # migration（head: m76_pinned_conv_summaries）
│   └── tests/                   # pytest (aiosqlite in-memory)
├── frontend/
│   └── src/
│       ├── app/                 # Next.js App Router（23+ route）
│       ├── components/          # UI component
│       └── lib/                 # api, hooks, stores, sse, types
├── docs/
│   ├── PRD.md                   # 产品需求
│   ├── PRD-screens.md           # 页面 wireframe
│   ├── ARCHITECTURE.md          # 系统架构
│   ├── design-docs/             # ADR（设计决策）
│   ├── marketplace-resources-prd.md  # Marketplace PRD
│   └── tool-setup-guide.md      # 工具 API Key 设置
├── tasks/                       # 任务笔记 + archive/
├── docker-compose.yml
├── HANDOFF.md                   # Session handoff 文档
├── TASKS.md                     # 按 Phase 划分的 task tracker
├── CLAUDE.md                    # Developer Handbook
├── CONTRIBUTING.md
└── SECURITY.md
```

## 🔧 环境变量

完整列表请参考 `backend/.env.example`。最小运行 Key：

| 变量 | 必需 | 说明 |
|------|------|------|
| `DATABASE_URL` | O | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `DATABASE_URL_SYNC` | O | PostgreSQL sync URL（`postgresql://...`）— 用于 LangGraph checkpointer。**不会从 `DATABASE_URL` 派生**，因此更换 DB host 时两者都要配置 |
| `ENCRYPTION_KEYS` | O | Cipher V2 master key — 以逗号分隔的 64-char hex，第一个为 active key（HKDF-SHA256 + AES-256-GCM）。生成：`python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_SECRET` | O | JWT HS256 signing key（ADR-016 多用户认证） |
| LLM Key（`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 等） | - | 推荐在 UI Credentials 中登记（ADR-013）。ENV 是 dev bootstrap 的可选值 |
| `OPENROUTER_API_KEY` | - | Agent 图片生成（OpenRouter + Gemini Flash Image） |
| `LANGSMITH_API_KEY` | - | LangSmith tracing（可选） |
| `TAVILY_API_KEY` | - | Tavily 搜索 / Deep Research skill 使用的 hosted key（可选） |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | - | Naver 搜索工具 |
| `GOOGLE_API_KEY` / `GOOGLE_CSE_ID` | - | Google CSE 工具 |
| Google OAuth2 令牌 | - | Gmail / Calendar 工具（`scripts/google_oauth_setup.py`） |

各工具的 key 设置请参考 [`docs/tool-setup-guide.md`](docs/tool-setup-guide.md)。

## 🧩 结构化数据（JSON-LD）

如果将 Moldy README 发布到项目主页、文档站点或产品页面，则可以使用下面的 JSON-LD
。GitHub README 渲染不会执行 JSON-LD，因此请将其放置在实际 Web
页面中 server-rendered 的 `<script type="application/ld+json">` 元素内。
该 schema 仅使用 repository 中可核实的事实。建议仅在新增正式资料页或文档 URL
之后再添加 `sameAs` 链接。

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "https://github.com/YooSuhwa/natural-mold#organization",
      "name": "Moldy 贡献者",
      "url": "https://github.com/YooSuhwa/natural-mold",
      "sameAs": [
        "https://github.com/YooSuhwa/natural-mold"
      ],
      "description": "Moldy 贡献者负责维护一款可创建、聊天和调度 AI Agent 的开源 self-hostable AI Agent 构建器。",
      "knowsAbout": [
        "AI Agent 构建器",
        "LangGraph",
        "deepagents",
        "FastAPI",
        "Next.js",
        "Model Context Protocol",
        "credential 加密",
        "Agent 调度"
      ]
    },
    {
      "@type": "SoftwareApplication",
      "@id": "https://github.com/YooSuhwa/natural-mold#software",
      "name": "Moldy",
      "url": "https://github.com/YooSuhwa/natural-mold",
      "description": "Moldy 是一款可在 Web UI 中创建、配置、聊天和调度 AI Agent 的开源 self-hostable 无代码 AI Agent 构建器。",
      "applicationCategory": "DeveloperApplication",
      "operatingSystem": "Web",
      "isAccessibleForFree": true,
      "license": "https://github.com/YooSuhwa/natural-mold/blob/main/LICENSE",
      "softwareVersion": "development snapshot, migration head m76_pinned_conv_summaries",
      "dateModified": "2026-09-01",
      "author": {
        "@id": "https://github.com/YooSuhwa/natural-mold#organization"
      },
      "publisher": {
        "@id": "https://github.com/YooSuhwa/natural-mold#organization"
      },
      "offers": {
        "@type": "Offer",
        "price": "0",
        "priceCurrency": "USD"
      },
      "softwareRequirements": [
        "Python 3.12",
        "Node.js 22",
        "PostgreSQL 16",
        "Docker",
        "uv",
        "pnpm"
      ],
      "featureList": [
        "对话式 AI Agent 构建器",
        "LangGraph 与 deepagents runtime",
        "MCP server registry 与工具导入",
        "Skill package 管理",
        "JWT 与 HttpOnly cookie 认证",
        "Cipher V2 credential 加密",
        "SSE chat streaming",
        "可分支对话",
        "Cron 与 interval Agent trigger",
        "Skill marketplace 安装"
      ]
    },
    {
      "@type": "SoftwareSourceCode",
      "@id": "https://github.com/YooSuhwa/natural-mold#source-code",
      "name": "Moldy source code",
      "codeRepository": "https://github.com/YooSuhwa/natural-mold",
      "programmingLanguage": [
        "Python",
        "TypeScript"
      ],
      "runtimePlatform": [
        "Python 3.12",
        "Node.js 22",
        "PostgreSQL 16"
      ],
      "license": "https://github.com/YooSuhwa/natural-mold/blob/main/LICENSE",
      "targetProduct": {
        "@id": "https://github.com/YooSuhwa/natural-mold#software"
      }
    },
    {
      "@type": "FAQPage",
      "@id": "https://github.com/YooSuhwa/natural-mold#faq",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "Moldy 能做什么？",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Moldy 可将自然语言需求转化为可执行的 AI Agent，并可使用工具、skill、MCP 工具、credential、chat streaming 与 schedule trigger。"
          }
        },
        {
          "@type": "Question",
          "name": "Moldy 如何保护 credential 与系统权限？",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Moldy 将由 super_user 管理的系统资源与用户级资源分离，使用 JWT auth、HttpOnly cookie、CSRF 防护，并通过基于 HKDF-SHA256 与 AES-256-GCM 的 Cipher V2 加密 credential payload。"
          }
        },
        {
          "@type": "Question",
          "name": "Moldy 使用什么技术栈？",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Moldy 使用 Next.js 16、React 19、TailwindCSS v4、FastAPI、SQLAlchemy 2.0 async、PostgreSQL 16、LangGraph 1.x、deepagents create_deep_agent。"
          }
        }
      ]
    }
  ]
}
```

## 🤝 Contributing

贡献方式请参考 [`CONTRIBUTING.md`](CONTRIBUTING.md)。安全问题请
按照 [`SECURITY.md`](SECURITY.md) 中的流程处理。

## 📄 License

[MIT](LICENSE) — Copyright (c) 2026 Moldy contributors.

---

<div align="center">

详细规范、设计 token 与 long-horizon workflow 请参考 [`CLAUDE.md`](CLAUDE.md) 与
[`frontend/AGENTS.md`](frontend/AGENTS.md)。

</div>
