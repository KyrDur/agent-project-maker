'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toApprove, toReject, toRespond } from '@/lib/chat/decision-mappers'
import { useHiTL } from '@/lib/chat/hitl-context'

export type ApprovalDecision = 'approved' | 'revision' | null

export interface UseApprovalFormOptions {
  /** revision 输入为空时使用的消息 */
  revisionFallback?: string
  /** 批准时的显示文本 */
  approveDisplay?: string
  /** status.type 是否为 'complete' */
  approvePayload?: () => Record<string, unknown>
  isComplete: boolean
}

export interface ApprovalFormState {
  revision: string
  setRevision: (value: string) => void
  submitted: ApprovalDecision
  isRunning: boolean
  isLocked: boolean
  handleApprove: () => Promise<void>
  handleRevision: () => Promise<void>
}

/** 通用 approval 表单 — revision 文本、submitted 决策、发送 HiTL resume。 */
export function useApprovalForm(options: UseApprovalFormOptions): ApprovalFormState {
  const t = useTranslations('chat.builderApproval')
  const {
    revisionFallback = t('requestRevision'),
    approveDisplay = t('approve'),
    isComplete,
  } = options

  const hitl = useHiTL()
  const [revision, setRevision] = useState('')
  const [submitted, setSubmitted] = useState<ApprovalDecision>(null)
  const isRunning = !isComplete
  const isLocked = !!submitted || !isRunning

  const handleApprove = async () => {
    if (submitted) return
    setSubmitted('approved')
    await hitl?.onResumeDecisions(
      [options.approvePayload ? toRespond(JSON.stringify(options.approvePayload())) : toApprove()],
      approveDisplay,
    )
  }

  const handleRevision = async () => {
    if (submitted) return
    const msg = revision.trim() || revisionFallback
    setSubmitted('revision')
    await hitl?.onResumeDecisions([toReject(msg)], msg)
  }

  return {
    revision,
    setRevision,
    submitted,
    isRunning,
    isLocked,
    handleApprove,
    handleRevision,
  }
}
