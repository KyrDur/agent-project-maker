'use client'

import { useTranslations } from 'next-intl'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import { guidanceScope, newestRuns } from '../_lib/project-guidance'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'
import { ProjectProposals } from './project-proposals'

export function GuidedOptimization({
  agentId,
  versionId,
  versions,
}: {
  agentId: string
  versionId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject.guided')
  const { sets, runs } = useProjectEvaluation(agentId)
  const ordered = newestRuns(runs.data ?? [])
  const { run, source } = guidanceScope(versionId, sets.data ?? [], ordered)
  // A completed candidate with failures can start its own NEXT iteration. While
  // its regression is pending retain the accepted source proposal for recovery.
  const current =
    run?.status === 'completed' && run.results_json?.some((r) => r.status === 'failed')
      ? run
      : (source ?? run)
  if (runs.isError) return <ErrorState onRetry={() => void runs.refetch()} />
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">{t('improveTitle')}</h3>
      <p>{t('improveDescription')}</p>
      {current?.results_json?.some((r) => r.status === 'failed') &&
      current.metrics_json?.quality_complete !== false ? (
        <ProjectProposals
          key={current.id}
          agentId={agentId}
          run={current}
          versions={versions}
          runs={ordered}
          guided
        />
      ) : (
        <p>{t('noFixableFailure')}</p>
      )}
    </div>
  )
}
