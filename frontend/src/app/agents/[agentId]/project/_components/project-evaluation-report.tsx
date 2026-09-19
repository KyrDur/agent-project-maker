'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { formatDisplayDateTime, formatDisplayNumber } from '@/lib/utils/display-format'
import { useEvaluationReports } from '../_hooks/use-project-evaluation'
import type { AgentProjectVersionSummary, EvaluationReport } from '../_lib/agent-project-types'
import { ProjectSelect } from './project-select'

export function ProjectEvaluationReport({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject.evaluationReport')
  const projectT = useTranslations('agentProject')
  const locale = useLocale()
  const query = useEvaluationReports(agentId)
  const [selectedId, setSelectedId] = useState('')
  const [baselineId, setBaselineId] = useState('')
  const reports = query.data?.reports ?? []
  const selected = reports.find((r) => r.evaluation_run_id === selectedId) ?? reports[0]
  const candidates = reports.filter((r) => r.version_id !== selected?.version_id)
  const baseline =
    candidates.find((r) => r.evaluation_run_id === baselineId) ??
    candidates.find((r) => r.evaluation_run_id === selected?.source_run_id) ??
    candidates.find((r) => r.comparison_key === selected?.comparison_key) ??
    candidates[0]
  const bestId = selected?.comparison_key && query.data?.best_run_ids[selected.comparison_key]
  const best = reports.find((r) => r.evaluation_run_id === bestId)
  const comparable =
    !!selected?.comparison_key &&
    selected.comparison_key === baseline?.comparison_key &&
    selected.score !== null &&
    baseline?.score != null
  const number = (value: number) => formatDisplayNumber(value, { locale, maximumFractionDigits: 1 })
  const percent = (value: number | null | undefined) =>
    value == null ? t('unavailable') : t('percent', { value: number(value * 100) })
  const delta = (a: number, b: number) =>
    t('delta', { value: `${b >= a ? '+' : ''}${number((b - a) * 100)}` })
  const version = (r: EvaluationReport) =>
    projectT('version', {
      number: versions.find((v) => v.id === r.version_id)?.version_number ?? 0,
    })
  const options = (items: EvaluationReport[]) =>
    items.map((r) => ({
      value: r.evaluation_run_id,
      label: `${version(r)} · ${formatDisplayDateTime(r.created_at, { locale })} · ${percent(r.score)} · ${r.evaluation_run_id.slice(0, 8)}`,
    }))
  const metricName = (name: string) =>
    projectT.has(`metricNames.${name}`) ? projectT(`metricNames.${name}`) : name

  return (
    <div id="evaluation-report">
      <SettingsSectionCard title={t('title')}>
        {query.isPending ? (
          <p role="status">{projectT('loading')}</p>
        ) : query.isError ? (
          <ErrorState onRetry={() => void query.refetch()} />
        ) : !selected ? (
          <p>{t(query.data?.active ? 'running' : 'empty')}</p>
        ) : (
          <div className="space-y-5">
            {query.data?.active && <p role="status">{t('running')}</p>}
            <ProjectSelect
              label={t('selectReport')}
              value={selected.evaluation_run_id}
              options={options(reports)}
              onChange={setSelectedId}
            />
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <h3 className="font-medium">{t('score')}</h3>
                <p className="text-3xl font-semibold">{percent(selected.score)}</p>
              </div>
              <div>
                <h3 className="font-medium">{t('summary')}</h3>
                <p>{t('summaryValue', { passed: selected.passed, total: selected.total })}</p>
                <p>{projectT(`runStatuses.${selected.status}`)}</p>
              </div>
              <div>
                <h3 className="font-medium">{t('best')}</h3>
                <p>{best ? `${version(best)} · ${percent(best.score)}` : t('unavailable')}</p>
                {best && (
                  <>
                    <p>{projectT('lifecycle.bestReason')}</p>
                    <p className="text-sm text-muted-foreground">
                      {formatDisplayDateTime(best.created_at, { locale })}
                    </p>
                  </>
                )}
              </div>
            </div>
            <p className="text-sm text-muted-foreground">{t('scoreRule')}</p>
            <p className="text-sm text-muted-foreground">{t('bestRule')}</p>
            <p className="break-all text-sm">{t('dataset', { id: selected.eval_set_id })}</p>
            <section className="space-y-2">
              <h3 className="font-medium">{t('metrics')}</h3>
              {!Object.keys(selected.metrics).length && <p>{t('noMetrics')}</p>}
              <dl className="grid gap-3 sm:grid-cols-2">
                {Object.entries(selected.metrics).map(([name, score]) => (
                  <div key={name}>
                    <dt>{metricName(name)}</dt>
                    <dd>{percent(score)}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section className="space-y-2">
              <h3 className="font-medium">{t('badCases', { count: selected.bad_case_count })}</h3>
              {!selected.bad_cases.length && <p>{t('noFailures')}</p>}
              {selected.bad_cases.map((item) => (
                <details key={item.case_id}>
                  <summary>{item.name}</summary>
                  <ul className="list-disc pl-5">
                    {(item.reasons.length ? item.reasons : [t('noReason')]).map((reason, i) => (
                      <li key={i}>{reason}</li>
                    ))}
                  </ul>
                </details>
              ))}
            </section>
            <section className="space-y-2">
              <h3 className="font-medium">{t('suggestions')}</h3>
              {selected.proposals?.map((proposal) => (
                <p key={proposal.id}>
                  {projectT(`lifecycle.statuses.${proposal.status}`)} ·{' '}
                  {proposal.affected_capabilities.join(', ')}
                </p>
              ))}
              {selected.optimization_suggestions.length ? (
                <ul className="list-disc pl-5">
                  {selected.optimization_suggestions.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>{t('noSuggestions')}</p>
              )}
              <a
                className="underline"
                href={`#evaluation-run-${selected.evaluation_run_id}`}
                onClick={() => {
                  const detail = document.getElementById(
                    `evaluation-run-${selected.evaluation_run_id}`,
                  )
                  if (detail instanceof HTMLDetailsElement) detail.open = true
                }}
              >
                {t('openRun')}
              </a>
            </section>
            <section className="space-y-3">
              <h3 className="font-medium">{t('compare')}</h3>
              {!baseline ? (
                <p>{t('needBaseline')}</p>
              ) : (
                <>
                  <ProjectSelect
                    label={t('baseline')}
                    value={baseline.evaluation_run_id}
                    options={options(candidates)}
                    onChange={setBaselineId}
                  />
                  <p>
                    {t('comparison', {
                      before: `${version(baseline)}: ${percent(baseline.score)}`,
                      after: `${version(selected)}: ${percent(selected.score)}`,
                    })}
                  </p>
                  {comparable && baseline.score != null && selected.score != null ? (
                    <>
                      <p className="text-lg font-semibold">
                        {delta(baseline.score, selected.score)}
                      </p>
                      <dl className="space-y-2">
                        {Object.entries(selected.metrics)
                          .filter(([name]) => baseline.metrics[name] != null)
                          .map(([name, score]) => (
                            <div key={name}>
                              <dt>{metricName(name)}</dt>
                              <dd>
                                {percent(baseline.metrics[name])} → {percent(score)} ·{' '}
                                {delta(baseline.metrics[name], score)}
                              </dd>
                            </div>
                          ))}
                      </dl>
                    </>
                  ) : (
                    <p>{t('notComparable')}</p>
                  )}
                </>
              )}
            </section>
          </div>
        )}
      </SettingsSectionCard>
    </div>
  )
}
