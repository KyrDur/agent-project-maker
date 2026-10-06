'use client'

import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { ChevronsUpDown, Sparkles } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { LineTabsList, LineTabsTrigger } from '@/components/ui/line-tabs'
import { Tabs } from '@/components/ui/tabs'
import { SkillSummaryStrip } from '@/components/skill/skill-summary-strip'
import { useBuilderSessionLauncher, useSkillBuilderSession } from '@/lib/hooks/use-skill-builder'
import { useSkill, useSkills } from '@/lib/hooks/use-skills'
import type { Skill } from '@/lib/types/skill'

import {
  deriveSkillStudioContext,
  isSkillScopedStudioTab,
  SKILL_STUDIO_TABS,
  skillStudioTabHref,
  type SkillStudioTab,
} from '../_lib/skill-studio-tabs'

/**
 * Skill Studio shell — 6-tab navigation + 当前 skill context bar（Phase 2 规范 AD-2）。
 *
 * layout 无法访问子 segment params（Next.js 契约），因此通过 client
 * hook(pathname) 派生 active tab/context。builder route 的 context skill
 * 按 session source（improve 原始项）→ finalized（生成产物）顺序反向解析。
 */
export function SkillStudioShell() {
  const t = useTranslations('skill.studio')
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const context = deriveSkillStudioContext(pathname)
  const { data: builderSession } = useSkillBuilderSession(context.sessionId)
  const builderSkillId = context.sessionId
    ? (builderSession?.source_skill_id ?? builderSession?.finalized_skill_id ?? null)
    : null
  // builder index（/skills/builder?skillId=）的 scope skill — pathname 中没有，
  // 从 query 补充。漏掉会导致 4 个 skill scope tab 被错误显示为 disabled（review R）。
  const builderIndexSkillId =
    context.activeTab === 'builder' && context.sessionId === null
      ? searchParams.get('skillId')
      : null
  const contextSkillId = context.skillId ?? builderSkillId ?? builderIndexSkillId
  const { data: contextSkill } = useSkill(contextSkillId)
  const launcher = useBuilderSessionLauncher()

  function handleTabChange(value: string) {
    const tab = value as SkillStudioTab
    if (tab === context.activeTab) return
    const href = skillStudioTabHref(tab, contextSkillId)
    if (href) router.push(href)
  }

  function handleSwitchSkill(skill: Skill) {
    // 保持 active tab（§2.2）— 在 builder tab 中跳到目标 skill scope 的 builder index。
    if (context.activeTab === 'builder') {
      router.push(skillStudioTabHref('builder', skill.id) ?? '/skills/builder')
      return
    }
    const tab = isSkillScopedStudioTab(context.activeTab) ? context.activeTab : 'source'
    router.push(`/skills/${skill.id}/${tab}`)
  }

  function handleImprove() {
    if (!contextSkillId) return
    void launcher.startImprove(contextSkillId)
  }

  const showContextBar = context.activeTab !== 'list'

  return (
    <div className="shrink-0 border-b border-border/60 bg-background">
      <Tabs value={context.activeTab} onValueChange={handleTabChange} className="gap-0">
        <div className="px-4">
          <LineTabsList aria-label={t('tabsAria')} className="w-full justify-start overflow-x-auto">
            {SKILL_STUDIO_TABS.map((tab) => {
              const disabled =
                isSkillScopedStudioTab(tab) && skillStudioTabHref(tab, contextSkillId) === null
              return (
                <LineTabsTrigger
                  key={tab}
                  value={tab}
                  disabled={disabled}
                  data-testid={`studio-tab-${tab}`}
                >
                  {t(`tabs.${tab}`)}
                </LineTabsTrigger>
              )
            })}
          </LineTabsList>
        </div>
      </Tabs>
      {showContextBar ? (
        <SkillStudioContextBar
          skill={contextSkill ?? null}
          isBuilderDraft={context.activeTab === 'builder' && !contextSkillId}
          improvePending={launcher.pending}
          showImprove={context.activeTab !== 'builder' && Boolean(contextSkillId)}
          onSwitchSkill={handleSwitchSkill}
          onImprove={handleImprove}
        />
      ) : null}
    </div>
  )
}

function SkillStudioContextBar({
  skill,
  isBuilderDraft,
  improvePending,
  showImprove,
  onSwitchSkill,
  onImprove,
}: {
  readonly skill: Skill | null
  readonly isBuilderDraft: boolean
  readonly improvePending: boolean
  readonly showImprove: boolean
  readonly onSwitchSkill: (skill: Skill) => void
  readonly onImprove: () => void
}) {
  const t = useTranslations('skill.studio.contextBar')

  if (!skill && !isBuilderDraft) return null

  const passRate = skill?.latest_evaluation_summary?.pass_rate
  const passRateLabel =
    typeof passRate === 'number' ? t('passRateValue', { percent: Math.round(passRate * 100) }) : '—'

  return (
    <div
      data-testid="studio-context-bar"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border/40 px-4 py-2"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="moldy-ui-micro shrink-0 text-muted-foreground">{t('currentSkill')}</span>
        {skill ? (
          <SkillSwitcher skill={skill} onSwitchSkill={onSwitchSkill} />
        ) : (
          <span className="text-sm font-semibold">{t('newDraft')}</span>
        )}
        {skill ? (
          <span className="moldy-ui-micro hidden truncate font-mono text-muted-foreground sm:inline">
            {skill.slug}
          </span>
        ) : null}
      </div>
      {skill ? (
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
          <SkillSummaryStrip skill={skill} />
          <span className="moldy-ui-micro text-muted-foreground">
            {t('passRate')} <span className="font-semibold text-foreground">{passRateLabel}</span>
          </span>
          <span className="moldy-ui-micro text-muted-foreground">
            {t('connectedAgents')}{' '}
            <span className="font-semibold text-foreground">{skill.used_by_count}</span>
          </span>
        </div>
      ) : null}
      {showImprove && skill ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto"
          disabled={improvePending}
          onClick={onImprove}
        >
          <Sparkles className="size-3.5" />
          {t('improve')}
        </Button>
      ) : null}
    </div>
  )
}

function SkillSwitcher({
  skill,
  onSwitchSkill,
}: {
  readonly skill: Skill
  readonly onSwitchSkill: (skill: Skill) => void
}) {
  const t = useTranslations('skill.studio.contextBar')
  const skillT = useTranslations('skill')

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="studio-skill-switcher"
        aria-label={t('switchSkill')}
        className="flex min-w-0 items-center gap-1 text-sm font-semibold hover:text-primary-strong"
      >
        <span className="truncate">{skill.name}</span>
        <Badge variant="secondary" className="moldy-ui-micro shrink-0">
          {/* 避免 raw enum('package'/'text') 暴露在中文界面文案旁，列表
              使用与表格相同的 typeFilter key 进行翻译（R5）。 */}
          {skillT(`typeFilter.${skill.kind}`)}
        </Badge>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
        {/* useSkills 仅在 popup 打开、content mount 时订阅 — 避免 shell 在所有
            skill route 中持续 fetch 完整列表(+enrichment)。 */}
        <SkillSwitcherItems currentSkillId={skill.id} onSwitchSkill={onSwitchSkill} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function SkillSwitcherItems({
  currentSkillId,
  onSwitchSkill,
}: {
  readonly currentSkillId: string
  readonly onSwitchSkill: (skill: Skill) => void
}) {
  const t = useTranslations('skill.studio.contextBar')
  const { data: skills } = useSkills()
  const candidates = (skills ?? []).filter((candidate) => candidate.id !== currentSkillId)

  if (candidates.length === 0) {
    return <DropdownMenuItem disabled>{t('noOtherSkills')}</DropdownMenuItem>
  }
  return (
    <>
      {candidates.map((candidate) => (
        <DropdownMenuItem key={candidate.id} onClick={() => onSwitchSkill(candidate)}>
          <span className="truncate">{candidate.name}</span>
          <span className="moldy-ui-micro ml-auto font-mono text-muted-foreground">
            {candidate.slug}
          </span>
        </DropdownMenuItem>
      ))}
    </>
  )
}
