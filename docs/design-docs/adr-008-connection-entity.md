# ADR-008：Connection 实体 — 统一 Credential 绑定

## 状态：废弃并由后续文档继承（Superseded by ADR-009）

2026-09-08 整理：以下为当时的设计记录。当前结构是
[ADR-009](adr-009-greenfield-credentials.md) 的 Credential 直连方式，
本文档并未批准重新引入 Connection 实体。

## 日期：2026-04-18

## 背景

当前工具（Tool）-credential（Credential）绑定在不同类型下的位置和语义不一致，并且 PREBUILT system tool 无法做到按用户隔离。

### 问题 1 — PREBUILT 共享 row 的 credential 混用

system tool（`is_system=True`）是 `user_id=NULL` 的共享 row。如果把用户 A 的 credential 写入 `tool.credential_id`，用户 B 查询或执行同一工具时，就可能看到或使用 A 的 credential。当前 PoC 阶段只有 1 个 mock user，因此问题未暴露，但一旦引入 multi-user auth，就会转化为 **production incident**。

### 问题 2 — 绑定位置不一致

| 类型 | credential 绑定位置 |
|------|----------------------|
| MCP | `mcp_servers.credential_id`（server 级） |
| CUSTOM | `tool.credential_id`（tool 级） |
| PREBUILT | `tool.credential_id`（共享 row 级 — 问题 1） |

从用户视角看，要确认“我的 key 绑定到这个工具的哪里”，需要查看三个位置；解析逻辑也在 `chat_service.build_tools_config` 中分为 3 个分支。前端 dialog（`prebuilt-auth-dialog`、`custom-auth-dialog`、`mcp-server-auth-dialog`）有 90% 相同，却因为保存路径不同而拆成 3 个（backlog F）。

### 问题 3 — 解析路径重复且 override 语义不清

目前存在将 `agent_tools.config` JSON 与工具 `auth_config` shallow merge 的惯例，同时 `credential_id` 与 inline `auth_config` fallback 并存，优先级模糊。env var fallback（`settings.naver_*`）也混在路径中，难以追踪“为什么使用了这个 key”。

---

## 决定

新增 `connections` 实体，在**用户×工具类型×provider**层级统一 credential 绑定。Tool 负责“调用什么（定义）”，Connection 负责“谁用哪个 key 调用（绑定）”，实现关注点分离。

### 1. Schema

```sql
connections
  id               UUID  PK
  user_id          UUID  FK users      NOT NULL                 -- 权限隔离基础
  type             VARCHAR(20)  NOT NULL                        -- 'prebuilt' | 'mcp' | 'custom'
  provider_name    VARCHAR(50)  NOT NULL                        -- PREBUILT: credential_registry enum 5 类
                                                                -- MCP/CUSTOM: 自由字符串
  display_name     VARCHAR(200) NOT NULL                        -- UI label（允许重复）
  credential_id    UUID  FK credentials (nullable, ON DELETE SET NULL)
  extra_config     JSON  nullable                               -- 仅 MCP 使用（结构如下）
  is_default       BOOLEAN NOT NULL DEFAULT false               -- 每个 (user_id, type, provider_name) 1 个
  status           VARCHAR(20)  NOT NULL DEFAULT 'active'       -- 'active' | 'disabled'
  created_at       TIMESTAMP NOT NULL
  updated_at       TIMESTAMP NOT NULL

  INDEX (user_id, type, provider_name)                          -- hot path：解析工具时查询
```

- **整行无 UNIQUE 约束**。UUID PK 保证唯一性，并允许同一 provider 下存在“公司用/个人用”等 display_name 相同或相近的多个 connection（行业标准：GitHub, Slack）。
- **partial unique index** `uq_connections_one_default_per_scope` — `(user_id, type, provider_name)` WHERE `is_default = true`。在 DB 层强制“每个 scope 最多 1 个 default”的不变量。应用层 count+clear+insert 模式在并发请求下可能发生 race，因此 DB 作为最终安全网（Codex adversarial Finding 2）。service 捕获 `IntegrityError` 并转换为 409。
- `provider_name` validator 在 Python/Pydantic 层根据 type 分支：
  - `type='prebuilt'`：仅允许 `credential_registry` enum（`naver`, `google_search`, `google_workspace`, `google_chat`, `custom_api_key`）
  - `type='mcp'` / `type='custom'`：自由字符串（英文/数字/下划线，长度限制）

### 2. `extra_config` 结构

**仅 MCP 使用**。PREBUILT/CUSTOM 必须为 NULL（在 service/schema 层强制，防止明文 secret channel）。

Pydantic 模型 `ConnectionExtraConfig`（`extra="forbid"`）：

```json
{
  "url": "https://example.com/mcp",
  "auth_type": "none | bearer | api_key | oauth2 | basic",
  "headers": { "X-Custom": "value" },
  "env_vars": { "RESEND_API_KEY": "${credential.api_key}" },
  "transport": "http | stdio",
  "timeout": 30
}
```

- `url`、`auth_type` 为必填。
- `headers`、`env_vars`、`transport`、`timeout` 为可选。
- **`env_vars` 的值必须只允许 `${credential.<field_name>}` 模板**。明文字符串返回 422。secret 必须保存在 credential 中，env_vars 只能引用 — API 响应也会以 Pydantic 模型形式 echo，因此不存在通过 connection CRUD 响应泄露明文 secret 的通道（Codex adversarial Finding 3）。
- **模板解析逻辑的实际实现放在 M2 MCP 执行路径中**（runtime 时解密 credential 后替换）。
- 通过 `extra="forbid"` 拒绝未知 key → 新增字段必须伴随 schema 变更，从而阻断隐藏通道。

### 3. 各工具类型解析逻辑

```python
# chat_service.build_tools_config（新路径）

if tool.type == PREBUILT:
    conn = get_connection(user_id, type='prebuilt', provider_name=tool.provider_name, is_default=True)
    cred_auth = resolve_credential_data(conn.credential) if conn and conn.credential else {}
    # 无 env fallback（参见决策 4）

elif tool.type == MCP:
    conn = get_connection_by_id(tool.connection_id)  # tool.connection_id（M2 新增 FK）
    cred_auth = resolve_credential_data(conn.credential)
    mcp_url = conn.extra_config['url']
    mcp_auth_type = conn.extra_config['auth_type']
    # headers、env_vars 等在 MCP 执行路径中处理

elif tool.type == CUSTOM:
    conn = get_connection_by_id(tool.connection_id)  # tool.connection_id（M4 新增 FK）
    cred_auth = resolve_credential_data(conn.credential)

# 若存在 agent_tools.connection_id（override），则使用该 connection
if link.connection_id is not None:
    conn = get_connection_by_id(link.connection_id)
    cred_auth = resolve_credential_data(conn.credential) if conn.credential else cred_auth
```

- `agent_tools.connection_id`（nullable FK）：当某个 agent 想使用不同于默认的 connection 时进行 override。
- `agent_tools.config`（现有 JSON）在 M6 中 drop。

### 4. env fallback 策略

**用户工具执行路径移除 env fallback**。解析 credential 时不再读取 `settings.naver_*` 等。

**依据**：
- env key 无法归属到个人，无法进行审计/成本分摊
- 会“神奇地工作”，但移除 env 后突然损坏，形成隐藏 bug
- 即使引入 multi-user auth 后仍把 env 作为所有用户的隐式默认值，也违反安全原则

**例外 — system 内部功能**：
- `creation_agent`（对话式 agent 创建 meta agent）
- agent card 图片生成
- 其他不归属于具体用户的 system 任务

这些功能不使用 connection 概念，继续保留直接读取 env 的现有路径。`config.py` 中的 `settings.openai_api_key` 等继续用于 LLM system 调用。

**M3 迁移策略**：当前 seed 的 system tool（`is_system=True`）依赖 env 运行，因此 M3 migration 时会针对 mock user 自动将 env 值复制为 credential，并把该 credential 连接为 default connection。若无 env 值，则不创建 connection，并显示为“未连接”。在不破坏现有 UX 的情况下完成迁移。

### 5. `is_default` 语义

- 用户为某 provider 创建第一个 connection 时自动 `is_default=True`
- UI 中将其他 connection 提升为 default 时，现有 default 自动变为 `is_default=False`（trigger 或 service 层原子处理）
- `agent_tools.connection_id = NULL` → 使用该 provider 的 default connection
- `agent_tools.connection_id = <uuid>` → override

### 6. 迁移策略

| 阶段 | Alembic | 作用 |
|------|---------|------|
| M1 | `m8_add_connections` | 创建表 + index（尚无人引用） |
| M2 | `m9_migrate_mcp_to_connections` | 每个 `mcp_servers` row → `connections`（type='mcp'，将 url/auth_type 迁入 extra_config）+ 新增 `tools.connection_id` 列 + 基于 `tools.mcp_server_id` 映射 |
| M3 | `m10_seed_prebuilt_connections` | 对 mock user 将 env 值 → credential → 自动创建 default connection。没有 env 的 provider 跳过 |
| M4 | `m11_migrate_custom_credentials` | 现有带 `tool.credential_id` 的 CUSTOM 工具 → 1 credential = 1 connection，多个工具以 N:1 共享 |
| M6 | `m12_drop_legacy_columns` | `mcp_servers` drop, `tools.credential_id` drop, `tools.auth_config` drop, `tools.mcp_server_id` drop, `agent_tools.config` drop |

- **M2~M5 期间**：legacy 列保留为 read-only（仅将代码路径切换到 connection）。可按 milestone 随时 rollback。
- **Alembic downgrade**：所有 migration 必须实现 `downgrade()`。CI 中验证 `upgrade → downgrade → upgrade` 往返。

---

## 替代方案

### 方案 A — 仅在 `agent_tools` 层绑定（无 Connection）

给 `agent_tools` 增加 `credential_id`、`mcp_config` 等，在每个 agent-tool 组合上直接绑定 credential。

**否决理由**：
- 同一用户如果 5 个 agent 都使用 Naver 搜索，就要重复指定 credential 5 次（不可复用）
- 没有按 provider 的“我的默认 key”概念，UX 繁琐
- MCP server 配置（URL、header）也会在每个 agent_tools 中重复保存

### 方案 B — 给 `tool.credential_id` 增加 user_id

给 `tool` 表新增 `user_id` 列，将共享 row 拆为按用户的 row。

**否决理由**：
- system seed tool 会按用户数复制（N 倍 row inflation）
- 工具定义（说明、schema）与用户绑定混在一起 — 关注点分离失败
- seed 更新时需要更新所有用户 row

### 方案 C — MCP 保留 `mcp_servers`，仅 PREBUILT 引入 Connection

MCP 已经有 server 级结构，因此保持不变，只将有问题的 PREBUILT 共享 row 拆到 connection。

**否决理由**：
- 绑定位置不一致问题（问题 2）未解决 — 仍需查看 3 个位置
- 前端 dialog 重复（F）未解决
- 长期来看 auth/state/override 逻辑需要在两张表重复维护

### 方案 D — 给 `credentials` 增加 `user_id + provider_name`，不使用 Connection

扩展 credential 本身，使其同时包含 provider 绑定。

**否决理由**：
- credential = secret，connection = 绑定 metadata，两者关注点分离被破坏
- 同一 API key 若以“公司用/个人用”等不同 display_name 使用，会通过重复创建 credential 解决 → secret 重复保存，轮换时有遗漏风险
- MCP URL/headers 等 non-secret 配置也必须混入 credential 表

---

## 结果

### 正面影响

- **按用户隔离 credential**：彻底解决 PREBUILT 共享 row 问题，引入 multi-user auth 后可立即安全使用
- **单一绑定路径**：解析工具时始终经过 connection，简化 `build_tools_config` 逻辑
- **统一 UI**：3 个 auth dialog → 1 个 `ConnectionBindingDialog` + context prop（吸收 backlog F）
- **按 Agent override**：power user 可为不同 agent 使用不同 credential
- **Credential 复用**：同一 API key 可由多个 CUSTOM 工具共享（N:1）
- **状态管理**：可在 connection 层实现 `is_default`、`status='disabled'` 等 on/off

### 负面影响

- **新增 1 张表 + 中间层**：tool → connection → credential 增加 1 层间接关系
- **migration 复杂度**：M2~M5 跨度较长，legacy 与新路径在各 milestone 共存
- **前后端类型同步负担**：每个 milestone 都必须更新 `lib/types/index.ts`

### 安全

- 因 `connections.user_id` 为 NOT NULL，API route 必须用 `get_current_user().id` 过滤。即使 PoC 阶段也要包含 IDOR regression test
- credential 本身继续使用现有 Fernet 加密（`data_encrypted`）。connection 不保存 secret 值
- 移除 env var 路径，阻断“无法审计的隐式 key 使用”
- `extra_config.env_vars` 模板引用（`${credential.xxx}`）只在服务端解析，客户端响应中不会暴露真实 secret

### 性能

- 通过 `INDEX (user_id, type, provider_name)` 使 hot path 查询为 O(log n)
- 解析工具时增加 1 层 join（tool → connection → credential）— 使用 SQLAlchemy `selectinload` 防止 N+1
- 修改 `is_default` 时在同一 (user_id, type, provider_name) scope 内执行 2 次 UPDATE — service 层 transaction

### Migration 风险

- M2 `mcp_servers → connections` 迁移期间数据遗漏：`upgrade()` 后做 row count assertion
- M3 env → credential 自动复制时若未设置 ENCRYPTION_KEY，则 skip + 明确 warning（遵循 ADR-007 模式）
- M6 drop legacy 时，如果仍有代码引用 legacy 路径会产生 runtime error — M5 完成时进行全量 grep 检查

---

## 测试场景

### M1（新增 `tests/test_connections.py`，8 个场景）

1. **CRUD 基础**：创建 / 查询 / 修改 / 删除（同时覆盖 credential 已连接 + NULL）
2. **MCP validator**：`type='mcp'` 但缺少 `extra_config.url` 时返回 422
3. **PREBUILT validator**：`type='prebuilt'` 且 `provider_name='foo'` 等 non-enum 值时返回 422
4. **is_default 自动设置**：创建第一个 connection 时自动 `is_default=True`
5. **is_default toggle 原子性**：已有 default 时将其他 connection 提升为 default，原 default 自动取消
6. **防止 IDOR**：user_A 尝试 GET/PATCH/DELETE user_B 的 connection 时返回 404
7. **credential ON DELETE SET NULL**：删除 credential 后 connection.credential_id 变为 NULL，connection 仍存在
8. **extra_config 类型不匹配**：给 PREBUILT 传 `extra_config={...}` 时 warning 或忽略（由 validator 决定）

### M2（MCP → Connection 迁移）

1. **确认现有 `mcp_servers` row 全部迁移到 `connections` 表**（row count + sample 对比）
2. **确认 tools.connection_id 基于现有 tools.mcp_server_id 正确映射**
3. **MCP 工具执行 smoke**：迁移后 agent 仍可调用 MCP 工具
4. **现有 `test_mcp_connection`、`test_tools_router_extended` regression PASS**
5. **Alembic 往返**：`m9` upgrade → downgrade → upgrade PASS

### M3（PREBUILT per-user — **E 核心验证点**）

1. **多用户隔离（必需）**：创建 2 个 mock user（user_A, user_B），让两者使用同一 PREBUILT 工具（如 naver_search）并分别通过自己的 connection 执行。通过 log/mock 验证使用各自不同的 credential → **证明共享 row 混用问题已解决**
2. **env → credential 自动 seed**：`.env` 中存在 `NAVER_CLIENT_ID` 时，为 mock user 自动创建 credential + default connection
3. **移除 env 后 regression**：临时移除 env 值，只要 connection 存在工具仍可运行；移除 connection 后给出明确错误
4. **is_default override**：指定 `agent_tools.connection_id` 时，使用该 connection 而非 default

### M4（CUSTOM Connection 统一）

1. **现有 `tool.credential_id` → connection FK 迁移的数据完整性**
2. **N:1 credential 共享**：多个 CUSTOM 工具指向同一个 connection → 执行时使用同一个 credential
3. **CUSTOM 工具执行 regression**：完整通过 HTTP 工具调用路径

### M5（UI 统一 + 吸收 F）

1. **ConnectionBindingDialog**：在 3 种 context（prebuilt/custom/mcp）中分别按正确 schema 渲染
2. **移除现有 3 个 dialog 后的 agent-browser E2E**：PREBUILT 连接、CUSTOM 创建、MCP 添加各流程通过
3. **重构 /connections 页面**：以 Connection 为中心的列表 + credential 作为下级辅助信息展示

### M6 (Cleanup)

1. **drop legacy 列后全部测试 PASS**
2. **Alembic 双向往返**
3. **全量 grep**：tool 模型/服务中不再残留 `mcp_server_id`、`credential_id`

---

## 相关文档

- 已结束的执行记录：`docs/exec-plans/completed/backlog-e-connection-refactor.md`（由 ADR-009 废弃并取代）
- 前置 ADR：ADR-007（credentials field_keys cache）、ADR-005（Builder/Assistant）
- 后续工作：引入 multi-user auth（E 完成后另行 ADR）
- 类似服务 UX 参考：MCP `导入 JSON`（Claude Desktop mcpServers config import）— 作为 M5 UX 扩展候选的 footnote
