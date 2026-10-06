'use client'

import { createContext, useContext } from 'react'
import type { Decision } from '@/lib/types'

export interface HiTLContextValue {
  /**
   * `decisions` 数组长度必须与 interrupt 的 `action_requests.length` 一致
   * （LangChain `HITLResponse` contract）。
   */
  onResumeDecisions: (decisions: Decision[], displayText?: string) => Promise<void>
  registerDecision?: (
    actionIndex: number,
    decision: Decision,
    displayText?: string,
    interruptId?: string | null,
  ) => Promise<void>
}

export const HiTLContext = createContext<HiTLContextValue | null>(null)

/** 用于从 Tool UI 组件调用 HiTL resume 的 hook */
export function useHiTL() {
  return useContext(HiTLContext)
}
