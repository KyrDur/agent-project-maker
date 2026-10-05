'use client'

import type { CSSProperties } from 'react'
import { useAuiState, type ToolCallMessagePartProps } from '@assistant-ui/react'
import { CheckIcon, SparklesIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { BuilderHeaderIcon, BuilderMuted, BuilderTitle } from './builder-primitives'

type PhaseStatus = 'pending' | 'in_progress' | 'completed'

interface PhaseTodo {
  id: number
  name: string
  status: PhaseStatus
}

interface TimelineArgs {
  todos: PhaseTodo[]
}

const PHASE_TIMELINE_TOOL_NAME = 'phase_timeline'

/** 在 assistant-ui thread state 中找到全部 phase_timeline tool_call，并返回最后一个 id。
 *
 * 后端每次 phase 转换时都会以新的 tool_call_id 对 phase_timeline 重新 emit。
 * 之前机器人消息中的 phase_timeline 已不再是最后一个，因此应被 hide。 */
function selectLatestPhaseTimelineId(
  messages: readonly {
    role?: string
    content?: readonly { type?: string; toolName?: string; toolCallId?: string }[]
  }[],
): string | undefined {
  let latest: string | undefined
  for (const m of messages) {
    if (m.role !== 'assistant') continue
    for (const part of m.content ?? []) {
      if (
        part.type === 'tool-call' &&
        part.toolName === PHASE_TIMELINE_TOOL_NAME &&
        part.toolCallId
      ) {
        latest = part.toolCallId
      }
    }
  }
  return latest
}

/** 当所有 phase 只有 completed/pending 状态时，将第一个 pending 推导为 in_progress。
 *
 * 后端若只调用 `mark_completed_through(N)`，则以 1..N=completed / N+1..=pending 形式
 * emit，导致没有任何阶段为 in_progress。视觉组件已支持 in_progress，因此在前端完成 derivation。
 * 后端将来即使 explicit emit 也兼容（若已有 in_progress 则
 * 不应用）。 */
function deriveInProgress(todos: PhaseTodo[]): PhaseTodo[] {
  if (todos.some((t) => t.status === 'in_progress')) return todos
  const idx = todos.findIndex((t) => t.status === 'pending')
  if (idx < 0) return todos
  const next = [...todos]
  next[idx] = { ...next[idx], status: 'in_progress' }
  return next
}

function PhaseDot({ status }: { status: PhaseStatus }) {
  if (status === 'completed') {
    return (
      <span className="moldy-phase-dot" data-status={status}>
        <CheckIcon className="size-3" strokeWidth={3} />
      </span>
    )
  }
  if (status === 'in_progress') {
    return (
      <span className="moldy-phase-dot" data-status={status}>
        <span className="moldy-phase-dot-core" data-status={status} />
      </span>
    )
  }
  return (
    <span className="moldy-phase-dot" data-status={status}>
      <span className="moldy-phase-dot-core" data-status={status} />
    </span>
  )
}

function StatusBadge({ status }: { status: PhaseStatus }) {
  const t = useTranslations('chat.phaseTimeline')

  return (
    <span className="moldy-phase-status" data-status={status}>
      {status === 'in_progress' && <span className="moldy-phase-status-pulse" />}
      {t(`status.${status}`)}
    </span>
  )
}

function ProgressRail({ todos }: { todos: PhaseTodo[] }) {
  const t = useTranslations('chat.phaseTimeline')
  const items = deriveInProgress(todos ?? [])
  const total = items.length || 1
  const done = items.filter((t) => t.status === 'completed').length
  const ratio = Math.min(100, (done / total) * 100)
  const phaseStyle = { '--phase-ratio': `${ratio}%` } as CSSProperties

  return (
    <div className="moldy-phase-rail" style={phaseStyle}>
      <div className="mb-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BuilderHeaderIcon>
            <SparklesIcon className="size-3" />
          </BuilderHeaderIcon>
          <BuilderTitle>{t('title')}</BuilderTitle>
          <BuilderMuted className="tabular-nums">
            {t('progress', { done, total: items.length })}
          </BuilderMuted>
        </div>
        <div className="moldy-phase-progress-track">
          <div className="moldy-phase-progress-fill" />
        </div>
      </div>

      <ol className="relative m-0 list-none p-0">
        <span aria-hidden className="moldy-phase-connector" />
        {items.map((todo) => (
          <li key={todo.id} className="moldy-phase-row">
            <PhaseDot status={todo.status} />
            <span className="moldy-phase-label" data-status={todo.status}>
              <span className="mr-2 moldy-ui-caption font-medium tabular-nums moldy-builder-color-muted">
                {String(todo.id).padStart(2, '0')}
              </span>
              {todo.name}
            </span>
            <StatusBadge status={todo.status} />
          </li>
        ))}
      </ol>
    </div>
  )
}

type ThreadMessageLite = {
  role?: string
  content?: readonly { type?: string; toolName?: string; toolCallId?: string }[]
}

export function PhaseTimelineRender({
  toolCallId,
  args,
}: {
  toolCallId: string
  args: TimelineArgs
}) {
  // 如果不是 thread 中最后一个 phase_timeline tool_call，则 hide。
  // 不再渲染之前机器人消息中的同一 tool，让进度卡片只显示在最新消息中。
  // assistant-ui 0.12+ 的 `useAuiState((s) => s.thread.messages)` 模式 — ThreadContext.d.ts 的
  // 迁移指南中正式公开的 selector。
  const latestId = useAuiState((s) => {
    const thread = (s as { thread?: { messages?: readonly ThreadMessageLite[] } }).thread
    return selectLatestPhaseTimelineId(thread?.messages ?? [])
  })
  if (latestId && latestId !== toolCallId) return null
  return (
    <div className="my-3">
      <ProgressRail todos={args.todos ?? []} />
    </div>
  )
}

export function PhaseTimelineToolUI({
  toolCallId,
  args,
}: ToolCallMessagePartProps<TimelineArgs, unknown>) {
  return <PhaseTimelineRender toolCallId={toolCallId} args={args} />
}
