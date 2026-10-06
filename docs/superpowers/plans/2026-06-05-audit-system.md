# Audit System Development Plan

## Goal

为 Moldy 添加面向用户/管理员的 audit 功能。

- 普通用户在 `Settings > 活动记录` 中只能查看与自己相关的 audit event。
- `super_user` 保留同一个个人页面，并可在管理员项的 `全部活动记录` 中查看所有用户的 event。
- event 必须能够追踪谁、何时、使用了什么功能、针对什么对象执行，以及成功/失败/阻止状态和失败原因。
- secret、prompt 正文、message 正文、API key cleartext、share token 完整值不保存到 audit metadata。

## 与 OpenTelemetry 的关系

OpenTelemetry 适合 trace/metric/log 关联和性能观测。该功能属于面向用户暴露的产品数据，需要权限/所有权/搜索/保留策略，因此直接在应用 DB 中实现。把 `request_id`, `trace_id`, `run_id` 保存到 event，以便后续与 OTel/Langfuse trace 连接。

## Backend Design

### Table

新增表 `audit_events`。

主要列：

- actor: `actor_type`, `actor_user_id`, `actor_api_key_id`, email/label snapshot
- owner: `owner_user_id`, email snapshot
- target: `target_type`, `target_id`, name snapshot, target owner
- result: `action`, `outcome`, `reason_code`, `reason_message`
- correlation: `request_id`, `trace_id`, `run_id`
- request context: `ip_address`, `user_agent`
- sanitized metadata: JSON `metadata`
- `created_at`

查询策略：

- `scope=mine`：只查询 `owner_user_id`, `actor_user_id`, `target_owner_user_id` 中与当前用户关联的 event
- `scope=all`：仅允许 `super_user`
- cursor pagination：按 `(created_at, id)` 降序

### API

`GET /api/audit-events`

过滤条件：

- `scope=mine|all`
- `limit`, `cursor`
- `action`, `target_type`, `outcome`
- `actor_user_id`, `owner_user_id`
- `request_id`, `trace_id`, `run_id`
- `created_from`, `created_to`

### Recorded Domains

Implemented audit domains:

- Auth: register, login success/failure, logout, refresh, profile/avatar changes
- Credentials: create/update/delete/test and existing credential audit bridge
- Agents: create/update/favorite/delete
- Tools: create/update/delete/run
- MCP: create/from-registry/probe/import/update/delete/test/discover
- Skills: create/upload/update/content/file/binding/delete
- Triggers: create/update/delete/run-now
- Conversations: create/update/read/delete, message send/resume/edit/regenerate/switch branch
- Share links: create/revoke without full token
- Agent API control plane: deployment create/update, key create/revoke without cleartext key
- Public Agent Runtime API: thread create, wait/stream runs by API key
- Models: create/update/delete
- System LLM settings: role update
- Marketplace: install/update/uninstall, publish/version publish, item patch, ACL, disable/enable, admin listing
- Permission/CSRF denials through the application error handler

Sensitive data handling:

- Metadata is redacted through `audit_service.sanitize_metadata`.
- Prompt/message/skill content is represented by boolean flags, counts, key lists, or lengths.
- MCP headers/env values are represented by key names only.
- API keys and share tokens are never stored in full.

## Frontend Design

Routes:

- `/settings/audit`: personal scope (`mine`)
- `/settings/admin/audit`: super_user-only all-user scope (`all`)

Navigation:

- Account section：`活动记录`
- Admin section, only for `super_user`：`全部活动记录`

UI pattern:

- Operational, dense settings view rather than a marketing page.
- Summary metrics for loaded success/failure/denied counts.
- Filter bar for action, target type, outcome, request id, run id.
- Cursor-based “load more”.
- Event list with time, outcome, action, target, actor, request/run id.
- Detail pane with actor/target/correlation fields and formatted redacted metadata JSON.

## Verification Plan

Backend:

- Unit/integration tests for core audit service and endpoint authorization.
- TDD coverage for representative mutation domains.
- Regression suite for changed routers.
- `ruff check` on touched backend files.

Frontend:

- `pnpm lint`
- `pnpm lint:design-system`
- `pnpm build` or documented reason if blocked by pre-existing type/build issues.

Browser E2E:

- Start backend and frontend with matched ports/CORS/API base.
- Log in as seeded super_user.
- Create actions that generate audit events.
- Verify `/settings/audit` shows personal events and filters.
- Verify `/settings/admin/audit` is visible to super_user and shows all scope.
- Verify detail pane does not expose sensitive values.
