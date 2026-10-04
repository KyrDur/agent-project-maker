'use client'

import { useTranslations } from 'next-intl'
import { useProjectEvaluation, useEvaluationReports } from '../_hooks/use-project-evaluation'
import { ErrorState } from '@/components/shared/error-state'
import { newestRuns } from '../_lib/project-guidance'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'

export function ProjectIterationJournal({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject.guided')
  const { runs } = useProjectEvaluation(agentId)
  const reports = useEvaluationReports(agentId)
  const ordered = newestRuns(runs.data ?? [])
  const entries = ordered.flatMap((run) =>
    (run.comparison_json?.proposals ?? [])
      .filter((p) => p.status === 'accepted')
      .map((p) => ({ proposal: p, source: run })),
  )
  const version = (id: string | null) => versions.find((v) => v.id === id)?.version_number ?? 0
  if (runs.isError || reports.isError) return <ErrorState />
  return (
    <div className="space-y-3">
      <h3 className="text-lg font-semibold">{t('journalTitle')}</h3>
      {!entries.length && <p>{t('noIterations')}</p>}
      {entries.map(({ proposal, source }) => {
        const regression = ordered.find(
          (r) => r.comparison_json?.regression?.proposal_id === proposal.id,
        )
        const before = reports.data?.reports.find((r) => r.evaluation_run_id === source.id)
        const after = reports.data?.reports.find((r) => r.evaluation_run_id === regression?.id)
        const comparable =
          before?.comparison_key &&
          before.comparison_key === after?.comparison_key &&
          before.score !== null &&
          after.score !== null
        return (
          <article key={proposal.id} className="space-y-2 rounded-lg border border-border p-4">
            <h4 className="font-medium">
              {t('versionChange', {
                before: version(proposal.source_version_id),
                after: version(proposal.version_id),
              })}
            </h4>
            <p>{proposal.what_changes || proposal.title}</p>
            <p>
              {t('hypothesis')} · {proposal.why_it_may_work}
            </p>
            <p>
              {t(
                proposal.decision_reason_source === 'ai_confirmed'
                  ? 'aiReasonConfirmed'
                  : 'userReason',
              )}{' '}
              · {proposal.decision_reason || t('noReason')}
            </p>
            {comparable && before && after ? (
              <p>
                {t('scoreChange', {
                  before: Math.round((before.score ?? 0) * 100),
                  after: Math.round((after.score ?? 0) * 100),
                })}
              </p>
            ) : (
              <p>{t('incompleteComparison')}</p>
            )}
            <details>
              <summary className="cursor-pointer">{t('changes')}</summary>
              {proposal.diffs.map((d, i) => (
                <div key={i} className="mt-2 grid gap-3 sm:grid-cols-2">
                  <pre className="whitespace-pre-wrap break-words text-xs">{d.before}</pre>
                  <pre className="whitespace-pre-wrap break-words text-xs">{d.after}</pre>
                </div>
              ))}
            </details>
            <p className="text-sm text-muted-foreground">{t('scoreBoundary')}</p>
          </article>
        )
      })}
    </div>
  )
}
