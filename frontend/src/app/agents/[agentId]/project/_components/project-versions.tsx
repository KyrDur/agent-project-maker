'use client'

import { useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/shared/error-state'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { formatDisplayDateTime } from '@/lib/utils/display-format'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'
import { useProjectVersions } from '../_hooks/use-project-evaluation'

export function ProjectVersions({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject')
  const locale = useLocale()
  const [selected, setSelected] = useState('')
  const request = useRef<string | null>(null)
  const { create, detail } = useProjectVersions(agentId, selected)
  const submit = () => {
    request.current ??= crypto.randomUUID()
    create.mutate(request.current, {
      onSuccess: () => {
        request.current = null
      },
    })
  }
  return (
    <SettingsSectionCard
      title={t('history')}
      actions={
        <Button onClick={submit} disabled={create.isPending}>
          {create.isPending ? t('creating') : t('createVersion')}
        </Button>
      }
    >
      {create.isError && <ErrorState onRetry={submit} />}
      {create.data && <p role="status">{t(`outcomes.${create.data.outcome}`)}</p>}
      <ul className="space-y-4">
        {versions.map((version) => (
          <li key={version.id} className="space-y-1">
            <Button variant="outline" onClick={() => setSelected(version.id)}>
              {t('version', { number: version.version_number })}
            </Button>
            <p className="text-sm text-muted-foreground">
              {version.status === 'original'
                ? t('originalSnapshot')
                : t(`statuses.${version.status}`)}
            </p>
            <p className="break-all text-sm text-muted-foreground">
              {t('configHash')}: {version.config_hash}
            </p>
            <time className="text-sm text-muted-foreground" dateTime={`${version.created_at}Z`}>
              {formatDisplayDateTime(version.created_at, { locale })}
            </time>
          </li>
        ))}
      </ul>
      {selected &&
        (detail.isError ? (
          <ErrorState onRetry={() => void detail.refetch()} />
        ) : detail.isPending ? (
          <p role="status">{t('loading')}</p>
        ) : (
          <details className="mt-4">
            <summary>{t('snapshotDetail')}</summary>
            <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
              {JSON.stringify(detail.data.snapshot_json, null, 2)}
            </pre>
          </details>
        ))}
    </SettingsSectionCard>
  )
}
