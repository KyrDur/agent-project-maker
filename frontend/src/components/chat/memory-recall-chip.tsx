'use client'

import { useMemo } from 'react'
import { BrainIcon } from 'lucide-react'
import { useAtomValue } from 'jotai'
import { useTranslations } from 'next-intl'
import { CollapsiblePill } from '@/components/chat/tool-ui/collapsible-pill'
import { useChatConversationId } from '@/components/chat/conversation-context'
import { useMemories } from '@/lib/hooks/use-memory'
import { chatMemoryRecallAtom, type RecalledMemoryBrief } from '@/lib/stores/chat-memory-recall'

/** 持久化事件的记忆内容掩码值（backend protocol_redaction 约定）。 */
const REDACTED_CONTENT = '<redacted>'

function MemoryRecallList({ memories }: { readonly memories: readonly RecalledMemoryBrief[] }) {
  const t = useTranslations('chat.memoryRecall')
  return (
    <ul className="space-y-1 border-t border-border/60 px-3 py-2">
      {memories.map((memory, index) => (
        <li
          key={memory.id ?? index}
          className="flex items-start gap-2"
          data-moldy-memory-recall-item={memory.scope}
        >
          <span className="mt-0.5 shrink-0 rounded-full bg-muted px-1.5 py-0.5 moldy-ui-micro font-medium text-muted-foreground">
            {memory.scope === 'user' ? t('scopeUser') : t('scopeAgent')}
          </span>
          <span className="min-w-0 flex-1 moldy-ui-caption leading-relaxed text-foreground/80">
            {memory.content && memory.content !== REDACTED_CONTENT ? (
              memory.content
            ) : (
              <span className="text-muted-foreground">{t('hiddenContent')}</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

/**
 * reload 路径 —— 持久化的回忆事件中的记忆内容会被 `<redacted>` 掩码
 * （共享/快照安全约定），因此用 brief 的 id 从 Memory API 重新查询内容
 * 并合并。与 memory-tool-ui 通过服务器重新查询恢复 proposal 的模式相同
 * —— 这是仅 owner 可用的 API，因此在共享页面不会恢复。
 * （该组件仅在存在 redacted brief 时 mount，不会产生无用 fetch。）
 */
function MemoryRecallListWithJoin({
  memories,
}: {
  readonly memories: readonly RecalledMemoryBrief[]
}) {
  const records = useMemories()
  const resolved = useMemo<readonly RecalledMemoryBrief[]>(() => {
    const contentById = new Map(
      (records.data ?? []).map((record) => [record.id, record.content] as const),
    )
    return memories.map((memory) =>
      memory.content === REDACTED_CONTENT && memory.id
        ? { ...memory, content: contentById.get(memory.id) ?? '' }
        : memory,
    )
  }, [memories, records.data])
  return <MemoryRecallList memories={resolved} />
}

/**
 * MemoryRecallChip —— 显示本次 run 注入 system prompt 的长期记忆（回忆）的
 * 常驻 chip。数据由 `moldy.memory_recalled` stream-head 事件
 * (memory-recall-events.ts) 填入对话级 atom。没有回忆的对话
 * 不渲染。展开后显示 scope badge + 记忆预览列表。
 */
export function MemoryRecallChip() {
  const t = useTranslations('chat.memoryRecall')
  const conversationId = useChatConversationId()
  const recallState = useAtomValue(chatMemoryRecallAtom)
  const memories = conversationId ? (recallState[conversationId] ?? []) : []
  const hasRedacted = memories.some((memory) => memory.content === REDACTED_CONTENT)

  if (memories.length === 0) return null

  return (
    <div
      className="border-b border-border/60 bg-background/95 px-4 py-1.5"
      data-moldy-memory-recall="true"
    >
      <div className="mx-auto w-full max-w-3xl">
        <CollapsiblePill
          kind="thinking"
          status="success"
          leadingIcon={BrainIcon}
          title={t('title')}
          meta={t('count', { count: memories.length })}
          defaultExpanded={false}
        >
          {hasRedacted ? (
            <MemoryRecallListWithJoin memories={memories} />
          ) : (
            <MemoryRecallList memories={memories} />
          )}
        </CollapsiblePill>
      </div>
    </div>
  )
}
