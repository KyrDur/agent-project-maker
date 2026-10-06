'use client'

import { useTranslations } from 'next-intl'
import { EmptyState } from '@/components/shared/empty-state'
import { ResourcePage } from '@/components/shared/resource-layout'

export function ToolsPageClient() {
  const t = useTranslations('tool.page')
  return (
    <ResourcePage title={t('title')} description={t('simulationDescription')}>
      <EmptyState
        iconId="tool"
        title={t('simulationEmptyTitle')}
        description={t('simulationEmptyDescription')}
      />
    </ResourcePage>
  )
}
