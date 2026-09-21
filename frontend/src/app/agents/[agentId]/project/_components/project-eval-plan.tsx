'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { Textarea } from '@/components/ui/textarea'
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
  const [focus, setFocus] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const options =
    spec?.focus_options?.length
      ? spec.focus_options
      : spec
        ? [
            ...spec.metrics.map((metric) => ({
              id: metric.name,
              label: t.has(`metricNames.${metric.name}`)
                ? t(`metricNames.${metric.name}`)
                : metric.name,
              description: metric.criteria,
            })),
            ...['ambiguous', 'missing_information', 'tool_failure']
              .filter((id) => !spec.metrics.some((metric) => metric.name === id))
              .map((id) => ({
                id,
                label: t.has(`scenarios.${id}`) ? t(`scenarios.${id}`) : id,
                description: t('evaluationFocus.fallbackDescription'),
              })),
          ].slice(0, 8)
        : []
  const toggleFocus = (id: string) =>
    setFocus((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    )
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
          {!!options.length && (
            <section className="space-y-3 rounded-lg border border-border/70 p-3">
              <div>
                <h4 className="font-medium">{t('evaluationFocus.title')}</h4>
                <p className="text-sm text-muted-foreground">
                  {t('evaluationFocus.description')}
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {options.map((option) => (
                  <label
                    key={option.id}
                    className="flex cursor-pointer gap-2 rounded-lg border border-border/70 p-3"
                  >
                    <input
                      type="checkbox"
                      checked={focus.includes(option.id)}
                      onChange={() => toggleFocus(option.id)}
                    />
                    <span>
                      <span className="block font-medium">{option.label}</span>
                      <span className="block text-sm text-muted-foreground">
                        {option.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
              <label className="block space-y-1">
                <span className="text-sm font-medium">{t('evaluationFocus.reason')}</span>
                <Textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder={t('evaluationFocus.reasonPlaceholder')}
                />
              </label>
              {focus.length < 2 && (
                <p className="text-sm text-destructive">{t('evaluationFocus.minimum')}</p>
              )}
            </section>
          )}
          <Button
            disabled={busy || spec.version_id !== versionId || focus.length < 2}
            onClick={() =>
              cases.mutate(
                {
                  versionId,
                  evaluation_focus: focus,
                  evaluation_focus_reason: reason.trim() || null,
                },
                { onSuccess: (row) => onGenerated(row.id) },
              )
            }
          >
            {t('generateCases')}
          </Button>
        </>
      )}
      {(plan.isError || cases.isError) && <ErrorState title={t('generationFailed')} />}
    </div>
  )
}
