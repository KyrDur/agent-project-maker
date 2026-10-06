# Pre-built 工具 API key 设置指南

要在 Moldy 中使用 Pre-built 工具，需要获取并设置各服务的 API key。
本文档是面向首次使用者的分步指南。

---

## 目录

1. [Naver Search 工具](#1-naver-search-工具)
2. [Google Search 工具](#2-google-search-工具)
3. [Google Chat Send 工具](#3-google-chat-send-工具)
4. [Gmail / Calendar 工具](#4-gmail--calendar-工具)
5. [在 Moldy 中输入密钥](#5-在-moldy-中输入密钥)
6. [问题排查](#6-问题排查)

---

## 1. Naver Search 工具

**目标工具**：Naver Blog Search, Naver News Search, Naver Image Search, Naver Shopping Search, Naver Local Search（共 5 个）

**所需密钥**：Client ID, Client Secret

### 获取步骤

1. 登录 [Naver 开发者中心](https://developers.naver.com)。

2. 在顶部菜单点击 **Application** > **注册应用**。

3. 输入应用信息：
   - **应用名称**：`Moldy`（任意名称）
   - **使用 API**：选择 `搜索`

4. 在**非登录开放 API 服务环境**中：
   - 添加环境：选择 `WEB 设置`
   - Web 服务 URL：输入 Moldy 运行的 URL（例：`http://localhost:3000`）

5. 点击**注册**。

6. 注册完成后，在**应用信息**页面确认：
   - **Client ID** — 用作 `NAVER_CLIENT_ID`
   - **Client Secret** — 用作 `NAVER_CLIENT_SECRET`

### 注意事项

- 每天可调用 25,000 次（免费）
- 5 个 Naver 工具共享同一个 Client ID / Secret。只需设置一次。

---

## 2. Google Search 工具

**目标工具**：Google Search, Google News Search, Google Image Search（共 3 个）

**所需密钥**：API Key, Search Engine ID (CSE ID)

### Step 1: 获取 API Key

1. 登录 [Google Cloud Console](https://console.cloud.google.com)。

2. 选择项目或创建新项目。

3. 前往 **API 和服务** > **库**。

4. 搜索 `Custom Search JSON API` 并**启用**。

5. 前往 **API 和服务** > **凭据**。

6. 点击 **+ 创建凭据** > **API 密钥**。

7. 复制生成的 API key — 用作 `GOOGLE_API_KEY`

> **安全提示**：在 API key 限制设置中，将“API 限制”限定为 `Custom Search JSON API` 更安全。

### Step 2: 获取 Search Engine ID (CSE ID)

1. 访问 [Programmable Search Engine](https://programmablesearchengine.google.com)。

2. 点击**添加**按钮。

3. 搜索引擎设置：
   - **要搜索的网站**：选择`搜索整个 Web`
   - **搜索引擎名称**：`Moldy Search`（任意名称）

4. 点击**创建**。

5. 复制生成的搜索引擎的**搜索引擎 ID** — 用作 `GOOGLE_CSE_ID`

### 注意事项

- 每天 100 次免费，超出后每 1,000 次 $5
- 3 个 Google Search 工具共享同一个 API Key / CSE ID。

---

## 3. Google Chat Send 工具

**目标工具**：Google Chat Send（1 个）

**所需密钥**：Webhook URL

### 获取步骤

1. 打开 [Google Chat](https://chat.google.com)。

2. 选择要发送消息的**空间**（或创建新空间）。

3. 点击空间名称旁的**下拉箭头** > **应用和集成**。

4. 点击 **+ 添加 Webhook**。

5. 输入 Webhook 信息：
   - **名称**：`Moldy Bot`（任意名称）
   - **头像 URL**：（可选，可以留空）

6. 点击**保存**。

7. 复制生成的 **Webhook URL**。
   - 格式：`https://chat.googleapis.com/v1/spaces/XXXXX/messages?key=...&token=...`

### 注意事项

- Webhook 仅可用于 Google Workspace（付费账户）。
- 只能发送消息，不支持接收/读取。

---

## 4. Gmail / Calendar 工具

**目标工具**：Gmail Read, Gmail Send, Calendar List Events, Calendar Create Event, Calendar Update Event（共 5 个）

**所需密钥**：OAuth Client ID, OAuth Client Secret, Refresh Token

这些工具使用 Google OAuth2 认证。设置稍微复杂，但按以下步骤操作即可。

### Step 1: Google Cloud 项目设置

1. 登录 [Google Cloud Console](https://console.cloud.google.com)。

2. 选择项目或创建新项目。

3. 在 **API 和服务** > **库**中分别**启用**以下 API：
   - `Gmail API`
   - `Google Calendar API`

### Step 2: OAuth 同意屏幕设置

1. 前往 **API 和服务** > **OAuth 同意屏幕**。

2. 选择**外部**用户类型并点击**创建**。

3. 输入必填信息：
   - **应用名称**：`Moldy`
   - **用户支持邮箱**：你的邮箱
   - **开发者联系邮箱**：你的邮箱

4. 在**添加范围**页面添加以下范围：
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/calendar`

5. 在**测试用户**中添加你的 Google 账户邮箱。

6. 确认摘要并点击**返回仪表盘**。

### Step 3: 创建 OAuth Client ID

1. 前往 **API 和服务** > **凭据**。

2. 点击 **+ 创建凭据** > **OAuth 客户端 ID**。

3. 设置：
   - **应用类型**：`Web 应用`
   - **名称**：`Moldy OAuth`
   - **已获授权的重定向 URI**：`https://developers.google.com/oauthplayground`

4. 点击**创建**。

5. 复制显示的信息：
   - **客户端 ID** — 用作 `OAuth Client ID`
   - **客户端密钥** — 用作 `OAuth Client Secret`

### Step 4: 获取 Refresh Token

1. 访问 [OAuth 2.0 Playground](https://developers.google.com/oauthplayground)。

2. 点击右上角**齿轮图标**（OAuth 2.0 configuration）。

3. 设置：
   - 勾选 **Use your own OAuth credentials**
   - **OAuth Client ID**：输入 Step 3 中复制的 Client ID
   - **OAuth Client Secret**：输入 Step 3 中复制的 Client Secret

4. 在左侧面板选择 API scope：
   - 展开 **Gmail API v1** → 勾选 `https://www.googleapis.com/auth/gmail.readonly` 和 `https://www.googleapis.com/auth/gmail.send`
   - 展开 **Google Calendar API v3** → 勾选 `https://www.googleapis.com/auth/calendar`

5. 点击 **Authorize APIs** 按钮。

6. 选择 Google 账户 → 允许权限（必须是已添加为测试用户的账户）。

7. 在 **Step 2** 页面点击 **Exchange authorization code for tokens** 按钮。

8. 复制响应中的 **Refresh token** 值 — 用作 `Refresh Token`

### 注意事项

- 如果 OAuth 同意屏幕处于 "测试" 状态，则只能使用已注册为测试用户的账号。
- Refresh Token 不会过期，但如果不将 OAuth 同意屏幕切换为 "生产"，则可能每 7 天过期一次。
- 5 个 Gmail/Calendar 工具共享相同的 OAuth 认证信息。

---

## 5. 在 Moldy 中输入密钥

所有 API 密钥签发完成后，在 Moldy UI 中进行设置。

1. 登录 Moldy 应用。

2. 从侧边栏进入 **工具管理** 页面。

3. 找到要设置的工具卡片。
   - Pre-built 工具会显示蓝色 `Pre-built` 徽标。
   - 如果尚未设置密钥，则会显示黄色警告。

4. 点击 **密钥设置** 按钮。

5. 输入已签发的密钥值:

   | 工具组 | 输入字段 |
   |-----------|-----------|
   | Naver Search (5个) | Client ID, Client Secret |
   | Google Search (3个) | API Key, Search Engine ID |
   | Google Chat Send | Webhook URL |
   | Gmail / Calendar (5个) | OAuth Client ID, OAuth Client Secret, Refresh Token |

6. 点击**保存**。

7. 保存完成后，状态会变为绿色勾选图标。

> **参考**: 同一组的工具共享认证信息。例如，如果为 Naver Blog Search 设置了密钥，其他 Naver 工具也会使用相同的密钥 — 但也可以为每个工具分别设置。

---

## 6. 问题排查

### "API 密钥无效"

- 请再次检查密钥值。确认复制时前后没有包含空格。
- 对于 Google API Key，请确认相应 API(Custom Search JSON API, Gmail API 等)已启用。

### "没有权限" (403 错误)

- Naver: 请确认应用的 "使用 API" 中包含 `搜索`。
- Google: 如果 API Key 设置了 API 限制，请确认所需 API 位于允许列表中。
- Gmail/Calendar: 请确认该账号已注册到 OAuth 同意屏幕的测试用户中。

### "Refresh Token 已过期"

- 请在 OAuth Playground 中签发新的 Refresh Token，并重新输入到 Moldy。
- 长期使用时，在 Google Cloud Console 中将 OAuth 同意屏幕切换为 "生产" 可避免过期。

### Google Chat Webhook 无法工作

- 请确认 Webhook URL 是否准确 (需要复制完整 URL)。
- 请确认是否为 Google Workspace (付费) 账号。免费 Gmail 账号无法使用 Webhook。
