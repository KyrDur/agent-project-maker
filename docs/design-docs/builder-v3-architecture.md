# ADR-001: Builder v3 LangGraph StateGraph 8-Phase 架构

**状态**：提议中<br>
**作者**：Pichai (Architecture DRI)<br>
**日期**：2026-04-26<br>
**影响范围**：`backend/app/agent_runtime/builder_v3/`, `frontend/src/app/agents/new/conversational/`, 路由器/服务

---

## 背景

### 当前情况 (Builder v2)

- **独立系统**：Builder 不使用 `executor.py`/`create_deep_agent()`，而是通过自有 `orchestrator.py` 流水线 + `invoke_with_json_retry()` 逻辑运行
- **HiTL 未实现**：即使用户选择“向用户提问”，后端仍直接接收结果并进入下一 phase
- **UI 分离**：使用自有 `PhaseTimeline` + 卡片，无消息历史
- **用户报告的两个 Bug**：
  1. 看不到阶段推进 → 事件被 push 到同一数组中，几乎同时到达
  2. 明明向用户反问却直接通过 → 根本没有调用 interrupt

### 根本原因

两个问题都源于**未集成聊天基础设施（HiTL、SSE、checkpointer）**。<br>
现有聊天已经通过 `interrupt()`/`Command(resume=...)`/checkpointer 完整运行，但 Builder 的自有实现绕开了这些机制。

### 解决方案的必要性

- **实现 HiTL**：各 phase（尤其 3/4/5/6/8）需要审批/修改请求循环
- **集成聊天 UI**：可复用现有 `assistant-thread.tsx` → 统一 UX，便于维护
- **进度可见性**：每次 phase 切换时在消息中 emit 卡片 → 与 mockup 图片对齐
- **强制顺序**：通过图拓扑在代码层保证 phase 顺序（LLM 无法违背）

---

## 决定

### 1. 技术选择：StateGraph（而非 ReAct）

| 标准 | ReAct (create_deep_agent) | StateGraph |
|------|--------------------------|-----------|
| **强制顺序** | LLM 选择工具 → 可能偏离 | 通过图边强制拓扑顺序 |
| **HiTL** | 支持 | 支持 |
| **Checkpoint** | 支持 | 支持 |
| **Interrupt 恢复** | 支持 | 支持 |
| **8-phase 保证** | X（LLM 可能跳过） | O（必须经过所有节点） |

**选择**：**StateGraph** — 为保证 mockup 图片中的严格推进顺序

### 2. 8-Phase 结构

```
[START]
  ↓
Phase 1：项目初始化（自动，无需 LLM）
  ↓
Phase 2：用户意图分析（ask_user 循环 — 名称/描述不足时）
  ↓
Phase 3：工具推荐（approval/revision 循环）
  ↓
Phase 4：中间件推荐（approval/revision 循环）
  ↓
Phase 5：编写系统提示词（approval/revision 循环）
  ↓
Phase 6：生成 Agent 图片（skip/generate，重新生成循环）
  ↓
Phase 7：保存设置（自动，切换至 PREVIEW）
  ↓
Phase 8：最终审批（approval → 修改时通过 router 跳转至 phase 2~6）
  ↓
[END]
```

**现有 7-phase vs 新 8-phase**：
- Phase 1~5：与现有相同（但新增 HiTL）
- Phase 6：**新增** — 生成 Agent 图片（nano-banana 或 OpenAI Image API）
- Phase 7~8：将现有 Phase 6~7 重新编号为 Phase 7~8

### 3. BuilderState TypedDict 签名

```python
from langchain_core.messages import BaseMessage, add_messages
from typing_extensions import Annotated, TypedDict

class BuilderState(TypedDict):
    """LangGraph StateGraph 的状态容器。"""
<br>
    # 消息历史（与现有聊天相同）
    messages: Annotated[list[BaseMessage], add_messages]
<br>
    # 各 Phase 中间结果
    user_request: str                           # 初始用户输入
    intent: dict | None                         # Phase 2: AgentCreationIntent
    tools: list[dict] | None                    # Phase 3: [{"name": "...", "description": "..."}, ...]
    middlewares: list[dict] | None              # Phase 4: [{"type": "...", "config": {...}}, ...]
    system_prompt: str | None                   # Phase 5：提示词文本
    image_url: str | None                       # Phase 6: "https://... or /api/agents/.../image.png"
    draft_config: dict | None                   # Phase 7：最终 Agent 设置（name, description, tools, etc.）
<br>
    # 进度
    todos: list[PhaseTodo]                      # 8个 phase 的进度（每个节点 emit）
    current_phase: int                          # 当前 phase（1~8），仅供参考
<br>
    # 用于 HiTL/重试
    last_revision_message: str | None           # Phase 3/4/5/6 修改请求时传给 LLM
    last_approved_data: dict | None             # Phase 3/4/5 之前已批准的数据（重试上下文）

class PhaseTodo(TypedDict):
    """进度卡片条目。"""
    phase_id: int                               # 1~8
    phase_name: str                             # "意图分析", "工具推荐", ...
    status: Literal["pending", "in_progress", "completed"]
    description: str                            # 选项、结果摘要
```

### 4. 8个节点签名

每个 phase 作为独立模块（`nodes/phase{1..8}.py`）实现：

```python
# 基础签名 — 所有节点均采用此模式
async def phase_X(state: BuilderState) -> dict | Command:
    """
    执行 Phase X 逻辑。
<br>
    1. emit 进入消息（AIMessage）
    2. update 进度卡片
    3. 执行任务（LLM call, interrupt, etc.）
    4. emit 完成消息
    5. 更新 State 后 return
<br>
    注意：节点函数必须是 idempotent（interrupt 后 resume 时会重新进入）
    """
```

#### Phase 1：项目初始化

```python
async def phase1_init(state: BuilderState) -> dict:
    """
    - 进入消息："现在开始初始化项目"
    - 更新进度：将 phase 1 设为 in_progress
    - 任务：创建目录/文件，更新 builder_session
    - 完成消息："[Phase 1 完成] 项目已初始化"
    - Return：部分更新 state（project_path, etc.）
    """
```

#### Phase 2：用户意图分析（ask_user 循环）

```python
async def phase2_intent(state: BuilderState) -> dict | Command:
    """
    - 进入消息
    - 意图分析 LLM call（使用 invoke_with_json_retry）
    - 提取 AgentCreationIntent：{name, description, ...}
    - 检查缺失项：
      - 若不足：interrupt({"type": "ask_user", "question": "名称？", "options": [...]})
      - LLM 生成 3-4 个选项 + "直接输入" fallback
    - 用 resume 响应更新 state.intent，重新检查循环
    - 重复直到全部补全（节点内部 while 循环）
    - 完成消息："[Phase 2 完成] 意图分析完成：名称={name}"
    """
```

#### Phase 3/4/5：推荐/生成 + 审批/修改循环

```python
async def phase3_tools(state: BuilderState) -> dict | Command:
    """
    - 进入消息
    - 工具推荐 LLM call（迁移现有 sub_agent）
    - emit 结果卡片（ToolMessage with tool_name="recommendation-approval"）
    - 审批 interrupt：interrupt({
        "type": "approval",
        "data": {"tools": [...]},
        "summary": "推荐4个工具：...",
        "allow_revision": True
      })
    - 分类 resume 响应：
      - {"approved": True}：进入下一 phase
      - {"approved": False, "revision_message": "..."}: 
        * 更新 state.last_revision_message
        * 在同一 phase 内重新执行（while 循环）
        * 向 LLM 传入之前结果 + revision_message 后重新生成
        * emit 新结果卡片后再次 interrupt
    - 重复直到批准
    - 完成消息："[Phase 3 完成] 工具推荐完成"
    """
<br>
    # Phase 4、5 也采用相同模式（generate → card → interrupt → revise loop）
```

#### Phase 6：生成 Agent 图片（新增）

```python
async def phase6_image(state: BuilderState) -> dict | Command:
    """
    - 进入消息："现在开始生成 Agent 图片"
    - 生成 auto_prompt：LLM 基于 intent/name/description 自动生成图片提示词
<br>
    - 第1次 interrupt（选择 skip/generate）：
      interrupt({
        "type": "choice",
        "title": "是否生成 Agent 图片？",
        "options": ["跳过", "生成"],
        "context": {"auto_prompt": "..."}
      })
<br>
    - resume 响应：{"choice": "skip"} or {"choice": "generate"}
<br>
    - "skip" → state.image_url=None → 下一 phase
    - "generate":
      * 调用 image_gen.py → 使用 nano-banana 生成图片（60s timeout）
      * 生成失败时：向用户提供 fallback（"重试" or "跳过"）
      * 保存图片：backend/uploads/agent_images/{builder_session_id}.png
      * emit 预览：ToolMessage with tool_name="image-generation-preview"
<br>
      * 第2次 interrupt（确认/重新生成/跳过）：
        interrupt({
          "type": "approval",
          "data": {"image_url": "...", "prompt": "..."},
          "options": ["确认", "重新生成", "跳过"],
          "allow_prompt_edit": True
        })
<br>
      * resume 响应：
        - {"choice": "confirm"} → 保存 state.image_url → 下一 phase
        - {"choice": "regenerate", "extra": {"prompt_edit": "..."}} → 再次生成（循环）
        - {"choice": "skip"} → state.image_url=None → 下一 phase
<br>
    - 完成消息："[Phase 6 完成] 图片生成完成"（或 "已跳过"）
    """
```

#### Phase 7：保存设置

```python
async def phase7_save(state: BuilderState) -> dict:
    """
    - 组装 draft_config：
      {
        "name": state.intent["agent_name"],
        "description": state.intent["agent_description"],
        "tools": state.tools,
        "middlewares": state.middlewares,
        "system_prompt": state.system_prompt,
        "image_url": state.image_url,
        ...
      }
    - 更新 builder_session：status=PREVIEW, draft_config=...
    - 完成消息："[Phase 7 完成] 设置已保存"
    """
```

#### Phase 8：最终审批 + 构建

```python
async def phase8_build(state: BuilderState) -> dict | Command:
    """
    - emit DraftConfigCard ToolMessage（显示全部设置）
    - interrupt({
        "type": "approval",
        "data": state.draft_config,
        "summary": "已准备好创建 Agent",
        "allow_revision": True
      })
<br>
    - resume 响应：
      - {"approved": True}:
        * builder_session.status = COMPLETED
        * 实际创建 Agent（或委托给 confirm 端点）
        * 完成消息："[Phase 8 完成] Agent 创建完成"
        * return {}  → END
<br>
      - {"approved": False, "revision_message": "..."}:
        * 分支到 router 节点
    """
```

#### Router：分类 Phase 8 修改请求

```python
async def router(state: BuilderState) -> str:
    """
    当用户在 Phase 8 请求修改时，通过分类 LLM 决定返回哪个 phase
    。
<br>
    - 使用 LLM 分类 revision_message（结构化输出，Pydantic enum）
    - 分类目标："phase2" | "phase3" | "phase4" | "phase5" | "phase6"
    - 若含糊：ask_user fallback（"您想修改哪个阶段？" + 选项）
    - return：对应 phase 名称（如 "phase3"）
<br>
    Phase 8 → router →（条件分支）→ 重新进入 phase 2/3/4/5/6 → ... → 再次到达 phase 8
    """
```

### 5. Interrupt Payload 契约（3种）

#### ask_user

```python
# 在 Node 中 emit：
interrupt({
    "type": "ask_user",
    "question": str,          # "Agent 名称是什么？"
    "options": list[str]      # ["网页搜索", "数据分析", "直接输入"]
})

# 前端 UI：user-input-ui.tsx（保持现有）
# 用户响应：
"网页搜索"  # or 直接输入的文本
```

#### approval (Phase 3/4/5/6/8)

```python
# 在 Node 中 emit：
interrupt({
    "type": "approval",
    "data": dict,             # 审批对象数据（tools, prompt, image_url, draft_config, etc.）
    "summary": str,           # 摘要文本
    "allow_revision": bool    # True 时启用 "修改意见" textarea
})

# 前端 UI：
#   - Phase 3/4: recommendation-approval-ui（推荐项 + textarea + 修改/批准按钮）
#   - Phase 5: prompt-approval-ui（提示词 + textarea + 修改/批准按钮）
#   - Phase 6: image-generation-ui 两阶段（图片 +（可选）prompt textarea + 确认/重新生成/跳过）
#   - Phase 8: draft-config-ui（全部设置 + textarea + 修改/批准按钮）

# 用户响应：
{"approved": True}
# 或
{"approved": False, "revision_message": "..."}
```

#### choice（Phase 6 第1阶段）

```python
# 在 Node 中 emit：
interrupt({
    "type": "choice",
    "title": str,             # "是否生成 Agent 图片？"
    "options": list[str],     # ["跳过", "生成"]
    "context": dict           # {"auto_prompt": "..."} 等
})

# 前端 UI：image-generation-ui 第1阶段（auto_prompt 预览 + 2个按钮）

# 用户响应：
{"choice": "skip"} or {"choice": "generate"}
# 或（Phase 6 第2阶段）：
{"choice": "confirm"} or {"choice": "regenerate", "extra": {"prompt_edit": "..."}} or {"choice": "skip"}
```

### 6. Resume Payload 契约

Resume 通过前端的 `useHiTL().onResume(payload)` → `/api/builder/{id}/messages/resume` POST 端点传递：

```python
# ask_user 响应：
str  # e.g., "网页搜索Agent"（选项或直接输入）

# approval 响应：
{"approved": bool, "revision_message": str | None}

# choice 响应：
{"choice": str, "extra": dict | None}  # extra 在 regenerate 时可包含 prompt_edit
```

### 7. SSE 事件格式（兼容现有 streaming.py）

在 NoCodeGraph 节点函数中更新 `state["messages"]` → 现有 `streaming.py` 的 `stream_agent_response` 函数原样处理：

| 事件 | Payload | 用途 |
|--------|----------|------|
| `message_start` | `{"id": "...", "role": "assistant"}` | 消息开始 |
| `content_delta` | `{"delta": "文本"}` | 流式文本 |
| `tool_call_start` | `{"tool_name": "...", "parameters": {...}}` | 工具调用开始 |
| `tool_call_result` | `{"tool_name": "...", "result": "..."}` | 工具结果 |
| `interrupt` | `{"interrupt_id": "...", "value": {...}}` | 检测 HiTL interrupt |
| `message_end` | `{"usage": {...}, "content": "..."}` | 消息结束 |
| `error` | `{"message": "..."}` | 发生错误 |

**与现有 streaming.py 的兼容性**：
- 在 StateGraph 节点中将消息添加到 `state["messages"]` 列表 → `add_messages` 自动合并
- `agent.astream(input, config, stream_mode="messages")` → 与现有方式相同地转换为 SSE 事件
- interrupt 检测也沿用 `agent.aget_state()` → `state.tasks[].interrupts[]` 相同逻辑

### 8. 图片生成基础设施

#### Provider 选择

```python
# backend/app/agent_runtime/builder_v3/image_gen.py

class ImageProvider(str, Enum):
    NANOBANAN = "nanobanan"         # Gemini Flash Image（推荐，快速）
    OPENAI = "openai"               # OpenAI DALL-E 3（高质量，较慢）
    GOOGLE = "google"               # Google Imagen 2

# 通过环境变量选择：
# BUILDER_IMAGE_PROVIDER=nanobanan（默认值）
# BUILDER_IMAGE_PROVIDER=openai（fallback）

async def generate_image(
    prompt: str,
    provider: ImageProvider = ImageProvider.NANOBANAN,
    fallback_provider: ImageProvider | None = ImageProvider.OPENAI,
    timeout: int = 60
) -> str | None:
    """
    生成并保存图片。
<br>
    Return：已保存图片的可访问 URL（或 base64）
    Timeout 超时/失败时：返回 None（由调用方展示 fallback UI）
    """
```

#### 保存策略

- **路径**：`backend/uploads/agent_images/{builder_session_id}.png`
- **URL 格式**：`/api/builders/{builder_session_id}/image`（代理端点）或直接 URL
- **选择理由**：
  - PoC 阶段使用本地保存（之后易于迁移到 S3）
  - 创建 Agent 时保存到 `agents.image_url` 列（已确认该列存在）
  - 比 Base64 URL 占用更少内存

### 9. 路由端点契约

#### 新增/变更端点

**现有**：
- `GET /api/builder` — 查询会话
- `GET /api/builder/{id}/stream` — 启动 SSE 流（当前）
- `POST /api/builder/{id}/confirm` — draft_config → 创建 Agent

**变更**：
```
POST /api/builder
  Request: {"user_request": "..."}
  Response: {"session_id": "...", "user_id": "..."}
  → 创建会话，StateGraph 自动启动（首条消息 SSE 流）

POST /api/builder/{id}/messages  （替代现有 /stream）
  Request: {"user_request": "..."}（首条消息，可选）
  Response: SSE（streaming.py 保持原样）
  → 调用 StateGraph.astream()，使用 checkpointer

POST /api/builder/{id}/messages/resume
  Request: {"response": ...}  （ask_user/approval/choice 响应）
  Response: SSE（streaming.py 保持原样）
  → 传入 Command(resume=response)，从中断节点继续

POST /api/builder/{id}/confirm
  Request: {}（draft_config 已在 Phase 7 保存）
  Response: {"agent_id": "..."}
  → Phase 8 完成后返回 agent_id（已创建）
```

### 10. 数据模型（最小化 DB 变更）

**保持现有**：
- `builder_sessions` 表：status、draft_config 等元数据（最小变更）
- `agents.image_url` 列已存在（无需迁移）

**新增使用**：
- LangGraph checkpoint 表（`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`）
  - `thread_id = builder_session_id` 映射
  - 使用 `get_checkpointer()` 函数（与现有聊天相同）

**Status 状态机**：
```
[BUILDING]（创建会话）
    ↓
[STREAMING]（Phase 1~7 进行中）
    ↓
[PREVIEW]（到达 Phase 7，保存 draft_config）
    ↓
[CONFIRMING]（到达 Phase 8，等待最终审批）
    ↓
[COMPLETED]（Agent 创建完成）
    ↓
（或错误时为 [FAILED]）
```

---

## 替代方案

### 备选方案 A：保留现有 v2 + 只添加 HiTL

**优点**：改动最小<br>
**缺点**：
- 无法强制顺序（orchestrator.py 的 7-phase 循环无法控制 LLM）
- 难以统一 SSE 事件格式（需要单独的自定义流）
- 添加图片生成阶段复杂（将 orchist.py 扩展为 8-phase，又需要另一套自定义）

**结论**：不采用

### 备选方案 B：ReAct（使用 create_deep_agent）

**优点**：复用现有 executor.py，可立即使用 HiTL<br>
**缺点**：
- LLM 选择工具 → 可能跳过 Phase 顺序
- 无法保证 mockup 图片中的“严格 8-phase”
- 各 phase 内 ask_user 循环也由 LLM 决定 → 不可预测

**结论**：不采用

### 备选方案 C：StateGraph（选定方案）

**优点**：
- 通过图拓扑强制 8-phase 顺序
- 完整支持 HiTL、checkpointer
- 可复用 SSE streaming.py
- 各节点内部 approve 循环可通过显式 while 控制

**缺点**：需要新增实现（预计约 1200 行）

**结论**：**采用** — 优先考虑结构健壮性和 UX

---

## 结果

### 实现影响

| 范围 | 变更 | 原因 |
|------|------|------|
| **Backend** | 新增 `builder_v3/` 模块 1200 行 | StateGraph 8-phase 节点 + 路由集成 |
| **Frontend** | 新增 5 个 Tool UI + 复用 `assistant-thread` | 匹配 mockup 图片 UI + 集成 HiTL |
| **Router** | 新增 `/messages`, `/messages/resume` | SSE + resume 端点 |
| **Service** | 移除 `run_build_stream()` → 改为 `graph.astream()` | 简化结构 |
| **DB** | 无变更（或最小） | 仅新增使用 checkpoint 表 |

### 废弃对象

- `backend/app/agent_runtime/builder/orchestrator.py`（v2 流水线）
- `frontend/src/app/agents/new/conversational/_components/builder-thread.tsx`
- `frontend/src/app/agents/new/conversational/_components/phase-timeline.tsx`
- `frontend/src/lib/chat/use-builder-runtime.ts`
- `frontend/src/lib/sse/stream-builder.ts`

### 迁移路径

1. **Step 1**：完成 `builder_v3/` 实现（含测试）
2. **Step 2**：替换路由 + 验证 `streaming.py` 兼容性
3. **Step 3**：实现前端 Tool UI
4. **Step 4**：替换页面并进行回归测试
5. **Step 5**：废弃现有文件

---

## 接口契约

### BuilderState ↔ 节点

每个节点以 `BuilderState` 为输入，返回更新后的 state dict 或 `Command(resume=...)`：

```python
async def phase_X(state: BuilderState) -> dict | Command:
    # 输入：前一节点的 state（包含所有之前结果）
    # 输出：{"intent": {...}, "messages": [...]}
    #      或 Command(resume=payload) — 处理 interrupt 时
```

### 节点 ↔ SSE

节点调用 `state["messages"].append(AIMessage(...))`：
- `streaming.py` 的 `stream_agent_response()` 函数自动转换为 SSE 事件
- 与现有聊天逻辑 100% 相同

### 节点 ↔ Interrupt

节点调用 `interrupt(payload)`：
- LangGraph 暂停 execution
- `streaming.py` 执行 `aget_state()` → 提取 `state.tasks[].interrupts[]` → emit SSE `interrupt` 事件
- 前端执行 `HiTLContext.onResume()` → POST `/messages/resume`
- 后端传入 `Command(resume=response)`
- 从同一节点继续

---

## 验证策略

### 单元测试

```bash
# backend/tests/test_builder_v3_graph.py
# 各节点独立测试，使用 mock state
# 例如：phase3_tools 中 tools=None → 确认生成 tools
```

### 集成测试

```bash
# 图可达性：到达 Phase 8 时是否经过 1~7
# 各 interrupt 前后 state 一致性
# 验证 Phase 8 router → 重新进入 phase 3 → 再次到达 phase 8
```

### E2E 验证（浏览器）

1. **基本流程**（复现 mockup 图片）
   - Phase 1~8 依次推进
   - 每个 phase 卡片在消息中累积显示
2. **审批/修改循环**
   - 在 Phase 3 输入 "修改意见" → 同一 phase 重新执行 → 显示新推荐
3. **Phase 6 skip/generate**
   - "跳过" → image_url=None
   - "生成" → 生成图片 → 预览 → 确认/重新生成/跳过
4. **Phase 8 router**
   - 在 Phase 8 输入 "移除工具" → 跳转到 phase3_tools → 重新走流程
5. **现有聊天回归**
   - `/agents/[id]/conversations/[cid]` 正常运行

---

## 风险及缓解措施

| 风险 | 影响 | 缓解措施 |
|--------|------|--------|
| **Router 分类错误** | Phase 8 跳转到错误 phase | 结构化输出（Pydantic enum）+ ask_user fallback |
| **Interrupt resume idempotency** | 重新进入时重复 LLM call | 节点函数设计为基于 state 的条件执行 |
| **图片生成 timeout** | 超过 60s → 用户体验下降 | fallback UI（"重试" or "skip"）+ 考虑异步后处理 |
| **use-chat-runtime 抽象** | 现有 conversations 页面损坏 | Step 3 必须进行回归测试 |
| **builder_session 状态机** | PREVIEW ↔ STREAMING 不一致 | 进入 Phase 7 时显式状态切换 |
| **Checkpoint 存储负载** | 多次 phase 重试 → DB 增长 | 考虑会话检查/清理批处理 job |

---

## 参考

- **现有资产**：executor.py、streaming.py、ask_user.py、sub_agents/*.py 均原样复用
- **基础设施**：使用现有函数 `get_checkpointer()`、`invoke_with_json_retry`、`stream_agent_response`
- **计划**：`/Users/chester/.claude/plans/kind-squishing-shore.md`
- **Progress**：`/Users/chester/dev/natural-mold/progress.txt`（实时记录技术决策）
- **Mockup 图片**：参考计划文档图片 1~4（8-phase、进度卡片、审批 UI、图片生成）

---

## ADR 审批检查清单

- [ ] Pichai：验证技术架构决策（本人）
- [ ] Jensen：验证 API 契约（`BuilderState` → 端点映射）
- [ ] Zuckerberg：验证前端 Tool UI 契约（interrupt payload ↔ React 状态）
- [ ] Bezos：整理测试策略 / 废弃对象

