# Agent Eval

2026-10-09 上线版源码，对应 [test.softcue.xyz](https://www.test.softcue.xyz/)。这是独立的 **Vue 3 + Vite / Python 3.12 + FastAPI** 应用，与仓库根目录的 Next.js / PostgreSQL 工程分别运行。

当前提供一个电商客服 RAG 场景：用户配置模型 → 准备知识库 → 聊天试用 → 建立评测题 → Baseline → 修改一个变量 → Retest → Compare → 导出证据和项目材料。

## 能力与边界

- 内置八题演示；用户也可以添加、编辑或让 AI 生成模拟知识库。AI 草稿须经用户审核后发布，不代表真实商家政策。
- 在选定知识版本上聊天，保存检索证据；聊天记录可转为待审核的评测题。AI 可根据知识库生成题目并引用原文，题目审核后进入评测。
- 每次运行冻结题目、知识、索引和模型配置。支持 Top K、Query Rewrite、Rerank 或知识更新的受控比较；检索与最终回答的结果分别记录。
- 默认使用本地 Chroma / ONNX `all-MiniLM-L6-v2` 语义 Embedding（384 维、CPU）；保留词汇检索作为明确可选的对照，不在模型失败时静默切换。
- Judge 可独立配置提供商、模型和 API Key；存在人工复核入口。LLM 判定仍可能有误，不能代替人工验证其可靠性。
- AI 可解释原始检索轨迹和比较证据，区分观察事实与推测。解释草稿不会改写原始结果。
- 可导出基于实际证据的项目、简历与面试材料草稿，需要用户确认个人贡献与结论；不推断真实业务收益。
- 一次历史实测为 8 题、4 改善、2 退步、2 持平，仅代表该次实验。私人实验记录不随源码发布。
- Agent 单题 Baseline 已实测；完整 Skill 修改闭环未验证，不作为已完成能力宣传。

## 目录

```text
agent-eval/
  EchoMind/                 Python 后端、测试、Skill 模板及公开演示资料
    experiments/app.py      当前产品的 ASGI 入口
    experiments/            知识、聊天、评测、比较、AI 助手和材料模块
    evaluation/             Agent 执行结果、规则及 Judge
    tests/                  合成数据测试和可选历史记录回归
  EchoMindFrontend/         Vue 前端、Node 单元测试、浏览器测试定义
    src/pages/              设置、知识库、聊天、题目、评测、比较与材料页
  requirements-runtime.txt  独立产品的运行依赖
  Dockerfile                独立后端镜像；构建时预加载公开 Embedding 模型
```

保留 `EchoMind` / `EchoMindFrontend` 文件夹名和 `ECHOMIND_*` 环境变量，兼容已有导入与部署；产品界面名称为 Agent Eval。各目录中的 `LEGACY_README.md`、旧 API / Memory / 监控模块是历史资料，**不是当前入口或上线范围的说明**。

## 本地运行

需要 Python 3.12、Node.js 22 和 pnpm 10。以下命令从仓库根目录开始执行。

终端一：

```sh
cd agent-eval/EchoMind
python3.12 -m venv .venv
.venv/bin/python -m pip install -r ../requirements-runtime.txt
# 第一次运行须联网下载公开模型，之后索引使用本机缓存。
.venv/bin/python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2(preferred_providers=['CPUExecutionProvider'])(['model initialization'])"
.venv/bin/python -m uvicorn experiments.app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

终端二：

```sh
cd agent-eval/EchoMindFrontend
pnpm install --frozen-lockfile
pnpm dev
```

打开 `http://127.0.0.1:5173`，在设置页输入自己的模型配置和 API Key。前端 `/api` 请求经 Vite 代理到 `127.0.0.1:8000`；可用 `ECHOMIND_BACKEND_URL` 修改代理目标。请勿在命令、配置文件或提交记录里填写真实 Key。

默认模式只供本机单用户开发，数据写入 `EchoMind/data/experiments/`（Git 已排除）。API Key 在后端进程内存中保存，不写入实验 JSON；重启后需要重新配置。请保持单 worker，避免不同进程间的凭据状态不一致。

## 公网匿名工作区部署

公开部署必须启用独立匿名工作区、HTTPS 和同源反向代理，不能直接公开默认单用户模式。

```sh
cd agent-eval
docker build -t agent-eval:20261009 .
docker volume create agent-eval-state
docker run -d --name agent-eval-backend \
  -p 127.0.0.1:8000:8000 \
  -v agent-eval-state:/state \
  -e ECHOMIND_ANONYMOUS_WORKSPACES=1 \
  -e ECHOMIND_WORKSPACE_DIR=/state/workspaces \
  -e ECHOMIND_PUBLIC_ORIGIN=https://your-domain.example \
  -e ECHOMIND_COOKIE_SECURE=1 \
  agent-eval:20261009
```

`ECHOMIND_PUBLIC_ORIGIN` 必须与真实公开站点 origin 一致。匿名工作区依赖服务端签发的 HttpOnly / Secure cookie；写请求检查 Origin，提供商只允许已列明的 HTTPS 地址。容器 `/state` 需要持久化；模型在镜像构建时下载，未作为仓库文件提交。

前端在 `EchoMindFrontend/` 执行 `pnpm build`，将 `dist/` 静态文件通过 HTTPS 站点发布；反向代理将 `/api/` 去掉前缀后转发到 `127.0.0.1:8000/`，并保留 Host、`X-Forwarded-Proto` 和请求 Origin。旧目录中的 compose 文件属于历史部署，当前独立应用请以上述入口为准。

## 验证

后端测试使用公开演示资料、合成用例和本地 HTTP 模型替身，不调用付费模型。需要已下载的 Embedding 缓存。

```sh
cd agent-eval/EchoMind
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

前端：

```sh
cd agent-eval/EchoMindFrontend
pnpm test
pnpm build
# 可选浏览器测试；此命令启动本地后端和固定响应的模型替身。
pnpm exec playwright install chromium
pnpm test:e2e
```

浏览器测试默认使用 `../EchoMind/.venv/bin/python`，可通过 `ECHOMIND_TEST_PYTHON` 指定其他解释器。证据输出到仓库 `output/e2e-captures/agent-eval/`，不会提交。

部分历史回归测试依赖私人的已封存实验与完整性清单；公开克隆默认明确跳过这些测试，其他合成回归继续执行。若持有原始资料，可以设置 `AGENT_EVAL_GOLDEN_FIXTURES`、`AGENT_EVAL_RERANK_FIXTURES`、`AGENT_EVAL_ARCHIVE_ROOT` 后执行相应测试。这些跳过项不代表已经在公开克隆中验证了真实模型质量。

本次导入保留线上 Python 运行文件的字节内容，避免改变冻结实验中的实现指纹。只调整测试资料发现方式和浏览器测试本机路径。原根工程的类型/格式规则以其技术栈为基础；此独立源码快照应以自身回归与构建结果判断。

本仓库不包含用户凭据、私有工作区、历史实验记录、模型权重、宣传片或网站截图。

## 本次源码快照验收

- 后端：357 passed / 38 skipped。37 项需要未公开的历史记录与清单，1 项要求显式开启真实模型测试。
- 前端：60 项测试通过，生产构建通过。
- 独立 Docker 镜像构建通过；断网验证匿名工作区初始化、本地语义索引和跨工作区隔离通过。
- 51 个后端运行文件与 2026-10-09 线上发布清单的 SHA-256 一致。
- 本轮未调用付费模型；这些回归不能证明 LLM Judge 的判定准确率。
