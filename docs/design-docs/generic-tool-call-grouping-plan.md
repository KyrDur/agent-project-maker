# 开发规划：通用 Tool-Call grouping（把所有工具归入 group box）

> 状态：**Phase-1 实现完成（2026-06-25）** · 分支 `worktree-feature+generic-tool-call-grouping` · 初次编写/修订 2026-06-25
> 决定：**采用官方 `MessagePrimitive.GroupedParts` + group container 视觉复用现有 `CollapsiblePill`**（替代 §5.3 的官方 `tool-group.tsx` vendoring 方案 — 保持 design token 一致 + 复用已验证折叠 UX + 避免 keyframe/guard 工作）。为按 tool name 细分，使用 inline `groupBy`，不使用按 type 的 `groupPartByType`。
>
> **实际实现/验证（Phase-1，仅 main v3）：**
> - `frontend/src/components/chat/assistant-thread.tsx` — `MessagePrimitive.GroupedParts` + module-level `groupAssistantParts`（`group-tool:${toolName}`，排除 `isGroupableTool`）+ `renderGroupedAssistantPart`（group N≥2 container / N=1 passthrough / 保留 text·tool-call·data·indicator·default leaf，已确认 default=null 与 `defaultComponents` 一致）。
> - `frontend/src/components/chat/tool-ui/tool-group-container.tsx` — `CollapsiblePill` wrapper（label·count·running/done key remount）。
> - `frontend/src/lib/chat/tool-group-meta.ts` — `toolGroupLabelKey`（搜索/文件类 i18n）+ `isGroupableTool`（排除 HiTL/approval）。
> - i18n `chat.toolGroup.{count,labels.*}`（ko/en），vitest 2 个，E2E `E2E_TOOL_GROUP` marker（`current_datetime`×3+`resolve_relative_date`×1，no-network/no-HITL builtin）。
> - 验证：tsc 0 · vitest 1009 green · lint（design-system/i18n）通过 · E2E cold `--retries=0` 通过（N box→1 group+count，done 折叠，展开恢复）。
> - **Phase-2 剩余**：吸收 deep-research 特殊处理（§6），适配 legacy/builder surface（test-chat-panel·conversational·assistant-panel）。
>
> ⚠️ 以下 §4~9 为**实现前规划**，其中 §5.3 的 vendoring 方案已按上面决定替换为复用 `CollapsiblePill`。
> ⚠️ 修订原因：初稿决定“官方 `GroupedParts`/`ToolGroup` API 尚未在 npm 发布，因此走自定义泛化（Option 3）”，但**这个前提是错的**。官方 grouping runtime API 已在**我们正在使用的 `@assistant-ui/react` 0.14.18 中以 STABLE 形式存在**（验证见 §10·附录 A）。因此放弃自定义泛化，**直接使用官方 API 实现**。registry component（`tool-group.tsx`/`tool-fallback.tsx`）通过 shadcn copy-paste vendoring 后再按我们的 design 调整。

---

## 0. 一句话摘要

当前 grouping（多个 box → 合并成 1 个）**仅限搜索/deep research（tavily）**，且**只在 legacy runtime** 生效。目标是让**所有工具表现一致**（连续相同工具 = 1 container + count label + running 展开/done 折叠），并应用到**main v3 聊天**。实现不做自定义泛化，而使用 **assistant-ui 官方 `MessagePrimitive.GroupedParts` + `groupPartByType`**（0.14.18 已存在），group container 视觉仅对 vendored `tool-group.tsx` 做 token 适配。

---

## 1. 目标（Done 标准）

1. 在**main v3 聊天**（`assistant-thread.tsx`）中，一条 assistant message 内的**连续相同 tool call N 个**会被渲染为**1 个可折叠 group container**。
2. group header 显示**count label**（如“网页搜索 · 10 次”等按工具的 label + count）。
3. **running 时自动展开 / 完成后折叠。**
4. group 内每个 call 显示**单行摘要**（搜索=查询词，文件=路径等）— 继续渲染现有 `makeAssistantToolUI` per-tool UI。
5. （可选）搜索类工具将**source 另行汇总成 pill**（Perplexity 风格）。
6. 单次调用（N≤1）**不 grouping**，继续按现有单独 box 渲染。
7. 通用于所有工具（移除 tavily 特殊处理，或吸收到通用 group 的特殊 case）。
8. **（修订新增）** grouping 使用官方 `GroupedParts` API，以减少未来 assistant-ui 升级时的自定义维护成本。

---

## 2. 当前状态（实测验证完成）

### 2.1 2 个 runtime
- **v3（main 聊天）**：`frontend/src/lib/chat/langgraph-runtime/use-moldy-langgraph-stream.ts` + LangGraph SDK（`useStream`）。render 入口为 `frontend/src/components/chat/assistant-thread.tsx`。
- **legacy**：`frontend/src/lib/chat/use-chat-runtime.ts`。仍在使用的 surface = conversational builder（`app/agents/new/conversational`）、Assistant panel（`components/agent/assistant-panel.tsx`）、settings test chat（`app/agents/[agentId]/settings/_components/right-panel/test-chat-panel.tsx`）。

### 2.2 tool box = 自定义实现
- `frontend/src/components/chat/tool-ui/` 下约 27 个 custom component 通过 assistant-ui **`makeAssistantToolUI` primitive**（tool name → render fn mapping）注册（`frontend/src/lib/chat/tool-ui-registry.ts`）。视觉 100% 自定义。**未使用 assistant-ui tool-group。**
- catch-all：`frontend/src/components/chat/tool-ui/generic-tool-ui.tsx` 中的 `GenericToolFallback`（`makeAssistantToolUI({ toolName: '*' })`）处理未注册工具。
- reasoning：`frontend/src/components/chat/tool-ui/reasoning-ui.tsx` 的 `ReasoningDataUI`（`makeAssistantDataUI`）注册于 `data-ui-registry.ts`。

### 2.3 当前 grouping = tavily 专用 + legacy 专用
- 逻辑：`frontend/src/lib/chat/deep-research-summary.ts`（253 行）
  - `compactDeepResearchMessages(messages)` → 以 turn 为单位汇总 `tavily_search` 调用，**2 个以上**（`tavilyCalls.length <= 1` 则 passthrough）时移除单独的 N 个 call + result message，并替换成**1 个 synthetic `deep_research_summary` tool_call**。
  - 常量：`TAVILY_SEARCH_TOOL_NAME = 'tavily_search'`、`DEEP_RESEARCH_SUMMARY_TOOL_NAME = 'deep_research_summary'`。
- UI：`frontend/src/components/chat/tool-ui/deep-research-summary-ui.tsx`（172 行）— `makeAssistantToolUI({ toolName: 'deep_research_summary' })`。渲染 source dedup·domain ranking·完成 N/M·耗时等**丰富摘要**。
- wiring：**`frontend/src/lib/chat/use-chat-runtime.ts:467`** `const merged = compactDeepResearchMessages(...)` — **只在 legacy runtime 调用**。
- 测试：`frontend/src/lib/chat/deep-research-summary.test.ts`。

> ⚠️ 核心：**main v3 聊天（`use-moldy-langgraph-stream.ts`）不会调用 `compactDeepResearchMessages`。** 也就是说 main 聊天**完全没有 grouping**，因此“N box”问题真实存在。泛化的第 1 目标就是这里。

### 2.4 可复用资产
- `frontend/src/components/chat/tool-ui/collapsible-pill.tsx` — 折叠/展开 UX。
- `frontend/src/lib/chat/search-results.ts`（90 行）— `parseSearchResults`、`sourceSummariesFromResults`（source dedup/domain 汇总）。可复用于 source pill。
- 工具属于**registry tool**：例如 `tavily_search` = `backend/app/tools/definitions/tavily_search.py`（key `tavily`，使用 `TAVILY_API_KEY`）。不是 MCP。

---

## 3. 经验依据（实测数据）

### 3.1 tool call 是 intra-message（同一 message 内 N 个）
- 来源：dev DB（`natural-mold-postgres-1`, localhost:5432）`message_events` table 中实际 deep-research conversation 2 个。
  - conversation `cba4e3c9…` → 1 条 assistant message（`c40c9bcd…`）中 **`tavily_search` ×10 + `read_file` ×1**。
  - conversation `992272b8…` → 1 条 assistant message（`bf62d812…`）中 **`tavily_search` ×4 + `naver_search_news` ×1**。
  - 所有 tool_call id 都是 `{assistant_msg_id}-{n}` 形式 → **确认属于同一 message**。
- **结论：搜索 N 个不是不同 message，而是同一 message 的 N 个 part → intra-message grouping 足够。** 官方 `GroupedParts` 默认是 **adjacent（相邻）grouping**，正好适配这一 case。（cross-message 参见 §8，暂缓。）

### 3.2 同一 message 中会混用工具
- 例如 tavily 10 + read_file 1 / tavily 4 + naver 1，**会混入不同工具。**
- → 不能“把所有工具放在一个 group”，而应按**连续相同 tool name** grouping。官方 `groupPartByType` 按 part type grouping，因此要实现**按 tool name 细分**，需要在 `groupBy` callback 的 group key 中包含 tool name（§5.2）。

### 3.3 存储格式（参考）
- `message_events.events` 使用 Moldy 自有 SSE protocol（`message_start`/`tool_call_start`/`tool_call_result`/`content_delta`/`message_end`）。**不是 AG-UI。** 用于 resume/replay/share/trace 持久化（ADR-011）。与 grouping 工作无关（在 frontend `Message[]`/part 层处理）。

---

## 4. 设计 — 3-rule 模式

1. **连续相同工具 = 1 container + count label**：`{tool label} · {N} 次`（例如“网页搜索 · 10 次”“读取文件 · 3 次”）。
2. **running 展开 / done 折叠**：group 内只要任一 tool-call part 的 status 为 running 就展开，全部完成后折叠。（官方 `ToolGroupTrigger` 的 `active` prop 接收该信号。）
3. **每次调用单行摘要** +（搜索类）**source pill 单独汇总**。group 内每个 call 继续**渲染现有 `makeAssistantToolUI` per-tool UI**。
- **threshold**：仅 N ≥ 2 时 grouping。N=1 继续使用现有单独 box。

> 这 3 条 rule 与官方 `tool-group.tsx`（ToolGroupRoot/Trigger/Content）的行为一致。也就是说**无需重新造 container**，只要 vendoring 官方 component 并修改 label/token 即可。

---

## 5. 实现计划 — 采用官方 GroupedParts

### 5.0 核心 API（0.14.18 已存在，§10 验证）
- `MessagePrimitive.GroupedParts`（STABLE）— 属于 `@assistant-ui/react` 的 `MessagePrimitive` namespace。接收 `groupBy: (part, context) => TKey[] | null` prop，把相邻 part 合成为 `group-*` node。render fn 接收 `{ part, children }`，且**只有 group case 渲染 `children`**。
- `groupPartByType(map)`（STABLE）— 从 root import。通过 `groupPartByType({ "tool-call": ["group-tool"] })` 这类写法生成 part type → group key mapping，传给 `groupBy`。
- synthetic key `"standalone-tool-call"`（human tools·MCP apps 自动 standalone，从 group 中排除）— 当前暂时不需要，但需知晓。（`"mcp-app"` 已 deprecated，将在 v0.15 移除。）

### 5.1 入口
- `frontend/src/components/chat/assistant-thread.tsx`
  - 当前 `AssistantMessageParts()`（约 236–239 行）使用 `<MessagePrimitive.Content components={ASSISTANT_PART_COMPONENTS} />` 渲染 parts。（`Content` 是 `Parts` 的 alias。）
  - → 将此处替换为 `<MessagePrimitive.GroupedParts groupBy={...}>{renderGroupOrPart}</MessagePrimitive.GroupedParts>`。
  - 还需检查另一个 `<MessagePrimitive.Content />` 使用点（约 757 行）+ `builder-overrides.tsx`（legacy/builder 用）— builder surface 第一阶段可以继续保持现状。

### 5.2 grouping 逻辑（按 tool name 细分）
- `groupPartByType` 按 type grouping，可能把 tavily·read_file 混到一个 group。我们需要**按 tool name**，因此直接编写 `groupBy` callback：
  ```ts
  const groupBy = (part) =>
    part.type === "tool-call" ? [`group-tool:${part.toolName}`] : null;
  ```
  - 在 group key 中包含 `toolName` → **只有连续相同工具**进入同一个 group（相邻不同工具会自动分开）。N=1 时不使用 container，而是单独 box 渲染（render fn 中用 `part.indices.length < 2` 分支）。
- render fn:
  ```tsx
  ({ part, children }) =>
    part.type.startsWith("group-tool:")
      ? <ToolGroupRoot defaultOpen={part.status?.type === "running"}>
          <ToolGroupTrigger count={part.indices.length} active={part.status?.type === "running"} label={metaFor(part).label} />
          <ToolGroupContent>{children}</ToolGroupContent>
        </ToolGroupRoot>
      : children // 非 group part 继续走现有 render 路径
  ```

### 5.3 需要 vendoring 的 component（shadcn copy-paste，按我们的 token 调整）
- `npx shadcn@latest add https://r.assistant-ui.com/tool-group.json https://r.assistant-ui.com/tool-fallback.json` → 生成 `frontend/src/components/assistant-ui/{tool-group,tool-fallback}.tsx`。（tool-group 依赖 tool-fallback，因此一起安装。）
  - 原始源码参考位置（本地）：`/Users/chester/dev/ref/assistant-ui/packages/ui/src/components/assistant-ui/`。
  - `tool-group.tsx` 的 runtime 依赖只有 `useScrollLock` → **在 0.14.18 可直接工作。**
  - `tool-fallback.tsx` 的 **approval（HiTL）subcomponent 使用 0.14.19+ API（`respondToApproval`）**，在 0.14.18 可能部分不可用 → 我们已有自定义 `ApprovalCard`，因此**移除 approval 部分/替换为我们的实现**。
- vendored 后：header 改为 `{tool label} · {N} 次`（新增 label prop），design token 对齐 ADR-010，tone 与 `collapsible-pill.tsx` 统一。
- tool meta map（新增，`frontend/src/lib/chat/tool-group-meta.ts`）：
  - `toolName → { label, summaryLine(args) }`。例如：`tavily_search → {label:'网页搜索', summaryLine: a => a.query}`，`read_file → {label:'读取文件', summaryLine: a => a.file_path}`。**generic fallback**（label=toolName，summaryLine=1 个主要 arg）。

### 5.4 每次调用单行摘要 / 保留现有 per-tool UI
- group 内每个 `tool-call` part 继续**使用现有 `makeAssistantToolUI` 注册 UI 渲染**（搜索=查询词一行、文件=路径等已由 per-tool UI 处理）。group 仅承担 container 角色。
- ⚠️ 需要验证（§8-1）：`GroupedParts` 的 `children` 渲染 group 内 part 时，**现有注册的 per-tool UI routing 是否仍然保留**。如果没有，则在 group render fn 内通过 `MessagePrimitive.PartByIndex`/`components.tools` 路径显式委派。

### 5.5 source pill（可选，搜索类）
- 使用 `lib/chat/search-results.ts` 的 `parseSearchResults` + `sourceSummariesFromResults`，对 group 内全部搜索结果的**唯一 source/domain 进行汇总** → 在 group footer 渲染 pill row。（官方 `sources.tsx` 基于 `source` **part type**，与我们的架构（result 在 tool result 中）不匹配 → 保留我们的 parser。）

---

## 6. 清理现有 deep-research grouping

> **决定（2026-06-26）：移除 + 文档化扩展路径。** Phase-2(a) 已吸收搜索 group 的 source 汇总（LITE），因此 tavily 专用特殊处理属于重复。**Phase-2(b) 移除对象**：`deep-research-summary.ts`（`compactDeepResearchMessages`）+ `deep-research-summary-ui.tsx`（FULL card）+ `tool-ui-registry.ts` 中的 `DeepResearchSummaryToolUI` 注册 + `use-chat-runtime.ts:467` wiring。⚠️ **必须与 legacy/builder surface 的 grouping 应用一起进行** — 如果单独移除，legacy surface 中的 tavily ×N 会退化为单独 box。
>
> **如果未来需要更丰富的搜索表达**（回应用户担忧）：不要复活 `deep_research_summary` synthetic message，而是将 **`ToolGroupContainer` 扩展为 rich mode**。由于已经可以通过 group `indices` 访问每个搜索 `result`，展开时可以在 render-time 新增**source link list**（FULL 的核心价值），无需 synthetic，且与我们的 grouping 一致。如果需要 FULL card 原始 markup，可参考 **commit 258d71a0 之前的 `deep-research-summary-ui.tsx`**。其中 title（“React 生态…”）、耗时（42s）、完成 N·M 属于 LLM synthetic data，不属于 render-time 再现目标，因此有意舍弃。

- （参考，当时规划）决定 `deep-research-summary.ts` + `deep-research-summary-ui.tsx` 的去向：
  - **(a) 吸收到通用 ToolGroup + 保留丰富摘要（若有价值则推荐）**：在 tavily group footer 中保留现有汇总（source dedup/domain/完成 N·M/耗时）的特殊 render（吸收到 §5.5 source pill）。
  - (b) 放弃丰富摘要，统一为简单通用 group（代码↓）。
- legacy `use-chat-runtime.ts:467` 中的 `compactDeepResearchMessages` 调用：通用 grouping 在 v3 稳定后，应**移除消息预转换方式本身**，并让 legacy surface 也统一使用 `GroupedParts`；或分阶段迁移二者。

---

## 7. 测试

- **vitest**:
  - `groupBy` callback + group render unit test：intra-message、**按 tool name**、混合工具（tavily+read_file）、threshold（N≥2）、running/done 状态 → 展开/折叠。
  - vendored `tool-group.tsx` render test（label·count·active）。
  - `deep-research-summary.test.ts` 迁移/更新。
- **chat E2E**（扩展现有 `frontend/e2e/chat-stream-integrity.spec.ts` 或新增）：
  - 在 scripted model 中新增**单条 message 发出 M 个相同 tool_call** 的 marker（`backend/app/agent_runtime/e2e_scripted_model.py` — 参考现有 `E2E_HITL_MULTI` 模式）。
  - 断言：N 个 call 渲染为**1 个 group + count**，running→展开/done→折叠，无重复 box。
  - 注意现有 baseline/known-flake：cg47（`chat-langgraph-v3.spec.ts:47`，subagent 完成 stall，另行处理）、visual-matrix:146（负载 flake）。
- **guard**：扩展 Phase A/B render-integrity spec。

---

## 8. 风险 / 未解决问题

1. **★保持 per-tool UI routing**：`GroupedParts` 的 group `children` 渲染 group 内 `tool-call` part 时，必须在**实现第一步就验证**现有 `makeAssistantToolUI` 注册 UI 是否仍按原样应用（§5.4）。如果不行，则需要显式委派路径。— 最大不确定性。
2. **vendored tool-fallback approval**：0.14.18 中不存在 approval API（`respondToApproval`，0.14.19+）→ 删除 tool-fallback.tsx 的 Approval subcomponent，使用自定义 `ApprovalCard`（§5.3）。
3. **cross-message**：实测以 intra-message 为主。`GroupedParts` 是相邻 grouping，已足够。如果未来出现按 message 依次只调用一个工具的 Agent，再考虑 `Unstable_PartsGrouped`（non-adjacent，unstable）— **暂缓**。
4. **legacy runtime**：是否也将通用 grouping 应用到 legacy/builder surface（§6）。先做 v3，之后统一。
5. **`makeAssistantToolUI` deprecated（0.14.24）**：本工作基于 0.14.18，因此无关，但**长期需要将 27 个注册迁移到 toolkit `render` API**（独立 track，见 §9）。不要与 GroupedParts 工作绑定。

---

## 9. 估算

- 官方 `GroupedParts`+`groupPartByType` wiring + 整理 vendored `tool-group.tsx` + tool-meta map + 测试：**~2 dev-days**（无需新造 custom container，比初稿缩短）。
- 保留/吸收丰富 deep-research 摘要（6-a）+ source pill（5.5）：**+0.5~1d。**
- （独立 track，与本工作拆开）0.14.24 升级可行性 + `makeAssistantToolUI`→toolkit `render` migration 影响分析：另行估算。

---

## 10. 官方 API 可用性验证（session 2，确定性）

- 已安装 `@assistant-ui/react` **0.14.18**。npm 最新 = **0.14.24**（与 monorepo 源码 HEAD 版本一致，源码并未超前）。9 个 docs 功能均已在 0.14.24 发布完成。
- **0.14.18 中已经存在（直接 grep 确认）** — `dist/index.d.ts`+`index.js` 会 export 以下内容：
  - `groupPartByType`、`GroupByContext`（runtime+type，可从 root import）
  - `MessagePrimitive.GroupedParts` (STABLE), `Unstable_PartsGrouped`, `Unstable_PartsGroupedByParentId`(deprecated)
  - `ReasoningMessagePartComponent`/`SourceMessagePartComponent`/`FileMessagePartComponent` + `useMessagePart{Reasoning,Source,File,Image}` hook + 各 part type slot
  - `AttachmentPrimitive`、`CompositeAttachmentAdapter`、`SimpleImageAttachmentAdapter` 等（我们已经在使用 attachment primitive）
  - `makeAssistantToolUI`/`makeAssistantDataUI`（在 0.14.18 中未 deprecated）
- **不存在**：`context-display`（无 runtime export，仅有 registry component + 需要 server usage forwarding）、`directive-text`（不是 message part — 只有 composer 用 `unstable_` directive）、`ToolGroupRoot/Trigger/Content`（不是 runtime primitive — 是 registry tsx 的本地 component）。`toolUI`/`ToolFallback` literal **不是 export**（用于 JSDoc example/scaffold）。
- **初稿附录 A 的错误原因**：grep 了 `frontend/node_modules/.pnpm` 中的**stale `core@0.1.13`**，因此结果为 0。实际 `react@0.14.18` resolve 的是 **repo-root `.pnpm` 中的 `core@0.2.14`**。重新验证时应 grep root store。

---

## 附录 A — （更正）官方 grouping 可用性

> **初稿附录 A 曾得出“官方 `GroupedParts`/`ToolGroup` 尚未在 npm 发布（dist 0 项）”的结论，这是错误的。** 参见 §10。

- 更正事实：官方 `MessagePrimitive.GroupedParts` + `groupBy` prop + `groupPartByType` helper **当前已可在 0.14.18 中以 STABLE 形式使用**。因此本文按**直接采用官方 API**推进。
- 仍然有效的注意事项：**0.14.18 → 0.14.24 升级在过去实测中曾导致 vitest 5 个文件 load 失败**（import breaking + `@assistant-ui/tap` 0.7→0.9 冲突），因此曾 revert。本 grouping 工作**不需要升级**（0.14.18 已足够），所以与此风险无关。如果未来需要升级，应作为**单独隔离任务**处理（clean reinstall + 全部 vitest green）。
- 官方 docs 模式（参考）：
  ```tsx
  <MessagePrimitive.GroupedParts groupBy={groupPartByType({ "tool-call": ["group-tool"] })}>
    {({ part, children }) =>
      part.type === "group-tool"
        ? <ToolGroupRoot><ToolGroupTrigger count={part.indices.length} active={part.status.type === "running"} /><ToolGroupContent>{children}</ToolGroupContent></ToolGroupRoot>
        : part.type === "tool-call" ? <ToolFallback {...part} /> : children}
  </MessagePrimitive.GroupedParts>
  ```
  - `ToolGroupRoot/Trigger/Content`·`ToolFallback` 是**registry copy-paste component**（由我们 vendoring·编辑）。runtime lock-in 只有 `GroupedParts`/`groupPartByType`。

---

## 附录 B — 核心文件索引

| 目的 | 路径 |
|------|------|
| v3 thread render 入口 | `frontend/src/components/chat/assistant-thread.tsx`（≈239，将 `MessagePrimitive.Content`→`GroupedParts`） |
| per-tool UI 注册 registry | `frontend/src/lib/chat/tool-ui-registry.ts`（27 个 `makeAssistantToolUI`） |
| catch-all tool box | `frontend/src/components/chat/tool-ui/generic-tool-ui.tsx`（`ToolFallbackPanel`/`GenericToolFallback`） |
| 当前 grouping 逻辑（tavily 专用） | `frontend/src/lib/chat/deep-research-summary.ts` |
| 当前 group box UI | `frontend/src/components/chat/tool-ui/deep-research-summary-ui.tsx` |
| grouping wiring（legacy） | `frontend/src/lib/chat/use-chat-runtime.ts:467` |
| 复用折叠 UX | `frontend/src/components/chat/tool-ui/collapsible-pill.tsx` |
| 复用 source 汇总 | `frontend/src/lib/chat/search-results.ts` |
| 新 tool meta map | `frontend/src/lib/chat/tool-group-meta.ts`（新增） |
| vendored group container | `frontend/src/components/assistant-ui/tool-group.tsx`（shadcn add，新增） |
| vendored fallback（参考） | `frontend/src/components/assistant-ui/tool-fallback.tsx`（shadcn add；移除 approval） |
| scripted E2E model（测试 marker） | `backend/app/agent_runtime/e2e_scripted_model.py` |
| tavily tool definition（registry） | `backend/app/tools/definitions/tavily_search.py` |
| 现有 grouping test | `frontend/src/lib/chat/deep-research-summary.test.ts` |
| 官方 registry 原始代码（本地参考） | `/Users/chester/dev/ref/assistant-ui/packages/ui/src/components/assistant-ui/{tool-group,tool-fallback}.tsx` |
