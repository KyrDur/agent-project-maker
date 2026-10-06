# Moldy Frontend

这是基于 Next.js 16 + React 19 的 Moldy Web 客户端。完整项目设置请
先参考根目录 [`README.md`](../README.md) / [原型技术说明中文译本](../README_PROTOTYPE_ZH_CN.md)。

## 快速开始

```bash
pnpm install
cp .env.example .env.local
pnpm dev -- --port 3000
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

`NEXT_PUBLIC_API_BASE_URL` 必须指向实际 backend 端口。默认值为
`http://localhost:8001`。

## Worktree 端口/CORS

如果 frontend 端口发生变化，backend 的 `CORS_ALLOWED_ORIGINS` 也必须允许相同 origin
。例如: frontend `3010`, backend `8010`。

```bash
# backend
cd ../backend
CORS_ALLOWED_ORIGINS=http://localhost:3010,http://127.0.0.1:3010 \
  uv run uvicorn app.main:app --reload --reload-dir app --port 8010

# frontend
cd ../frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8010 pnpm dev -- --port 3010
```

如果直接使用 Next.js 因端口冲突自动选择的端口，CORS/cookie/CSRF 可能不匹配
，因此请用 `--port` 固定。

## 测试

```bash
pnpm lint
pnpm exec tsc --noEmit
pnpm test --run
pnpm build
pnpm test:e2e
```

## Playwright E2E 认证

E2E 不让每个测试重复通过登录表单，而是在 global setup 中一次性创建 API
登录会话，并通过 `storageState` 注入。

如有需要，可在本地/CI 覆盖 `frontend/.env.example` 中的测试账号值:

```env
E2E_USER_EMAIL=e2e@moldy.local
E2E_USER_PASSWORD=e2e-password-change-me
```

推荐流程为 `login → register fallback → login → 保存 e2e/.auth/<lane>-user.json`。
scripted/live 分别使用 `scripted-user.json`/`live-user.json`，
也可通过 `E2E_AUTH_STATE_PATH` 显式覆盖。`e2e/.auth/` 是生成
产物，因此不要提交。`PW_SKIP_BACKEND=1` 仅
用于 mock 所有 `/api/*` 请求的 spec。

## Playwright E2E lanes

Todo04 的 lane runner 负责包含 PostgreSQL 16、backend/frontend、live egress proxy(仅 live)在内的
disposable lifecycle。用户无需手动创建 DB 或执行 migration·服务
关闭。每次执行固定为 scripted `3100/8101`, live `3200/8201`,
Playwright 固定为 `workers=1`/`retries=0`，禁止复用现有服务器，并在成功·失败·SIGINT
之后清理 owned resource。

```bash
# scripted smoke
pnpm test:e2e:scripted -- --project=scripted-smoke

# scripted full (默认 scripted project)
pnpm test:e2e:scripted -- --project=scripted-full

# scripted capture (仅在请求 capture tour 时)
E2E_CAPTURE_TOUR=1 pnpm test:e2e:scripted -- --project=scripted-capture

# live manual — 以下三个变量全部必需
E2E_LLM_BASE_URL='https://llm.example/v1' \
E2E_LLM_API_KEY='...' \
E2E_LLM_MODEL='...' \
pnpm test:e2e:live -- --project=live-manual
```

如果 `E2E_LLM_BASE_URL`, `E2E_LLM_API_KEY`, `E2E_LLM_MODEL` 中任意一个为空
，live lane 不会执行。带 `--list` 的 live 执行用于确认在不实际调用 provider 的情况下
是否只选择固定的四个 live test。
scripted lane 由 runner 启用 E2E scripted model，不传递外部 LiteLLM 值
。

runner manifest 可通过 `E2E_RUN_MANIFEST` 指定，默认值为
`.omo/evidence/project-restart-consolidated-roadmap/e2e-<lane>-<pid>-<timestamp>.json`。
可通过 `E2E_EXPORT_SLUG` 指定 export slug。在执行结束前
对 selection/execution receipt、JUnit/Playwright 结果和 capture 进行 secret scan 后，
将 `export-manifest.json` 及符合 allowlist 的文件
export 到 `output/e2e-captures/<Asia-Seoul-date>-<E2E_EXPORT_SLUG>/`。Screenshot 仅
在 `scripted-capture` 中 export，export 后也会移除 run root。
