'use client'

import { useTranslations } from 'next-intl'

/**
 * Follow-up ghost —— 在空 composer 上方以 placeholder 风格浅色显示 1 条建议
 * (fish autosuggestion)。开始输入后，父级(ThreadComposer)会根据 composer
 * 为空的条件自动隐藏，因此该组件只负责显示。
 *
 * 仅文本部分可点击(pointer-events-auto) —— 作为没有 → 键的触屏环境接受路径。
 * 其余区域点击仍直接传递给 textarea focus。
 * 屏幕阅读器会通过按钮 label 读出完整建议，视觉装饰（键帽提示）
 * 设为 aria-hidden。
 */
export function ComposerGhostSuggestion({
  text,
  onAccept,
}: {
  readonly text: string
  readonly onAccept: () => void
}) {
  const t = useTranslations('chat.followup')
  return (
    <div
      className="moldy-composer-ghost-overlay pointer-events-none"
      data-moldy-followup-ghost="true"
    >
      <button
        type="button"
        tabIndex={-1}
        onClick={onAccept}
        aria-label={t('acceptLabel', { text })}
        className="pointer-events-auto flex min-w-0 items-baseline gap-2 text-left"
      >
        <span className="truncate text-sm leading-relaxed text-muted-foreground/70">{text}</span>
        <kbd
          aria-hidden
          className="shrink-0 rounded border border-border/60 bg-muted px-1 py-0.5 font-sans moldy-ui-micro text-muted-foreground"
        >
          {t('hint')}
        </kbd>
      </button>
    </div>
  )
}
