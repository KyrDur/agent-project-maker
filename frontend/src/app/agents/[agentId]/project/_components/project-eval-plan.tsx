'use client'

import { useTranslations } from 'next-intl'
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
  const { project, plan, cases } = useProjectGeneration(agentId)
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
          <p>{t('planCount', { count: spec.case_count })}</p>
          <p>{t('passThreshold', { value: Math.round(spec.pass_threshold * 100) })}</p>
          <ul className="space-y-2">
            {spec.metrics.map((metric) => (
              <li key={metric.name}>
                <strong>
                  {t.has(`metricNames.${metric.name}`)
                    ? t(`metricNames.${metric.name}`)
                    : metric.name}
                </strong>
                {' · '}
                {t('metricWeight', { value: Math.round(metric.weight * 100) })}
                <p>{metric.criteria}</p>
              </li>
            ))}
          </ul>
          <p>
            {t('scenarioCategories')}:{' '}
            {spec.categories.map((name) => t(`scenarios.${name}`)).join(', ')}
          </p>
          {spec.version_id !== versionId && <p role="status">{t('planVersionMismatch')}</p>}
          <Button
            disabled={busy || spec.version_id !== versionId}
            onClick={() => cases.mutate(versionId, { onSuccess: (row) => onGenerated(row.id) })}
          >
            {t('generateCases')}
          </Button>
        </>
      )}
      {(plan.isError || cases.isError) && <ErrorState title={t('generationFailed')} />}
    </div>
  )
}
