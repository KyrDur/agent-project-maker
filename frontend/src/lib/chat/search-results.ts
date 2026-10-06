export interface SearchResultItem {
  title?: string
  url?: string
  link?: string
  snippet?: string
  content?: string
  description?: string
  score?: number
  published_date?: string
  /** 图片/购物结果的缩略图 URL（Naver thumbnail/image, Google image.thumbnailLink）。 */
  thumbnail?: string
  /** 购物结果的最低价（KRW）——Naver lprice。 */
  price?: number
  /** 购物结果的商家——Naver mallName。 */
  mall_name?: string
}

export interface SearchSourceSummary {
  title?: string
  url: string
  domain: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function parseJsonString(value: string): unknown {
  try {
    return JSON.parse(value) as unknown
  } catch {
    return undefined
  }
}

function thumbnailFrom(value: Record<string, unknown>): string | undefined {
  if (typeof value.thumbnail === 'string' && value.thumbnail) return value.thumbnail
  // Naver 购物中，`image` 是缩略图 URL 字符串。
  if (typeof value.image === 'string' && value.image.startsWith('http')) return value.image
  // Google 图片搜索中，`image: { thumbnailLink }` 是对象。
  if (isRecord(value.image) && typeof value.image.thumbnailLink === 'string') {
    return value.image.thumbnailLink
  }
  return undefined
}

function priceFrom(value: Record<string, unknown>): number | undefined {
  // Naver 购物 lprice 以数字字符串（"12900"）返回。
  const raw = value.lprice
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && /^\d+$/.test(raw)) return Number(raw)
  return undefined
}

function normalizeSearchItem(value: unknown): SearchResultItem | null {
  if (!isRecord(value)) return null
  const item: SearchResultItem = {}
  if (typeof value.title === 'string') item.title = value.title
  if (typeof value.url === 'string') item.url = value.url
  if (typeof value.link === 'string') item.link = value.link
  if (typeof value.snippet === 'string') item.snippet = value.snippet
  if (typeof value.content === 'string') item.content = value.content
  if (typeof value.description === 'string') item.description = value.description
  if (typeof value.score === 'number') item.score = value.score
  if (typeof value.published_date === 'string') item.published_date = value.published_date
  const thumbnail = thumbnailFrom(value)
  if (thumbnail) item.thumbnail = thumbnail
  const price = priceFrom(value)
  if (price !== undefined) item.price = price
  if (typeof value.mallName === 'string' && value.mallName) item.mall_name = value.mallName
  return Object.keys(item).length > 0 ? item : (value as SearchResultItem)
}

function normalizeSearchItems(value: unknown): SearchResultItem[] {
  if (!Array.isArray(value)) return []
  return value.map(normalizeSearchItem).filter((item): item is SearchResultItem => item !== null)
}

/**
 * 去掉 MCP 工具结果 wrapper（`[{type:'text', text:'<JSON>'}]`），
 * 返回内部 JSON。搜索类 MCP 工具（如 Tavily MCP）会以这种 shape 承载结果。
 */
function unwrapMcpTextContent(raw: readonly unknown[]): unknown {
  const textBlock = raw.find(
    (item): item is Record<string, unknown> =>
      isRecord(item) && item.type === 'text' && typeof item.text === 'string',
  )
  if (!textBlock) return undefined
  return parseJsonString(textBlock.text as string)
}

/** 提取搜索结果数组——Tavily/scripted 工具用 `results`，Naver/Google 用 `items`。 */
function itemsArrayFrom(raw: Record<string, unknown>): unknown[] | null {
  if (Array.isArray(raw.results)) return raw.results
  if (Array.isArray(raw.items)) return raw.items
  return null
}

export function parseSearchResults(raw: unknown): SearchResultItem[] {
  if (!raw) return []

  if (typeof raw === 'string') {
    const parsed = parseJsonString(raw)
    if (parsed !== undefined) return parseSearchResults(parsed)
    return [{ snippet: raw }]
  }

  if (Array.isArray(raw)) {
    const unwrapped = unwrapMcpTextContent(raw)
    if (unwrapped !== undefined) return parseSearchResults(unwrapped)
    return normalizeSearchItems(raw)
  }

  if (isRecord(raw)) {
    const items = itemsArrayFrom(raw)
    if (items) return normalizeSearchItems(items)
    const item = normalizeSearchItem(raw)
    return item ? [item] : []
  }

  return []
}

/** 提取 Tavily `answer`（摘要回答）——没有则返回 null。 */
export function searchAnswerFromResult(raw: unknown): string | null {
  if (typeof raw === 'string') {
    const parsed = parseJsonString(raw)
    return parsed === undefined ? null : searchAnswerFromResult(parsed)
  }
  if (Array.isArray(raw)) {
    const unwrapped = unwrapMcpTextContent(raw)
    return unwrapped === undefined ? null : searchAnswerFromResult(unwrapped)
  }
  if (!isRecord(raw)) return null
  const answer = raw.answer
  return typeof answer === 'string' && answer.trim() ? answer : null
}

/**
 * 检测结果是否属于"搜索结果 shape"——用于在 GenericToolFallback 中将名称不匹配的
 * 搜索工具（用户改名的 registry 工具、MCP 搜索工具）路由到 rich card。
 * 使用保守判定：`results|items` 数组的第一条记录必须同时含 title 与 url|link 字符串
 * 才返回 true。
 */
export function looksLikeSearchResults(raw: unknown): boolean {
  if (typeof raw === 'string') {
    const parsed = parseJsonString(raw)
    return parsed === undefined ? false : looksLikeSearchResults(parsed)
  }
  if (Array.isArray(raw)) {
    const unwrapped = unwrapMcpTextContent(raw)
    return unwrapped === undefined ? false : looksLikeSearchResults(unwrapped)
  }
  if (!isRecord(raw)) return false
  const items = itemsArrayFrom(raw)
  if (!items || items.length === 0) return false
  const first = items.find(isRecord)
  if (!first) return false
  const hasTitle = typeof first.title === 'string' && first.title.length > 0
  const hasUrl =
    (typeof first.url === 'string' && first.url.length > 0) ||
    (typeof first.link === 'string' && first.link.length > 0)
  return hasTitle && hasUrl
}

/**
 * 工具结果中的 URL 来自信任边界之外（MCP/外部 API）——在渲染为 `<a href>` 前
 * 只允许 http(s)，阻止 `javascript:` 等 scheme 注入。
 */
export function sanitizeExternalUrl(url: string | undefined): string | undefined {
  if (!url) return undefined
  const trimmed = url.trim()
  return /^https?:\/\//i.test(trimmed) ? trimmed : undefined
}

/** 缩略图除远程 http(s) 外，也允许本地（相对路径）asset。 */
export function sanitizeThumbnailUrl(url: string | undefined): string | undefined {
  if (!url) return undefined
  const trimmed = url.trim()
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) return trimmed
  return undefined
}

export function searchItemUrl(item: SearchResultItem): string | undefined {
  return sanitizeExternalUrl(item.url ?? item.link)
}

export function searchItemSnippet(item: SearchResultItem): string | undefined {
  return item.snippet ?? item.content ?? item.description
}

export function domainFromUrl(url: string): string {
  try {
    const hostname = new URL(url).hostname
    return hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function sourceSummariesFromResults(items: SearchResultItem[]): SearchSourceSummary[] {
  const seen = new Set<string>()
  const sources: SearchSourceSummary[] = []
  for (const item of items) {
    const url = searchItemUrl(item)
    if (!url || seen.has(url)) continue
    seen.add(url)
    sources.push({
      title: item.title,
      url,
      domain: domainFromUrl(url),
    })
  }
  return sources
}
