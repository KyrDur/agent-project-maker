import type { ReactNode } from 'react'

/**
 * 技能标签页组件的 4-插槽渲染属性契约 — 唯一的运行时渲染器是工作室的
 * `renderSkillStudioTabShell`(app/skills/[skillId]/_components)。旧
 * DialogShell 渲染器已随详情对话框一起移除 (Phase 2)。
 */
export type SkillDetailTabSlots = {
  readonly body: ReactNode
  readonly bodyClassName?: string
  readonly footer: ReactNode
  readonly overlay?: ReactNode
  readonly sidebar?: ReactNode
  readonly sidebarClassName?: string
}

export type SkillDetailTabRender = (slots: SkillDetailTabSlots) => ReactNode
