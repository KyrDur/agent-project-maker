# HITL Hardening Implementation Plan — robust `edit` + `allowed_decisions` gating

> **For agentic workers:** 本文按“只看这一份文档即可从头到尾实现”的标准编写。所有修改都包含文件路径 + 函数名 + 代码 snippet + 测试 + 验证 command。步骤用 checkbox（`- [ ]`）追踪。先阅读 §2（当前状态 — 已实现的内容），绝对不要重复实现。

**编写依据：** 直接对照当前源码（`/Users/chester/dev/ref/natural-mold-captures`，langchain 1.3.9，deepagents 0.6.9）。旧版文档（executor.py build site、手动 append `HumanInTheLoopMiddleware`）**全部废弃**。

**Goal：** 强化 main chat HITL（human-in-the-loop）中的 **`edit`（修改后批准）decision**，并让**按工具配置的 `allowed_decisions` whitelist 真正被尊重**。同时整理已经实现的 multi-action wire / subagent 继承中的*剩余 gap*与 ask_user 集成决策。

**Tech Stack:** FastAPI, LangChain 1.3.x (`HumanInTheLoopMiddleware`), LangGraph 1.x, DeepAgents 0.6.9 (`create_deep_agent(interrupt_on=...)`), React 19, assistant-ui, TanStack Query, Vitest, pytest.

---

## 1. 背景 — HITL 4 种 decision

工具执行前的用户介入使用 LangChain `HumanInTheLoopMiddleware` 标准 interrupt 体系。decision type 共 4 种：

| type | 含义 | 附加字段 |
|---|---|---|
| `approve` | 原样执行 | 无 |
| `edit` | **修改参数后执行** | `edited_action: {name, args}` |
| `reject` | 拒绝执行 | `message?`（原因） |
| `respond` | 不执行工具，直接把用户回答返回给模型（仅 ask_user） | `message` |

各工具允许哪些 decision，会通过 interrupt payload 的 `review_configs[i].allowed_decisions` 下发。本工作核心是让 **edit 稳定工作**并让**card 尊重 allowed_decisions**。

---

## 2. 当前状态 — 已经实现的部分（禁止重复实现）

此前文档写成“需要实现”的大多数项目其实**已经实现并测试完成**。禁止返工。

### 2.1 ✅ Backend：top-level `interrupt_on` 路径（含 subagent 继承）— DONE

- **build site 已移动。** `backend/app/agent_runtime/executor.py` 现在只是**re-export facade**（整个文件仅重新暴露 import）。实际 build 位于 `backend/app/agent_runtime/runtime_component_builder.py`。
- `build_agent()`（`runtime_component_builder.py:83-97`）通过 `create_deep_agent(..., interrupt_on=interrupt_on, ...)` 传入 **top-level parameter**。**app 代码中手动 `HumanInTheLoopMiddleware(` 实例为 0 个**（grep 确认）。
- 策略计算：`_build_interrupt_on_policy()`（`runtime_component_builder.py:363-392`）= `_default_interrupt_on_from_tools()`（`:354-360`）+ 合并 `middleware_configs` 中显式的 `human_in_the_loop.params.interrupt_on` + `ask_user` policy `setdefault`。
- **按工具的 policy 由 `backend/app/tools/risk.py` 决定**（本工作的 allowed_decisions 来源）：
  - `default_deepagents_interrupt_policy()` (`risk.py:271-276`): `write_file→[approve,reject]`, `edit_file→[approve,edit,reject]`, `execute→[approve,reject]`.
  - `interrupt_policy_for_tool()`（`risk.py:279-283`）：根据 tool risk metadata 发出**显式 allowed_decisions**（不是 `{tool: True}`）。
  - `_DEFAULT_APPROVAL_DECISIONS` (`risk.py:24-30`): WRITE_INTERNAL / EXTERNAL_MUTATION → `(approve, edit, reject)`; CODE_EXECUTION / UNKNOWN → `(approve, reject)`.
  - `execute_in_skill_risk()`（`risk.py:260-268`）：CODE_EXECUTION → **`(approve, reject)` — 不含 edit**。
  - MCP mutation (`risk.py:250-257`): `(approve, reject)`.
  - `ask_user`: `{"allowed_decisions": ["respond"]}` (`runtime_component_builder.py:390-391`).
- ask_user 顺序 bug 已修复：`ask_user_tool` / `execute_in_skill` 会在 policy 计算（`:690`）**之前** append（`:646`、`:688`）。
- **Subagent 继承**（`subagents.py:74-168`）：每个 child 都根据自己的工具计算自己的 `interrupt_on`，写入 `spec["interrupt_on"]`（`:162-163`）。deepagents 0.6.9 `graph.py:663` 优先使用 spec 值，缺失时继承 top-level；auto `general-purpose` subagent 继承 top-level（`graph.py:741-746`）。
- **Trigger mode 阻断**：`_build_interrupt_on_policy` 返回 None（`:377-378`），不注入 ask_user（`:687-688`、`:737`），`trigger_executor.py:202-218` 会预先阻断 risky tool 本身。
- `middleware_registry.py`：`human_in_the_loop` ∈ `EXPLICITLY_INSTANTIATED_TYPES`（`:459-464`）→ 跳过 `build_middleware_instances`（`runtime_component_builder.py:609-611`），但仍保留在 catalog 中。
- 测试：`tests/test_hitl_middleware.py`（top-level interrupt_on + `_hitl_instances == []` guard）、`tests/agent_runtime/test_subagents_runtime.py:184`、`tests/agent_runtime/test_langgraph_hitl_interrupts.py`。

### 2.2 ✅ Frontend: multi-action wire coordination — DONE

- `frontend/src/lib/chat/standard-interrupt.ts`：`standardInterruptToToolCalls()`（`:126-153`，action_request → synthetic tool call，通过 `metadataForAction` `:45-58` 附加 `hitl_action_index/total/interrupt_id/approval_id/allowed_decisions` metadata）、`createHiTLDecisionCoordinator()`（`:213-244`，**汇总 N 个 decision，按 index 顺序仅 resume 一次**，idempotent）。
- `reviewForAction()`（`:31-43`）：无 review_config 时 fallback `allowed_decisions: ['approve','reject']`。
- v3 路径 adapter `frontend/src/lib/chat/langgraph-runtime/hitl-interrupts.ts`（复用 `standardInterruptToToolCalls` `:10`，normalize/projection），stream hook wiring `use-moldy-langgraph-stream.ts:2328-2358`（projection），coordinator map `:2562`，`registerDecision` `:2871-2897`（single action bypass `:2880-2883`，multi coordinator `:2884-2894`），并发 interrupt batch `respondAll` `:2756-2811`。
- card dispatch：`approval-card.tsx` 的 `resumeDecision` 若有 `hitl_action_index` 则优先 `registerDecision`，否则 fallback 到 `onResumeDecisions`。`user-input-ui.tsx` 同样。
- `hitl-context.ts:12-17`: `registerDecision` API.
- 测试：`standard-interrupt.test.ts`（含 coordinator）、`use-moldy-langgraph-stream.test.tsx`（multi/concurrent batching）、`langgraph-runtime/__tests__/hitl-interrupts.test.ts`。

### 2.3 ✅ ask_user wire normalization — DONE（但基于 native interrupt）

- ask_user 是 LLM-visible tool，虽然 policy 注册为 `[respond]`，但实际等待发生在 **tool body 内部 native `interrupt()`**（`backend/app/agent_runtime/tools/ask_user.py:152`）。`streaming._interrupt_to_standard_chunk`（`streaming.py:198-221`）将 native payload 适配为标准 `respond` action。resume 解析 `_extract_respond_message`（`ask_user.py:62-77`）同时处理 `{"decisions":[{"type":"respond","message":...}]}` 和 bare string。

### 2.4 ❌ 尚未实现的部分（= 本工作范围）

1. **强化 `edit`** — frontend 不知道 `tool_name` 时 hard stop、raw JSON textbox、secret 恢复依赖位置（见 §3）。
2. **`allowed_decisions` gating** — card 收到了值，但**没有用于按钮显示**（潜在 bug）。即使工具不允许 edit（如 `execute_in_skill`），也会显示“修改”按钮，点击后 middleware 才晚到 ValueError。
3. （可选）**统一“N 项等待中” UX** — wire 已完成，但没有视觉 grouping/“全部批准”。
4. （可选/待决定）是否将 **ask_user 真正整合为 middleware respond**，还是保留当前 native+wire normalization 并文档化。
5. （可选）**父级 custom HITL policy 向 linked subagent 传播** — 当前 child 只读取自己的 `middleware_configs`（`subagents.py:118`），父级 override 不会传播。

---

## 3. 问题详情 — `edit` 出错的位置（当前代码）

以 `frontend/src/components/chat/tool-ui/approval-card.tsx` 为准。

### 3.1 hard stop — `tool_name` 未知时无法 edit
`toDecision('modified', resumeResponse, args?.tool_name)`（`:~118-133`，调用 `:~360`）：
```ts
case 'modified':
  if (!toolName) return null            // ← hard stop
  return toEdit({ name: toolName, args: response.modified_args ?? {} })
```
如果为 `null`，handler 会中断整个 submit，并显示**错误消息** `invalidJson`（`:~361-367`）。`tool_name` 会在 `standard-interrupt.ts:146` 中由 `action.name` 填充，但在 merge 路径里，来自 raw model tool-call 的 slot 中 `tool_name` 为空，因此只有 edit 会失败（approve/reject 正常）。

**根本原因：** frontend 必须**重建并发送** `edited_action.name`（tool name）。因为 langchain `human_in_the_loop.py:310-320` 会用 hard subscript 读取 `edited_action["name"]`/`["args"]`。

### 3.2 raw JSON textbox — 会因语法错误而崩
进入 edit 时，将 `JSON.stringify(toolArgs, null, 2)` 填入 `editedArgs`，通过 textarea 编辑（`:~480-495`、`:~515-527`）。submit 时执行 `JSON.parse(editedArgs)`（`:~342-358`）— 只要一个括号/引号出错就会触发 `invalidJson`。

### 3.3 secret（`<redacted>`）恢复依赖位置 — 泄漏/丢失
`tool_args` **在 source 中已经 redacted**（`standard-interrupt.ts:130` 的 `redactSensitiveRecord`）。因此 frontend 的 `restoreRedactedRecordPlaceholders(parsed, args?.tool_args)`（`:~56-80`、`:~347-350`）在**生产中是 no-op**（原始值也已经是 `<redacted>`，没有可恢复的值）。实际恢复由 backend 从 checkpoint 完成。更糟的是：frontend/backend 的恢复都依赖**key 名称·array index 位置匹配**，因此如果用户 rename `<redacted>` key / reorder array / 删除一行，secret 会**原样发送或丢失**（且无 error）。
> ⚠️ 现有测试 `approval-card.test.tsx` 中的“restores redacted placeholders…”通过直接向 `tool_args` 注入 **un-redacted** 值来通过 — 对生产中实际不工作的路径产生了错误安全感。本工作中替换该测试。

### 3.4 `allowed_decisions` 潜在 bug
`ApprovalArgs.allowed_decisions`（`:40`）虽然会被填充（`standard-interrupt.ts:150`），但**render 时没有读取**。button block（`:~500-562`）无条件画出 approve/edit/reject 3 个按钮。即使 `execute_in_skill`（allowed=`[approve,reject]`）也会显示 edit 按钮，点击后 v3 resume 路径不做验证，直接 raw 传递（`InputRespondEntry.response: Any`）→ 到 middleware `_process_decision` 才触发 ValueError（`human_in_the_loop.py:343-349`）。

---

## 4. 推荐设计

### 4.1 Edit-by-index（frontend 不发送 tool name）
- **backend 按 index 填充 tool name。** langchain 按**位置 index**匹配 decision↔action（`human_in_the_loop.py:438,450-455`），tool-call `id` 由 middleware 从匹配到的 pending call 中取得。因此 `edited_action.name` 可以由 backend 用**已经知道的** `action_requests[index].name` 填充。
- `conversation_agent_protocol_resume_redaction.py` **已经**按 interrupt index 重建原始 `{name,args}`（`_raw_pending_actions_by_interrupt` `:69`，匹配 `_restore_redacted_response` `:157`）。当前只恢复 args，name 沿用 frontend 值（`:184`）。→ 应**权威覆盖 name**。
- **结果：** frontend 不再需要可靠地构造 `edited_action.name` → 移除 §3.1 hard stop。

### 4.2 Field-based editor（替代 raw JSON）
- 将 `ArgsPreview` 已有 key/value list 扩展为**可编辑 form**：每个值使用 input control，**secret key（`isSensitiveDisplayKey`）设为 read-only lock**（显示 `<redacted>`，不可编辑）。
- submit 时不再使用 `JSON.parse` → 消除 §3.2。secret 被锁定，无法 rename/reorder → 消除 §3.3 泄漏/丢失。frontend 无需 `restoreRedactedRecordPlaceholders`（恢复归 backend 所有）。

### 4.3 allowed_decisions gating（仅 frontend）
- 按 card 收到的 `allowed_decisions` 条件渲染按钮。**为空/缺失时默认 `[approve, reject]`**（不包含 edit — 与 `reviewForAction` fallback 一致）。backend 已经发送正确值，因此**无需 backend 修改**。

---

## 5. 文件结构（修改对象）

### Backend
- **Modify** `backend/app/routers/conversation_agent_protocol_resume_redaction.py`
  - 对所有 edit decision 执行 action-by-index 解析（放宽当前仅存在 `<redacted>` 时才运行的 early-return）
  - 将 `edited_action["name"]` 权威设置为 `raw_actions[index]["name"]`
- **Modify** `backend/app/routers/conversation_agent_protocol_commands.py`（可选）
  - 在 `_handle_input_respond_command` 中将每个 decision.type 与 pending `review_configs[index].allowed_decisions` 交叉验证（提前拒绝）。或在 `conversation_agent_protocol_resume.py:validate_resume_payload` 中处理。
- **Modify** `backend/tests/test_hitl_wire.py`
  - 新增 v3 `responses`-keyed resume + name-fill + multi-action edit index 排序测试

### Frontend
- **Modify** `frontend/src/components/chat/tool-ui/approval-card.tsx`
  - 按 `allowed_decisions` gating 按钮
  - edit：移除 hard stop + field-based editor
  - 移除 `restoreRedactedRecordPlaceholders`（恢复归 backend 所有）
- **Modify** `frontend/src/lib/types/index.ts` + `frontend/src/lib/chat/decision-mappers.ts`
  - 将 `Decision.edited_action.name` 改为 optional（或允许 name-less edit）
- **Modify** `frontend/src/components/chat/tool-ui/__tests__/approval-card.test.tsx`
  - allowed_decisions gating / name-less edit / secret lock / field editor 测试

---

## 6. 实现任务（Task by Task）

> 推荐顺序：**Task 1（先写测试）→ 2（backend edit-by-index）→ 3（frontend gating）→ 4（frontend edit UI）→ 5（集成验证）**。每个 Task 都应做到独立 green。

### Task 1 — 先新增 backend 回归测试（TDD）

**Files:** `backend/tests/test_hitl_wire.py`

- [ ] **Step 1：测试 v3 edit 即使没有 name，也会由 backend 填充（预期失败）。**
  直接调用 `conversation_agent_protocol_resume_redaction.py` 的 restore function，当存在 pending action（`action_requests=[{name:"execute_in_skill", args:{command:"old"}}]`）时，输入 decision `{type:"edit", edited_action:{args:{command:"new"}}}`（无 name、无 redacted），断言结果为 `edited_action.name == "execute_in_skill"`、`args.command == "new"`。
  ```python
  def test_edit_decision_name_filled_from_pending_action_by_index():
      restored = restore_redacted_resume_payload(
          input_payload={"intr-1": {"decisions": [
              {"type": "edit", "edited_action": {"args": {"command": "new"}}}
          ]}},
          pending_actions_by_interrupt={"intr-1": [
              {"name": "execute_in_skill", "args": {"command": "old"}}
          ]},
      )
      d = restored["intr-1"]["decisions"][0]
      assert d["edited_action"]["name"] == "execute_in_skill"
      assert d["edited_action"]["args"]["command"] == "new"
  ```
  （实际 function signature/helper 名称需打开 `conversation_agent_protocol_resume_redaction.py` 对齐 — `restore_redacted_resume_payload`（`:18`）、`_raw_pending_actions_by_interrupt`（`:69`）。）

- [ ] **Step 2：测试 multi-action edit 按 index 对齐（预期失败）。** 有 2 个 action 时，2 个 decision 的 edit name 应分别填入 `action_requests[0].name`、`[1].name`。

- [ ] **Step 3：执行并确认失败。**
  ```bash
  cd backend && uv run pytest tests/test_hitl_wire.py -q
  ```

### Task 2 — backend：edit-by-index（填 name，应用于所有 edit）

**Files:** `backend/app/routers/conversation_agent_protocol_resume_redaction.py`

- [ ] **Step 1：放宽 early-return gate。** 当前 `restore_redacted_resume_payload` 在 `_resume_contains_redacted_edit(...)` 为 False 时直接返回 raw（`:24` 附近）。应扩展条件：只要存在任一 edit decision（无论是否 redacted）就走 index 解析路径。（普通无 redacted 的 edit 也需要填 name。）

- [ ] **Step 2：权威设置 name。** 在 `_restore_redacted_response`（`:157-190` 附近）的 edit 分支中，如果存在 `raw_actions[index]`：
  ```python
  edited = dict(decision.get("edited_action") or {})
  if index < len(raw_actions):
      edited["name"] = raw_actions[index]["name"]          # 权威：忽略 frontend name
      edited["args"] = restored_args                        # 保持现有 placeholder 恢复
  restored_decisions.append({**dict(decision), "edited_action": edited})
  ```
  - 如果没有 `raw_actions[index]`（防御性情况），fallback 到现有行为（保留 frontend 值）。
  - 现有 `<redacted>` placeholder 恢复（`_restore_placeholders`）**保持不变**。

- [ ] **Step 3：确认 Task 1 测试通过。**
  ```bash
  cd backend && uv run pytest tests/test_hitl_wire.py -q && uv run ruff check app tests
  ```

- [ ] **Step 4（可选，提前拒绝）：验证 allowed_decisions。** 在 `conversation_agent_protocol_commands.py:_handle_input_respond_command`（或 `conversation_agent_protocol_resume.py:validate_resume_payload` `:64`）中，如果某 decision.type 不在该 interrupt 的 `review_configs[index].allowed_decisions` 中，则提前以 422/结构化 error 拒绝。（当前不验证，导致直到 middleware 深处才 ValueError。）frontend gating（Task 3）为第 1 层防御，因此这里属于 defense-in-depth。

### Task 3 — frontend：`allowed_decisions` button gating

**Files：** `frontend/src/components/chat/tool-ui/approval-card.tsx`，测试

- [ ] **Step 1：派生 allow-set。** 在 `!submitting` 分支顶部（`:~501`）计算 1 次：
  ```ts
  const allowed = new Set(args?.allowed_decisions ?? [])
  const canApprove = allowed.size === 0 ? true : allowed.has('approve')
  const canEdit = allowed.has('edit')                      // 默认（空）时隐藏 edit
  const canReject = allowed.size === 0 ? true : allowed.has('reject')
  ```
  （空/缺失 → 仅 approve+reject，排除 edit — 与 `reviewForAction` fallback 相同策略。）

- [ ] **Step 2：给每组按钮加 guard。** approve（`:~503-512`）用 `canApprove &&` 包裹，edit（`:~515-538`）用 `canEdit &&`，reject（`:~541-561`）用 `canReject &&`。reject-only（approve/edit 都不可用）时保持 reject confirm 2-step。

- [ ] **Step 3：新增测试。** `approval-card.test.tsx`：
  - `allowed_decisions: ['approve','reject']` → 无 edit button（`queryByText('edit')` 为 null）。
  - `['approve','edit','reject']` → 3 个都有。
  - 缺失/`[]` → 仅 approve+reject（隐藏 edit）。
  - reject-only → 只有 reject + confirm 行为。
  - 执行：`cd frontend && pnpm exec vitest run src/components/chat/tool-ui/__tests__/approval-card.test.tsx`

### Task 4 — frontend：稳健 edit（移除 hard stop + field editor）

**Files：** `approval-card.tsx`、`decision-mappers.ts`、`types/index.ts`、测试

- [ ] **Step 1：放宽类型。** 将 `frontend/src/lib/types/index.ts` 中 `Decision.edited_action` 改为 `{ name?: string; args: Record<string, unknown> }`（name optional）。`decision-mappers.ts` 的 `toEdit` 也允许无 name 调用（或新增 `toEditByIndex(args)`）。

- [ ] **Step 2：移除 hard stop。** 删除 `toDecision('modified', ...)`（`approval-card.tsx:~126-129`）中的 `if (!toolName) return null`。如果有 name 则作为 advisory 附带，没有则省略（backend 按 index 填充）。调用处（`:~360-367`）的 `if (!standardDecision)` abort 对 edit 也不再需要。

- [ ] **Step 3：field-based editor。** 扩展 `ArgsPreview`（当前 key/value list）以支持 edit mode，或新增 `ArgsEditor` component：
  - 将 state 从 `editedArgs: string`（JSON）改为 `draft: Record<string, unknown>`（按 key 的值）。初始值 = `args.tool_args`（redacted）。
  - 每个 entry 使用 `<dt>{key}</dt><dd><input/></dd>`。**若 `isSensitiveDisplayKey(key)`，则 read-only lock**（显示 `<redacted>`，无 onChange）。
  - scalar 使用文本 input，非 scalar（object/array）使用 compact JSON 文本 input（解析失败时只在该 field 显示 error — 禁止整体 abort）。
  - submit（`handleDecision('modified')`）不再 `JSON.parse`，直接使用 `draft`。移除 `restoreRedactedRecordPlaceholders` 调用（secret 被锁定无法变形 → backend 恢复）。

- [ ] **Step 4：清理 dead code。** 如果不再使用 `restoreRedactedPlaceholders`/`restoreRedactedRecordPlaceholders`（`approval-card.tsx:56-80`），则删除。移除 `editedArgs`/`jsonError` state。

- [ ] **Step 5：替换测试。**
  - 删除/替换现有“restores redacted placeholders…”测试（`:~294-350`）：停止注入 un-redacted 值，改为断言“secret key 为 read-only 且不可编辑，只修改非 secret field 并提交时，不会把 `<redacted>` literal 发出去，并发送不带 name 的 edit decision”。
  - **新增：无 name 也能 edit**（§3.1 回归）。以 `tool_name` undefined 渲染 → 修改一个 field → submit → 不触发 `invalidJson` abort，断言发送 `{type:'edit', edited_action:{args:{...}}}`（无 name/advisory）。
  - “renders tool args as a readable key/value list”（`:~208-237`）按新增 edit control 更新。
  - 执行：`cd frontend && pnpm exec vitest run src/components/chat/tool-ui/__tests__/approval-card.test.tsx`

### Task 5 — 集成验证

- [ ] **Step 1：backend。**
  ```bash
  cd backend && uv run pytest tests/test_hitl_wire.py tests/test_hitl_middleware.py -q && uv run ruff check app tests
  ```
- [ ] **Step 2：frontend。**
  ```bash
  cd frontend && pnpm exec tsc --noEmit && pnpm exec vitest run && pnpm lint
  ```
- [ ] **Step 3：手动场景。**
  - `execute_in_skill` approval card → **无 edit button**（allowed=approve,reject），只有 approve/reject 可用。
  - `edit_file`/write tool approval card → 显示 edit button，修改一个 field 后 approve → 模型以修改后的 args 执行。
  - 含 secret（api_key 等）的 tool → secret field 锁定，只能修改非 secret field，submit 后 secret 正确保留（backend 恢复）。
  - 即使 `tool_name` 为空的 slot，edit 也能正常 submit，不出现 `invalidJson`。

---

## 7. （可选）额外 workstream

与本工作核心（§6）独立。必要时单独 PR。

### 7.1 统一“N 项等待中” multi-action UX（仅 frontend，增量型）
当前：N 个 card 分别渲染 + resume 仅在内部 batching（coordinator 已存在）。剩余只需**视觉 grouping**。
- 用 `hitl_interrupt_id` grouping 同一 interrupt 的 card（key：`args.hitl_interrupt_id`，总数：`args.hitl_total_actions`）。当前 card 作为独立 tool-call message 发出（`hitl-interrupts.ts:447-462`），因此需要 synthetic group header（“N 项等待中”）或 card group wrapper。
- “全部批准/全部提交”button → 对每个 pending action 调用 `hitl.registerDecision(i, 默认决策)`（默认基于每张 card 的 allowed_decisions）。现有 coordinator 会 batching，因此**backend/coordinator 无需修改，纯新增 UI**。
- 新增 i18n key（`chat.approval.pendingCount`、`chat.approval.approveAll`）— 当前不存在。
- 新增 component test（`hitl-coordinator.test.tsx` slot 目前为空）。

### 7.2 父级 custom HITL policy 向 linked subagent 传播（backend）
当前：auto general-purpose subagent 会继承 top-level，但**linked（声明式）subagent 只读取自己的 `middleware_configs`**（`subagents.py:118`），父级 custom `human_in_the_loop` override 不会传播。（基于自身 tool 的 policy 会正常应用 — 不是安全 gap，而是“父级 custom policy 一致性”问题。）
- Fix point：`subagents.py:142-163` — 将父级 policy/override merge 到 child `components.interrupt_on` 后设置 `spec["interrupt_on"]`。
- 测试：在 `tests/agent_runtime/test_subagents_runtime.py` 新增父级 override 传播用例。

### 7.3 （需要决定）ask_user 真正整合到 middleware respond，还是保持现状
当前：write/skill/MCP = `HumanInTheLoopMiddleware`，ask_user = native `interrupt()` — 只在 wire 层统一。两套机制并存。
- 选项 A（推荐，低成本）：**保持现状 + 文档化。** ask_user 通过 native interrupt + `_interrupt_to_standard_chunk` normalization 已可正常工作。确认 `runtime_component_builder.py:390-391` 的 `interrupt_on["ask_user"]` 是否属于 vestigial，再决定保留（防御）还是明确注释。
- 选项 B（高成本）：将 ask_user 迁移到 middleware respond 路径（`tools/ask_user.py:121-163` + policy + `streaming` adapter）。机制更统一，但有 UX/回归风险。**开始前需单独决策。**

---

## 8. Decision schema / wire 契约（实现参考）

### Decision（frontend→backend，与 `HumanInTheLoopMiddleware` `HITLResponse.decisions[i]` 1:1）
```ts
interface Decision {
  type: 'approve' | 'edit' | 'reject' | 'respond'
  edited_action?: { name?: string; args: Record<string, unknown> }  // ← 本工作：name optional
  message?: string  // respond 必填, reject 可选
}
```
- **edit 契约(langchain 1.3.9, `human_in_the_loop.py:310-320`):** middleware 通过 hard subscript 读取 `edited_action["name"]`/`["args"]`，tool-call `id` 从匹配的 pending call 中获取。decision↔action 匹配采用 **positional index**。→ backend 按 index 填充 name 后，frontend 无需 name。

### 标准 interrupt payload (backend→frontend, SSE `interrupt` event)
```ts
type StandardInterruptPayload = {
  interrupt_id: string          // = str(intr.ns) (namespace)
  action_requests: Array<{ name: string; args: Record<string, unknown>; description?: string }>  // 无 per-action id → 参照 index
  review_configs: Array<{ action_name: string; allowed_decisions: Array<'approve'|'edit'|'reject'|'respond'> }>
}
```
- **allowed_decisions 来源:** Moldy `risk.py` → `interrupt_on` 策略 → langchain 以 `review_configs` echo。各工具取值参见 §2.1(`execute_in_skill`=approve,reject / `edit_file`=approve,edit,reject 等)。
- **resume(v3):** `Command(resume={interrupt_id: {"decisions": [...]}})` — `conversation_agent_protocol_commands.py:_handle_input_respond_command`.

---

## 9. 推荐 commit 顺序
1. `test(hitl): pin edit-by-index name-fill + multi-action edit ordering`
2. `fix(hitl): backend fills edited_action.name from pending action by index`
3. `fix(chat): gate approval-card buttons on allowed_decisions`
4. `fix(chat): robust approval edit — field editor + name-less edit, drop client redaction restore`
5. `test(chat): allowed_decisions gating + name-less edit + locked-secret`
6. (可选) `feat(chat): unified N-pending multi-action approval UX`

## 10. 完成标准
- `execute_in_skill`(allowed=approve,reject) 卡片上**不显示修改按钮。**
- 在 `edit_file`/write 工具中修改后批准可正常工作，并且**即使 `tool_name` 为空也能在没有 `invalidJson` 的情况下**正常提交。
- secret key 在编辑卡片中为 read-only，提交时 secret 不会以字面量 `<redacted>` 泄露，并能正常保留(backend 恢复)。
- frontend 即使不重构 `edited_action.name`，backend 也会按 index 填充。
- 删除 `restoreRedactedRecordPlaceholders` 等失效的 frontend 恢复代码。
- backend `test_hitl_wire.py`/`test_hitl_middleware.py` green，frontend vitest/tsc/lint green。
- multi-action wire(§2.2)·subagent 继承(§2.1)无回归。

## 11. 风险 / 注意事项
- **放宽 edit-by-index 的 backend early-return**(Task 2 Step 1): 无 redacted 的普通 edit 也会走 index 解析路径，因此需用回归测试守护，确认不影响现有非 edit/respond resume 路径(`test_hitl_wire.py` 保持现有 case)。
- **field editor 的非 scalar 值**(嵌套 object/array): 单字段 JSON 解析失败时**仅该字段**显示错误，不阻止整体 submit(保持 §3.2 的防回归意图)。
- **allowed_decisions fallback** 必须为 `[approve, reject]`(不含 edit)。若把 edit 加入 fallback，会再次暴露给不支持 edit 的工具。
- approve/reject 路径(当前正常)在本工作中不改变行为 — 通过回归测试确认。
</content>
