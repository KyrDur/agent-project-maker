'use client'

import { CheckIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { BuilderBody, BuilderMuted, BuilderPill } from './builder-primitives'
import { PhaseCard, PhaseCardHeader } from './phase-card'

export type IntentConfidence = 'high' | 'medium' | 'low'

export interface IntentSummaryCardProps {
  /** 智能体名称（例：'行业新闻监控'）。 */
  name: string
  /** 智能体描述（一个段落）。 */
  description: string
  /** 标签（摘要关键词，0~N 个）。 */
  tags?: string[]
  /** 意图分析置信度。反映在标题区右侧标签中。 */
  confidence?: IntentConfidence
  /** 标题区 phase 标签（例：'Phase 2'）。 */
  phaseLabel?: string
}

function IntentSummaryHeader({
  confidence = 'high',
  phaseLabel = 'Phase 2',
}: {
  confidence?: IntentConfidence
  phaseLabel?: string
}) {
  const t = useTranslations('chat.intentSummary')
  return (
    <PhaseCardHeader variant="gradient">
      <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-[var(--builder-primary)] text-white">
        <CheckIcon className="size-2.5" strokeWidth={3.5} />
      </span>
      <span className="moldy-ui-compact font-semibold moldy-builder-color-primary-ink">
        {t('title')}
      </span>
      <BuilderMuted className="moldy-ui-caption-plus">· {phaseLabel}</BuilderMuted>
      <div className="flex-1" />
      <span className="moldy-ui-meta font-semibold uppercase tabular-nums moldy-builder-color-muted">
        {t(`confidence.${confidence}`)}
      </span>
    </PhaseCardHeader>
  )
}

function IntentLabel({ text }: { text: string }) {
  return (
    <div className="mb-1 moldy-ui-caption-plus font-semibold moldy-builder-color-muted">{text}</div>
  )
}

/**
 * Phase 2 结果卡片 — 意图分析摘要。
 *
 * 当前 backend 不会通过独立 tool emit，因此仅提供为 presentational 组件。
 * 后续 builder graph 若将 `intent_summary` ToolMessage emit 出来，则在对应 tool UI 中
 * 直接 wrap 此组件使用。
 */
export function IntentSummaryCard({
  name,
  description,
  tags,
  confidence = 'high',
  phaseLabel = 'Phase 2',
}: IntentSummaryCardProps) {
  const t = useTranslations('chat.intentSummary')
  return (
    <PhaseCard header={<IntentSummaryHeader confidence={confidence} phaseLabel={phaseLabel} />}>
      <BuilderBody loose>
        <IntentLabel text={t('agentName')} />
        <div className="mb-3.5 moldy-ui-display-compact font-bold moldy-builder-color-ink">
          {name}
        </div>

        <IntentLabel text={t('description')} />
        <p className="mb-3.5 text-sm leading-relaxed moldy-builder-color-ink-2 [text-wrap:pretty]">
          {description}
        </p>

        {tags && tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <BuilderPill key={tag}>{tag}</BuilderPill>
            ))}
          </div>
        )}
      </BuilderBody>
    </PhaseCard>
  )
}
