# 评估：引入 assistant-ui 9 类内置功能的可行性

> 编写于 2026-06-26 · 分支 `worktree-feature+generic-tool-call-grouping`
> 动机：聊天 UI 很多是自行实现的，如果使用 assistant-ui 默认能力，只把视觉改成我们的设计，稳定性会不会更好？— 对 9 类功能进行全面评估。
> 方法：像 tool-group 一样，对照我们的聊天代码 + ref 仓库（0.14.24）docs/registry 源码。3 个 subagent 并行分析后汇总。

---

## 0. 一句话结论

**9 类中，没有任何一类在采用“官方组件（registry `.tsx`）”后能获得净收益。** 原因是两道结构性门槛：

1. **数据模型不匹配** — 我们的聊天不会 emit `reasoning`/`source`/`file` 这类**官方 message-part type**。（reasoning=`data` part+activity，sources=嵌入 tool result，file=M59 artifact 系统。）连送进官方 primitive 的输入都没有。
2. **设计 token 成本** — registry `.tsx` 全部使用 raw tailwind（`rounded-lg`/`shadow-*`/hex/arbitrary spacing），违反我们的 `pnpm lint:design-system`。不能直接复制，必须改写成 moldy semantic token。（这与 Phase-2b 没采用官方 `tool-group.tsx`、而复用 `CollapsiblePill` 的原因相同。）

不过，**有选择地采用仍有价值**：① 使用**官方 runtime primitive（hook/slot）**，视觉使用我们的 token；② 引入**我们完全没有的功能**。下表是核心。

---

## 1. 9 类功能判断摘要

| # | 功能 | 我们现状 | 判断 | 优先级 | 0.14.18 可用 |
|---|------|----------|------|:---:|:---:|
| 1 | **part-grouping** | Phase-2b 已采用官方 `GroupedParts` | **保持现状（正确）** | 低 | O |
| 2 | **tool-group** | 复用 `CollapsiblePill`（有意） | **保留 + 增强 `useScrollLock`** | 中 | O |
| 3 | **tool-fallback** | 自有 `generic-tool-ui` | **保留 + 增强 argsText/error** | 低 | 部分 O |
| 4 | **reasoning** | `data` part + “thinking” activity | **保留**（模型不匹配） | 低 | 无输入 |
| 5 | **sources** | 解析 + 汇总 tool result | **保留**（模型不匹配） | 低 | 无输入 |
| 6 | **file** | M59 `conversation_artifacts` | **保留**（模型不匹配） | 低 | 无输入 |
| 7 | **attachment** | 仅 composer chip 使用 official，消息中不显示 | **部分引入（新增）** | **中** | O |
| 8 | **context-display** | token/费用**已经**由 `TokenUsagePopover` 显示，仅缺 context window % gauge | **部分新增**（仅 gauge） | 低 | registry-only |
| 9 | **directive-text** | 无（未使用 slash/mention） | **跳过** | 低 | unstable |
| 10 | **message-timing** (TTFT·tok/s) | 无 | **建议新增** | 中 | O（`useMessageTiming` 可用） |

---

## 2. 只保留“有实际收益”的 action（推荐顺序）

### A. attachment — 在消息正文显示附件（优先级：中）⭐ 实际收益最大
- **问题**：我们的 composer staging chip 只用 official（`AttachmentPrimitive`）实现，但**从未渲染 `MessagePrimitive.Attachments`/`UserMessageAttachments`**（grep 0 条）。即使转换器（`convert-message.ts`）给历史 user message 附上附件，**transcript 中也看不到** → 用户无法从对话记录确认“我发了什么”。
- **此外官方有、我们没有的功能**：图像**缩略图 tile** + 点击后**放大 dialog**（registry `attachment.tsx` 的 `AttachmentPreviewDialog`）。我们的 chip 只有图标。
- **可行性**：`MessagePrimitive.Attachments` 在 0.14.18 可用 → 无需升级。registry tsx 仅作参考，视觉使用 moldy token。
- **前置条件**：确认 backend 附件 hydration 契约 — CLAUDE.md 明确写了“附件 message_id=null，因此不会 echo 到消息响应”。只加 UI 可能仍是空渲染，所以应**先确认 GET /messages 是否 hydrate 附件**。

### B. tool-group — 增强 `useScrollLock`（优先级：中）⭐ 最低成本·高性价比
- **问题**：长聊天中折叠 group 时滚动位置可能跳动。官方 `tool-group.tsx` 用 `useScrollLock` 防止此问题。
- **核心**：`useScrollLock` 是 **0.14.18 runtime export** → 无需 vendoring，只把 hook 接到我们的 `CollapsiblePill`，一行即可增强。
- （collapse 动画·child stagger 属于 polish 项 → 优先级低。）

### C. tool-fallback — streaming argsText + error reason（优先级：低）
- **缺口**：我们只对完整 `args` 对象做 `JSON.stringify` → tool call 很长时，streaming 期间 panel 为空。官方实时显示 part 的 `argsText`（部分 JSON）。同时单独显示 `incomplete.reason`（error/cancelled 原因）。两者都可在 **0.14.18 增强**。
- duration 显示（`useToolCallElapsed`）是 0.14.24 新增，暂缓。
- **approval 无需增强** — 我们的 `ApprovalCard`（修改后批准·倒计时·redaction·多 action HiTL）优于官方 `ToolFallbackApproval`。

### D. message-timing (TTFT·tok/s·总时长) — 在 `TokenUsagePopover` 增加一行（优先级：中）⭐ 实际收益大
- **官方提供**：`useMessageTiming()`（0.14.18 可用）— 读取 `message.metadata.timing`。`message-timing.tsx` 显示**首 token（TTFT）·总 streaming 时间·tok/s·chunks**。
- **为什么干净**：与 reasoning/sources/file 不同，它**不是 part type，而只是 metadata slot**，因此没有数据模型冲突。我们已有 `convertMessage` 将 usage 写入 `metadata.custom`，`TokenUsagePopover` 读取该字段，所以把 **timing 合并到 usage breakdown** 后，token/费用所走的所有路径（v3/legacy + persistence）都可复用。
- **测量点**：backend streaming 两条路径（`streaming.py`·`langgraph_streaming.py`）。**总时长 runner 已用 `time.monotonic()` 测量**（`agent_stream_runner.py`）→ 只需暴露。TTFT 在第一个 `CONTENT_DELTA` yield 处加一行。tok/s = `completion_tokens` ÷ 生成时间。
- **UI**：为避免信息过载，在 popover 底部加**极简一行**（`45 tok/s · 5.2s · 首token 0.42s`）。平时页面仍为 `ⓘ 1,234`。
- 优先级中。与 attachment 同一档。（实现进行中。）

### E. context-display（context window % gauge）— 可选（优先级：低）
- **更正**：token/费用已经通过 `TokenUsagePopover`（每消息 4 类 token + 费用）+ `TokenBar`（session 累积）**显示中**。context-display 唯一额外提供的是**“相对于 context window 上限的 % gauge”**（上限警告）。
- 连这个 gauge 所需数据（`model.context_window` + 累积 token）也已经有。官方组件依赖 `@assistant-ui/react-ai-sdk`（未安装），不合适 → 如需要，可在 `TokenBar`/`TokenUsagePopover` **自行增加 % gauge**。属于 nice-to-have。

---

## 3. “保留”判断的依据（4·5·6 = reasoning/sources/file）

这三类的根本原因相同：**我们没有 emit 官方 message-part type** — 要采用它们，需先新增 backend part-type + 重写转换层，**超出请求范围**。

- **reasoning**：backend `moldy.reasoning` custom event → frontend 被**一分为二**：`data` part（`ReasoningDataUI`）+ streaming “thinking” activity。官方以 `reasoning` part 为前提。我们的 `CollapsiblePill` 已有折叠 UX → 净收益有限。
- **sources**：来源**嵌在 tool result JSON 内**（backend 不创建 native `source` part）。没有可送给官方 `SourceMessagePartComponent` 的输入。我们的 `search-results.ts`+`ToolGroupContainer` 汇总（domain badge+“来源 N 个”）已满足 LITE 要求（61b2367d）。
- **file**：聊天文件 = **M59 `conversation_artifacts`**（URL/meta/version/右侧 rail preview）或 deepagents 虚拟 FS state。官方 file 以 inline base64 part 为前提 → 结构上无关。若换 primitive，反而会失去 rail toggle·version·查看记录等，造成**功能倒退**。

> 最多可借鉴的不是“采用 primitive”，而是**参考 util/visual**：如有需要，用我们的 token 重写 `file.tsx` 的 `getMimeTypeIcon`/`formatFileSize`、`sources.tsx` 的 favicon+首字母 fallback 模式。

---

## 4. ⚠️ 分析中发现的事实更正（memory/plan-doc 错误）

在验证 subagent 安装的 `0.14.18`（core `0.2.14`）实际 `.d.ts` 时，更正了两点：

1. **`makeAssistantToolUI` 并非从 0.14.24 才 deprecated，而是在 `0.14.18` 就已经 `@deprecated`。**（deprecation message: "Put render/renderText on the matching toolkit entry, or use MessagePrimitive.Parts inline tool render overrides"。）也就是说，我们 27 个 tool UI（`tool-ui-registry.ts`）**已经建立在 deprecated API 上** → 迁移到 toolkit `render` 的紧迫性高于之前认知（仍属于单独的 0.14.24 track）。
2. **`respondToApproval`（服务器 approval gate）不是 0.14.19+ 才有，而是在 `0.14.18` 就已存在**（`ToolCallMessagePartProps` 中 `addResult`/`resume`/`respondToApproval` 全都有）。plan-doc §5.3 中“0.14.19+”的记载错误。（不过我们使用基于 deepagents interrupt 的 `useHiTL`+LangGraph resume 是合理的，无需替换。）
3. **更正 context-display 初步分析**：初始分析称“没有 token/费用显示功能（只有 TokenBar）”，但**assistant message footer 的 `TokenUsagePopover` 已经显示 4 类 token + 费用**（subagent 遗漏了这一点）。因此 context-display 不是“新功能”，而是“token/费用已有，只缺 context window % gauge”的状态。（已反映到 §2-E。）
4. **`useMessageTiming` 不会自动测量**：它只**读取** `message.metadata.timing`（`hooks/useMessageTiming.js`）。测量值（TTFT/total/tok-s）需要我们自行填充 → 参见 §2-D。

---

## 5. 贯穿原则 + 下一步

**原则**：官方**runtime primitive（hook/slot）**有价值时采用，但 registry `.tsx` **视觉层用我们的 moldy token 重写**。（与 Phase-2b 选择 CollapsiblePill 保持一致。）数据模型（part type）不匹配是阻碍采用 reasoning/sources/file 的根本门槛；0.14.24 升级由于有 vitest 回归历史，属于**单独 track**（大多数增强在 0.14.18 即可完成）。

**建议下一步**（各自独立任务）：
- （中）**message-timing（TTFT·tok/s）** — 在 `TokenUsagePopover` 增加极简一行。把 timing 合并进 usage breakdown，顺便进入持久化路径。**← 当前实现进行中。**
- （中）**attachment 消息显示** — 确认 backend echo 契约 → 用 moldy token 实现 `MessagePrimitive.Attachments` + 图像放大 dialog。
- （中）**tool-group `useScrollLock`** — 一行增强，性价比最高。
- （低）tool-fallback streaming argsText / error reason。
- （低）context-display = 自行扩展 context window % gauge。
- （单独）**0.14.24 + toolkit migration track** — `makeAssistantToolUI`（已 deprecated）→ toolkit `render`。完成后 part-grouping 中排除 HiTL 的硬编码（`NON_GROUPABLE_TOOLS`）也可由官方 `"standalone-tool-call"` 自动分类替代，从结构上消除新增 HiTL tool 的回归。

**跳过**：directive-text（本身没有 slash/mention 功能，unstable API）、官方 file/sources/reasoning 采用（数据模型不匹配）。
