# 开发规划书 — Context 压缩（Compaction）：gauge 正常化 + 自动压缩表达

> 为了能只凭这一份文档从头到尾完成实现，本文明确列出**实际源码对应的文件:行号 + 修改 snippet + 验证**。
> 目标版本：deepagents `0.6.9`，Moldy main（`d98ddd67` 之后）。
> 范围决定：**手动 compact 不包含在本次范围内（后续选项）**。仅自动压缩就足以构成功能安全网，因此推荐范围（Tier 2）为**Phase 0（context 单一化）+ Phase 1（自动压缩表达）**。
> 前置：`docs/design-docs/spec-context-compaction.md`。

---

## 0. 一览 — 范围 & 工作量

| Tier | 范围 | 用户体验 | 预计 |
|------|------|------------|------|
| 1（最小） | **仅 Phase 0** | gauge 工作 + 自动压缩前模型正常运行（静默压缩） | ~2–3d |
| **2（推荐）** | **Phase 0 + Phase 1** | + “刚刚已自动整理 · 查看原文” marker | **~3–4.5d** |
| 后续(Optional) | 手动 compact 工具 + 按钮 | 主动压缩（Claude Code 式） | +2–3d |

**核心一句话：** 真正价值在 **Phase 0**（gauge 启用 + 自定义模型自动压缩 threshold 修正）。手动不是必需 → 拆分到后续。

**Day1 spike 1 项（其余为事实确认）：**
- **`model.profile` 可写吗？** → 如果可以，Phase 0 就是一行。不可写则 fallback 到显式 middleware。

---

## 1. 背景 — “自动压缩是不是没工作？”的准确答案

deepagents `create_deep_agent` 会**自动注入 `SummarizationMiddleware`**（graph.py:779 main，:626/:702 subagent）。该 middleware 通过 `compute_summarization_defaults(model)`（summarization.py:223-260）读取 **`model.profile["max_input_tokens"]`**：

| 模型类型 | `model.profile` | 自动压缩 |
|----------|-----------------|-----------|
| **正式模型**（LangChain 认识的 Claude/GPT/Gemini） | 内置 O | ✅ **已经正常** — `trigger=("fraction",0.85)` |
| **自定义/`openai_compatible`/gateway** | 无 | ⚠️ **固定 `("tokens",170000)` fallback** → 与实际上限无关（小模型会在触发前报错，大模型则过早触发） |

→ “自动功能不起作用”这句话**只对自定义/gateway 模型成立**（threshold 错了）。正式模型已经可以工作。**Phase 0 会把这个 threshold 校正为我们的 `context_window`**。另外，**context gauge**（`context-window-gauge.tsx`）也只有存在这个值时才会启用（当前所有模型均为 NULL → disabled）。

> ⚠️ **几乎不需要“移除”自动 middleware。** 后续即使加上手动工具，`create_summarization_tool_middleware` 也只会**新增 tool layer**，自动 middleware 仍由 deepagents 默认提供（源码 docstring：*“Only the tool layer is registered ... `create_deep_agent` adds one by default, so dropping it into `middleware=[...]` gives you both layers; they share state via `_summarization_event`”*）。不会产生重复。（只有 §6 的 fallback 情况才需要移除。）

---

## 2. 当前状态（已核对源码）

### 已经具备的部分 ✅
- ORM/schema/CRUD：`Model.context_window`（`models/model.py:46`）、schema（`schemas/model.py:26/48/69/92/107`）、创建 `routers/models.py:157`、修改 `:205-215`、序列化 `services/model_service.py:100`。
- **`ModelBrief.context_window` 已暴露**（backend `schemas/agent.py:151`，frontend `lib/types/index.ts:36`）— gauge 会读取。
- **模型新增/编辑 UI 输入框已实现**（`model-add-dialog.tsx:91,222-235`、`model-edit-dialog.tsx:54,260-272`）。
- 自动压缩本身可工作（仅限正式模型，见 §1）。

### 当前缺失的部分 ❌（本次工作）
- `default_models.py`：**context_window 0 项** → 所有模型 NULL → gauge disabled + 自定义模型 threshold 错误。
- 我们的 `context_window` **没有传递给压缩引擎（model.profile）**。
- **完全没有提示自动压缩发生的 UI**。

---

## 3. Phase 0 — context_window 单一来源化（必做）

目标：让 `models.context_window` 成为 single source of truth → gauge + 自动压缩 threshold 使用同一个数字。

### 0.1 填充 seed 值（trivial）
`backend/app/seed/default_models.py` — 在 `DEFAULT_MODELS` 的 4 个 dict 中新增 `"context_window": int`。
```python
{
    "provider": "anthropic", "model_name": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6",
    "is_default": True,
    "cost_per_input_token": Decimal("0.000003"), "cost_per_output_token": Decimal("0.000015"),
    "context_window": 200000,   # ← 新增（来源注释）。GPT-4o=128000，Gemini 等官方上限
},
```
- ⚠️ 如果 seed 只在“无记录时 insert”，**现有生产 DB 模型仍会保留 NULL** → 通过 operator UI（已实现）修正，或做 1 次性 backfill。（确认 seed upsert 行为。）

### 0.2 context_window → 注入压缩引擎（核心，spike 后选 1）

**选项 A — 注入 model profile（推荐·idiomatic）：**
将 deepagents 读取的 `model.profile["max_input_tokens"]` 设置为我们的值 → **默认自动 middleware 会继续使用正确 threshold**。无需改 middleware stack。
- 位置：`agent_runtime/model_factory.py:create_chat_model()`（L215-278）返回前。
  ```python
  # context_window 通过 **extra 传入
  if context_window:
      try:
          model.profile = {**(getattr(model, "profile", None) or {}), "max_input_tokens": int(context_window)}
      except Exception:
          pass  # 如果 read-only，则用选项 B
  ```
- **spike：确认 `.profile` 是否可写**（取决于 LangChain 版本，可能是 property）。

**选项 B — 替换为显式 middleware（fallback，仅 profile read-only 时使用）：**
排除 deepagents 自动 summarization，改为我们自己添加。
- `runtime_component_builder._prepare_runtime_components()`（L494-666）middleware 装配部分（L570-575）：
  ```python
  from deepagents.middleware.summarization import create_summarization_middleware
  if cw:
      middleware.append(create_summarization_middleware(model, components.backend))  # 我们已设置 profile，或直接配置 trigger
  ```
- 在 `build_agent`（`runtime_component_builder.py:83`）的 `create_deep_agent` 调用中传入**自动排除**（`excluded_middleware={"SummarizationMiddleware"}` — 准确参数路径在 spike 中确认；`_excluded_middleware.py:90-165` 按 `.name` 字符串匹配）。

> 建议：**A**。只要 profile 正确，deepagents 默认逻辑就会正确工作 → 不需要排除/替换。B 仅在 A 不可行时使用。

### 0.3 AgentConfig wiring
- 在 `agent_runtime/runtime_config.py` 的 `AgentConfig`（L14-84）中新增 `context_window: int | None = None`。
- 在填充 cfg 的 conversation router/`chat_service`（→ `_prepare_agent`）中设置 `Agent.model.context_window`（Agent.model 关系已加载）。
- 打通向 model_factory 传递 cw 的路径（通过 `_model_constructor_params` 或调用处 `**extra`）。

### 0.4 （UI 已完成）— 只需确认
模型新增/编辑 dialog 已存在 context_window 输入框（§2）。无需修改。

### Phase 0 验证
- 单元：cw→trigger token（0.85）、AgentConfig 传递、model_factory 注入 profile。
- integration/E2E：用真实模型确认 **gauge enabled** + 长对话在 `cw*0.85` 附近触发自动压缩。**openai_compatible（无 profile 模型）也按我们的 cw 工作**。
- done-when：gauge enabled / 压缩 threshold=按我们的 cw / gauge% 与 threshold 一致。

---

## 4. Phase 1 — 自动压缩 inline marker（推荐范围中的展示部分）

目标：自动压缩发生时让用户知道（避免因静默替换消息而困惑）。

### 1.1 检测（frontend，稳健）
自动压缩会通过**插入摘要 `HumanMessage`**显现。识别 key（源码确认）：`additional_kwargs["lc_source"] === "summarization"`（`_is_summary_message` summarization.py:501-516）。content 中包含 offload 路径 `/conversation_history/{thread_id}.md`（L533-564）。
- 位置：`frontend/src/lib/chat/langgraph-runtime/langchain-message-conversion.ts`（`convertMoldyLangChainMessage`）— 转换时给该 message 添加 `metadata.isCompactionSummary = true` + 提取 offload 路径。
- ⚠️ 该 message 的 role=user，但属于**系统摘要** → 不能渲染成普通 user 气泡。应在转换阶段拦截并走 marker 分支。

### 1.2 渲染（新增组件）
- `frontend/src/components/chat/compaction-summary.tsx`（新增）：inline marker
  - “🗜️ 已摘要之前的对话以整理 context · 查看原文”
  - “查看原文” = 用从 content 提取的 `/conversation_history/...` 路径，通过 `read_file`/artifact 打开（复用现有文件工具）。
- 在 message render 分支点，如果 `metadata.isCompactionSummary` 则使用该组件。
- i18n：在 `messages/ko.json`+`en.json` 中新增 `chat.compaction.summary`、`chat.compaction.viewOriginal`。

### 1.3 （增强，Optional v2）专用 SSE event
- 若要更稳健，可在 backend 直接 emit 专用 compaction event：在 `agent_runtime/event_names.py` 新增 `COMPACTION` + 在 `streaming.py`/`langgraph_streaming.py` 检测 message 数量减少。**v1 仅使用 message marker（1.1）已足够** → 此项后续。

### Phase 1 验证
- 通过长对话触发自动压缩 → 显示 inline marker + 可打开原文。压缩后 gauge 下降。
- capture：压缩前/后（marker + gauge 下降）。

---

## 5. 修改文件摘要（推荐范围 Tier 2）

**backend**
- `seed/default_models.py` — context_window seed（+ 必要时 backfill）。
- `agent_runtime/runtime_config.py` — `AgentConfig.context_window`.
- `agent_runtime/model_factory.py` — （选项 A）注入 profile + 接收 cw 参数。
- 填充 cfg 的 conversation router/`chat_service` — 设置 cw。
- （仅选项 B）`runtime_component_builder.py` — 自动排除 + 显式 middleware。

**前端**
- `lib/chat/langgraph-runtime/langchain-message-conversion.ts` — 检测/分流摘要 message。
- `components/chat/compaction-summary.tsx`（新增）— inline marker。
- message render 分支点（assistant-thread message component）— 渲染 marker。
- `messages/ko.json`+`en.json` — i18n.

---

## 6. 后续(Optional) — 手动 compact 工具 + 按钮

> 仅自动功能已足够，因此拆开。用户出现“想在任务前先压缩”的需求时再增加。**只需新增，不需要删除现有部分。**

- **backend**：在 `runtime_component_builder` middleware list 中新增 `create_summarization_tool_middleware(model, components.backend)` → 暴露 `compact_conversation` tool。**无需移除自动 middleware**（只新增 tool layer，自动部分继续由 deepagents 默认负责，state 共享）。usage 低于 50% 时工具会自动拒绝（`_compact_threshold=value*0.5`）。
- **审批策略决定**：压缩可逆（原文 offload），因此建议**无需审批立即执行**。若需要审批，则在 `interrupt_on` 中新增 `compact_conversation` → 自动复用现有 HiTL approval card（`approval-card.tsx`）。
- **frontend**：在 `tool-icons.ts` 的 `EXACT_TOOL_ICONS` 中新增 `compact_conversation: <Icon>` 1 行（tool pill 自动渲染）。gauge 旁新增 compact button（`assistant-thread.tsx` ThreadComposer L1122-1130）— 通过 `pct = (latestTurnUsage.prompt_tokens / contextWindow)*100` 仅在 **≥50% 时启用**。trigger v1 = `sendMessage("压缩对话")`（callback prop 从 page→section→thread→composer 传递）。
- 预计 +2–3d。

---

## 7. 工作顺序 & 风险

```
Day1   Spike：model.profile 可写吗？→ 确定 Phase 0 选项 A/B
Day1-2 Phase 0：seed +（A 注入 profile 或 B 替换）+ AgentConfig wiring + 验证
Day3   Phase 1：检测摘要 message + marker component + i18n
Day3-4 E2E + capture（gauge 前后、marker）+ /code-review
```

| # | 风险 | 应对 |
|---|--------|------|
| R1 | `model.profile` read-only | fallback 到选项 B（排除+显式添加） |
| R2 | seed 不更新已有 row | operator UI（已实现）或 backfill |
| R3 | 把摘要 message 误渲染成 user 气泡 | 在 conversion 阶段分流（§4.1） |
| R4 | 正式模型自动压缩本来就能工作 | 对它们而言 Phase 0 主要用于“gauge”；对自定义模型则是核心 |

**实现前只需确定：** 选项 A/B（R1 spike 结果）之一。手动部分（§6）另行决策。

---

## 8. 测试策略 — “无需填到 85%”也能验证

核心原理：**自动压缩 threshold 与 `context_window` 成比例**（`0.85 × max_input_tokens`）。因此**测试中把 `context_window` 设小（例如 1500~2000），只需 2~3 条 message 就能越过 threshold**，无需无限填满 200k。

```
测试模型 context_window = 1500
→ trigger ≈ 0.85 × 1500 = 1275 token
→ system prompt + answer 2~3 turn 即可达到 → 发生自动压缩
```
> token count 由 `count_tokens_approximately` **直接从 message content** 计算（不需要 usage_metadata）。因此 scripted 模型只要 message 足够长也能计数。最稳妥的方式就是缩小 `context_window`。

### Level 1 — frontend 单元（立即，无需 LLM）[必做]
只验证压缩“展示”。无需真正 trigger。
- `langchain-message-conversion.ts`：转换**mock 摘要 message**（`HumanMessage` + `additional_kwargs.lc_source="summarization"`，content 含 `/conversation_history/...` 路径）→ 断言 `metadata.isCompactionSummary === true` + 提取到 offload 路径。
- `compaction-summary.tsx`：断言 marker 渲染“已摘要 + 查看原文”，且不渲染成普通 user 气泡。
- vitest，毫秒级。**与 85% 无关。**

### Level 2 — backend 集成（数秒，非浏览器）[推荐]
验证压缩是否真的被**触发** + offload。
- 测试中用 `context_window=1500`（较小）的模型构建 Agent → invoke 2~3 条 message → assert state messages 是否被替换成摘要 message（`lc_source=="summarization"`）+ 是否生成 offload 文件。
- 如果可用 aiosqlite/in-memory，则可快速且确定性运行。（如必须调用 LLM，可用 E2E scripted 模型或 cheap gateway 模型，最少 turn。）
- Phase 0 本身的单元测试：`cw → trigger token(0.85)` 计算、`model.profile` 注入后 `compute_summarization_defaults` 是否走 fraction 路径。

### Level 3 — E2E（浏览器，几 turn）[推荐]
覆盖 UI。**不是填到 85%，而是用 tiny-context 跑几 turn。**
- 使用隔离 stack（5433/8101/3100）。把测试 DB 模型的 `context_window` UPDATE 为较小值（复用 gauge capture 时的模式）→ 发送 2~3 turn → 断言/capture **inline marker 显示 + gauge 下降**。
- capture：压缩前/后（marker + gauge 从 90%→较低值）。

### 选项 — 确定性的 scripted 压缩 marker（最稳健的 frontend E2E）
如果想在不依赖 LLM·token counting 的情况下 100% 稳定地 E2E frontend marker，可像现有 `E2E_TOOL_GROUP`/`E2E_SEARCH_GROUP` 一样，在 `backend/app/agent_runtime/e2e_scripted_model.py` 中新增 **`E2E_COMPACTION` scripted marker**：
- 输入 marker 时确定性地发出**摘要 `HumanMessage`（lc_source="summarization"）+ offload 路径**。
- frontend 接收该 message 后渲染 marker → 断言。（与 trigger 逻辑分离，无 flaky。）
- 分工：**trigger 行为 = Level 2（tiny-context）**，**marker 渲染 = scripted marker E2E**。

### 验证矩阵
| 验证对象 | 方法 | 填满 85%？ |
|-----------|------|-----------|
| gauge enabled/% 准确 | E2E tiny-context（现有模式） | ❌ |
| 自动压缩 trigger + offload | Level 2 integration（cw=1500） | ❌（几 turn） |
| marker 转换/渲染 | Level 1 unit（mock） | ❌ |
| marker UI 全链路 | scripted `E2E_COMPACTION` 或 Level 3 | ❌ |
| 自定义模型 threshold 修正 | Level 2：注入 profile 后走 fraction 路径 | ❌ |
