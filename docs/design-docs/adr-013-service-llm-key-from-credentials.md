# ADR-013: Service-side LLM Key from Credentials (Builder/Assistant Sub-agent)

- **状态**：已批准（2026-05-06）
- **DRI**：Pichai（System Architect）
- **相关**：ADR-005（Builder/Assistant）、ADR-009（Greenfield Credentials）、commit `a7fc92d`（runtime key 隔离）
- **范围**: `app/agent_runtime/model_factory.py`, `app/agent_runtime/builder/sub_agents/helpers.py`, `app/services/system_credential_resolver.py`, `app/routers/credentials.py`, `app/main.py`

---

## § 背景

当前结构中，LLM 密钥来源**分为 3 个层级**：

| Caller | Key 来源 | 备注 |
|--------|---------|------|
| End-user agent (chat_service) | `Agent.llm_credential` → `decrypt_with_external` | 正常工作 |
| System-billed flow (Fix Agent, Image Gen) | `system_credential_resolver`: ENV → `is_system=True` Credential | ADR 之前已引入，ENV→system 分层 |
| **Builder / Assistant sub-agent** | `PROVIDER_API_KEY_MAP` (alias of `_ENV_FALLBACK`) — **ENV only** | 本 ADR 的缺口 |

Builder/Assistant helper (`builder/sub_agents/helpers.py:73,85`) 只使用 `PROVIDER_API_KEY_MAP.get(provider)`。即使用户在 `/credentials` UI 中注册 `anthropic` 密钥，builder 也看不到它。

**用户 mental model**: "Credentials UI = LLM 密钥的单一事实来源"<br>
**当前代码**: builder 只查看 `.env` → 违反 mental model

`system_credential_resolver` 已经具备 ENV→system credential 的分层 lookup 模式（用于 Fix Agent、Image Gen）。本 ADR 的核心是决定：**"在把该模式扩展到 builder/assistant 的同时，是否在不增加额外负担的情况下，把 user credentials 也纳入 fallback"**。

自 a7fc92d（"运行时密钥隔离"）以来，我们一直有意将 `Agent.llm_credential` 流程与 `_ENV_FALLBACK` 流程分离——隔离 end-user 使用自己的密钥计费的路径，与 operator 计费的路径。本 ADR 在不破坏这种隔离的前提下弥补 UX 缺口。

---

## § 决策

### 决策 1：优先级 — `ENV > system credentials > user credentials`

```
key resolution for builder/assistant sub-agent (provider P):
  1. settings.{P}_api_key  (env / .env)         ← 存在则立即返回
  2. Credential where is_system=True, definition_key=P
  3. （新增）Credential where is_system=False, definition_key=P, status='active'
       ↳ 同一 user 存在多行时 created_at DESC LIMIT 1
  4. None                                        ← caller 暴露 LLM 错误
```

**依据**：
- ENV 优先级第 1 = backward compat。对现有 `.env`-only 部署影响为 0。
- System 优先级第 2 = operator-managed 密钥优先于 user 密钥。PoC 阶段只有单一 mock user，几乎不会冲突；引入认证后也保持一致。
- User 优先级第 3 = 符合用户 mental model。在 `/credentials` UI 中注册密钥后，builder 也会自动使用。

### 决策 2：复用策略 — 扩展 `system_credential_resolver`

不**扩展** `system_credential_resolver.py` 的 `resolve_system_api_key()`，而是在 `app/credentials/service.py` 中添加**新的 helper**：

```python
# app/credentials/service.py（新增）
async def get_provider_keys(db: AsyncSession) -> dict[str, str | None]:
    """LLM provider → api_key dict。system credentials 优先，user fallback。
<br>
    Returns dict keyed by _ENV_FALLBACK key (openai/anthropic/google/openrouter).
    .env 优先级由调用方应用（sync_env_fallback_from_credentials）。
    """
```

**为什么使用新 helper**：
- `resolve_system_api_key()` 是针对单个 provider 的单次 lookup（Fix Agent、Image Gen 模式）。startup sync 需要以 **bulk** 方式一次性获取全部 provider，效率才高。
- 本 ADR 的调用方是“用于更新 dict 的 bulk reader”，而不是“运行时单次 resolver”。两者语义不同。
- `resolve_system_api_key` **有意排除** user credentials（operator billing）。不能破坏这一语义。

### 决策 3：Invalidate Hook — `_ENV_FALLBACK.update()` (mutable dict)

比较了 3 个选项：

| 选项 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| (a) **mutable dict `.update()`** | 保持 `PROVIDER_API_KEY_MAP` alias 不变，代码改动最小，atomic update | 需要在 startup + CRUD 时显式调用 | ✅ **采用** |
| (b) callback registry | 未来 consumer 也可以 hook | 过度抽象（当前 consumer = builder helper 1 处） | ❌ 违反 Musk Step 1 |
| (c) lazy reload-on-read + TTL cache | 防止遗漏 sync 调用 | 每次调用可能产生 DB 查询成本，TTL 期间 stale，测试 hook 困难 | ❌ |

**实现形式**：
```python
# model_factory.py
def sync_env_fallback_from_credentials(
    cred_keys: dict[str, str | None]
) -> None:
    """按 Provider 执行 dict.update()。.env 优先策略：不覆盖已有 truthy 值。"""
    for provider, key in cred_keys.items():
        if key and not _ENV_FALLBACK.get(provider):
            _ENV_FALLBACK[provider] = key
```

**调用位置**：
1. `app/main.py` lifespan startup — Bootstrap 之后执行 1 次
2. `app/routers/credentials.py` — POST/PATCH/DELETE handler 中 `await db.commit()` 之后，仅当 `definition_key in {anthropic, openai, google_genai, openrouter, openai_compatible}` 时

**Thread safety**: CPython GIL + dict `.update()` atomic。禁止替换 dict 对象（`_ENV_FALLBACK = ...`），否则 `PROVIDER_API_KEY_MAP` alias 会持有 stale 引用。

### 决策 4：Provider definition_key ↔ `_ENV_FALLBACK` Key 映射

| credential definition_key | `_ENV_FALLBACK` key | 备注 |
|---------------------------|---------------------|------|
| `anthropic` | `anthropic` | 1:1 |
| `openai` | `openai` | 1:1 |
| `google_genai` | `google` | **需要别名映射** (settings.google_api_key) |
| `openrouter` | `openrouter` | 1:1 |
| `openai_compatible` | — (skip) | 必须有 base_url，无法用 env 单一密钥表达。credential 流程保持不变（chat_service 路径）。builder 不使用。 |

映射表以常量形式显式写在 `app/credentials/service.py` 中：
```python
LLM_DEFINITION_TO_ENV_KEY: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google_genai": "google",
    "openrouter": "openrouter",
}
# openai_compatible: builder/assistant 不支持 — 仅使用 Agent.llm_credential 路径
```

`is_llm_definition(key) -> bool` helper 通过上述 dict 的 key membership 判断。

---

## § 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| Credential rotation 时遗漏 sync → builder 使用 stale 密钥 | 在 3 个 CRUD 位置（POST/PATCH/DELETE）设置防止遗漏 hook 的验证 guard（M3 新增测试）。按 `definition_key` 白名单分支。 |
| System 与 user credential 冲突 | 在决策 1 中明确优先级。system 1 条 + user N 条同时存在时 system 优先。 |
| 与 a7fc92d "运行时密钥隔离" 冲突 | end-user agent (`Agent.llm_credential`) 路径**改动 0**。本 ADR 只影响 builder/assistant（operator-billed surface）。ADR-005 builder 流程原本就意图由 operator 计费。 |
| `.env` priority 违规回归 | `sync_env_fallback_from_credentials` 使用 `if key and not _ENV_FALLBACK.get(provider)` guard。新增 guard `test_env_key_takes_priority_over_credential` (M1 §5.5)。 |
| Multi-user 环境中 user credentials 的“到底使用哪个 user 密钥”存在歧义 | PoC 阶段（单一 mock user）— 暂时不是问题。引入认证时重新评估。在 ADR §未来工作中注明。 |
| 缺少 `openai_compatible` 导致用户困惑 | 在 UI 中明确 builder/assistant 支持的 provider 列表（Zuckerberg 范围，本 ADR 范围外）。 |

---

## § 迁移

**Backward Compat**:
- `.env` 中已有 `ANTHROPIC_API_KEY` 的用户：行为改动 0。`_ENV_FALLBACK["anthropic"]` 在 startup 时由 settings 值填充，sync 函数不会覆盖 truthy 值。
- 保留 `PROVIDER_API_KEY_MAP` alias → builder helper (`L73,L85`) 代码改动 0。

**新增行为**：
- `.env` 为空且在 `/credentials` UI 注册 anthropic 密钥时：
  - startup → `_ENV_FALLBACK["anthropic"] = "<credentials key>"`
  - 之后调用 builder → `PROVIDER_API_KEY_MAP.get("anthropic")` 返回新密钥

**DB 迁移**：无。schema 改动 0。

**Frontend 改动**：无。UI 已可通过 `/credentials` 注册密钥（符合 mental model）。

---

## § 未来工作（本 ADR 范围外）

1. 引入认证时 user credentials fallback 的 user 选择策略（本 ADR 假设只有单一 mock user）。
2. `openai_compatible` builder 支持 — 需要 model_name + base_url + api_key 三元组。扩展 Settings 或另立 ADR。
3. Credential rotation audit log → 记录 `_ENV_FALLBACK` sync 事件（运维可观测性）。

---

## § 决策摘要

1. **优先级**: ENV > system credential > user credential > None
2. **复用**: 新 helper `credential_service.get_provider_keys(db)` (bulk reader)。`resolve_system_api_key` 保留原语义（改动 0）。
3. **Hook**: `_ENV_FALLBACK.update()` (mutable dict) — startup 1 次 + 3 个 CRUD 位置（按 `definition_key` LLM 白名单分支）。
4. **映射**: `anthropic`, `openai` 1:1 / `google_genai → google` / `openrouter` 1:1 / `openai_compatible` skip。
5. **Backward compat**: 保留 `.env` priority。对现有用户影响为 0。
