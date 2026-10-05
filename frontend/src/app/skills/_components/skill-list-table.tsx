'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import type { ColumnDef, RowSelectionState } from '@tanstack/react-table'
import { Download, MoreHorizontal, Trash2, UploadCloud } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog'
import { OriginBadge } from '@/components/marketplace/badges/origin-badge'
import { PublicationBadge } from '@/components/marketplace/badges/publication-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable } from '@/components/ui/data-table'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SkillEvaluationSummaryBadge } from '@/components/skill/skill-evaluation-summary-badge'
import { SkillHealthBadge } from '@/components/skill/skill-health-badge'
import { useAgents } from '@/lib/hooks/use-agents'
import { getSkillExportUrl, isSkillNotFoundError, useDeleteSkill } from '@/lib/hooks/use-skills'
import { formatDisplayDate } from '@/lib/utils/display-format'
import type { Skill } from '@/lib/types/skill'

/** 与旧 SkillCard 相同的 publish guard — 对已发布 skill 隐藏 publish 入口。 */
function canPublishSkill(skill: Skill): boolean {
  return !skill.publication_summary?.state || skill.publication_summary.state === 'not_published'
}

/** 确认 dialog 中列举名称的上限 — 无限制列举会在 max-w-xs dialog 中
 * 增长为数百行，导致确认/取消按钮被挤出屏幕（R5）。 */
const NAME_LIST_CAP = 8

function formatNameList(names: readonly string[], more: (count: number) => string): string {
  if (names.length <= NAME_LIST_CAP) return names.join(', ')
  return `${names.slice(0, NAME_LIST_CAP).join(', ')} ${more(names.length - NAME_LIST_CAP)}`
}

/**
 * skill 列表表格（Phase 2 mock skill-table）— DataTable rowSelection 的首次引入。
 *
 * 选择状态由 controlled(rowSelectionState) 管理，以便 bulk delete/取消选择时
 * 无需 remount 即可重置（保持排序·分页）。搜索可能留下被隐藏的已选 row，
 * 因此在确认 dialog 中列出目标名称（规范 AD-5）。
 */
export function SkillListTable({
  skills,
  isLoading,
  emptyTitle,
  onImprove,
  improvePending,
  onPublish,
}: {
  /** 直接接收父级 useMemo 结果 — 如果创建新的 identity，选择通知 effect 会循环触发。 */
  readonly skills: Skill[]
  readonly isLoading: boolean
  readonly emptyTitle: string
  readonly onImprove: (skillId: string) => void
  /** builder session 启动中 — 防止 row "编辑" 双击重复创建 session。 */
  readonly improvePending: boolean
  readonly onPublish: (skill: Skill) => void
}) {
  const t = useTranslations('skill')
  const list = useTranslations('skill.studio.list')
  const router = useRouter()
  const removeSkill = useDeleteSkill()
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [selected, setSelected] = useState<Skill[]>([])
  // 删除目标只保存 **id**，执行/显示时再从当前列表派生 —
  // 选择 snapshot object 在 refetch 后可能 stale（DataTable 通知基于 id）。
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([])
  const [deleting, setDeleting] = useState(false)
  const pendingSkills = skills.filter((skill) => pendingDeleteIds.includes(skill.id))
  // 如果 dialog 因派生条件 close 后（目标经 refetch 全部消失）仍残留 id，
  // 当该 skill 再次出现在列表中时，破坏性 dialog 会自动重新打开 —
  // 通过 guarded render-time reset 清理（沿用 package editor selectedPath 先例）。
  if (pendingDeleteIds.length > 0 && pendingSkills.length === 0 && !deleting) {
    setPendingDeleteIds([])
  }

  function resetSelection() {
    setRowSelection({})
    setSelected([])
  }

  async function executeDelete() {
    if (pendingSkills.length === 0) {
      // 如果 dialog 打开期间 refetch 导致目标全部消失 — 清理残留 id
      // 并关闭 dialog（否则确认按钮会无响应，形成 dead-end）。
      setPendingDeleteIds([])
      return
    }
    setDeleting(true)
    const failures: string[] = []
    // 顺序删除 — 复用现有单条 DELETE，部分失败按名称报告（AD-5）。
    for (const skill of pendingSkills) {
      try {
        await removeSkill.mutateAsync(skill.id)
      } catch (error) {
        // 404 = 幂等成功 — 目标已在其他 tab/flow 中删除。若计为失败，
        // 结果明明符合请求却会误发 "删除失败" toast（规则 ④，R5）。
        if (!isSkillNotFoundError(error)) {
          failures.push(skill.name)
        }
      }
    }
    setDeleting(false)
    setPendingDeleteIds([])
    resetSelection()
    const deletedCount = pendingSkills.length - failures.length
    if (deletedCount > 0) {
      toast.success(list('deleteSuccess', { count: deletedCount }))
    }
    if (failures.length > 0) {
      // 失败名称也与确认 dialog 使用相同上限 — 若因 session 过期等导致全部失败，
      // 无上限 toast 会覆盖屏幕（R6）。
      toast.error(
        list('deletePartialFailure', {
          names: formatNameList(failures, (count) => list('moreNames', { count })),
        }),
      )
    }
  }

  const connectedTotal = pendingSkills.reduce((sum, skill) => sum + skill.used_by_count, 0)
  const pendingNames = formatNameList(
    pendingSkills.map((skill) => skill.name),
    (count) => list('moreNames', { count }),
  )
  // AD-4.1 — 受影响的 Agent 名称无需新增 API，可从 Agent 列表反向推导。
  // 只有删除确认已打开且 **存在连接计数时** 才 fetch — 无条件 fetch 会在
  // 每次访问 /skills（R5）、每次删除连接数为 0 的项（R6）时触发沉重的 Agent 全量序列化，
  // （侧边栏使用 useAgentSummaries，无法共享 cache）。loading 时用占位
  // 文案避免 dialog 文本 reflow。
  const {
    data: agents,
    isLoading: agentsLoading,
    isError: agentsError,
  } = useAgents({
    enabled: pendingDeleteIds.length > 0 && connectedTotal > 0,
  })
  const pendingIdSet = new Set(pendingDeleteIds)
  const affectedAgentNames =
    connectedTotal > 0
      ? (agents ?? [])
          .filter((agent) => agent.skills?.some((brief) => pendingIdSet.has(brief.id)))
          .map((agent) => agent.name)
      : []

  const columns: ColumnDef<Skill, unknown>[] = [
    {
      accessorKey: 'name',
      header: t('columns.skill'),
      cell: ({ row }) => (
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{row.original.name}</p>
          <p className="moldy-ui-micro truncate font-mono text-muted-foreground">
            {row.original.slug}
            {row.original.version ? ` · v${row.original.version}` : ''}
          </p>
        </div>
      ),
    },
    {
      accessorKey: 'kind',
      header: t('columns.kind'),
      cell: ({ row }) => (
        <Badge variant="secondary" className="moldy-ui-micro">
          {t(`typeFilter.${row.original.kind}`)}
        </Badge>
      ),
    },
    {
      id: 'status',
      header: t('columns.status'),
      enableSorting: false,
      cell: ({ row }) => (
        // publish/source badge 从旧 card 迁移 — 列表中不会丢失 publish 状态。
        <div className="flex flex-wrap items-center gap-1">
          <SkillHealthBadge health={row.original.health} />
          <OriginBadge summary={row.original.origin_summary} />
          <PublicationBadge summary={row.original.publication_summary} />
        </div>
      ),
    },
    {
      id: 'evaluation',
      header: t('columns.evaluation'),
      // mock 契约（按通过率排序）— 基于 summary pass_rate，未评估项放最底部。
      accessorFn: (skill) => skill.latest_evaluation_summary?.pass_rate ?? -1,
      cell: ({ row }) => (
        <SkillEvaluationSummaryBadge summary={row.original.latest_evaluation_summary} />
      ),
    },
    {
      accessorKey: 'used_by_count',
      header: t('columns.agents'),
      cell: ({ row }) => (
        <span className="text-sm tabular-nums">
          {t('agentsCount', { count: row.original.used_by_count })}
        </span>
      ),
    },
    {
      accessorKey: 'updated_at',
      header: t('columns.updatedAt'),
      cell: ({ row }) => (
        <span className="moldy-ui-micro text-muted-foreground">
          {formatDisplayDate(row.original.updated_at, { fallback: '' })}
        </span>
      ),
    },
    {
      id: 'actions',
      header: '',
      enableSorting: false,
      cell: ({ row }) => (
        <SkillRowActions
          skill={row.original}
          onImprove={onImprove}
          improvePending={improvePending}
          onPublish={onPublish}
          onDelete={(skill) => setPendingDeleteIds([skill.id])}
        />
      ),
    },
  ]

  return (
    <>
      <DataTable
        columns={columns}
        data={skills}
        loading={isLoading}
        pageSize={20}
        enableRowSelection
        rowSelectionState={rowSelection}
        onRowSelectionStateChange={setRowSelection}
        onRowSelectionChange={setSelected}
        onRowClick={(skill) => router.push(`/skills/${skill.id}/source`)}
        emptyTitle={emptyTitle}
        toolbar={
          selected.length > 0 ? (
            <div className="flex items-center gap-2" data-testid="skill-bulk-bar">
              <span className="moldy-ui-micro text-muted-foreground">
                {list('selectedCount', { count: selected.length })}
              </span>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => setPendingDeleteIds(selected.map((skill) => skill.id))}
              >
                <Trash2 className="size-3.5" />
                {list('deleteSelected')}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={resetSelection}>
                {list('clearSelection')}
              </Button>
            </div>
          ) : null
        }
      />

      <DeleteConfirmDialog
        open={pendingSkills.length > 0}
        onOpenChange={(open) => {
          if (!open && !deleting) setPendingDeleteIds([])
        }}
        title={list('bulkDeleteTitle', { count: pendingSkills.length })}
        description={
          connectedTotal > 0
            ? [
                list('bulkDeleteDescriptionConnected', {
                  names: pendingNames,
                  connected: connectedTotal,
                }),
                // 不把查询失败静默吞掉 — 如果只显示连接计数而
                // 名称披露（AD-4.1）消失，用户会在不知失败的情况下点击破坏性
                // 确认（R6）。
                agentsLoading
                  ? list('affectedAgentsLoading')
                  : agentsError
                    ? list('affectedAgentsError')
                    : affectedAgentNames.length > 0
                      ? list('affectedAgents', {
                          names: formatNameList(affectedAgentNames, (count) =>
                            list('moreNames', { count }),
                          ),
                        })
                      : null,
              ]
                .filter(Boolean)
                .join('\n')
            : list('bulkDeleteDescription', { names: pendingNames })
        }
        confirmLabel={list('deleteSelected')}
        isPending={deleting}
        onConfirm={() => void executeDelete()}
      />
    </>
  )
}

function SkillRowActions({
  skill,
  onImprove,
  improvePending,
  onPublish,
  onDelete,
}: {
  readonly skill: Skill
  readonly onImprove: (skillId: string) => void
  readonly improvePending: boolean
  readonly onPublish: (skill: Skill) => void
  readonly onDelete: (skill: Skill) => void
}) {
  const t = useTranslations('skill')
  const list = useTranslations('skill.studio.list')
  const router = useRouter()

  // 为避免与 row click（跳转 source）冲突，在每个 interactive element 上阻止传播
  // （与 DataTable checkbox column 相同先例 — 静态 wrapper handler 违反 a11y）。
  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={improvePending}
        onClick={(event) => {
          event.stopPropagation()
          onImprove(skill.id)
        }}
        aria-label={list('rowImproveAria', { name: skill.name })}
      >
        {list('rowImprove')}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={(event) => {
          event.stopPropagation()
          router.push(`/skills/${skill.id}/evaluation`)
        }}
      >
        {list('rowEvaluation')}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={(event) => {
          event.stopPropagation()
          router.push(`/skills/${skill.id}/versions`)
        }}
      >
        {list('rowVersions')}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={list('rowMenuAria', { name: skill.name })}
          className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted"
          onClick={(event) => event.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => router.push(`/skills/${skill.id}/source`)}>
            {list('rowViewSource')}
          </DropdownMenuItem>
          {canPublishSkill(skill) ? (
            <DropdownMenuItem onClick={() => onPublish(skill)}>
              <UploadCloud className="size-4" />
              {t('actions.publish')}
            </DropdownMenuItem>
          ) : null}
          {skill.kind === 'package' ? (
            <DropdownMenuItem
              render={
                <a href={getSkillExportUrl(skill.id)} download aria-label={list('rowExport')} />
              }
            >
              <Download className="size-4" />
              {list('rowExport')}
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem variant="destructive" onClick={() => onDelete(skill)}>
            <Trash2 className="size-4" />
            {list('rowDelete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
