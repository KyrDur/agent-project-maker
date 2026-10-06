# 参与 Agent Project Maker 开发

欢迎贡献。项目目标是帮助用户通过模拟实践与评测证据理解并改进 AI 智能体。

## 开始开发

配置说明见根目录 [README.md](./README.md) 和 [backend/README.md](./backend/README.md)。

```bash
# Python 3.12 由 uv 管理；Node 22 由 .node-version 指定。

# 数据库
docker-compose up -d postgres

# 后端
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001

# 前端
cd frontend && pnpm install && pnpm dev
```

## 分支与提交

- 不直接提交到 main；在工作分支完成修改，通过 PR 合并。Codex 工作分支使用 `codex/` 前缀。
- 提交信息使用 `<type>(<scope>): <subject>`，英文祈使句；类型包括 `feat`、`fix`、`docs`、`style`、`refactor`、`test`、`chore`。
- 提交正文重点说明改动原因；PR 说明包含最终行为、验证结果和实际限制。
- 使用协作工具时，只记录实际参与者，不添加未经确认的共同作者。

## 代码约定

完整要求见 [AGENTS.md](./AGENTS.md) 和 [frontend/AGENTS.md](./frontend/AGENTS.md)。

### 后端

- Python 3.12、FastAPI、SQLAlchemy 2.0 async，使用类型提示、async/await 和 `select()`。
- Router → Service → Model 三层结构，业务逻辑位于 `services/`。
- 新增存储须附 Alembic 迁移，并验证历史兼容。
- 单元测试使用 aiosqlite；集成测试使用隔离 PostgreSQL，执行 `pytest -m integration`。
- 静态检查与格式化：`uv run ruff check .`、`uv run ruff format .`。

### 前端

- Next.js 16、React 19、TailwindCSS v4、shadcn/ui；修改前阅读本地 Next.js 文档。
- TypeScript strict，使用 `unknown` 和类型守卫，不使用 `any`。
- 优先 Server Components；尽量减少 `'use client'`。
- 对话框使用 `<DialogShell>` 与 `DIALOG_SIZE`/`DIALOG_HEIGHT`，不直接使用 `<DialogContent>`。
- 表单页脚复用 `FormFooter`，支持 `onCancel`、`onSubmit` 与 `pending`。
- 隐藏标题栏时使用 `<DialogShell.Header srOnly title="..." />`。
- 日期使用 `formatLongDate`/`formatMediumDate` 等公共函数，核对当前界面语言与时区。
- 执行 `pnpm lint && pnpm build`，文案修改同步执行 `pnpm lint:i18n`。

### 设计 token

- 强调文字使用 `--primary-strong`，`text-primary` 用于较浅的表面颜色。
- 状态使用 `--status-{success,info,warn,danger,accent}`，不直接使用 `bg-amber-*`、`bg-sky-*`。
- 详细说明见 `docs/design-docs/ADR-010-ui-tokens-and-dialog-shell.md`。

## PR 检查

- [ ] 相关测试和构建通过，未完成的真实模型验收明确标记。
- [ ] Ruff 与前端静态检查通过。
- [ ] 数据库修改附带迁移及兼容验证。
- [ ] PR 描述说明改动目的、验证和限制。
- [ ] 关联相关 issue（如有）。

## 安全与许可

安全漏洞请按 [SECURITY.md](./SECURITY.md) 的流程报告，不发布公开 issue。
贡献内容按 [MIT 许可](./LICENSE) 分发；保留第三方许可与来源说明。
