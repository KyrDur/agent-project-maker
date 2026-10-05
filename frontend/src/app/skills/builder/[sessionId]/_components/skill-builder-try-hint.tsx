'use client'

import { useAui } from '@assistant-ui/react'
import { CheckIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'

/**
 * "用示例测试" try-hint（M7 — 借用 mock composer 上方 dashed pill）。
 *
 * inline test（规范 §1.3 决策 1）的入口 affordance — 点击后在 composer 中预填测试
 * 请求。通过 AssistantThread 的 composerHint slot 渲染，位于
 * AssistantRuntimeProvider context 内，因此可访问 composer runtime。
 */
export function SkillBuilderTryHint() {
  const t = useTranslations('skill.builderChat')
  const composer = useAui().composer

  return (
    <button
      type="button"
      data-testid="builder-try-hint"
      onClick={() => composer.setText(t('tryHintPrefill'))}
      className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-dashed border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary-strong hover:bg-primary/20 hover:text-primary-strong"
    >
      <CheckIcon className="size-3" />
      {t('tryHint')}
    </button>
  )
}
