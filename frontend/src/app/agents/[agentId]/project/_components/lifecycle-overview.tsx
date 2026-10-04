'use client'

import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import { guidanceScope } from '../_lib/project-guidance'
import type { AgentProject, AgentProjectVersionSummary } from '../_lib/agent-project-types'
import type { ProjectWorkspaceTab } from './project-navigation'
import { ProjectBrief } from './project-brief'

export function LifecycleOverview({
  agentId,
  project,
  versions,
  onNavigate,
  versionId,
}: {
  agentId: string
  project: AgentProject
  versions: AgentProjectVersionSummary[]
  onNavigate: (tab: ProjectWorkspaceTab) => void
  versionId?: string
}) {
  const t = useTranslations('agentProject.guided')
  const selected = versionId ?? versions[0]?.id ?? ''
  const { sets, runs } = useProjectEvaluation(agentId)
  const { run, source } = guidanceScope(selected, sets.data ?? [], runs.data ?? [])
  const confirmed = !!project.requirements_json?.learning_brief
  const action = !confirmed
    ? 'brief'
    : !run
      ? source
        ? 'regression'
        : 'test'
      : run.status === 'pending' || run.status === 'running'
        ? 'wait'
        : run.status === 'failed'
          ? 'retry'
          : run.comparison_json?.proposals?.some((p) => p.status === 'pending')
            ? 'review'
            : run.results_json?.some((r) => r.status === 'failed')
              ? 'improve'
              : 'materials'
  const next: ProjectWorkspaceTab =
    action === 'review' || action === 'improve' || action === 'regression'
      ? 'optimization'
      : action === 'materials'
        ? 'results'
        : 'evaluation'
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">{project.title}</h3>
        <p>{t('overviewDescription')}</p>
      </div>
      <ol className="grid gap-3 sm:grid-cols-2">
        {(['create', 'test', 'improve', 'materials'] as const).map((step, i) => (
          <li key={step} className="border-l-2 border-border pl-3">
            <p className="font-medium">{t(`steps.${step}.title`)}</p>
            <p className="text-sm text-muted-foreground">{t(`steps.${step}.description`)}</p>
            <p className="text-sm">
              {t(
                i === 0
                  ? 'created'
                  : i === 1 && run?.status === 'completed'
                    ? 'tested'
                    : i === 2 && source
                      ? 'iterated'
                      : 'todo',
              )}
            </p>
          </li>
        ))}
      </ol>
      <div className="space-y-3 border-t border-border pt-4">
        <h4 className="font-medium">{t('nextStep')}</h4>
        <p>{t(`next.${action}`)}</p>
        {confirmed && (
          <Button disabled={action === 'wait'} onClick={() => onNavigate(next)}>
            {t(`nextActions.${action}`)}
          </Button>
        )}
      </div>
      <ProjectBrief key={selected} agentId={agentId} versionId={selected} project={project} />
    </div>
  )
}
