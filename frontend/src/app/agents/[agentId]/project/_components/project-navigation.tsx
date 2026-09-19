'use client'

import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'

export type ProjectWorkspaceTab = 'overview' | 'versions' | 'evaluation' | 'optimization' | 'settings'

const tabs: ProjectWorkspaceTab[] = ['overview', 'versions', 'evaluation', 'optimization', 'settings']

export function ProjectNavigation({
  active,
  onChange,
}: {
  readonly active: ProjectWorkspaceTab
  readonly onChange: (tab: ProjectWorkspaceTab) => void
}) {
  const t = useTranslations('agentProject.workspace')

  return (
    <nav aria-label={t('navAria')} className="border-b border-border/60 px-4">
      <div className="flex gap-1 overflow-x-auto py-2">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            aria-current={active === tab ? 'page' : undefined}
            onClick={() => onChange(tab)}
            className={cn(
              'min-w-32 rounded-md px-3 py-2 text-left transition-colors',
              active === tab
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            <span className="block text-sm font-medium">{t(`tabs.${tab}.label`)}</span>
            <span className="block text-xs opacity-80">{t(`tabs.${tab}.description`)}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
