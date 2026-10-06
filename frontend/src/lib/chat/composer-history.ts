/**
 * Composer 输入历史（↑/↓）——readline 风格的纯逻辑。
 *
 * 历史来源是当前 thread 的 user 消息（服务器持久化 → reload 后仍存在），
 * 探索状态由 hook（use-composer-history）保存在 ref 中。该模块只负责文本提取、
 * dedupe、插入符行判定和索引步进，以简化单元测试。
 */

interface MessageLike {
  readonly role?: unknown
  readonly content?: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** 从 assistant-ui ThreadMessage content（字符串 | part 数组）中提取纯文本。 */
export function extractMessageText(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .map((part) => {
      if (typeof part === 'string') return part
      if (isRecord(part) && part.type === 'text' && typeof part.text === 'string') {
        return part.text
      }
      return ''
    })
    .filter(Boolean)
    .join('\n')
}

/**
 * user 消息 → 历史列表（从旧到新）。排除空项 +
 * 移除连续重复项（HISTCONTROL ignoredups）。如果输入不是数组（如部分 mock），
 * 安全回退为空历史。
 */
export function collectUserHistory(messages: unknown): string[] {
  if (!Array.isArray(messages)) return []
  const history: string[] = []
  for (const message of messages) {
    if (!isRecord(message) || (message as MessageLike).role !== 'user') continue
    const text = extractMessageText((message as MessageLike).content).trim()
    if (!text) continue
    if (history[history.length - 1] === text) continue
    history.push(text)
  }
  return history
}

/** 插入符是否位于第一行——将 ↑ 升级为历史探索的条件。 */
export function caretOnFirstLine(value: string, selectionStart: number): boolean {
  return !value.slice(0, selectionStart).includes('\n')
}

/** 插入符是否位于最后一行——将 ↓ 升级为历史探索的条件。 */
export function caretOnLastLine(value: string, selectionEnd: number): boolean {
  return !value.slice(selectionEnd).includes('\n')
}

/**
 * 历史索引步进。index 为 -1（不在探索）/ 0（最新）/ 1（再前一条）…
 * 超过边界返回 null（不移动）。
 */
export function stepHistoryIndex(
  historyLength: number,
  index: number,
  direction: 'up' | 'down',
): number | null {
  if (historyLength === 0) return null
  if (direction === 'up') {
    const next = index + 1
    return next < historyLength ? next : null
  }
  if (index <= -1) return null
  return index - 1
}

/** index 指向的历史项（-1 时为 null = draft 恢复点）。 */
export function historyItemAt(history: readonly string[], index: number): string | null {
  if (index < 0 || index >= history.length) return null
  return history[history.length - 1 - index]
}
