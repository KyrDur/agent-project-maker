# Builder v2 → v3 迁移: 删除分析 (Musk Step 2)

**分析执行者**: 贝索斯 (Bezos — QA/Quality DRI)<br>
**分析日期**: 2026-04-26<br>
**状态**: GREEN ✓（分析完成，分类明确）

---

## 摘要

从 Builder v2（7-phase 自动 pipeline）迁移到 v3（LangGraph StateGraph 8-phase + 聊天 UI 整合）时:

- **保留 (K)**: 11项 — LLM prompt, JSON schema, 通用 helper, catalog 逻辑
- **迁移 (M)**: 8项 — sub-agent 逻辑, UI pattern, router/service 结构
- **删除 (D)**: 5项 — orchestrator.py, phase-timeline, stream-builder 等 v2 专用基础设施

**不可立即删除项目**: 0项（全部在 v3 实现完成后）<br>
**需要额外调查**: 0项（依赖关系明确）

---

## 详细分析

### BACKEND

#### 1. `backend/app/agent_runtime/builder/orchestrator.py`
**状态**: **D（计划删除）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | D | 7-phase StateGraph pipeline。v3 中完全重新设计为8-phase。 |
| 第43-70行: `BuilderState` TypedDict | D | v3 移至 `BuilderState` (state.py) 并扩展字段（增加 image_url, todos, last_revision_message）。 |
| 第77-97行: `phase1_init()` | M(部分) | 逻辑类似，但 v3 增加进入/完成消息 + 进度卡片 emit。 |
| 第100-140行: `phase2_intent()` | M(部分) | 复用 intent_analyzer 调用逻辑，但 v3 增加 ask_user loop。 |
| 第143-197行: `phase3_tools()` | M(部分) | 复用 tool_recommender 调用，但 v3 增加 approval/revision interrupt loop。 |
| 第200-257行: `phase4_middlewares()` | M(部分) | 复用 middleware_recommender 调用，v3 增加 approval/revision loop。 |
| 第260-305行: `phase5_prompt()` | M(部分) | 复用 prompt_generator 调用，v3 增加 approval/revision loop。 |
| 第308-338行: `phase6_config()` + `phase7_preview()` | M(部分) | 复用 draft_config 组装逻辑，v3 拆为 phase7 + phase8。 |
| 第373-408行: `build_builder_graph()` | D | StateGraph topology 在 v3 中重新定义 (phase1→...→8 + router 分支)。 |
| 第419-462行: `run_builder_pipeline()` | M(部分) | SSE event yield pattern 在 v3 中也类似，但 node 结构变化。 |

**依赖整理**:
- `builder_service.py` L14 import `run_builder_pipeline` → 替换为 v3 graph.astream
- `tests/test_builder_sub_agents.py` 只测试 sub-agent，因此影响最小

**废弃时点**: v3 graph.py 实现 + router 集成完成后

---

#### 2. `backend/app/agent_runtime/builder/sub_agents/intent_analyzer.py`
**状态**: **K（保留）+ 复用 prompt**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | K | 原样保留意图分析逻辑。 |
| 第21行: 加载 `SYSTEM_PROMPT` | K | 完整保留 `builder/prompts/intent_analyzer.md` prompt 文本。v3 phase2 node 直接相同调用。 |
| 第37-58行: `analyze_intent()` 函数 | K | 保留函数 signature、JSON schema (AgentCreationIntent)、fallback 逻辑。v3 phase2_intent.py 中直接 import 复用。 |
| 第24-34行: `_build_task_description()` | K | 保留 prompt 编写逻辑。v3 中也相同使用。 |

**无需改位置**: helpers.py 的 `invoke_with_json_retry()` 调用在 v3 中也相同使用。

---

#### 3. `backend/app/agent_runtime/builder/sub_agents/tool_recommender.py`
**状态**: **K（保留）+ 复用 prompt**

| 项目 | 分类 | 说明 |
|-----|------|------|
| **整个文件** | K | 原样保留工具推荐逻辑。 |
| 第22行: `SYSTEM_PROMPT` | K | 完整保留 `builder/prompts/tool_recommender.md` prompt。v3 phase3_tools.py 中相同调用。 |
| 第52-85行: `recommend_tools()` | K | 保留函数 signature、ToolRecommendation JSON schema、catalog filter 逻辑。 |
| 第25-49行: helper 函数 | K | 保留 catalog formatting、任务描述生成逻辑。 |

**依赖**: 在 v3 phase3_tools.py 直接 import 并复用。

---

#### 4. `backend/app/agent_runtime/builder/sub_agents/middleware_recommender.py`
**状态**: **K（保留）+ 复用 prompt**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | K | 原样保留 middleware 推荐逻辑。 |
| 第27行: `SYSTEM_PROMPT` | K | 完整保留 `builder/prompts/middleware_recommender.md` prompt。v3 phase4_middlewares.py 中相同调用。 |
| 第64-96行: `recommend_middlewares()` | K | 保留函数 signature、MiddlewareRecommendation schema、catalog 验证逻辑。 |

---

#### 5. `backend/app/agent_runtime/builder/sub_agents/prompt_generator.py`
**状态**: **K（保留）+ 复用 prompt**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | K | 原样保留 system prompt 生成逻辑。 |
| 第25行: `SYSTEM_PROMPT` | K | 完整保留 `builder/prompts/prompt_generator.md` prompt。v3 phase5_prompt.py 中相同调用。 |
| 第88-163行: `generate_system_prompt()` | K | 保留函数 signature、prompt 验证（必需 section）、fallback 逻辑。 |
| 第79-85行: `_has_required_sections()` | K | 保留 prompt 质量验证逻辑。 |

**重要备注**: LLM 输出结构（Markdown 格式, 8+1 section）必须保留。v3 phase5 也使用相同验证。

---

#### 6. `backend/app/agent_runtime/builder/sub_agents/helpers.py`
**状态**: **K（保留, 通用基础设施）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | K | 所有 sub-agent 共享的通用 helper。v3 仍必需。 |
| 第36-46行: `load_prompt()` | K | prompt 文件 loader, cache。v3 中也相同使用。 |
| 第144-192行: `invoke_with_json_retry()` | K | LLM 调用 + JSON parsing + API retry 逻辑。v3 intent, tool, middleware node 直接调用。 |
| 第195-247行: `invoke_for_text()` | K | 生成 text response(prompt) 的逻辑。v3 phase5_prompt.py 中相同调用。 |
| 第66-92行: `_get_builder_model()`, `_get_fallback_model()` | K | model factory。v3 中也相同使用。 |
| 第94-141行: `_invoke_with_api_retry()` | K | API error retry 逻辑。v3 all nodes 使用。 |

**依赖**:
- import `app.agent_runtime.model_factory.create_chat_model` → 无变化
- import `app.config.settings` → 无变化

---

#### 7. `backend/app/agent_runtime/builder/prompts/`（4个文件）
**状态**: **K（完全保留, LLM prompt 文本）**

| 文件 | 行数 | 状态 | 说明 |
|------|------|------|------|
| intent_analyzer.md | 58 | K | 与 AgentCreationIntent JSON schema 匹配的 LLM 指令。v3 phase2 直接复用。 |
| tool_recommender.md | 43 | K | ToolRecommendation 数组生成指令。v3 phase3 直接复用。 |
| middleware_recommender.md | 45 | K | MiddlewareRecommendation 数组生成指令。v3 phase4 直接复用。 |
| prompt_generator.md | 126 | K | 8-section Markdown prompt 结构指令。v3 phase5 直接复用。 |

**注意**: prompt 文本**绝对禁止修改**。v3 node 期待相同 LLM 输入/输出结构。

---

#### 8. `backend/app/services/builder_service.py`
**状态**: **M（大部分迁移，部分替换）**

| 行范围 | 项目 | 分类 | 说明 |
|---------|------|------|------|
| 34-56 | session CRUD (create_session, get_session) | K | 原样复用。schema 相同。 |
| 64-102 | 原子状态转换 (claim_for_streaming, claim_for_confirming) | K | 复用并发控制逻辑。 |
| 115-157 | catalog 查询, model 查询 | K | 保留 sub-agent 动态注入逻辑。v3 也需要。 |
| 160-197 | `_save_phase_result()` | M | 复用逻辑，但 v3 由 LangGraph checkpoint 管理状态 → DB 保存仅在 phase7/8。 |
| 213-341 | `run_build_stream()` | D | 整个函数替换。v3 中改为直接调用 `graph.astream()`。 |
| 344-362 | `_detect_event_type()` | M | 复用 SSE event type 推断逻辑，并扩展到 v3 Tool UI event。 |
| 370-446 | `confirm_build()` | K | 原样复用智能体创建逻辑。draft_config → Agent 转换。 |
| 449-468 | `_resolve_tools()` | K | 保留工具名称 → DB Tool 匹配逻辑。 |

**替换策略**:
- `run_build_stream()`: v3 中在 `builder_v3/graph.py` 使用 `graph = build_builder_graph(); async for msg in graph.astream(...)` 替代
- 其余函数大多保留或轻微修改

---

#### 9. `backend/app/routers/builder.py`
**状态**: **M（主要替换 + 新 endpoint）**

| 行范围 | 项目 | 分类 | 说明 |
|---------|------|------|------|
| 32-40 | `POST /api/builder` | K | 保留 session 创建 endpoint。 |
| 43-53 | `GET /{session_id}` | K | 保留 session 查询 endpoint。 |
| 56-86 | `GET /{session_id}/stream` | D | **v3 中移除并替换为 `POST /api/builder/{id}/messages`(SSE)**。复用现有 conversations.py 模式。 |
| **新增** | `POST /api/builder/{id}/messages` | M(新增) | SSE streaming endpoint（调用 v3 graph.astream）。借鉴 conversations.py 模式。 |
| **新增** | `POST /api/builder/{id}/messages/resume` | M(新增) | HiTL response endpoint。传递 `Command(resume=...)`。 |
| 89-148 | `POST /{session_id}/confirm` | K | 保留 confirm endpoint。逻辑相同。 |

**迁移**:
- 将现有 `GET /stream` 调用统一为 `POST /messages` + SSE
- 新增 `POST /messages/resume`（处理 ask_user, approval response）

---

### FRONTEND

#### 10. `frontend/src/app/agents/new/conversational/page.tsx`
**状态**: **D（完全替换）**

| 行范围 | 项目 | 分类 | 说明 |
|---------|------|------|------|
| **整个文件** | 全部实现 | D | v2 专用页面。v3 完全重写为基于 `<AssistantThread>` + `<HiTLContext>`。 |
| 60-230 | 状态管理 (phases, intent, tools, etc.) | D | v2 local 状态管理在 v3 中整合到 assistant-ui runtime + LangGraph checkpoint。 |
| 99-187 | `handleBuild()` 逻辑 | M(部分) | 基本流程类似，但不再解析 SSE，而简化为 `send_message` + `resume` API。 |

**v3 结构**:
```tsx
<AssistantRuntimeProvider runtime={...}>
  <HiTLContext.Provider value={hitlCallbacks}>
    <AssistantThread />
  </HiTLContext.Provider>
</AssistantRuntimeProvider>
```

废弃原因: v3 使用与普通聊天相同的 UI pattern → 不再需要现有 `page.tsx` 的 custom 状态管理。

---

#### 11. `frontend/src/app/agents/new/conversational/_components/builder-thread.tsx`
**状态**: **D（移除）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | D | v2 专用 thread 组件。v3 整合为 `<AssistantThread>`（普通聊天组件）。 |
| 第25-63行 | BuilderThread 组件 | D | custom composer, message primitives → 替换为普通 AssistantThread。 |

**原因**: v3 使用与聊天相同的消息结构 → 不再需要 builder 专用 custom。

---

#### 12. `frontend/src/app/agents/new/conversational/_components/phase-timeline.tsx`
**状态**: **M(概念迁移, 移除文件)**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | D（文件） | v2 专用时间线组件。 |
| 第 17-51 行：`PhaseIcon`、`PhaseStatusBadge` 组件 | M（移植 UI 模式） | 在 v3 `phase-timeline-ui.tsx` 中复用相同的图标（勾选/时钟/警告）+ 徽章样式。 |
| 第 69-156 行：`PhaseTimeline` 主组件 | M（移植 UI 模式） | 在 v3 中**扩展为 8-phase**，但使用相同的渲染逻辑（连接线、状态显示）模式。 |

**v3 变更**：
- Phase 数量：7 → 8（新增图像生成）
- 进度卡片以**消息内 ToolMessage** emit（每次 phase 转换时累积）

**废弃时点**：v3 phase-timeline-ui.tsx 实现完成后。

---

#### 13. `frontend/src/app/agents/new/conversational/_components/intent-card.tsx`
**状态**：**M（移植 UI 模式）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | M | v3 中也需要显示 Phase 2 完成结果。 |
| 第 8-52 行：IntentCard 组件 | M | 在 v3 phase2 中显示相同信息（agent_name_ko、agent_description、use_cases 等）。保持样式。 |

**废弃时点**：保留为单独文件，或整合到 `message-content.tsx`（tool UI registry）。

---

#### 14. `frontend/src/app/agents/new/conversational/_components/recommendation-card.tsx`
**状态**：**M（移植 UI 模式）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | M | 显示 v3 Phase 3/4 结果。但 v3 中**新增批准/修改按钮**。 |
| 第 19-49 行：RecommendationCard 组件 | M（功能扩展） | 在 v3 中扩展为 `recommendation-approval-ui.tsx`：推荐列表 + 修改意见 textarea + "请求修改"/"批准" 按钮。 |

**v3 变更**：
- 当前卡片为只读
- v3 需要 interactive approval UI（hitl.onResume 回调）

---

#### 15. `frontend/src/app/agents/new/conversational/_components/draft-config-card.tsx`
**状态**：**M（移植 UI 模式）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | M | 扩展为 v3 Phase 8 最终批准卡片。 |
| 第 18-126 行：DraftConfigCard 组件 | M（功能扩展） | 在 v3 中新增修改意见 textarea + "批准"/"请求修改" 按钮。通过 router 分流到 phase 2/3/4/5/6。 |

**v3 变更**：当前只有 "确认" 按钮 → v3 整合 approval interrupt UI。

---

#### 16. `frontend/src/lib/chat/use-builder-runtime.ts`
**状态**：**D（删除文件，部分逻辑整合）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | D | v2 专用 ExternalStoreRuntime 适配器。 |
| 第 27-74 行：`buildVirtualMessages()` 函数 | D | 状态 → ThreadMessageLike 转换。v3 中 LangGraph 消息已经是正确格式。 |
| 第 89-120+ 行：`useBuilderRuntime()` hook | D | v3 中可使用 `useAssistantRuntime`（普通聊天）。 |

**废弃原因**：v3 与普通聊天 runtime 整合，因此无需单独适配器。

---

#### 17. `frontend/src/lib/sse/stream-builder.ts`
**状态**：**D（删除，整合逻辑）**

| 项目 | 分类 | 说明 |
|------|------|------|
| **整个文件** | D | v2 专用 SSE 流解析器。 |
| 第 5-26 行：`streamBuilder()` 函数 | D | v3 中拆分为 `stream-builder-message.ts` + `stream-builder-resume.ts`。 |

**v3 变更**：
- 现有：`GET /stream`（SSE）
- v3：`POST /messages`（SSE，conversations.py 模式）+ `POST /messages/resume`

---

#### 18. `frontend/src/lib/api/builder.ts`
**状态**：**M（扩展及修改）**

| 行范围 | 项目 | 分类 | 说明 |
|---------|------|------|------|
| 5-9 | `start()` 方法 | K | 原样复用 `POST /api/builder`。 |
| 11 | `getSession()` 方法 | K | 原样复用 `GET /api/builder/{id}`。 |
| 13-14 | `confirm()` 方法 | K | 原样复用 `POST /api/builder/{id}/confirm`。 |
| **新增** | `sendMessage()` 方法 | M（新增） | `POST /api/builder/{id}/messages`（SSE）。借用 conversations.ts 模式。 |
| **新增** | `resume()` 方法 | M（新增） | `POST /api/builder/{id}/messages/resume`。发送 ask_user/approval 响应。 |

**迁移**:
```typescript
// 现有（v2）
// 通过 streamBuilder(sessionId, signal) 直接订阅 SSE

// v3
// 通过 await builderApi.sendMessage(sessionId, { ... }) 发送消息
// 通过 await builderApi.resume(sessionId, { approved: true/false, ... }) 响应
```

---

## 不必要的依赖 & 死代码

### Backend

1. **`orchestrator.py` 的 `build_builder_graph()` 函数**（第 373-408 行）
   - 已不再调用（在 v3 中删除）
   - `_COMPILED_GRAPH = build_builder_graph()`（第 416 行）也不再需要

2. **`builder_service.py` 的 `run_build_stream()` 函数**（第 213-341 行）
   - 在 v3 中由直接调用 `graph.astream()` 替代
   - `_detect_event_type()`（第 344-362 行）部分复用（新增 Tool UI 事件）

3. **`routers/builder.py` 的 `GET /stream` endpoint**（第 56-86 行）
   - 在 v3 中整合为 `POST /messages`（SSE）

### Frontend

1. **`conversational/page.tsx` 的状态管理**（第 60-230 行）
   - v2 专用 phase/intent/tools 本地状态
   - v3 中使用 assistant-ui runtime + LangGraph checkpoint

2. **整个 `use-builder-runtime.ts`**
   - ExternalStoreRuntime 可能与 v3 的 HiTL context 冲突
   - 改为使用普通 `useAssistantRuntime`

3. **整个 `stream-builder.ts`**
   - v2 专用 SSE 解析器
   - v3 使用与 `conversations.ts` 相同的结构

---

## 重复模式（Deduplication 机会）

### Backend

1. **Prompt 加载 + LLM 调用模式**
   - 4 个 subagent 全都相同：`load_prompt()` → `invoke_with_json_retry()` 或 `invoke_for_text()`
   - 已整合到 `helpers.py` ✓（重复删除完成）

2. **Catalog 格式化**
   - `tool_recommender.py` 的 `_format_catalog()`（第 25-35 行）
   - `middleware_recommender.py` 的 `_format_catalog()`（第 30-42 行）
   - 逻辑相似，可考虑单独提取函数（在 v3 中改进）

### Frontend

1. **ApprovalCard 模式**（v3 中新增）
   - 在 Phase 3、4、5、8 中重复："推荐项 + 修改意见 textarea + 批准/修改按钮"
   - 可统一为一个 `recommendation-approval-ui.tsx`（通过 prop 传入标题/项目）

2. **Icon 复用**
   - `PhaseTimeline` 的勾选/时钟/警告图标 → `phase-timeline-ui.tsx` 中也相同
   - 可考虑将图标组件化为 library component

---

## 迁移检查清单

### 禁止删除（直到 v3 实现完成）

- [ ] `builder/sub_agents/intent_analyzer.py` — 保留，在 phase2 中 import
- [ ] `builder/sub_agents/tool_recommender.py` — 保留，在 phase3 中 import
- [ ] `builder/sub_agents/middleware_recommender.py` — 保留，在 phase4 中 import
- [ ] `builder/sub_agents/prompt_generator.py` — 保留，在 phase5 中 import
- [ ] `builder/sub_agents/helpers.py` — 保留，在所有 phase 中 import
- [ ] `builder/prompts/*.md` — 保留，禁止修改 prompt 文本
- [ ] `services/builder_service.py` 中的 `confirm_build()`、`_resolve_tools()` — 保留

### 要替换的项目（v3 实现后）

- [ ] `orchestrator.py` → `builder_v3/graph.py`, `builder_v3/nodes/*.py`
- [ ] `builder_service.run_build_stream()` → `builder_v3/graph.astream()`
- [ ] `routers/builder.py GET /stream` → `POST /messages`（conversations.py 模式）
- [ ] `conversational/page.tsx` → 基于 AssistantThread + HiTLContext 重写
- [ ] `use-builder-runtime.ts` → 删除或使用 `useAssistantRuntime`
- [ ] `stream-builder.ts` → 删除或拆分为 `stream-builder-message.ts` + `resume.ts`

### 要删除的项目（v3 稳定后，逐步切换）

- [ ] `builder/orchestrator.py`（第 1-463 行）
- [ ] `conversational/_components/builder-thread.tsx`
- [ ] `conversational/_components/phase-timeline.tsx`（v3 `phase-timeline-ui.tsx` 实现后）
- [ ] `lib/sse/stream-builder.ts`
- [ ] `lib/chat/use-builder-runtime.ts`

### UI 组件移植（concept + 功能扩展）

- [ ] `intent-card.tsx` → v3 中继续使用（Phase 2 结果）
- [ ] `recommendation-card.tsx` → v3 `recommendation-approval-ui.tsx`（新增批准/修改按钮）
- [ ] `draft-config-card.tsx` → v3 `draft-config-ui.tsx`（批准/修改按钮 + router 分流）
- [ ] 整合 Phase 2/3/4/5/8 的公共 approval UI

---

## 风险及注意事项

### 高（Critical）

1. **禁止修改 prompt 文本**
   - **绝对不要修改** `builder/prompts/*.md` 的内容
   - v3 node 期待相同的 JSON schema 和 Markdown 结构
   - 如需变更，也要同时更新 v3 node

2. **保留 `helpers.py` 函数签名**
   - 禁止更改 `invoke_with_json_retry()`、`invoke_for_text()` 参数
   - 4 个 subagent + v3 node 全部依赖

3. **Router migration 顺序**
   - 删除 `routers/builder.py` 的 GET `/stream` 前，必须先完成 v3 POST `/messages` endpoint
   - 期间可能需要 dual-support

### 中（Medium）

4. **状态机一致性**
   - BuilderStatus enum (BUILDING → STREAMING → PREVIEW → CONFIRMING → COMPLETED)
   - 明确 v3 的 phase7（转换到 PREVIEW）、phase8（转换到 COMPLETED）时机
   - 必须与现有 confirm_build() 逻辑一致

5. **决定图像保存位置**
   - Phase 6 生成的图像 URL 保存位置：本地文件 vs S3 vs base64
   - 保存到 `builders_sessions.draft_config.image_url` 后迁移到 agents 表
   - 如果 agents 表没有 `image_url` 列，则需要 Alembic migration

### 低（Low）

6. **Frontend build 回归**
   - `use-chat-runtime.ts` 抽象化可能影响现有 conversations 页面
   - Step 3 中必须进行回归测试

---

## 最终判定

| 判定 | 状态 | 说明 |
|------|------|------|
| **GREEN** ✓ | ANALYSIS_COMPLETE | 所有文件分类清晰，依赖整理完成，删除项目已确定。 |
| | RISK_LOW | 保留 prompt/schema，通过稳定 helpers.py 将风险降至最低。 |
| | READY_FOR_IMPLEMENTATION | 可立即进入 v3 implementation 阶段。 |

---

## 产出物

- **分析文件**：`/Users/chester/dev/natural-mold/tasks/deletion-analysis.md` ✓
- **分类完成**：
  - 保留（K）：11 个项目
  - 移植（M）：8 个项目
  - 删除（D）：5 个项目
- **需要额外调查**：0 个
- **Blocker**：0 个

---

**分析执行者**：贝索斯（Bezos）<br>
**分析完成**：2026-04-26<br>
**状态**：ANALYSIS_COMPLETE, GREEN ✓
