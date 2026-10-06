# Backlog C — 移除 credentials list N+1 解密

**状态**：已完成 — 2026-09-08 对照源码后从 active 列表移至归档。
当前实现参考 `backend/app/credentials/service.py` 的 field_keys cache 和
`backend/app/models/credential.py`。以下 Fernet 与 legacy service
路径是引入当时的记录；当前加密已是 ADR-009 的 Cipher V2。

## Context

`GET /api/credentials` 会逐个对每个 credential row 的 `data_encrypted` 值执行 Fernet 解密 + JSON 解析，以提取 `field_keys` 数组。DB 查询只有 1 次，但 Fernet 解密发生 N 次，形成 **N+1 解密**结构。

- `credential_service.extract_field_keys()` (credential_service.py:98-103) → `resolve_credential_data()` → 调用 `decrypt_api_key()`
- router `_to_response()` 遍历 list 结果，对每个 row 调用一次（routers/credentials.py:32）
- 以 100 个 credential 估算，响应延迟约 1-2 秒，CPU O(n) Fernet 运算

目标：新增 `credentials.field_keys` 非加密 cache 列，使 list 时无需解密即可返回 field key 列表。response schema 不变（cache 为内部优化）。

**安全审查：** cache **仅保存 key 名称**（例如 `["api_key"]`, `["client_id","client_secret"]`）。值仍以 Fernet 保存在 `data_encrypted` 中。由于 key 名已经暴露在 API response 中，因此不会降低机密性。

---

## 变更范围

### 1. 模型 — `backend/app/models/credential.py`

在 `data_encrypted` 后新增 cache 列：

```python
from sqlalchemy import JSON

field_keys: Mapped[list[str]] = mapped_column(
    JSON, nullable=True, default=list
)
```

- `sa.JSON()` 在 PostgreSQL 映射为 JSONB，也兼容 SQLite（aiosqlite 测试）
- 设为 `nullable=True` 以处理 legacy row（backfill + runtime fallback 并行）

### 2. Service — `backend/app/services/credential_service.py`

#### `create_credential()` (42-66)
紧接 line 55：
```python
encrypted = encrypt_api_key(json.dumps(data.data))
cred = Credential(
    user_id=user_id,
    name=data.name,
    credential_type=data.credential_type,
    provider_name=data.provider_name,
    data_encrypted=encrypted,
    field_keys=list(data.data.keys()),   # ← 新增
)
```

#### `update_credential()` (69-82)
在 `data.data is not None` 分支中同步：
```python
if data.data is not None:
    cred.data_encrypted = encrypt_api_key(json.dumps(data.data))
    cred.field_keys = list(data.data.keys())   # ← 新增
```
- 仅修改 `name` 时不要触碰 `field_keys`

#### `extract_field_keys()` (98-103) — cache 优先 + lazy fallback
```python
def extract_field_keys(credential: Credential) -> list[str]:
    """Return cached field_keys; fall back to decryption for legacy rows."""
    if credential.field_keys is not None:
        return credential.field_keys
    try:
        return list(resolve_credential_data(credential).keys())
    except Exception:
        return []
```
- cache hit → 解密 0 次
- Legacy row（backfill 之前）→ fallback 到现有路径
- router `_to_response()` 无需变更

### 3. Alembic migration — 新文件

`backend/alembic/versions/{NEW}_add_credential_field_keys_cache.py`

- `revision`：新 ID（例如 `m7_add_credential_field_keys`）
- `down_revision = "m6_add_credentials"`（当前 head，已确认）
- `upgrade()`:
  1. `op.add_column("credentials", sa.Column("field_keys", sa.JSON(), nullable=True))`
  2. **Data migration**：backfill 现有 row
     - 用 `bind = op.get_bind()` SELECT `id, data_encrypted` from credentials
     - 对每个 row 调用 `app.services.encryption.decrypt_api_key` + `json.loads` 后提取 `.keys()`
     - `UPDATE credentials SET field_keys = :keys WHERE id = :id`
     - 解密失败时 `[]`（tolerant）
     - 未设置 ENCRYPTION_KEY 时 skip（warning log）
- `downgrade()`: `op.drop_column("credentials", "field_keys")`

### 4. 测试 — 新增 `backend/tests/test_credentials.py`

此前没有 `test_credentials*.py`（credential coverage 分散在 `test_tools.py`）。趁此新增 credential 专用测试文件：

- `test_create_credential_populates_field_keys` — POST 后 DB row 的 `field_keys == list(data.keys())`
- `test_update_credential_syncs_field_keys` — PATCH data 变更时更新 `field_keys`
- `test_update_credential_name_only_preserves_field_keys` — 仅修改 `name` 时 `field_keys` 不变
- `test_list_credentials_returns_cached_field_keys_without_decrypt` — 用 `unittest.mock` patch `decrypt_api_key`，验证 list 调用过程中调用次数为 0
- `test_extract_field_keys_fallback_for_legacy_row` — 直接插入 `field_keys=None` 的 row，确认 `extract_field_keys` 走解密路径

使用 aiosqlite in-memory。参考现有 `test_tools.py` 的 `_make_credential` helper 模式。

---

## 参考文件

| 路径 | 作用 |
|------|------|
| `backend/app/models/credential.py` | 新增列 |
| `backend/app/services/credential_service.py` | 修改 create/update/extract |
| `backend/app/routers/credentials.py` | 无变更（仅确认） |
| `backend/app/schemas/credential.py` | 无变更（`field_keys` 字段保持不变） |
| `backend/app/services/encryption.py` | 复用 `decrypt_api_key`（migration + fallback） |
| `backend/alembic/versions/m6_add_credentials.py` | 新 migration 的 down_revision |
| `backend/tests/test_tools.py` | 参考 `_make_credential` helper 模式 |
| `backend/tests/test_encryption.py` | 加密 round-trip 示例 |

---

## 可复用的现有 utility

- `app.services.encryption.encrypt_api_key / decrypt_api_key` — 现有 Fernet wrapper（原样使用）
- `app.services.credential_service.resolve_credential_data` — 在 fallback 路径原样复用
- `sa.JSON()` — 已在 `agent_tools.config`, `models.input_modalities`, `builder_sessions.*` 中使用的项目惯例

---

## 验证

```bash
# Backend
cd backend

# 1. 应用 migration
uv run alembic upgrade head
uv run alembic downgrade -1 && uv run alembic upgrade head   # up/down 往返

# 2. lint
uv run ruff check app/services/credential_service.py app/models/credential.py tests/test_credentials.py

# 3. 测试
uv run pytest tests/test_credentials.py -v     # 新测试
uv run pytest tests/test_tools.py -v           # 回归（credential 联动）
uv run pytest tests/test_encryption.py -v      # 回归
uv run pytest                                  # 全部 540+ 测试

# 4. runtime 验证（手动）
docker-compose up -d postgres
uv run uvicorn app.main:app --reload --port 8001
# POST /api/credentials → 创建
# GET  /api/credentials → 确认 field_keys 值一致
# PATCH /api/credentials/{id} name 变更 → 确认 field_keys 不变
# PATCH /api/credentials/{id} data 变更 → 确认 field_keys 更新
```

**完成标准（done-when）：**
- 新 migration up/down 双向成功
- list/create/update 场景 response schema 相同（diff 0）
- `test_list_credentials_returns_cached_field_keys_without_decrypt` 中 `decrypt_api_key` 调用次数为 0
- `pytest` 全绿，`ruff` clean
- Legacy row（backfill skip 的情况）fallback 路径正常工作

---

## 范围外（本 PR 排除）

- 无关性能优化（Backlog D `lazy="joined"` → `selectinload` 等）
- 更改基于 `credentials.is_active` 的过滤
- 更改 masking sentinel 逻辑
