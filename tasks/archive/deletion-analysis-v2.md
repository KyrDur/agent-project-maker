# 删除分析报告 v2

> 为替换 v2 Builder/Assistant 而分析现有 creation_agent、fix_agent 依赖关系
> 分析日期：2026-04-07 | 分析者：bezos (QA)

---

## 可立即删除

| 文件 | 原因 |
|------|------|
| `backend/app/agent_runtime/creation_agent.py` | 完全由 v2 Builder orchestrator 替代。外部依赖：仅 `agent_creation_service.py` import → 可同时替换 |
| `backend/app/agent_runtime/fix_agent.py` | 完全由 v2 Assistant 替代。外部依赖：仅 `routers/fix_agent.py` import → 可同时替换 |
| `backend/app/schemas/fix_agent.py` | 由 v2 `schemas/assistant.py` 替代。外部依赖：仅 `routers/fix_agent.py` import |
| `backend/tests/test_creation_agent.py` | 被删除的 `creation_agent.py` 的测试。10 个测试 case 全部属于删除范围 |
| `backend/tests/test_fix_agent.py` | 被删除的 `fix_agent.py` 和 `routers/fix_agent.py` 的测试。约 20 个测试 case 全部属于删除范围 |
| `frontend/tests/unit/api/creation-session.test.ts` | `creation-session.ts` API client 测试 |
| `frontend/tests/mocks/fixtures.ts`（部分） | `CreationMessageResult` 类型 import → 删除类型时，该 fixture 也需删除/替换 |

---

## 删除时需要修改（依赖关系）

### Backend

| 删除对象 | 依赖文件 | 修改内容 |
|-----------|----------|----------|
| `creation_agent.py` | `backend/app/services/agent_creation_service.py:8` | 删除 `from app.agent_runtime.creation_agent import run_creation_conversation`。把 `send_message()` 函数（L39-73）内部的 `run_creation_conversation()` 调用替换为 v2 Builder 调用 |
| `routers/agent_creation.py` | `backend/app/main.py:160,175` | 删除 `from app.routers import agent_creation` import，删除 `app.include_router(agent_creation.router)`。新增 v2 `routers/builder.py` |
| `routers/fix_agent.py` | `backend/app/main.py:163,176` | 删除 `from app.routers import fix_agent` import，删除 `app.include_router(fix_agent.router)`。新增 v2 `routers/assistant.py` |
| `creation_agent.py` | `backend/pyproject.toml:93` | 删除 `"app/agent_runtime/creation_agent.py" = ["E501"]` ruff 例外配置 |
| `schemas/agent_creation.py` | `backend/app/routers/agent_creation.py:11-15` | 删除路由时一并删除（依赖断开） |
| `models/agent_creation_session.py` | `backend/app/models/__init__.py:2,24` | 删除 import 及 `__all__` export（或替换为 v2 `BuilderSession` model） |
| `models/agent_creation_session.py` | `backend/app/models/user.py:26-28` | 删除 `creation_sessions` relationship（或替换为 v2 builder_sessions） |
| `models/agent_creation_session.py` | `backend/app/services/agent_creation_service.py:10` | 删除 import — 替换整个 service 时一并处理 |
| `agent_creation_service.py` | `backend/app/routers/agent_creation.py:16` | 删除路由时一并删除 |
| `test_agent_creation_extended.py` | 自身（14 个测试） | 全面引用 `agent_creation_service`, `AgentCreationSession`。整体删除后替换为 v2 测试 |

### Frontend

| 删除对象 | 依赖文件 | 修改内容 |
|-----------|----------|----------|
| `lib/api/creation-session.ts` | `app/agents/new/conversational/page.tsx:34` | 删除 `creationSessionApi`, `CreationMessageResult` import。替换为 v2 Builder API client |
| `lib/types/index.ts`（部分） | `creation-session.ts:2`, `conversational/page.tsx:35` | 删除 `CreationSession`（L295-302）、`DraftConfig`（L304-311）interface。替换为 v2 Builder 类型 |
| `components/agent/fix-agent-dialog.tsx` | `app/agents/[agentId]/settings/page.tsx:27,190` | 删除 `FixAgentDialog` import 和渲染。替换为 v2 Assistant 入口 |
| `app/agents/new/conversational/page.tsx` | `tests/pages/agent-conversational.test.tsx:2`, `agents/new/page.tsx:26` | 删除整个 page，或替换为 v2 Builder page |
| `tests/pages/agent-conversational.test.tsx` | 自身 | conversational page 测试。整体删除后替换为 v2 Builder page 测试 |
| `tests/pages/dashboard.test.tsx`（部分） | L67-68 | `'通过对话创建'` 链接 → 需要修改 `/agents/new/conversational` 路径 assertion |
| `tests/pages/agents-new.test.tsx`（部分） | L27-30 | 需要修改 conversational option 路径 assertion |
| E2E: `e2e/smoke.spec.ts` (部分) | L163-164 | settings page 的 '用 AI 修改' 按钮 assertion → 修改为 v2 Assistant 入口 |
| E2E: `e2e/smoke.spec.ts`（部分） | L357-389 | 整个 `Smoke Test - Conversational Creation` 测试块 → 替换为 v2 Builder page 测试 |
| `messages/ko.json`（部分） | L52, L715 | 修改/替换 `conversational` 相关 i18n key |

### DB/migration

| 对象 | 修改内容 |
|------|----------|
| `agent_creation_sessions` table | **不删除**。编写在 v2 中扩展/替换为 `builder_sessions` 的 migration。现有数据是 PoC，因此也可以 drop+recreate，但需要用 Alembic migration 跟踪 |
| `alembic/versions/aa5b4cc59ddb_initial_tables.py` | 无需修改（已应用的 migration）。在新 migration 中修改/替换 table |

---

## 可复用逻辑（迁移到 v2）

| 函数/逻辑 | 位置 | v2 中的使用方式 |
|-----------|------|-----------------|
| `confirm_creation()` 工具名匹配 | `agent_creation_service.py:94-105` | 在 Builder 的 `build_final_agent` 阶段复用 `recommended_tool_names` → 自动链接 Tool DB record 的逻辑。`func.lower(Tool.name).in_(lower_names)` pattern |
| `confirm_creation()` skill 名匹配 | `agent_creation_service.py:107-118` | 在 Builder 的 `build_final_agent` 中同样自动链接 skill |
| `confirm_creation()` model 匹配 | `agent_creation_service.py:82-92` | `display_name` → resolve Model ID。在 Builder 中复用 |
| `confirm_creation()` Agent 创建 | `agent_creation_service.py:120-135` | Agent ORM instance 创建 + tool_links/skill_links 设置 pattern |
| `_apply_changes()` 添加/删除工具 | `routers/fix_agent.py:81-133` | 在 Assistant 的工具修改功能中复用 batch resolve pattern。`func.lower(Tool.name).in_()` + 当前 tool_ids diff |
| `_apply_changes()` model 变更 | `routers/fix_agent.py:98-104` | 在 Assistant 中复用 display_name → model_id 转换 |
| `extract_json_from_markdown()` | `message_utils.py` | **不是删除对象**。作为 utility 在 v2 中继续使用 |
| `strip_json_blocks()` | `message_utils.py` | **不是删除对象**。作为 utility 在 v2 中继续使用 |
| `convert_to_langchain_messages()` | `message_utils.py` | **不是删除对象**。在 v2 中也可使用 |

---

## 前端影响摘要

### 删除文件（6 个）
1. `frontend/src/lib/api/creation-session.ts` — 替换为 v2 Builder API client
2. `frontend/src/components/agent/fix-agent-dialog.tsx` — 替换为 v2 Assistant 入口 UI
3. `frontend/src/app/agents/new/conversational/page.tsx` — 替换为 v2 Builder page
4. `frontend/tests/unit/api/creation-session.test.ts` — 替换为 v2 Builder API 测试
5. `frontend/tests/pages/agent-conversational.test.tsx` — 替换为 v2 Builder page 测试
6. `frontend/tests/mocks/fixtures.ts`（部分） — 删除 `CreationMessageResult` mock

### 修改文件（6 个）
1. `frontend/src/lib/types/index.ts` — 删除 `CreationSession`, `DraftConfig` 类型 → 新增 v2 Builder 类型
2. `frontend/src/app/agents/[agentId]/settings/page.tsx` — 删除 `FixAgentDialog` import/渲染 → v2 Assistant 入口
3. `frontend/src/app/agents/new/page.tsx:26` — 将 `/agents/new/conversational` routing → v2 Builder 路径
4. `frontend/src/app/page.tsx:44-45` — 修改 dashboard '通过对话创建' Quick Action 的路径/label
5. `frontend/src/components/layout/breadcrumb-nav.tsx:18` — 修改 `conversational` breadcrumb key
6. `frontend/messages/ko.json` — 替换 conversational、fix 相关 i18n key

### 修改测试（3 个）
1. `frontend/tests/pages/dashboard.test.tsx:67-68` — 路径 assertion
2. `frontend/tests/pages/agents-new.test.tsx:27-30` — conversational option assertion
3. `frontend/e2e/smoke.spec.ts:163,357-389` — fix agent 按钮 + conversational page E2E

---

## 删除顺序（基于依赖）

v2 代码准备好后，按以下顺序替换：

### Phase A: Backend（顺序重要）
1. 新增 v2 文件（builder/, assistant/, 新 router/service/schema）
2. 在 `main.py` 注册 v2 router
3. 从 `main.py` 移除现有 router（`agent_creation`, `fix_agent`）
4. 删除现有 router：`routers/agent_creation.py`, `routers/fix_agent.py`
5. 删除现有 service：`services/agent_creation_service.py`
6. 删除现有 runtime：`agent_runtime/creation_agent.py`, `agent_runtime/fix_agent.py`
7. 删除现有 schema：`schemas/agent_creation.py`, `schemas/fix_agent.py`
8. 替换 model：`models/agent_creation_session.py` → `models/builder_session.py`
9. 更新 `models/__init__.py`, `models/user.py`
10. 删除 `pyproject.toml` ruff 例外（L93）
11. 编写 Alembic migration
12. 删除现有测试 + 新增 v2 测试

### Phase B: Frontend（Backend API 稳定后）
1. 新增 v2 API client + 类型
2. 新增 v2 Builder page、Assistant UI
3. 删除现有文件（`creation-session.ts`, `fix-agent-dialog.tsx`, `conversational/page.tsx`）
4. 修改引用（settings, new, dashboard, breadcrumb, i18n）
5. 删除现有测试 + 新增 v2 测试
6. 修改 E2E 测试

---

## 影响范围摘要

| 类别 | 删除 | 修改 | 新增 (v2) |
|----------|------|------|----------|
| Backend runtime | 2 | 0 | ~4 (builder/*, assistant/*) |
| Backend router | 2 | 1 (main.py) | 2 (builder.py, assistant.py) |
| Backend service | 1 | 0 | 2 (builder_service, assistant_service) |
| Backend schema | 2 | 0 | 2 (builder.py, assistant.py) |
| Backend model | 1（替换） | 2 (__init__, user) | 1 (builder_session) |
| Backend 配置 | 0 | 1 (pyproject.toml) | 0 |
| Backend 测试 | 2 | 1 (extended) | ~2 |
| Frontend page | 1 | 3 | ~2 |
| Frontend 组件 | 1 | 0 | ~2 |
| Frontend API | 1 | 0 | 2 |
| Frontend 类型 | 0 | 1 | 0（新增 v2 类型） |
| Frontend i18n | 0 | 1 | 0 |
| Frontend 测试 | 2 | 3 | ~2 |
| E2E 测试 | 0 | 1 | 0 |
| DB migration | 0 | 0 | 1 |
| **合计** | **15** | **14** | **~22** |
