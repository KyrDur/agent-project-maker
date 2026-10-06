# SPEC — 技能工作室 Phase 1：技能构建器聊天（迁移至主聊天）

| 项目 | 内容 |
|------|------|
| 状态 | Draft v1 — 等待审查 |
| 编写日期 | 2026-07-07 |
| 分支 | `feature/skill-builder-chat` |
| 前置决策 | 确认选项 B（真正的多轮 tool-using Agent）。确认 5 项产品决策（§1.3） |
| 相关 | ADR-013(System LLM credential), ADR-018(相对 storage path), ADR-019(System LLM Settings), M59(conversation_artifacts), M64(skill_builder_sessions), `docs/design-docs/chat-feature-gap-analysis.md`(G1) |
| Mockup | `~/Downloads/Web-Prototype_skill/skill-studio.html` — 构建器视图（“原样带入主聊天的构建器对话” + 验证侧边栏）是 Phase 1 的目标 |

---

## 1. 背景与目标

### 1.1 当前状态（问题）

现有“技能构建器对话”并不是真正的对话：

- Draft 通过结构化 JSON **每次用 1 次调用重新生成整个 package**（`JsonChatDraftWorker`, `app/agent_runtime/skill_builder/graph.py:46-68`）。不会把之前的消息传给 LLM（输入仅 `{intent, mode, base_snapshot}`，`graph.py:210-215`）。
- 生产路径没有 checkpointer — 状态保存在 `skill_builder_sessions` 的 JSON 列中。
- SSE 用**伪脚本发出** 12 种事件（`services/skill_builder_workflow.py:96-143`），前端除 `error` 外全部忽略（`skill-builder-stream-events.ts`）。`content_delta` 也是 no-op — 不渲染 Assistant 文本。
- 前端是请求 textarea + Start 按钮的 2-pane 对话框（`skill-builder-dialog.tsx`）。没有气泡/多轮/附件/HITL。
- 构建器 session 评估会生成**伪结果**（`skill_builder_eval_service.py:44-60` — 操纵为 all-pass/all-fail）。

### 1.2 目标

把技能创建·改进改成**与主聊天相同的真正多轮对话**。Agent **逐步实际编辑** Draft 文件，用户可在对话过程中**立即用自己的示例测试**，最终确认通过 **HITL 审批卡**完成。右侧**验证栏**实时反映 Draft 状态与验证结果。

### 1.3 已确认的产品决策 (2026-07-06)

1. **内联“用示例测试” = 核心功能。** 通过 Draft workspace + scoped consent(HITL) 正面实现。禁止绕过。
2. **移除“未保存”概念。** working tree（Draft workspace，持续持久化）/ commit（revision，显式确认）模型。
3. **Benchmark 使用真正的 A/B**（Phase 3 — 超出本 spec 范围，§11）。
4. **成本·连接计数使用真实数据**（Phase 2/3 — 超出范围，§11）。
5. **真正基于路由的全页面 Studio**（Phase 2 — 本 spec 仅新增 builder 路由）。

### 1.4 项目路线图

| Phase | 内容 | spec |
|-------|------|------|
| **1（本 spec）** | 技能构建器 → 迁移到主聊天 runtime：隐藏 builder Agent、Draft workspace、5 种工具、HITL session consent、验证栏、`/skills/builder/[sessionId]` 路由 | 本文档 |
| 2 | Studio IA（5-tab 路由）、列表表格+bulk、版本 SKILL.md diff、已连接 Agent 真实计数、credentials/metadata tab 重新布局 | 另行 |
| 3 | 评估真实性：真实 with/without A/B、真实成本核算、case 人工反馈、按版本的通过率趋势 | 另行 |

---

## 2. 成功标准（可验证）

1. 用户从 `/skills` → “通过对话创建” → 在聊天中经过多轮说明·修改技能后，Agent 用 `write_file`/`edit_file` **逐步编辑** `SKILL.md`·`references/`·`evals/evals.json`（并非每轮重新生成全部内容 — 对话历史保留在 checkpoint 中）。
2. 用户说“用这个示例测试一下”（可包含附件）时，`test_skill_draft` 在 sandbox 中执行**保存前 Draft**并把结果显示在聊天里。首次执行显示审批卡；选择“本 session 持续允许”后，后续执行无需卡片。
3. `finalize_skill` **始终**弹出审批卡，批准后创建真实 `skills` row + `skill_revisions` revision（创建/改进均如此）。改进模式下若原始内容已变更，则以 `SOURCE_SKILL_CHANGED` 失败，并由 Agent 向用户说明。
4. 右侧验证栏显示 Draft 文件列表·验证状态（错误/警告）·兼容性，并在**reload 后**通过事件 replay 恢复。
5. 即使关闭浏览器后重新打开，session·对话·Draft 仍可原样恢复（Draft = 磁盘，对话 = checkpointer，session = DB）。
6. 验证：backend pytest 全绿、vitest 全绿、tsc/eslint 全绿、新增 E2E(scripted model) 全绿，并通过 capture tour 为每项成功标准提供视觉证据。

---

## 3. 架构决策

### AD-1. 执行表面 = 真实 v3 主聊天 runtime + per-user 隐藏 builder Agent row

**决策**：为每位用户 **lazy-seed** 一个 `runtime_profile='skill_builder'` 的真实 `agents` row（首次进入 builder 时创建），builder 对话作为该 Agent 的**真实 conversation**运行在 v3 agent-protocol 之上。

**依据**（已完成源码验证）：
- `conversations` 没有 `user_id` — 所有权完全通过 `Agent.user_id` join 强制执行（`chat_service.py:967-984`, `get_owned_thread` `conversation_agent_protocol_runtime.py:31-44`）。只要 row 属于用户，**整个 v3 栈（command/stream/HITL/checkpoint fork/runs/重连/message_events 持久化/artifact/usage）无需改动即可运行**。
- `user_id IS NULL` 的系统 Agent 需要全面重写所有权 join，因此否决。builder_v3 式单独 wire 会放弃 message_events 持久化、runs、重连和 artifact rail，因此否决（`use-chat-runtime.ts:1084-1091` — 重连仅适用于 conversations 路由）。
- 精确先例：assistant panel 已证明“代码定义 prompt + 代码构建工具 + build_agent”（`assistant/assistant_agent.py:55-99`）可行 — 只是那里使用 legacy wire，本 spec 在 **v3 路径内部**采用相同组装方式。

**需要的变更**：
- 新增 `agents.runtime_profile` 列（migration，`varchar`，default `'standard'`，值：`standard|skill_builder`）。
- 防止列表污染：在 `agent_service.list_agents`（`agent_service.py:68`）/`list_agent_summaries`（`:87,:137`）中加 `runtime_profile='standard'` 过滤。Dashboard/每日对话聚合等**跨 Agent 聚合也要排除**（实现时必须 grep 使用处）。
- 防止篡改：`PUT/DELETE /api/agents/{id}`（`routers/agents.py:191,260`）若 `runtime_profile!='standard'` 则返回 404（遵守 enumeration-safe 规则 — 不是 403）。
- 模型：隐藏 row 的 `model_id` 只是 seed 时的值，**runtime 始终通过 `resolve_system_model(db,'text_primary')` 重新解析**（ADR-019；与当前 builder 相同 — `skill_builder/agent.py:18-32`）。未配置时保持现有 `SYSTEM_LLM_NOT_CONFIGURED` 契约。

### AD-2. Draft workspace = `data/skill-drafts/<session_id>/` 可写虚拟 mount

**决策**：每个 session 创建物理目录 `data/skill-drafts/<session_id>/`，并以虚拟路径 `/skill-drafts/<session_id>/` 暴露给 Agent。Agent 直接通过 deepagents 标准 `write_file`/`edit_file`/`read_file`/`ls` 编辑。

**依据**：FilesystemBackend 使用单一 root（`backend/data`）+ virtual_mode，因此 `data/` 下内容自动可寻址（`runtime_component_builder.py:657`, deepagents `backends/filesystem.py:176-217`）。是否可写纯粹是权限规则问题 — 只要在 `build_filesystem_permissions`（`filesystem_permissions.py:21-82`）的 `/**` write-deny（`:79`）**之前**插入该 session 子树的 allow read+write 规则即可。

**规则**（顺序重要，first-match-wins）：
1. allow read+write `/skill-drafts/<本 session id>/**`
2. deny read+write `/skill-drafts/**`（阻断其他 session — unmatched 默认 allow，因此必需）
3. 保持现有规则。**额外安全修复**：出于同样原因，目前 `/uploads` 因默认 allow 暴露（跨用户暴露）— 本次一并加入 deny 规则（§6）。

**行为特性**（实现时写入 prompt）：
- deepagents `write()` 拒绝覆盖现有文件（`filesystem.py:486-488`）→ 修改使用 `edit_file`。在 builder prompt 中明确。
- 改进(improve)模式：session 开始时把原技能文件**复制**到 workspace（技能 mount 的 copytree 先例 — `skill_runtime.py:181-213`，禁止 symlink）+ 记录 `base_content_hash`（继承现有冲突模型）。
- 附件：run 开始时，把连接到对话的上传文件（`message_attachments.storage_path`，文件位于 `data/uploads/<uuid><ext>` — `uploads.py:135`）**复制**到 `<workspace>/inputs/<原文件名>`。解决 G1 gap（附件未传给模型）的 builder scope 问题 — 禁止 mount 整个 uploads（§6）。
- GC：复制 `cleanup_stale_runtime_roots` skeleton（`skill_runtime.py:381-418` + `scheduler.py:679-725` 注册模式），但**按 session 状态而非 mtime**（active/confirming session 在 abandon horizon 内保留，仅 `completed`/`abandoned` 超过 retention 后删除）。配置：`skill_draft_gc_retention_hours`。（R 更新）对话已丢失的 session（超过 retention）以及 `skill_draft_abandon_days`（默认 14 天）无活动 session 转为 `abandoned`，分两阶段回收 — 没有转移路径的 abandoned 原本是失效的 GC 规则（/review 发现）。

### AD-3. 工具集（代码构建，5 种 + FS 基础）

在 `_prepare_runtime_components`（`runtime_component_builder.py:571-749`）中新增 `cfg.runtime_profile == 'skill_builder'` 分支。分支内：使用代码定义 system prompt（`prompt.md` 加载模式 — `assistant_agent.py:31-44`），**跳过** `tools_config` 循环、`execute_in_skill`、memory 工具和 subagents，append 下列工具。保留 `ask_user`（`:727-728`）和 temporal 工具（澄清问题需要）。

| 工具 | 行为 | 复用（全部为现有函数） | HITL |
|------|------|------|------|
| (FS 基础) `ls/read_file/write_file/edit_file` | Draft 编辑 | deepagents FilesystemMiddleware — 无额外工作，权限负责 scope | write/edit：实现时决定是否保留 deepagents 默认风险元数据（为防止过度审批，建议 workspace 内排除 interrupt — 使用 fs 权限 allow，而不是 `interrupt` 模式） |
| `validate_skill` | Draft dir → `SkillDraftFile` 列表 adapter → 验证+兼容性。结果同时提供给模型和验证栏（§AD-5） | `validate_draft_package`（`skills/validator.py:29-78`）、`check_portable_compatibility`（`compatibility.py:30-110`）。输入契约：`Sequence[SkillDraftFile]`（text-only — binary skip，`errors="replace"` 先例 `skill_builder_service.py:162-191`） | 无（只读） |
| `test_skill_draft` | 在 sandbox 中执行 Draft。fabricated descriptor `{id: session uuid, slug, storage_path: 'skill-drafts/<sid>'}` → `build_skill_runtime_context(output_root=data/skill-draft-runs)` → `run_eval_skill_command` | descriptor **dict-driven，无需 DB row**（`skill_runtime.py:216-248`；credential 解析对 missing row 静默 skip `:344-346`）。自动应用完整 subprocess 策略：allowlist/timeout（默认 30s，cap 420s）/`requires_network` curl gate/SSRF 策略/credential env/`redact_credential_values`/output 收集（`skill_executor.py:37-217`, `skill_execution_policy.py`） | CODE_EXECUTION(approve/reject) + **session consent**（AD-4） |
| `generate_evals` | 生成评估 case → 将 `evals/evals.json` 写入 Draft | `select_eval_template`+`generate_eval_cases`（`eval_case_generator.py:7-74`），schema guard `parse_evals_json`+limits（`eval_limits.py:5-8`）。finalize 自动收集该文件（`skill_builder_evaluations.py:129-147`） | 无 |
| `finalize_skill` | 确认：重新验证 → `claim_for_confirming` → Draft zip → skills row + revision | zip 基于**workspace 磁盘** `build_workspace_zip_bytes`（`skill_draft_workspace.py` → `build_skill_zip_bytes_from_dir`, Phase 1.5）— 将 text adapter 无法承载的 binary asset 原字节包含进去（排除 `inputs/`·`evals/`，skip symlink）。REST `/confirm` 保持已发布 `draft_package` 契约（text zip）。创建：`create_package_skill`（重新经过完整 zip 防护，`service.py:136-188`）+ `unique_skill_slug`。改进：`lock_skill_for_mutation` → 检查 `base_content_hash` → `SOURCE_SKILL_CHANGED` → `replace_skill_storage`（`skill_builder_package_storage.py:22-42`）。revision `builder_create/builder_improvement`（`skill_revision_service.py:31-74`）。finalize 前必须通过 secret scan（`marketplace.secret_scan`）。zip 超上限等 packager guard 失败以 `PACKAGE_INVALID` 解除 claim 后报告 | **始终审批卡**（不允许 session consent） |

工具的 DB 访问：通过**session factory closure**传递，避免把 request-scoped session 固定到长生命周期 stream（先例：memory 工具在 run 中写 DB — `runtime_component_builder.py:629-639`；assistant 工具 closure 模式 `assistant_agent.py:84-87`）。

改进模式冲突（v1 策略）：`finalize_skill` 返回 `SOURCE_SKILL_CHANGED` 工具错误 → Agent 说明并提示“以最新版本开始新 session”。workspace re-seed 工具放到 Phase 1.5。

### AD-4. HITL scoped consent（“本 session 持续允许”）

**决策**：给 `test_skill_draft` 添加 `attach_tool_risk`（CODE_EXECUTION，`risk.py:134-150` 模式），默认每次调用都显示审批卡。在审批卡中新增**“本 session 持续允许”**选项，选择后：

1. 前端在 `input.respond` decisions 中带上扩展字段（例如 `scope: "session"`）。
2. 后端 command handler（`conversation_agent_protocol_commands.py:216-317`）把它**记录为 session row 的 consent 状态**，并且只向 middleware **传标准 `approve`** — 非标准 decision type 会让 langchain middleware 抛出 ValueError（`human_in_the_loop.py:343-349`）。绝不能原样下传。
3. `resolve_agent_context` 将 consent 状态 threading 到 `AgentConfig` → `_build_interrupt_on_policy`（`runtime_component_builder.py:363-392`）把 `test_skill_draft` 从策略中排除。
4. **时序保证**：Agent 会在**每次 resume 时重建**（`langgraph_agent_stream_runner.py:89`）— consent 只在 interrupt 响应时发生，因此从 consent 后紧接着的 resume 起立即生效。无需 run 中途动态修改。

**边界**：若 Draft `execution_profile.requires_network == true`，则**不能**使用 session consent（每次都显示卡片）。如需条件策略，使用 middleware 原生支持的 `when` predicate（`human_in_the_loop.py:194-213`）。`finalize_skill` 始终显示卡片。

前端：在 `review_configs` 带上可 session consent flag，让 approval-card 条件渲染该选项（沿用 `allowed_decisions` gate 模式 — `approval-card.tsx:477-486`）。

### AD-5. 验证栏 = 现有自定义 side-channel event 模式

**决策**：用两类事件驱动 rail（两者都复制现有契约）：

1. **`moldy.skill_draft`** — stream-head 1 次，stable id `f"{run_id}:skill_draft"`（先例：`_memory_recalled_event`, `langgraph_streaming.py:214-266`）。payload：session id/mode/slug/文件列表摘要/相对 base 的变更数。prepare 时放入 `AgentConfig` 字段（`runtime_config.py:59-65` 模式）。
2. **`moldy.skill_validation`** — `validate_skill`/`finalize_skill` 工具结果 projection（先例：`UI_DATA_TOOL_TRANSFORMERS`, `ui_data_projection.py:63-65`；收集 `protocol_side_effects.py:223-265`）。payload：沿用现有 `validation_result`/`compatibility_result` schema（目的是复用前端 panel）。

**必须注册**（CLAUDE.md 规则）：在 `event_names.py:33-58` 加名称 + 注册到 `protocol_redaction.py` 的自定义事件 matcher（即使 payload 不含 secret，漏注册也有回归风险）。wire/persist 双重 redaction 通过 `emit()` 自动完成（`langgraph_streaming.py:338-345`, `protocol_persistence.py:15-24`）。

前端：`useChannelEffect(stream, ['custom'], {replay:true})` + Jotai atom + 对话 scope dedup（沿用先例：`subagent-names-events.ts:76-106`, `data-ui-events.ts:196-251` — dedup 按 entity id，对话切换时重置 seen）。rail panel 复用现有组件：`skill-builder-preview*.tsx` 的 ValidationPanel/PortableCompatibilityPanel/文件摘要（payload shape 不变，因此大部分可保留）。

### AD-6. session·conversation 映射与入口流程

- `skill_builder_sessions` v2：`conversation_id`（FK conversations，nullable，index — `m64:54-58` 索引模式）、`draft_workspace_path`（ADR-018 **相对路径**，必须 `ensure_relative` — `storage/paths.py:44-54`）。`messages`/`draft_package` JSON 不再作为 source of truth（派生/legacy）。整理状态机：`active → confirming → completed` + `abandoned`（GC 对象）— 已确认现有 `drafting/failed/cancelled` 未使用（dead state）。
- 启动流程：`POST /api/skill-builder`(v2) = 隐藏 Agent lazy-seed → 创建 session row + workspace（+improve 时复制原内容）→ 创建 draft conversation（复用 `conversation_crud.py:206-232`）→ 返回 `{session_id, agent_id, conversation_id}` → 前端跳转 `/skills/builder/[sessionId]`。
- 删除项：`POST /{id}/messages`·`/messages/resume`（伪 SSE，`routers/skill_builder.py:97-142`）和整个 `skill_builder_workflow.py`、one-pass graph（`graph.py` 5 个 node·两个 worker）、`SkillBuilderState`、伪评估（`skill_builder_eval_service.py:44-60`）、前端 `skill-builder-dialog.tsx`+`stream-skill-builder-message.ts`。`GET /{id}`·`/validate`·`/confirm` 适配后保留（confirm 以工具路径为主，REST 用于 session 状态查询/管理）。

---

## 4. 后端详细设计

### 4.1 迁移（编号以实现时 head 为准，M67~）

1. `agents.runtime_profile varchar NOT NULL DEFAULT 'standard'` + 无需 index（列表过滤以 user_id 为前导）。
2. `skill_builder_sessions`：`conversation_id Uuid NULL FK conversations.id ON DELETE SET NULL` + index，`draft_workspace_path varchar(500) NULL`，（可选）`tool_consents JSON NULL`（保存 AD-4 consent）。

### 4.2 新增/变更模块

| 模块 | 职责 |
|------|------|
| `app/agent_runtime/skill_builder/prompt.md`（新增） | builder system prompt：收集目的 → 渐进编辑（`edit_file` 使用规则）→ 验证 → 测试 → 建议 finalize。Portable skill 原则（继承现有 prompt.md：SKILL.md <500 行，trigger 放在 frontmatter description，拆分 references/，禁止 secrets） |
| `app/services/skill_draft_workspace.py`（新增） | workspace 创建/seed（improve 复制）/附件复制（`inputs/`）/目录→`SkillDraftFile` adapter/GC。路径全部使用 `ensure_relative`/`resolve_data_path` |
| `app/agent_runtime/skill_builder/tools.py`（新增） | AD-3 的 5 种工具（closure + session factory）。附加 `attach_tool_risk` |
| `runtime_component_builder.py`（分支） | `cfg.runtime_profile=='skill_builder'` 分支：替换 prompt、替换工具集、Draft mount 权限、装载 `moldy.skill_draft` payload |
| `conversation_stream_service.py`（扩展） | `resolve_agent_context`：读取 runtime_profile、重新解析 System LLM、查询 session（conversation_id 反查）、thread consent 状态、触发附件→`inputs/` 复制 |
| `filesystem_permissions.py`（扩展） | Draft mount allow + sibling deny + `/uploads` deny |
| `conversation_agent_protocol_commands.py`（扩展） | 记录 `input.respond` 的 `scope:"session"` consent（对 middleware 仅传标准 approve） |
| `ui_data_projection.py`/`event_names.py`/`protocol_redaction.py`（扩展） | 注册 `moldy.skill_draft`/`moldy.skill_validation` |
| `routers/skill_builder.py`（改造） | start v2 / get / abandon。删除 messages·resume |
| `app/scheduler.py`（扩展） | 注册 drafts GC job（leader-only，`replace_existing` — `:699-725` 模式） |

### 4.3 审计事件（继承现有词汇）

`skill_builder.session_create`（继承 `routers/skill_builder.py:77`）、`skill_builder.draft_test`（新增 — 执行 test_skill_draft，sandbox denial 由现有 `skill_executor` 自动审计）、`skill_builder.confirm_create`/`apply_improvement`（`:244,:261-264`）+ `skill_revision.create`（`skill_builder_audit.py:66-83`）、`skill_builder.secret_scan_blocked`（`skill_builder_support.py:118`）、`skill_builder.apply_conflict`（`:216`）。

---

## 5. 前端详细设计

### 5.1 路由/入口

- 新增 `/skills/builder/[sessionId]/page.tsx`：查询 session → 将 `ChatRuntimeSection`（`chat-runtime-section.tsx:116-134`）以 `{agentId(隐藏), conversationId}` mount。原样继承主聊天 surface（AssistantThread v3）— composer/附件/HITL 卡/token gauge/重连。
- 替换入口：`SkillCreateDialog` chat tab（`skill-create-tabs.tsx:14`）和详情 dialog 的 “improve by chat”（`skill-detail-dialog.tsx:122`）调用 start v2 后跳到新路由。删除 `SkillBuilderDialog`。
- 自动首条消息（Phase 1.5）：首次进入 builder 页面时，dialog 的 `user_request` 自动作为第一条 user message 发出（`skill-builder-auto-request.tsx` — 在 composerHint slot 中 thread append）。guard：session `active` + envelope resolved + 对话 0 条 + 无 run 历史（防 reload/中断 run 重发）。create/improve 通用。
- finalize 完成时：完成卡跳转 `/skills?detailId=<skill_id>` deeplink（Phase 2 升级为 Studio 路由）。

### 5.2 验证栏

- 新增 `skill-builder-rail.tsx`：由 `moldy.skill_draft`/`moldy.skill_validation` hook+atom 驱动。复用 panel：ValidationPanel·PortableCompatibilityPanel（`skill-builder-preview*.tsx` 保留部分）、Draft 文件树（read-only）、改进模式变更摘要（继承 `fileDiffSummary` 逻辑 — `skill-builder-preview-model.ts:98-134`）。
- rail 布局沿用现有 artifact 右侧 rail 模式。移动端折叠。

### 5.3 审批卡扩展

- `review_configs` 的 session consent flag → approval-card 新增“本 session 持续允许”选项（checkbox/辅助按钮）。选择后在 decisions 中附加 `scope:"session"`。遵循与 `allowed_decisions` gate（`approval-card.tsx:477-486`）相同的条件渲染原则。
- 注意（现有规则）：审批卡代表的 raw tool call pill 去重继续遵守 `stripInterruptedRawToolCalls` 契约 — 确认 `test_skill_draft`/`finalize_skill` 也纳入匹配对象。

### 5.4 i18n

- 新增 namespace `skillBuilderChat`（rail/card/入口）。现有 `skill.builderDialog` key 中验证/兼容性/冲突 key 因 payload shape 不变可迁移复用。**注意**：在 navigator/root layout 中打开的 dialog 位于 chat scope 外（export dialog 先例）— rail 在 chat 页面内部，因此 chat scope 足够。

---

## 6. 安全

1. **权限规则顺序**：session Draft allow → `/skill-drafts/**` deny → 现有规则 → `/**` write-deny。由于 first-match-wins（`deepagents middleware/filesystem.py:126-136`），顺序本身就是安全边界。
2. **封堵 `/uploads` 默认 allow 漏洞**：当前 unmatched 默认 allow，使任意 Agent 可 `ls("/uploads")`（跨用户暴露，研究已验证）。本次加入 deny — 这是与 builder 无关的**现有漏洞修复**，单独 commit。
3. **附件复制，禁止 mount**：只把连接到对话的附件复制到 `<workspace>/inputs/`。uploads 整体 read mount 违反 scope。
4. **finalize 前必须 secret scan**（`marketplace.secret_scan` — 上传路径先例 `skill_uploads.py:57-62`）。阻断时记录 `secret_scan_blocked` 审计。
5. **重新经过 zip 防护**：finalize 经由 `create_package_skill`，因此再次通过 `extract_package` 的 symlink/zip-slip/null-byte/size(50MB)/count(1000) 防护（`packager.py:67-80`, `config.py:106-107`）。
6. **原样继承 subprocess 策略**：`test_skill_draft` 使用与 `execute_in_skill` 相同的 context 策略（allowlist/timeout/SSRF/redaction）— 不创建新的执行表面。
7. **注册事件 redaction**：把新的 moldy.* 事件注册到 `_redact_custom_event` matcher（CLAUDE.md 规则）。事件中不携带 Draft 文件内容（仅摘要·计数）— 文件内容只通过工具结果/FS 读取。
8. **enumeration-safe**：session/Agent 查询失败统一返回 404。

---

## 7. 测试计划

### 后端（pytest, aiosqlite）
- Workspace：创建/seed（improve 复制）/附件复制/adapter（binary skip）/GC（按状态 — 保留 active）。
- 权限：Draft mount allow/sibling deny/`/uploads` deny（permission rule 单元测试）。
- 工具：validate（issue shape）/test（fabricated descriptor 执行 + policy gate + 拒绝 slug 不一致）/generate_evals（写文件+schema guard）/finalize create·improve（+`SOURCE_SKILL_CHANGED`+secret scan 阻断+slug 冲突）。
- HITL：记录 `scope:"session"` + 转换为标准 approve（断言非标准 type 不会到达 middleware），requires_network Draft 不允许 consent。
- 事件：`moldy.skill_draft` stable-id、`moldy.skill_validation` projection、persist redaction 通过。
- runtime_profile：列表过滤/PUT·DELETE 404/System LLM 重解析/未配置错误。

### 前端（vitest）
- rail hook/atom（replay dedup、对话 scope reset）、panel 复用渲染、审批卡 session consent 选项（按 flag 条件显示）、入口流程。
- **遵守共享 transport mock 规则**：`MoldyAgentServerAdapter` 接口变更时统一更新 `createMockTransport()` + 全量 `pnpm vitest run`。

### E2E（scripted model + throwaway stack）
- 新增 marker `E2E_SKILL_BUILDER`：scripted 序列 = write_file(SKILL.md) → validate_skill → test_skill_draft（审批卡→session consent→第 2 次无卡）→ finalize_skill（审批卡→批准）→ 断言 skills row。（扩展 `e2e_scripted_model.py` — wave2 marker 先例。）
- reload replay：恢复 rail + 不存在 `<redacted>`。
- capture tour：入口/多轮编辑/测试卡/session consent/rail/finalize/完成 deeplink（§2 证据）。
- 注意（既有经验）：第一个 spec self-warm，`settle()` networkidle 5s cap，禁止 ask_user resume，fresh ports。

---

## 8. 实现里程碑（展开到 CHECKPOINT.md）

| M | 内容 | done-when |
|---|------|-----------|
| M1 | 2 个 migration + runtime_profile 过滤/guard + 隐藏 Agent lazy-seed + start v2 | pytest：seed/过滤/404 guard 全绿 |
| M2 | workspace 服务 + 权限规则（+`/uploads` 修复）+ GC job | pytest：workspace/权限/GC 全绿 |
| M3 | runtime 分支（prompt/工具骨架）+ validate_skill + generate_evals + 2 种事件 | pytest：工具/事件全绿，手动对话确认 SKILL.md 渐进编辑 |
| M4 | test_skill_draft + HITL session consent（后端+前端卡） | pytest+vitest 全绿，E2E consent 流程 |
| M5 | finalize_skill（创建/改进+冲突）+ audit + 完成 deeplink | pytest：finalize 全 case 通过 |
| M6 | 前端路由/rail/入口替换 + 删除旧路径 + i18n + E2E/capture 全部 | §2 成功标准全部满足，全套 suite 全绿 |

每个里程碑完成后 commit。使用 `SKILL_EVALUATION_ENABLED=true` 做 push 验证（既有经验）。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|--------|------|
| 隐藏 Agent 泄漏到列表/聚合/navigator | M1 全量 grep 使用处 + 过滤，E2E 断言列表中不存在 |
| deepagents write 拒绝（覆盖）导致 Agent loop | prompt 明确 edit_file 规则 + 工具错误信息已自行提示（"Read and then make an edit"） |
| Draft 事件 payload 过大（诱惑加入文件内容） | 用 schema 固定“只放摘要”契约（pydantic+Zod allowlist — ui_data fail-safe 先例） |
| session consent 应用范围过宽 | requires_network 例外 + finalize 始终卡片 + consent 仅按工具·session 粒度 |
| improve 冲突 UX 在对话中生硬 | v1 明确错误+引导，re-seed 工具放入 Phase 1.5 backlog |
| checkpoint 过大（长 builder session） | v3 已有现成 compaction 契约（moldy.compaction）— 继承 |

---

## 10. Phase 1 范围外（明确）

- Studio 5-tab IA/列表表格/bulk/版本 diff/连接计数（Phase 2）— **✅ 已发布：
  `skill-studio-phase2-studio-spec.md`（增加设置 tab，扩展为 6-tab IA）**
- 真实 with/without A/B benchmark·真实成本核算·人工反馈·按版本通过率（Phase 3）
- workspace re-seed（改进冲突后继续）、文本技能专用轻量流程、基于 LLM 的 eval case 质量改进、trigger 适配性工具化（Phase 1.5 backlog）
- G1 多模态通用解决方案（本 spec 仅通过 builder scope 复制解决）

## 11. Open questions（实现前需确认）

1. 隐藏 Agent 的对话会暴露在**Dashboard 最近对话/每日聚合**哪些表面 — M1 grep 时确认准确列表。
2. 是否允许分享 builder 对话（share link）— v1 默认允许且不做特殊处理（redaction 契约已应用）。如有异议则阻断。
3. 是否把 `test_skill_draft` 的输出文件（`data/skill-draft-runs/`）暴露到对话 artifact rail — v1：仅工具结果文本（评估复用 terminal ui_data projection）。
