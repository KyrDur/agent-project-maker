# Phase 5 Builder v3 Wire 统一 — M1 依赖分析报告

**作者**：Bezos（Quality/Audit DRI）<br>
**日期**：2026-05-06<br>
**分析范围**：Backend 8-phase wait node 响应格式、frontend 适配器 retire 影响、phase6 JSON.parse 回归场景

---

## 1. 各 Phase Wait Node 响应格式映射

### 1.1 Phase 2 Intent Wait — `phase2_intent_wait`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase2_intent.py:189-222`

- **interrupt 调用**：L191-196
  ```python
  answer = interrupt(
    {
      "type": "ask_user",
      "question": _ASK_QUESTION,
    }
  )
  ```

- **响应格式**：**string**（纯文本）
  - L198: `answer_text = str(answer or "").strip()`
  - 格式预期：Plain text（所选 选项 标签 或自由文本）
  - 处理：空响应 → intent_confirmed=False（L202-208），文本 → 存入 intent_dict["agent_name_ko"]（L210-222）

**结论**：**只处理 string。没有 dict 分支。**

---

### 1.2 Phase 3 Approval — `phase3_approval`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase3_tools.py:83-108`

- **interrupt 调用**：L85-91
  ```python
  response = interrupt(
    {
      "type": "approval",
      "phase": 3,
      "title": "工具推荐审批",
    }
  )
  ```

- **响应格式**：**dict** 或 **string**
  - L93: `approved, revision = parse_approval_response(response)`
  - Helper 调用 `_helpers.parse_approval_response()`

**Helper 定义**：`backend/app/agent_runtime/builder_v3/nodes/_helpers.py:103-114`
  ```python
  def parse_approval_response(response: Any) -> tuple[bool, str]:
    if isinstance(response, dict):
      approved = bool(response.get("approved"))
      revision = response.get("revision_message") or response.get("message") or ""
      return approved, revision
    if isinstance(response, str):
      return False, response
    return False, ""
  ```

**结论**：
- **dict 预期**：`{"approved": bool, "revision_message": str?}`
- **string 预期**：视为 revision_message（approved=False）
- **两者都可接受**

---

### 1.3 Phase 4 Approval — `phase4_approval`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase4_middlewares.py:84-108`

- **interrupt 调用**：L85-91（格式与 Phase 3 相同）
- **响应处理**：L93 调用相同的 `parse_approval_response()`

**结论**：与 Phase 3 相同（接受 dict | string）

---

### 1.4 Phase 5 Approval — `phase5_approval`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase5_prompt.py:78-116`

- **interrupt 调用**：L79-85
  ```python
  response = interrupt(
    {
      "type": "approval",
      "phase": 5,
      "title": "系统提示词审批",
    }
  )
  ```

- **响应处理**：L87
  ```python
  approved, revision = parse_approval_response(response)
  ```

**结论**：与 Phase 3/4 相同（接受 dict | string）

---

### 1.5 Phase 6a Choice Wait — `phase6_choice_wait`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase6_image.py:100-148`

- **interrupt 调用**：L104-115
  ```python
  response = interrupt(
    {
      "type": "image_choice",
      "phase": 6,
      "title": "是否生成智能体图片？",
      "auto_prompt": auto_prompt,
      "options": [
        {"value": "skip", "label": "跳过"},
        {"value": "generate", "label": "生成"},
      ],
    }
  )
  ```

- **响应格式**：**dict** 或 **string**
  - L119-123：当前处理
    ```python
    choice = ""
    custom_prompt = ""
    if isinstance(response, dict):
      choice = str(response.get("choice", "")).lower()
      custom_prompt = str(response.get("prompt") or response.get("auto_prompt") or "")
    elif isinstance(response, str):
      choice = response.lower()
    ```

**结论**：
- **dict 预期**：`{"choice": "skip" | "generate", "prompt": str?}`
- **string 预期**：简单 option value（"skip", "generate"）
- **JSON string 未处理**：Phase 5 后 frontend 若发送 `JSON.stringify({choice, prompt})`，string 分支会尝试 `response.lower()` → `"{"choice":"skip"}"` 无法匹配 choice（回归场景）

---

### 1.6 Phase 6b Image Approval — `phase6_image_approval`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase6_image.py:215-274`

- **interrupt 调用**：L217-223
  ```python
  response = interrupt(
    {
      "type": "image_approval",
      "phase": 6,
      "image_url": state.get("image_url"),
    }
  )
  ```

- **响应格式**：**dict** 或 **string**
  - L227-231：当前处理
    ```python
    choice = ""
    new_prompt = ""
    if isinstance(response, dict):
      choice = str(response.get("choice", "")).lower()
      new_prompt = str(response.get("prompt") or "")
    elif isinstance(response, str):
      choice = response.lower()
    ```

**结论**：与 Phase 6a 相同（接受 dict | string，未处理 JSON string）

---

### 1.7 Phase 8 Build Wait — `phase8_build_wait`

**文件**：`backend/app/agent_runtime/builder_v3/nodes/phase8_build.py:126-192`

- **interrupt 调用**：L128-135
  ```python
  response = interrupt(
    {
      "type": "approval",
      "phase": 8,
      "kind": "final",
      "draft": state.get("draft_config") or {},
    }
  )
  ```

- **响应格式**：**dict** 或 **string**
  - L139-143：直接处理（不使用 parse_approval_response）
    ```python
    approved = False
    revision = ""
    if isinstance(response, dict):
      approved = bool(response.get("approved"))
      revision = response.get("revision_message") or response.get("message") or ""
    elif isinstance(response, str):
      revision = response
    ```

**结论**：接受 dict | string（逻辑与 parse_approval_response 相同）

---

### 1.8 Router Fallback — `router`（phase 8 请求修改时）

**文件**：`backend/app/agent_runtime/builder_v3/nodes/router.py:64-110`

- **interrupt 调用**（fallback）：L78-90
  ```python
  answer = interrupt(
    {
      "type": "ask_user",
      "question": "想修改哪个阶段？",
      "options": [
        "智能体名称/描述",
        "工具推荐",
        "中间件推荐",
        "系统提示词",
        "智能体图片",
      ],
    }
  )
  ```

- **响应格式**：**string**（选择 option 或自由文本）
  - L92: `text = str(answer or "").lower()`

**结论**：**只处理 string**

---

## 2. 标准 Decision → Builder Native Shape 转换表

| Decision type | 映射结果 | 依据（目标 节点） | 代码行 |
|---|---|---|---|
| `approve` | `{"approved": True}` | phase3/4/5/8 approval: `response.get("approved")` → bool(True) | phase5_prompt.py:87, phase8_build.py:140 |
| `reject` (with message) | `{"approved": False, "revision_message": message}` | parse_approval_response: `response.get("revision_message")` | _helpers.py:110 |
| `reject` (no message) | `{"approved": False, "revision_message": ""}` | 与 parse_approval_response 的处理一致 | _helpers.py:110 |
| `respond` | `message` (string) | phase2_intent_wait 直接使用 `str(answer or "")` | phase2_intent.py:198 |
| `edit` | `{"approved": True}` | builder 不使用 edit args → 与 approve 同样处理 | phase5_prompt.py:87 |
| **空数组** | `None` | 调用处（router）得到 None → fallback 选择 phase | router.py:66 |

**验证完成**：已确认所有映射都兼容 backend wait node 代码。

---

## 3. Phase 6 Image Choice/Approval JSON.parse Fallback — 回归场景

### 3.1 当前问题

**情况**：Phase 5 完成后 frontend 统一为标准 `Decision[]`。image_choice/approval 预期 dict 响应：

```typescript
// frontend（Phase 5 后）
const response = {
  choice: 'skip',
  prompt: 'auto_prompt...'
}
await streamBuilderResume(sessionId, response, ...)  // 转换为 Decision[] 前
```

但当前 `decisionToBuilderResponse()`（frontend/src/lib/chat/builder-resume-adapter.ts:12-18）：
```typescript
export function decisionToBuilderResponse(decisions: Decision[]): unknown {
  const first = decisions[0]
  if (first?.type === 'respond' || first?.type === 'reject') {
    return first.message ?? ''
  }
  return first  // approve/edit → 原样返回（不是 dict）
}
```

**image_choice/approval 响应结构**：
```typescript
// frontend 中决定的格式
const decisions: Decision[] = [
  {
    type: 'respond',  // 或 'approve'?
    message?: '...'   // 或独立字段?
  }
]
```

**backend 接收格式**（streamBuilderResume 调用）：
```python
# stream-builder-resume.ts:19-28
POST /api/builder/{id}/messages/resume
{
  "decisions": [...],  # Phase 5 后：标准 Decision[]
  "display_text": "...",
  "interrupt_id": "..."
}
```

**转换后 图片 approval wait node 预期**：
```python
# phase6_image.py:119-123
if isinstance(response, dict):
  choice = str(response.get("choice", "")).lower()
  custom_prompt = str(response.get("prompt") or response.get("auto_prompt") or "")
```

### 3.2 JSON String 回归路径

**场景**：Frontend 在混合环境（Phase 4~5 过渡中）发送 JSON string：

```typescript
// builder-resume.ts (frontend)
const choices = { choice: 'skip', prompt: 'custom...' }
await streamBuilderResume(sessionId, JSON.stringify(choices), ...)
// 或 decisions_to_builder_response 仍返回旧格式
```

**backend 接收**：
```python
# builder.py:186-204
response: str = '{"choice":"skip","prompt":"custom..."}'
await run_v3_resume_stream(
  session_id=session_id,
  user_id=session.user_id,
  response=response,  # JSON string!
  ...
)
```

**phase6_choice_wait 处理**（当前 错误）：
```python
# phase6_image.py:122-123
elif isinstance(response, str):
  choice = response.lower()  # "{"choice":"skip"...}" 原样
  # 匹配失败：choice not in ("skip", "generate", "跳过", ...)
```

### 3.3 JSON.parse Fallback 插入位置

**位置 1**：`phase6_choice_wait`（L119-123 之前）

```python
# phase6_image.py:117-124（修改）
choice = ""
custom_prompt = ""
if isinstance(response, str):
  # 尝试解析 JSON string（Phase 5 适配器 回退）
  try:
    parsed = json.loads(response)
    if isinstance(parsed, dict):
      response = parsed  # 重新归类为 dict
  except (json.JSONDecodeError, ValueError):
    pass  # 保持普通 string 选项

if isinstance(response, dict):
  choice = str(response.get("choice", "")).lower()
  custom_prompt = str(response.get("prompt") or response.get("auto_prompt") or "")
elif isinstance(response, str):
  choice = response.lower()
```

**位置 2**：`phase6_image_approval`（L227-231 之前）

相同 JSON.parse 逻辑（or helper 抽取）。

---

## 4. Frontend 适配器 Retire 影响范围

### 4.1 删除文件

| 文件 | 行 | 删除原因 |
|---|---|---|
| `frontend/src/lib/chat/builder-resume-adapter.ts` | 全部（18 行） | 责任转移 → backend router helper |
| `frontend/src/lib/chat/__tests__/builder-resume-adapter.test.ts` | 全部（55 行） | 测试 retire（8 个防护项） |

### 4.2 修改文件

#### 4.2.1 `frontend/src/lib/chat/use-chat-runtime.ts`

**L19**：移除 import
```typescript
// 删除
import { decisionToBuilderResponse } from './builder-resume-adapter'
```

**L612-618**：移除 适配器 调用 + 直接传 decisions

```typescript
// 既有（L612-618）
if (resumeFn) {
  const response = decisionToBuilderResponse(decisions)
  await _runStream(
    (signal) => resumeFn(response, signal, displayText, intrId),
    userMsg,
  )
  return
}

// 新增
if (resumeFn) {
  await _runStream(
    (signal) => resumeFn(decisions, signal, displayText, intrId),
    userMsg,
  )
  return
}
```

**L95-100 (ResumeFn 类型)**：更新签名

```typescript
// 既有
type ResumeFn = (
  response: unknown,
  signal: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
) => AsyncGenerator<SSEEvent>

// 新增
type ResumeFn = (
  decisions: Decision[],
  signal: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
) => AsyncGenerator<SSEEvent>
```

**受影响调用处**：
- L145：interface 定义中的 resumeFn? 类型 自动更新
- L612-615：onResumeDecisions 回调（修改）
- 所有 resumeFn 注入处都必须接受新签名（TypeScript compile-time check）

#### 4.2.2 `frontend/src/lib/sse/stream-builder-resume.ts`

**L12-28**：签名 + POST body 格式变更

```typescript
// 既有
export async function* streamBuilderResume(
  sessionId: string,
  response: unknown,  // <-- 变更
  signal?: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
): AsyncGenerator<SSEEvent> {
  yield* streamSSEPost<SSEEventType>(
    `/api/builder/${sessionId}/messages/resume`,
    {
      response,  // <-- 字段名变更
      display_text: displayText,
      interrupt_id: interruptId ?? null,
    },
    signal,
    'content_delta',
  ) as AsyncGenerator<SSEEvent>
}

// 新增
import type { Decision } from '@/lib/types'

export async function* streamBuilderResume(
  sessionId: string,
  decisions: Decision[],  // <-- 变更
  signal?: AbortSignal,
  displayText?: string,
  interruptId?: string | null,
): AsyncGenerator<SSEEvent> {
  yield* streamSSEPost<SSEEventType>(
    `/api/builder/${sessionId}/messages/resume`,
    {
      decisions,  // <-- 字段名变更
      display_text: displayText,
      interrupt_id: interruptId ?? null,
    },
    signal,
    'content_delta',
  ) as AsyncGenerator<SSEEvent>
}
```

**影响**：所有 streamBuilderResume 调用处都必须修正 类型。确认 Decision[] 的生成。

---

## 5. Backend 回归 防护 候选（M3 由詹森编写）

### 5.1 Backend 防护 列表

#### 5.1.1 `test_resume_accepts_standard_decisions`

**场景**：用标准 `Decision[]` 格式 POST

```python
# POST /api/builder/{id}/messages/resume
{
  "decisions": [
    {"type": "respond", "message": "用户输入"}
  ],
  "display_text": "所选 选项 标签",
  "interrupt_id": "uuid"
}
```

**预期**：
- Status 200
- Builder graph 正常推进 phase
- phase2_intent_wait 响应处理完成（intent_confirmed=True）

#### 5.1.2 `test_resume_rejects_legacy_response_field_422`

**场景**：Legacy `response` 字段（clean break）

```python
{
  "response": "用户输入",  # 旧格式
  "display_text": "...",
  "interrupt_id": "..."
}
```

**预期**：
- Status 422 (ValidationError)
- 消息：`Field required: decisions`

#### 5.1.3 `test_decisions_to_builder_response_mapping`

**Helper 单元测试**（decisions_to_builder_response）

```python
# 按各 用例 assert
assert decisions_to_builder_response([Decision(type='approve')]) == {"approved": True}
assert decisions_to_builder_response([Decision(type='reject', message='修改')]) == {
  "approved": False,
  "revision_message": "修改"
}
assert decisions_to_builder_response([Decision(type='respond', message='文本')]) == '文本'
assert decisions_to_builder_response([Decision(type='edit', edited_action={...})]) == {"approved": True}
assert decisions_to_builder_response([]) == None
```

#### 5.1.4 `test_phase6_choice_accepts_json_string`

**场景**：phase6_choice_wait 接收 JSON string 响应

```python
# Simulated interrupt response
response_str = '{"choice":"skip","prompt":"custom prompt"}'

# 调用 phase6_choice_wait
result = await phase6_choice_wait({
  "pending_tool_call_id": "tc-uuid",
  ...
})

# 预期：进入 choice='skip' 分支 → image_skipped=True, current_phase=7
assert result['image_skipped'] == True
assert result['current_phase'] == 7
```

---

### 5.2 Frontend 防护 Retire

**删除文件**：`builder-resume-adapter.test.ts`（移除 8 个 防护）

```typescript
// 将被移除的 用例
✗ respond — 返回 message 字符串
✗ respond — message 缺失时 fallback 为空 字符串
✗ reject — 返回 message 字符串
✗ reject — message 缺失时 fallback 为空 字符串
✗ approve — 直接返回 decision 对象本身
✗ edit — 返回包含 edited_action 的 decision 对象
✗ multi-action 数组 — 只使用第一个 decision
✗ 空数组 — 返回 undefined
```

---

## 6. 禁止修改区域（保留）

### 6.1 Backend

- `backend/app/agent_runtime/builder_v3/graph.py`（8-phase 状态机）
- `backend/app/agent_runtime/builder_v3/state.py` (BuilderState)
- `backend/app/agent_runtime/builder_v3/nodes/_helpers.py:parse_approval_response`（兼容 dict|str 处理）
- `backend/app/agent_runtime/builder_v3/nodes/_helpers.py:build_approval_result`（变更 0）
- `backend/app/agent_runtime/builder_v3/nodes/phase{2,3,4,5,7,8}*.py`（除 phase6 JSON.parse 外）
- `backend/app/services/builder_service.py:run_v3_resume_stream`（L385-393 保留 pending_tool_call_id stale 验证）

### 6.2 Frontend

- `frontend/src/lib/chat/decision-mappers.ts` (PR #136)
- `frontend/src/lib/chat/has-new-assistant-message.test.ts` (PR #134)
- `frontend/src/app/agents/new/conversational/page.tsx:66-80`（resumeFn 定义，只更新 类型）

---

## 7. 最终清单

### 7.1 Schema 统一

- [x] Backend `BuilderResumeRequest.decisions: list[Decision]` (clean break)
- [x] Backend Decision import：`app.schemas.conversation.Decision`（复用 Phase 3 定义）
- [x] 适配器 责任转移：frontend → backend router helper

### 7.2 响应格式兼容

| Phase | Wait Node | 响应预期 | 转换后输入 | 验证完成 |
|---|---|---|---|---|
| 2 | phase2_intent_wait | string | "用户输入" | ✓ |
| 3 | phase3_approval | dict/string | {"approved": bool, "revision_message": str} | ✓ |
| 4 | phase4_approval | dict/string | 同上 | ✓ |
| 5 | phase5_approval | dict/string | 同上 | ✓ |
| 6a | phase6_choice_wait | dict/string/**JSON string** | {"choice": "skip"|"generate", "prompt": str} | ⚠️ 需要新增 JSON.parse |
| 6b | phase6_image_approval | dict/string/**JSON string** | {"choice": "confirm"|"regenerate"|"skip", "prompt": str} | ⚠️ 需要新增 JSON.parse |
| 8 | phase8_build_wait | dict/string | {"approved": bool, "revision_message": str} | ✓ |
| router fallback | ask_user | string | "选择阶段" | ✓ |

### 7.3 适配器 Retire

- [x] 删除 `builder-resume-adapter.ts`（18 行）
- [x] 删除 `builder-resume-adapter.test.ts`（55 行，8 个 防护）
- [x] 移除 `use-chat-runtime.ts` L19 import
- [x] 移除 `use-chat-runtime.ts` L612-618 适配器 调用
- [x] 更新 `use-chat-runtime.ts` L95-100 ResumeFn 类型
- [x] 修改 `stream-builder-resume.ts` L12-28 签名 + body

### 7.4 回归 防护

- [x] Backend 4 项：test_resume_accepts_standard_decisions, test_resume_rejects_legacy_response_field_422, test_decisions_to_builder_response_mapping, test_phase6_choice_accepts_json_string
- [x] Frontend retire：删除 builder-resume-adapter.test.ts（8 个 防护 自动 retire）
- [x] Phase 6 JSON.parse：phase6_choice_wait + phase6_image_approval（新增 fallback）

---

## 8. 风险最小化分析

### 8.1 Graph 变更最小化

✓ **保留 8-phase 状态机**：phase6 JSON.parse 只在 节点 入口前做响应规范化（graph 结构变更 0）

✓ **helper 兼容性**：保持 `parse_approval_response()` 原样（dict|str 处理一致）

✓ **backward compatible fallback**：phase6 JSON string 解析仅在 ordinary string 解析失败时尝试（优先既有 dict/string 分支）

### 8.2 Frontend 类型稳定性

✓ **编译时验证**：ResumeFn 签名变更 → TypeScript 编译器自动检测所有调用处

✓ **Decision[] 标准化**：`use-chat-runtime.ts` 内 onResumeDecisions 生成的 Decision[] 全部是标准格式（无需 runtime validation）

---

## 9. ADR-012 Phase 5 完成回顾

**达成事项**：
1. 将 frontend 适配器 责任转移到 Backend helper → 移除 dual-path
2. 只接收 Standard Decision[] wire 单一格式（clean break）
3. 通过 Phase 6 image_choice/approval JSON.parse fallback 防止混合环境回归
4. Graph 变更 0（保留核心 8-phase）+ 保持 helper 兼容

**里程碑**：
- M1 依赖分析完成 ✓
- M2 ADR + helper 位置决定（pending）
- M3 Backend 实现（pending）
- M4 Frontend 实现（pending）
- M5 回归验证（pending）

---

**EOF
cat /Users/chester/dev/ref/natural-mold/tasks/phase5-dependency-analysis.md | wc -l