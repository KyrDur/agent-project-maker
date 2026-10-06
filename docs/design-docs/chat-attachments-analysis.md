# 聊天附件 — 开发规划分析（决策前阶段）

> 目的：为“正确处理附件”预先分析**需要考虑的事项**、**需要决定的事项**、**工作量**。实现决策将在用户确定本文档中的“决策项”后，另行进入 SPEC/plan。
> 依据：backend/frontend 源码分析 + LangChain 1.x（`langchain_core 1.4.7`）源码 + assistant-ui 0.14.18 + assistant-ui 附件文档。

---

## 0. 核心重新定义 — “附件处理”是两个独立功能

| | 内容 | 当前状态 | 价值 |
|---|---|---|---|
| **① 显示(display)** | 将用户发送的附件再次显示在 transcript（user 气泡）中 | ❌ 发送后消失（仅存在 composer staging） | “我发送了什么”的 UX |
| **② 模型输入(ingestion)** | Agent 实际看到附件文件的**内容**（图片/文档） | ❌ **0%** — 模型只接收文本 | “Agent 理解附件” — 真正功能 |

两个功能可以**独立**发布。即使只做 ① 也有价值（确认已发送内容），② 是与 ① 分开的后端工作（消息组装 + provider gating）。**最大的决策是“做到什么范围”。**

---

## 1. 当前状态（已确认）

### 后端
- **模型只接收文本。** `send_message` → `input_payload=[{"role":"user","content":data.content}]` → `convert_to_langchain_messages`（message_utils.py:167）→ `HumanMessage(content=<string>)`。附件既未从磁盘读取，也未注入 content block。Agent 甚至不知道附件存在。
- **附件保存**：`message_attachments` 行。上传时 `message_id`·`conversation_id` 为 null → 发送时 `link_attachments_to_conversation` 仅设置 `conversation_id`（`message_id` 仍为 null）。
- **读取遗漏**：GET /messages hydration 以 `conversation_id == c AND message_id IS NOT NULL` 过滤 → 因 message_id 为 null，得到 **0 条 → 附件从响应中遗漏**。
- **安全缺口**（多用户环境中重要）：
  - `GET /api/uploads/{id}` **无认证** — 只要知道 UUID，任何人都能下载。
  - 上传文件**未加密**（明文保存在磁盘，`./data/uploads/`）。
  - orphan（未发送）上传**未实现 GC job**。
  - 白名单：image/*, text/*, application/pdf, application/json, 20MiB。
- **message_id 时机**：HumanMessage id **由服务器生成，直到 run 结束后**才确定 → Path A 需要在 `finalize_turn` 类 hook 中 backfill。客户端无法预先指定。

### 前端
- **生成文件（artifact）已经支持丰富渲染**：preview registry 16 类（image/pdf/docx/xlsx/pptx/hwp/mermaid/markdown/code/json/table/...）、右侧栏、Library 页面、assistant 消息内联卡片（`AssistantArtifactCards`）。
- **用户附件发送后完全不显示。** `convert-message.ts` 已经包含 `message.attachments` → assistant-ui `CompleteAttachment` 的转换代码（只需后端 echo 即可）。但 user 气泡中**未使用** `MessagePrimitive.Attachments`。
- assistant-ui 0.14.18：提供 `MessagePrimitive.Attachments components={{ Image, Document, File, Attachment }}` + `useAttachmentSrc()` + `AttachmentPrimitive.unstable_Thumb`（缩略图）+ 点击→预览对话框模式。

---

## 2. LangChain 1.x 推荐方式（若实现②）

**不是 Markdown 链接文本，而是以标准 content block 发送。** `HumanMessage(content_blocks=[...])`：
- **图片** → `{type:"image", base64, mime_type}`（或 url）
- **PDF** → `{type:"file", base64, mime_type:"application/pdf"}`（provider 支持时）
- **.txt/.md** → `{type:"text-plain", text}`
- **docx/xlsx/pptx/csv 等** → **没有原生 block** → 服务器提取文本后注入

### provider 支持矩阵
| provider | 图片 | PDF/文件 | 备注 |
|---|---|---|---|
| **OpenAI** | ✅ image_url | ✅ base64/file_id（**Chat Completions 拒绝文件 URL**，需要文件名） | |
| **Anthropic** | ✅ | ✅ document（PDF/text/url） | 将文件作为 document block |
| **Google** | ✅ inline_data | ✅ PDF base64/file_uri | |
| **OpenRouter/openai_compatible/Hancom 网关** | ⚠️ 取决于模型 | ⚠️ 取决于模型 | **不保证** — 当前 system 模型为 Hancom 网关 |

- **不支持的 block → `ValueError`（无 silent fallback）** → 必须按 `(provider, model)` 能力进行**门控**。
- deepagents 会原样传递 multimodal HumanMessage。但 **media 会显著增加 token 数，影响 auto-compaction 阈值**（与 context-window 工作联动）。
- `model_factory` 不处理 multimodal — 工作应进入**消息组装路径**（messages_history 生成处）。
- **替代方案（已存在）**：Assistant Agent 不使用 multimodal，而采用 **read-as-tool(RAG)** 模式（`list_agent_files`→`read_agent_file`→以文本回答）。对文档 Q&A 也有效，且已完成接线。

---

## 3. 生成文件 vs 附件文件（UI 是否统一展示？）

| | 附件（输入）`message_attachments` | 生成（输出）`conversation_artifacts` (M59) |
|---|---|---|
| 谁 | 用户上传 | Agent 工具（write_file 等） |
| 何时 | 发送前 | run 中/后 |
| 位置 | 应显示在 user 气泡中（目标） | 右侧栏/Library/assistant 内联卡片（已存在） |
| 版本 | 无 | 有版本管理 |
| 预览 | 无（新增） | preview registry 16 类（可复用） |

**需要决策**：两者视觉上是否统一（统一文件 UI），或区分（输入=中性/次要，输出=主要）。位置天然不同（user 气泡 vs 侧栏）。

---

## 4. 决策项（需要用户确定）

| # | 决策 | 选项 | 推荐 |
|---|---|---|---|
| **D1. 范围** | 做到哪里？ | (a) **仅显示** / (b) 显示+模型输入(multimodal) / (c) 显示+模型输入(RAG read-tool) | **分阶段**：先 (a)，之后 (b) — 见下方 phasing |
| **D2. 模型输入方式** | 选择 (b/c) 时 | multimodal content blocks vs 服务器文本提取(RAG) | 图片=multimodal，文档=文本提取/RAG 混合 |
| **D3. 支持类型** | 接收什么 | 仅图片 / +PDF / +office(docx·xlsx) | 先图片，再 PDF |
| **D4. provider 门控** | vision 不支持（Hancom 网关等）时 | 文本提取 fallback / 拒绝附件+警告 / 仅显示 | 能力门控 + 不支持时仅显示（skip 模型注入） |
| **D5. 显示 UX** | user 气泡渲染 | 图片缩略图+文件 chip / 点击时预览（复用侧栏 vs lightbox） / 与 generated 视觉区分 | 缩略图+chip，点击→复用现有 ArtifactPreview 侧栏 |
| **D6. 安全** | 上传访问/加密 | 增加 GET 认证？加密？ | **认证实际上是必须的**（多用户漏洞），加密属于策略决策 |
| **D7. orphan GC** | 未发送上传保留多久 | 24h/7d/… | 单独 cron，建议 24h |
| **D8. message_id 关联** | Path A 回填时机 | finalize_turn hook | finalize_turn |

---

## 5. 工作量 / 阶段建议

> 每个 phase 都可独立发布。推荐顺序如下。

- **Phase 0 — 安全（建议先做，S~M）**：`GET /api/uploads/{id}` 所有权/认证 guard + orphan GC job。*多用户环境中可猜 UUID 下载属于真实漏洞，与显示功能无关也应优先处理。*（D6/D7）
- **Phase 1 — 显示（M，2~3天）**：后端在 `finalize_turn` 回填 `message_attachments.message_id` + hydration echo → 前端用 `MessagePrimitive.Attachments` 在 user 气泡渲染（缩略图/chip）+ 点击预览（复用 ArtifactPreview）。即使没有模型输入，也能完成“看到已发送附件”。（D5/D8）— 后端+前端+测试+E2E。
- **Phase 2 — 模型输入：图片（M~L）**：在消息组装路径将图片附件注入 `image` content block + `(provider,model)` vision 门控 + 检查 token/compaction 影响。（D2/D4）— 以后端为主。
- **Phase 3 — 文档（L）**：PDF=file block（按 provider），office=服务器文本提取或 RAG read-tool，复用 `file_id`。（D3）— 后端 + 提取流水线。

**大致总量**：做到①显示（Phase 0+1）= **M（3~5天）**。做到②完整模型输入（Phase 2+3）= **额外 L~XL（1.5~3周）**，原因是 provider 门控、提取、token 管理。

---

## 6. 风险 / 注意事项

- **安全**：开启显示功能会让附件 URL 暴露更多 → 先做 Phase 0（认证）更安全。
- **provider 门控**：当前 system LLM 为 Hancom 网关，不能保证 vision → 必须有模型级能力矩阵 + 不支持时 graceful 处理（未处理会因 `ValueError` 导致 run 失败）。
- **token/成本**：base64 图片·PDF 会让 prompt token 暴增 → 与 context-window/compaction 联动，并考虑通过 `file_id` 引用避免重复发送。
- **数据模型**：附件应采用 message-scoped（Path A），这样 reload/分享/分支才准确。conversation-scoped（Path B）映射较弱，不推荐。
