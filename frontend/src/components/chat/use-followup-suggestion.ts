'use client'

import { useEffect, useRef } from 'react'
import { useAtomValue, useSetAtom } from 'jotai'
import { useAuiState } from '@assistant-ui/react'
import { useFollowupSuggestionMutation } from '@/lib/hooks/use-conversations'
import { followupEnabledAtom, setConversationFollowupAtom } from '@/lib/stores/chat-followup'
import { reportClientError } from '@/lib/logging/client-logger'

/**
 * 运行结束(thread.isRunning true→false)时生成 follow-up 建议 1 条，
 * 放入每个对话的 atom（use-files-run-sync 的完成检测模式）。
 *
 * - 开关 OFF 时完全不调用（成本 0）。
 * - 新运行开始时清空上一条建议，避免旧建议残留。
 * - 响应延迟到达但对话已切换时丢弃（竞态防护）。
 * - 失败静默忽略 — 幽灵只是 nice-to-have，不阻塞聊天。
 */
export function useFollowupSuggestion(conversationId: string | null): void {
  const enabled = useAtomValue(followupEnabledAtom)
  const setFollowup = useSetAtom(setConversationFollowupAtom)
  const isRunning = useAuiState((s) => s.thread.isRunning)
  const prevRunning = useRef(isRunning)
  // TanStack v5 的 mutateAsync 引用稳定 — 作为 effect 依赖是安全的。
  const { mutateAsync: fetchSuggestion } = useFollowupSuggestionMutation()

  useEffect(() => {
    const wasRunning = prevRunning.current
    prevRunning.current = isRunning
    if (!conversationId) return

    // 运行开始 — 上一轮的建议已不再有效。
    if (!wasRunning && isRunning) {
      setFollowup({ conversationId, suggestion: null })
      return
    }

    if (!wasRunning || isRunning || !enabled) return

    let cancelled = false
    const handlePageHide = () => {
      cancelled = true
    }
    window.addEventListener('pagehide', handlePageHide, { once: true })
    fetchSuggestion(conversationId)
      .then((response) => {
        if (cancelled) return
        setFollowup({ conversationId, suggestion: response.suggestion ?? null })
      })
      .catch((error) => {
        if (cancelled) return
        reportClientError('useFollowupSuggestion', 'suggestion fetch failed:', error)
      })
    return () => {
      cancelled = true
      window.removeEventListener('pagehide', handlePageHide)
    }
  }, [conversationId, enabled, fetchSuggestion, isRunning, setFollowup])
}
