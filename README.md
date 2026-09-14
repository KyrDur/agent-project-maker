<div align="center">

<img src="frontend/public/project-maker.svg" alt="Agent Project Maker" width="120">

# Agent Project Maker

**从「做出一个 Agent」到「证明它真的变好了」**

通过自然语言创建 Agent，并完成评测、Bad Case 分析、自动优化、版本回归、结果报告与作品分享。

[在线体验](https://agent.softcue.xyz) · [部署文档](docs/alibaba-2c2g-deployment.md) · [项目设置](docs/agent-project-setup.md) · [MIT License](LICENSE)

</div>

---

## 📌 项目简介

Agent Project Maker 是一个面向 **Agent 创建、评测与优化** 的开源项目。

很多 Agent Builder 解决的是：

> 怎么把一个 Agent 做出来？

Agent Project Maker 更进一步关注：

> 这个 Agent 到底好不好？  
> 哪里做得不好？  
> 优化以后真的变好了吗？  
> 哪个版本才是当前最佳版本？

因此，项目在传统 Agent Builder 的基础上增加了一套完整的 Agent 生命周期：

```text
创建 Agent
    ↓
生成不可变 V1 快照
    ↓
Eval Plan
    ↓
20-case EvalSet
    ↓
执行评测
    ↓
Bad Case 分析
    ↓
Optimize
    ↓
V2 / V3
    ↓
使用同一套测试集 Regression
    ↓
选择 Best Version
    ↓
Report / Resume / Share / Export
```

核心目标是：

> **让 Agent 的改进从「感觉更好了」，变成「有评测证据证明它更好了」。**

当前项目仍处于 **Beta / 持续开发阶段**。

---

## ✨ 核心能力

### 1. 通过对话创建 Agent

用户可以直接用自然语言描述自己想做什么。

例如：

> 我想做一个每周自动整理工作内容并生成周报的 Agent。

Conversational Builder 会逐步理解用户意图，并协助完成 Agent 的配置，包括：

- Prompt
- Model
- Tool
- Skill
- MCP
- Credential
- 运行配置

用户不需要从一大堆技术参数开始搭建。

> Builder 属于平台级能力，需要管理员先配置 System LLM 才能正常调用模型。

---

### 2. Agent Project

每个 Agent 都可以进入一个独立 Project。

Project 用来保存这个 Agent 从初始版本到最终版本的完整演进过程，包括：

- V1 / V2 / V3
- Eval Plan
- EvalSet
- Evaluation Runs
- Bad Cases
- Optimization
- Regression
- Best Version
- Report
- Resume
- Share
- Export

可以把两者理解为：

> **Agent 是执行体，Project 是它的实验记录和成长档案。**

---

### 3. Eval：结构化评测

Agent Project Maker 可以围绕一个 Project 建立固定评测集。

当前项目评测流程使用 **20 个测试 Case**，覆盖多类场景，例如：

- 正常请求
- 信息缺失
- 模糊请求
- Tool Failure
- Edge Case
- Hallucination 风险

评测结果区分两类指标。

#### Deterministic Assertions

适合可以确定性判断的结果，例如：

- 是否调用了正确 Tool
- 是否输出必需字段
- 是否违反固定规则
- 是否完成目标动作

#### LLM-as-a-Judge

适合评价难以通过规则直接判断的生成质量，例如：

- Relevance
- Accuracy
- Completeness
- Helpfulness

两类指标分别保存，避免把主观 Judge 分数伪装成确定性结果。

---

## 🧠 Bad Case Analysis

评测完成后，系统不会只给一个总分。

它会继续分析失败 Case，并尝试定位问题发生在哪一层：

```text
Case Failed
    ↓
为什么失败？
    ↓
Prompt？
Skill？
Tool Description？
任务理解？
知识不足？
    ↓
Root Cause
```

这样优化的对象不再只是模糊的“模型能力”，而是尽可能定位到 Agent 的具体配置问题。

---

## 🚀 Optimizer

Optimizer 是 Agent Project Maker 最核心的能力之一。

系统会根据 Bad Case 提出 **受约束的最小修改方案**，并生成新的不可变版本。

例如：

```text
V1
15 / 20
75%

↓ Optimize

V2
18 / 20
90%

→ Accepted
→ Best Version

↓ Optimize

V3
17 / 20
85%

→ Rejected
```

这里最重要的一点是：

> **最新版本不一定是最好版本。**

每一个 Candidate Version 都必须重新运行 **同一套冻结 EvalSet**。

因此系统真正判断的是：

```text
修改以后
到底是变好了
还是变差了
```

而不是让 AI 自己说一句“我已经帮你优化完成”。

---

## 🔁 Version & Regression

每轮优化都会生成新的不可变版本：

```text
V1 → V2 → V3
```

每个版本保留相应的：

- Agent 配置快照
- 评测结果
- Score
- Bad Cases
- 修改内容
- Regression 结果

最终根据回归结果确定：

```text
Best Version
```

而不是默认使用最新版本。

这使 Agent 的优化过程更接近真实的软件工程：

> **修改 → 测试 → Regression → 接受 / 拒绝**

Best Version 的选择也不会自动覆盖线上 Agent，避免未经确认的版本直接进入运行环境。

---

## 📊 Project Report

系统可以把整个 Agent Project 整理为项目报告。

报告基于已保存的项目证据生成，包括：

- Agent 要解决什么问题
- V1 如何设计
- EvalSet 测了什么
- 初始表现如何
- 出现了哪些 Bad Cases
- 做了哪些优化
- V2 / V3 表现如何
- 哪个版本最终胜出
- 当前仍有哪些限制

例如：

```text
V1
75%

主要问题：
- Tool selection 不稳定
- 缺少信息时直接猜测

Optimization：
- 补充工具选择规则
- 增加 missing information guard

V2
90%

Regression：
+15%

Best Version：
V2
```

因此 Report 既可以用于项目复盘，也可以作为作品集材料。

---

## 💼 Resume

系统可以根据 Project 中已有的评测证据生成不同方向的简历描述，例如：

- AI Product
- Product Manager
- Engineering

Resume Bullet 只应使用 Project 中已经存在的数据和实验结果，例如：

- Eval 数量
- Score
- Improvement
- Version
- Bad Case
- 优化结果

避免凭空生成不存在的项目指标。

---

## 🔗 Share

Project 可以生成只读分享链接，适合用于：

- 作品集
- 面试展示
- 项目 Demo
- 分享实验结果

公开页面只展示允许公开的项目成果，不应包含：

- API Key
- Credential
- 私有原始数据
- 内部敏感配置

分享链接可以被撤销。

---

## 📦 Export

Project 可以导出为 ZIP，用于：

- 项目存档
- Portfolio
- 实验记录
- 离线查看

需要注意：

> **Export ZIP 是项目成果包，不是生产部署包。**

---

# 🧩 Agent 的组成

Agent Project Maker 沿用了 natural-mold 已经成熟的 Agent 基础设施。

一个 Agent 可以简单理解为：

```text
Agent
├── Model
├── Prompt
├── Tool
├── Skill
├── MCP
└── Credential
```

### Model

Agent 使用的大语言模型，例如：

- OpenAI
- Anthropic
- OpenRouter
- OpenAI-compatible Provider

可以把 Model 理解成 Agent 的：

> **大脑**

### Tool

Agent 可以真正执行的能力，例如：

- 搜索
- 调用 API
- 获取外部数据
- 操作服务
- 读取资源

可以把 Tool 理解成：

> **手**

### Skill

Skill 描述的是：

> 遇到某一类任务时应该怎么做。

它通常是一套方法、规则和工作流程。

例如一个“研发周报 Skill”：

```text
1. 获取本周 merged PR
2. 按项目分类
3. 提取主要改动
4. 找出未解决风险
5. 按固定模板生成周报
```

因此：

> **Tool 决定能做什么，Skill 决定应该怎么做。**

### MCP

MCP 用于标准化地连接外部工具与服务。

可以把它理解为：

> **Agent 与外部能力之间的标准接口。**

### Credential

Credential 保存 Agent 调用外部服务所需要的认证信息，例如：

- API Key
- Token
- OAuth 凭证

Credential 与用户作用域隔离，并以加密形式保存。

---

# 🧠 System LLM 与用户模型

Agent Project Maker 区分两类模型调用。

### System LLM

用于平台自身能力，例如：

```text
Builder
Assistant
Image Generation
```

由平台管理员统一配置。

当前系统提供三个 System LLM Slot：

```text
text_primary
text_fallback
image
```

### User Model / BYOK

用户真正运行自己创建的 Agent 时，可以绑定自己的：

```text
Model + Credential
```

因此架构上可以实现：

```text
平台帮助用户造 Agent
→ 平台 System LLM

用户运行自己的 Agent
→ 用户自己的 BYOK
```

平台内部模型配置与用户 Agent 的模型配置彼此分离。

---

# 🏗 技术架构

```text
Browser
   │
   ▼
Next.js 16 + React 19
   │
   ▼
FastAPI
   │
   ├── Auth
   ├── Agent Builder
   ├── Agent Runtime
   ├── Agent Project
   ├── Eval
   ├── Optimizer
   ├── Report
   ├── Tools / Skills / MCP
   │
   ▼
PostgreSQL 16
   │
   ▼
LangGraph + deepagents
   │
   ▼
LLM / External Tools
```

主要技术栈：

| 层 | 技术 |
|---|---|
| Frontend | Next.js 16 / React 19 |
| UI | TailwindCSS / shadcn/ui |
| Backend | FastAPI |
| ORM | SQLAlchemy 2 |
| Migration | Alembic |
| Agent Runtime | LangGraph / deepagents |
| Database | PostgreSQL 16 |
| Language | Python 3.12 / TypeScript |
| Deployment | Docker / Docker Compose / Nginx |

---

# 🚀 本地运行

## 环境要求

建议使用：

```text
Python 3.12
Node.js 22
pnpm
uv
Docker
PostgreSQL 16
```

## 1. 启动 PostgreSQL

```bash
docker compose up postgres -d
```

## 2. 启动 Backend

```bash
cd backend

cp .env.example .env

uv sync
uv run alembic upgrade head

uv run uvicorn app.main:app \
  --reload \
  --reload-dir app \
  --port 8001
```

Backend：

```text
http://localhost:8001
```

Swagger：

```text
http://localhost:8001/docs
```

## 3. 启动 Frontend

新开一个 Terminal：

```bash
cd frontend

cp .env.example .env.local

pnpm install
pnpm dev
```

Frontend：

```text
http://localhost:3000
```

---

# ⚙️ 首次配置

启动项目以后，还需要配置模型。

## System Credential

管理员进入：

```text
/settings/system-credentials
```

添加平台使用的大模型 API Credential。

## System LLM

管理员进入：

```text
/settings/system-llm
```

为以下 Slot 选择模型：

```text
text_primary
text_fallback
image
```

如果 `text_primary` 没有配置，Conversational Builder 无法正常调用 LLM。

## 用户 Credential

普通用户可以添加自己的模型 API Key。

这些 Credential 用于用户自己的 Agent Runtime。

---

# 🐳 Docker Compose

```bash
cp backend/.env.example backend/.env

docker compose up -d
```

Backend 会在启动时执行数据库 migration。

---

# ✅ 开发检查

## Backend

```bash
cd backend

uv run ruff check .
uv run pytest
```

## Frontend

```bash
cd frontend

pnpm lint
pnpm exec tsc --noEmit
pnpm test --run
pnpm build
```

---

# 🌐 在线部署

当前项目支持：

```text
Docker Compose
+
PostgreSQL
+
FastAPI
+
Next.js
+
Nginx Reverse Proxy
```

当前测试站点：

**https://agent.softcue.xyz**

阿里云 2C2G 部署参考：

[`docs/alibaba-2c2g-deployment.md`](docs/alibaba-2c2g-deployment.md)

---

# ⚠️ 当前限制

Agent Project Maker 仍处于持续开发阶段，目前需要注意：

- Conversational Builder 依赖管理员配置 System LLM
- Eval 中的外部 Tool 默认使用 Mock 环境进行受控评测
- Mock Eval 结果不能等价于真实 Provider 的生产验证
- Optimizer 当前使用受约束的修改策略
- Historical Skill Package 不一定能够完全复现
- 部分长期任务暂未提供 durable worker 保证
- Export ZIP 用于作品展示和记录，不是直接部署包
- 多语言与部分上游遗留文案仍在持续清理

---

# 🗺 产品方向

Agent Project Maker 希望解决的并不是：

> 再做一个 Agent Builder。

我们更关心 Agent 被创建之后发生的事情：

```text
Build
↓
Evaluate
↓
Understand Failures
↓
Optimize
↓
Regression Test
↓
Version
↓
Prove Improvement
↓
Share
```

最终希望让一个 Agent 从：

> **“能跑”**

进化到：

> **“知道它为什么能跑、哪里跑不好，以及如何证明它变得更好。”**

---

# 🙏 开源致谢

Agent Project Maker 基于开源项目：

[natural-mold / Moldy](https://github.com/YooSuhwa/natural-mold)

进行开发。

本项目复用了 natural-mold 的多项基础能力，包括：

- Agent Builder
- Agent Runtime
- Authentication
- Model / Credential
- Tool
- Skill
- MCP
- Chat
- Marketplace
- Trigger
- 多用户基础设施

Agent Project Maker 在此基础上增加并重点发展：

- Agent Project
- Immutable Version
- Eval Plan
- EvalSet
- Evaluation
- Bad Case Analysis
- Optimizer
- Regression
- Best Version
- Report
- Resume
- Project Share
- Export

本仓库是 natural-mold 的衍生项目，并非上游官方版本。

原项目版权信息、贡献者 attribution 以及 MIT License 均予以保留。

---

# 📄 License

本项目遵循仓库中的 [MIT License](LICENSE)。

涉及上游 natural-mold 的代码继续保留原有版权与许可证声明。
