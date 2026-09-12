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
import { ProjectCaseEditor } from './project-case-editor'

export function ProjectMetrics({ metrics }: { metrics: EvaluationMetrics | null }) {
  const t = useTranslations('agentProject')
  return metrics ? (
    <p>
      {t('metrics', {
        total: metrics.total,
        passed: metrics.passed ?? 0,
        failed: metrics.failed ?? 0,
        errored: metrics.errored ?? 0,
      })}
    </p>
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
  const { sets, runs, save, start } = useProjectEvaluation(agentId)
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
    <SettingsSectionCard title={t('evaluation')} description={t('structuralOnly')}>
      <p className="mb-4 text-sm text-muted-foreground">{t('executionScope')}</p>
      {sets.isError ? (
        <ErrorState onRetry={() => void sets.refetch()} />
      ) : sets.isPending ? (
        <p role="status">{t('loading')}</p>
      ) : (
        <>
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
          <ul className="my-4 space-y-3">
            {cases.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2">
                <span>{item.name}</span>
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
              </li>
            ))}
          </ul>
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
        </>
      )}
      <div className="my-5 space-y-3">
        <ProjectSelect
          label={t('evaluationVersion')}
          value={selectedVersion}
          options={versions.map((version) => ({
            value: version.id,
            label: t('version', { number: version.version_number }),
          }))}
          onChange={setVersionId}
        />
        <Button
          onClick={submit}
          disabled={
            start.isPending || !selectedVersion || !cases.some((item) => item.enabled) || !!editing
          }
        >
          {start.isPending ? t('submitting') : t('runEvaluation')}
        </Button>
        {start.isError && <ErrorState onRetry={submit} />}
      </div>
      <h3 className="font-medium">{t('runHistory')}</h3>
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
              <details>
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
                  {run.error && <p role="alert">{errorText(run.error)}</p>}
                  <ul className="space-y-4">
                    {run.results_json?.map((result) => (
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
    </SettingsSectionCard>
  )
}
