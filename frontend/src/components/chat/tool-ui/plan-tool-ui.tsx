'use client'

import type { ToolCallMessagePartProps } from '@assistant-ui/react'
import { useTranslations } from 'next-intl'
import { CheckCircle2Icon, CircleDotIcon, CircleIcon } from 'lucide-react'
import { CollapsiblePill, pillStatusFromAssistantUi } from './collapsible-pill'
import { cn } from '@/lib/utils'

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

interface TodoItem {
  content: string
  status?: 'completed' | 'in_progress' | 'pending'
}

interface WriteTodosArgs {
  todos?: TodoItem[]
  items?: TodoItem[] // fallback
}

// ──────────────────────────────────────────────
// Status 设置
// ──────────────────────────────────────────────

const STATUS_MAP = {
  completed: {
    Icon: CheckCircle2Icon,
    color: 'text-status-success',
    bg: 'bg-status-success/10',
    labelKey: 'completed',
  },
  in_progress: {
    Icon: CircleDotIcon,
    color: 'text-primary-strong',
    bg: 'bg-primary/10',
    labelKey: 'inProgress',
  },
  pending: {
    Icon: CircleIcon,
    color: 'text-muted-foreground',
    bg: 'bg-muted',
    labelKey: 'pending',
  },
} as const

// ──────────────────────────────────────────────
// PlanToolUI — write_todos 工具
// ──────────────────────────────────────────────

export function PlanToolUI({ args, status }: ToolCallMessagePartProps<WriteTodosArgs, string>) {
  return <PlanToolView args={args} statusType={status.type} />
}

// 流式传输期间 tool-call args 会以部分 JSON 到达 — 在 `todos` 成为数组
// 之前（字符串/对象片段）也会触发渲染，因此需要 Array.isArray + item shape 防护；
// 否则真实 LLM 路径会发生渲染崩溃（在 M8-4 中发现，scripted 模型
// 只会输出完整 args，无法复现）。
function normalizeTodoItems(args: WriteTodosArgs | undefined): TodoItem[] {
  const raw = args?.todos ?? args?.items
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (item): item is TodoItem =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as { content?: unknown }).content === 'string',
  )
}

function PlanToolView({ args, statusType }: { args: WriteTodosArgs; statusType: string }) {
  const t = useTranslations('chat.toolCall.plan')
  const items = normalizeTodoItems(args)
  const isRunning = statusType === 'running'
  const completed = items.filter((it) => it.status === 'completed').length
  const meta = isRunning
    ? t('loading')
    : items.length > 0
      ? `${completed}/${items.length}`
      : undefined

  const body =
    items.length > 0 ? (
      <div>
        {items.map((item, i) => {
          // 部分流式 args 的 status 可能是 'in_prog' 之类的片段。
          const s = STATUS_MAP[item.status ?? 'pending'] ?? STATUS_MAP.pending
          const isLast = i === items.length - 1
          return (
            <div key={i} className="flex items-start gap-2">
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    'flex size-5 shrink-0 items-center justify-center rounded-full',
                    s.bg,
                  )}
                >
                  <s.Icon className={cn('size-3', s.color)} />
                </div>
                {!isLast && <div className="h-4 w-px bg-border" />}
              </div>
              <div className="flex flex-1 items-start justify-between gap-2 pb-2">
                <span
                  className={cn(
                    'leading-5',
                    item.status === 'completed' && 'text-muted-foreground line-through',
                  )}
                >
                  {item.content}
                </span>
                <span
                  className={cn(
                    'shrink-0 rounded-full px-1.5 py-0.5 moldy-ui-micro',
                    s.bg,
                    s.color,
                  )}
                >
                  {t(s.labelKey)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    ) : undefined

  return (
    <CollapsiblePill
      kind="tool"
      status={pillStatusFromAssistantUi(statusType)}
      title={t('title')}
      meta={meta}
      defaultExpanded={false}
    >
      {body}
    </CollapsiblePill>
  )
}
