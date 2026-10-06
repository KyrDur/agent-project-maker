import type { ArtifactKind, ArtifactSummary, MessageAttachmentBrief } from '@/lib/types'

/** filename → 扩展名（小写，去掉前导点）。没有扩展名时为 null。 */
export function extensionFromFilename(filename: string): string | null {
  const dot = filename.lastIndexOf('.')
  if (dot <= 0 || dot === filename.length - 1) return null
  return filename.slice(dot + 1).toLowerCase()
}

/**
 * mime_type → ArtifactKind。预览 registry 优先按 mime/extension
 * dispatch，但 kind 也是辅助匹配键，因此保持一致填充。
 */
export function artifactKindFromMime(mimeType: string): ArtifactKind {
  const mime = mimeType.toLowerCase()
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('video/')) return 'video'
  if (mime.startsWith('audio/')) return 'audio'
  if (mime === 'application/pdf') return 'pdf'
  if (mime === 'text/markdown') return 'markdown'
  if (mime === 'text/html' || mime === 'application/xhtml+xml') return 'html'
  if (mime === 'application/json') return 'data'
  if (mime.startsWith('text/')) return 'code'
  return 'other'
}

/**
 * 将已发送消息的附件（``MessageAttachmentBrief``）映射为现有 artifact 预览 registry
 * 可消费的 ``ArtifactSummary`` 形态。
 *
 * - 附件并不是真正的 conversation artifact，因此 artifact 专用标识符
 *   （agent_id/conversation_id/version 等）使用安全默认值。
 * - ``url``/``preview_url``/``download_url`` 都指向上传下载 URL
 *   （``/api/uploads/{id}``）——图片/PDF 预览只依赖这个 URL 即可渲染。
 */
export function attachmentToArtifactSummary(att: MessageAttachmentBrief): ArtifactSummary {
  return {
    id: att.id,
    agent_id: '',
    conversation_id: '',
    assistant_msg_id: '',
    run_id: '',
    tool_call_id: null,
    source_tool_name: null,
    path: att.filename,
    display_name: att.filename,
    mime_type: att.mime_type,
    extension: extensionFromFilename(att.filename),
    artifact_kind: artifactKindFromMime(att.mime_type),
    size_bytes: att.size_bytes,
    sha256: '',
    status: 'ready',
    is_favorite: false,
    last_opened_at: null,
    preview_count: 0,
    download_count: 0,
    version_id: '',
    version_number: 0,
    created_at: '',
    updated_at: '',
    agent_name: null,
    conversation_title: null,
    url: att.url,
    preview_url: att.url,
    download_url: att.url,
  }
}
