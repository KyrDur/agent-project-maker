# Moldy Backend

基于 FastAPI、SQLAlchemy 和 LangChain/LangGraph 的 AI 智能体构建后端。

项目概述、技术栈和配置请参阅根目录 [`README.md`](../README.md)。

## 快速开始

```bash
# 安装依赖
uv sync

# 数据库迁移
uv run alembic upgrade head

# 开发服务器 (http://localhost:8001/docs)
uv run uvicorn app.main:app --reload --reload-dir app --port 8001
```

在 worktree 中使用其他前端端口时，后端 CORS 必须允许相同的 origin。
例如：前端 `3010`，后端 `8010`。

```bash
CORS_ALLOWED_ORIGINS=http://localhost:3010,http://127.0.0.1:3010 \
  uv run uvicorn app.main:app --reload --reload-dir app --port 8010
```

## 常用命令

```bash
uv run pytest                # 基于 aiosqlite 的单元测试（无需 Postgres）
uv run ruff check .          # 静态检查
uv run ruff format .         # 格式化
uv run alembic revision -m "..." --autogenerate  # 新建迁移

# 使用仓库根目录的 runner 执行隔离 PostgreSQL 集成测试。
(
  cd ..
  manifest=".omo/evidence/project-restart-consolidated-roadmap/local-postgres-$(date +%s).json"
  bash scripts/run-isolated-postgres-tests.sh all --manifest "$manifest"
  (cd backend && uv run python ../scripts/check-isolation-cleanup.py "../$manifest")
)
```

runner 从整个 `backend/tests` 中选择带有 `integration` 标记的测试，
比直接指定 `tests/integration/` 更准确地覆盖标准集成验证流程。
仅在快速调试单项测试时，才从 backend 目录执行
`uv run pytest -q tests/integration/test_name.py -m integration`。

## 目录结构

`app/main.py` 是 FastAPI 应用工厂。采用 `routers/`（HTTP）→
`services/`（业务逻辑）→ `models/`（SQLAlchemy ORM）三层结构。
AI 执行逻辑独立放在 `agent_runtime/`。开发约定请参阅根目录 `AGENTS.md`。
