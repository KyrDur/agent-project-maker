# Lint·静态分析 Hardening 计划

> 编写于 2026-07-08。重构 master plan(`docs/refactoring-plan-2026-07.md`)的 DevX 后续 track。
> 目的：把"这样开发了，如果 lint 能抓出来就好了"的问题做成自动 gate。对 vibe coding 快速堆积产生的 convention drift，不依赖人的记忆，而是用工具阻止。
> 所有数值均为 2026-07-08 main 基准实测(`ruff check --select <RULE> --output-format concise app/`, grep count)。ruff 版本固定于 uv.lock，因此 deterministic。

## 0. 核心诊断

该 codebase 的 linting 呈现**frontend 成熟、backend 薄弱**的不对称结构，而关键问题是**frontend 成熟的 custom guard 没有接入自动 pipeline**。

| | frontend | backend |
|--|-----------|--------|
| 规模 | ~100k 行 | ~84k 行 |
| 基础 linter | eslint (flat config) | ruff (E/F/W/I/UP/B/SIM/ASYNC) |
| custom guard | **6 个**(design-system, static-i18n, frontend-architecture, jsx-a11y, type-safety, e2e-hygiene) | **0 个** |
| 安全敏感度 | 中 | **高**(JWT 认证·credential 加解密·ownership) |

最大的问题是 **B(custom guard 未接入)** 和 **C(security rule off)**。其余是低成本改进。

---

## A. custom guard 未接入 CI·pre-commit 任何一处 — 🔴 P0

> **A-1 ✅ 完成 (2026-07-10, PR #287)**: 重新测量后登记 3 个合理例外(i18n `global-error.tsx` SKIP / type-safety 仅测试场景允许带理由注释的 `@ts-expect-error` / e2e-hygiene 仅豁免 `e2e/captures/` fixed-timeout) + 为各例外添加 negative 回归测试(`tests/unit/lint/guard-exemptions.test.ts`, i18n 测试中对 sibling file 断言) → 将**4 个 green guard(lint·i18n·type-safety·e2e-hygiene)**接入 CI 独立 step + lint-staged(`frontend/**/*.{ts,tsx}`)。
> **⚠️ 重新分类 (PR #287 第 2 次 review)**: `lint:frontend-architecture` 在下方实测表中的 ✅ 是**假 green** — 非 strict 模式即使有 48 项违规也**始终 exit 0**(无 gate 价值)，而强制的 `--strict` 因**3 个 blocking 项为 red**。因此移至 A-2: 解决 strict blocking(或登记 strictBaseline 评估)后，将 `lint:frontend-architecture:strict` 接入 CI。复现: `node scripts/check-frontend-architecture.mjs --strict; echo $?`。
> **A-2 剩余**: a11y(新增 4 + 解决 baseline 2)·design-system(12 + card warning 19)需要实际修改 component(FE-D2·FE-D4 联动)，frontend-architecture 修复 strict blocking 3 项后接入。全部 green 后将 CI 改为调用 `lint:all`(但 lint:all 的 frontend-architecture 也需替换为 strict)。
> **lint-staged 注意**: guard 会忽略 staged 文件参数并扫描整个 tree — 若有 untracked 违规文件，可能连无关 commit 也会被阻止(CI 是 backstop，因此不做 fail-open)。由于与现有 `frontend/src/**` entry(prettier/eslint --fix)并行执行，罕见 read-write race 可能导致 flaky 失败 — 若重复发生，将 `.husky/pre-commit` 改为 `npx lint-staged --concurrent false`。

- **证据**:
  - `frontend/scripts/` 中存在 6 个 custom guard(`check-static-i18n.mjs` 就是检查韩文/英文消息一致性的那个 script)。
  - `.github/workflows/ci.yml` frontend job: `pnpm lint`(=`eslint`) + `vitest run` + `build`。调用 custom guard **0 次**。
  - `package.json` lint-staged: `prettier --write` + `eslint --fix`。调用 custom guard **0 次**。
  - 即 `pnpm lint:i18n`, `pnpm lint:design-system` 等**必须由开发者手动记得**运行才会执行。AGENTS.md 虽有"新增页面工作后运行"的说明，但不是强制。
- **问题**: "i18n 韩文/英文不一致时 lint 报错"的期待已经通过 script 实现，却不会自动触发。实际上本次 session 的 FE-D1 工作只运行了 `pnpm lint`(eslint)，即使破坏了 i18n 一致性 CI 也抓不到。
- **措施**:
  1. 在 `frontend/package.json` 添加汇总 script:
     ```json
     "lint:all": "pnpm lint && pnpm lint:i18n && pnpm lint:design-system && pnpm lint:frontend-architecture && pnpm lint:a11y && pnpm lint:type-safety && pnpm lint:e2e-hygiene"
     ```
  2. 将 CI frontend job 的 `pnpm lint` 替换为 `pnpm lint:all`(或将各 guard 作为独立 step — 失败点更明确)。
  3. 在 lint-staged 添加针对变更文件的 guard(若全量扫描较重，可只将 `check-static-i18n.mjs` 这类快速 guard 放 staged，其余交给 CI)。
  4. **注意**: 先确认 6 个 guard 当前是否 green(`pnpm lint:*` 分别执行)。有 baseline warning 的 guard(jsx-a11y 使用 `jsx-a11y-baseline.json`)已设计为仅 baseline 超出时失败 — 可直接接入 CI。
- **验证**: 故意只在一侧添加 i18n key 的 commit 是否会在 CI 中变 red。
- **工时**: ~~S~~ → **M** (根据下方实测上调)

### A 实测 (2026-07-08) — 接入前需要先 triage

分别执行各 guard 后，**6 个中已有 4 个处于违规状态**(未强制导致违规累积 — 这是 A 必要性的实证)。注意: `pnpm run <g> | tail` 的 exit code 是 tail 的，因此总会看成 0(与 pyright backlog 时相同陷阱) — 必须用 `pnpm run <g> >/dev/null 2>&1; echo $?` 确认。

| guard | 状态 | 违规 | triage 判断 |
|------|------|:---:|---------------|
| `lint` (eslint) | ✅ | — | — |
| `lint:frontend-architecture` | ⚠️ 假 green | strict 3 | 非 strict 始终 exit 0(不是 gate)，强制模式只有 `--strict` → 解决 strict blocking 3 项后接入 strict (见上方重新分类 note) |
| `lint:i18n` | ❌ | 3 | 全部为 `global-error.tsx`(FE-D1 新增) — 因位于 i18n provider 外，静态英文不可避免 → **在 guard SKIP_FILE_PATTERNS 登记例外** |
| `lint:type-safety` | ❌ | 2 | `chat-route-replacement.test.ts` 的 `@ts-expect-error`(模拟 SSR window 移除) — 合理 → **允许测试例外或理由注释** |
| `lint:e2e-hygiene` | ❌ | 12 | 全部为 `e2e/captures/` 的 `waitForTimeout`(截图 tour 中固定等待较实用) → **对 captures 目录设例外或改为条件等待** |
| `lint:a11y` | ❌ | 新增 3 + 解决 baseline 2 | approval-card/artifact-panel control label — **实际修改**(与 FE-D2 联动) + 更新 baseline |
| `lint:design-system` | ❌ | palette/svg/arbitrary 多项 + card warning 18 | data-ui(chart/stats/terminal-card) 的 `text-emerald-*`·inline-svg(FE-D4)，message-attachments/approval-card arbitrary-layout — **实际 token 化修改或登记有文档说明的例外** |

**启动方式**: (1) 将 3 个合理例外(i18n/type-safety/e2e-hygiene)登记到各 guard 中使其 green → 先将这 3 个接入 CI。(2) a11y·design-system 需要实际 component 修改(与 FE-D2·FE-D4 联动)，因此另行 commit/PR 使其 green 后再接入。**不要一次把 6 个都接入 CI** — 将 red guard 放进 CI 会阻塞之后所有 PR。`frontend/package.json` 中已预先添加 `lint:all` 汇总 script(所有 guard 都 green 后 CI 调用它)。

---

## B. Backend 缺少 custom guard — 🟠 P1

将 frontend 的 `check-*.mjs` pattern 也引入 backend。基于 grep 的轻量 script(`backend/scripts/check_*.py`) + CI step。

### B-1. 禁止 raw HTTPException (强制使用 error_codes factory)
- **证据**: `app/routers/` 中有 `raise HTTPException` **38 处**。BE-D2(#281) 中手动把 404/403 的 21 处改成 error_codes factory，如果已有规则，本可在 review 中自动发现。
- **规则**: router 中禁止直接使用 `raise HTTPException(` → 使用 `app/error_codes.py` factory。例外(按文件 allowlist)需明确。
- **效果**: response schema(`{error:{code,message}}`)一致性，遵守 enumeration-oracle contract。

### B-2. 检测函数局部 `app.*` import (循环耦合异味)
- **证据**: 函数体内部 `from app.` / `import app.` **155 处**。大多是为了规避 services↔agent_runtime 双向耦合(BE-S4)而做的 delayed import — 属于"隐藏 runtime dependency"，削弱 static analysis·IDE navigation。
- **规则**: 以 baseline count 阻止新增函数局部 import(减少可以，增加则失败)。根本解决方案是 BE-S4。

### B-3. 禁止 `print()` (ruff `T20` 足够)
- **证据**: `app/` 中 `print(` **8 处**。production 使用 `logging`。
- **规则**: 在 ruff `select` 中添加 `T20`(无需 custom)。

### B-4. router 直接 `db.commit()` — 仅观测(警告)
- **证据**: `app/routers/` 中 `await db.commit()` **152 处**。transaction boundary 分散在 router 中。全面禁止过度(现架构惯例是 router commit) → 只追踪 count。
- **工时**: B-1/B-2 = M(script+baseline), B-3 = S, B-4 = S(观测)。

---

## C. ruff security rule(S) off — 可自动发现 SSRF — 🟠 P1

> **C ✅ 完成 (2026-07-11, PR #288)**: 添加 `S` select + 全量 triage 51 项(app 43 + scripts/alembic 8)。实际修复 2 项 — openwiki `sync_repo.py`(验证 LLM 提供的 `--repo-url`/`--ref`: 仅 http(s)·拒绝 option injection·`git clone --` separator，测试 24 case) / `generate_image.py`(`IMAGE_API_BASE_URL` scheme guard 后抑制 S310)。false positive 使用 inline noqa+理由，`tests/*`(S101·S105-108·S603)·`alembic/versions/*`(S608·S112) per-file-ignores。gate 回归测试 `tests/test_lint_security_rules.py`(注入违规变 red + 例外 non-blanket negative，使用 `--stdin-filename` 避免 fixture 自我检测)。2-agent review 2 轮通过(Critical/High/Medium 0)。

- **证据**: `--select S` 共 **43 项**。明细:

  | rule | 数量 | 含义 |
  |----|:---:|------|
  | **S310** | 2 | **URL open (SSRF)** — ruff 自动发现了 SEC-1 中手动找到的 web_scraper 漏洞 |
  | S603/S607 | 14 | subprocess 执行(skill_executor — 安全敏感路径) |
  | S105/S106 | 13 | 硬编码 password/secret(不少是常量名 false positive — review 后 ignore) |
  | S101 | 10 | production `assert`(优化 build 中会被移除 → 绕过验证) |
  | S110 | 2 | try-except-pass(静默吞掉异常) |
  | S311 | 1 | 弱 random |
  | S104 | 1 | 绑定 0.0.0.0 |

- **问题**: 在处理 JWT 认证·credential 加解密的项目中 security linter 处于关闭状态。SEC-1 SSRF 本可通过 S310 提前发现。
- **措施**:
  1. 在 `[tool.ruff.lint] select` 添加 `"S"`。
  2. 43 项中真正危险的(S310, S603/607 的未验证输入, S101 production assert)修复，false positive(测试中的 assert=S101, 常量名 false positive=S105)用 `per-file-ignores` 或 inline `# noqa: S105 — 常量名，不是 secret` 带理由整理。
  3. test 目录用 `"tests/*" = ["S101"]` 允许 assert。
- **工时**: M (43 项 triage)

---

## D. 类型安全 gate — ✅ basic 完成 / standard 评估剩余

- **完成证据(2026-09-07)**: pyright `basic` 全量 0 errors。CI `backend-typecheck` 的
  `|| true` 已移除并升级为 blocking gate。
- **措施**(顺序):
  1. ✅ `docs/pyright-burndown-plan.md` 的 B/C/D 阶段完成 → 最新基准 1,258→0。
  2. ✅ 移除 CI `|| true`(hard gate)。
  3. 将 `typeCheckingMode = "standard"` 升级另作单独工作评估。
  4. `ANN` 可从新增代码开始渐进引入(`per-file-ignores` 给现有文件做 baseline，仅对新增文件强制)，或先只启用函数 signature 相关(`ANN001`/`ANN201`)。
- **剩余工时**: 确定 standard/ANN 范围后重新估算

---

## E. 批量添加低噪声 ruff rule — 🟡 P2

> **E ✅ 完成 (2026-07-11, PR #291)**: 7 个 rule 全部启用。下方实测 66 项仅限 `app/`，全量为 **373 项**(tests/ 308 — SLF001 178·PT 77·DTZ 19 占多数)。triage: 实际修复 ~48 + 全局 ignore `N818`(domain-style exception name) + per-file `app/**`=PT(FastAPI `test_*` endpoint false positive), `tests/*`+=`SLF001,DTZ,PT017,PT018,N801,N815` + inline noqa 14(含理由)。gate 回归测试 `tests/test_lint_low_noise_rules.py`(§C pattern — 注入违规变 red + 例外 rule-scoped negative)。DTZ 的"例外使用 ignore"通过 tests/ per-file + `usage_aggregate.date.today()` noqa 反映。

现在启用负担较小的项目(合计 ~66 项)。打包到一个 PR 中 triage。

| rule | 数量 | 效果 |
|----|:---:|------|
| `DTZ` | 1 | 明确 naive datetime 规范(与项目 UTC-naive policy 一致 — 例外使用 ignore) |
| `C4` | 3 | 不必要的 comprehension |
| `SLF` | 5 | 外部访问 private member(`obj._x`) |
| `RET` | 9 | return anti-pattern(不必要的 else 等) |
| `PTH` | 10 | `os.path` → `pathlib` |
| `PT` | 19 | pytest style(fixture/parametrize 一致性) |
| `N` | 19 | PEP8 naming |

渐进引入(数量较多): `TRY`(372), `EM`(388), `PLR`(274), `RUF`(155) — 有用但另开 track。

- **工时**: S~M

---

## F. 抑制(suppression)债务可视化 — 🟡 P2

> **F ✅ 完成 (2026-07-11, PR #290)**: 添加 `PGH` select。实测违规 0(现有 109/76 项是总数量 — 已不存在 bare suppression)，因此是纯预防 gate。确认 PGH004 注入变 red + gate 回归测试(`tests/test_lint_security_rules.py` — 固定 tests/ 的 S 例外不会覆盖 PGH)。未采纳 type-ignore 理由注释(措施 2)·数量上限(措施 3)(与 pyright burndown track 重复)。

- **证据**: `# noqa` **109 项**, `# type: ignore` **76 项**。suppression 本身正常，但会在无理由情况下不断增加。
- **措施**:
  1. 添加 ruff `PGH` rule(`PGH004` 禁止 bare-noqa 等) → 强制所有 noqa 带 code+理由。
  2. pyright: 对 `# type: ignore` 采用理由注释 convention(工具强制较难 — review checklist)。
  3. (可选) noqa/type:ignore 数量上限 script(超过 baseline 失败)。
- **工时**: S

---

## G. integration test marker 未强制 — 🟡 P2 (本次 CI 失败的根因)

> **G ✅ 完成 (2026-07-11, PR #290, review 中修正 exit code)**: `tests/integration/conftest.py` 自动 marker hook(基于路径, `item.path.is_relative_to`)。赋予 marker 后 plain `pytest tests/integration` 全部 deselect → **exit 5**(NO_TESTS_COLLECTED，dir-scoped CI step 会明确 red) — 最初"exit 0"实测是 `cmd | tail; echo $?` pipeline 吞掉 exit code 的错觉(与 §A 的 pyright 误判相同陷阱)。**静默** false green 是 full-suite `pytest tests/` 中 sibling test 通过将 deselection 的 exit 0 掩盖的变体。CI 串行 step 修改为显式选择 `-m integration`(后置 `-m` override addopts — argparse last-wins)，m9 因 `INTEGRATION_DATABASE_URL` self-skip，即使被选中也安全(29 passed + 1 skipped)。回归测试 `tests/test_integration_marker_hook.py`(固定 marker coverage + exit 5 deselection contract)。**已知盲点(pre-existing, 后续)**: `tests/test_trace_storage.py::test_message_event_cascade_delete_with_conversation` 虽有 integration marker 但位于目录外 — parallel step(marker deselect)·serial step(path restricted)都不会运行，而且在 aiosqlite 下 fail·没有 live PG 注入基础设施 → 需要按 m9 pattern 迁移到 tests/integration/。

- **证据**: PR #280·#282 CI 因 `test_conversation_run_lifecycle`·`test_stream_resume` 的 xdist starvation 失败。原因是这些文件**没有** `@pytest.mark.integration`(`test_m9_pg_roundtrip` 是唯一带 marker 的)，因此混入 parallel suite。通过拆分 CI step(`--ignore=tests/integration` + 串行)已先救火。
- **措施**: 在 `tests/integration/conftest.py` 中用自动 marker hook 从源头阻断 (实际实现不使用 deprecated `item.fspath`，而使用 `item.path.is_relative_to(目录)` — 无 substring false positive):
  ```python
  _INTEGRATION_DIR = Path(__file__).resolve().parent

  def pytest_collection_modifyitems(items):
      for item in items:
          if item.path.is_relative_to(_INTEGRATION_DIR):
              item.add_marker(pytest.mark.integration)
  ```
  但当前 CI 使用 `--ignore=tests/integration` 整体排除 integration 并在 serial step 单独运行，因此自动赋 marker 时需要确认与 serial step 的 `addopts '-m not integration'` 交互(将 serial step 调整为 `-m ''` 或 `-m 'integration or not integration'` 运行)。
- **工时**: S

---

## H. 其他观察 (参考)

- **DTO/schema 验证**: Pydantic 做 runtime 验证，但没有 static tool 可发现 response schema 与 ORM 字段 drift(与 frontend FE-S10 的 openapi-typescript 是对称问题)。
- **frontend `no-console`/`no-explicit-any`**: eslint flat config 中没有 `no-console` rule(匹配 0 项)。`check-type-safety.mjs` 正在 custom 检查 any，但它也属于 A 的未接入对象。
- **commit message 规范**: CLAUDE.md 中有 `<type>(<scope>): <subject>` 规范，但没有 commitlint 等强制(可选)。

---

## 推荐执行顺序

1. **A** — 接入 custom guard 到 CI·pre-commit (资产已存在，成本 0，立即见效)。用户想要的"i18n 自动检查"会直接开启。
2. **C** — 开启 ruff `S`(security) + triage 43 项。security 项目必需。
3. **E** — 批量启用低噪声 rule(`DTZ,C4,SLF,RET,PTH,PT,N`) + `T20`(B-3)。
4. **B-1** — Backend `check_router_errors.py`(禁止 raw HTTPException)。
5. **G** — 自动赋予 integration marker。
6. **F** — 可视化 suppression 债务(`PGH`)。
7. ✅ **D** — 2026-09-07 已完成 Pyright basic 1,258→0 并切换 CI hard gate。

每项为独立 PR。rule 添加 PR 要把"开启 rule + triage 违规"放在同一个 commit 中，确保 CI 为 green(不留下 red rule)。

## 验证命令 (依据复现)

```bash
cd backend
for R in S ANN DTZ PT TID RET TRY EM PTH RUF C4 N SLF PLR; do \
  echo "$R: $(uv run ruff check --select $R --output-format concise app/ | grep -cE ':[0-9]+:[0-9]+:')"; done
grep -rn "raise HTTPException" app/routers/ | wc -l          # B-1
grep -rnE "^    (from|import) app\." app/ | wc -l            # B-2
grep -rn "# noqa\|# type: ignore" app/ | wc -l              # F
```
