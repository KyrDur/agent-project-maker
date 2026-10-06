# Phase 0 — 安全网（refactor/phase0-safety-net）✅ 完成

> 依据文档：docs/refactoring-plan-2026-07.md §1(P0)·§3(安全跟踪)·§9(IX-1)
> 原则：每项 1 个 提交，功能变化仅限修复对象

## 开始前确认
- [x] 范围 已确定（用户确认）：Phase 0 全部 6 项，每项单独 提交 + 共 1 个 PR

## 项目

### SEC-1: 阻断 web_scraper SSRF — ✅ 41f4e4a9
- [x] 新增 `url_guard.py` — 限制 scheme 为 http/https + 拒绝 literal/resolved IP non-global（getaddrinfo non-blocking）
- [x] 手动 重定向 最多 5 hop，每 hop 重新验证（共享 客户端 配置不变）
- [x] 流式 正文 上限 2MB（包含 数据块 内截断 — 测试捕获了缺陷）
- [x] tests/test_web_scraper_ssrf.py 18 用例（metadata/loopback/RFC-1918/CGNAT/IPv6/file/redirect/cap）

### SEC-2: rotate_credentials no-progress 循环 防护 — ✅ 734f920a
- [x] 累积失败 id → 下一次 fetch 中用 `notin_` 排除（通过保证进展证明终止）
- [x] 回归测试：批次=2·失败 3 行时有限终止（wait_for 超时 防护）

### SEC-3: 触发器 run-now 防重复执行 防护 — ✅ 75d48655
- [x] execute_trigger 入口对触发器行 FOR UPDATE + 检查 non-stale running run 认领
- [x] run-now 返回 `TRIGGER_ALREADY_RUNNING`（409, error_codes 工厂），调度路径静默跳过
- [x] 陈旧边界 1h — 崩溃导致 running 卡住的 run 不会永久阻断
- [x] 3 项测试（跳过/409/忽略陈旧项）

### BE-P4: 消除 bcrypt 阻塞 事件 循环 — ✅ c64ce4e0
- [x] auth_service 3 处（register hash、时序填充 verify、登录 verify）使用 `asyncio.to_thread`
- [x] 种子（e2e_user）仅在启动时执行 1 次，因此保留（Minimal Impact）

### FE-D1: 路由错误边界 — ✅ 8cc7f430
- [x] `app/error.tsx`, `app/agents/error.tsx`, `app/shared/error.tsx`（复用既有 ErrorState 模式）
- [x] `app/global-error.tsx` — 因替换根布局，直接 import globals.css + 静态英文文案（无 i18n 提供方）

### IX-1: CI 流水线 — ✅ 6fd40da4
- [x] `.github/workflows/ci.yml` — backend（ruff+pytest -n 4）/ frontend（lint+vitest+build）必需 2-job
- [x] backend-typecheck 任务 为 non-blocking — **全量 pyright 968 个既有 错误**（最初"通过"的判断是 流水线 exit 代码 误读；计划文档已更正）
- [ ] 在 PR 中实测 任务 为绿（创建 PR 后）

## 完成条件
- [x] backend: ruff clean / 修改文件 pyright clean / **全量 pytest 2,558 通过**（1 次 test_default_image_skill_seed 并行 偶发失败 — 单独及 xdist 重跑均通过，与改动无关）
- [x] frontend: lint（错误 0，既有 警告 4）/ vitest 1,230 通过 / build 成功
- [x] docs/refactoring-plan-2026-07.md 矩阵标记完成 + 更正 pyright 错误
- [ ] 推送（`SKILL_EVALUATION_ENABLED=true`）+ PR

## 剩余/后续
- pyright 968 错误消减跟踪（另行处理）
- IX-2（pre-commit）需要重新评估计划文档：提交过程中确认 husky+lint-staged 已在 staged 文件上执行 ruff/eslint — 实际已覆盖
