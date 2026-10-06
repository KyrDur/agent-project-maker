# 删除分析报告 — Backlog C（删除 credentials list N+1 解密）

**Branch**：`feature/credentials-field-keys-cache`
**作者**：贝索斯（QA）
**编写日期**：2026-04-17
**Scope**：`backend/app/{services/credential_service.py, models/credential.py, routers/credentials.py, schemas/credential.py}`

---

## 可立即删除

1. **`credential_service.create_credential` 的函数内部 import（line 45, 48）**
   - 当前：`from app.config import settings` + `from app.exceptions import AppError` 位于函数体内部
   - 原因：此模块已经可以像其他 service module 一样将 `settings`/`AppError` 放到顶部。不存在循环 import 风险（其他 service/router 也在顶部 import）。也没有文档说明保留延迟 import 的理由。
   - 措施：M3 工作时由 Jensen 移到顶部。

2. **保留 `CredentialUpdate` schema 中无注释的 `data: dict[str, str] | None` 结构**
   - 并非删除，只是 M3 中 `data.data is not None` 检查仍是 sole trigger。当前 API 中不存在 `is_active` 更新路径（没有单独 toggle route），因此禁止新增与 `is_active` 相关的单独分支。

---

## 需要评估删除（需 Satya 确认）

1. **是否保留 `credential_service.extract_field_keys` 的 try/except fallback 逻辑（line 100-103）**
   - 当前：`try: list(resolve_credential_data(credential).keys()); except Exception: return []`
   - 引入 cache 列后：如果假设 cache hit 为 100%，try/except 会沦为 dead path。但 ADR-007 明确 "legacy row fallback" + 要求容忍 backfill 失败（tolerant）→ **必须保留**。
   - 风险：删除 fallback 后，在未设置 ENCRYPTION_KEY 的 migration 环境 + 现有 row 组合下可能出现 500 error。
   - 建议：**不要删除。** M3 实现中优先走 `credential.field_keys is not None` 分支 + 现有 try/except 路径保持原样。

2. **`credentials.is_active` 列（models/credential.py:26）+ response schema 的 `is_active` 字段（schemas/credential.py:26, routers/credentials.py:30）**
   - 当前：创建时默认 True，没有修改/toggle API。Query filter 中也未使用（`list_credentials` 没有 `is_active` filter）。
   - **状态：实质性的 dead column** — 始终返回 True。只暴露在 response/UI 中。
   - 风险：超出本次 Backlog C scope。停用功能可能需要作为单独 feature 设计（soft delete policy）。
   - 建议：**本 PR 不要动。** 在 Backlog D/E 中作为单独项目处理。本 scope 外变更 = drive-by refactoring。

3. **`CredentialResponse.has_data` 字段（schemas/credential.py:27, routers/credentials.py:31）**
   - 当前：`bool(cred.data_encrypted)` — credential 创建后始终为 True（create_credential 没有不带 `data_encrypted` 创建 row 的路径）。结构上始终为 True 的 field。
   - 风险：Client 可能像 `hasOwnProperty` 一样使用此字段。需要全面调查 frontend。
   - 建议：**本 PR 保留。** 删除应在确认 frontend 后通过单独 PR 处理。

---

## 简化建议

1. **`extract_field_keys` cache + fallback 分支形式**
   - 当前（计划）：`if credential.field_keys is not None: return credential.field_keys` + try/except fallback
   - 建议：M3 实现时保持 **early return 模式**（与 plan 建议相同）。虽有 2 条路径，但优先可读性 — 禁止嵌套 try/except。
   - 依据：两条路径语义不同（cache hit vs legacy 解密）→ 不要合并。尊重 ADR-007 的 "保留 2 条路径 — 维护负担低" 决定。

2. **`create_credential` 的 ENCRYPTION_KEY guard + AppError**
   - 当前：503 返回路径只存在于 `create_credential` 内部。
   - 建议：**禁止更改。** M2 migration 是 "ENCRYPTION_KEY 未设置时 skip + 警告 log"（CHECKPOINT M2 明确）— create 与 migration 属于不同层级 policy。拒绝为了对齐而修改。

3. **测试文件位置**
   - 当前：credential 相关 coverage 分散在 `test_tools.py`（line 513 等）中。
   - 建议：M4 新建 `test_credentials.py` 时，credential-only scenario 全部放入新文件。现有 `test_tools.py` 的 `resolve_credential_data` patch 模式（513-534）**不要重复复制**，只作参考 — 不要改现有测试（从回归角度）。

4. **`_to_response` 的 `extract_field_keys(cred)` 调用路径**
   - 当前：每次遍历都调用 → 引入 cache 后每次遍历都读取属性。
   - 建议：**无需额外简化。** `_to_response` 保持 pure mapper。list comprehension 的 Python 调用成本相对 Fernet 可忽略，因此禁止额外 vectorization。

---

## 贝索斯意见（结论）

- **本 PR 中实际要 "删除" 的项目：0 个**
- **简化调整：1 个**（create_credential 函数内部 import → 移至顶部，由 Jensen 在 M3 处理）
- **暂缓：3 个**（is_active, has_data, fallback try/except）— 超出 scope 或属于有意保留对象

"Good enough 并不存在"，但**也不能越界。** Backlog C 的目标是删除 N+1 解密 — credential model/schema 的其他问题应拆到各自 ticket。Minimal Impact 原则。
