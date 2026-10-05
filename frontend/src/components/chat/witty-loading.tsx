'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'

const WITTY_MESSAGE_COUNT = 27
const ROTATE_INTERVAL_MS = 3000
const FADE_DURATION_MS = 300

interface WittyLoadingMessageProps {
  className?: string
}

// 模块级状态 — 即使组件在 streaming 中 remount（assistant-ui 若
// 每个分块重建消息树时会发生），消息文本和下一次 rotate 时间也会
// 保持。以前 ``useState(() => pickRandom(...))`` 的初始值会在每次 mount 时
// 重新随机，导致消息被流式传输分块的时序左右。
let _currentMessage: string | null = null
let _recent: string[] = []
let _nextRotateAt = 0

/**
 * 机智风格的加载中消息组件。
 * 每 3 秒随机轮换消息，使用 fade 转场。
 * 避免与前 5 条消息重复。同时显示 ThinkingDots 3-dot 动画。
 */
export function WittyLoadingMessage({ className }: WittyLoadingMessageProps) {
  const t = useTranslations('chat.loading.witty')
  const messages = useMemo(
    () => Array.from({ length: WITTY_MESSAGE_COUNT }, (_, i) => t(String(i))),
    [t],
  )

  const [message, setMessage] = useState(() => {
    if (_currentMessage !== null && messages.includes(_currentMessage)) {
      return _currentMessage
    }
    const initial = pickRandom(messages, _recent)
    _currentMessage = initial
    _recent = [..._recent.slice(-4), initial]
    _nextRotateAt = Date.now() + ROTATE_INTERVAL_MS
    return initial
  })
  const [fading, setFading] = useState(false)

  const messagesRef = useRef(messages)
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  // 不使用 setInterval，而用 setTimeout 链式调用，将下一次 rotate 时间绑定在模块状态中。
  // 即使组件 remount，也只等待到 ``_nextRotateAt`` 的剩余时间，
  // 因此即使分块很频繁，轮换周期仍稳定保持在约 3 秒。
  useEffect(() => {
    let cancelled = false

    const scheduleNext = () => {
      const wait = Math.max(0, _nextRotateAt - Date.now())
      const timer = setTimeout(() => {
        if (cancelled) return
        setFading(true)
        setTimeout(() => {
          if (cancelled) return
          const next = pickRandom(messagesRef.current, _recent)
          _recent = [..._recent.slice(-4), next]
          _currentMessage = next
          _nextRotateAt = Date.now() + ROTATE_INTERVAL_MS
          setMessage(next)
          setFading(false)
          scheduleNext()
        }, FADE_DURATION_MS)
      }, wait)
      return timer
    }

    const timer = scheduleNext()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  return (
    <div className={cn('flex items-center gap-3', className)} data-moldy-witty-loading="true">
      <ThinkingDots />
      <span
        className={cn(
          'text-xs text-muted-foreground transition-opacity duration-300',
          fading ? 'opacity-0' : 'opacity-100',
        )}
      >
        {message}
      </span>
    </div>
  )
}

/** 3-dot 脉冲动画（沿用现有 ThinkingDots 样式） */
function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5">
      <span className="size-2 animate-pulse rounded-full bg-primary/50 [animation-delay:0ms] [animation-duration:1.4s]" />
      <span className="size-2 animate-pulse rounded-full bg-primary/50 [animation-delay:200ms] [animation-duration:1.4s]" />
      <span className="size-2 animate-pulse rounded-full bg-primary/50 [animation-delay:400ms] [animation-duration:1.4s]" />
    </div>
  )
}

/** 从排除最近 N 条后的候选中随机选择消息 */
function pickRandom(pool: string[], recent: string[]): string {
  const available = pool.filter((m) => !recent.includes(m))
  const source = available.length > 0 ? available : pool
  return source[Math.floor(Math.random() * source.length)]
}
