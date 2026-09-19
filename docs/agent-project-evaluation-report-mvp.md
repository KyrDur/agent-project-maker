# Evaluation Report MVP

> 本文记录 Report 阶段。后续建议审核、回归和最终验收结果见 [Agent Lifecycle MVP](agent-project-lifecycle-mvp.md)。

## 接入位置与范围

- 分支：`codex/agent-project-release`。
- `AgentProjectVersion.snapshot_json` / `config_hash` 已保存不可变版本；模型的更新监听器拒绝更新版本。
- `AgentProjectEvalRun` 已关联版本、评测集，并保存冻结用例、数据哈希、评分计划、逐条 Judge 结果、指标、通过率和完成时间。
- Judge 的 `metric_scores` 包含 `score / passed / reason / method`；运行保存聚合分数和已评分用例数量。
- Bad Case 分析保存在 `bad_cases_json`，分组优化建议保存在 `comparison_json.analysis.groups`。
- 前端已有版本、Evaluation、配置比较和 Portfolio 组件。本次在项目页增加独立报告区，复用已有运行详情及优化入口。

无需新表或数据库迁移。Evaluation Report 是历史 Run 的只读视图；读取报告不调用 LLM、不保存新结果、不修改版本或冻结用例。

## 数据流

```text
Agent Project → immutable Version
  → EvalSet Quality Judge 批准
  → Run Evaluation：冻结用例、数据哈希、评分计划
  → Snapshot Execution → deterministic / semantic Judge
  → Run.results_json + metrics_json + pass_rate + completed_at
  → GET /api/agents/{agent_id}/project/evaluation-reports
  → Evaluation Report → 历史选择 / Version Compare / Best Version

已有 Bad Case Analyze → bad_cases_json + analysis.groups
  → 报告展示失败原因和已有建议
  → 已有 Optimization / 创建新 Version
  → 使用同一冻结评测集再评估 → 新报告 → 比较
```

每次真实的新评估保存独立 Run。报告按运行创建顺序展示全部终态历史，时间使用完成时间；中途终止的记录回退到创建时间。原运行历史接口同步解除 100 条限制，保证报告中的运行详情链接可访问。

## 评分与 Best 规则

- **Overall Score = 已有 pass_rate**，显示为百分比，并在 UI 说明口径，不另造加权算法。
- Metrics 复用对应运行的 Judge 聚合分数，不从其他运行补齐。
- 运行出错、未完整完成或没有有效分数时显示“暂无有效评分”，不参与 Best。
- Best 按相同冻结数据、评分规则、Judge 配置和执行模式分组，取历史最高分；同分保留先评估的记录。用户切换报告时，展示该报告口径下的 Best。
- 比较可以选择任意两个不同版本的历史评估。相同口径且分数有效时显示 `B - A`，以**百分点**表示；例如 50% → 100% 是 +50 个百分点。主要指标同样显示差值。不同口径仅并列显示，不宣称改进。
- Best 为只读标记，不改变 immutable Version，也不会部署或覆盖线上 Agent 配置。原 Optimization 的接受/拒绝策略和 Portfolio 证据保持原有语义。
- Bad Case 优先展示已有分析的 root cause；未分析时展示失败 Judge 原因、失败断言及执行错误。建议优先取已有优化分组，没有时展示已保存的 suggested fix。

## 演示流程

1. 打开 Agent 的 Project 页面，确认已有 V1 快照。
2. 生成/选择评测集，完成质量审批，运行 V1 Evaluation。
3. 在 **Evaluation Report · 评估报告** 查看总分、通过数量、指标、失败用例和当前 Best。运行期间会轮询，结束后自动刷新。
4. 点击“打开运行详情 / 失败分析 / 优化”，展开原运行详情；使用已有 Analyze / Optimization 流程生成建议及候选版本。
5. 也可以通过已有 Agent 设置修改配置，再回项目页点击“创建版本”，生成独立 V2。
6. 对 V2 使用同一冻结评测集执行 Evaluation。
7. 在报告选择器选 V2（B），基准选择器选 V1（A），查看总分和指标变化，以及 Best 标记。
8. 切回 V1 的历史报告，确认旧分数、失败案例仍然存在。只有一个已评估版本时，页面提示评估另一个版本后再比较。

## 本次文件列表

### Backend

- `backend/app/schemas/agent_project_report.py`（新增）：Report 响应结构。
- `backend/app/services/agent_project_report.py`（新增）：历史 Run 投影、Best 分组。
- `backend/app/routers/agent_projects.py`：带项目所有权校验的报告读取接口。
- `backend/app/services/agent_project_evaluation.py`：完整运行历史，移除 100 条截断。
- `backend/tests/test_agent_project_report.py`（新增）：报告、权限、历史、Best、冻结口径及完整评估闭环测试。

### Frontend

- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation-report.tsx`（新增）：报告与评分比较 UI。
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation-report.test.tsx`（新增）：组件交互与轮询测试。
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.tsx`：接入报告区。
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation.tsx`：原运行详情增加锚点。
- `frontend/src/app/agents/[agentId]/project/_hooks/use-project-evaluation.ts`：报告查询和运行中轮询。
- `frontend/src/app/agents/[agentId]/project/_hooks/use-agent-project.ts`：报告 query key 与生命周期刷新。
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`：报告 API。
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`：报告类型。
- `frontend/messages/en.json`、`frontend/messages/zh-CN.json`：新增报告文案。
- `frontend/tests/mocks/handlers.ts`：默认空报告响应。
- 本文档。

开始工作时已有的 `project-results.tsx` 修改未动；两个语言文件中的已有改动保留。Builder、Runtime、Benchmark、数据库模型及迁移未修改。

## 验证结果

- Backend 新增报告测试：**10 passed**。
- 报告测试 + 原 Agent Project 基础测试：**18 passed**。
- Frontend 新增组件测试：**5 passed**，覆盖历史切换、对应运行的失败/建议、分数和指标差值、异口径/错误运行、空态/重试、完成后自动刷新。
- TypeScript `tsc --noEmit`：通过。
- 新增 Backend 模块 Pyright、Ruff：通过。
- 全前端 ESLint（`--quiet`，无错误）与 Project 页面直接 JSX accessibility ESLint：通过。
- i18n、Design System guard：通过；Architecture guard 为 43 条现有提示，退出码 0。
- Node 22 preflight：通过。使用本机已有 `.tooling/node22/node.exe`，未重装依赖。
- `git diff --check`：通过。

扩展 Backend 旧测试回归：44 passed、10 failed、20 errors。用 `git show HEAD:backend/app/services/agent_project_evaluation.py` 在独立测试进程加载原始模块后重跑，得到相同结果。主要阻塞是旧 fixture 未适配已存在的 EvalSet Quality Gate。本次没有绕过质量审批；新增闭环测试显式完成审批后执行。

仓库 `lint:a11y` 包装脚本在当前 Windows/pnpm 环境未能取得可靠 ESLint 输出，报 34 条 baseline 待删除；没有修改 baseline。改用仓库相同的 `eslint.a11y.config.mjs` 直接检查 Project 页面，检查通过。

闭环测试使用隔离 SQLite 和可控模型/执行返回，实际调用版本、质量审批、Run、Judge 聚合、Bad Case 分析与报告逻辑。没有进行真实模型付费调用、线上部署或生产数据库迁移；未执行浏览器端真实模型端到端验收。

## 下一阶段

1. 更新历史测试 fixture，使其显式遵循质量审批流程；统一现有前端测试的中文断言。
2. 在已配置模型的运行环境完成一次真实 V1 → Optimization → V2 Regression 演示。
3. 数据量增长后给报告和运行历史加分页，继续保证 Best 查询覆盖全部历史。
4. 有实际需求后再增加导出报告及手动发布最佳版本；保持评估与上线操作分离。
