# CHECKPOINT — 自定义工具 credential 集成（backlog B）

**分支**：`feature/custom-tool-credentials`
**plan**：`~/.claude/plans/mcp-idempotent-avalanche.md`
**开始**：2026-04-17

## M1: Backend — 允许 CUSTOM 类型 PATCH + 测试

- [x] services/tool_service.py:266-269 — 在 `update_tool_auth_config` 中加入 CUSTOM，扩展 owner check
- [x] tests/test_tools.py — 新增 `test_update_custom_tool_credential` + `test_update_custom_tool_unset_credential` 2 条
- [x] tests/test_tools_router_extended.py — 将语义反转的 `test_update_auth_config_non_prebuilt_returns_404` 更新为验证 IDOR（其他用户 CUSTOM → 404）
- 验证：`cd backend && uv run ruff check . && uv run pytest`
- done-when：新增 2 条通过，回归 0
- 状态：done（ruff PASS，539 passed）
- 负责人：Jensen

## M2: Frontend — 自定义工具 credential UI

- [x] components/tool/custom-auth-dialog.tsx（新增）— 采用 PrebuiltAuthDialog 模式，不做 provider filter
- [x] components/tool/add-tool-dialog.tsx — 移除 custom tab inline auth + 集成 CredentialSelect
- [x] app/tools/page.tsx — ToolCard isCustom 分支增加"认证设置"按钮 + 状态 badge
- [x] messages/ko.json — 新增 `tool.customAuth.*`
- [x] tests/components/tool/add-tool-dialog.test.tsx — 按新 credential UI 更新
- [x] lib/types/index.ts — ToolCustomCreateRequest 增加 credential_id
- 验证：`cd frontend && pnpm lint && pnpm build` PASS，`pnpm test add-tool-dialog` 11/11 PASS
- done-when: build PASS, lint 0 errors
- 状态：done
- 负责人：Zuckerberg

## M3: 集成验证 + HANDOFF

- [x] backend 回归：`cd backend && uv run pytest` — 539 passed
- [x] frontend full build：`cd frontend && pnpm build` — 14 routes，lint 0 errors
- [x] 更新 HANDOFF.md（backlog B 完成，下一个是 backlog C）
- 验证：backend ruff PASS，pytest 539 passed；frontend lint PASS，build PASS
- done-when：回归 0，HANDOFF 更新
- 状态：done
- 负责人：Bezos
