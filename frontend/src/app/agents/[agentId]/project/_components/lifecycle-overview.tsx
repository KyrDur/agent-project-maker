'use client'

import { useMemo } from 'react'
import { useLocale, useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { useAgentRuntimeReadiness } from '@/lib/hooks/use-agents'
import { useSystemLlmReadiness } from '@/lib/hooks/use-system-llm-settings'
import { formatDisplayDateTime, formatDisplayNumber } from '@/lib/utils/display-format'
import { useEvaluationReports, useProjectEvaluation } from '../_hooks/use-project-evaluation'
import type {
  AgentProject,
  AgentProjectVersionSummary,
  EvaluationReport,
  EvaluationRun,
  EvaluationSet,
  OptimizationProposal,
} from '../_lib/agent-project-types'
import type { ProjectWorkspaceTab } from './project-navigation'
import { ProjectResults } from './project-results'

type LifecycleOverviewProps = {
  readonly agentId: string
  readonly project: AgentProject
  readonly versions: AgentProjectVersionSummary[]
  readonly onNavigate: (tab: ProjectWorkspaceTab) => void
}

type StepState = 'completed' | 'current' | 'pending'

function percent(value: number | null | undefined, locale: string, fallback: string): string {
  if (value == null) return fallback
  return `${formatDisplayNumber(value * 100, { locale, maximumFractionDigits: 1 })}%`
}

function versionLabel(version: AgentProjectVersionSummary | undefined, fallback: string): string {
  return version ? `V${version.version_number}` : fallback
}

function sortRunsNewestFirst(runs: readonly EvaluationRun[]): EvaluationRun[] {
  return [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))
}

function sortReportsNewestFirst(reports: readonly EvaluationReport[]): EvaluationReport[] {
  return [...reports].sort((a, b) => b.created_at.localeCompare(a.created_at))
}

function proposalsFromRuns(runs: readonly EvaluationRun[]): OptimizationProposal[] {
  return runs.flatMap((run) => run.comparison_json?.proposals ?? [])
}

function hasAcceptedProposal(proposals: readonly OptimizationProposal[]): boolean {
  return proposals.some((proposal) => proposal.status === 'accepted')
}

function bestReportForScope(reports: readonly EvaluationReport[]): EvaluationReport | undefined {
  const scored = reports.find((report) => report.score != null && report.comparison_key)
  if (!scored?.comparison_key) return undefined
  const comparable = reports.filter((report) => report.comparison_key === scored.comparison_key)
  return comparable
    .filter((report) => report.score != null)
    .toSorted((a, b) => (b.score ?? 0) - (a.score ?? 0) || a.created_at.localeCompare(b.created_at))
    [0]
}

function improvementForBest(
  best: EvaluationReport | undefined,
  reports: readonly EvaluationReport[],
): number | null {
  if (!best?.comparison_key || best.score == null) return null
  const baseline = reports
    .filter(
      (report) =>
        report.evaluation_run_id !== best.evaluation_run_id &&
        report.comparison_key === best.comparison_key &&
        report.score != null,
    )
    .toSorted((a, b) => a.created_at.localeCompare(b.created_at))[0]
  if (!baseline?.score && baseline?.score !== 0) return null
  return (best.score - baseline.score) * 100
}

function lifecycleSteps({
  project,
  versions,
  sets,
  runs,
  reports,
  proposals,
}: {
  project: AgentProject
  versions: readonly AgentProjectVersionSummary[]
  sets: readonly EvaluationSet[]
  runs: readonly EvaluationRun[]
  reports: readonly EvaluationReport[]
  proposals: readonly OptimizationProposal[]
}): { key: string; state: StepState }[] {
  const hasSpec = Boolean(project.eval_spec_json)
  const hasSet = sets.length > 0
  const hasUsableSet = sets.some((set) => set.cases_json.some((item) => item.enabled))
  const hasApprovedSet = sets.some((set) => set.quality_report_json?.status === 'approved')
  const hasFrozenSet = sets.some((set) => set.frozen)
  const hasRunningEvaluation = runs.some(
    (run) =>
      (run.status === 'pending' || run.status === 'running') &&
      !run.comparison_json?.regression,
  )
  const hasEvaluation =
    reports.some((report) => report.score != null) ||
    runs.some((run) => run.status === 'completed' && !run.comparison_json?.regression)
  const hasFailedCases =
    reports.some((report) => report.bad_case_count > 0) ||
    runs.some((run) => run.results_json?.some((result) => result.status !== 'passed'))
  const hasOptimization = proposals.length > 0 || runs.some((run) => run.comparison_json?.analysis)
  const hasPendingProposal = proposals.some((proposal) => proposal.status === 'pending')
  const acceptedProposal = proposals.find((proposal) => proposal.status === 'accepted')
  const hasV2 = Boolean(acceptedProposal?.version_id)
  const hasRunningRegression = runs.some(
    (run) =>
      (run.status === 'pending' || run.status === 'running') &&
      Boolean(run.comparison_json?.regression),
  )
  const hasRegression = runs.some(
    (run) => run.status === 'completed' && Boolean(run.comparison_json?.regression),
  )
  const hasComparableReports = reports.some((report) => report.comparison_key)

  return [
    {
      key: 'v1Ready',
      state: versions.length ? 'completed' : 'current',
    },
    {
      key: 'generatorAnalyzing',
      state: hasSpec ? 'completed' : versions.length ? 'current' : 'pending',
    },
    {
      key: 'focusCheckpoint',
      state: hasSet ? 'completed' : hasSpec ? 'current' : 'pending',
    },
    {
      key: 'benchmarkGenerating',
      state: hasUsableSet ? 'completed' : hasSpec ? 'current' : 'pending',
    },
    {
      key: 'benchmarkFrozen',
      state: hasFrozenSet ? 'completed' : hasApprovedSet ? 'current' : 'pending',
    },
    {
      key: 'evaluationRunning',
      state: hasEvaluation ? 'completed' : hasRunningEvaluation ? 'current' : 'pending',
    },
    {
      key: 'resultsBadCases',
      state: hasEvaluation ? 'completed' : hasRunningEvaluation ? 'current' : 'pending',
    },
    {
      key: 'optimizationProposals',
      state: hasOptimization ? 'completed' : hasFailedCases ? 'current' : 'pending',
    },
    {
      key: 'optimizationDecision',
      state: hasAcceptedProposal(proposals) ? 'completed' : hasPendingProposal ? 'current' : 'pending',
    },
    {
      key: 'v2Generation',
      state: hasV2 ? 'completed' : hasAcceptedProposal(proposals) ? 'current' : 'pending',
    },
    {
      key: 'regressionEvaluation',
      state: hasRegression ? 'completed' : hasRunningRegression || hasV2 ? 'current' : 'pending',
    },
    {
      key: 'comparisonBestVersion',
      state: hasRegression && hasComparableReports ? 'completed' : hasRegression ? 'current' : 'pending',
    },
  ]
}

function nextAction({
  project,
  sets,
  runs,
  reports,
  proposals,
}: {
  project: AgentProject
  sets: readonly EvaluationSet[]
  runs: readonly EvaluationRun[]
  reports: readonly EvaluationReport[]
  proposals: readonly OptimizationProposal[]
}): { key: string; tab: ProjectWorkspaceTab } {
  const hasSet = sets.length > 0
  const hasEnabledCases = sets.some((set) => set.cases_json.some((item) => item.enabled))
  const uncheckedSet = sets.find((set) => set.cases_json.length && !set.quality_report_json)
  const hasCompletedEvaluation = reports.some((report) => report.score != null)
  const hasBadCases = reports.some((report) => report.bad_case_count > 0)
  const acceptedWithoutRegression = proposals.some((proposal) => proposal.status === 'accepted') &&
    !runs.some((run) => run.comparison_json?.regression)

  if (!hasSet) {
    if (project.eval_spec_json) {
      return {
        key: 'chooseEvaluationFocus',
        tab: 'evaluation',
      }
    }
    return {
      key: 'generateEvalSet',
      tab: 'evaluation',
    }
  }
  if (uncheckedSet) {
    return {
      key: 'qualityCheck',
      tab: 'evaluation',
    }
  }
  if (!hasEnabledCases || !hasCompletedEvaluation) {
    return {
      key: 'runEvaluation',
      tab: 'evaluation',
    }
  }
  if (hasBadCases && !proposals.length) {
    return {
      key: 'analyzeBadCases',
      tab: 'optimization',
    }
  }
  if (acceptedWithoutRegression) {
    return {
      key: 'runRegression',
      tab: 'optimization',
    }
  }
  return {
    key: 'compareVersions',
    tab: 'versions',
  }
}

export function LifecycleOverview({
  agentId,
  project,
  versions,
  onNavigate,
}: LifecycleOverviewProps) {
  const t = useTranslations('agentProject')
  const workspaceT = useTranslations('agentProject.workspace.overview')
  const locale = useLocale()
  const evaluation = useProjectEvaluation(agentId)
  const reportsQuery = useEvaluationReports(agentId)
  const runtimeReadiness = useAgentRuntimeReadiness(agentId)
  const systemModels = useSystemLlmReadiness()
  const sets = evaluation.sets.data ?? []
  const runs = useMemo(() => sortRunsNewestFirst(evaluation.runs.data ?? []), [evaluation.runs.data])
  const reports = useMemo(
    () => sortReportsNewestFirst(reportsQuery.data?.reports ?? []),
    [reportsQuery.data?.reports],
  )
  const latestRun = runs[0]
  const latestReport = reports.find((report) => report.evaluation_run_id === latestRun?.id) ?? reports[0]
  const latestSet = sets.find((set) => set.id === latestRun?.eval_set_id)
  const proposals = useMemo(() => proposalsFromRuns(runs), [runs])
  const latestProposal = proposals.toSorted((a, b) => b.created_at.localeCompare(a.created_at))[0]
  const best = bestReportForScope(reports)
  const bestVersion = versions.find((version) => version.id === best?.version_id)
  const currentVersion = versions[0]
  const improvement = improvementForBest(best, reports)
  const steps = lifecycleSteps({ project, versions, sets, runs, reports, proposals })
  const action = nextAction({ project, sets, runs, reports, proposals })
  const failedCases =
    latestRun?.results_json?.filter((result) => result.status !== 'passed').length ??
    latestReport?.bad_case_count ??
    null
  const noData = workspaceT('noData')
  const noVersion = workspaceT('noVersion')
  const platformRoles = useMemo(
    () => systemModels.data ?? [],
    [systemModels.data],
  )
  const platformReady =
    platformRoles.length > 0 && platformRoles.every((setting) => setting.configured)
  const runtimeModel = runtimeReadiness.data?.model
  const runtimeCredential = runtimeReadiness.data?.credential

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-border/70 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              {workspaceT('eyebrow')}
            </p>
            <h2 className="mt-1 text-2xl font-semibold">{project.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {workspaceT('narrative')}
            </p>
          </div>
          <div className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <p className="text-muted-foreground">{workspaceT('currentVersion')}</p>
              <p className="text-lg font-semibold">{versionLabel(currentVersion, noVersion)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{workspaceT('bestVersion')}</p>
              <p className="text-lg font-semibold">{versionLabel(bestVersion, noVersion)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{workspaceT('latestEvaluation')}</p>
              <p className="text-lg font-semibold">{percent(latestReport?.score, locale, noData)}</p>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-border/70 p-4">
        <h3 className="text-sm font-semibold">{workspaceT('progressTitle')}</h3>
        <div className="mt-4 grid gap-3 md:grid-cols-4 xl:grid-cols-6">
          {steps.map((step, index) => (
            <div key={step.key} className="relative">
              <div className="flex items-center gap-2">
                <span
                  className={
                    step.state === 'completed'
                      ? 'size-2 rounded-full bg-emerald-500'
                      : step.state === 'current'
                        ? 'size-2 rounded-full bg-primary'
                        : 'size-2 rounded-full bg-muted-foreground/30'
                  }
                />
                <span className="text-sm font-medium">{workspaceT(`steps.${step.key}`)}</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {workspaceT(`stepStates.${step.state}`)}
              </p>
              {index < steps.length - 1 ? (
                <div className="mt-3 hidden h-px bg-border md:block" aria-hidden="true" />
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <SettingsSectionCard
          title={workspaceT('aiReadiness.pipeline.title')}
          actions={
            <span
              className={
                platformReady
                  ? 'rounded-full bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-700'
                  : 'rounded-full bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700'
              }
            >
              {workspaceT(
                platformReady ? 'aiReadiness.status.ready' : 'aiReadiness.status.needsSetup',
              )}
            </span>
          }
        >
          <dl className="grid gap-3 text-sm">
            {platformRoles.map((role) => (
              <div key={role.role} className="flex items-center justify-between gap-3">
                <dt className="text-muted-foreground">
                  {workspaceT(`aiReadiness.pipeline.roles.${role.role}`)}
                </dt>
                <dd className="text-right">
                  {role.configured && role.provider && role.model_name
                    ? `${role.provider} · ${role.model_name}`
                    : workspaceT('aiReadiness.status.notConfigured')}
                </dd>
              </div>
            ))}
          </dl>
        </SettingsSectionCard>

        <SettingsSectionCard
          title={workspaceT('aiReadiness.runtime.title')}
          actions={
            <span
              className={
                runtimeReadiness.data?.ready
                  ? 'rounded-full bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-700'
                  : 'rounded-full bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700'
              }
            >
              {workspaceT(
                runtimeReadiness.data?.ready
                  ? 'aiReadiness.status.ready'
                  : 'aiReadiness.status.needsSetup',
              )}
            </span>
          }
        >
          <dl className="grid gap-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">{workspaceT('aiReadiness.runtime.model')}</dt>
              <dd className="text-right">
                {runtimeModel
                  ? `${runtimeModel.provider} · ${runtimeModel.display_name || runtimeModel.model_name}`
                  : workspaceT('aiReadiness.status.notConfigured')}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">
                {workspaceT('aiReadiness.runtime.credential')}
              </dt>
              <dd className="text-right">
                {runtimeCredential
                  ? `${runtimeCredential.name} (${workspaceT('aiReadiness.runtime.masked')})`
                  : workspaceT('aiReadiness.status.notConfigured')}
              </dd>
            </div>
          </dl>
        </SettingsSectionCard>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <SettingsSectionCard title={workspaceT('bestCard.title')}>
          {best && bestVersion ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-3xl font-semibold">{versionLabel(bestVersion, noVersion)}</p>
                  <p className="text-sm text-muted-foreground">{workspaceT('bestCard.badge')}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">
                    {workspaceT('bestCard.overallScore')}
                  </p>
                  <p className="text-3xl font-semibold">{percent(best.score, locale, noData)}</p>
                </div>
              </div>
              <p className="text-sm">{t('lifecycle.bestReason')}</p>
              <p className="text-sm text-muted-foreground">{t('evaluationReport.dataset', { id: best.eval_set_id })}</p>
              <p className="text-sm">
                {improvement == null
                  ? workspaceT('bestCard.noPreviousComparable')
                  : workspaceT('bestCard.improvement', {
                      value: `${improvement >= 0 ? '+' : ''}${formatDisplayNumber(improvement, {
                        locale,
                        maximumFractionDigits: 1,
                      })}`,
                    })}
              </p>
              <Button variant="outline" onClick={() => onNavigate('versions')}>
                {workspaceT('bestCard.viewVersions')}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {workspaceT('bestCard.empty')}
              </p>
              <Button variant="outline" onClick={() => onNavigate('evaluation')}>
                {workspaceT('bestCard.runEvaluation')}
              </Button>
            </div>
          )}
        </SettingsSectionCard>

        <SettingsSectionCard title={workspaceT('latestCard.title')}>
          {latestRun || latestReport ? (
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">{workspaceT('latestCard.version')}</dt>
                <dd>{versionLabel(versions.find((version) => version.id === (latestRun?.version_id ?? latestReport?.version_id)), noVersion)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{workspaceT('latestCard.score')}</dt>
                <dd>{percent(latestReport?.score ?? latestRun?.metrics_json?.pass_rate, locale, noData)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{workspaceT('latestCard.cases')}</dt>
                <dd>{latestRun?.metrics_json?.total ?? latestReport?.total ?? noData}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{workspaceT('latestCard.failedCases')}</dt>
                <dd>{failedCases ?? noData}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">{workspaceT('latestCard.evaluatedWith')}</dt>
                <dd>{latestSet?.name ?? latestRun?.eval_set_id ?? latestReport?.eval_set_id ?? noData}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">{workspaceT('latestCard.evaluationTime')}</dt>
                <dd>
                  {latestRun?.completed_at || latestRun?.created_at || latestReport?.created_at
                    ? formatDisplayDateTime(
                        latestRun?.completed_at ?? latestRun?.created_at ?? latestReport?.created_at ?? '',
                        { locale },
                      )
                    : noData}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">{workspaceT('latestCard.empty')}</p>
          )}
          <Button className="mt-4" variant="outline" onClick={() => onNavigate('evaluation')}>
            {workspaceT('latestCard.viewEvaluation')}
          </Button>
        </SettingsSectionCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1fr]">
        <SettingsSectionCard title={workspaceT('optimizationCard.title')}>
          {latestProposal ? (
            <div className="space-y-3 text-sm">
              <p>
                <span className="text-muted-foreground">{workspaceT('optimizationCard.status')}</span>
                {t(`lifecycle.statuses.${latestProposal.status}`)}
              </p>
              <p>
                <span className="text-muted-foreground">{workspaceT('optimizationCard.detectedIssue')}</span>
                {latestProposal.failure_patterns[0]?.category ?? workspaceT('optimizationCard.uncategorized')}
              </p>
              <p>
                <span className="text-muted-foreground">{workspaceT('optimizationCard.rootCause')}</span>
                {latestProposal.failure_patterns[0]?.root_cause ?? workspaceT('optimizationCard.noRootCause')}
              </p>
              <Button variant="outline" onClick={() => onNavigate('optimization')}>
                {workspaceT('optimizationCard.review')}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">{workspaceT('optimizationCard.empty')}</p>
              <Button variant="outline" onClick={() => onNavigate('optimization')}>
                {workspaceT('optimizationCard.view')}
              </Button>
            </div>
          )}
        </SettingsSectionCard>

        <SettingsSectionCard
          title={workspaceT('nextAction.title')}
          actions={
            <Button onClick={() => onNavigate(action.tab)}>
              {workspaceT(`nextAction.${action.key}.label`)}
            </Button>
          }
        >
          <p className="text-sm text-muted-foreground">
            {workspaceT(`nextAction.${action.key}.detail`)}
          </p>
        </SettingsSectionCard>
      </div>

      {(evaluation.sets.isError || evaluation.runs.isError || reportsQuery.isError) && <ErrorState />}
      <ProjectResults agentId={agentId} />
    </div>
  )
}
