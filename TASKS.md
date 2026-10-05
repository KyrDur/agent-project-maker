# Moldy — TASKS

> 本文件保留原型任务记录；当前产品定位与本轮验收以 README.md 为准。

<!-- project-current-source: migration=m77_side_chat_link; deepagents=0.7.11; ruff=0.16.5; refreshed=2026-09-10 -->

> Last updated: 2026-09-10
> Source-aligned snapshot: Alembic head `m77_side_chat_link`. The
> original Phase 0~14 list below is preserved as historical build-up context;
> M59 remains the feature-origin point for generated artifacts, not the current
> migration head.

## Current Source Snapshot (2026-09-10)

- [x] Multi-user auth and operator split (ADR-016): JWT, HttpOnly cookies, CSRF,
  refresh-token rotation, `super_user`, system/user resource separation.
- [x] Marketplace foundation: schema M40~M44, skill lineage, `agent_skills.config`,
  catalog/detail/version, install/update/uninstall, publish/version/ACL/admin,
  secret scan, k-skill importer, credential requirements and bindings.
- [x] System LLM settings (ADR-019): role-based model slots for builder,
  assistant, and image generation.
- [x] Schedule productization M47~M50: guardrails, conversation policy, run
  metadata/history.
- [x] Agent API M56: deployments, scoped API keys, threads, runs, `/v1`
  blocking/streaming/compatibility endpoints.
- [x] Long-term memory controls: user/agent settings, memory records/proposals,
  runtime memory tools, frontend settings.
- [x] Audit system M57: audit event model/router/service and auth/marketplace
  event recording.
- [x] Generated artifacts M59: conversation artifact/version models, artifact
  service/storage/router, chat right rail previews, `/artifacts` library.
- [x] Subagent runtime alignment: agent-to-agent delegation, runtime identity,
  filesystem permission updates.
- [x] Runtime cleanup: executor split into facade + runtime config/component
  builder/stream runner/MCP loader/skill executor.
- [x] Deep Agents 0.7.11 migration with Moldy's non-deleting filesystem and
  Todo projection compatibility at the shared graph-build boundary.
- [x] Versioned runtime policy: agent-level configuration, immutable
  conversation snapshots, run provenance, filesystem/Todo/summarization
  capability enforcement, and agent create/settings UI.
- [x] Conversation router cleanup: split CRUD/messages/branches/files/traces and
  move stream responsibilities into services.
- [x] Frontend performance and state cleanup: lazy chat preview modules, scoped
  i18n payloads, agent settings draft hook/lib.
- [x] MCP and Agent marketplace publishing/install UI and backend: MCP templates,
  agent blueprints, dependency snapshots, credential rebinding, shared publish/install wizards.
- [x] assistant-ui 0.15.18 and chat features: queued input (M73), persisted run
  metrics (M74), MCP Apps provenance (M75), pinned conversation summaries (M76).
  Direct injection into the currently running run is not implemented.
- [x] Backend Pyright basic-mode debt cleared and made blocking in CI (PR #302);
  see `docs/pyright-burndown-plan.md`. This is not a claim of strict-mode coverage.
- [x] Selected-message quotes with editable comments and source previews; independent
  same-agent side chat with explicit return-to-main and save-to-list actions (M77).
  Side conversations are server-stored and reopen after reload; closing the panel
  does not delete them. Main drafts and runs are isolated from side conversations.
- [x] Scripted E2E stabilization (PR #303) and smoke CI fixes (PR #304) merged.
- [x] Profile personalization (2), agent MCP attachment (1), and marketplace
  publish/moderation (3) E2E scenarios added. Focused capture run passed all six;
  validation scope and remaining visual gaps are recorded in `docs/e2e-coverage.md`.

## Active Follow-ups

- [x] Address narrow-viewport tool/skill dialog clipping, Korean text wrapping,
  and settings-sidebar footer overlap observed in the resource captures. The focused
  375/768/1280 capture run and two independent visual reviews passed; see
  `docs/e2e-coverage.md`.
- [x] Extend marketplace validation to credential-bound setup recovery and
  dirty in-place updates. The browser flow covers `needs_setup` → active with
  the same installation/resource, then an explicit overwrite of local edits;
  broader backend Marketplace/OAuth contracts are green.
- [ ] Complete a manual third-party OAuth consent/callback run against a real
  provider account. State, PKCE, callback, token, and ownership guards are
  automated, but the external consent screen remains intentionally manual.
- [x] Harden multi-worktree scheduler behavior when several backends share one DB:
  continuously validate/retry the PostgreSQL advisory-lock leader, fence stale
  scheduled triggers, and reconcile shared trigger definitions without resetting
  unchanged interval cadence. Unit and disposable-PostgreSQL handoff tests cover it.
- [ ] Keep `docs/ARCHITECTURE.md`, `docs/PRD.md`, `AGENTS.md`, and README files
  synchronized after migrations or runtime module splits.
- [ ] Treat Rubric, total technical-debt cleanup, domain relocation,
  attachment/video expansion, async subagents, general StoreBackend adoption,
  and observation-window removal as separately approved programs;
  none is a current commitment in this snapshot.
  `ScopedOffloadBackend` already uses CompositeBackend for scoped offloads;
  this is not a pending wholesale backend replacement.

---

## Phase 0: 项目初始化

- [x] git init + .gitignore
- [x] .mise.toml (Python 3.12, Node 22)
- [x] docker-compose.yml (PostgreSQL)
- [x] backend/ 搭建基础结构 (pyproject.toml, app factory, config, database)
- [x] frontend/ 搭建基础结构 (pnpm create next-app, TailwindCSS v4, shadcn/ui)

## Phase 1: Backend — DB 与基本 CRUD

- [x] SQLAlchemy 模型，11 张表
- [x] Alembic 初始迁移
- [x] 初始 Mock user dependency 与 Pydantic schema（现已由 ADR-016 auth dependency 替代）
- [x] 种子数据（默认模型、4 个模板）
- [x] Agent CRUD API (5 endpoints) 与测试
- [x] Template API (2 endpoints) 与测试
- [x] Model API (3 endpoints) 与测试
- [x] Tool API (5 endpoints) 与测试

## Phase 2: Backend — 聊天引擎 (LangChain/LangGraph)

- [x] agent_runtime/model_factory.py
- [x] agent_runtime/tool_factory.py
- [x] agent_runtime/executor.py（现为 `create_deep_agent` facade 与拆分后的 runtime modules）
- [x] agent_runtime/streaming.py (LangGraph → SSE)
- [x] agent_runtime/token_tracker.py
- [x] Conversation API (4 endpoints) + LangGraph PostgresSaver
- [x] 聊天引擎集成测试 — `backend/tests/integration/test_stream_resume.py` 与 scripted chat E2E

## Phase 3: Backend — MCP、对话创建与用量

- [x] agent_runtime/mcp_client.py 与 MCP 连接测试 endpoint
- [x] agent_runtime/creation_agent.py（对话创建的元智能体）
- [x] Agent creation session API (4 endpoints) 与测试
- [x] Usage API (2 endpoints) 与测试

## Phase 4: Frontend — 布局、仪表盘与 CRUD 页面

- [x] TypeScript 类型、API 客户端与 TanStack Query hooks
- [x] SSE 流式客户端与 Jotai stores
- [x] 公共布局（侧边栏、页头）
- [x] 仪表盘（智能体卡片网格与用量摘要）
- [x] 智能体设置页面
- [x] 工具管理页面（MCP/Custom 注册弹窗）
- [x] 模型管理页面
- [x] 用量仪表盘

## Phase 5: Frontend — 聊天与智能体创建

- [x] 智能体聊天页面
- [x] 对话创建智能体页面
- [x] 模板选择页面

## Phase 7A: Backend — 预构建工具目录

- [x] Tool 模型 schema 修改 (user_id nullable, is_system 标志) 与迁移
- [x] 内置工具实现 (Web Search, Web Scraper, Current DateTime)，位于 tool_factory.py
- [x] 种子数据 (default_tools.py) 与 main.py 初始化
- [x] 服务层修改（list_tools 包含系统工具，防止删除）
- [x] Executor builtin 类型处理
- [x] schema/类型更新 (is_system)
- [x] 测试

## Phase 7B: Backend — 创建智能体时自动绑定工具

- [x] confirm_creation() 中匹配 recommended_tool_names 名称并自动绑定
- [x] send_message() 提供系统工具上下文
- [x] 从模板创建时自动绑定工具
- [x] 测试

## Phase 7C: Backend — 触发器与调度系统

- [x] AgentTrigger 模型与迁移
- [x] 触发器 schema (Pydantic)
- [x] 触发器服务 (CRUD)
- [x] 触发器执行器 (trigger_executor.py)
- [x] APScheduler 集成 (scheduler.py + main.py)
- [x] 触发器 API (4 endpoints)
- [x] 测试

## Phase 8: Frontend — 工具与触发器 UI

- [x] TypeScript 类型、API 客户端与 hooks (triggers)
- [x] 工具管理页面展示系统工具
- [x] 智能体设置的触发器配置区域
- [x] 仪表盘智能体卡片展示工具名称

## Phase 9: Backend — 扩展内置工具 (Naver/Google)

- [x] config.py 增加 Naver/Google API Key 配置
- [x] naver_tools.py — Naver 搜索 API 通用构建器 (Blog, News, Image, Shopping, Local)
- [x] google_tools.py — Google Custom Search API 构建器 (Web, News, Image)
- [x] tool_factory.py 注册 8 个新工具并支持 auth_config
- [x] executor.py 传递 auth_config
- [x] default_tools.py 增加 8 项种子数据
- [x] default_templates.py 增加 3 个模板（新闻监测、购物比较、餐厅探索）
- [x] main.py 种子初始化改为 upsert
- [x] 测试（15 项通过）

## Phase 10A: Backend — Google Chat Webhook 工具 (P1)

- [x] google_workspace_tools.py 实现 Google Chat Webhook send
- [x] config.py 增加 google_chat_webhook_url 配置
- [x] tool_factory.py 注册 prebuilt 目录
- [x] default_tools.py 增加种子数据
- [x] 测试（20 项通过）

## Phase 10B: Backend — Google OAuth2 基础能力与 Gmail 工具 (P2)

- [x] 增加 google-auth、google-api-python-client 依赖
- [x] config.py — OAuth2 配置 (client_id, client_secret, refresh_token)
- [x] google_auth.py — OAuth2 令牌管理辅助函数（自动刷新）
- [x] scripts/google_oauth_setup.py — 一次性获取 refresh_token 的脚本
- [x] google_workspace_tools.py — Gmail Read（查询列表与读取正文）
- [x] google_workspace_tools.py — Gmail Send（发送邮件）
- [x] tool_factory.py 注册 2 个 Gmail 工具
- [x] default_tools.py 增加 Gmail 种子数据
- [x] 测试（25 项通过）

## Phase 10C: Backend — Google Calendar 工具 (P3)

- [x] google_workspace_tools.py — Calendar List Events（查询日程）
- [x] google_workspace_tools.py — Calendar Create Event（创建日程）
- [x] google_workspace_tools.py — Calendar Update Event（修改日程）
- [x] tool_factory.py 注册 3 个 Calendar 工具
- [x] default_tools.py 增加 Calendar 种子数据
- [x] default_templates.py 更新“邮件助手”与“Daily Brief”模板
- [x] 测试（29 项通过）

## Phase 10D: Backend — 每个智能体的工具配置 (agent_tools.config)

- [x] agent_tools 表新增 config(JSON) 列与 Alembic 迁移
- [x] AgentToolLink 模型 (association object 模式) 与 Agent.tool_links 关系
- [x] 构建 tools_config 时，将 agent_tool.config 合并到 tool.auth_config
- [x] AgentCreate/Update schema 新增 tool_configs 字段
- [x] agent_service 绑定工具时保存 config
- [x] conversations.py 与 trigger_executor.py 应用合并逻辑
- [x] 测试（全部 48 项通过）

## Phase 11: 展示 Pre-built 工具的服务器 Key 状态

- [x] Backend — ToolResponse 增加 server_key_available computed 字段
- [x] Frontend — 工具卡片三种状态（未配置 Key、服务器已配置、配置完成）
- [x] 测试（全部 62 项通过）

## Phase 6: 集成与体验完善

- [x] Scripted E2E 回归验证 — 当前范围与手工排除项见 `docs/e2e-coverage.md`
- [x] 错误处理、loading skeleton、empty state
- [x] Docker Compose 完整启动配置 (Dockerfile + docker-compose.yml)
- [ ] 无障碍、键盘导航与性能验证

## Phase 12: UX 改进 — 参考 Deep Agent Builder

### Backend
- [x] Agent 模型增加 is_favorite、model_params 字段
- [x] Tool 模型增加 tags 字段
- [x] Alembic 迁移（整合）
- [x] Agent 收藏切换 API (PATCH)
- [x] Agent schema 增加 is_favorite、model_params
- [x] Tool schema 增加 tags、agent_count
- [x] tool_service — agent_count 计算逻辑
- [x] default_tools.py — 系统工具标签
- [x] executor/model_factory 传递 model_params
- [x] 测试（62 项通过）

### Frontend — 深色模式
- [x] 安装 next-themes 与 ThemeProvider
- [x] 侧边栏主题切换按钮

### Frontend — 仪表盘搜索、排序与收藏
- [x] 仪表盘搜索与排序 UI
- [x] 智能体卡片收藏星标切换
- [x] API 客户端与 hooks (toggleFavorite)

### Frontend — 工具目录 UX
- [x] 标签筛选
- [x] 工具详情 Sheet

### Frontend — 模型参数
- [x] 智能体设置中的模型参数区域 (temperature/top_p/max_tokens)

### Frontend — 聊天 UX 增强
- [x] 工具调用详情折叠、展开与耗时
- [x] 消息令牌数、费用与复制按钮
- [x] 流式“思考中...”动画

## Phase 13: Tier 2 — Fix Agent 与 Skill 系统

### Fix Agent — Backend
- [x] fix_agent.py — 通过对话修改智能体的元智能体
- [x] fix_agent schema（请求与响应）
- [x] fix_agent API (POST /api/agents/:id/fix)
- [x] 测试（62 项通过）

### Fix Agent — Frontend
- [x] Fix Agent 对话 UI 组件 (FixAgentDialog)
- [x] 智能体设置中的“通过 AI 修改”按钮

### Skill 系统 — Backend
- [x] Skill 模型与 agent_skills 关联表
- [x] Alembic 迁移
- [x] Skill CRUD API (5 endpoints)
- [x] Executor 将 Skill content 注入 system_prompt
- [x] 测试（62 项通过）

### Skill 系统 — Frontend
- [x] 侧边栏增加“技能”菜单
- [x] Skill 管理页面 (CRUD)
- [x] 智能体设置中的 Skill 绑定与解除

## Phase 14: 中间件系统（历史 create_agent 转换 → 当前 create_deep_agent runtime）

### Backend — 运行时转换与数据层 (Phase A+B) ✅
- [x] executor.py: create_react_agent → create_agent + middleware（之后已改为 `create_deep_agent`）
- [x] middleware_registry.py: 22 种中间件目录与实例构建器
- [x] Agent 模型: middleware_configs JSON 列与 Alembic 迁移
- [x] API schema: 扩展 MiddlewareConfigEntry、AgentCreate/Update/Response
- [x] agent_service: middleware_configs 处理
- [x] GET /api/middlewares endpoint
- [x] conversations.py: 将 middleware_configs 传给运行时

### Frontend — 中间件 UI (Phase C) ✅
- [x] TypeScript 类型 (MiddlewareConfigEntry, MiddlewareRegistryItem)
- [x] API 客户端与 TanStack Query hooks
- [x] 中间件选择对话框 (AddMiddlewaresDialog)
- [x] Visual Settings Flow 中间件节点 (MiddlewaresNode)
- [x] 智能体设置中的中间件区域
- [x] 增加 i18n 文案

### 中间件 UX 改进 (Phase D) — 可选，按需进行
- [ ] 中间件预设一键应用（“基础”/“智能”/“高级”）
- [ ] 拖动调整中间件执行顺序（LangChain middleware 列表顺序即执行顺序）
- [ ] Provider 自动识别 UI（选择模型时推荐 Anthropic/OpenAI 专用中间件）
- [x] HumanInTheLoopMiddleware 中断 → 前端批准、拒绝 UI 与 E2E
