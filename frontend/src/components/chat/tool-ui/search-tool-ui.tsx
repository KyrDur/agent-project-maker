'use client'

import type { ToolCallMessagePartProps } from '@assistant-ui/react'
import { useTranslations } from 'next-intl'
import { ExternalLinkIcon, GlobeIcon, SearchIcon, SparklesIcon } from 'lucide-react'
import { CollapsiblePill, pillStatusFromAssistantUi } from './collapsible-pill'
import { useIsToolGroupChild } from './tool-group-child-context'
import {
  parseSearchResults,
  sanitizeThumbnailUrl,
  searchAnswerFromResult,
  searchItemSnippet,
  searchItemUrl,
  type SearchResultItem,
} from './search-tool-data'
import { formatDisplayNumber } from '@/lib/utils/display-format'

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

interface SearchArgs {
  query?: string
  [key: string]: unknown
}

// ──────────────────────────────────────────────
// SearchResultCard
// ──────────────────────────────────────────────

function SearchResultCard({ item }: { item: SearchResultItem }) {
  const t = useTranslations('chat.toolCall.search')
  const url = searchItemUrl(item)
  const thumbnail = sanitizeThumbnailUrl(item.thumbnail)
  const title = item.title
  const snippet = searchItemSnippet(item)

  // 只有文本、没有结构的情况
  if (!title && !url) {
    return (
      <div className="rounded-lg border border-border/40 bg-background p-2">
        <p className="moldy-ui-caption leading-relaxed text-foreground/80 line-clamp-3">
          {snippet ?? JSON.stringify(item)}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border/40 bg-background p-2 transition-colors hover:bg-accent/50">
      <div className="flex items-start gap-2">
        {thumbnail ? (
          // 搜索 API 缩略图来自任意远程域名，因此不用 next/image，而使用普通 img
          // 并 lazy 加载。（协议由 sanitizeThumbnailUrl 限制。）
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnail}
            alt={title ?? t('thumbnailAlt')}
            loading="lazy"
            referrerPolicy="no-referrer"
            className="size-12 shrink-0 rounded-md border border-border/40 object-cover"
            data-moldy-search-thumbnail="true"
          />
        ) : (
          <GlobeIcon className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          {title && (
            <div className="flex items-center gap-1">
              {url ? (
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="truncate moldy-ui-caption font-medium text-primary-strong hover:underline"
                >
                  {title}
                </a>
              ) : (
                <span className="truncate moldy-ui-caption font-medium">{title}</span>
              )}
              {url && <ExternalLinkIcon className="size-2.5 shrink-0 text-muted-foreground" />}
            </div>
          )}
          {url && <div className="truncate moldy-ui-micro text-muted-foreground">{url}</div>}
          {item.price !== undefined && (
            <div className="mt-0.5 flex items-center gap-1.5" data-moldy-search-price="true">
              <span className="moldy-ui-caption font-semibold text-foreground">
                {t('price', { price: formatDisplayNumber(item.price) })}
              </span>
              {item.mall_name ? (
                <span className="moldy-ui-micro text-muted-foreground">{item.mall_name}</span>
              ) : null}
            </div>
          )}
          {snippet && (
            <p className="mt-0.5 moldy-ui-caption leading-relaxed text-foreground/70 line-clamp-2">
              {snippet}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// 共享 render 函数 — 也复用于 GenericToolFallback 的 shape 路由。
// ──────────────────────────────────────────────

export function SearchRender({
  args,
  result,
  status,
}: {
  args: SearchArgs
  result?: unknown
  status: { readonly type: string }
}) {
  const t = useTranslations('chat.toolCall.search')
  // 分组内的搜索子项默认折叠（只显示查询标题）— 如果 N 个都把卡片展开，
  // 会过于冗长。单独搜索（非分组）仍像现在一样直接展开结果。
  const isGroupChild = useIsToolGroupChild()
  const isRunning = status.type === 'running'
  const items = parseSearchResults(result)
  const answer = isRunning ? null : searchAnswerFromResult(result)
  const title = args?.query ? `"${args.query}"` : t('defaultTitle')
  const meta = isRunning
    ? t('running')
    : items.length > 0
      ? t('count', { count: items.length })
      : undefined

  const hasBody = !isRunning && (items.length > 0 || Boolean(answer))
  const body = hasBody ? (
    <div className="space-y-1.5">
      {answer ? (
        <div
          className="rounded-lg border border-primary-strong/25 bg-primary/5 p-2.5"
          data-moldy-search-answer="true"
        >
          <div className="mb-1 flex items-center gap-1.5 moldy-ui-micro font-semibold uppercase tracking-wider text-primary-strong">
            <SparklesIcon className="size-3" aria-hidden />
            {t('answer')}
          </div>
          <p className="moldy-ui-caption leading-relaxed text-foreground/85">{answer}</p>
        </div>
      ) : null}
      {items.slice(0, 5).map((item, i) => (
        <SearchResultCard key={i} item={item} />
      ))}
    </div>
  ) : undefined

  return (
    <CollapsiblePill
      kind="tool"
      leadingIcon={SearchIcon}
      status={pillStatusFromAssistantUi(status.type)}
      title={title}
      meta={meta}
      defaultExpanded={!isGroupChild && hasBody}
    >
      {body}
    </CollapsiblePill>
  )
}

// ──────────────────────────────────────────────
// SearchToolUI — web_search + Tavily + Naver + Google
//
// toolName 必须与运行时名称一致才能匹配。registry 工具的运行时名称
// `_safe_tool_name(Tool.name || display_name, fallback=definition_key)`
// (backend tool_factory.py) — 韩文显示名会在清理时全部被移除，
// 因而回退到 definition_key，所以实际流过来的是 definition_key(naver_search_blog 等)。
// 如果用户将工具名改为 ASCII 导致名称不匹配，
// 则由 GenericToolFallback 的基于 shape 的路由(looksLikeSearchResults)处理。
// ──────────────────────────────────────────────

export const SEARCH_TOOL_UI_NAMES = [
  // builtin + 技能依赖(tavily_search) + E2E scripted
  'tavily_search',
  'web_search',
  // registry definition_key (Naver 5 类)
  'naver_search_blog',
  'naver_search_news',
  'naver_search_image',
  'naver_search_shop',
  'naver_search_local',
  // registry definition_key (Google 3 类)
  'google_search_web',
  'google_search_image',
  'google_search_news',
  // 过去的硬编码名称 — 虽然从未与实际运行时名称匹配，但为兼容旧对话
  // 快照/测试 fixture 而保留。
  'naver_blog_search',
  'naver_news_search',
  'google_search',
  'google_news_search',
] as const

export function SearchToolUI(props: ToolCallMessagePartProps<SearchArgs, unknown>) {
  return <SearchRender {...props} />
}
