'use client'

import { useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { formatDisplayDateTime, formatDisplayNumber } from '@/lib/utils/display-format'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'
import { useProjectVersions, useEvaluationReports } from '../_hooks/use-project-evaluation'

export function ProjectVersions({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject')
  const workspaceT = useTranslations('agentProject.workspace')
  const locale = useLocale()
  const reports = useEvaluationReports(agentId).data
  const scope = reports?.reports.find((r) => r.score !== null)?.comparison_key
  const bestRunId = scope ? reports?.best_run_ids[scope] : undefined
  const bestVersionId = reports?.reports.find((r) => r.evaluation_run_id === bestRunId)?.version_id
  const [selected, setSelected] = useState('')
  const request = useRef<string | null>(null)
  const { create, detail } = useProjectVersions(agentId, selected)
  const reportForVersion = (versionId: string) =>
    reports?.reports
      .filter((report) => report.version_id === versionId && report.score != null)
      .toSorted((a, b) => b.created_at.localeCompare(a.created_at))[0]
  const regressionForVersion = (versionId: string) =>
    reports?.reports.find((report) => report.version_id === versionId && report.source_run_id)
  const percent = (value: number | null | undefined) =>
    value == null
      ? t('notRun')
      : `${formatDisplayNumber(value * 100, { locale, maximumFractionDigits: 1 })}%`
  const submit = () => {
    request.current ??= crypto.randomUUID()
    create.mutate(request.current, {
      onSuccess: () => {
        request.current = null
      },
    })
  }
  return (
    <SettingsSectionCard
      title={t('history')}
      actions={
        <Button onClick={submit} disabled={create.isPending}>
          {create.isPending ? t('creating') : t('createVersion')}
        </Button>
      }
    >
      {bestVersionId && <p className="mb-4">{t('bestNotLive')}</p>}
      {create.isError && <ErrorState onRetry={submit} />}
      {create.data && <p role="status">{t(`outcomes.${create.data.outcome}`)}</p>}
      <ol className="space-y-4" aria-label={workspaceT('versions.evolutionAria')}>
        {versions.map((version) => {
          const evaluation = reportForVersion(version.id)
          const regression = regressionForVersion(version.id)
          const parent = versions.find((item) => item.id === version.parent_version_id)
          return (
            <li key={version.id} className="rounded-lg border border-border/70 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="outline" onClick={() => setSelected(version.id)}>
                      {t('version', { number: version.version_number })}
                    </Button>
                    {bestVersionId === version.id && (
                      <span className="moldy-ui-micro rounded-full bg-foreground px-2 py-1 text-background">
                        {workspaceT('versions.bestBadge')}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {version.status === 'original'
                      ? t('originalSnapshot')
                      : t(`statuses.${version.status}`)}
                    {' · '}
                    {formatDisplayDateTime(version.created_at, { locale })}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">
                    {workspaceT('versions.evaluationScore')}
                  </p>
                  <p className="text-2xl font-semibold">{percent(evaluation?.score)}</p>
                </div>
              </div>
              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">{workspaceT('versions.createdFrom')}</dt>
                  <dd>
                    {version.created_from
                      ? workspaceT('versions.optimizationProposal', {
                          id: version.created_from.optimization_proposal_id.slice(0, 8),
                        })
                      : version.status === 'original'
                        ? workspaceT('versions.initialVersion')
                        : workspaceT('versions.manualVersion')}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{workspaceT('versions.parent')}</dt>
                  <dd>
                    {parent
                      ? t('version', { number: parent.version_number })
                      : workspaceT('versions.none')}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{workspaceT('versions.regression')}</dt>
                  <dd>{regression ? t(`runStatuses.${regression.status}`) : t('notRun')}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{workspaceT('versions.changes')}</dt>
                  <dd>{version.change_summary || t('configurationChanged')}</dd>
                </div>
              </dl>
              <p className="mt-3 break-all text-xs text-muted-foreground">
                {t('configHash')}: {version.config_hash}
              </p>
            </li>
          )
        })}
      </ol>
      {selected &&
        (detail.isError ? (
          <ErrorState onRetry={() => void detail.refetch()} />
        ) : detail.isPending ? (
          <p role="status">{t('loading')}</p>
        ) : (
          <details className="mt-4">
            <summary>{t('snapshotDetail')}</summary>
            <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
              {JSON.stringify(detail.data.snapshot_json, null, 2)}
            </pre>
          </details>
        ))}
    </SettingsSectionCard>
  )
}
