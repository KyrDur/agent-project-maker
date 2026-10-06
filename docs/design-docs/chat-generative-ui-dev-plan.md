# 聊天 Generative UI — 开发规划文档（已准备实现）

> 本文档以“仅凭这一份文档即可从头到尾实现”为目标编写，包含假设/依据/文件位置/代码 skeleton/验证流程。需要推测的地方先通过**验证 spike**确认。

- **状态**：设计已确定，尚未实现
- **目标 runtime**：v3 聊天（`langgraph_v3`, `use-moldy-langgraph-stream.ts` + `useExternalStoreRuntime`）
- **assistant-ui**：0.14.18（无需升级 — 依据见 §2.3）
- **相关先例文档**：`docs/design-docs/chat-attachments-dev-plan.md`（原样沿用 commit 拆分·验证·throwaway E2E stack 模式）

---

## 0. TL;DR

1. **目标**：将 AI 工具结果从“字符串/JSON pretty-print”改为按**类型渲染 React 组件**（DataTable/Chart/StatsDisplay/Terminal …）。这是 assistant-ui 所说的 **"LangGraph Generative UI" 的 Moldy 原生实现** — 后端 push `{type, props}` typed payload，前端通过 **allowlist registry + Zod 验证**选择组件。
2. **为什么是“原生实现”**：Moldy 不使用 assistant-ui 的 LangGraph **Cloud** runtime（`@assistant-ui/react-langgraph` / `useLangGraphRuntime`），而是使用**自有 SSE agent-protocol + `useExternalStoreRuntime`**（§1）。因此不能原样使用 LangGraph Cloud 的 `push_ui_message`/`custom` channel 路径，而是把**相同概念加入 Moldy protocol**。但渲染使用 assistant-ui 0.14.18 已存在的 **`makeAssistantDataUI` data-part API**。
3. **传输机制完全复制 FILE_EVENT（artifact）先例** — 已验证的“后端 typed 事件 → 前端 custom channel 消费 → store → 附加到消息 → 渲染”流水线（§3）。
4. **顺序（用户要求）**：
   - **Phase 1**：只建设 Generative UI **基础设施**（传输契约 + 1个 demo 类型）→ 通过真实服务器 + 分页面截图证明**回归 0** → 然后才能添加组件。
   - **Phase 2**：DataTable → Chart → StatsDisplay → Terminal **逐个**添加，每一步都进行测试 + 截图。
5. **范围外**：全面切换 payload-type（所有工具结果契约化）、assistant-ui toolkit 迁移、升级到 0.14.24。本文档是**增量式(additive)**，不改动现有 tool-ui（`makeAssistantToolUI`）渲染。

---

## 1. 背景：Moldy 为什么使用自有 runtime（已确认事实）

- 前端 v3 runtime 由 `frontend/src/lib/chat/langgraph-runtime/use-moldy-langgraph-stream.ts:2798` 的 **`useExternalStoreRuntime`** 创建。`@assistant-ui/react-langgraph` **不在依赖中**（package.json 只有 `@assistant-ui/react`, `@assistant-ui/react-langchain`）。代码里的 `useLangGraphRuntime` 标识符只是**boolean flag**，并非 assistant-ui hook。
- 后端由约 25 个 `backend/app/routers/conversation_agent_protocol_*.py` 构成的**自有 agent-protocol over SSE**（commands/event_normalization/thread_stream/resume/redaction/state_snapshot …）。不是 LangGraph Cloud/Platform 部署，而是使用 **FastAPI + deepagents library**。
- **结论**：“切换到正式 LangGraph runtime”属于产品重设计级别（需重新接线多用户认证·credential·MCP·skill·market·SSE resume·branch·redaction），不在范围内。只在 Moldy protocol 中实现 **Generative UI 概念**。→ 本文档。

---

## 2. 核心设计决策

### 2.1 传输：custom SSE 事件（复制 FILE_EVENT 模式）

后端 emit `moldy.ui_data` **custom SSE 事件**。它是不会改动消息正文（LangChain content）的**side-channel**，因此不会与 LLM/deepagents 消息转换冲突。这是 artifact（FILE_EVENT）已经使用的验证路径。

Payload（示例）：
```json
{
  "schema_version": 1,
  "type": "data_table",
  "message_id": "019f0d8e-...",
  "run_id": "...",
  "tool_call_id": "call_abc",
  "props": { "columns": [...], "rows": [...] }
}
```

### 2.2 渲染：allowlist registry + Zod 验证 + fail-safe

前端通过 `type → React 组件` **registry（allowlist）**选择组件。使用 **Zod 验证 props**，**未知 type/验证失败时安全 fallback**（跳过渲染或显示“预览不支持”chip）。这与用户参考的 tool-ui.com 的“payload type → component，匹配则渲染，否则安全失败”模型相同。

### 2.3 assistant-ui data-part API 在 0.14.18 中已存在（无需升级）

`frontend/node_modules/@assistant-ui/react/dist/index.d.ts` 中以下内容**已 export**：
`makeAssistantDataUI`, `useAssistantDataUI`, `useMessagePartData`, `DataMessagePart`, `DataMessagePartComponent`, `AssistantDataUI`, `DataRenderers`.

此外，v3 渲染 switch `frontend/src/components/chat/assistant-thread.tsx:299-328` 中**已经有 `case 'data'` 分支**并渲染 `leaf.dataRendererUI`。`AssistantThread` 接受 `dataUI?: readonly AssistantDataUI[]` prop（文件内约 742, 1013-1015）。

> **决策**：渲染使用 `makeAssistantDataUI` registry。但“custom 事件 → data **part**”桥接是否足够干净，要先通过 §4 spike 验证；如果不干净，则 fallback 到**内联卡片渲染**（artifact `AssistantArtifactCards` 模式，复用同一 registry）。两条路径共享同一 registry/Zod，因此 fallback 成本很低。

---

## 3. FILE_EVENT（artifact）先例 — 可原样复制的流水线（依据）

### 3.1 后端 emit (streaming.py)

- `emit(event, data)` 闭包：`backend/app/agent_runtime/streaming.py:309-341` — `seq` 递增，并传播到 `format_sse`、broker/persist。
- 事件名常量：`backend/app/agent_runtime/event_names.py`（MESSAGE_START/CONTENT_DELTA/MESSAGE_END/TOOL_CALL_START/TOOL_CALL_RESULT/**FILE_EVENT**/`moldy.compaction`/MEMORY_*/STALE）。
- 工具结果之后立即 emit artifact：`streaming.py:520-547`
  ```python
  if msg.type == "tool":
      ...
      yield emit(event_names.TOOL_CALL_RESULT, result_payload)
      if artifact_recorder is not None:
          artifact_events = await artifact_recorder.collect_after_tool_result(...)
          for payload in artifact_events:
              yield emit(event_names.FILE_EVENT, payload)   # ← 先例 emit
  ```
- 工具结果 → 副作用事件模式：`backend/app/agent_runtime/memory_event_projection.py::memory_event_from_tool_result`（将工具结果字符串解析为 JSON 后投影为事件）。
- custom 事件命名：`moldy.*`（例如 `moldy.compaction`, `moldy.memory_proposed` — 参见 ag_ui_adapter.py）。protocol 转换以 `method="custom"` + namespace **自动通过**（`conversation_agent_protocol_runtime.py:118-149`, `protocol_events.py::_matches_channels`）。**新 custom 事件无需单独注册即可流通。**

### 3.2 前端消费 (artifact-events.ts)

- custom channel 订阅：`frontend/src/lib/chat/langgraph-runtime/artifact-events.ts:199-203`
  ```ts
  useChannelEffect(stream, ARTIFACT_CHANNELS /* ['custom'] */, { replay: true, bufferSize: 300, onEvent: handleEvent })
  ```
- Payload 提取 + type guard：同一文件中的 `protocolArtifactPayload()`（去掉 custom name 的 `moldy.` prefix 后匹配，并验证 shape）。
- Jotai store: `frontend/src/lib/stores/chat-artifacts.ts:48-65` `upsertChatArtifactAtom`.
- 附加到消息：`attachArtifactsToMessages`（准确匹配 assistant_msg_id + 最后一个 assistant 消息 fallback）。
- 内联渲染：`frontend/src/components/chat/assistant-thread.tsx:341-413` `AssistantArtifactCards`。

完整流程：
```
SSE custom:moldy.file_event
  → protocolArtifactPayload()（验证）
  → upsertChatArtifactAtom (Jotai)
  → attachArtifactsToMessages（匹配到消息）
  → AssistantArtifactCards（内联渲染）
```
**我们将为 `ui_data` 1:1 复制此流程。**

---

## 4. Phase 0 — 验证 spike（实现前 0.5~1天，消除猜测）

> 目的：确认“将 custom 事件转换为 assistant-ui **data part** 并通过 `makeAssistantDataUI` 渲染”是否干净可行。如不可行，则确定内联卡片 fallback。

- [ ] **S1**：在 `node_modules` 源码中准确确认 `@assistant-ui/react-langchain` 的 `convertLangChainBaseMessage` 会将何种 content block shape 转换为 `{type:'data', data}` part。（获取 data part 生成 block shape）
- [ ] **S2**：最小 PoC — 向消息注入 1 个硬编码 data part → 使用 `dataUI={[demoDataUI]}`，确认 `makeAssistantDataUI` 能否显示在页面。（无需 script model，用静态消息）
- [ ] **S3**：记录决策 — **路径 A（data part + makeAssistantDataUI）** vs **路径 B（内联卡片 + registry）**。二选一，确定为 §5 正式实现的渲染路径，并回写本文 §2.2。
- **done-when**：用代码确定唯一渲染路径（demo 类型能显示在页面）。无回归（现有聊天正常）。

> 后续 §5/§6 以**已确定的渲染路径**为前提。下方 skeleton 默认以路径 A（推荐）为基准，同时标明路径 B fallback 点。

---

## 5. Phase 1 — Generative UI 基础设施（传输契约 + demo 类型）

> 本阶段产物不是“DataTable/Chart 等实际组件”，而是**end-to-end 管线一条 + demo 类型**。使用 demo 类型（`demo_note`：将文本 props 渲染为方框）只证明流水线。实际组件放到 Phase 2。

### 5.1 后端

**Commit B1 — `feat(chat): ui_data event contract (schema + emit scaffold)`**

- `backend/app/schemas/ui_data.py`（新增）
  ```python
  from __future__ import annotations
  from typing import Any, Literal
  from pydantic import BaseModel

  UIDataType = Literal["demo_note"]  # Phase 2 扩展："data_table"|"chart"|"stats"|"terminal"

  class UIDataEvent(BaseModel):
      schema_version: Literal[1] = 1
      type: UIDataType
      message_id: str | None = None     # 附着目标（与 artifact 相同规则：没有则最后一个 assistant）
      run_id: str | None = None
      tool_call_id: str | None = None
      props: dict[str, Any]             # 各类型验证在前端 Zod +（可选）服务端 per-type model
  ```
- `backend/app/agent_runtime/event_names.py`
  ```python
  UI_DATA_EVENT: Final = "moldy.ui_data"
  ```
- `backend/app/agent_runtime/ui_data_projection.py`（新增，`memory_event_projection.py` 模式）
  ```python
  def ui_data_from_tool_result(tool_name: str, result: str, *, tool_call_id: str | None) -> list[dict]:
      """从工具结果（JSON 字符串）投影 ui_data payload。不适用则返回 []。"""
      if tool_name not in UI_DATA_TOOL_NAMES:   # demo 阶段为空 set → 始终 []（只验证管线）
          return []
      try:
          parsed = json.loads(result)
      except (json.JSONDecodeError, TypeError):
          return []
      if not isinstance(parsed, dict) or "ui_type" not in parsed:
          return []
      return [UIDataEvent(
          type=parsed["ui_type"], tool_call_id=tool_call_id,
          props={k: v for k, v in parsed.items() if k != "ui_type"},
      ).model_dump(mode="json")]
  ```
- `backend/app/agent_runtime/streaming.py:~548`（紧接 FILE_EVENT block 之后，与 memory_event block 并列）
  ```python
  for payload in ui_data_from_tool_result(tool_name, result, tool_call_id=normalized_tool_call_id):
      yield emit(event_names.UI_DATA_EVENT, payload)
  ```
- **demo 注入路径（用于 spike/E2E）**：在 script model 或测试 helper 中加入小 hook，emit 1 个 `demo_note`。（运行时代码路径中 `UI_DATA_TOOL_NAMES` 为空，因此不产生任何行为 = 回归 0）
- 测试：`backend/tests/test_ui_data_projection.py`（投影单元），`test_streaming.py` 增加 ui_data emit 场景（工具结果 → UI_DATA_EVENT）。`test_conversation_agent_protocol_*` 确认 custom channel 通过。

### 5.2 前端

**Commit F1 — `feat(chat): ui_data event ingestion + registry scaffold`**

- 契约类型：`frontend/src/lib/types/ui-data.ts`（新增）— 与后端 `UIDataEvent` 1:1。
- Zod schema + registry：`frontend/src/lib/chat/data-ui-registry.ts`（新增）
  ```ts
  import { z } from 'zod'
  // 各类型 props Zod（demo）
  const demoNoteProps = z.object({ text: z.string() })
  export const DATA_UI_REGISTRY = {
    demo_note: { props: demoNoteProps, Component: DemoNoteCard },
    // Phase 2: data_table, chart, stats, terminal
  } as const
  export function resolveDataUI(type: string, rawProps: unknown) {
    const entry = (DATA_UI_REGISTRY as Record<string, { props: z.ZodTypeAny; Component: React.FC<any> }>)[type]
    if (!entry) return null                         // 不支持的 type → fail-safe
    const parsed = entry.props.safeParse(rawProps)
    if (!parsed.success) return null                // 验证失败 → fail-safe
    return { Component: entry.Component, props: parsed.data }
  }
  ```
- 事件消费：`frontend/src/lib/chat/langgraph-runtime/data-ui-events.ts`（新增，复制 `artifact-events.ts`）
  - `useChannelEffect(stream, ['custom'], { onEvent })` → 匹配 custom name `moldy.ui_data` → 提取 payload。
  - Jotai store `frontend/src/lib/stores/chat-data-ui.ts`（新增，复制 `chat-artifacts.ts`）— 以 message_id 为 Key upsert。
- 渲染（路径 A — data part + makeAssistantDataUI）：
  - `frontend/src/lib/chat/data-ui.tsx` — `makeAssistantDataUI({ render: ({ data }) => <DataUIDispatcher data={data} /> })`。`DataUIDispatcher` 通过 `resolveDataUI` 选择组件 + fail-safe。
  - 通过 `AssistantThread` 的 `dataUI` prop 注入（page → chat-runtime-section → AssistantThread 路径接线）。
  - store→消息附加与 `attachArtifactsToMessages` 相同，实现为 `attachDataUIToMessages`（采用 spike 确认的 data part 注入方式）。
- 渲染（路径 B — fallback，内联卡片）：`AssistantDataUICards`（= 复制 `AssistantArtifactCards`）从 store 读取当前消息 payload，并通过 `resolveDataUI` 渲染。
- demo 组件：`frontend/src/components/chat/data-ui/demo-note-card.tsx`（文本框）。
- 测试(vitest)：`data-ui-registry`（不支持 type/验证失败 → null）、`data-ui-events`（事件→store）、demo 渲染（流水线）。**遵守共享 mock transport 规则**（CLAUDE.md）：新增方法时更新 `createMockTransport()`。

### 5.3 Phase 1 完成标准 (DoD)
- [ ] `tsc 0 / lint 0 / vitest green / 后端 pytest green / ruff clean`
- [ ] demo 类型（`demo_note`）在 v3 聊天气泡中以方框渲染（live + reload）。
- [ ] **运行路径无动作证明**：`UI_DATA_TOOL_NAMES` 为空，真实对话中 ui_data 为 0 条 → 与现有聊天 100% 相同。
- [ ] 通过 §7 回归截图 gate。

---

## 6. Phase 2 — 添加组件（逐个添加，每阶段截图）

每个组件 = **(a) 后端 per-type payload schema + (b) 前端 Zod + 组件 wrapper + registry 注册 + (c) 测试 + (d) 截图**。按顺序进行，每个 PR/commit 分开。

### 6.1 DataTable（最容易复用 — 先做）
- 复用：`frontend/src/components/ui/data-table.tsx`（tanstack, `DataTableProps<T>`: `columns: ColumnDef<T>[]`, `data: T[]`, `searchable`, `filters`, `pageSize`）。
- props 契约：`{ columns: {key, header}[], rows: Record<string,unknown>[], title?, searchable? }`。wrapper 将 `{key,header}` → `ColumnDef`。
- 组件：`frontend/src/components/chat/data-ui/data-table-card.tsx`（UsageChartFrame 类卡片 shell + DataTable）。
- 工作量：组件本身几乎只是“接上去”，核心是**adapter（行/列 → ColumnDef）**。

### 6.2 Chart
- 复用：`frontend/src/components/usage/usage-chart-frame.tsx`（shell）+ `spend-line-chart.tsx`/`spend-bar-chart.tsx`（内联 SVG 折线/柱状参考）。若要更丰富可包装 `chart.js`（已有依赖）。
- props 契约：`{ chartType: "line"|"bar", series: {label:string, value:number}[], title, xLabel?, yLabel? }`。
- 组件：`data-ui/chart-card.tsx` — 通用 series → 图表。（spend 图表仅用于 spend 数据，因此**新增通用 wrapper**。）

### 6.3 StatsDisplay
- 无可复用组件 → 基于 shadcn `Card` primitive 新建（轻量）。参考 usage 页面摘要数字模式。
- props 契约：`{ items: {label:string, value:string|number, delta?:number, unit?:string}[] }`。
- 组件：`data-ui/stats-card.tsx` — KPI 网格。

### 6.4 Terminal
- 最接近可复用：`frontend/src/components/chat/tool-ui/code-tool-ui.tsx` 的 `CodeBlock`（mono `<pre>`）。适配/新建（轻量）。
- props 契约：`{ lines: string[] | string, exitCode?: number, command?: string }`。
- 组件：`data-ui/terminal-card.tsx` — mono 输出 +（可选）命令/exit code header。

### 6.5 各组件通用工作
- 后端：扩展 `UIDataType` Literal +（可选）用 per-type Pydantic model 做服务端验证 + 在 `UI_DATA_TOOL_NAMES` 注册对应工具（或 demo emit）。
- 前端：在 `DATA_UI_REGISTRY` 增加 1 行 `{props: zod, Component}`。
- 测试 + §7 截图。

---

## 7. 回归验证 + 截图 gate（用户要求的核心）

> **只有在真实服务器 + 分页面截图证明 Phase 1 基础设施回归为 0 后，才能进入 Phase 2。** Phase 2 的每个组件也同样截图。

### 7.1 启动真实服务器（throwaway stack；CLAUDE.md "E2E 端口/DB 隔离"）
```bash
# throwaway Postgres
docker run -d --name moldy-genui-pg -p 5433:5432 \
  -e POSTGRES_DB=moldy -e POSTGRES_USER=moldy -e POSTGRES_PASSWORD=moldy postgres:16-alpine
cd backend && DATABASE_URL='postgresql+asyncpg://moldy:moldy@localhost:5433/moldy' \
  uv run alembic upgrade head
# 后端/前端由 playwright webServer 自行启动（端口 3100/8101）
```

### 7.2 回归检查清单（按页面截图 — 每项至少 1 张）
所有现有 surface 在引入 ui_data 前后都必须保持一致。

- [ ] **C1 普通对话**：文本流式传输、Markdown（代码/表格）、正常结束。
- [ ] **C2 工具调用组**：连续相同工具 grouping（GroupedParts）+ CollapsiblePill 正常。
- [ ] **C3 搜索工具**：search-tool-ui 来源聚合正常。
- [ ] **C4 HITL**：审批卡（ApprovalCard）/ask_user（OptionList）正常。
- [ ] **C5 artifact**：生成文件内联卡片 + 右侧栏 + 预览（FILE_EVENT 路径与 ui_data 共用 custom channel → 确认无冲突）。
- [ ] **C6 附件**：user 气泡内联 + /files 列表（刚合并的功能）。
- [ ] **C7 reasoning / phase-timeline / sub-agent / memory** 工具 UI 正常。
- [ ] **C8 上下文 gauge / token popover / 自动 compaction marker** 正常。
- [ ] **C9 reload 后完整历史重建**正常（包含 data part）。
- [ ] **C10 Generative UI demo（`demo_note`）** 在 live + reload 时以方框显示。

### 7.3 自动化(E2E) — `frontend/e2e/chat-generative-ui.spec.ts`（新增）
- 通过 script model/测试 helper emit 1 条 `demo_note` ui_data → 断言气泡中渲染 + reload 后保持。
- 不支持的 type / 验证失败 → 断言**跳过渲染（无错误）**（fail-safe）。
- 重新运行现有 `chat-attachments-display.spec.ts`·工具 grouping E2E，确认**无回归**。

### 7.4 截图产物
- 在 scratchpad 中以 `captures/` 保存各页面 PNG 后交付用户（SendUserFile）。headless 抓不到的内容（iframe-PDF 等）使用 `--headed`（chat-attachments 工作经验）。
- **No-regression 标准**：C1~C9 截图在引入前后视觉一致，C10 demo 正常，E2E green。

---

## 8. 验证命令（各阶段）

```bash
# 后端
cd backend && uv run pytest && uv run ruff check .
# 前端
cd frontend && pnpm vitest run && pnpm exec tsc --noEmit && pnpm lint
# E2E（throwaway stack；§7.1）
cd frontend && E2E_FRONTEND_PORT=3100 E2E_BACKEND_PORT=8101 \
  DATABASE_URL='postgresql+asyncpg://moldy:moldy@localhost:5433/moldy' \
  DATABASE_URL_SYNC='postgresql://moldy:moldy@localhost:5433/moldy' \
  RATE_LIMIT_ENABLED=false E2E_TEST_HELPERS_ENABLED=true \
  pnpm exec playwright test e2e/chat-generative-ui.spec.ts
```
- pre-push 被阻止时用 `SKILL_EVALUATION_ENABLED=true` push（规避共享 .env false）。

---

## 9. Commit/PR 计划（每个 commit 本身都保持 green）

- Phase 0：`chore(chat): generative-ui spike — confirm data-part render path`（spike 结果文档/PoC，必要时）
- Phase 1: `feat(chat): ui_data event contract (backend emit + schema)` / `feat(chat): ui_data ingestion + registry + demo render (frontend)` / `test(e2e): generative-ui demo render + no-regression`
- Phase 2（按组件）：`feat(chat): DataTable generative-ui card` → `... Chart ...` → `... StatsDisplay ...` → `... Terminal ...`
- 每个 Phase 结束时通过 §7 截图 gate 后再进入下一阶段。

---

## 10. 风险 & 未决事项

- **R1（依赖 spike）**：若 custom 事件 → assistant-ui **data part** 的桥接不够干净，则 fallback 到内联卡片（路径 B）。先在 §4 确认 → 消除正式实现风险。
- **R2（安全）**：props 是后端/工具生成的数据。**前端用 Zod 验证 shape** + **组件只使用可信 props**（禁止渲染任意 HTML/script；Terminal/CodeBlock 仅按文本）。allowlist 只控制 type，因此**必须验证 per-type props**。
- **R3（custom channel 共存）**：ui_data 与 FILE_EVENT 共用同一 `custom` channel。消费端按 custom **name**（`moldy.ui_data` vs `moldy.file_event`）准确分流（与 artifact `protocolArtifactPayload` 相同规则）。在 C5 检查回归。
- **R4（message_id 匹配）**：data part 的附着目标 message_id 与 artifact 规则相同（准确匹配 + 最后一个 assistant fallback）。live 发送后立即未匹配时通过 reload 恢复（与 artifact 相同特性）。
- **R5（范围克制）**：不改动现有 tool-ui（`makeAssistantToolUI`）渲染（增量式）。payload-type 全面切换/toolkit 迁移/0.14.24 升级作为单独 track。

---

## 11. 参考文件索引（实现时需要查看）

| 目的 | 文件 |
|------|------|
| SSE emit/event 名称 | `backend/app/agent_runtime/streaming.py:309-341,520-548`, `event_names.py` |
| 工具结果→事件投影模式 | `backend/app/agent_runtime/memory_event_projection.py` |
| artifact payload/schema | `backend/app/services/artifact_service.py:122-149,1028`, `backend/app/schemas/artifact.py:26-61` |
| protocol custom 通过 | `backend/app/routers/conversation_agent_protocol_runtime.py:118-149`, `agent_runtime/protocol_events.py` |
| 前端 custom 消费先例 | `frontend/src/lib/chat/langgraph-runtime/artifact-events.ts:78-203` |
| 前端 store 先例 | `frontend/src/lib/stores/chat-artifacts.ts:48-65` |
| part 渲染 switch（'data'） | `frontend/src/components/chat/assistant-thread.tsx:299-328,341-413` |
| part grouping | `frontend/src/lib/chat/group-assistant-parts.ts` |
| data-part API(0.14.18) | `frontend/node_modules/@assistant-ui/react/dist/index.d.ts`（`makeAssistantDataUI` 等） |
| 复用 DataTable | `frontend/src/components/ui/data-table.tsx` |
| 复用 Chart shell/图表 | `frontend/src/components/usage/{usage-chart-frame,spend-line-chart,spend-bar-chart}.tsx` |
| 复用 Terminal 相近组件 | `frontend/src/components/chat/tool-ui/code-tool-ui.tsx` (CodeBlock) |
| runtime 配置 | `frontend/src/lib/chat/langgraph-runtime/use-moldy-langgraph-stream.ts:2798`（`useExternalStoreRuntime`） |
