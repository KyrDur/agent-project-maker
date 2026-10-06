# 主聊天（v3 Agent run）功能缺口分析

- **编写日期**：2026-06-30
- **状态**：发现(discovery) — 优先级尚未达成一致。实现/日程未确定。
- **对象**：v3 主聊天（`langgraph_v3`, `use-moldy-langgraph-stream.ts` + `useExternalStoreRuntime`）。Builder/Assistant 面板不在范围内。
- **目的**：整理“Agent 运行的聊天”中**缺失的必需功能 / 有则更好的功能**，附上依据（代码·文档）并提出优先级建议。
- **方法**：分别盘点前端 UI/composer、后端 run 引擎、文档/PRD/计划（并行探索），再交叉对照“已有 vs 缺失”。

> **截至 2026-09-07 的状态附录。** 下方 G1–G16 与优先级是 2026-06-30 的 discovery 记录。本附录不删除该记录，也不重新审计其余 gap，仅标注本次 modernized-chat 范围内确认的状态。

## 当前状态附录（2026-09-07）

| 范围 | 当前状态 | 剩余限制 |
| --- | --- | --- |
| G2 retry/recovery | 将准确的 failed durable input 以 fresh request ID 重新接收，并执行 accepted-pending reconciliation。 | 若没有匹配的 durable input，则不提供 retry。 |
| G3 Steer | 在 cancel acknowledgement 后，从 committed state 启动 priority correction 的**新 run**。 | 未实现 same-run Steer（保留当前 run，并在下一个 agent step 消费新指令）。这也与修改 in-flight provider request 的 token 不同。 |
| G5/G6 export/search | export 为已加载 envelope 的 Markdown/JSON，search 为 rendered transcript 搜索。 | 不提供 backend full-history/PDF export。 |
| G9 command/context | 提供实际 capability command 和 authorized frozen text reference。 | `/compact` 因没有手动认证 endpoint 而 disabled，reference 也不是 multimodal input。 |
| run summary | 显示 terminal nullable metrics、root/descendant detail、bounded activity history。 | missing capture 表示 unknown 而非 0，并显示 activity truncation。 |
| MCP Apps | 提供 provenance-bound sandbox/proxy 和 ordinary tool fallback。 | open-link/message-append 被显式 deny，browser credential 不存在。 |
| side chat/pin | side chat 仅在 app-shell 生命周期内，pin 仅保存 user-selected display snapshot。 | 不提供 reload/cross-device side persistence、automatic summary、memory/prompt injection。 |
| G12 dictation | production 将 browser `SpeechRecognition` adapter 结果放入 editable composer，且不 auto-send。QA 使用 speech double。 | 未验证真实 microphone end-to-end。 |

当前实现的 source anchors 为 `use-moldy-langgraph-stream.ts`, `conversation_run_worker.py`, `chat_resource_context.py`, `mcp-apps/renderer.tsx`, `assistant-side-chat-provider.tsx`, `pinned-conversation-summary.tsx`, `use-browser-dictation.ts`。scripted-capture 的 named catalog 和 single-spec 执行契约遵循 ADR-006 的 2026-09-07 附录。本附录并不对 G1 multimodal、G4 structured output、G7 per-turn model、G8 manual compaction endpoint、G13 HITL 标准化等其余 discovery 项提出新的完成声明。

---

## 0. TL;DR

当前 v3 聊天**完成度很高** — 流式传输·rich Markdown（代码/表格/公式/mermaid/图片）·工具分组·搜索来源聚合·HITL 审批/ask_user·artifact 预览（20+ 类型）·附件显示·上下文 gauge·token/费用 popover·自动 compaction·子 Agent·memory（propose/save）·分支/重新生成·分享·navigator·Generative UI（DataTable/Chart/Stats/Terminal）。消息 feedback（👍👎）也已接线。

因此缺口主要集中在**Agent 能力 / run 控制 / 收尾（export·search）**。影响最大的单一缺口是**multimodal 模型输入**（Agent 实际看不到附件图片/文档）。

---

## 1. 当前优势（已有 — 非 gap）

为在上下文中理解 gap 的摘要。（详细文件 anchor 见 §5）

| 范围 | 已有功能 |
|---|---|
| 消息操作 | copy / edit / regenerate / branch picker(`<n/m>`) / **feedback 👍👎** / token·费用 popover / 时间戳 |
| composer | 多行+Enter 发送 / 文件附件（粘贴·拖拽）/ IME 安全 / opener questions / 上下文 gauge / queue(steer) 模式(Ctrl+Shift+Enter) |
| 流式 UX | witty 加载 / activity strip / stop / reconnect 徽章 / SSE resume / 上下文 gauge（80% amber·95% red）/ TTFT·tok-s·费用 popover / 自动 compaction marker |
| 工具/Agent | 工具 pill·分组 / 6种搜索+来源聚合 / 审批卡（approve/edit/reject·多动作索引）/ ask_user（option list·question flow）/ reasoning·phase timeline / 子 Agent 卡片 / deepagents state 面板 / memory 卡片 / code·diff 预览 / **Generative UI 数据卡片** |
| artifact | 内联卡片 + 右侧栏预览（PDF/DOCX/HWP/XLSX/PPTX/Mermaid/图片/代码/表格/data）+ Library |
| 对话 | navigator（pin/rename/delete/search/infinite scroll/⌘1-9）/ 分享链接（创建·复制·取消）/ jump-to-message / 右侧栏 resize |
| 后端 run | start/stream/stop·cancel / SSE resume(replay) / regenerate / branch·checkpoint fork / edit-and-rerun / 模型 fallback chain / memory(propose·save·proposal) / 子 Agent / trigger（计划任务）/ token·费用·Langfuse·audit |

---

## 2. Gap 分析

每项：**说明 · 当前状态（依据）· 价值 · 工作量 · 备注（文档是否 deferred）**。

### 🥇 Tier 1 — 最大功能 gap（直接影响 Agent 能力）

#### G1. multimodal 模型输入 — Agent 实际看不到附件图片/文档 ⭐ 最高优先
- **说明**：附件**显示**（P1）已完成，但附加图片没有作为 vision block、文档没有通过文本提取/RAG **传入模型消息**。用户可以附图，但 Agent 看不到。
- **依据**：后端 — “支持 image_url 消息 schema，但 frontend 附件→消息转换不存在”（`conversation_files.py`, `model_factory.py`）。图片生成仅限 Builder（`builder_v3/image_gen.py`）。文档：`docs/design-docs/chat-attachments-dev-plan.md` §3 D2/D4 明确 deferred 为 “P2（下一 phase）”。
- **价值**：↑↑（现代 Agent 几乎必需）。**工作量**：中（显示流水线已存在，主要是“附件→模型消息转换” + provider capability 门控）。
- **备注**：文档中有意 deferred（P2）。需要按 provider 分支 multimodal 支持。

#### G2. 错误后重试(Retry) — 低工作量·高价值
- **说明**：工具/模型失败时消息操作中**没有 retry 按钮**。regenerate 用于成功 turn 的重新生成，与错误恢复不同。run 失败后用户必须重新输入。
- **依据**：前端 — 操作栏只有 `ActionBarPrimitive.Reload`（regenerate），错误后 retry 未接线。后端 — 有 `tool_retry` middleware，但那是自动工具重试，与用户触发的 run-level retry 不同。
- **价值**：中~高（可靠性 UX）。**工作量**：小。

#### G3. run 途中介入/Steering（mid-run inject）— 仅部分存在
- **说明**：没有向执行中 run **注入上下文/纠正**的路径（只能中止）。Ctrl+Shift+Enter 的 "queue(steer)" 只是排队*下一条*消息，并不会插入当前 run。
- **依据**：后端 — “没有发送 mid-graph Command / 没有 live prompt·context steering”（`conversation_agent_protocol_commands.py`）。
- **价值**：中~高（Agent 可控性）。**工作量**：中~大（run lifecycle + graph Command 路径）。

#### G4. structured output / 强制 tool_choice — 未暴露
- **说明**：LangChain 模型支持 JSON mode·structured output·`tool_choice="required"`，但**未暴露到 Agent 设置**。限制了需要可靠结构化响应的 Agent。
- **依据**：后端 — “structured output / JSON mode：模型支持，但未作为 config 暴露”（`model_factory.py`）。
- **价值**：中（Builder·自动化 Agent）。**工作量**：中。

### 🥈 Tier 2 — 有则更好的功能

#### G5. 对话 export / 下载（markdown · JSON · PDF）
- 完全没有。常见且实用（分享·记录·调试）。**价值中 / 工作量小~中**。（已有分享链接，但静态文件 export 是另一回事。）

#### G6. 对话内(in-conversation)全文搜索
- 只有 navigator（对话**之间**）搜索，**没有单个对话内的消息/工具结果全文搜索**。长 Agent run 中寻找历史结果不方便。jump-to-message 仅用于 artifact。**价值中 / 工作量中**。

#### G7. composer 模型选择 / 每 turn 切换模型
- 模型在 run 开始时固定，中途无法切换（仅错误时有 fallback chain）。例如在便宜↔强模型间切换会很有用。**价值中 / 工作量中**。（`model_factory`：model bound at run init。）

#### G8. 手动 compaction 按钮（用户主动“现在压缩”）
- 只有自动 compaction，手动为 deferred（Optional）。类似 Claude-Code。**价值中 / 工作量小~中**。文档：`dev-plan-context-compaction-marker.md` — “后续(Optional) 手动 compact 工具+按钮”。

#### G9. Slash command / @mention
- assistant-ui primitive 已有但**未使用**（也无 i18n Key）。`/clear`·`/model`·`/summarize`，以及文件·Agent·工具 mention。**价值中 / 工作量中**。

#### G10. 子 Agent 流式可见性
- 父 Agent **只看到最终结果**，内部进度/思考不可见（“subagent progress visibility：仅最终结果”）。可提升可观测性。**价值中 / 工作量中**。

#### G11. Generative UI 数据卡扩展
- 为刚添加的 DataTable/Chart/Stats/Terminal 增加 **CSV export · 列切换 · 图表交互（drilldown/filter）**。图表目前是 plain SVG 静态渲染。**价值小~中 / 工作量小（增量）**。

#### G12. 语音输入 / draft 自动保存
- 只有 dictation hook（assistant-ui），**UI 未接线**。composer 文本不会跨会话保留。**价值小~中 / 工作量小**。

### 🥉 Tier 3 — 更大/运维性（文档中有意 deferred 或 ops）

#### G13. HITL 标准化（草稿，未合并）
- "edit" 只是 payload shape 而非一等 enum / 多动作被分散成 N 张卡（没有统一“N项待处理”UX）/ 子 Agent interrupt 继承 Bug / 标准 interrupt 尚未完整接入 UI。文档：`docs/design-docs/hitl-ask-user-standardization-plan.md`（仅设计）。**价值中 / 工作量大**。

#### G14. 成本提醒 / 使用量 quota
- 没有阈值警告·quota 强制（仅追踪·聚合，`daily_spend_*`）。**价值中(ops) / 工作量中**。

#### G15. trigger 输入参数化 / 输出 action
- schedule run **每次都是同一提示词**，没有动态输入·webhook/通知输出·dry-run（`trigger_executor.py`）。**价值中 / 工作量中**。

#### G16. 其他架构
- 聊天内图片**生成**（当前仅 Builder）/ **LangSmith**（当前仅 Langfuse）/ **AG-UI adapter**（ADR-020, Phase P6 deferred）/ 跨对话·RAG memory 自动注入（当前工具手动）。

---

## 3. 优先级 + 推荐

| 排名 | 项目 | 价值 | 工作量 | 备注 |
|---|---|---|---|---|
| **1** | **G1 multimodal 输入**（图片 vision + 文档提取） | ↑↑ | 中 | 在显示 P1 之上连接“附件→模型消息” |
| **2** | **G2 错误 retry** | 中~高 | 小 | 快速可靠性 win |
| **3** | **G5 对话 export**（md/json） | 中 | 小~中 | 实用·独立 |
| 4 | G3 mid-run steering | 中~高 | 中~大 | 涉及 run lifecycle |
| 5 | G4 暴露 structured output | 中 | 中 | Builder 可靠性 |
| 6 | G6 对话内搜索 / G8 手动 compaction / G9 Slash command | 中 | 中 | UX |

**推荐：先做 G1（multimodal 输入）。** 显示流水线（P1）已经铺好，只需连接“附件 → 模型消息转换 + provider capability 门控”，而且让 Agent 看图片、读文档的体感提升最大。如果想要快速 win，可以搭配 G2（retry）·G5（export）。

建议的推进方式：将选定项目（类似 Generative UI）按 **Phase 0 spike → 设计文档 → 分阶段实现 + 回归 gate** 推进。

---

## 4. 注意 / 限制

- 本分析是基于代码/文档 inventory 的**发现**，各 gap 的准确实现难度/风险需在启动对应项目时通过 spike 确认。
- 部分项目（G1·G8·G13·G15·G16）在文档中被记录为**有意 deferred**，因此属于“后续 phase”而非“遗漏”。优先级按价值·工作量评定，与是否 deferred 无关。
- 即使被归类为“优势”的功能，其细节 policy（例如多动作 HITL 统一、图表交互）也可能尚未完成。

## 5. 参考（inventory 来源）

- 前端 UI/composer：`frontend/src/components/chat/`（assistant-thread.tsx, composer, tool-ui/, right-rail/, navigator），`frontend/src/lib/chat/`。
- 后端 run 引擎：`backend/app/agent_runtime/`（langgraph_streaming, runtime_component_builder, model_factory, subagents, trigger_executor, middleware_registry），`backend/app/routers/conversation_agent_protocol_*`，`backend/app/services/`。
- 计划/文档：`docs/PRD.md`, `docs/design-docs/`（ADR-012/016/019/020, chat-attachments-dev-plan, chat-generative-ui-dev-plan, dev-plan-context-compaction[-marker], generic-tool-call-grouping-plan, hitl-ask-user-standardization-plan），`TASKS.md`。
</content>
