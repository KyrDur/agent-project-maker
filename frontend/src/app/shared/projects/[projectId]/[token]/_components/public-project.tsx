'use client'

import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { readPublicProject } from '../_lib/public-project-api'
import { ErrorState } from '@/components/shared/error-state'

const publicProjectKey = (id: string, token: string) => ['public-project', id, token] as const

export function PublicProject({ projectId, token }: { projectId: string; token: string }) {
  const t = useTranslations('agentProject.portfolio')
  const report = useQuery({
    queryKey: publicProjectKey(projectId, token),
    queryFn: () => readPublicProject(projectId, token),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: 30000,
  })
  return (
    <main className="mx-auto max-w-4xl space-y-6 p-6">
      <h1 className="text-2xl font-semibold">{t('publicTitle')}</h1>
      {report.isPending ? (
        <p role="status">{t('loading')}</p>
      ) : report.isError ? (
        <ErrorState title={t('shareUnavailable')} />
      ) : (
        report.data.sections.map((section) => (
          <section key={section.title} className="space-y-2">
            <h2 className="text-lg font-medium">{section.title}</h2>
            <pre className="whitespace-pre-wrap break-words text-sm">{section.body}</pre>
          </section>
        ))
      )}
    </main>
  )
}
