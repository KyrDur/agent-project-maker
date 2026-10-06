# 聊天附件 — 开发规划书（准备实现）

> 状态：规划确认进行中。背景/备选分析请参见 `chat-attachments-analysis.md`。
> 本文档定义**要做什么、如何做**（文件级任务 + 测试 + 里程碑）。
> 依据：实际源码分析（backend/frontend）+ LangChain 1.x（`langchain_core 1.4.7`）+ assistant-ui 0.14.18。
> 行号是分析时点的近似值（`~`），实现时重新确认。

---

## 1. 目标 / 非目标

### 目标
- **（显示）** 用户发送附件后仍能看到：① 在已发送消息（user 气泡）中内联显示，② 在对话统一“文件”列表中显示（与生成文件一起，用 `附件` 徽章区分）。
- **（预览）** 支持格式使用现有 artifact 预览，不支持格式显示“暂不支持 + 下载”（复用现有 fallback）。
- **（上下文）** 从文件跳转到附有该文件的对话消息（仅限已加载消息）。
- **（安全）** 通过认证·所有权保护附件访问。
- **（模型输入，后续）** Agent 实际感知附件（图片→文档）（multimodal）。

### 非目标（本次范围外，后续 phase）
- 直接编辑附件（附件为 read-only）。“复制 → 生成 artifact → 编辑”为 **P2+**。
- 上传加密（策略决策后另行处理）。
- fetch-and-scroll 跳转到分页之外的旧消息（本次仅显示标签）。

---

## 2. 当前状态（基于源码摘要）

### 后端
| 范围 | 当前 | 文件 |
|---|---|---|
| 上传 | `POST /api/uploads` → 创建 `message_attachments` 行（明文磁盘 `./data/uploads/`），`message_id`·`conversation_id` 为 null。白名单 image/text/pdf/json，20MiB | `routers/uploads.py:~67-108` |
| 下载 | `GET /api/uploads/{id}` **无认证/所有权检查** | `routers/uploads.py:~111-133` |
| 发送时关联 | `link_attachments_to_conversation` 仅设置 `conversation_id`（`message_id` 保持 null） | `services/chat_service.py:~1221-1247`, 调用处 `routers/conversation_messages.py:~73-79, ~399-405` |
| 消息读取 hydration | `WHERE conversation_id=c AND message_id IS NOT NULL` → message_id 为 null，因此 **0条 → 附件遗漏** | `services/chat_service.py:~1102-1120` |
| 响应 schema | `MessageResponse.attachments: list[MessageAttachmentBrief] | None`（id/filename/mime_type/size_bytes/url） | `schemas/conversation.py:~121-135, ~183` |
| 模型输入 | `input_payload=[{"role":"user","content":data.content}]` → `convert_to_langchain_messages` → `HumanMessage(content=<str>)`。**附件没有传给模型** | `routers/conversation_messages.py:~434`, `agent_runtime/message_utils.py:~167-178`, `runtime_component_builder.py:~746` |
| message_id 时机 | HumanMessage id 由服务器生成，**run 结束后**才确定。客户端不能指定。backfill hook 候选 = `finalize_turn` | `services/trace_storage.py: finalize_turn` |
| 生成文件 | `conversation_artifacts` + `artifact_versions`（M59），关联 `assistant_msg_id`+`logical_path`，有版本管理 | `models/conversation_artifact.py` |

### 前端
| 范围 | 当前 | 文件 |
|---|---|---|
| 上传 adapter | `MoldyAttachmentAdapter`（accept=image/text/pdf/json），`send()` 上传后转换为 `[attachment: name](url)` Markdown 链接 | `lib/chat/attachment-adapter.ts` |
| 消息转换 | 后端 `message.attachments` → assistant-ui `CompleteAttachment` 的转换**已经存在** | `lib/chat/convert-message.ts:~49-61` |
| user 气泡 | 仅渲染 `MessagePrimitive.Content`。**未使用 `MessagePrimitive.Attachments` → 发送后附件不显示** | `components/chat/assistant-thread.tsx` UserMsg(~600+) |
| composer staging | `ComposerPrimitive.Attachments` + `AttachmentChip` + `AddAttachment`(paperclip) | `assistant-thread.tsx:~1124-1135, ~1209-1242` |
| 生成文件内联 | `AssistantArtifactCards`（assistant 消息底部卡片） | `assistant-thread.tsx:~355-410` |
| 生成文件侧栏/Library | `ArtifactPanelContent`（侧栏），`ArtifactLibraryContent`（Library） | `right-rail/artifact-panel-content.tsx`, `components/artifacts/artifact-library-content.tsx` |
| 预览 registry | 16类 provider（image/pdf/docx/xlsx/pptx/hwp/mermaid/markdown/code/json/table/text/...）+ fallback（"不支持→图标+下载"） | `components/chat/artifacts/preview-registry.tsx` + `providers/`, dispatch=`artifact-preview.tsx:~15-72` |
| 标准化类型 | `ArtifactSummary`（id/path/display_name/mime_type/extension/artifact_kind/preview_url/download_url/...） | `lib/types/artifact.ts` |

### assistant-ui 0.14.18 提供的 API
- `MessagePrimitive.Attachments components={{ Image, Document, File, Attachment }}`（user 消息附件渲染，与 composer 同 shape）
- `AttachmentPrimitive.Root/Name/Remove/unstable_Thumb`, `useAttachmentSrc()`（缩略图），点击→预览对话框模式

---

## 3. 设计决策（已确定 / 未确定）

| # | 决策 | 值 | 状态 |
|---|---|---|---|
| D1 | 范围 | 分阶段：**Phase 0 安全 → P1 显示 → P2+ 模型输入 → P2+ 复制编辑** | ✅ 已确定 |
| D2 | 模型输入方式 |（P2）图片=multimodal block，文档=文本提取/RAG。按 provider 能力门控 | ✅ 方向已确定 |
| D3 | 支持类型 | 先图片 → PDF → office（文本提取） | ✅ 已确定 |
| D4 | provider 门控 | 通过能力矩阵门控，不支持的模型则 **skip 模型注入（仅显示）** | ✅ 已确定 |
| D5 | 显示 UX | **内联（user 气泡）为 primary + 统一列表为 secondary**，用 `附件` 徽章区分，点击→复用 `ArtifactPreview`，附件 **read-only** | ✅ 已确定 |
| D6 | 安全 | `GET /api/uploads/{id}` 增加认证 + 所有权（+分享链接读取） | ✅ 已确定（加密暂缓） |
| D7 | orphan GC | 未发送上传 24h 后由 cron 清理 | ✅ 已确定（默认值） |
| D8 | message_id 关联 | 在 `finalize_turn` hook 中 backfill | ✅ 已确定 |
| D9 | 文件→消息跳转 | **仅已加载消息** scroll+highlight，否则显示“较早消息”禁用标签 | ✅ 已确定（简化版，P1 包含） |
| D10 | PR/Commit 组成 | **Phase 0 + P1 一个 PR**，按阶段**拆分 commit**（P0 安全 → 后端显示 → 前端显示 → 测试） | ✅ 已确定 |
| D11 | 分享对话策略 | 分享视图中**附件和生成文件均不暴露**（从分享快照排除） | ✅ 已确定 |
| D12 | 统一列表数据 | 使用**单个后端统一端点** `GET /api/conversations/{id}/files`，标准化返回生成文件+附件（单一来源）。侧栏使用它，Library 也扩展为同一来源。*不采用前端合并（各 surface 重复）*。风险：替换现有 artifact 侧栏数据源 → 注意回归 | ✅ 已确定 |
| D13 | DB schema | **无需迁移** — `message_attachments.message_id` 列已存在（当前一直为 null）。只需填充 | ✅ 已确定 |
| O2 | 上传加密 | 全部/仅敏感 MIME/不做 | ⛳ 暂缓（后续） |
| O3 | P2（模型输入）启动时点 | P1 发布后单独进行 | ⛳ 后续 |

---

## 4. 架构 / 数据流（P1，Path A = message-scoped）

```
[发送]
 composer 上传 → POST /api/uploads → message_attachments(row, message_id=null)
 send_message(data.content, attachments[])
   → link_attachments_to_conversation（设置 conversation_id）
   → run 开始 → 流式传输 → run 结束(finalize_turn)
       └─（新增）确定 user HumanMessage id → 回填对应 attachment rows.message_id   ← D8

[读取/渲染]
 GET /messages
   → hydration（message_id 已填充，因此可 echo）  ← 现有查询原样工作
   → MessageResponse.attachments[]
   → convert-message → CompleteAttachment[]
   →（新增）UserMsg: <MessagePrimitive.Attachments components={...}>  ← 内联 primary  (D5)
   →（新增）统一文件列表（侧栏）：GET /api/conversations/{id}/files（生成+附件标准化、徽章）← secondary (D5/D12)
        点击 → 复用 ArtifactPreview（支持/不支持）                      ← 预览        (D5)
        "跳转到对话" → 按 message_id scroll（已加载）/标签（未加载）        ← navigation   (D9)

[安全]  GET /api/uploads/{id} → 认证 + 所有权/分享检查  ← Phase 0 (D6)
```

核心：**附件采用 message-scoped**（D8），因此在 reload/分享/分支中准确。统一列表由**后端 `/files` 端点**（D12）提供，将两个来源标准化合并为单一响应（前端不按 surface 分别合并）。

---

## 4.5 核心机制 & 数据契约（实现规格 — 已验证）

### M1. message_id 关联 — **确定 Option B（post-run 回填）**
- HumanMessage id 在 send 时无法由 moldy 控制（`convert_to_langchain_messages` 仅创建 `HumanMessage(content=...)`，未指定 id → 由 checkpointer 生成）。∴ 无法使用 send-time id（Option A）。
- 位置：在 `services/conversation_stream_service.py::finalize_trace()`（流结束后）解析本轮 **user HumanMessage id**，并关联本次 send 的附件。
- **id 匹配规则**：`list_messages_from_checkpointer` 使用 `parse_msg_id(msg.id, conversation_id, idx)`（`message_utils.py:111`, `parse_msg_id:24-30`）生成 user 消息 id → 回填也必须用**相同规则**生成同一 UUID，才能与 hydration 匹配。
- ⚠️ **注意（实现关键点）**：不要断定 `msg_id_sink[0]`/`idx=0` 就是 user 消息。必须从 post-run checkpoint 状态中**准确识别本轮新增的 HumanMessage**（最后一个 HumanMessage 或 content 匹配），再按其 (id, idx) parse。
- 新增 helper（只关联本次 send 的 attachment_ids → 防止跨 send 错误关联）：
  ```python
  async def link_attachments_to_message(db, *, attachment_ids, message_id: str) -> None:
      await db.execute(update(MessageAttachment)
          .where(MessageAttachment.id.in_(attachment_ids),
                 MessageAttachment.message_id.is_(None))
          .values(message_id=message_id))
  ```
- attachment_ids 在 send 时放入 run/turn 上下文（run 记录或 stream 上下文）并一路传到 finalize。

### M2. 分享排除(D11) — **确定（单函数门控）**
- 分享读取使用与认证读取**相同的** `list_messages_from_checkpointer(db, conversation, user_id=None)`（`routers/shares.py` `GET /api/shares/{token}/messages`）。
- 当前：附件 hydration（`chat_service.py:~1102-1120`）**没有** user_id 门控 → 一旦补上 message_id，附件会暴露在分享中。artifact（`~1122-1136`）已有 `if user_id is not None` 门控 → 分享中已排除。
- 变更：附件 hydration 也包在 `if user_id is not None:` 内 → 分享（user_id=None）中**附件·生成文件都不暴露**。（生成文件无需额外修改。）

### M3. 统一文件端点(D12) — `GET /api/conversations/{id}/files`
- 所有权/参与 guard。合并 `conversation_artifacts`（生成）+ `message_attachments`（附件，message_id 非空），按 `created_at` 排序，添加 `source` 标签。
- `FileItem` 标准 shape（前后端共用）：
  ```ts
  type FileItem = {
    source: 'generated' | 'attached'
    id: string
    name: string            // display_name | filename
    mime_type: string
    extension?: string
    kind?: string           // artifact_kind (generated)
    size_bytes?: number
    preview_url: string     // generated=artifact preview_url / attached=/api/uploads/{id}
    download_url: string
    message_id?: string      // attached→user 消息 / generated→assistant_msg_id
    created_at: string
    editable: boolean        // generated=true, attached=false (read-only, D5)
  }
  ```
- 前端对于内联用 `MessageAttachmentBrief`、列表用 `FileItem`，都通过现有 `ArtifactPreview` registry dispatch（不支持→fallback "不支持预览 + 下载"）。

### M4. 文件→消息跳转(D9)
- 为每个消息气泡添加 `data-moldy-message-id={id}` 锚点（若没有）。
  ```ts
  function jumpToMessage(messageId?: string) {
    if (!messageId) return
    const loaded = runtimeMessages.some(m => m.id === messageId)  // 基于 state（兼容虚拟化）
    if (loaded) {
      document.querySelector(`[data-moldy-message-id="${messageId}"]`)?.scrollIntoView({ block: 'center' })
      highlight(messageId)
    } else { /* "较早消息" 禁用标签/tooltip */ }
  }
  ```

### M5. i18n 新增 Key (ko/en)
`chat.files.attachedBadge`("附件"), `chat.files.generatedBadge`("生成"), `chat.files.jumpToMessage`("跳转到对话"), `chat.files.notInLoaded`("较早消息"), `chat.files.unsupportedPreview`("不支持预览").

---

## 5. 各 Phase 工作（文件级检查清单）

### Phase 0 — 安全（建议前置，S~M）
- [ ] **上传访问 guard**：在 `routers/uploads.py` 的 `GET /api/uploads/{id}` 添加 `Depends(get_current_user)` + 所有权检查（`MessageAttachment.user_id == user.id` 或对话参与者）。同源 cookie 下 `<img src>` 也能正常工作。
- [ ] **分享链接场景**：若分享对话查看者需要看到附件，则增加基于 share token 的读取允许路径（或 P1 简化为分享时隐藏附件 — 需要决策）。
- [ ] **orphan GC**：使用 APScheduler job 清理 `message_id IS NULL AND created_at < now()-24h` 的上传，同时删除存储文件。
- [ ] 测试：未认证/其他用户下载 403/404，本人 200，share token 场景，GC job 单元测试。

### P1 — 显示（M，4~6天）

**后端**（无需迁移 — D13）
- [ ] **message_id 关联(D8)** — 使用 §4.5 的机制。以下两个候选在实现时确定（验证中）：
  - **A（推荐，send-time id）**：send 时由 moldy 生成 user 消息 UUID 并赋给 HumanMessage，同时在 `link_attachments_to_conversation` 中将同一 id 设置到 `message_attachments.message_id`。如果 checkpointer round-trip 能保留 id，则无需 post-run 回填。
  - **B（fallback，post-run 回填）**：若 A 不可行，则在 `finalize_turn`（`services/trace_storage.py`）解析本轮 user HumanMessage id，并 UPDATE 本次 send 的 attachment_ids。（将 attachment_ids 传入 run/turn 上下文）
- [ ] hydration（`chat_service.py:~1102-1120`）保持现有查询（现在会匹配）。如有遗漏再补充。
- [ ] **分享排除(D11)**：在分享 snapshot builder 中**排除**消息 `attachments` 和生成文件（artifacts）。（§8 — 先确认当前分享是否暴露生成文件，若暴露则包含移除这一策略变更。）统一列表（侧栏/Library）在分享视图中不暴露。
- [ ] **统一文件端点(D12)**：`GET /api/conversations/{id}/files` — 将 `conversation_artifacts`（生成）+ `message_attachments`（附件）标准化为 §4.5 `FileItem` 并合并（按创建时间排序），添加 `source` 标签。权限使用对话所有权/参与 guard。内联（per-message）单独使用 `MessageResponse.attachments` echo（与此端点无关）。
- [ ] 测试：发送附件→GET /messages echo，`/files` 返回生成+附件标准化结果·排序·source，reload 保持，分支/多次发送能按消息准确映射，分享视图中附件·生成文件不暴露。

**前端**
- [ ] **内联渲染(D5, primary)**：在 `UserMsg`（`assistant-thread.tsx`）添加 `<MessagePrimitive.Attachments components={{ Image, Document, File, Attachment }}/>`。图片=`unstable_Thumb`+`useAttachmentSrc()` 缩略图，文档=文件 chip。点击 → 预览。
- [ ] **附件预览 adapter**：将 `CompleteAttachment`/`MessageAttachmentBrief` → `ArtifactSummary` 类标准 shape（id/filename/mime/extension/preview_url=download_url=`/api/uploads/{id}`/`source:'attached'`）。通过现有 `ArtifactPreview` registry dispatch（支持/不支持 fallback 自动处理）。
- [ ] **统一文件列表(D5, secondary)**：将 `ArtifactPanelContent`（侧栏）切换为消费 **`GET /files`（D12）**（替换现有 artifacts-only 数据源 — 注意回归）。每项显示 **`附件`/`生成` 徽章**（或分组标题“我发送的文件”/“生成的文件”）。点击 → 同一 `ArtifactPreview`。*全局 `ArtifactLibraryContent` 统一为后续工作。*
- [ ] **附件 read-only(D5)**：附件项不显示 edit/save 操作，只提供 preview·download·"跳转到对话"。
- [ ] **文件→消息跳转(D9)**：在列表/预览中添加 "跳转到对话" 操作。目标 message_id **存在于当前已加载消息 set 中**时，scroll+highlight 到对应气泡（为消息气泡添加 `data-moldy-message-id` 锚点）；否则显示“较早消息”禁用标签/tooltip。（确认虚拟化后按 state 判断）
- [ ] 测试(vitest)：内联渲染（图片/文档）、不支持格式 fallback、统一列表徽章区分、read-only（无编辑按钮）、跳转操作（已加载/未加载分支）。

**E2E**
- [ ] 发送附件（图片+文档）→ user 气泡内联显示 → reload 后保持 → 统一列表中以 `附件` 徽章暴露 → 打开预览 → "跳转到对话" 生效 → 下载链接。

### P2+ — 模型输入：图片（M~L，后续）
- [ ] 在消息组装路径中将图片附件注入 LangChain `image` content block：`HumanMessage(content_blocks=[{type:'text',...},{type:'image',base64,mime_type}])`。位置 = `messages_history` 生成/`convert_to_langchain_messages` 上游。
- [ ] **provider 能力门控(D4)**：仅当 `(provider, model)` 支持 vision 时注入，否则仅显示（skip 注入）。Hancom 网关/openai_compatible 不保证支持 → 保守处理。
- [ ] 检查 token/compaction 影响（media 会让 prompt token 暴增 → 与 context-window profile 联动）。
- [ ] 测试：vision 模型注入/不支持 vision 时 skip，token 计数。

### P2+ — 文档模型输入（L，后续）
- [ ] PDF → `file` content block（按 provider：Anthropic document / OpenAI base64+filename / Google PDF）。注意 OpenAI Chat Completions 拒绝 URL 文件。
- [ ] office/csv → 没有原生 block → 服务器文本提取（python-docx/openpyxl 等）或复用现有 RAG read-tool 模式。
- [ ] 大文件/重复使用 → 通过 Files API `file_id` 引用避免重复发送。

### P2+ — 复制 → 编辑（M，后续）
- [ ] "将此附件复制为工作文件" 操作：`message_attachments` 字节 → 复制到 `conversation_artifacts`（新行/版本）→ 进入可编辑 lifecycle。原始附件保持不变。

---

## 6. LangChain multimodal 参考（用于 P2 实现）

LangChain 1.x 标准 content block（`langchain_core/messages/content.py`）：
- 图片 `ImageContentBlock(:~498)`：`{type:'image', base64|url, mime_type}`
- 文件/PDF `FileContentBlock(:~721)`：`{type:'file', base64|url, mime_type}`（docx/PDF 等非图片）
- 纯文本 `PlainTextContentBlock(:~651)`：`{type:'text-plain', text}`
- 创建：`HumanMessage(content_blocks=[...])`（`messages/human.py:43-56`）或 factory `create_image_block`/`create_file_block`。

provider 矩阵：
| provider | 图片 | 文件/PDF | 注意 |
|---|---|---|---|
| OpenAI | image_url | base64/file_id | **拒绝文件 URL（Chat Completions）**，需要文件名 |
| Anthropic | ✅ | document(PDF/text/url) | |
| Google | inline_data | PDF base64/file_uri | |
| OpenRouter/compat/Hancom | 取决于模型 | 取决于模型 | **不保证 → 必须门控** |

- 不支持的 block → `ValueError`（无 silent fallback）。deepagents 会传递，但 media 影响 token/compaction。`model_factory` 只负责模型配置 — 注入在消息组装处完成。

---

## 7. 测试计划（摘要）
- **后端**：上传 guard（403/404/200/share）、GC job、message_id 回填、hydration echo、分支映射。（pytest aiosqlite）
- **前端**：内联渲染、不支持 fallback、统一列表徽章、read-only、跳转分支。（vitest）
- **E2E**：发送→内联→reload→列表→预览→跳转→下载。（Playwright，throwaway 栈）
- 回归：现有 artifact 渲染/预览/侧栏不受影响，聊天 E2E sweep green。

---

## 8. 风险 / 未解决问题
**已解决的决策**（参见上方 D 表）：PR 组成（D10，P0+P1 一个 PR/commit 分拆）、分享策略（D11，附件·生成均不暴露 — M2）、统一列表数据（D12，后端 `/files` 端点）、迁移（D13，无）、message_id（M1，post-run 回填）。

**剩余风险 / 后续**
- **（实现关键点，M1）**：准确识别本轮 user HumanMessage id — 禁止断定 `msg_id_sink[0]`/`idx=0`。必须通过单元测试验证多轮·分支映射。
- **侧栏数据源替换(D12)**：现有 artifact 侧栏迁移到 `/files`，需注意现有 artifact 渲染回归 + 回归测试。
- **虚拟化**：transcript 虚拟化时，“已加载判定”应基于 runtime state 而非 DOM（M4）。
- **provider 门控(P2)**：system LLM 为 Hancom 网关 → 不保证 vision。未处理时 run 会失败（`ValueError`）— 必须能力门控。
- **token/成本(P2)**：base64 media 会让 prompt token 暴增 → 联动 context-window/compaction。
- **O2 加密（暂缓）**：策略未定（后续）。

---

## 9. 里程碑 / 工作量
| 阶段 | 范围 | 工作量 |
|---|---|---|
| Phase 0 | 上传认证/所有权/分享 + orphan GC | S~M |
| **P1** | message_id 回填 + 内联 + 统一列表（徽章）+ read-only + 文件→消息跳转（简化版） | **M（4~6天）** |
| P2（图片） | image content block 注入 + 门控 + token | M~L |
| P2（文档） | PDF/office/RAG/file_id | L |
| P2+ | 复制→编辑 | M |

**①显示（Phase 0 + P1）合计 ≈ 5~8天。** ②完整模型输入另需 L~XL（1.5~3周）。

---

## 10. PR / Commit 计划（D10 — Phase 0 + P1 一个 PR，拆分 commit）
分支示例：`feature/chat-attachments-display`。Commit 顺序（每个 commit 本身都保持 green）：
1. `fix(security): authn+ownership guard on GET /api/uploads/{id}`（+ orphan GC job）— Phase 0
2. `feat(chat): backfill message_attachments.message_id on turn finalize` — M1（后端 + 单元测试）
3. `feat(chat): gate attachment hydration to authed views (exclude from shares)` — M2
4. `feat(chat): unified conversation files endpoint (generated + attached)` — M3 `/files` + FileItem
5. `feat(chat): render user attachments inline on the message bubble` — 前端内联（MessagePrimitive.Attachments）+ 预览 adapter
6. `feat(chat): show attachments in the file list with a badge + jump-to-message` — 统一列表（侧栏）+ read-only + M4 跳转 + i18n
7. `test(e2e): attachment send → inline → reload → list → preview → jump` — E2E

## 11. 验收标准（Definition of Done）
- 未认证/其他用户访问 `GET /api/uploads/{id}` → 拒绝。仅本人/参与者返回 200。
- 未发送上传由 GC 清理（24h）。
- 发送图片·文档附件 → **在 user 气泡内联**显示（图片=缩略图，文档=chip）→ **reload 后保持**。
- 统一文件列表（侧栏）中同时显示生成+附件，并用 `附件`/`生成` **徽章区分**；点击可预览（支持格式渲染 / 不支持则“暂不支持 + 下载”）。
- 附件**不可 edit**（仅 preview·download·跳转）。
- 从文件点击 "跳转到对话" → 若消息已加载则滚动+高亮 / 否则显示“较早消息”标签。
- **分享视图中附件·生成文件均不暴露。**
- 多轮/分支中附件映射到**正确的 user 消息**。
- 回归：现有 artifact 侧栏/预览/Library 正常，vitest·聊天 E2E sweep green。

## 12. 开始实施
所有核心决策均已确定（仅 O2 加密暂缓）。可从上方 commit 1（安全）开始依次进行。实现第一步先打开 `conversation_stream_service.finalize_trace` + `parse_msg_id` 路径，确定 M1 的“识别本轮 user 消息 id”后继续。
