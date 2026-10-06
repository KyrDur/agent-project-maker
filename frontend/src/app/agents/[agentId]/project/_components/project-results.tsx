'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { formatDisplayNumber } from '@/lib/utils/display-format'
import { Button, buttonVariants } from '@/components/ui/button'
import { useProjectPortfolio } from '../_hooks/use-project-portfolio'
import { useProjectEvaluation, useEvaluationReports } from '../_hooks/use-project-evaluation'
import { agentProjectApi } from '../_lib/agent-project-api'
import { ProjectMetricScores, ProjectCaseScores, useMetricName } from './project-scoring'
import type { ResumeStyle } from '../_lib/agent-project-types'

export function ProjectResults({ agentId }: { agentId: string }) {
  const t = useTranslations('agentProject.portfolio')
  const locale = useLocale()
  const metricName = useMetricName()
  const { report, generate, resume, share } = useProjectPortfolio(agentId)
  const evaluation = useProjectEvaluation(agentId)
  const evaluationReports = useEvaluationReports(agentId).data
  const scope = evaluationReports?.reports.find((run) => run.score !== null)?.comparison_key
  const bestRunId = scope ? evaluationReports?.best_run_ids[scope] : undefined
  const latestRun =
    evaluation.runs.data?.find((run) => run.comparison_json?.regression) ??
    evaluation.runs.data?.find((run) => run.id === bestRunId)
  const [style, setStyle] = useState<ResumeStyle>('ai_product')
  const [copyState, setCopyState] = useState<'copied' | 'copyFailed' | null>(null)
  const [showReport, setShowReport] = useState(false)
  const data = report.data?.evidence
  const results = data?.results
  const bestSpec = evaluationReports?.reports.find(
    (row) => row.evaluation_run_id === results?.best_run_id,
  )?.eval_spec
  const percent = (value: number | null | undefined) =>
    value == null
      ? t('unavailable')
      : t('percent', {
          value: formatDisplayNumber(value * 100, { locale, maximumFractionDigits: 1 }),
        })
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
    } catch {
      setCopyState('copyFailed')
    }
  }

  return (
    <SettingsSectionCard title={t('title')}>
      <div className="space-y-4">
        {report.isPending && <p role="status">{t('loading')}</p>}
        {report.isError && <ErrorState title={t('error')} onRetry={() => void report.refetch()} />}
        {data && results && (
          <>
            <p>{t('latestVersion', { version: results.latest_version ?? t('unavailable') })}</p>
            <p>
              {t('currentResult', {
                version: results.current_version ?? t('unavailable'),
                passed: results.current?.passed ?? t('unavailable'),
                total: results.current?.total ?? t('unavailable'),
                rate: results.current?.complete
                  ? percent(results.current.pass_rate)
                  : t('unavailable'),
              })}
            </p>
            <p>{t('best', { version: results.best_version ?? t('unavailable') })}</p>
            <p>
              {t('evaluation', {
                passed: results.best?.passed ?? t('unavailable'),
                total: results.best?.total ?? t('unavailable'),
              })}{' '}
              · {percent(results.best?.pass_rate)}
            </p>
            <p>
              {t('improvement', {
                before: percent(results.baseline?.pass_rate),
                after: percent(results.candidate?.pass_rate),
              })}
            </p>
            {results.comparisons?.map((comparison) => (
              <details key={`${comparison.source_run_id}:${comparison.target_run_id}`}>
                <summary>
                  {t('roundComparison', {
                    source: comparison.source_version,
                    target: comparison.target_version,
                  })}
                </summary>
                {!comparison.comparable || !comparison.changes ? (
                  <p>{t('notComparable')}</p>
                ) : (
                  <>
                    <p>
                      {t(`outcomes.${comparison.changes.outcome}`)} ·{' '}
                      {percent(comparison.changes.pass_rate.before)} →{' '}
                      {percent(comparison.changes.pass_rate.after)}
                    </p>
                    <dl className="space-y-2">
                      {Object.entries(comparison.changes.metrics).map(([name, metric]) => (
                        <div key={name}>
                          <dt>
                            {metricName(
                              name,
                              bestSpec?.metrics?.find((m) => m.name === name),
                            )}
                          </dt>
                          <dd>
                            {metric.before == null
                              ? t('unavailable')
                              : formatDisplayNumber(metric.before * 100, {
                                  locale,
                                  maximumFractionDigits: 3,
                                })}{' '}
                            /100 →{' '}
                            {metric.after == null
                              ? t('unavailable')
                              : formatDisplayNumber(metric.after * 100, {
                                  locale,
                                  maximumFractionDigits: 1,
                                })}{' '}
                            /100
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <p>
                      {t('newFailures', {
                        cases: comparison.changes.regressed_cases.join(', ') || t('none'),
                      })}
                    </p>
                  </>
                )}
                <p>
                  {t('runReferences', {
                    source: comparison.source_run_id,
                    target: comparison.target_run_id,
                  })}
                </p>
              </details>
            ))}
            <ol className="space-y-2" aria-label={t('journey')}>
              {data.versions.map((v) => (
                <li key={v.version}>
                  {t('version', { version: v.version })} · {percent(v.evaluation?.pass_rate)} ·{' '}
                  {v.decision}
                  {v.best && ` · ${t('bestLabel')}`}
                </li>
              ))}
            </ol>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border p-4">
                <p className="text-sm text-muted-foreground">{t('reportOverview')}</p>
                <p className="text-2xl font-semibold">{percent(results.best?.pass_rate)}</p>
                <p className="text-sm">
                  {t('evaluation', {
                    passed: results.best?.passed ?? t('unavailable'),
                    total: results.best?.total ?? t('unavailable'),
                  })}
                </p>
              </div>
              <div className="rounded-lg border p-4">
                <p className="text-sm text-muted-foreground">{t('bestVersion')}</p>
                <p className="text-2xl font-semibold">
                  {results.best_version == null
                    ? t('unavailable')
                    : t('version', { version: results.best_version })}
                </p>
                <p className="text-sm">{t('bestEvidence')}</p>
              </div>
              <div className="rounded-lg border p-4">
                <p className="text-sm text-muted-foreground">{t('failedCases')}</p>
                <p className="text-2xl font-semibold">
                  {latestRun?.results_json?.filter((item) => item.status !== 'passed').length ?? 0}
                </p>
                <p className="text-sm">{latestRun?.eval_set_id ?? t('unavailable')}</p>
              </div>
            </div>
            <section className="space-y-3">
              <h3 className="font-medium">{t('metricsTitle')}</h3>
              <ProjectMetricScores
                summaries={results.best?.metrics}
                spec={bestSpec}
                total={results.best?.total ?? 0}
              />
            </section>
            {latestRun?.results_json?.some((item) => item.status !== 'passed') && (
              <section className="space-y-3">
                <h3 className="font-medium">{t('failedCaseDetails')}</h3>
                {latestRun.results_json
                  .filter((item) => item.status !== 'passed')
                  .map((item) => (
                    <details key={item.case_id} className="rounded-lg border p-3">
                      <summary>{item.name}</summary>
                      <p className="mt-2 text-sm">{item.input}</p>
                      {item.error && <p className="text-sm text-destructive">{item.error}</p>}
                      <ProjectCaseScores
                        result={item}
                        spec={latestRun.comparison_json?.eval_spec}
                      />
                      <p className="text-sm">
                        {t('toolCalls')}:{' '}
                        {item.tool_calls.map((call) => call.name).join(', ') || t('none')}
                      </p>
                    </details>
                  ))}
              </section>
            )}
            <p className="text-sm text-muted-foreground">{t('liveNotice')}</p>
            <div className="flex flex-wrap gap-2">
              <Link className={buttonVariants({ variant: 'outline' })} href={`/agents/${agentId}`}>
                {t('tryLive')}
              </Link>
              <Button variant="outline" onClick={() => setShowReport((v) => !v)}>
                {t('viewReport')}
              </Button>
              <Button
                variant="outline"
                disabled={generate.isPending}
                onClick={() => generate.mutate()}
              >
                {t('refresh')}
              </Button>
              <a
                className={buttonVariants({ variant: 'outline' })}
                href={agentProjectApi.exportUrl(agentId)}
              >
                {t('download')}
              </a>
            </div>
            {showReport && (
              <div className="space-y-4">
                {report.data?.sections.map((section) => (
                  <section key={section.title}>
                    <h3 className="font-medium">{section.title}</h3>
                    <pre className="whitespace-pre-wrap break-words text-sm">{section.body}</pre>
                  </section>
                ))}
              </div>
            )}
            <div className="space-y-2">
              <label className="block" htmlFor={`resume-${agentId}`}>
                {t('style')}
              </label>
              <select
                id={`resume-${agentId}`}
                className="rounded-md border bg-background p-2"
                value={style}
                onChange={(e) => setStyle(e.target.value as ResumeStyle)}
              >
                {(['ai_product'] as const).map((value) => (
                  <option key={value} value={value}>
                    {t(`styles.${value}`)}
                  </option>
                ))}
              </select>
              <Button
                variant="outline"
                disabled={resume.isPending}
                onClick={() => resume.mutate(style)}
              >
                {t('generateResume')}
              </Button>
              {resume.data && (
                <>
                  <p>{t(`styles.${resume.data.style}`)}</p>
                  <ul className="list-disc space-y-2 pl-5">
                    {resume.data.bullets.map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                  <Button
                    variant="outline"
                    onClick={() => void copy(resume.data.bullets.join('\n'))}
                  >
                    {t('copy')}
                  </Button>
                </>
              )}
            </div>
            <p className="text-sm text-muted-foreground">{t('shareNotice')}</p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={share.isPending}
                onClick={() => share.mutate(false)}
              >
                {t('share')}
              </Button>
              <Button
                variant="outline"
                disabled={share.isPending}
                onClick={() => share.mutate(true)}
              >
                {t('revoke')}
              </Button>
              {share.data?.path && (
                <>
                  <Link href={share.data.path} target="_blank" rel="noopener noreferrer">
                    {t('openShare')}
                  </Link>
                  <Button
                    variant="outline"
                    onClick={() =>
                      void copy(new URL(share.data.path ?? '', window.location.origin).href)
                    }
                  >
                    {t('copyLink')}
                  </Button>
                </>
              )}
            </div>
            {share.isSuccess && !share.data.path && <p role="status">{t('revoked')}</p>}
            {copyState && <p role="status">{t(copyState)}</p>}
            {(generate.isError || resume.isError || share.isError) && (
              <ErrorState title={t('error')} />
            )}
            <ul className="list-disc space-y-2 pl-5">
              {data.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </SettingsSectionCard>
  )
}
