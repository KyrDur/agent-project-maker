/**
 * Builder Conversational UI 专用颜色令牌。
 *
 * 在构建器卡片组(ProgressRail, IntentSummary, ToolRecommendation 等)中共享。
 * 如果也在其他页面复用，则提升到 globals.css `@theme`。
 */
export const BUILDER_TOKENS = {
  surface: 'var(--builder-surface)',
  surfaceAlt: 'var(--builder-surface-alt)',
  border: 'var(--builder-border)',
  borderSoft: 'var(--builder-border-soft)',
  ink: 'var(--builder-ink)',
  ink2: 'var(--builder-ink-2)',
  muted: 'var(--builder-muted)',
  mutedSoft: 'var(--builder-muted-soft)',
  primary: 'var(--builder-primary)',
  primaryHover: 'var(--builder-primary-hover)',
  primaryDim: 'var(--builder-primary-dim)',
  primaryBg: 'var(--builder-primary-bg)',
  primaryBgSoft: 'var(--builder-primary-bg-soft)',
  primaryBgStrong: 'var(--builder-primary-bg-strong)',
  primaryInk: 'var(--builder-primary-ink)',
  bubble: 'var(--builder-bubble)',
  trackBg: 'var(--builder-track-bg)',
  connectorRest: 'var(--builder-connector-rest)',
  pendingDot: 'var(--builder-pending-dot)',
  cardShadow: 'var(--builder-card-shadow)',
  primaryShadow: 'var(--builder-primary-shadow)',
  focusShadow: 'var(--builder-focus-shadow)',
} as const

export type BuilderToken = typeof BUILDER_TOKENS
