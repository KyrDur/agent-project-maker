# Pyright 积压问题清零完成记录

> 状态：**2026-09-07 完成**。`uv run pyright` 已达到 0 个错误，并且 CI
> 已移除 `backend-typecheck` 的 `|| true`，升级为 basic-mode 硬门禁。
> `typeCheckingMode = "standard"` 的升级不包含在本次工作中，保留为单独决策。

## 完成结果

- 最新 `origin/main` 起点：**1,258 项**（`app/**` 104，`tests/**` 1,154）
- 完成状态：**0 errors, 0 warnings, 0 informations**（`filesAnalyzed: 1,058`）
- 设置：保持 `basic`，继续排除 `data`、`.venv`、`alembic/versions`
- CI：将 `.github/workflows/ci.yml` 的 `backend-typecheck` 改为 blocking
- Pydantic 应用原则：仅在 HTTP、LLM、存储 JSON 等需要验证的信任边界使用
- 内部契约：使用 `TypedDict`、dataclass、Protocol、窄化的 JSON 类型和显式运行时窄化
- 工具测试：使用官方 `BaseTool.ainvoke`，而不是实现细节中的 `BaseTool.coroutine`

以下分布和各阶段内容是 2026-07-08 当时的首次分析记录。实际工作后来
是在合并后代码更大的基准值上完成的。

## 0. 整体分布（分析时：970 项）

| 区域 | 数量 | 性质 |
|------|-----:|------|
| `data/**` | 343 | **不是应用代码** — 已安装 Skill 包脚本/上游 vendor 代码（运行时数据，每台机器不同） |
| `tests/**` | 502 | 集中在少数重复模式（见下文 §3） |
| `app/**` | 125 | 实际代码 — 按文件局部集中（见下文 §2） |

## Phase A — 设置整理 ✅ 完成（本次提交）

在 `[tool.pyright]` 中添加 `exclude = ["data", ".venv", "alembic/versions"]`。
`data/` 是运行时内容（已安装 Skill、上传、Marketplace 快照），不属于类型门禁对象，而且每台机器内容不同，是导致计数不确定的原因。

**结果：970 → 627**（-343，无风险）

## Phase B — app 实际代码整理 ✅ 完成

问题按文件高度集中，只处理排名前 8 的文件就能消除 77 项。

| 文件 | 数量 | 主要原因 | 修改方向 |
|------|-----:|-------------|-----------|
| `services/agent_blueprint_service.py` | 20 | JSON 列（`dict \| None`）上调用 `.get()`/迭代 — 缺少 null 防护 | 在函数入口将 `payload = blueprint.payload or {}` 规范化，或做局部窄化。**注意：检查实际运行时 null 的可能性 — 应逐案例判断是否需要真实防护，而不只是让类型检查静默** |
| `agent_runtime/legacy_event_projection.py` | 12 | 将 `dict[bytes, bytes]` 传给 `dict[str, Any]` 参数等 | "legacy" 模块 — **先确认删除/使用处**（若 dead，删除才是正确做法）。仍在使用则在解码边界做显式转换 |
| `agent_runtime/checkpointer.py` | 7 | 库（psycopg/langgraph）类型边界 | 在边界使用窄化的 `cast`/适配器 |
| `agent_runtime/skill_builder/graph.py` | 7 | LangGraph state dict 访问 | 定义 TypedDict state schema |
| `agent_runtime/skill_builder/trigger_eval.py` | 7 | 〃 | 〃 |
| `services/conversation_run_worker.py` | 6 | Optional 访问 | null 防护 |
| `marketplace/install_service.py` | 5 | Optional/arg 类型 | 建议与 BE-S3 拆分工作一起处理 |
| `agent_runtime/langgraph_pending_inputs.py` 等尾部 17 个文件 | 61 | 每个文件 1~3 项 | 逐文件机械修改 |

- 推进方式：按 blueprint、skill builder/evaluation、protocol/runtime、storage 边界分组
  修改，并确认每个文件及整个 `app/` 都为 0。
- `app/seed/system_skill_packages/*/scripts` 的 4 项是 subprocess 执行脚本（不会 import）— 修改或新增 exclude 二选1（建议修改，只有 4 项）。

## Phase C — 测试契约整理 ✅ 完成

消息模式收敛为 6 种，因此按**模式维度**处理，而不是按文件：

| 模式 | 数量 | 原因 | 修改方向 |
|------|-----:|------|-----------|
| `"__getitem__" not defined on int/float/bool` + `No overloads for __getitem__` | ~218 | skill_evaluation 测试直接对宽泛递归 JSON 结果做嵌套索引 | 为结果添加 dict-compatible 类型和边界窄化以保留结构。不使用 blanket `Any` |
| `Object of type "None" is not subscriptable` | 59 | 直接索引返回 Optional 的 helper | 在 helper 中 `assert x is not None` 后返回 or 将返回类型改为非 Optional |
| `No parameter named "model"` | 41 | 单个文件 `test_e2e_scripted_model.py` — 构造函数 kwargs 中的类型没有该参数 | 在相应 factory 签名中明确参数（1 处） |
| `Cannot access attribute "coroutine" for BaseTool` | 24 | builder 返回 `BaseTool`，但测试访问了实现细节属性 | 改用 `BaseTool.ainvoke` |
| TypedDict/`metadata` 键访问类 | ~30 | LangChain 消息 TypedDict 窄化失败 | 改用 `cast` 或 `.get()` |
| 其余单项 | ~130 | 零散 | 按文件机械修改 |

- **原则：放宽规则（用 executionEnvironments 只关闭 tests）是最后手段** — 上述模式大多只需改几行 helper 签名，比放宽规则成本更低，而且 `reportIndexIssue` 等在测试中也能捕获真实 bug。

## Phase D — 门禁升级 ✅ 完成

1. 已从 `.github/workflows/ci.yml` 的 `backend-typecheck` step 中移除 `|| true`。
2. 已更新 `docs/refactoring-plan-2026-07.md` 中的类型门禁状态。
3. 将 `typeCheckingMode = "standard"` 的升级拆分为可选事项。

## 进度跟踪

| Phase | 目标剩余 | 状态 |
|-------|----------:|------|
| A. 排除 data | 627 | ✅ 2026-07-08 (PR #279) |
| B. app 实际代码 | 仅剩 tests | ✅ 2026-09-07 |
| C. tests 模式 | 0 | ✅ 2026-09-07 |
| D. 硬门禁 | 保持 0 | ✅ 2026-09-07 |

验证命令：`cd backend && uv run pyright`（全部），`uv run pyright <文件>`（修改分组）。
