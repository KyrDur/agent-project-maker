# CHECKPOINT — backlog E M5 · UI 集成 + 吸收 F（仅 frontend）

**分支**：`feature/backlog-e-m5`
**worktree**: `/Users/chester/dev/natural-mold/.claude/worktrees/backlog-e-m5`
**base**：main @ `12d3d18`（PR #57 merge — M4 HANDOFF docs 后续）
**ADR**: `docs/design-docs/adr-008-connection-entity.md`
**执行计划**：`docs/exec-plans/active/backlog-e-connection-refactor.md`（§4 M5）
**团队**：Tim Cook（UX spec + design review）+ Zuckerberg（实现 DRI）+ Bezos（deletion analysis + 回归）— Satya lead

---

## scope 共识 (2026-04-19，用户批准)

| 项目 | 决策 |
|------|------|
| scope | M5 = **仅 frontend**（5 项）。`agent_tools.connection_id` override 拆到 M5.5 |
| /connections 重构深度 | **以 Connection 为中心全面重构** — 移除 Credential card，Connection 为 1 级实体。Credential 仅在 Connection detail 内暴露 |
| backend 变更 | **无** — M4 前 backend 已完成。新增 alembic / model / service 变更 0 |
| Legacy fallback | 保留到 M6 — `tool.credential_id IS NULL AND tool.auth_config` 时使用 inline auth |
| F（重复 dialog 吸收） | 在 M5 完成 — 3 个 dialog → 收敛为 1 个 ConnectionBindingDialog |
| 后续 M5.5 | `agent_tools.connection_id` override（backend m12 + chat_service + UI）。M5 merge 后单独 worktree |
| 后续 M6 | drop `tool.credential_id` / `tool.auth_config` / `tool.mcp_server_id` / `agent_tools.config` + 删除 legacy code |

---

## S0: docs/ 结构确认 [done]

- [x] main 中存在 docs/、ADR-008、exec-plan
- [x] 已将 M4 progress.txt / CHECKPOINT.md 移到 tasks/archive/
- 验证：`ls tasks/archive/progress-backlog-e-m4.txt tasks/archive/CHECKPOINT-backlog-e-m4.md`

## S1: deletion analysis（Bezos）[blockedBy: S0]

- [ ] 识别 M5 scope legacy code：
  - `components/tool/prebuilt-auth-dialog.tsx`, `custom-auth-dialog.tsx`, `mcp-server-auth-dialog.tsx` — 分析 3 类 dialog 重复 surface（删除/替换/保留分类）
  - `app/connections/page.tsx` 当前结构 — 分析 Credential card、PREBUILT section 依赖
  - `add-tool-dialog.tsx` MCP tab 当前行为（直接选择 mcp_server_id）→ connection based rewire 区域
  - `lib/api/credentials.ts` / `lib/hooks/use-credentials.ts` — /connections 重构后的使用量变化
- [ ] `tasks/deletion-analysis-e-m5.md`（立即删除 / 简化 / 暂缓到 M6）
- [ ] **必须分离**：M5.5（agent_tools.override）/M6（legacy drop）处理项要明确标记为"暂缓"
- 验证：报告存在，遵守禁止 drive-by，backend 文件 0 个

## S2: ConnectionBindingDialog shell + UX spec（Tim Cook）[blockedBy: S0]

- [ ] 编写 `docs/design-docs/m5-connection-binding-dialog-spec.md`
  - 定义 3 个 dialog（prebuilt/custom/mcp）的 common surface
  - props contract：`type: 'prebuilt' | 'custom' | 'mcp'`, `provider_name`, `tool`（or external context）, `onBound`
  - state machine：idle → loading → connection_select（现有 active connection list）→ credential_form（新建时）→ binding → success/error
  - 明确 PREBUILT vs CUSTOM vs MCP 差异（provider_name 固定 vs 可选 vs 输入 server config）
  - i18n key 命名：`connection.binding.{type}.*`
  - accessibility：focus trap，ESC 关闭，error alert（role=alert）
- [ ] 编写 `docs/design-docs/m5-connections-page-redesign-spec.md`
  - 移除 Credential card → Connection card 为 1 级实体
  - section：PREBUILT（按 provider 分组）/ CUSTOM / MCP
  - Connection detail（drawer or modal）：credential metadata、使用中的 tool list、status toggle、delete
  - "添加连接" CTA → 进入 ConnectionBindingDialog
  - empty-state copy、error display policy
- 验证：两个 spec 文档存在，Zuckerberg 读 spec 后可直接实现（soft gate）

## S3: 实现 ConnectionBindingDialog + 替换 3 个 dialog（Zuckerberg）[blockedBy: S1, S2]

- [ ] 新建 `frontend/src/components/connection/ConnectionBindingDialog.tsx` — common shell
  - Props：`type`, `provider_name?`, `triggerContext`（创建 tool / 编辑 tool / standalone）, `onBound(connection)`
  - internal state：`useConnections({type, provider_name})` 查询 → 选择现有 connection or 新建分支
  - 新建时：CredentialFormDialog → `useCreateConnection` → setQueryData seed（复用 M4 模式）
  - PREBUILT mode：provider_name 固定，仅提供 credential form
  - CUSTOM mode：吸收 M4 add-tool-dialog Custom tab 模式
  - MCP mode：server config（name, transport, url, headers）+ credential option
- [ ] 将 `prebuilt-auth-dialog.tsx` 调用改为 `ConnectionBindingDialog(type='prebuilt')`。原文件作为 thin wrapper or 删除
- [ ] 将 `custom-auth-dialog.tsx` 替换为 `ConnectionBindingDialog(type='custom')`。绝对不要碰 M4 bridge override 流程（`tool.credential_id != connection.credential_id`）— M6 再整理
- [ ] 将 `mcp-server-auth-dialog.tsx` 替换为 `ConnectionBindingDialog(type='mcp')`
- [ ] rewire `add-tool-dialog.tsx` MCP tab — 从直接选择 server → 进入 ConnectionBindingDialog（Custom tab 在 M4 已完成，不改）
- [ ] i18n `messages/ko.json` 新增 `connection.binding.*` key
- [ ] **F 吸收验证**：用 grep 确认 3 个 dialog 文件已经 thin wrapper(or 删除)（`rg "Auth.*Dialog" components/tool/`）
- 验证：pnpm lint PASS，pnpm build PASS，现有页面（agent tools tab/添加）手动回归 OK

## S4: /connections 页面以 Connection 为中心重构（Zuckerberg）[blockedBy: S2]

- [ ] 重构 `app/connections/page.tsx`
  - 移除现有 Credential card section（直接暴露 Credential → 吸收到 Connection 内）
  - section 顺序：PREBUILT（按 provider 分组）→ CUSTOM → MCP
  - 各 section header + "添加连接" CTA → 进入 ConnectionBindingDialog
  - Connection card：name, status, provider, 使用中 tool count
- [ ] Connection detail panel（推荐 drawer，也可 modal）
  - credential metadata（name，部分 masking）
  - 使用中 tool list
  - status toggle（active ↔ disabled），delete（若 tool 正在使用则 block/warn）
  - 调用 PATCH `/api/connections/{id}`（M1 已实现）
- [ ] 移除 Credential 独立管理 UI（`lib/hooks/use-credentials.ts` 为 backend compatibility 保留，仅从 UI 分离）
- [ ] empty state："还没有连接" copy + CTA
- 验证：pnpm lint PASS，pnpm build PASS，手动验证所有 connection CRUD，现有 PREBUILT flow（M3 connections 页面）回归 0

## S5: 回归验证 + 新组件测试（Bezos）[blockedBy: S3, S4]

- [ ] **backend 测试不改**（scope backend 0）。但为确认回归执行 1 次 `uv run pytest` — 保持 646
- [ ] frontend 已知 broken tests（HANDOFF known issue）在 M5 中只要不新增破坏即可，OK。确认新增失败 0
- [ ] manual E2E 场景（Bezos 编写 → Satya review）
  - PREBUILT：connections 页面 → 添加 Naver provider 连接 → 创建 tool 时自动匹配
  - CUSTOM：创建 tool → Custom tab → 新 credential → 自动创建 connection
  - MCP：创建 tool → MCP tab → 新 server connection → 注册 tool
  - 禁用 Connection → 调用 tool 时 disabled error（确认 M3/M4 fail-closed 回归）
- [ ] `tasks/manual-e2e-e-m5.md` 记录场景 + 结果
- 验证：pytest 保持 646+，pnpm lint 0 errors，pnpm build PASS，manual E2E 报告存在

## S6: 集成 + commit（Satya）[blockedBy: S5]

- [ ] 全量 verify：ruff + pytest + pnpm lint + pnpm build
- [ ] /codex:review（大规模 UI 变更 — 推荐）
- [ ] 更新 HANDOFF.md（M5 完成，下一个 = M5.5 或 M6）
- [ ] 单一 commit → PR

---

## 风险（M5 要点）

1. **吸收 3 个 dialog 时 props surface 冲突** — PREBUILT 固定 provider，CUSTOM 自由，MCP 额外 server config。单一 shell 可能变得臃肿。Tim Cook spec 中要清晰区分 type-specific sub-section（type）
2. **/connections 全面重构回归** — M3 的 PREBUILT section 已在工作。必须 manual E2E 确认用户创建的 connection 在新 UI 中全部可见
3. **add-tool-dialog MCP tab rewire** — 现有 mcp_server_id 直接选择流程。注意向新 connection-based flow 的 migration UX（已注册的 mcp_server 如何显示），connection 迁移需清晰
4. **i18n key 冲突** — 新 key `connection.binding.*`。禁止与现有 `tool.addDialog.*` 重复
5. **移除 Credential card** — credentials API 本身必须保留（在 Connection 内调用）。只移除 UI surface
6. **禁止 drive-by（M5.5/M6）** — backend `agent_tools.connection_id` 变更 0，`tool.credential_id` column drop 0。Bezos 在 S1 明确标注为"暂缓"

---

## 验证命令

```bash
cd backend
uv run ruff check .
uv run pytest                           # 保持 646+

cd ../frontend
pnpm lint
pnpm build

# F 吸收验证
rg -l "AuthDialog" frontend/src/components/tool/ | wc -l   # 0 或仅 thin wrapper
rg -l "ConnectionBindingDialog" frontend/src/components/   # 新 shell + N 个调用处
```
