# 新窗口执行提示词：Agent Project Maker 完整修补

请直接执行这项修补任务，保留已有修改，持续完成实现、验证、文档和交付。不要再次只给修改大纲，也不要把旧测试通过当成本方案已完成。

## 一、先完整读取文件

源码仓库：`/Users/Cade/Projects/agent-project-maker`（本机实际路径大小写可能显示为 `/Users/Cade/projects/agent-project-maker`，先用 pwd/git 确认是同一个仓库）。

当前聊天工作目录 `/Users/Cade/Documents/ChatGPT/agent project maker` 不是源码根目录，请在源码仓库执行修改和检查。

必读：

1. `/Users/Cade/Projects/agent-project-maker/AGENTS.md`，以及后端/前端/目标目录适用的 AGENTS.md。
2. `/Users/Cade/Projects/agent-project-maker/docs/agent-project-quality-revision-plan-2026-10-06.md`：完整、已获用户同意的十项修补大纲和验收矩阵，是本轮范围依据。逐项读取，不只读摘要。
3. `/Users/Cade/Projects/agent-project-maker/docs/agent-project-quality-research-2026-10-06.md`：外部资料、原始实验核查、两个案例和旧材料的问题，已从本地研究产物完整保留。
4. `/Users/Cade/Projects/agent-project-maker/output/human-trial-20261006/guided-trial-observations.md`：实际 UI 操作、实验结果及体验问题。

再阅读 README、相关现有实现和测试。已有研究包含牛客面试官分享、作品集、Anthropic Agent 评测、τ-bench、Ragas 事实支持与裁判校准；参考方法和表达，不照抄别人的业绩或把社区示例阈值当行业标准。遇到新事实或需要补充依据时再查权威来源。

## 二、用户目标及不可改动的约束

目标：用户用个人 API Key 创建通用 Agent，在纯模拟环境试用；系统自动评测与分析，用户查看实际日志、确认改动，通过 V1/V2/V3 回归理解失败，取得能在面试展开讲的两个具体案例和中文 AI 产品经理作品材料。

- 模型 A：生成指令/文本 Skill、执行 Agent、生成修改方案。
- 模型 B：设计测试、20 条正式回归用例、模拟数据和预期结果。
- 模型 C：裁判、证据分析与失败分析。
- 三角色独立配置，可以主动复用同一模型或 Key；显示实际配置，角色不可用明确报错，无隐式模型替换。普通用户不依赖管理员配置。
- 用户确认需求、能力和逐轮优化方案，不手工评分，不强制抽查用例。裁判校准属于开发验收，不能重新强迫普通用户打分。
- 只保留对话构建；归纳/写作等优先指令或文本 Skill，不强行推荐工具。无工具/无 Skill Agent 也要正常工作。
- 聊天与正式实验复用模拟能力，但会话和实验数据独立；业务操作不调用真实服务、MCP 或脚本型 Skill。
- V2 基于 V1，V3 固定基于 V2，V2 退步也不自动切换到最佳版本。无证据支持改进可以结束，V3 不强制。
- 每轮人工确认和理由、差异、来源运行、候选版本均留存；使用锁/幂等，不能自动连续优化或重复生成版本。
- 最低成绩不是项目完成门槛；全部执行/裁判错误不算有效实验。没有失败时真实分析薄弱项和边界。
- 求职材料仅 AI 产品经理，不编造生产部署、真实客户、业务收益、专家标注、统计显著性或个人职责。
- 用户理由保留原文；系统生成、用户亲写/确认、Codex 演示分别注明。本次 V3 演示操作不能被写成用户本人主导。
- 不引入韩文或已删除的韩国特化服务/兼容代码。
- 本轮不新增真实业务接入、脚本执行、MCP 配置、持续自动优化、公开分享验收或生产部署。

## 三、交接时 Git 状态

2026-10-06 交接时分支为 `fix/ci-validation`，最新提交 `8f22a366`。

相关本地提交：

- `8f22a366`：已完成评测门禁和可读运行标签。
- `ed7d156e`：需求来源、结构化评分与逐项证据展示。
- `19134ac2`：模型/工具调用改为可读日志。
- `a0d6623f`：创建需求确认阻断修复、理由说明。

保存交接文档前工作树干净；此次新增的是本地大纲、研究记录和交接文件，尚未提交或推送。启动时重新核对，不丢弃或覆盖其他未提交修改，不 reset/clean 恢复“干净”。

此前 `gh` 不可用，HTTPS 推送因 GitHub 凭据不可用而受阻；关联已有 PR 为 https://github.com/KyrDur/agent-project-maker/pull/5 ，其远端状态需要重新核实。不要假定本地提交已推送或 main 已包含它们。

先核实当前分支与远端。如果另开修补分支，使用 `codex/` 前缀并从包含上述提交的当前状态出发；不从缺少本地修复的旧 main 重做。先完成代码与检查，再提交本次范围修改；凭据可用时更新正确 PR 或创建指向 main 的 PR 并附到任务。不要擅自合并、直接推 main 或强推。

## 四、已存在的实现，继续复用

遵循 Router → Service → Model，并同步 schema、前端类型和语言资源。新增存储用 Alembic，验证历史缺失字段读取，不补造旧证据。

重点文件：

- `backend/app/services/agent_project_semantic.py`：B 生成计划/用例，C 需求规则审查和评分。
- `backend/app/services/agent_project_rubric.py`：rubric_version=2 结构化判据、适用性、证据引用校验与程序聚合。
- `backend/app/services/agent_project_evaluation.py`：测试集校验、正式运行、程序检查与比较。
- `backend/app/services/agent_project_mock_tools.py`：参数查询、状态操作、故障与冻结 Skill。
- `backend/app/services/agent_project_simulation.py`：项目模拟聊天。
- `backend/app/services/agent_project_proposals.py`：方案生成、审批及回归。
- `backend/app/services/agent_project_portfolio.py` / `agent_project_materials.py` / `agent_project_portfolio_export.py`：证据投影、报告/简历/面试、脱敏和 ZIP。
- `backend/app/models/agent_project.py` / `agent_project_simulation.py` 与相应 schema/router。
- `frontend/src/app/agents/[agentId]/project/`：工作台、评测、优化、版本、比较、案例与材料。
- `project-execution-log.tsx` / `_lib/execution-log.ts`：可读模型与工具日志。

不是重写一套评测框架。先核对已实现覆盖，再按大纲补场景可执行性、任务与表达分离、裁判校准、统计、证据与贡献来源、两个案例卡和材料写法。

注意：当前真实项目冻结的是旧 rubric_version=1。已有 rubric_version=2 代码不能证明这批旧实验已使用新口径；不得静默迁移或改写旧成绩。

## 五、真实实验数据与两个关键反例

Agent：`675f8337-713e-4c9e-a319-09cde3d8de24`，名称“电商客服助手”。
Project：`54d9b133-bc27-4819-8dc8-8a6b91fb0963`。
冻结测试集：`24af4e07-b32c-56e1-b828-63c6a6de2672`，20 条，B 生成的模拟数据，不是真实客户日志。

| 版本 | 完整运行 | 任务通过/失败 | 通过率 |
|---|---|---|---|
| V1 已完成基线 | abb6332f-589b-4a09-bfdb-a1feb24ec087 | 12/8 | 60% |
| V2 | 07bf291c-1f03-4e8a-b3d8-d4a100774a73 | 11/9 | 55% |
| V3 | 0ca89a70-b569-4944-ba97-b540a0d36e55 | 13/7 | 65% |

另有 V1 首次失败运行 f07827aa-8ba6-4810-842c-e48e5529e3ce，10 通过、9 任务失败、1 执行错误；不能隐藏或代替完整基线。

V1→V2 修复 4 条、新增失败 5 条；V2→V3 修复 5 条、新增失败 3 条；V1→V3 修复 3 条、新增失败 2 条。完整运行均没有执行/裁判错误计数，但这不证明裁判没有误判或环境没有未分类缺陷。

V1/V2/V3 快照 ID 分别为：

- d695a925-bae5-48d8-9df4-da3fe2d4ca33
- 5cd1648e-ddf7-4532-8990-071a3fd69c8f
- ec761a65-1e91-4c75-87a4-959829c4cb6d

**商品咨询反例（experiment-3/case-4 与 experiment-4/case-4）：**

用户问“这款纯棉短袖 M码的材质是什么？M码大概多大？”query_product 返回 100% 棉、衣长 68cm、胸围 104cm、库存 120、价格 89 元。

V2 补写“亲肤透气”“1–3cm 测量误差”“库存充足”，旧裁判 groundedness=0。V3 删除上述补充，旧裁判 groundedness=1 并整体通过，但仍写“平铺测量”，实际返回没有该来源。要修漏检，不能把案例写成幻觉已消除。

**价保空结果反例（experiment-3/case-16 与 experiment-4/case-16）：**

用户问“你们支持价格保护吗？怎么申请？”search_faq 返回空；escalate_to_human 因缺少模拟响应报 evaluation_mock_missing，未生成工单。

V2 说“已登记转接”；V3 如实说“转接未成功、未生成工单”，但又建议“提供订单号核实”，该路径没有来源。旧裁判给予 groundedness=0.9 并整体通过，理由却承认一处无依据延伸；旧规则写明一处扣 50%。需要分别修环境缺项、评分规则执行和材料结论。可以说失败告知改善，不能说转人工成功。

旧工具评分对这两例主要检查必需/禁止工具，tool_arguments 为空，不能从满分推出参数语义全部正确。旧格式门槛也造成正确物流回答因缺共情/满意度邀请失败。

旧结果要保留，疑点另存复核记录；新规则新范围，对三个冻结快照同口径重跑。不要重新贴新名称后声称旧指标即事实支持率。

## 六、个人贡献与材料现状

用户确认需求/能力并在 V2 选择“意图—工具对照与订单号先核验”，原理由“优先修复工具”。V3 选择“可溯源表述与敏感场景结果不预判”是 Codex 完整操作演示，原理由开头明确“【Codex 操作演示记录，非用户本人撰写】”，必须保留作者区别。

当前简历有 26 条 bullet，混入所有指标、比较和决策记录；报告约 89KB，包含难读字典。部分引用被脱敏成 [redacted]，前端和 Python 舍入有 0.1 差异。

用户要求：简历像真正的 AI 产品经理项目经历；至少两个具体场景能够说出背景、本人任务、动作、判据、方法、前后数据和局限。STAR 展开在面试卡，简历压缩成背景与 3–4 条有依据经历。不能为了好看编造责任、用户理解或业务收益。

现有成果副本：

- `output/human-trial-20261006/guided-trial-v3.zip`
- `output/human-trial-20261006/guided-trial-project_report.md`
- `output/human-trial-20261006/guided-trial-resume.json`
- `output/human-trial-20261006/guided-trial-interview.json`
- ZIP 内 evidence.json 包含稳定 experiment/case 别名；完整日志可从授权页面或本地项目记录读取。

只读取所需字段，不把 Key、Cookie、加密环境配置或全部私有日志打印到聊天。旧材料缺失内容明确标记，不能补造。

## 七、本地运行线索，使用前复核

上次运行：前端 http://localhost:3100 ，后端 8111，后端没有 reload。当前页面为：

`http://localhost:3100/agents/675f8337-713e-4c9e-a319-09cde3d8de24/project`

PostgreSQL 容器 `apm-practice-validation-pg`，本机端口 55433；真人试用数据库 `apm_human_trial_20261006`。不能把这个保留证据的数据库当可清空测试库。迁移/破坏性校验另建隔离数据库。

当前用户 A/B/C 曾均配置真实 deepseek-flash，共用凭据；必须现场复核，历史配置不代表当前仍有效。Key 不需要用户发到聊天，不能输出秘密。四类固定响应链路过去验证过，真实模型完整演示目前仅电商客服达到 V3；不能写成四类真实验收完成。

运行工具：backend/.venv/bin/python；Node/pnpm 可查仓库 `.codex/runtime/bin` 与 `.codex/runtime/node/bin`。优先沿用项目既有命令，不无故升级依赖。重启服务前确认没有用户试用或评测在运行，不取消有效实验。

## 八、执行和交付要求

按完整大纲 P0→P1→P2 顺序实施，先完成测试场景/裁判/评分可信度，再生成案例与求职材料，最后整体验证 UX。建立逐项进度记录，每项区分已有、补修、验证、未完成。

验收覆盖四类项目：写作、客服、知识问答、纯对话；含无工具/无 Skill、正常和异常路径、有效替代路径、退步继续迭代、无需改进结束、两轮审批、重复请求、刷新恢复、旧数据兼容、两案例、材料引用/数字一致。

在隔离 PostgreSQL 验证 Alembic 和历史兼容；跑相关 pytest、Vitest、Playwright、类型、构建、国际化、无障碍和设计系统检查。新测试必须针对实质行为/已发现反例，不仅镜像实现。

固定响应与真实模型验收分别记录。真实运行前展示预算/额外调用量，保留运行参数与全部试验，不能挑最佳一次。配置不足时只将真实验收标为未完成，不伪装已通过。裁判校准未涵盖的领域明确限制，不声称专家级效度。

最终交付修改文件、测试记录、四类实验结果、两个实际案例、V1/V2/V3 同口径结果、简历/面试/报告/ZIP、限制与 GitHub 状态。更新 README 区分已实现与已验收。

需要缺失信息时随时用简短具体问题问我，并继续不依赖答案的工作；不要重复询问已确认约束。先完成具体可审查成果再处理必要审批，不以“方案已写”作为实施完成。
