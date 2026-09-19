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
import { OptimizationWorkspace } from './optimization-workspace'
import { ProjectNavigation, type ProjectWorkspaceTab } from './project-navigation'

export function ProjectWorkbench({ agentId }: { agentId: string }) {
  const t = useTranslations('agentProject')
  const { project, versions, create, bootstrap } = useAgentProject(agentId)
  const currentVersion = versions.data?.[0]
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
                {activeTab === 'overview' ? (
                  <LifecycleOverview
                    agentId={agentId}
                    project={project.data}
                    versions={versions.data}
                    onNavigate={setActiveTab}
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
                    <ProjectEvaluation agentId={agentId} versions={versions.data} />
                    <ProjectEvaluationReport agentId={agentId} versions={versions.data} />
                  </div>
                ) : null}
                {activeTab === 'optimization' ? (
                  <OptimizationWorkspace agentId={agentId} versions={versions.data} />
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
                        {(project.data.requirements_json?.bootstrap?.error || bootstrap.isError) && (
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
