'use client'

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { ChevronDownIcon, ChevronUpIcon, SearchIcon, XIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { jumpToMessage } from '@/components/chat/right-rail/jump-to-message'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  applySearchHighlights,
  clearSearchHighlights,
  collectMatchRanges,
} from '@/lib/chat/chat-search'

interface ChatSearchOverlayProps {
  onClose: () => void
  initialQuery?: string
  /** 搜索 scope。在挂载多个 thread 的页面（设置 fix/test tab）中限定到该 thread 的
   * viewport。以 ref 传入，避免渲染时访问 .current（在 handler 中读取）。
   * 若无则使用 document 全局。 */
  searchRootRef?: RefObject<HTMLElement | null>
}

/**
 * 对话内搜索(G6) Ctrl+F overlay。从 DOM anchor 收集文本并在客户端过滤，
 * 将匹配项通过 ``jumpToMessage`` 滚动 + 高亮。Enter/Shift+Enter 切换
 * 下一个/上一个，Esc 关闭。
 */
export function ChatSearchOverlay({
  initialQuery = '',
  onClose,
  searchRootRef,
}: ChatSearchOverlayProps) {
  const t = useTranslations('chat.search')
  const [query, setQuery] = useState(initialQuery)
  const [matchIds, setMatchIds] = useState<readonly string[]>([])
  const [rangeMap, setRangeMap] = useState<ReadonlyMap<string, Range[]>>(() => new Map())
  const [current, setCurrent] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
    return () => clearSearchHighlights()
  }, [])

  function handleChange(value: string) {
    setQuery(value)
    const ranges = collectMatchRanges(value, searchRootRef?.current ?? document)
    const ids = Array.from(ranges.keys())
    setMatchIds(ids)
    setRangeMap(ranges)
    setCurrent(0)
    applySearchHighlights(ranges, ids[0])
    if (ids.length > 0) jumpToMessage(ids[0])
  }

  useEffect(() => {
    if (!initialQuery) return
    const ranges = collectMatchRanges(initialQuery, searchRootRef?.current ?? document)
    const ids = Array.from(ranges.keys())
    setMatchIds(ids)
    setRangeMap(ranges)
    setCurrent(0)
    applySearchHighlights(ranges, ids[0])
    if (ids.length > 0) jumpToMessage(ids[0])
  }, [initialQuery, searchRootRef])

  const go = useCallback(
    (delta: number) => {
      if (matchIds.length === 0) return
      const next = (current + delta + matchIds.length) % matchIds.length
      setCurrent(next)
      applySearchHighlights(rangeMap, matchIds[next])
      jumpToMessage(matchIds[next])
    },
    [matchIds, current, rangeMap],
  )

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    } else if (event.key === 'Enter') {
      // IME 组合输入确认 Enter（中文/CJK）不会触发移动。
      if (event.nativeEvent.isComposing) return
      event.preventDefault()
      go(event.shiftKey ? -1 : 1)
    }
  }

  const hasQuery = query.trim().length > 0
  const total = matchIds.length
  const position = total === 0 ? 0 : current + 1

  return (
    <div
      role="search"
      className="moldy-popover sticky top-2 z-20 mx-auto flex w-full max-w-md items-center gap-1.5 rounded-lg px-3 py-1.5"
    >
      <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
      <Input
        ref={inputRef}
        value={query}
        onChange={(event) => handleChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('placeholder')}
        aria-label={t('placeholder')}
        className="h-8 flex-1 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
      />
      {hasQuery ? (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {t('count', { position, total })}
        </span>
      ) : null}
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => go(-1)}
        disabled={total === 0}
        aria-label={t('previous')}
      >
        <ChevronUpIcon className="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => go(1)}
        disabled={total === 0}
        aria-label={t('next')}
      >
        <ChevronDownIcon className="size-4" />
      </Button>
      <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label={t('close')}>
        <XIcon className="size-4" />
      </Button>
    </div>
  )
}
