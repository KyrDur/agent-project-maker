# 技能工作室 Phase 3 — 实测 A/B benchmark · 真实成本核算 · 按版本通过率 · 人工反馈

状态：已确认（2026-07-12）· 分支 `feature/skill-studio-phase3`（基于 origin/main 5c7a6c01）
前置：Phase 2 6-tab Studio（PR #293, `skill-studio-phase2-studio-spec.md`）

---

## 1. 背景与目标

Phase 2 按“禁止伪数据原则”将以下 4 项推迟到范围外（§1.4）。
Phase 3 将基于**实测数据**实现这些项目。

| # | 项目 | 当前状态（伪/缺失） |
|---|------|----------------------|
| 1 | skill 轴 usage/cost 数据源 | 无 — `token_usages`/`daily_spend_*` 只有 user/agent/model 轴 |
| 2 | with/without A/B benchmark | `benchmark` 列存在，但 baseline 并非实测 — deterministic runner 全部是 `passed=False` placeholder，LLM runner 使用 grader 的**估算**（"Also estimate the baseline"） |
| 3 | 真实成本核算 | `estimate_run()` 将 `estimated_cost_usd=0` 硬编码，评估 LLM call usage 未记录 |
| 4 | 按版本通过率 | 原料（`runs.skill_version`/`skill_content_hash`+`summary.pass_rate`）在累积，但没有聚合 API/UI |
| 5 | 人工反馈 UI | 无（`message_feedbacks` 仅用于 chat） |

## 2. 已确认的产品决策（2026-07-12 用户）

| # | 决策 | 内容 |
|---|------|------|
| D1 | A/B = 单例 model call 2-arm | 每个 case：with-arm 1 次 + without-arm 1 次 + grader 1 次。与现有 estimate 的 3-call/case 模型一致。完整 Agent run 超出范围（后续） |
| D2 | 人工反馈 = 两类都做 | ① 评估 run 每个 case agree/disagree+comment（验证 grader 判定）② skill 级 up/down+comment。**仅展示** — 不纳入 pass_rate/health 计算（纳入留待后续） |
| D3 | usage 归属 = 仅实测 | ① 评估 run 的实际 LLM token/cost（全部归属该 skill — 准确）② chat `execute_in_skill` 执行次数。“连接了该 skill 的对话全部 LLM cost”会因多 skill 重复计费·包含无关 turn 而失真，因此**排除** |

## 3. 数据模型（migration m70）

### 3.1 `skill_usage_events` — skill 轴 usage ledger

| 列 | 类型 | 备注 |
|------|------|------|
| id | UUID PK | |
| skill_id | FK skills CASCADE, index | |
| user_id | FK users CASCADE | |
| source_kind | String(30) | `evaluation_run` \| `chat_execution` |
| evaluation_run_id | FK skill_evaluation_runs SET NULL, nullable | 仅 eval 来源 |
| conversation_id | UUID nullable (FK conversations SET NULL) | 仅 chat 来源 |
| agent_id | UUID nullable (FK agents SET NULL) | 仅 chat 来源 |
| model_name | String(160) nullable | 仅 eval 来源 |
| tokens_in / tokens_out | Integer, default 0 | 仅 eval 来源使用实值 |
| cost_usd | Numeric(12,6) nullable | 无单价时为 NULL（不是 0 — 区分“未知”和“免费”） |
| execution_count | Integer, default 1 | chat 来源执行次数 |
| created_at | DateTime | Index `(skill_id, created_at)` |

不创建聚合表（`daily_spend_skill`）— 每个 skill 的 event volume 较低
（评估 run 粒度 + skill 执行粒度），按需聚合足够。需要时后续增加。

### 3.2 `skill_evaluation_runs.usage` JSON (nullable)

实测 rollup：`{"model_calls": n, "tokens_in": n, "tokens_out": n, "cost_usd": f|null, "measured": true}`。
历史 run 为 NULL → 前端显示“无实测”。

### 3.3 `skill_feedbacks` — skill 级人工反馈

`message_feedback.py` 模式。id, skill_id FK CASCADE, user_id FK CASCADE,
rating String(8) (`up`|`down`), comment Text nullable, created_at/updated_at,
**unique(skill_id, user_id)**.

### 3.4 `skill_evaluation_case_feedbacks` — case 级判定反馈

id, run_id FK skill_evaluation_runs CASCADE, user_id FK CASCADE,
case_index Integer, verdict String(10) (`agree`|`disagree`), comment Text nullable,
created_at/updated_at, **unique(run_id, user_id, case_index)**.

## 4. 实测 A/B benchmark（runner `llm-2`）

### 4.1 Case 执行（D1）

Case schema 保持现有 `{name, input, expected, metadata?}`。每个 case：

1. **with-arm**：模型 1 call — system：“使用该技能完成任务” + skill
   payload（复用现有 `skill_payload()`：SKILL.md + 文件摘要）+ 执行 case
   （`metadata.execute_in_skill`）时包含现有 sandbox 执行结果（`deterministic_with_skill_results`）
   。user：case input。
2. **without-arm**：模型 1 call — user：仅 case input（无 skill context）。
3. **grader**：模型 1 call — 对两个 arm 输出 + expected 评分，per-case
   返回 `{status, score, baseline_status, baseline_score, notes}` JSON。
   保持现有 `normalize_case_results` 契约 — **不是估算，而是给真实输出评分**。

- 实测每个 arm 的 wall-clock/token → benchmark 增加 `measured: true`、`token_delta`
  （with−without tokens）、`duration_delta_ms`。现有 with/without pass rate·
  score 统计（`aggregate_benchmark`）继续使用实测输入计算。
- 取消：现有 `EvalCancellationCheckpoint` — 增加 arm 粒度 checkpoint。
- 超时：应用 case 粒度 `skill_evaluation_case_timeout_seconds`（两个 arm 合计）。
- `run_config.baseline_comparison`（默认 true）为 false 时跳过 without-arm/grader baseline
  （与 estimate `uses_baseline_comparison` 联动）。
- runner_version `llm-2`，grader_prompt_version `llm-grader-2`。替换 worker 默认 evaluator。
  deterministic runner 保留用于测试/fallback。
- 执行失败（模型异常）按 case 标记 failed — run 整体 fail 保持现有契约。

### 4.2 E2E 确定性（scripted model）

在 `e2e_scripted_model.py` 中增加评估场景：
- 检测 grader system prompt（`GRADER_SYSTEM_PROMPT` 识别 marker）→ 返回有效 grader JSON
  （with=pass，without=fail → 制造正 delta）。
- 检测 arm prompt → 简短确定性回答（包含 token usage_metadata）。

## 5. 真实成本核算

### 5.1 usage 捕获

- 每个 arm/grader call 收集 LangChain response `usage_metadata`（input_tokens/output_tokens）
  → run rollup。按 runner model_name lookup `Model` 表单价（`cost_per_input_token/output`，
  按 model_name lookup（复用 `chat_service.py` 的单价查询模式）。无单价则 cost NULL。
- run 完成时：保存 `run.usage` + 记录 `skill_usage_events(source=evaluation_run)`。
- case 自动生成（`skill_evaluation_case_generator_llm`）call 超出 v1 范围（后续）。

### 5.2 estimate 真实计算

`estimate_run()`：基于 case input/expected + skill payload 大小的 token heuristic
（chars/4，明确常量）× call 数（3 or 2）× Model 单价 → `estimated_cost_usd`。
无单价时保持 0 + response `pricing_available: false` flag（前端显示“未设置单价”）。

### 5.3 chat 执行计数

在 `skill_executor.py` execute_in_skill **成功路径**记录
`skill_usage_events(source=chat_execution, execution_count=1)`。
- **非破坏性**：SpendHook 模式 — try/except 全部吞掉 + 独立 session（禁止污染 request session）。
- draft 执行（无 skill row）·eval 内部执行（fabricated descriptor）skip —
  仅 descriptor 有 skill_id 时记录。

## 6. API

| 方法 | 路径 | 响应 |
|--------|------|------|
| GET | `/api/skills/{id}/usage?days=30` | totals(tokens_in/out, cost_usd, eval_run_count, execution_count) + 每日 series + 按 source 拆分 |
| GET | `/api/skills/{id}/evaluations/version-stats` | `[{skill_version, content_hash, run_count, latest_pass_rate, avg_pass_rate, latest_benchmark_delta, last_run_at}]` 按时间顺序 |
| PUT/DELETE | `/api/skills/{id}/evaluations/{setId}/runs/{runId}/case-feedback` | body `{case_index, verdict, comment?}` — (run,user,case_index) upsert |
| GET/PUT/DELETE | `/api/skills/{id}/feedback` | 我的反馈 + `{up_count, down_count}` 聚合 |

- 全部沿用现有 ownership guard（enumeration-safe 404）+ mutation 使用 `verify_csrf`。
- `SkillEvaluationRunResponse` 增加 `usage` 字段，run detail 同时携带 case feedback（我的+聚合）。
- 禁止在 feedback/usage payload 中保存 secret·prompt 原文（§8 陷阱）。

## 7. 前端（改造评估 tab + 版本 tab badge）

| 元素 | 位置 | 实现 |
|------|------|------|
| A/B 对比图 | run detail | chart.js bar（with/without pass rate·mean score），`measured` badge，legacy run（无 measured）标“估算”。现有显示 key（duration_delta_ms/token_delta/quality_delta）与真实 key 对齐 |
| 真实成本 | run detail + estimate dialog | run.usage token·cost·call 数 / 按真实单价估算 cost + pricing_available |
| 按版本通过率趋势 | 评估 tab section | chart.js line (version-stats) |
| usage card | 评估 tab | 30 天 token/cost/执行次数，按 source 拆分 |
| case feedback | run detail case row | agree/disagree toggle + comment popover，聚合计数 |
| skill feedback | 评估 tab 顶部 card | up/down + comment，up/down 聚合 |
| revision 通过率 badge | 版本（history）tab | 匹配 version-stats 的 content_hash |

- 图表复用 `components/usage/spend-{line,bar}-chart.tsx` 模式（chart.js 4.5）。
- 新增 api/hooks/types — 遵守 query key factory，同时新增 i18n ko/en。
- design guard（`pnpm lint:design-system`）·a11y 新违规 0。

## 8. 陷阱（继承此前 session 经验）

- push 使用 `SKILL_EVALUATION_ENABLED=true git push`（pre-push hook）。
- 真实 LLM tour 会把 throwaway DB text_primary 持久化 → scripted 验证前重建 DB。
- seed skill package byte content-hash — 禁止 lint fix。
- grader prompt 中包含 skill 文件内容 — 禁止在 usage event/feedback payload 保存 prompt
  原文（只保存 token 数·cost scalar）。
- `test_worker_loop_consumes_enqueued_run` xdist 偶发 flake（单独重跑判定）。
- 前端：DataTable rowSelection 规则、useAuiState reference-stable、partial streaming
  args guard、E2E bubble scope 断言（禁止 page-wide getByText）。

## 9. E2E 证据（capture tour）

`captures/captures-skill-studio-phase3.spec.ts` (E2E_CAPTURE_TOUR=1):

1. 评估 tab 全景 — A/B 图 + usage card + skill feedback card
2. run detail — 实测 benchmark（measured badge）+ 真实成本
3. 按版本通过率趋势图
4. history（版本）tab revision 通过率 badge
5. case feedback 交互（disagree + comment）
6. skill feedback 交互（up + 聚合更新）
7. estimate dialog 按真实单价计算的预计成本

## 10. 成功标准（可验证）

1. 评估 run 完成时记录实测 `run.usage` + 写入 `skill_usage_events` event
   （无单价模型 cost 为 NULL）。
2. llm-2 run benchmark 为 `measured: true` + 实测 with/without pass rate·token_delta —
   评分对象是两个 arm 的实际执行输出，而不是 grader 估算。
3. chat execute_in_skill 成功时对应 skill 的 execution count 增加（排除 draft/eval 内部）。
4. 评估 tab 用真实数据渲染 A/B 图·按版本通过率图·usage card·skill feedback，
   history tab revision 显示通过率 badge。
5. case/skill feedback upsert 往返 + reload 后保留。
6. backend pytest(SKILL_EVALUATION_ENABLED=true)+ruff, vitest/tsc/eslint/build/
   lint:i18n/design-system、mock+live E2E、7 张 capture tour 全绿。
