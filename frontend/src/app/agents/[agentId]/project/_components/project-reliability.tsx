'use client'

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import { useProjectLearning, useReliability } from '../_hooks/use-project-learning'
import { guidanceScope, newestRuns } from '../_lib/project-guidance'
import { ProjectEvidenceCard } from './project-evidence-card'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'

export function ProjectReliability({
  agentId,
  versionId,
  versions,
}: {
  agentId: string
  versionId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject.guided')
  const { sets, runs, cancel } = useProjectEvaluation(agentId)
  const { holdout, repeat, validate } = useProjectLearning(agentId, versionId)
  const ordered = newestRuns(runs.data ?? [])
  const { run, source } = guidanceScope(versionId, sets.data ?? [], ordered)
  const reference = source ?? run
  const development = sets.data?.find((s) => s.id === reference?.eval_set_id)
  const baselineVersion = development?.rubric_json?.version_id
  const baseline =
    [...ordered]
      .reverse()
      .find(
        (r) =>
          r.version_id === baselineVersion &&
          r.eval_set_id === reference?.eval_set_id &&
          r.status === 'completed' &&
          !r.comparison_json?.reliability &&
          r.comparison_json?.purpose !== 'holdout',
      ) ?? reference
  const reserved =
    holdout.data ??
    sets.data?.find(
      (s) =>
        s.rubric_json?.purpose === 'holdout' &&
        s.rubric_json.development_set_id === baseline?.eval_set_id &&
        s.quality_report_json?.status === 'approved',
    )
  const active = ordered.some((r) => r.status === 'pending' || r.status === 'running')
  const report = useReliability(agentId, versionId, active)
  const ids = useRef<Record<string, string>>({})
  const [count, setCount] = useState(3)
  const [showCases, setShowCases] = useState(false)
  const busy = holdout.isPending || repeat.isPending || validate.isPending
  const request = (key: string) => ids.current[key] ?? (ids.current[key] = crypto.randomUUID())
  const version = (id: string) => versions.find((v) => v.id === id)?.version_number ?? 0
  return (
    <div className="space-y-4 border-t border-border pt-4">
      <h3 className="text-lg font-semibold">{t('reliabilityTitle')}</h3>
      <p>{t('reliabilityDescription')}</p>
      {runs.isError || sets.isError || report.isError ? (
        <ErrorState
          onRetry={() => {
            void runs.refetch()
            void sets.refetch()
            void report.refetch()
          }}
        />
      ) : (
        <>
          {!baseline && <p>{t('testFirst')}</p>}
          {baseline && (
            <>
              <label className="flex flex-wrap items-center gap-2">
                <span>{t('repetitions')}</span>
                <select
                  className="rounded-md border border-border bg-background p-2"
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                >
                  {[2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <p className="text-sm text-muted-foreground">{t('repeatCost', { count })}</p>
              <Button
                variant="outline"
                disabled={busy || active || !run}
                onClick={() => {
                  if (run)
                    repeat.mutate(
                      { runId: run.id, requestId: request('repeat'), count },
                      {
                        onSuccess: () => {
                          delete ids.current.repeat
                        },
                      },
                    )
                }}
              >
                {t('repeatAction')}
              </Button>
              <div className="space-y-3">
                <h4 className="font-medium">{t('reservedTitle')}</h4>
                <p>{t('reservedDescription')}</p>
                {!reserved ? (
                  <Button
                    variant="outline"
                    disabled={busy || active}
                    onClick={() =>
                      holdout.mutate(
                        { setId: baseline.eval_set_id, requestId: request('holdout') },
                        {
                          onSuccess: () => {
                            delete ids.current.holdout
                          },
                        },
                      )
                    }
                  >
                    {t(holdout.isPending ? 'working' : 'reserveAction')}
                  </Button>
                ) : (
                  <>
                    <p>
                      {reserved.name} · {reserved.cases_json.length}
                    </p>
                    {reserved.quality_report_json?.status !== 'approved' ? (
                      <>
                        <p role="alert">{t('structureRejected')}</p>
                        <Button
                          disabled={busy}
                          onClick={() => {
                            delete ids.current.holdout
                            holdout.mutate({
                              setId: baseline.eval_set_id,
                              requestId: request('holdout'),
                            })
                          }}
                        >
                          {t('regenerateReserved')}
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button variant="outline" onClick={() => setShowCases(!showCases)}>
                          {t('previewReserved')}
                        </Button>
                        {showCases && (
                          <div className="space-y-3">
                            {reserved.cases_json.slice(0, 3).map((c) => (
                              <article key={c.id} className="border-l-2 border-border pl-3">
                                <p>{c.name}</p>
                                <p>{c.input}</p>
                                <p>{t('expected', { value: c.expected.answer ?? '' })}</p>
                              </article>
                            ))}
                          </div>
                        )}
                        <p className="text-sm text-muted-foreground">
                          {t('validationCost', { count: count * 2 })}
                        </p>
                        <Button
                          disabled={
                            busy || active || baseline.version_id === versionId || !showCases
                          }
                          onClick={() =>
                            validate.mutate(
                              {
                                runId: baseline.id,
                                setId: reserved.id,
                                requestId: request('validate'),
                                count,
                              },
                              {
                                onSuccess: () => {
                                  delete ids.current.validate
                                },
                              },
                            )
                          }
                        >
                          {t('validateAction')}
                        </Button>
                        {baseline.version_id === versionId && <p>{t('candidateRequired')}</p>}
                      </>
                    )}
                  </>
                )}
              </div>
            </>
          )}
          {report.data?.trials.map((group) => (
            <article key={group.group_id} className="space-y-2 border-t border-border pt-3">
              <h4 className="font-medium">
                {t(group.kind === 'validation' ? 'validationResult' : 'repeatResult')}
              </h4>
              {Object.entries(group.versions).map(([id, result]) => (
                <div key={id}>
                  <p>
                    {t('trialProgress', {
                      version: version(id),
                      completed: result.completed,
                      scheduled: result.scheduled,
                    })}
                  </p>
                  <p>
                    {result.mean === null
                      ? t('incompleteScore')
                      : t('trialSpread', {
                          mean: Math.round(result.mean * 100),
                          min: Math.round((result.min ?? 0) * 100),
                          max: Math.round((result.max ?? 0) * 100),
                          spread: Math.round((result.stddev ?? 0) * 100),
                        })}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {t('excludedTrials', { count: result.incomplete })}
                  </p>
                  {result.run_ids.map((runId) => {
                    const trial = ordered.find((r) => r.id === runId)
                    return trial && (trial.status === 'pending' || trial.status === 'running') ? (
                      <Button
                        key={runId}
                        variant="outline"
                        size="sm"
                        disabled={cancel.isPending}
                        onClick={() => cancel.mutate(runId)}
                      >
                        {t('cancelTrial', { version: version(id) })}
                      </Button>
                    ) : null
                  })}
                </div>
              ))}
            </article>
          ))}
          <p className="text-sm text-muted-foreground">{t('statisticsBoundary')}</p>
          <details>
            <summary className="cursor-pointer">{t('calibrationTitle')}</summary>
            <div className="mt-3 space-y-3">
              <p>{t('calibrationHelp')}</p>
              {report.data && (
                <p>
                  {t('calibrationCount', {
                    reviewed: report.data.calibration.reviewed,
                    disagreements: report.data.calibration.disagreements,
                  })}
                </p>
              )}
              {run?.results_json?.slice(0, 3).map((result) => (
                <ProjectEvidenceCard
                  key={result.case_id}
                  agentId={agentId}
                  run={run}
                  result={result}
                />
              ))}
              {report.data?.calibration.reviews
                .filter((r) => !r.agreed)
                .map((r) => (
                  <p key={`${r.run_id}:${r.case_id}`}>
                    {t('disagreement')} · {r.reason}
                  </p>
                ))}
            </div>
          </details>
        </>
      )}
      {(holdout.isError || repeat.isError || validate.isError || cancel.isError) && <ErrorState />}
    </div>
  )
}
