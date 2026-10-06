'use client'

import { useLocale, useTranslations } from 'next-intl'
import { formatDisplayNumber } from '@/lib/utils/display-format'
import type {
  EvaluationResult,
  EvaluationSpec,
  MetricSummary,
  ScoringMetric,
} from '../_lib/agent-project-types'

export function useMetricName() {
  const t = useTranslations('agentProject')
  return (name: string, metric?: ScoringMetric) =>
    t.has(`metricNames.${name}`)
      ? t(`metricNames.${name}`)
      : metric?.display_name || t('scoring.customMetric')
}

export function ProjectScoringRule({ metric, legacy }: { metric: ScoringMetric; legacy: boolean }) {
  const t = useTranslations('agentProject.scoring')
  const p = useTranslations('agentProject.practice')
  return (
    <details className="space-y-2">
      <summary>{t('viewRule')}</summary>
      <div className="space-y-3 text-sm">
        <p>{metric.description || metric.criteria}</p>
        <p>
          {t(
            metric.type === 'deterministic'
              ? 'programRule'
              : legacy
                ? 'legacyMethod'
                : 'criterionMethod',
          )}
        </p>
        {legacy && <p className="text-muted-foreground">{t('legacyEvidence')}</p>}
        {metric.requirement_refs?.map((ref, i) => (
          <blockquote key={i} className="border-l-2 pl-3">
            {t('requirementSource')}: {p.has(ref.field) ? p(ref.field) : ref.field} · {ref.quote}
          </blockquote>
        ))}
        {metric.scoring_criteria?.map((criterion) => (
          <div key={criterion.id} className="space-y-1 border-t pt-2">
            <p className="font-medium">{criterion.description}</p>
            <p>{t('anchor', { level: 0, description: criterion.fail })}</p>
            <p>{t('anchor', { level: 0.5, description: criterion.partial })}</p>
            <p>{t('anchor', { level: 1, description: criterion.full })}</p>
            {criterion.critical && <p>{t('critical')}</p>}
            {criterion.requirement_refs.map((ref, i) => (
              <blockquote key={i} className="border-l-2 pl-3">
                {t('requirementSource')}: {ref.quote}
              </blockquote>
            ))}
          </div>
        ))}
        <details>
          <summary>{t('technicalIdentifier')}</summary>
          <code>{metric.name}</code>
        </details>
      </div>
    </details>
  )
}

export function ProjectMetricScores({
  summaries,
  spec,
  total,
}: {
  summaries?: Record<string, MetricSummary>
  spec?: EvaluationSpec | null
  total: number
}) {
  const t = useTranslations('agentProject.scoring')
  const metricName = useMetricName()
  const locale = useLocale()
  const names = [
    ...new Set([...(spec?.metrics?.map((m) => m.name) ?? []), ...Object.keys(summaries ?? {})]),
  ]
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t('averageExplanation')}</p>
      {(spec?.rubric_version ?? 1) >= 3 && <p>{t('taskQualitySeparation')}</p>}
      {!names.length && <p>{t('noScores')}</p>}
      <dl className="grid gap-4 sm:grid-cols-2">
        {names.map((name) => {
          const metric = spec?.metrics?.find((m) => m.name === name)
          const value = summaries?.[name]
          return (
            <div key={name} className="space-y-2">
              <dt className="font-medium">
                {metricName(name, metric)}
                {metric?.verdict_role === 'quality' && ` · ${t('qualityOnly')}`}
              </dt>
              <dd className="space-y-1">
                <p>
                  {value
                    ? t('average', {
                        value: formatDisplayNumber(value.score * 100, {
                          locale,
                          minimumFractionDigits: 1,
                          maximumFractionDigits: 1,
                        }),
                      })
                    : t('unavailable')}
                </p>
                <p className="text-sm text-muted-foreground">
                  {value?.evaluated_cases != null
                    ? t('coverage', { count: value.evaluated_cases, total })
                    : (spec?.rubric_version ?? 1) >= 2
                      ? t('coverage', { count: 0, total })
                      : t('coverageUnavailable')}
                </p>
                {value?.passed_cases != null && (
                  <p className="text-sm">
                    {t('metricPassCount', {
                      count: value.passed_cases,
                      total: value.evaluated_cases ?? 0,
                    })}
                  </p>
                )}
                {value?.not_applicable_cases != null && value.not_applicable_cases > 0 && (
                  <p>{t('notApplicableCount', { count: value.not_applicable_cases })}</p>
                )}
                {value?.unscored_cases != null && value.unscored_cases > 0 && (
                  <p>{t('unscoredCount', { count: value.unscored_cases })}</p>
                )}
                {metric ? (
                  <ProjectScoringRule metric={metric} legacy={(spec?.rubric_version ?? 1) < 2} />
                ) : (
                  <p className="text-sm">{t('missingRule')}</p>
                )}
              </dd>
            </div>
          )
        })}
      </dl>
      <p className="text-sm text-muted-foreground">{t('retrievalNotMeasured')}</p>
    </div>
  )
}

export function ProjectCaseScores({
  result,
  spec,
}: {
  result: EvaluationResult
  spec?: EvaluationSpec
}) {
  const t = useTranslations('agentProject.scoring')
  const p = useTranslations('agentProject')
  const metricName = useMetricName()
  const locale = useLocale()
  return (
    <div className="space-y-3">
      {result.fact_check && (
        <div className="space-y-2">
          <p>
            {t('factCounts', {
              supported: result.fact_check.supported,
              total: result.fact_check.total,
              unsupported: result.fact_check.unsupported,
              unknown: result.fact_check.unknown,
            })}
          </p>
          {result.fact_check.items.map((fact, i) => (
            <div key={i} className="border-l-2 pl-3">
              <p>
                {fact.claim} ·{' '}
                {t.has(`factVerdicts.${fact.verdict}`)
                  ? t(`factVerdicts.${fact.verdict}`)
                  : fact.verdict}
              </p>
              {fact.evidence.map((ref, j) => (
                <blockquote key={j}>
                  {ref.reference}：{ref.quote}
                </blockquote>
              ))}
            </div>
          ))}
          <p className="text-sm text-muted-foreground">{t('calibrationLimit')}</p>
        </div>
      )}
      {Object.entries(result.metric_scores ?? {}).map(([name, score]) => (
        <div key={name} className="space-y-2">
          <p className="font-medium">
            {metricName(
              name,
              spec?.metrics?.find((m) => m.name === name),
            )}{' '}
            ·{' '}
            {t('caseScore', {
              value: formatDisplayNumber(score.score * 100, {
                locale,
                minimumFractionDigits: 1,
                maximumFractionDigits: 1,
              }),
            })}{' '}
            · {p(score.passed ? 'checkPassed' : 'checkFailed')}
          </p>
          <p className="whitespace-pre-wrap">
            {score.method === 'deterministic' ? p('deterministicReason') : score.reason}
          </p>
          {score.criteria_results?.map((v) => (
            <div key={v.criterion_id} className="space-y-1 border-l-2 pl-3">
              <p>
                {spec?.metrics
                  ?.find((m) => m.name === name)
                  ?.scoring_criteria?.find((c) => c.id === v.criterion_id)?.description ||
                  v.criterion_id}{' '}
                · {t('level', { value: v.level })}
              </p>
              <p>{v.reason}</p>
              {v.evidence.map((ref, i) => (
                <blockquote key={i} className="whitespace-pre-wrap">
                  {t('evidenceReference', { reference: ref.reference })}
                  <br />
                  {ref.quote}
                </blockquote>
              ))}
            </div>
          ))}
        </div>
      ))}
      {Object.values(result.metric_scores ?? {}).some(
        (score) => score.method !== 'deterministic' && !score.criteria_results,
      ) && <p className="text-sm text-muted-foreground">{t('legacyEvidence')}</p>}
      {Object.entries(result.metric_unavailable ?? {}).map(([name, reason]) => (
        <p key={name}>
          {metricName(
            name,
            spec?.metrics?.find((m) => m.name === name),
          )}{' '}
          · {t('unavailable')} ·{' '}
          {reason === 'no_applicable_program_checks' ? t('noProgramChecks') : reason}
        </p>
      ))}
    </div>
  )
}
