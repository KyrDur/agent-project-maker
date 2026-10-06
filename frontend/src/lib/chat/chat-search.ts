/**
 * 对话内搜索（G6）。从已渲染消息的 DOM 锚点（``data-moldy-message-id``）中
 * 收集搜索词位置的 Range，通过 CSS Custom Highlight API 高亮，并用
 * ``jumpToMessage`` 跳转到匹配项。不论 v3 聊天的消息源是 stream/envelope，
 * 都搜索"屏幕上可见的正文"。通过 ``root`` 限定到特定 thread viewport。
 */

const HIGHLIGHT_MATCH = 'moldy-search-match'
const HIGHLIGHT_CURRENT = 'moldy-search-current'
const HIGHLIGHT_STYLE_ID = 'moldy-search-highlight-style'

/** 搜索时排除非消息正文文本：元数据行（复制/编辑/分支选择器/
 *  时间戳/token 数）和 sr-only 标签。否则"复制"/"编辑"会匹配所有消息，
 *  数字也会匹配元数据，导致计数膨胀并跳到不可见文本。 */
function isNonBodyText(node: Node): boolean {
  const parent = node.parentElement
  if (!parent) return false
  return (
    parent.closest('[data-moldy-message-meta-row="true"]') !== null ||
    parent.closest('.sr-only') !== null
  )
}

function matchRangesInElement(element: Element, needle: string): Range[] {
  const ranges: Range[] = []
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      isNonBodyText(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  })
  let node = walker.nextNode()
  while (node) {
    const lower = (node.textContent ?? '').toLowerCase()
    let index = lower.indexOf(needle)
    while (index !== -1) {
      const range = document.createRange()
      range.setStart(node, index)
      range.setEnd(node, index + needle.length)
      ranges.push(range)
      index = lower.indexOf(needle, index + needle.length)
    }
    node = walker.nextNode()
  }
  return ranges
}

/**
 * 在消息锚点内部按 messageId 收集 query 每次出现位置的 Range
 * （忽略大小写，按文本节点——跨 markdown 渲染分割节点的短语会漏掉）。
 * 传入 ``root`` 以限定到对应 thread viewport（应对设置页面双重挂载）。
 * 返回 map 的 key 集合 = 匹配消息 id（DOM 顺序）。
 */
export function collectMatchRanges(
  query: string,
  root: ParentNode = document,
): Map<string, Range[]> {
  const map = new Map<string, Range[]>()
  const needle = query.trim().toLowerCase()
  if (!needle) return map
  root.querySelectorAll('[data-moldy-message-id]').forEach((el) => {
    const id = el.getAttribute('data-moldy-message-id')
    if (!id) return
    const ranges = matchRangesInElement(el, needle)
    if (ranges.length > 0) map.set(id, ranges)
  })
  return map
}

function highlightApiSupported(): boolean {
  return (
    typeof Highlight !== 'undefined' && typeof CSS !== 'undefined' && CSS.highlights !== undefined
  )
}

function ensureHighlightStyles(): void {
  if (typeof document === 'undefined' || document.getElementById(HIGHLIGHT_STYLE_ID)) return
  const style = document.createElement('style')
  style.id = HIGHLIGHT_STYLE_ID
  style.textContent = `
::highlight(${HIGHLIGHT_MATCH}) {
  background-color: color-mix(in srgb, var(--status-warn) 28%, transparent);
}

::highlight(${HIGHLIGHT_CURRENT}) {
  background-color: var(--status-warn);
  color: var(--background);
}
`
  document.head.appendChild(style)
}

/**
 * 使用 CSS Custom Highlight API 内联高亮搜索词。当前匹配消息的
 * Range 注册为 ``moldy-search-current``，其余匹配注册为 ``moldy-search-match``。
 * 不支持的浏览器中为 no-op，仅跳转高亮（moldy-jump-highlight）生效。
 */
export function applySearchHighlights(
  rangeMap: ReadonlyMap<string, readonly Range[]>,
  currentId: string | undefined,
): void {
  if (!highlightApiSupported()) return
  ensureHighlightStyles()
  const matchHighlight = new Highlight()
  const currentHighlight = new Highlight()
  for (const [id, ranges] of rangeMap) {
    const target = id === currentId ? currentHighlight : matchHighlight
    for (const range of ranges) target.add(range)
  }
  CSS.highlights.set(HIGHLIGHT_MATCH, matchHighlight)
  CSS.highlights.set(HIGHLIGHT_CURRENT, currentHighlight)
}

export function clearSearchHighlights(): void {
  if (!highlightApiSupported()) return
  CSS.highlights.delete(HIGHLIGHT_MATCH)
  CSS.highlights.delete(HIGHLIGHT_CURRENT)
}
