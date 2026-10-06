import type { ColumnDef } from '@tanstack/react-table'
import { render, screen, userEvent } from '../../test-utils'
import { DataTable } from '@/components/ui/data-table'

// 用于 FilterDef(Radix Select) 交互的轻量 mock — 在 jsdom 中真实 Radix Select
// 依赖 pointer capture，表现不稳定（models 页面测试先例）。
let lastOnValueChange: ((value: string) => void) | undefined
vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
  }: {
    children: React.ReactNode
    onValueChange?: (value: string) => void
  }) => {
    lastOnValueChange = onValueChange
    return <div>{children}</div>
  },
  SelectTrigger: ({ children }: { children: React.ReactNode }) => (
    <button type="button">{children}</button>
  ),
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <button type="button" data-value={value} onClick={() => lastOnValueChange?.(value)}>
      {children}
    </button>
  ),
}))

interface Row {
  id: string
  name: string
}

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'name',
    header: '名称',
    cell: ({ row }) => row.original.name,
  },
]

describe('DataTable', () => {
  it('uses Korean default empty text', () => {
    render(<DataTable columns={columns} data={[]} />)

    expect(screen.getByText('没有找到物品')).toBeInTheDocument()
  })

  it('uses Korean pagination labels', () => {
    render(
      <DataTable
        columns={columns}
        data={[
          { id: '1', name: '第一个' },
          { id: '2', name: '第二个' },
        ]}
        pageSize={1}
      />,
    )

    expect(screen.getByText('第 1 页 / 共 2 页 · 2 个项目')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /上一页/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /下一页/ })).toBeInTheDocument()
  })

  it('does not recompute global search results on same-prop rerenders', async () => {
    const data = [
      { id: '1', name: '第一个' },
      { id: '2', name: '第二个' },
    ]
    const filterFn = vi.fn((row: Row, query: string) =>
      row.name.toLowerCase().includes(query),
    )

    const { rerender } = render(
      <DataTable
        columns={columns}
        data={data}
        searchable
        globalFilterFn={filterFn}
      />,
    )

    await userEvent.type(screen.getByPlaceholderText('搜索...'), '第一')
    const callsAfterSearch = filterFn.mock.calls.length

    rerender(
      <DataTable
        columns={columns}
        data={data}
        searchable
        globalFilterFn={filterFn}
      />,
    )

    expect(filterFn).toHaveBeenCalledTimes(callsAfterSearch)
  })

  // R5 三类回归 — 防止 rowSelection prune/pageIndex clamp effect 自我破坏。

  it('loading 闪烁（query key 变化导致 data 暂时为 []）期间不清除选择', () => {
    const rows = [
      { id: '1', name: '第一个' },
      { id: '2', name: '第二个' },
    ]
    const onStateChange = vi.fn()
    const controlled = {
      columns,
      enableRowSelection: true,
      rowSelectionState: { '1': true },
      onRowSelectionStateChange: onStateChange,
    }
    const { rerender } = render(<DataTable {...controlled} data={rows} />)

    // 模拟搜索键输入/kind 标签切换：data 为空数组 + loading=true.
    rerender(<DataTable {...controlled} data={[]} loading />)
    expect(onStateChange).not.toHaveBeenCalled()

    // 只有加载结束且该行确实消失时 prune 才生效。
    rerender(<DataTable {...controlled} data={[rows[1]]} loading={false} />)
    expect(onStateChange).toHaveBeenCalled()
  })

  it('被内部搜索隐藏的已选行不会被 prune', async () => {
    const rows = [
      { id: '1', name: '第一个' },
      { id: '2', name: '第二个' },
    ]
    const onStateChange = vi.fn()
    render(
      <DataTable
        columns={columns}
        data={rows}
        searchable
        enableRowSelection
        rowSelectionState={{ '1': true }}
        onRowSelectionStateChange={onStateChange}
      />,
    )

    // 隐藏 '第一个'（已选择）的搜索 — 选择 key 以 data prop 为准仍然有效。
    await userEvent.type(screen.getByPlaceholderText('搜索...'), '二')
    expect(screen.queryByText('第一个')).not.toBeInTheDocument()
    expect(onStateChange).not.toHaveBeenCalled()
  })

  it('被内部搜索隐藏的已选行也会保留在父级通知 payload 中 (R6)', async () => {
    const rows = [
      { id: '1', name: '第一个' },
      { id: '2', name: '第二个' },
    ]
    const onSelectionChange = vi.fn()
    render(
      <DataTable
        columns={columns}
        data={rows}
        searchable
        enableRowSelection
        rowSelectionState={{ '1': true }}
        onRowSelectionStateChange={vi.fn()}
        onRowSelectionChange={onSelectionChange}
      />,
    )
    expect(onSelectionChange).toHaveBeenLastCalledWith([rows[0]])
    const callsBeforeSearch = onSelectionChange.mock.calls.length

    // 隐藏已选行的搜索 — 如果 payload 基于搜索 scope 的 row model，则这里
    // 会重新通知为 []，导致父级状态（批量对象）与 checkbox 分叉。
    await userEvent.type(screen.getByPlaceholderText('搜索...'), '二')

    expect(onSelectionChange).toHaveBeenCalledTimes(callsBeforeSearch)
    expect(onSelectionChange).toHaveBeenLastCalledWith([rows[0]])
  })

  it('没有 id 的行在搜索中也会通知正确的行 — 对象引用 Map id 空间 (R7)', async () => {
    // 没有 id 字段的行：若 index fallback id 在 filtered/data 中分叉，则搜索时
    // payload 中会放入 data[0](A)，而不是勾选的行(C)。
    interface Anon {
      name: string
    }
    const rows: Anon[] = [{ name: 'A行' }, { name: 'B行' }, { name: 'C行' }]
    const onSelectionChange = vi.fn()
    const anonColumns: ColumnDef<Anon>[] = [
      { accessorKey: 'name', header: '名称', cell: ({ row }) => row.original.name },
    ]
    render(
      <DataTable
        columns={anonColumns}
        data={rows}
        searchable
        enableRowSelection
        onRowSelectionChange={onSelectionChange}
      />,
    )

    await userEvent.type(screen.getByPlaceholderText('搜索...'), 'C行')
    await userEvent.click(screen.getByRole('checkbox', { name: '选择行' }))

    expect(onSelectionChange).toHaveBeenLastCalledWith([rows[2]])
  })

  it('经列筛选缩小后的表格不会停留在越界页面', async () => {
    interface TypedRow extends Row {
      type: string
    }
    const typedColumns: ColumnDef<TypedRow>[] = [
      { accessorKey: 'name', header: '名称', cell: ({ row }) => row.original.name },
      { accessorKey: 'type', header: '类型', cell: ({ row }) => row.original.type },
    ]
    const rows: TypedRow[] = [
      { id: '1', name: 'A行', type: 'x' },
      { id: '2', name: 'B行', type: 'x' },
      { id: '3', name: 'C行', type: 'y' },
    ]
    render(
      <DataTable
        columns={typedColumns}
        data={rows}
        pageSize={1}
        filters={[
          { columnId: 'type', label: '类型', options: [{ value: 'x', label: '仅 X' }] },
        ]}
      />,
    )

    // 移动到第 3 页(C行)后，用筛选只保留 2 行(x)。
    await userEvent.click(screen.getByRole('button', { name: /下一页/ }))
    await userEvent.click(screen.getByRole('button', { name: /下一页/ }))
    expect(screen.getByText('C行')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '仅 X' }))

    // 如果没有 clamp，pageIndex=2 会停在 pageCount=2 之外，导致空 body + pagination
    // 隐藏形成 dead-end — 应收敛到最后一个有效页面(B行)。
    expect(screen.getByText('B行')).toBeInTheDocument()
    expect(screen.getByText('第 2 页 / 共 2 页 · 2 个项目')).toBeInTheDocument()
  })
})
