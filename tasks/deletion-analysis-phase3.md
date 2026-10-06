# Deletion Analysis — HiTL Phase 3 Transition End

> 贝索斯（read-only）分析 + 萨提亚验证（实际行号在实现阶段重新确认）。
> 分支：`feature/hitl-phase3-transition-end`（main `be5a735`）。
> 目标：彻底移除 legacy wire format（约改 80 行，对用户无影响的 clean break）。

---

## A. Backend Legacy

### A1. `backend/app/schemas/conversation.py`
- 移除：`ResumeRequest.response` 字段 + `@deprecated` 注释
- 移除：dual-shape `_at_least_one` `model_validator`（验证两者至少存在一个）
- 保留：`Decision` 模型（4 type: approve/edit/reject/respond），`decisions` 字段
- 移除后 `ResumeRequest`：`decisions: list[Decision]` 为必填的单一字段

### A2. `backend/app/routers/conversations.py:resume_message`
- 移除：`_legacy_response_to_decisions()` 辅助函数（legacy → respond decision 转换）
- 移除：`if data.decisions is not None: ... else: legacy 转换 ...` dual 分支
- 移除：transition 日志记录
- 移除后：标准单一路径 `resume_payload = {"decisions": [...]}`

### A3. `backend/app/agent_runtime/streaming.py`
- 移除：正常分支中的 legacy chunk emit（`{interrupt_id, value}`）
- **变更**：fallback 路径（`aget_state` 失败）— legacy chunk → empty standard chunk（`{interrupt_id: "", action_requests: [], review_configs: []}`）
- 保留：标准 chunk emit（`{interrupt_id, action_requests, review_configs}`）

### A4. `backend/tests/test_hitl_phase2_wire.py` → rename `test_hitl_wire.py`
- 保留：标准场景（Decision/decisions/标准 streaming）
- 移除：`response` 字段场景（str/list/dict）
- 移除：dual-shape 共存场景（`both decisions and response`）
- 移除：422 dual 缺失验证（单一字段重新定义 422）
- **变更**：fallback 测试 — legacy emit 验证 → empty standard emit 验证
- expected-fail 测试（fallback 调用 2 次的回归）→ 自然消除（因为移除了 legacy emit）

---

## B. Frontend Legacy

### B1. `frontend/src/lib/types/index.ts`
- 移除：`LegacyInterruptPayload` 接口
- 变更：`InterruptPayload = StandardInterruptPayload`（union → 单一 alias 或直接使用）
- 保留：`StandardInterruptPayload`、`Decision`、`ResumeDecisionsRequest`

### B2. `frontend/src/lib/sse/stream-resume.ts`
- 移除：`streamResume()` 函数 + `ResumeRequest` 类型（legacy）
- 保留：`streamResumeDecisions()` + `ResumeDecisionsRequest`

### B3. `frontend/src/lib/chat/hitl-context.ts`
- 移除：`onResume(response, displayText)` 回调（legacy 适配器）
- 保留：`onResumeDecisions(decisions, displayText)` 回调

### B4. `frontend/src/lib/chat/use-chat-runtime.ts`
- 移除：`case 'interrupt'` 的 legacy 分支（`'value' in data`）
- 移除：`handledStandardInterruptIdsRef`（dedup ref）— 单一路径下不再需要
- 移除：`onResume` 回调 + `streamResume` import
- 保留：标准处理（`onStandardInterrupt`）

### B5. `frontend/messages/ko.json`
- 验证后只保留正在使用的 标签（大部分作为标准共用项保留）

### B6. **Tool UI 调用站点 迁移** ⚠️ Day 1 风险
以下组件将 `onResume` 调用 → 改为 `onResumeDecisions`：
- `frontend/src/components/.../approval-card.tsx`
- `frontend/src/components/.../image-generation-ui.tsx`
- `frontend/src/components/.../user-input-ui.tsx`
- `frontend/src/lib/.../use-approval-form.ts`（钩子）
- chat 页面（HiTLContext provider 部分）

贝索斯分析中的行号是估算 — **实现阶段必须用 grep 重新确认**。

### B7. Frontend 测试
- `stream-resume.test.ts`（6 项）：移除 legacy 2 项，保留标准 4 项
- `use-chat-runtime-hitl.test.tsx`（9 项）：整理 legacy/fallback 场景，保留标准场景

---

## C. 保留区域（禁止修改）
- `backend/app/agent_runtime/middleware_registry.py` (Phase 1)
- `backend/app/agent_runtime/executor.py:_prepare_agent`（Phase 1，阻断 触发器）
- `backend/tests/test_hitl_middleware.py`（Phase 1，5 项回归 防护）
- `backend/app/agent_runtime/tools/ask_user.py`（保留到 Phase 4）
- `backend/app/agent_runtime/builder_v3/**`（保留到 Phase 5，自带 native interrupt）

---

## D. 最终验证 grep（Phase 3 完成后应为 0 项）

```bash
# Backend
rg -n "ResumeRequest.*response[^_]|_legacy_response_to_decisions" backend/app

# Frontend（用单词边界排除 *Decisions 变体）
rg -nw "streamResume" frontend/src
rg -nw "onResume" frontend/src
rg -n "handledStandardInterruptIdsRef" frontend/src
rg -n "LegacyInterruptPayload" frontend/src
```

---

## E. 风险分析（Day 1）

| 风险 | 风险度 | 应对 |
|-----|-------|-----|
| Tool UI 调用站点 迁移 遗漏 | **HIGH** | grep 全量调查 + 更新单元测试 |
| fallback empty array 处理 — frontend 检查 `'action_requests' in data` | LOW | empty array 也按 truthy 标准处理 |
| 移除 `handledStandardInterruptIdsRef` 的回归 | LOW | 单一路径 → 无需 dedup |
| 页面 useMemo HiTLContext 签名变更 | MEDIUM | 移除 onResume → 确认页面中未使用 |

---

## F. 行数估算

| 区域 | 行数 | 备注 |
|-----|------|-----|
| `conversation.py` (schema) | ~10 | 字段 + validator |
| `conversations.py` (router) | ~25 | 辅助函数 函数 + dual 分支 |
| `streaming.py` | ~15 | legacy emit + fallback 变更 |
| `types/index.ts` | ~5 | LegacyInterruptPayload |
| `stream-resume.ts` | ~15 | streamResume 函数 |
| `hitl-context.ts` | ~5 | onResume |
| `use-chat-runtime.ts` | ~25 | onResume + dedup + legacy case |
| Tool UI | 调用站点变更 | 5-10 项 |
| 测试 | 整理 -10 项 | rename + 场景整理 |
| **合计** | **约 100 行变更** | 与 HANDOFF"约 80 行"的估算相差 ±20 |
