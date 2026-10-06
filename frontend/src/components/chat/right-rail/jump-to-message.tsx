'use client'

import { useCallback, useSyncExternalStore } from 'react'
import { MessageSquareIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'

const HIGHLIGHT_MS = 1500

/**
 * 查询 `[data-moldy-message-id="<id>"]` anchor。消息 id 属于 UUID 系列，但
 * 为保证 selector 安全，使用 ``CSS.escape``（若存在）进行转义。
 */
function findMessageAnchor(messageId: string): HTMLElement | null {
  if (typeof document === 'undefined') return null
  const escaped =
    typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
      ? CSS.escape(messageId)
      : messageId.replace(/["\\]/g, '\\$&')
  const el = document.querySelector(`[data-moldy-message-id="${escaped}"]`)
  return el instanceof HTMLElement ? el : null
}

/** 判断消息是否存在于当前已加载的 transcript（无虚拟化）。 */
export function messageAnchorExists(messageId: string): boolean {
  return findMessageAnchor(messageId) !== null
}

/**
 * 在已加载 transcript 中滚动到该消息 + 短暂高亮。
 * 若无 anchor（其他页面的消息），不执行任何操作并返回 false。
 */
export function jumpToMessage(messageId: string): boolean {
  const el = findMessageAnchor(messageId)
  if (!el) return false
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  el.classList.add('moldy-jump-highlight')
  window.setTimeout(() => el.classList.remove('moldy-jump-highlight'), HIGHLIGHT_MS)
  return true
}

// One shared MutationObserver for ALL jump buttons (the rail can render many
// files). Per-button observers would each re-process every streamed-token DOM
// mutation; instead a single observer notifies subscribers, coalesced to one
// notification per animation frame so a burst of mutations costs one pass.
const anchorListeners = new Set<() => void>()
let anchorObserver: MutationObserver | null = null
let anchorNotifyScheduled = false

function flushAnchorListeners(): void {
  anchorNotifyScheduled = false
  for (const listener of anchorListeners) listener()
}

function scheduleAnchorNotify(): void {
  if (anchorNotifyScheduled) return
  anchorNotifyScheduled = true
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(flushAnchorListeners)
  else flushAnchorListeners()
}

function subscribeAnchors(onStoreChange: () => void): () => void {
  if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return () => {}
  anchorListeners.add(onStoreChange)
  if (!anchorObserver) {
    anchorObserver = new MutationObserver(scheduleAnchorNotify)
    anchorObserver.observe(document.body, { childList: true, subtree: true })
  }
  return () => {
    anchorListeners.delete(onStoreChange)
    if (anchorListeners.size === 0 && anchorObserver) {
      anchorObserver.disconnect()
      anchorObserver = null
    }
  }
}

/**
 * 在 DOM 中订阅消息 anchor 是否存在于当前 transcript。
 * transcript 未虚拟化，因此只有"已加载消息"才有 anchor。
 * 用 ``useSyncExternalStore`` 读取外部 mutable source(DOM)，无需 effect-setState
 * 即可在 render 中获取 snapshot，并通过共享 observer 在消息延迟加载后也能更新。
 */
function useMessageInLoadedPage(messageId: string | null | undefined): boolean {
  const getSnapshot = useCallback(
    () => (messageId ? messageAnchorExists(messageId) : false),
    [messageId],
  )
  return useSyncExternalStore(subscribeAnchors, getSnapshot, () => false)
}

/**
 * 从文件 → 对话消息的跳转 action。
 * - 消息在已加载页面中时显示"前往留言处"按钮。
 * - 不在时（更早页面）显示禁用的"早些时候的消息"标签 + 原生 tooltip。
 * - 没有 message_id 时不渲染。
 */
export function JumpToMessageButton({
  messageId,
  className,
}: {
  messageId: string | null | undefined
  className?: string
}) {
  const t = useTranslations('chat.files')
  const inLoadedPage = useMessageInLoadedPage(messageId)

  if (!messageId) return null

  if (!inLoadedPage) {
    return (
      <span
        className={cn(
          'inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground/70',
          className,
        )}
        title={t('notInLoaded')}
        aria-disabled="true"
      >
        <MessageSquareIcon className="size-3.5" aria-hidden />
        {t('notInLoaded')}
      </span>
    )
  }

  return (
    <button
      type="button"
      onClick={() => jumpToMessage(messageId)}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
        'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
    >
      <MessageSquareIcon className="size-3.5" aria-hidden />
      {t('jumpToMessage')}
    </button>
  )
}
