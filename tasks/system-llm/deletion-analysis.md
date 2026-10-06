# 删除分析报告 — S1 (Musk Step 2)

**编写**: 贝索斯 (QA) · 2026-05-26
**对象**: 应用 ADR-019 决策2（移除 .env fallback，DB 单一 source）时的删除/断开对象
**扫描**: 委派 Explore 子智能体 4 项（config read 路径 / functools.cache / resolve_system_api_key 调用方 / 会失败的测试）

---

## 1. config.py 模型设置值 — runtime read 路径（断开对象）

### 定义位置 (config.py)
| 属性 | 行 | 默认值 |
|------|------|-------|
| `builder_model_provider` | 105 | `"anthropic"` |
| `builder_model_name` | 106 | `"claude-sonnet-4-6"` |
| `builder_fallback_provider` | 107 | `"openai"` |
| `builder_fallback_name` | 108 | `"gpt-5.4"` |
| `assistant_model_provider` | 109 | `"anthropic"` |
| `assistant_model_name` | 110 | `"claude-sonnet-4-6"` |
| `image_gen_model` | 119 | `"google/gemini-3.1-flash-image-preview"` |

> ADR-019 决策2: **config 常量本身可继续保留用于参考 seed 默认值**。需要断开的是下方 **runtime read 路径**。

### runtime read 路径（共 18 个点，4 个文件）

**builder_model_* / builder_fallback_*** — `agent_runtime/builder/sub_agents/helpers.py`
- L71-73: `_get_builder_model()` → `create_chat_model(settings.builder_model_provider, settings.builder_model_name, api_key=PROVIDER_API_KEY_MAP.get(...))`
- L81-90: `_get_fallback_model()` → fallback==primary 比较 + `create_chat_model(settings.builder_fallback_provider, settings.builder_fallback_name, ...)`
- L138-139: 再次引用 fallback provider/name

**assistant_model_*** — `agent_runtime/assistant/assistant_agent.py`
- L74,77-78: `resolve_system_api_key(db, settings.assistant_model_provider)` + `create_chat_model(settings.assistant_model_provider, settings.assistant_model_name, ...)`

**image_gen_model** — 2 个文件
- `agent_runtime/builder_v3/image_gen.py:112`: `"model": settings.image_gen_model`
- `services/image_service.py:125`: `"model": settings.image_gen_model`

### 单独分类: base_url（ADR-019 — 从 credential payload 中提取）
`image_gen_base_url` (config.py:118) runtime read 2 处:
- `builder_v3/image_gen.py:133`: `f"{settings.image_gen_base_url}/chat/completions"`
- `services/image_service.py:119`: `f"{settings.image_gen_base_url}/chat/completions"`

→ 将这两条路径的 image role 切换为 `resolve_system_model("image")` 时，**必须替换为 credential payload 的 base_url**。（M3 接线负责人=詹森）

---

## 2. 移除 `@functools.cache` 的影响 (helpers.py)

| 函数 | 行 | 缓存 key | config read | 移除时成本 |
|------|------|--------|-------------|-------------|
| `load_prompt(filename)` | 37 | filename | 无（文件系统） | **无** — 模块 import 时 static 绑定，runtime 不会再次调用。移除也无影响 |
| `_get_builder_model()` | 68 | 无（singleton） | builder_model_provider/name + API_KEY_MAP | 创建 LLM 实例 ~5-10ms/调用（httpx+SSL） |
| `_get_fallback_model()` | 78 | 无（singleton） | builder_fallback_provider/name + API_KEY_MAP | 相同 |

**调用方**: helpers.py 内部 L176-177、L226-227（`invoke_with_json_retry`, `invoke_for_text`）。外部 sub_agents 4 种（intent_analyzer, tool_recommender, middleware_recommender, prompt_generator）通过上述 public 函数调用。

**判断**:
- 按 ADR-019 决策5，`@functools.cache` **必须移除**（以反映 runtime 设置变更）。当前 singleton cache 存在设置变更在 process 重启前都会被忽略的 bug 风险。
- 移除后两个函数都需要 **async + 添加 db 参数**（调用 resolver）→ 签名变更。调用方 L176/226 也改为 await。
- 成本缓解: 按 ADR-019 建议，推荐引入 **基于 `updated_at` 的轻量 cache**（否则每次 builder 请求都会重新创建 LLM 实例）。但这是詹森的实现判断 — 从 QA 角度标记为 "移除 cache + 缺少失效机制时会有性能回归" 风险。

---

## 3. `resolve_system_api_key` 调用方 — 保留 vs 切换到 `resolve_system_model`

`system_credential_resolver.py`: `async resolve_system_api_key(db, provider) -> str|None`（ENV→is_system credential→None，支持 api_key/token key）。**为兼容 ADR-013，函数本身保留**（决策3）。

| 调用方 | 行 | 功能 | 切换判断 |
|--------|------|------|----------|
| `assistant_agent.py` | 73-75 | assistant | **切换为 resolve_system_model("text_primary")** — provider/model_name 在 config 中是 static，因此必须断开。base_url 也需要 |
| `image_service.py` | 102 | image | **切换为 resolve_system_model("image")** ⚠️ |
| `builder_v3/image_gen.py` | 49 | image（可用性检查） | 考虑保留 — 用于 bool 检查。见下方注释 |
| `builder_v3/image_gen.py` | 96 | image（生成） | **切换为 resolve_system_model("image")** ⚠️ |

> ⚠️ **Explore #3 与贝索斯判断的差异（重要）**: Explore 得出结论 "image_gen 的 base_url/model 在 settings 中是 static，因此只需要 api_key → 保留 resolve_system_api_key"。**但 ADR-019 决策2明确将 `image_gen_model` 列为需要移除的 runtime read 对象**，且决策5表要求 image 切换为 `resolve_system_model("image")`。因此 image 也必须**从 DB(image role) 获取 model_name+base_url+api_key**才符合 ADR。`resolve_system_api_key` "保留" 属于违反 ADR。
>
> 但 `image_gen.py:49` 的 **可用性检查（`is_image_generation_available`）**是在询问 "image role 是否 configured"，因此建议改为 try/except 包裹 `resolve_system_model` 抛出的 `SystemModelNotConfiguredError`，或检查 setting 的 configured flag。仅检查 api_key 是否存在的逻辑会变得不准确。

**保留 resolve_system_api_key 的理由**: 兼容 ADR-013 其他路径（用户智能体 LLM key 优先级）。system 模型 3 个 slot（builder/assistant/image）全部迁移到 `resolve_system_model` → 最终 system 模型流程中对 `resolve_system_api_key` 的直接调用应**断开为 0 个**才正常。

---

## 4. 会失败的现有测试

| 文件 | 行 | 失败原因 | 严重度 |
|------|------|-----------|--------|
| `test_builder_v3.py` | image 全流程 | 移除 `settings.image_gen_model` fallback → 未配置时出现 runtime error（改为显式 `SystemModelNotConfiguredError`） | CRITICAL |
| `test_builder_sub_agents.py` | ~338-389 (model getter), ~351/377 (mock) | `_get_builder_model/_get_fallback_model` 改为 async+db 签名 → 同步 mock 失效，cache 依赖失效 | HIGH |
| `test_assistant_agent.py` | ~77,119,144 | `resolve_system_api_key` patch → 需要替换为 `resolve_system_model` | HIGH |
| `test_assistant_agent.py` | ~14-49（调用 cache_clear） | 移除 `@functools.cache` 后 `.cache_clear()` 方法消失 → AttributeError | MEDIUM |
| `conftest.py` | ~60-82 (`_stub_llm_credential_resolution`) | 未 patch system model resolver → builder/assistant 测试中出现 DB 未配置错误 | HIGH |

> 行号是 Explore 的估算值 — 需要詹森/实现者在实际文件中重新确认。模式（为什么会坏）可信。

### 新增所需测试（摘要）
- `tests/test_system_llm_settings.py`（新增）: role UNIQUE, CHECK 约束, credential SET NULL, CRUD
- 扩展 `test_system_credential_resolver.py`: `resolve_system_model` configured/未配置（`SystemModelNotConfiguredError`）/base_url 为 None 时 canonical pin/image role
- conftest: 添加 system model resolver stub fixture

---

## § 可立即删除
- helpers.py `_get_builder_model`/`_get_fallback_model` 的 `@functools.cache`（决策5，存在阻断 runtime 设置变更生效的 bug 风险）
- system 模型流程中的 `settings.builder_model_*`/`assistant_model_*`/`image_gen_model` **runtime read**（config 常量定义可保留供 seed 参考）

## § 需要评估删除（萨提亚/詹森确认）
- `image_gen.py:49` 可用性检查: 从 api_key 存在→configured 检查进行语义切换（不是简单删除）
- 移除 `@functools.cache` 后，**若不引入基于 updated_at 的 cache 会有性能回归** — 需要决定是否同时采用缓解措施
- `resolve_system_api_key` 函数本身: 为兼容 ADR-013 保留，但 system 模型流程中的调用方全部归为 0

## § 简化建议
- image_service.py 与 builder_v3/image_gen.py 存在重复的 base_url+model+api_key 获取逻辑 → 统一为 `resolve_system_model("image")` 单一入口
