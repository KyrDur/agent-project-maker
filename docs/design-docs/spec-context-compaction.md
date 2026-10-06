# SPEC — Context Compaction 单一化 + 手动 compact + UI 表达

状态：Draft（实现前共识用）
相关：ADR-001(Deep Agent Engine), ADR-012(HiTL Middleware), ADR-019(System LLM), context gauge(commit 82f8ab32)
实现文档：`dev-plan-context-compaction.md`

> **更新（范围·事实纠正）** — 实现文档中确认/纠正如下。若与本 SPEC 部分描述冲突，以实现文档优先。
> 1. **自动 compaction 在正式模型（LangChain 已知 Claude/GPT/Gemini）中已正常工作**（有 `model.profile`）。**仅 custom/`openai_compatible` 使用固定 170k fallback，阈值错误** → Phase 0 修正。
> 2. **手动 compact 不在本次范围内（后续选项）**。只靠自动已足够。推荐范围 = **Phase 0（context_window 单一化）+ 自动压缩 inline marker**（Tier 2）。
> 3. **即使加入手动，也无需“移除”自动 middleware**。`create_summarization_tool_middleware` 只新增工具层，自动仍由 deepagents 默认保留（无重复，共享 state）。只有在 `model.profile` read-only、必须通过显式 middleware 修正阈值时，才考虑移除。
> 4. context_window 注入默认使用**选项 A（profile 注入）**，选项 B（排除+替换）作为 fallback。
> 5. **Engine 已更新到 deepagents `0.7.11`。** Compaction 原始内容路径不再由 thread ID 派生，而使用避免 parent/subagent 记录冲突的 opaque `/conversation_history/session_<uuid>.md` 格式。UI 与 protocol 将该路径作为字符串传递，不依赖文件名结构。

## 1. 背景 / 问题

deepagents `0.7.11` 会在 `create_deep_agent` 默认栈中**自动注入 `SummarizationMiddleware`**（graph.py）。当 token usage 超过基于 model profile 的阈值时，会用 LLM summary 替换旧消息，并把原文 offload 到 invocation-scoped `/conversation_history/session_<uuid>.md`。我们没有关闭它，因此**自动 compaction 已启用**。

但仍有三个空缺：

1. **context size source 分裂成两套，而我们这一侧为空。**
   - 我们 DB 的 `models.context_window`（context gauge 读取的值）在 **seed/UI 中都没有填充**（`default_models.py` 中 `context_window` 为 0 条，模型创建/编辑 UI 无字段）。→ 真实服务前模型为 NULL → **gauge 全部因“未设置上限”而停用**。
   - deepagents 自动 compaction 使用 **LangChain model `.profile["max_input_tokens"]`**（summarization.py L234）。`model_factory` 未注入我们自己的值，因此正式模型（有 LangChain profile）只有 85% 阈值生效，而 **`openai_compatible`/custom 无 profile → 使用保守固定 fallback**。
   - 结果：gauge % 与 compaction threshold 使用**不同（或为空）的数字**，彼此错位。

2. **手动 compact 被关闭。** `compact_conversation` 工具（`SummarizationToolMiddleware`）是 opt-in，但我们的 stack 中没有。用户说“帮我压缩”也无法执行。

3. **没有表示 compaction 的 UI。** streaming/前端完全没有压缩标识 → 自动 compaction 发生时用户不知道。

### 官方推荐方案（LangChain Deep Agents 文档，已用 Context7 确认）
- 手动 compaction：添加 `create_summarization_tool_middleware(model, backend)` → `compact_conversation` 工具。**默认需要用户批准（approval-by-default）**。与自动 compaction 共享相同 engine/state。
- Compaction 在 `messages` stream 中以**tool call**出现 → 推荐像普通工具一样渲染。
- 阈值应 **model-aware**（需要 context size）→ 必须先解决空缺 #1。

## 2. 目标 / 成功标准

- [ ] `models.context_window` 成为单一 source of truth，**gauge·自动 compaction·手动 compaction 全部使用同一数字**。
- [ ] 用户可通过两条路径执行手动 compaction：(a) 在对话中说“帮我压缩”，(b) composer gauge 旁的 **compact 按钮**。
- [ ] Compaction 发生时 UI 可感知：手动=tool pill+审批卡，自动=inline“已总结”marker + 查看原文。
- [ ] 在 `openai_compatible`/custom 模型中 compaction threshold 也按预期工作（含验证）。

### 非目标（Out of scope）
- **clear（重置对话）**：现有**“新对话”（new conversation）**已满足该意图 → 不新增 in-thread clear。（如需要，只重新暴露 gauge 旁“新对话”快捷入口 — 可选）
- 升级 deepagents 版本。

## 3. 设计 — Phase 0/1/2

### Phase 0 — context_window 单一来源化（基础，优先）

最重要。如果不做，gauge 停用 + threshold 不一致，Phase 1·2 效果会大打折扣。

1. **填充**
   - `backend/app/seed/default_models.py`：为正式模型 seed `context_window`（例如 Claude 200000、GPT-4o 128000、Gemini 1.5/2.x 等）。注释注明来源。
   - 模型创建/编辑 UI（`frontend/.../settings/models`，后端 `schemas/model.py` 已有 `context_window` 字段）新增**输入字段** — 运营人员可直接给 custom/gateway 模型设置。
   - （可选）从 LangChain profile **自动 derive**：创建模型时若 `init_chat_model(...).profile["max_input_tokens"]` 存在，则作为默认值填入。

2. **注入（核心）— 让 compaction 使用我们的数字。** 二选一（实现时需验证）：
   - **(A) 注入 model profile**：在 `model_factory` 创建的 LangChain model 的 `.profile["max_input_tokens"]` 设置为我们的 `context_window` → deepagents 自动 compaction 直接使用我们的值。*侵入最小，但需确认 `.profile` 是否可设置。*
   - **(B) 用显式 middleware 替换**：通过 deepagents alias 排除自动注入的 summarization，再由我们显式加入 `create_summarization_middleware(model, backend, SummarizationMiddlewareOptions(trigger=("tokens", int(context_window*0.85)), ...))`。*显式、易控制。与 ADR-012 “规避 auto-injected + 显式实例”模式一致。*
   - → **推荐：(B)**（控制/一致性）。若无 `context_window`，保持 deepagents 默认（profile/固定 fallback）。

3. **验证**：在主力模型（Anthropic/OpenAI/openai_compatible）中验证自动 compaction 是否在预期 token 触发 + gauge % 是否一致，使用 E2E/集成测试。

**done-when**：gauge 在真实模型中启用显示 / compaction trigger token = `context_window*0.85` / openai_compatible 也正常。

### Phase 1 — 默认开启手动 compact 工具（小型后端改动）

- 在 `runtime_component_builder` 增加 `create_summarization_tool_middleware`（或 `SummarizationToolMiddleware`）→ 暴露 `compact_conversation` 工具。
- 因为 approval-by-default，调用时**自动显示现有 HiTL 审批卡** → 无需额外 UI 即可表达“要压缩吗？”。
- gate：deepagents 在 usage **低于约 50% 时阻止使用工具**（防止过早压缩）— 验证该行为。
- 在 trigger 模式（schedule）中 HiTL 不启用，因此需要决定 compact 工具自动批准/跳过策略。

**done-when**：对话中说“帮我压缩”→ Agent 调用 `compact_conversation` → 审批卡 → 批准后执行 summary+offload。

### Phase 2 — UI：compact 按钮 + 自动 compaction marker

1. **手动 compact UI（主要复用现有基础设施）**
   - `compact_conversation` tool call → 通过**现有 tool pill**渲染。在 `tool-icons.ts` 增加 `compact_conversation → 🗜️`（例如 `ArchiveIcon`/`Minimize2Icon`）。
   - gauge 旁增加 **compact 按钮**（`context-window-gauge.tsx` 附近）：点击 → 触发 compact。
     - v1 触发方式：**方式 A** — 向 Agent 发送隐藏的压缩请求 → 工具调用（消耗 1 次 LLM turn）。v2：专用 endpoint，无需 turn 直接执行（后续）。
     - **低于 ≥50% gate 时按钮禁用** + tooltip（“还没占用到需要压缩的程度”）。
   - 审批卡 = “进行压缩”表达。无需额外 spinner（gauge 下降即可看见结果）。

2. **自动 compaction（85%）marker（需要新增检测）**
   - 自动 compaction 不是 tool call，而是通过**插入 summary HumanMessage**体现（`_is_summary_message`：内容包含 `Here is a summary of the conversation to date` / `<summary>` + `/conversation_history/...` 路径）。
   - 前端检测该消息 → 渲染**inline marker**：“🗜️ 已总结之前的对话并整理上下文 · 查看原文”（原文 = 通过 `read_file`/artifact 打开 offload 文件）。
   - 或在后端 streaming 中把 compaction step emit 为专用 SSE event（更稳健但工作量更大）— v2。

**done-when**：手动 compact 显示 tool pill+审批，自动 compaction 后显示 inline marker 且可查看原文。

## 4. 影响文件（预计）
- 后端：`seed/default_models.py`、`schemas/model.py`（已有字段）、`routers/models`（创建/编辑）、`agent_runtime/model_factory.py` 或 `runtime_component_builder.py`（注入/middleware）、`agent_runtime/middleware_registry.py`（summarization 排除/显式）、streaming（自动 compaction event，v2）。
- 前端：`settings/models` form（字段）、`lib/chat/tool-icons.ts`（compact icon）、`context-window-gauge.tsx`/`assistant-thread.tsx`（按钮）、summary 消息检测 + inline marker component、i18n。

## 5. 待定决策（实现前确认）
- Phase 0 注入：(A) profile 注入 vs (B) 显式 middleware — 推荐 (B)，但需根据 `.profile` 可设置性重新评估 (A)。
- compact 按钮触发：是否可接受 v1 方式 A（消耗 turn），还是直接做专用 endpoint(B)。
- trigger（schedule）模式下 compact 工具/自动 compaction 策略。
- 自动 compaction marker：消息检测（轻量）vs 专用 SSE event（稳健）— v1 使用检测。

## 6. 验证计划
- 单元：context_window 注入/threshold 计算、summary 消息检测逻辑、tool-icon mapping。
- 集成/E2E：真实模型自动 compaction trigger token = 预期值、与 gauge 一致；“帮我压缩”→审批卡→生成 offload 文件；compact 按钮 ≥50% gate；自动 compaction 后 inline marker + 原文查看。
- Capture：手动 compact（tool pill+审批）、自动 compaction marker、gauge 下降 before/after。
