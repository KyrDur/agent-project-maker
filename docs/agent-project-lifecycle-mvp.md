# Agent Lifecycle MVP 交付与演示

## 当前结论

项目页面已支持创建项目、生成/检查评测集、运行评估、报告、失败分析、AI 建议审核、接受后创建 immutable Version、原冻结评测集回归、版本比较和基于证据的 Best Version。

没有新增数据库表或迁移。Builder 和 Runtime 的实现未重设计。修改了 Builder **之后**的 Project 基线编排：补充质量检查，并让失败重试追加新 Run，保留旧结果。

本地使用隔离数据库和可控模型返回完成闭环测试。真实模型脚本已准备，但当前 Windows 主机没有运行中的应用服务、Docker 或可用的 WSL 发行版；尚未进行真实模型端到端验收。模型改善不是预设结果，不能保证真实模型复现某个固定提升数值。

## 数据流与存储

```text
Create Agent（已有 Builder / 手动创建）
  → Create Project → immutable V1
  → Capability Profile → AI EvalSet → Quality Check
  → Run Evaluation（冻结用例、rubric、Judge 配置）
  → Judge → Evaluation Report → Bad Case Analysis
  → AI Optimization Proposal（pending）
      ├─ rejected：保留建议及预览，不创建版本
      └─ accepted：原子创建 V2，保存来源关系
          → Run Regression（复制 V1 Run 的冻结用例和评分计划）
          → 新 Run / Report → Compare A/B → Best Version
```

- 建议保存在 source Run 的 `comparison_json.proposals[]`，包含来源、能力画像、failure patterns、根因、改进建议、具体 patch、before/after 预览、暂缓事项、审核状态和时间。
- 生成建议只分析与预览，不创建版本，不修改线上 Agent。
- 只允许 `pending → accepted / rejected`。相同审核重复提交返回原结果；相反决策返回 409。
- 接受时在项目写锁内校验 source hash、重算并核对已审核的 diffs，再创建快照和保存审核结果。版本创建与审核使用同一事务。
- V2 保存 `parent_version_id`，以及 `snapshot_json.created_from.source_version_id / optimization_proposal_id / source_run_id`；版本列表展示来源与变更原因。
- 复用已有补丁限制：prompt、冻结 Skill 内容、已关联 tool/MCP description。缺少历史 Skill 内容的修改仅作为待办建议；没有可应用 patch 时不可接受。
- 回归 Run 复制 source Run 的 cases、EvalSet ID、eval_spec、spec_hash、roles、execution_mode；不读取后来改变的当前评分计划。新增 Run 保存 source Run / Proposal 关系。
- 生成建议和回归通过 request ID 防止网络重试重复创建；回归再次运行使用新 request ID，保留每次结果。
- 项目所有权、CSRF 和错误脱敏沿用现有路由机制。

## 质量检查与历史规则

- 页面增加质量评分、审批状态和问题提示。未批准的评测集无法点击运行。
- 编辑未冻结用例后，旧质量审批失效，必须重新检查；被拒绝的评测集可以修改后复审。
- Quality Check 使用该评测集绑定的 Capability Profile。冻结后的评测集不会因当前 Project 画像变化而重新评分。
- AI 生成提示明确要求给用例标记其实际测试的能力，供质量覆盖检查使用。
- Builder 项目的失败基线重试创建新 Run；不会重置旧 Run 的状态、完成时间或结果。正在运行的记录不会被再次抢占，超时记录沿用既有 lease 过期规则。

## Best Version 与 Dashboard

- Overall Score 复用通过率，指标使用原 Judge 聚合结果。
- 只比较同一 EvalSet、相同冻结数据与评分规则、Judge 配置/执行模式一致且完整成功的评估。
- 取最高有效分，同分保留先评估记录；版本号更新不代表更好。
- Dashboard 展示版本、评分、评估时间和“同一评测集和评分规则下的最高有效评分”理由。
- 多个评测集分别排名。报告选中某个历史 Run 时，Best 属于该报告的评测口径；项目版本列表及 Portfolio 使用最近有效评估的口径。
- 回归报告默认优先对比其真实 source Run；用户仍可选其他历史评估。差值单位为百分点，缺少可比较证据时不显示提升。
- Portfolio 与版本列表改为使用实际评估证据，不再要求先跑过旧自动优化链才能显示 Best。
- Best 仅管理项目证据，不自动发布、替换线上 Agent 或修改历史版本。

## 最终用户操作流程

1. 使用现有 Builder 创建 Agent，或使用已有 Agent；配置可用模型与用户自己的模型凭据。
2. 打开 Agent Project 页面，创建 Project 和 V1（Builder 来源项目沿用自动基线入口）。
3. 生成 Evaluation Plan，再生成 EvalSet；检查用例与业务要求，点击“执行质量检查”。
4. 质量批准后运行 Evaluation。上方报告区显示结果，下方保留完整运行历史。
5. 从报告打开运行详情，点击“分析失败用例”。
6. 点击“生成 AI 优化建议”，查看根因、受影响能力及具体 before/after。
7. 点击“拒绝建议”保留历史，或点击“接受建议并创建新版本”生成 V2。
8. 点击“运行同一评测集回归”。无需重新生成评测集；页面运行中轮询。
9. 回归完成后查看报告与 A/B 指标差值、Best 原因和时间。切回 V1 确认旧结果仍在。

## Customer Service Agent 演示

### 可重复的本地业务测试

`backend/tests/test_agent_project_proposals.py` 包含退款案例：

1. V1 两条用例，一条问候通过，一条退款遗漏身份/订单核验，得分 50%。
2. 基于实际保存的失败结果生成“增加退款核验流程”建议。
3. 先拒绝一份建议，证明不会创建版本且记录保留。
4. 再生成并接受建议，创建 V2，V1 和线上 Agent 保持原样。
5. V2 在同一冻结用例和 Judge 规则下回归到 100%，显示 +50 个百分点并成为 Best。

这些数值来自**可控测试模型**，仅用于验证业务闭环，不代表真实模型性能。

### 真实模型 UI 演示准备

在支持现有 Runtime 的 Linux/Docker 部署中，使用现有 Customer Service Agent。业务说明写清：退款前必须确认身份、订单归属和退款条件，不得在未经工具确认时声称退款已完成。

V1 可以是尚未明确这些步骤的简短客服 prompt。生成 EvalSet 后，在冻结前确认至少有一条退款用例明确检查该业务约束，并提供合成订单数据。完成质量审批后运行基线，选择**实际失败的用例**进行优化。若真实 V1 已全部通过，不制造失败或伪造分数，应改用确有遗漏的真实业务场景重新生成独立评测集。

演示时展开 Proposal diff，再接受、回归、查看差值。真实回归可能提升、持平或下降；只有证据支持时才会选 V2 为 Best。

### 真实 API 演示脚本

`backend/scripts/agent_lifecycle_demo.py` 使用已部署 HTTP API 和真实模型，无模型 mock。先在环境中设置 `APM_DEMO_EMAIL` / `APM_DEMO_PASSWORD`，凭据不会作为 CLI 参数或写入文件。

在 backend 目录执行，替换示例中的 ID：

```sh
python scripts/agent_lifecycle_demo.py baseline --base-url http://localhost:8001 --agent-id AGENT_UUID
python scripts/agent_lifecycle_demo.py propose --agent-id AGENT_UUID --run-id V1_RUN_UUID
# 先检查打印的建议；接受和拒绝是独立操作：
python scripts/agent_lifecycle_demo.py accept --agent-id AGENT_UUID --run-id V1_RUN_UUID --proposal-id PROPOSAL_UUID
python scripts/agent_lifecycle_demo.py regress --agent-id AGENT_UUID --run-id V1_RUN_UUID --proposal-id PROPOSAL_UUID
python scripts/agent_lifecycle_demo.py report --agent-id AGENT_UUID
```

使用远程环境时，每条命令都传入对应 `--base-url`。`propose` / `regress` 网络失败后可以复用打印的 `--request-id`；baseline 涉及多步生成，部分成功后优先从 UI 已有记录继续。脚本失败会报告 HTTP 状态或保存的 Run ID，不把失败当作成功演示。

## 验证

- Project 后端测试：**89 passed**，覆盖原 Phase 1–5、Evaluation Report、新审核回归闭环、权限、幂等、无效建议、质量复审及 Builder 重试历史。
- Project 前端测试：**36 passed**，覆盖原项目页面、报告、建议审核、拒绝保留、回归按钮、请求重试、质量门禁和异步刷新。
- TypeScript、全前端 ESLint、修改的 Backend 模块 Ruff / Pyright：通过。
- Node 22 preflight、i18n、Design System guard、Project JSX accessibility 检查：通过。
- Frontend Architecture guard 保留仓库既有 43 条提示，退出码为 0；未修改全仓库 baseline。
- 本次修复前已存在的后端质量审批 fixture 问题、前端韩语断言问题，已在 Project 测试范围内修复。旧“点击自动优化”的测试已改为历史回显检查，新流程由 Proposal 交互测试覆盖。
- Windows 下使用 `--noconftest` 运行隔离 Project 测试，避免加载全应用 Unix Runtime；没有增加 Runtime 兼容 shim。
- 未执行全仓库所有领域测试，也未宣称真实模型端到端已通过。

## 非 MVP 后续事项

- 持久任务队列、进程重启后的自动恢复与取消；当前复用 FastAPI BackgroundTasks。
- 大量项目历史的分页与查询优化；当前为小规模完整历史读取。
- 多用户审批/权限策略、显式发布 Best Version 与回滚线上配置。
- 更丰富的配置 patch、无法冻结的 Skill 执行与真实外部工具验证。
- 统计置信度、多次采样、成本/延迟等更复杂的优劣策略。
- 真实部署和模型账户接入后的现场验收（这是环境验收待办，并非已完成的实测）。

## 修改文件列表

下列列表包含本轮生命周期完成改动及上一轮 Report 的工作区成果；原有未提交 UI 改动在此基础上保留和接入。

- `backend/app/routers/agent_projects.py`
- `backend/app/schemas/agent_project.py`
- `backend/app/schemas/agent_project_optimization.py`
- `backend/app/schemas/agent_project_report.py`
- `backend/app/services/agent_project_evaluation.py`
- `backend/app/services/agent_project_optimization.py`
- `backend/app/services/agent_project_portfolio.py`
- `backend/app/services/agent_project_proposals.py`
- `backend/app/services/agent_project_report.py`
- `backend/app/services/agent_project_semantic.py`
- `backend/app/services/builder_project_lifecycle.py`
- `backend/scripts/agent_lifecycle_demo.py`
- `backend/tests/test_agent_project_phase2.py`
- `backend/tests/test_agent_project_phase3.py`
- `backend/tests/test_agent_project_phase4.py`
- `backend/tests/test_agent_project_proposals.py`
- `backend/tests/test_agent_project_report.py`
- `docs/agent-project-evaluation-report-mvp.md`
- `docs/agent-project-lifecycle-mvp.md`
- `frontend/messages/en.json`
- `frontend/messages/zh-CN.json`
- `frontend/src/app/agents/[agentId]/project/_components/project-comparison.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation-report.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation-report.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-optimization.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase2.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase3.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase4.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase5.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-proposals.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-proposals.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-results.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-versions.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-agent-project.ts`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-project-evaluation.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`
- `frontend/tests/mocks/handlers.ts`
