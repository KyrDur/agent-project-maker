# 基于真实浏览器的 E2E 引入指南

本文整理将 Moldy 当前的 E2E 配置迁移到其他项目时所需的内容与工作顺序。
基准来源是以下文件。

- `frontend/playwright.config.ts`
- `frontend/e2e/global-setup.mjs`
- `frontend/e2e/fixtures.ts`
- `frontend/e2e/smoke.spec.ts`
- `frontend/e2e/*.spec.ts`
- `backend/app/seed/e2e_user.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/.env.example`
- `frontend/.env.example`
- `frontend/.gitignore`

目标不是简单的 DOM 单元测试，而是在真实浏览器中启动真实 dev server，
使用已登录会话在主要菜单间跳转，并在需要时捕获并分享页面图像，
从而建立一套可运行、可维护的 E2E 体系。

---

## Moldy 当前结构

Moldy 将 Playwright 放在前端包中。`frontend/package.json` 中有以下
脚本。

```json
{
  "test:e2e": "playwright test",
  "test:e2e:ui": "playwright test --ui"
}
```

`frontend/playwright.config.ts` 会在测试执行时一并启动服务器。

- `E2E_FRONTEND_PORT` 默认值为 `3000`
- `E2E_BACKEND_PORT` 默认值为 `8001`
- `E2E_BASE_URL` 默认值为 `http://localhost:<frontendPort>`
- `E2E_API_BASE_URL` 默认值为 `http://localhost:<backendPort>`
- backend 按当前 frontend origin 设置 `CORS_ALLOWED_ORIGINS` 后运行
- frontend 按当前 backend URL 设置 `NEXT_PUBLIC_API_BASE_URL` 后运行
- 因为 `reuseExistingServer: true`，若服务器已经启动则复用

关键是将 frontend port、backend port、CORS origin、API base URL 作为一组
联动。这四个值一旦不一致，浏览器 cookie、CSRF、CORS、API 请求就会像是
访问不同服务器一样失败。

`frontend/e2e/global-setup.mjs` 不会在每个浏览器中重复走登录表单。
而是通过 Playwright API client 登录一次，并将成功后的 cookie storage
保存到 `frontend/e2e/.auth/user.json`。

当前认证流程顺序如下。

1. `POST /api/auth/login`
2. 失败时 `POST /api/auth/register`
3. 若为 `409 Conflict`，再次 `POST /api/auth/login`
4. 成功后执行 `api.storageState({ path: authFile })`
5. Playwright config 的 `use.storageState` 注入所有测试浏览器

Moldy 在 backend 也提供 E2E 账户 bootstrap。`backend/app/seed/e2e_user.py` 会
当 `E2E_SEED_USER_ENABLED=true` 时，创建或更新仅用于本地的测试用户。
但如果 `APP_ENV=production`，则始终 skip。该账户用于验证 Moldy 中需要 admin 权限的
页面，因此以 `is_super_user=True` 创建。

---

## 其他项目所需的组成部分

### 1. 浏览器测试运行器

Moldy 使用 Playwright。其他项目如果也要一次性使用真实浏览器操作、storage state、
trace、screenshot、route mocking，Playwright 是最简单的选择。

所需包和脚本：

```bash
pnpm add -D @playwright/test
pnpm exec playwright install chromium
```

```json
{
  "scripts": {
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui"
  }
}
```

### 2. 在测试执行过程中启动服务器的配置

迁移 Moldy 的 `webServer` 模式。关键是让测试执行器直接启动 frontend 和 backend。
也就是由测试执行器自行启动它们。

```ts
import { defineConfig } from "@playwright/test";

const skipBackend = process.env.PW_SKIP_BACKEND === "1";
const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? "3000");
const backendPort = Number(process.env.E2E_BACKEND_PORT ?? "8001");
const baseURL = process.env.E2E_BASE_URL ?? `http://localhost:${frontendPort}`;
const apiBaseURL =
  process.env.E2E_API_BASE_URL ?? `http://localhost:${backendPort}`;
const corsOrigins = `http://localhost:${frontendPort},http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.mjs",
  use: {
    baseURL,
    storageState: "./e2e/.auth/user.json",
    trace: "on-first-retry",
  },
  webServer: [
    ...(skipBackend
      ? []
      : [
          {
            command: `cd ../backend && CORS_ALLOWED_ORIGINS=${corsOrigins} uv run uvicorn app.main:app --port ${backendPort}`,
            port: backendPort,
            reuseExistingServer: true,
          },
        ]),
    {
      command: `NEXT_PUBLIC_API_BASE_URL=${apiBaseURL} pnpm dev --port ${frontendPort}`,
      port: frontendPort,
      reuseExistingServer: true,
    },
  ],
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
```

即使目标项目不是 FastAPI/Next.js，原理也相同。

- 将 backend command 替换为该项目的 API 服务器启动命令。
- 将 frontend command 替换为该项目的 web dev server 启动命令。
- 将 frontend 读取的 API URL env 名称替换为实际名称。
- 如果使用 cookie 认证，则对齐 API 服务器的 CORS allow credentials 配置与 allowed origins。

### 3. 本地 E2E 专用账户

如果测试需要实际经过登录页面或执行 API login，就需要一个可预测的账户。
Moldy 通过双重方式处理。

第一层是 backend seed。

- env: `E2E_SEED_USER_ENABLED`
- env: `E2E_USER_EMAIL`
- env: `E2E_USER_PASSWORD`
- env: `E2E_USER_NAME`
- 在 production 中无条件 skip
- 如果已有账户，则更新姓名、激活状态、权限和密码

第二层是 Playwright global setup 的 register fallback。如果 seed 尚未执行
或使用的是新 DB，测试也可以自行创建账户。

其他项目也应应用以下原则。

- 测试账户与真实用户账户分离。
- 不要把 production/staging 共享账户密码写入 git。
- 在 production boot 中阻止自动创建测试账户。
- 如果需要跑到 admin 页面，则显式提升测试账户权限。
- 测试生成的数据在测试结束后删除，或加上唯一 prefix。

### 4. 登录 storage state

Moldy 的 `global-setup.mjs` 模式几乎可以原样复用。

```js
import { request } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dirname = path.dirname(fileURLToPath(import.meta.url));
const authFile = path.join(dirname, ".auth", "user.json");

const backendPort = process.env.E2E_BACKEND_PORT ?? "8001";
const apiBase =
  process.env.E2E_API_BASE_URL ?? `http://localhost:${backendPort}`;
const email = process.env.E2E_USER_EMAIL ?? "playwright-e2e@example.local";
const password = process.env.E2E_USER_PASSWORD ?? "change-me-for-local-e2e";
const name = process.env.E2E_USER_NAME ?? "E2E User";

export default async function globalSetup() {
  await fs.mkdir(path.dirname(authFile), { recursive: true });

  const api = await request.newContext({ baseURL: apiBase });
  try {
    let response = await api.post("/api/auth/login", {
      data: { email, password },
    });

    if (!response.ok()) {
      response = await api.post("/api/auth/register", {
        data: { email, password, name },
      });
    }

    if (!response.ok() && response.status() === 409) {
      response = await api.post("/api/auth/login", {
        data: { email, password },
      });
    }

    if (!response.ok()) {
      const body = await response.text().catch(() => "");
      throw new Error(
        `E2E authentication setup failed (${response.status()}): ${body}`,
      );
    }

    await api.storageState({ path: authFile });
  } finally {
    await api.dispose();
  }
}
```

各项目需要修改的部分：

- login endpoint
- register endpoint
- request body shape
- 如果 CSRF token 不是通过 response body，而是通过 cookie/header 返回，则相应处理
- 如果使用 MFA、OAuth、SSO 等难以通过 API login 的认证方式，则提供测试用 password login，或
  单独提供 test-only session mint endpoint。

### 5. 公共 fixture

Moldy 的 `frontend/e2e/fixtures.ts` 做两件事。

- 当 `PW_SKIP_BACKEND=1` 时，mock `/api/auth/me`，让页面看起来处于登录状态。
- 收集 console error、page exception、request failure，并在测试结束时验证。

其他项目至少也应提供以下 fixture。

```ts
import { test as base, expect } from "@playwright/test";

type ErrorCollector = {
  console: string[];
  page: string[];
  network: string[];
};

export const test = base.extend<{ errors: ErrorCollector }>({
  errors: async ({ page }, use) => {
    const errors: ErrorCollector = { console: [], page: [], network: [] };

    page.on("console", (msg) => {
      if (msg.type() === "error") errors.console.push(msg.text());
    });
    page.on("pageerror", (err) => errors.page.push(err.message));
    page.on("requestfailed", (req) =>
      errors.network.push(`${req.method()} ${req.url()}`),
    );

    await use(errors);

    expect(errors.page, "JS exceptions detected").toEqual([]);
  },
});

export { expect };
```

实际项目中，仅狭义忽略 favicon、devtools 提示、analytics 屏蔽等已知 benign error。
只应窄范围忽略这些错误。

### 6. smoke spec

Moldy 的 `frontend/e2e/smoke.spec.ts` 会广泛检查最重要的菜单和 dialog 是否正常。
进行较宽范围的检查。

当前 Moldy smoke 包括以下内容。

- `/` dashboard
- `/agents/new`
- `/agents/new/template`
- `/tools`
- `/models`
- `/usage`
- 创建 agent 后检查 chat/settings/redirect
- 添加模型 dialog
- 创建工具 dialog
- 预配置工具 credential dialog
- 删除 agent confirmation dialog
- 对话式 agent 创建页面

其他项目的首批 E2E 也应从这种程度的“菜单遍历 smoke”开始。

推荐模式：

```ts
import { test, expect } from "./fixtures";

test.describe("Smoke", () => {
  test("/dashboard loads", async ({ page, errors }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    await expect(
      page.getByRole("heading", { name: /dashboard/i }),
    ).toBeVisible();

    expect(errors.console).toEqual([]);
    expect(errors.network).toEqual([]);
  });

  test("/settings opens dialog", async ({ page, errors }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: /new|add|create/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    expect(errors.console).toEqual([]);
    expect(errors.network).toEqual([]);
  });
});
```

选择器原则：

- 优先使用 `getByRole`、`getByLabel`、`getByPlaceholder`。
- 对复杂组件添加稳定的 `data-testid`。
- CSS class selector 与布局实现绑定，因此仅作为最后手段。
- 对于 E2E 验证文案会随 i18n 变化的项目，固定 locale，或使用更接近 key 的
  可访问性 label。

### 7. 区分真实 backend 与 mock-only 模式

Moldy 同时支持两种模式。

真实 backend 模式：

- 默认值
- 同时运行 FastAPI 和 Next.js
- login storage state 持有真实 cookie。
- 用于验证 smoke、动态页面和 CRUD 流程

mock-only 模式：

- `PW_SKIP_BACKEND=1`
- 不启动 backend。
- 所有 `/api/*` 请求都必须用 `page.route` mock。
- 用于验证 UI 状态、dialog、table、chart 等不依赖 backend 稳定性的页面

Moldy 示例：

- `credentials.spec.ts`：对 credential catalog/create API 进行 route mock
- `mcp-server-wizard.spec.ts`：对 MCP probe/discover API 进行 route mock
- `health-check.spec.ts`：对 model health API 和 history API 进行 route mock
- `model-test.spec.ts`：对 provider test success/auth error 响应进行 route mock

其他项目也要明确制定规则。

- smoke 和核心用户 journey 使用真实 backend 运行。
- 外部 API、支付、LLM、OAuth、webhook 等不稳定或会产生成本的边界使用 mock。
- 可在 `PW_SKIP_BACKEND=1` 下运行的 spec，必须显式 mock 所有 API。
- 需要真实 backend 的 spec 使用 `test.skip(process.env.PW_SKIP_BACKEND === '1', ...)`。

### 8. CSRF 与状态变更 API

Moldy 使用 HttpOnly cookie + CSRF double-submit，因此通过 Playwright request
创建测试数据时需要 CSRF header。

`frontend/e2e/smoke.spec.ts` 中的 `loginApi()` 流程如下。

1. `POST /api/auth/login`
2. 从响应 body 中提取 `csrf_token`
3. 在状态变更请求中添加 `X-CSRF-Token` header

如果其他项目使用 cookie 认证和 CSRF，应先创建这个 helper。

```ts
async function loginApi(request) {
  const res = await request.post(`${API_BASE}/api/auth/login`, {
    data: { email: E2E_EMAIL, password: E2E_PASSWORD },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return { "X-CSRF-Token": body.csrf_token };
}
```

如果项目使用 Bearer token 认证，则在同一位置返回 `Authorization: Bearer <token>`
即可。

### 9. 测试数据创建与清理

Moldy smoke 为验证动态页面，会先通过 API 创建 agent 和 conversation，
然后在 `afterAll` 中删除 agent。

其他项目也应遵循以下规则。

- 不需要通过 UI 创建的前置数据，用 API 创建。
- 只有用户实际必须走过的核心 flow 才通过 UI 创建。
- 数据名称加上 `E2E` prefix。
- 保存测试生成的数据 id，并在 `afterAll` 或 teardown 中删除。
- 即使失败也优先采用可重新执行的 idempotent setup。

### 10. 页面截图产物

Moldy 的 repo 规则是不把 E2E 产物散落在 repo root，而是集中到以下路径。

```text
output/e2e-captures/<YYYYMMDD>-<feature>/
```

`output/` 已包含在 `.gitignore` 中。Playwright 自身的产物也
在 `frontend/.gitignore` 中排除。

- `frontend/e2e/.auth/`
- `frontend/test-results/`
- `frontend/playwright-report/`

其他项目也应采用相同规则。

截图用 helper 示例：

```ts
import fs from "node:fs/promises";
import path from "node:path";

export async function capturePage(page, feature, name) {
  const stamp = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const dir = path.resolve(
    process.cwd(),
    "..",
    "output",
    "e2e-captures",
    `${stamp}-${feature}`,
  );
  await fs.mkdir(dir, { recursive: true });

  const file = path.join(dir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}
```

运维规则：

- 截图前确认登录账户和页面状态正确。
- secret 页面使用 dummy 值代替真实 secret。
- 截图后用 `file output/e2e-captures/.../*.png` 确认实际 PNG 与分辨率。
- 分享给他人前亲自打开检查，确认没有文字裁切、空白页面或破损图片。
- trace/video/raw capture 也统一放在同一 feature directory 下。

### 11. CI 与本地命令

本地基础命令：

```bash
cd frontend
pnpm test:e2e
```

端口冲突或同时运行多个 worktree 时：

```bash
cd frontend
E2E_FRONTEND_PORT=3010 \
E2E_BACKEND_PORT=8010 \
E2E_BASE_URL=http://localhost:3010 \
E2E_API_BASE_URL=http://localhost:8010 \
pnpm test:e2e
```

仅指定 mock-only spec 运行时：

```bash
cd frontend
PW_SKIP_BACKEND=1 pnpm exec playwright test e2e/credentials.spec.ts
```

CI 中还需额外固定以下内容。

- DB service 或 test database
- 执行 migration
- E2E env 值
- Playwright browser install cache
- test result, trace, screenshot artifact upload
- 限制 worker 数量：`E2E_WORKERS=1`，或从较小值开始

---

## 迁移检查清单

### Backend

- [ ] 有启动 test database 的命令。
- [ ] 可以在测试前执行 migration。
- [ ] 有本地 E2E 账户 seed。
- [ ] 在 production 中 E2E seed 必须无条件禁用。
- [ ] 若使用 cookie 认证，CORS allow credentials 与 allowed origins 明确。
- [ ] 若有 CSRF，提供测试用 header helper。
- [ ] 有测试数据 cleanup API 或 seed reset 方法。

### Frontend

- [ ] 已安装 Playwright。
- [ ] 有 `test:e2e`、`test:e2e:ui` 脚本。
- [ ] `playwright.config.ts` 会同时启动 frontend/backend 服务器。
- [ ] frontend API base URL env 指向测试 backend port。
- [ ] `globalSetup` 在 login/register fallback 后保存 storage state。
- [ ] `.auth/`、`test-results/`、`playwright-report/` 已加入 gitignore。
- [ ] 公共 fixture 会收集 console/page/network error。

### Spec

- [ ] 有 dashboard 或 home route smoke。
- [ ] 有主要菜单 route smoke。
- [ ] 至少有 1 个 dialog/open-close smoke。
- [ ] 至少有 1 个需要真实 backend 的 CRUD journey。
- [ ] 外部 API 或产生成本的边界已拆分为 route mock spec。
- [ ] mock-only spec 可在 `PW_SKIP_BACKEND=1` 模式下运行。
- [ ] 主要 selector 基于 role/label/testid。

### Capture

- [ ] 已确定 screenshot/video/trace 保存路径。
- [ ] 保存路径已加入 gitignore。
- [ ] 截图前只使用 dummy secret。
- [ ] 分享前确认文件确实是 PNG 并检查分辨率。
- [ ] 分享前亲自打开图片，确认 UI 没有损坏。

---

## 推荐引入顺序

1. 安装 Playwright 并添加 `test:e2e` 脚本。
2. 只启动 frontend，先通过一个静态 smoke。
3. 接入 backend webServer，并对齐 CORS/API base URL。
4. 添加 E2E 账户 seed 与 `globalSetup` storage state。
5. 通过已登录的 dashboard smoke。
6. 添加 5~10 个主要菜单 smoke。
7. 添加 1 个混合 API setup + UI 验证的真实 CRUD journey。
8. 对需要外部 API 的页面拆分为 route mock spec。
9. 添加截图 helper 与 `output/e2e-captures/` 规则。
10. 将 Playwright report、trace、screenshot 作为 CI artifact 上传。

按这个顺序推进，可以避免一开始就试图用 E2E 覆盖所有功能而导致进展缓慢，同时
能够快速获得“服务器能真实启动、可以登录、浏览器中的核心菜单不会损坏”这一
信号。

---

## 可以从 Moldy 学到的点

- 登录不在每个测试中重复走 UI，而是通过 `storageState` 共享。
- 将真实 backend smoke 与 route mock spec 分离。
- port、CORS、API base URL 作为一组处理。
- 测试账户通过 backend seed 与 Playwright register fallback 构成双重安全网。
- production 中强制阻止测试 seed。
- 对状态变更 API 创建可复用的 CSRF/auth helper。
- E2E 产物统一收集到指定的 ignored directory。
- 页面验证基于 role/label/testid 编写。

将这套配置迁移到其他项目时，最先应复制的文件是
`playwright.config.ts`、`global-setup.mjs`、`fixtures.ts`、`smoke.spec.ts` 这四个。
之后再根据项目的认证方式和服务器启动方式接入 backend seed、env、cleanup
流程即可。
