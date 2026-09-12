'use client'

import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { PageShell } from '@/components/shared/page-shell'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { Button } from '@/components/ui/button'
import { useAgentProject } from '../_hooks/use-agent-project'
import { ProjectVersions } from './project-versions'
import { ProjectEvaluation } from './project-evaluation'
import { ProjectComparison } from './project-comparison'

export function ProjectWorkbench({ agentId }: { agentId: string }) {
  const t = useTranslations('agentProject')
  const { project, versions, create } = useAgentProject(agentId)
  const currentVersion = versions.data?.[0]

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
                <dd>{currentVersion ? t(`statuses.${currentVersion.status}`) : t('loading')}</dd>
              </div>
            </dl>
          </SettingsSectionCard>
          {versions.isError ? (
            <ErrorState onRetry={() => void versions.refetch()} />
          ) : versions.isPending ? (
            <p role="status">{t('loading')}</p>
          ) : (
            <>
              <ProjectVersions agentId={agentId} versions={versions.data} />
              <ProjectEvaluation agentId={agentId} versions={versions.data} />
              <ProjectComparison agentId={agentId} versions={versions.data} />
            </>
          )}
        </>
      )}
    </PageShell>
  )
}
