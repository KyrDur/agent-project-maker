'use client'

/**
 * Settings 页面 form-mode 使用的 tool·skill 添加 dialog。
 *
 * 为了让 form-mode 也使用与 Visual-settings 集成 4-tab dialog（Catalog / My Tools / MCP / Skills）
 * 相同的 UX，直接原样 export。component 主体位于
 * ``@/components/agent/visual-settings/dialogs/tools-skills-dialog``，
 * settings 页面将通过 useTools/useSkills 加载的 list 作为 prop 传入。
 */

export { ToolsSkillsDialog } from '@/components/agent/visual-settings/dialogs/tools-skills-dialog'
