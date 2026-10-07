'use client'

import { useAui } from '@assistant-ui/react'
import { BookOpenIcon, PlugIcon, TerminalIcon, WrenchIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { AgentAvatar } from '@/components/agent/agent-avatar'
import { requestThreadComposerFocus } from '@/components/chat/composer-focus'
import { useTemplates } from '@/lib/hooks/use-templates'
import type { Agent } from '@/lib/types'

interface ChatEmptyStateProps {
  readonly agent: Agent | undefined
  readonly fallback: string
}

const MAX_CAPABILITY_CHIPS = 6

interface CapabilityChip {
  readonly kind: 'skill' | 'tool' | 'mcp'
  readonly name: string
}

function capabilityChips(agent: Agent | undefined): CapabilityChip[] {
  if (!agent) return []
  return [
    ...(agent.skills ?? []).map((s) => ({ kind: 'skill' as const, name: s.name })),
    ...(agent.tools ?? []).map((t) => ({ kind: 'tool' as const, name: t.name })),
    ...(agent.mcp_tools ?? []).map((m) => ({ kind: 'mcp' as const, name: m.name })),
  ]
}

function CapabilityIcon({ kind }: { kind: CapabilityChip['kind'] }) {
  const className = 'size-3 shrink-0'
  if (kind === 'skill') return <BookOpenIcon aria-hidden className={className} />
  if (kind === 'mcp') return <PlugIcon aria-hidden className={className} />
  return <WrenchIcon aria-hidden className={className} />
}

export function ChatEmptyState({ agent, fallback }: ChatEmptyStateProps) {
  const t = useTranslations('chat')
  const composer = useAui().optional.composer
  const openerQuestions = agent?.opener_questions ?? []

  // starter fallback：仅当 Agent 没有 curated opener 时，才从模板中
  // 通过前端 join 获取 usage_example（backend 无改动，缓存 5 分钟）。
  const needsTemplateStarter = openerQuestions.length === 0 && Boolean(agent?.template_id)
  const { data: templates } = useTemplates(undefined, { enabled: needsTemplateStarter })
  const templateStarter = needsTemplateStarter
    ? (templates?.find((tpl) => tpl.id === agent?.template_id)?.usage_example ?? null)
    : null

  const isWeeklyReport = /周报|weekly.report/i.test(
    [agent?.name, ...(agent?.skills ?? []).map((skill) => skill.name)].join(' '),
  )
  const starters =
    openerQuestions.length > 0
      ? openerQuestions
      : templateStarter
        ? [templateStarter]
        : [t(isWeeklyReport ? 'emptyState.weeklyExample' : 'emptyState.genericExample')]
  const capabilities = capabilityChips(agent)
  const visibleCapabilities = capabilities.slice(0, MAX_CAPABILITY_CHIPS)
  const extraCapabilities = capabilities.length - visibleCapabilities.length

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4">
        <AgentAvatar
          imageUrl={agent?.image_url ?? null}
          name={agent?.name ?? t('defaultAgentName')}
          size="lg"
        />
      </div>
      <h2 className="mb-1 text-lg font-semibold">{agent?.name ?? fallback}</h2>
      {agent?.description && (
        <p className="mb-4 max-w-md text-sm text-muted-foreground">{agent.description}</p>
      )}
      <button
        type="button"
        className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-primary-strong/20 bg-background/80 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-primary hover:text-primary-foreground"
        onClick={() => {
          composer?.setText('/')
          requestThreadComposerFocus()
        }}
      >
        <TerminalIcon className="size-3.5" aria-hidden />
        {t('emptyState.commandDiscovery')}
      </button>
      {capabilities.length > 0 && (
        <div className="mt-5 flex max-w-2xl flex-col items-center gap-2">
          <span className="moldy-ui-caption text-muted-foreground">{t('emptyState.canDo')}</span>
          <div
            className="flex flex-wrap justify-center gap-1.5"
            data-moldy-empty-capabilities="true"
          >
            {visibleCapabilities.map((capability) => (
              <span
                key={`${capability.kind}-${capability.name}`}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-background/80 px-2.5 py-1 text-xs text-muted-foreground"
              >
                <CapabilityIcon kind={capability.kind} />
                <span className="max-w-40 truncate">{capability.name}</span>
              </span>
            ))}
            {extraCapabilities > 0 && (
              <span className="inline-flex items-center rounded-full border border-border bg-background/80 px-2.5 py-1 text-xs text-muted-foreground">
                {t('emptyState.moreCapabilities', { count: extraCapabilities })}
              </span>
            )}
          </div>
        </div>
      )}
      {starters.length > 0 && (
        <div className="mt-6 max-w-2xl space-y-2">
          <p className="text-sm text-muted-foreground">{t('emptyState.exampleLabel')}</p>
          <div
            className="mt-6 flex max-w-2xl flex-wrap justify-center gap-2"
            data-moldy-empty-starters="true"
          >
            {starters.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => {
                  composer?.setText(question)
                  requestThreadComposerFocus()
                }}
                className="rounded-full border border-primary-strong/20 bg-background/80 px-3 py-1.5 text-xs transition-colors hover:bg-primary hover:text-primary-foreground"
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
