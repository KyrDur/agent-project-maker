'use client'

import { useEffect } from 'react'
import { useSetAtom } from 'jotai'
import { useRouter } from 'next/navigation'
import { shortcutPreviewActiveAtom } from '@/lib/stores/chat-navigator-store'

interface ChatNavigatorShortcutsOptions {
  onOpenQuickSwitcher: () => void
  onEscape: () => void
}

function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  // navigator.platform 已 deprecated — 对返回空值的浏览器用 userAgent 判断
  return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent)
}

export function formatShortcutLabel(index: number, mac = isMacPlatform()): string {
  return mac ? `⌘⇧${index}` : `Ctrl+Shift+${index}`
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
}

function sessionHrefAt(index: number): string | null {
  // 只计算屏幕上可见的行，避免折叠分组/隐藏面板的行推动索引
  const rows = Array.from(
    document.querySelectorAll<HTMLElement>('[data-chat-session-href]'),
  ).filter((row) => (typeof row.checkVisibility === 'function' ? row.checkVisibility() : true))
  const row = rows[index - 1]
  return row?.dataset.chatSessionHref ?? null
}

export function useChatNavigatorShortcuts({
  onOpenQuickSwitcher,
  onEscape,
}: ChatNavigatorShortcutsOptions): void {
  const router = useRouter()
  const setShortcutPreviewActive = useSetAtom(shortcutPreviewActiveAtom)

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // IME 组合中的按键不是快捷键（保护中文等组合输入）
      if (event.isComposing) return
      if (event.metaKey || event.ctrlKey) setShortcutPreviewActive(true)
      if ((event.metaKey || event.ctrlKey) && event.code === 'KeyK') {
        event.preventDefault()
        onOpenQuickSwitcher()
        return
      }
      // Shift 组合时 event.key 会变成布局对应字符('!')，因此通过物理键代码判断
      const digitMatch = /^Digit([1-9])$/.exec(event.code)
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && digitMatch) {
        // 输入元素聚焦时进行导航会丢失正在编写的内容（Cmd+K 命令面板仍保持全局）
        if (isEditableTarget(event.target)) return
        const href = sessionHrefAt(Number(digitMatch[1]))
        if (href) {
          event.preventDefault()
          router.push(href)
        }
        return
      }
      if (event.key === 'Escape') onEscape()
    }

    function handleKeyUp(event: KeyboardEvent) {
      if (!event.metaKey && !event.ctrlKey) setShortcutPreviewActive(false)
    }

    function handleBlur() {
      setShortcutPreviewActive(false)
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    window.addEventListener('blur', handleBlur)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
      window.removeEventListener('blur', handleBlur)
    }
  }, [onEscape, onOpenQuickSwitcher, router, setShortcutPreviewActive])
}
