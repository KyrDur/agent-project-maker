/**
 * Skill Studio 6-tab IA — 从 pathname 派生 active tab/context 的纯 helper。
 *
 * route 契约（Phase 2 规范 AD-1）：
 *   /skills                                 → list
 *   /skills/builder(/[sessionId])           → builder
 *   /skills/[skillId]/{evaluation,versions,source,settings} → 对应 tab
 *   /skills/[skillId]                       → source（与 server redirect 相同解释）
 */

export type SkillStudioTab = 'list' | 'builder' | 'evaluation' | 'versions' | 'source' | 'settings'

export const SKILL_STUDIO_TABS: readonly SkillStudioTab[] = [
  'list',
  'builder',
  'evaluation',
  'versions',
  'source',
  'settings',
]

export type SkillScopedStudioTab = Exclude<SkillStudioTab, 'list' | 'builder'>

const SKILL_SCOPED_TABS: ReadonlySet<string> = new Set([
  'evaluation',
  'versions',
  'source',
  'settings',
])

export function isSkillScopedStudioTab(value: string): value is SkillScopedStudioTab {
  return SKILL_SCOPED_TABS.has(value)
}

export type SkillStudioContext = {
  readonly activeTab: SkillStudioTab
  /** skill scope route 的 skillId（在 builder/list 中为 null）。 */
  readonly skillId: string | null
  /** builder session route 的 sessionId。 */
  readonly sessionId: string | null
}

export function deriveSkillStudioContext(pathname: string | null | undefined): SkillStudioContext {
  const segments = (pathname ?? '').split('/').filter(Boolean)
  if (segments[0] !== 'skills' || segments.length === 1) {
    return { activeTab: 'list', skillId: null, sessionId: null }
  }
  if (segments[1] === 'builder') {
    return { activeTab: 'builder', skillId: null, sessionId: segments[2] ?? null }
  }
  const tab = segments[2]
  return {
    activeTab: tab !== undefined && isSkillScopedStudioTab(tab) ? tab : 'source',
    skillId: segments[1],
    sessionId: null,
  }
}

/**
 * tab 跳转目标 URL。skill scope tab 在没有 context skill 时为 null（disabled）。
 * builder tab 在存在 context skill 时将 skillId 传给 index，
 * 从而将 session history/improve CTA scope 到该 skill。
 */
export function skillStudioTabHref(tab: SkillStudioTab, skillId: string | null): string | null {
  if (tab === 'list') return '/skills'
  if (tab === 'builder') {
    return skillId ? `/skills/builder?skillId=${encodeURIComponent(skillId)}` : '/skills/builder'
  }
  if (!skillId) return null
  return `/skills/${encodeURIComponent(skillId)}/${tab}`
}

/** legacy `?detailId=&tab=` deeplink 的 tab 值 → studio segment 映射（M2b redirect）。 */
export function legacyDetailTabToStudioTab(tab: string | null | undefined): SkillScopedStudioTab {
  switch (tab) {
    case 'evaluation':
      return 'evaluation'
    case 'history':
      return 'versions'
    case 'credentials':
    case 'metadata':
      return 'settings'
    default:
      return 'source'
  }
}
