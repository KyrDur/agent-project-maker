'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeftIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { PackageSkillEditor } from '@/components/skill/skill-detail-package-editor'
import { TextSkillEditor } from '@/components/skill/skill-detail-text-editor'
import { SkillEvaluationTab } from '@/components/skill/skill-evaluation-tab'
import { SkillHistoryTab } from '@/components/skill/skill-history-tab'
import { useSkill } from '@/lib/hooks/use-skills'
import { cn } from '@/lib/utils'
import type { Skill } from '@/lib/types/skill'

import type { SkillScopedStudioTab } from '../../_lib/skill-studio-tabs'
import { renderSkillStudioTabShell } from './skill-studio-tab-shell'
import { SkillRevisionSourceViewer } from './skill-revision-source-viewer'
import { SkillSettingsSections } from './skill-settings-sections'

/**
 * skill scope tab 页面（evaluation/versions/source/settings）— 将旧 detail dialog 的 tab
 * component 按原 4-slot render prop 契约渲染到 full-page shell 中（规范 AD-3）。
 */
export function SkillTabPageClient({
  skillId,
  tab,
  revisionId = null,
}: {
  readonly skillId: string
  readonly tab: SkillScopedStudioTab
  /** 仅用于 source tab — revision read-only 模式（`?revision=`）。 */
  readonly revisionId?: string | null
}) {
  const t = useTranslations('skill.studio')
  const { data: skill, isLoading, isError } = useSkill(skillId)

  if (isLoading) {
    return (
      <div className="moldy-app-surface flex min-h-0 flex-1 overflow-hidden p-3">
        <div className="moldy-panel flex-1 space-y-4 p-6">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    )
  }

  if (isError || !skill) {
    return (
      <div className="moldy-app-surface flex min-h-0 flex-1 items-center justify-center p-3">
        <div className="moldy-panel max-w-md space-y-3 p-6 text-center">
          <h2 className="text-base font-semibold">{t('skillUnavailableTitle')}</h2>
          <p className="text-sm text-muted-foreground">{t('skillUnavailableHint')}</p>
          <Link href="/skills" className={cn(buttonVariants({ variant: 'outline' }))}>
            <ArrowLeftIcon className="size-4" />
            {t('backToList')}
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="moldy-app-surface flex min-h-0 flex-1 overflow-hidden p-3">
      <div className="moldy-panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <SkillTabBody skill={skill} tab={tab} revisionId={revisionId} />
      </div>
    </div>
  )
}

function SkillTabBody({
  skill,
  tab,
  revisionId,
}: {
  readonly skill: Skill
  readonly tab: SkillScopedStudioTab
  readonly revisionId: string | null
}) {
  const router = useRouter()

  if (tab === 'evaluation') {
    return renderSkillStudioTabShell({
      body: (
        <SkillEvaluationTab
          skillId={skill.id}
          skillContentHash={skill.content_hash}
          needsCredentialSetup={skill.health?.state === 'needs_credentials'}
          onOpenCredentials={() => router.push(`/skills/${skill.id}/settings`)}
        />
      ),
      footer: null,
    })
  }
  if (tab === 'versions') {
    return <SkillHistoryTab skillId={skill.id}>{renderSkillStudioTabShell}</SkillHistoryTab>
  }
  if (tab === 'settings') {
    return renderSkillStudioTabShell({
      body: <SkillSettingsSections skill={skill} />,
      footer: null,
    })
  }
  // source + ?revision= — revision snapshot read-only viewer（M4）。
  if (revisionId) {
    // key — 在同一位置仅 ?revision= 变化时（back/forward）重置 selectedPath 状态。
    return <SkillRevisionSourceViewer key={revisionId} skillId={skill.id} revisionId={revisionId} />
  }
  // source — 保留保存（=创建 revision），delete/export/凭据由 settings tab 管理（D1/D2）。
  if (skill.kind === 'text') {
    return <TextSkillEditor skillId={skill.id}>{renderSkillStudioTabShell}</TextSkillEditor>
  }
  return <PackageSkillEditor skillId={skill.id}>{renderSkillStudioTabShell}</PackageSkillEditor>
}
