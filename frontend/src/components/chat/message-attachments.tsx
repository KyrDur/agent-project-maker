'use client'

import { useMemo, useState } from 'react'
import { useAuiState } from '@assistant-ui/react'
import { FileIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { DialogShell } from '@/components/shared/dialog-shell'
import { ArtifactPreview } from '@/components/chat/artifacts/artifact-preview'
import { ChatImage } from '@/components/chat/chat-image'
import { attachmentToArtifactSummary } from '@/lib/chat/attachment-to-artifact'
import { getAttachmentTextPreview } from '@/lib/chat/attachment-preview'
import { useChatConversationId } from '@/components/chat/conversation-context'
import { useConversationFiles } from '@/lib/hooks/use-conversation-files'
import type { FileItem, MessageAttachmentBrief } from '@/lib/types'

/** Unified-files attachment row → the brief the preview cards consume. */
export function fileItemToBrief(file: FileItem): MessageAttachmentBrief {
  return {
    id: file.id,
    filename: file.name,
    mime_type: file.mime_type,
    size_bytes: file.size_bytes ?? 0,
    url: file.preview_url,
  }
}

/**
 * 非图片附件（PDF/文档/文本……）的预览 dialog。
 *
 * 使用与图片打开的 ``ChatImage`` lightbox **相同的全屏 ``DialogShell`` 外壳**，
 * 让两个 viewer 在视觉上保持一致（内容由 ``ArtifactPreview`` 按类型
 * render —— 不支持时 fallback 到下载）。仅在 ``open`` 时 mount，避免无用 fetch。
 */
export function AttachmentPreviewDialog({
  brief,
  open,
  onOpenChange,
}: {
  brief: MessageAttachmentBrief
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      height="auto"
      className="moldy-dialog-attachment-preview"
    >
      <DialogShell.Header title={<span className="truncate">{brief.filename}</span>} />
      <DialogShell.Body className="min-h-0 overflow-auto">
        {open ? (
          <ArtifactPreview
            artifact={attachmentToArtifactSummary(brief)}
            textLoader={() => getAttachmentTextPreview(brief.id)}
          />
        ) : null}
      </DialogShell.Body>
    </DialogShell>
  )
}

/**
 * 已发送消息气泡中显示的 1 个附件。
 * - 图片：复用聊天公共 ``ChatImage`` → 与 markdown/inline image 相同的
 *   缩略图 + 点击后全屏 lightbox（一致 UX）。
 * - 其他(PDF/文档/文本)：文件 chip → ``ArtifactPreview`` dialog（不支持时 fallback 到下载）。
 * 因为是已发送附件，所以只读（不可移除/修改）。
 */
export function MessageAttachmentItem({ brief }: { brief: MessageAttachmentBrief }) {
  const tMessageArtifacts = useTranslations('chat.message.artifacts')
  const [open, setOpen] = useState(false)

  if (brief.mime_type.startsWith('image/')) {
    return <ChatImage src={brief.url} alt={brief.filename} />
  }

  const openLabel = tMessageArtifacts('openLabel', { name: brief.filename })
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={openLabel}
        title={brief.filename}
        className="moldy-card-hover inline-flex max-w-56 items-center gap-2 rounded-lg border border-border bg-muted/40 px-2.5 py-2 text-left transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
          <FileIcon className="size-3.5" />
        </span>
        <span className="min-w-0 truncate text-xs text-foreground">{brief.filename}</span>
      </button>
      <AttachmentPreviewDialog brief={brief} open={open} onOpenChange={setOpen} />
    </>
  )
}

/**
 * 已发送 user 消息气泡的附件行。通过 assistant-ui ``MessagePrimitive.Attachments``
 * render-prop 遍历各附件。没有附件时不渲染任何内容。
 *
 * 无限 render guard：count selector 只返回 reference-stable 的数字。
 */
export function UserMessageAttachments() {
  // The v3 runtime builds messages from LangGraph state (LangChain messages),
  // which do NOT carry the moldy attachment side channel — so `s.message`
  // never exposes `attachments`. Instead we key off the message id (which
  // equals the backfilled `message_attachments.message_id` — same id the
  // anchor/jump uses) and look this turn's attachments up from the unified
  // `/files` list. Reference-stable selector (a string id) avoids re-render loops.
  const conversationId = useChatConversationId()
  const messageId = useAuiState((s) => (s.message?.role === 'user' ? s.message.id : null))
  const { data } = useConversationFiles(conversationId)
  const briefs = useMemo<MessageAttachmentBrief[]>(() => {
    if (!messageId) return []
    return (data ?? [])
      .filter((f) => f.source === 'attached' && f.message_id === messageId)
      .map(fileItemToBrief)
  }, [data, messageId])

  if (briefs.length === 0) return null
  return (
    <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
      {briefs.map((brief) => (
        <MessageAttachmentItem key={brief.id} brief={brief} />
      ))}
    </div>
  )
}
