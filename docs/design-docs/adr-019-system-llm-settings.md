# ADR-019: System LLM Settings（按角色选择模型 + 注入 base_url）

- **状态**: 已提议 (2026-05-26)
- **DRI**: chester
- **相关**: ADR-005 (Builder/Assistant), ADR-013 (Service LLM Key from Credentials), ADR-014 (Chat Model Factory)
- **范围**: `app/models/system_llm_setting.py`（新增）, `app/services/system_credential_resolver.py`, `app/agent_runtime/assistant/assistant_agent.py`, `app/agent_runtime/builder/sub_agents/helpers.py`, `app/services/image_service.py`, `app/agent_runtime/builder_v3/image_gen.py`, `app/routers/system_llm_settings.py`（新增）, `frontend/src/app/.../system-llm`（新增）

---

## § 背景

System 功能（Builder、Assistant、图像生成）调用的 LLM 模型目前**硬编码在 `.env`（`config.py:104-119`）中**：

```python
builder_model_provider: str = "anthropic"
builder_model_name: str = "claude-sonnet-4-6"
builder_fallback_provider: str = "openai"
builder_fallback_name: str = "gpt-5.4"
assistant_model_provider: str = "anthropic"
assistant_model_name: str = "claude-sonnet-4-6"
image_gen_base_url: str = "https://openrouter.ai/api/v1"
image_gen_model: str = "google/gemini-3.1-flash-image-preview"
```

这带来两个限制：

1. **operator 无法在 UI 中切换 system 模型** — 需要修改 `.env` + 重启。
2. **没有 base_url 注入路径** — `resolve_system_api_key()` 只返回 api_key（`system_credential_resolver.py:34`），Builder/Assistant 调用 `create_chat_model()` 时不传 base_url（`assistant_agent.py:76`）。因此 **system 功能无法走 LiteLLM proxy 等 self-hosted OpenAI-compatible endpoint。**

普通用户 agent 已经通过 `Model.base_url` 列支持 openai_compatible/LiteLLM（`conversations.py:104`）。只剩 System 流程有缺口。

**需求**：operator 必须能在一个页面中选择文本 primary / 文本 fallback / 图像 3 个槽位的模型，每个槽位都可指定 openai / anthropic / openrouter / litellm(openai_compatible) 任一 provider。

---

## § 决策

### 决策 1：新建 `system_llm_settings` 表（保存按 role 的模型选择）

System 模型选择具有**单例性质**（一个 operator 组织 = 一组槽位），因此建立以 role 为 key 的表。

| 列 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `role` | str(40) UNIQUE | `text_primary` / `text_fallback` / `image` |
| `credential_id` | UUID FK → credentials(id) ON DELETE SET NULL, nullable | 选中的 System Credential。provider/key/base_url 的来源 |
| `model_name` | str(200), nullable | 通过 discover 获取的模型标识符 |
| `updated_at` | datetime | |

- 不设 `user_id` 列 — system 全局设置。（RLS/多租户为后续课题）
- `credential_id` **必须是 `is_system=True` credential**（router 中验证）。
- provider 不单独保存，而是**从 credential 的 `definition_key` 派生** → 单一事实来源。

### 决策 2：移除 `.env` fallback — DB 作为单一 source

`builder_model_*`, `assistant_model_*`, `image_gen_model` 不再在运行时读取。（config 常量仅保留用于 seed 默认值参考）

- **启动 seed**：确保 `system_llm_settings` 中存在 3 个 role row，均为 `credential_id=NULL, model_name=NULL`（idempotent）。不强行填默认值 — 由 operator 在页面选择。
- **未配置时行为**：若某 role 的 `credential_id` 或 `model_name` 为 NULL，则调用对应 system 功能时抛出 `SystemModelNotConfiguredError(role)` → 向用户显示“operator 必须完成 System LLM 设置”。（不再静默 `.env` fallback — 不隐藏配置缺失）

### 决策 3：扩展 resolver — `resolve_system_model(role)`

为兼容 ADR-013，保留 `resolve_system_api_key(provider)`，并新增函数：

```python
async def resolve_system_model(
    db: AsyncSession, role: str
) -> ResolvedSystemModel:  # (provider, model_name, api_key, base_url)
    setting = await _get_setting(db, role)
    if setting is None or setting.credential_id is None or not setting.model_name:
        raise SystemModelNotConfiguredError(role)
    cred = await credential_service.get_system(db, setting.credential_id)
    payload = await credential_service.decrypt_with_external(cred.data_encrypted)
    return ResolvedSystemModel(
        provider=cred.definition_key,                      # anthropic|openai|openrouter|openai_compatible
        model_name=setting.model_name,
        api_key=payload.get("api_key") or payload.get("token"),
        base_url=payload.get("base_url"),                  # openai_compatible/openrouter → 值，其他为 None
    )
```

- 若 `base_url` 为 None，`model_factory._apply_openai_compatible_base_url` 会 pin canonical endpoint（openai/openrouter）。openai_compatible 的 credential 中 base_url 必填（definition 中 `required=True`）。

### 决策 4：credential 注册沿用现有页面，新页面只负责“选择”

- **权限**：System LLM 设置的所有 API endpoint 都由 `Depends(require_super_user)` 保护，前端页面也只在 operator 菜单中显示（与 System Credentials 相同权限模型）。普通用户看不到菜单·route·API。
- credential CRUD 保留现有 System Credentials 页面（`/settings/system-credentials`）。
- 新增 **System LLM 设置页面**：3 个槽位。每个槽位：
  1. 选择 System Credential（dropdown，仅 `is_system=True` 的 LLM credential）
  2. 通过 `POST /api/credentials/{id}/discover-models` 加载模型列表（复用现有 API）
  3. 选择模型 → 保存到 `system_llm_settings`

### 决策 5：接线 — 用 resolver 替换 config 调用点

| 调用点 | 修改 |
|--------|------|
| `assistant_agent.py:build_assistant_agent` | `resolve_system_model("text_primary")` → `create_chat_model(provider, model_name, api_key, base_url)` |
| `builder/sub_agents/helpers.py:_get_builder_model` | `text_primary` |
| `builder/sub_agents/helpers.py:_get_fallback_model` | `text_fallback` |
| `image_service.py` / `builder_v3/image_gen.py` | `resolve_system_model("image")` → 使用 base_url + model_name |

- 移除 `_get_builder_model`/`_get_fallback_model` 的 `@functools.cache`（设置可在运行时改变）。如需缓存，则基于设置 `updated_at` 失效。

---

## § DB 迁移

Alembic **M45** — 创建 `system_llm_settings` 表 + seed 3 个 role row（credential 为 NULL）。downgrade 为 drop table。

`CHECK (role IN ('text_primary','text_fallback','image'))` + `UNIQUE(role)`.

---

## § 影响 / 风险

- **Breaking**：合并后，在 operator 于 System LLM 设置页面选择 3 个槽位前，Builder/Assistant/图像生成均无法工作（移除 .env fallback 的预期行为）。发布说明中明确“需要 operator 配置”。
- **移除 cache** 后 builder 模型实例可能每次调用都重新创建 → 可用基于 `updated_at` 的轻量 cache 缓解。
- 删除 credential 时 `SET NULL` → 对应槽位进入未配置状态，下次调用时给出明确错误。

## § 替代方案（拒绝）

- **A. 保留 .env fallback** — 用户明确拒绝。不希望配置缺失被静默隐藏。
- **B. provider 单独存入表** — 会与 credential.definition_key 形成双重事实来源，存在不一致风险。拒绝。
- **C. 将 credential 注册整合到新页面** — 页面变重，并与现有 System Credentials 页面职责重叠。拒绝（决策 4）。
