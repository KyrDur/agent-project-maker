# Builder + Assistant UI 设计规范

| 项目 | 值 |
|------|-----|
| 作者 | tim-cook |
| 日期 | 2026-04-07 |
| 状态 | 已提议 |
| 相关文档 | ADR-005, moldy-agent-builder-spec-v2.md |

---

## 1. 概述

将现有 4 阶段对话式 agent 创建 UI（`conversational/page.tsx`）替换为 7 阶段 pipeline monitoring Builder UI，
并将现有 `fix-agent-dialog.tsx` 的简单 dialog 替换为全尺寸 Assistant 对话 panel。

**设计原则：**
- 优先使用 shadcn/ui 组件，尽量减少自定义 UI
- 遵循现有项目设计系统（colors, spacing, typography）
- 同时支持 dark/light mode
- 考虑移动端响应式（最小 360px viewport）

---

## 2. Builder UI（7 阶段 pipeline）

### 2.1 整体布局

```
+---------------------------------------------------------------+
| [<] Agent Builder                              [Reset]        | <- Header
+---------------------------------------------------------------+
|                                                               |
|  [Phase 1: Input]                                             |
|  +-----------------------------------------------------------+|
|  | “想创建什么样的 agent？”                           ||
|  |                                                           ||
|  | +-------------------------------------------------------+ ||
|  | | textarea（自然语言输入）                                   | ||
|  | +-------------------------------------------------------+ ||
|  |                                          [开始 ->]    ||
|  +-----------------------------------------------------------+|
|                                                               |
|  [Phase Timeline — 7 阶段]                                     |
|  +-----------------------------------------------------------+|
|  | Phase 1: 项目初始化           [完成]                   ||
|  | Phase 2: 意图分析                [进行中]                 ||
|  | Phase 3: 工具推荐                [等待]                    ||
|  | Phase 4: 中间件推荐            [等待]                    ||
|  | Phase 5: System prompt 生成      [等待]                    ||
|  | Phase 6: Agent 设置            [等待]                    ||
|  | Phase 7: 最终构建                [等待]                    ||
|  +-----------------------------------------------------------+|
|                                                               |
|  [Phase Result Cards — 已完成阶段结果]                       |
|  +-----------------------------------------------------------+|
|  | Intent 摘要 card / 工具推荐 card / ...                     ||
|  +-----------------------------------------------------------+|
|                                                               |
|  [Phase 7: Final Confirmation]                                |
|  +-----------------------------------------------------------+|
|  | DraftAgentConfig 摘要                                      ||
|  |                                          [创建 agent]    ||
|  +-----------------------------------------------------------+|
|                                                               |
+---------------------------------------------------------------+
```

### 2.2 输入阶段（Phase 1 开始前）

复用现有 `conversational/page.tsx` 的 Phase 1 输入区域。

**组件：** `BuilderInputSection`

| 元素 | 规格 |
|------|------|
| 问题 card | `rounded-xl border bg-background p-5`, MessageCircleIcon + 文本 |
| textarea | `min-h-[80px] max-h-[160px]`, placeholder: “创建一个汇总新闻的 agent” |
| 提交按钮 | `Button size="lg"`, SendIcon + “开始” |
| 键盘 | Enter 提交（Shift+Enter 换行），处理 IME composition |

**支持 searchParams：**
- 通过 `?initialMessage=...` query parameter 可从 dashboard 直接传入初始值（保持现有模式）

### 2.3 Phase Timeline（7 阶段）

将现有 `PhaseTimeline` 组件从 4 阶段扩展到 7 阶段。

**组件：** `BuilderTimeline`

```tsx
interface BuilderTimelineProps {
  currentPhase: number          // 0-7（0=输入前）
  phaseStatuses: PhaseStatus[]  // 通过 SSE 实时更新
}

type PhaseStatus = {
  phase: number
  status: 'pending' | 'started' | 'completed' | 'failed'
  message?: string
}
```

**7 阶段定义：**

| Phase | Label | Description | 图标 |
|-------|-------|-------------|--------|
| 1 | 项目初始化 | 准备工作环境 | FolderOpenIcon |
| 2 | 意图分析 | 正在分析请求 | BrainIcon |
| 3 | 工具推荐 | 选择合适工具 | WrenchIcon |
| 4 | 中间件推荐 | 选择稳定性/性能 layer | ShieldIcon |
| 5 | System prompt | 编写 agent 指令 | FileTextIcon |
| 6 | Agent 设置 | 汇总最终设置 | SettingsIcon |
| 7 | 最终构建 | 创建 agent 实例 | RocketIcon |

**按状态的视觉表现（扩展现有模式）：**

| 状态 | 图标 | 颜色 | Badge |
|------|--------|------|------|
| completed | CheckIcon（圆形） | `bg-emerald-500 text-white` | `bg-emerald-100 text-emerald-700` |
| started | CircleDotIcon（圆形） | `bg-primary text-primary-foreground` | `bg-primary/10 text-primary` |
| failed | XCircleIcon（圆形） | `bg-destructive text-destructive-foreground` | `bg-destructive/10 text-destructive` |
| pending | ClockIcon（圆形） | `border-muted-foreground/30 text-muted-foreground/50` | `bg-muted text-muted-foreground` |

**连接线：**
- 完成：`bg-emerald-500`
- 失败：`bg-destructive`
- 等待：`bg-muted-foreground/20`

**SSE 连接：**
- `GET /api/builder/{session_id}/stream` → 通过 `phase_progress` event 实时更新
- `sub_agent_start` / `sub_agent_end` → 在 Phase 2-5 显示 subagent 运行状态

**subagent 运行指示器：**
- Phase 2-5 处于 started 状态时，在 Phase label 下方用小文本显示 subagent 名称
- 例如：“意图分析 subagent 运行中...” （Loader2Icon animate-spin + text-xs text-muted-foreground）

### 2.4 Phase 结果 card

每个 Phase 完成后以 card 显示结果。按顺序堆叠在 Phase Timeline 下方。

**组件：** `PhaseResultCard`

```tsx
interface PhaseResultCardProps {
  phase: number
  title: string
  children: React.ReactNode  // 各 Phase 的自定义内容
  status: 'completed' | 'failed'
}
```

**通用样式：**
- `rounded-xl border bg-background`（现有 Card 样式）
- 顶部显示 Phase 编号 badge + 标题
- 完成时 `border-emerald-500/20`，失败时 `border-destructive/20`
- 动画：`animate-in fade-in slide-in-from-bottom-2 duration-300`

#### Phase 2 结果：Intent 摘要 card

**组件：** `IntentSummaryCard`

摘要显示 AgentCreationIntent 的核心字段。

```
+-----------------------------------------------------------+
| [2] 意图分析完成                                [完成]    |
+-----------------------------------------------------------+
| Agent: News Summarizer（新闻摘要 agent）              |
| 角色：搜索最新新闻并提炼核心内容进行传达        |
|                                                           |
| 核心任务：新闻搜索与摘要                               |
| 响应风格：简洁摘要 + 核心要点                      |
|                                                           |
| 使用场景：                                                |
|  - 每日新闻简报                                       |
|  - 特定主题新闻监控                                 |
|  - 新闻对比分析                                         |
+-----------------------------------------------------------+
```

**布局：**
- `space-y-2.5 rounded-lg bg-muted/50 p-4 text-sm`（复用现有 draft info 样式）
- 各字段采用 `flex justify-between` 或 label + value 结构
- use_cases 使用 `ul` 列表

#### Phase 3 结果：工具推荐 card

**组件：** `ToolRecommendationCards`

复用现有 `ToolCard` 模式。

```
+-----------------------------------------------------------+
| [3] 工具推荐完成                                [完成]    |
+-----------------------------------------------------------+
| +-------------------------------------------------------+ |
| | [WrenchIcon] tavily_search                            | |
| | 通用 Web 搜索。适合搜索最新新闻与信息               | |
| | 选择理由：新闻搜索的核心工具                        | |
| +-------------------------------------------------------+ |
| +-------------------------------------------------------+ |
| | [WrenchIcon] naver_news                               | |
| | Naver 新闻搜索。专注韩文新闻                       | |
| | 选择理由：扩大韩国新闻覆盖                       | |
| +-------------------------------------------------------+ |
+-----------------------------------------------------------+
```

**布局：**
- 扩展现有 `ToolCard`：新增 `reason` 字段（text-xs text-muted-foreground）
- `flex gap-3 rounded-xl border bg-background p-4`

#### Phase 4 结果：中间件推荐 card

**组件：** `MiddlewareRecommendationCards`

与工具 card 使用相同布局。仅将图标改为 `ShieldIcon`。

```
+-------------------------------------------------------+
| [ShieldIcon] ToolRetryMiddleware                      |
| 外部 API 调用失败时自动重试                        |
| 选择理由：确保新闻 API 调用稳定性                     |
+-------------------------------------------------------+
```

#### Phase 5 结果：System prompt 预览

**组件：** `SystemPromptPreview`

复用现有 Phase 4 的 `<details>` 模式，但表达更明确。

```
+-----------------------------------------------------------+
| [5] System prompt 生成完成                     [完成]    |
+-----------------------------------------------------------+
| [v] 查看 System prompt                                    |
| +-------------------------------------------------------+ |
| | # News Summarizer                                     | |
| | ## Role                                               | |
| | 搜索最新新闻并提炼核心内容...             | |
| | ...                                                   | |
| +-------------------------------------------------------+ |
|                                  约 3,200 字 / 5,000 字上限 |
+-----------------------------------------------------------+
```

**布局：**
- 使用 `<Collapsible>`（shadcn/ui）— 默认折叠
- 展开时：`max-h-[300px] overflow-auto rounded-lg bg-muted p-4`
- 使用 `<MarkdownContent>` 组件渲染（复用现有 chat 模式）
- 底部显示字符数（text-xs text-muted-foreground）

#### Phase 6-7 结果：最终设置摘要

复用现有 Phase 4 的 `DraftConfig` 显示模式。

### 2.5 最终确认（Phase 7 完成后）

**组件：** `BuilderConfirmation`

从 SSE 收到 `build_preview` event 后显示 DraftAgentConfig。

```
+-----------------------------------------------------------+
| [SparklesIcon] Agent 设置完成                           |
+-----------------------------------------------------------+
|                                                           |
| Agent 名称：News Summarizer                              |
| 韩文名称：新闻摘要 agent                                |
| 说明：搜索最新新闻并...                               |
| 模型：anthropic:claude-sonnet-4-5                         |
|                                                           |
| 工具（3 个）：                                               |
|  [WrenchIcon] tavily_search                               |
|  [WrenchIcon] naver_news                                  |
|  [WrenchIcon] naver_blog                                  |
|                                                           |
| 中间件（2 个）：                                           |
|  [ShieldIcon] ToolRetryMiddleware                         |
|  [ShieldIcon] SummarizationMiddleware                     |
|                                                           |
| [v] 查看 System prompt                                    |
|                                                           |
| +-------------------------------------------------------+ |
| |              [创建 agent]                         | |
| +-------------------------------------------------------+ |
+-----------------------------------------------------------+
```

**行为：**
- 点击“创建 agent” → `POST /api/builder/{session_id}/confirm`
- 成功后 redirect 到 `/agents/{agent_id}`
- 加载中显示 Loader2Icon animate-spin + 按钮 disabled

### 2.6 Error 状态

从 SSE 收到 `error` event 时：

**recoverable: true**
- 在 Phase Timeline 中将对应 Phase 标为 `failed`
- 显示错误信息 card（border-destructive/20）
- 提供“重试”按钮

**recoverable: false**
- 显示整体构建失败
- “从头重新开始”按钮（handleReset）

### 2.7 SSE streaming client

扩展现有 `stream-chat.ts` 模式。

**新文件：** `frontend/src/lib/sse/stream-builder.ts`

```typescript
export async function* streamBuilder(
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<BuilderSSEEvent> {
  // GET /api/builder/{session_id}/stream
  // event type: phase_progress, sub_agent_start, sub_agent_end,
  //             build_preview, error
}
```

**Event type（TypeScript）：**

```typescript
type BuilderSSEEventType =
  | 'phase_progress'
  | 'sub_agent_start'
  | 'sub_agent_end'
  | 'build_preview'
  | 'error'

type BuilderSSEEvent =
  | { event: 'phase_progress'; data: { phase: number; status: string; message?: string } }
  | { event: 'sub_agent_start'; data: { phase: number; agent_name: string } }
  | { event: 'sub_agent_end'; data: { phase: number; result_summary: string } }
  | { event: 'build_preview'; data: { draft_config: DraftAgentConfig } }
  | { event: 'error'; data: { phase: number; message: string; recoverable: boolean } }
```

### 2.8 State 管理

**Jotai atoms** (`frontend/src/lib/stores/builder-store.ts`):

```typescript
// 构建 session 状态
export const builderSessionIdAtom = atom<string | null>(null)
export const builderPhaseStatusesAtom = atom<PhaseStatus[]>(INITIAL_PHASES)
export const builderCurrentPhaseAtom = atom<number>(0)

// Phase 结果
export const builderIntentAtom = atom<AgentCreationIntent | null>(null)
export const builderToolsAtom = atom<ToolRecommendation[]>([])
export const builderMiddlewaresAtom = atom<MiddlewareRecommendation[]>([])
export const builderSystemPromptAtom = atom<string>('')
export const builderDraftConfigAtom = atom<DraftAgentConfig | null>(null)

// 错误
export const builderErrorAtom = atom<BuildErrorEvent | null>(null)

// subagent 状态（Phase 2-5）
export const builderSubAgentAtom = atom<{ phase: number; name: string } | null>(null)
```

### 2.9 Routing

| 路径 | 作用 |
|------|------|
| `/agents/new` | 选择创建方式（保持现有） |
| `/agents/new/builder` | Builder UI（新增） |
| `/agents/new/conversational` | 现有对话式界面（v2 完成后删除） |

v2 迁移期间两条路径共存。

### 2.10 响应式布局

| Viewport | 行为 |
|--------|------|
| Desktop (1024px+) | `max-w-2xl mx-auto`，现有布局 |
| Tablet (768-1023px) | `max-w-xl mx-auto`，相同布局 |
| Mobile (360-767px) | `px-4`，缩小 Phase Timeline 文本，card stack |

---

## 3. Assistant UI（Agent 设置对话 panel）

### 3.1 整体布局

将现有 `fix-agent-dialog.tsx` 的 600px dialog 替换为 agent 设置页面内的全高 panel。

**入口：** 在 agent 设置页面（`/agents/{agentId}/settings`）新增“AI Assistant”tab

```
+---------------------------------------------------------------+
| [<] Agent 设置 — My Agent                                    |
+---------------------------------------------------------------+
| [基本信息] [模型] [工具] [触发器] [AI Assistant]               | <- 新增 tab
+---------------------------------------------------------------+
|                                                               |
|  Assistant 对话区域                                           |
|  +-----------------------------------------------------------+|
|  |                                                           ||
|  | [空状态 / 对话消息]                                    ||
|  |                                                           ||
|  +-----------------------------------------------------------+|
|                                                               |
|  +-----------------------------------------------------------+|
|  | [输入区域]                                                ||
|  +-----------------------------------------------------------+|
|                                                               |
+---------------------------------------------------------------+
```

### 3.2 Tab 集成

在现有设置页面 Tabs 中新增“AI Assistant”tab。

```tsx
<TabsList>
  <TabsTrigger value="basic">{t('tabs.basic')}</TabsTrigger>
  <TabsTrigger value="model">{t('tabs.model')}</TabsTrigger>
  <TabsTrigger value="tools">{t('tabs.tools')}</TabsTrigger>
  <TabsTrigger value="triggers">{t('tabs.triggers')}</TabsTrigger>
  <TabsTrigger value="assistant">
    <SparklesIcon className="size-4 mr-1" />
    {t('tabs.assistant')}
  </TabsTrigger>
</TabsList>
```

**替代方案（移动端）：** tab 增加到 5 个，因此移动端使用可滚动 `TabsList`（复用现有 `overflow-x-auto scrollbar-none` 样式）。

### 3.3 空状态（Empty State）

扩展现有 `fix-agent-dialog.tsx` 的空状态模式。

```
+-----------------------------------------------------------+
|                                                           |
|            [SparklesIcon size-10 text-primary/30]          |
|                                                           |
|         使用 AI Assistant 修改 agent                 |
|     用自然语言提出需求后，工具、prompt、模型等              |
|            将自动为你修改。                         |
|                                                           |
|    [改得说话更亲切一些]                          |
|    [添加搜索工具]                                   |
|    [我想降低成本]                                     |
|    [改进 System prompt]                              |
|                                                           |
+-----------------------------------------------------------+
```

**Quick suggestion chips:**
- `rounded-full border px-3 py-1.5 text-xs hover:bg-accent transition-colors cursor-pointer`
- 点击后把文本插入输入字段（沿用现有模式）

### 3.4 对话区域

扩展现有 `fix-agent-dialog.tsx` 的消息渲染。

**组件：** `AssistantChatArea`

#### 用户消息

```
                                              +------------------+
                                              | 请添加搜索工具 |
                                              +------------------+
                                                           [UserIcon]
```

- 现有样式：`bg-primary text-primary-foreground rounded-2xl px-3.5 py-2`
- 右对齐

#### Assistant 消息

```
[BotIcon]
+-----------------------------------------------------------+
| 已添加 tavily_search 工具。                           |
| 也已在系统提示词中添加工具使用指南。           |
+-----------------------------------------------------------+
```

- 现有样式：`bg-muted rounded-2xl px-3.5 py-2.5`
- 使用 `<MarkdownContent>`（支持 Markdown 渲染）
- 左对齐，BotIcon 头像

#### 内联显示工具执行结果

当 Assistant 执行工具（add_tool、remove_tool、edit_system_prompt 等）时，在 SSE 流式传输过程中内联显示工具执行结果。

**组件：** `AssistantToolAction`

```
[BotIcon]
+-----------------------------------------------------------+
| [工具执行结果]                                            |
| +-------------------------------------------------------+ |
| | [+] 已添加 tavily_search                    [成功徽章] | |
| +-------------------------------------------------------+ |
| +-------------------------------------------------------+ |
| | [~] 已修改系统提示词                   [成功徽章] | |
| +-------------------------------------------------------+ |
|                                                           |
| 已添加 tavily_search 工具，并在系统提示词中            |
| 添加了工具使用指南。                             |
+-----------------------------------------------------------+
```

**工具操作徽章：**

| 操作 | 图标 | 徽章颜色 |
|------|--------|----------|
| 添加工具 | PlusIcon | `bg-emerald-500/10 text-emerald-600` |
| 移除工具 | MinusIcon | `bg-orange-500/10 text-orange-600` |
| 修改提示词 | PencilIcon | `bg-blue-500/10 text-blue-600` |
| 替换提示词 | RefreshCwIcon | `bg-blue-500/10 text-blue-600` |
| 添加中间件 | PlusIcon + ShieldIcon | `bg-emerald-500/10 text-emerald-600` |
| 移除中间件 | MinusIcon + ShieldIcon | `bg-orange-500/10 text-orange-600` |
| 更改模型 | CpuIcon | `bg-purple-500/10 text-purple-600` |
| 创建/修改计划任务 | CalendarIcon | `bg-indigo-500/10 text-indigo-600` |
| 查看（只读） | EyeIcon | `bg-muted text-muted-foreground` |

**成功/失败显示：**
- 成功：`CheckCircle2Icon text-emerald-500` + "成功"
- 失败：`XCircleIcon text-destructive` + 错误消息

**SSE 映射（复用现有 chat SSE 事件）：**
- `tool_call_start` → 显示工具名称 + args（加载状态）
- `tool_call_result` → 更新结果（成功/失败）
- `content_delta` → 文本流式传输
- `message_end` → 确定最终消息

#### 提示词 Diff 显示

在 `edit_system_prompt` 工具执行结果中显示 diff。

**组件：** `PromptDiffDisplay`

```
+-------------------------------------------------------+
| [~] 已修改系统提示词                              |
| - "请适当地处理"                                   |  <- 红色背景
| + "请按照以下步骤处理：1. ..."                  |  <- 绿色背景
+-------------------------------------------------------+
```

**样式：**
- 删除行：`bg-destructive/10 text-destructive line-through`
- 新增行：`bg-emerald-500/10 text-emerald-700`
- 可折叠 `<Collapsible>` — 默认展开，较长 diff 折叠

### 3.5 Clarifying Question (ask_clarifying_question)

复用现有 `OptionCard` 模式。

当 Assistant 调用 `ask_clarifying_question` 工具时，显示选项卡片。

```
[BotIcon]
+-----------------------------------------------------------+
| 您希望修改哪个范围？                               |
+-----------------------------------------------------------+

+-----------------------------------------------------------+
| ( ) 仅改进系统提示词                                   |
+-----------------------------------------------------------+
+-----------------------------------------------------------+
| ( ) 同时优化工具和中间件                            |
+-----------------------------------------------------------+
+-----------------------------------------------------------+
| ( ) 从头重新审视全部设置                              |
+-----------------------------------------------------------+
+-----------------------------------------------------------+
| ( ) 直接输入                                               |
+-----------------------------------------------------------+

                                              [发送 ->]
```

**行为：**
- 点击选项 → 高亮所选项（单选）
- 选择 "直接输入" 时 → 显示 textarea
- 点击 "发送" → 将所选选项文本作为消息发送
- 原样复用现有 `OptionCard` 组件（`multiSelect: false`）

### 3.6 输入区域

复用现有 `ChatInput` 组件。

**差异：**
- 禁用文件附件（PaperclipIcon）（Assistant 不支持文件）
- 无需显示模型（省略现有 ChatInput 的 modelName prop）
- 显示 token 使用量（SSE `message_end` 的 usage 数据）

### 3.7 SSE 流式传输

原样复用现有 `stream-chat.ts`。

**API:** `POST /api/agents/{agent_id}/assistant/message`

```typescript
// 与 stream-chat.ts 的 streamChat() 模式相同
// POST body: { content: string }
// SSE 事件：message_start, content_delta, tool_call_start,
//             tool_call_result, message_end, error
```

由于与现有 SSE 事件类型完全相同，无需单独的流式函数。
只需向 `streamChat()` 函数传入不同的端点 URL。

```typescript
// 或 streamAssistant 包装器
export async function* streamAssistant(
  agentId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  // POST /api/agents/{agentId}/assistant/message
  // 其余与 streamChat 相同
}
```

### 3.8 状态管理

**Jotai atoms** (`frontend/src/lib/stores/assistant-store.ts`):

```typescript
// 消息历史
export const assistantMessagesAtom = atom<AssistantMessage[]>([])

// 流式状态
export const assistantStreamingAtom = atom<boolean>(false)
export const assistantStreamingContentAtom = atom<string>('')
export const assistantToolActionsAtom = atom<AssistantToolAction[]>([])

// Clarifying question
export const assistantClarifyingQuestionAtom = atom<ClarifyingQuestion | null>(null)
```

```typescript
interface AssistantMessage {
  role: 'user' | 'assistant'
  content: string
  toolActions?: AssistantToolAction[]  // 工具执行结果
}

interface AssistantToolAction {
  toolName: string
  summary: string
  success: boolean
  diff?: { old: string; new: string }  // 用于 edit_system_prompt
}

interface ClarifyingQuestion {
  question: string
  options: string[]  // 3个 + "直接输入"
}
```

### 3.9 响应式布局

| Viewport | 行为 |
|--------|------|
| Desktop (1024px+) | 标签页内 `max-w-2xl mx-auto`，对话区域固定高度 |
| Tablet (768-1023px) | 相同 |
| Mobile (360-767px) | 标签页内全宽，对话区域 `flex-1` |

---

## 4. 组件列表

### 4.1 Builder 组件（新增）

| 组件 | 路径 | 说明 |
|----------|------|------|
| `BuilderPage` | `app/agents/new/builder/page.tsx` | Builder 整体页面 |
| `BuilderInputSection` | `components/builder/builder-input.tsx` | 自然语言输入 |
| `BuilderTimeline` | `components/builder/builder-timeline.tsx` | 7阶段时间线 |
| `PhaseResultCard` | `components/builder/phase-result-card.tsx` | Phase 结果卡片包装器 |
| `IntentSummaryCard` | `components/builder/intent-summary-card.tsx` | Phase 2 结果 |
| `ToolRecommendationCards` | `components/builder/tool-recommendation-cards.tsx` | Phase 3 结果 |
| `MiddlewareRecommendationCards` | `components/builder/middleware-recommendation-cards.tsx` | Phase 4 结果 |
| `SystemPromptPreview` | `components/builder/system-prompt-preview.tsx` | Phase 5 结果 |
| `BuilderConfirmation` | `components/builder/builder-confirmation.tsx` | 最终确认 |

### 4.2 Assistant 组件（新增）

| 组件 | 路径 | 说明 |
|----------|------|------|
| `AssistantTab` | `app/agents/[agentId]/settings/_components/assistant-tab.tsx` | 设置页面标签页 |
| `AssistantChatArea` | `components/assistant/assistant-chat-area.tsx` | 对话区域 |
| `AssistantToolAction` | `components/assistant/assistant-tool-action.tsx` | 工具执行结果 |
| `PromptDiffDisplay` | `components/assistant/prompt-diff-display.tsx` | 提示词 diff |
| `ClarifyingQuestionCard` | `components/assistant/clarifying-question-card.tsx` | 选项卡片 |

### 4.3 复用组件（现有）

| 组件 | 原始位置 | 复用位置 |
|----------|------|------------|
| `OptionCard` | `conversational/page.tsx` | Assistant ClarifyingQuestion |
| `ToolCard` | `conversational/page.tsx` | Builder Phase 3 |
| `ChatInput` | `components/chat/chat-input.tsx` | Assistant 输入 |
| `MarkdownContent` | `components/chat/markdown-content.tsx` | Builder, Assistant |
| `StreamingMessage` | `components/chat/streaming-message.tsx` | Assistant（参考模式） |
| `PhaseTimeline` | `conversational/page.tsx` | Builder（扩展） |

**需要重构：** 需要从 `conversational/page.tsx` 中提取 `OptionCard`、`ToolCard` 并移动到 `components/shared/`，以便 Builder 和 Assistant 两侧复用。

---

## 5. 可访问性 (a11y)

### WCAG 2.1 AA 合规事项

| 项目 | 要求 | 实现 |
|------|----------|------|
| 键盘导航 | 所有交互元素均可通过 Tab 访问 | `tabIndex`, `focus-visible` 样式 |
| 屏幕阅读器 | 通知 Phase 状态变化 | Timeline 上使用 `aria-live="polite"` |
| 颜色对比度 | 4.5:1 以上 | 遵循现有 shadcn/ui token |
| 焦点管理 | Phase 完成时将焦点移动到结果卡片 | `useEffect` + `ref.focus()` |
| IME 支持 | 输入韩文时防止 Enter 误触 | `isComposingRef`（现有模式） |
| 错误通知 | 构建失败时通知 | error card 上使用 `role="alert"` |
| 加载状态 | 向屏幕阅读器传递加载状态 | `aria-busy="true"`, `aria-label` |

### Phase Timeline aria 属性

```tsx
<div role="list" aria-label="构建进度">
  <div role="listitem" aria-current={status === 'started' ? 'step' : undefined}>
    <span aria-label={`Phase ${phase.id}: ${phase.label}, ${statusLabel}`} />
  </div>
</div>
```

---

## 6. 深色/浅色模式

所有颜色均基于 CSS 变量（沿用现有 shadcn/ui 系统）：

| 用途 | 浅色 | 深色 |
|------|--------|------|
| 完成徽章 | `bg-emerald-100 text-emerald-700` | `bg-emerald-500/20 text-emerald-400` |
| 错误徽章 | `bg-destructive/10 text-destructive` | 相同（CSS 变量） |
| 添加工具 | `bg-emerald-500/10 text-emerald-600` | 相同（基于 opacity） |
| 移除工具 | `bg-orange-500/10 text-orange-600` | 相同（基于 opacity） |
| 提示词 diff+ | `bg-emerald-500/10 text-emerald-700` | `text-emerald-400` |
| 提示词 diff- | `bg-destructive/10 text-destructive` | 相同 |

基于 opacity 的颜色（`/10`, `/20`）在深色/浅色模式下都能良好工作。

---

## 7. 动画

| 元素 | 动画 | 实现 |
|------|-----------|------|
| Phase 完成切换 | fade + scale | `animate-in fade-in duration-200` |
| 结果卡片出现 | slide up + fade | `animate-in fade-in slide-in-from-bottom-2 duration-300` |
| 子 Agent 加载动画 | spin | `Loader2Icon animate-spin` |
| 流式光标 | pulse | `animate-pulse bg-primary/60`（现有模式） |
| 工具执行徽章 | fade in | `animate-in fade-in duration-200` |

所有动画都遵循 `prefers-reduced-motion: reduce` 媒体查询（Tailwind 默认支持）。

---

## 8. i18n Key 结构

### Builder

```
agent.builder.header
agent.builder.initialQuestion
agent.builder.initialPlaceholder
agent.builder.startButton
agent.builder.resetButton
agent.builder.cancelButton
agent.builder.cancelConfirm
agent.builder.cancelDescription
agent.builder.progress
agent.builder.phase1.label ~ phase7.label
agent.builder.phase1.description ~ phase7.description
agent.builder.status.completed / active / pending / failed
agent.builder.loadingText
agent.builder.confirmTitle
agent.builder.createAgent
agent.builder.draftName / draftDescription / draftModel
agent.builder.includedTools
agent.builder.includedMiddlewares
agent.builder.viewSystemPrompt
agent.builder.error.sessionFailed / generic / buildFailed
agent.builder.phaseLogCompleted
```

### Assistant

```
agent.settings.tabs.assistant
agent.assistant.emptyState
agent.assistant.emptyDescription
agent.assistant.suggestion.polite / addSearch / cost / improvePrompt
agent.assistant.inputPlaceholder
agent.assistant.toolAction.added / removed / modified / replaced
agent.assistant.toolAction.success / failed
agent.assistant.clarifying.submit
agent.assistant.clarifying.customInput
agent.assistant.error.generic
agent.assistant.toast.applied / failed
```

---

## 9. 实现优先级

| 顺序 | 组件 | 原因 |
|------|----------|------|
| 1 | `BuilderTimeline` | 核心 UI，显示 Phase |
| 2 | `BuilderInputSection` | 复用现有代码，快速 |
| 3 | Phase 结果卡片 | SSE 联动前的静态 UI |
| 4 | `stream-builder.ts` | SSE 客户端 |
| 5 | `BuilderPage`（集成） | 组装完整页面 |
| 6 | `BuilderConfirmation` | 最终确认 |
| 7 | `AssistantTab` | 集成设置页标签 |
| 8 | `AssistantChatArea` | 对话区域 |
| 9 | `AssistantToolAction` | 工具执行结果 |
| 10 | `ClarifyingQuestionCard` | 复用 OptionCard |

---

## 10. 现有代码迁移检查清单

- [ ] 将 `OptionCard` 提取到 `components/shared/option-card.tsx`
- [ ] 将 `ToolCard` 提取到 `components/shared/tool-card.tsx`
- [ ] 将 `PhaseTimeline` 提取到 `components/shared/phase-timeline.tsx` 后扩展为 7 阶段
- [ ] 在 `/agents/new` 页面添加 "AI Builder" 选项（位于现有 "对话式创建" 旁）
- [ ] 在设置页 Tabs 中添加 "AI Assistant" 标签
- [ ] `fix-agent-dialog.tsx` → v2 Assistant 完成后删除
- [ ] `conversational/page.tsx` → v2 Builder 完成后删除
