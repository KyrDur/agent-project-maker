# Agent Eval · 电商 Agent 工作台 Frontend

当前主品牌是 **Agent Eval**，当前唯一内置场景为 **电商 Agent**。支持 RAG 聊天、自有知识、测试与对比、项目及求职材料。下文保留各阶段实现记录；最新功能与本地验收见 [新版说明](../../../../implementation-20261009/README.md)。旧目录名、部署环境变量和持久化标识保留兼容。

Python MVP 的本地产品实验工作台。沿用仓库原有 Vue 3 / Vite，补齐入口和页面；只连接 Python `experiments.app`，不调用历史在线 Chat/RAG API。

## 启动

需要 Node >= 20.19（或 >= 22.12）与 pnpm 11；当前验证环境 Node 24.19.0 / pnpm 11.25.0。当前依赖以 `pnpm-lock.yaml` 为准；原 `package-lock.json` 是扫描时已有的历史依赖清单。未使用旧 Docker compose。

在仓库根目录启动 Python 后端：

```sh
PYTHONPATH=analysis/20261007-echomind/source/EchoMind .venv-echomind-eval/bin/python -m uvicorn experiments.app:app --host 127.0.0.1 --port 8000
```

在前端目录 `analysis/20261007-echomind/source/EchoMindFrontend`：

```sh
pnpm install --frozen-lockfile
pnpm dev
```

打开 `http://127.0.0.1:5173`。所有 API 从同源 `/api/experiments` 代理到 Python，不需要开放跨域 CORS。可用 `ECHOMIND_BACKEND_URL=http://127.0.0.1:8014 pnpm dev` 指定其他后端端口。生产构建为 `pnpm build`，本地预览为 `pnpm preview`（4173 端口，沿用代理）；正式静态部署需要为 `/api` 配置相同的反向代理。本阶段未部署云端服务。

后端 Key 仅保留在进程内存，使用单 worker。服务重启后页面会提示“模型凭据需要重新输入”，原实验记录仍保留。后端数据/Skill 目录可用 `ECHOMIND_EXPERIMENT_DIR` / `ECHOMIND_SKILL_DIR` 指定，正式修改前建议使用独立 Skill 副本。

## 工作流

1. **Setup**：Provider / Base URL / Model / API Key / Temperature / Max Tokens；高级角色覆盖、超时、调用预算和 token 参数。保存后 Key 输入清空。先测试文本，再显式探测工具能力。
2. **Define**：场景名称、产品目标、正确/不可接受行为；手动创建、复制、删除单轮/多轮 Case。预览、自然语言 must-do/must-not-do 与结构化 Hard Rule 分开。自然语言目标以原文进入 EvalSet metadata 和 Case 的 Judge 上下文。
3. **Evaluate**：真实 Baseline / Retest、PASS/FAIL/INVALID/待人工复核分别呈现、四维评分与工具证据。没有逐题进度接口时只显示“评测运行中”。Judge 失败不展示占位分。Intent 单独显示。
4. **Improve**：在 FAIL Case 中创建 Decision 草稿，AI 建议与“我的判断”分开；当前后端没有 AI 诊断生成器，显示未提供提示。用户填写并明确确认后，才允许一个 Skill 的规则正文 Before/After 修改。
5. **Compare**：后端提供的五种转移、配对完整性、机器/有效判定、人工复核和 Hard Rule 证据；可比较不等于可归因。Reduced Runtime、单次运行与服务内部版本限制可见。复核不改写旧比较，点击“生成最新比较”创建新版本。

Apply 只有真实 APPLIED 才允许 Retest；NOOP / FAILED / UNSUPPORTED 各有文案。Retest 固定 Baseline 的 EvalSet ID 和版本。Rollback 只恢复规则，保留历史 Run/Comparison。

## 状态恢复与安全

浏览器 localStorage 仅保存当前导航步骤及 session / EvalSet / Run / Decision / Change / Comparison ID；没有保存 Key、表单配置或完整实验。sessionStorage、IndexedDB 不使用。刷新后从 Python GET/list 读取真实 artifact 与有效复核结果；丢失 POST 返回时可“同步状态”从后端查回已保存 Run。历史实验列表也来自后端。

未保存的目标、Case、判断或规则编辑内容刷新后不会恢复。没有离线模式、服务工作线程、前端实验 mock、乐观 APPLIED 或浏览器评分规则。API client 对 409 / 422 / 503 与 Provider 静态错误分类，不保留/展示敏感的原始 exception。所有文本由 Vue 插值呈现，不使用 v-html。

工程字段默认收在“实验详情 / Evidence”折叠区。浏览器 Key 请求发到本机 Python 后端，浏览器无需从后端取回 Key；前后端只绑定随机 Session ID，不显示 fingerprint。

## 测试

```sh
pnpm test
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
```

`playwright.config.js` 自动启动隔离 Python 后端（8014）与 Vite（5174），本地 scripted OpenAI Chat Completions Provider（8124）通过真实 HTTP 调用；使用独立 Skill 副本和新 artifact 目录，不修改原业务 Skill。当前配置优先复用仓库根目录 `.venv-echomind-eval/bin/python`，其中需安装 Python 项目所需依赖。

可用 `ECHOMIND_TEST_CHROMIUM=/absolute/path/to/chromium` 指定已有测试浏览器。自动化 trace/video 关闭，避免把 Key 请求录进调试归档。

Golden Path 没有浏览器请求 mock，不替换 Python Runtime/Evaluator/Comparison，包含真实 NOOP → APPLIED → Retest、五类转移、Hard Rule 人工复核、刷新与 Rollback。少量罕见错误/部分结果的 UI 状态测试使用明确标注的响应夹具，夹具只存在于测试，不进入应用或 Golden Path。真实商业模型未验证。

人工试用同一 scripted Provider：在前端目录，启动以下隔离测试服务，然后用另一个终端运行指向 8014 的前端。

```sh
PYTHONPATH=../EchoMind ../../../../.venv-echomind-eval/bin/python tests/local_server.py
ECHOMIND_BACKEND_URL=http://127.0.0.1:8014 pnpm dev
```

Setup 选择 OpenAI-compatible；Base URL `http://127.0.0.1:8124/v1`；Model `phase4-scripted`；Key 任意至少 8 字符的本地测试串（非商业秘密）。Baseline 问题可填写退款申请；确认 Decision 后在账单 Skill 正文中添加 `PHASE4_CHECK_PAYMENT_BEFORE_CLAIMS`，scripted Provider 即按其公开测试脚本返回不同文本，Judge 用脚本分数验证前后链路。这只验证 UI/HTTP/实验闭环，不能作为真实 AI 优化效果。特殊输入 `PHASE4_REGRESSION_CASE` / `PHASE4_STILL_PASS` / `PHASE4_STILL_FAIL` / `PHASE4_JUDGE_FAILURE` 用于测试退化、保持与 Judge 错误边界。

## 范围

桌面优先（1366 / 1440 / 1280 已测）；移动端可查看，不承诺完整编辑体验。当前为单进程、本地、无登录或多租户的工作台。Agent Behavior 路径保持 Knowledge/RAG、query rewrite、rerank、Memory 关闭；Retrieval 路径正式启用独立冻结的 RAG 检索、可选查询改写与重排。Memory 仍未启用。未实现 Case Study、简历或面试材料，未进入 Phase 5。

仓库保留历史 Java 实现，但当前电商 Agent MVP 产品主线仅维护 Python，Java 不在本阶段及后续 MVP 范围内。

## 模型服务快捷配置（2026-10-07 补充）

Setup 默认选择 DeepSeek，并提供通义千问 / Kimi / OpenAI / Claude / 自定义选项。选择服务后预填 Base URL、模型和输出预算参数；模型名称仍可手动修改，适用于账号已开通模型或第三方兼容接口。切换预设会清空未提交 Key 和角色覆盖。Key 的内存与存储边界保持不变。

DeepSeek 官方预设：`https://api.deepseek.com/v1`、`deepseek-flash`（另提供 `deepseek-v4-pro` 建议），使用 `max_tokens`。默认显式发送 `thinking: {type: disabled}`，匹配当前普通文本/工具链；该设置保存于 ProviderSession、Run provider 配置与 inference snapshot，参与前后可比性检查。旧配置未选择此项时保持服务默认，不自动注入参数。高级设置可改回服务默认；当前工具链不支持思考内容回传，因此 DeepSeek 工具评测建议保留普通对话模式。

预设来自官方文档：[DeepSeek 模型和接口](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)、[千问兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[Kimi 快速接入](https://platform.kimi.com/blog/posts/kimi-api-quick-start-guide)、[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[Claude 模型](https://platform.claude.com/docs/en/models/overview)。预设不保证账号权限或商业服务可用，仍须运行文本连接测试与工具探针。

本次追加证据保存在 `analysis/20261007-echomind/phase4/model-presets-update/`，保留原 Phase 4 报告、XML 和 Golden Path 证据。没有部署外部模型或执行商业 API 请求。

## 批量粘贴测试题（2026-10-07 补充）

Define 默认提供“批量粘贴 JSON”，逐题填写保留为可选。支持单个对象、对象数组、JSONL 或连续完整对象；也可粘贴包在 json 代码块中的内容。点击“解析并预览”只生成可编辑草稿，不调用模型；确认目标后保存到现有 Python EvalSet API。

支持用户题中的 `case_id`、`category`、`turns`、`conditions`、`expected_tools`、`must_do`、`must_not_do`。`conditions` 映射为 `test_conditions`；缺标题时以类别/编号生成；多轮仍是一道题。保留用户 ID，缺 ID 时分配随机 ID。类别和期望工具保存在 EvalSet metadata；非空 expected_tools 作为自然语言期望进入 Judge 上下文，**不自动生成 Hard Rule**；空数组不意味着禁止调用工具。结构化规则只有用户明确提供的 executable_rules 才进入可执行规则。

可替换或追加；重复 ID、无效 JSON、空问题、未知字段和不支持规则均拒绝本次整批导入，保留当前草稿。每批 1–100 题、输入上限 1 MB。未保存的原始 JSON 和编辑仅在组件内存中，浏览器持久存储仍只存实验 ID。导入不会创建订单、模拟工具返回或启用 RAG；conditions 是评测背景。

仓库六类示例知识与旧在线 RAG/当前实验的差异见 `analysis/20261007-echomind/phase4/json-import-update/knowledge-inventory.md`。该次 JSON 导入更新仅查看知识原文，尚未启动 Chroma 或接入 RAG。后续 Phase 4B 使用独立、冻结的知识与索引，详见下方说明。追加测试证据保存在同目录；测试使用 5176/8016/8126 隔离端口，无需重启当前用户 5173/8014/8124 服务。

## Phase 4B · Retrieval / RAG（2026-10-08）

左侧“实验路径”可选择 **Agent 行为 / Skill** 或 **Retrieval / RAG 知识**。沿用同一组 Setup / Define / Evaluate / Improve / Compare。原 Skill Run 仍标识 RAG disabled，旧记录不会变成 Retrieval Run。

RAG 路径：

1. Define 上传 .txt / .md 或输入知识，分配稳定文档 ID。保存产生不可变 Knowledge version；可载入明确标注的 8 文档 / 8 题 Demo。
2. 建立独立 Persistent Chroma 索引（需要 Python requirements.txt 的 Chroma 依赖）。默认本地 `all-MiniLM-L6-v2` 语义模型、384 维、L2、cosine（Chroma 原有 ONNX 模型）；首次使用自动下载。可显式选择 `sha256-lexical-bigram-v1` 作为词汇对照，旧索引保持原模型。模型不代表中文效果提升，需实际评测。每段最多 256 Token，超限明确拒绝，不静默截断；默认切分为 200 字符、重叠 20 字符。
3. 粘贴检索 JSON，逐题填写 query 与 relevant_document_ids **或** relevant_chunk_ids；支持数组、JSONL、连续对象。未填写标签时指标 unavailable。原文不自动转换为 Hard Rule。
4. Evaluate 运行实际 Baseline，可选“同时验证最终回答”。固定候选池 Top 20，展示返回 Top K；改写/重排错误统一 INVALID，无 silent fallback。
5. 从问题选择一个变量：Top K、Query Rewrite toggle 或 Rerank toggle。模型改写预览不构成 Apply；用户填写理由并确认后，才记录并应用配置。
6. 使用相同知识 / Chunk / Embedding / Index / EvalSet / Provider 配置运行 Retest，比较逐题 Rank 和六项指标；答案另用 Phase 2 判定。

Hit@1、Hit@3、MRR 基于固定候选池的最终排序；Recall@K、Precision@K、NDCG@K 基于返回 Top K。文档标签的重复 Chunk 不额外增加 Recall/Precision/DCG。没有标签或执行 INVALID 均不进入指标分母；每项指标显示自己的有效标注分母。向量分数仅作为证据，不定义 improvement。

最终回答为固定 Prompt 的 **单一知识客服 Agent**，通过用户配置的 general 角色真实请求模型，再由配置的 judge 角色评测；不含 Router / Composer / Memory，不冒充完整在线多 Agent/RAG 链路。执行和 Judge 错误保持 INVALID；人工复核保留原判、违规与理由。

Browser localStorage 额外只保存路径类型、Knowledge / Index / Retrieval EvalSet / Run / Change / Comparison / Session ID；不存知识、Query、标签、Key 或模型配置。刷新后重读后端，重新录入的当前 ProviderSession 不会被历史 Run 的不可用 Session 覆盖。

知识变化应“基于这份知识建立新 Baseline”，保存新版本并建立新索引。不能把更新知识伪装成 Top K/Rewrite/Rerank 普通 Retest。控制条件相同但 PARTIAL 时，只比较已经完成的有效配对。Comparable 不等于 Attributable。

本地 scripted Provider 仅是 HTTP 模型响应夹具：可选 Model `phase4-rag`（Max Tokens 4096），使用公开的 Demo 改写映射；检索排名、指标与 Comparison 全部由真实 Python / Chroma 重新产生，没有硬编码改善结果。商业 DeepSeek/OpenAI 等服务需用户自行通过 Connection Test，当前证据不包含商业模型质量验证。

新增 API、Schema、指标协议、限制与测试证据见 `experiments/RETRIEVAL.md` 和 `analysis/20261007-echomind/phase4/rag/report.md`。未进入 Phase 5，未创建 Commit / Tag。


## 站内 AI 助手（2026-10-09）

知识库可描述场景生成八类完整模拟知识，Define 可基于冻结知识生成带逐字原文依据的测试草稿；Evaluate／Compare 的每题新增 AI 轨迹解读。生成结果先核对、编辑、确认再保存，AI 建议只带入修改草稿，不自动应用或改写判定。Setup 可配置独立 Judge 地址、模型与 Key，保留原实验的冻结条件。

成功生成的原草稿保存在后端，刷新恢复并重新确认；未保存的手工编辑不会恢复。知识、测试、分析都保留来源。生成模型可沿用当前回答模型或另选已连接会话。Key 仍只在后端内存保存。新主连接不继承重启后失效的独立 Judge，需重新验证再绑定。

本次验收与截图：仓库根目录 `implementation-20261009/ai-assistance/README.md`、`verification.json`。后端 394 项通过、1 项已有 opt-in 测试跳过；前端 60 项通过，生产构建通过。商业模型验收独立于本地 scripted HTTP 集成测试，不据此宣称 Judge 准确性或产品整体改善。
