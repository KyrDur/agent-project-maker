# Architecture Decision Records (ADR) Index

> This index lists every tracked ADR file. Titles and statuses reproduce the
> source document's heading or explicit status declaration; where a document
> declares neither, that absence is recorded instead of inferred.

| ADR | Title | Status |
|-----|-------|--------|
| ADR-001 | [Deep Agent 引擎替换](adr-001-deep-agent-engine.md) | 已提议 |
| ADR-002 | [基于 Checkpointer 的对话管理](adr-002-checkpointer.md) | 已批准 |
| ADR-003 | [Skill + Memory 转换设计](adr-003-skills-memory.md) | 已批准 |
| ADR-004 | [M4 整理 — Creation Agent + Trigger + Streaming](adr-004-m4-cleanup.md) | 已批准 |
| ADR-005 | [Builder/Assistant 架构](adr-005-builder-assistant.md) | 已提议 |
| ADR-006 | [assistant-ui ExternalStoreRuntime adapter](adr-006-assistant-ui-runtime.md) | 已批准，2026-06-13 批准 LangGraph v3 扩展 |
| ADR-007 | [Credentials `field_keys` 非加密缓存列](adr-007-credentials-field-keys-cache.md) | 已批准 |
| ADR-008 | [Connection 实体 — Credential 绑定整合](adr-008-connection-entity.md) | 已提议 |
| ADR-009 | [Credential / Tools / Skills greenfield 重写](adr-009-greenfield-credentials.md) | Accepted |
| ADR-010 | [Sprint 1 / Story S2 — 设计 token oklch 修复 + DialogShell 视觉 spec (Tim Cook)](ADR-010-ui-tokens-and-dialog-shell.md) | 无明确状态 |
| ADR-011 | [SSE Stream Resume (W3-out)](adr-011-sse-stream-resume.md) | M1-M6 实现完成 (M6 PR 等待 merge) |
| ADR-012 | [HiTL — 从自研实现迁移到 LangChain `HumanInTheLoopMiddleware`](adr-012-hitl-middleware-migration.md) | Phase 1~4 完成，Phase 5 进行中 (Builder v3 wire 统一) |
| ADR-013 | [Service-side LLM Key from Credentials (Builder/Assistant Sub-agent)](adr-013-service-llm-key-from-credentials.md) | 已批准 (2026-05-06) |
| ADR-014 | [Chat Model Factory — Provider Quirks 分离 (引入 Strategy 模式)](adr-014-chat-model-factory-strategy.md) | 已批准 (2026-05-08) |
| ADR-016 | [引入多用户认证 (HttpOnly Cookie + JWT + super_user)](adr-016-multiuser-auth.md) | Accepted |
| ADR-017 | [Marketplace Resources (Skill / MCP / Agent 共享层, Phase 1: Skill)](adr-017-marketplace-resources.md) | Proposed |
| ADR-018 | [Relative `storage_path` for Skills & Marketplace Versions](adr-018-relative-storage-path.md) | Proposed |
| ADR-019 | [System LLM Settings (按角色选择模型 + 注入 base_url)](adr-019-system-llm-settings.md) | 已提议 (2026-05-26) |
| ADR-020 | [Chat Run AG-UI Adapter](adr-020-chat-run-ag-ui-adapter.md) | Accepted |
| ADR-021 | [Value-Based Trace Redaction (基于值的 trace secret 脱敏)](adr-021-value-based-trace-redaction.md) | Proposed (已提议, 2026-06-24) |
| ADR-022 | [Versioned Runtime Policy Lifecycle](adr-022-runtime-policy-lifecycle.md) | Accepted (2026-09-05) |
