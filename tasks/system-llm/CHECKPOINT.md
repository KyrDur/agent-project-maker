# CHECKPOINT — System LLM Settings (ADR-019)

worktree: `.claude/worktrees/system-llm-settings` (branch `feature/system-llm-settings`)
backend cwd: `.../system-llm-settings/backend`, frontend cwd: `.../system-llm-settings/frontend`
ADR: `docs/design-docs/adr-019-system-llm-settings.md`

## M1: DB — system_llm_settings 表 + Alembic M45
- [ ] 新增 `app/models/system_llm_setting.py`（role UNIQUE, credential_id FK SET NULL nullable, model_name nullable, updated_at）
- [ ] `models/__init__.py` export
- [ ] Alembic `m45_system_llm_settings.py` — create table + CHECK(role IN ...) + 3 role seed row (NULL cred/model)
- 验证: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- done-when: 迁移往返成功
- 状态: pending

## M2: resolver — resolve_system_model(role)
- [ ] 在 `system_credential_resolver.py` 中添加 `resolve_system_model(db, role) -> ResolvedSystemModel(provider, model_name, api_key, base_url)`
- [ ] `SystemModelNotConfiguredError(role)`（credential_id 或 model_name 为 NULL 时）
- [ ] 从 credential payload 中提取 base_url
- 验证: `uv run pytest tests/ -k system_llm -q`
- done-when: 新增单元测试通过
- 状态: pending

## M3: 接线 — 替换 builder/assistant/image 调用方
- [ ] `assistant_agent.py` → text_primary，传递 base_url
- [ ] `builder/sub_agents/helpers.py` _get_builder_model→text_primary, _get_fallback_model→text_fallback，移除 @functools.cache
- [ ] `image_service.py` + `builder_v3/image_gen.py` → image role
- 验证: `uv run ruff check . && uv run pytest -q`
- done-when: 回归 0，ruff 通过
- 状态: pending

## M4: API — system-llm-settings 路由（super_user）
- [ ] `routers/system_llm_settings.py`: GET (3 role), PUT /{role}
- [ ] 验证 credential 是否为 is_system=True 的 LLM credential（统一不存在/无权限响应）
- [ ] 添加 `schemas/system_llm_setting.py` + 注册 main.py
- 验证: `uv run pytest tests/ -k system_llm -q`
- done-when: API 测试通过，确认 require_super_user guard
- 状态: pending

## M5: 前端 — System LLM 设置页面
- [ ] api client + TanStack Query hooks
- [ ] 在管理员菜单中添加页面（与 System Credentials 相同权限）
- [ ] 3 个 slot: credential select → discover-models → model select → 保存
- 验证: `pnpm build && pnpm lint`
- done-when: 类型检查/构建通过
- 状态: pending

## M6: 集成验证
- [ ] backend: `uv run ruff check . && uv run pytest`
- [ ] frontend: `pnpm build && pnpm lint`
- done-when: 全部 green
- 状态: pending
