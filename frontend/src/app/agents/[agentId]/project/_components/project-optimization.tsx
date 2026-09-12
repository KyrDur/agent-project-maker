'use client'

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectOptimization, useProjectVersions } from '../_hooks/use-project-evaluation'
import type { AgentProjectVersionSummary, EvaluationRun } from '../_lib/agent-project-types'

export function ProjectOptimization({
  agentId,
  run,
  versions,
}: {
  agentId: string
  run: EvaluationRun
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject')
  const { analyze, optimize } = useProjectOptimization(agentId, run.id)
  const request = useRef<string | null>(null)
  const [selected, setSelected] = useState('')
  const { detail } = useProjectVersions(agentId, selected)
  const analysis = run.comparison_json?.analysis
  const state = run.comparison_json?.optimization
  const badCases = run.bad_cases_json ?? []
  const failedCount = run.results_json?.filter((r) => r.status !== 'passed').length ?? 0
  const counts = badCases.reduce<Record<string, number>>((result, item) => {
    result[item.category] = (result[item.category] ?? 0) + 1
    return result
  }, {})
  const versionName = (id: string) =>
    t('version', { number: versions.find((v) => v.id === id)?.version_number ?? 0 })
  const busy =
    analyze.isPending || optimize.isPending || ['pending', 'running'].includes(state?.state ?? '')
  const meta = detail.data?.snapshot_json.optimization
  const patches =
    meta && typeof meta === 'object' && 'patches' in meta && Array.isArray(meta.patches)
      ? meta.patches
      : []
  return (
    <div className="space-y-3 border-t border-border pt-4">
      <h4 className="font-medium">{t('badCases')}</h4>
      <p>{t('failedCases', { count: failedCount })}</p>
      {!analysis && (
        <Button variant="outline" disabled={busy || !failedCount} onClick={() => analyze.mutate()}>
          {t('analyzeBadCases')}
        </Button>
      )}
      <ul>
        {Object.entries(counts).map(([category, count]) => (
          <li key={category}>
            {t(`causeCategories.${category}`)}: {count}
          </li>
        ))}
      </ul>
      {badCases.map((item) => (
        <details key={item.case_id}>
          <summary>
            {run.results_json?.find((r) => r.case_id === item.case_id)?.name} ·{' '}
            {t(`causeCategories.${item.category}`)}
          </summary>
          <p>{item.root_cause}</p>
          <p>{item.suggested_fix}</p>
          <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
            {JSON.stringify(item.observations, null, 2)}
          </pre>
        </details>
      ))}
      {analysis && (
        <>
          <h4 className="font-medium">{t('optimizationPlan')}</h4>
          <ol className="list-decimal space-y-2 pl-5">
            {analysis.groups.map((group, i) => (
              <li key={i}>
                {group.proposed_change} · {t('affectedCases', { count: group.case_ids.length })}
              </li>
            ))}
          </ol>
          {!analysis.groups.length && <p>{t('optimizationStops.no_fixable_cases')}</p>}
        </>
      )}
      {!!run.comparison_json?.deferred_changes?.length && <p>{t('deferredSkillChange')}</p>}
      <p className="text-sm text-muted-foreground">{t('optimizationPolicy')}</p>
      <p className="text-sm text-muted-foreground">{t('bestNotLive')}</p>
      <Button
        disabled={busy || !failedCount || !!state?.state || (!!analysis && !analysis.groups.length)}
        onClick={() => {
          request.current ??= crypto.randomUUID()
          optimize.mutate(request.current)
        }}
      >
        {t('optimizeAgent')}
      </Button>
      {busy && <p role="status">{t('optimizing')}</p>}
      {(analyze.isError || optimize.isError) && <ErrorState title={t('optimizationFailed')} />}
      {state?.stop_reason && (
        <p role="status">
          {t.has(`optimizationStops.${state.stop_reason}`)
            ? t(`optimizationStops.${state.stop_reason}`)
            : t('optimizationFailed')}
        </p>
      )}
      {state?.best_version_id && (
        <p className="font-medium">
          {t('bestVersion')}: {versionName(state.best_version_id)}
        </p>
      )}
      {state?.rounds?.map((round) => (
        <div key={round.version_id} className="space-y-2">
          <p>
            {versionName(round.parent_version_id)} → {versionName(round.version_id)} ·{' '}
            {t(`statuses.${round.decision}`)}
          </p>
          <Button variant="outline" onClick={() => setSelected(round.version_id)}>
            {t('viewChanges')}
          </Button>
          {round.comparison && (
            <details>
              <summary>{t('compareVersions')}</summary>
              <p>
                {t('regressionRates', {
                  before: Math.round(round.comparison.pass_rate.before * 100),
                  after: Math.round(round.comparison.pass_rate.after * 100),
                })}
              </p>
              <ul>
                {(
                  [
                    'fixed_cases',
                    'regressed_cases',
                    'still_failing_cases',
                    'still_passing_cases',
                  ] as const
                ).map((key) => (
                  <li key={key}>
                    {t(`regressionCounts.${key}`, { count: round.comparison?.[key].length ?? 0 })}
                  </li>
                ))}
              </ul>
              <ul>
                {Object.entries(round.comparison.metrics).map(([name, scores]) => (
                  <li key={name}>
                    {t.has(`metricNames.${name}`) ? t(`metricNames.${name}`) : name}:{' '}
                    {scores.before == null || scores.after == null
                      ? t('notRun')
                      : t('regressionRates', {
                          before: Math.round(scores.before * 100),
                          after: Math.round(scores.after * 100),
                        })}
                  </li>
                ))}
              </ul>
              <ul>
                {round.comparison.reasons.map((reason) => (
                  <li key={reason}>{t(`decisionReasons.${reason}`)}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      ))}
      {selected &&
        (detail.isError ? (
          <ErrorState />
        ) : detail.isPending ? (
          <p>{t('loading')}</p>
        ) : (
          <div>
            <h4 className="font-medium">
              {t('viewChanges')} · {versionName(selected)}
            </h4>
            {meta != null &&
              typeof meta === 'object' &&
              'deferred_changes' in meta &&
              Array.isArray(meta.deferred_changes) &&
              meta.deferred_changes.length > 0 && <p>{t('deferredSkillChange')}</p>}
            {patches.map((patch: unknown, i: number) => {
              if (
                !patch ||
                typeof patch !== 'object' ||
                !('before' in patch) ||
                !('after' in patch)
              )
                return null
              return (
                <div key={i} className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p>{t('beforeChange')}</p>
                    <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
                      {String(patch.before)}
                    </pre>
                  </div>
                  <div>
                    <p>{t('afterChange')}</p>
                    <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
                      {String(patch.after)}
                    </pre>
                  </div>
                </div>
              )
            })}
          </div>
        ))}
    </div>
  )
}
