'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { PageShell } from '@/components/shared/page-shell'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { Button } from '@/components/ui/button'
import { useAgentProject } from '../_hooks/use-agent-project'
import { ProjectVersions } from './project-versions'
import { ProjectEvaluation } from './project-evaluation'
import { ProjectComparison } from './project-comparison'
import { ProjectEvaluationReport } from './project-evaluation-report'
import { LifecycleOverview } from './lifecycle-overview'
import { GuidedEvaluation } from './guided-evaluation'
import { GuidedOptimization } from './guided-optimization'
import { ProjectResults } from './project-results'
import { ProjectInterview } from './project-interview'
import { ProjectReliability } from './project-reliability'
import { ProjectIterationJournal } from './project-iteration-journal'
import { OptimizationWorkspace } from './optimization-workspace'
import { ProjectNavigation, type ProjectWorkspaceTab } from './project-navigation'

export function ProjectWorkbench({ agentId }: { agentId: string }) {
  const t = useTranslations('agentProject')
  const guided = useTranslations('agentProject.guided')
  const { project, versions, create, bootstrap } = useAgentProject(agentId)
  const [selectedVersion, setSelectedVersion] = useState('')
  const currentVersion =
    versions.data?.find((v) => v.id === selectedVersion) ??
    versions.data?.find((v) => v.status === 'accepted') ??
    versions.data?.[0]
  const versionId = currentVersion?.id ?? ''
  const [advancedTests, setAdvancedTests] = useState(false)
  const [advancedImprovements, setAdvancedImprovements] = useState(false)
  const bootstrapError = project.data?.requirements_json?.bootstrap?.error
  const [activeTab, setActiveTab] = useState<ProjectWorkspaceTab>('overview')

  return (
    <PageShell
      title={t('title')}
      description={t('description')}
      action={
        <Button variant="outline" render={<Link href={`/agents/${agentId}/settings`} />}>
          {t('backToSettings')}
        </Button>
      }
      isError={project.isError}
      onRetry={() => void project.refetch()}
    >
      {project.isPending ? (
        <p role="status">{t('loading')}</p>
      ) : !project.data ? (
        <div className="space-y-4">
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? t('creating') : t('create')}
          </Button>
          {create.isError && <ErrorState title={t('createError')} />}
        </div>
      ) : (
        <>
          {versions.isError ? (
            <ErrorState onRetry={() => void versions.refetch()} />
          ) : versions.isPending ? (
            <p role="status">{t('loading')}</p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border/70 bg-background">
              <ProjectNavigation active={activeTab} onChange={setActiveTab} />
              <div className="p-4 sm:p-5">
                <label className="mb-5 flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground">{guided('selectedVersion')}</span>
                  <select
                    className="rounded-md border border-border bg-background p-2"
                    value={versionId}
                    onChange={(e) => setSelectedVersion(e.target.value)}
                  >
                    {versions.data.map((v) => (
                      <option key={v.id} value={v.id}>
                        {t('version', { number: v.version_number })}
                      </option>
                    ))}
                  </select>
                </label>
                {activeTab === 'overview' ? (
                  <LifecycleOverview
                    agentId={agentId}
                    project={project.data}
                    versions={versions.data}
                    onNavigate={setActiveTab}
                    versionId={versionId}
                  />
                ) : null}
                {activeTab === 'versions' ? (
                  <div className="space-y-5">
                    <ProjectVersions agentId={agentId} versions={versions.data} />
                    <ProjectComparison agentId={agentId} versions={versions.data} />
                  </div>
                ) : null}
                {activeTab === 'evaluation' ? (
                  <div className="space-y-5">
                    {!advancedTests && (
                      <GuidedEvaluation
                        key={versionId}
                        agentId={agentId}
                        versionId={versionId}
                        onImprove={() => setActiveTab('optimization')}
                      />
                    )}
                    <details onToggle={(e) => setAdvancedTests(e.currentTarget.open)}>
                      <summary className="cursor-pointer">{guided('advancedTests')}</summary>
                      {advancedTests && (
                        <div className="mt-4 space-y-5">
                          <ProjectEvaluation agentId={agentId} versions={versions.data} />
                          <ProjectEvaluationReport agentId={agentId} versions={versions.data} />
                        </div>
                      )}
                    </details>
                  </div>
                ) : null}
                {activeTab === 'optimization' ? (
                  <div className="space-y-5">
                    {!advancedImprovements && (
                      <GuidedOptimization
                        key={versionId}
                        agentId={agentId}
                        versionId={versionId}
                        versions={versions.data}
                      />
                    )}
                    <details onToggle={(e) => setAdvancedImprovements(e.currentTarget.open)}>
                      <summary className="cursor-pointer">{guided('advancedImprovements')}</summary>
                      {advancedImprovements && (
                        <OptimizationWorkspace agentId={agentId} versions={versions.data} />
                      )}
                    </details>
                  </div>
                ) : null}
                {activeTab === 'results' ? (
                  <div className="space-y-6">
                    <ProjectIterationJournal agentId={agentId} versions={versions.data} />
                    <ProjectReliability
                      key={versionId}
                      agentId={agentId}
                      versionId={versionId}
                      versions={versions.data}
                    />
                    <ProjectInterview
                      key={`interview:${versionId}`}
                      agentId={agentId}
                      versionId={versionId}
                    />
                    <details>
                      <summary className="cursor-pointer">{guided('exportMaterials')}</summary>
                      <div className="mt-4">
                        <ProjectResults agentId={agentId} />
                      </div>
                    </details>
                  </div>
                ) : null}
                {activeTab === 'settings' ? (
                  <div className="space-y-5">
                    {project.data.builder_session_id && (
                      <SettingsSectionCard title={t('bootstrap.title')}>
                        <p>{t('bootstrap.steps')}</p>
                        <p role="status">
                          {t('bootstrap.current', {
                            stage: t(
                              `bootstrap.stages.${project.data.requirements_json?.bootstrap?.stage ?? 'v1'}`,
                            ),
                          })}
                        </p>
                        {(project.data.requirements_json?.bootstrap?.error ||
                          bootstrap.isError) && (
                          <div role="alert" className="space-y-2">
                            <p>{t('bootstrap.blocked')}</p>
                            <p>
                              {bootstrapError && t.has(`executionErrors.${bootstrapError}`)
                                ? t(`executionErrors.${bootstrapError}`)
                                : t('executionErrors.evaluation_execution_failed')}
                            </p>
                            <Link className="underline" href="/credentials">
                              {t('bootstrap.credentials')}
                            </Link>
                            {' · '}
                            <Link className="underline" href="/models">
                              {t('bootstrap.models')}
                            </Link>
                            <Button
                              onClick={() => bootstrap.mutate()}
                              disabled={bootstrap.isPending}
                            >
                              {t('bootstrap.retry')}
                            </Button>
                          </div>
                        )}
                      </SettingsSectionCard>
                    )}
                    <SettingsSectionCard title={t('project')}>
                      <dl className="grid gap-4 sm:grid-cols-2">
                        <div>
                          <dt className="text-sm text-muted-foreground">{t('project')}</dt>
                          <dd>{project.data.title}</dd>
                        </div>
                        <div>
                          <dt className="text-sm text-muted-foreground">{t('currentVersion')}</dt>
                          <dd>
                            {currentVersion
                              ? t('version', { number: currentVersion.version_number })
                              : t('loading')}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-sm text-muted-foreground">{t('status')}</dt>
                          <dd>
                            {currentVersion ? t(`statuses.${currentVersion.status}`) : t('loading')}
                          </dd>
                        </div>
                      </dl>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          render={<Link href={`/agents/${agentId}/settings`} />}
                        >
                          {t('backToSettings')}
                        </Button>
                      </div>
                    </SettingsSectionCard>
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </>
      )}
    </PageShell>
  )
}
