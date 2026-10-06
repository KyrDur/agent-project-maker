'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * HITL Countdown Timer + Auto-Extend
 *
 * - 每 1 秒 tick 更新到过期 deadline 的剩余时间
 * - ≤60 秒 → urgent 标志 true
 * - 表单交互时调用 extend() → 30 秒 cooldown 内仅 1 次 +60s 延长
 * - 过期时调用 onExpire 1 次（自动 reject 等）
 */

const DEFAULT_TIMEOUT_S = 300 // 5 分钟
const EXTEND_AMOUNT_S = 60
const EXTEND_COOLDOWN_MS = 30_000
const URGENT_THRESHOLD_S = 60

export interface UseApprovalDeadlineOptions {
  approvalId: string
  initialTimeoutSeconds?: number
  onExpire: () => void
  /** false 时停止 timer（例如：已经完成决策的卡片） */
  active?: boolean
}

export interface UseApprovalDeadlineReturn {
  /** 剩余秒数（0 ~ initialTimeout） */
  remaining: number
  /** ≤60 秒 + 活跃状态 */
  isUrgent: boolean
  /** "MM:SS" 格式 */
  formatted: string
  /** 表单交互时调用 — cooldown 内则忽略 */
  extend: () => void
}

export function useApprovalDeadline({
  approvalId,
  initialTimeoutSeconds,
  onExpire,
  active = true,
}: UseApprovalDeadlineOptions): UseApprovalDeadlineReturn {
  const initial = initialTimeoutSeconds ?? DEFAULT_TIMEOUT_S
  // mount 后在 effect 中初始化 — 禁止在 useRef 初始值中使用 Date.now()（react-hooks/purity）
  const deadlineRef = useRef<number | null>(null)
  const lastExtendRef = useRef<number>(0)
  const expiredFiredRef = useRef(false)
  const onExpireRef = useRef(onExpire)
  const [remaining, setRemaining] = useState<number>(initial)

  // 同步 ref，避免 onExpire 变化时重新运行 effect
  useEffect(() => {
    onExpireRef.current = onExpire
  }, [onExpire])

  // approvalId（或 initial timeout）变化时 reset deadline
  // setState 在 tick effect 中处理（规避 set-state-in-effect 规则）
  useEffect(() => {
    deadlineRef.current = Date.now() + initial * 1000
    lastExtendRef.current = 0
    expiredFiredRef.current = false
  }, [approvalId, initial])

  useEffect(() => {
    if (!active) return undefined

    const tick = () => {
      const deadline = deadlineRef.current
      if (deadline === null) return
      const next = Math.max(0, (deadline - Date.now()) / 1000)
      setRemaining((prev) => (Math.ceil(prev) === Math.ceil(next) ? prev : next))
      if (next <= 0 && !expiredFiredRef.current) {
        expiredFiredRef.current = true
        onExpireRef.current()
      }
    }
    // 初始同步 — 避免等待 interval 第一次调用的 1 秒
    const start = setTimeout(tick, 0)
    const id = setInterval(tick, 1000)
    return () => {
      clearTimeout(start)
      clearInterval(id)
    }
  }, [active, approvalId, initial])

  const extend = useCallback(() => {
    if (!active) return
    const now = Date.now()
    if (now - lastExtendRef.current < EXTEND_COOLDOWN_MS) return
    lastExtendRef.current = now
    // 如果已经过期，则以 now 为基准重新开始
    const current = deadlineRef.current ?? now
    const base = Math.max(current, now)
    deadlineRef.current = base + EXTEND_AMOUNT_S * 1000
    expiredFiredRef.current = false
  }, [active])

  return {
    remaining,
    isUrgent: active && remaining > 0 && remaining <= URGENT_THRESHOLD_S,
    formatted: formatTime(remaining),
    extend,
  }
}

function formatTime(seconds: number): string {
  const total = Math.ceil(Math.max(0, seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}
