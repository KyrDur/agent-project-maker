# ADR-012：HiTL — 从自研实现迁移到 LangChain `HumanInTheLoopMiddleware`

## 状态：Phase 1~4 完成，Phase 5 进行中（统一 Builder v3 wire）

相关文档：
- milestone 进度：`HANDOFF.md`（根目录）
- 分析 PR：feature/hitl-analysis-and-plan（本 PR）

## Phase 4 决策复盘（2026-05-06）

曾尝试方案 B（retire ask_user），但在用户验证中发现**自然语言“追问” UX 丢失**，随即 revert。方案 A（保留）为最终决策。

核心洞察：
- `HumanInTheLoopMiddleware` = “执行高风险工具前的审批 gate”。仅在工具调用时触发。
- `ask_user` = “向用户提出自然语言问题的工具”。LLM 收到模糊输入时向用户提供选项。
- **两项职责正交** — middleware 无法替代 ask_user。方案 B 虽然能简化，但会整体丢失 UX 场景。

§5 方案 B 的表面理由（“tool description 的 implicit prompt 污染”）确实存在，但此前错误估计了 trade-off：该成本小于 UX 丢失。明确记录本复盘，避免未来再次尝试方案 B。

---

## Phase 5 复盘 — ADR-012 migration 结束（2026-05-06）

Phase 0~5 全部完成后，ADR-012 5 阶段 migration 整体结束。进入 Phase 5 时的核心决策：

- **Router-only adapter**：graph 本体（`builder_v3/graph.py`, `state.py`, `phase{2,3,4,5,7,8}*.py`）0 变更。backend router/services 通过 `decisions_to_builder_response` helper 将标准格式 → builder native shape。将 frontend `decisionToBuilderResponse` adapter（PR #135）的职责原样迁移到 backend — 行为 0 变更，移除 dual-wire。
- **Phase 6 JSON.parse fallback**：仅在 image_choice / image_approval 的 string 分支增加 JSON.parse 尝试（3-5 行）。优先保持现有 dict/string 分支，仅新增处理 JSON string — backward compatible。
- **Clean break**：立即移除 `BuilderResumeRequest.response` 字段。沿用 Phase 2 dual-path transition（main chat）的经验 — Builder 影响用户范围较小，clean break 安全。
- **retire adapter**：PR #135（-18）+ test（-55，retire 8 个 guard）。Phase 5 PR 本身保留新增 guard ≥3 个（helper mapping、422、JSON.parse）。

核心学习：
1. **graph 目录保持单一职责**。wire adapter / conversion helper 由 services 层负责。把 `_resume_adapter.py` 放进 builder_v3/ 会模糊 graph state machine 的内聚性 — 将 helper 放在 services/builder_service.py 才是正确模块边界。
2. **逐 Phase 统一 wire vs 保留 graph 的 trade-off**：main chat 迁移到标准 middleware（包括 graph 行为变化）价值很高。Builder 属于 8-phase deterministic state machine 模式，因此只通过 router-only adapter 统一 wire 才正确 — 保持两者正交。
3. **clean break guard 的价值**：`test_resume_rejects_legacy_response_field_422` 这样的 guard 不只是 negative test，而是将“无意让两种 wire format 共存”的 ADR 决策锁进代码的 design lock。防止未来有人以兼容性为由重新加入 dual-shape。

---

## 背景

当前 main chat 的 HiTL（Human-in-the-Loop）是在引入 deep agents 之前构建的自研实现，分散在三条路径：

1. `tools/ask_user.py` — 直接调用 LangGraph `interrupt()` 的 special tool
2. `streaming.py:331-367` — catch `GraphInterrupt` + 自定义 SSE INTERRUPT event emit
3. `routers/conversations.py:813-833` — `POST /messages/resume` + `Command(resume=response)`

middleware 只注册但明确不实例化（`middleware_registry.py:419`）。`executor.py:477-493` 只提取 `interrupt_on` dict 后自行处理。

问题：
1. **trigger 模式无效** — 调用 `ask_user` 后，没有用户响应会永久停止
2. **无法按工具设 policy** — all-or-nothing（调用 ask_user = 必须等待人工）
3. **Multi tool_call 分散** — 一个 AIMessage 的 N 个 tool_call → N 个 interrupt → 用户点击 N 次
4. **无法利用 deep agents 的 SubAgent 继承 / built-in tool 应用**

---

## 决定

### 1. 仅将 main chat 迁移到标准 `HumanInTheLoopMiddleware`

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[send_email, write_file, ask_user],
    interrupt_on={
        "send_email": True,
        "write_file": {"allowed_decisions": ["approve", "reject"]},
        "ls": False,
        "ask_user": {"allowed_decisions": ["respond"]},  # 自定义工具也通过标准路径 wrap
    },
    checkpointer=postgres_saver,
)
```

依据：
- trigger 模式：通过 `interrupt_on={"ask_user": False}` 可自动批准
- 按工具 policy：按风险级别差异化（与 PRD 的“高风险 action 前审批”精确对应）
- Multi tool_call 批量处理：一个 AIMessage 的全部 tool_call → 一个 interrupt
- LangChain 1.x 稳定 + DeepAgents 自动注入

### 2. Builder v3 保持自有模式

**依据**（分析结果）：
- Builder v3 是 8-phase deterministic state machine（`backend/app/agent_runtime/builder_v3/graph.py`）
- node 不是在 LLM 调用循环中，而是**直接**调用 `interrupt()` — 分离 `propose + wait`（LangGraph 推荐 pattern）
- 各 Phase 的 dialog flow 不适合“tool_call interrupt”这一隐喻
- Stale interrupt 验证（`pending_tool_call_id`）也是 long-running multi-step 专用 — 普通 chat 不需要

→ **与 main chat 正交。** Builder v3 继续使用 LangGraph native interrupt 才正确。不与标准 middleware 统一。仅可选择性统一 wire format。

### 3. ResumeRequest payload 标准格式

```python
# 新增（Phase 2）
class ResumeRequest(BaseModel):
    decisions: list[Decision]  # length === interrupt_on tool_call count
    # transition 期间：也接收 response 字段并转换为单一 respond decision
    response: str | list[str] | dict | None = None  # @deprecated

class Decision(BaseModel):
    type: Literal["approve", "edit", "reject", "respond"]
    edited_action: dict | None = None  # type=edit
    message: str | None = None         # type=reject | respond
```

### 4. INTERRUPT SSE event payload 标准化

```typescript
// 标准（Phase 2）
{ event: 'interrupt', data: {
    action_requests: [{ name: string, args: Record<string, unknown>, description?: string }],
    review_configs: [{ action_name: string, allowed_decisions: ('approve'|'edit'|'reject'|'respond')[] }]
} }
// 现有（transition 期间可 dual emit）
{ event: 'interrupt', data: { interrupt_id: string, value: { type: 'ask_user', question: string, options?: string[] } } }
```

### 5. 保留 `ask_user` 工具（方案 A）

方案 A（已选择）：原样保留 `ask_user` 工具 + 标准 middleware 使用 `interrupt_on={"ask_user": True}` wrap。
- 不影响 LLM prompt / tool description
- 自身 `interrupt()` 调用可与 middleware 调用共存（middleware 在 tool_call 阶段发出 interrupt，ask_user 本身可逐步 retire 为无操作工具）
- migration 后逐步简化 ask_user

方案 B（搁置）：完全移除 `ask_user`。需要修改 LLM prompt + regression 风险。

### 6. 利用 Frontend UI — 4 种 action 已实现

分析结果：
- `UserInputUI`（ask_user）— `respond` action（free text + single/multi select）
- `ApprovalCard`（request_approval）— 已支持 `approve` / `reject` / `edit`
- `HiTLContext` + `onResume` callback 模式

→ **Phase 2 的 UI 工作不是新增 component，而是 wire adapter** + multi-action queue 处理。

### 7. Multi-action 批量 queue 处理（Phase 2）

当前 `consumeStream` 的 `case 'interrupt'` 假设单个 interrupt（`onInterrupt(payload)`）。
标准 middleware 会把一个 AIMessage 的所有 tool_call 打包 → frontend 以数组 queue 处理。

### 8. APScheduler trigger 显式禁用

`execute_agent_invoke` 路径（trigger）处于用户异步环境 — 无法 interrupt。
trigger 调用时将 `interrupt_on` config 全部 override 为 `False`（或完全不注入 middleware）。

---

## Migration 阶段（按 Phase 分 PR）

### Phase 0 — 前置分析 + ADR（本 PR）
- 不改代码。只更新 ADR-012 + HANDOFF。

### Phase 1 — Backend 基础设施（用户无感，~150 行）
**Done-when**：标准 middleware instance 注入 deep agent，但 SSE wire 继续保留自有格式（dual-path）

- `executor.py`：`interrupt_on` dict → 创建 `HumanInTheLoopMiddleware(interrupt_on=...)` instance，并加入 deep agent
- `middleware_registry.py`：整理 `human_in_the_loop` 排除列表 — 正常实例化 middleware
- 新增单元测试：按工具应用标准 middleware interrupt_on / trigger 模式自动批准

**文件**：`backend/app/agent_runtime/{executor.py, middleware_registry.py}` + 新增 `tests/test_hitl_middleware.py`

### Phase 2 — Wire Format 统一（影响用户，dual-path transition，~400 行）
**Done-when**：INTERRUPT event 标准格式 + ResumeRequest `decisions: [...]` 格式都可工作，frontend 支持 4 种 action + multi-action queue

Backend:
- `schemas/conversation.py`: `ResumeRequest{decisions, response?}` (dual-shape)
- `routers/conversations.py:resume_message`：`decisions` → `Command(resume={"decisions": [...]})`。若传入 `response`，则转换为单一 respond decision（transition）
- `streaming.py`：catch GraphInterrupt 时 emit 标准 `{action_requests, review_configs}` 格式。现有自定义格式也 dual emit（transition）

Frontend:
- `lib/types/index.ts`：`SSEEventType` 的 interrupt variant 使用标准 + 现有两种格式 union
- `lib/chat/use-chat-runtime.ts:case 'interrupt'`：处理标准 payload（multi-action queue）
- `lib/sse/stream-resume.ts`：以 `{decisions: [...]}` 格式发送
- `HiTLContext` / `useHiTL`：数组处理 + adapter
- `messages/ko.json`：新增 `chat.approval.respond`、`chat.approval.allActionsCompleted` 等 label
- regression test — 标准格式 + 现有格式都能处理

### Phase 3 — Transition 结束（~80 行）
**Done-when**：移除 dual-path，只保留标准格式

- 移除 backend ResumeRequest 的 `response` 字段
- 移除 frontend 现有 `{interrupt_id, value}` 处理代码
- 移除 streaming.py 自定义 INTERRUPT emit（仅保留标准 middleware 发出）

### Phase 4 — `ask_user` 评估（可选，~30 行）
**Done-when**：完成 ask_user 工具依赖性评估，决定简化或 retire

- 分析 ask_user 对 LLM prompt 的影响
- 若标准 middleware 足以替代则移除工具
- 若需要保留选项 UX，则调整 `ask_user` description

### Phase 5 — 统一 Builder v3 wire format（~150 行）
**Done-when**：Builder v3 的 ResumeRequest 也接收标准 `decisions: list[Decision]` 格式，retire frontend `decisionToBuilderResponse` adapter，graph + state + 8 个 phase node（phase6 除外）0 变更，regression guard ≥3 个 PASS

**用户决策（2026-05-06）**：Router-only adapter + image_choice JSON.parse fallback + Clean break（无 dual-path）

工作项：
- 新增 `decisions_to_builder_response(decisions)` helper — `backend/app/services/builder_service.py`（graph 目录保持 graph/state/nodes 单一职责，wire adapter 由 services 负责）
- `routers/builder.py` `BuilderResumeRequest{decisions: list[Decision]}` clean break（移除 legacy `response` 字段）
- `routers/builder.py` `resume_message` handler — 调用 helper 后传入 `Command(resume=...)`
- `phase6_image.py`（choice + approval）string JSON.parse fallback 3-5 行 — backward compatible（优先现有 dict/string 分支，仅新增处理 JSON string）
- 删除 frontend `lib/chat/builder-resume-adapter.ts`（-18）+ 删除 `__tests__/builder-resume-adapter.test.ts`（-55，retire 8 个 guard — Phase 5 PR 本身新增 regression guard ≥3 个作为保留）
- 移除 `use-chat-runtime.ts:onResumeDecisions` adapter 调用，将 `ResumeFn` 签名更新为 `decisions: Decision[]`
- `stream-builder-resume.ts` 签名 + POST body `{decisions, display_text, interrupt_id}`

Regression guard（≥3 个，新增）：
- `test_resume_accepts_standard_decisions` — 标准 wire 200
- `test_resume_rejects_legacy_response_field_422` — clean break guard
- `test_decisions_to_builder_response_mapping` — helper 单元测试
- `test_phase6_choice_accepts_json_string` — 防止 JSON.parse fallback regression

**保留（禁止修改）**：`builder_v3/graph.py`、`state.py`、`phase{2,3,4,5,7,8}*.py`、`_helpers.parse_approval_response`（dict|str 兼容）、`pending_tool_call_id` stale 验证。

---

## 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| Wire format 变更 = breaking change | dual-path transition window — 一个 PR 中同时接收两种格式，4 个 PR 后移除 |
| Multi-action UI 没有新设计 | `ApprovalCard` 已支持单个 action — 只需增加数组渲染 + 批量确认按钮 |
| `ask_user` LLM prompt 变更时 regression | 保留 ask_user 到 Phase 4，充分 regression test 后再决定 |
| Builder v3 graph 影响 | 通过 Router-only adapter 让 graph + state + 大多数 node 0 变更。只有 phase6 image_choice/approval 增加 backward-compatible JSON.parse fallback（优先现有 dict/string 分支，只新增 JSON string 处理）。通过 regression guard ≥3 个验证 mapping + 422 + JSON.parse。 |
| trigger 模式发生 interrupt 时 hang | trigger 调用时强制 override `interrupt_on` config，并做 regression test |
| Stale interrupt（点击旧 card） | 考虑把 Builder 的 `pending_tool_call_id` 模式也应用到 main chat（Phase 2 内） |

---

## 验证

每个 Phase PR：
- `cd backend && uv run alembic upgrade head && uv run ruff check . && uv run pytest tests/ && uv run pyright app/ tests/`
- `cd frontend && pnpm lint && pnpm test --run && pnpm build`

按 Phase 新增 regression test：
- Phase 1：按工具应用 interrupt_on / trigger 模式自动批准
- Phase 2：标准 + 现有 wire 两边都可工作 / multi-action 批量处理
- Phase 3：移除现有 wire 后 regression 0
- Phase 4：retire ask_user 时做 LLM prompt regression
- Phase 5：builder graph state regression 0

手动 e2e：
- 调用普通工具（e.g. write_file）→ approve/reject/edit 各 action 正常工作
- 同时 emit multi tool_call（e.g. delete_file + send_notification）→ 数组 review → 批量 decision
- 调用 ask_user → respond 正常工作
- trigger 中调用可 interrupt 工具 → 自动批准

---

## 决策依据摘要（TL;DR）

引入 deep agents 后，自研 HiTL 实现阻碍了标准 middleware 的价值（按工具 policy / SubAgent 继承 / trigger 自动批准 / multi tool_call 批量处理）。将 main chat 迁移到标准 `HumanInTheLoopMiddleware` 后，可实现 (a) 在 trigger 模式中有意义地应用 HiTL policy，(b) 按工具风险级别差异化（PRD 核心场景），(c) 一个 AIMessage 的 multi tool_call 只需用户点击 1 次。Builder v3 属于 deterministic state machine 模式，与其正交，应保持自有实现。成本为 5 个 Phase、约 800 行，regression 风险通过 dual-path transition 缓解。
