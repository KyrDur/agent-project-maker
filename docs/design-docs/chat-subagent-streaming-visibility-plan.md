# G10 — 子 Agent streaming 可见性 (Subagent Streaming Visibility)

> 状态：**规划(Plan)** — 实现前
> 编写：2026-07-02
> 分支：`feature/chat-subagent-streaming-visibility` (worktree)
> 来源：`docs/design-docs/chat-feature-gap-analysis.md` G10 (Tier 2, 价值中 / 工作量中)
> 相关：[[chat-generative-ui-dev-plan]] · `docs/superpowers/plans/2026-06-13-assistant-ui-langgraph-v3-streaming.md` · `adr-021-value-based-trace-redaction.md` · `adr-011-sse-stream-resume.md`

---

## 0. TL;DR

G10 原本的定义是“父级只看到**最终结果**，看不到子 Agent 内部进展/思考”。但调查实际源代码后发现，**v3 聊天路径中，子 Agent streaming 可见性基础设施已经有相当一部分完成并经过验证。** 因此 G10 并非“新建”，而是**“在生产（真实 LLM）路径中 end-to-end 完成现有基础设施，并补齐识别、标签、思考摘要、策略方面剩余 gap 的增量工作”**。

**当前已经可用的内容（已通过 e2e 验证）：**
- v3 路径中，`task` tool call → 立即渲染子 Agent pill（`SubagentCard`）
- 进度汇总 pill（`SubagentProgress`：完成/进行中/失败）+ 活动条（`RunActivityStrip`）
- 子 Agent 内部消息/tool call 的 **scoped 实时渲染**（基于 `useMessages`/`useToolCalls`、`tools:<call_id>` 嵌套 namespace）
- 右侧 rail 详情（`subagent-panel-content.tsx`），reload hydration 保持（cg47 修复）

**真正剩余的 gap（= G10 工作）：**
1. **未注入显示名** — v3 路径不消费 `subagent_display_names`，导致 pill 显示 runtime name（`agent_xxxxxxxx`）/description（只有 legacy 路径会 enrich 成人类可读名称）。
2. **内部思考(reasoning) masking** — `redact_private_reasoning` 将子 Agent reasoning 只保留 `summary`/`status`/`signature` 后进行 masking → 无法观察“内部思考”。
3. **内联可见性策略** — 并发运行的子 Agent 中，只有前 2 个显示内联详情（`DEFAULT_MAX_LIVE_INLINE_DETAILS = 2`），完成数达到 5 个以上后自动折叠（`AUTO_COLLAPSE_COMPLETED_THRESHOLD = 5`）。增强可观测性时需要重新评估。
4. **真实 LLM 实测尚未确认** — 上述可见性已通过 scripted 模型 e2e 验证。实际 deepagents `task`（阻塞式 `ainvoke`）+ 真实 LLM 是否真的会通过 `tools:<call_id>` namespace 发出内部 token，需要通过 **Phase 0 spike 实测**确认。

---

## 1. 背景 — 两条 streaming 路径

生产 v3 聊天与 legacy 聊天并存，两者对子 Agent 的暴露级别从根本上不同。

### 1-1. legacy 路径（结构上无法实现内部 streaming）
- `backend/app/agent_runtime/streaming.py:395-399` — `agent.astream(..., stream_mode="messages")`，**没有 `subgraphs=True`**。
- deepagents `task` 工具通过阻塞式 **`.ainvoke()`** 执行子 Agent（`deepagents/middleware/subagents.py:721`），只把最后一条非空 `AIMessage.text` 作为 `ToolMessage` 返回（`:600-638`）。
- 结果：父级 stream 只暴露 `task` tool call start（通过 `enrich_subagent_tool_call_parameters` 注入 `agent_name`/`agent_runtime_name`，`streaming.py:499-503`）+ `task` tool result（= 子 Agent 最终报告）。**完全没有内部 token/tool call。**

### 1-2. v3 协议路径（生产默认，内部事件会传播）
- endpoint：`POST /api/conversations/{id}/langgraph/threads/{tid}/commands`（`run.start`）→ `execute_agent_stream_langgraph`（`conversation_agent_protocol_commands.py:328-329`）。
- 主 stream：`agent.astream_events(actual_input, config=config, version="v3")`（`langgraph_streaming.py:75-86`）。
  - `astream_events(version="v3")` 是 LangGraph Pregel 原生能力，**会强制将 `subgraphs` 设为 True**（`langgraph/pregel/main.py:378-393`：“subgraphs is forced True so nested namespaces flow through scoped muxes”）。
- fallback stream：`agent.astream(..., stream_mode=["messages","updates","values","custom"], subgraphs=True)`（`langgraph_streaming.py:89-101`）。
- 事件适配器将 namespace/checkpoint_ns 一直保留到 wire：`langgraph_protocol_adapter.py:37-72`、`protocol_events.py:174-193`。
- 主循环不做 namespace 过滤，emit 所有事件（`langgraph_streaming.py:394-483`）。
- **测试依据**：`backend/tests/agent_runtime/test_langgraph_streaming.py:111` — `"namespace": ["tools:call-1"]` 的嵌套 namespace 事件会被 emit/persist/replay。`tools:<tool_call_id>` 正是 `task` 工具内部子 Agent 执行时产生的 namespace 模式。

**结论：** v3 路径已经通过 `tools:<task_call_id>` 嵌套 namespace 传递子 Agent 内部事件。frontend SDK 会消费这些事件。

---

## 2. frontend — 3 层实时可见性（已实现）

`@langchain/react` v1.0.22 的 `useStream` 维护 discovery map（`stream.subagents`），项目组件负责渲染。

### 2-1. 数据源
- `frontend/src/lib/chat/langgraph-runtime/use-moldy-langgraph-stream.ts:2100-2103` — `useStream({ transport, threadId })`.
- 订阅通道：`:218-227` — `messages, tools, values, updates, lifecycle, tasks, checkpoints, custom`。
- SDK discovery（`@langchain/langgraph-sdk/.../discovery/subagents.js`）：`tool-started`+name=`task` → 注册 subagent（running），`tool-finished`/`tool-error` → complete/error。**`task` tool call 本身被用作 subagent 标识符（trigger_call_id）**。reload 时用 checkpoint 的 `getState().values.messages` seed（`subagents.js:34-45`）。
- scoped 详情：`useMessages(stream, subagent)`/`useToolCalls(stream, subagent)` — 以 subagent namespace（`tools:<call_id>`）在 mount 时开启 **ref-counted 订阅**（`@langchain/react/dist/selectors.d.ts:27-48`）。**token 级 streaming 要成立，backend 必须通过该 namespace 发出 `messages` 通道 delta**（`:36-45`）。

### 2-2. 渲染层
1. **粗粒度进度（始终实时）**：`subagent-progress.tsx:14-44`（“完成 N/M · 进行中 K · 失败 J”）+ `RunActivityStrip`（`activity-model.ts:25-60` 在每个带 namespace 的 messages 事件上 upsert subagent 活动）。仅在 running 时由 `assistant-message-loading.tsx:105-116` 显示。
2. **子 Agent pill（始终实时）**：`sub-agent-ui.tsx:92-97`（`makeAssistantToolUI({toolName:'task'})`）→ `subagent-card.tsx:160-206`（`SubagentCard` = `CollapsiblePill`）。基于 discovery snapshot 进行状态转移。
3. **内联 scoped 详情（有限实时）**：`subagent-card.tsx:97-158`（`SubagentDetails`）。gate 为 `canRenderScopedDetails = subagent !== null && stream !== null && inlinePolicy.canRenderInlineDetails`（`:170-171`）。

### 2-3. 内联策略（核心限制）
- `subagent-runtime.tsx:8-9` — `AUTO_COLLAPSE_COMPLETED_THRESHOLD = 5`, `DEFAULT_MAX_LIVE_INLINE_DETAILS = 2`.
- `getSubagentInlinePolicy`（`:129-163`）：running 中只有索引 `< 2` 的项自动展开+内联渲染，其余为 `overflowedLiveDetails`（折叠，不渲染详情 → 在右侧 rail 按需查看）。complete 时 `defaultExpanded: scoped.length < 5`。error 始终展开。
- **lazy resolve**：`CollapsiblePill` 只有展开后才调用 `renderBody`（`collapsible-pill.tsx:233-235`）→ 折叠卡甚至不会开启 scoped 订阅。cg47 修复（`collapsible-pill.tsx:125-147`）会在 reload 后 `defaultExpanded` false→true rising-edge 时重新展开（尊重用户手动折叠的卡片）。

---

## 3. backend — 剩余 gap 的准确位置

### 3-1. 显示名(display name) 不对称
- `runtime_config.py:58-59` — `AgentConfig.subagents_config` + `AgentConfig.subagent_display_names`.
- 聊天 cfg 构建：`conversation_stream_service.py:163-168` — `cfg.subagents_config, cfg.subagent_display_names = await build_subagents_config(...)`。**两个值都会被填充。**
- **消费不对称**：
  - `subagents_config` → 两条路径都会传给 `create_deep_agent(subagents=...)`（`runtime_component_builder.py:767`）。
  - `subagent_display_names` → **只有 legacy 路径消费**（`agent_stream_runner.py:218` → `streaming.py:239,499-503`）。v3 runner（`langgraph_agent_stream_runner` / `stream_agent_response_langgraph`）**甚至不接收该参数**（`langgraph_streaming.py:214-228` signature 中没有）。
- 结果：v3 pill 显示 `task` args 中的 `subagent_type`（runtime name = `agent_xxxxxxxx`）或 `description`。不是人类可读的 Agent 名称。

### 3-2. reasoning masking
- `langgraph_protocol_adapter.py:103` — 所有 v3 event data 都会经过 `redact_private_reasoning(normalized)`。
- `langgraph_reasoning_redaction.py:6-30` — `reasoning`/`thinking`/`chain_of_thought` 等会被 `[redacted]`；reasoning **block** 只暴露 `DISPLAYABLE_REASONING_KEYS = {type,id,index,summary,message,status,signature}`。
- 结果：只有 provider 填充 `summary` 时，子 Agent 的内部思考才会部分暴露。这里是 G10“内部思考可见性”的策略决策点（需要与 ADR-021 值级 redaction 保持一致）。

### 3-3. dead code `extract_subagent_discovery`
- `langgraph_protocol_adapter.py:107-137` — 已完整实现，但 `app/` 内调用 0 次。frontend SDK 会通过 `task` tool call 自行 discovery，因此**功能上不需要**。如果 G10 选择在 emit 层注入显示名，该函数会继续作为 dead code，或成为清理对象。

---

## 4. 目标 / 非目标 / 成功标准

### 4-1. 目标
- **G10-A（显示名）**：在 v3 路径中，子 Agent pill/进度/右侧 rail 显示**人类可读的 Agent 名称**。
- **G10-B（实测 & 可靠性）**：在真实 LLM 生产路径中，**通过实测确认**子 Agent 内部进展（token/tool call）会实时显示在内联区域/右侧 rail；如果不行，则修复原因（namespace 发出缺失等）。
- **G10-C（思考摘要暴露，可选）**：以可观测方式暴露子 Agent 的 reasoning **摘要**（保持安全策略）。决策点。
- **G10-D（内联策略，可选）**：从可观测性角度重新调整并发 2 个/完成 5 个的限制，或提供“全部展开”toggle。决策点。

### 4-2. 非目标
- 为 legacy 路径新增内部 streaming（结构上不可行 + v3 是生产默认，因此无价值）。
- 修改 deepagents `task` 工具的阻塞执行结构（vendor code）。
- 为 `AsyncSubAgentMiddleware`（background subagent）新增 UI（单独 track，参见 `2026-06-13...streaming.md:82,98`）。
- 暴露子 Agent raw private reasoning（全文）— 出于安全明确排除。

### 4-3. 成功标准（done-when）
- 在 v3 真实 LLM 聊天中，当父级委派子 Agent 时，委派后立即出现**带 Agent 名称的 pill**，进行中的内部 tool call/部分输出实时显示在内联区域（或右侧 rail）。
- backend `uv run pytest` green（包括新增显示名/emit 测试）。
- frontend `pnpm vitest run` 全部 green + `pnpm build`/`pnpm lint` green。
- v3 子 Agent e2e（新增/增强 spec）green + 回归 spec（`chat-langgraph-v3-regressions.spec.ts` 子 Agent 用例）无回归。
- 捕获 PNG（可见性状态）1~2 张。

---

## 5. 决策点（需要用户确认）

| # | 决策 | 选项 | 默认建议 |
|---|------|------|-----------|
| D1 | **范围** | (a) 仅 A+B（显示名+实测） / (b) A+B+C（思考摘要） / (c) A+B+C+D（含策略） | **(a) 最小 → 实测后扩展** |
| D2 | **显示名注入方式** | (a) 向 v3 runner 传递 `subagent_display_names` 后 enrich `task` tool call args（与 legacy 相同模式） / (b) frontend 单独 fetch config 映射 | **(a) 复用 legacy 模式** |
| D3 | **思考摘要暴露（采用 C 时）** | (a) 仅 reasoning `summary`（保持现状，不改 redaction） / (b) 仅在子 Agent context 中扩展暴露 key | **(a) 保持现状 — 安全优先** |
| D4 | **内联策略（采用 D 时）** | (a) 不变 / (b) 提高限制（2→3~4） / (c) 用户“全部展开”toggle | **(c) toggle（策略不变+用户控制）** |

---

## 6. Phase 0 — 实测 spike（实现前必做）

**目标：通过日志确认“真实 LLM v3 路径中的子 Agent 内部事件是否确实以 `tools:<call_id>` namespace 发出”。**

1. 配置一个带子 Agent 的 Agent（父级 + 子级 1 个，真实 LLM key）。
2. 在 `langgraph_streaming.py` emit 循环中临时添加 debug logging（仅 namespace + method；**不提交**），或在浏览器 devtools 中观察 SSE event stream。
3. 委派执行后确认：
   - [ ] `task` tool call 是否以 `tools:<call_id>` namespace 出现
   - [ ] 子 Agent 内部 LLM token 是否以**相同或嵌套 namespace**发出 delta（`messages` channel）
   - [ ] 子 Agent 内部 tool call 是否发出
   - [ ] 是否注册到 frontend `stream.subagents`，且 scoped `useMessages` 被填充（React devtools/画面）
4. 产出：将实测结果记录到 `tasks/g10-spike-findings.md` → 确定 Phase 1 范围。

> scripted e2e（`e2e_langgraph_v3_script.py` slow subagent parts）已经验证内部 streaming，因此**路径本身大概率可用**。Phase 0 的目的，是缩小到“真实 LLM 是否也一样 + 除显示名之外还有没有额外 gap”。

---

## 7. 实现计划（按 Phase）

### Phase 1 — 显示名注入（G10-A）[核心，工作量小~中]

> **实现备注（实际采用，commit f15f7367）**：以下计划假设 D2=(a)“像 legacy 一样 enrich `task` tool call args”，但实际采用的是**side-channel `moldy.subagent_names` custom event + frontend 显示层替换**。原因：重写 checkpoint-backed `subagent_type` 会破坏执行/namespace binding/reload seeding，而 args enrich 在 stream-mode fallback（不改 args）中不起作用。side-channel 同时绕开这两个问题。用 backend 发出映射替代第 3 项（args enrich），第 4 项则由 `SubagentCard`+右侧 rail 通过 conversation-scoped atom 将 `runtime_name→display_name` 替换。

backend（计划当时假设 D2=a — 实际情况参见上方备注）：
1. 在 `langgraph_streaming.py` 的 `stream_agent_response_langgraph` signature 中新增 `subagent_display_names`（对应 legacy `streaming.py:239`）。
2. 在 v3 runner（`langgraph_agent_stream_runner`）中传递 `cfg.subagent_display_names`（对应 legacy `agent_stream_runner.py:218`）。
3. 发出 `task` tool call event 时，将 `subagent_type`（runtime name）enrich 为显示名。共享/复用 legacy `enrich_subagent_tool_call_parameters`（`streaming.py:139-156,499-503`）逻辑到 v3 发出路径。
   - 注意：v3 的 `astream_events` 会发出原始 tool call → 需要确定 enrich 点在 emit loop 还是 adapter（`adapt_*`），并确认不会与 redaction/persist 顺序冲突。
frontend：
4. 确认 `SubagentCard` 优先使用显示名（当前 discovery `name` fallback → task args）。必要时新增显示名字段映射。
测试：backend v3 emit 单元测试（显示名 enrich），frontend `subagent-card.test.tsx` 显示名用例。

### Phase 2 — 基于实测增强可靠性（G10-B）[依赖 Phase 0 结果]
- 如果 Phase 0 判定内部 token 没有发出：修复 namespace 发出/订阅路径（例如检查 emit loop 的 namespace filter、`synthesize_tool_events_from_values` 的 namespace 继承 `langgraph_tool_event_synthesis.py:119`）。
- 如果确认正常发出：只增强 e2e，加入更接近真实 LLM 的（slow subagent）用例。

### Phase 3 — 暴露思考摘要（G10-C）[采用 D1=b/c 时]
- 根据 D3 决定调整或维持 `langgraph_reasoning_redaction.py` 暴露策略。若调整，限定在**子 Agent context** + 与 ADR-021 对齐 + 更新 redaction 测试（`backend/tests/.../reasoning_redaction` 系列）。

### Phase 4 — 内联策略（G10-D）[采用 D1=c 时]
- 根据 D4 调整 `subagent-runtime.tsx:8-9` 常量，或新增“全部展开”toggle UI。更新 `subagent-runtime.test.tsx`（2 个限制/5 个折叠契约）。

### Phase 5 — 验证 & 捕获
- backend pytest / frontend vitest·build·lint / v3 子 Agent e2e / 回归 spec / 捕获 PNG。
- `/code-review` session diff。

---

## 8. 测试 & 回归 gate

**复用/增强现有测试：**
- frontend unit：`subagent-runtime.test.tsx`（内联策略）、`subagent-progress.test.tsx`、`subagent-card.test.tsx`、`collapsible-pill.test.tsx`（defaultExpanded 再同步）、`subagent-panel-content.test.tsx`、`activity-model.test.ts`。
- backend：`test_langgraph_protocol_adapter_subgraphs.py`（namespace 保留/discovery normalization）、`test_langgraph_streaming.py:111`（嵌套 namespace emit/replay）、`test_subagents_runtime.py:52`（`build_subagents_config`）。
- e2e：`chat-langgraph-v3-regressions.spec.ts:323-384`（subagent 结果内联保持：live→reload→HITL resume→第 2 次 reload）。helper `langgraph-v3-helpers.ts:97-109`，脚本 `e2e_langgraph_v3_script.py`（slow subagent parts）。

**核心回归 guard（绝不能破坏）：**
- 子 Agent 卡片内联结果在 reload/HITL resume 全阶段保持。
- 用户折叠的卡片不会自动重新展开（cg47 契约）。
- 保持 secret args redaction（`chat-langgraph-v3-regressions.spec.ts:259`）。

**E2E 执行：** throwaway stack（独立 PG port）+ `E2E_SCRIPTED_MODEL_ENABLED=true` + `E2E_SEED_USER_ENABLED=true`。（参见 CLAUDE.md E2E 隔离章节。）

---

## 9. 风险

| 风险 | 缓解 |
|--------|------|
| 真实 LLM 中内部 token 没有 namespace，而是 flat 混在一起 | 通过 Phase 0 spike **先**确认。没有数据前禁止开始实现 |
| 显示名 enrich 点与 redaction/persist/replay 顺序冲突 | 原样移植 legacy enrich 模式 + 用 replay 测试 guard |
| 暴露思考导致 secret/PII 泄漏 | D3 默认 = 维持现有 redaction。扩展时限定子 Agent + 同时进行值级 masking（ADR-021） |
| 放宽内联限制导致 streaming 性能/滚动下降 | D4 默认 = toggle（默认值不变）。考虑 `chat-scroll-follow-streaming-ux-plan.md:490` 的布局 |
| 共享 checkpointer pool 负载导致 e2e timeout | 通过与 origin/main 对照运行进行拆分判断（CLAUDE.md） |

---

## 10. 参考资料（精读顺序）
1. `docs/superpowers/plans/2026-06-13-assistant-ui-langgraph-v3-streaming.md` — v3 streaming/subagent discovery 架构原始文档。
2. `frontend/src/lib/chat/langgraph-runtime/subagent-runtime.tsx` — 内联策略实现。
3. `backend/app/agent_runtime/langgraph_streaming.py` + `langgraph_protocol_adapter.py` — v3 emit/adapter。
4. `backend/app/agent_runtime/langgraph_reasoning_redaction.py` — 思考暴露限制。
5. `backend/app/agent_runtime/streaming.py:139-156,499-503` — legacy 显示名 enrich（移植对象）。
