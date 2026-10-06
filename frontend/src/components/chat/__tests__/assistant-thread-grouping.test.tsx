import type { ReactNode } from 'react'
import type { PartState } from '@assistant-ui/react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../../../tests/test-utils'

// ToolGroupContainer 为了汇总搜索组来源，通过 useAuiState 读取 message.parts
// 因此只 mock useAuiState，使其在没有 aui provider 的单元测试中也能工作。
// （其余 assistant-thread import 仍直接使用实际模块。）
const auiMocks = vi.hoisted(() => ({
  state: { message: { parts: [] as readonly { readonly result?: unknown }[] } },
}))

vi.mock('@assistant-ui/react', async () => {
  const actual = await vi.importActual<typeof import('@assistant-ui/react')>('@assistant-ui/react')
  return {
    ...actual,
    useAuiState: (selector: (state: typeof auiMocks.state) => unknown) => selector(auiMocks.state),
  }
})

const { groupAssistantParts, renderGroupedAssistantPart } = await import('../assistant-thread')

function toolCallPart(toolName: string, args: Record<string, unknown> = {}): PartState {
  return {
    type: 'tool-call',
    toolName,
    toolCallId: `tc-${toolName}`,
    args,
    status: { type: 'complete' },
  } as unknown as PartState
}

function textPart(): PartState {
  return { type: 'text', text: 'hi', status: { type: 'complete' } } as unknown as PartState
}

/** 将一条消息的 parts 序列传给 groupBy，把相邻且 key 相同的项合并形成分组边界
 * —— 用一个精简的测试 helper 复现与官方 buildGroupTree 相同的相邻合并规则。 */
function groupKeysFor(parts: PartState[]): (string | null)[] {
  return parts.map((p) => {
    const path = groupAssistantParts(p)
    return path ? path[0] : null
  })
}

/** 合成 group-tool 节点 —— 接收 count（=indices 长度）和 running 状态并传给 render fn。 */
function renderGroupNode(toolName: string, count: number, running: boolean, children: ReactNode) {
  const node = {
    type: `group-tool:${toolName}` as `group-${string}`,
    status: { type: running ? 'running' : 'complete' },
    indices: Array.from({ length: count }, (_, i) => i),
  }
  return render(<>{renderGroupedAssistantPart({ part: node, children })}</>)
}

describe('groupAssistantParts (groupBy)', () => {
  it('tool-call 走 group-tool:<toolName> 路径，非 tool part 为 null', () => {
    expect(groupAssistantParts(toolCallPart('tavily_search'))).toEqual(['group-tool:tavily_search'])
    expect(groupAssistantParts(textPart())).toBeNull()
  })

  it('排除分组的工具（ask_user 等）为 null，因此不会被分组', () => {
    expect(groupAssistantParts(toolCallPart('ask_user'))).toBeNull()
    expect(groupAssistantParts(toolCallPart('ask_clarifying_question'))).toBeNull()
  })

  it('request_approval 作为例外属于分组对象 —— 用于归入审批组容器', () => {
    expect(groupAssistantParts(toolCallPart('request_approval'))).toEqual([
      'group-tool:request_approval',
    ])
  })

  it('request_approval 按中断边界拆分 —— 不同 hitl_interrupt_id 使用不同 key (M8-3)', () => {
    // 即使上一条中断（resolved）与新中断（pending）相邻，也不会 coalesce 后
    // "待审批 2 项" 的虚假计数不会出现，因此把 interrupt id 放进 key。
    const resolvedA = toolCallPart('request_approval', { hitl_interrupt_id: 'int-a' })
    const pendingB = toolCallPart('request_approval', { hitl_interrupt_id: 'int-b' })
    expect(groupAssistantParts(resolvedA)).toEqual(['group-tool:request_approval:int-a'])
    expect(groupAssistantParts(pendingB)).toEqual(['group-tool:request_approval:int-b'])
    expect(groupAssistantParts(resolvedA)?.[0]).not.toBe(groupAssistantParts(pendingB)?.[0])
  })

  it('同一 hitl_interrupt_id 的多 action request_approval 会归为同一个 key', () => {
    const first = toolCallPart('request_approval', { hitl_interrupt_id: 'int-a' })
    const second = toolCallPart('request_approval', { hitl_interrupt_id: 'int-a' })
    expect(groupAssistantParts(first)).toEqual(groupAssistantParts(second))
  })

  it('intra-message: 相同工具使用相同 key，不同工具拆成不同 key', () => {
    // tavily ×3 + read_file ×1（实测数据模式）→ 2 个不同的分组 key
    const parts = [
      toolCallPart('tavily_search'),
      toolCallPart('tavily_search'),
      toolCallPart('tavily_search'),
      toolCallPart('read_file'),
    ]
    const keys = groupKeysFor(parts)
    expect(keys).toEqual([
      'group-tool:tavily_search',
      'group-tool:tavily_search',
      'group-tool:tavily_search',
      'group-tool:read_file',
    ])
    const distinct = new Set(keys.filter((k): k is string => k !== null))
    expect(distinct.size).toBe(2)
  })
})

describe('renderGroupedAssistantPart (group-tool node)', () => {
  it('N≥2: 用容器分组，并显示标签 + 数量', () => {
    renderGroupNode('tavily_search', 2, false, <div data-testid="leaf">leaf</div>)
    expect(screen.getByText('网页搜索')).toBeInTheDocument()
    expect(screen.getByText('2次')).toBeInTheDocument()
  })

  it('N=1: 不使用容器，仅 passthrough children（无标签/数量）', () => {
    renderGroupNode('tavily_search', 1, false, <div data-testid="leaf">leaf</div>)
    expect(screen.getByTestId('leaf')).toBeInTheDocument()
    expect(screen.queryByText('网页搜索')).not.toBeInTheDocument()
    expect(screen.queryByText('一次')).not.toBeInTheDocument()
  })

  it('running=true: 处于展开状态，可看到组内 children', () => {
    renderGroupNode('read_file', 3, true, <div data-testid="leaf">leaf</div>)
    expect(screen.getByText('读取文件')).toBeInTheDocument()
    expect(screen.getByText('3次')).toBeInTheDocument()
    expect(screen.getByTestId('leaf')).toBeInTheDocument()
  })

  it('done(running=false): 处于折叠状态，组内 children 被隐藏', () => {
    renderGroupNode('read_file', 3, false, <div data-testid="leaf">leaf</div>)
    expect(screen.getByText('读取文件')).toBeInTheDocument()
    expect(screen.queryByTestId('leaf')).not.toBeInTheDocument()
  })

  it('indicator part 为 null（另有独立的加载指示器渲染）', () => {
    const { container } = render(
      <>{renderGroupedAssistantPart({ part: { type: 'indicator' }, children: null })}</>,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('审批组 N≥2: 不用 generic 容器，而以 "待审批 N 项" + "批准全部" 分组，卡片始终可见', () => {
    renderGroupNode('request_approval', 2, false, <div data-testid="approval-leaf">card</div>)
    expect(screen.getByText('待批准 2 项')).toBeInTheDocument()
    expect(screen.getByText('批准全部')).toBeInTheDocument()
    // 审批卡不会折叠，始终渲染（因为需要用户作出决定）。
    expect(screen.getByTestId('approval-leaf')).toBeInTheDocument()
    // 不显示 generic 分组标签/数量 badge。
    expect(screen.queryByText('2次')).not.toBeInTheDocument()
  })

  it('审批组 N=1: 不使用容器，直接 passthrough 单个审批卡', () => {
    renderGroupNode('request_approval', 1, false, <div data-testid="approval-leaf">card</div>)
    expect(screen.getByTestId('approval-leaf')).toBeInTheDocument()
    expect(screen.queryByText(/待批准/)).not.toBeInTheDocument()
  })

  it('中断-suffix 组节点也会渲染为审批容器（M8-3 key 编码）', () => {
    // 即使 groupBy 将 key 细分为 `request_approval:<interruptId>`，render 路径也必须
    // 通过 groupToolName 还原工具名，以维持专用审批容器。
    renderGroupNode('request_approval:int-b', 2, false, <div data-testid="approval-leaf">card</div>)
    expect(screen.getByText('待批准 2 项')).toBeInTheDocument()
    expect(screen.getByTestId('approval-leaf')).toBeInTheDocument()
  })
})
