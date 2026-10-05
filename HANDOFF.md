# 历史交接记录 — System LLM Settings 与 LiteLLM 集成

> 原型历史记录（2026-05-26），不作为当前产品的配置指南。
> 当前个人模型 A/B/C 配置见 README.md；下列状态与测试数字仅反映当时记录。

**会话日期**：2026-05-26
**当时目标**：由运营者在 UI 为 Builder、Assistant、图片等系统功能选择角色模型，并通过 LiteLLM（openai_compatible）端点执行。

## 当时已完成的工作

- [x] **ADR-019 System LLM Settings**：PR #168 已合并。`system_llm_settings` 表（m45）、`resolve_system_model(role)`、base_url 注入与 `/settings/system-llm` 页面（三个配置槽）。
- [x] **LLM Key 文档修正**：PR #169 已合并。ENV Key 从必填改为可选，可通过 UI 注册；涉及 `.env.example`、CLAUDE 与 README。
- [x] **LiteLLM/Builder 三项集成修复**：PR #170 已推送，等待评审。
  - (a) discover-models 遇到系统凭据 404 时，为 super_user 回退到 `get_system`。
  - (b) Builder 使用 `raw_decode` 解析 JSON，忽略尾随文本以兼容 LiteLLM。
  - (c) Builder 聊天通过 `allMessages` ID 去重，防止触发 assistant-ui 不变式导致崩溃。

## 当时进行中的工作

- [ ] PR #170 等待评审与合并；合并后执行 `/sync`。

## 当时列出的后续工作

1. 合并 PR #170，然后在 main 执行 `git pull` 或 `/sync`。
2. 当时的运营者配置要求：super_user 在 `/settings/system-llm` 选择 text_primary、text_fallback、image，Builder、Assistant 与图片功能才可运行。m45 当时已应用。
3. 单独 PR 跟进：OPEN-2，为 aiosqlite 全局启用 `PRAGMA foreign_keys=ON`，避免其他 FK SET NULL 测试假通过；OPEN-4，将运营者警告框 `bg-amber-*` 改为 `--status-warn`，覆盖 system-llm 与 system-credentials。
4. 可选：Builder 的 `streamingMessages` 未清理可能导致轻微内存累积。上述去重仅避免崩溃；根本清理与 W3-out 流恢复保护相关，当时暂缓。

## 当时的注意事项

- ADR-019 决策 2 要求 DB 为单一配置来源：运行时不使用 `.env` 中的 builder_model_* 与 assistant_model_*，未配置则明确抛出 `SystemModelNotConfiguredError`。
- `backend/data` 与 `backend/.env` 是本地数据与配置，不提交；worktree 使用符号链接。不要误改 `use-chat-runtime.ts` 中与 W3-out 流恢复保护有关的清理逻辑。
- LiteLLM gateway 可能在 JSON 后附加文本，解析修复用于处理该情况。
- 当时记录认为已合并的 `.claude/worktrees/system-llm-settings` 可通过 `git worktree remove` 清理，ADR-018 用于保护数据。

## 相关文件

- `docs/design-docs/adr-019-system-llm-settings.md`
- 后端：`app/models/system_llm_setting.py`、`app/services/system_credential_resolver.py`、`app/routers/system_llm_settings.py`、`alembic/.../m45_*.py`
- 调用连接：`assistant_agent.py`、`builder/sub_agents/helpers.py`、`image_service.py`、`builder_v3/image_gen.py`
- 前端：`frontend/src/app/settings/system-llm/`、`lib/chat/use-chat-runtime.ts`
- discover 修复：`app/routers/credentials.py`

## 当时的最终记录

- 分支：`fix/litellm-builder-integration`，位于 main 检出目录。
- 最后提交：`b611ff4`。
- 当时测试记录：后端 1221 项通过、无回归；前端构建与静态检查通过。
- PR 状态：#168 与 #169 已合并，#170 等待评审。
