'use client'

import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { useTranslations } from 'next-intl'
import { useProjectEvaluation } from '../_hooks/use-project-evaluation'
import type { AgentProjectVersionSummary, EvaluationRun } from '../_lib/agent-project-types'
import { ProjectOptimization } from './project-optimization'

function sortNewest(runs: readonly EvaluationRun[]): EvaluationRun[] {
  return [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))
}

function needsOptimization(run: EvaluationRun): boolean {
  return Boolean(
    run.results_json?.some((item) => item.status !== 'passed') ||
    run.bad_cases_json?.length ||
    run.comparison_json?.analysis ||
    run.comparison_json?.proposals?.length,
  )
}

export function OptimizationWorkspace({
  agentId,
  versions,
}: {
  readonly agentId: string
  readonly versions: AgentProjectVersionSummary[]
}) {
  const workspaceT = useTranslations('agentProject.workspace.optimization')
  const projectT = useTranslations('agentProject')
  const evaluation = useProjectEvaluation(agentId)
  const runs = useMemo(() => sortNewest(evaluation.runs.data ?? []), [evaluation.runs.data])
  const candidates = runs.filter(needsOptimization)
  const runNumbers = new Map<string, number>()
  const countsByVersion = new Map<string, number>()
  for (const run of [...runs].reverse()) {
    const number = (countsByVersion.get(run.version_id) ?? 0) + 1
    countsByVersion.set(run.version_id, number)
    runNumbers.set(run.id, number)
  }
  const runLabel = (run: EvaluationRun) => {
    const number = runNumbers.get(run.id) ?? 1
    const version = versions.find((item) => item.id === run.version_id)
    const evaluationLabel = workspaceT('runNumber', { number })
    return version
      ? `${projectT('version', { number: version.version_number })} · ${evaluationLabel}`
      : evaluationLabel
  }
  const [selectedRunId, setSelectedRunId] = useState('')
  const selected = candidates.find((run) => run.id === selectedRunId) ?? candidates[0]

  if (evaluation.runs.isPending) {
    return <p role="status">{workspaceT('loading')}</p>
  }
  if (evaluation.runs.isError) {
    return <ErrorState onRetry={() => void evaluation.runs.refetch()} />
  }

  return (
    <div className="space-y-5">
      <SettingsSectionCard title={workspaceT('title')} description={workspaceT('description')}>
        {candidates.length ? (
          <div className="flex flex-wrap gap-2">
            {candidates.map((run) => (
              <Button
                key={run.id}
                type="button"
                variant={selected?.id === run.id ? 'secondary' : 'outline'}
                onClick={() => setSelectedRunId(run.id)}
              >
                {runLabel(run)}
              </Button>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{workspaceT('empty')}</p>
        )}
      </SettingsSectionCard>

      {selected ? (
        <ProjectOptimization agentId={agentId} run={selected} versions={versions} runs={runs} />
      ) : null}
    </div>
  )
}
