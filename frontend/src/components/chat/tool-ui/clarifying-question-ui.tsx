'use client'

import { useCallback, useId, useMemo, useState } from 'react'
import { useAui, type ToolCallMessagePartProps } from '@assistant-ui/react'
import { MessageCircleQuestionIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { reportClientWarning } from '@/lib/logging/client-logger'
import { cn } from '@/lib/utils'
import { useApprovalDeadline } from '@/lib/hooks/use-approval-deadline'
import { CountdownBadge } from './countdown-badge'

const STATE_CLASS = {
  idle: 'cursor-pointer border-border hover:border-primary/50 hover:bg-accent',
  selected: 'border-primary bg-primary/10 text-primary-foreground ring-1 ring-primary/30',
  dimmed: 'cursor-default opacity-40',
} as const

interface ClarifyingArgs {
  question?: string
  option_1?: string
  option_2?: string
  option_3?: string
  /** 选择过期 timeout (秒) — 未指定时为 5 分钟 */
  timeout_seconds?: number
  /** 标识符 — 用作 deadline 重置键 */
  approval_id?: string
}

interface ClarifyingResult {
  type: 'clarifying_question'
  question: string
  options: string[]
}

/**
 * Fix 智能体 `ask_clarifying_question` 工具 UI。
 * Backend 通过普通 LLM tool 返回 3 个选项 + "直接输入"。
 * 用户点击选项时，通过 setText + send 发送新的用户消息。
 *
 * 因为不是 HITL，backend 不会 pause，所以过期时无需额外操作，
 * 只将选项按钮设为 disabled，以视觉方式表达 urgency。
 */
export function ClarifyingQuestionUI({
  args,
  result,
  status,
}: ToolCallMessagePartProps<ClarifyingArgs, string>) {
  const t = useTranslations('chat.clarifying')
  const aui = useAui()
  const [picked, setPicked] = useState<string | null>(null)
  const directInputLabel = t('directInput')

  const parsed = useMemo<ClarifyingResult | null>(() => {
    if (typeof result === 'string') {
      try {
        return JSON.parse(result) as ClarifyingResult
      } catch {
        return null
      }
    }
    return null
  }, [result])

  const question = parsed?.question ?? args?.question ?? ''
  // parsed 是工具结果 JSON — 也要防御 options 不是数组的 shape。
  const options =
    (Array.isArray(parsed?.options) ? parsed.options : undefined) ??
    ([args?.option_1, args?.option_2, args?.option_3, directInputLabel].filter(Boolean) as string[])

  // 每个卡片实例的稳定 key —— 优先 args.approval_id，没有则 mount 时生成
  const fallbackId = useId()
  const approvalId = args?.approval_id ?? `clarifying-${fallbackId}`

  // 过期仅作为视觉信号 — backend 并非 paused 状态，因此无需额外 resume
  const handleExpire = useCallback(() => {
    // no-op: remaining<=0이 picked===null과 함께 disabled 트리거
  }, [])

  const { remaining, isUrgent, formatted, extend } = useApprovalDeadline({
    approvalId,
    initialTimeoutSeconds: args?.timeout_seconds,
    onExpire: handleExpire,
    active: picked === null,
  })

  if (status.type === 'running' && !args?.question) {
    // tool 调用中 args 尚未到达 — 空状态
    return null
  }

  const expired = remaining <= 0
  const disabled = picked !== null || expired

  const handleClick = (opt: string) => {
    if (disabled) return
    extend()
    setPicked(opt)
    if (opt === directInputLabel) {
      // 用户直接输入 — 仅做 disabled 处理，直接在输入框中打字
      return
    }
    try {
      // 与 SuggestionTrigger 相同的模式 — 直接在 thread 中对 user message 执行 append
      aui.thread.append({
        content: [{ type: 'text', text: opt }],
      })
    } catch (err) {
      reportClientWarning('clarifying', 'thread append error:', err)
      setPicked(null) // 失败后可再次点击
    }
  }

  return (
    <div className="moldy-chat-card mt-2 p-4">
      <div className="mb-3 flex items-start gap-2">
        <MessageCircleQuestionIcon className="mt-0.5 size-4 shrink-0 text-primary-strong" />
        <p className="flex-1 text-sm font-medium">{question}</p>
        <CountdownBadge
          formatted={formatted}
          isUrgent={isUrgent}
          expired={expired}
          label={t('expiresIn')}
          expiredLabel={t('expired')}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const state: 'idle' | 'selected' | 'dimmed' = disabled
            ? picked === opt
              ? 'selected'
              : 'dimmed'
            : 'idle'
          return (
            <button
              key={opt}
              type="button"
              disabled={disabled}
              onClick={() => handleClick(opt)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs transition-[background-color,border-color,color,box-shadow]',
                STATE_CLASS[state],
              )}
            >
              {opt}
            </button>
          )
        })}
      </div>
    </div>
  )
}
