'use client'

import Link from 'next/link'
import { useMutation } from '@tanstack/react-query'
import { ProjectSelect } from './project-select'
import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { formatDisplayNumber } from '@/lib/utils/display-format'
import { Button, buttonVariants } from '@/components/ui/button'
import { useProjectPortfolio } from '../_hooks/use-project-portfolio'
import { useProjectEvaluation, useEvaluationReports } from '../_hooks/use-project-evaluation'
import { agentProjectApi } from '../_lib/agent-project-api'
import { ProjectEvidenceValue } from './project-execution-log'
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
  const [caseOne, setCaseOne] = useState('')
  const [caseTwo, setCaseTwo] = useState('')
  const selection = useMutation({
    mutationFn: () => agentProjectApi.selectCases(agentId, [caseOne, caseTwo].filter(Boolean)),
    onSuccess: () => report.refetch(),
  })
  const caseOptions = [
    ...new Map(
      (evaluation.runs.data ?? []).flatMap((run) =>
        (run.results_json ?? []).map(
          (r) => [r.case_id, { value: r.case_id, label: r.name }] as const,
        ),
      ),
    ).values(),
  ]
  const [style, setStyle] = useState<ResumeStyle>('ai_product')
  const [copyState, setCopyState] = useState<'copied' | 'copyFailed' | null>(null)
  const [showReport, setShowReport] = useState(false)
  const data = report.data?.evidence
  const results = data?.results
  const versionsForBest = (id: string) =>
    evaluation.runs.data?.find((run) => run.version_id === id)?.id === bestRunId
  const bestSpec = evaluationReports?.reports.find((row) =>
    versionsForBest(row.version_id),
  )?.eval_spec
  const percent = (value: number | null | undefined) =>
    value == null
      ? t('unavailable')
      : t('percent', {
          value: formatDisplayNumber(value * 100, {
            locale,
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
          }),
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
            <details>
              <summary>{t('chooseCases')}</summary>
              <ProjectSelect
                label={t('caseOne')}
                value={caseOne}
                onChange={setCaseOne}
                options={caseOptions}
              />
              <ProjectSelect
                label={t('caseTwo')}
                value={caseTwo}
                onChange={setCaseTwo}
                options={caseOptions.filter((c) => c.value !== caseOne)}
              />
              <Button
                disabled={!caseOne || !caseTwo || caseOne === caseTwo || selection.isPending}
                onClick={() => selection.mutate()}
              >
                {t('saveCases')}
              </Button>
              {selection.isError && <ErrorState />}
            </details>
            {data.case_cards?.map((card) => (
              <article key={card.reference} className="space-y-3 border-b pb-4">
                <h3 className="font-medium">{card.title}</h3>
                <p>{card.personal_task}</p>
                <p>{card.system_task}</p>
                <details>
                  <summary>{t('caseChanges')}</summary>
                  {card.changes?.length ? (
                    card.changes.map((change, i) => (
                      <div key={`${change.source}:${i}`} className="space-y-2">
                        <p>
                          {change.title} · {change.source}
                        </p>
                        <p>
                          {t('changeAuthor', {
                            author: t(
                              change.author === 'codex_demo'
                                ? 'authorDemo'
                                : ['user', 'user_confirmed'].includes(change.author)
                                  ? 'authorUser'
                                  : 'authorSystem',
                            ),
                          })}
                        </p>
                        <p>{change.reason}</p>
                        <ProjectEvidenceValue value={change.diffs} />
                      </div>
                    ))
                  ) : (
                    <p>{t('caseNoChanges')}</p>
                  )}
                </details>
                {card.history.map((trial) => (
                  <details key={trial.reference}>
                    <summary>
                      V{trial.version} · {trial.reference}
                    </summary>
                    <p>{trial.user_request}</p>
                    <p>{trial.judgment_basis}</p>
                    <p>
                      {t('caseOutcome', {
                        status: trial.status,
                        trial: trial.trial,
                        termination: trial.termination ?? t('unavailable'),
                      })}
                    </p>
                    <details>
                      <summary>{t('caseEnvironment')}</summary>
                      <ProjectEvidenceValue value={trial.initial_state} />
                      <ProjectEvidenceValue value={trial.final_state} />
                    </details>
                    <details>
                      <summary>{t('caseJudgment')}</summary>
                      <ProjectEvidenceValue value={trial.checks} />
                      <ProjectEvidenceValue value={trial.judgments} />
                      <ProjectEvidenceValue value={trial.model_calls} />
                    </details>
                    <p>{trial.success_conditions}</p>
                    <p>{trial.actual_answer}</p>
                    {trial.timeline.map((event) => (
                      <div key={event.event}>
                        <p>
                          {event.event} · {event.tool} · {event.error}
                        </p>
                        <ProjectEvidenceValue value={event.arguments} />
                        <ProjectEvidenceValue value={event.returned_facts} />
                      </div>
                    ))}
                  </details>
                ))}
                {card.reviews.map((review, i) => (
                  <p key={i}>
                    {review.finding} · {review.source}
                  </p>
                ))}
                {card.limitations.map((limit) => (
                  <p key={limit}>{limit}</p>
                ))}
              </article>
            ))}
            {data.material_readiness === 'missing_actual_cases' && (
              <p role="status">{t('missingCases')}</p>
            )}
            {Object.values(report.data?.artifact_status ?? {}).includes('stale') && (
              <p role="status">{t('staleMaterials')}</p>
            )}
            {resume.data &&
              report.data &&
              resume.data.evidence_hash !== report.data.evidence_hash && (
                <p role="status">{t('staleMaterials')}</p>
              )}
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
                                  minimumFractionDigits: 1,
                                  maximumFractionDigits: 1,
                                })}{' '}
                            /100 →{' '}
                            {metric.after == null
                              ? t('unavailable')
                              : formatDisplayNumber(metric.after * 100, {
                                  locale,
                                  minimumFractionDigits: 1,
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
                    <details
                      key={`${item.case_id}:${item.trial ?? 1}`}
                      className="rounded-lg border p-3"
                    >
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
