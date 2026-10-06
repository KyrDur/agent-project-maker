# Wave 2 实现 checklist (feature/chat-wow-wave2)

基于精密验证（2026-07-04, main fdef4567）。各项按 commit 单位推进。

- [x] W2-1 团队 strip — `subagent-team-strip.tsx`（commit 6519530a）
  - useSubagentSnapshots + chatSubagentNames 显示名替换，点击 chip → 右侧 rail
  - 验证: vitest 6/6, tsc
- [x] W2-2 搜索 rich card（commit cce9293d）
  - parseSearchResults {items} + description/thumbnail/lprice，Tavily answer box
  - 注册 definition_key 名称（naver_search_*, google_search_*）+ shape fallback routing
  - 验证: vitest 14/14 + 相关回归 213, tsc, i18n
- [x] W2-3 Memory recall chip（commit de71db42）
  - cfg.recalled_memories → moldy.memory_recalled stream-head event(stable id)
  - frontend replay:true hook + 常驻 chip。验证: pytest 293, vitest 8/8
- [x] W2-4/6 genui producer + skill 执行 card（commit 56285b34）
  - UI_DATA_TOOL_TRANSFORMERS: execute_in_skill → terminal（移除 OUTPUT_FILES，6k cap）
  - SkillExecutionToolUI: skill 名称/命令/文件 chip（文件 API 链接）
  - 验证: pytest 277(agent_runtime)+projection, vitest 584(chat scope)
- [x] W2-5 E2E + capture
  - [x] scripted fixture: E2E_SEARCH_RICH(answer)/E2E_SEARCH_SHOP(items shape, thumbnail key 必须 — image 相对路径会被 http guard 拦截)
  - [x] captures-wave2-scenario.spec.ts（7 个 capture, 1 passed 2.1m）— memory resetMemories(rerun-safe) + 末尾清理（防止 user-scope 泄漏）
  - [x] backend 全量 pytest: 2520 passed（+5 skill-eval 依赖 .env — 已确认设置 SKILL_EVALUATION_ENABLED=true 后通过）
  - [x] vitest 全量: 1219/1219
  - [x] 回归 E2E: hitl-approval/chat-generative-ui 全部 green。**发现·更新 stale 3 项**:
    chat-stream-integrity :63/:299 + chat-langgraph-v3 :47 — PR #272 将 approval card
    headline 改为 skill 名（docx-document），group card 改为 '待批准 N项'
    变更后未更新的断言。**通过 main checkout 对照执行确认 pre-existing**
    后更新为新契约 → 3 项全部通过。
  - [x] team strip ↳ marker: SDK depth 为 root=0/直接委派=1 → 将嵌套判断修正为 depth>1
  - [x] 向用户交付 7 张 capture PNG

## 验证命令
- backend: `uv run --with pytest-xdist pytest -q -n 8`（skill-eval 5 项需要 SKILL_EVALUATION_ENABLED=true）
- frontend: `pnpm vitest run && pnpm exec tsc --noEmit && pnpm lint:i18n`
- capture: `E2E_CAPTURE_TOUR=1 E2E_FRONTEND_PORT=3310 E2E_BACKEND_PORT=8310 DATABASE_URL=...5436... DATABASE_URL_SYNC=... RATE_LIMIT_ENABLED=false E2E_TEST_HELPERS_ENABLED=true pnpm exec playwright test e2e/captures/captures-wave2-scenario.spec.ts`

## 已知陷阱（本 session 发现）
- lint:design-system 在 main 也会 exit 1（pre-existing, message-attachments/approval-card）
- makeAssistantToolUI render 测试: 必须在渲染 Provider "下方组件" 期间调用 renderFn，才能获取 context
- ui_data custom name 为无前缀 "ui_data"（side-effect 惯例；不是 moldy.*）
