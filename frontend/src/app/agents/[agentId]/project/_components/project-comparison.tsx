'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import type { AgentProjectVersionSummary } from '../_lib/agent-project-types'
import { useProjectComparison } from '../_hooks/use-project-evaluation'
import { ProjectSelect } from './project-select'
import { ProjectMetrics } from './project-evaluation'

export function ProjectComparison({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject')
  const [leftId, setLeftId] = useState('')
  const [rightId, setRightId] = useState('')
  const left = leftId || versions[1]?.id || ''
  const right = rightId || versions[0]?.id || ''
  const comparison = useProjectComparison(agentId, left, right)
  const options = versions.map((version) => ({
    value: version.id,
    label: t('version', { number: version.version_number }),
  }))
  return (
    <SettingsSectionCard title={t('compareVersions')}>
      {versions.length < 2 ? (
        <p>{t('needTwoVersions')}</p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <ProjectSelect
              label={t('leftVersion')}
              value={left}
              options={options}
              onChange={setLeftId}
            />
            <ProjectSelect
              label={t('rightVersion')}
              value={right}
              options={options}
              onChange={setRightId}
            />
          </div>
          {left === right ? (
            <p>{t('chooseDifferentVersions')}</p>
          ) : comparison.isError ? (
            <ErrorState onRetry={() => void comparison.refetch()} />
          ) : comparison.isPending ? (
            <p role="status">{t('loading')}</p>
          ) : (
            <div className="mt-4 space-y-4">
              {!comparison.data.changes.length && <p>{t('noChanges')}</p>}
              <ul className="space-y-3">
                {comparison.data.changes.map((change) => (
                  <li key={change.field}>
                    <p className="font-medium">{t(`configFields.${change.field}`)}</p>
                    {change.added ? (
                      <p>
                        {t('linkChanges', {
                          added: change.added.length,
                          removed: change.removed?.length ?? 0,
                          changed: change.changed?.length ?? 0,
                        })}
                      </p>
                    ) : (
                      <p>{t('configurationChanged')}</p>
                    )}
                    {change.field === 'system_prompt' ? (
                      <div className="grid gap-4 sm:grid-cols-2">
                        <p className="whitespace-pre-wrap">{String(change.before ?? '')}</p>
                        <p className="whitespace-pre-wrap">{String(change.after ?? '')}</p>
                      </div>
                    ) : (
                      <details>
                        <summary>{t('changeDetail')}</summary>
                        <div className="grid gap-4 sm:grid-cols-2">
                          <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
                            {JSON.stringify(change.before, null, 2)}
                          </pre>
                          <pre className="overflow-auto whitespace-pre-wrap break-all text-sm">
                            {JSON.stringify(change.after, null, 2)}
                          </pre>
                        </div>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted-foreground">
                {comparison.data.same_dataset ? t('sameDataset') : t('differentDatasets')}
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {comparison.data.evaluations.map((result, index) => (
                  <div key={index}>
                    <h3 className="font-medium">
                      {index === 0 ? t('leftVersion') : t('rightVersion')}
                    </h3>
                    <ProjectMetrics metrics={result?.metrics ?? null} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </SettingsSectionCard>
  )
}
