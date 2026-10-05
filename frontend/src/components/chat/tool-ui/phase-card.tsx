'use client'

import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PhaseCardProps {
  /** Header strip (e.g. IntentSummaryHeader, ToolRecommendationHeader). */
  header: ReactNode
  /** Body slot — main content. */
  children: ReactNode
  /** Footer action row (optional). */
  footer?: ReactNode
  className?: string
}

/**
 * Builder Phase 结果卡片通用外壳。
 *
 * Phase 2~8 结果卡片(IntentSummary, ToolRecommendation, MiddlewareRecommendation,
 * SystemPrompt, ImagePreview, DraftConfig …)的通用外壳。
 *
 * Spec:
 *  - bg `--surface` / 1px border `--border` / radius 14
 *  - shadow via `--builder-card-shadow`
 *  - overflow hidden — 让 header strip 贴到卡片边角
 */
export function PhaseCard({ header, children, footer, className }: PhaseCardProps) {
  return (
    <div className={cn('moldy-phase-card', className)}>
      {header}
      <div>{children}</div>
      {footer}
    </div>
  )
}

interface PhaseCardHeaderProps {
  children: ReactNode
  /** 'gradient' = mint gradient (IntentSummary), 'plain' = bottom border only (ToolRecommendation). */
  variant?: 'gradient' | 'plain'
  className?: string
}

/**
 * 卡片标题区去除。
 *
 * - gradient: 薄荷绿渐变 + bottom border（Phase 完成结果卡片 — 如意图收集完成等）
 * - plain: white + bottom border（review/approval 卡片 — 如工具推荐等）
 */
export function PhaseCardHeader({ children, variant = 'plain', className }: PhaseCardHeaderProps) {
  return (
    <div className={cn('moldy-phase-card-header', className)} data-variant={variant}>
      {children}
    </div>
  )
}

interface PhaseCardFooterProps {
  children: ReactNode
  className?: string
}

/**
 * 卡片页脚区域 (action row)。
 *
 * surfaceAlt 背景 + top border。内部 padding 和布局由使用方自由定义。
 */
export function PhaseCardFooter({ children, className }: PhaseCardFooterProps) {
  return <div className={cn('moldy-phase-card-footer', className)}>{children}</div>
}
