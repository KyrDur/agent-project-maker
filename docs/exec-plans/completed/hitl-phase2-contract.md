# HiTL Phase 2 — Wire Contract (Backend ↔ Frontend Single Source of Truth)

> **DRI**: 皮查伊 (M0)。本文档是 Jensen(M1, backend) + 扎克伯格(M2, frontend) 在同一个 PR 中双端同步实现的单一事实来源。wire 细节只在本文档一处决定 — 将 ADR-012 §3, §4, §7 的抽象契约具体化到行级。
>
> **上位契约**: `docs/design-docs/adr-012-hitl-middleware-migration.md` (尤其 §3, §4, §7, Phase 2)
> **状态**: APPROVED — 后续里程碑(M1·M2)的进入 gate
> **分支**: `feature/hitl-phase2-wire-format` (从 main `750d587` 分支)
> **保留 Phase 1 产物**: `backend/app/agent_runtime/middleware_registry.py`, `backend/app/agent_runtime/executor.py:_prepare_agent` signature, `backend/tests/test_hitl_middleware.py` 5 项 — Phase 2 中一律不修改。

---

## 1. 目的 — Transition Window 策略

Phase 2 是一个在**单个 PR 中让标准 wire 与 legacy wire 两条路径同时工作**的 dual-path transition window。Phase 3 中将移除 legacy 路径(自有 `{interrupt_id, value}` chunk + `response` 字段)。本 PR 的 done-when:

- 标准 client(M2 更新版) ↔ 标准 backend(M1 更新版) → 通过标准 wire 正常工作
- 标准 client ↔ legacy backend(理论上；实际 merge 后会同步更新) → 通过 legacy wire adapter 正常工作
- legacy client(全面部署前的 cache 等) ↔ 标准 backend → 通过 legacy chunk 正常工作
- 回归 0 — 现有 826 backend test + 现有 frontend test 全部 PASS

**规则**: dual-path 的**两边必须一起进入同一个 PR**。不定义只 merge 一边的场景 (测试会验证两边)。

---

## 2. Pydantic schema — `Decision` + `ResumeRequest`

**文件**: `backend/app/schemas/conversation.py`

### 2.1 `Decision`

与 LangChain 标准 `HITLResponse.decisions[i]` 结构 1:1 匹配。定义为自有 Pydantic 模型，在 router 层验证后序列化为 dict，并传给 `Command(resume={"decisions": [dict, ...]})` (LangChain middleware 接收 TypedDict)。

```python
from typing import Any, Literal
from pydantic import BaseModel, model_validator

class Decision(BaseModel):
    """针对单个 tool_call 的人工决策。

    与 LangChain `HumanInTheLoopMiddleware` 的 `HITLResponse.decisions[i]` 相同 shape:
    - approve: 无附加字段
    - edit: 必须有 edited_action={"name": str, "args": dict}
    - reject: message 可选 (没有时 middleware 生成默认消息)
    - respond: message 必填 (synthetic ToolMessage content)
    """
    type: Literal["approve", "edit", "reject", "respond"]
    edited_action: dict[str, Any] | None = None  # type=edit 时必填
    message: str | None = None                   # type=respond 时必填, type=reject 时可选

    @model_validator(mode="after")
    def _validate_payload_for_type(self) -> "Decision":
        if self.type == "edit" and self.edited_action is None:
            raise ValueError("Decision(type='edit') requires 'edited_action'")
        if self.type == "respond" and self.message is None:
            raise ValueError("Decision(type='respond') requires 'message'")
        return self
```

### 2.2 `ResumeRequest` (dual-shape)

```python
class ResumeRequest(BaseModel):
    """HiTL resume 请求。Phase 2 transition: 两种格式都接受。

    - decisions: 标准 (Phase 2 新增)。兼容 LangChain HITLResponse。
    - response: legacy (@deprecated, Phase 3 移除)。转换为单个 respond decision。

    如果一个请求同时包含两个字段，只采用标准(decisions)，丢弃 legacy。
    两者都为 None 时返回 422。
    """
    decisions: list[Decision] | None = None
    response: str | list[str] | dict[str, Any] | None = None  # @deprecated

    @model_validator(mode="after")
    def _at_least_one(self) -> "ResumeRequest":
        if self.decisions is None and self.response is None:
            raise ValueError("ResumeRequest requires either 'decisions' or 'response'")
        return self
```

### 2.3 验证规则 (明确决定)

| case | 结果 |
|---|---|
| `{"decisions": [...]}` | 进入标准路径。忽略 `response` (None)。 |
| `{"response": ...}` | 进入 legacy 路径。router 转换为单个 respond decision。 |
| `{"decisions": [...], "response": ...}` | **标准优先，忽略 legacy。** 不以 422 拒绝 (transition 宽容)。仅记录 logging。 |
| `{}` 或两者都为 None | **422** (`_at_least_one` validator reject)。 |
| `decisions: []` (空数组) | router 原样发送 `Command(resume={"decisions": []})` — middleware 发生 ValueError (decisions_len ≠ interrupt_count)。验证委托给 middleware 层。 |

### 2.4 legacy → 标准转换规则 (明确决定)

在 router 的 resume_message 中，当 `data.decisions is None and data.response is not None` 时:

```python
def _legacy_response_to_decisions(response: str | list[str] | dict) -> list[dict]:
    """将 legacy `response` 字段转换为单个 respond Decision。

    - str: 原样作为 message
    - list[str]: 用 ", ".join(...) 合并为单个字符串 (multi-select 响应)
    - dict: 用 json.dumps(..., ensure_ascii=False) 序列化
      (嵌套对象响应 — 自有 ask_user 的 historical edge case)
    """
    if isinstance(response, str):
        message = response
    elif isinstance(response, list):
        message = ", ".join(str(item) for item in response)
    else:  # dict
        import json
        message = json.dumps(response, ensure_ascii=False)
    return [{"type": "respond", "message": message}]
```

**依据**: legacy `response` 是自有 `ask_user` 的 free-text/single-select/multi-select 答案或 builder 的 dict 响应。标准 middleware 的 `respond` decision 在语义上相同 — 将 synthetic ToolMessage(success) 传递给模型。

---

## 3. Backend Resume payload (Command)

**文件**: `backend/app/routers/conversations.py:813-833` → `backend/app/agent_runtime/executor.py:resume_agent_stream`

标准 middleware 精确期望的 dict shape:

```python
from langgraph.types import Command

# 原样发送 router 中已完成转换的 decisions (list[dict])
resume_payload: dict = {"decisions": [
    # 每个 dict 与 LangChain Decision TypedDict 精确匹配
    {"type": "approve"},
    {"type": "edit", "edited_action": {"name": "send_email", "args": {...}}},
    {"type": "reject", "message": "..."},
    {"type": "respond", "message": "..."},
]}

# executor 或 streaming 入口之前:
async for chunk in agent.astream(Command(resume=resume_payload), config=config, ...):
    ...
```

**Decision dict 序列化规则**:
- 使用 `Decision.model_dump(exclude_none=True)` — `None` 字段在 LangChain TypedDict 中连 key 本身都不放入 (`NotRequired` 兼容)。
- `edited_action` 保持 dict 原样 (由 Pydantic 验证)。LangChain 要求 `{"name", "args"}` 两个 key 都存在。

**resume_agent_stream signature**:
- 当前: `resume_agent_stream(cfg, response, ...)` — `response` 为任意类型。
- Phase 2: 保留 signature (变量名也原样)。router 转换为 dict (`{"decisions": [...]}`) 后传入。executor 内部的 `Command(resume=response)` 调用保持不变。
- 语义变更: `response` 参数现在始终是 `dict[str, Any]` (准确说是 `{"decisions": list[dict]}`)。类型提示可以收窄为 `dict[str, Any]`，也可以保留 `Any` (Phase 3 再收窄)。

---

## 4. INTERRUPT SSE Event Payload — Dual Emit 规则

**文件**: `backend/app/agent_runtime/streaming.py:331-367`

### 4.1 标准 chunk (新增)

```typescript
{ event: 'interrupt', data: {
    interrupt_id: string,                       // ★ 标准 chunk 也一并携带 (安全网)
    action_requests: [
      { name: string, args: Record<string, unknown>, description?: string }
    ],
    review_configs: [
      { action_name: string, allowed_decisions: ('approve'|'edit'|'reject'|'respond')[] }
    ]
}}
```

**携带 `interrupt_id` 的决定 (明确)**: ADR-012 §4 的标准格式中没有明确规定。但作为 Phase 2 transition 安全网，**标准 chunk 也一起 emit `interrupt_id`** — 为了让 frontend 无缝维持 (a) 与 legacy chunk 的 dedup，(b) stale 验证(`lastInterruptIdRef`)。参见 progress.txt §"Gotchas (Phase 2)"。Phase 3 移除 legacy 时一并评估移除 (但需先用单独的 correlation 字段替代 frontend stale 验证)。

### 4.2 legacy chunk (保留)

```typescript
{ event: 'interrupt', data: {
    interrupt_id: string,
    value: { type?: string, question?: string, options?: string[], message?: string, ... }
}}
```

现有 `streaming.py:349-357` 代码原样保留。

### 4.3 dual emit 顺序 / 数量 (明确)

| 项目 | 决策 |
|---|---|
| **顺序** | **标准在前 → legacy 在后。** frontend 将已处理标准的 interrupt_id 记录到 set → 忽略相同 ID 的 legacy chunk。 |
| **数量** | 每个 task 的每个 interrupt **恰好两个 chunk** (标准 1 + legacy 1)。multi-action(多个 tool_call)由标准 middleware 打包为一个 `action_requests: [...]` 数组发布，因此**一个 interrupt = 一组 = 两个 chunk**。不会按 tool_call 数量增加 chunk。 |
| **共同 interrupt_id** | 两个 chunk 拥有**相同的 `interrupt_id`** 值。source: `str(intr.ns)` (与当前代码相同)。frontend 用该 ID 做 dedup。 |

### 4.4 标准 chunk payload source (明确)

从 `streaming.py` 的 `agent.aget_state(config)` 结果 `task.interrupts[*]` 中提取:

```python
for task in state.tasks:
    for intr in task.interrupts:
        intr_id = str(getattr(intr, "ns", ""))
        intr_value = intr.value if isinstance(intr.value, dict) else None

        # 标准 chunk: intr.value 为 LangChain HITLRequest TypedDict
        # 当为 ({"action_requests": [...], "review_configs": [...]}) 时原样使用。
        # 自有 ask_user.py 发出的 interrupt 不是这个 shape，因此不 emit 标准 chunk。
        if intr_value and "action_requests" in intr_value and "review_configs" in intr_value:
            yield emit(event_names.INTERRUPT, {
                "interrupt_id": intr_id,
                "action_requests": intr_value["action_requests"],
                "review_configs": intr_value["review_configs"],
            })

        # legacy chunk: 始终 emit (transition window)。
        # ask_user 自有 interrupt + 标准 middleware interrupt 两者都同样处理。
        yield emit(event_names.INTERRUPT, {
            "interrupt_id": intr_id,
            "value": intr_value if intr_value is not None else {"message": str(intr.value)},
        })
```

**重要**: 自有 `ask_user.py` (保留至 Phase 4)不会发布标准 wire 的 `action_requests/review_configs` shape，因此**不会 emit 标准 chunk**。此时 frontend 仅收到 legacy chunk → 通过现有 adapter(adapter to standard) 或现有 onInterrupt 路径处理。回归 0。

### 4.5 fallback 分支 (`was_interrupted=True` + `aget_state` 失败)

`streaming.py` 的 except block。由于 state 查询失败，缺少构造标准 shape 的信息，因此**只 emit legacy chunk**，`interrupt_id=""` (空字符串)。

```python
except Exception:
    logger.warning("aget_state failed (interrupt check)", exc_info=True)
    if was_interrupted:
        yield emit(event_names.INTERRUPT, {
            "interrupt_id": "",
            "value": {"message": "Interrupt detected but state unavailable"},
        })
```

frontend 因缺少 `action_requests` key 而采用 legacy 路径，并显示 1 次 fallback 消息 (参见第 5 节)。

---

## 5. Frontend 处理规则

**文件**: `frontend/src/lib/chat/use-chat-runtime.ts:case 'interrupt'`, `frontend/src/lib/types/index.ts`

### 5.1 InterruptPayload union (types)

```ts
// 标准 chunk
export interface ActionRequest {
  name: string
  args: Record<string, unknown>
  description?: string
}
export type DecisionType = 'approve' | 'edit' | 'reject' | 'respond'
export interface ReviewConfig {
  action_name: string
  allowed_decisions: DecisionType[]
}
export interface StandardInterruptPayload {
  interrupt_id: string
  action_requests: ActionRequest[]
  review_configs: ReviewConfig[]
}

// legacy chunk (现有，保留)
export interface LegacyInterruptPayload {
  interrupt_id: string
  value: Record<string, unknown>
}

export type InterruptPayload = StandardInterruptPayload | LegacyInterruptPayload

// Decision (用于发送 resume)
export interface Decision {
  type: DecisionType
  edited_action?: { name: string; args: Record<string, unknown> }
  message?: string
}

export interface ResumeDecisionsRequest {
  decisions: Decision[]
}
```

### 5.2 分支 + dedup (use-chat-runtime.ts)

```ts
// module/component scope ref
const handledStandardInterruptIdsRef = useRef<Set<string>>(new Set())

// case 'interrupt': 分支逻辑 (标准优先, legacy fallback)
case 'interrupt': {
  setIsRunning(false)
  const data = event.data as InterruptPayload
  const intrId = data.interrupt_id
  if (intrId) lastInterruptIdRef.current = intrId

  // 标准 chunk: 仅在存在 action_requests key + 非空时进行标准处理
  if (
    'action_requests' in data &&
    Array.isArray(data.action_requests) &&
    data.action_requests.length > 0
  ) {
    handledStandardInterruptIdsRef.current.add(intrId)
    onStandardInterrupt?.(data)
    break
  }

  // legacy chunk: 如果相同 interrupt_id 的标准已处理则忽略 (dedup)
  if (intrId && handledStandardInterruptIdsRef.current.has(intrId)) {
    break
  }

  // legacy 单独到达 (保证回归 0 的路径)
  onInterrupt?.(data as LegacyInterruptPayload)
  break
}
```

**明确规则**:
- 仅当**`action_requests` 非空时**处理标准 chunk。空数组标准 chunk(第 4.5 节 fallback)在标准处理中 skip → 当相同 ID 的 legacy chunk 到达时采用后者。
- `handledStandardInterruptIdsRef` 在**component lifecycle 期间累积**。进入新 conversation 时随 component remount 自然 reset(其他区域已有这种 pattern)。回归 guard: 与 streamGuard 分开用独立 ref 保存(streamGuard 按 stream 级 reset)。
- `lastInterruptIdRef.current = intrId` 可在两个 chunk 中都更新 — 因值相同所以幂等。resume 时保持原有 stale 验证路径。
- Phase 3 中同时移除 legacy chunk 处理 + handledStandardInterruptIdsRef。

### 5.3 multi-action 处理 (Phase 2 决定 — 明确)

当标准 `action_requests.length >= 2` 时:
- frontend 将数组渲染为**顺序卡片 + 批量确认按钮** UX (M2 扎克伯格负责)。详细 component 设计在 M2 story 中决定。
- 用户对 N 个卡片全部做出决定 → "全部确认" → 单次调用 `streamResumeDecisions(conversationId, decisions)`。backend 一次发送 `Command(resume={"decisions": [N个]})`。
- 长度为 1 时与现有单卡片 UX 等价。

---

## 6. stream-resume.ts 发送格式

**文件**: `frontend/src/lib/sse/stream-resume.ts`

### 6.1 新增函数 (标准)

```ts
export async function* streamResumeDecisions(
  conversationId: string,
  decisions: Decision[],
  signal?: AbortSignal,
  options?: StreamSSEPostOptions,
): AsyncGenerator<SSEEvent> {
  yield* streamSSEPost<SSEEventType>(
    `/api/conversations/${conversationId}/messages/resume`,
    { decisions },                              // 标准 body
    signal,
    'content_delta',
    options,
  ) as AsyncGenerator<SSEEvent>
}
```

### 6.2 现有函数 (作为 legacy adapter 保留)

```ts
// 保持现有 signature。发送 body { response }。
// 用于兼容自有 ask_user / 现有调用方(未修改路径)。
export async function* streamResume(
  conversationId: string,
  response: unknown,
  signal?: AbortSignal,
  options?: StreamSSEPostOptions,
): AsyncGenerator<SSEEvent> { /* ... 与现有相同 ... */ }
```

### 6.3 暴露 HiTLContext

```ts
export interface HiTLContextValue {
  /** 标准 (Phase 2 新增)。发送 decisions[] → /resume。 */
  onResumeDecisions: (decisions: Decision[], displayText?: string) => Promise<void>
  /** legacy (@deprecated, Phase 3 移除)。发送单个 respond/任意值。 */
  onResume: (response: unknown, displayText?: string) => Promise<void>
}
```

标准使用方(ApprovalCard 新处理路径)调用 `onResumeDecisions`。legacy 使用方(自有 UserInputUI)保持现有 `onResume` — 此时 backend router 执行 legacy → 标准转换。

---

## 7. `allowed_decisions` 默认值 (代码验证结果)

**source**: `backend/.venv/lib/python3.13/site-packages/langchain/agents/middleware/human_in_the_loop.py:215-220`

```python
for tool_name, tool_config in interrupt_on.items():
    if isinstance(tool_config, bool):
        if tool_config is True:
            resolved_configs[tool_name] = InterruptOnConfig(
                allowed_decisions=["approve", "edit", "reject", "respond"]
            )
    elif tool_config.get("allowed_decisions"):
        resolved_configs[tool_name] = tool_config
```

**明确决定**:
- `interrupt_on={"tool_name": True}` → `allowed_decisions = ["approve", "edit", "reject", "respond"]` (四种全部允许)。
- `interrupt_on={"tool_name": False}` → 忽略 entry 本身 (auto-approve)。
- `interrupt_on={"tool_name": {"allowed_decisions": [...]}}` → 保持显式值原样。

**Frontend 影响**: 设置为 `True` 的工具允许全部 4 个 action — `ApprovalCard` 也必须显示 `respond` 按钮 (目前只对 ask_user 工具显示)。该 UX 决定由 M2 扎克伯格负责 — 本 wire contract 原样暴露 `review_configs[i].allowed_decisions` 数组，因此 frontend 根据该数组动态渲染按钮即可。

---

## 8. 保留 Phase 1 产物 (禁止修改)

本 PR 对以下区域**一律不修改**:

| 文件 | 保留原因 |
|---|---|
| `backend/app/agent_runtime/middleware_registry.py` | 保留 Phase 1 注释(规避自动注入 + executor 显式实例化路径)。 |
| `backend/app/agent_runtime/executor.py:_prepare_agent` signature + trigger 阻断行为 (`include_ask_user=False` → `interrupt_on=None`) | Phase 1 的核心安全装置。Phase 2 只能修改 resume 路径(`resume_agent_stream`)，`_prepare_agent` 的 signature/行为均保留。 |
| `backend/tests/test_hitl_middleware.py` (5 项) | Phase 1 回归 guard。`test_hitl_middleware_instance_injected_when_interrupt_on_provided`, `test_hitl_middleware_not_injected_in_trigger_mode`, `test_hitl_middleware_per_tool_policy_applied`, `test_hitl_middleware_auto_extraction_from_write_keywords`, `test_deepagents_interrupt_on_param_is_none_when_explicit_instance` 全部保持 PASS 状态。 |
| `backend/app/agent_runtime/tools/ask_user.py` | 保留至 Phase 4。继续直接调用 `interrupt()`。 |
| `backend/app/agent_runtime/builder_v3/**` | 保留至 Phase 5 — Builder v3 继续维持自有 native interrupt pattern(`pending_tool_call_id`)。wire format 统一放到 Phase 5 单独 track。 |

---

## 9. 按文件变更规格 (供 M1·M2 立即开工)

### Backend (4 个文件, Jensen M1)

| 文件 | 行 / 位置 | 变更摘要 |
|---|---|---|
| `backend/app/schemas/conversation.py` | 45-46 (当前 `ResumeRequest`) | 新增 `Decision` model + `ResumeRequest{decisions?, response?}` dual-shape + `model_validator` 验证。准确落实本文档 §2。 |
| `backend/app/routers/conversations.py` | 813-833 (`resume_message`) | 优先分支 `data.decisions`。若无则通过 `_legacy_response_to_decisions(data.response)` 转换。两者统一为 dict `{"decisions": [...]}` 后调用 `resume_agent_stream(cfg, payload, ...)`。 |
| `backend/app/agent_runtime/streaming.py` | 331-367 (`GraphInterrupt` catch + `aget_state` 分支) | 标准 chunk(action_requests/review_configs/interrupt_id) + legacy chunk(interrupt_id/value) **按顺序 dual emit**。fallback 分支(except)也 emit 两个 chunk，`interrupt_id=""`。准确落实本文档 §4。 |
| `backend/app/agent_runtime/executor.py` | `resume_agent_stream` signature | **保留 signature**。第二个参数(`response` → 可 rename 为 `payload`，语义为 dict `{"decisions": [...]}`)。内部 `Command(resume=...)` 调用保持原样。`_prepare_agent` 一律不修改 (保留 Phase 1)。 |

### Frontend (5 个文件, 扎克伯格 M2)

| 文件 | 位置 | 变更摘要 |
|---|---|---|
| `frontend/src/lib/types/index.ts` | 264-300 (interrupt variant) | `StandardInterruptPayload` + `LegacyInterruptPayload` + `InterruptPayload` union + `Decision` + `ActionRequest` + `ReviewConfig` + `DecisionType` + `ResumeDecisionsRequest`。现有 `InterruptPayload` interface rename 为 `LegacyInterruptPayload` 后，由 union 占据 `InterruptPayload` 的位置。 |
| `frontend/src/lib/chat/use-chat-runtime.ts` | 360-367 (`case 'interrupt'`), 98-99 (callback prop), 137-138 (refs) | 新增 `handledStandardInterruptIdsRef`。通过 `'action_requests' in data` 检查分支标准/legacy。标准则 `onStandardInterrupt?.(data)`, dedup。legacy fallback 保持 `onInterrupt?.(data)` 原样。props 添加 `onStandardInterrupt?: (payload: StandardInterruptPayload) => void`。 |
| `frontend/src/lib/sse/stream-resume.ts` | 新增 export | 新增 `streamResumeDecisions(conversationId, decisions[], ...)`。保留现有 `streamResume(conversationId, response, ...)` signature。 |
| `frontend/src/lib/chat/hitl-context.ts` | `HiTLContextValue` | 添加 `onResumeDecisions(decisions: Decision[], displayText?: string)`。`onResume` 保持原样。`useHiTL` 无变更。 |
| `frontend/src/messages/ko.json` | `chat.approval.*` | `chat.approval.respond`, `chat.approval.allActionsCompleted`, `chat.approval.confirmAll`, `chat.approval.actionN` 等 multi-action UX label。准确 key/文案由 M2 扎克伯格决定。 |

追加(由扎克伯格酌情决定): `frontend/src/components/chat/{user-input-ui,approval/*}.tsx` — 应用 wire adapter。component 本身已支持 4 个 action，因此只需 props adapting。

---

## 10. 验证矩阵 (Phase 2 PR done-when)

### Backend (M1 — Jensen)

| 命令 | gate |
|---|---|
| `cd backend && uv run ruff check .` | exit 0 (clean) |
| `cd backend && uv run pyright app/` | 0 errors / 0 warnings |
| `cd backend && uv run pytest tests/` | **826 (Phase 1 baseline) + 新增(M3) PASS, 回归 0** |
| `cd backend && uv run alembic upgrade head` | 可 merge (Phase 2 无 migration, sanity check) |

### Frontend (M2 — 扎克伯格)

| 命令 | gate |
|---|---|
| `cd frontend && pnpm lint` | 0 errors (允许现有 pre-existing warning) |
| `cd frontend && pnpm test --run` | 现有 PASS + 新增(M3) PASS, 回归 0 |
| `cd frontend && pnpm build` | TypeScript clean, 16 routes OK |

### 新增回归测试 (M3 — 贝索斯)

| 测试文件 | 场景 → contract section |
|---|---|
| `backend/tests/test_hitl_phase2_wire.py` (新增) | (a) 发送 `decisions: [...]` → 验证 `Command(resume={"decisions": [...]})` → §3 |
| 同上 | (b) 发送 `response: "foo"` → 验证转换为单个 respond decision → §2.4 |
| 同上 | (c) `response: ["a","b"]` → ", ".join → 验证 respond.message → §2.4 |
| 同上 | (d) `response: {"x":1}` → json.dumps → 验证 respond.message → §2.4 |
| 同上 | (e) `{}` 空 body → 422 → §2.3 |
| 同上 | (f) `{"decisions": [...], "response": "x"}` → 标准优先，忽略 legacy → §2.3 |
| 同上 | (g) streaming GraphInterrupt → 标准 + legacy 两个 chunk emit，验证顺序、相同 interrupt_id → §4.3 |
| 同上 | (h) `was_interrupted=True` + `aget_state` 失败 → emit 两个 chunk，`interrupt_id=""` → §4.5 |
| `frontend/src/lib/chat/__tests__/use-chat-runtime-hitl.test.ts` (新增或加强) | (a) 标准 payload 到达 → 调用 `onStandardInterrupt`，multi-action queue → §5.2, §5.3 |
| 同上 | (b) legacy payload 到达 → 调用 `onInterrupt` (回归 0) → §5.2 |
| 同上 | (c) 标准 → legacy 顺序到达 (相同 interrupt_id) → 只处理标准 1 次，legacy dedup → §4.3, §5.2 |
| 同上 | (d) 验证 `streamResumeDecisions` body shape (`{decisions:[...]}`) → §6.1 |
| 同上 | (e) 验证 `streamResume` body shape (`{response}`) — 回归 guard → §6.2 |

### M4 — 集成验证 (Satya)

以上 backend + frontend + 新增测试全部 PASS + 将 HANDOFF.md 更新为 Phase 3 预备信息。

---

## 附录 A. Trigger 模式 (保留 Phase 1)

由于 `backend/app/agent_runtime/executor.py:_prepare_agent` 的 `include_ask_user=False` indicator，trigger(scheduler/`execute_agent_invoke`) 路径被强制设为 `interrupt_on=None`，因此不会注入 `HumanInTheLoopMiddleware` 实例本身。所以 trigger 路径不会发生本 contract 的 INTERRUPT 发布 — Phase 2 中无额外变更。

## 附录 B. 尚未解决的决策项 (Phase 3+)

本 contract 只包含 Phase 2 的 wire 决定。以下在 Phase 3+ 决定:

- 是否保留标准 chunk 的 `interrupt_id` (§4.1 安全网 — Phase 3 中将 frontend stale 验证迁移到单独 correlation 字段后可移除)。
- 移除 legacy `streamResume` 函数 + `onResume` HiTLContextValue 字段的时点 (Phase 3)。
- multi-action UI 的设计 (carousel vs accordion vs sequential) — M2 扎克伯格决定后拆分为 ADR 或 design-doc。
- 是否把 `respond` 按钮暴露给所有标准工具(`interrupt_on={"tool": True}` case) — 先采用直接遵循 `review_configs[i].allowed_decisions` 的简单策略 (M2 决定)。
