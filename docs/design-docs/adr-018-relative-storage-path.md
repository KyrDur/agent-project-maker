# ADR-018 — Relative `storage_path` for Skills & Marketplace Versions

## 1. Status & Date

- **Status**: Proposed
- **Date**: 2026-05-23
- **Owner**: chester
- **Branch**: `worktree-adr-018-relative-storage-path`
- **Relates / Depends on**:
  - ADR-003 (Skills Memory) — 保持本 ADR 引入的 `data/skills/<id>/` layout 不变
  - ADR-017 (Marketplace Resources) — 引入 `marketplace_versions.storage_path` 的 ADR。本 ADR 仅改变该列语义
- **Supersedes**: 无

---

## 2. Context

### 2.1 事件 — 2026-05-23 数据丢失

`worktree-marketplace-resources` 工作结束并清理 worktree 目录后，发生了以下情况：

- `skills` 表 — ranian963 用户的 2 条 row（`seating-guide`, `korean-spell-check`）正文文件丢失
- `marketplace_versions` 表 — 93 条 row 的全部正文文件丢失
- DB row 的 metadata（name/description/size/hash）仍在，但 `storage_path` 指向的文件/目录随 worktree 一起被删除

调查结果：

```sql
SELECT storage_path FROM skills WHERE user_id='ranian963';
-- /Users/chester/dev/ref/natural-mold/.claude/worktrees/marketplace-resources/backend/data/skills/<id>
```

DB 中写入了 **worktree 绝对路径**。

### 2.2 根本原因 — 两个 mismatch

**原因 1 — `_storage_root()` 按 CWD 解析为绝对路径**（`app/skills/service.py:46-51`）：

```python
def _storage_root() -> Path:
    return Path(settings.skill_storage_dir).resolve()  # 依赖 CWD
```

`settings.skill_storage_dir = "./data/skills"` 虽是相对路径，但 `.resolve()` 会基于 CWD（= 启动服务器的目录）转成绝对路径。在 worktree 启动 dev server 时，写入的就是 worktree 路径。

相同模式：`publish_service._versions_storage_root()`、`k_skill_importer` 的 `builtin_storage_dir`。

**原因 2 — `scripts/worktree-setup.sh` 只 symlink `.env`，`data/` 分离**：

`.env` symlink 到 main，因此共享同一个 PostgreSQL，但 `backend/data/` 在各 worktree 中是独立目录。结果是**DB 共享、storage 分离** — worktree 中创建的 skill 正文只存在于 worktree 内，而 DB 保存的是 worktree 绝对路径。worktree 清理后只剩 dangling reference。

### 2.3 影响范围

| 对象 | 损坏 row 数 | 正常 row 数 |
|---|---|---|
| skills | 2 | 0 |
| marketplace_versions | 93 | 0 |

100% 损坏。也就是说，本项目所有 publish/install/k-skill sync 事务都发生在 worktree 中，而 main collection 为空。

### 2.4 为什么不能只在 worktree-setup.sh 中增加 `data/` symlink

只加 filesystem symlink 时，worktree 内 `backend/data` → main 被链接，文件会共享，但 DB 的 `storage_path` 仍然写入 **worktree 绝对路径**（`.claude/worktrees/.../backend/data/skills/<id>`）。删除 worktree 本身后，该绝对路径也无法再 traverse（因为 symlink 本身也消失）。

→ **两个 layer 都必须修复**：
1. DB 层 — `storage_path` 存相对路径（无论从哪里启动都以相同方式解析）
2. Filesystem 层 — 在 worktree-setup.sh 增加 `backend/data` symlink 指引（让 publish/install 写入 main data）

---

## 3. Decision

### 3.1 `storage_path` 始终以 `settings.data_root` 为基准存相对路径

- 新增 `settings.data_root: str = "./data"`（不与现有 `*_dir` 设置冲突，是 derived 概念）
- 所有保存位置在列值中只保存 **`./data` 下的相对路径**
- 禁止保存绝对路径。CI/测试用 `is_absolute()` assert 作为回归 guard

**相对路径 schema**：

| 列 | 模式 | 示例 |
|---|---|---|
| `skills.storage_path` (text) | `skills/<skill_id>/SKILL.md` | `skills/abc.../SKILL.md` |
| `skills.storage_path` (package) | `skills/<skill_id>` | `skills/abc...` |
| `marketplace_versions.storage_path` (k-skill) | `marketplace/k-skill/<version_id>` | `marketplace/k-skill/def...` |
| `marketplace_versions.storage_path` (publish) | `skills/_marketplace_versions/<version_id>` | `skills/_marketplace_versions/def...` |

保持现有 `data/skills/<id>` layout 与 `data/marketplace/k-skill/<vid>` layout 不变。只改变**列值**。

### 3.2 单一 helper `resolve_data_path(rel) -> Path`

新增 `app/storage/paths.py`：

```python
def resolve_data_path(rel: str | os.PathLike[str]) -> Path:
    """Return an absolute path for a value stored relative to ``settings.data_root``.

    - Empty/None → ValueError
    - Absolute input → returned as-is (legacy fallback; logged as deprecation)
    - Relative input → ``(settings.data_root / rel).resolve()``
    """
```

所有读取位置都通过此 helper wrap。禁止直接使用 `Path(skill.storage_path)`。

### 3.3 Alembic M44 — clean slate

经用户同意（2026-05-23）：

- `DELETE FROM marketplace_installations`
- `DELETE FROM marketplace_publication_links`
- `DELETE FROM marketplace_item_acl`
- `DELETE FROM marketplace_versions`
- `DELETE FROM marketplace_items`
- `DELETE FROM skill_credential_bindings`
- `DELETE FROM agent_skills WHERE skill_id IN (...broken skills...)`
- `DELETE FROM skills WHERE storage_path LIKE '%/worktrees/%' OR storage_path LIKE '/%'`
  （即 worktree 路径 OR 所有绝对路径 row）

同时更新列注释，把 schema 语义传达给未来 reader。

Downgrade 为 noop（数据无法恢复，也无 schema 变更）。

### 3.4 `scripts/worktree-setup.sh` — 增加 data symlink

按与 `.env` symlink 相同模式设置 `backend/data` → main `backend/data` symlink。应用 ADR-018 后 storage_path 为相对路径，但在 **filesystem 层**也让 worktree 与 main 看到相同数据，从而保证：

- 在 worktree publish 的 skill 可在 main 中立即 read
- 删除 worktree 后 main data 保持不变

---

## 4. Consequences

### 4.1 Positive

- 从 worktree 启动的服务器产生的 publish/install/k-skill sync 结果，在删除 worktree 后仍然存在
- `storage_path` 具备 deploy-portable — 将 DB dump 导入另一环境也能继续工作（只要 `data_root` 一致）
- 通过单一 helper 让读取位置统一受保护（后续增加 path traversal 等额外验证时只有一个入口）

### 4.2 Negative

- 与现有绝对路径 row backward compat：helper 对 `is_absolute()` 直接放行，但**禁止新保存**。legacy 绝对路径 row 已在 M44 删除，因此 production code path 不会看到
- 如果用户从非 main 环境启动，或错误配置 `data_root`，所有 skill 都会显示 broken — 这是预期行为（single source of truth）

### 4.3 迁移影响

- ranian963 的 2 个 skill：M44 删除 row。用户需自行重新 install/reimport
- 91 个 k-skill marketplace_versions：M44 删除 row。super_user 重新运行 `sync_k_skill`
- 2 个 user-publish marketplace_versions：M44 删除 row。原始 skill 持有者重新 publish

---

## 5. Alternatives Considered

### 5.1 仅在 worktree-setup.sh 增加 data symlink（DB schema 不变）

淘汰。见 §2.4 — 未解决 DB storage_path 写入 worktree 绝对路径的问题。

### 5.2 在 storage_path 保存 canonical path（`os.path.realpath`）

在 `_storage_root()` 中 `.resolve(strict=False)` 后再用 `os.path.realpath` 跟随 symlink → 最终 path 指向 main。淘汰原因：

- 仅在 worktree 已配置 `data` symlink 时有效。未 setup 的 worktree 仍会写入 worktree 路径
- DB 保存环境相关绝对路径 — deploy/clone 时无 portability

### 5.3 废弃列，仅用 `<id>` 重建路径

移除 `storage_path` 列本身，只使用 `data/skills/<skill_id>/` 约定。淘汰原因：

- marketplace publish snapshot 位于 `data/skills/_marketplace_versions/<vid>`，无法仅靠 skill_id 重建
- k-skill builtin 位于 `data/marketplace/k-skill/<vid>` — 路径更为多样
- 显式 path 列为未来 Phase 2/3（MCP/Agent marketplace）扩展提供灵活性

---

## 6. Implementation Plan

1. 编写 ADR（本文档）
2. 新增 `settings.data_root = "./data"`
3. `app/storage/paths.py` — `resolve_data_path()` + assert helper
4. 修改保存位置：
   - `app/skills/service.py:118, 160` (text/package skill create)
   - `app/marketplace/publish_service.py:398` (publish snapshot)
   - `app/marketplace/install_service.py:363-365` (install copy)
   - `app/marketplace/k_skill_importer.py:571` (k-skill version)
5. 修改读取位置 — 所有 `Path(skill.storage_path)` / `Path(version.storage_path)` 均经 `resolve_data_path()`
6. Alembic M44 — wipe 损坏 row + 列注释
7. 回归测试：
   - `tests/test_storage_paths.py` — helper unit
   - `tests/test_skill_service_paths.py` — text/package create 后 assert 列值为相对路径
   - `tests/test_marketplace_paths.py` — publish/install 后同样 assert
8. `scripts/worktree-setup.sh` — 增加 `backend/data` symlink
9. 更新 `CLAUDE.md` / `HANDOFF.md`
10. 验证 ruff + pytest 全部通过后提交 PR

---

## 7. Rollback

- M44 只删除数据 — 无 schema 变更。Downgrade 为 noop，因此 rollback 困难（被删除的 row 无法恢复）
- 代码修改在 helper 单点仍允许 absolute path，因此可 partial rollback（只要不运行 M44，现有绝对路径 row 仍可原样读取）
- 可按 PR 粒度 revert
