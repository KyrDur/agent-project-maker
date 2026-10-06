'use client'

import { ListChecksIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { completedTodoCount, TodosBody } from '@/components/chat/deepagents-todos'
import { CollapsiblePill } from '@/components/chat/tool-ui/collapsible-pill'
import type { DeepAgentTodo } from '@/lib/chat/langgraph-runtime/deepagents-state'

/**
 * MissionControlBar —— Agent 计划(write_todos)的常驻 checklist。
 *
 * 与流式加载指示器（run 结束时 unmount）不同，它固定在线程最上方，
 * 在流式中、结束后、reload 后都在同一位置显示进度。
 * 数据来自 `stream.values.todos`（deepagents 计划 channel）—— reload 时通过 thread state
 * hydrate 恢复。inline write_todos Plan 卡作为"当时的快照"
 * 保留在 history 中，而此栏是"当前计划"的 canonical 界面。
 */
export function MissionControlBar({ todos }: { readonly todos: readonly DeepAgentTodo[] }) {
  const t = useTranslations('chat.deepAgentsState')
  if (todos.length === 0) return null
  const done = completedTodoCount(todos)
  const allDone = done === todos.length
  const activeTodo = todos.find((todo) => todo.status === 'in_progress')
  const progress = t('tasks.progress', { done, total: todos.length })
  const summary = activeTodo
    ? `${progress} · ${t('tasks.current', { item: activeTodo.content })}`
    : progress
  return (
    <div
      className="border-b border-border/60 bg-background/95 px-4 py-1.5"
      data-moldy-mission-control="true"
    >
      <div className="mx-auto w-full max-w-3xl">
        <CollapsiblePill
          status={allDone ? 'success' : 'loading'}
          kind="thinking"
          title={t('tasks.title')}
          meta={summary}
          leadingIcon={ListChecksIcon}
          defaultExpanded={false}
          titleClassName="shrink-0"
        >
          <TodosBody todos={todos} />
        </CollapsiblePill>
      </div>
    </div>
  )
}
