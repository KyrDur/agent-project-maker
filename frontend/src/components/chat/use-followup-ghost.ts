'use client'

import { useCallback, type KeyboardEvent, type RefObject } from 'react'
import { useAtomValue, useSetAtom } from 'jotai'
import { useAui, useAuiState } from '@assistant-ui/react'
import {
  chatFollowupSuggestionAtom,
  followupEnabledAtom,
  setConversationFollowupAtom,
} from '@/lib/stores/chat-followup'
import { focusTextareaAtEnd } from './composer-focus'

/**
 * Follow-up 幽灵（浅色建议文本）交互 — fish autosuggestion 契约。
 *
 * - 显示条件：开关 ON + 有建议 + 输入器为空 + 运行未进行。
 *   （开始输入后输入器不再为空，因此自动消失。）
 * - → 或 End：将建议填入实际输入（发送仍需另按 Enter）。
 * - Esc：取消本次建议。
 * - IME 组合中不介入。
 */
export function useFollowupGhost(
  conversationId: string | null,
  textareaRef: RefObject<HTMLTextAreaElement | null>,
): {
  ghostText: string | null
  handleGhostKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void
  acceptGhost: () => void
} {
  const aui = useAui()
  const enabled = useAtomValue(followupEnabledAtom)
  const suggestions = useAtomValue(chatFollowupSuggestionAtom)
  const setFollowup = useSetAtom(setConversationFollowupAtom)
  const composerEmpty = useAuiState(
    (state) => !state.composer.isEditing || state.composer.text.trim() === '',
  )
  const isRunning = useAuiState((state) => state.thread.isRunning)

  const suggestion = conversationId ? (suggestions[conversationId] ?? null) : null
  const ghostText = enabled && composerEmpty && !isRunning ? suggestion : null

  const acceptGhost = useCallback(() => {
    if (!ghostText || !conversationId) return
    aui.composer.setText(ghostText)
    // 已接受的建议视为已消耗 — 清空后不要再次出现同一建议。
    setFollowup({ conversationId, suggestion: null })
    requestAnimationFrame(() => focusTextareaAtEnd(textareaRef.current))
  }, [aui, conversationId, ghostText, setFollowup, textareaRef])

  const handleGhostKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.defaultPrevented) return
      if (event.nativeEvent.isComposing) return
      if (!ghostText || !conversationId) return
      if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return

      if (event.key === 'ArrowRight' || event.key === 'End') {
        event.preventDefault()
        acceptGhost()
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        setFollowup({ conversationId, suggestion: null })
      }
    },
    [acceptGhost, conversationId, ghostText, setFollowup],
  )

  return { ghostText, handleGhostKeyDown, acceptGhost }
}
