# Chat Scroll Follow Streaming UX Plan

编写日期：2026-06-05

## 目的

为避免长时间 deepagent 执行期间聊天 viewport 抢走用户阅读位置，将 LambChat 的滚动跟随策略按 Moldy 实际基于 assistant-ui 的聊天结构进行移植。

核心目标有以下三点。

1. 当用户停留在底部时，流式响应、工具结果、布局高度变化都持续跟随到底部。
2. 当用户向上滚动开始阅读历史消息或工具日志时，立即解除自动跟随。
3. 当用户点击向下箭头按钮或发送新消息时，明确恢复跟随。

## 仅凭本文档进行开发的方法

本文档编写为无需此前对话上下文也能实现。开发者按以下顺序阅读并工作即可。

1. 在“当前 Moldy 行为诊断”中确认当前代码的起点。
2. 在“要借鉴的策略”中确认产品行为的状态模型与转移规则。
3. 按“实现设计”和“分阶段工作计划”添加或修改文件。
4. 以“实现详细契约”中的函数 signature 和算法为基准编写代码。
5. 以“测试详细契约”中的测试名称和 arrange/act/assert 为基准编写 Vitest。
6. 通过“验收标准”和“手动 QA”后视为工作完成。

目标 repository 为 `/Users/chester/dev/ref/natural-mold`，frontend 工作目录为 `/Users/chester/dev/ref/natural-mold/frontend`。

## 已确认的源码

### Moldy

| 文件 | 当前角色 |
| --- | --- |
| `frontend/src/components/chat/assistant-thread.tsx` | 公共聊天 Thread UI。渲染 `ThreadPrimitive.Viewport`，并在 `onScroll` 中仅计算 `isThreadViewportAtBottom` 来管理向下箭头按钮是否显示。 |
| `frontend/src/components/chat/scroll-bottom.ts` | 基于 `scrollHeight`、`scrollTop`、`clientHeight` 只判断“是否在底部”的小型工具。 |
| `frontend/src/components/chat/__tests__/scroll-bottom.test.ts` | 仅验证 1px rounding、无 overflow、底部/非底部。 |
| `frontend/src/lib/chat/use-chat-runtime.ts` | 将 SSE stream 转换为 assistant-ui `ExternalStoreRuntime` 消息。`content_delta` 通过 rAF batching 更新流式消息内容。 |
| `frontend/src/lib/chat/convert-message.ts` | 将 backend `Message` 转换为 assistant-ui 消息。带 `stream-` prefix 的 assistant 消息会标记为 `metadata.custom.isStreamingMessage = true`。 |
| `frontend/package.json` | `@assistant-ui/react` 为 `^0.12.24`。已按当前安装链接 `@assistant-ui/react@0.12.28` 确认。 |

### LambChat

| 文件 | 可借鉴点 |
| --- | --- |
| `/Users/chester/dev/ref/LambChat/frontend/src/components/layout/AppContent/useMessageScroll.followState.ts` | 将滚动跟随拆分为纯状态转移。核心是 `userScrolledUp`、`autoScrollActive`、`streamLockActive`、`manualDetachFromStream`。 |
| `/Users/chester/dev/ref/LambChat/frontend/src/components/layout/AppContent/messageScrollUtils.ts` | 分离底部/接近/脱离 threshold、user scroll 判定、重复 bottom scroll、streaming finish 判定。 |
| `/Users/chester/dev/ref/LambChat/frontend/src/components/layout/AppContent/useMessageScroll.hook.ts` | 根据 wheel/touch/scroll/resize/layout 变化，将纯状态转移连接到实际 DOM 滚动。 |
| `/Users/chester/dev/ref/LambChat/frontend/src/components/layout/AppContent/__tests__/useMessageScroll.test.ts` | 通过测试固定移动端 detach、桌面端 detach、stream finish settle、explicit scrollToBottom re-entry 等实际体验 UX。 |

## 当前 Moldy 行为诊断

### 当前实现

`AssistantThread` 目前只有以下流程。

```tsx
const [isViewportAtBottom, setIsViewportAtBottom] = useState(true)

const handleViewportScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
  const nextIsAtBottom = isThreadViewportAtBottom(event.currentTarget)
  setIsViewportAtBottom((current) => (current === nextIsAtBottom ? current : nextIsAtBottom))
}, [])
```

然后将这个 handler 连接到 `ThreadPrimitive.Viewport`。

```tsx
<ThreadPrimitive.Viewport
  className="min-h-0 flex-1 overflow-y-auto"
  onScroll={handleViewportScroll}
>
```

下方箭头按钮只调用 `useThreadViewport((v) => v.scrollToBottom)`。

```tsx
function ScrollToBottomButton({ isAtBottom }: { isAtBottom: boolean }) {
  const scrollToBottom = useThreadViewport((v) => v.scrollToBottom)
  // ...
  onClick={() => scrollToBottom()}
}
```

`scroll-bottom.ts` 将距离 1px 以内视为已到底部。

```ts
return Math.abs(scrollHeight - scrollTop - clientHeight) <= 1 || scrollHeight <= clientHeight
```

### assistant-ui 默认行为

当前 `ThreadPrimitive.Viewport` 没有额外传入 props，因此会启用 assistant-ui 默认 auto-scroll。

以已安装的 `@assistant-ui/react@0.12.28` 为准，`ThreadPrimitive.Viewport` 内部使用 `useThreadViewportAutoScroll`。

- 当 `turnAnchor` 为 `"bottom"` 时，`autoScroll` 默认值为 `true`。
- content resize 时，如果 `autoScroll && isAtBottom`，会调用 `scrollToBottom("instant")`。
- run start、initialize、thread switch 时默认也会滚动到底部。
- viewport store 中有 `isAtBottom`、`scrollToBottom`、`onScrollToBottom`。

也就是说，Moldy 只是在 assistant-ui 的默认自动滚动之上，额外叠加了“用于显示按钮的是否到底部”状态。用户向上滚动后，如果 assistant-ui 的 `isAtBottom` 变为 false，content resize auto-scroll 默认会停止，但在 Moldy 代码层面，以下策略仍未被明确固定。

- 没有将用户的 upward wheel/touch 明确视为“取消自动跟随的意图”。
- 没有区分程序产生的 scroll 与用户产生的 scroll。
- 移动端 touch/visual viewport 变化期间，没有 `manualDetachFromStream` 之类的锁。
- streaming assistant 结束时，如果接近底部，没有决定是否执行最后一次 settle scroll。
- 没有验证上述行为的测试。

## 用户问题场景

### 1. 阅读较长 deepagent 日志时，感觉画面被拉回底部

deepagent 会连续出现很长的 tool call、tool result、approval UI、phase timeline、markdown 文本。用户为了阅读中间的工具结果向上滚动，但如果因为新 token 或 tool result 高度变化导致画面持续移动，UX 会明显变差。

仅凭当前 assistant-ui 默认值也能实现部分 detach，但由于没有将其作为 Moldy 的产品策略固化到测试中，未来修改 `ThreadPrimitive.Viewport` props、升级 assistant-ui 版本、改变按钮状态或 builder variant 时都很容易回归。

### 2. 在移动端，只要开始触摸就意味着产生了阅读意图

LambChat 在移动端 active stream 期间，只要出现 `touchstart` 或明确的 upward gesture，就会启用 `manualDetachFromStream`。原因是移动端经常发生键盘、safe area、visual viewport resize 变化，如果用户刚把手放上去，passive bottom scroll 又重新开启跟随，就会产生“我已经抓住画面，却又被拖走”的感觉。

Moldy 的移动端 builder/chat 画面都使用同一个 `AssistantThread`，因此适合共用这项策略。

### 3. 发送新消息始终是一个新的跟随周期

即使用户在上一条回复中处于 detach 状态，发送新消息后也应该移动到最新 turn。LambChat 测试中的 `local send clears the detach lock and starts a fresh follow cycle` 就属于这一场景。

在 Moldy 中，`useChatRuntime.onNew`、`onResumeDecisions`、`sendMessage`、edit/regenerate 都可能启动新的 stream。UI 侧可以观察 assistant-ui `thread.messages` 最后 appended user message 或 `thread.isRunning` 的切换来启动 bottom scroll。

## 要借鉴的策略

### 状态模型

基本沿用 LambChat 的状态名称，但文件/类型名按照 Moldy 的语境调整。

```ts
export interface ThreadScrollFollowState {
  userScrolledUp: boolean
  autoScrollActive: boolean
  streamLockActive: boolean
  manualDetachFromStream: boolean
}
```

各字段含义如下。

| 字段 | 含义 |
| --- | --- |
| `userScrolledUp` | 用户当前没有跟随回复，而是在阅读上方内容。阻止 message update auto-scroll。 |
| `autoScrollActive` | 当前 bottom scroll loop 正在运行。即使 layout height 发生变化也应跟随底部。 |
| `streamLockActive` | assistant stream 处于 active 时需要维持 bottom follow。用于长时间 streaming 中高度持续变化的情况。 |
| `manualDetachFromStream` | 尤其在移动端，用户手动从 active stream detach。不能因 passive resize 或 near-bottom 判定而自动重新连接。只能通过 explicit scrollToBottom 或新的 local send 解除。 |

### 核心状态转移

| 事件 | 转移 |
| --- | --- |
| viewport 到达底部 | `userScrolledUp=false`。但不解除 `manualDetachFromStream`。 |
| 点击 explicit scrollToBottom | `userScrolledUp=false`、`autoScrollActive=true`，若为 active stream 则 `streamLockActive=true`，`manualDetachFromStream=false`。 |
| append 新 user message | 解除 detach lock 并移动到底部。 |
| active stream 中 upward wheel/touch/scroll | `userScrolledUp=true`、`autoScrollActive=false`、`streamLockActive=false`。若为移动端则 `manualDetachFromStream=true`。 |
| streaming assistant finish + 接近底部 + 非 detach | 为最后一次布局 settle 执行 `request-scroll-to-bottom`。 |
| streaming assistant finish + detach 状态 | 不执行任何 scroll。 |
| viewport resize/layout change | 仅在非 detach 且 follow active 或 near bottom 时执行 bottom scroll。 |

## 实现设计

### 文件结构

建议的文件结构如下。

| 文件 | 工作 |
| --- | --- |
| `frontend/src/components/chat/scroll-bottom.ts` | 保留现有 `isThreadViewportAtBottom`。新增 distance/near-bottom/away-from-bottom helper。 |
| `frontend/src/components/chat/scroll-follow-state.ts` | 新增对应 LambChat `useMessageScroll.followState.ts` 的纯状态转移工具。 |
| `frontend/src/components/chat/use-thread-scroll-follow.ts` | 新增连接 assistant-ui viewport、`useAuiState`、DOM event、ResizeObserver 的 React hook。 |
| `frontend/src/components/chat/assistant-thread.tsx` | 用 hook 结果替换现有 `isViewportAtBottom` state 和 `handleViewportScroll`。让 `ThreadPrimitive.Viewport` props 符合 controlled policy。 |
| `frontend/src/components/chat/__tests__/scroll-follow-state.test.ts` | 新增纯状态转移测试。移植 LambChat 测试中适合 Moldy 的用例。 |
| `frontend/tests/components/chat/assistant-thread-scroll-follow.test.tsx` | 新增基于 assistant-ui mock 的 component integration 测试。 |

### 扩展 `scroll-bottom.ts`

保留当前函数。现有测试不能被破坏。

新增以下程度的 helper 就足够了。

```ts
export function getThreadViewportDistanceFromBottom(metrics: ThreadViewportScrollMetrics): number {
  return Math.max(0, metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight)
}

export function isThreadViewportNearBottom(
  metrics: ThreadViewportScrollMetrics,
  thresholdPx: number,
): boolean {
  return metrics.scrollHeight <= metrics.clientHeight ||
    getThreadViewportDistanceFromBottom(metrics) <= thresholdPx
}

export function isThreadViewportAwayFromBottom(
  metrics: ThreadViewportScrollMetrics,
  thresholdPx: number,
): boolean {
  return getThreadViewportDistanceFromBottom(metrics) > thresholdPx
}
```

建议 threshold：

| 项目 | Desktop | Mobile | 原因 |
| --- | --- | --- | --- |
| exact bottom | 1px | 1px | 保持当前行为。按钮显示适合采用严格的底部判定。 |
| near bottom | 48px | 120px | 移动端 safe area/keyboard/手指滚动误差更大。与 LambChat 的 `getAutoScrollResumeThresholdPx` 类似。 |
| away from bottom | 16px | 50px 以上 | 判断用户是否真正离开底部，而非轻微 rounding。 |

### `scroll-follow-state.ts`

纯工具函数不要感知 React 和 DOM。这样才能像 LambChat 一样用小型测试固定 UX 策略。

主要 export：

```ts
export type ThreadScrollUpdateAction =
  | 'scroll-to-bottom'
  | 'request-scroll-to-bottom'
  | null

export interface ThreadScrollMessageLike {
  id: string
  role?: string
  isStreaming?: boolean
}

export function createThreadScrollFollowState(
  overrides?: Partial<ThreadScrollFollowState>,
): ThreadScrollFollowState

export function getNextThreadScrollFollowStateForAtBottomChange(...)
export function getNextThreadScrollFollowStateForBottomScroll(...)
export function getNextThreadScrollFollowStateForUserIntent(...)
export function getNextThreadScrollFollowStateForUserGesture(...)
export function getNextThreadScrollFollowStateForUserScroll(...)

export function getThreadMessageUpdateScrollAction(...)
export function didLatestStreamingAssistantFinish(...)
export function hasNewOutgoingMessage(...)
export function shouldStopAutoScrollOnUserScroll(...)
```

针对 Moldy 的差异：

- LambChat 还会同时处理 `isLoadingHistory`、`pendingHistoryScroll`、external navigation。Moldy 第 1 阶段范围中排除这些内容。
- LambChat 使用 Virtuoso，但 Moldy 使用 assistant-ui viewport div。纯状态转移保持一致，scroll runner 单独编写。
- Moldy 的 streaming 状态优先使用 assistant-ui `message.status.type === 'running'`，并将 `metadata.custom.isStreamingMessage` 作为辅助信号。

### `use-thread-scroll-follow.ts`

hook 在 `AssistantThread` 内调用。

建议 interface：

```ts
interface UseThreadScrollFollowOptions {
  sessionKey?: string | null
}

interface UseThreadScrollFollowReturn {
  viewportRef: RefCallback<HTMLDivElement>
  isViewportAtBottom: boolean
  handleViewportScroll: (event: UIEvent<HTMLDivElement>) => void
  handleViewportWheel: (event: WheelEvent<HTMLDivElement>) => void
  handleViewportTouchStart: (event: TouchEvent<HTMLDivElement>) => void
  handleViewportTouchMove: (event: TouchEvent<HTMLDivElement>) => void
  handleViewportTouchEnd: () => void
  scrollToBottom: () => void
}
```

实现中要使用的 assistant-ui state：

```ts
const threadMessages = useAuiState((s) =>
  s.thread.messages.map((message) => ({
    id: message.id,
    role: message.role,
    isStreaming:
      message.role === 'assistant' &&
      (
        message.status?.type === 'running' ||
        message.metadata?.custom?.isStreamingMessage === true
      ),
  })),
)

const threadIsRunning = useAuiState((s) => s.thread.isRunning)
const requestAssistantUiScrollToBottom = useThreadViewport((v) => v.scrollToBottom)
```

`sessionKey` 默认使用 `conversationId ?? '__local_thread__'`。conversation 切换时 reset follow state。

### 控制 assistant-ui auto-scroll

引入自定义策略后，为避免与 assistant-ui 默认的 content resize auto-scroll 冲突，应将 `ThreadPrimitive.Viewport` 设为 controlled。

建议 props：

```tsx
<ThreadPrimitive.Viewport
  ref={viewportRef}
  className="min-h-0 flex-1 overflow-y-auto"
  autoScroll={false}
  scrollToBottomOnRunStart={false}
  onScroll={handleViewportScroll}
  onWheel={handleViewportWheel}
  onTouchStart={handleViewportTouchStart}
  onTouchMove={handleViewportTouchMove}
  onTouchEnd={handleViewportTouchEnd}
  onTouchCancel={handleViewportTouchEnd}
>
```

初始 history load 和 thread switch 在第 1 阶段实现中可从以下方案中选择一个。

1. `scrollToBottomOnInitialize` 和 `scrollToBottomOnThreadSwitch` 保持 assistant-ui 默认值。
2. 关闭所有自动选项，在 `sessionKey` 变化的 effect 中直接 bottom scroll。

建议采用方案 2。因为 scroll follow 策略可以集中在一处，也更容易编写 session reset 测试。

```tsx
scrollToBottomOnInitialize={false}
scrollToBottomOnThreadSwitch={false}
```

但这种情况下，需要通过 component test 和手动验证确认空状态/初始加载/对话切换时确实仍会移动到底部。

### bottom scroll runner

如果只调用一次 `scrollToBottom()`，可能会被 streaming markdown、tool result、图片/代码块、approval card 的高度变化顶开。应像 LambChat 一样设置一个短时重复 runner。

Moldy 用的 runner 不需要 Virtuoso API。只使用 viewport div 和 assistant-ui `scrollToBottom`。

```ts
function forceThreadViewportToBottom(viewport: HTMLElement | null) {
  if (!viewport) return
  viewport.scrollTop = viewport.scrollHeight
}
```

runner 策略：

- 启动后立即同时执行 assistant-ui `scrollToBottom({ behavior: 'auto' })` 和 direct `scrollTop = scrollHeight`。
- 通过 `ignoreProgrammaticScrollUntilRef.current = Date.now() + 120`，避免将下一次 scroll event 误判为用户 scroll。
- interval 约为 desktop 16ms、mobile 20ms。
- 默认 max duration 为 240-500ms，如果 stream lock active，则在 height change 期间 keep-alive。
- 如果 `shouldAbort` 为 `userScrolledUpRef.current === true`，则立即中断。
- 如果可用 ResizeObserver，就 observe viewport 的第一个 content child。否则只使用 interval。

### 按钮行为

当前 `ScrollToBottomButton` 在内部直接读取 `useThreadViewport`。使用 controlled hook 后，按钮应该只接收命令。

变更前：

```tsx
<ScrollToBottomButton isAtBottom={isViewportAtBottom} />
```

变更后：

```tsx
<ScrollToBottomButton
  isAtBottom={isViewportAtBottom}
  onScrollToBottom={scrollToBottom}
/>
```

`scrollToBottom` 应该是一个会 clear `manualDetachFromStream` 的 explicit action。passive resize 或 near-bottom 判定不能 clear 这个 lock。

## 分阶段工作计划

### Phase 1. 纯工具和测试

工作：

- 在 `scroll-bottom.ts` 中新增 distance/near/away helper。
- 新增 `scroll-follow-state.ts`。
- 将 LambChat 测试中的以下用例移植为 Moldy 风格的 Vitest。

必测项：

| 测试 | 预期 |
| --- | --- |
| at bottom change clears `userScrolledUp` | 到达底部时，只 clear 用户向上滚动过的 flag。 |
| mobile upward scroll detaches active stream | `manualDetachFromStream=true`, `autoScrollActive=false`, `streamLockActive=false`. |
| mobile touchstart detaches immediately | active stream follow 期间，仅开始 touch 就 detach。 |
| desktop upward wheel detaches without manual mobile lock | `userScrolledUp=true`, `manualDetachFromStream=false`. |
| detached stream finish does not scroll | `getThreadMessageUpdateScrollAction` 为 `null`。 |
| stream finish near bottom settles | 非 detach 且仍维持 stream lock 时，执行 `request-scroll-to-bottom`。 |
| explicit scrollToBottom clears detach | `manualDetachFromStream=false`，恢复 follow。 |
| local send clears detach | append 新 user message 时执行 `scroll-to-bottom`。 |
| passive bottom scroll does not clear mobile detach lock | 当 `clearManualDetachFromStream=false` 时维持 lock。 |

验证命令：

```bash
cd frontend
pnpm vitest run src/components/chat/__tests__/scroll-bottom.test.ts src/components/chat/__tests__/scroll-follow-state.test.ts
```

### Phase 2. Hook 集成

工作：

- 新增 `use-thread-scroll-follow.ts`。
- 用 hook 替换 `AssistantThread` 的 local `isViewportAtBottom` state 和 `handleViewportScroll`。
- 在 `ThreadPrimitive.Viewport` 上连接 `ref`、`autoScroll={false}`、scroll/touch/wheel handler。
- 为 `ScrollToBottomButton` 新增 `onScrollToBottom` prop。
- 将 `conversationId` 作为 `sessionKey` 传入，以便对话切换时 reset。

注意：

- 如果在 `useAuiState` selector 中原样返回整个 `s.thread.messages` 对象，每个 token 都可能造成大量不必要的 rerender。只 projection `id`、`role`、`status.type`、`metadata.custom.isStreamingMessage`。
- `scrollToBottom` 调用通过 rAF 延迟一次，在 DOM 绘制新消息后再执行。
- 程序 scroll 后立即发生的 `scroll` event 通过 `ignoreProgrammaticScrollUntilRef` 忽略。

### Phase 3. Component integration test

现有测试 mock 中，`ThreadPrimitive.Viewport` 只是接收 `className` 和 `children` 的 passthrough，不足以验证 scroll event。新测试文件中应创建单独的 mock，或增强现有 mock。

需要验证的项目：

| 测试 | 预期 |
| --- | --- |
| viewport receives controlled auto-scroll props | `autoScroll=false`, `scrollToBottomOnRunStart=false`. |
| not-at-bottom shows button | 操作 `scrollHeight/clientHeight/scrollTop` 后 button visible。 |
| clicking button calls hook scroll action | 确认调用 mock `scrollToBottom` 或 direct viewport scroll。 |
| upward wheel while running keeps button visible and prevents auto re-entry | state 保持 detached。 |
| sessionKey change resets bottom state | conversationId 变化后初始化 bottom state。 |

验证命令：

```bash
cd frontend
pnpm vitest run tests/components/chat/assistant-thread-scroll-follow.test.tsx
```

### Phase 4. 手动 QA 与 Playwright 候选

手动 QA 场景：

1. 在普通 conversation 画面启动一个较长回复。
2. 回复过程中向上滚动，阅读之前的 tool result。
3. 确认即使新 token/工具结果持续到达，画面也不会被拉到底部。
4. 按下下方箭头按钮后，确认会移动到最新回复底部，并继续跟随。
5. 在 builder variant 中重复相同场景。
6. 在移动端 viewport 中 touchstart/touchmove 后，确认不会发生自动重新连接。
7. 发送新消息后，确认无论之前是否 detach，都移动到最新 turn。

Playwright 自动化候选：

- 配置 mock SSE endpoint，使其按固定间隔输出较长的 `content_delta`。
- 用户向上滚动 viewport 后，assert `scrollTop` 不会被任意增加。
- button click 后，assert `scrollTop + clientHeight` 接近 `scrollHeight`。

## 验收标准

功能验收标准：

- 用户在 active stream 中向上滚动后，后续 streaming text/tool UI height 变化不会把 viewport 拉到底部。
- 用户点击下方箭头后，detach lock 被解除，active stream follow 恢复。
- 当新 user message、edit、regenerate、HITL resume 启动新 run 时，会开始 fresh follow cycle。
- 在移动端，可通过 touchstart/touchmove 从 active stream detach，且 passive viewport resize 不会解除 lock。
- 保留现有下方箭头按钮的无障碍属性（`aria-label`、`aria-hidden`、`tabIndex`、disabled）。

测试验收标准：

- `scroll-bottom.test.ts` 现有测试通过。
- `scroll-follow-state.test.ts` 覆盖从 LambChat 借鉴的核心状态转移。
- `assistant-thread` component test 覆盖 controlled viewport props 和 button 重新连接路径。
- 全部 `pnpm vitest run` 或至少聊天相关测试通过。

## 非范围

本次工作不做以下内容：

- 引入 Virtuoso。Moldy 继续使用 assistant-ui viewport。
- 修改 backend SSE protocol。
- 引入 message virtualization。
- 移植 LambChat 的 external navigation/reveal_file anchor scroll。
- history pagination 的最终滚动策略。如果 Moldy 另行实现 history loading UX，再用后续文档处理。
- nested subagent anchor navigation。不过，基于 ResizeObserver 的 bottom runner 应把 nested tool/subagent panel 的高度变化也当作普通 layout change 处理。

## 风险与应对

| 风险 | 应对 |
| --- | --- |
| assistant-ui 版本变化后，`useAuiState((s) => s.thread.messages)` shape 可能改变 | 本文以当前安装的 `@assistant-ui/react@0.12.28` 为准。实现时优先确认类型错误，并尽量减少 selector projection。 |
| 关闭 assistant-ui 默认 auto-scroll 后，初始加载/对话切换的 bottom 移动可能丢失 | 用 `sessionKey` reset effect 和 component test 补足。必要时可设置 fallback，仅对 initialize/threadSwitch 保留 assistant-ui 默认值。 |
| 每个 token 都导致 messages projection 变化，rerender 可能增加 | selector 只返回必要 primitive，scroll action 判定通过 `previousMessagesRef` 与 cheap snapshot 比较完成。 |
| direct `scrollTop = scrollHeight` 与 assistant-ui `scrollToBottom` 重复调用可能造成跳动 | 设置 programmatic scroll ignore window，并统一使用默认 `auto` behavior。 |
| 移动端 touchstart detach 可能过于敏感 | 仅在 active stream follow 状态应用 touchstart detach。没有 stream 或 follow 已关闭时不改变状态。 |
| near-bottom threshold 可能与按钮显示冲突 | 按钮显示继续使用现有 exact bottom 标准，仅在 auto-scroll 恢复/settle 判定中使用 near-bottom threshold。 |

## 建议实现顺序摘要

1. 创建 `scroll-follow-state.ts`，先用 Moldy/Vitest 固定 LambChat 的纯状态转移测试。
2. 扩展 `scroll-bottom.ts`，同时保持现有 exact bottom 行为。
3. 在 `use-thread-scroll-follow.ts` 中连接 assistant-ui `useAuiState`、`useThreadViewport`、viewport ref、wheel/touch/scroll event。
4. 将 hook 接入 `AssistantThread`，并把 `ThreadPrimitive.Viewport` 切换为 controlled auto-scroll。
5. 将 `ScrollToBottomButton` 改为基于 prop，使按钮点击成为 explicit re-entry。
6. 通过 component test 和手动 QA 确认 default/builder/mobile 流程。

## 实现详细契约

本节定义各文件契约，使实际实现者只看文档也能编写代码。代码块接近完整代码，但 import 排序和类型收窄应根据实际 TypeScript 错误调整。

### 1. `scroll-bottom.ts`

保留现有 `isThreadViewportAtBottom` 函数的名称和含义。在同一文件中新增以下 helper。

```ts
export interface ThreadViewportScrollMetrics {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
}

export function isThreadViewportAtBottom({
  scrollHeight,
  scrollTop,
  clientHeight,
}: ThreadViewportScrollMetrics): boolean {
  return Math.abs(scrollHeight - scrollTop - clientHeight) <= 1 || scrollHeight <= clientHeight
}

export function getThreadViewportDistanceFromBottom({
  scrollHeight,
  scrollTop,
  clientHeight,
}: ThreadViewportScrollMetrics): number {
  return Math.max(0, scrollHeight - scrollTop - clientHeight)
}

export function isThreadViewportNearBottom(
  metrics: ThreadViewportScrollMetrics,
  thresholdPx: number,
): boolean {
  return (
    metrics.scrollHeight <= metrics.clientHeight ||
    getThreadViewportDistanceFromBottom(metrics) <= thresholdPx
  )
}

export function isThreadViewportAwayFromBottom(
  metrics: ThreadViewportScrollMetrics,
  thresholdPx: number,
): boolean {
  return getThreadViewportDistanceFromBottom(metrics) > thresholdPx
}
```

新增测试放入 `frontend/src/components/chat/__tests__/scroll-bottom.test.ts`。

- `getThreadViewportDistanceFromBottom` 在普通 overflow 情况下返回剩余 px。
- content 小于 viewport 时视为 near bottom。
- 在 threshold 内时视为 near bottom。
- 超出 threshold 时视为 away from bottom。

### 2. `scroll-follow-state.ts`

新文件：`frontend/src/components/chat/scroll-follow-state.ts`

该文件不能有 React import。状态转移保持为纯函数。

```ts
export type ThreadScrollUpdateAction = 'scroll-to-bottom' | 'request-scroll-to-bottom' | null

export interface ThreadScrollMessageLike {
  id: string
  role?: string
  isStreaming?: boolean
}

export interface ThreadScrollFollowState {
  userScrolledUp: boolean
  autoScrollActive: boolean
  streamLockActive: boolean
  manualDetachFromStream: boolean
}

export function createThreadScrollFollowState(
  overrides: Partial<ThreadScrollFollowState> = {},
): ThreadScrollFollowState {
  return {
    userScrolledUp: false,
    autoScrollActive: false,
    streamLockActive: false,
    manualDetachFromStream: false,
    ...overrides,
  }
}
```

bottom 到达转移：

```ts
export function getNextThreadScrollFollowStateForAtBottomChange({
  state,
  atBottom,
}: {
  state: ThreadScrollFollowState
  atBottom: boolean
}): ThreadScrollFollowState {
  if (!atBottom) return state
  return {
    ...state,
    userScrolledUp: false,
  }
}
```

显式或 passive bottom scroll 转移：

```ts
export function getNextThreadScrollFollowStateForBottomScroll({
  state,
  streamingAssistantActive,
  clearManualDetachFromStream = false,
}: {
  state: ThreadScrollFollowState
  streamingAssistantActive: boolean
  clearManualDetachFromStream?: boolean
}): ThreadScrollFollowState {
  if (state.manualDetachFromStream && !clearManualDetachFromStream) {
    return state
  }

  return {
    ...state,
    userScrolledUp: false,
    autoScrollActive: true,
    streamLockActive: streamingAssistantActive,
    manualDetachFromStream: clearManualDetachFromStream
      ? false
      : state.manualDetachFromStream,
  }
}
```

用户意图与 gesture 转移：

```ts
function hasActiveStreamFollow({
  state,
  streamingAssistantActive,
}: {
  state: ThreadScrollFollowState
  streamingAssistantActive: boolean
}): boolean {
  return state.autoScrollActive || (state.streamLockActive && streamingAssistantActive)
}

export function getNextThreadScrollFollowStateForUserIntent({
  state,
  isMobileViewport,
  streamingAssistantActive,
}: {
  state: ThreadScrollFollowState
  isMobileViewport: boolean
  streamingAssistantActive: boolean
}): ThreadScrollFollowState {
  if (!hasActiveStreamFollow({ state, streamingAssistantActive })) return state

  return {
    ...state,
    userScrolledUp: true,
    autoScrollActive: false,
    streamLockActive: false,
    manualDetachFromStream:
      state.manualDetachFromStream || (isMobileViewport && streamingAssistantActive),
  }
}

export const getNextThreadScrollFollowStateForUserGesture =
  getNextThreadScrollFollowStateForUserIntent
```

用户 scroll 转移：

```ts
export function shouldStopAutoScrollOnUserScroll({
  autoScrollActive,
  programmaticScroll,
  movedUp,
  isAwayFromBottom,
  deltaScrollPx,
}: {
  isMobileViewport: boolean
  autoScrollActive: boolean
  programmaticScroll: boolean
  movedUp: boolean
  isAwayFromBottom: boolean
  deltaScrollPx: number
  scrollTop: number
}): boolean {
  if (!autoScrollActive || programmaticScroll || !movedUp) return false
  if (isAwayFromBottom) return true
  return deltaScrollPx > 6
}

export function getNextThreadScrollFollowStateForUserScroll({
  state,
  isMobileViewport,
  streamingAssistantActive,
  programmaticScroll,
  movedUp,
  isAwayFromBottom,
  deltaScrollPx,
  scrollTop,
}: {
  state: ThreadScrollFollowState
  isMobileViewport: boolean
  streamingAssistantActive: boolean
  programmaticScroll: boolean
  movedUp: boolean
  isAwayFromBottom: boolean
  deltaScrollPx: number
  scrollTop: number
}): ThreadScrollFollowState {
  const autoScrollActive = hasActiveStreamFollow({ state, streamingAssistantActive })

  if (
    !shouldStopAutoScrollOnUserScroll({
      isMobileViewport,
      autoScrollActive,
      programmaticScroll,
      movedUp,
      isAwayFromBottom,
      deltaScrollPx,
      scrollTop,
    })
  ) {
    return state
  }

  return {
    ...state,
    userScrolledUp: true,
    autoScrollActive: false,
    streamLockActive: false,
    manualDetachFromStream:
      state.manualDetachFromStream || (isMobileViewport && streamingAssistantActive),
  }
}
```

由消息变化触发的 scroll action：

```ts
export function hasNewOutgoingMessage(
  previousMessages: ThreadScrollMessageLike[],
  nextMessages: ThreadScrollMessageLike[],
): boolean {
  if (
    nextMessages.length <= previousMessages.length ||
    nextMessages.length - previousMessages.length > 2
  ) {
    return false
  }

  const appendedMessages = nextMessages.slice(previousMessages.length)
  return appendedMessages[0]?.role === 'user'
}

export function didLatestStreamingAssistantFinish({
  previousMessages,
  nextMessages,
}: {
  previousMessages: ThreadScrollMessageLike[]
  nextMessages: ThreadScrollMessageLike[]
}): boolean {
  const previousLatestMessage = previousMessages[previousMessages.length - 1]
  const nextLatestMessage = nextMessages[nextMessages.length - 1]

  return (
    previousLatestMessage?.id === nextLatestMessage?.id &&
    previousLatestMessage?.role === 'assistant' &&
    nextLatestMessage?.role === 'assistant' &&
    previousLatestMessage.isStreaming === true &&
    nextLatestMessage.isStreaming === false
  )
}

function shouldAutoScrollForMessageUpdate({
  previousMessages,
  nextMessages,
  userScrolledUp,
  autoScrollActive,
  isNearBottom,
  isLoadingHistory = false,
  shouldMaintainStreamLock = false,
  manualDetachActive = false,
}: {
  previousMessages: ThreadScrollMessageLike[]
  nextMessages: ThreadScrollMessageLike[]
  userScrolledUp: boolean
  autoScrollActive: boolean
  isNearBottom: boolean
  isLoadingHistory?: boolean
  shouldMaintainStreamLock?: boolean
  manualDetachActive?: boolean
}): boolean {
  if (userScrolledUp || nextMessages.length === 0 || isLoadingHistory) return false
  if (!autoScrollActive && !isNearBottom && !shouldMaintainStreamLock) return false

  const previousLatestMessage = previousMessages[previousMessages.length - 1]
  const nextLatestMessage = nextMessages[nextMessages.length - 1]
  const appendedMessageCount = nextMessages.length - previousMessages.length

  if (nextLatestMessage?.role !== 'assistant') return false

  const latestChanged = nextLatestMessage.id !== previousLatestMessage?.id
  const latestContinued =
    nextLatestMessage.id === previousLatestMessage?.id &&
    previousLatestMessage?.role === 'assistant'

  if (latestChanged) {
    return !manualDetachActive && appendedMessageCount === 1
  }

  if (
    latestContinued &&
    previousLatestMessage?.isStreaming === true &&
    nextLatestMessage.isStreaming === false
  ) {
    return (
      !manualDetachActive &&
      (autoScrollActive || isNearBottom || shouldMaintainStreamLock)
    )
  }

  if (latestContinued) {
    return (
      !manualDetachActive &&
      nextLatestMessage.isStreaming !== false &&
      !autoScrollActive &&
      (isNearBottom || shouldMaintainStreamLock)
    )
  }

  return false
}

export function getThreadMessageUpdateScrollAction({
  previousMessages,
  nextMessages,
  state,
  isNearBottom,
  isLoadingHistory = false,
  shouldMaintainStreamLock,
}: {
  previousMessages: ThreadScrollMessageLike[]
  nextMessages: ThreadScrollMessageLike[]
  state: ThreadScrollFollowState
  isNearBottom: boolean
  isLoadingHistory?: boolean
  shouldMaintainStreamLock?: boolean
}): ThreadScrollUpdateAction {
  if (hasNewOutgoingMessage(previousMessages, nextMessages)) {
    return 'scroll-to-bottom'
  }

  if (
    shouldAutoScrollForMessageUpdate({
      previousMessages,
      nextMessages,
      userScrolledUp: state.userScrolledUp,
      autoScrollActive: state.autoScrollActive,
      isNearBottom,
      isLoadingHistory,
      shouldMaintainStreamLock,
      manualDetachActive: state.manualDetachFromStream,
    })
  ) {
    return 'request-scroll-to-bottom'
  }

  return null
}
```

### 3. `use-thread-scroll-follow.ts`

新文件：`frontend/src/components/chat/use-thread-scroll-follow.ts`

该 hook 只在 `AssistantThread` 中调用。由于必须在 assistant-ui context 内运行，不能移到 `ThreadPrimitive.Root` 外部。

必需 import：

```ts
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefCallback,
  type TouchEvent as ReactTouchEvent,
  type UIEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react'
import { useAuiState, useThreadViewport } from '@assistant-ui/react'
import {
  getThreadViewportDistanceFromBottom,
  isThreadViewportAtBottom,
  isThreadViewportAwayFromBottom,
  isThreadViewportNearBottom,
} from '@/components/chat/scroll-bottom'
import {
  createThreadScrollFollowState,
  getNextThreadScrollFollowStateForAtBottomChange,
  getNextThreadScrollFollowStateForBottomScroll,
  getNextThreadScrollFollowStateForUserGesture,
  getNextThreadScrollFollowStateForUserIntent,
  getNextThreadScrollFollowStateForUserScroll,
  getThreadMessageUpdateScrollAction,
  type ThreadScrollFollowState,
  type ThreadScrollMessageLike,
} from '@/components/chat/scroll-follow-state'
```

hook interface:

```ts
export interface UseThreadScrollFollowOptions {
  sessionKey?: string | null
}

export interface UseThreadScrollFollowReturn {
  viewportRef: RefCallback<HTMLDivElement>
  isViewportAtBottom: boolean
  handleViewportScroll: (event: UIEvent<HTMLDivElement>) => void
  handleViewportWheel: (event: ReactWheelEvent<HTMLDivElement>) => void
  handleViewportTouchStart: (event: ReactTouchEvent<HTMLDivElement>) => void
  handleViewportTouchMove: (event: ReactTouchEvent<HTMLDivElement>) => void
  handleViewportTouchEnd: () => void
  scrollToBottom: () => void
}
```

常量：

```ts
const MOBILE_BREAKPOINT_PX = 640
const MOBILE_NEAR_BOTTOM_PX = 120
const DESKTOP_NEAR_BOTTOM_PX = 48
const MOBILE_AWAY_FROM_BOTTOM_PX = 50
const DESKTOP_AWAY_FROM_BOTTOM_PX = 16
const PROGRAMMATIC_SCROLL_IGNORE_MS = 120
```

viewport helper:

```ts
function isMobileViewport(): boolean {
  return typeof window !== 'undefined' && window.innerWidth < MOBILE_BREAKPOINT_PX
}

function getNearBottomThresholdPx(): number {
  return isMobileViewport() ? MOBILE_NEAR_BOTTOM_PX : DESKTOP_NEAR_BOTTOM_PX
}

function getAwayFromBottomThresholdPx(): number {
  return isMobileViewport() ? MOBILE_AWAY_FROM_BOTTOM_PX : DESKTOP_AWAY_FROM_BOTTOM_PX
}
```

assistant-ui message projection:

```ts
const threadMessages = useAuiState((s) =>
  s.thread.messages.map((message) => ({
    id: message.id,
    role: message.role,
    isStreaming:
      message.role === 'assistant' &&
      (message.status?.type === 'running' ||
        message.metadata?.custom?.isStreamingMessage === true),
  })),
)
```

hook 内部 refs：

```ts
const viewportElementRef = useRef<HTMLDivElement | null>(null)
const previousMessagesRef = useRef<ThreadScrollMessageLike[]>([])
const followStateRef = useRef<ThreadScrollFollowState>(createThreadScrollFollowState())
const isNearBottomRef = useRef(true)
const streamingAssistantActiveRef = useRef(false)
const ignoreProgrammaticScrollUntilRef = useRef(0)
const lastScrollTopRef = useRef(0)
const touchStartYRef = useRef<number | null>(null)
const scrollTimerCleanupRef = useRef<(() => void) | null>(null)
const sessionKeyRef = useRef<string | null | undefined>(sessionKey)
const [isViewportAtBottom, setIsViewportAtBottom] = useState(true)
```

ref callback:

```ts
const viewportRef = useCallback<RefCallback<HTMLDivElement>>((node) => {
  viewportElementRef.current = node
  if (node) {
    lastScrollTopRef.current = node.scrollTop
    const atBottom = isThreadViewportAtBottom(node)
    const nearBottom = isThreadViewportNearBottom(node, getNearBottomThresholdPx())
    setIsViewportAtBottom(atBottom)
    isNearBottomRef.current = nearBottom
  }
}, [])
```

state 应用 helper：

```ts
const applyFollowState = useCallback((nextState: ThreadScrollFollowState) => {
  const previousState = followStateRef.current
  followStateRef.current = nextState
  if (previousState.autoScrollActive && !nextState.autoScrollActive) {
    scrollTimerCleanupRef.current?.()
    scrollTimerCleanupRef.current = null
  }
}, [])
```

bottom scroll runner 在第 1 阶段实现中可以降低复杂度。最小契约如下。

```ts
const requestAssistantUiScrollToBottom = useThreadViewport((v) => v.scrollToBottom)

const forceViewportToBottom = useCallback(() => {
  const viewport = viewportElementRef.current
  requestAssistantUiScrollToBottom({ behavior: 'auto' })
  if (viewport) {
    viewport.scrollTop = viewport.scrollHeight
  }
  ignoreProgrammaticScrollUntilRef.current = Date.now() + PROGRAMMATIC_SCROLL_IGNORE_MS
}, [requestAssistantUiScrollToBottom])
```

重复 runner 契约：

```ts
const startScrollToBottomLoop = useCallback(() => {
  scrollTimerCleanupRef.current?.()
  let attempts = 0
  let stopped = false
  const startedAt = Date.now()

  const tick = () => {
    if (stopped) return
    const viewport = viewportElementRef.current
    if (!viewport) return

    if (followStateRef.current.userScrolledUp) {
      stopped = true
      return
    }

    forceViewportToBottom()
    attempts += 1

    const atBottom = isThreadViewportAtBottom(viewport)
    const keepAlive =
      followStateRef.current.streamLockActive && streamingAssistantActiveRef.current
    const exceeded = attempts >= 20 || Date.now() - startedAt > 600

    if (atBottom && !keepAlive) {
      stopped = true
      followStateRef.current = {
        ...followStateRef.current,
        autoScrollActive: false,
      }
      return
    }

    if (exceeded && !keepAlive) {
      stopped = true
      followStateRef.current = {
        ...followStateRef.current,
        autoScrollActive: false,
      }
    }
  }

  const timer = window.setInterval(tick, isMobileViewport() ? 20 : 16)
  tick()

  scrollTimerCleanupRef.current = () => {
    stopped = true
    window.clearInterval(timer)
  }
}, [forceViewportToBottom])
```

explicit bottom action:

```ts
const requestBottomScroll = useCallback(
  ({ clearManualDetachFromStream }: { clearManualDetachFromStream: boolean }) => {
    const nextState = getNextThreadScrollFollowStateForBottomScroll({
      state: followStateRef.current,
      streamingAssistantActive: streamingAssistantActiveRef.current,
      clearManualDetachFromStream,
    })

    if (nextState === followStateRef.current) return

    applyFollowState(nextState)
    startScrollToBottomLoop()
  },
  [applyFollowState, startScrollToBottomLoop],
)

const scrollToBottom = useCallback(() => {
  requestBottomScroll({ clearManualDetachFromStream: true })
}, [requestBottomScroll])
```

scroll handler:

```ts
const handleViewportScroll = useCallback(
  (event: UIEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget
    const now = Date.now()
    const scrollTop = viewport.scrollTop
    const previousScrollTop = lastScrollTopRef.current
    const movedUp = scrollTop < previousScrollTop - 2
    const upwardScrollPx = Math.max(0, previousScrollTop - scrollTop)
    const programmaticScroll = now <= ignoreProgrammaticScrollUntilRef.current
    const atBottom = isThreadViewportAtBottom(viewport)
    const nearBottom = isThreadViewportNearBottom(viewport, getNearBottomThresholdPx())
    const awayFromBottom = isThreadViewportAwayFromBottom(
      viewport,
      getAwayFromBottomThresholdPx(),
    )

    setIsViewportAtBottom((current) => (current === atBottom ? current : atBottom))
    isNearBottomRef.current = nearBottom

    if (atBottom) {
      applyFollowState(
        getNextThreadScrollFollowStateForAtBottomChange({
          state: followStateRef.current,
          atBottom,
        }),
      )
    } else {
      applyFollowState(
        getNextThreadScrollFollowStateForUserScroll({
          state: followStateRef.current,
          isMobileViewport: isMobileViewport(),
          streamingAssistantActive: streamingAssistantActiveRef.current,
          programmaticScroll,
          movedUp,
          isAwayFromBottom: awayFromBottom,
          deltaScrollPx: upwardScrollPx,
          scrollTop,
        }),
      )
    }

    lastScrollTopRef.current = scrollTop
  },
  [applyFollowState],
)
```

wheel/touch handlers:

```ts
const detachFromUserIntent = useCallback(
  (transition: typeof getNextThreadScrollFollowStateForUserIntent) => {
    const nextState = transition({
      state: followStateRef.current,
      isMobileViewport: isMobileViewport(),
      streamingAssistantActive: streamingAssistantActiveRef.current,
    })
    if (nextState === followStateRef.current) return
    ignoreProgrammaticScrollUntilRef.current = 0
    applyFollowState(nextState)
  },
  [applyFollowState],
)

const handleViewportWheel = useCallback(
  (event: ReactWheelEvent<HTMLDivElement>) => {
    if (event.deltaY >= -1) return
    detachFromUserIntent(getNextThreadScrollFollowStateForUserIntent)
  },
  [detachFromUserIntent],
)

const handleViewportTouchStart = useCallback(
  (event: ReactTouchEvent<HTMLDivElement>) => {
    touchStartYRef.current = event.touches[0]?.clientY ?? null
    detachFromUserIntent(getNextThreadScrollFollowStateForUserIntent)
  },
  [detachFromUserIntent],
)

const handleViewportTouchMove = useCallback(
  (event: ReactTouchEvent<HTMLDivElement>) => {
    const touchStartY = touchStartYRef.current
    const currentTouchY = event.touches[0]?.clientY
    if (!isMobileViewport() || touchStartY == null || typeof currentTouchY !== 'number') return

    const upwardGestureDeltaPx = touchStartY - currentTouchY
    if (upwardGestureDeltaPx <= 6) return

    detachFromUserIntent(getNextThreadScrollFollowStateForUserGesture)
    touchStartYRef.current = currentTouchY
  },
  [detachFromUserIntent],
)

const handleViewportTouchEnd = useCallback(() => {
  touchStartYRef.current = null
}, [])
```

message change effect:

```ts
useEffect(() => {
  const previousMessages = previousMessagesRef.current
  const nextMessages = threadMessages
  const latestMessage = nextMessages[nextMessages.length - 1]
  const streamingAssistantActive =
    latestMessage?.role === 'assistant' && latestMessage.isStreaming === true

  streamingAssistantActiveRef.current = streamingAssistantActive
  previousMessagesRef.current = nextMessages

  const action = getThreadMessageUpdateScrollAction({
    previousMessages,
    nextMessages,
    state: followStateRef.current,
    isNearBottom: isNearBottomRef.current,
    shouldMaintainStreamLock:
      followStateRef.current.streamLockActive && streamingAssistantActive,
  })

  if (action === 'scroll-to-bottom') {
    requestBottomScroll({ clearManualDetachFromStream: true })
    return
  }

  if (action === 'request-scroll-to-bottom') {
    requestBottomScroll({ clearManualDetachFromStream: false })
  }
}, [requestBottomScroll, threadMessages])
```

session reset effect:

```ts
useEffect(() => {
  if (sessionKeyRef.current === sessionKey) return
  sessionKeyRef.current = sessionKey

  scrollTimerCleanupRef.current?.()
  scrollTimerCleanupRef.current = null
  followStateRef.current = createThreadScrollFollowState()
  previousMessagesRef.current = threadMessages
  streamingAssistantActiveRef.current = false
  ignoreProgrammaticScrollUntilRef.current = 0
  touchStartYRef.current = null
  isNearBottomRef.current = true
  setIsViewportAtBottom(true)

  requestAnimationFrame(() => {
    requestBottomScroll({ clearManualDetachFromStream: true })
  })
}, [requestBottomScroll, sessionKey, threadMessages])
```

cleanup:

```ts
useEffect(() => {
  return () => {
    scrollTimerCleanupRef.current?.()
    scrollTimerCleanupRef.current = null
  }
}, [])
```

hook return:

```ts
return {
  viewportRef,
  isViewportAtBottom,
  handleViewportScroll,
  handleViewportWheel,
  handleViewportTouchStart,
  handleViewportTouchMove,
  handleViewportTouchEnd,
  scrollToBottom,
}
```

### 4. `assistant-thread.tsx` 变更契约

修改文件：`frontend/src/components/chat/assistant-thread.tsx`

当前 import：

```ts
import { useCallback, useMemo, useState, type UIEvent } from 'react'
```

变更后，如果从 `AssistantThread` 中移除 local scroll state，需要确认 `useState`、`UIEvent` 是否在其他位置使用，并删除不需要的项。该文件中的 `CopyButton`、`BranchPicker` 等仍会继续使用 `useState`，因此 `useState` 本身很可能保留。`UIEvent` 很可能可以删除。

`useThreadViewport` 当前只在 `ScrollToBottomButton` 内使用。按钮改为基于 prop 后，应从 `@assistant-ui/react` import 中移除。

新增 import：

```ts
import { useThreadScrollFollow } from '@/components/chat/use-thread-scroll-follow'
```

删除现有代码：

```ts
const [isViewportAtBottom, setIsViewportAtBottom] = useState(true)
const handleViewportScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
  const nextIsAtBottom = isThreadViewportAtBottom(event.currentTarget)
  setIsViewportAtBottom((current) => (current === nextIsAtBottom ? current : nextIsAtBottom))
}, [])
```

替换代码：

```ts
const {
  viewportRef,
  isViewportAtBottom,
  handleViewportScroll,
  handleViewportWheel,
  handleViewportTouchStart,
  handleViewportTouchMove,
  handleViewportTouchEnd,
  scrollToBottom,
} = useThreadScrollFollow({
  sessionKey: conversationId ?? '__local_thread__',
})
```

修改 `ThreadPrimitive.Viewport`：

```tsx
<ThreadPrimitive.Viewport
  ref={viewportRef}
  className="min-h-0 flex-1 overflow-y-auto"
  autoScroll={false}
  scrollToBottomOnRunStart={false}
  scrollToBottomOnInitialize={false}
  scrollToBottomOnThreadSwitch={false}
  onScroll={handleViewportScroll}
  onWheel={handleViewportWheel}
  onTouchStart={handleViewportTouchStart}
  onTouchMove={handleViewportTouchMove}
  onTouchEnd={handleViewportTouchEnd}
  onTouchCancel={handleViewportTouchEnd}
>
```

修改按钮调用：

```tsx
<ScrollToBottomButton
  isAtBottom={isViewportAtBottom}
  onScrollToBottom={scrollToBottom}
/>
```

修改 `ScrollToBottomButton`：

```tsx
function ScrollToBottomButton({
  isAtBottom,
  onScrollToBottom,
}: {
  isAtBottom: boolean
  onScrollToBottom: () => void
}) {
  return (
    <button
      type="button"
      aria-label="Scroll to bottom"
      aria-hidden={isAtBottom}
      disabled={isAtBottom}
      tabIndex={isAtBottom ? -1 : 0}
      className={cn(
        'moldy-floating-icon-button flex size-8 items-center justify-center text-muted-foreground',
        isAtBottom ? 'pointer-events-none opacity-0' : 'pointer-events-auto opacity-100',
      )}
      onClick={onScrollToBottom}
    >
      <ArrowDownIcon className="size-4" />
    </button>
  )
}
```

删除 import：

```ts
import { isThreadViewportAtBottom } from '@/components/chat/scroll-bottom'
```

`isThreadViewportAtBottom` 在新的 hook 内使用。

## 测试详细契约

测试分为三层。

1. 小型数学 helper 测试：`scroll-bottom.test.ts`
2. 状态机测试：`scroll-follow-state.test.ts`
3. React 集成测试：`assistant-thread-scroll-follow.test.tsx`

### 1. `scroll-bottom.test.ts` 新增用例

添加到现有测试下方。

```ts
import {
  getThreadViewportDistanceFromBottom,
  isThreadViewportAwayFromBottom,
  isThreadViewportNearBottom,
} from '../scroll-bottom'

it('returns the remaining distance from bottom', () => {
  expect(
    getThreadViewportDistanceFromBottom({
      scrollHeight: 2000,
      scrollTop: 1200,
      clientHeight: 600,
    }),
  ).toBe(200)
})

it('treats a viewport inside the near-bottom threshold as near bottom', () => {
  expect(
    isThreadViewportNearBottom(
      {
        scrollHeight: 2000,
        scrollTop: 1360,
        clientHeight: 600,
      },
      48,
    ),
  ).toBe(true)
})

it('treats a viewport outside the away threshold as away from bottom', () => {
  expect(
    isThreadViewportAwayFromBottom(
      {
        scrollHeight: 2000,
        scrollTop: 1300,
        clientHeight: 600,
      },
      50,
    ),
  ).toBe(true)
})
```

### 2. `scroll-follow-state.test.ts`

新文件：`frontend/src/components/chat/__tests__/scroll-follow-state.test.ts`

必需 import：

```ts
import { describe, expect, it } from 'vitest'
import {
  createThreadScrollFollowState,
  didLatestStreamingAssistantFinish,
  getNextThreadScrollFollowStateForAtBottomChange,
  getNextThreadScrollFollowStateForBottomScroll,
  getNextThreadScrollFollowStateForUserGesture,
  getNextThreadScrollFollowStateForUserIntent,
  getNextThreadScrollFollowStateForUserScroll,
  getThreadMessageUpdateScrollAction,
} from '../scroll-follow-state'
```

测试 1：到达底部时解除 user flag。

```ts
it('clears the user-scrolled flag when the viewport reaches bottom', () => {
  expect(
    getNextThreadScrollFollowStateForAtBottomChange({
      state: createThreadScrollFollowState({
        userScrolledUp: true,
        autoScrollActive: true,
        streamLockActive: true,
        manualDetachFromStream: true,
      }),
      atBottom: true,
    }),
  ).toEqual({
    userScrolledUp: false,
    autoScrollActive: true,
    streamLockActive: true,
    manualDetachFromStream: true,
  })
})
```

测试 2：移动端 upward scroll detach。

```ts
it('marks the active mobile stream as manually detached on upward scroll', () => {
  const nextState = getNextThreadScrollFollowStateForUserScroll({
    state: createThreadScrollFollowState({
      autoScrollActive: true,
      streamLockActive: true,
    }),
    isMobileViewport: true,
    streamingAssistantActive: true,
    programmaticScroll: false,
    movedUp: true,
    isAwayFromBottom: false,
    deltaScrollPx: 12,
    scrollTop: 260,
  })

  expect(nextState).toMatchObject({
    userScrolledUp: true,
    autoScrollActive: false,
    streamLockActive: false,
    manualDetachFromStream: true,
  })
})
```

测试 3：移动端 touchstart detach。

```ts
it('detaches the active mobile stream immediately on touch intent', () => {
  const nextState = getNextThreadScrollFollowStateForUserIntent({
    state: createThreadScrollFollowState({
      autoScrollActive: true,
      streamLockActive: true,
    }),
    isMobileViewport: true,
    streamingAssistantActive: true,
  })

  expect(nextState.manualDetachFromStream).toBe(true)
  expect(nextState.userScrolledUp).toBe(true)
  expect(nextState.autoScrollActive).toBe(false)
  expect(nextState.streamLockActive).toBe(false)
})
```

测试 4：桌面端 wheel detach 不启用 mobile lock。

```ts
it('detaches desktop stream follow without setting the mobile detach lock', () => {
  const nextState = getNextThreadScrollFollowStateForUserGesture({
    state: createThreadScrollFollowState({
      autoScrollActive: true,
      streamLockActive: true,
    }),
    isMobileViewport: false,
    streamingAssistantActive: true,
  })

  expect(nextState.userScrolledUp).toBe(true)
  expect(nextState.manualDetachFromStream).toBe(false)
})
```

测试 5：处于 mobile detach lock 时，即使 near bottom 也不恢复 auto-scroll。

```ts
it('does not re-arm streaming follow while mobile detach lock is active', () => {
  expect(
    getThreadMessageUpdateScrollAction({
      previousMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: true }],
      nextMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: true }],
      state: createThreadScrollFollowState({
        userScrolledUp: false,
        manualDetachFromStream: true,
      }),
      isNearBottom: true,
    }),
  ).toBeNull()
})
```

测试 6：stream finish near bottom settle。

```ts
it('settles the bottom lock when the active stream finishes near the bottom', () => {
  expect(
    getThreadMessageUpdateScrollAction({
      previousMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: true }],
      nextMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: false }],
      state: createThreadScrollFollowState({
        streamLockActive: true,
      }),
      isNearBottom: true,
      shouldMaintainStreamLock: true,
    }),
  ).toBe('request-scroll-to-bottom')
})
```

测试 7：detached stream finish 不执行 scroll。

```ts
it('does not settle the bottom lock when a detached stream finishes', () => {
  expect(
    getThreadMessageUpdateScrollAction({
      previousMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: true }],
      nextMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: false }],
      state: createThreadScrollFollowState({
        userScrolledUp: true,
        manualDetachFromStream: true,
      }),
      isNearBottom: false,
      shouldMaintainStreamLock: false,
    }),
  ).toBeNull()
})
```

测试 8：explicit scrollToBottom clears detach。

```ts
it('explicit scrollToBottom clears the detach lock and resumes follow', () => {
  const nextState = getNextThreadScrollFollowStateForBottomScroll({
    state: createThreadScrollFollowState({
      userScrolledUp: true,
      manualDetachFromStream: true,
    }),
    streamingAssistantActive: true,
    clearManualDetachFromStream: true,
  })

  expect(nextState).toMatchObject({
    userScrolledUp: false,
    autoScrollActive: true,
    streamLockActive: true,
    manualDetachFromStream: false,
  })
})
```

测试 9：passive scroll 不 clear detach lock。

```ts
it('passive bottom scroll does not clear the mobile detach lock', () => {
  const state = createThreadScrollFollowState({
    userScrolledUp: true,
    manualDetachFromStream: true,
  })

  expect(
    getNextThreadScrollFollowStateForBottomScroll({
      state,
      streamingAssistantActive: true,
      clearManualDetachFromStream: false,
    }),
  ).toBe(state)
})
```

测试 10：新 user message 开始 fresh follow cycle。

```ts
it('local send clears the detach lock and starts a fresh follow cycle', () => {
  const detachedState = createThreadScrollFollowState({
    userScrolledUp: true,
    manualDetachFromStream: true,
  })

  expect(
    getThreadMessageUpdateScrollAction({
      previousMessages: [{ id: 'assistant-1', role: 'assistant' }],
      nextMessages: [
        { id: 'assistant-1', role: 'assistant' },
        { id: 'user-2', role: 'user' },
      ],
      state: detachedState,
      isNearBottom: false,
    }),
  ).toBe('scroll-to-bottom')
})
```

测试 11：latest assistant stream finish detector。

```ts
it('detects when the latest assistant stream finishes', () => {
  expect(
    didLatestStreamingAssistantFinish({
      previousMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: true }],
      nextMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: false }],
    }),
  ).toBe(true)

  expect(
    didLatestStreamingAssistantFinish({
      previousMessages: [{ id: 'assistant-1', role: 'assistant', isStreaming: true }],
      nextMessages: [{ id: 'assistant-2', role: 'assistant', isStreaming: false }],
    }),
  ).toBe(false)
})
```

### 3. `assistant-thread-scroll-follow.test.tsx`

新文件：`frontend/tests/components/chat/assistant-thread-scroll-follow.test.tsx`

目标不是启动完整的 assistant-ui，而是确认 Moldy 的 `AssistantThread` 是否正确连接新的 hook/props/button 契约。

mock strategy:

- `ThreadPrimitive.Viewport` mock 必须把接收到的 props spread 到实际 `<div>` 上。
- `useAuiState` mock 必须能够返回 `thread.messages`、`thread.isRunning`、`message` context。
- `useThreadViewport` mock 必须把 `scrollToBottom` spy 传给 selector。
- `ThreadPrimitive.Messages` mock 至少渲染 UserMessage/AssistantMessage。

测试 scaffold：

```ts
import type { ReactNode } from 'react'
import { fireEvent, render, screen } from '../../test-utils'
import { describe, expect, it, vi } from 'vitest'

const scrollToBottomSpy = vi.fn()

let mockThreadMessages: Array<{
  id: string
  role: 'user' | 'assistant'
  status?: { type: 'running' | 'complete' }
  metadata?: { custom?: Record<string, unknown> }
}> = []

let mockThreadIsRunning = false

vi.mock('@assistant-ui/react', () => {
  const passthrough = ({ children, className }: { children?: ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  )

  return {
    ThreadPrimitive: {
      Root: passthrough,
      Viewport: ({
        children,
        ...props
      }: {
        children?: ReactNode
        [key: string]: unknown
      }) => (
        <div data-testid="thread-viewport" {...props}>
          {children}
        </div>
      ),
      Empty: () => null,
      Messages: ({ components }: { components: { UserMessage: () => ReactNode; AssistantMessage: () => ReactNode } }) => (
        <>
          {components.UserMessage()}
          {components.AssistantMessage()}
        </>
      ),
      ViewportFooter: passthrough,
      If: ({ children }: { children?: ReactNode }) => <>{children}</>,
    },
    MessagePrimitive: {
      Content: () => <span>消息</span>,
    },
    ComposerPrimitive: {
      Root: passthrough,
      Input: () => <textarea aria-label="message input" />,
      Cancel: ({ children }: { children?: ReactNode }) => <>{children}</>,
      Send: ({ children }: { children?: ReactNode }) => <>{children}</>,
      Attachments: () => null,
      AddAttachment: ({ children }: { children?: ReactNode }) => <>{children}</>,
    },
    AttachmentPrimitive: {
      Root: passthrough,
      Name: () => <span>file.txt</span>,
      Remove: ({ children }: { children?: ReactNode }) => <>{children}</>,
    },
    ActionBarPrimitive: {
      Copy: ({ children }: { children?: ReactNode }) => <button type="button">{children}</button>,
      Edit: ({ children }: { children?: ReactNode }) => <button type="button">{children}</button>,
      Reload: ({ children }: { children?: ReactNode }) => <button type="button">{children}</button>,
      FeedbackPositive: ({ children }: { children?: ReactNode }) => <button type="button">{children}</button>,
      FeedbackNegative: ({ children }: { children?: ReactNode }) => <button type="button">{children}</button>,
    },
    useThreadViewport: (selector: (state: { scrollToBottom: typeof scrollToBottomSpy }) => unknown) =>
      selector({ scrollToBottom: scrollToBottomSpy }),
    useAuiState: (selector: (state: unknown) => unknown) =>
      selector({
        thread: {
          messages: mockThreadMessages,
          isRunning: mockThreadIsRunning,
          isDisabled: false,
          capabilities: { attachments: false, queue: false },
        },
        message: {
          status: { type: 'complete' },
          metadata: { custom: {}, submittedFeedback: undefined },
        },
        composer: { dictation: null, isEditing: true, text: '' },
      }),
    useAssistantState: (selector: (state: unknown) => unknown) =>
      selector({
        message: {
          status: { type: 'complete' },
          metadata: { custom: {}, submittedFeedback: undefined },
        },
      }),
    useAui: () => ({
      composer: () => ({
        addAttachment: vi.fn(),
        getState: () => ({ isEditing: true, isEmpty: true }),
        send: vi.fn(),
        setText: vi.fn(),
      }),
      thread: () => ({
        cancelRun: vi.fn(),
        getState: () => ({ capabilities: { attachments: false, queue: false }, isRunning: false }),
      }),
    }),
    makeAssistantToolUI: () => () => <div data-testid="tool-ui" />,
  }
})
```

测试 1：viewport controlled props。

```ts
it('renders the viewport with controlled auto-scroll props', () => {
  render(<AssistantThread />)
  const viewport = screen.getByTestId('thread-viewport')

  expect(viewport).toHaveAttribute('autoscroll', 'false')
  expect(viewport).toHaveAttribute('scrolltobottomonrunstart', 'false')
})
```

注意：React 将 boolean custom prop 以何种方式下发为 DOM attribute，可能因测试环境而异。如果不稳定，可在 mock `Viewport` 内将 props 单独保存到 spy，再用 `expect(lastViewportProps.autoScroll).toBe(false)` 方式验证。推荐这种方式。

测试 2：not-at-bottom shows button。

```ts
it('shows the scroll-to-bottom button when viewport is away from bottom', () => {
  render(<AssistantThread />)
  const viewport = screen.getByTestId('thread-viewport')

  Object.defineProperties(viewport, {
    scrollHeight: { value: 2000, configurable: true },
    clientHeight: { value: 600, configurable: true },
    scrollTop: { value: 200, configurable: true },
  })

  fireEvent.scroll(viewport)

  const button = screen.getByRole('button', { name: 'Scroll to bottom' })
  expect(button).not.toBeDisabled()
})
```

测试 3：button click delegates explicit re-entry。

```ts
it('scrolls to bottom when the floating button is clicked', () => {
  render(<AssistantThread />)
  const viewport = screen.getByTestId('thread-viewport')

  Object.defineProperties(viewport, {
    scrollHeight: { value: 2000, configurable: true },
    clientHeight: { value: 600, configurable: true },
    scrollTop: { value: 200, configurable: true },
  })

  fireEvent.scroll(viewport)
  fireEvent.click(screen.getByRole('button', { name: 'Scroll to bottom' }))

  expect(scrollToBottomSpy).toHaveBeenCalled()
})
```

测试 4：active stream upward wheel detach。

```ts
it('keeps the viewport detached after an upward wheel gesture during streaming', () => {
  mockThreadIsRunning = true
  mockThreadMessages = [
    { id: 'user-1', role: 'user' },
    {
      id: 'assistant-1',
      role: 'assistant',
      status: { type: 'running' },
      metadata: { custom: { isStreamingMessage: true } },
    },
  ]

  render(<AssistantThread />)
  const viewport = screen.getByTestId('thread-viewport')

  Object.defineProperties(viewport, {
    scrollHeight: { value: 2000, configurable: true },
    clientHeight: { value: 600, configurable: true },
    scrollTop: { value: 1000, configurable: true, writable: true },
  })

  fireEvent.wheel(viewport, { deltaY: -20 })

  mockThreadMessages = [
    ...mockThreadMessages.slice(0, -1),
    {
      id: 'assistant-1',
      role: 'assistant',
      status: { type: 'running' },
      metadata: { custom: { isStreamingMessage: true } },
    },
  ]

  expect(scrollToBottomSpy).not.toHaveBeenCalled()
})
```

测试 4 根据实现方式可能需要 rerender。使用 `render` 结果中的 `rerender(<AssistantThread />)` 再次触发 message update effect。

### 4. 执行命令

最小验证：

```bash
cd frontend
pnpm vitest run src/components/chat/__tests__/scroll-bottom.test.ts src/components/chat/__tests__/scroll-follow-state.test.ts tests/components/chat/assistant-thread-scroll-follow.test.tsx
```

聊天相关回归：

```bash
cd frontend
pnpm vitest run src/components/chat/__tests__ tests/components/chat src/lib/chat/__tests__
```

全部 frontend 单元测试：

```bash
cd frontend
pnpm vitest run
```

## 实现过程中需要确认的实际代码点

工作前后必须确认的文件及原因：

| 文件 | 确认原因 |
| --- | --- |
| `frontend/src/components/chat/assistant-thread.tsx` | 是否移除 `useThreadViewport` import、修改 `ScrollToBottomButton` prop、修改 `ThreadPrimitive.Viewport` props。 |
| `frontend/tests/components/chat/assistant-thread-actions.test.tsx` | 现有 assistant-ui mock 对 `useThreadViewport` state shape 的假设很简单。若新 hook 需要 `useAuiState`，可能需要增强 mock。 |
| `frontend/tests/components/chat/assistant-thread-edit.test.tsx` | 与上面相同，可能需要增强 assistant-ui mock。 |
| `frontend/src/components/chat/builder-overrides.tsx` | builder variant 本身共享 `AssistantThread` viewport，因此原则上不需要单独修改。但需要手动 QA 确认 streaming indicator 也以同样方式工作。 |
| `frontend/src/lib/chat/convert-message.ts` | 确认作为 streaming assistant marker 的 `metadata.custom.isStreamingMessage` 是否保留。 |
| `frontend/src/lib/chat/use-chat-runtime.ts` | 确认 `stream-` id assistant message 在 streaming 中保持，并在 message_end 后由 hook selector 感知 `isRunning`/status 切换。 |

## Definition Of Done

必须满足以下全部条件才算完成。

- 新文档中的 Phase 1、Phase 2、Phase 3 工作全部已实现。
- `ThreadPrimitive.Viewport` 由自定义 follow hook 控制。
- 用户在 active stream 中向上滚动后，后续 content resize 和 message update 不会执行 bottom scroll。
- 点击下方箭头按钮会解除 `manualDetachFromStream` 并恢复 follow。
- append 新 user message 会无视之前的 detach 状态，开始 bottom scroll。
- 移动端 touchstart 或 upward touchmove 会从 active stream follow detach。
- `scroll-bottom.test.ts`、`scroll-follow-state.test.ts`、`assistant-thread-scroll-follow.test.tsx` 均通过。
- 现有 `assistant-thread-actions.test.tsx`、`assistant-thread-edit.test.tsx` 按新的 assistant-ui mock 要求通过。
- 手动 QA 中，default conversation 与 builder variant 都表现出相同的滚动策略。

## 最终判断

该项很值得借鉴到 Moldy。当前 Moldy 依赖 assistant-ui 默认 auto-scroll，基本聊天体验可以运行，但对于 deepagent 这类长 streaming 且工具 UI height 变化很多的产品，显式采用“尊重用户正在阅读的位置”这一策略更安全。

最合适的方式不是直接复制 LambChat 的实现，而是借鉴其纯状态转移和测试理念，再集成为适合 assistant-ui viewport 的小型 hook。
