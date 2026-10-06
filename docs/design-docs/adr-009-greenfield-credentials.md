# ADR-009：Credential / Tools / Skills Greenfield 重写

**状态**：Accepted
**日期**：2026-04-29
**决策者**：Satya（PO）、Pichai（架构 DRI）
**相关**：ADR-007（credentials field_keys）、ADR-008（Connection entity）

---

## Context

`Credential` / `Connection` / `Tools` / `Skills` 系统经过 ADR-007 ~ ADR-008 和 M6 ~ M11 migration 持续演进。结果：

1. **二元化**：Credential 与 Connection 分离为 N:1 关系，工具认证路径按 PREBUILT/CUSTOM/MCP/BUILTIN 4 类分支。
2. **认证解析复杂度**：`chat_service.build_tools_config()`（L369-462）中累积了 `_resolve_prebuilt_auth`、`_resolve_custom_auth`、`_gate_connection_active`、`_gate_connection_credential` 等分支。
3. **migration 累积**：`m11_custom_credential_migration` 将 `tool.credential_id` → `tool.connection_id`，但旧列仍残留，downgrade 复杂。
4. **缺少 OAuth/Vault/key rotation**：不支持自动 OAuth refresh、外部 secret store（Vault）、多 key rotation。
5. **UI 一致性不足**：工具、连接、credential、skill 页面分别使用不同 card grid，状态展示不统一。

在当前状态下继续加入 OAuth refresh、External Secrets、多 key rotation、动态 form 验证等功能，将再次需要一次 M11 级别的 migration。

## Decision

将 Credential/Tool/Skill stack 基于 Python（FastAPI/SQLAlchemy）·React（Next.js/shadcn）的 Moldy 自有模型进行 greenfield 重写。统一认证解析路径，并在同一 domain model 中集成 OAuth refresh、External Secrets、多 key rotation、动态 form 验证。

### 核心决策

| # | 决策 | 依据 |
|---|---|---|
| 1 | **取消二元化** | 统一为 Credential。删除 Connection model/router/service。Tool 统一为 `definition_key + parameters + credential_id FK` 单一路径。 |
| 2 | **Cipher V2** | HKDF-SHA256、AES-256-GCM、单一 blob Base64 `[0x01][salt 32B][authTag 16B][ciphertext]`。HKDF info 为 `b'moldy-encryption-v1'`。多 key 标识使用独立的 `credentials.key_id` 列。 |
| 3 | **统一 LLM model** | 保留 `models` 表，但移除 `api_key_encrypted` 列。新增 `agents.llm_credential_id` FK。废弃 `llm_providers` 表。LLM API key 也使用新 Credential。 |
| 4 | **OAuth2 自动 refresh** | `expirable` typeOptions 检查 token 过期 → refresh → 重新加密 → audit log。并发：使用 `SELECT ... FOR UPDATE` 串行化。 |
| 5 | **External Secrets（Vault）** | 实现 HVAC SDK。通过 feature flag（`settings.external_secrets_enabled`）默认关闭。runtime 解析 `__external__: { provider, ref }` marker。 |
| 6 | **自动 key rotation** | APScheduler job `rotate_credentials_to_active_key` 每周 1 次。对 `key_id != active_key_id` 的 row 批量重新加密。audit log `rotate`。 |
| 7 | **migration** | 单一 migration `m13_greenfield_credentials`。DROP + CREATE 所有关联表 + ADD `agents.llm_credential_id`。PoC 阶段允许丢弃 dev DB。downgrade 为 `NotImplementedError`。 |
| 8 | **单一 PR** | 以新增文件为主，约 ~80 个文件。避免 dual system 共存。按 milestone commit 保证 review 可读性。 |
| 9 | **branding 验证** | `scripts/check_branding.py` 作为 CI gate。检查配置的禁用标识符、package prefix、asset SHA-256 blacklist。 |

### 范围外

- 通用 node system 全部 — 工具简化为单一 `ToolDefinition` 类型
- 任意代码执行表达式引擎 — 仅评估 `={{ $credentials.<field> }}` 的受限 interpolator
- enterprise 专用模块 — 不在当前产品范围内
- 外部 UI component port — 使用 React+shadcn 重新实现

## Consequences

### Positive

- 统一认证解析路径：`tool.credential_id` 直连，取消分支
- 第 1 阶段引入 OAuth/Vault/rotation 等运维能力
- 通过 Cipher V2 支持 key lifecycle 管理
- UI 一致性：统一 DataTable + status chip + dynamic form renderer
- 降低新增 tool/credential 的成本（只需注册定义）

### Negative

- 丢弃 dev DB 数据（PoC 阶段可接受）
- 单一 PR review 负担（通过 milestone commit 缓解）
- 学习曲线：团队需要熟悉新的 domain model

### Risks & Mitigations

| 风险 | 应对 |
|---|---|
| 违反 branding policy | 强制 `scripts/check_branding.py` CI gate |
| OAuth refresh 并发 | 在 `oauth2_base` 中通过 `SELECT ... FOR UPDATE` 串行化 |
| chat/trigger regression | M5 重写 chat_service 后立即执行 chat+tool+trigger+MCP 场景 regression test |
| Vault 依赖 | feature flag 默认关闭，fallback 到 env_provider |
| license 适配 | review dependency license，并在公开部署前最终确认 |

## Implementation

milestone 定义见 `CHECKPOINT.md`，详细文件/spec 见根目录 `PLAN.md`，任务跟踪见 TaskList（`tth-greenfield-credentials` team）。

执行顺序：
- M0 governance（含本 ADR）→ M1 branding 验证 + Cipher V2 → M2 Credential + Vault → M3 Tools + MCP → M4 Skills + m13 migration → M5 agent_runtime 重连 + cron → M6 前端。

## References

- 之前的 ADR：ADR-007（field_keys）、ADR-008（Connection — 由本 ADR 废弃并取代）
