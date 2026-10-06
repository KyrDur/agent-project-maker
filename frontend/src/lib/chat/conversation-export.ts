import type { Message, MessagesEnvelope, ToolCallInfo } from '@/lib/types'

/**
 * 对话 export（G5）。将前端已加载的 ``envelope.messages`` 转为 markdown/json
 * （无需 backend export API）。纯函数——用户可见标签通过 i18n
 * 由调用方（ExportDialog）注入。日期保留 ISO 原值以便机器解析。
 */

export interface ExportLabels {
  readonly roleUser: string
  readonly roleAssistant: string
  readonly roleTool: string
  readonly toolCalls: string
  readonly attachments: string
  readonly exportedAt: string
}

function roleLabel(role: Message['role'], labels: ExportLabels): string {
  if (role === 'user') return labels.roleUser
  if (role === 'assistant') return labels.roleAssistant
  return labels.roleTool
}

function toolCallsToMarkdown(toolCalls: readonly ToolCallInfo[], label: string): string {
  const lines = toolCalls.map((call) => `- \`${call.name}\` ${JSON.stringify(call.args)}`)
  return `**${label}:**\n${lines.join('\n')}`
}

function attachmentsToMarkdown(
  attachments: readonly { readonly filename: string; readonly url: string }[],
  label: string,
): string {
  const lines = attachments.map((attachment) => `- [${attachment.filename}](${attachment.url})`)
  return `**${label}:**\n${lines.join('\n')}`
}

function messageToMarkdown(message: Message, labels: ExportLabels): string {
  const parts: string[] = [`## ${roleLabel(message.role, labels)} · ${message.created_at}`]
  const content = message.content.trim()
  if (content) parts.push(content)
  if (message.tool_calls && message.tool_calls.length > 0) {
    parts.push(toolCallsToMarkdown(message.tool_calls, labels.toolCalls))
  }
  if (message.attachments && message.attachments.length > 0) {
    parts.push(attachmentsToMarkdown(message.attachments, labels.attachments))
  }
  return parts.join('\n\n')
}

export function conversationToMarkdown(
  messages: readonly Message[],
  opts: { readonly title: string; readonly exportedAt: string; readonly labels: ExportLabels },
): string {
  const header = `# ${opts.title}\n\n_${opts.labels.exportedAt}: ${opts.exportedAt}_`
  const blocks = messages.map((message) => messageToMarkdown(message, opts.labels))
  return `${[header, ...blocks].join('\n\n---\n\n')}\n`
}

export function conversationToJson(envelope: MessagesEnvelope): string {
  return `${JSON.stringify(envelope, null, 2)}\n`
}

export function exportFilename(
  conversationId: string,
  ext: 'md' | 'json',
  timestamp: string,
): string {
  return `conversation-${conversationId}-${timestamp}.${ext}`
}

/** 客户端 Blob 下载（mcp-servers export 模式）。属于 DOM 副作用，因此不纳入工具函数测试。 */
export function downloadTextFile(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
