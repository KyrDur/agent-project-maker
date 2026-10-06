# Skill 隔离执行 sandbox migration 开发计划（方案 B → 方案 A）

> **文档目的**：将 Moldy 的 skill 执行器从“host 本地 subprocess + command allowlist”迁移到“隔离 container 执行”，使 Anthropic 官方 office skill（docx/xlsx/pptx/pdf）可以**几乎原样**执行。本文档包含当前 architecture 精密分析、目标设计、文件级 task、测试/安全/rollout，可仅凭此文档从头到尾完成实现。
>
> **读者**：Moldy backend/infra 开发者。
> **编写日期基准 branch**：`feature/skill-studio-phase3` / `main` (deepagents 0.6.9)。
> **策略**：先完成**方案 B（container-backed `execute_in_skill`，保持 contract）**，再以其产出为基础收敛到**方案 A（deepagents native `SandboxBackendProtocol`）**。

---

## 0. 术语

| 术语 | 定义 |
|---|---|
| **seam** | 替换执行方式的单一代码位置。此处为 `skill_executor.py:154-160` 的 `asyncio.create_subprocess_exec`。 |
| **runner** | 实际执行 skill 命令的 backend。`host`（当前，本地 subprocess）/ `container`（新增，隔离）。 |
| **sidecar(skill-sandbox)** | 包含 toolchain 的独立 container service。与 backend 共享 `backend_data` volume，并通过 exec API 代为执行命令。 |
| **5 个 contract** | redaction·credential·audit·HiTL·artifact — 无论执行位置如何变化都必须保持的安全/观测 invariant。 |
| **SandboxBackendProtocol** | deepagents 定义的隔离执行 backend interface（提供 `execute()`）。方案 A 的目标。 |

---

## 1. 背景 & 目标

### 1.1 问题

Anthropic office skill 的设计前提是**丰富 toolchain + 任意代码执行**：
- READ: `pandoc`, `python -m markitdown`, `pdftotext`, `pdfplumber` …
- CREATE：Agent 编写并执行**新的代码文件**（docx-js, pptxgenjs, reportlab）。
- 转换/渲染：LibreOffice（`soffice`），poppler（`pdftoppm`）。

相比之下，Moldy 当前执行器是**直接运行在 backend host 上的本地 subprocess**，唯一防线是 `python scripts/<f>.py` / `node scripts/<f>.cjs` / `curl` **3 种 command allowlist**。也就是说：
- 未安装 toolchain（`pandoc`/`soffice`/`markitdown` + pip/npm library 全无）。
- allowlist 会拦截上述全部命令。

### 1.2 安全核心（为什么不能“直接放开 allowlist”）

当前 skill subprocess 在**持有 `ENCRYPTION_KEYS`·`JWT_SECRET`·`DATABASE_URL`·所有 API secret 的 backend host**上执行（`skill_executor.py:154` `create_subprocess_exec`，无 container 隔离）。若放开 allowlist 允许任意命令 = **multi-user（ADR-016）环境中的用户 Agent 获得 host RCE** → secret·DB 被窃取。allowlist 是有意设置的 sandbox。

**因此，应将隔离从“command allowlist”迁移到“container 边界”。** container 内允许任意命令/toolchain，但与 host secret 物理隔离。

### 1.3 目标

| # | 目标 |
|---|---|
| G1 | office skill（docx/xlsx/pptx/pdf）无需修改 SKILL.md 即可执行。 |
| G2 | 将执行从 host 迁移到隔离 container，host secret 暴露为 0。 |
| G3 | 保持现有 5 个 contract（redaction/credential/audit/HiTL/artifact）。 |
| G4 | 现有 skill（image-generation, deep-research, openwiki, k-skill 等）无回归。 |
| G5 | 方案 B 的产出设计为方案 A（deepagents native）的下层实现。 |

### 1.4 非目标（本次范围外）

- 将 office skill payload commit 到 Moldy repo（vendoring）— **license 禁止**（§4.5）。仅管理 toolchain image，skill 在 runtime 安装/mount。
- 完全切换到 hosted sandbox（Modal/Daytona）— 仅作为方案 A 的扩展选项说明。
- per-run 一次性 container spawn（强 cross-run 隔离）— 作为方案 B hardening 后续（§11）。

---

## 2. 当前 architecture 精密分析（as-is）

> 依据：source 精密调查。所有路径以 `backend/` 为基准。

### 2.1 完整执行路径（`execute_in_skill`）

该 tool 是 `app/agent_runtime/skill_executor.py:37` `_create_skill_execute_tool(ctx: SkillToolContext) -> BaseTool` 的 closure。内部 coroutine `execute_in_skill(skill_directory, command)`（`:53`）流程：

1. **slug 解析 + attachment gate**（`:64-78`）：若不存在 `ctx.descriptors[slug]` 则拒绝。`resolved = descriptor.runtime_storage_path.resolve()` 同时作为 `cwd` 与验证 root。
2. **构建 base env**（`:80-94`）：**不是完整复制 `os.environ`** — 仅从 host 继承 `PATH`，`PYTHONPATH=HOME=resolved`（skill dir），`SKILL_OUTPUT_DIR/OUTPUTS_DIR=output_dir`，`NODE_PATH`（如有），`SSL_CERT_FILE/REQUESTS_CA_BUNDLE`（如有）。
3. **注入 credential env**（`:100-112`）：通过 `descriptor.credential_bindings[key].env_map`（`{field: env_var}`）设置 `env[env_name]=rc.decrypted[field]`，同时设置 `injected_env[env_name]=value`（→ 后续 redaction key）。
4. **allowlist 验证**（`:114`）：`_prepare_skill_subprocess_args(command, resolved, env)` → `(args, error)`。失败时记录 sandbox denial audit + 返回错误。
5. **timeout policy + network gate**（`:126-151`）：`curl` 仅在 `execution_profile.requires_network=True` 时允许。记录 credential invoke audit。
6. **🔴 SEAM — spawn subprocess**（`:153-160`）：
   ```python
   await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
   proc = await asyncio.create_subprocess_exec(
       *args, cwd=str(resolved),
       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
   )
   ```
7. **capture + timeout + cancel**（`:161-175`）：`wait_for(proc.communicate(), timeout)`；遇到 `TimeoutError`/`CancelledError` 时 `proc.kill()`+`wait()`（防 orphan，继续传播 cancel）。
8. **组装返回值**（`:177-217`）：exit≠0 时附加 STDERR。exit 0 + `audit_kind=="execute_in_skill"` + user_id 时写入 usage ledger（`record_chat_execution_nonfatal`）。绝对路径→替换为 `/api/conversations/<thread>/files/...` URL。`OUTPUT_FILES:` 列表。
9. **stdout redaction**(`:224-227`): `redact_credential_values(result, injected_env)`.
10. tool 通过 `StructuredTool` + `attach_tool_risk(execute_in_skill_risk())`（HiTL metadata）包装（`:231-240`）。

**核心**：到 seam 时，`args`/`cwd=resolved`/`env`/`timeout_seconds` 已全部准备完成。后处理（URL 替换、OUTPUT_FILES、usage、redaction、audit）**全部留在 parent（backend）process**，并通过 filesystem 读取 `output_dir`。

### 2.2 deepagents 集成（关键事实）

- `create_deep_agent` 单一调用：`runtime_component_builder.py:116-147` `build_agent(...)`。
- Moldy 传入的 backend = **`FilesystemBackend(root_dir=str(_DATA_DIR), virtual_mode=True)`**（`:429`, `:288`）。`_DATA_DIR = backend/data`。
- `FilesystemBackend` 是 `BackendProtocol`，且**没有 `execute` method** → **deepagents 内置 `execute` tool 被禁用**。Moldy 使用自定义 `execute_in_skill` tool 直接运行 host subprocess（2.1）。**不经过 deepagents backend。**
- `virtual_mode=True` 只提供路径封锁，**不提供 process 隔离**（deepagents 文档明确说明）。
- skills 通过 `create_deep_agent(skills=[prefix])` → `SkillsMiddleware(backend=FilesystemBackend, sources=[prefix])`。prefix = `/runtime/<thread_id>/[agents/<name>/]skills/` → disk `data/runtime/<thread>/.../skills/`。

### 2.3 allowlist policy（`skill_execution_policy.py`）

`_prepare_skill_subprocess_args(command, *, resolved, env)`(`:46`):
- `shlex.split` + 前置 `NAME=value` local variable + `${VAR}` 展开（不启动 shell，直接执行 argv）。
- **允许 3 种**：`python scripts/<f>.py`（→ `args[0]=sys.executable`），`node scripts/<f>.{js,cjs,mjs}`（→ `_resolve_node_binary()`），`curl <one-url>`。script 必须位于 `resolved` 内。
- **拒绝 code**：`unsupported_executable`（python/node/curl 以外），`inline_python`（`python -m`/`-c`），`path_traversal`，`curl_url_policy`，+ 执行器发出的 `timeout_policy`/`undeclared_network`。
- curl SSRF guard：阻止 private/loopback/link-local/metadata，并通过 `--resolve` 固定已验证 IP。

### 2.4 context/descriptor/profile

- `SkillToolContext`(`skill_runtime.py:112`): `thread_id, output_dir, runtime_root, descriptors{slug→desc}, user_id, agent_id, run_id, audit_kind`.
- `SkillRuntimeDescriptor`(`:88`): `id, slug, name, description, original_storage_path, runtime_storage_path, execution_profile, credential_bindings`.
- `output_dir` = `data/conversations/<thread_id>` = **`/app/data/conversations/<thread>`**（container）。
- `runtime_root` = `data/runtime/<thread>/[agents/<name>/]skills` = **`/app/data/runtime/<thread>/.../skills`**；skill 由 `_materialize_skill` 通过 `copytree` 做 per-thread 复制（slug key）。
- **execution_profile 在 runtime 中只消费 `timeout_seconds`（clamp 0<t≤420，默认 30）和 `requires_network`（curl gate）**。`support_level/runners/requires_*` 仅用于 Marketplace badge，执行器不读取。

### 2.5 5 个 contract（执行位置变化时受威胁的 invariant）

| contract | 当前实现 | 位置 |
|---|---|---|
| **A. Redaction** | `redact_credential_values(result, injected_env)` — 基于实际注入值列表，`str.replace`（无 ReDoS）。值≥5 个字符。+ run-scoped `_add_skill_secrets_to_run`（protocol/SSE/持久化 masking）。 | `marketplace/redaction.py:110`, `skill_executor.py:224`, `runtime_component_builder.py:210` |
| **B. Credential** | `resolve_credential_bindings`（override: agent_skills.config > SkillCredentialBinding > 无）→ build 时 decrypt → `descriptor.credential_bindings` → hot path 中通过 `env_map` 注入 env。**最小 env（无 host leak）**。未满足时 build 阶段 fail-fast。 | `credential_requirements.py:308`, `skill_runtime.py:306`, `skill_executor.py:81-112` |
| **C. Audit** | `record_sandbox_denial`（action `skill_security.sandbox_denied`, reason_code）+ `record_credential_audits`（action `credential.invoke`, per binding, spawn 前）。独立 session，best-effort。`audit_events` table。 | `skill_executor_audit.py`, `credentials/service.py:267` |
| **D. HiTL** | `execute_in_skill_risk()`=`CODE_EXECUTION`, `allowed_decisions=(approve,reject)`, `trigger_safe=False` → `interrupt_on={"execute_in_skill":...}`。interrupt 位于**tool call 边界**（spawn 前），与执行 substrate 无关。trigger mode 为 `interrupt_on=None` + 硬性阻止 `execute_in_skill`。 | `tools/risk.py:260`, `runtime/interrupts.py`, `runtime_component_builder.py:502` |
| **E. Artifact** | `ArtifactDeltaRecorder` — **基于 filesystem diff**（不是解析返回字符串）。`ARTIFACT_SOURCE_TOOL_NAMES={execute_in_skill,write_file,edit_file}`。`output_dir` snapshot→diff→`conversation_artifacts`+`artifact_versions`。 | `services/artifacts/recorder.py:33,70`, `conversation_stream_service.py:435` |

**host 保留的 4 大 invariant**：① 明文 value→env-name map（供 A/C 使用）驻留 host，② `output_dir` 是 stat-faithful **共享 mount**（供 E 使用），③ 预先 policy gate（供 C denial code 使用）位于 host·spawn 前，④ tool call interrupt（D）位于 spawn 之上，无需重新定位。

### 2.6 seed/package/version

- office built-in（docx-document/xlsx-spreadsheet/pptx-presentation/patent-hwpx-generator）vendored 在 `app/seed/system_skill_packages/`，通过 `DOCUMENT_SKILL_SPECS` seed 到 Marketplace。
- **content-hash 按 byte 计算**（`_content_hash`, `default_marketplace_skills.py:181`）— 任何 byte 变化都会导致 spurious version bump。（教训：不要修改此目录。）
- inspector 必需 frontmatter：**仅 `name`, `description`**。`version` 可选（无则 None）。通过 `SkillMetadataError(ValueError)` 做 leaf normalize。

### 2.7 部署 infra（enabler）

- `docker-compose.yml`：backend **已经是 container**。`build: backend/Dockerfile`，volume `backend_data:/app/data`，默认 compose network，**未 mount docker socket**。
- `backend/Dockerfile`：final `python:3.12-slim`。node binary 从 `node:22-slim` 复制，`skill-node/node_modules`（docx@9.7.1, pptxgenjs@4.0.1, xlsx）在 build stage 用 pnpm 安装后复制。`ENV SKILL_NODE_BINARY=/usr/local/bin/node`, `SKILL_NODE_MODULES_DIR=/app/backend/skill-node/node_modules`。
- **🟢 关键**：`_DATA_DIR=/app/data`。`runtime_root`（skill cwd）与 `output_dir` **都位于 `/app/data` 下** → **sidecar 若 mount `backend_data:/app/data`，路径 byte 完全一致**。ADR-018 使用相对路径，因此 DB 中不会写入 host absolute path，迁移安全。
- config：`skill_node_binary`, `skill_node_modules_dir`, `conversation_output_dir=./data/conversations`, `data_root=./data`。**没有预定义 sandbox/container/docker-socket 配置**（需要新增）。

---

## 3. 目标 architecture

### 3.1 方案 B — container-backed `execute_in_skill`（推荐第 1 阶段）

```
┌──────────────────────────── backend container ────────────────────────────┐
│  create_deep_agent(FilesystemBackend, tools=[..., execute_in_skill])      │
│  execute_in_skill coroutine：                                              │
│    ① attachment gate ② env 构建 ③ credential 注入 ④（host runner 时）allowlist   │
│    ⑤ audit/HiTL ──（以下全部保留在 host）──                              │
│    ⑥ SkillRunner.run(command|args, cwd, env, timeout, network) ───────────┼──┐
│    ⑦ URL替换·OUTPUT_FILES·usage ⑧ redaction（host）                       │  │ HTTP
└───────────────────────────────────────────────────────────────────────────┘  │ (compose net)
        │ backend_data:/app/data（共享）                                         ▼
┌──────────────────────────── skill-sandbox sidecar ─────────────────────────┐
│  toolchain image（LibreOffice/pandoc/poppler/pip/npm）+ POST /run          │
│  backend_data:/app/data（相同 mount）→ cwd/output_dir 路径 byte 完全一致       │
│  无 secret/DB 访问。non-root, read-only rootfs（+ /tmp,/app/data 可写）      │
└─────────────────────────────────────────────────────────────────────────────┘
```

- 仅将执行移动到 sidecar。**allowlist/redaction/audit/HiTL/artifact/credential contract 全部保留在 backend**（保持 §2.5 的 4 大 invariant）。得益于共享 volume，无需路径转换。
- sidecar 不是 backend，而是**隔离边界** — 与 host secret 分离。

### 3.2 方案 A — deepagents native `SandboxBackendProtocol`（标准第 2 阶段）

deepagents skill 文档的正式 pattern：
```python
backend = CompositeBackend(
    default=MoldySandbox(...),                     # SandboxBackendProtocol.execute
    routes={"/skills/": StoreBackend(store, ns)},  # skill 文件使用 Store
)
agent = create_deep_agent(backend=backend, skills=["/skills/"], store=store,
                          middleware=[SkillSandboxSyncMiddleware(backend), CredentialRedactionMiddleware(...)])
```
- 移除 custom `execute_in_skill` → 使用 deepagents built-in `execute`（backend 现在是 Sandbox，因此启用）。
- 通过 **middleware/wrapper 重新实现** 5 个 contract（§7）。
- **B 的 `ContainerSandboxRunner` 成为 A 的 `MoldySandbox.execute` 下层实现** → B 不是丢弃路线，而是 A 的跳板。

### 3.3 为什么 B→A（trade-off）

| | B（container-backed execute_in_skill）| A（deepagents native）|
|---|---|---|
| contract | 全部保留（代码不移动）| 通过 middleware 重新实现 |
| 变更范围 | 1 个 seam + runner 抽象 + sidecar | backend/skill storage/tool/middleware 大改 |
| 风险 | 低（渐进，feature flag）| 高（redaction/audit 回归）|
| framework 对齐 | 保持 custom | 标准做法，可吸收 upstream |
| 达成目标（office 执行）| ✅ 立即 | ✅（更晚）|

**结论**：G1~G4 先用 B 达成，G5（对齐）再收敛到 A。下文 §5~6 为 B，§7~8 为 A。

---

## 4. Anthropic office skill 要求 & toolchain

### 4.1 按 skill 的 flow/tool

| skill | READ | CREATE | EDIT/转换 |
|---|---|---|---|
| **docx** | `pandoc --track-changes=all`, `unpack.py` | **Agent 编写 Node/docx-js script** | `unpack.py`→编辑 XML→`comment.py`/`pack.py`; `.doc`转换·accept-changes = `soffice` |
| **xlsx** | pandas | **Agent 编写 Python(openpyxl)** | 公式重算 `recalc.py`（→`soffice`，必需）|
| **pptx** | `python -m markitdown`, `thumbnail.py`（→soffice+pdftoppm+Pillow）| **Agent 编写 Node/pptxgenjs**（icon sharp）| `unpack.py`→`add_slide.py`→编辑 XML→`clean.py`→`pack.py` |
| **pdf** | pypdf/pdfplumber, `pdftotext` | **Agent 编写 Python(reportlab)** | pypdf(merge/split/rotate/encrypt)，填表= bundled script+JSON，OCR=pdf2image+tesseract |

- **共享 `scripts/office/` package**（docx/xlsx/pptx 共用）：soffice shim, unpack/pack/validate, helpers, validators（`lxml`+`defusedxml`），bundled OOXML XSD。
- **隐式 namespace 相对 import**（`from office.soffice import …` 等）→ 执行时必须满足 `cwd=技能dir` + `scripts/` 可 import（当前代码已设置 `cwd=resolved`, `PYTHONPATH=resolved` → 符合）。

### 4.2 集成 toolchain inventory（sidecar image）

**apt**（基于 Debian/Ubuntu）：
```
libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress   # 较重(~500MB~1GB)，soffice cold start 慢
pandoc poppler-utils qpdf git
fonts-liberation fonts-dejavu           # Arial/Times 替代
fonts-noto-cjk fonts-nanum              # ★ 韩文/CJK 渲染必需（没有会显示 tofu）
nodejs npm                              # docx-js/pptxgenjs/pdf-lib
# 可选（按 flow）：imagemagick tesseract-ocr tesseract-ocr-kor pdftk-java build-essential（仅 AF_UNIX 阻断 sandbox）
```
**pip**:
```
defusedxml lxml openpyxl pandas Pillow pypdf pdfplumber pdf2image reportlab "markitdown[pptx]"
# 可选：pypdfium2 pytesseract
```
**npm(-g)**：`docx pptxgenjs sharp react-icons react react-dom`（+ 可选 `pdf-lib pdfjs-dist`）。→ 在 image 中**全局安装**，runtime 无需 `npm install`（避免 network）。将 `NODE_PATH` 指向全局 node_modules。

### 4.3 system 要求

- `SAL_USE_VCLPLUGIN=svp`（soffice.py 自动设置）— 无 X server 的 headless。
- **必须有可写 `HOME`/`/tmp`** — `recalc.py` 会向 `~/.config/libreoffice/...` 写 macro，accept-changes 使用 `/tmp/libreoffice_docx_profile`。→ container runner 应将 `HOME` 设为 **per-run 可写 tmp**（例如 `/tmp/skillhome-<runid>`），避免污染共享 skill dir + 隔离 soffice profile。
- **预装 CJK 字体** — 首次渲染时构建字体 cache，缺失时会静默显示方块。
- **cold start** — 首次 `soffice` 需要数秒。image build/boot 时通过 `soffice --headless --terminate_after_init` prewarm。
- **poppler PATH** — `pdf2image` 会 shell out `pdftoppm`。

### 4.4 “Agent 编写代码→执行” flow

CREATE 时 Agent 会**编写**并执行新的 script（`node create.js`/`python gen.py`）。在 Moldy 中：
1. Agent 通过 `write_file`（deepagents FilesystemBackend, root=`data/`）向 `/runtime/<thread>/.../skills/docx/create.js` 写入 → **因为是共享 volume，sidecar 可见**。
2. `execute_in_skill(command="node create.js")` → container runner 在 sidecar 中执行。

→ 当前 host allowlist 固定要求 `scripts/<f>`，因此会阻止此操作。**container runner 放宽 allowlist**（§5.3），允许任意命令。write_file 必须可写 runtime skill dir（FilesystemBackend virtual_mode 允许写 root 下路径 — 符合）。

### 4.5 🔴 license 警告（禁止 vendoring）

- 四个 skill 的 frontmatter 均为 `license: Proprietary. LICENSE.txt has complete terms` — **但任何位置都没有 LICENSE.txt**。再分发权不明 → **不要 commit 到 repo**（禁止 §2.6 content-hash seed path）。
- toolchain（pypdf/reportlab BSD, pdfplumber/pdf-lib MIT, **poppler GPL-2**, **LibreOffice MPL-2/LGPL-3**）以**独立 binary 通过 apt/pip/npm 安装·subprocess 调用** → 避免 GPL derivative 纠缠。**禁止静态链接/ vendoring source**。
- bundled OOXML XSD（ECMA/MS）也属于第 3 方 spec 再分发项。
- **采用 pattern（已确定）**：toolchain 仅放入 **image**（apt/pip/npm，禁止静态链接/vendoring）。skill payload 根据 operator 决定以 **built-in seed**（§5.7）提供。⚠️ 但仅限**自用/内部部署** — Moldy 对外分发/公开前必须先获得实际 license。注意 content-hash 对 byte 敏感（§2.6）。

---

## 5. 方案 B 详细设计

### 5.1 执行抽象：`SkillRunner`

新增 `app/agent_runtime/skill_runner.py`：
```python
@dataclass(frozen=True)
class SkillRunResult:
    stdout: bytes
    stderr: bytes
    returncode: int | None
    timed_out: bool = False

class SkillRunner(Protocol):
    async def run(self, *, args: list[str] | None, command: str | None,
                  cwd: str, env: dict[str, str], timeout_seconds: float,
                  network: bool) -> SkillRunResult: ...
    async def cancel(self, handle) -> None: ...   # CancelledError 路径

class LocalSubprocessRunner:      # 当前行为迁移（host runner）
    # asyncio.create_subprocess_exec(*args, cwd, env) + wait_for + kill
    ...

class ContainerSandboxRunner:     # 新增（sidecar HTTP）
    # POST {command, cwd, env, timeout, network} → sidecar，streaming/polling 返回结果
    ...
```
- `LocalSubprocessRunner` **原样**迁移 §2.1 的第 6~7 步（目标回归 0）。
- `ContainerSandboxRunner` 调用 §5.4 sidecar API。

### 5.2 execution_profile 扩展（无需 migration）

`execution_profile` 是 JSON column，因此**无需 DB migration**。新增字段（均可选，默认 host）：
```jsonc
{
  "runner": "container",          // "host"（默认）| "container"
  "image": "moldy-skill-sandbox", // container 时使用的 sidecar/image label
  "timeout_seconds": 600,         // 考虑 office 的 soffice cold start，向上调整
  "requires_network": false,      // 映射到 container network mode
  "relaxed_commands": true        // container 时绕过 allowlist
}
```
- 扩展执行器消费位置：当前仅读取 `_skill_timeout_seconds`/`_requires_network`，因此在此加入 `runner`/`relaxed_commands` 分支。`_MAX_SKILL_TIMEOUT_SECONDS`（420）在 container 时提高 clamp（例如 900）。

### 5.3 条件式 allowlist

`skill_executor.py` 第 4 步分支：
```python
runner_kind = _runner_kind(descriptor)   # "host" | "container"
if runner_kind == "host":
    args, error = _prepare_skill_subprocess_args(command, resolved=resolved, env=env)
    # ... 保持现有拒绝/denial 路径不变
    run_input = {"args": args, "command": None}
else:  # container
    error = _prepare_container_command(command)   # 轻量验证（§5.3.1）
    run_input = {"args": None, "command": command}
```
**container 轻量验证**（`_prepare_container_command`）：限制命令长度、阻止 NUL/控制字符、确认 `shlex.split` 可解析（失败则拒绝）。**无 executable allowlist·无 path 强制** — 因为隔离由 container 边界负责。`curl`/network 通过 `requires_network`→container network mode 强制（§5.9）。保留 denial audit（新增 reason_code `container_command_policy`）。

> ⚠️ 即使在 container mode 中，**仍只注入最小 host secret env**（§2.5-B）— 即使 container 已隔离，也不注入不必要的 secret。

### 5.4 sidecar service `skill-sandbox`

**Dockerfile** `skill-sandbox/Dockerfile`（新增目录，可 commit 到 repo — 仅 toolchain）：
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress \
    pandoc poppler-utils qpdf git \
    fonts-liberation fonts-dejavu fonts-noto-cjk fonts-nanum \
    nodejs npm ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir defusedxml lxml openpyxl pandas Pillow pypdf \
    pdfplumber pdf2image reportlab "markitdown[pptx]"
RUN npm install -g docx pptxgenjs sharp react-icons react react-dom
ENV NODE_PATH=/usr/local/lib/node_modules
ENV SAL_USE_VCLPLUGIN=svp
# font cache + soffice prewarm
RUN fc-cache -f && soffice --headless --terminate_after_init || true
COPY skill-sandbox/runner /app/runner
CMD ["uvicorn", "runner.main:app", "--host", "0.0.0.0", "--port", "8899"]
```

**exec API**（`runner/main.py`，最小 FastAPI）：
- `POST /run` body `{command, cwd, env, timeout_seconds, network, run_id}` → sidecar 内将 `HOME` 设置为 `/tmp/skillhome-<run_id>`（§4.3），`asyncio.create_subprocess_shell(command, cwd=cwd, env=env)` 或 `create_subprocess_exec(["/bin/sh","-c",command])`，`wait_for(timeout)`。返回 `{stdout, stderr, returncode, timed_out}`。
- `POST /cancel/{run_id}` → kill 对应 subprocess（供 backend CancelledError 路径使用）。
- 认证：共享 secret header（`X-Sandbox-Token`, compose env）。仅 compose 内部 network，不向外暴露。

**docker-compose 新增**：
```yaml
  skill-sandbox:
    build: { context: ., dockerfile: skill-sandbox/Dockerfile }
    environment:
      SANDBOX_TOKEN: ${SANDBOX_TOKEN:?set-a-token}
    volumes:
      - backend_data:/app/data          # ★ 相同 volume → 路径 byte 完全一致
    tmpfs: [ "/tmp" ]                    # HOME/profile 可写（或 writable layer）
    read_only: true                     # rootfs 只读（仅 /app/data, /tmp 可写）
    mem_limit: 2g
    pids_limit: 256
    cpus: "2.0"
    networks: [ default ]               # network policy 见 §5.9
    # 不 mount docker socket，no privileged
  backend:
    environment:
      SKILL_SANDBOX_ENABLED: ${SKILL_SANDBOX_ENABLED:-false}
      SKILL_SANDBOX_URL: http://skill-sandbox:8899
      SANDBOX_TOKEN: ${SANDBOX_TOKEN:-}
    depends_on: { skill-sandbox: { condition: service_started } }
```

> **隔离级别（如实说明）**：此 sidecar **与 host 隔离**（无 secret/DB）。但**所有 skill run 共用一个 sidecar** → cross-run 隔离为 process 级（sidecar 内不同 user/`/tmp` 分离）。强 per-run container 隔离留到 §11 hardening（runner 以 per-run `docker run` spawn；或在方案 A 使用 hosted provider）。B 的目标（移除 host RCE）已满足。

### 5.5 Seam 替换

将 `skill_executor.py:153-175` 改为 runner 调用：
```python
runner = get_skill_runner(runner_kind)          # factory（基于 config）
await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
try:
    res = await runner.run(
        args=run_input["args"], command=run_input["command"],
        cwd=str(resolved), env=env,
        timeout_seconds=timeout_seconds,
        network=_requires_network(descriptor),
    )
except asyncio.CancelledError:
    await runner.cancel(handle)   # container：POST /cancel
    raise
if res.timed_out:
    return f"Error: script execution timed out ({timeout_seconds:g}s)."
stdout, stderr = res.stdout, res.stderr
returncode = res.returncode
# ↓ 之后第 8~10 步（URL替换/OUTPUT_FILES/usage/redaction）完全相同
```
- `LocalSubprocessRunner` 在上述 `except` 中保留 `proc.kill()`+`wait()`。
- 第 8~10 步与 audit/HiTL **不修改** → contract 自动保持。

### 5.6 contract 保持映射（B）

| contract | B 中的保持方式 |
|---|---|
| A. Redaction | runner 原样返回 `stdout/stderr` → 在 host 上**相同应用** `redact_credential_values(result, injected_env)`。`injected_env` map 驻留 host。 |
| B. Credential | 将 env dict 原样传给 runner（sidecar request body）。保持最小-env invariant。`PYTHONPATH/HOME/SKILL_OUTPUT_DIR` 因为是**共享路径而仍有效**（但 HOME 建议按 §4.3 通过 env override 设为 container tmp）。fail-fast 在 build 阶段，因此无关。 |
| C. Audit | 预先 policy gate（host allowlist 或 container 轻量验证）·credential invoke·denial 均**保留在 host·spawn 前**。新增 container denial reason `container_command_policy`。 |
| D. HiTL | interrupt 位于 tool call 边界，因此**不修改**。保持 `execute_in_skill` 名称 → risk 映射不变。 |
| E. Artifact | `output_dir` 是**共享 stat-faithful mount**，因此 recorder 的 fs diff 可直接观察 sidecar 产出文件。`ARTIFACT_SOURCE_TOOL_NAMES` 无需修改（名称保留）。 |

### 5.7 隔离对象决定 — 基于 capability（非 office 特化）

> **原则（2026-07-14 确定）**：隔离依据不是“是否 office”，而是**“skill 是否实际执行代码/生成文件”**。有 side effect 的 skill 全部隔离。

skill 分为两类：
- **文本/参考 skill** — 不执行（按 deepagents 定义 "skills = TEXT"）。根本不会调用 `execute_in_skill` → **隔离无关**（没有任何执行）。
- **执行型 skill** — 有 script 执行/文件写入等 side effect（office·image-generation·deep-research·openwiki·patent-hwpx·k-skill 等）→ **全部在隔离 container 中执行**。

即 **"执行型 skill = 默认隔离"**。`execution_profile.runner` 对执行型默认设为 `container`，`host`（现有 allowlist 本地 subprocess）作为**legacy opt-out → Phase 2 移除**。（文件写入几乎是所有执行型 skill 的正常行为，因此不是单独标准；“是否执行代码”才是实质标准 — 所有调用 `execute_in_skill` 的 skill 都属于此类。）

- **共享 warm sidecar 的隔离成本较小**（不是 per-run container spawn，而是 HTTP 往返+subprocess）。简单 skill 放到 container 中运行的 overhead 也很小 → 保留 host 快速路径的理由较弱。
- 代价：**sidecar image 必须包含所有执行型 skill 的 runtime dependency**（office toolchain §4.2 + 现有 skill python/network dependency）。Phase 2 需要清点现有 skill dependency inventory。
- `requires_network` 按 skill 映射到 sidecar network policy（image-gen/deep-research/openwiki=需要 network，office/pdf=通常不需要）。

**rollout（渐进，§12）**：Phase 1(B) = **仅 office skill** 使用 sidecar（路径验证，`SKILL_SANDBOX_ENABLED` gate，现有 skill 保持 host）→ Phase 2 = **所有执行型 skill 迁移到 sidecar + 移除 host allowlist 路径**（完成默认隔离）。

**office skill 供给（确定：built-in）**：按 operator 决定将 office skill 作为 **built-in seed**（`system_skill_packages/` + Marketplace seed，沿用现有 docx-document 方式）bundle，并赋予 `execution_profile.runner="container"`。
> ⚠️ **license 注意（保留）**：Anthropic office skill 为 `Proprietary`（无 LICENSE.txt）。**自用/内部部署**可按 operator 决策进行，但**对外公开/再分发前必须取得实际 license**。toolchain binary（poppler GPL-2, LibreOffice MPL/LGPL）仅通过 apt 安装到 image 并 subprocess 调用（禁止静态链接/vendoring），以避免衍生关系纠缠。注意 content-hash 的 byte 敏感性（§2.6）— seed 后禁止修改文件 byte。

### 5.8 新增 config（`app/config.py`）

```python
skill_sandbox_enabled: bool = False
skill_sandbox_url: str = "http://skill-sandbox:8899"
skill_sandbox_token: str = ""            # SANDBOX_TOKEN
skill_sandbox_default_timeout_seconds: int = 600
skill_sandbox_max_timeout_seconds: int = 900
skill_sandbox_home_dir: str = "/tmp"     # per-run HOME 基础目录
```

### 5.9 network/security policy

- `requires_network=false`（默认）→ sidecar 使用**阻断 egress 的 network**（compose internal network，无外部 route）。`true` 时使用受限 egress network。
- sidecar：`read_only` rootfs, `mem_limit`/`pids_limit`/`cpus`, non-root user, `no-new-privileges`, seccomp 默认。禁止 docker socket/privileged。
- 验证 SANDBOX_TOKEN header。backend↔sidecar 仅 compose 内部使用。
- secret 仅放在 request **body** 中（禁止放入 process args/URL），sidecar 日志不记录 env。

### 5.10 cancel/timeout

- timeout：sidecar 自行 `wait_for` + kill，返回 `{timed_out:true}`。
- cancel：backend `CancelledError` → `runner.cancel(run_id)` → `POST /cancel/{run_id}` → sidecar kill。保持“防止 orphan/死亡 conversation dir 写入”的 invariant。

---

## 6. 方案 B 实现 task（文件级 checklist）

### Phase B0 — sidecar scaffolding
- [ ] `skill-sandbox/Dockerfile`（§5.4），`skill-sandbox/runner/main.py`（`/run`,`/cancel`,token）。
- [ ] 验证 `skill-sandbox/runner/package` node 全局安装（`node -e "require('docx');require('pptxgenjs')"`）。
- [ ] image build + 确认 `soffice --headless --terminate_after_init` prewarm，CJK render smoke（韩文 docx→pdf 无方块）。
- [ ] `docker-compose.yml` 添加 `skill-sandbox` service + backend env/depends_on。

### Phase B1 — runner 抽象（无行为变更）
- [ ] `app/agent_runtime/skill_runner.py`：`SkillRunner`/`SkillRunResult`/`LocalSubprocessRunner`（迁移当前逻辑）/`get_skill_runner` factory。
- [ ] 将 `skill_executor.py:153-175` refactor 为经过 `LocalSubprocessRunner`（仅 seam）。**回归测试：现有 skill smoke 仍全部 green**。

### Phase B2 — container runner + 条件式 allowlist
- [ ] `ContainerSandboxRunner`（HTTP, token, timeout, cancel）。
- [ ] `skill_execution_policy.py`：`_prepare_container_command`（轻量验证）+ `_runner_kind(descriptor)` + 消费 `runner`/`relaxed_commands`。
- [ ] `skill_executor.py`：host/container 分支（§5.3），新增 container denial reason。
- [ ] config 新增字段（§5.8）。`_skill_timeout_seconds` 对 container 提高 clamp。

### Phase B3 — office skill built-in seed + HOME 处理
- [ ] 将 4 种 office skill 作为 built-in seed 加入 `system_skill_packages/` + `DOCUMENT_SKILL_SPECS`（现有 docx-document 方式），赋予 `execution_profile.runner="container"`。（license caveat §5.7）
- [ ] 消费 `runner` 字段 + `SKILL_SANDBOX_ENABLED` gate（Phase 1 仅 office 使用 container）。
- [ ] container runner 将 `HOME` override 为 per-run tmp（§4.3），由 sidecar 创建/清理。
- [ ] 验证韩文 render smoke（字体）+ soffice cold start prewarm。

### Phase B4 — contract 保持验证
- [ ] redaction：即使 container stdout 中出现已注入 secret，也确认 `<redacted:...>`。
- [ ] artifact：确认 sidecar 写出的 `.docx/.pdf` 被索引到 `conversation_artifacts`（共享 volume diff）。
- [ ] audit：container_command_policy denial + credential.invoke event。
- [ ] HiTL：office skill 执行前 approval card（确认无变化）。

### Phase B5 — test/security/docs（§10, §11）
- [ ] unit（runner 抽象、条件 policy），integration（真实 sidecar 往返），E2E（真实 office 文档生成），security（host 隔离·secret 不暴露）。
- [ ] 运维文档：安装 office skill·启用 `SKILL_SANDBOX_ENABLED`·构建 image。

**方案 B done-when**：在 `SKILL_SANDBOX_ENABLED=true` + office skill install 状态下，(1) chat 中“制作韩文报告 docx” → 产出 `.docx` + artifact 索引 + preview，(2) secret 不暴露，(3) 无法在 host spawn 任意 process（隔离），(4) 现有 skill 无回归。

---

## 7. 方案 A 详细设计（标准收敛）

### 7.1 `MoldySandbox(SandboxBackendProtocol)`
- 参考 `deepagents/backends/sandbox.py`,`local_shell.py`,`langsmith.py`。将 `execute(command)->ExecuteResponse` **委托给 B 的 `ContainerSandboxRunner`** + `BaseSandbox` 自动在 execute 之上构建文件操作。
- `upload_files`/`download_files` 使用共享 volume（sidecar）或 sidecar file API。

### 7.2 backend 替换
```python
backend = CompositeBackend(
    default=MoldySandbox(runner=ContainerSandboxRunner(...)),
    routes={"/skills/": StoreBackend(store=store, namespace=...)},  # 或保持共享 volume FilesystemBackend
)
```
- 选项 A1（最小 contract 重建）：`/skills/` 与 `output_dir` 保持在**共享 volume** → artifact recorder fs diff 不变。仅 `default=MoldySandbox` 做执行隔离。
- 选项 A2（完全 native）：将 skill 迁移到 `StoreBackend` + `SkillSandboxSyncMiddleware`（store→sandbox upload）+ 产出通过 sandbox download API → 重做 recorder。

### 7.3 tool 转换
- custom `execute_in_skill` → deepagents built-in `execute`（backend 为 Sandbox 因此启用）。或保留 `execute_in_skill` 作为 `MoldySandbox.execute` 的薄 wrapper（保留 contract hook，更安全）。

### 7.4 5 个 contract 重建（middleware/wrapper）
| contract | A 中的重建 |
|---|---|
| Redaction | `execute` 后处理 middleware 重新应用 `redact_credential_values(out, injected_env)`。从 credential 解析向 middleware 注入 `injected_env`。 |
| Credential | binding 解析→将 env 作为 `execute` 的 per-call env 传递（Cipher decrypt 保留在 host，仅将明文送入 sandbox）。 |
| Audit | `execute` wrapper 记录 denial/invoke event。预先 policy 仍由 wrapper 维护。 |
| HiTL | `interrupt_on["execute"]`（base policy 中**已存在**）+ 在 `trigger_blocked_tools` 中添加 `"execute"`（当前仅对 `execute_in_skill` 特例）。 |
| Artifact | A1：保持共享 volume → 无变化。A2：`ARTIFACT_SOURCE_TOOL_NAMES` 增加 `"execute"` + 使用 sandbox file API 做 diff。 |

### 7.5 B→A 升级
- `ContainerSandboxRunner`（B）→ `MoldySandbox.execute`（A）**直接升级**。
- 复用 sidecar/image/network policy/cancel 逻辑。
- 可选：扩展为 hosted provider（LangSmith/Daytona/Modal/Harbor）进行 per-run 隔离（§11）。

---

## 8. 方案 A 实现 task（摘要）
- [ ] `MoldySandbox(SandboxBackendProtocol)` + 升级 `ContainerSandboxRunner`。
- [ ] 将 `build_agent` backend 改为 `CompositeBackend(default=MoldySandbox, routes=...)`。
- [ ] 5 个 contract middleware（§7.4）。`trigger_blocked_tools` 添加 `execute`。
- [ ] (A2) skill Store migration + `SkillSandboxSyncMiddleware` + recorder sandbox file API。
- [ ] contract 等价性测试（用与 B 相同的 oracle 固定两侧 — 避免委托等价性陷阱）。
- [ ] 删除自定义 `execute_in_skill`，或缩减为薄包装器。

**A 方案 done-when**：通过 deepagents 原生 `execute` + Sandbox backend 执行办公技能，5 个契约回归测试全部通过，与 B 行为等价。

---

## 9. 数据模型 / 迁移

- **无需 DB 迁移**：`execution_profile` 是 JSON 列。新增 `runner/image/relaxed_commands` 不改变 schema。
- 办公技能**不是 seed**（许可证）→ `default_marketplace_skills.py`/`system_skill_packages` **不变**（避免 content-hash 陷阱）。
- 无需新增观测列。audit 复用现有 `audit_events`（仅新增 reason_code）。

---

## 10. 测试策略

| 层级 | 项目 |
|---|---|
| **单元(backend)** | `SkillRunner` 抽象(Local/Container mock)、`_prepare_container_command` 边界、`_runner_kind`/profile 消费、redaction 同样应用于容器 stdout、timeout clamp(container 上调)。mutation 实证（移除 guard 时 FAIL）。 |
| **集成** | sidecar 真实往返（`POST /run` 执行/超时/取消）、共享卷路径一致性（宿主可观察到 sidecar 写入的文件）。`-m integration`。 |
| **E2E** | 办公真实文档生成 tour：韩文 docx（字体）、xlsx（公式 recalc）、pptx(pptxgenjs)、pdf(reportlab/表单)。artifact 索引+预览。使用 scripted model 固化。 |
| **安全** | (1) 容器命令无法触达宿主进程/文件，(2) 注入 secret 不以明文暴露在 stdout/持久化事件中，(3) `requires_network=false` 时阻断 egress，(4) sidecar 中无 DB/secret env。 |
| **契约回归** | 5 个契约分别使用独立 oracle（禁止委托等价性 tautology）。断言 audit action/outcome/reason_code 内容。 |

---

## 11. 安全审查 & 加固

- **威胁模型**：用户 Agent 执行任意命令 →（缓解）隔离容器边界、宿主 secret/DB 分离、阻断 egress、资源上限。
- **剩余风险(B)**：单个 sidecar 共享 → 跨 run 隔离较弱（进程级）。**加固**：per-run `docker run`（按需 docker socket + rootless/gVisor），或 A 方案 hosted per-run sandbox。
- **Secret**：通过 body 传递·不记录日志·不进入镜像层/`docker inspect`。双重 redaction（基于值 + run-scoped）。
- **DoS**：`mem_limit/pids_limit/cpus/timeout`，与技能 usage/queue 联动。
- **许可证**：§4.5 — 镜像仅含 toolchain，技能 payload 不提交。

---

## 12. 发布 / 回滚

- **feature flag `SKILL_SANDBOX_ENABLED`**（默认 false）。off 时所有技能 host runner = **与当前 100% 相同**（无回归）。
- 渐进： (1) 部署 sidecar + flag off smoke，(2) **Phase 1：仅办公技能** container dogfood（§5.7），(3) 稳定后 **Phase 2：所有执行型技能迁移到 sidecar + 废弃 host allowlist 路径**（完成隔离 by default）— 此时需向 sidecar 镜像加入现有技能依赖 inventory。
- **回滚**：Phase 1 期间可通过 flag off 立即恢复 host（即便 sidecar 宕机也仅办公技能失败，其余不受影响）。Phase 2 后 sidecar 成为必经路径，因此需要 sidecar HA/健康检查。

---

## 13. 风险 & 缓解

| 风险 | 缓解 |
|---|---|
| LibreOffice 冷启动/镜像大小 | 预热、镜像缓存、上调 timeout(600s)，必要时常驻 warmed sidecar。 |
| 缺少 CJK 字体（方框） | `fonts-noto-cjk`/`fonts-nanum` + `fc-cache` 构建步骤，韩文渲染 smoke。 |
| 共享卷 stat 变化(inode/ctime) → 虚假的 artifact "updated" | 让 sidecar in-place 写入（避免 copy-out），放宽 diff 范围。 |
| 跨 run 隔离较弱(B) | 分离 per-run HOME/tmp，§11 加固，升级到 A 方案。 |
| 许可证 | 禁止 vendoring，运行时安装，toolchain 使用独立二进制。 |
| Runner 重构回归 | B1（无行为变化迁移）后以现有技能 smoke 全绿作为 gate。 |

---

## 14. 决策确认 (2026-07-14)

| # | 决策 | 确认 | 备注 |
|---|---|---|---|
| 1 | 容器运行时 | **共享 sidecar exec API** | 不需要 docker socket，与宿主隔离。per-run spawn/hosted 是 §11 加固·A 扩展选项。 |
| 2 | 技能 payload 供应 | **内置 seed** | `system_skill_packages/`+市场 seed。⚠️ 许可证仅限自部署·对外公开前取得（§5.7）。 |
| 3 | 隔离对象 | **基于能力 — 所有执行型技能全部隔离**（非办公特化） | 采纳用户反馈。文本技能无执行→无关。§5.7。 |
| 4 | A 方案范围 | **先 A1（保留共享卷，最小重实现契约）→ 再逐步 A2** | |
| 5 | 网络 | **默认阻断**，npm/pip baked 进镜像，仅 `requires_network=true` 技能允许 egress | |

**发布结论**：架构按“执行型技能 = 隔离 by default”设计，但实现采用 **Phase 1 仅办公技能走 sidecar（验证）→ Phase 2 迁移全部执行型技能 + 废弃 host allowlist** 的渐进方式（§12）。

---

## 15. 附录 — 核心文件参考索引

| 关注点 | 文件:行 |
|---|---|
| 执行 seam | `app/agent_runtime/skill_executor.py:153-175` |
| allowlist 策略 | `app/agent_runtime/skill_execution_policy.py:46-160` |
| SkillToolContext/descriptor | `app/marketplace/skill_runtime.py:70-138, 257-303` |
| create_deep_agent 调用 | `app/agent_runtime/runtime_component_builder.py:116-147, 429/288, 431-473, 502-507` |
| execution_profile 消费 | `skill_execution_policy.py:144-160`(timeout/network) |
| redaction | `app/marketplace/redaction.py:110`, `runtime_component_builder.py:210` |
| credential 解析/注入 | `app/marketplace/credential_requirements.py:308`, `skill_runtime.py:306`, `skill_executor.py:81-112` |
| audit | `app/agent_runtime/skill_executor_audit.py`, `app/credentials/service.py:267` |
| HiTL risk/interrupt | `app/tools/risk.py:260-326`, `app/agent_runtime/runtime/interrupts.py:21-59` |
| artifact recorder | `app/services/artifacts/recorder.py:33,70,199`, `conversation_stream_service.py:435` |
| seed/版本/content-hash | `app/seed/default_marketplace_skills.py:45-155,181-193,459-563` |
| 部署 | `docker-compose.yml`(backend/volumes), `backend/Dockerfile`, `docs/design-docs/adr-018-relative-storage-path.md` |
| deepagents 参考 | `.venv/.../deepagents/backends/{sandbox,langsmith,local_shell,filesystem}.py`, docs.langchain.com/oss/python/deepagents/{sandboxes,backends,skills} |

### execution_profile schema（提案，最终）
```jsonc
{
  "support_level": "node_package|ready_python|...",  // 现有（badge）
  "runners": ["node"|"python"|...],                  // 现有（badge）
  "requires_python": true, "requires_node": true,    // 现有（badge）
  "requires_network": false,                          // runtime 消费（网络模式）
  "timeout_seconds": 600,                             // runtime 消费(clamp)
  "runner": "host|container",                         // 新增（runtime 分支）
  "image": "moldy-skill-sandbox",                     // 新增(container)
  "relaxed_commands": true                            // 新增（绕过 allowlist）
}
```

### 命令示例（办公，container runner）
```
# 生成 docx：Agent 用 write_file 编写 create.js 后
execute_in_skill(skill_directory="docx", command="node create.js")
# xlsx 公式重新计算
execute_in_skill(skill_directory="xlsx", command="python scripts/recalc.py out.xlsx")
# 提取 pdf 文本
execute_in_skill(skill_directory="pdf", command="python scripts/extract_form_structure.py in.pdf")
# pptx 缩略图
execute_in_skill(skill_directory="pptx", command="python scripts/thumbnail.py deck.pptx")
```

---

**结束。实现按 §6(B) → §8(A) 顺序，先确认 §14 的决策事项。**
