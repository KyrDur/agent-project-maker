'use client'

import type { ToolCallMessagePartProps } from '@assistant-ui/react'
import { useTranslations } from 'next-intl'
import { BookOpenIcon, FileIcon } from 'lucide-react'
import { CollapsiblePill, pillStatusFromAssistantUi } from './collapsible-pill'
import { useIsToolGroupChild } from './tool-group-child-context'
import { useChatConversationId } from '@/components/chat/conversation-context'
import { API_BASE } from '@/lib/api/client'

// ──────────────────────────────────────────────
// SkillExecutionToolUI — execute_in_skill 专用富媒体 pill (W2-4/6)。
//
// 职责划分：stdout 由 moldy.ui_data terminal 卡片负责，生成文件预览由
// artifact 卡片负责。这个 pill 只负责"哪个技能执行了什么命令，
// 产出了哪些文件"的摘要 + 文件链接。
//
// 实时运行中 HITL 批准卡片显示期间，raw pill 会被
// stripInterruptedRawToolCalls 隐藏 — 这个卡片主要会出现在
// 重新加载后的对话以及 HITL 被关闭（允许）的执行中。
// ──────────────────────────────────────────────

interface SkillExecutionArgs {
  skill_directory?: string
  command?: string
  [key: string]: unknown
}

/** 从 skill_directory 虚拟路径中提取技能名称（最后一个片段）。 */
export function skillNameFromDirectory(directory: unknown): string | null {
  if (typeof directory !== 'string') return null
  const segments = directory.split('/').filter(Boolean)
  const last = segments[segments.length - 1]
  return last && last !== 'skills' ? last : null
}

/** 从结果字符串末尾的 `OUTPUT_FILES: a.md, b.png` 契约行中提取文件名列表。 */
export function outputFilesFromResult(result: unknown): string[] {
  if (typeof result !== 'string') return []
  const marker = 'OUTPUT_FILES:'
  const index = result.lastIndexOf(marker)
  if (index === -1) return []
  return result
    .slice(index + marker.length)
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean)
}

function SkillExecutionRender({
  args,
  result,
  status,
}: {
  args: SkillExecutionArgs
  result?: unknown
  status: { readonly type: string }
}) {
  const t = useTranslations('chat.toolCall.skillExecution')
  const isGroupChild = useIsToolGroupChild()
  const conversationId = useChatConversationId()
  const isRunning = status.type === 'running'
  const skillName = skillNameFromDirectory(args?.skill_directory)
  const command = typeof args?.command === 'string' ? args.command : ''
  const files = isRunning ? [] : outputFilesFromResult(result)

  const title = skillName ?? t('fallbackTitle')
  const meta = isRunning
    ? t('running')
    : files.length > 0
      ? t('files', { count: files.length })
      : t('completed')

  const hasBody = Boolean(command) || files.length > 0
  const body = hasBody ? (
    <div className="space-y-2 border-t border-border/60 px-3 py-2">
      {command ? (
        <div>
          <div className="mb-1 moldy-ui-micro font-semibold uppercase tracking-wider text-muted-foreground">
            {t('command')}
          </div>
          <pre className="whitespace-pre-wrap break-all rounded-md bg-muted/45 px-2 py-1.5 font-mono moldy-ui-caption text-foreground/85">
            {command}
          </pre>
        </div>
      ) : null}
      {files.length > 0 ? (
        <div>
          <div className="mb-1 moldy-ui-micro font-semibold uppercase tracking-wider text-muted-foreground">
            {t('outputFiles')}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {files.map((name) => (
              <a
                key={name}
                href={
                  conversationId
                    ? `${API_BASE}/api/conversations/${conversationId}/files/${encodeURIComponent(name)}`
                    : undefined
                }
                target="_blank"
                rel="noopener noreferrer"
                data-moldy-skill-file={name}
                className="inline-flex max-w-56 items-center gap-1 rounded-md border border-border/60 bg-background px-2 py-1 moldy-ui-caption text-foreground/85 transition-colors hover:bg-accent hover:text-foreground"
              >
                <FileIcon className="size-3 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{name}</span>
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  ) : undefined

  return (
    <div data-moldy-skill-execution={skillName ?? 'unknown'}>
      <CollapsiblePill
        kind="tool"
        leadingIcon={BookOpenIcon}
        status={pillStatusFromAssistantUi(status.type)}
        title={title}
        meta={meta}
        defaultExpanded={!isGroupChild && files.length > 0}
        renderBody={body ? () => body : undefined}
      />
    </div>
  )
}

export function SkillExecutionToolUI(props: ToolCallMessagePartProps<SkillExecutionArgs, unknown>) {
  return <SkillExecutionRender {...props} />
}
