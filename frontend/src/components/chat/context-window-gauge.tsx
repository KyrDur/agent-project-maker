'use client'

import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatContextWindow } from '@/lib/utils/provider'
import { formatCompactCount, formatDisplayNumber } from '@/lib/utils/display-format'
import type { TokenUsageBreakdown } from '@/lib/types'

// ──────────────────────────────────────────────
// ContextWindowGauge —— composer 底部的 "上下文窗口使用量" 显示（Claude Code 风格）。
//
// 占用量 = 最新 assistant turn 的 ``prompt_tokens`` 单独值。LangChain 1.x 中
// input_tokens 是包含全部 cache token 的总 input，因此不再叠加 cache_*
// （否则会重复计数）。上限 = model.context_window。
//
// context_window 为 null 的模型不隐藏，而显示为 "停用" 状态 —— muted/虚线 ring +
// 不同颜色 + hover 时提示未设置上限。（明确说明无法显示使用量。）
// ──────────────────────────────────────────────

interface ContextWindowGaugeProps {
  /** 最近一次 assistant turn usage（占用量用 prompt_tokens）。首轮前为 null。 */
  readonly usage: TokenUsageBreakdown | null
  /** 模型上下文窗口上限（token）。为 null 时禁用。 */
  readonly contextWindow: number | null | undefined
  /** 与 gauge 一起显示的模型名。 */
  readonly modelName?: string
  readonly runtimeCredentialName?: string | null
  readonly runtimeReady?: boolean
}

// 14px ring. r=6 → circumference 2π·6 ≈ 37.699.
const RING_RADIUS = 6
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

/** 自定义：80%↑ 警告色，95%↑ 危险色。低于此值为中性。 */
function levelColorClass(hasLimit: boolean, percent: number): string {
  if (!hasLimit) return 'text-muted-foreground/50'
  if (percent >= 95) return 'text-status-danger'
  if (percent >= 80) return 'text-status-warn'
  return 'text-muted-foreground'
}

export function ContextWindowGauge({
  usage,
  contextWindow,
  modelName,
  runtimeCredentialName,
  runtimeReady,
}: ContextWindowGaugeProps) {
  const t = useTranslations('chat.contextWindow')
  const hasLimit = typeof contextWindow === 'number' && contextWindow > 0
  const promptTokens = usage?.prompt_tokens ?? 0
  const percent = hasLimit ? Math.min((promptTokens / (contextWindow as number)) * 100, 100) : 0
  const roundedPercent = Math.round(percent)
  const colorClass = levelColorClass(hasLimit, percent)
  const strokeDashoffset = RING_CIRCUMFERENCE * (1 - percent / 100)

  const ring = (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5', colorClass)}>
      <svg viewBox="0 0 16 16" className="size-3.5 -rotate-90" aria-hidden focusable="false">
        <circle
          cx="8"
          cy="8"
          r={RING_RADIUS}
          fill="none"
          strokeWidth={2.5}
          stroke="currentColor"
          className="text-border"
          {...(hasLimit ? {} : { strokeDasharray: '2 2' })}
        />
        {hasLimit ? (
          <circle
            cx="8"
            cy="8"
            r={RING_RADIUS}
            fill="none"
            strokeWidth={2.5}
            stroke="currentColor"
            strokeLinecap="round"
            strokeDasharray={RING_CIRCUMFERENCE}
            style={{ strokeDashoffset }}
          />
        ) : null}
      </svg>
      {hasLimit ? (
        <span className="tabular-nums">
          {formatCompactCount(promptTokens, { thousandSuffix: 'k' })} /{' '}
          {formatContextWindow(contextWindow)} · {roundedPercent}%
        </span>
      ) : (
        <span className="text-muted-foreground/50">{t('disabledShort')}</span>
      )}
    </span>
  )

  return (
    <Tooltip>
      <TooltipTrigger
        render={(triggerProps) => {
          const { className, ...props } = triggerProps
          return (
            <button
              {...props}
              type="button"
              className={cn(
                className,
                'flex max-w-full items-center gap-1.5 rounded-md px-1.5 py-0.5 moldy-ui-micro text-muted-foreground',
              )}
              aria-label={
                hasLimit ? t('percentAria', { percent: roundedPercent }) : t('disabledAria')
              }
            >
              {modelName ? (
                // 在较窄 composer（panel 宽度 < @md）中隐藏模型名，避免 gauge·费用
                // 过于拥挤 —— 仅较宽时显示模型名（长名称 truncate）。
                <span className="hidden min-w-0 items-center gap-1.5 @md:flex">
                  <span className="max-w-40 truncate font-medium text-foreground/70">
                    {modelName}
                  </span>
                  <span className="shrink-0 text-muted-foreground/50" aria-hidden>
                    ·
                  </span>
                </span>
              ) : null}
              {ring}
            </button>
          )
        }}
      />
      <TooltipContent
        role="tooltip"
        side="top"
        align="end"
        sideOffset={6}
        className="moldy-popover block w-60 max-w-none bg-popover p-2.5 moldy-ui-caption text-popover-foreground"
      >
        {hasLimit ? (
          <>
            <div className="mb-1 flex items-center justify-between border-b pb-1.5 text-foreground">
              <span className="font-medium">{t('label')}</span>
              <span className="tabular-nums text-muted-foreground">{roundedPercent}%</span>
            </div>
            <div className="tabular-nums text-muted-foreground">
              {formatDisplayNumber(promptTokens, { locale: 'en-US' })} /{' '}
              {formatDisplayNumber(contextWindow as number, { locale: 'en-US' })}
            </div>
            <RuntimeDetails
              credentialName={runtimeCredentialName}
              modelName={modelName}
              ready={runtimeReady}
            />
            {percent >= 80 ? (
              <div className={cn('mt-1.5 border-t pt-1.5', colorClass)}>{t('compactHint')}</div>
            ) : null}
          </>
        ) : (
          <>
            <div className="text-muted-foreground">{t('disabled')}</div>
            <RuntimeDetails
              credentialName={runtimeCredentialName}
              modelName={modelName}
              ready={runtimeReady}
            />
          </>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

function RuntimeDetails({
  credentialName,
  modelName,
  ready,
}: {
  readonly credentialName?: string | null
  readonly modelName?: string
  readonly ready?: boolean
}) {
  const t = useTranslations('chat.contextWindow')
  if (!modelName && !credentialName && ready === undefined) return null
  return (
    <div className="mt-2 space-y-1 border-t pt-1.5 text-muted-foreground">
      <div className="flex items-center justify-between gap-3">
        <span>{t('runtimeModel')}</span>
        <span className="truncate text-right text-foreground">
          {modelName ?? t('notConfigured')}
        </span>
      </div>
      <div className="flex items-center justify-between gap-3">
        <span>{t('runtimeCredential')}</span>
        <span className="truncate text-right text-foreground">
          {credentialName ? `${credentialName} (${t('masked')})` : t('notConfigured')}
        </span>
      </div>
      {ready !== undefined ? (
        <div className="flex items-center justify-between gap-3">
          <span>{t('runtimeReadiness')}</span>
          <span className={ready ? 'text-status-success' : 'text-status-warn'}>
            {ready ? t('ready') : t('needsSetup')}
          </span>
        </div>
      ) : null}
    </div>
  )
}
