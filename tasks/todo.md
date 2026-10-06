# Stage 3 — God 模块拆分（一个 PR，逐项 commit + 逐项 review）

branch: `refactor/stage3-god-modules`（基于 origin/main = 5c7a6c01）
原则: 功能变化 0，纯移动 + facade re-export，每项小 commit，每项完成后 code-review → 修复 commit → 下一项。
验证（逐项）: `ruff check` + 目标 pytest → commit 前 `SKILL_EVALUATION_ENABLED=true pytest -q -n 4 --ignore=tests/integration`
最终: integration 串行（必须 `-m integration`）+ push 时 `SKILL_EVALUATION_ENABLED=true`

- [x] 0. baseline: 2702 passed / 5 failed = 全部由 SKILL_EVALUATION_ENABLED=false 导致（开启 flag 即通过）→ 实质 green
- [x] 1. BE-S1 — chat_service.py(1810行→104行 facade) → 拆分为 `app/services/chat/` 7个模块 (a901b319)
  - [x] 实现 commit → [x] review: 批准，发现 0（通过 AST 全量对比确认纯移动，实证保留 4 处函数局部 import 的原因）→ 无需修复
- [x] 2. BE-S3 — install_service.py(1365行→400行 facade+dispatcher) → 拆分为 `app/marketplace/install/`（第 2 个 commit）
  - common / snapshot / bindings / skill / mcp / agent_blueprint。2 处提取 seam（skill create/overwrite）做语句级 AST 一致性验证
  - [x] 实现 commit → [x] review: 批准，发现 0 → 无需修复
- [x] 3. BE-S5 — write_tools.py(1091行) → `write_tools/` package + WriteToolContext (9eee9bea)
  - 23 个 tool schema 字节级相同，通过 call-time 注入保留 patch surface(async_session_factory)
  - [x] 实现 commit → [x] review: 批准，发现 0 → 无需修复
- [x] 4. BE-S8 — artifact_service.py(1035行→137行 facade) → `app/services/artifacts/` recorder/library/content/summary/errors (1e7d519f)
  - [x] 实现 commit → [x] review: 批准，Low 1项（hot path call-time facade import — 为保留 patch 契约的有意设计，判定无需修改）
- [x] 5. BE-S9 — scheduler.py(805→706行) 内联 job 4项 → credentials/rotation·mcp_service·conversation_run_service·skill_runtime (ccf4d25b)
  - 保留同名 wrapper（保留持久化 jobstore module:qualname + 测试 patch surface call-time 注入）
  - [x] 实现 commit → [x] review: 批准，阻断 0（信息性 1: _DATA_DIR import-time 绑定 — 判定不影响功能）
- [x] 6. BE-S10 — runtime_component_builder.py(930→600行) → `agent_runtime/runtime/` models/reliability/interrupts/prompts/memory_context (9fa1facc)
  - 保留 12 种 monkeypatch 透明性（仅 create_chat_model 使用 call-time builder import 模式），executor facade 不修改
  - [x] 实现 commit → [x] review: 批准，发现 0
- [x] 7. 最终全量验证: ruff 0 / full 2707 passed / integration 29 passed·1 skipped / frontend vitest 1294 passed + plan 文档 ✅ 更新
- [x] 8. push + 创建 **PR #296**（pre-push gate: worktree node_modules 缺少 diff@9 导致的 vitest 失败通过 clean pnpm install 解决 — 与代码无关）
- [x] 9. 最终 /review（交叉 review）批准 + 提炼 CLAUDE.md facade-拆分规则 (0e3da3f2)
- [x] 10. 对抗性 review 4 个 lens 并行（动态引用·序列化 / mutation 实证 / 安全 / 并发·事务）: **commit branch 缺陷 0**。mutation 7/8 CAUGHT，MISSED 1 为现有缺口 → seam 加固测试 6项（每个 mutation FAIL 实证）commit 292dedb4，全部 2713 passed。记录 PR comment。
  - 后续候选（范围外）: xdist 低频 flake(test_state_snapshot fallback，隔离冲突·与 main 相同), write_tools docstring "18个" 标记（pre-existing）
