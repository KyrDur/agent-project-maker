'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { BookOpen, Plus } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/shared/empty-state'
import { SearchInput } from '@/components/shared/search-input'
import {
  CountedLineTabs,
  ResourcePage,
  ResourcePanel,
  ResourceToolbar,
} from '@/components/shared/resource-layout'
import { useBuilderSessionLauncher } from '@/lib/hooks/use-skill-builder'
import { useSkills } from '@/lib/hooks/use-skills'
import {
  ALL_SKILL_FILTER,
  filterSkillList,
  SKILL_STATE_FILTERS,
  type SkillKindFilter,
  type SkillStateFilter,
} from '@/lib/skill-state-filters'
import type { Skill, SkillKind } from '@/lib/types/skill'
import { SkillListTable } from './skill-list-table'
import { SkillPageDialogs } from './skill-page-dialogs'
import { SkillStateFilterChips } from './skill-state-filter-chips'

type CreateTab = 'chat' | 'text' | 'package'
type SkillTab = SkillKindFilter

const SKILL_TABS: readonly SkillTab[] = [ALL_SKILL_FILTER, 'text', 'package']

function isSkillTab(value: string): value is SkillTab {
  return value === ALL_SKILL_FILTER || value === 'text' || value === 'package'
}

export function SkillsPageClient() {
  const t = useTranslations('skill')
  const router = useRouter()
  const launcher = useBuilderSessionLauncher()
  const [createOpen, setCreateOpen] = useState(false)
  const [createTab, setCreateTab] = useState<CreateTab>('chat')
  const [activeTab, setActiveTab] = useState<SkillTab>(ALL_SKILL_FILTER)
  const [stateFilter, setStateFilter] = useState<SkillStateFilter>(ALL_SKILL_FILTER)
  const [search, setSearch] = useState('')
  const normalizedSearch = search.trim().toLowerCase()
  const skillQueryParams = useMemo(() => {
    const params: { kind?: SkillKind; q?: string } = {}
    if (activeTab !== ALL_SKILL_FILTER) params.kind = activeTab
    if (normalizedSearch) params.q = normalizedSearch
    return Object.keys(params).length > 0 ? params : undefined
  }, [activeTab, normalizedSearch])
  const { data: skills, isLoading } = useSkills(skillQueryParams)
  const [publishSkill, setPublishSkill] = useState<Skill | null>(null)

  function openCreate(tab: CreateTab) {
    setCreateTab(tab)
    setCreateOpen(true)
  }

  // detail 不是 dialog，而是 studio route — legacy `?detailId=` 入口由
  // page.tsx server redirect 吸收（Phase 2）。
  function openDetail(id: string) {
    router.push(`/skills/${id}/source`)
  }

  // 进入 builder chat — session 启动/routing/失败 toast 由共享 launcher 管理。
  // dialog 会在 onStartChat 后立即自行关闭，因此这里不管理关闭。
  function openBuilderCreate(request: string) {
    void launcher.startCreate(request)
  }

  // list 表格中的 row "编辑" — 按 mock 契约直接启动 improve builder session。
  function openBuilderImprove(skillId: string) {
    void launcher.startImprove(skillId)
  }

  const data = useMemo(() => skills ?? [], [skills])

  const filteredSkills = useMemo(() => {
    // spread 在 useMemo 内只执行一次 — 如果每次 render 都创建新 identity，
    // DataTable 选择通知 effect 会循环触发（review R）。
    return [
      ...filterSkillList(data, {
        kind: activeTab,
        state: stateFilter,
        query: normalizedSearch,
      }),
    ]
  }, [activeTab, data, normalizedSearch, stateFilter])

  function countSkills(tab: SkillTab): number {
    return filterSkillList(data, {
      kind: tab,
      state: stateFilter,
      query: normalizedSearch,
    }).length
  }

  function countStateSkills(state: SkillStateFilter): number {
    return filterSkillList(data, {
      kind: activeTab,
      state,
      query: normalizedSearch,
    }).length
  }

  const tabs = SKILL_TABS.map((value) => ({
    value,
    label: value === ALL_SKILL_FILTER ? t('typeFilter.all') : t(`typeFilter.${value}`),
    countLabel: t('count', { count: countSkills(value) }),
  }))

  const stateFilters = SKILL_STATE_FILTERS.map((value) => ({
    value,
    label: t(`stateFilter.${value}`),
    countLabel: t('count', { count: countStateSkills(value) }),
  }))

  const isInitialEmpty = !isLoading && data.length === 0

  return (
    <ResourcePage
      title={t('title')}
      description={t('description')}
      action={
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => openCreate('package')}>
            {t('studio.list.uploadPackage')}
          </Button>
          <Button onClick={() => openCreate('chat')}>
            <Plus className="size-4" />
            {t('new')}
          </Button>
        </div>
      }
    >
      <ResourcePanel>
        {isInitialEmpty ? (
          <ResourcePanel.Body>
            <EmptyState
              icon={<BookOpen className="size-6" />}
              title={t('empty.title')}
              description={t('empty.description')}
              className="bg-card/50"
              action={
                <Button onClick={() => openCreate('chat')}>
                  <Plus className="size-4" />
                  {t('firstSkill')}
                </Button>
              }
            />
          </ResourcePanel.Body>
        ) : (
          <>
            <ResourcePanel.Toolbar>
              <CountedLineTabs
                ariaLabel={t('viewMode.label')}
                value={activeTab}
                tabs={tabs}
                onValueChange={(value) => {
                  if (isSkillTab(value)) setActiveTab(value)
                }}
              />
              <ResourceToolbar>
                <SkillStateFilterChips
                  ariaLabel={t('stateFilter.label')}
                  value={stateFilter}
                  filters={stateFilters}
                  onValueChange={setStateFilter}
                  className="flex-1"
                />
                <SearchInput
                  containerClassName="flex-1 sm:max-w-sm"
                  placeholder={t('searchPlaceholder')}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </ResourceToolbar>
            </ResourcePanel.Toolbar>

            <ResourcePanel.Body className="bg-background/30">
              <SkillListTable
                skills={filteredSkills}
                isLoading={isLoading}
                emptyTitle={t('empty.filtered')}
                onImprove={openBuilderImprove}
                improvePending={launcher.pending}
                onPublish={setPublishSkill}
              />
            </ResourcePanel.Body>
          </>
        )}
      </ResourcePanel>

      <SkillPageDialogs
        createOpen={createOpen}
        createTab={createTab}
        publishSkill={publishSkill}
        onCreateOpenChange={setCreateOpen}
        onCreated={(id) => openDetail(id)}
        onStartChat={openBuilderCreate}
        onPublishOpenChange={(open) => !open && setPublishSkill(null)}
      />
    </ResourcePage>
  )
}
