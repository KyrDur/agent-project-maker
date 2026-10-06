/**
 * Tool-call group container 元数据。
 *
 * 在通用分组（`MessagePrimitive.GroupedParts`）中将连续相同工具合并为一个
 * container 时，定义要使用的标签/是否可分组。分组逻辑本身由
 * 官方 API 负责，本模块只负责"各工具显示标签"和"排除分组的对象"。
 */

/**
 * toolName → `chat.toolGroup.labels.*` i18n key。未映射时返回 `null`，
 * 调用方将 toolName 自身作为 fallback 标签。（只映射搜索类/文件类——
 * 其他工具分组频率较低，使用 toolName fallback 即可。）
 */
const TOOL_LABEL_KEYS: Readonly<Record<string, string>> = {
  tavily_search: 'webSearch',
  web_search: 'webSearch',
  // registry definition_key——runtime 工具名的实际 fallback 值（tool_factory）。
  naver_search_blog: 'naverBlog',
  naver_search_news: 'naverNews',
  naver_search_image: 'naverImage',
  naver_search_shop: 'naverShop',
  naver_search_local: 'naverLocal',
  google_search_web: 'googleSearch',
  google_search_image: 'googleImage',
  google_search_news: 'googleNews',
  // 过去硬编码的名称——用于兼容 fixture/snapshot。
  naver_blog_search: 'naverBlog',
  naver_news_search: 'naverNews',
  google_search: 'googleSearch',
  google_news_search: 'googleNews',
  read_file: 'readFile',
  write_file: 'writeFile',
  edit_file: 'editFile',
}

/** toolName 的 group label i18n key。没有则为 null（由调用方使用 toolName fallback）。 */
export function toolGroupLabelKey(toolName: string): string | null {
  return TOOL_LABEL_KEYS[toolName] ?? null
}

/**
 * 搜索类工具。结果 shape 为 `{results:[{title,url}]}`，因此可在 group header 中显示来源
 * domain badge + "来源 N 个"汇总。其他（文件类等）没有来源概念，
 * 因此不添加汇总行。
 */
const SEARCH_TOOLS: ReadonlySet<string> = new Set([
  'tavily_search',
  'web_search',
  'naver_search_blog',
  'naver_search_news',
  'naver_search_image',
  'naver_search_shop',
  'naver_search_local',
  'google_search_web',
  'google_search_image',
  'google_search_news',
  'naver_blog_search',
  'naver_news_search',
  'google_search',
  'google_news_search',
])

/** 判断该工具是否为搜索类（可在 group header 显示来源汇总的工具）。 */
export function isSearchTool(toolName: string): boolean {
  return SEARCH_TOOLS.has(toolName)
}

/**
 * 从分组中排除的工具。像 ask_user 一样，每次调用都是与用户独立交互，
 * 不应合并成一组。`request_approval` 例外，属于可分组对象——用于把一个
 * interrupt 的 N 张批准卡合并为"等待批准 N 项 + 全部批准"的 container
 * （GroupedApprovalCard）。其余普通工具连续 N≥2 时会分组。
 */
const NON_GROUPABLE_TOOLS: ReadonlySet<string> = new Set(['ask_user', 'ask_clarifying_question'])

/** 判断该工具是否可以放入 group container。 */
export function isGroupableTool(toolName: string): boolean {
  return !NON_GROUPABLE_TOOLS.has(toolName)
}

/** 每次调用的代表性参数 key——用于 group 子项标题，按此顺序寻找"区分值"。 */
const CHILD_LABEL_ARG_KEYS = [
  'query',
  'q',
  'file_path',
  'path',
  'url',
  'expression',
  'keyword',
  'date',
  'timezone',
  'command',
  'name',
] as const

function shortenLabel(value: string): string {
  const trimmed = value.trim().replace(/\s+/g, ' ')
  return trimmed.length > 48 ? `${trimmed.slice(0, 47)}…` : trimmed
}

/** 从 JSON 值中取第一个标量（字符串/数字/布尔）——比 raw JSON 更易读。 */
function firstScalar(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    for (const item of value) {
      const scalar = firstScalar(item)
      if (scalar) return scalar
    }
    return null
  }
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) {
      const scalar = firstScalar(item)
      if (scalar) return scalar
    }
  }
  return null
}

function resultPreview(result: unknown): string | null {
  if (typeof result !== 'string') return null
  const text = result.trim()
  if (!text) return null
  // JSON 对象/数组结果会抽取一个代表性标量，只显示值而不是 `{"now_iso": "…",`。
  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      const scalar = firstScalar(JSON.parse(text))
      if (scalar) return shortenLabel(scalar)
    } catch {
      // JSON 파싱 실패 → 아래 첫 줄 폴백.
    }
  }
  const firstLine = text.split('\n').find((line) => line.trim().length > 0)
  return firstLine ? shortenLabel(firstLine) : null
}

/**
 * group 子 pill 的标题——不再显示工具名（group header 已有），而是展示"这次调用做了什么"。
 * 顺序：代表性参数 → 任意第一个字符串参数 → 结果预览。都没有合适内容时
 * 返回 null（调用方回退为工具名）。
 */
export function toolCallChildLabel(
  args: Record<string, unknown> | undefined,
  result: unknown,
): string | null {
  for (const key of CHILD_LABEL_ARG_KEYS) {
    const value = args?.[key]
    if (typeof value === 'string' && value.trim()) return shortenLabel(value)
  }
  for (const value of Object.values(args ?? {})) {
    if (typeof value === 'string' && value.trim()) return shortenLabel(value)
  }
  return resultPreview(result)
}
