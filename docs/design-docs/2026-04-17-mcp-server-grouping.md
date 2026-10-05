# ADR：按 MCP 服务器分组 + 服务器级认证

**日期**：2026-04-17
**状态**：已决定
**上下文**：feature/mcp-server-grouping
**详细计划**：`~/.claude/plans/mcp-idempotent-avalanche.md`

## 决定

在 `/tools` 页面中，不以扁平列表展示 MCP 工具，而是按 **MCP 服务器分组卡片** 展示。认证按**服务器级别设置一次**，并应用到该服务器下全部工具。

## 权衡

| 决定 | 采用原因 | 替代方案 |
|---|---|---|
| Backend：新增 3 个 `/api/tools/mcp-servers` 路由（GET/PATCH/DELETE） | 符合 REST collection 惯例，且 `tool_service.get_mcp_servers()` 已存在 | 扩展现有 `/api/tools` 响应（服务器 metadata 不足） |
| Runtime：MCP 工具只使用 server-level credential（忽略 tool-level） | 与 UI 策略一致——既然隐藏 tool-level auth UI，runtime 也应统一 | 保留现有 fallback chain（UI/runtime 策略不一致） |
| Frontend：自行实现 Collapsible | 避免增加 dependency，不到 30 行 | shadcn-ui add accordion（不必要的 dependency） |
| 不支持删除组内单个工具 | MCP 工具依赖服务器——即使单独删除，下次 fetch 仍会重新出现 | 允许删除（容易造成混乱） |
| 无 DB migration | schema 变更为 0。现有 `tool.credential_id` 会在 runtime 中自然忽略 | 自动 migration script（手动选项已足够） |

## 影响范围

- Backend: `schemas/tool.py`, `services/tool_service.py`, `services/chat_service.py`, `routers/tools.py`, `tests/test_tools.py`
- Frontend：`lib/types/index.ts`, `lib/api/tools.ts`, `lib/hooks/use-tools.ts`, `app/tools/page.tsx`, `components/tool/mcp-server-{group-card,auth-dialog,rename-dialog}.tsx`（新增）, `components/tool/mcp-auth-dialog.tsx`（删除）, `messages/ko.json`

## 未解决（backlog）

- 清理现有 `tool.credential_id` 数据的 script（`scripts/migrate_mcp_credentials.py` 选项）
- MCP 服务器启用/禁用 toggle（仅保留 status 字段）
- 将 `lazy="joined"` → `selectinload`（HANDOFF backlog D）
