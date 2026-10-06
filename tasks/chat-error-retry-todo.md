# G2 — 主聊天 error 后 Retry

分支：`feature/chat-error-retry`（worktree）

## 设计结论
- retry ≈ failed state 的 regenerate。backend 已有 checkpoint fork 重执行（`run.start`+`forkFrom`）路径 → **无需新 command**。
- failed state 以 `latest_run.status="failed"` 到达 frontend。与 canceled 相同 hydration 路径 render error bubble。
- 在 error bubble（synthetic AIMessage）复用 `ActionBarPrimitive.Reload` → assistant-ui 将前一个 user message 作为 parentId 传递 → `checkpointForReload` fork 最后一个 user checkpoint → 重执行。

## backend ✅
- [x] `_run_metadata` 暴露 `error_message`/`error_code` — **仅 failed 时**（保留 stale/canceled contract）。使用经 `public_stream_error_message` masking 的安全值。
- [x] scripted model 新增 `E2E_ERROR` marker（invoke/stream 两边 raise → run.status=failed）

## frontend ✅
- [x] 新增 `terminal-notice.ts`（status 类型 + key 常量 + `terminalNoticeFromMessage`）
- [x] `ThreadRunNotice` 新增 `failed` + `errorMessage?`
- [x] `terminalRunNoticeFromThreadState`：failed gate + 提取 error_message
- [x] conversion: `attachTerminalNoticeMetadata` → `metadata.custom.terminalNotice`
- [x] `terminalNoticeText`：failed 分支（优先 error_message，fallback `chat.page.runFailed`）
- [x] `AssistantMsg`：failed 时显示 `moldy-status-danger` error bubble + AlertTriangle + 始终可见 RetryButton（省略 hover metaRow）
- [x] `RetryButton`（复用 ActionBarPrimitive.Reload）
- [x] i18n: `chat.message.retry`, `chat.page.runFailed` (ko/en)

## 验证 ✅
- [x] typecheck / eslint / lint:i18n 通过
- [x] lint:design-system：新增代码 clean（11 个 issue 全部为 pre-existing 现有文件）
- [x] 全量 vitest 1149 通过（包含 terminal-notice unit + conversion 提升 + stream hook failed 检测新增测试）
- [x] backend ruff + 相关 pytest 通过（修复 stale contract regression 后再次通过），scripted model 增加 E2E_ERROR unit test

## capture + E2E ✅
- [x] capture spec `captures-chat-error-retry.spec.ts`（error bubble + retry button + 点击 retry 后）
- [x] E2E spec `chat-error-retry.spec.ts`（failed→error bubble→点击 retry→`/commands` POST 重执行 contract）
- [x] 使用 throwaway stack（PG 5435 / port 3310·8310）执行 E2E → **通过**（DB 中每个 conversation 有 2 个 failed run = retry 重执行证据）
- [x] 执行 capture（E2E_CAPTURE_TOUR=1）→ 生成 3 个 PNG（01 error bubble / 02 element / 03 retry 后重执行 loading+stop）
- [x] 清理（移除 throwaway PG container）

## 执行中发现并修复的根本 bug（retry no-op）
- 首次 E2E 中点击 retry 没有发送 `/commands` = no-op。原因：synthetic error bubble（AIMessage）在 `checkpointForReload` 中被误认为 "regenerate target assistant"，导致 fork target 查找以 null 结束（checkpoint-fork.ts:89）。
- 修复：在 `terminal-notice.ts` 新增 `isTerminalNoticeMessageId` → 从 fork context 的 visible message 中排除 synthetic notice → 精确 fork 到 user checkpoint。新增 regression unit test。
- 重执行验证：E2E 通过 + 03 capture 显示重执行 loading 状态。

## 最终验证 ✅
- typecheck / eslint / lint:i18n / lint:design-system（新增 clean）/ 全量 vitest **1151** / backend ruff+pytest / E2E 通过 / capture PNG 3 个

## 决策：E2E 必要性
- 核心逻辑（failed 检测、error bubble 提升、retry wiring）由 vitest 覆盖。
- E2E 验证 "真实浏览器中 failed run → render error bubble + 点击 retry 会实际触发重执行 command" 的集成 contract → **有价值，因此新增**。通过 scripted model `E2E_ERROR` marker 复现真实失败 pipeline（run seed 因没有 checkpoint 导致 retry no-op，因此不适用）。
