'use client'

import { useMemo, useState } from 'react'
import { LayersIcon, PlusIcon, SearchIcon, Trash2Icon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { DialogShell } from '@/components/shared/dialog-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useMiddlewares } from '@/lib/hooks/use-middlewares'
import type { MiddlewareRegistryItem } from '@/lib/types'

/**
 * 集成 middleware 添加 dialog。
 *
 * 与 SubAgents/ToolsSkills dialog 相同的 2-column（Current | Available）pattern。
 * 同时用于 visual-settings 的 MiddlewaresNode 和 form-mode 的 MiddlewaresBox。
 *
 * category filter（chip）显示在右侧 column 上方。
 */

type CategoryFilter = 'all' | 'context' | 'planning' | 'safety' | 'reliability' | 'provider'

const CATEGORY_FILTERS: CategoryFilter[] = [
  'all',
  'context',
  'planning',
  'safety',
  'reliability',
  'provider',
]

interface MiddlewaresDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  selectedTypes: Set<string>
  onToggleMiddleware: (type: string) => void
  /**
   * 可以从外部注入预加载的 catalog（visual-settings 由父级持有）。
   * 未提供时通过 useMiddlewares() 直接查询。
   */
  allMiddlewares?: MiddlewareRegistryItem[]
}

export function MiddlewaresDialog({
  open,
  onOpenChange,
  selectedTypes,
  onToggleMiddleware,
  allMiddlewares: providedAll,
}: MiddlewaresDialogProps) {
  const t = useTranslations('agent.visualSettings.addMiddlewaresDialog')
  const { data: fetched } = useMiddlewares()
  const allMiddlewares = useMemo(() => providedAll ?? fetched ?? [], [providedAll, fetched])
  const isLoading = !providedAll && !fetched

  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<CategoryFilter>('all')

  const selected = useMemo(
    () => allMiddlewares.filter((m) => selectedTypes.has(m.type)),
    [allMiddlewares, selectedTypes],
  )
  const available = useMemo(() => {
    const q = query.trim().toLowerCase()
    return allMiddlewares
      .filter((m) => !selectedTypes.has(m.type))
      .filter((m) => (category === 'all' ? true : m.category === category))
      .filter((m) =>
        !q
          ? true
          : m.display_name.toLowerCase().includes(q) ||
            m.description.toLowerCase().includes(q) ||
            m.type.toLowerCase().includes(q),
      )
  }, [allMiddlewares, selectedTypes, category, query])

  return (
    <DialogShell open={open} onOpenChange={onOpenChange} size="xl" height="tall">
      <DialogShell.Header
        icon={<LayersIcon className="size-5" />}
        title={t('title')}
        description={t('description')}
      />
      <DialogShell.Body>
        <div className="grid gap-6 md:grid-cols-2">
          <CurrentColumn
            isLoading={isLoading}
            selected={selected}
            onRemove={onToggleMiddleware}
            t={t}
          />
          <AvailableColumn
            isLoading={isLoading}
            available={available}
            query={query}
            onQueryChange={setQuery}
            category={category}
            onCategoryChange={setCategory}
            onAdd={onToggleMiddleware}
            tc={t}
          />
        </div>
      </DialogShell.Body>
    </DialogShell>
  )
}

function CurrentColumn({
  isLoading,
  selected,
  onRemove,
  t,
}: {
  isLoading: boolean
  selected: MiddlewareRegistryItem[]
  onRemove: (type: string) => void
  t: ReturnType<typeof useTranslations>
}) {
  return (
    <section className="flex min-h-0 flex-col">
      <h3 className="mb-3 text-sm font-medium">{t('current', { count: selected.length })}</h3>
      <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1 sm:h-[60vh]">
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : selected.length === 0 ? (
          <EmptyBox>{t('selectedEmpty')}</EmptyBox>
        ) : (
          selected.map((m) => (
            <SelectedCard key={m.type} item={m} onRemove={() => onRemove(m.type)} />
          ))
        )}
      </div>
    </section>
  )
}

function AvailableColumn({
  isLoading,
  available,
  query,
  onQueryChange,
  category,
  onCategoryChange,
  onAdd,
  tc,
}: {
  isLoading: boolean
  available: MiddlewareRegistryItem[]
  query: string
  onQueryChange: (v: string) => void
  category: CategoryFilter
  onCategoryChange: (v: CategoryFilter) => void
  onAdd: (type: string) => void
  tc: ReturnType<typeof useTranslations>
}) {
  return (
    <section className="flex min-h-0 flex-col">
      <h3 className="mb-3 text-sm font-medium">{tc('available')}</h3>
      <div className="relative mb-3">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder={tc('searchPlaceholder')}
          className="pl-9 focus-visible:border-input focus-visible:ring-0"
        />
      </div>
      <div className="mb-3 flex flex-wrap gap-1">
        {CATEGORY_FILTERS.map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => onCategoryChange(cat)}
            className={`rounded-full px-2.5 py-0.5 moldy-ui-caption font-medium transition-colors ${
              category === cat
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
          >
            {cat === 'all' ? tc('categories.all') : cat}
          </button>
        ))}
      </div>
      <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1 sm:h-[60vh]">
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : available.length === 0 ? (
          <EmptyBox>{query.trim().length > 0 ? tc('noResults') : tc('empty')}</EmptyBox>
        ) : (
          available.map((m) => (
            <AvailableCard key={m.type} item={m} addLabel={tc('add')} onAdd={() => onAdd(m.type)} />
          ))
        )}
      </div>
    </section>
  )
}

function SelectedCard({ item, onRemove }: { item: MiddlewareRegistryItem; onRemove: () => void }) {
  const t = useTranslations('agent.visualSettings.addMiddlewaresDialog')
  return (
    <MiddlewareCard
      item={item}
      align="center"
      subtitle={
        <p className="truncate font-mono moldy-ui-caption text-muted-foreground">{item.type}</p>
      }
      categoryBadgeVariant="secondary"
      action={
        <Button
          size="sm"
          variant="ghost"
          onClick={onRemove}
          className="shrink-0"
          aria-label={t('removeNamed', { name: item.display_name })}
        >
          <Trash2Icon className="size-3.5" />
          {t('remove')}
        </Button>
      }
    />
  )
}

function AvailableCard({
  item,
  addLabel,
  onAdd,
}: {
  item: MiddlewareRegistryItem
  addLabel: string
  onAdd: () => void
}) {
  const t = useTranslations('agent.visualSettings.addMiddlewaresDialog')
  return (
    <MiddlewareCard
      item={item}
      align="start"
      subtitle={
        <p className="line-clamp-2 moldy-ui-caption text-muted-foreground">{item.description}</p>
      }
      categoryBadgeVariant="outline"
      extraBadge={
        item.provider_specific ? (
          <Badge variant="secondary" className="shrink-0 moldy-ui-micro">
            {item.provider_specific}
          </Badge>
        ) : null
      }
      action={
        <Button
          size="sm"
          variant="outline"
          onClick={onAdd}
          className="shrink-0"
          aria-label={t('addNamed', { name: item.display_name })}
        >
          <PlusIcon className="size-3.5" />
          {addLabel}
        </Button>
      }
    />
  )
}

function MiddlewareCard({
  item,
  align,
  subtitle,
  categoryBadgeVariant,
  extraBadge,
  action,
}: {
  item: MiddlewareRegistryItem
  align: 'start' | 'center'
  subtitle: React.ReactNode
  categoryBadgeVariant: 'secondary' | 'outline'
  extraBadge?: React.ReactNode
  action: React.ReactNode
}) {
  return (
    <div
      className={`flex gap-3 rounded-lg border p-3 ${
        align === 'center' ? 'items-center' : 'items-start'
      }`}
    >
      <span className="moldy-dashboard-action-icon moldy-status-warn flex size-8 shrink-0 items-center justify-center rounded-md">
        <LayersIcon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium">{item.display_name}</p>
          <Badge variant={categoryBadgeVariant} className="shrink-0 moldy-ui-micro">
            {item.category}
          </Badge>
          {extraBadge}
        </div>
        {subtitle}
      </div>
      {action}
    </div>
  )
}

function EmptyBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-32 items-center justify-center rounded-lg border border-dashed text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}
