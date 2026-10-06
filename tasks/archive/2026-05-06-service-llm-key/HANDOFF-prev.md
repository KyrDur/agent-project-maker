# 工作移交 — 8 个 PR 已合并，下一会话 live 验证

> 新会话第一步: 阅读本文件 + (如有需要) 参考 `docs/design-docs/adr-014-chat-model-factory-strategy.md`。

## 最后状态

- 分支: `main` (所有工作已合并，仅剩用于更新本文件的 docs 分支)
- 本会话 8 个 PR (#140~#147) **全部已合并到 main** ✅
- backend: pytest **908** / pyright 0/0 / ruff clean / alembic m35 OK
- frontend: vitest **286** / lint clean / build PASS

## 本会话 8 个 PR (全部合并)

| PR | 含义 |
|----|------|
| #140 | credential_resolution env fallback WARNING→INFO |
| #141 | 分离 chat model factory provider quirks (ADR-014) |
| #142 | chat toast 同一 stream 多个错误 dedup id |
| #143 | 移除 Model.default_credential dead eager-load |
| #144 | 阻止 builder confirm MCP 工具 silent drop |
| #145 | builder 感知 skill + revision 限定表达 ("仅这个") |
| #146 | prompt approval 卡片 — 全部查看 toggle → 内部滚动 |
| #147 | agent 删除 — builder_sessions FK ON DELETE SET NULL |

## PR #145 核心变更

同时解决 Builder v3 无法感知 Skill 资源的 gap + 忽略 revision 限定表达的回归。
- catalog + 推荐 + confirm 全部统一为 Tool/McpTool/Skill 3-way
- `recommend_tools` 添加 first-class 参数 `revision_message`/`previous_recommendations`
- `tool_recommender.md` 限定表达 lookup table (仅这个/排除 X/用 Y 替代 X/限定 category)
- 回归 guard 13 个 — 详情参考 PR #145 说明

## 下一会话入口

1. **live 验证场景** (本会话所有 fix):
   - #145: "员工位置" agent → 暴露 skill catalog + 修改为 "仅这个" → 准确反映 → 创建 `skill_links`
   - #146: phase5 prompt 卡片内部滚动
   - #147: builder agent 立即删除 → 204 + `builder_sessions.agent_id` NULL 断开
2. 生产 DB migration: `cd backend && uv run alembic upgrade head` (应用 m35)
3. 开始新 task (HANDOFF follow-up + 即时 bug 均已耗尽)

## W3-out 剩余 (等待外部 trigger — 当前不要动)

- 🟠 cross-tenant LRU sub-cap (与认证引入 PR 一起)
- 🟡 multi-worker (Redis pub/sub)
- 🟡 `evict_expired` dirty flag (multi-worker 之后)
- 🟡 `events_chunks` 独立表 (turn 5000+ 时)

## 保留区域 (禁止修改)

- `agent_runtime/builder_v3/**` — ADR-012 native interrupt pattern
- `agent_runtime/middleware_registry.py:DEEPAGENT_AUTO_INJECTED_TYPES`
- `agent_runtime/tools/ask_user.py` (选项 A 最终)
- `agent_runtime/credential_resolution.py:resolve_llm_api_key_for_agent` (tiered policy)
- `agent_runtime/model_factory.py:_apply_*` helpers (ADR-014)
- `services/builder_service.py:decisions_to_builder_response` (Phase 5 router adapter)
- `services/chat_service.py:get_owned_conversation_with_agent` — 禁止添加 `Model.default_credential` (#143)
- `services/builder_service.py:_resolve_tools` — 保持 3-way 签名 (#144 #145)

## 验证命令

```
cd backend && uv run alembic upgrade head && uv run ruff check . && uv run pytest tests/ && uv run pyright app/ tests/
cd frontend && pnpm lint && pnpm test --run && pnpm build
```

## 环境注意 (用户 shell)

`~/.zshrc:225` 中 export `OPENAI_BASE_URL=https://*.proxy.runpod.net/v1`。通过 PR #139 + ADR-014 的 canonical endpoint pin 已屏蔽对 backend 的影响。

## commit 注意事项

始终将 scope 外 catalog 自动更新(6 小时 cron)排除在 staging 外:
- `backend/app/data/model_catalog/{catalog,fetch_metadata}.json`
- `backend/app/data/model_catalog/sources/*.json`
