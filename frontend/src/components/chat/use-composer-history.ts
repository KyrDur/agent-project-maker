'use client'

import { useCallback, useEffect, useMemo, useRef, type KeyboardEvent } from 'react'
import { useAui, useAuiState } from '@assistant-ui/react'
import {
  caretOnFirstLine,
  caretOnLastLine,
  collectUserHistory,
  historyItemAt,
  stepHistoryIndex,
} from '@/lib/chat/composer-history'
import { focusTextareaAtEnd } from './composer-focus'

// useAuiState(useSyncExternalStore, Object.is) 若 selector 在每个 snapshot 返回新
// 数组，就会产生无限重新渲染（tool-group-container.tsx 中已确认的陷阱）。
// 历史通过分隔符 join 成签名字符串来稳定，再用 useMemo 还原。
// U+0000 是不可能出现在聊天输入中的控制字符。
const HISTORY_SEP = '\u0000'

/**
 * ↑/↓ 输入器输入历史（readline 风格）。
 *
 * - ↑ 仅在光标位于第一行时，↓ 仅在最后一行时进入历史 —
 *   其他情况保留普通光标移动（多行安全）。
 * - 进入浏览时保存正在编写的 draft，向下越过最新记录后恢复。
 * - 编辑已调出的条目时（包括外部 setText）重置浏览状态。
 * - IME 组合中(isComposing)不介入 — 确保中文输入安全。
 *
 * 历史来源是当前线程的 user 消息，因此重新加载后仍保留。
 */
export function useComposerHistory(conversationId: string | null): {
  handleHistoryKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void
} {
  const aui = useAui()
  const historySig = useAuiState((state) =>
    collectUserHistory(state.thread.messages).join(HISTORY_SEP),
  )
  const history = useMemo(() => (historySig ? historySig.split(HISTORY_SEP) : []), [historySig])
  const composerText = useAuiState((state) => (state.composer.isEditing ? state.composer.text : ''))

  const indexRef = useRef(-1)
  const draftRef = useRef('')
  const lastAppliedRef = useRef<string | null>(null)

  // 对话切换时初始化浏览状态。
  useEffect(() => {
    indexRef.current = -1
    draftRef.current = ''
    lastAppliedRef.current = null
  }, [conversationId])

  // 用户编辑条目（或发送后清空）时退出浏览 — readline 简化模式。
  useEffect(() => {
    if (lastAppliedRef.current !== null && composerText !== lastAppliedRef.current) {
      indexRef.current = -1
      lastAppliedRef.current = null
    }
  }, [composerText])

  const applyText = useCallback(
    (textarea: HTMLTextAreaElement, next: string) => {
      lastAppliedRef.current = next
      aui.composer.setText(next)
      // setText → 外部值同步后将光标移到末尾。
      requestAnimationFrame(() => focusTextareaAtEnd(textarea))
    },
    [aui],
  )

  const handleHistoryKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.defaultPrevented) return
      if (event.nativeEvent.isComposing) return
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
      if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return
      if (history.length === 0) return

      const textarea = event.currentTarget
      const direction = event.key === 'ArrowUp' ? 'up' : 'down'
      if (direction === 'up' && !caretOnFirstLine(textarea.value, textarea.selectionStart)) return
      if (direction === 'down' && !caretOnLastLine(textarea.value, textarea.selectionEnd)) return

      const nextIndex = stepHistoryIndex(history.length, indexRef.current, direction)
      if (nextIndex === null) return

      event.preventDefault()
      if (indexRef.current === -1) {
        // 进入浏览 — 保存正在编写的内容。
        draftRef.current = textarea.value
      }
      indexRef.current = nextIndex
      const item = historyItemAt(history, nextIndex)
      applyText(textarea, item ?? draftRef.current)
    },
    [applyText, history],
  )

  return { handleHistoryKeyDown }
}
