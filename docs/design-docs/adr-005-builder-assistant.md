# ADR-005：Builder/Assistant 架构

| 项目 | 值 |
|------|-----|
| 状态 | 已提议 |
| 日期 | 2026-04-07 |
| 影响范围 | agent_runtime, routers, services, schemas, models |

---

## 背景

当前 agent 创建/修改系统：
- **creation_agent.py**：单一 GPT-4o，tools=[]，4 阶段对话式（约 ~220 行）
- **fix_agent.py**：单一 LLM，输出 JSON changes → 代码应用（约 ~150 行）

限制：
1. creation_agent 将工具/middleware catalog 以文本形式注入 system prompt → 存在幻觉风险
2. fix_agent 输出 free-form JSON 而非结构化变更 → 经常解析失败
3. 两个 agent 都不使用工具，无法保证与 DB 一致
4. system prompt 改进只能整体替换（无法局部修改）

## 决定

替换为 **Builder**（orchestrator + 4 个 sub-agent）和 **Assistant**（基于工具的单一 agent）。

### Builder：LangGraph StateGraph pipeline

按顺序执行 7 个 Phase 的 StateGraph。Phase 2-5 分别由专业 sub-agent 处理。

```
Phase 1 (init) → Phase 2 (intent) → Phase 3 (tools) → Phase 4 (middlewares)
                                                                    ↓
                                    Phase 7 (build) ← Phase 6 (config) ← Phase 5 (prompt)
```

**sub-agent 隔离原则：**
- 每个 sub-agent 只接收自己的 system prompt + orchestrator 发来的 description
- 无法直接访问 orchestrator 内部 state 或其他 sub-agent 输出
- orchestrator 将前一 Phase 的结果包含在 description 中传递

**sub-agent 实现：**
- `create_deep_agent(model, tools=[], system_prompt=sub_prompt)` → `.ainvoke()`
- 不使用工具，只做纯推理（JSON 输出）
- 输出解析失败时重试 1 次，之后使用默认值

### Assistant：基于工具的 agent

通过 `create_deep_agent` 创建，绑定 32 个工具，直接操作 DB。

**核心原则：VERIFY before MODIFY**
- 所有修改前调用 get_agent_config
- 工具直接修改 DB，因此无需额外 confirm 阶段
- system prompt 优先使用 edit_system_prompt（局部修改），update_system_prompt（整体替换）作为辅助

## 核心架构决策

### AD-1：用 LangGraph StateGraph 实现 Builder

**采纳：** LangGraph StateGraph（基于 node）
**否决：** 单一 agent + 工具 / 简单函数链

原因：
- 用 graph edge 显式表达 Phase 间依赖
- 将每个 Phase 隔离为独立 node → 便于单独测试
- 出错时可从特定 Phase 重试（保存 state）
- SSE streaming：可自然地将 node 执行事件转换为 SSE

### AD-2：以 create_deep_agent(tools=[]) 创建 sub-agent

**采纳：** create_deep_agent + ainvoke
**否决：** 直接调用 LLM（model.ainvoke）/ LangGraph subgraph

原因：
- create_deep_agent 是项目标准 agent 创建方式
- 当前 creation_agent.py 也已使用 build_agent(tools=[])
- subgraph 会增加不必要复杂性（无工具的简单推理）
- 未来给 sub-agent 增加工具时可自然扩展

### AD-3：Assistant 工具直接修改 DB

**采纳：** 工具内部接收 AsyncSession 并直接修改 DB
**否决：** 工具返回变更 → 服务层统一应用

原因：
- VERIFY-MODIFY 循环需要在工具粒度工作
- 工具立即写入 DB → 可通过 get_agent_config 立即确认
- 从根本上解决 fix_agent 的 JSON 解析失败问题
- transaction 按工具管理（失败时只 rollback 该工具）

### AD-4：Builder API 分 2 阶段（start + SSE → confirm）

**采纳：** POST /start → SSE /stream → POST /confirm
**否决：** 单一 POST（同步）/ WebSocket

原因：
- 7 个 Phase 执行需要几十秒 → 通过 SSE 实时报告进度
- 在 confirm 阶段由用户检查 draft_config 后修改/批准
- SSE 可复用现有聊天基础设施（streaming.py）
- WebSocket 增加服务器资源负担 + 与现有基础设施不一致

### AD-5：用 BuilderSession DB 模型持久化中间状态

**采纳：** 扩展现有 AgentCreationSession → BuilderSession
**否决：** 仅内存（session 结束即丢失）/ 文件系统

原因：
- 即使服务器重启/崩溃也可继续 build
- 将各 Phase 中间结果（intent, tools, middlewares, prompt）保存到 JSON 列
- 通过迁移现有 agent_creation_sessions 表完成转换
- 文件系统是规划文档中的设想，但 PoC 阶段 DB 更简单

### AD-6：Assistant 复用现有 conversation 基础设施

**采纳：** conversations 表 + 基于 checkpointer 的历史
**否决：** 单独 assistant_sessions 表

原因：
- Assistant 对话与普通聊天结构相同（user/assistant 消息）
- checkpointer 管理历史 → 无需额外表
- 给 conversation 增加 `type` 字段区分（chat / assistant）
- 完全复用现有 SSE 基础设施

### AD-7：向 sub-agent 动态注入真实 catalog

**采纳：** 调用 sub-agent 时从 DB 查询 catalog 并包含到 description 中
**否决：** 在 system prompt 中硬编码 catalog

原因：
- 工具/middleware 会动态增删，因此硬编码存在 drift 风险
- sub-agent 不使用工具，因此无法直接调用 API
- orchestrator 查询 DB → 注入 description 模板
- catalog 规模不大，context 成本在可接受范围内

## 接口契约

### Builder API

| 方法 | 路径 | 说明 |
|--------|------|------|
| POST | `/api/builder/start` | 启动 build session → BuilderSessionResponse |
| GET | `/api/builder/{session_id}/stream` | SSE streaming（build 进度） |
| GET | `/api/builder/{session_id}` | 查询 session 状态 |
| POST | `/api/builder/{session_id}/confirm` | 确认 build → AgentResponse |

### Assistant API

| 方法 | 路径 | 说明 |
|--------|------|------|
| POST | `/api/agents/{agent_id}/assistant/message` | SSE 消息（包含工具执行） |
| GET | `/api/agents/{agent_id}/assistant/config` | 查询当前 agent 配置 |

### Builder SSE 事件

```typescript
// phase_progress：阶段进度
{phase: number, status: "started" | "completed" | "failed", message?: string}

// sub_agent_start/end：sub-agent 执行
{phase: number, agent_name: string}
{phase: number, result_summary: string}

// build_preview：build 预览
{draft_config: DraftAgentConfig}

// error：错误
{phase: number, message: string, recoverable: boolean}
```

## 结果

### 正面影响
- 通过 sub-agent 隔离，可独立测试各 Phase
- Assistant 基于工具，保证 DB 一致性
- 最大程度复用现有基础设施（SSE、checkpointer、executor）
- 支持局部修改（edit_system_prompt），提升 prompt 质量

### 负面影响/风险
- Builder 7 个 Phase 执行时间较长，可能影响用户体验 → 通过 SSE 进度报告缓解
- 4 个 sub-agent 的 LLM 调用成本 → 考虑低成本模型（gpt-4o-mini）
- Assistant 32 个工具的 schema 较大，消耗 token → 必要时进行工具分组

### 迁移策略
1. 新建 builder/、assistant/ 目录
2. 新增 routers/services（与现有共存）
3. 前端切换到新 API
4. 删除现有 creation_agent.py、fix_agent.py 及相关代码
