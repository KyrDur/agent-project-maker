import type { EvaluationRun, EvaluationSet } from './agent-project-types'

export function newestRuns(runs: EvaluationRun[]) {
  return [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))
}
export function guidanceScope(versionId: string, sets: EvaluationSet[], runs: EvaluationRun[]) {
  const run = newestRuns(runs).find(
    (r) =>
      r.version_id === versionId &&
      r.comparison_json?.purpose !== 'holdout' &&
      !r.comparison_json?.reliability,
  )
  const source = runs.find((r) =>
    r.comparison_json?.proposals?.some(
      (p) => p.status === 'accepted' && p.version_id === versionId,
    ),
  )
  const dataset =
    sets.find((s) => s.id === run?.eval_set_id) ??
    sets.find(
      (s) => s.rubric_json?.version_id === versionId && s.rubric_json?.purpose !== 'holdout',
    )
  return { run, source, dataset }
}
