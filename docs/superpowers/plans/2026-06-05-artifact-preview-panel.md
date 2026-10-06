# Artifact Preview Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LLM/skill 执行过程中生成的文件不再只依赖最终回答中的 Markdown 链接，而是通过 SSE 文件事件和右侧 Artifact Panel 即时发现、列出、preview、下载。

**Architecture:** 保持 Moldy 现有的 Deep Agents runtime、`execute_in_skill`、`message_events` SSE persistence、conversation ownership 模型。文件由 DB artifact manifest 和 storage backend 管理，UI 扩展为 event-driven right rail 和 preview provider registry。

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Deep Agents `create_deep_agent`, LangGraph checkpointer, Next.js 16, React 19, Jotai, TanStack Query, EventSource SSE, existing `react-markdown`, `mermaid`, `react-syntax-highlighter`.

---

## 1. 背景与核心判断

当前 Moldy 主要通过 `OUTPUT_FILES` 文本和 `/api/conversations/{conversation_id}/files/{file_path}` 链接暴露 skill 执行结果文件。这种方式实现简单，但用户在收到最终回答前很难知道生成了哪些文件，也难以在聊天旁持续浏览多个候选图片、报告草稿、图表、CSV、PDF 等产物。

本次功能的核心，是将“LLM 创建了文件”从仅在回答文本中显示链接，提升为把文件创建/修改本身作为 runtime 事件。

```text
execute_in_skill writes files
-> backend detects artifact delta
-> backend persists artifact manifest/version
-> SSE emits file_event
-> frontend artifact store updates
-> right rail ArtifactPanel renders tree + preview
```

从 LangChain/Deep Agents 角度看，没有必要单独创建新的 LangGraph runtime。按 `framework-selection` 标准，此功能结合了长时运行 agent、tool call、skill、filesystem、persistence，因此应继续使用现有基于 Deep Agents 的 top-level runtime。按 `deep-agents-core` 标准，file management、skills、checkpointer 也应通过 deepagents 设置和周边服务扩展；如果重写独立 agent runtime，会与 Moldy 的 `message_events`、checkpointer、credential、permission 流程重复。

## 2. 实际代码审计摘要

### Backend

- [backend/app/config.py](/Users/chester/dev/ref/natural-mold/backend/app/config.py): 存在 `conversation_output_dir = "./data/conversations"`, `upload_dir = "./data/uploads"`。目前还没有 artifact storage 设置。
- [backend/app/marketplace/skill_runtime.py](/Users/chester/dev/ref/natural-mold/backend/app/marketplace/skill_runtime.py): 通过 `output_dir = data/conversations/{thread_id}` 确定 skill 产物位置。
- [backend/app/agent_runtime/executor.py](/Users/chester/dev/ref/natural-mold/backend/app/agent_runtime/executor.py): `execute_in_skill` 有限度地允许执行 Python/curl，并在执行后把 output dir 文件列表附加为 `OUTPUT_FILES`。这是最现实的第 1 阶段 artifact 检测点。
- [backend/app/agent_runtime/streaming.py](/Users/chester/dev/ref/natural-mold/backend/app/agent_runtime/streaming.py): `emit()` 一次性处理 SSE 发送、`EventBroker` publish、trace sink、DB persistence flush。`file_event` 也应走这条路径，这样 resume 和 message event 保存才自然。
- [backend/app/agent_runtime/event_names.py](/Users/chester/dev/ref/natural-mold/backend/app/agent_runtime/event_names.py): SSE event name 常量文件。需要添加 `FILE_EVENT = "file_event"`。
- [backend/app/models/message_event.py](/Users/chester/dev/ref/natural-mold/backend/app/models/message_event.py): 将 assistant turn 的 event stream 以 append-only 方式保存。适合文件事件 replay。
- [backend/app/models/message_attachment.py](/Users/chester/dev/ref/natural-mold/backend/app/models/message_attachment.py): 用户上传 input file 的模型。artifact 是 LLM/runtime output file，因此单独建模更安全。
- [backend/app/routers/uploads.py](/Users/chester/dev/ref/natural-mold/backend/app/routers/uploads.py): 上传文件以 UUID 为基础保存在 local disk。注释中说明切换 S3 时只替换 storage backend，因此 artifact 也可沿用同一方向。
- [backend/app/routers/conversations.py](/Users/chester/dev/ref/natural-mold/backend/app/routers/conversations.py): 现有文件下载 endpoint 从 `data/conversations/{conversation_id}` 提供文件并生成 image preview。新增 artifact API 时，也要一并检查该 endpoint 的 ownership guard。
- [backend/app/routers/shares.py](/Users/chester/dev/ref/natural-mold/backend/app/routers/shares.py), [backend/app/services/share_service.py](/Users/chester/dev/ref/natural-mold/backend/app/services/share_service.py): 分享链接以 conversation snapshot 为中心。artifact 需要可通过 share token 访问的独立 public read endpoint。

### Frontend

- [frontend/package.json](/Users/chester/dev/ref/natural-mold/frontend/package.json): 已有 `mermaid`, `react-markdown`, `react-syntax-highlighter`。Markdown、Mermaid、code preview 的第 1 阶段实现无需新增库即可完成。
- [frontend/src/lib/types/index.ts](/Users/chester/dev/ref/natural-mold/frontend/src/lib/types/index.ts): `SSEEventType`, `SSEEvent` union 中没有 `file_event` 类型。
- [frontend/src/lib/sse/parse-sse.ts](/Users/chester/dev/ref/natural-mold/frontend/src/lib/sse/parse-sse.ts): SSE parser 以 generic 方式解析 event，因此新增 event type 的改动很小。
- [frontend/src/lib/chat/use-chat-runtime.ts](/Users/chester/dev/ref/natural-mold/frontend/src/lib/chat/use-chat-runtime.ts): 需要在 SSE event switch 中增加 `file_event` 处理。
- [frontend/src/lib/stores/chat-right-rail.ts](/Users/chester/dev/ref/natural-mold/frontend/src/lib/stores/chat-right-rail.ts): right rail mode 为 `none | subagent | tool-result | outline`。增加 `artifacts`。
- [frontend/src/components/chat/right-rail/chat-right-rail.tsx](/Users/chester/dev/ref/natural-mold/frontend/src/components/chat/right-rail/chat-right-rail.tsx): 右侧 panel shell 已存在。这里很适合添加 `ArtifactPanelContent`。
- [frontend/src/components/chat/markdown-content.tsx](/Users/chester/dev/ref/natural-mold/frontend/src/components/chat/markdown-content.tsx): inline Markdown、image、Mermaid rendering 已存在。保留该功能，side artifact panel 仅用于“以文件形式生成的 durable artifact”。
- [frontend/src/lib/chat/tool-ui-registry.ts](/Users/chester/dev/ref/natural-mold/frontend/src/lib/chat/tool-ui-registry.ts): 有 tool result UI registry。Artifact preview registry 与 tool UI 分离，但可以参考其模式。

## 3. 可借鉴的模式

### LambChat 类文件/文档 preview 模式

可借鉴的是“把生成文件像独立文件库一样展示的 UX”。但 PDF、文档、CAD、项目 preview 并不能全部由单一库解决。通常不同文件类型需要不同 provider，高级文档 preview 需要服务端转换或专用 viewer。

可直接引入 Moldy 的内容如下。

- 将聊天正文 inline preview 与右侧 durable artifact preview 分离。
- 建立基于文件扩展名/MIME 的 provider registry。
- 对无法 preview 的文件，也稳定提供 metadata、download、open original。
- 长期可将 PDF、Office、CAD、project preview 作为 provider plugin 接入。

### JoySafeter 类 file event 模式

可借鉴的是 backend 将文件 write/update/delete 提升为 UI event 的流程。

Moldy 不直接复制 WebSocket/run model。既然已有 SSE、`message_events`、`EventBroker`、broker resume，最优做法是把 `file_event` 放入现有 stream。

第 1 阶段实现即使没有 sandbox write proxy 也可以完成。比较 `execute_in_skill` 执行前后的 output dir snapshot，将新文件/修改文件 ingest 为 artifact，并在 tool result 后立即 emit `file_event`。之后如有需要，可以增加 output dir polling，最终再用 sandbox/file backend write proxy 提升实时性。

## 4. 设计原则

1. **将 MessageAttachment 与 Artifact 分离。**<br>
   `MessageAttachment` 是用户输入文件。`ConversationArtifact` 是 agent/runtime 输出文件。权限、lifecycle、share、versioning 要求不同。

2. **Event log 不是 source of truth。**<br>
   `message_events` 用于 replay 和 UI stream。artifact 列表的 source of truth 是 DB manifest 和 storage object。

3. **不将 LLM 建议的 path 信任为 storage path。**<br>
   将用于 UI 显示的 `logical_path` 与实际存储位置 `object_key` 分离。实际 storage key 基于 UUID artifact id/version id。

4. **采用 local-first，并为 S3/MinIO-ready 做准备。**<br>
   第 1 阶段实现使用 local disk 就足够。但先建立 storage interface，并设计 API 不依赖具体 storage backend。

5. **右侧面板专用于 durable file artifact。**
   保留现有 inline Markdown image、Mermaid、code rendering。不要把回答正文中的所有 inline content 都移到 artifact panel。

6. **preview 通过 addon/provider registry 扩展。**
   PDF、Office、CAD、Excalidraw、Mermaid、code 分别由不同 provider 负责。不要绑定到单一 viewer 库。

7. **将 Generated File Library 纳入第 1 阶段范围。**
   如果只先做 Artifact Panel，把全局文件库推迟，之后就要重新拆改 DB/API/UI。从一开始就把 `conversation_artifacts` 设计为对话面板与全局 Generated Files Library 共用的单一索引。

## 5. Backend 设计

### 5.1 数据模型

新增表。

```text
conversation_artifacts
- id UUID PK
- user_id UUID FK users.id NOT NULL
- agent_id UUID FK agents.id NOT NULL  # 用于 library 过滤/统计的 denormalized key
- conversation_id UUID FK conversations.id NOT NULL
- assistant_msg_id TEXT NOT NULL  # stream_agent_response run_id，与 message_events.assistant_msg_id 相同
- run_id TEXT NOT NULL            # assistant_msg_id alias；API/event 中以 run_id 暴露
- tool_call_id TEXT NULL
- source_tool_name TEXT NULL
- logical_path TEXT NOT NULL
- display_name TEXT NOT NULL
- extension TEXT NULL
- mime_type TEXT NOT NULL
- artifact_kind TEXT NOT NULL  # image | video | audio | pdf | markdown | html | code | document | data | cad | other
- size_bytes BIGINT NOT NULL
- sha256 TEXT NOT NULL
- current_version_id UUID NULL
- status TEXT NOT NULL  # writing | ready | deleted | failed
- is_favorite BOOLEAN NOT NULL DEFAULT false
- last_opened_at TIMESTAMPTZ NULL
- preview_count INTEGER NOT NULL DEFAULT 0
- download_count INTEGER NOT NULL DEFAULT 0
- branch_checkpoint_id TEXT NULL
- linked_message_ids JSONB NULL   # message_events.linked_message_ids snapshot，用于 UI message 匹配
- metadata_json JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMPTZ NOT NULL
- updated_at TIMESTAMPTZ NOT NULL
```

```text
artifact_versions
- id UUID PK
- artifact_id UUID FK conversation_artifacts.id NOT NULL
- version_number INTEGER NOT NULL
- storage_provider TEXT NOT NULL  # local | s3
- bucket TEXT NULL
- object_key TEXT NOT NULL
- original_filename TEXT NOT NULL
- size_bytes BIGINT NOT NULL
- sha256 TEXT NOT NULL
- metadata_json JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMPTZ NOT NULL
```

推荐的 constraint/index：

- `conversation_artifacts(conversation_id, assistant_msg_id, logical_path)` unique
- `conversation_artifacts(user_id, conversation_id, created_at)`
- `conversation_artifacts(conversation_id, assistant_msg_id, updated_at)`
- `conversation_artifacts(user_id, created_at)`
- `conversation_artifacts(user_id, agent_id, created_at)`
- `conversation_artifacts(user_id, artifact_kind, created_at)`
- partial index: `conversation_artifacts(user_id, created_at) WHERE is_favorite = true`
- `artifact_versions(artifact_id, version_number)` unique

以每个 `run_id` 下的 path unique 作为首要判据。同一个 `report/final.md` 在不同执行中再次生成时，显示为独立 artifact，并在 UI 中按执行分组。后续“把相同 logical path 作为 conversation-level 文档进行 version merge”的策略，在另行做 UX 决策后再扩展。

`agent_id` 也可以通过 `conversation -> agent` join 获得，但为了 Generated Files Library 的 agent filter 和统计而 denormalize。artifact ingest 时 router 已经通过 `_resolve_agent_context()` 知道 `cfg.agent_id`，因此一并放入 recorder context。

`is_favorite`, `last_opened_at`, `preview_count`, `download_count` 不要等到“以后增加文件库功能时”再加，而是从第 1 阶段就加入。panel 与 library 都查看同一个 artifact row，因此收藏和最近打开状态保持一致。

### 5.2 Storage 模型

第 1 阶段 local storage：

```text
data/artifacts/conversations/{conversation_id}/{artifact_id}/v{version_number}/{safe_filename}
```

S3/MinIO storage:

```text
bucket: moldy-artifacts
key: conversations/{conversation_id}/{artifact_id}/v{version_number}/{safe_filename}
```

保留现有 `data/conversations/{conversation_id}` 作为 skill runtime 的 staging/output directory。artifact service 发现新文件/修改文件后，将其复制到 canonical artifact storage 并写入 DB manifest。

新增 settings：

```text
ARTIFACT_STORAGE_BACKEND=local
ARTIFACT_STORAGE_DIR=./data/artifacts
ARTIFACT_MAX_BYTES=104857600
ARTIFACT_PREVIEW_MAX_TEXT_BYTES=1048576
ARTIFACT_S3_ENDPOINT_URL=
ARTIFACT_S3_BUCKET=
ARTIFACT_S3_ACCESS_KEY_ID=
ARTIFACT_S3_SECRET_ACCESS_KEY=
```

即使一开始不实际实现 S3 设置，只要先对齐 `StorageBackend` interface 和 config shape，后续切换 MinIO 的成本就较低。

### 5.3 Path 与 filename 规则

`logical_path` 是相对于 skill output dir 的路径。强制以下规则。

- 禁止 absolute path
- 禁止 `..` segment
- 禁止 null byte、control character
- 限制 segment 长度
- 限制完整 path 长度
- 隐藏/系统文件排除选项：`.DS_Store`, `__pycache__`, preview cache
- symlink 不 follow

实际 storage key 使用 artifact UUID 和 version number 构造。LLM 创建的文件名只保存在 `display_name`, `original_filename`, `logical_path` 中。

### 5.4 Event schema

在 `event_names.py` 中添加 `FILE_EVENT = "file_event"`。

```json
{
  "event": "file_event",
  "data": {
    "op": "created",
    "id": "uuid",
    "version_id": "uuid",
    "version_number": 1,
    "agent_id": "uuid",
    "conversation_id": "uuid",
    "assistant_msg_id": "uuid-string",
    "run_id": "uuid",
    "tool_call_id": "call_...",
    "source_tool_name": "execute_in_skill",
    "path": "report/final.md",
    "display_name": "final.md",
    "mime_type": "text/markdown",
    "extension": "md",
    "artifact_kind": "markdown",
    "size_bytes": 18342,
    "sha256": "64-char-hex",
    "status": "ready",
    "is_favorite": false,
    "last_opened_at": null,
    "preview_count": 0,
    "download_count": 0,
    "agent_name": null,
    "conversation_title": null,
    "url": "/api/conversations/{conversation_id}/artifacts/{artifact_id}",
    "preview_url": "/api/conversations/{conversation_id}/artifacts/{artifact_id}/content",
    "download_url": "/api/conversations/{conversation_id}/artifacts/{artifact_id}/download"
  }
}
```

`op` 值：

- `created`：创建新的 logical path
- `updated`：为同一 run/logical path 创建新 version
- `deleted`：artifact 被删除或不再可访问
- `failed`：ingest 或 preview 准备失败

### 5.5 Artifact service

新增 service 文件：

- `backend/app/models/conversation_artifact.py`
- `backend/app/schemas/artifact.py`
- `backend/app/services/artifact_storage.py`
- `backend/app/services/artifact_service.py`
- `backend/app/routers/artifacts.py`

核心函数：

```text
snapshot_output_dir(base_dir) -> ArtifactSnapshot
diff_snapshots(before, after) -> list[ArtifactDelta]
ingest_output_dir_delta(conversation_id, user_id, run_id, source_tool_name, tool_call_id, before, after) -> list[FileEventPayload]
list_artifacts(conversation_id, user_id) -> list[ArtifactSummary]
read_artifact_content(artifact_id, user_id, max_bytes) -> ArtifactContent
open_artifact_stream(artifact_id, user_id) -> StreamingResponse
```

`snapshot_output_dir` 记录 path、size、mtime_ns、sha256。小文件立即计算到 sha256，大文件先用 size/mtime 做第 1 轮检测，ingest 时再计算 streaming hash。

### 5.6 Stream 集成

第 1 阶段实现的最佳路径，是直接复用 `streaming.py` 现有的 `emit()`。在 `execute_in_skill` tool result 后立即 ingest artifact delta 并 emit `file_event`，broker resume、trace persistence、`message_events` 保存就会自动跟进。

实现方向：

- 在 `AgentConfig` 或 stream context 中明确包含 `run_id`, `user_id`, `conversation_id`, `artifact_output_dir`。
- `stream_agent_response` 开始时创建 output dir snapshot。
- 在 `tool_call_result` event 中，如果 tool name 是 `execute_in_skill`，则重新 snapshot 当前 output dir。
- 与之前的 snapshot 比较，由 artifact service 执行 DB/storage ingest。
- 将生成的 event payload 通过 `emit(FILE_EVENT, payload)` 发送。
- 更新 snapshot 基准点。

这种方式不尝试在 `execute_in_skill` 内部直接 emit SSE，因此对当前结构侵入更小。如果后续需要 near-real-time，可作为第 2 阶段工作增加 tool 执行中的 polling task 或 file backend proxy。

### 5.7 API 设计

已认证的 conversation API：

```text
GET /api/conversations/{conversation_id}/artifacts
GET /api/conversations/{conversation_id}/artifacts/{artifact_id}
GET /api/conversations/{conversation_id}/artifacts/{artifact_id}/content?version=current
GET /api/conversations/{conversation_id}/artifacts/{artifact_id}/download?version=current
DELETE /api/conversations/{conversation_id}/artifacts/{artifact_id}
```

已认证的 generated file library API：

```text
GET /api/artifacts?q=&agent_id=&conversation_id=&kind=&favorite=&limit=&cursor=
GET /api/artifacts/stats
GET /api/artifacts/recent?limit=
PATCH /api/artifacts/{artifact_id}
POST /api/artifacts/{artifact_id}/opened
GET /api/artifacts/{artifact_id}/content?version=current
GET /api/artifacts/{artifact_id}/download?version=current
```

`GET /api/artifacts` 搜索当前用户拥有的全部 artifact。`q` 针对 `display_name`, `logical_path`，`agent_id`, `conversation_id`, `kind`, `favorite` 作为 AND filter 应用。`limit/cursor` 使用与 conversation list 相同的 cursor pagination 风格。

`PATCH /api/artifacts/{artifact_id}` 在第 1 阶段只允许 `{"is_favorite": true|false}`。重命名、移动、编辑标签在另行产品决策后扩展。

`POST /api/artifacts/{artifact_id}/opened` 在 preview/open action 时调用，并更新 `last_opened_at`, `preview_count`。`download` endpoint 在返回文件前增加 `download_count`。

`GET /api/artifacts/stats` 至少返回以下内容。

```json
{
  "total_count": 42,
  "total_size_bytes": 1234567,
  "favorite_count": 3,
  "by_kind": [
    { "kind": "markdown", "count": 10, "size_bytes": 12000 }
  ],
  "recent_count_7d": 8
}
```

分享链接 API：

```text
GET /api/shares/{token}/artifacts
GET /api/shares/{token}/artifacts/{artifact_id}
GET /api/shares/{token}/artifacts/{artifact_id}/content
GET /api/shares/{token}/artifacts/{artifact_id}/download
```

所有 authenticated endpoint 都检查 conversation owner。现有 `/api/conversations/{conversation_id}/files/{file_path}` 可以为 backward compatibility 保留，但在首个 milestone 中要明确是强化 owner guard，还是改为 artifact API。

### 5.8 Security 与权限

- artifact API 必须使用 `get_owned_conversation_with_agent` 或等效的 owner guard。
- public share endpoint 只允许 share token 与 snapshot 中包含的 artifact。
- API 响应中不暴露 storage object path 和 local absolute path。
- HTML preview 仅通过 sandboxed iframe 提供。
- SVG 存在 script/event handler 风险，因此不要作为 image preview inline，或需 sanitize。
- Markdown preview 禁用 raw HTML。
- text preview 设置 byte limit 和 line limit。
- artifact ingest 应用 max file size、max files per run、max total bytes per conversation quota。
- 删除优先采用 soft-delete：先将 DB status 设为 `deleted`，再通过 storage garbage collection 处理，更安全。

## 6. Frontend 设计

### 6.1 State 与 SSE

新增类型：

- `ArtifactSummary`
- `ArtifactVersion`
- `FileEventPayload`
- `ArtifactPreviewKind`

修改点：

- `frontend/src/lib/types/index.ts`：在 `SSEEventType` 中添加 `file_event`
- `frontend/src/lib/chat/use-chat-runtime.ts`：收到 `file_event` 时 update artifact store
- `frontend/src/lib/stores/chat-artifacts.ts`：按 conversation/run 管理 artifact 列表状态
- `frontend/src/lib/hooks/use-conversation-artifacts.ts`：刷新/进入时 fetch artifact list

通过 SSE 进入的 event 按 optimistic state update 方式反映；进入 conversation 时用 API list 做 authoritative sync。

### 6.2 Right rail

修改点：

- `frontend/src/lib/stores/chat-right-rail.ts`：在 `RightRailMode` 中添加 `artifacts`
- `frontend/src/components/chat/right-rail/chat-right-rail.tsx`：render `ArtifactPanelContent`
- `frontend/src/components/chat/right-rail/artifact-panel-content.tsx`：新增
- `frontend/src/components/chat/right-rail/artifact-preview.tsx`：新增

panel UX：

- 按执行/run 分组
- 文件树或 compact list
- 显示创建/修改状态
- MIME 图标
- preview 区域
- download/open controls
- unsupported preview fallback

### 6.3 Preview provider registry

初始结构：

```ts
type ArtifactPreviewProvider = {
  id: string
  priority: number
  match: (artifact: ArtifactSummary) => boolean
  render: (props: ArtifactPreviewProps) => React.ReactNode
  maxBytes?: number
}
```

推荐文件：

- `frontend/src/components/chat/artifacts/preview-registry.ts`
- `frontend/src/components/chat/artifacts/providers/image-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/media-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/markdown-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/mermaid-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/code-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/text-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/fallback-preview.tsx`

第 1 阶段 provider：

- Image: browser native `<img>`
- Video/audio: browser native controls
- Markdown：复用 existing `MarkdownContent`
- Mermaid：复用 existing `mermaid` dependency
- Code/text/json/csv：existing syntax highlighter 或 lightweight text viewer
- HTML：sandboxed iframe，default disabled 或 explicit open
- PDF：first pass 使用 browser iframe/open original，later `react-pdf` or pdf.js
- Excalidraw: later `@excalidraw/excalidraw`
- Office/CAD: later server conversion or specialized provider

重要标准是“不要移除现有 inline preview 功能”。Markdown 回答中的 Mermaid/code/image 继续 inline，右侧 panel provider 仅应用于 artifact file。

### 6.4 Addon 扩展性

为了便于添加外部 preview provider，保持 core registry API 小而精。

- provider 根据 `mime_type`, `extension`, `metadata_json` 进行 match。
- 通过 provider priority 解决冲突。
- provider 允许 lazy import。
- heavy dependency 按 provider 拆成独立 chunk。
- untrusted file rendering 由 provider 自行声明 iframe sandbox 或 sanitize 策略。

没必要从一开始就开放外部 npm plugin loading。第 1 阶段使用代码级 addon registry 足够。runtime 外部插件加载还需要安全模型、dependency isolation、CSP，因此应放在单独 threat model 之后。

## 7. 实现阶段

### Milestone 1: Backend artifact foundation

- [ ] 通过 Alembic migration 添加 `conversation_artifacts`, `artifact_versions`
- [ ] 添加 SQLAlchemy model
- [ ] 添加 Pydantic schema
- [ ] 添加 `ArtifactStorageBackend` interface
- [ ] 实现 `LocalArtifactStorageBackend`
- [ ] 实现 path sanitization utility
- [ ] 实现 artifact service 的 snapshot/diff/ingest
- [ ] 添加 quota 和 max bytes 设置

### Milestone 2: SSE file_event

- [ ] 在 `event_names.py` 中添加 `FILE_EVENT`
- [ ] 在 stream context 中明确 `run_id`, `conversation_id`, `user_id`, `artifact_output_dir`
- [ ] `execute_in_skill` tool result 后 ingest output dir delta
- [ ] 通过 `emit(FILE_EVENT, payload)` 发送 ingest 结果
- [ ] 验证 `message_events` persistence/replay 中会保留 `file_event`
- [ ] 现有 `OUTPUT_FILES` 文本继续保留以兼容

### Milestone 3: Artifact API

- [ ] `GET /api/conversations/{id}/artifacts`
- [ ] `GET /api/conversations/{id}/artifacts/{artifact_id}`
- [ ] `GET /api/conversations/{id}/artifacts/{artifact_id}/content`
- [ ] `GET /api/conversations/{id}/artifacts/{artifact_id}/download`
- [ ] `GET /api/artifacts` 全局 generated file library 列表/搜索
- [ ] `GET /api/artifacts/stats` 文件统计
- [ ] `GET /api/artifacts/recent` 最近打开/生成文件
- [ ] `PATCH /api/artifacts/{artifact_id}` favorite toggle
- [ ] `POST /api/artifacts/{artifact_id}/opened` 记录最近打开/preview count
- [ ] share token artifact read API
- [ ] 检查/修改现有 conversation file endpoint owner guard
- [ ] 整理 content disposition, MIME, cache headers

### Milestone 4: Frontend event/store/right rail

- [ ] 在 TS SSE type 中添加 `file_event`
- [ ] 添加 `chat-artifacts` Jotai store
- [ ] 添加 `useConversationArtifacts` query
- [ ] 在 `use-chat-runtime` 中处理 `file_event`
- [ ] 在 right rail mode 中添加 `artifacts`
- [ ] 添加 `ArtifactPanelContent`
- [ ] 在 tool result 或 toolbar 中添加打开 artifact panel 的 affordance

### Milestone 5: Preview providers

- [ ] 实现 preview registry
- [ ] image/video/audio provider
- [ ] markdown provider
- [ ] mermaid provider
- [ ] code/text/json/csv provider
- [ ] fallback/download provider
- [ ] 决定 HTML sandbox preview 策略后实现
- [ ] 实现 PDF first-pass preview

### Milestone 6: Generated File Library UI

- [ ] 添加 `/artifacts` route
- [ ] 在 sidebar navigation 中添加 Files/Artifacts 项
- [ ] 文件搜索、agent filter、conversation filter、kind filter、favorite filter
- [ ] 文件列表/网格、preview rail 或 detail pane
- [ ] favorite toggle
- [ ] 最近打开/生成区块
- [ ] 显示 total size、kind breakdown、favorite count 统计
- [ ] 复用与 ArtifactPanel 相同的 preview provider registry

### Milestone 7: Hardening and share

- [ ] 连接 share snapshot 与 artifact visibility
- [ ] 测试 share artifact public read endpoint
- [ ] 实现 artifact 删除/retention 策略
- [ ] 添加 storage cleanup job
- [ ] 如果需要 preview cache，引入独立 cache namespace

### Milestone 8: Optional near-real-time

- [ ] skill subprocess 执行期间 polling output dir
- [ ] file update debounce
- [ ] writing/ready 状态转换 event
- [ ] 检测大文件 partial write

### Milestone 9: Optional MinIO/S3

- [ ] 实现 S3 artifact storage backend
- [ ] local/S3 storage integration test
- [ ] 决定直接暴露 signed URL，还是继续使用 backend proxy
- [ ] 文档化 lifecycle policy 与 bucket prefix cleanup

## 8. 测试计划

### Backend tests

- [ ] path traversal：拒绝 `../`、absolute path、null byte、symlink
- [ ] artifact ingest: created/updated/no-change delta
- [ ] same run + same logical path 时 version 增加
- [ ] different run + same logical path 时创建独立 artifact
- [ ] 确认 local storage object key 不信任 LLM filename
- [ ] router ownership：拒绝访问其他用户 conversation artifact
- [ ] library API：`q`, `agent_id`, `conversation_id`, `kind`, `favorite` filter
- [ ] favorite toggle：只能修改同一用户的 artifact
- [ ] stats API: total count/bytes, kind breakdown, favorite count
- [ ] opened/download tracking：增加 `last_opened_at`, `preview_count`, `download_count`
- [ ] share token：只能访问已分享 conversation 的 artifact
- [ ] stream：`execute_in_skill` 结果后 emit `file_event`
- [ ] stream resume：从 `message_events` replay `file_event`
- [ ] quota：超过 max bytes/max files 时发送 failed event 或跳过 ingest

### Frontend tests

- [ ] SSE `file_event` 更新 artifact store
- [ ] 进入 conversation 时合并 artifact list fetch 与 SSE state
- [ ] 切换 right rail `artifacts` mode
- [ ] provider registry priority 与 fallback
- [ ] Markdown/Mermaid/code artifact preview
- [ ] unsupported file download fallback
- [ ] `/artifacts` library search/filter/favorite/stat UI
- [ ] ArtifactPanel 与 Generated File Library 复用同一个 preview provider
- [ ] 保留现有 inline Markdown/Mermaid/image rendering

## 9. 主要风险与缓解

### 现有 file endpoint 权限

如果现有 `/api/conversations/{conversation_id}/files/{file_path}` 与 artifact API 并存，权限模型可能分裂。在第 1 阶段工作中检查 owner guard，新 UI 只使用基于 artifact id 的 API。

### 部分写入文件与大文件

第 1 阶段实现是在 tool 结束后检测 delta，因此 partial write 问题较少。进入 near-real-time polling 阶段后，需要在 size/mtime 稳定后才转为 `ready` 的 debounce。

### HTML/SVG preview

HTML 和 SVG 的 preview UX 很好，但 XSS 风险高。HTML 限制为 sandbox iframe，SVG 默认禁用 image inline，或仅提供经过 sanitize 的 preview。

### Office/CAD preview 预期

Office、PPT、CAD preview 需要按文件类型引入 dependency 和转换服务器。第 1 阶段集成范围先准备 provider registry 与 fallback download/open，高级 preview 再从必要格式开始逐个接入 provider。

### Storage migration

如果一开始就强制 MinIO，会扩大部署/运维范围。先从 Local backend 开始，但将 DB manifest 与 storage interface 分离，使切换 S3 时无需修改 API。

## 10. 集成第 1 阶段范围

第 1 阶段 PR 的目标定为：“生成文件出现在右侧 panel，同时可在全局 Generated File Library 中搜索/过滤/收藏/统计复用”。该功能不拆成 MVP 和 P2。文件索引、panel、library 页面必须共享同一个 `conversation_artifacts` source of truth，避免 API 和 DB 被重做两次。

包括：

- local artifact storage
- DB manifest/version
- library metadata: `agent_id`, `artifact_kind`, `is_favorite`, `last_opened_at`, `preview_count`, `download_count`
- `execute_in_skill` 结束后 ingest delta
- SSE `file_event`
- conversation artifact list/content/download API
- global generated file library API: search/filter/favorite/recent/stats
- right rail ArtifactPanel
- `/artifacts` Generated File Library 页面
- Markdown, Mermaid, code/text, image preview
- fallback download

排除：

- MinIO/S3 实际实现
- sandbox write proxy
- Office/CAD 高级 preview
- 外部 npm plugin runtime loading
- 文件协同编辑

这个范围最符合 Moldy 当前路线。保留现有限制版 `execute_in_skill` 模型，同时显著改善用户在 panel 和 library 两侧感知到的 artifact 体验；将来需要 sandbox 或 MinIO 时，也可以继续扩展而无需推倒重来。

## 11. 基于源代码的详细实现契约

本节旨在让实现者无需前置对话上下文，仅凭本文档就能按实际 Moldy 源码结构实施。以下路径和函数名是在 2026-06-05 的代码中确认的当前结构。

### 11.1 当前 runtime 不变量

- `backend/app/routers/conversations.py` 的 `_prepare_stream_context(conversation_id)` 在每个 assistant turn 创建 `run_id`, `EventBroker`, `persist_callback`, `trace_sink`, `msg_id_sink`, `error_sink`。
- `run_id` 传给 `stream_agent_response()`，内部成为 `msg_id = run_id`。SSE id 格式为 `"{msg_id}-{seq}"`。
- 相同的 `run_id` 保存为 `message_events.assistant_msg_id`。因此 artifact 不使用独立 `messages` FK，而以 `assistant_msg_id/run_id` 作为稳定的 turn key。
- `stream_agent_response()` 的 `emit(event, data)` 每调用一次，就同时处理 SSE、broker publish、trace sink append、partial DB persistence buffer append。`file_event` 必须通过这个 `emit()` 发布。
- `execute_in_skill` 是 `backend/app/agent_runtime/executor.py` 中 `_create_skill_execute_tool(ctx)` 内部的 closure。skill 输出目录是 `SkillToolContext.output_dir`，`build_skill_runtime_context()` 将其设为 `data/conversations/{thread_id}`。
- `frontend/src/lib/chat/use-chat-runtime.ts` 在 SSE event switch 中处理 `content_delta`, `tool_call_start`, `tool_call_result`, memory events, `interrupt`, `error`, `message_end`。`file_event` 在这里应只更新 artifact store，不修改 assistant message content。

### 11.2 Backend file map

Create:

- `backend/app/models/conversation_artifact.py`  
  `ConversationArtifact`, `ArtifactVersion`, status/storage constants.
- `backend/app/schemas/artifact.py`  
  API response schema, file event payload schema, content response schema.
- `backend/app/services/artifact_paths.py`  
  logical path normalization, safe filename, MIME detection, symlink/path traversal guard.
- `backend/app/services/artifact_storage.py`  
  storage interface and local disk backend.
- `backend/app/services/artifact_service.py`  
  output dir snapshot/diff, DB manifest/version creation, library search/filter/stats, favorite/open/download counters, content/download helpers.
- `backend/app/routers/artifacts.py`  
  authenticated conversation artifact APIs and global generated file library APIs.
- `backend/app/routers/share_artifacts.py`  
  public share-token artifact APIs, or add these routes to existing `shares.py` if the file remains readable.
- `backend/tests/test_artifact_paths.py`
- `backend/tests/test_artifact_storage.py`
- `backend/tests/test_artifact_service.py`
- `backend/tests/test_artifacts_router.py`
- `backend/tests/test_artifact_library_router.py`
- `backend/tests/integration/test_artifact_streaming.py`

Modify:

- `backend/app/config.py`  
  Add artifact storage settings next to `conversation_output_dir` and `upload_dir`.
- `backend/app/models/__init__.py`  
  Import and export new artifact models.
- `backend/app/agent_runtime/event_names.py`  
  Add `FILE_EVENT`.
- `backend/app/agent_runtime/streaming.py`  
  Add artifact recorder protocol parameter and emit `file_event` after `execute_in_skill` results.
- `backend/app/agent_runtime/executor.py`  
  Pass artifact recorder through `execute_agent_stream`, `resume_agent_stream`, `_run_agent_stream`, and `stream_agent_response`.
- `backend/app/routers/conversations.py`  
  Build an artifact recorder for message send/resume/edit/regenerate streams. Fix existing `/files/{file_path}` ownership guard.
- `backend/app/main.py`  
  Include artifact routers.
- `backend/alembic/versions/<next>_add_conversation_artifacts.py`  
  Add tables/indexes/check constraints.

### 11.3 Frontend file map

Create:

- `frontend/src/lib/chat/artifact-types.ts`  
  UI-only helpers if the shared `lib/types` file becomes too large.
- `frontend/src/lib/api/artifacts.ts`  
  Fetch conversation artifacts, global library list, stats, favorite/open/download metadata.
- `frontend/src/lib/hooks/use-conversation-artifacts.ts`
- `frontend/src/lib/hooks/use-artifact-library.ts`
- `frontend/src/lib/stores/chat-artifacts.ts`
- `frontend/src/app/artifacts/page.tsx`
- `frontend/src/components/artifacts/artifact-library-content.tsx`
- `frontend/src/components/artifacts/artifact-library-filters.tsx`
- `frontend/src/components/artifacts/artifact-library-stats.tsx`
- `frontend/src/components/chat/right-rail/artifact-panel-content.tsx`
- `frontend/src/components/chat/artifacts/artifact-preview.tsx`
- `frontend/src/components/chat/artifacts/preview-registry.tsx`
- `frontend/src/components/chat/artifacts/providers/image-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/media-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/markdown-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/mermaid-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/code-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/text-preview.tsx`
- `frontend/src/components/chat/artifacts/providers/fallback-preview.tsx`
- `frontend/src/lib/stores/__tests__/chat-artifacts.test.ts`
- `frontend/src/lib/hooks/__tests__/use-artifact-library.test.tsx`
- `frontend/src/components/chat/artifacts/__tests__/preview-registry.test.tsx`

Modify:

- `frontend/src/lib/types/index.ts`  
  Add artifact types and `file_event` SSE union.
- `frontend/src/lib/chat/use-chat-runtime.ts`  
  Update artifact store on `file_event`.
- `frontend/src/lib/stores/chat-right-rail.ts`
  Add `artifacts` mode.
- `frontend/src/components/chat/right-rail/chat-right-rail.tsx`
  Render `ArtifactPanelContent`.
- `frontend/src/components/layout/app-sidebar.tsx`
  Add a first-class Files/Artifacts nav item pointing to `/artifacts`.
- `frontend/src/components/layout/breadcrumb-nav.tsx`
  Add breadcrumb label for `/artifacts`.
- `frontend/messages/ko.json`, `frontend/messages/en.json`
  Add all visible copy.

### 11.4 Backend model skeleton

Use JSON columns rather than JSONB in SQLAlchemy model code unless existing migration uses PostgreSQL-specific JSONB explicitly. Existing `MessageEvent` uses `JSON`, and backend tests run on aiosqlite.

```python
# backend/app/models/conversation_artifact.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

ARTIFACT_STATUS_VALUES = ("writing", "ready", "deleted", "failed")
ARTIFACT_STORAGE_VALUES = ("local", "s3")
ARTIFACT_KIND_VALUES = (
    "image",
    "video",
    "audio",
    "pdf",
    "markdown",
    "html",
    "code",
    "document",
    "data",
    "cad",
    "other",
)


class ConversationArtifact(Base):
    __tablename__ = "conversation_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "assistant_msg_id",
            "logical_path",
            name="uq_conversation_artifacts_turn_path",
        ),
        Index("ix_conversation_artifacts_user_conversation_created", "user_id", "conversation_id", "created_at"),
        Index("ix_conversation_artifacts_conversation_turn_updated", "conversation_id", "assistant_msg_id", "updated_at"),
        Index("ix_conversation_artifacts_user_created", "user_id", "created_at"),
        Index("ix_conversation_artifacts_user_agent_created", "user_id", "agent_id", "created_at"),
        Index("ix_conversation_artifacts_user_kind_created", "user_id", "artifact_kind", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_msg_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_tool_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    logical_path: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    preview_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    branch_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    linked_message_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "version_number", name="uq_artifact_versions_number"),
        Index("ix_artifact_versions_artifact_created", "artifact_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_key: Mapped[str] = mapped_column(String(800), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
```

PostgreSQL migration should add `CHECK (status IN (...))`, `CHECK (artifact_kind IN (...))`, `CHECK (storage_provider IN (...))`, and a partial favorite index for `is_favorite = true`. SQLite tests can rely on SQLAlchemy model plus service validation.

### 11.5 Config additions

Add below upload settings in `backend/app/config.py`.

```python
    # Agent/runtime generated artifacts. The first integrated release uses local disk; S3/MinIO can be
    # added behind app.services.artifact_storage without changing API URLs.
    artifact_storage_backend: Literal["local", "s3"] = "local"
    artifact_storage_dir: str = "./data/artifacts"
    artifact_max_bytes: int = 100 * 1024 * 1024
    artifact_max_files_per_run: int = 100
    artifact_preview_max_text_bytes: int = 1 * 1024 * 1024
    artifact_s3_endpoint_url: str = ""
    artifact_s3_bucket: str = ""
    artifact_s3_access_key_id: str = ""
    artifact_s3_secret_access_key: str = ""
```

`Literal` is already imported at the top of `config.py`.

### 11.6 Path utility contract

`backend/app/services/artifact_paths.py` should own all path validation. Do not duplicate traversal checks in routers/services.

```python
from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path


class ArtifactPathError(ValueError):
    pass


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
_SKIP_NAMES = {".DS_Store"}
_SKIP_PARTS = {"__pycache__", ".previews"}


@dataclass(frozen=True)
class NormalizedArtifactPath:
    logical_path: str
    display_name: str
    extension: str | None
    mime_type: str
    artifact_kind: str


def artifact_kind_for(mime_type: str, extension: str | None) -> str:
    ext = (extension or "").lower()
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type == "application/pdf" or ext == "pdf":
        return "pdf"
    if mime_type == "text/markdown" or ext in {"md", "markdown", "mmd", "mermaid"}:
        return "markdown"
    if mime_type == "text/html" or ext in {"html", "htm"}:
        return "html"
    if ext in {"py", "js", "ts", "tsx", "jsx", "css", "json", "yaml", "yml", "toml", "sql", "sh"}:
        return "code"
    if ext in {"csv", "tsv", "xlsx", "xls"}:
        return "data"
    if ext in {"doc", "docx", "ppt", "pptx"}:
        return "document"
    if ext in {"dwg", "dxf", "step", "stp", "iges", "igs", "stl"}:
        return "cad"
    return "other"


def normalize_output_path(base_dir: Path, path: Path) -> NormalizedArtifactPath:
    resolved_base = base_dir.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_base):
        raise ArtifactPathError("artifact path escapes output directory")
    if not resolved_path.is_file():
        raise ArtifactPathError("artifact path is not a file")
    if path.is_symlink() or resolved_path.is_symlink():
        raise ArtifactPathError("artifact symlinks are not allowed")

    relative = resolved_path.relative_to(resolved_base)
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ArtifactPathError("artifact path contains invalid segments")
    if any(part in _SKIP_PARTS for part in parts) or relative.name in _SKIP_NAMES:
        raise ArtifactPathError("artifact path is excluded")
    if len(parts) > 12:
        raise ArtifactPathError("artifact path is too deep")
    if any(len(part) > 120 for part in parts):
        raise ArtifactPathError("artifact path segment is too long")

    logical_path = relative.as_posix()
    if len(logical_path) > 500:
        raise ArtifactPathError("artifact path is too long")
    if any(ord(ch) < 32 for ch in logical_path):
        raise ArtifactPathError("artifact path contains control characters")

    extension = relative.suffix.lower().lstrip(".") or None
    mime_type = mimetypes.guess_type(relative.name)[0] or "application/octet-stream"
    artifact_kind = artifact_kind_for(mime_type, extension)
    return NormalizedArtifactPath(
        logical_path=logical_path,
        display_name=relative.name,
        extension=extension,
        mime_type=mime_type,
        artifact_kind=artifact_kind,
    )


def safe_storage_filename(display_name: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("_", display_name).strip(" .")
    return cleaned[:160] or "artifact"
```

### 11.7 Storage interface contract

The first integrated local backend writes canonical copies to `settings.artifact_storage_dir`. Routers should never serve directly from `data/conversations/{conversation_id}` once an artifact row exists.

```python
# backend/app/services/artifact_storage.py
from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import settings
from app.services.artifact_paths import safe_storage_filename


@dataclass(frozen=True)
class StoredArtifactObject:
    storage_provider: str
    bucket: str | None
    object_key: str
    path: Path | None


class ArtifactStorageBackend(Protocol):
    async def put_file(
        self,
        *,
        conversation_id: uuid.UUID,
        artifact_id: uuid.UUID,
        version_number: int,
        display_name: str,
        source_path: Path,
    ) -> StoredArtifactObject:
        ...

    async def local_path(self, *, object_key: str) -> Path:
        ...


class LocalArtifactStorageBackend:
    provider = "local"

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = Path(root_dir or settings.artifact_storage_dir)

    async def put_file(
        self,
        *,
        conversation_id: uuid.UUID,
        artifact_id: uuid.UUID,
        version_number: int,
        display_name: str,
        source_path: Path,
    ) -> StoredArtifactObject:
        safe_name = safe_storage_filename(display_name)
        object_key = (
            f"conversations/{conversation_id}/{artifact_id}/"
            f"v{version_number}/{safe_name}"
        )
        target = (self.root_dir / object_key).resolve()
        root = self.root_dir.resolve()
        if not target.is_relative_to(root):
            raise ValueError("artifact object key escapes storage root")
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, source_path, target)
        return StoredArtifactObject(
            storage_provider=self.provider,
            bucket=None,
            object_key=object_key,
            path=target,
        )

    async def local_path(self, *, object_key: str) -> Path:
        target = (self.root_dir / object_key).resolve()
        if not target.is_relative_to(self.root_dir.resolve()):
            raise ValueError("artifact object key escapes storage root")
        return target
```

### 11.8 Artifact service and stream recorder contract

The streaming layer should not know SQLAlchemy table details. It receives a recorder object with a tiny async method. This preserves `streaming.py` as event orchestration code rather than storage code.

```python
# backend/app/services/artifact_service.py
from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.conversation_artifact import ArtifactVersion, ConversationArtifact
from app.services.artifact_paths import ArtifactPathError, NormalizedArtifactPath, normalize_output_path
from app.services.artifact_storage import ArtifactStorageBackend, LocalArtifactStorageBackend


@dataclass(frozen=True)
class ArtifactFileState:
    logical_path: str
    path: Path
    size_bytes: int
    mtime_ns: int
    sha256: str
    normalized: NormalizedArtifactPath


@dataclass
class ArtifactSnapshot:
    files: dict[str, ArtifactFileState] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRuntimeContext:
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    agent_id: uuid.UUID
    assistant_msg_id: str
    output_dir: Path
    source_tool_name: str = "execute_in_skill"
    branch_checkpoint_id: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def snapshot_output_dir(base_dir: Path) -> ArtifactSnapshot:
    def _scan() -> ArtifactSnapshot:
        files: dict[str, ArtifactFileState] = {}
        if not base_dir.exists():
            return ArtifactSnapshot(files=files)
        for path in base_dir.rglob("*"):
            try:
                normalized = normalize_output_path(base_dir, path)
            except ArtifactPathError:
                continue
            stat = path.stat()
            files[normalized.logical_path] = ArtifactFileState(
                logical_path=normalized.logical_path,
                path=path,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                sha256=_sha256_file(path),
                normalized=normalized,
            )
        return ArtifactSnapshot(files=files)

    return await asyncio.to_thread(_scan)


def diff_snapshots(before: ArtifactSnapshot, after: ArtifactSnapshot) -> list[ArtifactFileState]:
    changed: list[ArtifactFileState] = []
    for logical_path, current in after.files.items():
        previous = before.files.get(logical_path)
        if previous is None or previous.sha256 != current.sha256:
            changed.append(current)
    return changed


class ArtifactDeltaRecorder:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        context: ArtifactRuntimeContext,
        storage: ArtifactStorageBackend | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._storage = storage or LocalArtifactStorageBackend()
        self._snapshot = ArtifactSnapshot()
        self._prepared = False

    async def prepare(self) -> None:
        self._snapshot = await snapshot_output_dir(self._context.output_dir)
        self._prepared = True

    async def collect_after_tool_result(
        self,
        *,
        tool_name: str,
        tool_call_id: str | None,
    ) -> list[dict[str, Any]]:
        if tool_name != self._context.source_tool_name:
            return []
        if not self._prepared:
            await self.prepare()
        after = await snapshot_output_dir(self._context.output_dir)
        changed = diff_snapshots(self._snapshot, after)
        self._snapshot = after
        if not changed:
            return []
        async with self._session_factory() as session:
            payloads = await ingest_changed_files(
                session,
                context=self._context,
                changed=changed,
                storage=self._storage,
                tool_call_id=tool_call_id,
            )
            await session.commit()
        return payloads
```

`ingest_changed_files()` must upsert by `(conversation_id, assistant_msg_id, logical_path)`. If an artifact exists and `sha256` changed, create `ArtifactVersion(version_number=max+1)`, update `current_version_id`, `sha256`, `size_bytes`, `artifact_kind`, `updated_at`, and emit `op="updated"`. If not exists, create artifact + version with `user_id`, `agent_id`, `conversation_id`, `assistant_msg_id`, `logical_path`, `artifact_kind`, and emit `op="created"`.

Payload builder should produce the exact event schema in section 5.4. `url`, `preview_url`, `download_url` should use artifact id endpoints, not the legacy `/files/{file_path}` endpoint.

### 11.9 Streaming integration contract

In `backend/app/agent_runtime/streaming.py`, add a Protocol near the top-level type aliases.

```python
from typing import Protocol


class ArtifactDeltaRecorderProtocol(Protocol):
    async def prepare(self) -> None:
        ...

    async def collect_after_tool_result(
        self,
        *,
        tool_name: str,
        tool_call_id: str | None,
    ) -> list[dict[str, Any]]:
        ...
```

Add a parameter to `stream_agent_response()`:

```python
    artifact_recorder: ArtifactDeltaRecorderProtocol | None = None,
```

After `yield emit(event_names.MESSAGE_START, start_data)` and before `agent.astream(...)`, prepare the recorder. If prepare fails, emit an `error` only if the stream cannot proceed. Recommended 第 1 阶段 behavior is fail-open with a log, because artifact panel/library failure must not block chat.

```python
    yield emit(event_names.MESSAGE_START, start_data)
    if artifact_recorder is not None:
        try:
            await artifact_recorder.prepare()
        except Exception:
            logger.warning("artifact recorder prepare failed (run_id=%s)", msg_id, exc_info=True)
            artifact_recorder = None
```

Inside the current `if msg.type == "tool":` block, immediately after `yield emit(event_names.TOOL_CALL_RESULT, result_payload)`, emit artifact events for `execute_in_skill`.

```python
                        yield emit(event_names.TOOL_CALL_RESULT, result_payload)
                        if artifact_recorder is not None:
                            try:
                                file_payloads = await artifact_recorder.collect_after_tool_result(
                                    tool_name=tool_name,
                                    tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
                                )
                            except Exception:
                                logger.warning(
                                    "artifact delta collection failed (run_id=%s tool=%s)",
                                    msg_id,
                                    tool_name,
                                    exc_info=True,
                                )
                                file_payloads = []
                            for file_payload in file_payloads:
                                yield emit(event_names.FILE_EVENT, file_payload)
```

This preserves the event order:

```text
tool_call_result
file_event created/updated...
message_end
```

The frontend can therefore show tool stdout/stderr and artifact list independently.

### 11.10 Executor pass-through contract

In `backend/app/agent_runtime/executor.py`, add `artifact_recorder: Any | None = None` to the following functions and pass it through unchanged:

- `_run_agent_stream(...)`
- `execute_agent_stream(...)`
- `resume_agent_stream(...)`
- `run_agent(...)` only if its stream path delegates to the same function and tests require signature consistency.

At the existing call to `stream_agent_response(...)`, add:

```python
                artifact_recorder=artifact_recorder,
```

Do not put artifact detection inside `_create_skill_execute_tool()` for the first integrated release. That closure currently validates skill slug, prepares env, runs subprocess, redacts credentials, and appends `OUTPUT_FILES`. Keeping artifact ingest outside the tool avoids DB/session coupling inside tool execution.

### 11.11 Router integration contract

Add a helper in `backend/app/routers/conversations.py`.

```python
def _build_artifact_recorder(
    *,
    conversation_id: uuid.UUID,
    user: CurrentUser,
    agent_id: uuid.UUID,
    run_id: str,
) -> ArtifactDeltaRecorder:
    return ArtifactDeltaRecorder(
        session_factory=async_session,
        context=ArtifactRuntimeContext(
            conversation_id=conversation_id,
            user_id=user.id,
            agent_id=agent_id,
            assistant_msg_id=run_id,
            output_dir=Path(settings.conversation_output_dir) / str(conversation_id),
        ),
    )
```

Required imports:

```python
from pathlib import Path
from app.config import settings
from app.services.artifact_service import ArtifactDeltaRecorder, ArtifactRuntimeContext
```

Use the helper in every route that starts an assistant stream:

- `send_message`
- `resume_message`
- `edit_message`
- `regenerate_message`

Pattern:

```python
    ctx = _prepare_stream_context(conversation_id)
    artifact_recorder = _build_artifact_recorder(
        conversation_id=conversation_id,
        user=user,
        agent_id=uuid.UUID(cfg.agent_id),
        run_id=ctx.run_id,
    )
    return _sse_handler(
        lambda: execute_agent_stream(
            cfg,
            [{"role": "user", "content": data.content}],
            moldy_source="chat",
            artifact_recorder=artifact_recorder,
            **ctx.as_stream_kwargs(),
        ),
        ...
    )
```

For `resume_agent_stream(...)`, pass the same `artifact_recorder=artifact_recorder`.

Fix the existing file endpoint at the same time. Current code calls `chat_service.get_conversation(db, conversation_id)` even though it receives `CurrentUser`. Change it to owner-gated lookup:

```python
    conv = await chat_service.get_owned_conversation(db, conversation_id, user.id)
    if not conv:
        raise conversation_not_found()
```

This is required even if the new UI stops using `/files/{file_path}` because old Markdown links can still hit that endpoint.

### 11.12 Artifact router contract

`backend/app/routers/artifacts.py` should use owner-gated conversation lookup for every route.

```python
@router.get("/api/conversations/{conversation_id}/artifacts")
async def list_conversation_artifacts(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[ArtifactSummary]:
    conv = await chat_service.get_owned_conversation(db, conversation_id, user.id)
    if not conv:
        raise conversation_not_found()
    return await artifact_service.list_artifacts(db, conversation_id=conversation_id)
```

For content route:

- Text-like MIME (`text/*`, `application/json`, `application/xml`, `application/csv`) returns UTF-8 text with replacement and a `truncated` flag if over `settings.artifact_preview_max_text_bytes`.
- Binary files return `415` for `/content` unless a provider-specific preview exists.
- Download route streams with `FileResponse` for local backend and backend-proxy streaming for S3 later.

`download` must use `filename=artifact.display_name` and `media_type=artifact.mime_type`.

Global library routes in the same router should use artifact-owner lookup, not conversation lookup. The service query must always include `ConversationArtifact.user_id == user.id`.

```python
@router.get("/api/artifacts")
async def list_generated_artifacts(
    q: str | None = Query(None),
    agent_id: uuid.UUID | None = Query(None),
    conversation_id: uuid.UUID | None = Query(None),
    kind: str | None = Query(None),
    favorite: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ArtifactLibraryPage:
    return await artifact_service.list_library_artifacts(
        db,
        user_id=user.id,
        q=q,
        agent_id=agent_id,
        conversation_id=conversation_id,
        kind=kind,
        favorite=favorite,
        limit=limit,
        cursor=cursor,
    )
```

Required service functions:

```text
list_library_artifacts(user_id, q, agent_id, conversation_id, kind, favorite, limit, cursor)
get_library_stats(user_id)
set_artifact_favorite(user_id, artifact_id, is_favorite)
record_artifact_opened(user_id, artifact_id)
record_artifact_download(user_id, artifact_id)
```

`content` and `download` endpoints can be exposed under both `/api/conversations/{id}/artifacts/{artifact_id}/...` and `/api/artifacts/{artifact_id}/...`. Both must call the same service method that validates `artifact.user_id == user.id`. The conversation-scoped variant additionally verifies the artifact belongs to that conversation.

### 11.13 Frontend type contract

Add to `frontend/src/lib/types/index.ts`.

```ts
export type ArtifactStatus = 'writing' | 'ready' | 'deleted' | 'failed'
export type ArtifactKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'markdown'
  | 'html'
  | 'code'
  | 'document'
  | 'data'
  | 'cad'
  | 'other'
export type FileEventOperation = 'created' | 'updated' | 'deleted' | 'failed'

export interface ArtifactSummary {
  id: string
  agent_id: string
  conversation_id: string
  assistant_msg_id: string
  run_id: string
  tool_call_id?: string | null
  source_tool_name?: string | null
  path: string
  display_name: string
  mime_type: string
  extension?: string | null
  artifact_kind: ArtifactKind
  size_bytes: number
  sha256: string
  status: ArtifactStatus
  is_favorite: boolean
  last_opened_at?: string | null
  preview_count: number
  download_count: number
  version_id: string
  version_number: number
  created_at: string
  updated_at: string
  agent_name?: string | null
  conversation_title?: string | null
  url: string
  preview_url: string
  download_url: string
}

export interface FileEventPayload extends ArtifactSummary {
  op: FileEventOperation
}

export interface ArtifactLibraryPage {
  items: ArtifactSummary[]
  next_cursor: string | null
  has_more: boolean
}

export interface ArtifactLibraryParams {
  q?: string
  agent_id?: string
  conversation_id?: string
  kind?: ArtifactKind
  favorite?: boolean
  limit?: number
  cursor?: string | null
}

export interface ArtifactKindStat {
  kind: ArtifactKind
  count: number
  size_bytes: number
}

export interface ArtifactLibraryStats {
  total_count: number
  total_size_bytes: number
  favorite_count: number
  by_kind: ArtifactKindStat[]
  recent_count_7d: number
}
```

Update `SSEEventType`:

```ts
  | 'file_event'
```

Update `SSEEvent` union:

```ts
  | { event: 'file_event'; data: FileEventPayload }
```

### 11.14 Frontend store contract

Create `frontend/src/lib/stores/chat-artifacts.ts`.

```ts
import { atom } from 'jotai'
import type { ArtifactSummary, FileEventPayload } from '@/lib/types'

export type ArtifactMap = Record<string, ArtifactSummary[]>

export const chatArtifactsAtom = atom<ArtifactMap>({})

export const upsertChatArtifactAtom = atom(null, (get, set, payload: FileEventPayload) => {
  const current = get(chatArtifactsAtom)
  const conversationId = payload.conversation_id
  const existing = current[conversationId] ?? []
  const withoutDeleted =
    payload.op === 'deleted'
      ? existing.filter((artifact) => artifact.id !== payload.id)
      : existing
  if (payload.op === 'deleted') {
    set(chatArtifactsAtom, { ...current, [conversationId]: withoutDeleted })
    return
  }
  const idx = withoutDeleted.findIndex((artifact) => artifact.id === payload.id)
  const nextItem: ArtifactSummary = payload
  const next =
    idx >= 0
      ? withoutDeleted.map((artifact, index) => (index === idx ? nextItem : artifact))
      : [nextItem, ...withoutDeleted]
  set(chatArtifactsAtom, { ...current, [conversationId]: next })
})

export const replaceConversationArtifactsAtom = atom(
  null,
  (get, set, update: { conversationId: string; artifacts: ArtifactSummary[] }) => {
    const current = get(chatArtifactsAtom)
    set(chatArtifactsAtom, { ...current, [update.conversationId]: update.artifacts })
  },
)
```

`use-chat-runtime.ts` currently uses mocked `useSetAtom` in tests. Add:

```ts
import { upsertChatArtifactAtom } from '@/lib/stores/chat-artifacts'
```

Inside `useChatRuntime`, create:

```ts
const upsertChatArtifact = useSetAtom(upsertChatArtifactAtom)
```

Add switch case:

```ts
            case 'file_event': {
              upsertChatArtifact(event.data)
              break
            }
```

This case should not call `setStreamingMessages()` because artifacts are independent right-rail state.

### 11.15 Right rail contract

Update `frontend/src/lib/stores/chat-right-rail.ts`.

```ts
export type RightRailMode = 'none' | 'subagent' | 'tool-result' | 'outline' | 'artifacts'

export interface ArtifactsPayload {
  conversationId: string
  selectedArtifactId?: string | null
}

export type RightRailState =
  | { mode: 'none' }
  | { mode: 'subagent'; subagent: SubagentPayload }
  | { mode: 'tool-result'; toolResult: ToolResultPayload }
  | { mode: 'outline'; outline: OutlinePayload }
  | { mode: 'artifacts'; artifacts: ArtifactsPayload }
```

Update `conversationIdForState()` and `titleFor()` in `chat-right-rail.tsx`:

```ts
  if (state.mode === 'artifacts') return state.artifacts.conversationId
```

```ts
  if (state.mode === 'artifacts') return t('artifacts')
```

Because `titleFor` currently does not receive `t`, either change the signature to `titleFor(state, t)` or keep a literal only if moved into `messages`. Product copy must go through `next-intl`, so prefer `titleFor(state, t)`.

Render:

```tsx
{state.mode === 'artifacts' ? <ArtifactPanelContent payload={state.artifacts} /> : null}
```

### 11.16 Preview registry contract

The registry should be deterministic and small.

```tsx
// frontend/src/components/chat/artifacts/preview-registry.tsx
import type { ArtifactSummary } from '@/lib/types'

export interface ArtifactPreviewProps {
  artifact: ArtifactSummary
}

export interface ArtifactPreviewProvider {
  id: string
  priority: number
  match: (artifact: ArtifactSummary) => boolean
  Component: React.ComponentType<ArtifactPreviewProps>
}

export function pickPreviewProvider(
  artifact: ArtifactSummary,
  providers: ArtifactPreviewProvider[],
): ArtifactPreviewProvider {
  return [...providers]
    .sort((a, b) => b.priority - a.priority)
    .find((provider) => provider.match(artifact)) ?? fallbackPreviewProvider
}
```

Provider matching rules for the first integrated release:

- Image: `artifact.mime_type.startsWith('image/')`, except SVG unless sanitized policy is implemented.
- Audio/video: `audio/*`, `video/*`.
- Markdown: extension `md`, `markdown`, MIME `text/markdown`.
- Mermaid: extension `mmd`, `mermaid`, or display name ending `.mermaid`.
- Code/text/json/csv: text-like MIME or known code extension.
- Fallback: all files.

Markdown provider may reuse `MarkdownContent`, but set `isStreaming={false}`. Mermaid provider may reuse `MermaidDiagram` directly for `.mmd` files.

## 12. Task-by-task implementation plan

Each task should be implemented and committed separately. Commands assume the repository root is `/Users/chester/dev/ref/natural-mold`.

### Task 1: Artifact DB model and migration

**Files:**

- Create: `backend/app/models/conversation_artifact.py`
- Create: `backend/alembic/versions/<next>_add_conversation_artifacts.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_artifact_models.py`

- [ ] **Step 1: Write model import test**

```python
# backend/tests/test_artifact_models.py
from app.models import ArtifactVersion, ConversationArtifact


def test_artifact_models_are_registered() -> None:
    assert ConversationArtifact.__tablename__ == "conversation_artifacts"
    assert ArtifactVersion.__tablename__ == "artifact_versions"
```

- [ ] **Step 2: Run the failing test**

```bash
cd backend
uv run pytest tests/test_artifact_models.py -q
```

Expected: import failure because the models do not exist yet.

- [ ] **Step 3: Add model classes**

Use the complete model skeleton in section 11.4. Then add imports/exports in `backend/app/models/__init__.py`:

```python
from app.models.conversation_artifact import ArtifactVersion, ConversationArtifact
```

and include `"ArtifactVersion"` and `"ConversationArtifact"` in `__all__`.

- [ ] **Step 4: Add Alembic migration**

Migration must create both tables, indexes, unique constraints, and PostgreSQL CHECK constraints for status/storage provider values. Use `sa.JSON()` for `metadata_json` and `linked_message_ids` to keep tests dialect-friendly.

- [ ] **Step 5: Run the model test**

```bash
cd backend
uv run pytest tests/test_artifact_models.py -q
```

Expected: pass.

### Task 2: Artifact path and storage services

**Files:**

- Create: `backend/app/services/artifact_paths.py`
- Create: `backend/app/services/artifact_storage.py`
- Test: `backend/tests/test_artifact_paths.py`
- Test: `backend/tests/test_artifact_storage.py`

- [ ] **Step 1: Write path tests**

```python
# backend/tests/test_artifact_paths.py
from pathlib import Path

import pytest

from app.services.artifact_paths import ArtifactPathError, normalize_output_path, safe_storage_filename


def test_normalize_output_path_accepts_nested_file(tmp_path: Path) -> None:
    base = tmp_path / "outputs"
    target = base / "report" / "final.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Final", encoding="utf-8")

    normalized = normalize_output_path(base, target)

    assert normalized.logical_path == "report/final.md"
    assert normalized.display_name == "final.md"
    assert normalized.extension == "md"
    assert normalized.mime_type in {"text/markdown", "text/x-markdown", "text/plain"}


def test_normalize_output_path_rejects_escape(tmp_path: Path) -> None:
    base = tmp_path / "outputs"
    base.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ArtifactPathError):
        normalize_output_path(base, outside)


def test_safe_storage_filename_removes_control_and_slashes() -> None:
    assert safe_storage_filename("../weird:name.md") == "_weird_name.md"
```

- [ ] **Step 2: Run path tests and confirm failure**

```bash
cd backend
uv run pytest tests/test_artifact_paths.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement `artifact_paths.py`**

Use section 11.6 exactly, adjusting MIME assertion in tests only if Python's `mimetypes` differs on the local machine.

- [ ] **Step 4: Write storage tests**

```python
# backend/tests/test_artifact_storage.py
from pathlib import Path
import uuid

import pytest

from app.services.artifact_storage import LocalArtifactStorageBackend


@pytest.mark.asyncio
async def test_local_storage_copies_file_under_artifact_root(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("hello", encoding="utf-8")
    storage = LocalArtifactStorageBackend(tmp_path / "artifacts")
    conversation_id = uuid.uuid4()
    artifact_id = uuid.uuid4()

    stored = await storage.put_file(
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        version_number=1,
        display_name="final.md",
        source_path=source,
    )

    assert stored.storage_provider == "local"
    assert stored.bucket is None
    assert stored.object_key.endswith("/v1/final.md")
    assert stored.path is not None
    assert stored.path.read_text(encoding="utf-8") == "hello"
```

- [ ] **Step 5: Implement `artifact_storage.py` and run tests**

```bash
cd backend
uv run pytest tests/test_artifact_paths.py tests/test_artifact_storage.py -q
```

Expected: pass.

### Task 3: Artifact service ingest and event payloads

**Files:**

- Create: `backend/app/schemas/artifact.py`
- Create: `backend/app/services/artifact_service.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_artifact_service.py`

- [ ] **Step 1: Add config settings**

Add the config block from section 11.5.

- [ ] **Step 2: Write service ingest test**

```python
# backend/tests/test_artifact_service.py
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.conversation_artifact import ArtifactVersion, ConversationArtifact
from app.models.model import Model
from app.models.user import User
from app.services.artifact_service import (
    ArtifactDeltaRecorder,
    ArtifactRuntimeContext,
)
from app.services.artifact_storage import LocalArtifactStorageBackend
from tests.conftest import TEST_USER_ID, TestSession


async def _seed_conversation() -> tuple[uuid.UUID, uuid.UUID]:
    async with TestSession() as db:
        if await db.get(User, TEST_USER_ID) is None:
            db.add(User(id=TEST_USER_ID, email="test@test.com", name="Test"))
        model = Model(provider="openai", model_name="gpt-4o", display_name="GPT-4o")
        db.add(model)
        await db.flush()
        agent = Agent(
            user_id=TEST_USER_ID,
            name="Artifact Tester",
            description=None,
            system_prompt="...",
            model_id=model.id,
            status="active",
        )
        db.add(agent)
        await db.flush()
        conv = Conversation(agent_id=agent.id, title="Artifacts")
        db.add(conv)
        await db.commit()
        return conv.id, agent.id


@pytest.mark.asyncio
async def test_recorder_ingests_created_and_updated_file(tmp_path: Path) -> None:
    conv_id, agent_id = await _seed_conversation()
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    storage = LocalArtifactStorageBackend(tmp_path / "artifacts")
    recorder = ArtifactDeltaRecorder(
        session_factory=TestSession,
        context=ArtifactRuntimeContext(
            conversation_id=conv_id,
            user_id=TEST_USER_ID,
            agent_id=agent_id,
            assistant_msg_id="run-1",
            output_dir=output_dir,
        ),
        storage=storage,
    )

    await recorder.prepare()
    report = output_dir / "report.md"
    report.write_text("v1", encoding="utf-8")
    created = await recorder.collect_after_tool_result(
        tool_name="execute_in_skill",
        tool_call_id="call-1",
    )

    assert [event["op"] for event in created] == ["created"]
    artifact_id = created[0]["id"]

    report.write_text("v2", encoding="utf-8")
    updated = await recorder.collect_after_tool_result(
        tool_name="execute_in_skill",
        tool_call_id="call-1",
    )

    assert [event["op"] for event in updated] == ["updated"]
    assert updated[0]["id"] == artifact_id

    async with TestSession() as db:
        artifacts = (await db.execute(select(ConversationArtifact))).scalars().all()
        versions = (await db.execute(select(ArtifactVersion))).scalars().all()
        assert len(artifacts) == 1
        assert len(versions) == 2
        assert artifacts[0].logical_path == "report.md"
        assert artifacts[0].current_version_id == versions[-1].id
```

- [ ] **Step 3: Run the failing service test**

```bash
cd backend
uv run pytest tests/test_artifact_service.py -q
```

Expected: imports fail until service/schema exist.

- [ ] **Step 4: Implement service and schema**

Implement section 11.8 plus Pydantic response models. Event payload keys must match section 11.13 exactly: `id`, `conversation_id`, `assistant_msg_id`, `run_id`, `path`, `display_name`, `mime_type`, `extension`, `size_bytes`, `sha256`, `status`, `version_id`, `version_number`, `url`, `preview_url`, `download_url`, and `op`.

- [ ] **Step 5: Run service tests**

```bash
cd backend
uv run pytest tests/test_artifact_service.py -q
```

Expected: pass.

### Task 4: SSE file_event integration

**Files:**

- Modify: `backend/app/agent_runtime/event_names.py`
- Modify: `backend/app/agent_runtime/streaming.py`
- Modify: `backend/app/agent_runtime/executor.py`
- Modify: `backend/app/routers/conversations.py`
- Test: `backend/tests/integration/test_artifact_streaming.py`

- [ ] **Step 1: Write streaming integration test**

```python
# backend/tests/integration/test_artifact_streaming.py
from pathlib import Path
import uuid

import pytest

from app.agent_runtime.streaming import stream_agent_response
from app.services.artifact_service import ArtifactDeltaRecorder, ArtifactRuntimeContext
from app.services.artifact_storage import LocalArtifactStorageBackend
from tests.conftest import TEST_USER_ID, TestSession
from tests.test_artifact_service import _seed_conversation


class FakeAgent:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    async def astream(self, input_, config, stream_mode):
        from langchain_core.messages import ToolMessage
        target = self.output_dir / "chart.csv"
        target.write_text("x,y\n1,2\n", encoding="utf-8")
        yield ToolMessage(
            content="created chart",
            name="execute_in_skill",
            tool_call_id="call-1",
        ), {}

    async def aget_state(self, config):
        class State:
            tasks = []

        return State()


@pytest.mark.asyncio
async def test_stream_emits_file_event_after_execute_in_skill(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    conv_id, agent_id = await _seed_conversation()
    recorder = ArtifactDeltaRecorder(
        session_factory=TestSession,
        context=ArtifactRuntimeContext(
            conversation_id=conv_id,
            user_id=TEST_USER_ID,
            agent_id=agent_id,
            assistant_msg_id="run-artifact-1",
            output_dir=output_dir,
        ),
        storage=LocalArtifactStorageBackend(tmp_path / "artifacts"),
    )

    chunks = [
        chunk
        async for chunk in stream_agent_response(
            FakeAgent(output_dir),
            [{"role": "user", "content": "make csv"}],
            config={"configurable": {"thread_id": str(conv_id)}},
            run_id="run-artifact-1",
            artifact_recorder=recorder,
        )
    ]

    body = "".join(chunks)
    assert "event: tool_call_result" in body
    assert "event: file_event" in body
    assert '"path":"chart.csv"' in body or '"path": "chart.csv"' in body
```

This test may need a seeded conversation row if `ingest_changed_files()` enforces FK existence. If so, reuse `_seed_conversation()` from Task 3 instead of `uuid.uuid4()`.

- [ ] **Step 2: Run failing integration test**

```bash
cd backend
uv run pytest tests/integration/test_artifact_streaming.py -q
```

Expected: `artifact_recorder` parameter is not accepted or `file_event` constant is missing.

- [ ] **Step 3: Add `FILE_EVENT` constant**

```python
# backend/app/agent_runtime/event_names.py
FILE_EVENT: Final = "file_event"
```

- [ ] **Step 4: Implement streaming/executor/router pass-through**

Apply sections 11.9, 11.10, and 11.11. Keep `OUTPUT_FILES` in `execute_in_skill` unchanged.

- [ ] **Step 5: Run streaming tests**

```bash
cd backend
uv run pytest tests/integration/test_artifact_streaming.py tests/integration/test_broker_dual_write.py tests/integration/test_stream_resume.py -q
```

Expected: pass. `test_stream_resume.py` is included because `file_event` must not break DB replay slicing.

### Task 5: Artifact APIs and existing file endpoint guard

**Files:**

- Create: `backend/app/routers/artifacts.py`
- Modify: `backend/app/routers/conversations.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_artifacts_router.py`
- Test: `backend/tests/test_artifact_library_router.py`

- [ ] **Step 1: Write router tests**

```python
# backend/tests/test_artifacts_router.py
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.artifact_service import ArtifactDeltaRecorder, ArtifactRuntimeContext
from app.services.artifact_storage import LocalArtifactStorageBackend
from tests.conftest import TEST_USER_ID, TestSession
from tests.test_artifact_service import _seed_conversation


@pytest.mark.asyncio
async def test_artifact_list_and_download(client: AsyncClient, tmp_path: Path) -> None:
    conv_id, agent_id = await _seed_conversation()
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "report.md").write_text("# Report", encoding="utf-8")
    recorder = ArtifactDeltaRecorder(
        session_factory=TestSession,
        context=ArtifactRuntimeContext(
            conversation_id=conv_id,
            user_id=TEST_USER_ID,
            agent_id=agent_id,
            assistant_msg_id="run-api-1",
            output_dir=output_dir,
        ),
        storage=LocalArtifactStorageBackend(tmp_path / "artifacts"),
    )
    await recorder.prepare()
    await recorder.collect_after_tool_result(tool_name="execute_in_skill", tool_call_id="call-1")

    resp = await client.get(f"/api/conversations/{conv_id}/artifacts")
    assert resp.status_code == 200, resp.text
    artifacts = resp.json()
    assert len(artifacts) == 1
    artifact_id = artifacts[0]["id"]

    content_resp = await client.get(
        f"/api/conversations/{conv_id}/artifacts/{artifact_id}/content"
    )
    assert content_resp.status_code == 200
    assert "# Report" in content_resp.json()["text"]

    download_resp = await client.get(
        f"/api/conversations/{conv_id}/artifacts/{artifact_id}/download"
    )
    assert download_resp.status_code == 200
    assert download_resp.content == b"# Report"
```

```python
# backend/tests/test_artifact_library_router.py
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.artifact_service import ArtifactDeltaRecorder, ArtifactRuntimeContext
from app.services.artifact_storage import LocalArtifactStorageBackend
from tests.conftest import TEST_USER_ID, TestSession
from tests.test_artifact_service import _seed_conversation


@pytest.mark.asyncio
async def test_generated_file_library_search_favorite_and_stats(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    conv_id, agent_id = await _seed_conversation()
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "report.md").write_text("# Report", encoding="utf-8")
    recorder = ArtifactDeltaRecorder(
        session_factory=TestSession,
        context=ArtifactRuntimeContext(
            conversation_id=conv_id,
            user_id=TEST_USER_ID,
            agent_id=agent_id,
            assistant_msg_id="run-library-1",
            output_dir=output_dir,
        ),
        storage=LocalArtifactStorageBackend(tmp_path / "artifacts"),
    )
    await recorder.prepare()
    await recorder.collect_after_tool_result(tool_name="execute_in_skill", tool_call_id="call-1")

    list_resp = await client.get("/api/artifacts", params={"q": "report", "kind": "markdown"})
    assert list_resp.status_code == 200, list_resp.text
    page = list_resp.json()
    assert len(page["items"]) == 1
    artifact_id = page["items"][0]["id"]

    fav_resp = await client.patch(f"/api/artifacts/{artifact_id}", json={"is_favorite": True})
    assert fav_resp.status_code == 200
    assert fav_resp.json()["is_favorite"] is True

    stats_resp = await client.get("/api/artifacts/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total_count"] == 1
    assert stats["favorite_count"] == 1
    assert stats["by_kind"][0]["kind"] == "markdown"
```

- [ ] **Step 2: Run failing router tests**

```bash
cd backend
uv run pytest tests/test_artifacts_router.py tests/test_artifact_library_router.py -q
```

Expected: routes do not exist.

- [ ] **Step 3: Implement `artifacts.py` router**

Use the route contract in section 11.12. Register it in `backend/app/main.py`:

```python
from app.routers import artifacts
...
app.include_router(artifacts.router)
```

Follow the existing import block style around `uploads`, `shares`, and `conversations`.

- [ ] **Step 4: Fix legacy file endpoint owner guard**

In `get_conversation_file()`, replace `chat_service.get_conversation` with `chat_service.get_owned_conversation` as shown in section 11.11.

- [ ] **Step 5: Run router tests**

```bash
cd backend
uv run pytest tests/test_artifacts_router.py tests/test_artifact_library_router.py tests/test_conversations_router.py -q
```

Expected: pass.

### Task 6: Frontend types, store, and SSE handling

**Files:**

- Modify: `frontend/src/lib/types/index.ts`
- Create: `frontend/src/lib/stores/chat-artifacts.ts`
- Modify: `frontend/src/lib/chat/use-chat-runtime.ts`
- Test: `frontend/src/lib/stores/__tests__/chat-artifacts.test.ts`
- Test: `frontend/src/lib/chat/__tests__/use-chat-runtime-commit.test.tsx`

- [ ] **Step 1: Write artifact store test**

```ts
// frontend/src/lib/stores/__tests__/chat-artifacts.test.ts
import { createStore } from 'jotai'
import { describe, expect, it } from 'vitest'
import { chatArtifactsAtom, upsertChatArtifactAtom } from '../chat-artifacts'
import type { FileEventPayload } from '@/lib/types'

function payload(overrides: Partial<FileEventPayload> = {}): FileEventPayload {
  return {
    op: 'created',
    id: 'artifact-1',
    agent_id: 'agent-1',
    conversation_id: 'conv-1',
    assistant_msg_id: 'run-1',
    run_id: 'run-1',
    tool_call_id: 'call-1',
    source_tool_name: 'execute_in_skill',
    path: 'report.md',
    display_name: 'report.md',
    mime_type: 'text/markdown',
    extension: 'md',
    artifact_kind: 'markdown',
    size_bytes: 6,
    sha256: 'a'.repeat(64),
    status: 'ready',
    is_favorite: false,
    last_opened_at: null,
    preview_count: 0,
    download_count: 0,
    version_id: 'version-1',
    version_number: 1,
    created_at: '2026-06-05T00:00:00Z',
    updated_at: '2026-06-05T00:00:00Z',
    url: '/api/conversations/conv-1/artifacts/artifact-1',
    preview_url: '/api/conversations/conv-1/artifacts/artifact-1/content',
    download_url: '/api/conversations/conv-1/artifacts/artifact-1/download',
    ...overrides,
  }
}

describe('chat artifact store', () => {
  it('upserts by artifact id and removes deleted artifacts', () => {
    const store = createStore()
    store.set(upsertChatArtifactAtom, payload())
    store.set(upsertChatArtifactAtom, payload({ op: 'updated', version_number: 2 }))

    expect(store.get(chatArtifactsAtom)['conv-1']).toHaveLength(1)
    expect(store.get(chatArtifactsAtom)['conv-1'][0].version_number).toBe(2)

    store.set(upsertChatArtifactAtom, payload({ op: 'deleted' }))
    expect(store.get(chatArtifactsAtom)['conv-1']).toEqual([])
  })
})
```

- [ ] **Step 2: Run failing frontend store test**

```bash
cd frontend
pnpm test frontend/src/lib/stores/__tests__/chat-artifacts.test.ts
```

Expected: store file does not exist. If the project test script uses Vitest path syntax differently, use the same command pattern as existing frontend tests.

- [ ] **Step 3: Add TS types and store**

Use sections 11.13 and 11.14.

- [ ] **Step 4: Update `use-chat-runtime.ts`**

Import and set `upsertChatArtifactAtom`; add the `file_event` switch case. Existing tests mock `useSetAtom`, so ensure the new setter does not require provider changes.

- [ ] **Step 5: Run frontend tests**

```bash
cd frontend
pnpm test frontend/src/lib/stores/__tests__/chat-artifacts.test.ts frontend/src/lib/chat/__tests__/use-chat-runtime-commit.test.tsx
```

Expected: pass.

### Task 7: Artifact right rail and preview registry

**Files:**

- Modify: `frontend/src/lib/stores/chat-right-rail.ts`
- Modify: `frontend/src/components/chat/right-rail/chat-right-rail.tsx`
- Create: `frontend/src/components/chat/right-rail/artifact-panel-content.tsx`
- Create: preview provider files listed in section 11.3
- Modify: `frontend/messages/ko.json`
- Modify: `frontend/messages/en.json`
- Test: `frontend/src/components/chat/artifacts/__tests__/preview-registry.test.tsx`

- [ ] **Step 1: Write preview registry test**

```tsx
// frontend/src/components/chat/artifacts/__tests__/preview-registry.test.tsx
import { describe, expect, it } from 'vitest'
import { pickPreviewProvider } from '../preview-registry'
import { imagePreviewProvider } from '../providers/image-preview'
import { markdownPreviewProvider } from '../providers/markdown-preview'
import { fallbackPreviewProvider } from '../providers/fallback-preview'
import type { ArtifactSummary } from '@/lib/types'

function artifact(overrides: Partial<ArtifactSummary>): ArtifactSummary {
  return {
    id: 'a1',
    agent_id: 'agent-1',
    conversation_id: 'c1',
    assistant_msg_id: 'r1',
    run_id: 'r1',
    path: 'file.bin',
    display_name: 'file.bin',
    mime_type: 'application/octet-stream',
    extension: 'bin',
    artifact_kind: 'other',
    size_bytes: 1,
    sha256: 'a'.repeat(64),
    status: 'ready',
    is_favorite: false,
    last_opened_at: null,
    preview_count: 0,
    download_count: 0,
    version_id: 'v1',
    version_number: 1,
    created_at: '2026-06-05T00:00:00Z',
    updated_at: '2026-06-05T00:00:00Z',
    url: '#',
    preview_url: '#',
    download_url: '#',
    ...overrides,
  }
}

describe('artifact preview registry', () => {
  it('prefers specific providers over fallback', () => {
    const providers = [fallbackPreviewProvider, markdownPreviewProvider, imagePreviewProvider]
    expect(pickPreviewProvider(artifact({ mime_type: 'image/png', extension: 'png' }), providers).id).toBe('image')
    expect(pickPreviewProvider(artifact({ mime_type: 'text/markdown', extension: 'md' }), providers).id).toBe('markdown')
    expect(pickPreviewProvider(artifact({ mime_type: 'application/octet-stream' }), providers).id).toBe('fallback')
  })
})
```

- [ ] **Step 2: Run failing preview test**

```bash
cd frontend
pnpm test frontend/src/components/chat/artifacts/__tests__/preview-registry.test.tsx
```

Expected: provider files do not exist.

- [ ] **Step 3: Implement right rail state**

Apply section 11.15. Add i18n keys:

```json
// frontend/messages/ko.json
{
  "chat": {
    "rightRail": {
      "artifacts": "文件"
    },
    "artifacts": {
      "empty": "尚未生成文件。",
      "download": "下载",
      "previewUnavailable": "该文件不支持预览。"
    }
  }
}
```

```json
// frontend/messages/en.json
{
  "chat": {
    "rightRail": {
      "artifacts": "Files"
    },
    "artifacts": {
      "empty": "No files have been generated yet.",
      "download": "Download",
      "previewUnavailable": "Preview is not available for this file."
    }
  }
}
```

Merge these keys into existing JSON objects rather than replacing the whole files.

- [ ] **Step 4: Implement preview providers**

Use native elements for image/audio/video, `MarkdownContent` for Markdown, `MermaidDiagram` for Mermaid, and syntax highlighter/text fallback for code/text. Keep provider components small and lazy-load heavy pieces if bundle size rises.

- [ ] **Step 5: Run frontend checks**

```bash
cd frontend
pnpm test frontend/src/components/chat/artifacts/__tests__/preview-registry.test.tsx
pnpm lint:i18n
pnpm lint:design-system
```

Expected: pass.

### Task 8: Generated File Library UI

**Files:**

- Create: `frontend/src/app/artifacts/page.tsx`
- Create: `frontend/src/components/artifacts/artifact-library-content.tsx`
- Create: `frontend/src/components/artifacts/artifact-library-filters.tsx`
- Create: `frontend/src/components/artifacts/artifact-library-stats.tsx`
- Create: `frontend/src/lib/hooks/use-artifact-library.ts`
- Modify: `frontend/src/lib/api/artifacts.ts`
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/components/layout/breadcrumb-nav.tsx`
- Modify: `frontend/messages/ko.json`
- Modify: `frontend/messages/en.json`
- Test: `frontend/src/lib/hooks/__tests__/use-artifact-library.test.tsx`

- [ ] **Step 1: Write library API hook test**

```tsx
// frontend/src/lib/hooks/__tests__/use-artifact-library.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useArtifactLibrary } from '../use-artifact-library'

vi.mock('@/lib/api/artifacts', () => ({
  listArtifactLibrary: vi.fn(async () => ({
    items: [],
    next_cursor: null,
    has_more: false,
  })),
}))

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useArtifactLibrary', () => {
  afterEach(() => vi.clearAllMocks())

  it('returns generated file library results', async () => {
    const { result } = renderHook(
      () => useArtifactLibrary({ q: 'report', kind: 'markdown', favorite: true }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toEqual([])
  })
})
```

- [ ] **Step 2: Run failing hook test**

```bash
cd frontend
pnpm test frontend/src/lib/hooks/__tests__/use-artifact-library.test.tsx
```

Expected: hook/API files do not exist.

- [ ] **Step 3: Implement artifact library API client and hook**

`frontend/src/lib/api/artifacts.ts` should expose:

```ts
listConversationArtifacts(conversationId: string): Promise<ArtifactSummary[]>
listArtifactLibrary(params: ArtifactLibraryParams): Promise<ArtifactLibraryPage>
getArtifactLibraryStats(): Promise<ArtifactLibraryStats>
toggleArtifactFavorite(artifactId: string, isFavorite: boolean): Promise<ArtifactSummary>
recordArtifactOpened(artifactId: string): Promise<ArtifactSummary>
```

`useArtifactLibrary` should use a query key that includes `q`, `agent_id`, `conversation_id`, `kind`, `favorite`, and cursor.

- [ ] **Step 4: Implement `/artifacts` page**

The page should render the actual file library as the first screen:

- search input
- agent filter
- conversation filter
- kind filter
- favorite filter
- stats strip
- dense file list or grid
- preview/detail pane using the same `ArtifactPreview` and provider registry from Task 7

Do not make a landing page for this route.

- [ ] **Step 5: Add navigation and i18n**

Add a sidebar item pointing to `/artifacts` and breadcrumb label `nav.artifacts`. Add Korean and English copy under `artifacts.library`.

- [ ] **Step 6: Run library UI checks**

```bash
cd frontend
pnpm test frontend/src/lib/hooks/__tests__/use-artifact-library.test.tsx
pnpm lint:i18n
pnpm lint:design-system
```

Expected: pass.

### Task 9: End-to-end verification

**Files:**

- No required new files if backend/frontend unit coverage is enough.
- Add Playwright coverage only if an existing chat E2E suite is already active for this branch.

- [ ] **Step 1: Backend full targeted run**

```bash
cd backend
uv run pytest \
  tests/test_artifact_models.py \
  tests/test_artifact_paths.py \
  tests/test_artifact_storage.py \
  tests/test_artifact_service.py \
  tests/test_artifacts_router.py \
  tests/test_artifact_library_router.py \
  tests/integration/test_artifact_streaming.py \
  tests/integration/test_broker_dual_write.py \
  tests/integration/test_stream_resume.py \
  -q
```

Expected: pass.

- [ ] **Step 2: Frontend targeted run**

```bash
cd frontend
pnpm test \
  frontend/src/lib/stores/__tests__/chat-artifacts.test.ts \
  frontend/src/lib/hooks/__tests__/use-artifact-library.test.tsx \
  frontend/src/components/chat/artifacts/__tests__/preview-registry.test.tsx \
  frontend/src/lib/chat/__tests__/use-chat-runtime-commit.test.tsx
pnpm lint:i18n
pnpm lint:design-system
```

Expected: pass.

- [ ] **Step 3: Manual local verification**

Start servers with the project worktree port rules:

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8001 --reload-dir app
```

```bash
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 pnpm dev -- --port 3000
```

Create or use a skill that writes `report.md` to `$SKILL_OUTPUT_DIR`, send a chat message that triggers `execute_in_skill`, and verify:

- SSE stream contains `event: file_event`.
- Right rail can open `Files`.
- `/artifacts` library shows the generated file.
- Library search finds `report.md`.
- Favorite toggle persists after refresh.
- Stats reflect total count and markdown kind count.
- `report.md` appears without waiting for final answer text links.
- Markdown preview renders in the side panel.
- Download endpoint returns the exact file bytes.
- Existing inline Markdown/Mermaid/image rendering in chat messages still works.
