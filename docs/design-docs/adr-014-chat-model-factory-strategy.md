# ADR-014: Chat Model Factory — 分离 Provider Quirks（引入 Strategy 模式）

- **状态**: 已批准 (2026-05-08)
- **DRI**：Pichai（System Architect）
- **相关**: PR #139（chat runtime 回归批量 fix），HANDOFF follow-up #1 + #5
- **范围**: `app/agent_runtime/model_factory.py`, `app/services/model_test.py`

---

## § 背景

PR #139 回归追踪中暴露出的两类累积技术债：

1. **GPT-5 family 处理重复** — `create_chat_model`（运行时）+ `_completion_token_cap_kw`（test surface）两边分别实现了相同的 quirk 分支（拒绝 `max_tokens` → top-level forward `max_completion_tokens` + drop `temperature`）。PR #139 中只修了一侧，曾发生 1 次 wire mismatch 回归（#137 → #138 → #139 连锁）。
2. **`model_test.py` 的孤立副本** — `_is_gpt5_family` / `_GPT5_FAMILY_PREFIXES` 与 `model_factory.py` 分开定义。raw curl surface（`/api/models/{id}/test/raw`）可能与实际 wire drift。

`create_chat_model` 的主体中已累积 6 个 quirk：
- 解析 env-fallback 密钥
- explicit base_url vs canonical pin
- temperature/top_p/max_tokens 选项映射
- Anthropic 同时拒绝 temperature+top_p
- GPT-5 family `max_completion_tokens` + temperature drop
- 仅为 ChatOpenAI 注入 SSL trust store

新增 provider quirk（例如 Gemini reasoning、Anthropic thinking）时，函数会继续变长，并累积 test path 与 sync 断开的风险。

---

## § 决策

### 决策 1：拆分为 4 个 kwargs in-place 变形 helper

|Helper|职责|调用路径|
|---|---|---|
|`_apply_anthropic_quirks`|temperature+top_p 同时存在时 drop top_p|`create_chat_model`|
|`_apply_gpt5_quirks`|max_tokens→max_completion_tokens，drop temperature，注入 default cap|`create_chat_model`(default=4096), `create_chat_model_for_test`(default=200)|
|`_apply_openai_compatible_base_url`|未指定 `base_url` 时 pin provider canonical|两者|
|`_apply_openai_ssl_clients`|仅 `ChatOpenAI` 系列注入 truststore SSL|两者|

**替代方案评估**：也评估过按 provider 分类（e.g. `OpenAIQuirks`, `AnthropicQuirks`），但 quirk 具有 cross-cutting 特性（GPT-5 是 OpenAI 的 sub-family），且调用侧只有两处，因此函数式更划算。未来 quirk 增多时可升级为类。

### 决策 2：公开 `is_gpt5_family` — 单一事实来源

`_is_gpt5_family` (private) → `is_gpt5_family` (public)。`model_test.py` 不再使用自己的副本，而是 `from app.agent_runtime.model_factory import is_gpt5_family`。

`_GPT5_FAMILY_PREFIXES` 保持为函数内部实现常量（外部不引用）。

### 决策 3：移除 `_completion_token_cap_kw`

由 `_apply_gpt5_quirks(completion_token_default=...)` 吸收相同职责。`create_chat_model_for_test` 调用时注入 `default=TEST_COMPLETION_TOKEN_CAP=200`。

### 决策 4：公开 API 保持不变

- `create_chat_model(provider, model_name, api_key, base_url, **extra)` — 保持签名不变
- `create_chat_model_for_test(...)` — 保持签名不变
- `create_chat_model_with_fallback(...)` — 保持签名不变
- `TEST_COMPLETION_TOKEN_CAP`（在 PR #138 中设为 public）— 保留
- `_TEST_COMPLETION_TOKEN_CAP` alias — 保留（backward compat）

---

## § 结果

**正面**：
- GPT-5 quirk 单一实现 → 阻断 wire mismatch 回归
- `model_test.py` 使用与运行时相同的函数判断 family → raw curl drift 0
- 新增 provider quirk 时只需增加一个 helper（open/closed）

**负面 / 约束**：
- 多增加一层函数调用（忽略微小开销）
- 职责拆分到 4 个 helper，需要追踪短调用 chain — 由于职责命名明确，可读性损失 < 可读性收益

**不变项**：
- 所有外部 import 的符号（`PROVIDER_API_KEY_MAP`, `PROVIDER_MAP`, `TEST_COMPLETION_TOKEN_CAP`, `sync_env_fallback_from_credentials`, `env_provider_keys`, `create_chat_model*`）签名/名称保持不变
- 现有 test 资产（`tests/test_model_factory.py:188~270` GPT-5/base_url guard）必须无需修改即可通过

---

## § 验证

- `tests/test_model_factory.py` — GPT-5 guard + base_url pin guard 通过
- `tests/test_credentials_llm_sync.py` — 确认 `_ENV_FALLBACK` 同步不受影响
- `tests/test_model_fallback.py` — 确认 `create_chat_model_with_fallback` chain 不受影响
- pyright 0/0, ruff clean

## § 后续

- ADR-015 候选：provider quirk 累积到 5 个以上时升级为 strategy 类
- `model_test.py:_provider_wire_shape` 也与 helper 调用模式对齐（单独 PR — scope 外）
