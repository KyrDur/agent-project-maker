# ADR-007：Credentials `field_keys` 非加密缓存列

## 状态：已批准

## 日期：2026-04-17

## 背景

`GET /api/credentials` 会对每个 credential 使用 Fernet 解密 `data_encrypted` 并解析 JSON，将 `field_keys` 列表（仅键名）包含在响应中。当前 `credential_service.extract_field_keys()` → `resolve_credential_data()` → `decrypt_api_key()` 路径会在遍历 list 结果时被调用，从而产生 **N+1 解密**。DB 查询只有 1 次，但 Fernet 运算会按 row 数重复。

- 以 100 个 credential 估算响应延迟：约 ~1–2 秒（CPU bound）
- 解密成本随 credential 数量线性增长

## 决定

在 `credentials` 表新增 `field_keys` 列：

- 类型：`sa.JSON()`（PostgreSQL JSONB 映射，兼容 SQLite aiosqlite）
- nullable=True（用于 legacy row backfill 前兼容）
- 保存内容：**仅键名列表**（例如 `["api_key"]`、`["client_id", "client_secret"]`）— 值仍以 Fernet 加密方式保存在 `data_encrypted` 中

当 `create_credential` / `update_credential` 的 data 变更时同步缓存。`extract_field_keys()` 优先使用缓存，若为 NULL 则 fallback 到现有解密路径。

Alembic migration（`m7_add_credential_field_keys`）的 `upgrade()` 会对现有 row 执行一次性 backfill（未设置 ENCRYPTION_KEY 时跳过）。

## 替代方案

- **A. Runtime lazy write-through**：只新增列，read 路径中 NULL → 解密 → 保存。简单，但 read 会产生 write 副作用，需要注意并发。
- **B. Runtime lazy fallback only**：migration 不 backfill，保持 NULL，仅在创建/更新时缓存。现有 row 将永远只走 fallback 路径（性能改善不完整）。
- **C. 单独表 `credential_meta`**：拆分 metadata。结构过度 — 此场景无必要。
- **D. 从响应 schema 中移除 `field_keys`**：会破坏客户端兼容性。UI 正通过该列表构建 form UI，因此否决。

## 结果

### 正面影响

- List API 响应时解密 0 次（cache hit 时）
- 响应 schema 不变 → 客户端无需修改
- Legacy row 可通过 fallback 路径逐步迁移（提供与 A 同等的安全兜底）

### 负面影响

- `credentials` 表新增 1 列（影响很小）
- 保留 2 条路径（cache/fallback）— 但 fallback 复用相同逻辑，维护负担较低

### 安全

- `field_keys` **只保存键名**，不保存值。
- 现有 API 响应本就会暴露键名，因此不会降低机密性。
- `data_encrypted` 继续保持 Fernet 加密。

## 相关文档

- 计划：`~/.claude/plans/c-credentials-list-glistening-kurzweil.md`
- 已完成执行记录：`docs/exec-plans/completed/backlog-c-field-keys-cache.md`
- 之前的 ADR：ADR-005（Builder/Assistant）、ADR-003（skill+memory）
