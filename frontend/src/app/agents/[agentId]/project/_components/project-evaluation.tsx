'use client'

import { useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { formatDisplayDateTime } from '@/lib/utils/display-format'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import type {
  AgentProjectVersionSummary,
  EvaluationCase,
  EvaluationMetrics,
} from '../_lib/agent-project-types'
import { ProjectSelect } from './project-select'
import { ProjectEvalPlan } from './project-eval-plan'
import { ProjectOptimization } from './project-optimization'
import { ProjectCaseEditor } from './project-case-editor'

export function ProjectMetrics({ metrics }: { metrics: EvaluationMetrics | null }) {
  const t = useTranslations('agentProject')
  return metrics ? (
    <div>
      <p>
        {t('metrics', {
          total: metrics.total,
          passed: metrics.passed ?? 0,
          failed: metrics.failed ?? 0,
          errored: metrics.errored ?? 0,
        })}
      </p>
      {metrics.pass_rate != null && (
        <p>{t('passRate', { value: Math.round(metrics.pass_rate * 100) })}</p>
      )}
      {!!Object.keys(metrics.metric_scores ?? {}).length && (
        <>
          <h4 className="font-medium">{t('metricScores')}</h4>
          <ul>
            {Object.entries(metrics.metric_scores ?? {}).map(([name, value]) => (
              <li key={name}>
                {t.has(`metricNames.${name}`) ? t(`metricNames.${name}`) : name}:{' '}
                {t('scorePercent', { value: Math.round(value.score * 100) })}
                {' · '}
                {t('scoredCases', { count: value.evaluated_cases })}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  ) : (
    <p>{t('notRun')}</p>
  )
}

export function ProjectEvaluation({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject')
  const locale = useLocale()
  const { sets, runs, save, start, quality } = useProjectEvaluation(agentId)
  const lifecycleT = useTranslations('agentProject.lifecycle')
  const workspaceT = useTranslations('agentProject.workspace.evaluation')
  const [datasetId, setDatasetId] = useState('')
  const [versionId, setVersionId] = useState('')
  const [editing, setEditing] = useState<EvaluationCase | null>(null)
  const request = useRef<{ selection: string; id: string } | null>(null)
  const dataset = sets.data?.find((set) => set.id === datasetId) ?? sets.data?.[0]
  const selectedVersion = versionId || versions[0]?.id || ''
  const cases = dataset?.cases_json ?? []
  const write = (updated: EvaluationCase[], close = false) =>
    save.mutate(
      { id: dataset?.id, name: dataset?.name ?? t('defaultDataset'), cases: updated },
      {
        onSuccess: (row) => {
          setDatasetId(row.id)
          if (close) setEditing(null)
        },
      },
    )
  const submit = () => {
    if (!dataset) return
    const selection = `${selectedVersion}:${dataset.id}`
    if (request.current?.selection !== selection)
      request.current = { selection, id: crypto.randomUUID() }
    start.mutate(
      { request_id: request.current.id, version_id: selectedVersion, eval_set_id: dataset.id },
      {
        onSuccess: () => {
          request.current = null
        },
      },
    )
  }
  const errorText = (code: string) =>
    t.has(`executionErrors.${code}`) ? t(`executionErrors.${code}`) : t('executionFailed')
  return (
    <SettingsSectionCard title={t('evaluation')} description={t('semanticDescription')}>
      <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
        <p className="font-medium">{t('mockEnvironmentTitle')}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t('mockScope')}</p>
      </div>
      <ProjectSelect
        label={t('evaluationVersion')}
        value={selectedVersion}
        options={versions.map((version) => ({
          value: version.id,
          label: t('version', { number: version.version_number }),
        }))}
        onChange={setVersionId}
      />
      <ProjectEvalPlan
        agentId={agentId}
        versionId={selectedVersion}
        onGenerated={(id) => {
          setDatasetId(id)
          setEditing(null)
        }}
      />
      {sets.isError ? (
        <ErrorState onRetry={() => void sets.refetch()} />
      ) : sets.isPending ? (
        <p role="status">{t('loading')}</p>
      ) : (
        <>
          <section className="mt-5 space-y-4" aria-label={workspaceT('evalSets.title')}>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold">{workspaceT('evalSets.title')}</h3>
                <p className="text-sm text-muted-foreground">
                  {workspaceT('evalSets.description')}
                </p>
              </div>
              {dataset?.frozen ? (
                <span className="moldy-ui-micro rounded-full border border-border px-2 py-1">
                  {workspaceT('evalSets.frozen')}
                </span>
              ) : (
                <span className="moldy-ui-micro rounded-full border border-border px-2 py-1">
                  {workspaceT('evalSets.draft')}
                </span>
              )}
            </div>
          {!!sets.data.length && (
            <ProjectSelect
              label={t('dataset')}
              value={dataset?.id ?? ''}
              options={sets.data.map((set) => ({ value: set.id, label: set.name }))}
              onChange={(id) => {
                setDatasetId(id)
                setEditing(null)
              }}
            />
          )}
          {!cases.length && <p className="my-4">{t('noCases')}</p>}
          {dataset && (
            <div className="my-4 rounded-lg border border-border/70 p-3">
              <dl className="grid gap-3 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-muted-foreground">{workspaceT('evalSets.name')}</dt>
                  <dd className="font-medium">{dataset.name}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{workspaceT('evalSets.caseCount')}</dt>
                  <dd>{cases.length}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{workspaceT('evalSets.qualityStatus')}</dt>
                  <dd>
                    {lifecycleT(`qualityStates.${dataset.quality_report_json?.status ?? 'pending'}`)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{workspaceT('evalSets.source')}</dt>
                  <dd>
                    {cases.some((item) => item.source === 'ai_generated')
                      ? workspaceT('evalSets.sources.aiGenerated')
                      : cases.some((item) => item.source === 'imported')
                        ? workspaceT('evalSets.sources.imported')
                        : workspaceT('evalSets.sources.manual')}
                  </dd>
                </div>
              </dl>
              {dataset.quality_report_json && (
                <div className="mt-3 space-y-1 text-sm">
                  <p>
                    {lifecycleT('qualityScore', {
                      value: Math.round(dataset.quality_report_json.overall_score * 100),
                    })}
                  </p>
                  {dataset.quality_report_json.issues.map((issue) => (
                    <p key={issue}>
                      {lifecycleT.has(`qualityIssues.${issue}`)
                        ? lifecycleT(`qualityIssues.${issue}`)
                        : issue}
                    </p>
                  ))}
                </div>
              )}
              {!dataset.frozen && (
                <Button
                  className="mt-3"
                  variant="outline"
                  disabled={quality.isPending || save.isPending || !!editing || !cases.length}
                  onClick={() => quality.mutate(dataset.id)}
                >
                  {lifecycleT(quality.isPending ? 'checking' : 'qualityCheck')}
                </Button>
              )}
              {quality.isError && <ErrorState />}
            </div>
          )}
          <div className="my-4 space-y-3">
            {cases.map((item) => (
              <article key={item.id} className="rounded-lg border border-border/70 p-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h4 className="font-medium">{item.name}</h4>
                    <p className="mt-1 whitespace-pre-wrap text-sm">{item.input}</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {t('expectedBehavior')}:{' '}
                      {item.expected_behavior
                        ? JSON.stringify(item.expected_behavior)
                        : item.expected.answer || item.expected.exact_answer || t('semanticExpected')}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
                    <span className="rounded-full border px-2 py-1">
                      {item.evaluation_type ?? workspaceT('caseDefaults.evaluationType')}
                    </span>
                    <span className="rounded-full border px-2 py-1">
                      {item.difficulty ?? workspaceT('caseDefaults.difficulty')}
                    </span>
                    <span className="rounded-full border px-2 py-1">
                      {item.source ?? workspaceT('caseDefaults.source')}
                    </span>
                    <span className="rounded-full border px-2 py-1">
                      {item.enabled ? workspaceT('caseDefaults.enabled') : workspaceT('caseDefaults.disabled')}
                    </span>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    disabled={save.isPending || dataset?.frozen}
                    onClick={() => setEditing(item)}
                    aria-label={t('editCaseNamed', { name: item.name })}
                  >
                    {t('editCase')}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={save.isPending || dataset?.frozen}
                    onClick={() =>
                      write(
                        cases.map((value) =>
                          value.id === item.id ? { ...value, enabled: !value.enabled } : value,
                        ),
                      )
                    }
                    aria-label={t('toggleCaseNamed', { name: item.name })}
                  >
                    {item.enabled ? t('disableCase') : t('enableCase')}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={save.isPending || dataset?.frozen}
                    onClick={() => write(cases.filter((value) => value.id !== item.id))}
                    aria-label={t('removeCaseNamed', { name: item.name })}
                  >
                    {t('removeCase')}
                  </Button>
                </div>
              </article>
            ))}
          </div>
          <Button
            variant="outline"
            disabled={save.isPending || dataset?.frozen || cases.length >= 20}
            onClick={() =>
              setEditing({
                id: crypto.randomUUID(),
                name: '',
                input: '',
                context: [],
                expected: { required_tools: [], forbidden_tools: [] },
                tags: [],
                enabled: true,
              })
            }
          >
            {t('addCase')}
          </Button>
          {editing && (
            <ProjectCaseEditor
              key={editing.id}
              initial={editing}
              busy={save.isPending}
              onCancel={() => setEditing(null)}
              onSave={(value) =>
                write(
                  cases.some((item) => item.id === value.id)
                    ? cases.map((item) => (item.id === value.id ? value : item))
                    : [...cases, value],
                  true,
                )
              }
            />
          )}
          {save.isError && <ErrorState />}
          </section>
        </>
      )}
      <div className="my-5 space-y-3">
        <Button
          onClick={submit}
          disabled={
            start.isPending ||
            !selectedVersion ||
            !cases.some((item) => item.enabled) ||
            !!editing ||
            save.isPending ||
            quality.isPending ||
            dataset?.quality_report_json?.status !== 'approved'
          }
        >
          {start.isPending ? t('submitting') : t('runEvaluation')}
        </Button>
        {start.isError && <ErrorState onRetry={submit} />}
      </div>
      <section className="mt-6 space-y-3" aria-label={workspaceT('runs.title')}>
      <div>
        <h3 className="text-base font-semibold">{workspaceT('runs.title')}</h3>
        <p className="text-sm text-muted-foreground">
          {workspaceT('runs.description')}
        </p>
      </div>
      {runs.isError ? (
        <ErrorState onRetry={() => void runs.refetch()} />
      ) : runs.isPending ? (
        <p role="status">{t('loading')}</p>
      ) : !runs.data.length ? (
        <p>{t('noRuns')}</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {runs.data.map((run) => (
            <li key={run.id}>
              <details id={`evaluation-run-${run.id}`}>
                <summary>
                  {t('version', {
                    number:
                      versions.find((version) => version.id === run.version_id)?.version_number ??
                      0,
                  })}{' '}
                  · {t(`runStatuses.${run.status}`)} ·{' '}
                  {formatDisplayDateTime(run.created_at, { locale })}
                </summary>
                <div className="mt-3 space-y-3">
                  <p role="status">{t(`runStatuses.${run.status}`)}</p>
                  <ProjectMetrics metrics={run.metrics_json} />
                  {['completed', 'failed'].includes(run.status) &&
                    run.comparison_json?.eval_spec && (
                      <ProjectOptimization
                        agentId={agentId}
                        run={run}
                        versions={versions}
                        runs={runs.data}
                      />
                    )}
                  {run.error && <p role="alert">{errorText(run.error)}</p>}
                  {run.results_json?.some((result) => result.status !== 'passed') && (
                    <h4 className="font-medium">
                      {t('failedCases', {
                        count: run.results_json.filter((result) => result.status !== 'passed')
                          .length,
                      })}
                    </h4>
                  )}
                  <ul className="space-y-4">
                    {run.results_json
                      ?.toSorted(
                        (a, b) => Number(a.status === 'passed') - Number(b.status === 'passed'),
                      )
                      .map((result) => (
                        <li key={result.case_id} className="space-y-2">
                          <h4 className="font-medium">
                            {result.name} · {t(`caseStatuses.${result.status}`)}
                          </h4>
                          <p className="whitespace-pre-wrap">
                            {t('caseInput')}: {result.input}
                          </p>
                          <p className="whitespace-pre-wrap">
                            {t('output')}: {result.output}
                          </p>
                          {!!result.tool_trace?.length && (
                            <details>
                              <summary>{t('toolTrace')}</summary>
                              <ul className="space-y-2 pt-2 text-sm">
                                {result.tool_trace.map((event, index) => (
                                  <li key={`${event.name}-${event.order ?? index}`} className="rounded border border-border/70 p-2">
                                    <p className="font-medium">
                                      {t('toolOrder', { value: event.order ?? index + 1 })} · {event.name}
                                      {event.latency_ms != null
                                        ? ` · ${event.latency_ms} ms`
                                        : ''}
                                    </p>
                                    <p className="whitespace-pre-wrap break-words">
                                      {t('toolArguments')}: {JSON.stringify(event.arguments ?? {})}
                                    </p>
                                    {event.error ? (
                                      <p className="text-destructive">
                                        {t('toolError')}: {event.error}
                                      </p>
                                    ) : (
                                      <p className="whitespace-pre-wrap break-words">
                                        {t('toolResult')}: {JSON.stringify(event.output)}
                                      </p>
                                    )}
                                  </li>
                                ))}
                              </ul>
                            </details>
                          )}
                          {result.expected?.answer && (
                            <p>
                              {t('expectedBehavior')}: {result.expected.answer}
                            </p>
                          )}
                          <p>{t('latency', { ms: result.latency_ms })}</p>
                          {!!result.tool_calls.length && (
                            <p>
                              {t('toolCalls')}:{' '}
                              {result.tool_calls.map((call) => call.name).join(', ')}
                            </p>
                          )}
                          <ul>
                            {result.assertions.map((assertion, index) => (
                              <li key={index}>
                                {t(`assertions.${assertion.kind}`)} {assertion.target} ·{' '}
                                {assertion.passed ? t('checkPassed') : t('checkFailed')}
                              </li>
                            ))}
                          </ul>
                          {result.metric_scores && (
                            <ul>
                              {Object.entries(result.metric_scores).map(([name, score]) => (
                                <li key={name}>
                                  {t.has(`metricNames.${name}`) ? t(`metricNames.${name}`) : name}:{' '}
                                  {t('scorePercent', { value: Math.round(score.score * 100) })}
                                  {' · '}
                                  {score.method === 'deterministic'
                                    ? t('deterministicReason')
                                    : score.reason}
                                </li>
                              ))}
                            </ul>
                          )}
                          {result.limitations?.map((code) => (
                            <p key={code}>{errorText(code)}</p>
                          ))}
                          {result.error && <p role="alert">{errorText(result.error)}</p>}
                        </li>
                      ))}
                  </ul>
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
      </section>
    </SettingsSectionCard>
  )
}
