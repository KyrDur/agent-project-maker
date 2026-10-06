'use client'

import { useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import {
  type ColumnDef,
  type ColumnFiltersState,
  type RowSelectionState,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { SearchInput } from '@/components/shared/search-input'
import { EmptyState } from '@/components/shared/empty-state'
import { reportClientWarning } from '@/lib/logging/client-logger'

export interface FilterDef {
  /** column id (must match a column.accessorKey/id in the columns array) */
  columnId: string
  label: string
  options: Array<{ value: string; label: string }>
}

export interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[]
  data: T[]
  searchable?: boolean
  searchPlaceholder?: string
  /**
   * Custom global filter function. Defaults to substring-match across the
   * `name` and `description` fields if present.
   */
  globalFilterFn?: (row: T, query: string) => boolean
  filters?: FilterDef[]
  onRowClick?: (row: T) => void
  pageSize?: number
  loading?: boolean
  emptyTitle?: string
  emptyDescription?: string
  emptyAction?: ReactNode
  /**
   * When true, the leading column becomes a per-row checkbox and the header
   * gets a select-all checkbox. The parent receives selection updates via
   * `onRowSelectionChange`.
   */
  enableRowSelection?: boolean
  onRowSelectionChange?: (rows: T[]) => void
  /**
   * Controlled selection state. Pass together with
   * `onRowSelectionStateChange` when the parent needs to reset/own the
   * selection (e.g. clear after a bulk action) without remounting the table —
   * a key-remount would also wipe sorting and the page index.
   */
  rowSelectionState?: RowSelectionState
  onRowSelectionStateChange?: (
    updater: RowSelectionState | ((previous: RowSelectionState) => RowSelectionState),
  ) => void
  /** Stable row identifier for selection state. Defaults to `row.id`. */
  getRowId?: (row: T, index: number) => string
  /**
   * Optional toolbar slot rendered on the right of the search/filter row.
   * Use it to render bulk actions ("Test Selected", "Delete selected"...).
   */
  toolbar?: ReactNode
}

export function DataTable<T>({
  columns,
  data,
  searchable = false,
  searchPlaceholder,
  globalFilterFn,
  filters,
  onRowClick,
  pageSize = 10,
  loading = false,
  emptyTitle,
  emptyDescription,
  emptyAction,
  enableRowSelection = false,
  onRowSelectionChange,
  rowSelectionState,
  onRowSelectionStateChange,
  getRowId,
  toolbar,
}: DataTableProps<T>) {
  const t = useTranslations('common.dataTable')
  const resolvedEmptyTitle = emptyTitle ?? t('emptyDefault')
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [search, setSearch] = useState('')
  const [internalRowSelection, setInternalRowSelection] = useState<RowSelectionState>({})
  const rowSelection = rowSelectionState ?? internalRowSelection
  const setRowSelection = onRowSelectionStateChange ?? setInternalRowSelection
  const deferredSearch = useDeferredValue(search)
  const normalizedSearch = useMemo(() => deferredSearch.trim().toLowerCase(), [deferredSearch])

  const filtered = useMemo(() => {
    if (!normalizedSearch) return data

    return data.filter((row) => {
      if (globalFilterFn) return globalFilterFn(row, normalizedSearch)
      const r = row as unknown as Record<string, unknown>
      const name = String(r.name ?? '').toLowerCase()
      const description = String(r.description ?? '').toLowerCase()
      return name.includes(normalizedSearch) || description.includes(normalizedSearch)
    })
  }, [data, globalFilterFn, normalizedSearch])

  // Inject the leading selection column when requested. Wrapped in a separate
  // const so the original `columns` prop is preserved for downstream use.
  const tableColumns = useMemo(() => {
    if (!enableRowSelection) return columns

    return [
      {
        id: '__select',
        header: ({ table }) => (
          <Checkbox
            aria-label={t('selectAll')}
            checked={table.getIsAllPageRowsSelected()}
            indeterminate={table.getIsSomePageRowsSelected()}
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(Boolean(value))}
            onClick={(e) => e.stopPropagation()}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            aria-label={t('selectRow')}
            checked={row.getIsSelected()}
            disabled={!row.getCanSelect()}
            onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
            onClick={(e) => e.stopPropagation()}
          />
        ),
        enableSorting: false,
        size: 32,
      } as ColumnDef<T, unknown>,
      ...columns,
    ] as ColumnDef<T, unknown>[]
  }, [columns, enableRowSelection, t])

  // 行 id 推导的单一来源 — table(getRowId)·prune·notify 必须使用相同规则，
  // 否则 id 空间会分裂。index 回退在 filtered/data 中可能指向不同的行，
  // 因此将**基于 data 分配的 id 固定到对象引用 Map**，即使 table
  // 接收 filtered 中的同一对象也能得到相同 id（真正的单一 id 空间，R7）。
  // index 回退本身对数据重排仍不稳定 — 保留 dev 警告。
  const resolveRowId = useMemo(() => {
    if (getRowId) return getRowId
    return (row: T, index: number) => {
      const r = row as unknown as { id?: string }
      return r.id ?? String(index)
    }
  }, [getRowId])
  const rowIdByObject = useMemo(() => {
    const map = new Map<T, string>()
    data.forEach((row, index) => map.set(row, resolveRowId(row, index)))
    return map
  }, [data, resolveRowId])
  const rowIdOf = (row: T, index: number) => rowIdByObject.get(row) ?? resolveRowId(row, index)
  if (
    process.env.NODE_ENV !== 'production' &&
    enableRowSelection &&
    !getRowId &&
    data.some((row) => (row as unknown as { id?: string }).id === undefined)
  ) {
    reportClientWarning(
      'DataTable',
      'DataTable: enableRowSelection with id-less rows needs an explicit getRowId — index fallback ids are unstable when the data reorders.',
    )
  }

  const table = useReactTable({
    data: filtered,
    columns: tableColumns,
    state: { sorting, columnFilters, rowSelection },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onRowSelectionChange: setRowSelection,
    enableRowSelection,
    // filtered 的行与 data 使用相同对象引用 — 通过 Map 查询返回基于 data 的 id。
    getRowId: rowIdOf,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    // 每次数据更新(refetch/删除)时不要都跳回第 1 页 — 与引入 controlled
    // selection 的理由("保持排序·分页")采用同一契约。超出范围的
    // pageIndex 由下面的 effect 限制到最后一页。
    autoResetPageIndex: false,
    initialState: { pagination: { pageSize } },
  })

  useEffect(() => {
    // 加载中闪烁（查询键变更 → data 短暂为 []）期间若执行限制，会重置到第 0 页，
    // 与 autoResetPageIndex:false 的目的（保持分页）自相矛盾 (R5)。
    if (loading) return
    const pageCount = table.getPageCount()
    const pageIndex = table.getState().pagination.pageIndex
    if (pageIndex > 0 && pageIndex >= pageCount) {
      table.setPageIndex(Math.max(0, pageCount - 1))
    }
    // filtered·columnFilters 是 pagination 输入的全部 — table 实例
    // 稳定。若缺少 columnFilters，因 FilterDef select 缩小后的表会
    // 卡在越界页面（空 body + 隐藏 pagination，R5）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, pageSize, columnFilters, loading])

  // Notify parent when the selection changes. We map back to the source rows
  // so callers receive the original objects (not table-wrapper rows).
  // `filtered` is a dep on purpose: when the parent swaps/shrinks `data`
  // (external search/filter), selected keys can point at rows no longer in
  // the model — without re-running, the parent would keep a stale selection
  // (bulk bar count/targets diverge from visible checkboxes).
  // The row-id signature guard makes the effect convergent: parents that pass
  // unstable `data` identities would otherwise loop (notify → parent setState
  // → new data → notify …, "Maximum update depth exceeded"). NOTE the guard
  // is id-based: same ids with refreshed row objects do NOT re-notify — treat
  // the callback payload as "which rows", and derive fresh objects from your
  // current data at action time (store ids, not object snapshots).
  // 半受控的 controlled 组合会悄悄失效 — 开发模式下立即警告。
  if (
    process.env.NODE_ENV !== 'production' &&
    (rowSelectionState === undefined) !== (onRowSelectionStateChange === undefined)
  ) {
    reportClientWarning(
      'DataTable',
      'DataTable: rowSelectionState and onRowSelectionStateChange must be passed together.',
    )
  }

  // 清理已从数据中消失的行（外部筛选/删除）的选择键 — 若保留，
  // 用户"全部取消选择"后再解除筛选时，幽灵选择会复活并重新成为批量对象。
  // 清理后，下面的通知 effect 会通过签名变化同步给父级。
  // 两个防护(R5)：① loading 中跳过 — 查询键变化导致 data 短暂 [] 的
  // 闪烁中，所有选择会被清空。② 有效性基准是**完整 data prop** —
  // 如果把内部搜索隐藏的行（filtered 外）也删掉，会破坏用户在切换搜索时累积的选择
  // （models 批量测试）以及"列举隐藏选中行名称"的契约。
  useEffect(() => {
    if (!enableRowSelection || loading) return
    const validIds = new Set(data.map((row, index) => rowIdOf(row, index)))
    const staleKeys = Object.keys(rowSelection).filter((key) => !validIds.has(key))
    if (staleKeys.length === 0) return
    setRowSelection((previous) => {
      const next = { ...previous }
      for (const key of staleKeys) delete next[key]
      return next
    })
    // rowSelection/data/loading 是有效性输入的全部 — setter·rowIdOf 为 render closure。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowSelection, data, loading, enableRowSelection])

  const lastSelectionSignature = useRef('')
  useEffect(() => {
    // loading 中跳过 — 若用闪烁的空 data 向父级通知 []，批量条形会
    // 闪烁消失后又出现 (R5)。加载中结束后会因 data 变化再次执行。
    if (!enableRowSelection || !onRowSelectionChange || loading) return
    // payload 不是从搜索范围内 row model，而是从**完整 data prop**推导 —
    // 若基于 row model，内部搜索隐藏的选择会悄悄从父级状态中消失，
    // 导致 prune 保留的选择与父级实际执行对象分叉（models "Test
    // Selected" 少报 + AD-5 无法列举隐藏名称，R6）。
    const selectedIds: string[] = []
    const selectedRows: T[] = []
    data.forEach((row, index) => {
      const id = rowIdOf(row, index)
      if (rowSelection[id]) {
        selectedIds.push(id)
        selectedRows.push(row)
      }
    })
    const signature = selectedIds.join('\u0000')
    if (signature === lastSelectionSignature.current) return
    lastSelectionSignature.current = signature
    onRowSelectionChange(selectedRows)
    // rowSelection/data/loading 是 payload 输入的全部 — rowIdOf 为 render closure。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowSelection, data, loading, enableRowSelection])

  return (
    <div className="space-y-3">
      {(searchable || filters?.length || toolbar) && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-card/70 p-3">
          {searchable && (
            <SearchInput
              containerClassName="w-full sm:w-72"
              placeholder={searchPlaceholder ?? t('searchPlaceholder')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          )}
          {filters?.map((filter) => (
            <DataTableFilter
              key={filter.columnId}
              filter={filter}
              value={(table.getColumn(filter.columnId)?.getFilterValue() as string) ?? ''}
              onValueChange={(value) =>
                table
                  .getColumn(filter.columnId)
                  ?.setFilterValue(value === 'all' ? undefined : value)
              }
            />
          ))}
          {toolbar && <div className="ml-auto flex items-center gap-2">{toolbar}</div>}
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-border/70 bg-card/90 shadow-[var(--moldy-shadow-card)]">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sortable = header.column.getCanSort()
                  return (
                    <TableHead key={header.id}>
                      {header.isPlaceholder ? null : sortable ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 text-left font-medium"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <ArrowUpDown className="size-3 text-muted-foreground" />
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <TableRow key={`skeleton-${i}`}>
                  {tableColumns.map((_col, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={tableColumns.length} className="p-0">
                  <EmptyState
                    title={resolvedEmptyTitle}
                    description={emptyDescription}
                    action={emptyAction}
                    className="border-0"
                  />
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-clickable={onRowClick ? '' : undefined}
                  className={onRowClick ? 'cursor-pointer' : undefined}
                  onClick={
                    onRowClick
                      ? (event) => {
                          // 单元格中的交互元素（复选框/按钮/菜单/链接）
                          // 点击不应升级为行导航 — 某些
                          // 原语的点击始于子项，仅靠单元格级
                          // stopPropagation 无法保证不会泄漏。
                          const target = event.target as HTMLElement
                          if (
                            target.closest(
                              'button, a, input, select, textarea, label, ' +
                                '[role="checkbox"], [role="switch"], [role="combobox"], ' +
                                '[role="menu"], [role="menuitem"], [role="menuitemcheckbox"], ' +
                                '[role="option"]',
                            )
                          ) {
                            return
                          }
                          onRowClick(row.original)
                        }
                      : undefined
                  }
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {t('pagination', {
              page: table.getState().pagination.pageIndex + 1,
              totalPages: table.getPageCount(),
              count: table.getFilteredRowModel().rows.length,
            })}
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronLeft className="size-4" />
              {t('previous')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              {t('next')}
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function DataTableFilter({
  filter,
  value,
  onValueChange,
}: {
  filter: FilterDef
  value: string
  onValueChange: (value: string) => void
}) {
  const t = useTranslations('common.dataTable')
  return (
    <Select value={value || 'all'} onValueChange={(v) => v !== null && onValueChange(v)}>
      <SelectTrigger className="h-8 w-40" aria-label={filter.label}>
        <SelectValue placeholder={filter.label} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{t('allFilter', { label: filter.label })}</SelectItem>
        {filter.options.map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
