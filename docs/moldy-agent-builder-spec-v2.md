# Deep Agent Builder — 系统规划书 (v2)

> 通过一个自然语言请求自动创建并管理定制 AI agent 的多 agent 编排系统
>
> **v2 变更点:** 通过分析 Deep Agent Assistant prompt，补充了工具生态、系统 prompt 模板、agent 管理 workflow、subagent 结构、secret 管理、cron schedule、RAG 设置等实际实现细节。

---

## 1. 项目概览

### 1.1 系统整体结构: Builder + Assistant

该系统由两个独立 agent 构成:

| agent | 角色 | 运行时机 |
|---------|------|----------|
| **Deep Agent Builder** | 接收自然语言请求并**从零开始创建**新 agent 的 orchestrator | 创建 agent 时 |
| **Deep Agent Assistant** | **修改·管理**已创建 agent 设置的助手 | 创建 agent 后 |

Builder 创建 agent 后，用户可以通过 Assistant 添加/移除工具、改进 system prompt、变更模型、设置 schedule 等。

### 1.2 核心设计原则

- **单一职责原则 (Single Responsibility):** 每个 subagent 只负责一个明确的专业领域。
- **顺序 pipeline:** 前一阶段的输出作为下一阶段输入的链式结构。
- **基于文件的状态管理:** 将所有中间产物以 YAML/Markdown 文件写入磁盘，确保可复现性并便于 debugging。
- **隔离的 context:** subagent 之间不共享内部状态，仅传递结构化数据。
- **VERIFY before MODIFY:** 每次修改前先确认当前状态（借鉴 Assistant 原则）。
- **MINIMAL changes:** 仅修改用户明确要求的部分。

### 1.3 系统组成

| 组成 | 角色 |
|-----------|------|
| **Orchestrator (Deep Agent Builder)** | 按顺序执行完整构建 pipeline，负责调用 subagent、保存结果、报告进度 |
| **意图分析 subagent** | 精确分析用户请求并整理为 AgentCreationIntent 结构体 |
| **工具推荐 subagent** | 基于 Intent 选择 agent 所需的 Tool 列表 |
| **Middleware 推荐 subagent** | 基于 Intent + 工具信息选择 middleware（稳定性·性能·安全层） |
| **Prompt 生成 subagent** | 综合以上全部信息编写 agent 的 system prompt（Markdown） |
| **构建系统** | 读取配置文件并实例化实际的 LangGraph/Agent Framework agent |
| **Deep Agent Assistant** | 修改·管理构建完成后的 agent 设置的独立 agent |

---

## 2. 整体架构

### 2.1 Agent 创建流程 (Builder)

```
用户请求（自然语言）
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator (Deep Agent Builder)                              │
│                                                                  │
│  Phase 1: 项目初始化                                             │
│    ├─ write_project_config()   → project_config.md               │
│    ├─ create_project_folder()  → 创建项目目录                    │
│    └─ update_project_config_path() → 更新 project_config.md 路径 │
│                                                                  │
│  Phase 2: 意图分析                                               │
│    └─ 调用 subagent（description + 用户请求）                    │
│       → AgentCreationIntent (JSON)                               │
│                                                                  │
│  Phase 3: 工具推荐                                               │
│    └─ 调用 subagent (AgentCreationIntent)                        │
│       → 保存 tools.yaml                                         │
│                                                                  │
│  Phase 4: Middleware 推荐                                        │
│    └─ 调用 subagent（AgentCreationIntent + 工具列表）             │
│       → 保存 middlewares.yaml                                   │
│                                                                  │
│  Phase 5: 生成 system prompt                                     │
│    └─ 调用 subagent (Intent + Tools + Middlewares)               │
│       → 保存 system_prompt.md                                   │
│                                                                  │
│  Phase 6: 保存 agent 设置                                        │
│    └─ write_agent_config() → config.yaml                         │
│                                                                  │
│  Phase 7: 最终构建 agent                                         │
│    └─ build_final_agent() → 返回 Agent ID                       │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
实际可运行的 agent（可通过 agent_id 调用）
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  Deep Agent Assistant（创建后管理）                              │
│  - 添加·移除工具/middleware/subagent                            │
│  - 修改·改进 system prompt                                      │
│  - 修改模型设置                                                  │
│  - 管理 cron schedule                                            │
│  - 设置 RAG 文件                                                 │
│  - 检查 secret(API key)                                         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 依赖图（Builder 内部）

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──┐
                                   │
                                   ▼
                                Phase 4
                                   │
                         ┌─────────┘
                         ▼
                     Phase 5 ──→ Phase 6 ──→ Phase 7
```

Phase 3（工具推荐）和 Phase 4（middleware 推荐）都只依赖 Phase 2 的 AgentCreationIntent，但如果 Phase 4 参考工具列表，推荐会更准确，因此默认建议按 Phase 3 → Phase 4 顺序执行。

---

## 3. 实际工具·middleware·subagent 生态

> 从 Deep Agent Assistant prompt 中确认的实际资源管理体系

### 3.1 Tool 管理体系

agent 可用工具由中央目录管理。可通过 `list_available_tools` 查询，并通过 `add_tool_to_agent` / `remove_tool_from_agent` 与 agent 建立/解除连接。

**已确认的工具示例:**

| 类别 | 工具名 | 说明 |
|---------|--------|------|
| Web 搜索 | tavily_search | 通用 Web 搜索，适合最新新闻/信息 |
| 语义搜索 | exa_search | 基于概念/context 的语义搜索 |
| 韩国新闻 | naver_news | Naver 新闻搜索 API |
| 韩国博客 | naver_blog | Naver 博客搜索 API |

**内部自动工具（所有 agent 自动包含，不显示在目录中）:**

| 工具名 | 说明 |
|--------|------|
| list_agent_files | 查询上传到 agent 的永久文件列表 |
| read_agent_file | 读取文件内容（PDF→Markdown, Image→Base64） |

**工具配置结构:**
每个工具都可以有独立设置(config_override)，通过 `get_tool_config` / `update_tool_config` 管理。此外，每个工具还定义了所需 secret(API key)。

### 3.2 Middleware 管理体系

middleware 是在 agent 工具调用前后介入的层。可通过 `list_available_middlewares` 查询，通过 `add_middleware_to_agent` / `remove_middleware_from_agent` 管理。

**已确认的 middleware 示例:**

| middleware 名 | 说明 | 特别事项 |
|-----------|------|---------|
| ToolRetryMiddleware | 外部 API 调用失败时自动重试 | - |
| SummarizationMiddleware | 自动总结对话 history 以节省 token | - |
| TodoListMiddleware | 制定任务计划并跟踪进度 | **必须在 system prompt 中加入使用说明**（见下文） |

**TodoListMiddleware 必需的 prompt 说明:**

添加该 middleware 时，必须在 system prompt 中包含以下内容:

```markdown
## 任务规划与执行 (Todo List)

执行复杂任务时，必须使用 `write_todos` 工具先制定
任务计划(plans)。
制定计划后，按顺序完成各项并执行任务。

### 任务顺序
1. 分析用户请求，识别所需步骤
2. 使用 `write_todos` 工具编写任务计划
3. 按计划顺序执行各步骤
4. 每个步骤完成时更新进度
```

### 3.3 Subagent 管理体系

agent 可以调用其他 agent 作为 subagent。通过 `list_available_subagents` 查询，通过 `add_subagent_to_agent` / `remove_subagent_from_agent` 管理。

添加 subagent 时需确认:
- 角色/专业领域
- 使用的模型
- 调用条件（何时委派）
- 可访问的工具

### 3.4 Model 设置

通过 `list_available_models` 查询可用模型列表，通过 `update_model_config` 修改设置。

**可配置参数:**

| 参数 | 说明 | 默认值 |
|---------|------|--------|
| model_name | LLM 模型标识符 | anthropic:claude-sonnet-4-5 |
| temperature | 响应的创造性/随机性 |（模型默认值） |
| max_tokens | 最大响应 token 数 |（模型默认值） |
| top_p | 累积概率采样 |（模型默认值） |
| top_k | Top K token 采样 |（模型默认值） |

### 3.5 Secret 管理

agent 使用外部 API 时需要 API key。secret 管理体系:

1. `get_agent_required_secrets` → 查询 agent 所需的 secret key 列表（模型、工具、middleware 所需 key）
2. `get_user_secrets` → 查询用户已注册的 secret 列表
3. 对比并识别缺失的 key
4. 若存在缺失 key，提供申请指南后引导至 `/secrets` 页面

### 3.6 Cron Schedule 管理

可以为 agent 设置预约执行。

**Schedule 类型:**
- **重复(recurring):** 使用 cron 表达式定义（5 个字段: minute hour day-of-month month day-of-week）
- **1次(one-time):** 使用 scheduled_at 指定具体时间点

**限制事项:**
- 默认 timezone: Asia/Seoul
- 每个用户最多 20 个 schedule（所有 agent 合计）
- 1次 schedule: scheduled_at 必须是未来时间

**主要 cron 模式:**

| 模式 | 表达式 | 说明 |
|------|--------|------|
| 每小时整点 | `0 * * * *` | Every hour |
| 每天上午 9 点 | `0 9 * * *` | Daily 9 AM |
| 工作日上午 9 点 | `0 9 * * 1-5` | Weekdays 9 AM |
| 每周一 10 点 | `0 10 * * 1` | Every Monday 10 AM |
| 每月 1 日 9 点 | `0 9 1 * *` | 1st of month 9 AM |
| 每 30 分钟 | `*/30 * * * *` | Every 30 minutes |

### 3.7 Recursion Limit（递归上限）

这是限制基于 LangGraph 的 agent 执行深度的设置。

| 范围 | 推荐对象 |
|------|----------|
| 默认值 25 | 简单 Q&A |
| 25~50 | 一般工具使用 |
| 50~75 | 复杂分析 |
| 75~100 | 多阶段任务 |
| 100+ | 调用 subagent 的 agent |

注意: 数值过高时，如果发生无限循环，API 成本可能大幅增加。

---

## 4. 项目文件夹结构

### 4.1 数据库根目录结构

```
agent_database/
└── {user_id}/
    ├── project_config.md          # 用户 metadata
    ├── tmp/                       # 项目工作文件夹
    │   └── {timestamp}_{uuid}/    # 每个 agent 创建 session
    └── agents/
        └── {agent_id}/            # 构建完成的 agent
            ├── project_config.md
            ├── system_prompt.md
            ├── tools.yaml
            ├── middlewares.yaml
            └── config.yaml
```

### 4.2 各文件的 schema

**project_config.md**
```markdown
# Project Configuration

user_id="{用户唯一 ID}"
project_path="{user_id}/tmp/{timestamp}_{uuid}"
```

**tools.yaml**
```yaml
tools:
  - tool_name: "tavily_search"
    tool_path: "tools/tavily-search.yaml"
  - tool_name: "naver_news"
    tool_path: "tools/naver-news.yaml"
```

**middlewares.yaml**
```yaml
middlewares:
  - middleware_name: "ToolRetryMiddleware"
    middleware_path: "middlewares/tool-retry.yaml"
  - middleware_name: "SummarizationMiddleware"
    middleware_path: "middlewares/summarization.yaml"
```

**config.yaml**
```yaml
agent_name: "Web Search Agent"
agent_description: "接收用户的搜索 query，在互联网上搜索信息并..."
tools:
  - "tavily_search"
  - "naver_news"
  - "naver_blog"
middlewares:
  - "ToolRetryMiddleware"
  - "SummarizationMiddleware"
model_name: "anthropic:claude-sonnet-4-5"
primary_task_type: "web_search"
use_cases:
  - "信息搜索"
  - "新闻查询"
```

---

## 5. 各 Phase 详细设计 (Builder)

---

### 5.1 Phase 1: 项目初始化

#### 目的
为 agent 创建 session 准备工作空间。

#### 执行主体
由 orchestrator 直接调用工具。不使用 subagent(LLM)。

#### 分步动作

**Step 1 — write_project_config**
- 功能: 将用户 ID 写入文件系统。
- subagent 只接收 messages，因此无法访问 state.user_id。因此必须先用该工具将 user_id 写入文件。
- 输出: `{AGENT_BASE_FOLDER}/{user_id}/project_config.md`
- 初始内容: `user_id="{user_id}"`, `project_path=""`
- 限制: 必须在 create_project_folder 之前调用。

**Step 2 — create_project_folder**
- 功能: 创建 `{AGENT_BASE_FOLDER}/{user_id}/tmp/{timestamp}_{uuid}/` 文件夹。
- 使用 timestamp + UUID v4 确保唯一标识符。
- 输出: 已创建文件夹的绝对路径。

**Step 3 — update_project_config_path**
- 功能: 将 Step 1 创建的 project_config.md 中空的 project_path 更新为 Step 2 的路径。

#### Orchestrator 指引

```
1. 调用 write_project_config → 创建 project_config.md
2. 调用 create_project_folder → 创建项目文件夹
3. 调用 update_project_config_path → 同步路径
4. 在 Todo 中标记 Phase 1 完成
5. 报告 "[Phase 1 完成] 项目初始化完成"
```

---

### 5.2 Phase 2: 意图分析

#### 目的
分析用户的自然语言请求，生成 **AgentCreationIntent**。

#### 执行主体
**意图分析 subagent**

#### Subagent system prompt（设计参考）

```markdown
# 意图分析 agent — system prompt

## 角色
你是用于创建 AI agent 的意图分析专家。
接收用户的自然语言请求，分析创建 agent 所需的全部信息，
并进行系统化分析与结构化整理。

## 输出格式 (AgentCreationIntent)
必须只以以下 JSON 格式响应:

{
  "agent_name": "英文 agent 名称",
  "agent_name_ko": "韩文 agent 名称",
  "agent_description": "关于 agent 角色和功能的详细说明（3~5 句）",
  "primary_task_type": "用一句话描述 agent 的核心任务",
  "tool_preferences": "偏好的工具类型或 API 种类",
  "output_style": "结果形式（摘要、报告、列表等）",
  "response_tone": "响应的语气和风格",
  "use_cases": ["使用场景 1", "使用场景 2", "使用场景 3"],
  "constraints": ["限制条件"],
  "required_capabilities": ["必需功能 1", "必需功能 2"]
}

## 推理指南
- 仅提及"搜索 agent" → 默认包含通用 Web 搜索 + 新闻搜索
- 仅提及"翻译 agent" → 默认多语言翻译，韩语↔英语优先
- 仅提及"编码 agent" → 默认代码生成 + debugging + 说明
- 未指定语气 → 默认值"友好且 casual 的语气"
- 未指定 output_style → 默认值"简要摘要和主要要点"

## 注意事项
- 不向用户追加提问。仅根据已有信息做最佳分析。
- 即使请求模糊，也填充合理默认值并返回完整 Intent。
- 不包含 JSON 以外的其他文本。
```

#### Orchestrator 传递的 Task Description

```
用户请求了"{用户的原始请求}"。
请收集以下信息:

1. agent 名称（英文和韩文）
2. agent 说明（详细功能说明）
3. 主要任务类型 (primary_task_type)
4. agent 的主要功能
5. 用户期望功能的特征

请整理用户请求，并以 AgentCreationIntent 格式返回。
```

---

### 5.3 Phase 3: 工具推荐

#### 目的
分析 AgentCreationIntent，选择 agent 所需工具。

#### 执行主体
**工具推荐 subagent**

#### Subagent system prompt（设计参考）

```markdown
# 工具推荐 agent — system prompt

## 角色
分析 AgentCreationIntent，为 agent 推荐最合适的工具。

## 可用工具目录

（实际系统中通过 list_available_tools API 动态查询）

### Web 搜索
| 工具名 | 路径 | 说明 |
|--------|------|------|
| tavily_search | tools/tavily-search.yaml | 通用 Web 搜索。覆盖新闻、博客、普通网页 |
| exa_search | tools/exa-search.yaml | 语义搜索。适合基于概念/context 的搜索 |
| naver_news | tools/naver-news.yaml | Naver 新闻搜索。专注韩文新闻 |
| naver_blog | tools/naver-blog.yaml | Naver 博客搜索。用户体验、评论 |

### 数据处理
| 工具名 | 路径 | 说明 |
|--------|------|------|
| data_parser | tools/data-parser.yaml | 解析 JSON, XML, CSV |
| text_summarizer | tools/text-summarizer.yaml | 长文本摘要 |

### 代码执行
| 工具名 | 路径 | 说明 |
|--------|------|------|
| code_executor | tools/code-executor.yaml | 执行 Python 代码 |
| code_analyzer | tools/code-analyzer.yaml | 静态分析代码 |

### 外部 API
| 工具名 | 路径 | 说明 |
|--------|------|------|
| api_caller | tools/api-caller.yaml | 通用 REST API 调用 |

## 选择标准
1. **必要性:** 是否为执行 primary_task_type 所必需？
2. **适配性:** 是否满足 use_cases 和 required_capabilities？
3. **最小化:** 以 3~5 个为宜。禁止不必要工具。
4. **多样性:** 优先选择彼此互补的工具组合。
5. **用户偏好:** 若指定 tool_preferences，优先反映。

## 注意: 相似工具选择标准
存在多个相同功能工具时:
- tavily_search vs exa_search: 最新新闻/一般信息 → tavily，基于概念/context → exa
- 需要韩国本地化时 → 添加 naver_news, naver_blog

## 输出格式
只返回 JSON 数组:
[
  {
    "tool_name": "唯一标识符",
    "tool_path": "定义文件路径",
    "description": "一句话说明",
    "reason": "选择原因"
  }
]
```

#### Orchestrator 传递的 Task Description

```
user_id: {user_id}

请分析以下 AgentCreationIntent 并推荐所需工具:

AgentCreationIntent:
{Phase 2 返回的完整 JSON}

请分析以上信息，为该 agent 推荐所需工具。
请以包含每个工具的 tool_name 和 tool_path 的格式返回:

[
  {
    "tool_name": "工具名称",
    "tool_path": "工具文件路径",
    "description": "工具的简要说明",
    "reason": "需要该工具的原因"
  }
]
```

---

### 5.4 Phase 4: Middleware 推荐

#### 目的
选择用于 agent 稳定性·性能·安全的 middleware。

#### 执行主体
**Middleware 推荐 subagent**

#### Subagent system prompt（设计参考）

```markdown
# Middleware 推荐 agent — system prompt

## 角色
分析 AgentCreationIntent 和工具列表，推荐合适的 middleware。

## 可用 middleware 目录

### 稳定性
| middleware 名 | 路径 | 说明 |
|-----------|------|------|
| ToolRetryMiddleware | middlewares/tool-retry.yaml | 外部 API 失败时指数 backoff 重试（最多 3 次） |
| CircuitBreakerMiddleware | middlewares/circuit-breaker.yaml | 连续失败时暂时阻止工具调用 |
| FallbackMiddleware | middlewares/fallback.yaml | 主工具失败时自动切换到替代工具 |

### 性能
| middleware 名 | 路径 | 说明 |
|-----------|------|------|
| SummarizationMiddleware | middlewares/summarization.yaml | 自动总结对话 history 以节省 token |
| CacheMiddleware | middlewares/cache.yaml | 缓存相同 query 结果 |
| RateLimiterMiddleware | middlewares/rate-limiter.yaml | 限制 API 调用频率 |

### 任务管理
| middleware 名 | 路径 | 说明 |
|-----------|------|------|
| TodoListMiddleware | middlewares/todo-list.yaml | 制定任务计划并跟踪进度（提供 write_todos 工具） |

### 安全
| middleware 名 | 路径 | 说明 |
|-----------|------|------|
| InputSanitizer | middlewares/input-sanitizer.yaml | 过滤恶意输入 |
| OutputFilterMiddleware | middlewares/output-filter.yaml | 过滤响应中的敏感信息 |

## 选择标准
1. 存在外部 API 工具 → ToolRetryMiddleware 几乎必需
2. 预计长对话 → 推荐 SummarizationMiddleware
3. 复杂多阶段任务 → 推荐 TodoListMiddleware
4. 频繁 API 调用 → 推荐 RateLimiter 或 Cache
5. 处理敏感数据 → 推荐 InputSanitizer + OutputFilter
6. 至少 1 个、最多 5 个

## 特别规则
- 推荐 TodoListMiddleware 时: 必须在 reason 中
  明确写出"需要在 system prompt 中添加 write_todos 使用说明"

## 输出格式
只返回 JSON 数组:
[
  {
    "middleware_name": "唯一标识符",
    "middleware_path": "定义文件路径",
    "description": "一句话说明",
    "reason": "选择原因"
  }
]
```

#### Orchestrator 传递的 Task Description

```
user_id: {user_id}

请分析以下信息并推荐所需 middleware:

AgentCreationIntent:
{Phase 2 返回的完整 JSON}

推荐的工具:
{Phase 3 中确定的工具名称数组}

请分析以上信息，综合考虑 agent 的性能、安全、稳定性，
推荐 middleware:

[
  {
    "middleware_name": "middleware 名称",
    "middleware_path": "middleware 文件路径",
    "description": "middleware 的简要说明",
    "reason": "需要该 middleware 的原因"
  }
]
```

---

### 5.5 Phase 5: 生成 system prompt

#### 目的
综合所有信息编写 agent 的 system prompt。

#### 执行主体
**Prompt 生成 subagent**

#### 官方 prompt 模板（从 Deep Agent Assistant 中确认）

Deep Agent Assistant 使用的官方 system prompt 模板结构:

```markdown
# {Agent Name}

## Role
[1-2 sentence purpose]

## Responsibilities
[Numbered task list]

## Tool Guidelines
### `{tool_name}`
- Purpose: [function]
- When: [trigger condition]
- Caution: [what to avoid]

## Subagent Guidelines
### `{name}`
- Expertise: [domain]
- Delegate when: [condition]

## Workflow
[Step-by-step process]

## Constraints
- ALWAYS: [required behaviors]
- NEVER: [prohibited behaviors]
```

#### Subagent system prompt（设计参考）

```markdown
# Prompt 生成 agent — system prompt

## 角色
综合所有信息，编写 agent 可立即使用的
高质量 Markdown system prompt。

## 必须包含的 section（遵循官方模板）

### 1. Role（角色）
- 用 1~2 句话定义 agent 名称和核心角色

### 2. Responsibilities（核心职责）
- 用编号列表描述 3~5 项主要任务

### 3. Tool Guidelines（工具指南）
- 对每个工具:
  - `{tool_name}`: Purpose, When（使用条件）, Caution（注意事项）
  - 建议包含调用示例

### 4. Subagent Guidelines（subagent 指南）— 存在 subagent 时
- 对每个 subagent: Expertise（专业领域）, Delegate when（委派条件）

### 5. Workflow（工作流程）
- 接收用户请求时应遵循的分步流程
- 包含决策逻辑（何时选择哪个工具）

### 6. Constraints（限制条件）
- ALWAYS: 必须行为列表
- NEVER: 禁止行为列表

### 7.（middleware 特殊 section）
- 包含 TodoListMiddleware 时: 必须新增"任务规划与执行"section
- 包含 SummarizationMiddleware 时: 明确 agent 应知晓它，但不直接控制

## Prompt 质量标准
1. 清晰性: 使用具体行为指引，避免模糊表达
2. 具体性: 不写"适当处理"，而是描述准确流程
3. 完整性: 包含工具用法、错误处理、响应风格
4. 实用性: 包含实际使用场景示例

## 限制
- 长度: 2000~5000 字符
- 语言: 与 agent 说明语言相同
- 仅使用 Markdown 格式。禁止包含 JSON/YAML。
- 只返回 prompt。禁止附加说明。
```

#### Orchestrator 传递的 Task Description

```
user_id: {user_id}

请综合以下所有信息，生成高质量 system prompt（Markdown 格式），
长度控制在 2000~5000 字符，并能够作为 agent 实际使用的
操作指南。

=== AgentCreationIntent ===
{Phase 2 返回的完整 JSON}

=== 推荐工具 ===
1. {tool_name} ({tool_path}) - {description}
2. ...

=== 推荐 middleware ===
1. {middleware_name} ({middleware_path}) - {description}
2. ...

=== 要求 ===
- Markdown 格式
- 遵循官方模板结构:
  # {Agent Name}
  ## Role → ## Responsibilities → ## Tool Guidelines → ## Workflow → ## Constraints
- 每个工具包含 Purpose / When / Caution
- 包含响应风格和语气指南
- 包含可实际执行的具体指引
- 包含 TodoListMiddleware 时必须新增 write_todos 使用说明 section
- 2000~5000 字符
```

---

### 5.6 Phase 6: 保存 agent 设置

#### 目的
将所有 metadata 统一写入 config.yaml。

#### 执行主体
orchestrator 直接调用 `write_agent_config` 工具。

#### Orchestrator 指引

```
1. 从 Phase 2 Intent 提取 agent_name, agent_description, primary_task_type, use_cases
2. 从 Phase 3 tools.yaml 提取工具名称列表
3. 从 Phase 4 middlewares.yaml 提取 middleware 名称列表
4. 调用 write_agent_config
5. 在 Todo 中标记 Phase 6 完成
```

---

### 5.7 Phase 7: 最终构建 agent

#### 目的
读取所有配置文件，创建实际 agent 实例。

#### 构建流程

```
1. config.yaml → 读取 model_name 并创建 LLM 实例
2. system_prompt.md → 设置为 system message
3. tools.yaml → 加载每个工具定义并绑定到 agent
4. middlewares.yaml → 将每个 middleware 插入执行 pipeline
5. 构建 LangGraph graph
6. 生成 Agent ID (= timestamp_uuid)
7. 移动到 agents 目录并永久保存
8. 设置 Recursion Limit 默认值（根据工具数量及是否存在 subagent）
```

---

## 6. Deep Agent Assistant 详细设计（创建后管理）

> Builder 创建 agent 后，由 Assistant 修改·管理 agent。

### 6.1 身份与核心原则

```
Identity: Deep Agent Assistant
角色: 修改现有 agent 设置的 AI

核心原则:
1. VERIFY before MODIFY: 修改前始终调用 get_agent_config
2. MINIMAL changes: 仅修改用户明确要求的部分
3. PRESERVE existing: 禁止删除未被要求删除的现有指引
4. VALIDATE resources: 添加前使用 list_available_* 确认存在
5. SYNC prompt: 添加/移除资源后必须同步更新 system prompt
```

### 6.2 添加资源 workflow (ADD)

```
1. get_agent_config        → 确认当前状态
2. list_available_*        → 校验资源是否存在
3. add_*_to_agent          → 添加资源（支持 batch）
4. update_system_prompt    → 在 system prompt 中添加使用指南
5. CHECK secrets           → 确认所需 API key 是否已注册
```

### 6.3 移除资源 workflow (REMOVE)

```
1. get_agent_config             → 确认资源存在
2. remove_*_from_agent          → 移除资源
3. search_system_prompt         → 通过 2-pass 搜索发现 prompt 中的引用
   ├─ 1st pass: 精确资源名称（例如 "tavily_search"）
   ├─ 确认发现的替代名称（例如 "Web 搜索工具"）
   └─ 2nd pass: 使用替代名称再次搜索
4. edit_system_prompt           → 依次移除/修改每个引用
5. search_system_prompt         → 确认没有残留引用（最多重复 3 次）
6. get_agent_config             → 最终确认
```

### 6.4 改进 system prompt workflow (IMPROVE)

使用迭代式"确认-识别-应用"循环:

**Step 0: 初始设置**
1. get_agent_config → 读取完整 prompt
2. 分析 prompt 状态: 空 / 部分 / 完整
3. 向用户发送进度消息

**Step 1: 迭代改进循环（3~7 次）**

每次迭代经过三个阶段:

| 迭代 | 视角 | 重点 |
|------|------|------|
| 第 1 次 | STRUCTURE | section 结构、标题层级、逻辑流、formatting |
| 第 2 次 | PRECISION | 模糊表达、遗漏 edge case、不明确条件 |
| 第 3 次 | COMPLETENESS | 工具/middleware workflow 遗漏、功能 gap、限制遗漏 |
| 第 4~7 次 | OPEN | 所有维度的剩余问题 |

**Phase A — Verify（确认）**
- 通过 get_agent_config 再次确认当前 prompt
- 校验上一轮修改是否正确应用

**Phase B — Identify（识别）**
- 以当前视角分析并列出修改点
- 质量 gate: 只允许实质性变更（不允许纯美化修改）
- 结束条件: 第 3 次后若没有实质性修改则 STOP

**Phase C — Apply（应用）**
- 空 prompt → `update_system_prompt`（整体替换）
- 修改现有 prompt → `edit_system_prompt`（局部修改，优先）
- 必须顺序调用（并行调用有 race condition 风险）

**结束条件:**
- 第 3 次完成后没有剩余问题 → STOP
- 第 7 次完成 → 强制 STOP，并向用户报告未解决事项

### 6.5 澄清问题 (Ask Clarifying Question)

对于模糊请求应提问而不是猜测。**每次响应只允许恰好 1 个问题。**

**必须提问的场景:**

| 场景 | trigger 示例 | 问题示例 |
|---------|-----------|----------|
| 修改范围模糊 | "请改进" | "您希望修改哪个范围？" |
| agent 目的不明确 | 创建新 agent，未说明目的 | "这个 agent 的主要用途是什么？" |
| subagent 角色不明确 | "添加 subagent" | "它负责什么角色？" |
| 存在多个相似工具 | 多个搜索工具 | "tavily vs exa，您更偏好哪个？" |
| 是否需要 middleware | 添加新功能时 | "需要 middleware 吗？" |
| 未指定输出风格 | 语气/格式重要但未说明 | "您希望响应采用什么格式？" |

### 6.6 安全规则

```
- 绝不要在响应中提及使用过的工具名称。
  ❌ "使用 get_agent_config 确认了设置..."
  ✅ "已确认当前设置，并添加 tavily-search 工具。"
- 说明 WHAT，但隐藏 HOW（工具名）。
```

---

## 7. 核心数据结构

### 7.1 AgentCreationIntent

```typescript
interface AgentCreationIntent {
  agent_name: string;              // 英文名称
  agent_name_ko: string;           // 韩文名称
  agent_description: string;       // 详细说明（3~5 句）
  primary_task_type: string;       // 核心任务
  use_cases: string[];             // 使用场景（至少 3 个）
  required_capabilities: string[]; // 必需功能
  tool_preferences: string;        // 工具偏好
  output_style: string;            // 输出风格
  response_tone: string;           // 响应语气
  constraints: string[];           // 限制条件
}
```

### 7.2 ToolRecommendationResult

```typescript
interface ToolRecommendation {
  tool_name: string;
  tool_path: string;
  description: string;
  reason: string;
}
type ToolRecommendationResult = ToolRecommendation[];
```

### 7.3 MiddlewareRecommendationResult

```typescript
interface MiddlewareRecommendation {
  middleware_name: string;
  middleware_path: string;
  description: string;
  reason: string;
}
type MiddlewareRecommendationResult = MiddlewareRecommendation[];
```

---

## 8. 完整工具列表

### 8.1 Builder 专用工具

| 工具 | 类型 | 说明 |
|------|------|------|
| write_project_config | Write | 保存项目 metadata |
| create_project_folder | Write | 创建项目工作文件夹 |
| update_project_config_path | Write | 更新项目路径 |
| task(description) | Invoke | 将任务委派给 subagent |
| write_tool_information | Write | 保存 tools.yaml |
| write_middleware_information | Write | 保存 middlewares.yaml |
| write_system_prompt | Write | 保存 system_prompt.md |
| write_agent_config | Write | 保存 config.yaml |
| build_final_agent | Build | 创建最终 agent 实例 |

### 8.2 Assistant 专用工具

**读取 (Safe)**

| 工具 | 说明 |
|------|------|
| get_agent_config | 当前 agent 状态（工具、middleware、prompt） |
| get_model_config | 当前模型参数 |
| get_tool_config | 特定工具的参数 |
| list_available_tools | 可添加的工具列表 |
| list_available_middlewares | 可添加的 middleware 列表 |
| list_available_subagents | 可添加的 subagent 列表 |
| list_available_models | 可用模型列表 |
| get_agent_required_secrets | agent 所需 API key 列表 |
| get_user_secrets | 用户已注册的 secret |
| get_chat_openers | 当前聊天开场问题 |
| get_recursion_limit | 当前递归上限 |
| list_permanent_files | 已上传的永久文件（用于 RAG） |
| get_file_content | 文件内容预览 |
| search_system_prompt | 搜索 prompt 中的关键词 |
| list_cron_schedules | cron schedule 列表 |
| get_cron_schedule | 特定 schedule 详情 |

**用户澄清**

| 工具 | 说明 |
|------|------|
| ask_clarifying_question | 以 3 个选项 + 直接输入向用户提问 |

**写入 (Verify First)**

| 工具 | 说明 |
|------|------|
| add_tool_to_agent | batch 添加工具 |
| remove_tool_from_agent | batch 移除工具 |
| add_middleware_to_agent | batch 添加 middleware |
| remove_middleware_from_agent | batch 移除 middleware |
| add_subagent_to_agent | batch 添加 subagent |
| remove_subagent_from_agent | batch 移除 subagent |
| edit_system_prompt | 局部修改（优先） |
| update_system_prompt | 整体替换 |
| update_model_config | 修改模型设置 |
| update_tool_config | 修改工具参数 |
| update_middleware_config | 修改 middleware 参数 |
| update_chat_openers | 修改聊天开场问题 |
| update_recursion_limit | 修改递归上限 |
| create_cron_schedule | 创建 cron schedule |
| update_cron_schedule | 修改 schedule |
| delete_cron_schedule | 删除 schedule |
| enable_cron_schedule | 启用 schedule |
| disable_cron_schedule | 禁用 schedule |

---

## 9. 错误处理策略

### 9.1 Builder 各 Phase 错误应对

| Phase | 可能的错误 | 应对 |
|-------|-----------|------|
| Phase 1 | 文件夹创建失败 | 立即中止，通知用户 |
| Phase 2 | subagent 响应不是 JSON | 重试 1 次。失败时使用默认 Intent 模板 |
| Phase 3 | 推荐了不存在的工具 | 排除该工具，显示警告消息 |
| Phase 4 | 推荐了不存在的 middleware | 排除该 middleware，显示警告消息 |
| Phase 5 | prompt 长度低于/超过标准 | 重试 1 次 |
| Phase 6 | 文件保存失败 | 立即中止 |
| Phase 7 | 构建失败 | 报告错误内容，建议手动修改 |

### 9.2 Assistant edit_system_prompt 错误应对

- old_string 未在 prompt 中发现 → 返回错误消息和 context
- old_string 不唯一（多处匹配）→ 使用 replace_all 参数或以更具体的字符串重试
- 违反顺序调用（并行调用）→ 可能发生 race condition，必须顺序执行

---

## 10. RAG（基于文件的响应）设置指南

这是让 agent 参考已上传文档进行回答的功能。

### 10.1 核心规则

- `list_agent_files` 和 `read_agent_file` 是**所有 agent 自动包含**的内部工具
- 不会显示在 `list_available_tools` 中
- 不应通过 `add_tool_to_agent` 添加
- 只需在 system prompt 中添加使用指引

### 10.2 设置 workflow

```
1. list_permanent_files   → 确认已上传文件
2. get_file_content       →（可选）预览文件内容
3. get_agent_config       → 确认当前 prompt
4. update_system_prompt   → 添加基于文件的响应指引
```

### 10.3 添加到 prompt 的 RAG section 示例

```markdown
## 基于文件的响应指引

该 agent 会参考已上传文档回答。

### 可参考文件
- sample.pdf: [文件的简要说明]
- data.md: [文件的简要说明]

### 任务顺序
1. 接收用户问题
2. 使用 list_agent_files() 确认文件列表
3. 通过 read_agent_file(file_id) 读取相关文件
4. 基于文件内容生成回答

### 注意事项
- 回答前始终先确认文件内容
- 文件中没有相关内容时，提示"无法在文件中找到相关信息"
```

**重要:** 不得将文件内容直接复制到 system prompt。仅将文件名作为引用，并应在 runtime 中通过 `read_agent_file` 读取。

---

## 11. Subagent 调用机制

### 11.1 task() 函数的运行方式

```python
def task(description: str) -> str:
    """
    将任务委派给 subagent。
    
    subagent 无法访问 orchestrator 的 state。
    所有所需信息都必须包含在 description 中。
    """
    sub_agent = get_sub_agent_for_current_phase()
    response = sub_agent.invoke({
        "messages": [HumanMessage(content=description)]
    })
    return response["messages"][-1].content
```

### 11.2 隔离原则

subagent **会接收:**
- 自己的 system prompt（内置）
- orchestrator 发送的 description (messages)

subagent **不会接收:**
- orchestrator 的 system prompt
- 其他 subagent 的 prompt 或响应
- 与用户的直接对话 history
- orchestrator 的内部 state（user_id 等）

---

## 12. 可扩展设计点

### 12.1 工具目录动态化
当前: 在 subagent prompt 中 hardcode 目录
改进: 由 subagent 直接调用 `list_available_tools` API 动态查询

### 12.2 通过用户对话收集 Intent
当前: 通过单次请求完成 Intent
改进: 通过对话逐步细化 Intent（借鉴 Assistant 的 ask_clarifying_question 模式）

### 12.3 并行执行
理论上 Phase 3 和 Phase 4 可并行。可用 asyncio 或 LangGraph 并行 node 缩短构建时间。

### 12.4 Agent 测试自动化
Phase 8 增加"自动测试": 向生成的 agent 发送测试 query → 确认正常运行

### 12.5 Builder → Assistant 顺畅连接
构建完成后自动启动 Assistant session，使用户可立即微调 agent。

---

## 13. 基于 LangGraph 的实现草图

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, List

class BuilderState(TypedDict):
    user_id: str
    user_request: str
    project_path: str
    intent: dict
    tools: List[dict]
    middlewares: List[dict]
    system_prompt: str
    agent_id: str
    current_phase: int
    error: str

def phase1_init(state: BuilderState) -> BuilderState:
    config = write_project_config(state["user_id"])
    folder = create_project_folder(state["user_id"])
    update_project_config_path(state["user_id"], folder)
    return {**state, "project_path": folder, "current_phase": 2}

def phase2_intent(state: BuilderState) -> BuilderState:
    description = f'''
    用户请求了"{state['user_request']}"。
    请以 AgentCreationIntent 格式进行分析。
    '''
    result = intent_agent.invoke({"messages": [HumanMessage(content=description)]})
    intent = json.loads(result["messages"][-1].content)
    return {**state, "intent": intent, "current_phase": 3}

def phase3_tools(state: BuilderState) -> BuilderState:
    description = f'''
    AgentCreationIntent: {json.dumps(state['intent'])}
    请推荐所需工具。
    '''
    result = tool_agent.invoke({"messages": [HumanMessage(content=description)]})
    tools = json.loads(result["messages"][-1].content)
    write_tool_information(state["project_path"], tools)
    return {**state, "tools": tools, "current_phase": 4}

def phase4_middlewares(state: BuilderState) -> BuilderState:
    tool_names = [t['tool_name'] for t in state['tools']]
    description = f'''
    AgentCreationIntent: {json.dumps(state['intent'])}
    推荐工具: {json.dumps(tool_names)}
    请推荐所需 middleware。
    '''
    result = middleware_agent.invoke({"messages": [HumanMessage(content=description)]})
    middlewares = json.loads(result["messages"][-1].content)
    write_middleware_information(state["project_path"], middlewares)
    return {**state, "middlewares": middlewares, "current_phase": 5}

def phase5_prompt(state: BuilderState) -> BuilderState:
    description = f'''
    === AgentCreationIntent ===
    {json.dumps(state['intent'])}
    
    === 推荐工具 ===
    {format_tools(state['tools'])}
    
    === 推荐 middleware ===
    {format_middlewares(state['middlewares'])}
    
    请按照官方模板结构生成 2000~5000 字符的 system prompt。
    '''
    result = prompt_agent.invoke({"messages": [HumanMessage(content=description)]})
    prompt = result["messages"][-1].content
    write_system_prompt(state["project_path"], prompt)
    return {**state, "system_prompt": prompt, "current_phase": 6}

def phase6_config(state: BuilderState) -> BuilderState:
    write_agent_config(
        project_path=state["project_path"],
        agent_name=state["intent"]["agent_name"],
        agent_description=state["intent"]["agent_description"],
        tools=[t["tool_name"] for t in state["tools"]],
        middlewares=[m["middleware_name"] for m in state["middlewares"]],
        model_name="anthropic:claude-sonnet-4-5"
    )
    return {**state, "current_phase": 7}

def phase7_build(state: BuilderState) -> BuilderState:
    agent_id = build_final_agent(state["project_path"])
    return {**state, "agent_id": agent_id, "current_phase": 8}

# 构建 graph
graph = StateGraph(BuilderState)
graph.add_node("phase1", phase1_init)
graph.add_node("phase2", phase2_intent)
graph.add_node("phase3", phase3_tools)
graph.add_node("phase4", phase4_middlewares)
graph.add_node("phase5", phase5_prompt)
graph.add_node("phase6", phase6_config)
graph.add_node("phase7", phase7_build)

graph.set_entry_point("phase1")
graph.add_edge("phase1", "phase2")
graph.add_edge("phase2", "phase3")
graph.add_edge("phase3", "phase4")
graph.add_edge("phase4", "phase5")
graph.add_edge("phase5", "phase6")
graph.add_edge("phase6", "phase7")
graph.add_edge("phase7", END)

builder = graph.compile()
```

---

## 附录 A: 工具/middleware YAML 定义示例

### 工具定义 (tools/tavily-search.yaml)

```yaml
name: tavily_search
display_name: "Tavily Web Search"
description: "使用 Tavily API 的通用 Web 搜索"
version: "1.0.0"

parameters:
  query:
    type: string
    description: "搜索 query"
    required: true
  max_results:
    type: integer
    default: 5
  search_depth:
    type: string
    default: "basic"
    enum: ["basic", "advanced"]

authentication:
  type: api_key
  env_var: TAVILY_API_KEY

rate_limit:
  requests_per_minute: 60
```

### Middleware 定义 (middlewares/tool-retry.yaml)

```yaml
name: ToolRetryMiddleware
display_name: "重试工具调用"
description: "外部 API 调用失败时进行指数 backoff 重试"
version: "1.0.0"

config:
  max_retries: 3
  initial_delay_seconds: 1.0
  backoff_multiplier: 2.0
  retryable_errors:
    - "ConnectionTimeout"
    - "RateLimitExceeded"
    - "ServerError"

applies_to:
  - "all_tools"
```

---

## 附录 B: Secret 确认 workflow (Assistant)

```
1. get_agent_required_secrets → 所需 key 列表
   示例: ["TAVILY_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]

2. get_user_secrets → 已注册 key 列表
   示例: ["TAVILY_API_KEY"]

3. 识别缺失 key: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

4. 对每个缺失 key:
   - 使用 tavily_search 搜索 "{KEY_NAME} API key how to get"
   - 提供申请指南

5. 用户指引:
   🔧 Key 注册方法
   如果您已申请全部 API key:
   1. 前往 /secrets 页面
   2. 注册以下 key:
      - NAVER_CLIENT_ID: 从 Naver 开发者中心申请
      - NAVER_CLIENT_SECRET: 从 Naver 开发者中心申请
   3. 保存
```

---

*本规划书是综合（1）用户-Builder 对话逆向分析 +（2）Deep Agent Assistant 官方 prompt 分析编写的参考文档。实际实现时，工具目录、subagent prompt、error 处理逻辑需要根据项目要求调整。*
