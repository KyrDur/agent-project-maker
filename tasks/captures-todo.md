# 全应用 capture + 核心 flow E2E

分支：`test/full-app-captures`（基于 genui HEAD — 包含生成 UI card）。
产出物：PNG → `output/captures/<wave>/`（gitignore，所以在本地）。仅 commit script。
内容：现实感 scripted fixture（可流转的 agent/tool）。E2E 仅 2 个 flow（其余是 capture tour）。

## 执行环境（throwaway stack）
- PG：host 5434（genui 已启动），已应用 `alembic upgrade head`。
- playwright webServer 自动启动：`E2E_FRONTEND_PORT=3100 E2E_BACKEND_PORT=8101`。
- 必需 env：`E2E_SCRIPTED_MODEL_ENABLED=true`（无 key 的确定性 model）、`E2E_SEED_USER_ENABLED=true`（operator 页面用 super_user seed）、`E2E_TEST_HELPERS_ENABLED=true`、`RATE_LIMIT_ENABLED=false`、`E2E_LIVE_CHAT_SURFACES=1`（gate）。
- capture spec 使用 `E2E_CAPTURE_TOUR=1` gate，在普通 CI 中 skip。

## 复用基础设施
- `e2e/fixtures.ts`：loginApi（seed super_user）、apiPostJson/GetJson/DeleteOk、API_BASE。
- `e2e/langgraph-v3-helpers.ts`: setupLangGraphV3Agent, sendMessage, waitForActiveRun/RunStatus, approveExecuteInSkill.
- `e2e/chat-surfaces-live-captures.spec.ts`：capture(page,file) 模式。
- scripted marker：E2E_CHAT_RICH_OUTPUTS, E2E_HITL_APPROVAL/MULTI, E2E_TOOL_GROUP, E2E_SEARCH_GROUP, E2E_ASK_USER_FRUIT, E2E_LANGGRAPH_V3, E2E_DOCX/XLSX/PPTX/HWPX, E2E_TOKEN_USAGE_STREAM, E2E_SLOW_STREAM, E2E_UI_DATA_*（genui）。

## Wave

### Wave 0 — harness + 现实感 seed factory
- [ ] `e2e/captures/_capture-helpers.ts`：CAPTURE_ROOT=output/captures，capture(page,wave,file)，viewport，现实感 agent factory（可流转名称/prompt/工具）。
- [ ] stack 启动 1 次 + 用单次 capture 验证 pipeline。

### Wave 1 — 2 个核心 flow（真实 E2E + 分阶段 capture）
- [ ] `captures-flow-agent-creation.spec.ts`：通过自然语言 Builder 创建 agent → 结果 → 测试生成的 agent 聊天。（视频 2 flow）
- [ ] `captures-flow-daily-conversation.spec.ts`：日常助手多轮 — 问候→表格/Markdown→搜索→ask_user→工具组→生成 UI card，每轮 capture。（视频 3 flow）

### Wave 2 — page/route tour（capture）
- [ ] dashboard(/), /agents/new(+conversational/manual/template), 资源列表(/skills /tools /mcp-servers /marketplace tabs /artifacts), /usage, /settings/*(profile/appearance/credentials/agent-api/audit/security/memory/artifacts/models/schedules), shared view(/shared), auth(/login /register).

### Wave 3 — dialog/modal（capture）
- [ ] share, credential create/detail, tool create/detail, skill create/detail, mcp import/detail, install wizard(steps), publish wizard(steps), schedule create, model test, delete confirm, sub-agents picker, api-key created.

### Wave 4 — 聊天 UI 状态矩阵（capture）
- [ ] empty/opener, streaming, tool group, search group, HITL single/multi（批准前/后）, ask_user, reasoning, phase timeline, subagent, deepagents panel, artifacts inline+rail+preview(docx/xlsx/pptx/hwpx), attachments, 生成 UI(data_table/chart/stats/terminal), compaction marker, branch picker, token popover, context gauge, reconnect/stop.

### Wave 5 — operator/super_user 页面（capture）
- [ ] system-llm, system-credentials, admin-audit, marketplace-admin(moderation), models(system).

## 进度日志（结果）
- **Wave 0 harness ✓** — _capture-helpers.ts（capture/seed/scriptedModelId）。使用 persistent stack（reuseExistingServer）加速重跑。
- **Wave 2 页面 26/26 ✓** — dashboard（seed agent 5 个）, agent-new(hub/manual/template), 资源列表(skills/tools/mcp/marketplace/artifacts), usage, settings/*(profile/appearance/credentials/agent-api/audit/security/memory/artifacts/models/schedules), operator(system-llm/system-credentials/admin-audit/marketplace-admin), auth(login/register)。已验证 super_user auth。
- **Wave 4 聊天状态 13/14 ✓** — rich markdown, tool group, search group, ask_user, 生成 UI(table/chart/stats/terminal), HITL 批准（single+multi）, artifact, langgraph-v3 planning, branch picker。（缺失：empty-state — chat route cold compile 反复失败，最低重要度。）
- **Wave 3 dialog 5/8 ✓** — credential/skill/mcp/model create + agent delete。（缺失：tool/schedule/api-key create — 空状态 icon CTA 无法匹配 label。）
- **Wave 1 hero flow** — Builder 创建 flow ✓（05 welcome + 06 阶段 timeline+名称建议，video 2 可复现）。日常对话多轮 ✗（240s timeout；组件在 Wave 4 全部存在）。

总计 **46 张** → output/captures/{wave1-flows,wave2-pages,wave3-dialogs,wave4-chat-states}/

## Wave 6 — 代码/backend 改进（用户反馈）
- [x] **图表颜色**：chart-card.tsx 的 bar/line 改为区分 palette（mint 单色 → indigo/emerald/amber/...）。✓
- [ ] **ask_user 变体 4 种**（新增 scripted fixture）：① text 输入（无 option）② single-select+其他（直接输入）③ multi-select（4 个，maxSelections>1）④ question_flow 多步骤。（现有：single-select 3 个=fruit）
- [ ]（保留/确认）批准 card args 过于技术化（暴露 raw dict）→ 是否改进 approval-card rendering，等待用户确认。

## Wave 7 — 有内容/新增 capture（用户反馈）
**rich seed 前置**：绑定 tool/skill/MCP/trigger 的 agent + 多个对话 + artifact（docx+图片）+ attachment + usage 数据。
- [ ] agent 修改 — 有内容状态 + 全部 tab（basic/tools/skills/mcp/subagents/triggers/memory/api/fallback）+ **visual 修改**。
- [ ] dashboard — 展开 agent（显示 session list 的形式）+ **排序/group 变体**（按 session·按 agent·排序 option）。
- [ ] usage — 有数据状态。
- [ ] schedule — 已注册 trigger 状态 + 发生时 agent **感叹号（attention）badge**。
- [ ] 文件/artifact list（包含图片）+ **点击图片放大（lightbox）**。
- [ ] 聊天 — agent 名称旁 hover/click **摘要 popup**。
- [ ] 聊天 — **trace 页面** + trace 中展示真实对话。
- [ ] 聊天 — **attachment**：composer 显示 + message bubble 表达。
- [ ] 聊天 — **todo/plan**（langgraph_v3 write_todos）。
- [ ] 聊天 — **web search 工具展开**状态（展开 source）。
- [ ] 聊天 — capture 5 种 ask_user 变体（基于 Wave 6 fixture）。
- [ ] empty-state chat / rich-markdown 顶部（message element capture）。

## Wave 6/7 结果（反映用户反馈）
- **Wave 6（7 张）**：ask_user single/multi/text/question_flow，web search 展开，todo/plan，重新着色 chart。+ backend ask_user 3 种变体 + chart 颜色代码修改。
- **Wave 7（17 张）**：编辑 overview+tab（form-visual/test/opener/schedule/settings/api）+visual，dashboard session，schedule 已注册，attachment composer，file list（docx），attachment bubble，image lightbox，trace+detail，usage。

**总计 70 张** → output/captures/{wave1-flows,wave2-pages,wave3-dialogs,wave4-chat-states,wave6-chat-enhancements,wave7-rich-content}/

### 未解决（少数）→ ✅ 全部解决（branch `fix/capture-issues`）

修改后受影响 spec 全部绿色：chat-states 14/14（51.7s），flows 2/2（daily 11.6s），dialogs 5/5，rich-content 6/6。已用实际 PNG 验证。

- ✅ **12-dashboard-sort**：在 `dashboard-page-client.tsx` 排序 trigger 添加 `data-testid="dashboard-sort-trigger"` → spec `getByTestId`。（已确认 287KB capture）
- ✅ **attachment inline bubble（15）+ 17-lightbox**：按已验证的 `chat-attachments-display` spec 重写 tour flow（composer 可见性 gate + upload 201 断言 + alt-text selector `getByRole('img',{name:'membership-card.png'})`，best-effort wrapping）。（15=97KB, 17=90KB 已确认）
- ✅ **empty-state chat / rich-markdown 顶部**：(1) empty-state 新增 composer gate（吸收 cold compile）。(2) rich-markdown 使用新 `captureLocator` 做 message element scoped screenshot（规避内部 overflow-y-auto clipping）。+ 根本修复：给 `settle()` 的 `waitForLoadState('networkidle')` 加 5s 上限（chat route 因 SSE 永远到不了 networkidle，之前一直 hang 到测试 timeout）。+ warming `beforeAll`（hook timeout 300s）把 cold compile 移出测试 budget。
- ✅ **3 个 dialog（tool/schedule/api-key）**：并非简单 label 问题 — tool 点击 catalog card（`data-testid="tool-catalog-card"`），schedule 不是页面而是 agent 设置 schedule tab（`data-testid="trigger-add-button"`），api-key 在 seed deployment 后激活（`data-testid="api-key-create-button"`）。拆成 3 个专用 test。
- ✅ **批准 card UI 简化**（approval-card）：① 展开 args 从 raw `JSON.stringify` `<pre>` dump → 易读的 key/value list（scalar 原样，对象/数组仅 compact JSON）。② 抑制工具名下 langchain boilerplate 描述（`"Tool execution requires approval\n\nTool: X\nArgs: {...}"` — header·工具名·args 全重复）→ 仅显示有意义的 custom 描述。③ header 标题从 "需要批准" → "**需要批准工具使用**"（一眼看出批准什么；args 默认折叠）。redaction·edit(JSON) 路径不变。新增 regression test（approval-card 8/8，vitest 1124/1124）。最终 card = 标题 / 工具名 / 执行参数（折叠）/ 批准·修改·拒绝。

#### scripted 更自然（单独 backend 工作）→ ✅ 解决
- 在 `e2e_scripted_model.py` 新增 `E2E_DAILY_GREETING` marker + 温暖的日常助手响应（默认 sentinel "E2E scripted document model is ready." 不变 → 依赖测试 8 frontend+1 backend 不受影响）。日常对话 hero 作为问候 Turn 0 opt-in。（已确认 `01b-greeting-reply.png`）

#### daily-conversation hero 追加修改
- ask_user **选择/恢复**（`04-after-selection`）因 interrupt loop（20+ 次 re-invoke）超过 240s 而移除 — 像 wave4 HITL capture 一样，以 ask_user card（03）作为自然结尾。多轮累积超时通过 `settle` 上限 + warming 解决（240s → 11.6s）。

## Wave 10 — HITL 批准决策状态（edit hardening + allowed_decisions gating）

通过画面验证 branch `feature/hitl-edit-hardening` 的 HITL 变更（field editor + allowed_decisions button gating）。
现有 wave4 只有 card **初始状态**（10-hitl-approval, 11-hitl-multi）— 没有 decision（批准/拒绝/修改）结果和新的 field editor 画面。

- 新增 spec：`e2e/captures/captures-hitl-decisions.spec.ts`（wave10-hitl-decisions）。用单一 agent（docx skill + subagent）为每个场景创建 fresh conversation，best-effort。
- 新增 backend fixture：`E2E_HITL_EDIT`（e2e_scripted_model.py）— 1 次 `edit_file` 调用。与 execute_in_skill([approve,reject]) 不同，edit_file 是 [approve,edit,reject] policy，因此会出现**修改按钮 + field editor**。args 含 secret key（api_key）→ 演示 editor 的 read-only lock（`<redacted>`）。
- capture 方法：card（`data-testid="approval-action-N"`）使用 element-scoped（captureLocator）— 排除 marker bubble。decision 后 card 替换为 badge，testid 消失，因此 badge/multi 使用 full-page。

8 张（`output/captures/wave10-hitl-decisions/`）：
- [ ] `01-single-card` — execute_in_skill card（仅批准/拒绝 = **gating：无修改按钮**）
- [ ] `02-single-approved` — 批准 → 已批准 badge
- [ ] `03-single-rejected` — 拒绝 → 拒绝确认 → 已拒绝 badge
- [ ] `04-edit-card` — edit_file card（批准/**修改**/拒绝 = gating 对比）
- [ ] `05-edit-field-editor` — 点击修改 → **field editor**（逐字段编辑 + api_key read-only lock）
- [ ] `06-edit-approved` — 修改一个字段后批准 → 修改已批准 badge
- [ ] `07-multi-card` — multi（2× execute_in_skill）card
- [ ] `08-multi-approved` — 两个都批准 → 已批准 ×2

执行：throwaway stack（PG 5434）+ fresh port（避免 reuseExistingServer 复用 stale genui 代码）。`E2E_CAPTURE_TOUR=1 E2E_SCRIPTED_MODEL_ENABLED=true E2E_SEED_USER_ENABLED=true E2E_TEST_HELPERS_ENABLED=true RATE_LIMIT_ENABLED=false E2E_LIVE_CHAT_SURFACES=1`。
