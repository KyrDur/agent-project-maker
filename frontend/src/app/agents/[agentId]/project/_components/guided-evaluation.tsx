'use client'

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectEvaluation, useProjectGeneration } from '../_hooks/use-project-evaluation'
import { guidanceScope } from '../_lib/project-guidance'
import { ProjectEvalPlan } from './project-eval-plan'
import { ProjectEvidenceCard } from './project-evidence-card'

export function GuidedEvaluation({
  agentId,
  versionId,
  onImprove,
}: {
  agentId: string
  versionId: string
  onImprove: () => void
}) {
  const t = useTranslations('agentProject.guided')
  const projectT = useTranslations('agentProject')
  const { sets, runs, quality, start, cancel, retry } = useProjectEvaluation(agentId)
  const project = useProjectGeneration(agentId).project
  const contract = project.data?.requirements_json?.learning_brief?.content_hash
  const [selectedSet, setSelectedSet] = useState('')
  const [previewAll, setPreviewAll] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [rejected, setRejected] = useState(false)
  const requestId = useRef<string | null>(null)
  const retryId = useRef<string | null>(null)
  const scope = guidanceScope(versionId, sets.data ?? [], runs.data ?? [])
  const matchingSets = [...(sets.data ?? [])]
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    .filter(
      (s) =>
        s.rubric_json?.version_id === versionId &&
        s.rubric_json?.purpose !== 'holdout' &&
        (!contract || s.rubric_json?.business_contract?.content_hash === contract),
    )
  const dataset =
    sets.data?.find((s) => s.id === selectedSet) ?? (contract ? matchingSets[0] : scope.dataset)
  const run = scope.run?.eval_set_id === dataset?.id ? scope.run : undefined
  const active = run?.status === 'running' || run?.status === 'pending'
  const failed = run?.results_json?.filter((r) => r.status === 'failed') ?? []
  async function test() {
    if (!dataset) return
    setSubmitting(true)
    setRejected(false)
    requestId.current ??= crypto.randomUUID()
    try {
      const checked =
        dataset.quality_report_json?.status === 'approved'
          ? dataset
          : await quality.mutateAsync(dataset.id)
      if (checked.quality_report_json?.status !== 'approved') {
        setRejected(true)
        return
      }
      await start.mutateAsync({
        request_id: requestId.current,
        version_id: versionId,
        eval_set_id: dataset.id,
      })
      requestId.current = null
    } catch {
    } finally {
      setSubmitting(false)
    }
  }
  if (sets.isError || runs.isError)
    return (
      <ErrorState
        onRetry={() => {
          void sets.refetch()
          void runs.refetch()
        }}
      />
    )
  if (sets.isPending || runs.isPending) return <p role="status">{t('loading')}</p>
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold">{t('testTitle')}</h3>
        <p>{t('testDescription')}</p>
      </div>
      {!dataset ? (
        <ProjectEvalPlan agentId={agentId} versionId={versionId} onGenerated={setSelectedSet} />
      ) : (
        <>
          <div className="space-y-3">
            <h4 className="font-medium">{dataset.name}</h4>
            <p>{t('previewHelp')}</p>
            {(previewAll ? dataset.cases_json : dataset.cases_json.slice(0, 3)).map((c) => (
              <article key={c.id} className="space-y-2 border-l-2 border-border pl-3">
                <p className="font-medium">{c.name}</p>
                <p>{c.input}</p>
                <p>{t('expected', { value: c.expected.answer ?? '' })}</p>
              </article>
            ))}
            <Button variant="outline" onClick={() => setPreviewAll(!previewAll)}>
              {t(previewAll ? 'showLess' : 'showAll', { count: dataset.cases_json.length })}
            </Button>
          </div>
          {active ? (
            <div className="space-y-2">
              <p role="status">{t('testRunning')}</p>
              <Button
                variant="outline"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(run.id)}
              >
                {t('cancel')}
              </Button>
            </div>
          ) : (
            <Button disabled={submitting} onClick={() => void test()}>
              {t(submitting ? 'working' : run ? 'rerun' : 'confirmAndTest')}
            </Button>
          )}
          {rejected && <p role="alert">{t('structureRejected')}</p>}
          {run?.status === 'failed' && (
            <div className="space-y-2">
              <p>{t('executionFailed')}</p>
              <Button
                disabled={retry.isPending}
                onClick={() => {
                  retryId.current ??= crypto.randomUUID()
                  retry.mutate(
                    { runId: run.id, requestId: retryId.current },
                    {
                      onSuccess: () => {
                        retryId.current = null
                      },
                    },
                  )
                }}
              >
                {t('retry')}
              </Button>
            </div>
          )}
          {run && !active && (
            <>
              <p>
                {projectT(`runStatuses.${run.status}`)} ·{' '}
                {t('resultCount', {
                  passed: run.metrics_json?.passed ?? 0,
                  total: run.metrics_json?.total ?? 0,
                })}
              </p>
              <p className="text-sm text-muted-foreground">{t('scoreBoundary')}</p>
              {run.results_json
                ?.filter((r) => r.status !== 'passed')
                .map((result) => (
                  <ProjectEvidenceCard
                    key={result.case_id}
                    agentId={agentId}
                    run={run}
                    result={result}
                  />
                ))}
              {!!failed.length && run.metrics_json?.quality_complete !== false && (
                <Button onClick={onImprove}>{t('improveAction')}</Button>
              )}
              <details>
                <summary className="cursor-pointer">{t('passedCases')}</summary>
                <div className="mt-3 space-y-3">
                  {run.results_json
                    ?.filter((r) => r.status === 'passed')
                    .map((result) => (
                      <ProjectEvidenceCard
                        key={result.case_id}
                        agentId={agentId}
                        run={run}
                        result={result}
                      />
                    ))}
                </div>
              </details>
            </>
          )}
        </>
      )}
      {(quality.isError || start.isError || cancel.isError || retry.isError) && <ErrorState />}
    </div>
  )
}
