'use client'

import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { useSystemLlmReadiness } from '@/lib/hooks/use-system-llm-settings'

export function SetupNotice() {
  const t = useTranslations('systemLlm')
  const readiness = useSystemLlmReadiness()
  const missing = readiness.data?.filter((role) => !role.configured)
  if (!missing?.length) return null
  return (
    <div role="status" className="moldy-status-surface moldy-status-warn px-4 py-2 text-sm">
      {t('setupMissing', { count: missing.length })}{' '}
      <Link className="underline" href="/settings/ai-models">{t('personalTitle')}</Link>
    </div>
  )
}
