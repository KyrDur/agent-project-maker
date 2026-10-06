# CHECKPOINT — Service LLM Key from Credentials (解决 UX gap)

> milestone gate — Satya 所有。团队成员完成报告时验证 → 满足 done-when 后标记 done。
> 分支: `feat/service-llm-key-from-credentials` (从 main `4fee88c` 分出)
> 用户决定 (2026-05-06): 选项 B — credentials UI 中注册的 LLM key 也可供 builder/assistant sub-agent 使用。解决 UX gap。

---

## 核心 scope

**问题**: Builder/Assistant sub-agent 只使用 `settings.{provider}_api_key` (.env / OS env)。用户在 `/credentials` UI 注册的 LLM provider key 仅供普通 chat agent (`Agent.llm_credential`) 使用，builder 无法使用。与用户 mental model("credentials = 单一事实来源") 不一致。

**解决**: 在 lifespan startup 时 + credential CRUD 变更时，将 credentials 表中的 LLM provider key 同步到 `_ENV_FALLBACK` dict。若有 `.env` key 则优先 (backward compat)。

| 区域 | 决策 |
|------|------|
| `model_factory.py:_ENV_FALLBACK` 同步 | ✅ 新增 — credentials → dict 注入 |
| `main.py` lifespan | ✅ 通过 startup hook 同步 1 次 |
| credential CRUD API | ✅ invalidate hook (无需重启即可生效) |
| `.env` key 优先级 | ✅ env 存在时优先 (backward compat) |
| Frontend 变更 | ❌ 0 (符合 mental model 的 backend-only fix) |
| `Agent.llm_credential` (end-user agent) 路径 | 🔒 保留 (已正常工作) |

最小化回归风险: 保留 env-only fallback 行为。credentials 集成是*新增*路径。

---

## M0: 治理初始化 (Satya DRI)
- [x] 创建分支 `feat/service-llm-key-from-credentials` (main `4fee88c`)
- [x] 编写 CHECKPOINT.md
- [ ] AUDIT.log 入口记录
- 验证: `git branch --show-current`
- done-when: 新分支 + CHECKPOINT + AUDIT 条目
- 状态: in-progress

## M1: 依赖分析 (Bezos DRI)
- [ ] credentials 表 LLM provider key 识别模式 (definition_key 映射 — anthropic/openai/google/openrouter)
- [ ] 追踪现有 `Agent.llm_credential` decrypt 路径 — 识别可复用 helper
- [ ] credential CRUD API 位置 (POST/PATCH/DELETE) + invalidate hook 插入点
- [ ] `_ENV_FALLBACK` 调用点映射 (除 helpers.py / model_factory.py 外)
- [ ] 回归 guard 候选场景 spec
- 验证: `tasks/credentials-llm-key-sync-analysis.md` 存在
- done-when: 依赖报告 + invalidate hook 位置 + 回归 guard 场景
- 状态: pending

## M2: 架构 + ADR (Pichai DRI, M1 后)
- [ ] 编写新 ADR `docs/design-docs/adr-013-service-llm-key-from-credentials.md` — 决策理由 (用户 mental model + a7fc92d "runtime key isolation" 的 trade-off)
- [ ] 决定 key 优先级: env > credentials (或 credentials > env)。backward compat 侧推荐 = env 优先
- [ ] 决定 invalidate hook 机制 (mutable dict vs lock-protected reload vs callback registry)
- [ ] 明确 credentials 的 anthropic/openai/google/openrouter definition_key 映射
- 验证: `test -f docs/design-docs/adr-013-service-llm-key-from-credentials.md`
- done-when: ADR 编写 + 优先级 + hook 设计 + provider 映射
- 状态: pending

## M3: Backend 实现 (Jensen DRI, M2 后)
- [ ] `app/services/credential_service.py` (或新增) async helper `get_provider_keys() -> dict[str, str | None]` — 按 credentials 表中的 LLM provider decrypt key
- [ ] 将 `model_factory.py` `_ENV_FALLBACK` 改为 mutable dict 或 resolver function + thread-safe sync helper `sync_env_fallback_from_credentials(db)`
- [ ] `main.py` lifespan startup — 调用 sync 1 次
- [ ] credential CRUD (POST/PATCH/DELETE) handler — 重新调用 sync (或 callback registry)
- [ ] 新增 guard ≥3 个:
  - `test_lifespan_syncs_credentials_to_env_fallback`
  - `test_credential_create_invalidates_env_fallback`
  - `test_env_key_takes_priority_over_credential` (backward compat)
  - `test_get_provider_keys_decrypts_anthropic` (helper 单元)
- 验证: `cd backend && uv run alembic upgrade head && uv run ruff check . && uv run pytest tests/ && uv run pyright app/ tests/`
- done-when: ruff 0 / pyright 0/0 / pytest 回归 0 + 新增 guard ≥3 个 PASS
- 状态: pending

## M4: 回归验证 + 集成 (Bezos DRI, M3 后)
- [ ] backend gate 4 类 + 新增 guard PASS
- [ ] 用户场景验证: 在 credentials 注册 anthropic key → builder 正常 LLM 调用 (手动或集成测试)
- [ ] backward compat: `.env` ANTHROPIC_API_KEY 存在时优先使用它
- [ ] 删除 credential 后重新调用 sync，反映 key 缺失
- 验证: 上述项目全部通过
- done-when: gate + 用户场景 + backward compat + invalidate 全部 PASS
- 状态: pending

## M5: HANDOFF (Satya DRI, M4 后)
- [ ] 编写 HANDOFF.md
- [ ] progress.txt 学习 entry
- [ ] AUDIT PROJECT_DONE
- 状态: pending

---

## 保留区域 (禁止修改)

- `Agent.llm_credential` decrypt 路径 (chat_service / agent_runtime 的 end-user agent flow)
- `credentials` 表 schema (变更 0)
- `Cipher` / `key_provider` (M1 产物，保留)
- frontend `/credentials` 页面 (UI 变更 0)

## 最小化回归风险

1. **`.env` 优先** — backward compat。现有用户影响 0
2. **mutable dict 同步** — 保持现有 `PROVIDER_API_KEY_MAP = _ENV_FALLBACK` alias，只更新 dict 内容
3. **lifespan startup 1 次 + CRUD invalidate** — credential 变更立即生效
4. **新增 guard ≥3 个** + 用户场景验证 (M4)
5. **保留 end-user agent 路径** — `Agent.llm_credential` flow 变更 0
