# 开发规划书 — 自动压缩显示(marker) B-完整版：“压缩中… → 摘要完成”

> 为了能**只看这一份文档**就从头到尾完成实现，本文基于实际源码明确列出**文件:行号 + 已验证事实 + 修改 snippet + 测试 + 风险**。
> 目标版本：deepagents `0.6.9`、langchain `1.4.x`、Moldy 分支 `feature/context-compaction`（Phase 0 commit `c1b03660` 之后）。
> 前置：Phase 0（`models.context_window` 单一化 + gauge + 自动压缩 threshold 修正）**已完成、验证并提交**。本文是在此基础上增加的**显示(marker)**工作。
> 范围：**自动压缩发生时，在 v3 聊天（生产）中显示 (a) 进行中的“压缩中…”临时状态 + (b) 完成后的“已摘要之前的对话 · 查看原文”永久 marker**。同时顺带处理**防止摘要 token 泄漏（污染 answer）**（LangChain 官方建议）。

---

## 0. 一览 — 做什么 / 在哪里

| 阶段 | 用户体验 | 核心变更 |
|------|------------|-----------|
| 压缩进行中 | 回复 spinner 标签变为**“压缩中…”**（与答案生成区分） | backend：检测摘要 token → emit `compaction(state=running)` event + **suppress** 摘要 token / frontend：transient activity |
| 压缩完成 | “压缩中…”消失，答案开始流出，并在该 turn 上永久显示一行小字**“已摘要之前的对话 · 查看原文”** | backend：检测 `_summarization_event` → emit `compaction(state=done, offload_path)` / frontend：attach 到 message metadata → 渲染 inline marker |

**核心一句话：** deepagents 0.6.9 自动压缩不会把摘要留在 `messages` 中，只通过 stream metadata（`lc_source=summarization`）和 state（`_summarization_event`）暴露 → 在 **backend stream adapter 中检测/emit**，frontend 渲染该事件。（LangChain 官方 deepagents *context-engineering* 文档建议检测 `metadata.lc_source=="summarization"`。）

---

## 1. 前置事实（均已实测/源码确认）

### 1.1 deepagents 0.6.9 自动压缩的实际行为
- `create_deep_agent` 会将 `create_summarization_middleware(model, backend)` 注入默认 stack（`graph.py:779`，子 Agent `:626/:702`）。trigger 由 `compute_summarization_defaults(model)` 基于 `model.profile["max_input_tokens"]` 计算 → **以 Phase 0 填充的 `context_window` 为准使用 `("fraction", 0.85)`**。
- **摘要不会进入 `messages` state。** `_DeepAgentsSummarizationMiddleware.wrap_model_call`（summarization.py:1003~）正如 docstring 所写：*“does NOT modify the LangGraph state. Instead, it tracks summarization events in middleware state(`_summarization_event`)”*。摘要只会**临时应用到模型请求**，persisted `messages` 保留原文。
- 因此，“在 messages 中查找摘要消息”的方式（旧 `before_model` 假设）在 0.6.9 中**不起作用。** 这正是 Phase 1 重新设计的原因。

### 1.2 压缩是“回答前步骤”，因此与不可输入区间重叠
顺序（一个 turn 内）：
```
[用户发送] → 摘要旧对话（LLM 1 次，压缩中）→ 生成实际回答 → [完成]
```
这个 turn 执行期间 composer 已处于“回复中（Stop）”状态 → **压缩中无法额外输入**（与 Claude Code 相同）。缺少的只是告诉用户“为什么在等待”的显示。

### 1.3 在 v3（生产）stream 中暴露压缩信号的形式 — **实测**
生产聊天默认是 `runtimeMode==='langgraph_v3'`（`frontend/src/lib/chat/runtime-mode.ts`），backend 使用 `astream_events(version="v3")`（`langgraph_streaming.py:_open_v3_stream` L72-83）。通过较小的 `context_window` 强制压缩并抓取 v3 event 后，可看到：

```
v3 methods: {'values': 2, 'messages': 10}
携带 lc_source=summarization：method=='messages' 的 (payload, metadata) tuple 中 metadata.lc_source
携带 _summarization_event：method=='values' 的 data 中 {cutoff_index, summary_message, file_path}
```

也就是说，在 v3 event 中：
- **摘要生成 token** = `method=="messages"` event 的 `metadata.lc_source == "summarization"`。
- **压缩确认信号** = `method=="values"` event 的 `data["_summarization_event"]`（key：`cutoff_index`、`summary_message`、`file_path`）。

timeline：
```
messages(lc_source)×N   ← 压缩中（摘要 token）        → state=running
values(_summarization_event, cutoff_index>0)         → state=done (+offload_path)
messages(lc_source 无)×M ← 实际答案
```

> ⚠️ **当前泄漏风险：** `adapt_v3_protocol_event`（langgraph_protocol_adapter.py:37）→ `_normalize_protocol_data`（:140）→ `_message_payload_with_metadata`（:151-163）会把 `metadata.lc_source` **原样合并进 message payload 并发送到 frontend。** 如果摘要 token（`messages`）原样流出，assistant-ui LangGraph SDK 可能会**把摘要文本渲染为答案/ghost message**。LangChain 官方文档也会**过滤**这些 token → 本工作中将其 suppress。

### 1.4 offload 文件路径
Moldy backend 使用 `FilesystemBackend(root_dir=_DATA_DIR, virtual_mode=True)`（runtime_component_builder.py:603）— **不是 CompositeBackend** → `artifacts_root="/"` → offload 路径可确定为 **`/conversation_history/{thread_id}.md`**。不过应尽量直接使用 `_summarization_event["file_path"]`，只有缺失时才按此规则 derive（保证未来 backend 替换安全）。

### 1.5 两条 streaming 路径（production = v3）
| 路径 | 使用位置 | backend | frontend 转换 |
|------|--------|--------|-------------|
| **v3（生产）** | `langgraph_v3` 默认 | `langgraph_streaming.py`（`astream_events v3`）+ `adapt_v3_protocol_event` | LangGraph runtime（`use-moldy-langgraph-stream.ts`） |
| legacy | `NEXT_PUBLIC_CHAT_RUNTIME=legacy` | `streaming.py`(`stream_mode="messages"`) | `use-chat-runtime.ts` + `convert-message.ts` |

→ **v3 必做，legacy 可选（建议）。** 两者都使用相同信号（`lc_source` / `_summarization_event`），因此可在两条路径中放置相同逻辑。

---

## 2. 设计

### 2.1 事件契约（backend → frontend）
通过 frontend `custom` channel 发送单一 side-channel event。method = `custom:moldy.compaction`（或 `custom`+`name="moldy.compaction"`）。data payload：

```jsonc
// 压缩开始
{ "state": "running" }
// 压缩完成
{ "state": "done", "offload_path": "/conversation_history/{thread_id}.md", "cutoff_index": 12 }
```

- **每个 run 最多 1 对（running→done）**，进行 dedup。（一个 turn 通常压缩 1 次。multi-step run 中若达到 2 次以上，也可以 emit 每一对，但 v1 简化为**每个 run 1 次** + 留 `log`。）
- event 通过现有 emit 路径（`stored_custom_protocol_event`）发出，可自动获得 **persist + broker + replay**（见 3.1）。

### 2.2 backend 责任
1. **检测**：在 v3 loop 中检查 adapted event
   - `method=="messages"` & `data.metadata.lc_source=="summarization"` → 摘要 token。
   - `method=="values"` & `data._summarization_event.cutoff_index>0` → 压缩确认。
2. **suppress**：摘要 token（`messages` w/ lc_source）event **不 yield 给 frontend**（阻止泄漏）。
3. **emit**：在第一个摘要 token 时 emit 1 次 `compaction(running)`，在 `_summarization_event` 到达时 emit 1 次 `compaction(done, offload_path)`。

### 2.3 frontend 责任（v3 LangGraph runtime）
1. **transient“压缩中…”**：`compaction(running)` → `done` 之间显示。向现有 activity 基础设施（`RunActivity`）新增 `kind:'compaction'` → loading indicator 渲染。
2. **永久“已摘要之前的对话 · 查看原文”**：`compaction(done)` → attach 到对应 assistant turn message metadata → 在 `AssistantMessageParts` 附近渲染 inline marker。（persisted event 会在 reload 时 replay → 再次 attach → 永久存在。）

---

## 3. 实现 — backend

### 3.1 event helper（确认契约 + emit 手段）
- `RAW_PROTOCOL_METHODS`（langgraph_protocol_adapter.py:18-）中已包含 `"custom"`。
- side-channel emit 工具：`app/agent_runtime/protocol_events.py:stored_custom_protocol_event(name, data, ...)`（protocol_side_effects.py 已在使用）。用它创建 `name="moldy.compaction"` event。
- **event_names.py**：backend 常量并非必需，但为可读性建议新增：
  ```python
  # event_names.py
  COMPACTION: Final = "moldy.compaction"   # custom side-channel name
  ```

### 3.2 v3 路径检测/suppress/emit — `langgraph_streaming.py`
目标：`stream_agent_response_langgraph` 的 v3 loop（当前 L275-309 `else: async for raw_event in stream:`）。

检测 helper（添加在同一 module 或 `langgraph_protocol_adapter.py`）：
```python
def _compaction_signal(event: StoredProtocolEvent) -> str | None:
    """从 adapted protocol event 中分类压缩信号。
    returns: "summary_token" | "committed" | None
    """
    data = event.get("data")
    method = event.get("method")
    if method == "messages" and isinstance(data, Mapping):
        md = data.get("metadata")
        if isinstance(md, Mapping) and md.get("lc_source") == "summarization":
            return "summary_token"
    if method == "values" and isinstance(data, Mapping):
        ev = data.get("_summarization_event")
        if isinstance(ev, Mapping) and isinstance(ev.get("cutoff_index"), int) and ev["cutoff_index"] > 0:
            return "committed"
    return None

def _compaction_offload_path(event: StoredProtocolEvent, thread_id: str) -> str | None:
    data = event.get("data")
    if isinstance(data, Mapping):
        ev = data.get("_summarization_event")
        if isinstance(ev, Mapping) and isinstance(ev.get("file_path"), str):
            return ev["file_path"]
    return f"/conversation_history/{thread_id}.md" if thread_id else None
```

修改 loop（snippet，位于现有 `yield await emit(event)` 前后）：
```python
# 进入 loop 前的状态：
_compaction_running_emitted = False
_compaction_done_emitted = False

# ... async for raw_event in stream:
event = adapt_v3_protocol_event(raw_event, run_id=msg_id, thread_id=thread_id)
if _is_empty_input_requested_event(event):
    deferred_empty_input_requested = event
    continue

signal = _compaction_signal(event)
if signal == "summary_token":
    # 1) 为防止污染 answer，不将摘要 token 发送到 frontend（阻止泄漏）。
    # 2) 在第一个 token 时 emit 1 次“压缩中”。
    if not _compaction_running_emitted:
        _compaction_running_emitted = True
        side_effect_seq += 1
        yield await emit(stored_custom_protocol_event(
            name=event_names.COMPACTION, run_id=msg_id, thread_id=thread_id,
            seq=side_effect_seq, data={"state": "running"},
        ))
    continue  # ← suppress：摘要 token 本身不 yield
if signal == "committed" and not _compaction_done_emitted:
    _compaction_done_emitted = True
    side_effect_seq += 1
    yield await emit(stored_custom_protocol_event(
        name=event_names.COMPACTION, run_id=msg_id, thread_id=thread_id,
        seq=side_effect_seq, data={
            "state": "done",
            "offload_path": _compaction_offload_path(event, thread_id),
            "cutoff_index": event["data"]["_summarization_event"]["cutoff_index"],
        },
    ))
    # values event 本身仍按现有逻辑继续流出（维持 state 同步）→ 保留下方 yield

yield await emit(event)
# （之后的 usage/side-effect 收集逻辑保持不变）
```
> ⚠️ `stored_custom_protocol_event` 的准确 signature（seq/event_id/namespace 参数）请在 `protocol_events.py:75-148` 中确认后匹配。完全沿用 side-effect events 通过增加 `side_effect_seq` 使用的模式（`collect_protocol_side_effect_events`）。

> ⚠️ **fallback 路径（L241-274，`_open_stream_mode_fallback`，测试 fake 用）** 也需要加入相同处理以保持一致。那里 `adapt_stream_mode_chunk` 会 adapt (mode,data) tuple，因此可复用同一个 `_compaction_signal`。

### 3.3 legacy 路径（可选，建议）— `streaming.py`
目标：`stream_agent_response` 的 `async for chunk in agent.astream(stream_mode="messages")`（L394-）。在 `msg, metadata = chunk` 之后、`builder:internal` skip（L402）之后：
```python
if (metadata or {}).get("lc_source") == "summarization":
    if not _compaction_emitted:
        _compaction_emitted = True
        yield emit(event_names.COMPACTION, {"state": "running"})
    continue  # suppress 摘要 token
```
legacy 不会接收 `_summarization_event`（updates/values），因此 `done` 可在**第一个非摘要 token 切换**时或 stream 结束时 emit 1 次（`{"state":"done","offload_path": f"/conversation_history/{thread_id}.md"}`）。thread_id 为 `config["configurable"]["thread_id"]`。
> legacy 不是生产路径 → v1 即使只做 **running**（阻止泄漏 + “压缩中”）也可接受。done marker 优先支持 v3。

### 3.4 redaction / persist 确认
- 确认 `redact_private_reasoning`（adapter）与 `protocol_redaction.py` 不会破坏新 custom event data（`offload_path` 等）。`offload_path` 不属于敏感信息（路径），也不是 secret masking 对象。
- custom event 会通过现有 emit 路径 persist（`message_events`），因此会在 **reload replay** 中出现 → 成为 frontend 永久 marker 的依据。

---

## 4. 实现 — frontend（v3 LangGraph runtime）

路径前提：当 `chat-runtime-section.tsx` 中 `runtimeMode==='langgraph_v3'` 时使用 `useMoldyLangGraphStream`（`use-moldy-langgraph-stream.ts`）。custom event 会进入 `['custom']` channel（`activity-protocol.ts` 的 `ActivityProtocolMethod` 已包含 `custom:${string}`）。

### 4.1 compaction event 解析 hook — 新增 `langgraph-runtime/compaction-events.ts`
模式来源：`memory-events.ts`（useLangGraphMemoryEffects，custom event 解析/dedup）+ `usage-events.ts`（message attach）。新增 hook：
- 订阅 `['custom']` channel，过滤 `customName(event)==='moldy.compaction'`。
- 解析 `state==='running'|'done'`（Zod 或 type guard；`isCompactionPayload`）。
- 返回：
  - `compactionStatus: 'idle' | 'running'`（transient，从收到 running 到收到 done）
  - `compactionByRunId: Map<runId, {offloadPath?}>`（done 时记录）→ 用于 message attach。
- dedup：`event_id`（`memory-events.ts:84-89` 模式）。

### 4.2 transient“压缩中…”— activity 或 status flag
两种方式中选 1（推荐 A）：
- **A. 注入 activity（推荐）**：在 `activity-model.ts` 的 `RunActivityKind` 中新增 `'compaction'`。compaction-events hook 在 `running` 期间将 `{kind:'compaction', status:'running', label}` activity 合并进 `activities` → `StreamingMessageLoadingIndicator`（assistant-message-loading.tsx:76-114）通过 `RunActivityStrip` 渲染（复用现有基础设施）。`done` 时移除（或 complete 后消失）。
- **B. status flag**：hook 暴露 `compactionStatus` → loading indicator 不再显示 `WittyLoadingMessage`，改为 `t('chat.compaction.running')`（“压缩中…”）。
- A 复用现有 activity 渲染/排序基础设施，更稳健。只需在 `run-activity-strip.tsx`/`activity-model.ts` 中新增 kind 标签/图标。

### 4.3 永久 marker“已摘要之前的对话 · 查看原文”
- compaction-events hook 的 `compactionByRunId` → attach 到对应 assistant message metadata：完全仿照 `usage-events.ts` 的 `withUsage`/`attachUsageToMessages`（向 message array 合并 metadata.custom）模式，编写 `attachCompactionToMessages(messages, compactionByRunId)` → `metadata.custom.compaction = {offloadPath}`。
  - run→message 映射参考/复用 usage-events 已使用的 `runMessageIds` 映射（usage-events.ts:393-400）。
- 新组件 `components/chat/compaction-summary.tsx`（重写 Phase 1 尝试版本）：
  ```tsx
  export function CompactionSummary({ offloadPath }: { offloadPath?: string }) {
    const t = useTranslations('chat.compaction')
    // icon（lucide Minimize2Icon）+ t('summary') +（有 offloadPath 时提供 clipboard copy“查看原文”按钮）
    // design-system：text-xs text-muted-foreground / text-primary-strong，rounded-md 以内，仅使用 semantic color
  }
  ```
- 渲染位置：`assistant-thread.tsx` 的 `AssistantMessageParts`（L236 附近）之后，或 `AssistantArtifactCards`（L248-303）附近。通过 `useAuiState((s)=> (s.message?.metadata as {custom?:{compaction?:{offloadPath?:string}}})?.custom?.compaction)` 读取，存在时渲染 `<CompactionSummary/>`。
  - ⚠️ **selector reference-stable**：空默认值必须使用 module 常量（`const EMPTY = {}`）— 如果每次 render 返回新对象，会无限 rerender（过去 Phase 2a 曾遇到 `useAuiState` bug）。

### 4.4 i18n
在 `frontend/messages/ko.json` + `en.json` 的 `chat` namespace 中：
```jsonc
"chat": {
  "compaction": {
    "running": "正在压缩之前的对话…",   // en: "Compacting earlier messages…"
    "summary": "已摘要之前的对话以整理 context",  // en: "Older messages were summarized to free up context"
    "viewOriginal": "查看原文",  // en: "View original"
    "copied": "路径已复制"        // en: "Path copied"
  }
}
```
如果使用 activity 标签，也一起添加 `chat.activity.compaction`。完成后运行 `pnpm lint:i18n`。

---

## 5. 修改文件摘要

**backend**
- `app/agent_runtime/event_names.py` — `COMPACTION` 常量。
- `app/agent_runtime/langgraph_streaming.py` — 在 v3 loop + fallback loop 中检测/suppress/emit。
- `app/agent_runtime/langgraph_protocol_adapter.py` — `_compaction_signal`/`_compaction_offload_path` helper（或放在 streaming module 中）。
- （可选）`app/agent_runtime/streaming.py` — legacy 路径做相同处理。
- `app/agent_runtime/protocol_events.py` — 确认 `stored_custom_protocol_event` signature（预计无需修改）。

**前端**
- `src/lib/chat/langgraph-runtime/compaction-events.ts`（新增）— custom event 解析/dedup/attach。
- `src/lib/chat/langgraph-runtime/activity-model.ts` — 在 `RunActivityKind` 中新增 `'compaction'`（方式 A）。
- `src/lib/chat/langgraph-runtime/use-moldy-langgraph-stream.ts` — hook wiring（在返回值中合并 compaction，并 attach 到 message）。
- `src/components/chat/assistant-message-loading.tsx` — 渲染 transient“压缩中”（activity 或 flag）。
- `src/components/chat/compaction-summary.tsx`（新增）— 永久 marker。
- `src/components/chat/assistant-thread.tsx` — 在 `AssistantMessageParts` 附近添加 marker 渲染分支。
- `frontend/messages/ko.json` + `en.json` — i18n.

---

## 6. 风险 & 注意事项（★ hot path）

| # | 风险 | 应对 |
|---|--------|------|
| R1 ★ | **摘要 token suppress 过度，导致普通答案 token 也被漏掉** | suppress 条件必须只做 `lc_source=="summarization"` **精确匹配**。回归测试：发生压缩的 run 中断言 answer content 无损（Level 2）。 |
| R2 ★ | suppress 漏掉 → 摘要文本**泄漏**到答案/ghost message | v3 `messages`+lc_source、legacy metadata.lc_source 两处都阻断。加入泄漏断言测试。 |
| R3 | compaction event **重复/顺序**（多次 running、done 先到） | 每个 run 用 `_running/_done` flag 保证 1 次。multi-step 时限制为每个 run 1 对 + `log`。 |
| R4 | reload 后 marker **消失/重复** | 确认 event 会 persist 到 `message_events`→replay。frontend 按 event_id dedup。 |
| R5 | `useAuiState` selector 无限 rerender | 默认值使用 module 常量，保持 reference-stable。 |
| R6 | usage 漏记（因跳过摘要 token 而未统计摘要 LLM 成本） | v1 可接受（内部 overhead）。如需要，后续通过独立 usage channel 分开统计。用 `log` 提供可见性。 |
| R7 | trigger（schedule）模式 | 如果 trigger executor 也走相同 stream 路径则自动适用。与 HiTL 无关。通过 capture 确认。 |
| R8 | feature flag | 用 `MOLDY_COMPACTION_MARKER_ENABLED`（env，默认 on）或 settings 包裹，出现问题时可立即 off（建议）。 |

**回滚**：无 DB migration → 出问题时可通过 PR revert 完全恢复。与 Phase 0 **分 PR**（Phase 0 已提交）。

---

## 7. 测试策略（与 §Phase 0 相同原理 — 不用填满 85%，直接缩小 `context_window`）

### Level 1 — frontend 单元（vitest）
- `compaction-events.ts`：mock custom event（`{method:'custom:moldy.compaction', params:{data:{state:'running'}}}` / `done`）→ 断言 status 转移 + `compactionByRunId` attach。（`memory-tool-ui.test.ts` 风格）
- `attachCompactionToMessages`：确认 message array 中合并了 `metadata.custom.compaction`。
- `compaction-summary.tsx`：渲染“已摘要”+“查看原文”（有/无 offloadPath），且不是 user 气泡。

### Level 2 — backend 集成（pytest，非浏览器）★最重要
用 `context_window=1500`（或 50）模型构建 deep agent → 直接运行 `astream_events(version="v3")`：
- 压缩发生时是否各 yield **1 次 `compaction(running)` + 1 次 `compaction(done, offload_path)`**。
- **摘要 token（messages+lc_source）是否不被 yield（suppress）** + 最终 answer content 无损。
- 最理想是直接调用 `stream_agent_response_langgraph` 的 integration test（参考现有 `tests/agent_runtime/test_langgraph_*`）。fake model 使用 `GenericFakeChatModel` + `bind_tools`→self，`profile={"max_input_tokens":50}`。

> 复现关键：fake model 多 turn 累积 token > `0.85×window` → 触发压缩。（验证 snippet §9）

### Level 3 — E2E（可选，确定性）
- **scripted `E2E_COMPACTION` marker**（`e2e_scripted_model.py`）：输入包含 marker 时确定性地发出 `compaction` event 序列 → 断言/capture frontend marker 渲染。与 trigger 逻辑分离，减少 flaky。（现有 `E2E_TOOL_GROUP` 模式）
- 或使用 tiny-context 真实模型 2~3 turn → capture“压缩中…” + 永久 marker。

### 验证矩阵
| 对象 | 方法 | 85%? |
|------|------|------|
| event emit(running/done) + suppress | Level 2(window=50, astream_events v3) | ❌ |
| answer 无损（不泄漏） | Level 2 断言 | ❌ |
| parsing/attach/render | Level 1 单元 | ❌ |
| marker UI 全链路 | scripted E2E or tiny-context | ❌ |

---

## 8. 完成标准（done-when）
- [ ] 发生压缩的 run 中，backend 各 emit **1 次** `compaction(running)`→`compaction(done,offload_path)`，摘要 token 不发送到 frontend（泄漏 0）。
- [ ] 普通（无压缩）turn 中完全没有 compaction event，答案行为无回归。
- [ ] v3 生产聊天中，压缩时显示**“压缩中…”** → 消失后永久显示**“已摘要之前的对话 · 查看原文”**，reload 后仍保留。
- [ ] tsc 0 / vitest / backend ruff+pytest / lint（i18n·design-system）green。
- [ ] 真实 server（或 scripted）capture：“压缩中…” + 永久 marker +（压缩后 gauge 下降）。
- [ ] 可通过 feature flag off。与 Phase 0 分 PR。

---

## 9. 附录 — 压缩复现/验证 snippet（实现过程中直接使用）

通过较小 window 强制自动压缩并确认 v3 event：
```python
import itertools, asyncio, inspect, warnings
warnings.filterwarnings("ignore")
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from deepagents import create_deep_agent

class FakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs): return self

fake = FakeModel(messages=itertools.cycle([AIMessage(content="摘要/回答")]))
fake.profile = {"max_input_tokens": 50}   # 缩小 → 立即压缩
agent = create_deep_agent(model=fake, tools=[], system_prompt="sys", checkpointer=InMemorySaver())
cfg = {"configurable": {"thread_id": "t"}}
agent.invoke({"messages": [HumanMessage(content="第一个问题 " * 30)]}, cfg)  # 累积 history

async def go():
    s = agent.astream_events({"messages": [HumanMessage(content="第二个 " * 30)]}, cfg, version="v3")
    if inspect.iscoroutine(s): s = await s
    async for ev in s:
        params = (ev or {}).get("params") or {}
        data = params.get("data")
        if ev.get("method") == "messages" and isinstance(data, (list, tuple)) and len(data) == 2:
            md = data[1] if isinstance(data[1], dict) else {}
            if md.get("lc_source") == "summarization":
                print("摘要 token（suppress 对象）")
        if ev.get("method") == "values" and isinstance(data, dict) and "_summarization_event" in data:
            print("压缩确认：", data["_summarization_event"]["file_path"])
asyncio.run(go())
```
预期输出：“摘要 token…”多次 → “压缩确认：/conversation_history/t.md”。

---

## 10. 工作顺序
```
1) backend v3 检测/suppress/emit（langgraph_streaming + adapter helper）+ Level 2 integration test（泄漏 0 + emit 1 对）
2) backend legacy 同样处理（可选）+ event_names 常量
3) frontend compaction-events hook + Level 1 unit
4) transient“压缩中”（activity kind）+ 永久 marker（compaction-summary + assistant-thread 分支）+ i18n
5) （可选）scripted E2E_COMPACTION + capture
6) feature flag、/code-review、PR（与 Phase 0 分开）
```
