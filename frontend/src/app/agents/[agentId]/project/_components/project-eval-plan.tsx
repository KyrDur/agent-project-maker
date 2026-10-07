'use client'

import { formatDisplayNumber } from '@/lib/utils/display-format'

import { useState } from 'react'
import { ProjectSelect } from './project-select'
import { useLocale, useTranslations } from 'next-intl'
import { ProjectScoringRule, useMetricName } from './project-scoring'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectGeneration } from '../_hooks/use-project-evaluation'

export function ProjectEvalPlan({
  agentId,
  versionId,
  onGenerated,
}: {
  agentId: string
  versionId: string
  onGenerated: (id: string) => void
}) {
  const t = useTranslations('agentProject')
  const locale = useLocale()
  const [purpose, setPurpose] = useState<'regression' | 'validation'>('regression')
  const metricName = useMetricName()
  const { project, plan, cases, errorCode } = useProjectGeneration(agentId)
  const spec = project.data?.eval_spec_json
  const busy = plan.isPending || cases.isPending
  return (
    <div className="my-4 space-y-3">
      <Button
        variant="outline"
        disabled={busy || !versionId}
        onClick={() => plan.mutate(versionId)}
      >
        {t('generatePlan')}
      </Button>
      {busy && <p role="status">{t('generating')}</p>}
      {spec && (
        <>
          <h3 className="font-medium">{t('evalPlan')}</h3>
          <p>{t('scoring.weightNotice')}</p>
          {(spec.rubric_version ?? 1) >= 2 && <p>{t('scoring.sourceReview')}</p>}
          <p>{t('scoring.thresholdRule')}</p>
          <p>{t('planCount', { count: spec.case_count })}</p>
          <p>
            {t('passThreshold', {
              value: formatDisplayNumber(spec.pass_threshold * 100, {
                locale,
                minimumFractionDigits: 1,
                maximumFractionDigits: 1,
              }),
            })}
          </p>
          {spec.pass_threshold_reason && <p>{spec.pass_threshold_reason}</p>}
          <ul className="space-y-2">
            {spec.metrics.map((metric) => (
              <li key={metric.name}>
                <strong>{metricName(metric.name, metric)}</strong>
                <ProjectScoringRule metric={metric} legacy={(spec.rubric_version ?? 1) < 2} />
              </li>
            ))}
          </ul>
          <p>
            {t('scenarioCategories')}:{' '}
            {spec.categories.map((name) => t(`scenarios.${name}`)).join(', ')}
          </p>
          {spec.version_id !== versionId && <p role="status">{t('planVersionMismatch')}</p>}
          <p>{t('automaticEvaluation')}</p>
          <ProjectSelect
            label={t('qualityRevision.setPurpose')}
            value={purpose}
            onChange={(v) => setPurpose(v as 'regression' | 'validation')}
            options={['regression', 'validation'].map((v) => ({
              value: v,
              label: t(`qualityRevision.purposes.${v}`),
            }))}
          />
          <p>{t('qualityRevision.validationBoundary')}</p>
          <Button
            disabled={busy || spec.version_id !== versionId}
            onClick={() =>
              cases.mutate(
                {
                  versionId,
                  purpose,
                  evaluation_focus: undefined,
                },
                { onSuccess: (row) => onGenerated(row.id) },
              )
            }
          >
            {t('generateCases')}
          </Button>
        </>
      )}
      {(plan.isError || cases.isError) && (
        <ErrorState
          title={
            t.has(`executionErrors.${errorCode}`)
              ? t(`executionErrors.${errorCode}`)
              : t('generationFailed')
          }
          onRetry={() =>
            plan.isError
              ? plan.mutate(versionId)
              : cases.mutate({ versionId, purpose }, { onSuccess: (row) => onGenerated(row.id) })
          }
        />
      )}
    </div>
  )
}
