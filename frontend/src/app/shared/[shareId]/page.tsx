'use client'

import { use, useMemo } from 'react'
import Link from 'next/link'
import dynamic from 'next/dynamic'
import { AlertCircleIcon, ArrowLeftIcon, MessageSquareIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { AgentAvatar } from '@/components/agent/agent-avatar'
import { CollapsiblePill } from '@/components/chat/tool-ui/collapsible-pill'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { usePublicShare } from '@/lib/hooks/use-share'
import { extractChips, type ChipInfo } from '@/lib/share/extract-chips'
import { formatLongDate, formatMediumDate } from '@/lib/utils/format-relative-time'
import type { Message } from '@/lib/types'
import type { SharedConversationView, TurnTrace } from '@/lib/types/share'

const SharedMarkdownContent = dynamic(
  () => import('@/components/chat/markdown-content').then((m) => m.MarkdownContent),
  {
    ssr: false,
    loading: () => <div className="h-16 animate-pulse rounded-md bg-muted" aria-hidden />,
  },
)

/** 判断公开页面中应显示的消息。
 *
 * 排除：
 * - 所有 tool role（tool result 消息会合并到 chips 中显示）
 * - 正文为空的 assistant（只包含 tool call 的 placeholder AIMessage。live
 *   chat UI 会合并到 chips 中显示，但公开页面中会作为独立 block 出现，
 *   造成类似 "公司内部位置引导助手" 的 header 重复出现的视觉噪声）
 */
const isVisibleInPublic = (m: Message): boolean => {
  if (m.role === 'tool') return false
  if (m.role === 'assistant') {
    const content = typeof m.content === 'string' ? m.content : ''
    if (!content.trim()) return false
  }
  return true
}

interface PageProps {
  params: Promise<{ shareId: string }>
}

export default function SharedConversationPage({ params }: PageProps) {
  const { shareId } = use(params)
  const { data, isLoading, isError } = usePublicShare(shareId)

  if (isLoading) return <SharedSkeleton />
  if (isError || !data) return <SharedError />
  return <SharedArticle data={data} />
}

function SharedArticle({ data }: { data: SharedConversationView }) {
  const visibleMessages = useMemo(() => data.messages.filter(isVisibleInPublic), [data.messages])

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SharedHeader />

      <main className="flex-1">
        <article className="mx-auto w-full max-w-3xl px-5 sm:px-6">
          <Hero data={data} messageCount={visibleMessages.length} />

          {visibleMessages.length === 0 ? (
            <EmptyConversation />
          ) : (
            <ConversationBody messages={visibleMessages} agent={data.agent} traces={data.traces} />
          )}
        </article>
      </main>

      <SharedFooter
        messageCount={visibleMessages.length}
        createdAt={data.conversation_created_at}
      />
    </div>
  )
}

function SharedHeader() {
  const t = useTranslations('sharedConversation')
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-5 sm:px-6">
        <Link
          href="/"
          className="flex items-center gap-2 text-sm font-semibold text-foreground hover:text-primary-strong"
        >
          <span className="flex size-7 items-center justify-center rounded-lg bg-primary-strong/15 text-primary-strong">
            <span aria-hidden className="text-base">
              M
            </span>
          </span>
          {t('brand')}
        </Link>
        <Link href="/" className="text-xs font-medium text-muted-foreground hover:text-foreground">
          {t('headerCta')}
        </Link>
      </div>
    </header>
  )
}

function Hero({ data, messageCount }: { data: SharedConversationView; messageCount: number }) {
  const t = useTranslations('sharedConversation')
  const readingMinutes = useReadingMinutes(data.messages)
  const dateLabel = useMemo(
    () => formatLongDate(data.conversation_created_at),
    [data.conversation_created_at],
  )

  return (
    <section className="pt-16 pb-2 text-center sm:pt-24">
      <p className="moldy-ui-caption moldy-ui-eyebrow font-semibold text-muted-foreground">
        {t('eyebrow')}
      </p>
      <h1 className="mt-5 text-3xl font-light leading-tight text-foreground sm:text-4xl">
        {data.conversation_title ?? t('titleFallback')}
      </h1>

      <div className="mt-10 flex items-center justify-center gap-3">
        <AgentAvatar imageUrl={data.agent.image_url} name={data.agent.name} size="md" />
        <div className="text-left">
          <p className="text-sm font-semibold text-foreground">{data.agent.name}</p>
          <p className="moldy-ui-caption tracking-wide text-muted-foreground">{dateLabel}</p>
        </div>
      </div>

      <div className="mt-6 flex flex-col items-center gap-2" data-slot="share-hero-metadata">
        <div
          className="flex flex-wrap items-center justify-center gap-3"
          data-slot="share-hero-summary"
        >
          <Badge variant="secondary">
            <MessageSquareIcon />
            {t('footer.messageCount', { count: messageCount })}
          </Badge>
          <Badge variant="secondary">
            {readingMinutes < 1
              ? t('readingTime.underOneMinute')
              : t('readingTime.minutes', { minutes: readingMinutes })}
          </Badge>
        </div>
        {data.agent.description ? (
          <p
            className="max-w-lg text-center text-xs leading-relaxed text-muted-foreground"
            data-slot="share-hero-description"
          >
            {data.agent.description}
          </p>
        ) : null}
      </div>
    </section>
  )
}

function ConversationBody({
  messages,
  agent,
  traces,
}: {
  messages: Message[]
  agent: SharedConversationView['agent']
  traces: TurnTrace[]
}) {
  const t = useTranslations('sharedConversation')
  // 与 live chat UX 保持一致：连续的 assistant 消息合并为一个 group，
  // 将 chips 挂到 group 的第一条消息上（即使 "助手" 在同一个 turn 中多次
  // 发言，header 也只显示一次，tool chip 也只在其上方显示一次）。
  const turnGroups = useMemo(() => groupMessagesIntoTurns(messages, traces), [messages, traces])

  return (
    <section className="py-10 sm:py-14">
      <DividerLabel>{t('history')}</DividerLabel>
      <ol className="mt-10 flex flex-col gap-8">
        {turnGroups.map((group, i) =>
          group.kind === 'user' ? (
            <UserMessageItem key={group.message.id} message={group.message} />
          ) : (
            <AssistantTurnItem
              key={group.messages[0]?.id ?? `turn-${i}`}
              messages={group.messages}
              chips={group.chips}
              agent={agent}
            />
          ),
        )}
      </ol>
    </section>
  )
}

/** 一个 turn = (user message) | (assistant 消息 group + 该 turn 的 chips)。 */
type TurnGroup =
  | { kind: 'user'; message: Message }
  | { kind: 'assistant'; messages: Message[]; chips: ChipInfo[] }

/**
 * 将消息展平为 user / assistant-group，同时与 trace 做 1:1 映射。
 *
 * 匹配优先级：
 *  1. ``trace.linked_message_ids`` 包含 group 第一条 message.id → 直接匹配（W6 准确度，m33+）
 *  2. fallback：chronological turn 顺序（linked_message_ids 为 NULL 的 m32 之前 row）
 *
 * 对于存在 branch 的对话，active 之外的 trace 可能无法映射（graceful）。
 */
function groupMessagesIntoTurns(messages: Message[], traces: TurnTrace[]): TurnGroup[] {
  const groups: TurnGroup[] = []
  // 用于直接匹配的 index — 展开的是 linked_message_ids，而不是 assistant_msg_id。
  const traceByMsgId = new Map<string, TurnTrace>()
  for (const t of traces) {
    if (!t.linked_message_ids) continue
    for (const id of t.linked_message_ids) traceByMsgId.set(id, t)
  }
  // 已用于直接匹配的 trace 从 fallback queue 中排除。
  const usedTraces = new Set<TurnTrace>()
  let turnIdx = 0

  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]
    if (m.role === 'user') {
      groups.push({ kind: 'user', message: m })
      continue
    }
    if (m.role !== 'assistant') continue

    const lastGroup = groups[groups.length - 1]
    if (lastGroup && lastGroup.kind === 'assistant') {
      lastGroup.messages.push(m)
      continue
    }

    // 优先尝试直接匹配
    let trace = traceByMsgId.get(m.id)
    if (trace) {
      usedTraces.add(trace)
    } else {
      // fallback：从未用于直接匹配的 trace 中取 chronological 下一个
      while (turnIdx < traces.length && usedTraces.has(traces[turnIdx])) {
        turnIdx += 1
      }
      trace = traces[turnIdx]
      if (trace) {
        usedTraces.add(trace)
        turnIdx += 1
      }
    }
    const chips = trace ? extractChips(trace) : []
    groups.push({ kind: 'assistant', messages: [m], chips })
  }
  return groups
}

function DividerLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-px flex-1 bg-gradient-to-r from-transparent via-border to-transparent" />
      <span className="select-none moldy-ui-micro moldy-ui-eyebrow font-semibold text-muted-foreground">
        {children}
      </span>
      <span className="h-px flex-1 bg-gradient-to-r from-transparent via-border to-transparent" />
    </div>
  )
}

function UserMessageItem({ message }: { message: Message }) {
  return (
    <li className="flex justify-end">
      <div className="moldy-chat-card max-w-[85%] px-4 py-3 text-sm text-foreground">
        <p className="whitespace-pre-wrap break-words leading-relaxed">{message.content}</p>
      </div>
    </li>
  )
}

function AssistantTurnItem({
  messages,
  chips,
  agent,
}: {
  messages: Message[]
  chips: ChipInfo[]
  agent: SharedConversationView['agent']
}) {
  return (
    <li className="space-y-3">
      <div className="flex items-center gap-2">
        <AgentAvatar imageUrl={agent.image_url} name={agent.name} size="xs" />
        <span className="text-sm font-semibold text-foreground">{agent.name}</span>
      </div>
      <div className="pl-8 space-y-3">
        {chips.length > 0 && (
          <div className="flex flex-col gap-1.5">
            {chips.map((chip, i) => (
              <CollapsiblePill
                key={i}
                kind={chip.kind}
                status={chip.status}
                title={chip.title}
                meta={chip.meta}
              />
            ))}
          </div>
        )}
        {messages.map((m) => (
          <SharedMarkdownContent key={m.id} content={m.content} />
        ))}
      </div>
    </li>
  )
}

function EmptyConversation() {
  const t = useTranslations('sharedConversation')
  return (
    <div className="py-16 text-center">
      <div className="moldy-empty-icon mx-auto mb-4 size-12">
        <MessageSquareIcon className="size-5 text-primary-foreground" />
      </div>
      <p className="text-sm text-muted-foreground">{t('empty')}</p>
    </div>
  )
}

function SharedFooter({ messageCount, createdAt }: { messageCount: number; createdAt: string }) {
  const t = useTranslations('sharedConversation')
  const dateLabel = useMemo(() => formatMediumDate(createdAt), [createdAt])

  return (
    <footer className="mx-auto mt-10 w-full max-w-3xl px-5 pb-12 sm:px-6">
      <div className="moldy-card p-6 sm:flex sm:items-center sm:justify-between sm:gap-6 sm:p-8">
        <div className="text-center sm:text-left">
          <p className="text-base font-semibold text-foreground">{t('footer.title')}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t('footer.description')}</p>
        </div>
        <Link
          href="/"
          data-variant="solid"
          className="moldy-action-pill moldy-status-success mt-4 w-full sm:mt-0 sm:w-auto"
        >
          {t('footer.cta')}
        </Link>
      </div>

      <div className="mt-6 flex flex-col items-center gap-2 moldy-ui-caption text-muted-foreground sm:flex-row sm:justify-between">
        <div className="flex items-center gap-2">
          <span>{dateLabel}</span>
          <span className="size-0.5 rounded-full bg-border" />
          <span>{t('footer.messageCount', { count: messageCount })}</span>
        </div>
        <span>{t('footer.madeWith')}</span>
      </div>
    </footer>
  )
}

function SharedSkeleton() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SharedHeader />
      <main className="mx-auto w-full max-w-3xl px-5 pt-16 sm:px-6 sm:pt-24">
        <div className="space-y-6 text-center">
          <Skeleton className="mx-auto h-3 w-24" />
          <Skeleton className="mx-auto h-10 w-2/3" />
          <div className="mx-auto flex w-fit items-center gap-3">
            <Skeleton className="size-10 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-32" />
            </div>
          </div>
          <div className="mx-auto flex flex-wrap justify-center gap-2">
            <Skeleton className="h-5 w-20 rounded-full" />
            <Skeleton className="h-5 w-24 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        </div>
        <div className="mt-14 space-y-8">
          <Skeleton className="moldy-skeleton-message ml-auto h-16 w-3/4" />
          <Skeleton className="moldy-skeleton-message h-24 w-3/4" />
        </div>
      </main>
    </div>
  )
}

function SharedError() {
  const t = useTranslations('sharedConversation')
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6 text-center">
      <div className="moldy-error-icon mb-4 size-14">
        <AlertCircleIcon className="size-6" />
      </div>
      <h1 className="text-lg font-semibold text-foreground">{t('error.title')}</h1>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{t('error.description')}</p>
      <Link href="/" data-variant="solid" className="moldy-action-pill moldy-status-success mt-6">
        <ArrowLeftIcon className="size-4" />
        {t('error.home')}
      </Link>
    </div>
  )
}

/**
 * Naive 200 wpm estimate. Tool calls / non-string content count as 0 to
 * avoid wild over-estimates from serialized payloads.
 */
function useReadingMinutes(messages: Message[]): number {
  return useMemo(() => {
    const totalWords = messages.reduce((acc, m) => {
      if (typeof m.content !== 'string') return acc
      return acc + m.content.split(/\s+/).filter(Boolean).length
    }, 0)
    return Math.max(1, Math.ceil(totalWords / 200))
  }, [messages])
}
