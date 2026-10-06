# 历史 CHECKPOINT — Skill Studio Phase 3：实测 A/B 基准、实际费用、分版本通过率与用户反馈

> 原型历史记录（2026-07-12），不作为本轮项目验收结果。
> 原 Phase 2 六页签 Studio 已完成并合并（PR #293），被本记录替换。
> Phase 1.5/2 剩余待办保留在文末。

规格：`docs/design-docs/skill-studio-phase3-benchmark-cost-spec.md`
分支：`feature/skill-studio-phase3`（worktree `.claude/worktrees/feature+skill-builder-chat`，基于 origin/main 5c7a6c01）
原则：每个里程碑完成后提交，推送验证设置 `SKILL_EVALUATION_ENABLED=true`。
已确认决策：D1 A/B 为单例双 arm（每用例 3 次调用）；D2 同时提供用例与 Skill 级反馈（仅展示）；D3 用量归属仅记录实测数据。

## M0：规格文档

- [x] `skill-studio-phase3-benchmark-cost-spec.md` 与 CHECKPOINT 替换。
- 状态：done（2026-07-12）。

## M1：m70 迁移与三类 ORM

- [x] `skill_usage_events`、`skill_evaluation_runs.usage` JSON、`skill_feedbacks`、`skill_evaluation_case_feedbacks`。
- [x] ORM 模型、`models/__init__.py` 注册与 aiosqlite 兼容。
- 验证：`cd backend && uv run pytest -q tests/test_migrations*.py -k m70; uv run alembic upgrade head`（本地 PG）。
- 完成条件：upgrade/downgrade 往返与模型导入通过。
- 状态：done（2026-07-12）。

## M2：Skill 维度的 usage 来源（后端）

- [x] `skill_usage_service.py`：record_evaluation_usage / record_chat_execution / get_skill_usage_summary。
- [x] execute_in_skill 成功后记录 chat_execution；不破坏现有流程，使用独立会话，跳过 draft/eval 内部调用。
- [x] `GET /api/skills/{id}/usage`，安全检查所有权，避免资源枚举。
- [x] LLM usage_metadata 捕获与 Model 单价查询。
- 验证：`uv run pytest -q -k "skill_usage"`。
- 完成条件：事件记录、聚合与 API 测试通过。
- 状态：done（2026-07-12）。

## M3：实际费用核算

- [x] estimate_run 使用实际单价计算与 pricing_available。
- [x] Worker 保存 run.usage 并记录 skill_usage_events。
- [x] Schema：RunResponse.usage / RunEstimate 字段。
- 验证：`uv run pytest -q -k "estimate or skill_evaluation_worker"`。
- 完成条件：实测 rollup 持久化与费用估算测试通过。
- 状态：done（2026-07-12）。

## M4：实测 A/B 基准（runner llm-2）

- [x] with-arm / without-arm / grader 三次实测调用；benchmark measured:true、token_delta、duration_delta_ms。
- [x] arm 级取消检查点、用例超时与 run_config.baseline_comparison。
- [x] e2e_scripted_model grader/arm 场景。
- 验证：`uv run pytest -q -k "skill_evaluation_llm or ab_arm"`。
- 完成条件：实测基准单元测试与 scripted 确定性验证通过。
- 状态：done（2026-07-12）。

## M5：分版本通过率 API

- [x] `GET /api/skills/{id}/evaluations/version-stats`。
- 验证：`uv run pytest -q -k "version_stats"`。
- 状态：done（2026-07-12）。

## M6：用户反馈后端

- [x] 用例反馈 PUT/DELETE 并随 run 响应返回；Skill 反馈 GET/PUT/DELETE 与聚合。
- [x] CSRF、所有权与防枚举。
- 验证：`uv run pytest -q -k "feedback"`。
- 状态：done（2026-07-12）。

## M7：前端评测页签与版本标记

- [x] A/B 图表 (chart.js)、实测/估算标签、旧 key 对齐。
- [x] run 详情实际费用、estimate 对话框实际单价。
- [x] 分版本通过率趋势与历史页签标记。
- [x] usage 卡片、用例/Skill 反馈 UI。
- [x] api/hooks/types 与当时的 i18n 资源。
- 验证：`pnpm vitest run`、tsc、lint、build、lint:i18n、lint:design-system。
- 状态：done（2026-07-12）。

## M8：E2E 与截图规格

- [x] mock `skill-studio-phase3.spec.ts`，扩展 live `skill-evaluation-actions`。
- [x] `captures-skill-studio-phase3.spec.ts` 七张导览截图。
- 验证：mock 模式与隔离 live 环境。
- 状态：done（2026-07-12）。

## M9：完整验证与对抗性评审

- [x] 后端 pytest（SKILL_EVALUATION_ENABLED=true）、Ruff；前端 Vitest、tsc、ESLint、build、i18n、design-system；mock/live E2E。
- [x] `/code-review` 对抗性评审，直到发现问题归零，至少两轮。
- 状态：done（2026-07-12）。

## M10：实际服务截图导览与用户报告

- [x] 启动隔离环境、执行截图、发送 PNG。
- 状态：done（2026-07-12）。

## 里程碑依赖

M0 → M1 → (M2, M3) → M4 → M5 → M6 → M7 → M8 → M9 → M10，之后创建 PR。

## 保留：Phase 1.5/2 剩余待办

- 右侧源码文件列表不显示二进制 asset；保持展示层 fail-closed，必要时仅列文件名，内容请求返回 404。
- improve 冲突时重新初始化；刷新后的同意标记；失效会话的对话重建。
- 刷新与首次 POST 间极短窗口中的第二次自动发送尝试；服务端唯一活跃 run 约束返回 409，防止真实重复，可进一步收敛到服务端首条消息幂等。
- 批量包导出（D3 暂缓）、Skill 复制（模拟行菜单）、移除 used_by_count 列（需要迁移）。
- Phase 2 仅报告问题：文件列表/查看器三份实现共用、复用 SettingsSectionCard、columns useMemo、serialize_skill 标量子查询、shell useSelectedLayoutSegments、重写未配置 System LLM 提示、content path max_length 不对称。
- 修订数超过 100 时的截断提示；文本 rollback 修改后失败窗口的原子化；页签 enabled、breadcrumb UUID 与 Builder 422-as-empty UX 边界。
