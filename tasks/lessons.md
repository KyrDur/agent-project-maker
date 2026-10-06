# Lessons — Cumulative Patterns (across sessions)

## Session 9 (2026-05-31) — ask_user QuestionFlow / OptionList

### Keep HiTL tool identity stable; branch on payload mode
**情况**：为 `ask_user` 新增分阶段问题和选项列表 UI 时，本可以另外
创建 `question_flow`/`option_list` 工具。

**模式**：
1. Runtime tool name 和 interrupt policy 仍统一使用 `ask_user`。
2. `mode`/`questions`/`minSelections`/`maxSelections` 等 UI shape 放在 payload args 中。
3. Streaming bridge 从 native interrupt dict 中只移除 `type`，其余内容原样
   传给 frontend。
4. Frontend 保持 `respond(message)` contract，但 structured 回答序列化为 JSON string，
   用户看到的 receipt 则将 label text 单独保存。

**效果**：可以在不破坏既有 persisted tool call、approval policy、Builder pending-card 模式的情况下
新增 UI。若创建重复工具，策略/registry/test surface 会同时
增加，因此应避免。

### Browser harnesses belong outside the product tree and should be short-lived
**情况**：为了在不依赖本地 DB/LLM 状态的情况下，在浏览器中点击测试 React Tool UI，
在 `/private/tmp` 创建了临时 Vite harness。

**规则**：临时 测试架 容易被误认为项目配置，因此必须清楚说明用途，并
在验证后立即删除。没有功能实现理由时不要改动实际产品配置文件。

### Pending tool call + standard interrupt can double-render the same card
**情况**：Builder 先 emit pending `ask_user` AI tool call，然后在同一次 pause 中
又 emit standard interrupt event。若 Frontend 总是把 interrupt 作为 synthetic tool call
添加，就会看到两个相同的 ask_user 卡片。

**模式**：添加 interrupt synthetic tool call 前，先检查是否已经存在相同名称和相同 args 的
`ask_user` tool call。若存在，不要 push 新卡片，只在既有 args 中
合并 `hitl_*` metadata。

## Session 6 (2026-04-28) — Agent Edit Workbench

### Hybrid controlled/uncontrolled component pattern
**情况**：单个组件（`VisualSettingsFlow`）需要在两个 上下文 下表现不同 — 独立路由（internal state，自带 Save）vs 工作台 inline（上层 page state，单一 Save）。

**模式**：
1. 新增可选 props：`embedded?: boolean`、`controlledState?: {...}`、`controlledHandlers?: {...}`
2. 显式 防护：`const isControlled = embedded && !!controlledState && !!controlledHandlers`
3. 所有 read/write/useEffect/callback 都按 `isControlled` 分支。`isControlled` 时使用 props，否则使用 internal state setter
4. 自有 UI（Save 按钮等）使用 `{!embedded && <Toolbar />}` 做 conditional
5. 防止遗漏分支：验证时 grep `isControlled` 使用位置 — 确认所有 callback 中都出现

**应用时注意**：agent sync useEffect 在 controlled 模式下必须 early return，避免 internal state 覆盖 props。

### Pydantic v2 — 在两个 模式（Create + Update）中复用共享 validator
**情况**：`AgentCreate` 和 `AgentUpdate` 需要相同的 `opener_questions` 验证逻辑。

**模式**：
```python
def _validate_opener_questions(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if len(value) > 12:
        raise ValueError("最多 12 个")
    cleaned = [s.strip() for s in value]
    if any(not s for s in cleaned):
        raise ValueError("不允许空项")
    if any(len(s) > 200 for s in cleaned):
        raise ValueError("单项超过 200 字")
    return cleaned

class AgentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    opener_questions: list[str] | None = None

    @field_validator('opener_questions')
    @classmethod
    def _v_opener(cls, v): return _validate_opener_questions(v)

class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    opener_questions: list[str] | None = None

    @field_validator('opener_questions')
    @classmethod
    def _v_opener(cls, v): return _validate_opener_questions(v)
```

**Gotcha**：由于 `extra='forbid'`，新字段必须在两个 类 中**都**注册。只注册一边会返回 422。

### `_to_response` 单一路径模式
**情况**：新增响应字段时，只要某处漏掉就不会反映到响应中。

**原则**：ORM → Response 转换只放在路由器的 `_agent_to_response()` 这类单一 辅助函数 函数中。新增字段时只改这一处。

### assistant-ui composer 文本注入（发送 X）
**情况**：点击空白页的示例问题按钮/建议 小标签 时，只想把文本填进输入框，让用户自己发送。

**模式**：
```tsx
const composer = useComposerRuntime()
const onClick = (text: string) => composer.setText(text)
```

**Gotcha**：`useComposerRuntime` 只能在 `<AssistantRuntimeProvider>` 子级中使用。确认空白页组件是否是 provider 子级，否则需要抽取组件（本次会话中的 `ChatEmptyState`）。

### 使用 shadcn Tabs 构建左右分栏 工作台
**情况**：一个页面里有两组独立 Tabs。

**原则**：
- 每组 Tabs 用独立 state 管理（value/onValueChange）
- `<Tabs value={leftTab}>` + `<Tabs value={rightTab}>` 使用两个独立实例
- 不用 defaultValue，改用 controlled value（page state）

### Next.js 16 + `use(params)` 模式（原样保留）
- `params: Promise<{ agentId: string }>` 签名
- 调用 `const { agentId } = use(params)`
- 在 `use-client` 组件中可以调用 `use`

---

## Session 5 (2026-04-28) — Chat UI 稳定化 + 时间系统

### `useFormatter` (next-intl) 类型与 `Intl.DateTimeFormatOptions` 不兼容
- timeZoneName 等部分选项被 next-intl 自身类型进一步收窄
- 在 工具函数 函数中直接定义 Formatter 类型时 构建 失败
- 解法：用 `type Formatter = ReturnType<typeof useFormatter>` 直接 import

### assistant-ui — 通过 `useAssistantState` 访问 message.createdAt
- 模式：`useAssistantState((s) => (s.message as { createdAt?: Date } | undefined)?.createdAt)`
- 需要类型 类型转换 的原因：message union 类型分支

### 防止 AssistantThread 回归
- builder v3 等其他页面也在使用
- 新增视觉变更（消息时间 标签）必须通过 `showMessageTimestamp?: boolean` 可选 prop 门控
- 只在 聊天 页面传 `true`

### shadcn `DropdownMenuTrigger.render` 模式
- 用 `render={<Button ... aria-label={...} />}` 将 Button 委托为 trigger
- aria-label 必须放在 render 内，确保 a11y

### Anthropic streaming list-content
- multi-block content 以 `list[dict]` 到来时，如果只处理 `isinstance(delta, str)`，token streaming 会是 0
- 需要用共享 辅助函数 `content_to_text` 展平

### 防止 refetch 闪烁
- 调用 `setStreamingMessages([])`，若在 `finally` 中立即执行，在 refetch 到达前回答会消失
- 解法：通过 `prevMessagesRef` 的 rendering-time 比较，仅在 messages 变化后 clear

### 聊天 viewport `min-h-0`
- 若 `ThreadPrimitive.Root`/`Viewport` 没有 `min-h-0`，消息多时输入框会被挤出屏幕

---

## Session 8 (2026-05-09) — ADR-016 多用户认证集成验证（S7）

### 路由器漏掉 commit 会让失败路径中的安全副作用失效
**情况**：`auth_service.authenticate` 在密码错误时通过 `record_login_failure(db, user)` 增加计数器 → 立即 raise `AppError`。路由器（`login_endpoint`）只在 success path 调用 `await db.commit()`。raise 后 request scope 结束，`async with async_session()` exit 自动 rollback → 计数器增加永久丢失。

**影响**：failed_login_attempts 始终为 0，因此 5 次 lockout 不工作。brute-force 无限制。

**同类第二个 instance**：`rotate_refresh` 检测到 replay 时，执行 `_revoke_all_active(db, user_id)` UPDATE 后 raise。同样会 回滚 mass-revoke，使 ADR-016 §5.2 的核心防御失效。

**模式化 fix**：
1. **Best**：安全副作用函数（record_login_failure, _revoke_all_active）使用独立 short-lived session 并 commit。与路由器 transaction 分离。
2. **Worse but minimal**：路由器中使用 `try: ...; except AppError: await db.commit(); raise`。

**验证回路**：单元测试里即使只 assert `failed_login_attempts == 1` 也能捕获。集成测试暴露了 commit 边界。

### conftest 的 `verify_csrf` override 是 迁移 后维持 legacy 测试的标准模式
**情况**：S3 在 routers 中新增 `verify_csrf` Depends。既有 conftest 的 `client` fixture 不设置 cookie/header，导致所有 mutation 测试一起变成 403。149 个测试变红。

**解法**：直接新增 `app.dependency_overrides[verify_csrf] = _bypass_verify_csrf`。保留 legacy 测试意图（=验证 mutation 本身的 validation/business logic），新测试则用独立 `raw_client` fixture 验证真实 cookie+CSRF flow。

**规则**：迁移 时新增安全 dependency，应同时在 conftest 中引入显式 bypass + 新 fixture。只做一边，要么掩盖回归，要么只增加 noise。

### Test fixture 必须同时隔离 ORM identity-map 和 transaction scope
**情况**：路由器通过 `async with async_session()` 创建独立 会话 并 commit/rollback。测试的 `db` fixture 是另一 会话。即便测试执行 `db.execute(select(User))` 查询，也可能因 identity-map staleness 看不到路由器刚 commit 的变化。

**解法**：用 `_fresh_user(email)` 辅助函数 通过 `async with TestSession() as fresh: ...` 打开新 会话 查询。每次 assertion 使用新的 read 事务。SQLite in-memory 共享同一 engine，因此 commit 可见性 有保证。

### 测试应直接验证 Enumeration oracle 阻断
**情况**：即使 ADR/security.md 规则中明确要求统一"404 vs 403"，如果实际 service 实现产生分支响应，不用测试捕获就会回归。

**模式**：隔离矩阵测试（`test_multiuser_isolation.py`）对所有 owner-scoped 资源都必须 assert cross-user 访问准确返回 `404`。enumeration prevention 必须在 status code 级 hard-assert。

### m22 → m36 ADR 编号校正案例
**情况**：编写 ADR-016 时假设 迁移 编号为 m22，但真正实现时已推进到 m36。代码超前 ADR 是常见情况。

**规则**：ADR 应聚焦"做了什么决定"，而不是"属于哪个 迁移"。迁移 编号只在写代码时确定。amend ADR 时只需更新正文 + 在 Status 部分加"originally drafted assuming m22; landed as m36"之类 注记。

### AgentConfig.user_id Optional + post_init 防护 — legacy callsite 兼容范例
**情况**：若在 dataclass 中强制新增 `user_id` 字段，所有既有调用处会一次性全部崩。改为 `Optional[uuid.UUID]`，并在 `__post_init__` 中 `if self.user_id is None: raise ValueError`。

**效果**：新 callsite 不在编译时，而是在 instantiation 时验证。可以分阶段引入 迁移 安全网。

**注意**：不要永久保持 Optional — 所有 callsite 迁移 完成后，需要后续 PR 将 dataclass field 本身升级为 required，并移除 `__post_init__` 防护。

### 首个注册用户自动成为 super_user 的运维风险
**情况**：`allow_first_user_as_admin=True` 为默认值。DB 为空时，下一个注册用户会获得管理员权限。发生 事故（DB drop、灾备恢复后数据缺失等）时会成为攻击面。

**缓解**：
1. 在 `.env` 暴露按环境 开关（无需改代码，让运维可关闭）
2. 在 README/部署指南中明确"创建运维账号后立即改为 `false`"
3. 首个用户 promotion 时记录 `logger.info` 日志（用于 审计）

以上 3 项都已实现。**在指南文档中反复强调**是最薄弱部分 — 应在 `docs/QUALITY_SCORE.md` 的 Authentication 部分明确写为运维 操作。

### Mock user → real user 转移脚本的 idempotency
**情况**：`scripts/migrate_mock_to_real_user.py`（S6）可能在运维中执行两次。已 transferred 的 row 若再次 transfer，`user_id` 可能被替换。

**模式**：通过 `WHERE user_id = '00000000-0000-0000-0000-000000000001'` 限定 mock UUID。执行后删除 mock row → 第二次执行时 0 rows affected。

**规则**：数据迁移脚本必须同时具备：(1) 能精确找到来源 row 的 predicate；(2) 执行结束前移除来源痕迹；(3) 部分失败后可重跑的 idempotent 结构。

## Session 7 (2026-05-19) — Marketplace Resources Phase 1

### Pattern: 用 strict xfail 将未实现/有错误的 spec 项 pin
**情况**：在其他团队成员负责区域发现 spec 违规（例如 `service.create_package_skill` 未设置 `origin_kind`）。

**模式**：
1. 用 `@pytest.mark.xfail(reason="...", strict=True)` 写出预期行为
2. 将当前行为另行记录为 pinning test（可选）
3. 通过"?"协议向负责人报告
4. 负责人 fix 后 strict xfail 会变成 XPASS 并自动 fail → 贝索斯再 promote（移除 xfail + 删除 pinning test）

**效果**：无需越界修改即可自动检测 spec drift。是 Ralph Loop backpressure 的核心工具。

**示例**：`test_legacy_upload_package_should_set_imported_by_me`（在 M5 stage 4 自动触发）。

### Pattern: 用 ? 协议报告 cross-team boundary issue
**情况**：编写测试时发现回归，或发现超出责任边界的 错误。

**模式**：
- 用简短"?"标记 + file:line + 1 行说明 → SendMessage 给负责人
- 同时报告给萨提亚（release gate 决策者）
- 贝索斯不修改该区域代码，继续下一阶段（并行化）

**示例**：
- `tests/test_executor.py:426` Stage 2 后 deprecated assertion → 发给詹森 ?
- `install_service.install_item` lazy load on `acl_entries` → MissingGreenlet → 发给詹森 ?（M9 发现）

### Pattern: M2.5 course correction（同步修正 spec 违规）
**情况**：编写 M2 listing 测试时发现 service.py 违反 PRD §10.1 default filter（只有 `is_listed` filter mechanic，未强制 default）。

**模式**：
1. 贝索斯在发现时报告 + 测试先保持当前行为（XPASS 防护）
2. 萨提亚创建"course correction"任务 → 詹森修正 backend
3. 同步修正后贝索斯再修正测试（按预期行为重写）

**效果**：测试不只是 spec 的"实现镜像"，而是作为**spec 验证工具**运行。贝索斯的发现会立即 escalate 给 release gate 负责人（萨提亚）。

### Pattern: per-thread runtime root + selected-skill mount + credential injection + redaction（4 类安全项）
**情况**：引入 市场 后，存在访问同一用户未选 skill + 其他用户 skill 的可能（executor.py broad mount）。

**模式**：
1. 用 `SkillToolContext(thread_id, output_dir, runtime_root, descriptors)` dataclass 防止参数膨胀
2. `build_skill_runtime_context(cfg, *, data_dir)` — per-thread `copytree(symlinks=False)`
3. `_create_skill_execute_tool(ctx)` — 用 `Path(skill_dir).name` 提取 slug → `ctx.descriptors` lookup 作为安全边界
4. `resolve_runtime_credentials(ctx, *, db, cfg)` — 只注入 mapped env var，fail-fast 409
5. `redact_credential_values(text, mapped_env)` — 自动替换 subprocess result
6. `redact_keys(payload)` — 对 SSE TOOL_CALL_START.parameters 做结构化 脱敏
7. `cleanup_stale_runtime_roots(data_dir, retention_seconds=3600)` — 基于 mtime 的 GC

**规则**：
- redaction 明确使用类似 `\bsk-[A-Za-z0-9]{20,}\b` 的 boundary（防止 false-positive）
- `len < 5` 时 skip（placeholder/fragment 防护）
- 按长度排序（先替换长值 → 避免部分匹配冲突）

### Pattern: enumeration oracle envelope equality
**情况**：访问私有 item 的尝试与访问不存在 item 的尝试必须得到相同响应（security.md）。

**模式**：
- 不仅 status code，JSON envelope shape 也验证等价：`assert r_hidden.json() == r_missing.json()`
- 分支信息只记录到 `logger.info(...)` 服务端日志，响应统一

### Pattern: 多用户测试 客户端
**情况**：默认 `client` fixture 强制 super_user → 无法验证 ACL/权限矩阵。

**模式**：
```python
async def _client_for_user(user: CurrentUser) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    async def _override() -> CurrentUser: return user
    app.dependency_overrides[get_current_user] = _override
    app.dependency_overrides[verify_csrf] = _no_csrf
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
```

复用位置：`test_marketplace_access.py`、`test_marketplace_listing.py`、`test_marketplace_e2e.py`。

### Failure: stage 2 后既有 executor test deprecated
**情况**：`tests/test_executor.py:426` 用 `assert build_kwargs["skills"] == ["/skills/"]` 精确验证值 → Stage 2 补丁 后失败。

**教训**：integration test 若用 hardcoded literal 验证 production value，production 每次改动都会破。应写成**prefix/suffix 检查或动态变量比较**。

```python
# 差
assert build_kwargs["skills"] == ["/skills/"]
# 好
assert build_kwargs["skills"][0].startswith("/runtime/")
assert build_kwargs["skills"][0].endswith("/skills/")
# 或
assert build_kwargs["skills"] == [f"/runtime/{cfg.thread_id}/skills/"]
```

### Failure: install_service lazy load on acl_entries（M9 发现）
**情况**：`install_service.install_item` 执行 `db.get(MarketplaceItem, ...)` 后调用 `can_install_item(item, user)`。`can_install_item` → `can_view_item` → `item.acl_entries` lazy load → MissingGreenlet → 返回 500 instead of 404。

**教训**：当 access predicate 使用同一 ORM 模型的 relationship 时，**service-layer query 必须像 catalog_service.get_item 一样使用 selectinload(MarketplaceItem.acl_entries)**。在 access 异常处理中，``db.get`` 的捷径很危险。

**Status**：在 M9 中已用 strict xfail pin（test_marketplace_e2e.py::TestScenario_10_4_RestrictedACL::test_restricted_acl_grants_and_denies）。等待詹森 fix。

## Session 10 (2026-06-12) — Chat Navigator E2E + Base UI 菜单 错误

### 对 UI 库模块做整体 vi.mock 的两类成本
**情况**：`vi.mock('@/components/ui/dropdown-menu', () => ({...}))` 整体 mock 在 4 个
测试文件中重复。生产环境 中 `DropdownMenuLabel` 违反 Base UI 契约（GroupLabel 只能
`Menu.Group` 内），因此发生了**菜单完全无法打开的崩溃**，但 单元
测试全绿，直到 E2E 才首次发现。

**成本**：
1. mock 无法验证库的 运行时 契约（上下文 要求、事件行为）—
   只能通过"标签 存在"这类层级。
2. 组件一旦新增一个 import（例如 `DropdownMenuGroup`），使用 mock 工厂 的
   **所有**测试文件都会因为 undefined 渲染 而坏。本次在 2 个文件分别发生。

**规则**：
- 对菜单/对话框等有 上下文 契约 的 UI，不要只信 单元 mock，应保留一个真实打开的
  E2E（或无 mock 的 集成 渲染）+ 控制台 错误 为 0 的断言。
- 如果确实需要整体 mock，使用 `importOriginal` 部分 mock 或共享 mock 辅助函数，把重复
  集中到一处。

### Base UI(@base-ui/react) 菜单与 Radix 行为不同
本项目的 dropdown/tooltip 用的不是 Radix，而是 Base UI。E2E/实现时注意：
1. `Menu.GroupLabel` 位于 `Menu.Group` 外时会 throw `MenuGroupRootContext is missing`。
2. RadioItem/CheckboxItem 默认 `closeOnClick=false` — 选择后菜单不会关闭。
   → E2E 采用一次打开菜单后连续操作的流程更稳健（无需猜测是否要重新打开）。
3. Escape 每次只关闭一层（子菜单 → 根）。不会像 Radix 那样全部关闭。
4. `TooltipTrigger` 默认元素是 `<button>` — 放在 `<Link>` 内时要用 `render={<span />}`
   避免交互元素嵌套。`Tooltip.Provider` 不是必需，只用于共享 delay
   （app-layout 已有全局 `delay={0}` Provider）。

### 把文本移到 工具提示 时，要用 sr-only 将名称留在 DOM 中
**情况**：把 会话 行 的 智能体 小标签 从名称文本改为 头像 + hover 工具提示。

**规则**：工具提示 仅 hover 可见，屏幕 阅读器/键盘用户会丢失信息。移除的
文本要以 `<span className="sr-only">{name}</span>` 保留在 触发器 内。
触摸设备本身没有 hover，如果以后必须确认名称，再考虑其他方式
（例如点击显示）。

## Session 2026-06-11 — codex/marketplace 代码 审查 中发现的模式

### Soft-delete 资源 join 时始终包含 status 过滤器
**情况**：`marketplace_installations` uninstall 时不删除 row，只把
`install_status='uninstalled'`。`agent_blueprints` 列表 查询 外连接 该表时
outerjoin 时漏掉 status 过滤器，导致重装时列表重复 + stale 状态显示错误。

**模式**：所有 join/outerjoin soft-delete 表的 查询，都应在 join 条件里包含
`install_status != 'uninstalled'`（或相应 status 过滤器）。
参考模式：`install_service._existing_installation`。

### 单个请求内禁止多次 commit — 主操作和 audit 放在一个 事务
**情况**：4 个 publish 路由采用 `主操作 commit → audit 记录 → audit commit` 两次提交。
第一次 commit 后若 audit 阶段异常，publish 已持久化但审计日志缺失。

**模式**：主操作 + audit 记录使用同一 会话，commit 只在最后执行一次。

### Secret scan 仅靠 denylist 不够 — 可能包含秘密的字段使用 allowlist 策略
**情况**：基于 键 名 正则（`password` 等）的 扫描器 无法检测 `DATABASE_PASS` 明文值和
URL userinfo（`https://user:pass@host`）（已实证）。

**模式**：对于 `env_vars`/`headers` 这类值本身可能是秘密的字段，
采用"非 credential placeholder 且非空的值一律阻断"的 allowlist 策略。

### 禁止翻译 en.json placeholder — t.rich 数据块 标签 与 ko 保持相同结构
**情况**：en.json 很多值只是把 键 名 titlecase 的 占位值（"Not Found", "Required Missing"）。
尤其 `t.rich` 消息如果英语值里没有 `<code>`/`<type>` 数据块 标签，回调 不会工作。

**模式**：ko 是 source of truth，但 en 必须提供有实际语义的翻译 + 相同 数据块 标签 结构。

### Marketplace payload 按发布者可控输入处理
**模式**：install/materialize 时，`definition_key`、`middleware_configs`、tool `parameters`
与 registry/允许列表对照后使用。MCP tool snapshot 在 discovery 验证前不得物化为 runtime-linkable
状态（enabled McpTool）（设计 §6.1 "no phantom tools"）。

### 修复模式时，要用 grep 检查 范围 外是否仍有同类模式
**情况**：修复 publish 6 处 双重 commit 后，同一文件的 patch/acl/disable/enable/admin
5 处仍残留相同 反模式（复审发现）。

**模式**：修 反模式 时不要只改被指出的位置，要对同一文件/模块整体
grep 检查是否还有相同模式，并一起处理或明确报告。

### Snapshot re-materialize 必须保留用户手动状态
**情况**：reuse_or_update（只更新 credential）重新调用 `_materialize_mcp_tool_snapshot`，
把用户手动开关的 McpTool.enabled 覆盖回 publish 时的默认值。

**模式**：安装后用户可修改的字段（enabled 等），在 重装/更新 路径中
除非是"版本 overwrite"，否则必须保留。用测试固定保留/重置策略。

### Radix Select 选项 用 findByRole 等待（vitest/jsdom）
**情况**：新测试在点击 Select 触发器 后立刻用 `getByRole('option', ...)`，
传送门 中 选项 异步 挂载，导致约 40% 非确定失败（通过 8 次重复执行实证）。

**模式**：Radix Select/Popover 等基于 传送门 的内容，点击后始终用
`await screen.findByRole(...)` 查询。触发器 点击本身用 `getByRole` 没问题。
新测试在 合并 前应重复执行（例如 8 次）检查 flakiness。

### Alembic revision ID 必须 ≤32 字符（VARCHAR(32) 硬约束）
**情况**：`m62_agent_blueprint_credential_bindings`（39 字符）revision ID
超过 `alembic_version.version_num VARCHAR(32)` → `upgrade head`
在所有环境都因 StringDataRightTruncationError 失败。m58（正好 32 字符）是上限。

**模式**：revision ID 始终 ≤32 字符。写新 迁移 时检查 `len(revision)`。
如果是 头 迁移，仅改 revision 也安全（没有其他 down_revision 引用）。

### Soft-delete + 派生 status fallback 的陷阱
**情况**：agent_blueprint uninstall 只把 installation.install_status 改为 'uninstalled'，
blueprint 行/状态 保持原样。列表 查询 从 join 中排除 uninstalled installation 后，
installation=None → fallback 到 blueprint.install_status（stale 的 'active'），
导致 幽灵 以 'active' 暴露。属于修重复 行 时反而暴露 幽灵-active 的案例。

**模式**：soft-delete 时同步所有关联 实体 的 status，或者验证 派生
projection 的 fallback 值可能 stale。修改 join 过滤器 时必须同时看 fallback 分支。
一起检查。

### Secret 检测按结构+entropy 判断，而不是只看长度
**情况**：env_vars/headers allowlist 只用"长度 ≥20 的单一 令牌"判断 secret，
把 `claude-3-5-sonnet-20241022`（模型名）、UUID、region、`Idempotency-Key` 头部 全部
误拒绝，产生 false positive。用户第一次 publish 就会碰到。

**模式**：若分隔符（`-_./:@`+空格）≥2 个则视为 标识符 放行。只有连续字母数字 运行 且
长度 ≥20 + Shannon entropy ≥3.0 才怀疑为 secret。头部 名匹配不要用宽泛的
`key`/`token`/`auth` 片段，而用真实 凭证 头部 的 enum allowlist。best-effort
防御优先最小化 FP — 与其阻断正常配置，不如漏掉罕见 opaque secret。

### 对抗性 审查者 的"Critical 回归"主张要用 git history 交叉验证
**情况**：审查者 声称"ghost 修复会在 reinstall 时新造成 孤儿 累积（Critical）"，
但 `_existing_installation` 的 `install_status != 'uninstalled'` 过滤器
在 main 中早已存在（skill 的既有 soft-delete 行为）。blueprint 只是遵循同一模式，
并非新回归。

**模式**：对"这个修复破坏了 X"的主张，用 `git show main:<file>` 检查 X 在修改前是否
已经存在。区分既有行为和新回归，再重新调整严重级别。

### Pattern: chat-run-lifecycle 审查 得出的结论（2026-06-11）

**1. 状态机 转换 必须在 锁/CAS 下进行。** 多个 会话/任务 对同一 row 的 status 做
read-modify-write 时，stale read 会导致错误 转换（ValueError）或 lost update。
修改状态的 调用方 应用 `with_for_update` 加载，或使用 `UPDATE ... WHERE status IN (...)`
条件式 更新，并在 转换 函数 docstring 中明确 并发 契约。
（例如 cancel 刚把 `queued→canceling` 提交 后，worker 又拿旧 `queued` 快照 尝试 `running` 转换 → canceled 被误分类为 failed）

**2. 长生命周期 流 钩子 中 attach/send 共享 AbortController 时必须有 所有权 防护。**
effect 进入时无条件 `abort()` 会抢走正在进行的 流。需要 in-flight ref 防护 +
记录"已消费到底的 run"（consumedRunIdRef）来区分，并在 cleanup 中让 guard 令牌
失效，防止 unmount 后执行 setState/回调。cleanup 的 令牌 失效必须放在
`isStale(token)` 检查之后 — 否则会杀掉新流的令牌。

**3. 协议 适配器 的 关联 ID（messageId/toolCallId）应从单一来源生成。**
若不同 事件 类型 从不同字段（data.id vs run_id）提取 ID，START/CONTENT/END 匹配会
破裂。测试必须包含"两种来源值不同"的场景。

**4. 回归测试要验证"在修复前代码上会失败"。** 修 错误 时暂时
禁用 防护，确认测试准确失败后再恢复。如果测试用 mock 回调（例如
onMessagesCommit）掩盖 缺口，就添加一个复现真实页面构成（无 回调）的 用例。

**5. 基于 ring buffer 的 resume 不应把"after_id 不存在"当成 silent gap。**
`slice_events_after` 在 after_id 不存在时什么也不 yield — 调用方 必须解释这一语义，
应 degrade 为 stale 标记 + 全量 buffer replay（重复由客户端 dedup 处理）。

**6. 将 回调 型库 bridge 为 async generator 时，所有 settle 路径都必须设置结束信号。**
`fetch-event-source` 在 signal abort 时不会 reject promise，而是 resolve，且
onclose/onerror 也不调用。若只在 `.catch` 中设置 `closed=true`，abort 时
消费循环会永久等待形成 deadlock（Stop 后 isRunning 不解除的根因）。
结束处理应放在 `.finally`，abort 则显式转换为 AbortError，以维持 消费者
契约。不要假设库的 abort 语义（reject? resolve? 回调 调用?），
必须查看 源码 确认。

**7. E2E 的 webServer `reuseExistingServer` 不保证占用端口的是"正确服务器"。**
如果 docker-compose 容器 占用了 3000，Playwright 会把它当 前端
复用，导致全部 404。工作树 中跑 E2E 应通过 `E2E_FRONTEND_PORT`/`E2E_BACKEND_PORT`
指定空闲端口启动自己的代码。另外 background 执行时不要用 tail
截断输出 — 失败诊断需要完整 服务器 日志。

---

## 聊天附件显示代码审查教训（feature/chat-attachments-display）

**8. 用户上传文件若以 `Content-Disposition: inline` 从同源提供，会形成 存储型/自身 XSS。**
上传 允许列表 若使用 `text/*` prefix，`text/html`·`image/svg+xml` 也会通过 → inline 时
直接访问 `/api/uploads/{id}` 会在 应用 来源 执行 脚本。MIME 是 客户端 提供值，
不可信任。inline 只适用于**预览安全类型（pdf iframe、光栅图像）**，html/svg
强制 `attachment` + 始终 `X-Content-Type-Options: nosniff`。（图片 `<img>`
不受 disposition 影响也能 渲染，因此真正必须 inline 的只有 PDF iframe。）
**补充（注意绕过）**：若对客户端提供的 MIME 用**exact 比较（`!= "image/svg+xml"`）**阻断，
`image/svg+XML`（大写）·`image/svg+xml; charset=utf-8`（参数）·尾部空格仍可通过 `startswith("image/")`
而绕过 svg 阻断并 inline。安全比较前必须**规范化**（`split(";")[0].strip().lower()`）。
测试也不能只放 exact MIME，应包含大小写/参数变体 用例。

**9. 附件预览不能复用工件 content 端点 — id 域不同。**
`ArtifactPreview` 的 text provider 通过 `getArtifactTextContent(artifact.id)` 获取
正文，但 附件 的 id 是 **上传 id**，所以 `/api/artifacts/{id}/content` 返回 404 → 空 预览。
image/pdf 因 基于 URL 能工作，所以**测试若只覆盖 image/pdf 会掩盖这个 缺口。** 应提供 上传
范围 `/api/uploads/{id}/content` + 在 `ArtifactPreview` 中通过 `textLoader` override 分支。
预览 测试必须覆盖 **text/json 这类 content-fetch 类型**。

**10. finalize 中基于 `active_branch_checkpoint_id` 解析的后处理，应放在 分支 激活 *之后*。**
worker finally 中 附件 message_id backfill（`resolve_turn_user_message_id`）如果
比 `_activate_latest_branch_leaf_if_needed` **更早**执行，edit/regenerate 运行 会
挂到 stale 分支，并 stamp 到错误 消息 → 内联 不显示。线性（新 send）场景则
因为 `None→最新 leaf` fallback 恰好正确，测试抓不到。read path 使用的 leaf 与
将读取顺序对齐，确保读取到**同一状态**。

**11. 不要为每个组件的 `useSyncExternalStore` 订阅创建 `MutationObserver(document.body, subtree)`。**
如果列表有 N 项，就会有 N 个 观察器 各自处理每次 DOM mutation → 在 流式 hot path 中
达到 O(N×mutations)。应按模块合并为**共享 观察器 1 个 + 订阅者 Set + rAF 合并**。

**12. 后端 模式 新增字段后，要确认一直连接到了真正消费它的地方。**
仅暴露 `ArtifactSummary.linked_message_ids`，但 侧栏 jump 仍使用
`assistant_msg_id`（run id），于是与 气泡 锚点 永远不一致 → 始终失效。要一路追踪是否完成了暴露/管线/
**实际消费**。

**13. 用于验证判断的 exit code 绝不要在 流水线 后面读取。**
`cmd | tail -2; echo $?` 中的 `$?` 是 **tail 的 exit code**（始终 0）。PR #290 中
把"pytest 全量 deselect = exit 0 假绿"写进了 5 处文档/注释，但实测其实是
exit 5（red），直到 审查 才发现 — 同一会话里这个坑**踩了两次**
（CLAUDE.md CI·门控 规则 ① 已经写过的坑）。需要 exit code 的验证应使用
`cmd > /dev/null 2>&1; echo $?` 这种无 流水线 的分离执行方式；固定为回归测试时也
直接断言 subprocess 的 returncode。
