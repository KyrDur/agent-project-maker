'use client'

import { useAtomValue } from 'jotai'
import { Loader2 } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { reconnectStateAtom } from '@/lib/stores/chat-store'

/** 仅在 SSE stream 中断并自动重连时显示的 badge。失败时通过 toast
 *  通知，并立即将 badge 恢复为 idle。 */
export function ReconnectIndicator() {
  const state = useAtomValue(reconnectStateAtom)
  const t = useTranslations('chat.reconnect')
  if (state !== 'reconnecting') return null
  return (
    <div className="flex justify-center pb-2">
      <div
        role="status"
        aria-live="polite"
        className="moldy-status-pill inline-flex items-center gap-2 px-3 py-1 text-xs text-muted-foreground"
      >
        <Loader2 className="size-3 animate-spin" />
        <span>{t('reconnecting')}</span>
      </div>
    </div>
  )
}
