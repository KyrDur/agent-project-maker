# Moldy 全面重构计划 + 新功能发掘 (2026-07-07)

> **文档目的**：确保只看这一份文档就能从头到尾完成重构，记录各项依据(file:line)、问题、分阶段方案、验证命令和工时。
> **分析方法**：按领域并行分析（后端结构/性能/重复，前端结构·重复/性能·设计，基础设施/DevX，功能 gap）。所有条目只采纳**实际打开代码确认过的 file:line 依据**，排除推测项。行号以 2026-07-07 main(`828d056a`) 为准 — 时间推移后可能偏移，应按函数/符号名重新搜索。
> **分析时规模**：backend/app 84,902 行（router 68，service 84，model 39），frontend/src 100,620 行（component 342），Alembic revision 76(M63)，backend 测试文件 267，e2e spec 69。

---

## 0. 总评

该代码库已经**证明了拆分与公共化能力** — `conversation_agent_protocol*` 拆成 18 个文件、executor split、38 处采用 `DialogShell`、`lib/query-keys` factory、设计 token lint guard 都是证据。真正的问题不是能力不足，而是**一致性不足**：

1. **仍有未覆盖区域** — `chat_service.py`（1,786 行）、`install_service.py`（1,366 行）、`use-moldy-langgraph-stream.ts`（2,941 行）这类 God module，以及完全没有 service layer 的 MCP/tools/models router。
2. **half-done 公共化** — error factory（`error_codes.py`）、query key factory、`make_user` fixture、`BaseDetailDialog` **已经存在**，却只采用了一半，drift 正在发生。
3. **hot path 性能债务** — 每次 polling 的 N+1（3 类）、让 event loop 停顿 250ms 的 bcrypt、每个 SSE 事件双重 redaction。
4. **双系统** — 前端聊天 legacy/v3 runtime 并行维护，使所有聊天功能成本变为 2 倍。
5. **安全网空白** — 缺少 CI pipeline、聊天 route error boundary、SSRF 尚未修复。

---

## 进展情况 (Progress) — 2026-07-09 更新

基于已 merge PR 的实际进展状态。各细项完成标记已反映到下方 §1 matrix 的对应行。

| PR | 分组 | 完成项 | 状态 |
|----|------|-----------|------|
| #279 | Phase 0 安全网 | SEC-1, SEC-2, SEC-3, BE-P4, FE-D1, IX-1 + master 计划文档 | ✅ merge |
| #279 | pyright 清零 A | data/ exclude(970→627) + `docs/pyright-burndown-plan.md` | ✅ merge |
| #280 | Phase 1 hot path | BE-P1, BE-P3, BE-P6, BE-P7, **BE-P5 部分**((a)(c) 完成) | ✅ merge |
| #281 | Phase 2 去重 | **BE-D2**（error factory）, **BE-D4**（visibility 谓词）, CI integration test 拆分 | ✅ merge |
| #282 | Phase 2 所有权 | **BE-D1 部分**（owned_conversation 依赖 + 10/30 router: artifacts·files·traces） | ✅ merge |
| #283 | lint hardening 计划 | `docs/lint-hardening-plan.md` + lint:all 脚本 | ✅ merge |
| #287 | lint A-1 | 登记 3 个 guard 例外（+回归测试）+ 4 个绿色 guard 接入 CI·pre-commit（a11y·design-system·frontend-architecture strict 留待 A-2） | ✅ merge |

**部分完成剩余项**（恢复点）：
- ~~**BE-P5**: (b) 双重 redaction, (d) seen_event_ids, (e) inline flush~~ → **由 PR #294 完成**（详见执行顺序 6）
- ~~**BE-D1**: 剩余 20 处~~ → **由 PR #292 完成**（转换 18 处 + 文档化有意保留的 run_cancel/stream_resume 2 处；详见执行顺序 5）

- ~~**Stage 2 全部** (BE-S7·BE-S2·BE-D3·BE-D7)~~ → **由 PR #295 完成**（详见执行顺序 7–10）
- ~~**Stage 3 全部** (BE-S1·BE-S3·BE-S5·BE-S8·BE-S9·BE-S10)~~ → **由 PR #296 完成**（详见执行顺序 11–13）

**未启动 P1**（下一优先）：BE-P2（消息 pagination·FE 联动）、FE-S1（runtime 收敛）、FE-S2（2941 行 hook）、FE-P1（context churn）、FE-P2（virtualization）。**未启动 P2/P3**：§1 matrix 中所有没有 ✅/🔶 的行。

**单独 track**：pyright 清零 B/C/D（`docs/pyright-burndown-plan.md`），lint hardening A~G（`docs/lint-hardening-plan.md`）。

---

## 1. 综合优先级矩阵

优先级定义 — **P0**：安全·可靠性，本周内启动。**P1**：直接影响用户体验/开发速度，1~2 个 sprint。**P2**：随数据增长·功能增加而恶化的债务。**P3**：有余力时。工时 — S（半天）、M（1~2 天）、L（3 天+）。

### P0 — 立即（安全·可靠性·低工时高收益）

| ID | 标题 | 类别 | 工时 |
|----|------|----------|:---:|
| SEC-1 | ✅ web_scraper SSRF 未修复（见 §3）— Phase 0 完成 | 安全 | S~M |
| SEC-2 | ✅ rotate_credentials no-progress 无限循环残留 — Phase 0 完成 | 可靠性 | S |
| SEC-3 | ✅ trigger run-now 路径缺少重复执行 guard — Phase 0 完成 | 可靠性 | S~M |
| BE-P4 | ✅ bcrypt 阻塞 event loop 250ms → `asyncio.to_thread` — Phase 0 完成 | 性能 | S |
| FE-D1 | ✅ chat/share/dashboard route 完全没有 error boundary — Phase 0 完成 | 可靠性 | M |
| IX-1 | ✅ CI pipeline + Pyright basic 硬门禁完成 (2026-09-07, 0 errors) | DevX | M |

### P1 — 影响最大（1~2 个 sprint）

| ID | 标题 | 类别 | 工时 |
|----|------|----------|:---:|
| BE-P1 | ✅ `GET /messages` polling N+1（interrupt hydration）— Phase 1 完成 | 性能 | M |
| BE-P3 | ✅ polling 路径 MCP credential `FOR UPDATE` N+1 — Phase 1 完成 | 性能 | S~M |
| BE-P5 | ✅ 每个 SSE 事件的重复成本 — (a)(c) PR #280，(b)(d)(e) PR #294 完成 | 性能 | M |
| BE-P2 | `GET /messages` 无限制加载 → keyset pagination | 性能 | L |
| BE-S2 | 新建 MCP/tools/models service layer（移除 router raw DB） | 结构 | M |
| BE-S7 | credentials router OAuth 逻辑 → oauth_service | 结构 | M |
| BE-S1 | chat_service.py 拆分 8 个 cluster | 结构 | L |
| BE-S3 | install_service.py 按 3 种类型拆分 | 结构 | L |
| BE-D1 | ✅ 所有权查询+404 模式 30 处 → Depends 依赖 — #282（10 处）+ #292（剩余 18 处 + 文档化保留 2 处）完成。agents `owned_agent` 扩散为可选后续 | 重复 | M |
| BE-D2 | ✅ raw HTTPException 21 处 → 统一使用 error_codes factory — #281 完成（system_llm_settings 因 byte-identical 契约排除） | 重复 | S~M |
| FE-S1 | 聊天 runtime 双轨（legacy/v3）收敛第 1 阶段 | 结构 | M~L |
| FE-S2 | 拆分 use-moldy-langgraph-stream.ts（2,941 行） | 结构 | L |
| FE-P1 | streaming 期间 context churn → 全部消息 rerender | 性能 | M |
| FE-P2 | 聊天 thread virtualization（先行 memo 为 S） | 性能 | L |

### P2 — 偿还债务（backlog 顶部）

| ID | 标题 | 类别 | 工时 |
|----|------|----------|:---:|
| BE-P6 | ✅ 5 个 FK index（M67）— Phase 1 完成 | 性能 | S |
| BE-P7 | ✅ checkpointer pool 2/20 + 暴露 engine pool 设置 — Phase 1 完成 | 性能 | S~M |
| BE-P8 | health_check_history 无限增长（retention dead code） | 性能 | S |
| BE-P9 | MCP health polling 串行 → 并行化+backoff | 性能 | M |
| BE-P10 | Marketplace MCP 安装每个 tool 一次 SELECT N+1 | 性能 | S |
| BE-P11 | artifact ingest 每个文件多次 SELECT | 性能 | M |
| BE-P12 | memories 无限制列表 + Marketplace OFFSET pagination | 性能 | M |
| BE-S4 | 反转 services↔agent_runtime 双向耦合 | 结构 | L |
| BE-S5 | 拆分 write_tools.py 的 26 个 closure | 结构 | M |
| BE-S6 | 目录 convention ADR + services 子包化 | 结构 | M |
| BE-S8 | artifact_service.py 拆分 recorder/library | 结构 | M |
| BE-S9 | scheduler.py job 逻辑 → 迁移到领域 service | 结构 | M |
| BE-S10 | runtime_component_builder.py 拆分 5 个关注点 | 结构 | M |
| BE-D3 | audit record_event self-action wrapper | 重复 | M |
| BE-D4 | ✅ 8 处 system-or-owned 谓词 → Tool.visible_to — #281 完成（`_load_owned` 统一仍与 BE-D1 一并剩余） | 重复 | S~M |
| BE-D7 | 引入测试 Model/Agent factory fixture | 重复 | M~L |
| FE-S3 | 拆分 assistant-thread.tsx（1,458 行） | 结构 | M |
| FE-S4 | 拆分 approval-card + 合并 2 类 approval hook | 结构 | M |
| FE-S5 | 拆分 2 个超大 page（memory 649/template 617） | 结构 | M |
| FE-S6 | dialog shell 复制粘贴 8+ 次 → 公共 hook + 清理 dead 抽象 | 重复 | L |
| FE-S7 | 拆除 lib/types/index.ts 混合 barrel | 结构 | M |
| FE-S8 | 9 个 inline Query key hook → 迁移到 factory（quick win） | 重复 | S |
| FE-P3 | 管理 table/navigator virtualization | 性能 | M |
| FE-P4 | 活跃 run 每 1 秒双重 polling 统一 | 性能 | M |
| FE-D2 | 26 个 a11y label（消除 baseline） | 设计 | M |
| FE-D3 | 统一 loading/error/empty state 覆盖 | 设计 | M |
| FE-D5 | agent-prism trace UI 仅英文（i18n） | 设计 | M |
| FE-D6 | tool-ui 绕过 shadcn + 新建 RadioGroup primitive | 设计 | M |
| FE-D7 | media artifact aria-label/caption | 设计 | S |
| IX-2 | 缺少 pre-commit hook | DevX | S |
| IX-3 | docker-compose/Dockerfile production hardening | 基础设施 | S~M |
| IX-5 | 缺少结构化 logging + request-id | 基础设施 | M |
| IX-6 | aiosqlite↔PG 差距 — 在 CI 增加 PG integration job | 测试 | S~M |

### P3 — 有余力时

| ID | 标题 | 类别 | 工时 |
|----|------|----------|:---:|
| BE-P13 | scrape HTML parsing/zip export `to_thread` | 性能 | S |
| BE-S11 | 统一 marketplace projection 重复 | 结构 | M |
| BE-D5 | 共享 keyset cursor normalization + 统一 limit 常量 | 重复 | S~M |
| BE-D6 | 提取 tool runner auth+HTTP helper | 重复 | S |
| BE-D8 | Response schema mixin（收益最小 — 后置） | 重复 | S |
| FE-S9 | 迁移 features/ 目录（按领域渐进） | 结构 | L |
| FE-S10 | 引入 openapi-typescript 类型生成 | 结构 | M |
| FE-P5 | page 'use client' → 拆分 server shell（新规则优先） | 性能 | M |
| FE-P6 | 移除 chart.js dead dep + next/image | 性能 | S |
| FE-P7 | selector hardening + phase-timeline O(n) scan | 性能 | S |
| FE-D4 | chart-card palette token 化 + 3 处 bg-white dark variant | 设计 | S |
| IX-4 | squash 76 个 Alembic revision | DevX | M |
| IX-7 | 拆分 e2e captures/regression playwright project | 测试 | S |

### Quick Wins（仅汇总工时 S、可立即处理的事项）

`BE-P4`（bcrypt to_thread）· `BE-P6`（1 个 index migration）· `BE-P8`（history GC）· `BE-P10`（安装 N+1 hoist）· `BE-P13`（2 处 to_thread）· `BE-D2`（替换 error factory）· `BE-D6`（runner helper）· `FE-S8`（迁移 query key）· `FE-P6`（移除 chart.js）· `FE-P7`（selector 常量）· `FE-D4`（chart token）· `FE-D7`（media label）· `IX-2`（pre-commit）· `SEC-2`（rotation loop guard）

---

## 2. 推荐执行路线图 (Phase)

### ▶ 当前执行顺序 (2026-07-10，仅未完成项) — 新 session 从这里开始

> **使用方法**：`/clear` 后，在新 session 中只需一句 **"按本文档执行顺序继续下一个未完成项"**。如需指定某项，直接复制下方编号对应的 prompt。通用规则：在 worktree 中基于 origin/main 建新 branch，一个 PR = 一个条目，功能变化 0（纯移动用 facade），验证全绿后 PR。（后端验证 = `ruff` + `pyright` + `pytest -n 4 --ignore=tests/integration` + `pytest tests/integration -m integration` 串行（自动加 marker 后必须带 `-m integration` — 否则全部 deselect：dir-scoped 为 exit 5 red，完整执行 `pytest tests/` 时会静默排除），push 时 `SKILL_EVALUATION_ENABLED=true`。）
> 完成后在该列表对应行留下 ✅ 和 PR 编号，让下一 session 接着进行。

**Stage 0 — 先做自动门禁（之后所有工作都自动验证。杠杆最大）**
1. ✅ **lint A-1** — PR #287。重新测量（i18n 3·type-safety 2·e2e-hygiene 40 = 全部合理）→ 登记 3 个例外 + 每个例外的回归测试 → 将 4 个绿色 guard（lint·i18n·type-safety·e2e-hygiene）接入 CI 独立 step + lint-staged。**frontend-architecture 在第 2 次 review 中被确认是假绿**（非 strict 始终 exit 0，strict 有 3 个 blocking red）→ 与 a11y（新增4+解决2）·design-system（12）一起留到 A-2（联动 FE-D2·FE-D4 + 修复 strict blocking）。
2. ✅ **lint C** — PR #288。启用 `S` rule + triage 51 项（app 43 + scripts/alembic 8）。实际修改 2 处：openwiki sync_repo.py（注入 LLM 提供的 --repo-url/--ref 选项·阻断 ext::/file:// transport + 22 个测试 case），generate_image.py（S310 scheme guard）。其余误报采用 inline noqa + tests/·alembic/ per-file-ignores。附带门禁回归测试（注入 red + 例外 non-blanket negative）。
3. ✅ **lint F·G** — PR #290。F：启用 `PGH`（当前 tree 违规 0 — 纯预防门禁，禁止 bare noqa/blanket type-ignore）+ 门禁回归测试。G：`tests/integration/conftest.py` 自动 marker hook + **CI 串行 step 必须 `-m integration`**（加 marker 后 plain `pytest tests/integration` 会全部 deselect → exit 5 red；安静变体是在 full-suite `pytest tests/` 中被 sibling 测试通过掩盖为 exit 0 — review 中修正了 exit code，最初实测踩了 `| tail` pipe 陷阱）+ coverage/deselection 回归测试。m9 因 self-skip 安全。pre-push 的 plain `pytest tests/` 排除 integration 是有意设计（CI 串行为 gate）。**已知盲区（pre-existing）**：`tests/test_trace_storage.py` 中有 1 个 integration marker 测试位于目录外，因此任何 CI step 都不会运行；在 aiosqlite 下执行会失败，且没有 live PG 注入基础设施，是 dead test — 后续应按 m9 模式（INTEGRATION_DATABASE_URL）迁移到 tests/integration/。
4. ✅ **lint E** — PR #291。批量启用 7 条 rule + triage 373 项（文档实测的 66 项仅限 app/ — 实际多数是 tests/ 308 项）。实际修改 ~48（RET inline·PTH pathlib（含启动 SSL 路径）·PT011 match=·PT019 usefixtures·PT013/PT006/N806/N814），全局 ignore N818（领域风格异常名 18 项），per-file `app/**`=PT（router `test_*` endpoint 误报 17 项）·`tests/*`+=SLF001/DTZ/PT017/PT018/N801/N815（惯用法·wire mock 267 项），inline noqa 14（ssl patch·ORM stash·tool schema camelCase·本地日期 — 全部带原因）。门禁回归测试 `test_lint_low_noise_rules.py`（red + 证明例外为 rule-scoped）。2 次陷阱实证：C416 unsafe fix（`dict(rows.all())`）导致 pyright 类型回归 → 用 `.tuples()` 解决 / commit hook 重新格式化（113→354 insertions）后必须复查 noqa anchor（已保持）。

**Stage 1 — 收尾部分完成项**
5. ✅ **BE-D1 剩余项** — PR #292。转换剩余 18 处（8 个文件）：复用 conv 的 router（branches 2·crud 3·messages list·followup·shares create/revoke·e2e 4）注入 conv — 将参数位置放在 **`verify_csrf` 之后**以保持 CSRF 403→404 顺序（decorator dependencies 比 param 依赖更早运行，如果把 gate 放到 decorator 会颠倒顺序，e2e heartbeat 注释已实证）。GET gate 5 处（runs 3·ag_ui·shares get）使用 decorator `dependencies=[...]`。有意保留 3 处：run_cancel helper（两个 router 共享不同 path param 的 conversation_id/thread_id）、messages stream_resume（独立 `resume_not_found` 契约+reject logging）、crud get_conversation_detail（agent eager-load 独立 getter）。删除 shares 本地 `_require_owned_conversation`。agents.py 的 `owned_agent` 扩散（6 处）留作 §6 方案第 2 阶段的可选后续。
6. ✅ **BE-P5 剩余项** — PR #294。(b) persist 复用 wire 1 次 redaction（`persistable_wire_protocol_event` = compact + 仅 memory masking；W2-3 契约通过拆出 `redact_memory_content` 保持，并用 full/wire 变体等价性测试锁定）。(d) `build_persist_callback` 增加 run-scoped seen_event_ids cache — 首次 flush 1 次 seed（`load_persisted_event_ids`）后增量更新，**不变量 cache ⊆ DB**（仅 commit 成功的部分写入；失败时 reset 并 reseed；若 cache 领先 DB，retry event 会被 dedup 丢失）。(e) v3 emit 的 inline `await` flush → `asyncio.create_task` fire-and-forget — in-flight 上限 **1**（legacy 为 4），以 run 内串行化保证 chunk seq_start 单调 + (d) cache 无竞争；失败 chunk 恢复到 buffer **前端**保持顺序 + 5000 events cap（legacy parity），finally 中 join task → final flush。

**Stage 2 — 分层·边界（答案明确）** — ✅ **全部 PR #295**（一个 PR，按条目 commit + 按条目 review）
7. ✅ **BE-S7** — PR #295。OAuth ~286 行 → `app/credentials/oauth_service.py`（client=底层 HTTP / service=DB 状态·orchestration 契约明确）。**全局事务策略决定：service flush / router commit。** `gc_oauth_states` public 暴露（供 scheduler 复用）。review 反馈：加入 callback 跨用户 forbidden 回归测试（未认证 callback 唯一可劫持 state 的防御分支契约锁定）。已知偏差 1（有意）：auth_start 的 malformed URL error 路径从 commit→rollback 改变（策略推导，更原子）。
8. ✅ **BE-S2** — PR #295。新建 `mcp_service` + 扩展 `tool_service`（CRUD·run·audit）·`model_service`（operator CRUD·in-use check），3 个 router raw DB 访问 0。保留原有 commit sequence（包括 double commit）以确保 semantics 不变。review 通过（发现 0）。
9. ✅ **BE-D3** — PR #295。`audit_service.record_self_event` 吸收 self-action identity kwargs 7 个，替换 18 处（actor≠owner 保留 record_event）。review 反馈：补上遗漏的 finalize site + identity column literal expected-value contract test（避免 delegation tautology）。
10. ✅ **BE-D7** — PR #295。conftest `make_model`/`make_agent`/`seed_agent(db)->(user,model,agent)` + `AuthSession`/`register_session`（auth 5 个文件 shim 转换，签名保留）。ORM factory 在代表性 2 个文件采用，其余按 guardrail 渐进迁移。参考：Model 没有 (provider,model_name) unique constraint（ORM 层）— seed 重复调用安全。

**Stage 3 — God module 拆分（facade 纯移动，逐个进行）** — ✅ **全部 PR #296**（一个 PR，按条目 commit + 每项 6 次 adversarial review，blocking 发现 0）
11. ✅ **BE-S1** — PR #296。chat_service.py 1810→104 行 facade，`app/services/chat/` 7 个模块（interrupts/secrets/conversations/messages/usage/attachments/runtime_context）。有意保留 4 处函数内 import（1 处 import-order cycle + 3 处测试 monkeypatch 的 call-time lookup — 提升到 top-level 会绕过 patch，造成功能变化）。
12. ✅ **BE-S3** — PR #296。install_service.py 1365→400 行 facade+dispatcher，`app/marketplace/install/`（common/snapshot/bindings/skill/mcp/agent_blueprint）。2 个非纯移动 seam（install_item skill 分支·update skill tail 提取）通过逐句 AST identical 验证。`_payload_skill_kind` 为避免 snapshot↔skill cycle 放到 common。
13. ✅ **BE-S5 · BE-S8 · BE-S9 · BE-S10** — PR #296（按用户指示合并为一个 PR）。BE-S5：write_tools 1091 行 → 4 组 builder package + `WriteToolContext`（23 个 tool schema byte-identical，`async_session_factory` patch surface 通过 call-time injection 保留）。BE-S8：artifact_service 1035→137 行 facade，`artifacts/`（recorder/library/content/summary/errors）— recorder 的 `_sha256_file` 使用 call-time facade import（测试 patch 观察路径）。BE-S9：scheduler 4 个 inline job → credentials/rotation·mcp_service·conversation_run_service·skill_runtime，**同名 wrapper 必须保留**（持久化 SQLAlchemyJobStore 序列化 module:qualname + 测试 patch `app.scheduler.async_session`/`_ROTATION_BATCH` — wrapper 在 call-time 读取 global 做 DI）。BE-S10：runtime_component_builder 930→600 行，`agent_runtime/runtime/`（models/reliability/interrupts/prompts/memory_context）— 只有 `create_chat_model` 在 models 中 call-time import builder（12 种 patch surface 中唯一风险）。memory_context 参数注入推迟到 BE-S4（Stage 5）。

**Stage 4 — 前端大型项**
14. **FE-P1** — streaming context churn（全消息 rerender）。§8 [FE-P1]。（独立·性能影响大，因此先做前端）
15. **FE-S2** — 拆分 use-moldy-langgraph-stream.ts（2,941 行）。§7 [FE-S2]。
16. **FE-S3 · FE-S4** — 拆分 assistant-thread / approval-card。
17. **FE-S1** — 聊天 runtime 双轨收敛。§7 [FE-S1]。（设计难题，熟悉前端后再做）

**Stage 5 — 结构难题 + pagination**
18. **BE-S4** — 反转 services↔agent_runtime 依赖（155 处函数内 import 的根源）。§4 [BE-S4]。
19. **BE-P2** — 消息 keyset pagination（FE 联动）。§5 [BE-P2]。
20. **BE-S6** — 目录 convention ADR + 子包化。§4 [BE-S6]。

**Stage 6 — Backlog（P2/P3 quick win，可并行）**
- 后端性能：BE-P8·P9·P10·P11·P12·P13 / 前端性能：FE-P2（virtualization）·P3·P4·P5·P6·P7
- 设计·a11y：FE-D2~D7 + lint A-2（接入 design-system·a11y guard）/ 重复：BE-D5·D6·D8 · FE-S5~S10
- 基础设施：IX-3（docker）·IX-5（结构化 logging）·IX-4（squash）

**Stage 7 — 类型门禁（大型，最后）**
21. ✅ **pyright 清零** — 2026-09-07 完成。1,258→0，移除 CI `|| true`，
    切换为 basic-mode 硬门禁。详情见 `docs/pyright-burndown-plan.md`。
22. **lint D·B 剩余项** — 决定是否升级 pyright standard + 后端自定义
    guard（禁止 raw HTTPException 的脚本）。与 basic 0 达成分开推进。

**顺序依据**：Stage 0 先做 = 后续 20 多个 PR 自动验证（本次重构 session 的最大教训）。BE-S2 是 BE-S9 的前置，God module（3）在 layer 整理（2）后更安全。BE-S4 是多个 God module 函数内 import 气味的根因，因此在拆分后收尾。类型门禁（7）需要先完成 968 项清零，所以最后做。

---

### 初始分析路线图 (2026-07-07，参考)

考虑依赖关系和风险后的顺序。每个 Phase 作为独立 branch/PR 分组推进，Phase 间顺序需遵守，Phase 内可并行。

- **Phase 0 — 安全网（1 周）**：SEC-1·2·3 + BE-P4 + FE-D1 + IX-1（CI）。CI 必须先建立，这样之后所有重构 PR 才能自动验证。当时 Pyright 有 968 个既有错误，因此 typecheck 是 non-blocking；2026-09-07 清零完成后已改为 blocking。
- **Phase 1 — hot path 性能（1~2 周）**：BE-P1 → BE-P3 → BE-P5 → BE-P6 → BE-P7 + Quick Wins 批量处理。都是小规模 diff，回归风险低，体感收益立即。
- **Phase 2 — 分层·边界（2 周）**：BE-S2 → BE-S7 → BE-D1 → BE-D2 → BE-D4。属于"答案明确"的类型，review 负担小。此时全局确定事务策略（service flush / router commit）。
- **Phase 3 — God module 拆分（2~3 周）**：BE-S1 → BE-S3 → FE-S2 → FE-S3 → FE-S4 → BE-S5。全部采用基于 facade 的纯移动策略，保持功能变化 0。并行：FE-P1（context 拆分）。
- **Phase 4 — 双系统收敛（2 周+）**：FE-S1（runtime 收敛第 1 阶段）→ BE-S4（依赖反转）→ BE-S9（scheduler）。BE-P2（消息 pagination）与 FE 消费端修改一起做。
- **Phase 5 — 长期改善（backlog）**：virtualization（FE-P2/P3）、设计/a11y 分组（FE-D2~D7）、测试 factory（BE-D7）、目录迁移（FE-S9, BE-S6）、类型生成（FE-S10）、squash（IX-4）。

**通用 guardrail**：
- 重构 PR 遵守**功能变化 0**原则 — 纯移动通过 facade re-export 保留现有 import 路径。
- merge 前完整验证：`cd backend && uv run ruff check . && uv run pyright && uv run --with pytest-xdist pytest -q -n 4` / `cd frontend && pnpm lint && pnpm vitest run && pnpm build`。聊天相关变更额外执行 e2e `chat-*.spec.ts`（push 时需要 `SKILL_EVALUATION_ENABLED=true`）。
- 一个 PR = 一个条目。禁止 drive-by 重构（CLAUDE.md Minimal Impact）。

---

## 3. 安全·可靠性遗留问题 — 2026-07-03 审计跟踪（已重新验证）

本次分析通过代码重新确认了审计 High 4 项的当前状态。**建议作为与重构独立的 track 最高优先处理。**

### [SEC-1] web_scraper SSRF — **未修复 (STILL PRESENT)**
- **证据**：`backend/app/agent_runtime/tool_factory.py:149-162` — `scrape_url` 对模型（Agent）提供的 URL 不做任何验证就 `client.get(url)`。共享 client 设置 `follow_redirects=True`（`:102-106`），因此也可通过 redirect 进行 SSRF。完全没有 `ipaddress`/`is_private`/`169.254`/allowlist guard — 未阻断 localhost·RFC-1918·云 metadata（`169.254.169.254`）。
- **修改方案**：① 解析 URL 后只允许 scheme http/https ② 若 host resolve 结果为私网/loopback/link-local IP 则拒绝（`ipaddress.ip_address(...).is_private/is_loopback/is_link_local`）③ redirect 每个 hop 也重新验证（httpx event hook 或手动 follow）④ 设置响应大小上限。与现有 `sanitizeExternalUrl`（前端）的理念相同，是服务端版本。
- **验证**：新增 pytest，确保 `http://169.254.169.254/`、`http://localhost:8001/`、redirect 到私网 IP 的 URL 全部被阻断。

### [SEC-2] rotate_credentials 无限循环 — **部分修复（仍有风险）**
- **证据**：`backend/app/scheduler.py:235-251` — 移除 OFFSET 后原问题有所缓解，但如果一个 batch（≥`_ROTATION_BATCH=100`）全部持续失败，仍存在反复查询同一批 row 的 no-progress `while True`（终止 guard `len(rows) < _ROTATION_BATCH` 不会触发）。
- **修改方案**：在 session 内累积失败 id，并在下一次 fetch 时加 `id.notin_(failed)` 过滤；或检测 no-progress（连续 2 次相同 id 集）后 break + error logging；或设置 max-iteration cap。
- **验证**：seed 100+ 个无法解密的 credential 后，加入确保 job 能结束的 unit test。

### [SEC-3] trigger 重复执行 — **部分修复（run-now 路径仍存在）**
- **证据**：`backend/app/agent_runtime/trigger_executor.py:80-122` — APScheduler `coalesce=True, max_instances=1` + leader lock 已保护 schedule 路径，但 `routers/triggers.py:167` 的 **run-now 绕过 APScheduler**，当 schedule 执行 in-flight 时用户点击 run-now 会发生双重执行。
- **修改方案**：进入 `execute_trigger` 时对 trigger row 执行 `SELECT … FOR UPDATE` + status→running claim（已 running 则返回 409），或在 `agent_trigger_runs` 上加"每个 in-flight run 仅 1 行"的 partial unique index（`WHERE status='running'`）做 DB 层防御。
- **验证**：并发 run-now 2 次 → 只执行 1 次的 concurrency test。

### [SEC-4] 前端聊天 error boundary 缺失 — **有效（纳入 FE-D1）**
- 两个独立分析再次确认。详情和方案见 §8 FE-D1。

---

## 4. 后端 — 结构/架构 (BE-S)

分析范围：`backend/app/`（只读）。总计 84,902 LOC / Python。所有发现均实际打开文件确认，行号引用已验证。

**正向基准（非重构对象，仅供参考）：** `routers/conversation_agent_protocol*.py` 的 18 个文件是**优秀拆分案例** — route 仅存在于 `conversation_agent_protocol.py`（6 个）/`_sdk.py`（1 个），其余 16 个都是纯 helper module（state, replay, resume, redaction, interrupts, event_normalization 等），职责分离。下面的 god module 是"团队已经会做"却尚未应用这一模式的地方。另外，`services → routers` 反向 import 为 0（layer direction 本身得到遵守）。

---

### [BE-S1] `chat_service.py` God module — 7 个异质职责混在一个文件（1786 行）
- **优先级建议**：P1 — 项目最大文件，也是 chat/trigger/polling hot path 核心。变更频率、merge conflict、回归风险最高（MEMORY 的 W2-3、secret 收集规则等多起事故都发生在该文件）。
- **类别**：结构
- **证据**：`app/services/chat_service.py`。`__all__`（56-84）有 24 个 export。实际函数 cluster：
  1. **HITL interrupt 重建** `_review_config_for_action`~`_hydrate_pending_interrupt_tool_calls`（104-493，约 20 个 private function）
  2. **secret 收集/redaction** `collect_conversation_secret_values`, `_redact_response_tool_calls`（494-602）
  3. **conversation CRUD + keyset pagination + cursor encoding** `ConversationPageCursor`~`delete_conversation`（623-1030，包含 `_encode/_decode_conversation_cursor`）
  4. **checkpointer 消息加载** `list_messages_from_checkpointer`（1031-1224，单个 194 行函数）
  5. **token usage/pricing** `_resolve_agent_model_pricing`, `save_token_usage`（1239-1291）
  6. **attachment link** `link_attachments_to_conversation`, `resolve_turn_user_message_id`, `link_attachments_to_message`（1293-1400）
  7. **file list** `list_conversation_files`（1402-1480）
  8. **Agent runtime context 组装** `get_agent_with_tools`, `build_tools_config`, `build_effective_prompt`, `build_agent_skills`, `trigger_blocked_tools_for_agent_tree`（1513-1786）
- **问题**：8 个 cluster 几乎没有相互耦合，却放在同一文件中，导致 (a) 任何变更都必须重新理解整文件，(b) `import base64/json/uuid` + 12 个 model import 全部 top-level，而 cluster 4（checkpointer）·6（attachment）已经用函数内 deferred import（1024, 1057-1059 行）规避 cycle — god module 已经引发循环引用。(c) read/poll 路径与重型组装逻辑同模块，做 cache/performance tuning 时 blast radius 很大。
- **重构方案**：
  1. 新建 package `app/services/chat/`，现有 `chat_service.py` 保留为 **facade** 并 re-export `__all__`（向后兼容：trigger executor·conversations router 依赖 public shape — 文件 docstring 第 9-12 行已明确）。
  2. `chat/interrupts.py` ← 整体移动 cluster 1（104-493）。
  3. `chat/secrets.py` ← cluster 2（`collect_conversation_secret_values`, `_redact_response_tool_calls`）。它与 CLAUDE.md 规则（"read/poll 共享轻量 agent-only 收集"）完全对应，独立模块也更利于验证规则遵守。
  4. `chat/conversations.py` ← cluster 3（CRUD + cursor）。移动 `ConversationPageCursor`, `_encode/_decode_conversation_cursor`, `list_*_page`。
  5. `chat/messages.py` ← cluster 4（`list_messages_from_checkpointer` + deferred import 可提升到 top-level）。
  6. `chat/usage.py` ← cluster 5，`chat/attachments.py` ← cluster 6+7，`chat/runtime_context.py` ← cluster 8。
  7. facade 不使用 `from app.services.chat.interrupts import *`，只做显式 re-export。
  8. import 更新点：`grep -rl "from app.services import chat_service\|from app.services.chat_service import"` → 大多可通过 facade 保持不变。内部交叉引用（如 cluster 8 调 cluster 2）改成新模块路径。
- **验证**：`uv run pytest tests/test_chat*.py tests/test_conversations*.py tests/test_triggers.py && uv run ruff check app/services/chat`
- **预计工时**：L（包含 facade 向后兼容 + deferred import 清理）

---

### [BE-S2] MCP/tools/models 领域**完全没有 service layer** — router 直接处理 DB
- **优先级建议**：P1 — layering 违规最明显的 case。router 中混入 transaction·query·business rule，无法复用和测试。
- **类别**：结构
- **证据**：所有 router 的 raw DB 访问 224 处中排名靠前：
  - `routers/mcp.py`（825 行，**28 处**）：`_load_owned`（92）、`_load_tools_for`（103）直接 `select`，handler 直接执行 `db.add(server)`/`db.commit()`/`db.delete()`（234, 244, 292, 566, 582, 738-740）。`import_servers`（455-608）甚至在 router 中执行 credential 存在性检查 `select(Credential.id)`（492）。
  - `routers/tools.py`（11 处）：`create_tool`→`db.add`+`commit`（135-136），`run_tool_endpoint`（251）执行逻辑 inline。
  - `routers/models.py`（9 处）：`delete_model` 在 router 中执行 `select(func.count(Agent.id))` in-use check（254）。
  - 已确认 `services/` 中没有 `mcp_service.py`/`model_service.py`。`services/mcp_registry.py` 只是 static registry cache，不是 CRUD。对比之下 agents/artifacts/memory/triggers/shares 都有 service。
- **问题**：transaction boundary 在 router 中，使 scheduler·trigger·其他 router 无法复用相同逻辑 → 产生复制粘贴。ownership 规则（`_load_owned`）在各 router 重复实现，很难审计 enumeration-oracle 防护规则（security.md）是否一致应用。unit test 只能穿过 HTTP layer 才能完成。
- **重构方案**：
  1. 新建 `app/services/mcp_service.py`。从 `mcp.py` 的 `_load_owned`, `_load_tools_for`, `create_server`/`update_server`/`delete_server`/`import_servers`/`export_servers` 中**仅提取 DB 操作部分**为函数（如 `create_server(db, *, user_id, payload) -> McpServer`）。commit 统一在 service 内或 router 中其中一处（项目现有惯例 = service `flush`，router `commit` → 建议采用与 BE-S7 相同策略）。
  2. router 只保留 service 调用 + schema conversion + permission guard（`Depends`）。`_invalidate_runtime_mcp_cache`/`_record_mcp_audit` 等 side effect 也移到 service。
  3. 对 `tool_service.py`（扩展现有文件）·`model_service.py`（新建）做同样处理。`run_tool_endpoint` 执行逻辑改为 `tool_service.run_tool(...)`。
  4. import 更新：各 router 顶部 `from app.services import mcp_service`。model import 移到 service。
  5. 不需要 facade（router 不是外部复用对象）。
- **验证**：`uv run pytest tests/test_mcp*.py tests/test_tools*.py tests/test_models*.py && uv run ruff check app/services/mcp_service.py app/routers/mcp.py`
- **预计工时**：M（每个领域半天 × 3）

---

### [BE-S3] `marketplace/install_service.py` God module — 3 种安装类型 + update + delete 混在 1366 行中
- **优先级建议**：P1 — marketplace 最大文件。skill/mcp/agent_blueprint 3 类安装·重装·binding validation 交织，一个类型的修改可能破坏其他类型。
- **类别**：结构
- **证据**：`app/marketplace/install_service.py`。函数组：
  - **公共 util/snapshot**：`_skill_storage_root`, `_target_for`, `_copy_snapshot`, `_rmtree_skill_storage`, `_replace_skill_snapshot`（83-273）
  - **binding validation**：`_validate_version_credential_bindings`, `_validate_mcp_bindings`, `_apply_mcp_payload_to_server`, `_materialize_mcp_tool_snapshot`（380-540）
  - **MCP 安装**：`_install_mcp_item`（541-672），`_mcp_install_status_for_server`, `_overwrite_mcp_installation`（990-1054）
  - **Agent blueprint 安装**：`_install_agent_blueprint_item`（673-810），`_agent_blueprint_status_from_bindings`, `_apply_agent_payload_to_blueprint`, `_overwrite_agent_blueprint_installation`（1055-1153）
  - **orchestrator**：`install_item`（811-989，178 行 — 类型分支），`update_installation`（1154-1265），`delete_installation`（1266-1306），`_remove_install_artifacts`（1307）
- **问题**：`install_item` 用 if/elif 分支处理 3 种类型，并在同一文件调用各类型细节逻辑 → 修改一种类型也必须理解整文件。MCP binding validation 与 agent blueprint binding validation 相邻，容易复制粘贴和产生不一致。snapshot copy（文件系统）与 DB transaction 混在同一函数，rollback 一致性难以推理。
- **重构方案**：
  1. 新建 `app/marketplace/install/` package。
  2. `install/snapshot.py` ← snapshot/storage util（83-273）。
  3. `install/bindings.py` ← credential/mcp binding validation（338-540）。
  4. `install/skill.py` / `install/mcp.py` / `install/agent_blueprint.py` ← 各类型 `_install_*`/`_overwrite_*`/`_status_*`。
  5. 在 `install/__init__.py`（或现有 `install_service.py` facade）中只保留 `install_item`/`update_installation`/`delete_installation` **dispatcher**，委托到类型模块。
  6. 向后兼容：`routers/marketplace.py` 使用 `from app.marketplace import install_service` → 在 facade re-export 3 个 public function。
  7. import 更新：用 `grep -rn "install_service\." app/` 检查 `install_locks.py`, `origin_service.py` 是否引用 install symbol，再替换路径。
- **验证**：`uv run pytest tests/test_marketplace*.py && uv run ruff check app/marketplace/install`
- **预计工时**：L

---

### [BE-S4] `services ↔ agent_runtime` 双向耦合 → 为规避循环引用而存在的函数内 import 24 处（仅 chat_service）
- **优先级建议**：P2 — 虽无即时 bug，但模块边界已崩坏，新增耦合持续增加，deferred import 成为"隐藏 runtime 依赖"，把 import-time error 推迟到执行时。
- **类别**：结构
- **证据**：`services/` import `agent_runtime` 的文件 **30 个**，`agent_runtime/` import `services` 的文件 **14 个**（双向）。结果 `chat_service.py` 中有函数内 import 24 处（如 464-465, 515-517, 1024, 1057-1059）。`scheduler.py` 也全部使用函数内 import（117, 228-230, 313, 377, 446, 481, 522-523, 609-610, 638, 687-688）来规避启动 cycle。
- **问题**：不清楚哪一方向才是"上层 layer"。agent_runtime 调 service（DB/CRUD），service 又回调 agent_runtime（runtime assembly），形成 cycle，使 import graph 不是 DAG。deferred import 削弱 static analysis·IDE navigation，并把 typo/signature change 隐藏到 runtime。
- **重构方案**：
  1. 确定并文档化边界规则（`docs/ARCHITECTURE.md`）：**agent_runtime = 纯执行引擎，services = DB/orchestration**。只允许 `services → agent_runtime` 单向依赖。
  2. 调查 14 个 `agent_runtime → services` 反向 import（`grep -rn "from app.services" app/agent_runtime/`）。大多是 CRUD 查询（memory, followup, agent）→ 改为由**调用方（service）预加载所需数据并通过参数注入**（依赖反转）。例：`runtime_component_builder._load_memory_context` 不再直接调用 `memory_service`，而是由上层 service 查询 memory records 后放入 `AgentConfig` 传递。
  3. 只有无法反转的最小 case 才抽象为 `Protocol` interface（`app/agent_runtime/ports.py`）。
  4. 完成反转后，将 `chat_service`/`scheduler` 的函数内 import 提升为 top-level，只对剩余部分保留文档注释。
- **验证**：`uv run python -c "import app.main"`（确认启动无循环）+ 完整 `uv run pytest` + `uv run ruff check`（unused import）。
- **预计工时**：L（调查·反转设计是核心）

---

### [BE-S5] `write_tools.py` — `build_write_tools` 单函数 1093 行中包含 26 个 tool closure
- **优先级建议**：P2 — Assistant panel 的所有工具都在一个 factory function 内作为 nested closure。修改单个工具时需要加载 1093 行 scope，单工具 unit test 基本不可行。
- **类别**：结构
- **证据**：`agent_runtime/assistant/tools/write_tools.py`。单个 `def build_write_tools(`（53）中包含 `add_tool_to_agent`（72）、`remove_tool_from_agent`（107）、`add/remove_mcp_tool`（132/170）、`add/remove_middleware`（195/226）、`add/remove_subagent`（256/328）、`add/remove_skill`（367/416）、`edit/update_system_prompt`（441/478）、`update_model_config`（500）、`update_middleware_config`（554）、`update_chat_openers`（578）、`update_agent_metadata`（601）、`update_agent_identity_mode`（635）、`update_recursion_limit`（676）、5 种 cron `create/update/delete/enable/disable_cron_schedule`（696-980）等 **26 个 async closure** + 共享 helper `_get_agent_with_session`（65）、`_resolve_trigger_for_write`（789）。同级 `read_tools.py`（470）、`clarify_tools.py`（48）已经拆分。
- **问题**：closure 隐式依赖共享闭包变量（session, agent_id 等）→ 单独提取困难。cron 5 类（696-980，约 284 行）在 trigger 领域完全独立，却仍放在同一函数中。文件越大，新增工具的 diff·review 成本越高。
- **重构方案**：
  1. 用 `@dataclass WriteToolContext(session_factory, agent_id, ...)` 显式化共享 context（closure capture → 显式对象）。
  2. 按组拆成子 builder：`write_tools/tool_links.py`（add/remove tool·mcp）、`write_tools/composition.py`（middleware·subagent·skill）、`write_tools/agent_config.py`（prompt·model·metadata·identity·openers·recursion）、`write_tools/cron.py`（cron 5 类 + `_resolve_trigger_for_write`）。每个 builder 接收 `ctx` 并返回 `list[BaseTool]`。
  3. `build_write_tools` 变成只 concat 各组 builder 结果的薄 assembly。
  4. import 更新：`assistant_agent.py` 只引用 `build_write_tools`，若签名保持不变则无需修改。
- **验证**：`uv run pytest tests/test_assistant*.py && uv run ruff check app/agent_runtime/assistant/tools`
- **预计工时**：M

---

### [BE-S6] 目录 convention 双轨 — domain package（`app/marketplace/`,`mcp/`,`credentials/`,`skills/`）vs 平铺 `services/*_service.py`
- **优先级建议**：P2 — 缺少新领域应该放哪里的规则，各团队摆放方式不同。每次都要重新搜索"marketplace 逻辑在哪？"。
- **类别**：结构
- **证据**：业务逻辑同时存在于两类位置 — (a) domain package：`app/marketplace/`（19 个文件）、`app/mcp/`（7）、`app/credentials/`（11）、`app/skills/`（14）、`app/agent_api/`（6）。(b) 平铺 service：`app/services/` 有 90+ 个文件（`agent_service.py`, `artifact_service.py`, `conversation_*` 等）。不存在 `services/marketplace_service.py`（marketplace 是 package）。反之 conversation/agent CRUD 是平铺 service。同属"service layer"，物理位置规则却不同。
- **问题**：有些 domain 有自己的 package（service/schemas/payloads 内聚），另一些则散落在 `services/`（`conversation_*` 12 个文件平铺在 `services/` 根目录）。新开发者定位 domain 代码成本更高，重构时也要再次判断"这个 domain 采用哪种 convention？"。
- **重构方案**：
  1. **记录决策**（新增 ADR，例如 ADR-020 "Service layout convention"）：定义规模阈值 — "3 个及以上文件 = domain package `app/<domain>/`，不足该数量 = `services/<domain>_service.py`"。
  2. 立即迁移风险高，因此采用**新规则 + 渐进迁移**。优先把 `services/` 中内聚的组（`conversation_*` 12 个、`skill_evaluation_*` 20+ 个、`skill_builder_*` 8 个、`skill_revision_*` 5 个、`model_*` 6 个）分别归入 `services/conversation/`、`services/skill_evaluation/`、`services/skill_builder/` 子 package（纯移动 + facade）。
  3. 需要 facade：移动后的模块通过 `services/__init__` 或薄 re-export 保留旧 import 路径，再渐进更新调用处。
- **验证**：`uv run pytest`（全部）— 因为是纯移动，应保持全绿。`uv run ruff check app/services`。
- **预计工时**：M（规则决策 S + 子包化 M）

---

### [BE-S7] `credentials.py` router 直接持有约 286 行 OAuth2 flow 业务逻辑
- **优先级建议**：P1 — secret/token exchange 属于安全敏感路径，但 orchestration 在 router 中，难以复用、测试和审计。credentials 已有 `app/credentials/service.py`，属于"部分 service"，只有 OAuth 仍留在 router。
- **类别**：结构
- **证据**：`routers/credentials.py`（786 行）。CRUD 委托给 `credential_service.create/update`（已确认 156-180），但**commit 在 router 中**（`await db.commit()` 176）。OAuth 相关全部在 router：`_prepare_mcp_oauth_data`（491）、`_persist_credential_payload`（574）、`_gc_oauth_states`（584，直接 `db.execute`）、`oauth2_auth_start`（617，`db.add(CredentialOAuthState)` 667）、`oauth2_callback`（708，`select(CredentialOAuthState)` 718 + `select(Credential)` 732 + token exchange + `db.commit` 777）。另有 `credentials/mcp_oauth_client.py`（474 行），但 router 在其上层重复持有 orchestration。
- **问题**：OAuth state 创建/哈希/存储/callback/token exchange/GC 都 inline 在 HTTP handler → MCP server 注册 flow（mcp.py）或 scheduler state GC 无法复用同一逻辑。安全 review 必须通读 router 代码。`_gc_oauth_states` 与 scheduler GC job 概念重复。
- **重构方案**：
  1. 新建 `app/credentials/oauth_service.py`。移动 `_prepare_mcp_oauth_data`, `_persist_credential_payload`, `_gc_oauth_states`、`oauth2_auth_start`/`oauth2_callback` 的 **DB·token exchange 逻辑**。函数签名为 `start_oauth(db, *, user, credential_id) -> AuthStartResult`, `handle_callback(db, *, code, state) -> Credential`。
  2. 明确 `mcp_oauth_client.py` 的角色：client=底层 HTTP，oauth_service=DB 状态·orchestration。
  3. router 只保留 service 调用 + redirect/response conversion。
  4. 统一 transaction 策略：service `flush`，router `commit`（与当前 create 模式一致），或反过来作为项目全局决策（与 BE-S2 一起）。
  5. 将 `_gc_oauth_states` 暴露为 service function，供 scheduler 复用。
- **验证**：`uv run pytest tests/test_credentials*.py tests/test_*oauth*.py && uv run ruff check app/credentials/oauth_service.py`
- **预计工时**：M

---

### [BE-S8] `artifact_service.py`（1037 行）— delta recorder/ingest + CRUD + library query + storage helper 混杂
- **优先级建议**：P2 — streaming 中的文件检测（hot path）与 library 查询（read path）在同一模块，不同性能特性的代码被耦合。
- **类别**：结构
- **证据**：`services/artifact_service.py`。cluster：
  - **snapshot/delta/ingest**：`ArtifactFileState`~`ArtifactDeltaRecorder`（45-151），`snapshot_output_dir`（152），`diff_snapshots`（211），`ingest_changed_files`（230-364）
  - **run 级 finalize/link**：`link_artifacts_to_messages`（392），`finalize_artifacts_for_run`（413）
  - **library/query CRUD**：`list_conversation_artifacts`（365），`list_library_artifacts`（503），`list_recent_artifacts`（574），`set_artifact_favorite`（601），`record_artifact_opened/download`（614/627），`get_library_stats`（639），`delete_artifact`（774）
  - **content/storage helper**：`read_artifact_text_content`（697），`get_artifact_download_path`（729），`_storage_local_path`（834），`_sha256_file*`（1016-1027），`_summaries_from_artifacts`（841），`_file_event_payload`（1028）
- **问题**：delta recording（runtime streaming 每个文件事件都会调用）和 library pagination（UI polling）放在同一文件 → 修改一边可能让另一边回归，import surface 过宽。
- **重构方案**：
  1. 将其 package 化为 `app/services/artifacts/`，`artifact_service.py` 保留 facade。
  2. `artifacts/recorder.py` ← `ArtifactFileState`/`ArtifactSnapshot`/`ArtifactDelta`/`ArtifactDeltaRecorder`/`snapshot_output_dir`/`diff_snapshots`/`ingest_changed_files`/`finalize_artifacts_for_run`.
  3. `artifacts/library.py` ← query/favorite/stats/cursor（包含 `_encode/_decode_library_cursor`）。
  4. `artifacts/content.py` ← text read·download·sha256·storage_local_path。
  5. `artifacts/summary.py` ← `_summaries_from_artifacts`/`_summary_from_*`/`_file_event_payload`.
  6. 在 facade re-export 现有 public symbol（保留 streaming.py·routers/artifacts.py 依赖；用 `grep -rn "artifact_service\." app/` 确认位置）。
- **验证**：`uv run pytest tests/test_artifact*.py && uv run ruff check app/services/artifacts`
- **预计工时**：M

---

### [BE-S9] `scheduler.py`（752 行）— 11 个 job 的业务逻辑与注册代码 inline 在同一模块
- **优先级建议**：P2 — scheduler 应只知道"何时运行什么"，却连"怎么做"也持有，因此 job 逻辑修改与 scheduler 启动耦合。全部采用函数内 import 来规避循环（BE-S4 的症状）。
- **证据**：`app/scheduler.py`。`_run` body 中 inline 实际业务逻辑：`rotate_credentials_to_active_key`（218-253，credential rotation algorithm）、`poll_mcp_servers_health`（511-571，MCP health polling）、`sweep_stale_conversation_runs`（607-631）、`cleanup_skill_runtime_roots`（679），`draft_conversation_gc_run`（436）/`orphan_attachment_gc_run`（472）虽然委托给 `chat_service`（446, 481），其余仍 inline。每个 job 都有配对 `register_*_job()`（11 对）。所有依赖都是函数内 import。
- **问题**：job 逻辑 unit test 必须经过 scheduler module。credential rotation 等算法存在于 scheduler，无法手动执行或复用（MEMORY 审计中指出的 `rotate_credentials 无限循环` 逻辑就 inline 在这里）。启动时又因 cycle 导致所有函数延迟 import。
- **重构方案**：
  1. 将 job **body（逻辑）**移到各 domain service：`rotate_credentials_to_active_key` → `credentials/service.py`（或新建 `credential_rotation.py`），`poll_mcp_servers_health` → `services/mcp_service.py`（与 BE-S2 联动），`sweep_stale_conversation_runs` → `conversation_run_service.py`，`cleanup_skill_runtime_roots` → `marketplace/skill_runtime.py`。
  2. `scheduler.py` **只保留注册**：`register_*_job()` 通过 `scheduler.add_job(target=service.fn, ...)` 引用 service function。`_job_id`/`_naive_utc`/`get_scheduler`/leader-election（27-92）属于纯基础设施，保留。
  3. 逻辑移入 service 后可使用 top-level import，移除函数内 import（部分解决 BE-S4）。
  4. 不需要 facade。
- **验证**：`uv run pytest tests/test_scheduler*.py tests/test_credentials*.py tests/test_mcp*.py && uv run python -c "import app.scheduler"`
- **预计工时**：M

---

### [BE-S10] `runtime_component_builder.py`（828 行）— model assembly + middleware + memory + prompt + interrupt policy 多关注点
- **优先级建议**：P2
- **证据**：`agent_runtime/runtime_component_builder.py`：
  - **model candidate/fallback**：`_resolve_middleware_model_params`（103），`_model_constructor_params`（133），`_model_chain`（154），`_build_model_candidates`（166），`_build_model_with_fallback`（219），`_is_retryable_model_error`（225）
  - **reliability middleware**：`_has_visible_ai_content`（233），`EmptyContentRetryMiddleware`（254），`_build_default_reliability_middleware`（279）
  - **interrupt policy**：`_default_interrupt_on_from_tools`（354），`_build_interrupt_on_policy`（363）
  - **memory**：`_recalled_memory_briefs`（448），`_load_memory_context`（464，反向 import `memory_service`），`_memory_write_policy_for_run`（500）
  - **prompt builder**：`_system_prompt_with_temporal_context`（428），`_memory_tool_instruction_prompt`（521），`_interactive_tool_instruction_prompt`（541），`_artifact_file_instruction_prompt`（557）
  - **orchestrator**：`_prepare_runtime_components`（571），`_prepare_agent`（752），`build_agent`（66）
- **问题**：model fallback 逻辑·middleware 定义·prompt 字符串·memory 查询放在同一文件，各自的修改原因不同（provider quirk vs prompt copy vs memory policy），容易冲突。`EmptyContentRetryMiddleware` class 甚至定义在 assembly 模块中。
- **重构方案**：
  1. `agent_runtime/runtime/models.py` ← model candidate/fallback/retry 判定（103-231）。
  2. `agent_runtime/runtime/reliability.py` ← `EmptyContentRetryMiddleware` + `_build_default_reliability_middleware`.
  3. `agent_runtime/runtime/interrupts.py` ← interrupt policy（354-393）。（与 CLAUDE.md 的 `_default_interrupt_on_from_tools` 规则对应 → 独立模块更利于规则追踪。）
  4. `agent_runtime/runtime/prompts.py` ← 4 个 prompt builder（428, 521-570）。
  5. `agent_runtime/runtime/memory_context.py` ← 3 个 memory function（BE-S4 的反转对象 — 在这里把直接调用 `memory_service` 改为参数注入）。
  6. `runtime_component_builder.py` 只保留 `_prepare_runtime_components`/`_prepare_agent`/`build_agent` assembly，并 import 上述模块。
- **验证**：`uv run pytest tests/test_runtime*.py tests/test_agent_stream*.py tests/test_memory*.py && uv run ruff check app/agent_runtime/runtime`
- **预计工时**：M

---

### [BE-S11] `marketplace/` projection 逻辑分散 — `service.py` + `origin_service.py` 重复持有 install/publish 状态计算
- **优先级建议**：P3
- **证据**：`marketplace/service.py` 的 `_project_item`（261）/`_project_items`（383）/`_publication_state_for_owner`（404）与 `marketplace/origin_service.py` 的 `derive_origin_summary_for_skill`（70）/`_derive_publication_state`（128）/`derive_publication_summary_for_skill`（156）/`bulk_derive_publication_summaries`（198）/`derive_installation_summary`（265）/`bulk_derive_installation_summaries`（587）都在计算"catalog item 的 publish·install 状态"。`_publication_state_for_owner`（service.py）和 `_derive_publication_state`（origin_service.py）连名称都体现关注点重复。
- **问题**：publish 状态规则变化时必须同步修改两个文件，漏改会导致 catalog list 与 detail 不一致。`origin_service.py`（786 行）实际上已经是"projection service"，但 `service.py` 也在做 projection。
- **重构方案**：
  1. 将 projection 计算收敛到单一模块 `marketplace/projection.py`：合并 `_publication_state_for_owner` 和 `_derive_publication_state`（通过参数区分 owner 视角/viewer 视角）。
  2. `service.py` 只负责 catalog **query/pagination**（`_base_catalog_query`, `list_items_page` 等），`projection.py` 只负责状态派生，`origin_service.py` 只负责 installation summary。
  3. 合并前用测试固定两种状态计算实际结果相同（characterization test）后再统一。
- **验证**：`uv run pytest tests/test_marketplace*.py -k "project or publication or installation" && uv run ruff check app/marketplace`
- **预计工时**：M

---

### [BE-S12] `config.py`（262 行）/ `dependencies.py`（182 行）肥大化检查 — **建议保持现状（无需重构）**
- **优先级建议**：P3 — 低于阈值。根据避免过度拆分（Simplicity First）原则，明确建议现在不要动。
- **证据**：`app/config.py` — 单个 `Settings(BaseSettings)` 有 101 个字段，但按 section comment 划分良好（6-262）。`app/dependencies.py` 182 行 — 只有 DI，不算过大。
- **重构方案**：**不要做。** 当前 no-op。
- **预计工时**：S（仅判断）

---

### 总结 — 按优先级整理

| ID | 标题 | 优先级 | 工时 |
|----|------|:---:|:---:|
| BE-S1 | chat_service.py God module 拆分 8 个 cluster | **P1** | L |
| BE-S2 | MCP/tools/models 缺少 service layer（router raw DB） | **P1** | M |
| BE-S3 | install_service.py 3 类型 God module 拆分 | **P1** | L |
| BE-S7 | credentials router OAuth 逻辑 → oauth_service | **P1** | M |
| BE-S4 | 反转 services↔agent_runtime 双向耦合 | P2 | L |
| BE-S5 | 拆分 write_tools.py 1093 行单一 factory | P2 | M |
| BE-S6 | 目录 convention 双轨（ADR + 渐进子包化） | P2 | M |
| BE-S8 | artifact_service.py 拆分 recorder/library/content | P2 | M |
| BE-S9 | scheduler.py job 逻辑 → domain service | P2 | M |
| BE-S10 | runtime_component_builder.py 拆分 5 个关注点 | P2 | M |
| BE-S11 | 统一 marketplace projection 重复（service↔origin_service） | P3 | M |
| BE-S12 | config/dependencies — **保持现状（不要做）** | P3 | S |

**建议启动顺序**：BE-S2·BE-S7（layering 违规 = 答案明确，blast radius 小）→ BE-S1·BE-S3（最大 god module，用 facade 可安全拆）→ BE-S4·BE-S9（cycle/scheduler 一起解决有协同）→ 其余 P2 → BE-S6 在 ADR 决策后渐进。

**核心洞察**：该代码库具备拆分能力（`conversation_agent_protocol*` 18 个文件、executor split、marketplace 细分就是证据）。问题是**一致性** — 同样模式还没有应用到 chat/artifact/scheduler/write_tools/install。大多可以通过 facade 纯移动，风险低。唯一真正的设计难题是 BE-S4（services↔agent_runtime 方向反转），也是多个 god module 出现函数内 import 气味的根因。

---

## 5. 后端 — 性能 (BE-P)

**范围**：只读分析 `backend/app`。7 个并行调查（N+1、blocking、index、streaming、scheduler、pool/pagination）+ 核心文件直接验证。
**优先级标准**：用户体感频率 × 成本。**P1 = 每个活跃聊天都会重复的 polling/streaming hot path 或全局 event loop blocking** / P2 = 随数据增长无限恶化或写入/安装路径 / P3 = 管理·后台路径。

---

### [BE-P1] 每次 `GET /messages` polling 的 pending-interrupt hydration 都按 MessageEvent row 单独查询（N+1）
- **优先级建议**：**P1** — `GET /messages` 是每个活跃对话都会重复 polling 的顶级 hot path。对话越长，每次 polling 的 query 数线性增长。
- **类别**：性能（N+1）
- **证据**：`services/chat_service.py:468-491`（loop）+ `services/trace_storage.py:163-171`（每 row 一次 query）
  ```python
  # chat_service.py:473-478
  for record in result.scalars().all():
      target_responses = [response_by_id[mid] for mid in linked_ids if mid in response_by_id]
      if not target_responses:
          continue
      events = await trace_storage.load_events(db, record)   # ← loop 内 await DB
  ```
  `load_events` 对每个 `record` 执行 1 次 `select(MessageEventChunk.events).where(message_event_id == record.id)`。经 `_messages_to_response`（`chat_service.py:1136`，存在 `user_id` 时）会在**所有已认证 `GET /messages` 中执行**。
- **问题**：40 轮 tool call 对话 = 1（parent）+ 最多 40（chunk）= 每次 polling 41 次 query。随对话长度线性增长，而且聊天 UI 每次 polling 都重复。
- **重构方案**：
  1. loop 前只筛选 `target_responses` 非空的 `record` 并收集 id。
  2. 用单次 IN query：`select(MessageEventChunk.message_event_id, MessageEventChunk.events).where(message_event_id.in_(ids)).order_by(message_event_id, seq_start, created_at)` 批量加载。
  3. 以 `dict[event_id, list[events]]` 分组后 in-memory 合并。→ N+1 降为 2 次 query。
- **验证**：SQLAlchemy `echo=True` 或 pytest query counter fixture，确认 40 轮对话 polling 的 query 数从 41→2。
- **预计工时**：**M**

---

### [BE-P2] `GET /messages` 无限制加载整个对话（无 pagination·上限）
- **优先级建议**：**P1** — 与上面相同的 polling hot path。与 checkpointer pool（BE-P7）直接叠加恶化。
- **类别**：性能（pagination）
- **证据**：`routers/conversation_messages.py:137` → `services/chat_service.py:1031, 1079`
  ```python
  # chat_service.py:1079
  messages = [node.message for node in tree.nodes]   # 无 limit/cursor
  ```
  `build_message_tree` 每次调用遍历完整 checkpoint tree 并序列化全部消息。
- **问题**：数百~数千轮/branch 的对话每次 polling 都重新遍历完整 tree + 全量序列化。checkpointer pool connection 也在每次 polling 被占用（与 BE-P7 复合）。
- **重构方案**：
  1. 返回最近 N 条消息 + 反向 keyset cursor（基于 message index）。旧 turn lazy-load。
  2. 至少强制 hard max limit。
  3. polling 路径避免重新遍历完整 checkpoint tree（增量/cache）。
- **验证**：用 500 轮对话 fixture 测量 `GET /messages` response size·latency，对比应用上限前后。
- **预计工时**：**L**（涉及 checkpoint tree 遍历结构修改）

---

### [BE-P3] polling 路径的 `build_tools_config` 对每个 MCP tool link 重复 `SELECT … FOR UPDATE`（N+1 + 不必要 lock）
- **优先级建议**：**P1** — `collect_conversation_secret_values`（`chat_service.py:568`）在**所有 `GET /messages`·`GET /threads/{id}/state` polling** 中执行。read 路径甚至会拿 row lock。
- **类别**：性能（N+1 + lock contention）
- **证据**：`services/chat_service.py:1702-1734`（loop）+ `mcp/auth.py:61-64`
  ```python
  # chat_service.py:1719
  resolved_auth = await resolve_mcp_auth(db, credential_id=server.credential_id, ...)
  # mcp/auth.py:64
  credential = (await db.execute(stmt.with_for_update())).scalar_one_or_none()
  ```
  而且该 credential row 已由 `_agent_runtime_load_options`（`chat_service.py:1521-1524`, `selectinload(McpTool.server).selectinload(McpServer.credential)`）eager load，**重复查询本身就是多余的**。
- **问题**：有 credential 的 MCP tool 为 M 个时，每次 polling 执行 M 次 `SELECT … FOR UPDATE`。(1) 随 MCP tool 数线性增长，(2) 纯 read 路径拿 row lock → 与并发 stream 产生 lock contention。
- **重构方案**：
  1. `collect_conversation_secret_values`（read 路径）给 `build_tools_config` 传 `db=None` → 使用已 eager-load 的 `server.credential` 通过 `decrypt_cached` in-memory 解密（1733 行已有该分支）。
  2. 如果 run 路径必须保留 `resolve_mcp_auth`，read caller 去掉 `.with_for_update()` + 用 `WHERE id IN (...)` 批量。
- **验证**：polling 时观察 `pg_locks` + query counter，确认 M+1→0（read 路径）。
- **预计工时**：**S~M**

---

### [BE-P4] bcrypt 哈希/验证完全阻塞 event loop（每次登录·注册约 250ms）
- **优先级建议**：**P1** — 单次登录会让**整个 server** 的所有并发 SSE stream·polling·API 停顿约 250ms。credential-stuffing 时 server 串行化。
- **类别**：性能（event loop blocking）
- **证据**：`services/auth_service.py:113, 131`（+`:84`），`auth/password.py:28`
  ```python
  # auth_service.py:131  (async def authenticate)
  if not verify_password(password, user.hashed_password):   # ~250ms 同步
  # auth_service.py:113  不存在的 email 也以 timing pad 支付同等成本
  verify_password(password, _DUMMY_PASSWORD_HASH)
  # password.py:28  bcrypt__rounds=12  （有意的慢 KDF）
  ```
- **问题**：bcrypt cost-12 ≈ 250ms 在 loop thread 执行 → 期间任何 coroutine 都无法调度。失败/假登录也因 pad 消耗 250ms。
- **重构方案**：用 `await asyncio.to_thread(verify_password, …)` / `await asyncio.to_thread(hash_password, …)` offload 到 worker thread。`_DUMMY_PASSWORD_HASH`（`:43`）在 import time，与此无关。
- **验证**：用负载工具并发登录 20 rps + 单独测 `GET /health` latency，对比 to_thread 前后 p99。确认现有 auth test 回归。
- **预计工时**：**S**

---

### [BE-P5] 每个 SSE streaming event 的重复成本（redaction 2 次 + 被丢弃的 json.dumps + secret set 重排 + O(n²) event id reload）
- **优先级建议**：**P1** — 乘以每 token（每个回复 10²~10³ 次）的 hot path。多个子项叠加。
- **类别**：性能（per-event CPU + 近似 quadratic DB）
- **证据**:
  - **(a) 每个 event 都做却丢弃的 `json.dumps`** — `agent_runtime/protocol_events.py:50-55`，无条件调用（`:104`）。为验证可序列化性，用 stdlib `json.dumps` 完整编码后丢弃结果。`values` event 每次会重新编码完整 graph state。
  - **(b) redaction 2 次** — `langgraph_streaming.py:338-354`（wire）+ `protocol_persistence.py:15-24`（persist）。`redact_protocol_data` 每个 event 做**两次**完整递归（`_mask_known_values` + `_redact_sensitive_keys`）。
  - **(c) 每个字符串 node 都重建 secret set** — `marketplace/redaction.py:70-80`。run 内不变的 secret set 对字符串 key/value 每次都重新建 `set` + `sorted(key=len)`。
  - **(d) O(n²) event id reload** — `services/trace_storage.py:147-160`。每次 partial flush（32 项/2s）都重新 SELECT **累计全部** chunk `event_ids` 并建 set。一个 T event turn 约为 O(T²/64)。
  - **参考（良好）**：所有 redaction regex 都在 module-level `re.compile`，value masking 用 `str.replace`（无 ReDoS），DB persistence 以 32 项/2s batch。没有 compile-in-loop。
- **问题**：2000 token 回复 = json.dumps 2000 次（resequence 时 2 倍，`values` 是完整 state）、redaction 2×2000 递归、secret 排序约 16k 次、event id reload 累计约 62k。deep research/multi-tool 长 turn 中 CPU·DB 暴涨。
- **重构方案**：
  1. (a) 移除 `_jsonable` 中仅用于验证的 `json.dumps`（payload 已由 `_serialize_value` 规范化）或放到 debug flag 后。
  2. (b) wire 只做 1 次 redaction，persist 只额外 compact `values`/`updates` — 移除重复 redaction。
  3. (c) 每个 run 1 次 `sorted(unique, key=len)` memoize（ContextVar set identity key），再注入 `replace_secret_values`。
  4. (d) 在 persist closure（`conversation_stream_service.py:349`）维护 run-scoped `seen_event_ids` set，只有 retry 路径才 reload DB。
  5. （追加）v3 flush 在 `emit` 中 inline `await`（`langgraph_streaming.py:354`），会阻塞 token emission → 改成与 legacy 相同的 `asyncio.create_task` fire-and-forget（`streaming.py:338`）模式。
- **验证**：在 2000-token scripted model run 中做 per-event CPU profile（py-spy）+ 测量长 turn 总 query 数，比较优化前后。
- **预计工时**：**M**（子项可独立应用，(d) 单独）

---

### [BE-P6] 缺少 FK·filter column index（5 项，全部需要新 Alembic migration）
- **优先级建议**：**P2** — 尤其 `token_usages` 是 schema 中增长最快（每个 LLM turn 1 row）的表，却有 **0 个非 PK index**。
- **类别**：性能（index）
- **证据**（逐一对照 66 个 migration 确认确实不存在）：
  1. `models/token_usage.py:20` `agent_id` FK — `usage_service.py:18-23` 的 `SUM(...) WHERE agent_id = ?`（`GET /api/agents/{id}/usage`）每次都 full scan。**已直接确认完全没有 index**（只有 PK）。
  2. `models/token_usage.py:17` `conversation_id` FK（`ON DELETE CASCADE`）— 删除对话时 cascade full table scan。
  3. `models/message_attachment.py:28` `conversation_id` FK — 在 `chat_service.py:1176-1178`（`GET /messages` polling）+ `/files`（`:1450`）中过滤。唯一 index 是 `message_id`（m28）。
  4. `models/mcp_server.py:44` `user_id` FK — MCP server list（`routers/mcp.py:200`）等大量 `WHERE user_id = ?`。完全没有 index。
  5. `models/agent_trigger.py:16` `agent_id` FK — `trigger_service.py:203`, `agent_service.py:544`。现有 composite（`(user_id,status)` m47，`(status,next_run_at)` m53）不是以 `agent_id` 开头，因此不覆盖。
- **重构方案**：在新 Alembic migration 中创建 `Index("ix_token_usages_agent_id","agent_id")`、`ix_token_usages_conversation_id`、`ix_message_attachments_conversation_id`（可考虑 partial index `WHERE message_id IS NOT NULL`）、`ix_mcp_servers_user_id`、`ix_agent_triggers_agent_id`（或 `(agent_id,status)` composite）。模型已经在 production 存在，只加 `index=True` 不够 → 必须 migration。
- **验证**：用 `EXPLAIN ANALYZE` 确认切换到 index scan + 大量 row seed 后测 latency。
- **预计工时**：**S**（1 个 migration）

---

### [BE-P7] checkpointer pool `max_size=10` 全局瓶颈 + 主 engine pool 使用库默认值
- **优先级建议**：**P2** — CLAUDE.md 已记录症状（"slow streaming/大量 eval run 并发 → backend 串行化，无关 request timeout"）。
- **类别**：性能（connection pool）
- **证据**:
  - `agent_runtime/checkpointer.py:47-53` — `AsyncConnectionPool(min_size=1, max_size=10)`。所有 stream write + **read polling** 共享、争抢这 10 个 connection。
  - `database.py:15` — `create_async_engine(url, echo=False, pool_pre_ping=True)`。`pool_size`/`max_overflow`/`pool_timeout`/`pool_recycle` 全未设置 → 默认 5+10=15，`pool_recycle=-1`。config 中没有 engine pool knob。
  - httpx：tool client singleton（`tool_factory.py:97`）+ model client cache（`model_factory.py`）是**良好实践**。
- **重构方案**：
  1. 提高 `CHECKPOINTER_POOL_MAX_SIZE`（例如 20~30，从 PG `max_connections` 中扣除 engine 配额），`min_size` 设 2~4 保持 warm。
  2. 把 engine `pool_size`/`max_overflow`/`pool_recycle`（例如 1800s）暴露到 settings 并配置。
  3. 通过 BE-P2 降低 read 路径本身的 pool 压力。
- **验证**：并发 N 个 stream + polling load 时观察 `pg_stat_activity`·pool wait，对比提升前后 timeout rate。
- **预计工时**：**S**（配置）~ M（暴露 engine knob）

---

### [BE-P8] `health_check_history` 无限增长 — retention 设置是 dead code
- **优先级建议**：**P2**
- **类别**：性能（table bloat）
- **证据**：`services/health_check.py:222-225, 296`（daily cron `0 4 * * *`）— 每 model/server 每天 1 INSERT。`config.py:88` `health_check_history_retention_days: int = 90` **没有任何引用**，也没有 `delete(HealthCheckHistory)` 代码。
- **重构方案**：
  1. 新增 GC job：`DELETE FROM health_check_history WHERE checked_at < now() - retention_days`（配置已存在）。
  2. 给 `checked_at` 添加 index。
  3. disabled/未使用 model 不做每日 probe。
- **验证**：大量 seed 后执行 GC job，确认 row 数下降。
- **预计工时**：**S**

---

### [BE-P9] `mcp_health_poll` 每 5 分钟串行重新 probe 所有活跃 MCP server
- **优先级建议**：**P2**
- **类别**：性能（scheduler job）
- **证据**：`scheduler.py:511, 532, 544`（`IntervalTrigger(minutes=5)`）— `select(McpServer).where(or_(is_system.is_(True), status != "disabled"))` 无 LIMIT，`for server in rows:` 顺序执行 — 每个 server 都做 credential decrypt + connect_and_list live roundtrip。
- **问题**：每 5 分钟串行执行 `O(#server)` network connect。error/unreachable server 也没有 backoff，持续重复。
- **重构方案**：
  1. 用 bounded `asyncio.gather`/semaphore 并行化（`check_all_active` 已有相同模式）。
  2. 设置 per-probe timeout budget。
  3. 仅对 `health_polled_at` stale server 做增量 polling + 对持续失败 server 做指数 backoff。
- **验证**：seed 50 个 server 后，测量 sweep wall-clock 并行化前后差异。
- **预计工时**：**M**

---

### [BE-P10] Marketplace MCP 安装时每个 tool 单独 SELECT — 所需 batch query 在下面 3 行已经存在
- **优先级建议**：**P2**
- **类别**：性能（N+1）
- **证据**：`marketplace/install_service.py:489-524` — `:498` loop 内每个 tool 执行 `select(McpTool)...limit(1)`，而 `:522` loop 后立刻执行了恰好所需的 batch query。
- **重构方案**：将 `:522` query hoist 到 loop 前 → `existing_by_name = {t.name: t for t in existing_tools}` → loop 内 `existing_by_name.get(name)`。`:532` stale link 删除也改为单条 `delete(...).where(mcp_tool_id.in_(stale_ids))`。
- **验证**：安装 30-tool server 时确认 query count。
- **预计工时**：**S**

---

### [BE-P11] run 文件 ingest 的 `ingest_changed_files` 对每个变更文件执行多次 SELECT
- **优先级建议**：**P2**
- **类别**：性能（N+1）
- **证据**：`services/artifact_service.py:239-298` — `:245` 存在性检查、`:274` 再检查、`:291` max(version_number) — 都按 delta（文件）执行。`_summary_from_artifact`（`:269/:359`）还会额外执行 `_current_version` SELECT。
- **重构方案**：
  1. loop 前执行 `select(ConversationArtifact).where(conversation_id, assistant_msg_id, logical_path.in_([...]))` → `{logical_path: artifact}`。
  2. batch 执行 `select(ArtifactVersion.artifact_id, func.max(version_number)).where(artifact_id.in_(...)).group_by(...)`。
  3. loop 只做 in-memory 查询 + insert。
- **验证**：10 个文件变更的 run 中测量 query 数。
- **预计工时**：**M**

---

### [BE-P12] 无限制列表：`GET /api/memories` 无上限 + Marketplace OFFSET pagination
- **优先级建议**：**P2**
- **类别**：性能（pagination）
- **证据**:
  - `services/memory_service.py:368-373` — 没有 limit/cursor（router `routers/memory.py:81-96` 甚至没有 `limit` 参数）。对比 `list_runtime_memory_records`（`:376`）已经用 `.limit(RUNTIME_MEMORY_MAX_RECORDS)` 设置上限。
  - `marketplace/service.py:207, 460-507` — `.limit(limit).offset(offset)` + post-filter，页面没填满时循环用 `raw_offset += batch_size` 重新查询。
- **重构方案**：
  1. memories：`limit`（server 强制 max）+ `(updated_at, id)` keyset — 复用 conversation list 模式。
  2. Marketplace：切换到 `(created_at, id)` keyset + 尽可能把 post-load filter push down 到 SQL。
- **验证**：大量 seed memory/Marketplace item 后比较 deep page latency。
- **预计工时**：**M**

---

### [BE-P13] async handler 内的同步 CPU/文件操作（web_scraper HTML parsing、Skill zip export）
- **优先级建议**：**P3**
- **类别**：性能（event loop blocking）
- **证据**:
  - `agent_runtime/tool_factory.py:164-170` — `async def scrape_url` 内执行 `BeautifulSoup(resp.text,"html.parser")` + `get_text()`。数 MB HTML parsing 在 loop 中进行。
  - `routers/skills.py:237` → `skills/package_exporter.py:12-34` — async handler 直接调用同步 zip build。
  - `routers/skill_files.py:40, 53` — 同步文件读取（轻微）。`image_service.py:139` 首次加载静态 PNG 同步执行（有 cache，轻微）。
  - **参考（良好）**：`skill_executor.py`、`mcp/client.py`、`skills/service.py`、install/publish 的 zip/shutil 已经使用 `asyncio.to_thread`。credential decrypt 为 sub-ms。
- **重构方案**：将 `BeautifulSoup` block 拆成 sync helper，用 `await asyncio.to_thread(...)`（或限制 `resp.text` 长度）。`zip_bytes = await asyncio.to_thread(build_installed_skill_zip_bytes, ...)`。skill_files 的两个读取路径也改为 `to_thread`。
- **验证**：用大型 HTML/package 测量 scrape·export 期间其他 request latency。
- **预计工时**：**S**

---

### 附加任务 — 2026-07-03 审计 3 项当前状态

| 项目 | 判定 | 证据 |
|------|------|------|
| **web_scraper SSRF** (`tool_factory.py`) | **STILL PRESENT（未修复）** | `tool_factory.py:149-162` 的 `scrape_url` 对模型提供的 URL 不做验证就 `client.get(url)`。共享 client 设置 `follow_redirects=True`（`:102-106`），因此可经 redirect SSRF。完全没有 `ipaddress`/`is_private`/`169.254`/`localhost`/allowlist guard — 未阻断 localhost·RFC-1918·云 metadata `169.254.169.254`·`file://`。 |
| **rotate_credentials 无限循环** (`scheduler.py:235-251`) | **PARTIALLY FIXED** | 移除 OFFSET 后原有 OOM/cursor 不前进问题有所缓解。但仍有 **no-progress 无限循环**：若 `re_encrypt_with_active_key` 对一个 batch（≥`_ROTATION_BATCH=100`）全部持续失败，就会重新 fetch 同一批 row；终止 guard `if len(rows) < _ROTATION_BATCH` 因 batch 始终满额不会触发 → `while True` 无限。需要排除失败 id/no-progress break/max-iter cap。 |
| **trigger 重复执行** (`trigger_executor.py:80-122`) | **PARTIALLY FIXED** | `execute_trigger` 没有 DB concurrency guard（无 status→running claim/idempotency）。APScheduler `coalesce=True, max_instances=1` + leader lock 可防止单进程内重复。但 **run-now（`routers/triggers.py:167`）绕过 APScheduler** → schedule 执行 in-flight + 用户同时 run-now = 双重执行。需要 DB 层 `SELECT … FOR UPDATE` 或 in-flight run partial unique index。 |

---

### 总结（按优先级）

- **P1（聊天 hot path / 全局 blocking）**：BE-P1（polling N+1 hydration）、BE-P2（无限制消息加载）、BE-P3（polling MCP `FOR UPDATE` N+1）、BE-P4（bcrypt loop blocking）、BE-P5（每个 SSE event 重复成本）
- **P2**：BE-P6（5 个 index）、BE-P7（checkpointer pool+engine pool）、BE-P8（health history 膨胀）、BE-P9（MCP poll 串行）、BE-P10（安装 N+1）、BE-P11（ingest N+1）、BE-P12（无限制/offset pagination）
- **P3**：BE-P13（async blocking parsing/zip）

**杠杆最大的 4 项**：BE-P4（bcrypt `to_thread`，工时 S，全局影响）→ BE-P1/BE-P3（移除 polling N+1，工时 S~M）→ BE-P6（index migration，工时 S）→ BE-P7（提升 pool，工时 S）。

**安全注意**：web_scraper SSRF 不是性能问题，而是**未修复的安全问题**，建议独立 track。rotate_credentials·trigger 重复执行仍处于部分修复状态，残留风险存在。

---

## 6. 后端 — 重复 (BE-D)

### [BE-D1] 所有权查询+None 检查→not_found() 模式在 router 全面重复
- **优先级建议**：P1
- **类别**：重复
- **证据**：`conv = await chat_service.get_owned_conversation(db, conversation_id, user.id)` + `if conv is None/not conv: raise conversation_not_found()` 的 3 行 block 在 **13 个文件 30 个调用处**重复：
  - `conversation_traces.py:52-54, 67-69`
  - `conversation_branches.py:118-120, 224-226`
  - `conversation_files.py:35-37, 51-53`
  - `conversation_messages.py:142-144`, `conversation_runs.py:110-112, 132-134`
  - 其余 `conversation_run_cancel/ag_ui/followup/crud`, `artifacts.py`, `shares.py`
  - 另外 `agents.py` 将 `get_agent(db, agent_id, user.id)`+`agent_not_found()` **重复 6 次**（185/200/236/268/297/316），`assistant.py` 也使用同一 getter
- **问题**：(1) None 检查混用 `if conv is None` 和 `if not conv` 两种形式 — 风格 drift。(2) 新增 conversation endpoint 时容易漏掉 ownership guard（漏掉即 IDOR）。(3) enumeration-oracle 统一规则（单一 404 response）依赖各调用处手动遵守 — 只要一处 raise 403，规则就被破坏。
- **重构方案**：
  1. 在 `app/dependencies.py` 中增加 ownership resolver dependency factory：
     ```python
     def owned_conversation(
         conversation_id: uuid.UUID,
         db: AsyncSession = Depends(get_db),
         user: CurrentUser = Depends(get_current_user),
     ) -> Conversation:  # async
         conv = await chat_service.get_owned_conversation(db, conversation_id, user.id)
         if conv is None:
             raise conversation_not_found()  # 将单一 404 response 规则封装在一个位置
         return conv
     ```
     endpoint 使用 `conv: Conversation = Depends(owned_conversation)`，一次吸收 path param + ownership + 404。
  2. **先做一个 domain**：conversation 系列（最密集）→ 验证后扩展到 agents（`owned_agent`）。各 domain getter 已存在（`get_owned_conversation`, `get_agent`），只需 dependency wrapper。
  3. **防止过度抽象**：不要统一成"所有资源共用一个 generic dependency" — 每个 domain 的 path param 名称/getter/error factory 不同，泛型化反而更复杂。每种资源只做一个薄 dependency function。
- **验证**：`uv run pytest tests/test_conversation_*.py tests/test_agents.py tests/test_multiuser_isolation.py`（覆盖 ownership 404 回归），`uv run ruff check .`
- **预计工时**：M（getter 复用，router signature 替换量大）

### [BE-D2] error_codes.py 已有 factory，但 raw HTTPException 404/403 仍在 drift
- **优先级建议**：P1
- **类别**：重复（+规则违规）
- **证据**：`app/error_codes.py` 已有 `credential_not_found()`, `tool_not_found()`, `model_not_found()` 等结构化 factory（KOR 消息 + error code），但很多 router 绕过它，直接 raw `HTTPException(status_code=404, detail="...")`（ENG 小写）：
  - `credential not found` raw：`credentials.py:110,247,422,735`, `models.py:282,324`, `mcp.py:357,365`, `health.py:226` — **9 处**（已有 factory `credential_not_found()`）
  - `tool not found`: `tools.py:73`, `mcp server not found`: `mcp.py:99`, `health.py:229`
  - `super_user required`: `models.py:110` (403 raw), `forbidden`: `credentials.py:740` (403 raw)
  - router raw 404/403 共 **24 处**（未经过 `error_codes`）
- **问题**：同一个 "not found" 含义产生**两种 response schema** — 结构化 error（`{code, message}` KOR）vs raw `{detail: "credential not found"}` ENG。如果前端按 error code 分支，raw 路径没有 code 就无法处理。此外 raw 字符串会泄露资源类型（"credential"/"mcp server"），可能成为 enumeration hint。
- **重构方案**：
  1. 不新增 factory，**只替换为已有 error_codes factory**：`raise HTTPException(status_code=404, detail="credential not found")` → `raise credential_not_found()`。只有没有 factory 的（`unknown definition '{key}'`, `system credential not found`）少量补到 error_codes.py。
  2. `models.py:110` 的 `super_user required` 403 尽量升级为 `Depends(require_super_user)`（但如果像 `include_hidden` 一样是条件式 gate，只能参数依赖 → 此时仅统一为 `ForbiddenError` factory）。
  3. **guardrail**：建立 convention，禁止在 router 直接使用 `HTTPException(status_code=404|403` + ruff custom rule 或 grep CI check 阻断回归。
- **验证**：`uv run pytest tests/test_credentials*.py tests/test_tools.py tests/test_mcp*.py tests/test_models.py`（需要更新 response schema 断言），`uv run ruff check .`
- **预计工时**：S~M

### [BE-D3] audit_service.record_event self-owned identity kwargs boilerplate
- **优先级建议**：P2
- **类别**：重复
- **证据**：`actor_user_id=user.id` 出现在 **16 个 router 41 个调用处**（`agents.py:152,205,240,271`, `tools.py`, `mcp.py`, `credentials.py`, `triggers.py`, `marketplace.py`, `shares.py` 等）。大多数是 actor==owner==target_owner 的 self-action，因此每次调用都原样重复下面 6~7 个 kwargs（agents.py:152-166 为代表）：
  ```python
  actor_type="user", actor_user_id=user.id, actor_email_snapshot=user.email,
  owner_user_id=user.id, owner_email_snapshot=user.email,
  target_owner_user_id=user.id, outcome="success", request=request,
  ```
  `record_event` 签名有 **24 个 kwargs**（audit_service.py:86）。
- **问题**：手工填写 6 个 identity field 时漏掉一个（如 `owner_email_snapshot`），audit log 就会静默缺字段。反复硬编码 `actor_type="user"` 也有 typo 风险。
- **重构方案**：
  1. 在 audit_service 中增加 self-action convenience wrapper：
     ```python
     async def record_self_event(
         db, user: CurrentUser, *, action: str, target_type: str,
         target_id, target_name: str | None = None,
         outcome: AuditOutcome | str = "success",
         request: Request | None = None, metadata: dict | None = None,
     ) -> AuditEvent:
         return await record_event(
             db, actor_type="user", actor_user_id=user.id,
             actor_email_snapshot=user.email, owner_user_id=user.id,
             owner_email_snapshot=user.email, target_owner_user_id=user.id,
             action=action, target_type=target_type, target_id=target_id,
             target_name_snapshot=target_name, outcome=outcome,
             request=request, metadata=metadata,
         )
     ```
  2. 少数 actor≠owner 的 case（管理员操作其他用户资源、marketplace 等）继续使用 full `record_event` — wrapper 只用于 self-action。
  3. **防止过度抽象**：wrapper 只吸收"最常见的一种组合"。不要让参数再次膨胀到 24 个。
- **验证**：`uv run pytest tests/test_audit*.py` + 各 domain audit test，`ruff`
- **预计工时**：M（替换 41 个调用处）

### [BE-D4] 每个 router 自己的 _load_owned helper + system-or-owned query 谓词重复
- **优先级建议**：P2
- **类别**：重复
- **证据**：各文件自定义 ownership loader：`tools.py:62 _load_owned`, `mcp.py:92 _load_owned`, `credentials.py:107 _load_owned`, `models.py:277 _load_owned_credential`, `uploads.py:93 _get_owned_attachment`, `shares.py:63 _require_owned_conversation` — **6 个**。另外"system（NULL）或自己所有"谓词 `or_(Tool.user_id == user_id, Tool.user_id.is_(None))` 被**复制 7 处**：`tool_service.py:34`, `agent_service.py:246,428`, `agent_blueprint_service.py:294`, `builder_service.py:295`, `tools.py:68,103`。
- **问题**：这些 `_load_owned` 的**ownership 语义不同** — tools=system-or-owned，mcp=strict owned，credentials=`get_for_user`（委托 is_system=False filter），uploads=strict+404-collapse。名字看起来相同，未来容易误以为"都一样"而错误合并/修改。system-or-owned 谓词 7 处中只要一处条件变化（如新增 enabled filter），就会 policy drift。
- **重构方案**：
  1. 将谓词提取成 model helper（最安全的最小单位）：
     ```python
     # app/models/tool.py 等
     def visible_to(user_id: uuid.UUID):  # system(NULL) + owned
         return or_(Tool.user_id == user_id, Tool.user_id.is_(None))
     ```
     7 个调用处共享 `Tool.visible_to(user_id)` → policy 单一来源。
  2. `_load_owned` 系列由 **BE-D1 的 dependency factory 吸收**，但用 `system_visible: bool` flag 显式区分 ownership 语义：
     ```python
     def owned_tool(..., system_visible=True): ...   # tools
     def owned_mcp_server(..., system_visible=False): ...  # strict
     ```
  3. **防止过度抽象**：不要合并成单一 generic `load_owned(Model, id, user)` — ownership 语义（是否包含 system、是否 404-collapse）按资源不同，会导致 flag 爆炸。仅提取谓词（1）就有很大收益。
- **验证**：`uv run pytest tests/test_tools.py tests/test_mcp*.py tests/test_agent_service*.py`，`ruff`
- **预计工时**：S（谓词提取）+ M（loader 统一，与 BE-D1 并行）

### [BE-D5] keyset cursor 编码/规范化 + pagination 参数重复·不一致
- **优先级建议**：P3
- **类别**：重复
- **证据**：`_encode/_decode_*_cursor` 在各 service 重复实现：`chat_service.py:656/674`（JSON+base64）、`artifact_service.py:88/92`（separator string）、`audit_service.py`（含 cursor 逻辑）。timestamp UTC-naive 规范化 `astimezone(UTC).replace(tzinfo=None)` 在 `chat_service.py:691`（inline）和 `artifact_service.py:82 _normalize_cursor_datetime`（helper）重复。Query 声明 `limit: int = Query(default=…, ge=1, le=…)` 也在 **12+ router** 上上限各异：100（`conversation_crud:82`），200（`credentials:457`, `marketplace:178`, `health:162`），100（`artifacts:171`），100（`audit:49`）。
- **问题**：(1) cursor timestamp normalization 有两处 — 如果只修一处 tz bug，另一处仍会因 aware/naive 不一致造成 keyset page 错位（重复/漏 row）。(2) limit 上限 API 间不同，client 难以预测。cursor format 也有 2 种（JSON vs separator），无法共享 decoder。
- **重构方案**：
  1. 新建 `app/services/pagination.py` — 先只共享 normalization（风险最低）：
     ```python
     def normalize_cursor_dt(value: datetime) -> datetime:
         return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
     ```
     `chat_service`/`artifact_service` 共享。
  2. cursor format 统一（可选）：`(sort_value, id)` tuple → 收敛到 1 个 base64(JSON) encoder/decoder。**但 chat_service 的 scope/is_pinned composite cursor 属于 domain-specific** → 禁止强行统一（有意分离）。
  3. pagination Query 上限用公共常量（`DEFAULT_PAGE_LIMIT`, `MAX_PAGE_LIMIT`）统一，但真实需求不同的地方（marketplace 大列表 200）保留。
- **验证**：`uv run pytest tests/test_conversation_crud*.py tests/test_artifact*.py tests/test_audit*.py`（keyset 边界测试），`ruff`
- **预计工时**：S（共享 normalization）/ M（若统一 cursor format）

### [BE-D6] 工具定义 runner 的 auth+HTTP call 微模式重复
- **优先级建议**：P3
- **类别**：重复
- **证据**：`app/tools/definitions/` runner 重复同样 5 步 — `cred_def = credential_registry.require("<key>")` → `apply_authentication(cred_def.authenticate, {...}, ctx.credentials)` → `response = await ctx.http_client.request(**request_opts)` → `response.raise_for_status()` → `response.json()`：
  - `naver_search.py:56-68`, `google_search.py:34-42`, `gmail_send.py:37-49`, `google_calendar_event.py:47-55`, `http_request.py:61-73`（variant）— **5~6 个文件**
- **问题**：每个 runner 手写 error handling（raise_for_status 后 status/body assembly）— 有的包含 `http_status`，有的不包含，response shape 轻微 drift。新增工具时如果漏掉一行 auth injection，就会发出未认证 request。
- **重构方案**：
  1. 公共 helper（既然 `apply_authentication` 已经提取，就在它上面加薄 wrapper）：
     ```python
     # app/tools/http_runner.py
     async def authed_json_request(ctx, cred_key: str, *, method, url, params=None, json=None):
         cred_def = credential_registry.require(cred_key)
         opts = apply_authentication(cred_def.authenticate, {"method": method, "url": url, "params": params, "json": json}, ctx.credentials)
         resp = await ctx.http_client.request(**{k: v for k, v in opts.items() if v is not None})
         resp.raise_for_status()
         return resp
     ```
  2. **防止过度抽象**：像 naver 的 `_format_items`/HTML strip 这类 tool-specific postprocess 保留在 runner — helper 只负责"auth+request+raise+返回 resp"。response assembly（`{"http_status":…, "items":…}`）由各 runner 自由处理。
  3. `naver_search.py` 已在文件内部用 `_make_runner`/`_common_parameters` 做了良好 factoring — 只新增跨文件 runner helper。
- **验证**：`uv run pytest tests/test_tool_definitions*.py tests/agent_runtime/`（tool execution test），`ruff`
- **预计工时**：S

### [BE-D7] 测试 fixture 重复 — 缺少 Model/Agent seed factory
- **优先级建议**：P2
- **类别**：重复
- **证据**：`tests/conftest.py` 已有 `make_user`（217）、`make_refresh_token`（240）、`client`/`db`/`TEST_USER_ID` 共享 fixture，但**没有 Model/Agent/Conversation seed fixture**：
  - `Model(provider="openai", model_name="gpt-4o", …)` 一行在 **37 个文件 41 次**复制粘贴
  - 本地 `_seed_agent`/`_make_agent` helper 在 **21 个文件约 24 个**定义（`test_memory_router.py:16`, `test_draft_conversation_gc.py:28`, `test_assistant_router.py:21`, `test_agent_api_control_plane.py:12`, `test_conversation_run_service.py:24`）— 名称/prompt 不同，结构相同
  - inline `User(id=TEST_USER_ID, …)` **63 次**，但 `make_user` 只在 5 个文件使用（helper 已有却未采用）
  - `/api/auth/register`+cookie/CSRF 提取本地 `_register`/`_login` helper **7 个文件**（`test_auth_login.py:26`, `test_multiuser_isolation.py:57`, `test_csrf.py:19` 等）
- **问题**：schema/model field 变化时（如 Model 新增 required column），必须批量修改 37+21 个文件 — 实际每次 schema migration 都会让测试崩。`make_user` 已存在却没用，说明 factory adoption 失败。
- **重构方案**：
  1. 在 `conftest.py` 增加现有 `make_user` 风格的 factory-as-fixture：`make_model(db, *, provider="openai", model_name="gpt-4o", …)`, `make_agent(db, *, user_id=TEST_USER_ID, model_id=…, name=…)`，组合 `seed_agent(db) -> (user, model, agent)`。
  2. 用基于 `raw_client` 的 `login_as`/`registered_session` fixture 统一 7 个 auth helper（与 ORM factory **保持分离** — 因为它们验证真实 cookie/CSRF path，目的不同）。
  3. **禁止一次性全替换**：引入新 fixture 后，新测试开始强制使用；现有测试在 schema 变化时渐进迁移。`_make_agent_item*`（marketplace object graph）、credential-specific `_make_agent_with_model` 属于有意分离 → 不要改。
  - 大约 231 个 top-level test 中 **80~90 个**使用 inline ORM seed → 属于 factory adoption 对象。
- **验证**：`uv run --with pytest-xdist pytest -q -n 4`（确认全绿）
- **预计工时**：M~L（量大但机械）

### [BE-D8] Response schema id/timestamp field + ConfigDict 重复
- **优先级建议**：P3
- **类别**：重复
- **证据**：`id: uuid.UUID` / `user_id` / `created_at: datetime` / `updated_at: datetime` field 声明在 **17 个 schema 文件重复 184 次**，`ConfigDict(from_attributes=True)` 另有 9 次。代表：`tool.py:64-77 ToolInstanceResponse`（id/created_at/updated_at）、`agent.py`, `mcp.py`, `credential.py`, `trigger.py`, `model.py` 等所有 `*Response` 都重复声明相同 3~4 个 field。
- **问题**：低 — 实际风险不大，但没有 ORM Response 公共 base，各 class 单独管理 `from_attributes` 设置（漏掉时 `model_validate` 失败）。若修改 timestamp 序列化规范（如统一 tz-aware），需改 17 个文件。
- **重构方案**：
  1. 在 `app/schemas/base.py` 增加薄 mixin：
     ```python
     class ORMModel(BaseModel):
         model_config = ConfigDict(from_attributes=True)
     class TimestampedResponse(ORMModel):
         id: uuid.UUID
         created_at: datetime
         updated_at: datetime
     ```
     `*Response` 继承 `TimestampedResponse` → 吸收 id/timestamp/config。
  2. **防止过度抽象（重要）**：`user_id` 的 nullable 与否按资源不同（`user_id: uuid.UUID | None` vs 必填），不要放进 base。字段组合不同的 schema 不要强制继承 — `ORMModel`（只含 config）程度是安全线。**该项收益最小，只在其他 P1/P2 后有余力时做。**
- **验证**：`uv run pytest tests/`（serialization 回归），`ruff`
- **预计工时**：S

---

**不属于重复（有意分离 — 排除）**：
- **credential interpolation（`resolve_deep`）**：已经通过 `app/credentials/interpolation.py` 单一函数完全中心化 — mcp/client·mcp/auth·credentials/tester·authenticate 全部复用（11 call sites）。无需处理。
- **generic base CRUD service**：`db.add/commit/refresh` 3 类约重复 35 次，但各 service create/update 含 scheduler sync·validation·audit 等大量 domain logic。引入 generic BaseService 违反 Simplicity First → **不建议**。如有需要，只做 `commit_refresh(db, obj)` mini helper。
- **chat_service scope/is_pinned composite cursor**：属于 domain-specific field，不是统一对象（见 BE-D5）。

---

## 7. 前端 — 结构/重复 (FE-S)

**总结判断**：公共 primitive layer（`components/shared/*`：`DialogShell` 38 个使用处、`ResourcePage`/`SettingsShell`/`FormFieldShell`/`base-detail-dialog`，`lib/query-keys/*` factory）已经成熟。真正的问题是**采用不一致（half-done commonization）**和**聊天 runtime 双轨 + 3 个超大文件**。API 3 层（`apiFetch<T>` → `xxxApi` → `use-xxx`）很干净，不属于 findings。

核心数据：前 3 大文件共 5,766 行（use-moldy-langgraph-stream.ts 2941 / assistant-thread.tsx 1458 / use-chat-runtime.ts 1367）。远超项目规则（coding-style.md：文件 ≤800 行）。

### [FE-S1] 聊天 runtime 双轨 — legacy `useChatRuntime` vs v3 `useMoldyLangGraphStream` 完全并行实现并存
- **优先级建议**：P1 / 结构
- **证据**：switch `lib/chat/runtime-mode.ts:3-5`（默认 langgraph_v3）→ `conversations/[conversationId]/page.tsx:108,324` → `components/chat/chat-runtime-section.tsx:116` 分支为 `LegacyRuntimeSection`（:174 useChatRuntime）/ `LangGraphRuntimeSection`（:207 useMoldyLangGraphStream）。legacy 有完整并行实现：SSE 手动 parsing `use-chat-runtime.ts:554-914` vs v3 `useStream`+`useChannel`。HITL/edit/regenerate/attach/stop/usage/artifact 所有概念双份。legacy 直接 consumer 4 处：`test-chat-panel.tsx:39`, `assistant-panel.tsx:109`, `app/agents/new/conversational/page.tsx:115`, chat-runtime-section legacy 分支。
- **问题**：每增加一个聊天功能都要同时维护两条 SSE interpretation path。回归风险 2 倍。
- **重构方案**（收敛路线图）：
  1. **移除主聊天 legacy 分支**：去掉 `chat-runtime-section.tsx` 的 useLangGraphRuntime false fallback（draft/no-conversation），draft 始终通过 `useLanggraphDraftConversation`（page.tsx:179-189）bootstrap 为真实 conversation。移除 `runtime-mode.ts` legacy escape hatch。
  2. **剩余 3 个 consumer blocker**：builder（new/conversational）使用 builder_v3 session protocol，在后端出现 builder session 用 LangGraph thread endpoint 前无法迁移（明确保留 legacy）。test-chat-panel/assistant-panel 是 ephemeral（streamAssistant, onMessagesCommit local history）— 没有 v3 等价物。需要 rehost 到真实 conversation 或隔离成 legacy 专用精简版。
  3. **最终**：将 `use-chat-runtime.ts` 隔离移动到 `lib/chat/legacy/`，把 consumer 明确缩减到 3 处。删除要等后端 protocol 统一后。
  - 测试：保留 `use-chat-runtime-*.test.tsx` 5 类 legacy 专用测试。统一 v3 transport mock `createMockTransport()` helper。
- **验证**：`pnpm vitest run` / `pnpm build` / e2e `chat-*.spec.ts` 全部。
- **预计工时**：L（第 1 阶段 M，consumer retire L，后端统一 XL）

### [FE-S2] 拆分 `use-moldy-langgraph-stream.ts`（2941 行）
- **优先级建议**：P1 / 结构
- **证据**：`1-79` import，`81-1991` 约 1900 行 module-level pure helper，`1993-2941` hook body（约 948 行）。已经委托良好的概念（artifact :2384, usage :2389, compaction :2395, data-ui :2425, memory :2517, subagent-names :2518, deepagents-state :2132, transport :2091, checkpoint-fork :2578, activity :2127）。仍 inline、应拆分的对象：thread-state parser 4 类（:234-309）、terminal-notice append（:512-532）、pending-edit/reload render state machine（:137-174, :644-1064）、sticky message cache（:534-642, 1441-1951）。状态：useState 8 / useRef 9 / useCallback 20 / useMemo 23 / useEffect 12。
- **重构方案**（6 个模块 + 2 个 hook，父级约 200 行 composition shell）：
  ```
  lib/chat/langgraph-runtime/
    thread-state-checkpoints.ts   ← （现有）+ parser 4 类（:234-334）   [pure, seam 低]
    terminal-notice.ts            ← （现有）+ appendTerminalRunNotice（:512-532）
    sticky-messages.ts            ← 新增：module-global Map cache（:534-642,1441-1951）  [必须保持 singleton]
    pending-checkpoint-render.ts  ← 新增：edit/reload pure state machine（:398-1344）  [seam 高]
    use-thread-hydration.ts       ← 新增：postRun polling 3 个 effect（:2173-2256,2433-2492）  [注意 onCancel 的 hydrationCanceledRef 顺序]
    use-hitl-decisions.ts         ← 新增：coordinator refs + resume API（:2773-2930）  [resolvedInterrupts 由父级持有]
    use-draft-submit.ts           ← 新增（:553-585,1346-1370）
  ```
  - 渐进顺序：pure parser/notice → sticky-messages → 先拆 pending-render pure function → hydration hook → HITL hook。
  - **必须守住的 seam**：① 禁止复制 shared ref `latestVisibleMessagesRef`（:2035）、`pendingEditBase*Ref`（:2036-37）。② `handleThreadState`（:2078）是单一 mutation funnel — 保留在父级（防止 tearing）。③ `resolvedInterrupts` cycle state 由父级持有。④ 保持 `onNew/onEdit/onReload` 的 `flushSync`（:2664,2696,2740）同步可观察性。
- **验证**：`pnpm vitest run src/lib/chat/langgraph-runtime` / tsc / e2e chat 回归。
- **预计工时**：L

### [FE-S3] 拆分 `assistant-thread.tsx`（1458 行）
- **优先级建议**：P2 / 结构
- **证据**：message part rendering :179-364，artifact/compaction :366-438，message action :440-554,702-740，branch picker :556-700（自包含），message component map :830-1039，Cmd+F :1046-1056，ThreadComposer :1167-1345，StopButton/AttachmentChip/TokenBar :1347-1458。
- **重构方案**：
  ```
  components/chat/thread/
    message-parts.tsx / message-artifacts-compaction.tsx / message-actions.tsx
    branch-picker.tsx（建议先提取）/ message-components.tsx / thread-composer.tsx
    assistant-thread.tsx（shell）
  ```
  顺序：branch-picker → thread-composer → message-*。HITL plumbing 保持 context injection。
- **预计工时**：M

### [FE-S4] 拆分 `approval-card.tsx`（701 行）+ `use-approval-form` 重复
- **优先级建议**：P2 / 结构+重复
- **证据**：ArgsPreview（:223-272）、ArgsEditor（:281-374）、decision submit（:383-456）、3 类 button（:588-654）、ApprovalBadge（:146-167）、wrapper（:664-699）。重复①：`approval-card` 自己的 `handleDecision`（:420-456）vs `tool-ui/use-approval-form.ts`（prompt-approval-ui.tsx:23 使用）— 共享代码 0。重复②：header shell approval-card.tsx:684-696 ≈ grouped-approval-card.tsx:43-62。
- **重构方案**：1. 纯提取 `approval-args-editor/preview`, `decision-buttons`, `approval-badge`。2. 用 `useApprovalDecision` hook 与 `use-approval-form.ts` 统一。3. 共享 `ApprovalCardShell`。测试注意："restores redacted placeholders" 测试注入的是 un-redacted args → 应修正为真实 redacted path。
- **预计工时**：M

### [FE-S5] 超大 page — `settings/memory/page.tsx`（649）· `agents/new/template/page.tsx`（617）
- **优先级建议**：P2 / 结构
- **证据**：memory：CreateMemoryCard（:297-419）、MemoryRecordItem（:421-576）、PolicyCard（:173-295）、ToggleField/SelectField（:578-649，重新发明 FormFieldShell）。template：orchestrator（:48-259），`filtered`（:77-94）与 `filteredBlueprints`（:96-119）重复，TemplateCard（:375-462）与 BlueprintCard（:464-545）约 80% 相同。
- **重构方案**：memory → 提取到 `_components/` + `useDirtyDraft` 小 hook + 吸收 FormFieldShell。template → `_hooks/use-template-gallery.ts` + 单一 `GalleryItemCard` + `sortByKey` util。
- **预计工时**：M

### [FE-S6] create/edit dialog shell 复制粘贴 8+ 次 + 未使用的 `BaseDetailDialog`
- **优先级建议**：P2 / 重复
- **证据**：`credential-create-modal.tsx`（:54-57,:96-112）、`model-add-dialog.tsx`（:85-128）、`model-edit-dialog.tsx`（11 个 useState :51-63）、`skill-create-tabs.tsx`, `tool-create-dialog.tsx`, `mcp-import-dialog.tsx` 使用相同 shell。**dead abstraction**：`components/shared/base-detail-dialog.tsx`（130 行）consumer 0。agent create（`agents/new/manual/page.tsx:62-103`）绕过 edit 的 `useAgentSettingsDraft`（settings/page.tsx:70）— 重新声明 13 个 field raw useState。
- **重构方案**：1. 小 hook `useResourceFormDialog<T>`（prop re-seed 用 remount `key` 模式）。2. detail dialog 迁移到 `BaseDetailDialog`（否则删除）。3. 将 `useAgentSettingsDraft` 泛化为 create/edit 共用 + 共享 `AgentSettingsHeader`。
- **预计工时**：L

### [FE-S7] `lib/types/index.ts`（775 行）— 混合 barrel（re-export 14 + local 定义 67）
- **优先级建议**：P2 / 结构
- **证据**：:6-19 re-export + :23-775 Agent domain type 67 个 local inline。与 AGENTS.md "避免 barrel export" 冲突。
- **重构方案**：移动到 `types/agent.ts`, `types/chat.ts`, `types/middleware.ts`。index.ts 只保留 re-export（保持兼容）→ 渐进切换为直接 import。
- **预计工时**：M

### [FE-S8] Query key factory drift — 已有 13 个 factory，但 9 个 hook inline 定义
- **优先级建议**：P2 / 结构+重复（quick win S）
- **证据**：`lib/query-keys/*` 已有 13 个 factory。inline 定义的 9 个 hook：`use-memory.ts:15`, `use-conversations.ts:39`, use-agent-api, use-artifact-library, use-audit-events, use-conversation-artifacts, use-conversation-files, use-conversation-title, use-share, use-system-llm-settings。违反 AGENTS.md 规则。
- **重构方案**：将 inline `*Keys` 移到 `lib/query-keys/`（沿用现有 `toolQueryKeys` 层级格式）。测试中的 literal array 断言因返回相同 array 而无需修改。
- **预计工时**：S

### [FE-S9] 目录布局不一致 — `features/` 只有 schedules
- **优先级建议**：P3 / 结构
- **证据**：AGENTS.md 规则（route-only→`_components/`，多 route→`features/<domain>/`）已存在，但 `features/` 里只有 schedules。agent domain 分散在 `components/agent/`（8）+ `app/agents/.../settings/_components/`，形成双轨。`src/hooks` vs `src/lib/hooks` 也双轨。
- **重构方案**：强制遵守规则（lint:frontend-architecture）+ 按 domain 独立 PR 渐进迁移（`components/chat/` → `features/chat/` 等）。
- **预计工时**：L（全量）/ 每个 domain S~M

### [FE-S10] 类型 drift — 后端 Pydantic ↔ `lib/types/*` 手工同步，没有 OpenAPI codegen
- **优先级建议**：P3 / 结构
- **证据**：没有 openapi/codegen 脚本。FastAPI 自动提供 `/openapi.json`。
- **重构方案**：引入 `openapi-typescript` — `pnpm gen:types` → `lib/types/api.gen.ts`，domain type 从 `components['schemas']['AgentRead']` 派生。只生成 type（无需全面 orval）。CI drift check。
- **预计工时**：M

### 附录：不是 findings（优点）
- API client 3 层：一致、简洁。引入 generic `useResourceQuery` 会是过度抽象。
- Jotai stores：8 个 atom 文件整体一致。
- DialogShell adoption：raw DialogContent 只剩 2 个。
- mcp-servers wizard / agent settings：已经拆分良好（参考模型）。

**优先级总结**：P1 = FE-S1, FE-S2。P2 = FE-S3·S4·S5·S6·S7·S8。P3 = FE-S9·S10。quick win = FE-S8。影响最大 = FE-S1 + FE-S2。

---

## 8. 前端 — 性能/设计/可访问性 (FE-P/FE-D)

**先说明 — 已经良好（无需修改，用于避免误报）**
- **design token**：`pnpm lint:design-system` guard 工作得很强。产品代码几乎没有 raw hex/arbitrary typography（`text-[..px]` 0 处，product hex 只有 data-viz palette + vendor logo）。
- **重型 viewer bundle**：mermaid/docx/xlsx/pptx/hwp/pdf/react-syntax-highlighter 全部通过 `lazy()` 拆分（`artifacts/preview-registry.tsx`, `markdown-code-block.tsx:7`）。
- **message conversion/list layer**：converter cache·fingerprint·per-message memo 很精细（`message-list.ts:215-235`）。
- **useAuiState selector 大多遵守规范**。

### [FE-P1] 聊天 context（`AssistantThreadDynamicContext`）值随 streaming token churn → 全消息 rerender
- **优先级建议**：P1 / 性能
- **证据**：`components/chat/assistant-thread.tsx:860-883` — `dynamicContextValue` 虽是 `useMemo`，但依赖包含 `activities`, `deepAgentsState`。每个 token 都产生新 reference：
  - `deepAgentsState`：`use-moldy-langgraph-stream.ts:2132` `useMemo(selectDeepAgentsState(stream.values ?? {}), [stream.values])`。`stream.values` 每个 chunk 都是新 reference + `selectDeepAgentsState`（`deepagents-state.ts:187-192`）始终返回新 `{todos, files}` + 新 array。
  - `activities`：`use-moldy-langgraph-stream.ts:2124-2131` 的 `reduce` 返回新 array。
  - Provider 在 `assistant-thread.tsx:1059` 包裹整个 thread，所有 user/assistant message 都订阅（:888, :931/:958）。
- **问题**：context value identity 每个 token 都变化，导致所有已挂载 message wrapper subtree rerender。对话长度 N 越大，streaming 期间 jank 越严重。
- **重构方案**：1. 把每 token 变化的字段（`deepAgentsState`, `activities`）从 identity context 中拆出 — 移到独立 provider 或 jotai atom，只在实际消费点 read。2. `AssistantThreadDynamicContext` 只保留稳定字段。3. `selectDeepAgentsState` 在内容不变时复用旧 reference（结构等价比较）。
- **验证**：用 React DevTools Profiler 对 streaming 60 秒的 commit 次数做 before/after 对比。
- **预计工时**：M

### [FE-P2] 缺少聊天消息 thread virtualization
- **优先级建议**：P1 / 性能
- **证据**：`assistant-thread.tsx:1095` 的 `<ThreadPrimitive.Messages>` non-virtualized。`useVirtualizer`/`react-window` 0 处。
- **问题**：进入 100+ 轮对话时一次性挂载完整 tree → 初始 render 变慢 + scroll 掉帧。
- **重构方案**：1. 低成本 — message `React.memo` + 解决 FE-P1。2. 引入 `@tanstack/react-virtual`，可变高度使用 `measureElement`，保证 bottom pin 一致性。3. 基于消息 N 条阈值渐进启用。
- **验证**：Profiler 测 200 轮初始 commit + scroll long task，Lighthouse TBT。
- **预计工时**：L（主体）/ S（memo 先行）

### [FE-P3] 管理 table/展开 navigator list 缺少 virtualization
- **优先级建议**：P2 / 性能
- **证据**：`components/ui/data-table.tsx:261` 渲染全部 row。navigator `layout/chat-navigator-agent-group.tsx:78-80` 展开+无限滚动时无上限。
- **重构方案**：DataTable opt-in row virtualizer（超过 50 行时），navigator 展开 list 复用相同方案。
- **预计工时**：M

### [FE-P4] 活跃 run 中每 1 秒 polling 导致完整 conversation list 双重重复请求
- **优先级建议**：P2 / 性能
- **证据**：`lib/hooks/use-conversations.ts:174-176` + `195-197` 两处都有 1000ms `refetchInterval`，`use-conversation-runs.ts:20` 的 run status 也是 1s。streaming 时每秒 2 次完整 list + 1 次 run status。
- **重构方案**：1. 将 run-status polling 统一为单一 channel → 只有变化时 `invalidateQueries`。2. 移除完整 page `refetchInterval` 或改为 3~5s + `structuralSharing`。3. navigator 不可见时停止 polling。
- **验证**：Network tab 60 秒 request 数 before/after。
- **预计工时**：M

### [FE-P5] page-level 'use client' 使用范围过广
- **优先级建议**：P3 / 性能
- **证据**：774 个文件中 361 个 `'use client'`。`settings/*/page.tsx` 全部 + marketplace page root 都是 client。
- **重构方案**：从新 page 开始规范为 server page.tsx + `_components/*-page-client.tsx` 分离；现有大型 settings 先从 header server 提取开始。
- **预计工时**：M（全面）/ S（仅新规则）

### [FE-P6] dead dependency chart.js + 未使用 next/image
- **优先级建议**：P3 / 性能
- **证据**：`package.json` 中 `chart.js ^4.5.1` — src import 0 处。`next/image` 0 处，raw `<img>` 9 处。
- **重构方案**：移除 chart.js；backend-served avatar 使用 `images.remotePatterns` + `next/image`；外部 thumbnail 保持 `<img>`。
- **预计工时**：S

### [FE-P7] useAuiState selector 细微违规 + phase-timeline 每 token 做 O(n) scan
- **优先级建议**：P3 / 性能
- **证据**：`assistant-thread.tsx:605-608` BranchPicker 的 `meta` selector 使用 `?? {}` 新对象。`tool-ui/phase-timeline-ui.tsx:157-160` 每个 token 扫描全部消息 O(n)。
- **重构方案**：使用 `EMPTY_BRANCH_META` module 常量；phase-timeline latest id 从 runtime event 派生。
- **预计工时**：S

### [FE-D1] chat/dashboard/share route 完全缺少 error boundary（2026-07-03 审计确认有效）
- **优先级建议**：P1 / 设计（可靠性）
- **证据**：`ErrorBoundary` 0 处。没有 `app/error.tsx`·`app/global-error.tsx`。route `error.tsx` 只有 settings/tools/marketplace/skills/mcp-servers 5 处 — **agents（核心聊天）、conversations、shared/[shareId]、dashboard root、usage/artifacts 未覆盖**。
- **问题**：streaming chat render exception 时白屏 → 整个 app shell 崩溃。公开 share link 访问者也会遇到。
- **重构方案**：1. 新增 `app/global-error.tsx` + `app/error.tsx`。2. `app/agents/error.tsx`, `app/shared/error.tsx` — reset button + i18n。聊天考虑 stream-level boundary。3. 统一为公共 `RouteError` primitive。
- **验证**：注入 intentional throw 的 E2E，axe。
- **预计工时**：M

### [FE-D2] icon control 缺少 accessibility label（baseline 40 项）
- **优先级建议**：P2 / 可访问性
- **证据**：`scripts/jsx-a11y-baseline.json` 40 项：`control-has-associated-label` 26，`anchor-has-content` 7 等。最多的文件：`chat/trace-debugger-view.tsx`（4），`agent/visual-settings/nodes/agent-node.tsx`（3），`chat/right-rail/chat-right-rail.tsx`（2）。
- **重构方案**：先给 26 项加 `aria-label`（i18n key）→ 移除 baseline → 纳入 review checklist。
- **预计工时**：M

### [FE-D3] loading/error/empty state 覆盖不均
- **优先级建议**：P2 / 设计
- **证据**：只有 5 处 `loading.tsx`。agents（chat）/dashboard/shared/usage/artifacts 两者都没有。Skeleton 55 文件 vs Spinner 38 文件混用。
- **重构方案**：给未覆盖 route 增加 `loading.tsx`（管理=Skeleton，chat=专用 shell）→ 文档化选择规则 → 公共 `EmptyState`。
- **预计工时**：M

### [FE-D4] chart-card theme 不适配的硬编码 palette（+绕过双重 guard）
- **优先级建议**：P3 / 设计
- **证据**：`components/chat/data-ui/chart-card.tsx:22-29` 的 `CHART_PALETTE` 固定 8 个 hex。由于 `fill={seriesColor(index)}` 是 JS string，绕过 `raw-hex-utility` guard 和 inline-SVG guard 两者。另有 3 处无 `dark:` 的 `bg-white` — `ui/slider.tsx:45`, `hwp-preview.tsx:147`, `pptx-preview.tsx:108`。
- **重构方案**：CSS variable data-viz token（`--chart-cat-1..8` light/dark）→ 共享 palette → 缩小 guard 例外。给 slider/文档 pane 增加 `dark:` variant。
- **预计工时**：S

### [FE-D5] i18n 硬编码 — agent-prism trace UI 仅英文（guard skip 区域）
- **优先级建议**：P2 / i18n
- **证据**：`scripts/check-static-i18n.mjs` 显式 skip `src/components/agent-prism/**`（line 33-40）。`TextInput.tsx:133`, `Tabs.tsx:112`, `CollapseAndExpandControls.tsx:23/39`, `SearchInput.tsx:13`, `TraceViewerDesktopLayout.tsx:97/113`, `TraceViewerSearchAndControls.tsx:23`, `DetailsView.tsx:73` 等。
- **重构方案**：1. 在 wrapper 层注入 label/placeholder prop。2. 只有无法注入的 string 才通过最小 fork 改成 next-intl key。3. 缩小 skip 范围。
- **预计工时**：M

### [FE-D6] 绕过 shadcn/ui — chat tool-ui 手写 form control + 缺少 radio primitive
- **优先级建议**：P2 / 设计
- **证据**：raw `<textarea>` 8 处（approval-footer.tsx:57 等），raw text input（approval-card.tsx:335/345/355），raw checkbox（`user-input-ui.tsx:97` — 已有 shadcn Checkbox 却绕过），raw radio（`marketplace/update-strategy-dialog.tsx:131` — **RadioGroup primitive 本身不存在**）。
- **重构方案**：1. 新建 `RadioGroup` shadcn primitive。2. tool-ui form control 替换为 `ui/` primitive（IME composer 例外）。3. review checklist/lint 强制。
- **预计工时**：M

### [FE-D7] media artifact 可访问性 — audio/video 缺少 caption·label
- **优先级建议**：P2（局部）/ 可访问性
- **证据**：`components/chat/artifacts/providers/media-preview.tsx:7` `<audio controls>` / `:9` `<video controls>` — 没有 `<track>` + 没有 `aria-label`。
- **重构方案**：基于文件名设置 `aria-label`，可用时加入 `<track kind="captions">`。
- **预计工时**：S

### 优先级总结
- **P1**：FE-P1（context churn）、FE-P2（thread virtualization）、FE-D1（error boundary）
- **P2**: FE-P3, FE-P4, FE-D2, FE-D3, FE-D5, FE-D6, FE-D7
- **P3**: FE-P5, FE-P6, FE-P7, FE-D4

---

## 9. 测试/基础设施/DevX (IX)

基于直接调查结果（`.github/`, `docker-compose.yml`, 两个 Dockerfile, `backend/pyproject.toml`, `backend/tests/conftest.py`, `frontend/e2e/`, `backend/app/seed/`, `backend/app/main.py`）。

**先说明 — 已经良好（用于避免误报）**：
- `backend/tests/conftest.py`（271 行）：autouse DB setup，`client`/`raw_client`/`db` fixture，`make_user`/`make_refresh_token` factory，CSRF bypass — 共享 fixture 体系本身健康（adoption rate 问题见 BE-D7）。
- pytest marker 体系已存在：`[tool.pytest.ini_options]` 中有 `integration` marker + `addopts = "-m 'not integration'"` — live PG test 分离结构已经具备。
- 两个 Dockerfile 都是 multi-stage：backend 为 skill-node build stage + `uv sync --frozen --no-dev`，frontend 为 standalone Next build + 最小 runner。layer 顺序（dependency → source）也有利于 cache。
- seed 系统（`app/seed/`，共 1,257 行）：文件小，upsert 幂等 — 没有启动性能问题。

---

### [IX-1] CI pipeline 完全缺失 — 所有 gate 依赖本地手动执行
- **当前状态（2026-09-07）**：CI 引入和 Pyright basic 0 均已完成，
  `backend-typecheck` 是 blocking。以下内容为首次调查时的记录。
- **优先级建议**：**P0** — 没有 CI，本文件所有重构 PR 的"全绿"保证都依赖人工。应在重构开始前最高优先。
- **类别**：DevX
- **证据**：没有 `.github/workflows/` 目录（已直接确认）。也没有 `.pre-commit-config.yaml`。而可作为 gate 的工具都已准备：ruff（有配置）、pyright（当时共有 968 个既有错误 — 先以 non-blocking job 开始，新/改文件保持 file-level clean）、pytest 2,500+、vitest 1,183+、eslint custom guard（`lint:design-system`, `lint:a11y`, `lint:i18n`, `lint:frontend-architecture`）。
- **问题**：每个 branch/PR 都要人工跑完整 suite，忘记就会让回归进入 main。CLAUDE.md memory 中也记录过"merge 前确认 vitest 全绿"失败案例。
- **重构方案**：
  1. 新建 `.github/workflows/ci.yml` — backend/frontend 拆成 2 个 job，用 path filter 跳过无关变更：
     ```yaml
     name: CI
     on:
       pull_request:
       push: { branches: [main] }
     jobs:
       backend:
         runs-on: ubuntu-latest
         defaults: { run: { working-directory: backend } }
         steps:
           - uses: actions/checkout@v4
           - uses: astral-sh/setup-uv@v5
             with: { enable-cache: true }
           - run: uv sync --frozen
           - run: uv run ruff check .
           - run: uv run pyright
           - run: uv run --with pytest-xdist pytest -q -n 4
       frontend:
         runs-on: ubuntu-latest
         defaults: { run: { working-directory: frontend } }
         steps:
           - uses: actions/checkout@v4
           - uses: pnpm/action-setup@v4
           - uses: actions/setup-node@v4
             with: { node-version-file: '.node-version', cache: pnpm }
           - run: pnpm install --frozen-lockfile
           - run: pnpm lint
           - run: pnpm vitest run
           - run: pnpm build
     ```
  2. （第 2 阶段）e2e 单独 workflow，nightly 或 label trigger — throwaway PG service container + `E2E_SCRIPTED_MODEL_ENABLED=true E2E_SEED_USER_ENABLED=true`（完全按 CLAUDE.md 的 E2E 隔离流程）。
  3. （第 3 阶段）增加 IX-6 的 PG integration job。
  4. branch protection rule：main 要求两个 job required。
- **验证**：确认引入 workflow 的 PR 自己能全绿通过 + 用 intentional failure commit 验证 gate 确实阻断。
- **预计工时**：M

---

### [IX-2] 缺少 pre-commit hook — commit 阶段没有自动 gate
- **优先级建议**：P2
- **类别**：DevX
- **证据**：没有 `.pre-commit-config.yaml`（已直接确认）。
- **问题**：ruff format/lint 违规、大文件误 commit 等直到 CI（引入后）才发现 — feedback loop 慢。
- **重构方案**：
  1. 增加 `.pre-commit-config.yaml`：`ruff check --fix` + `ruff format`（backend），`eslint --fix`（frontend staged，可与 lint-staged 并用），`check-added-large-files`, `check-merge-conflict`。
  2. 在 README/CLAUDE.md setup 流程增加 `uv run pre-commit install` 指引。
  3. 不要把重型检查（pyright, vitest）放进 pre-commit — 保护 commit speed，由 CI 负责。
- **验证**：确认 intentional lint violation commit 在本地被阻断。
- **预计工时**：S

---

### [IX-3] docker-compose/Dockerfile production hardening（审计指出部分仍有效）
- **优先级建议**：P2
- **类别**：基础设施
- **证据**：`docker-compose.yml` — PG password 明文 `moldy`（:6），所有 service 都没有 `restart` policy，backend/frontend 没有 `healthcheck`（只有 postgres 有，:12-16），frontend `depends_on: [backend]` 没有 condition（:71-72）。两个 Dockerfile 都**未指定 non-root USER**，没有 `HEALTHCHECK` instruction。（参考：env_file 分离·先执行 migration·NEXT_PUBLIC build-time 注入等已经做得很好。）
- **问题**：该 compose 文件结构上也可能被当作 production deploy path 使用，但没有 container restart·startup ordering·health monitoring，故障时需手动恢复。container 以 root 运行，发生 container escape 时损害扩大。
- **重构方案**：
  1. dev/prod 分离：明确当前文件仅供 dev，新增 `docker-compose.prod.yml` overlay — `restart: unless-stopped`，PG password 改为 `.env` variable（`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}`），最小化 port binding（移除 PG 5432 外部暴露）。
  2. backend 增加 healthcheck：`test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]`（复用现有 `/health` route）+ frontend `depends_on: { backend: { condition: service_healthy } }`。
  3. Dockerfile：`RUN useradd -m app && chown -R app /app` + `USER app`（backend 注意 `data/` volume 权限），两个 image 都增加 `HEALTHCHECK`。
- **验证**：执行 `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` 后确认 `docker ps` healthy，kill container 后确认自动 restart。
- **预计工时**：S~M

---

### [IX-4] 76 个 Alembic revision — 评估 squash
- **优先级建议**：P3（conflict·启动成本未到临界，无需急）
- **类别**：DevX
- **证据**：`backend/alembic/versions/` 76 个文件（M1~M63 + 1 个 merge）。每个新环境都顺序应用 76 个。
- **问题**：新环境/E2E throwaway stack setup 每次顺序执行 76 revision（目前数秒，实际问题较小）。并行 feature branch 之间的 head conflict 频率随 revision 数增加。
- **重构方案**（启动时）：
  1. 以 milestone（如 M63）为基准，在已完成 `alembic upgrade head` 的 DB 上先确认 `alembic revision --autogenerate` 是否为空 diff（验证 model↔migration sync）。
  2. 新建 1 个 baseline revision：把当前 head 完整 schema 写成 `op.create_table` 集合，并设 `down_revision=None`。
  3. **保留现有 deploy DB path 是核心**：在 baseline revision 的 `upgrade()` 中加入"若现有 `alembic_version` 为 M63，只更新 stamp"分支，或者把旧 revision chain 移到 `versions/archive/`，并在 release note 明确现有 DB 执行 `alembic stamp <new-baseline>` 的步骤。
  4. 确认 E2E/CI 可从新 baseline 启动后删除旧 chain。
  - **注意**：只要有任一 production DB 停在中间 revision 就会失败，因此 squash 前必须让所有环境统一到 head。
- **验证**：空 DB 仅用 1 个新 baseline 执行 `upgrade head` → 完整 `uv run pytest` 全绿 + 在现有 DB 演练 stamp 流程。
- **预计工时**：M

---

### [IX-5] 缺少结构化 logging·request-id — production observability 空白
- **优先级建议**：P2
- **类别**：基础设施
- **证据**：`backend/app/main.py:43-55` — 只有 `logging.basicConfig`。没有 request-id middleware/correlation（LLM trace 通过 Langfuse/LangSmith 独立存在，但**HTTP request-level** 没有关联）。没有 error tracking（如 Sentry）。
- **问题**：production 中无法从 log 反查"这个 500 error 来自哪个 request/user/conversation"。在 multi-user service 转换完成（ADR-016）后，这是 production 必需能力。
- **重构方案**：
  1. request-id middleware：接收 `X-Request-ID` 或生成 uuid4 → 存入 `contextvars` → 在 response header echo。
  2. 用 logging Filter 给所有 log record 注入 request_id/user_id，format 改为 JSON lines（仅 prod；dev 用 flag 保持现状）。
  3. exception handler 中记录包含 request_id 的结构化 error log + （可选）是否引入 Sentry SDK 单独决策。
  4. **注意**：遵守现有 redaction 规则（CLAUDE.md Backend redaction），不要让 credential/token 进入 log — 尤其禁止 header logging。
- **验证**：测试两个并发 request 的 log 能否用 request_id 区分、error response header 是否返回 id。
- **预计工时**：M

---

### [IX-6] aiosqlite↔PostgreSQL 差距 — 有 integration marker 但 CI 不运行
- **优先级建议**：P2
- **类别**：测试
- **证据**：`backend/pyproject.toml` — `markers = ["integration: tests requiring live Postgres (skipped by default via addopts)"]` + `addopts = "-m 'not integration'"`。也就是说 live PG test 体系已经设计好，但没有 CI，**没有任何地方定期运行**。默认 suite 使用 aiosqlite in-memory，因此会漏掉 FK enforcement·JSONB operation·`FOR UPDATE` lock behavior·partial unique index（SEC-3 方案）等 PG-specific bug class（与 2026-07-03 审计"aiosqlite 未验证 FK"的指出同一背景）。
- **问题**：本文档的性能重构（index、移除 FOR UPDATE、keyset）只有在 PG 上验证才有意义，却没有验证 channel。
- **重构方案**：
  1. 在 IX-1 CI 增加 `backend-integration` job：`services: postgres:16-alpine` + 注入 `DATABASE_URL`/`DATABASE_URL_SYNC` + `uv run pytest -m integration`。
  2. 扩充 integration test：FK cascade（删除对话）、trigger 并发执行（SEC-3）、keyset pagination boundary、credential rotation batch。
  3. 在 CLAUDE.md test section 增加一行本地执行流程（`docker compose up -d postgres && uv run pytest -m integration`）。
- **验证**：integration job 在 PG service 上全绿，并用 1 个 sqlite 通过、PG 失败的案例（如 FK violation）证明差距已覆盖。
- **预计工时**：S~M（CI job）+ test 扩充渐进

---

### [IX-7] e2e spec 69 个 — captures tour 与 regression 混杂
- **优先级建议**：P3
- **类别**：测试
- **证据**：`frontend/e2e/` root 混有 regression spec、`captures/` 目录、`manual-atlassian-oauth.spec.ts`（manual-only）。`playwright.config.ts`（48 行）没有 project 拆分。memory 中也记录过依赖文件名字母顺序的陷阱（chat-states warm-up）。
- **问题**：完整执行时 capture tour（截图目的、`E2E_CAPTURE_TOUR` gate）与 manual spec 混在一起，配置 runner/CI 时每次都要手写 grep filter。
- **重构方案**：
  1. 在 `playwright.config.ts` 拆分 projects：`regression`（默认，testIgnore 排除 captures/·manual-*）、`captures`（testDir: e2e/captures，文档化 env gate）、`manual`（仅手动）。
  2. 增加 `pnpm e2e`, `pnpm e2e:captures` script。
  3. 在 config 明确注释对 alphabetical order 的依赖（warm-up）。
- **验证**：确认 `pnpm exec playwright test --project=regression` 不触碰 captures。
- **预计工时**：S

---


## 10. 不要做 — 评估后否决的条目

分析过程中曾列为候选，但根据 **Simplicity First 原则明确否决**。记录下来以节省未来再次提案时的复核成本。

| 否决项 | 原因 |
|-----------|------|
| 按 domain 拆分 `config.py` Settings（BE-S12） | 虽有 101 个字段，但 section comment 划分良好。拆分只会引发 `settings.X` 访问路径全量修改 diff，实际收益为零 |
| generic BaseService（CRUD 公共 parent class） | 各 service create/update 含 scheduler sync·validation·audit 等 domain logic — 泛型化会过度抽象。需要时最多做 `commit_refresh(db, obj)` mini helper |
| 所有资源共用单一 generic `load_owned(Model, id, user)` | ownership 语义（是否包含 system、是否 404-collapse）按资源不同，会导致 flag 爆炸。正确做法是按资源各自一个薄 dependency function（BE-D1/D4） |
| 前端 generic `useResourceQuery` hook | 当前 API 3 层（`apiFetch` → `xxxApi` → `use-xxx`）是 idiomatic TanStack — 这不是 boilerplate，而是 convention |
| credential interpolation 逻辑公共化 | 已通过 `app/credentials/interpolation.py` 的 `resolve_deep` 单函数**完全中心化**（11 call sites）。无需处理 |
| 将 chat_service 的 scope/is_pinned composite cursor 统一为公共 cursor | domain-specific field — 强行统一反而造成耦合。只共享 normalization function（`normalize_cursor_dt`）（BE-D5） |
| BE-D8 Response schema mixin 全面应用 | `user_id` nullable 与否按资源不同，不能放进 base。`ORMModel`（只含 config）是安全线，收益最小 — 仅在 P1/P2 清完后考虑 |
| 全面 OpenAPI codegen（orval 等） | API layer 已经很干净 — 只生成**类型**的轻量 `openapi-typescript` 更合适（FE-S10） |

---

## 11. 新功能发掘

### 11-A. 已规划·文档化的 roadmap（不是重新发掘 — 只需启动）

| 项目 | 来源 | 备注 |
|------|------|------|
| G1 multimodal input — attachment image 未传给 model | `docs/design-docs/chat-feature-gap-analysis.md` | **chat gap 第 1 优先**。断点已收窄到 `conversation_agent_protocol_commands.py` 一处，且存在 `models.supports_vision` column — 工时 M。唯一风险是 checkpoint base64 膨胀 |
| Marketplace MCP/Agent publish·install UX 扩展 | `TASKS.md` Active Follow-ups | Skill Phase 1 已完成。install_service 已有 MCP/blueprint path（建议与 BE-S3 拆分一起推进） |
| 扩充 artifact/share/Marketplace install/memory approval E2E | `TASKS.md` | 与 IX-7（project 拆分）一起 |
| multi-worktree scheduler hardening | `TASKS.md` | SEC-3（重复执行 guard）是前置条件 |
| OpenWiki Phase 2 — schedule auto-update | memory（openwiki 分析） | 需要解除 trigger path 的 Skill 阻断（`risk.py:317-325`）+ 在 invoke path 注入 artifact recorder |
| Skill builder 多轮对话迁移 + Skill 管理 UI 大改 | memory（skill-ui-overhaul） | 当前 Skill builder 是 single-shot form — 需要在 A（shell 复用）/B（deep-agent 重写）/C（一般 Agent 化）中决策 |
| Middleware UX Phase D — preset/执行顺序 DnD/provider 自动检测 | `TASKS.md` Phase 14 剩余 | registry·UI 基础设施完备，纯 UX 工作 |
| chat 小型 quick win 组：G9 slash command, G11 CSV/column toggle, G12 voice·draft, G15 时间替换, G10-C/D | chat-feature-gap-analysis | 全部已完成 S 级 feasibility 验证 |

### 11-B. 新功能建议（按优先级）

在提案前已通过 grep 确认相关 table/router/screen 是否存在，排除已有功能。（确认示例：trigger type 只有 `interval|cron|one_time` — `models/agent_trigger.py:23-25`，不存在 notification 基础设施，不存在 RAG/vector 基础设施，agent_blueprints·daily_spend_*·skill_evaluation_* 已存在。）

### [F1] Webhook（事件）Trigger
- **价值**：目前 Agent 只能按时间（interval/cron/one_time）唤醒。若能由外部事件（表单提交、通知接收、GitHub event、IoT）触发 Agent，自动化范围会根本扩展 — 这是相对 n8n/Zapier 类产品最大的 gap 之一。
- **优先级建议**：P1（价值高 × 可复用现有资产，成本低）
- **现有资产复用**：`agent_triggers`+`agent_trigger_runs` table，`trigger_executor.py`（invoke mode·HiTL 禁用 policy 原样复用），Agent API 的 key auth pattern（`agent_api_*`），`audit_events`。
- **实现草图**：
  1. migration：给 `agent_triggers.trigger_type` 增加 `"webhook"` + `webhook_secret`（加密存储，复用 Cipher V2）column。
  2. `POST /api/hooks/{trigger_id}` public endpoint — HMAC-SHA256 signature 验证（`X-Moldy-Signature`），rate limit，payload size 上限。
  3. 将 payload 插入 trigger message template，再调用 `trigger_executor.execute_trigger`（必须先完成 SEC-3 重复执行 guard）。
  4. 前端：在 schedule form（`features/schedules/components/schedule-form.tsx`）增加 webhook type — URL/secret 显示 + regenerate button。
  5. run history 继续使用现有 `agent_trigger_runs` screen。
- **预计工时**：M

### [F2] RAG Knowledge Base（文档上传 → 搜索工具）
- **价值**："懂我的文档的 Agent"是 no-code Agent builder 的标准预期（Dify/Flowise 都有），但 Moldy 只有 Skill（指令），没有 document KB。可立即支持基于内部 wiki/manual 的 Q&A Agent。
- **优先级建议**：P1（价值最大 — 工时 L，但属于差异化核心）
- **现有资产复用**：PostgreSQL 16（+pgvector extension）、upload pipeline（`POST /api/uploads`·`message_attachments`）、credential 系统（embedding 用 LLM key — 沿用 ADR-013 优先级）、tool registry（`builtin:*` 模式）、document artifact viewer（复用 preview）、APScheduler（后台 indexing）。
- **实现草图**：
  1. migration：pgvector extension + `knowledge_bases`/`kb_documents`/`kb_chunks(embedding vector)` table（遵守 is_system/user_id convention）。
  2. indexing pipeline：upload → text extract（复用现有 document parser 资产）→ chunking → embedding（在 system LLM settings 增加 embedding role，沿用 ADR-019 模式）— 通过 scheduler background job 异步处理。
  3. `builtin:kb_search` tool：把 KB 连接到 Agent（`agent_knowledge_bases` link table），top-k search result 包含 source chunk。
  4. 前端：`/knowledge` 管理 screen（upload·indexing status），Agent settings 增加 KB connection section。
  5. chat citation card：复用现有 search-tool rich card（source aggregation）模式。
- **预计工时**：L

### [F3] Usage Quota·Budget Limit
- **价值**：multi-user 转换（ADR-016）完成后，这是 operator 必需能力 — 当前没有手段阻止特定 user/Agent 的成本失控（只有 aggregate/display）。
- **优先级建议**：P2
- **现有资产复用**：**`daily_spend_*` aggregate table 已存在**，`token_usages`，super_user 权限，chat error bubble（复用预算超限提示）。
- **实现草图**：
  1. `user_budgets`（user_id, monthly_usd_cap, alert_threshold）table + super_user 管理 API。
  2. run 开始前检查：在 `agent_stream_runner` entry 汇总 daily_spend 并与 cap 对比 → 超限立即以结构化 error（error_codes 模式）返回。
  3. 达到 80%/100% 时 notification（与 F4 联动）+ composer 旁 budget gauge（复用现有 context gauge UI 模式）。
  4. super_user screen：在 `/settings/usage` 增加按 user 管理 cap 的 tab。
- **预计工时**：M

### [F4] Notification Center（扩展 G14）
- **价值**：trigger 失败·等待 HITL approval·长 run 完成，目前只有进入对应 screen 才知道。随着 schedule automation 增多（尤其 F1 引入后），未确认失败会静默累积。
- **优先级建议**：P2
- **现有资产复用**：`message_events` SSE 基础设施，`agent_trigger_runs`（failure status），HITL interrupt event，Google Chat Webhook tool（复用外部 channel），navigator layout（放置 bell icon）。
- **实现草图**：
  1. `notifications` table（user_id, type, payload, read_at）+ service/router。
  2. 3 个发生点 hook：trigger_executor 失败时，HITL interrupt 发生时（仅非 trigger conversation），60s+ run 完成时。
  3. 前端：header bell icon + unread badge + dropdown list（点击跳到对应 conversation/schedule — 复用现有 jump-to-message）。
  4. （可选）按 user 设置外部 channel：转发到 Google Chat webhook/email。
- **预计工时**：M

### [F5] Agent Version History·Rollback
- **价值**：试验 prompt/tool 配置后无法回到"昨天还能正常工作的设置"。Fix Agent·Assistant 会自动修改 Agent，因此变更历史价值尤其高。
- **优先级建议**：P2
- **现有资产复用**：**`agent_blueprints` 已经是 Agent snapshot format**（用于 marketplace 安装 — `models/agent_blueprint.py`），`install_service._apply_agent_payload_to_blueprint` 反向转换逻辑，`audit_events`（记录变更主体）。
- **实现草图**：
  1. agent_service.update 时，把变更前状态按 blueprint format snapshot 到 `agent_versions` table（与上一版无 diff 则 skip）。
  2. `GET /api/agents/{id}/versions` + 版本间 diff API（system_prompt 用 text diff，tool/Skill 用 set diff）。
  3. rollback：复用 blueprint→agent apply 逻辑（BE-S3 拆分后模块化的 `install/agent_blueprint.py`）。
  4. 前端：Agent settings 增加"版本记录"tab — timeline + diff view + rollback button（confirm dialog）。
- **预计工时**：M

### [F6] Agent Evaluation (eval) Harness
- **价值**：目前无法确认 prompt/model 变更到底提升还是降低质量（只能凭感觉）。结合 F5（版本）后可以做"版本 A vs B scorecard"。
- **优先级建议**：P2（F5 之后）
- **现有资产复用**：**`skill_evaluation_*` service 20+ 文件**（Skill eval 基础设施·`SKILL_EVALUATION_ENABLED` flag — eval 概念已存在于代码库），`e2e_scripted_model`，`trigger_executor` invoke mode（batch execution），checkpoint fork（re-run 基础设施），`message_feedback`（隐式 eval data）。
- **实现草图**：
  1. `eval_datasets`/`eval_cases`（问题、expected criteria）CRUD。
  2. batch runner：对 Agent（或版本）批量 invoke case — 复用 trigger_executor 模式，限制 concurrency。
  3. LLM-judge scoring（system LLM settings 增加 judge role）+ 保存 score。
  4. 前端：Agent 设置“评估”标签页 — 数据集管理、执行、版本间分数对比表。
- **预计工时**：L

### [F7] Agent 嵌入小组件
- **价值**：把创建的 Agent 作为聊天小组件嵌入自己的网站 — Agent API(M56) 已经完成，只缺最后一块（小组件 JS）。外部曝光 = 产品推广循环。
- **优先级建议**：P2
- **利用现有资产**：**Agent API 完备**（`agent_deployments`, scoped API keys, threads, runs, `/v1` 流式传输），`share_links`（公开暴露模式），设计 token。
- **实现草图**：
  1. 轻量小组件 bundle（iframe 方式 — 隔离宿主 CSS）：悬浮按钮 + 聊天面板，消费 `/v1` 流式传输。
  2. 扩展 deployment 设置：小组件主题色/问候语/允许域名（Origin 校验）。
  3. 公共 rate limit（deployment 单位）+ 小组件专用匿名 thread 策略。
  4. 在 Agent API 设置页面提供复制 embed `<script>` 代码片段的 UI。
- **预计工时**：M

### [F8] 对话分析仪表盘
- **价值**：让运营人员和重度用户一眼看清“哪些 Agent 使用量大、哪里失败、成本流向何处”。当前 `/usage` 主要是 token 汇总。
- **优先级建议**：P3
- **利用现有资产**：`token_usages`, `daily_spend_*`, `agent_trigger_runs`, `message_feedback`, `audit_events`，现有手写 SVG 图表组件（chart-card — FE-D4 token 化之后）。
- **实现草图**：
  1. 聚合 API：按时间段统计对话数/token/成本、按 Agent 的 top-N、工具使用频率、失败率（存在 error_message 的 run）、反馈分布。
  2. 将 `/usage` 扩展为标签页结构（使用量 | 分析），或新建 `/analytics`。
  3. 必须先做 BE-P6 索引（尤其 token_usages）— 如果聚合查询走全表扫描会适得其反。
- **预计工时**：M

### [F9] 对话文件夹·标签整理
- **价值**：对话积累到数百条后，仅靠 pin/搜索不够。按项目分组是聊天产品的常见演进路径。
- **优先级建议**：P3
- **利用现有资产**：导航器（keyset 分页·pin·rename 完备，M63 索引），`conversations` 表。
- **实现草图**：① `conversation_tags`（或 folders）表 + CRUD ② 导航器过滤 chip ③ 在对话上下文菜单中指定标签。
- **预计工时**：S~M

### [F10] 团队工作区（Agent 协作共享）
- **价值**：当前共享只有 marketplace 发布（异步复制）或对话 share link — 团队没有共同运营、修改**同一个 Agent 实例**的模型。这是通往 B2B 方向的关键入口功能。
- **优先级建议**：P3（价值高，但需要全面扩展权限模型，工作量最大 — 必须先做 ADR）
- **利用现有资产**：marketplace ACL 表（共享权限概念），`is_super_user` 权限模型（ADR-016 中注明了 RBAC 扩展空间），audit_events。
- **实现草图**：① 编写 ADR（workspace vs 按资源共享 — scope 决策是关键）② `workspaces`/`workspace_members`(role) ③ 将资源所有权从 user_id → owner(workspace|user) 扩展为多态（大规模迁移）④ 邀请流程 + 成员管理 UI。**注意：相比 F1~F9 风险高一个量级，因此建议走单独的规格（/spec）轨道。**
- **预计工作量**：XL

### 功能优先级汇总

| 排名 | 功能 | 依据 |
|:---:|------|------|
| 1 | G1 多模态输入（已有计划） | 仅 1 处断点，列已存在 — 以最小工作量获得最大的聊天体验提升 |
| 2 | F1 Webhook 触发器 | 自动化扩展的入口，复用现有触发器基础设施 |
| 3 | F2 RAG 知识库 | 与竞品相比差距最大，是差异化核心 |
| 4 | F3 配额·预算 | 多用户运营必需，通过复用 daily_spend，工作量为 M |
| 5 | F4 通知中心 | 引入 F1 后必要性急剧上升 |
| 6 | F5 版本历史 → F6 评估 | 复用 blueprint/skill_evaluation 资产，有顺序依赖 |
| 7 | F7 嵌入小组件 | Agent API 的最后一块拼图 |
| 8+ | F8 分析、F9 标签、F10 工作区 | 有余力时 / F10 需先做 ADR |

---

## 12. 附录 — 通用验证命令

所有重构 PR 在合并前都必须通过以下检查（引入 IX-1 CI 后自动化）。

```bash
# 后端 (backend/)
uv run ruff check .                          # lint
uv run pyright                               # 类型检查 — basic-mode 全部保持 0，CI blocking
uv run --with pytest-xdist pytest -q -n 4    # 全量测试 (aiosqlite, 无需 DB)
uv run pytest -m integration                 # 需要 live PG 时 (先执行 docker compose up -d postgres)

# 前端 (frontend/)
pnpm lint                                    # eslint + design-system/a11y/i18n/architecture guard
pnpm vitest run                              # 全量单元测试（不是单个文件 — CLAUDE.md 规则）
pnpm build                                   # tsc + Next 构建

# 涉及聊天的变更时追加
pnpm exec playwright test e2e/chat-langgraph-v3-regressions.spec.ts
# 全量 e2e 遵循 throwaway 栈流程（CLAUDE.md “E2E 端口/DB 隔离”）
# push 前 backend pytest 需要 SKILL_EVALUATION_ENABLED=true
```

**性能项测量工具**：SQLAlchemy `echo=True` 或 pytest 查询计数器（N+1 验证），`py-spy`（事件循环/CPU profile），`EXPLAIN ANALYZE`（索引），React DevTools Profiler（rerender commit 次数），Network 标签页（polling 次数），Lighthouse（TBT/bundle）。

**文档维护规则**：条目完成时，在本文档对应行加删除线 + PR 编号；如果行号偏差较大，则按 symbol 名重新搜索并更新。
