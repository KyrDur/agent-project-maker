# ADR-021: Value-Based Trace Redaction（基于值的 Trace Secret 遮罩）

- **状态**: 已提议 (2026-06-24)
- **DRI**: chester
- **相关**: ADR-007/009/013 (Credentials), ADR-011 (SSE Stream Resume), ADR-017 (Marketplace Resources — `redact_credential_values` 来源)
- **范围**: `app/agent_runtime/protocol_redaction.py`, `app/agent_runtime/run_secrets.py`（新增）, `app/services/conversation_stream_service.py`, `app/agent_runtime/runtime_component_builder.py`, `app/agent_runtime/agent_stream_runner.py`, `app/marketplace/redaction.py`（复用）

---

## § 背景

`redact_protocol_data`（`protocol_redaction.py`）在 trace/persistence/SSE egress 的 5 个位置遮挡 secret：

| 调用方 | 内容 | 暴露对象 |
|--------|--------|-----------|
| `protocol_persistence.py:23` | LangGraph event data | DB 持久化（`message_events`） |
| `langgraph_streaming.py:189` | 同一 event | 发送给 SSE client |
| `conversation_agent_protocol_state*.py` | state snapshot(messages/values) | state API 响应 |
| `chat_service.py:491` | tool_calls | 消息保存 |
| `trace_debug_service.py:52` | langfuse observation 输入输出 | operator debug trace 页面 |

agent 运行期间，通过 `{{$credentials.x}}` 插值（ADR-009）注入 tool/MCP 的 API key、header（Authorization/Cookie）、DSN 会残留在 tool 输入输出/state 中，因此需要在保存/发送/暴露前遮罩。

**问题**：当前方式在**不知道 secret 实际是什么**的情况下，用 key 名启发式（`SENSITIVE_PROTOCOL_KEY_RE`）+ 值形态正则（`_VALUE_MASK_PATTERNS`）进行**猜测**。这种猜测式方案已连续发生 3 次回归：

1. substring key 匹配 → over-redaction（`session_id`/`token_count`）+ leak（无 key 的 `Bearer`、`{name,value}` header）
2. 改为单词边界 → ReDoS（通配符重叠）+ camelCase key 泄漏
3. DSN scheme 泛化 → 更严重的 ReDoS（96KB=23 秒）+ acronym key 泄漏

每次修复都会制造新的 edge。这是基于正则猜测的根本局限。

## § 核心洞察

**正确答案已经存在于代码库中。** `app/marketplace/redaction.py:51` 的 `redact_credential_values(text, mapped_env_vars)` 会**精确按 substring 替换实际注入的 secret 值** — 包含 min-length threshold（`_MIN_REDACT_LEN=5`）和按长度降序排序（避免部分替换）。`skill_executor.py:202` 已在 subprocess 输出中使用，是经过验证的函数。

该系统具备 credential 系统，因此**运行时知道实际注入的 secret 值**。无需猜测。唯一缺口是“把这组值传递到 5 个 trace egress 位置”。

## § 决策

以**基于值的遮罩作为第一道防线，以启发式作为辅助 fallback**。

1. 按 run 收集明文 secret 值，汇总为 run-scoped set。
2. 通过 ContextVar 传播到 redaction call site。
3. `redact_protocol_data` 在启发式**之前**精确按 substring 替换这些值（复用 `redact_credential_values` 逻辑）。
4. 启发式缩减为“DB 中没有的 secret”（例如 LLM 在响应中生成的 token）的 fallback，并移除/收缩 ReDoS 表面积大的模式（URL/DSN userinfo）。

基于值的 exact-substring 替换只执行单次 `str.replace`，因此**从根本上不可能发生 ReDoS**。

## § 详细设计

### 1. 值收集
每个 run 的明文 secret 汇集位置：
- **eager**（请求进入时）：`conversation_stream_service._build_cfg`（行 108–160）— LLM `api_key`, `tools_config[*]["credentials"]`, `mcp_transport_headers`。
- **lazy**（executor 端）：`runtime_component_builder._prepare_runtime_components`（行 576）— skill `descriptor.credential_bindings[*].decrypted`。subagent 也走同一路径。

新增 helper `collect_run_secret_values(cfg, *, extra=None) -> set[str]`，在两处把值 union 到 set。过滤条件：`isinstance(str)` + `len >= 阈值`，递归扁平化 dict/list。`Bearer `/`Basic ` 前缀后的 token 本体也一并保存（应对不带前缀 echo 的情况）。

### 2. 传播 — ContextVar
在 `app/agent_runtime/run_secrets.py`（新增）中定义 `ContextVar[set[str] | None]`。在 `agent_stream_runner._run_agent_stream`（行 113–183）中 `set()`，在 `finally` 中 `reset()`（复用现有 langfuse flush finally）。

**async/streaming 边界验证**：`emit` 闭包（`langgraph_streaming.py:176`）与 persistence 写入均在与 `_run_agent_stream` **相同 async task** 中直线执行，因此 ContextVar 跨 yield 保持。fire-and-forget DB write task 会通过 `copy_context()` 复制 set 后的值，形成双重保障。subagent 在同一 run task 中，因此对 set 对象做 in-place union（不是 frozenset）。

**拒绝的替代方案**：注入 `config["configurable"]`（有 secret 泄漏到 checkpointer DB 的风险 — 绝对禁止）、AgentConfig 显式参数（会污染连 cfg 都没有的纯函数调用图）、thread_id 全局 registry（内存泄漏/race）。

### 3. Redaction 接口
```python
def redact_protocol_data(method, data, *, redact_memory=True,
                         secret_values: Iterable[str] | None = None) -> Any
```
当 `secret_values=None` 时，在入口从 ContextVar 读取 → 5 个 call site **无需改代码**即可自动生效（签名向后兼容）。先做值遮罩（`_mask_known_values`），再做 key 启发式。按长度降序 + min-length 过滤。

**局限（文档化）**：经过编码/转换的 secret（base64/url-encode/JSON-escape/部分暴露）无法 exact-match → 保留启发式 fallback 进行补充。

### 4. 缩减 Fallback 启发式
- **保留**：基于 key 的遮罩（`_is_sensitive_protocol_key` — 与 key 长度无关、与 ReDoS 无关）、anchored value 模式（`Bearer\s+\S+`, JWT `\beyJ...`, `sk-...`）。
- **移除/收缩**：URL/DSN userinfo 模式（ReDoS 根源）— 基于值方式会直接遮罩来自 DB 的 DSN，因此冗余。`SENSITIVE_ASSIGNMENT_RE` 让位于基于值方式。

### 5. trace_debug_service 路径
这是事后渲染，因此没有 ContextVar。但只要**在 persistence-time 准确遮罩，保存的 `message_events` 已经干净**（`protocol_persistence.py:23` 已做遮罩）。Langfuse 路径交由 capture 时的 `mask`（`langfuse.py:176`）处理 — 如有需要可在 capture 时集成 ContextVar（M3，可选）。

## § 渐进式 rollout（no big-bang）

| 阶段 | 内容 | done-when |
|------|------|-----------|
| M0 | `run_secrets.py`（ContextVar+helper）+ set/reset 接线。redaction 行为不变（启发式 100% 保留） | 现有测试全绿，回归 0 |
| M1 | 在 `redact_protocol_data` 中增加值遮罩层（位于启发式之前）。ContextVar 为空时 no-op | 基于值/启发式两套测试都通过（重叠防护） |
| M2 | 用 trace 样本测量覆盖率后，缩减/移除 URL/DSN userinfo 启发式 | 回归 guard 通过 |
| M3（可选） | 在 Langfuse capture 时集成 ContextVar | — |

每个阶段独立 PR，启发式保留到 M2，以保护基于值方案的空白。

## § 影响
- **无 DB 迁移**（仅运行时行为修改）。
- 签名向后兼容（keyword-only optional）→ 5 个 call site 无需修改。
- M1 之后新的 `message_events` 更干净。已保存的旧数据保持不变（backfill 属于 Open Question）。
- ContextVar 未设置（unit test/trigger 模式）时跳过值遮罩 + 只执行启发式 → 现有测试保持全绿。

## § Open Questions（需要决策）

1. **min-length/熵阈值**：如果连短密码（`hunter2` 7 字符）也要捕捉，需要降低阈值，但普通文本过度遮罩风险↑。5 字符（当前 marketplace）vs 8~12 字符+熵（复用 `secret_scan._is_opaque_secret_run`）。
2. **URL/DSN userinfo 启发式**：完全移除 vs 保留更严格的 bounded 版本（“LLM 生成的任意 DSN”不在值 set 中，无法捕捉）。
3. **编码变形的 secret**：是否把 url-quote/base64/JSON-escape 变形值也一起放入收集 set（覆盖率↑/内存·性能↓）。第一阶段建议只收 raw。
4. **Langfuse capture 集成（M3）**：纳入范围 vs 交给 Langfuse 自身 `mask`。
5. **历史存储数据 backfill**：现有 `message_events` 可能存在泄漏 — 本次范围内处理 vs 单独任务。
