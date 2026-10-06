'use client'

import { useTranslations } from 'next-intl'

export interface ClarifyingQuestionsCardProps {
  /** 标题区标签。默认为 `需要确认`。 */
  label?: string
  /** 问题列表 — 每项为字符串或 [正文, 提示] 元组。提示使用 muted-soft 颜色 inline 显示。 */
  items: Array<string | { text: string; hint?: string }>
}

/**
 * Builder Phase 2 进行中显示的 "澄清标题" 卡片。
 *
 * 作为机器人消息内 child block 的 presentational 组件。
 * 如果后端后续开始通过独立 tool emit，则在该 tool UI 中 wrap 此组件使用。
 */
export function ClarifyingQuestionsCard({ label, items }: ClarifyingQuestionsCardProps) {
  const t = useTranslations('chat.intentSummary')
  const resolvedLabel = label ?? t('clarifyingTitle')
  return (
    <div className="moldy-chat-card px-4 py-3.5">
      <div className="mb-2 moldy-ui-compact font-semibold moldy-builder-color-muted">
        {resolvedLabel}
      </div>
      <ul className="m-0 list-disc pl-5 text-sm leading-relaxed moldy-builder-color-ink-2">
        {items.map((item, idx) => {
          const text = typeof item === 'string' ? item : item.text
          const hint = typeof item === 'string' ? undefined : item.hint
          return (
            <li key={idx}>
              {text}
              {hint && <span className="moldy-builder-color-muted-soft"> ({hint})</span>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
