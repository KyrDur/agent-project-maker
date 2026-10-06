'use client'

import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import type { SkillDetailTabSlots } from '@/components/skill/skill-detail-tab-shell'

/**
 * 将 skill tab component（4-slot render prop 契约）渲染为 full-page studio layout
 * — 唯一的 runtime renderer（旧 DialogShell mapping 已随 dialog 一并删除）。overlay slot 会承载 rollback 确认 dialog 等，
 * 因此必须渲染（Phase 2 规范 AD-3）。
 */
export function renderSkillStudioTabShell(slots: SkillDetailTabSlots): ReactNode {
  return <SkillStudioTabShell slots={slots} />
}

function SkillStudioTabShell({ slots }: { readonly slots: SkillDetailTabSlots }) {
  return (
    <>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {slots.sidebar ? (
          <aside
            className={cn(
              'shrink-0 overflow-y-auto border-r border-border/60 p-4',
              slots.sidebarClassName,
            )}
          >
            {slots.sidebar}
          </aside>
        ) : null}
        <div className={cn('min-w-0 flex-1 overflow-y-auto px-6 py-4', slots.bodyClassName)}>
          {slots.body}
        </div>
      </div>
      {slots.footer ? (
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-border/60 px-6 py-3">
          {slots.footer}
        </div>
      ) : null}
      {slots.overlay ?? null}
    </>
  )
}
