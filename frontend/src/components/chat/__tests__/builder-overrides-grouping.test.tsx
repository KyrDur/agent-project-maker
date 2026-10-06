import type { ReactNode } from 'react'
import type { EnrichedPartState, PartState } from '@assistant-ui/react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../../../tests/test-utils'

// Builder 界面也与主 v3 共用相同的 GroupedParts groupBy/节点判定（Phase-2b）。
// ToolGroupContainer 通过 useAuiState 读取 message.parts，BuilderAssistantTextPart 则
// 通过 useMessagePartText 读取文本，因此在没有 aui provider 的单元测试中只 mock 这两个 hook
// mock（其余 builder-overrides import 仍使用实际模块）。
const auiMocks = vi.hoisted(() => ({
  state: {
    message: {
      parts: [] as readonly { readonly result?: unknown }[],
      status: { type: 'complete' },
    },
  },
  partText: { text: '' } as { text: string } | null,
}))

vi.mock('@assistant-ui/react', async () => {
  const actual = await vi.importActual<typeof import('@assistant-ui/react')>('@assistant-ui/react')
  return {
    ...actual,
    useAuiState: (selector: (state: typeof auiMocks.state) => unknown) => selector(auiMocks.state),
    useMessagePartText: () => auiMocks.partText,
  }
})

const { renderBuilderGroupedPart } = await import('../builder-overrides')

/** 合成 group-tool 节点 —— 接收 count（=indices 长度）和 running 状态并传给 render fn。 */
function renderGroupNode(toolName: string, count: number, running: boolean, children: ReactNode) {
  const node = {
    type: `group-tool:${toolName}` as `group-${string}`,
    status: { type: running ? 'running' : 'complete' },
    indices: Array.from({ length: count }, (_, i) => i),
  }
  return render(<>{renderBuilderGroupedPart({ part: node, children })}</>)
}

describe('renderBuilderGroupedPart (group-tool 节点)', () => {
  it('N≥2: 用分组容器包裹并显示标签 + 数量', () => {
    renderGroupNode('read_file', 2, false, <div data-testid="leaf">leaf</div>)
    expect(screen.getByText('读取文件')).toBeInTheDocument()
    expect(screen.getByText('2次')).toBeInTheDocument()
  })

  it('N=1: 不使用容器，仅 passthrough children（无标签/数量）', () => {
    renderGroupNode('read_file', 1, false, <div data-testid="leaf">leaf</div>)
    expect(screen.getByTestId('leaf')).toBeInTheDocument()
    expect(screen.queryByText('读取文件')).not.toBeInTheDocument()
    expect(screen.queryByText('一次')).not.toBeInTheDocument()
  })

  it('running=true: 处于展开状态，可看到组内 children', () => {
    renderGroupNode('read_file', 3, true, <div data-testid="leaf">leaf</div>)
    expect(screen.getByText('读取文件')).toBeInTheDocument()
    expect(screen.getByText('3次')).toBeInTheDocument()
    expect(screen.getByTestId('leaf')).toBeInTheDocument()
  })
})

describe('renderBuilderGroupedPart (leaf part)', () => {
  it('text part: 经 phase-narration 解析器后保留渲染正文文本', () => {
    auiMocks.partText = { text: '已整理搜索结果。' }
    const textPart = { type: 'text', text: '已整理搜索结果。' } as unknown as PartState
    render(<>{renderBuilderGroupedPart({ part: textPart as never, children: null })}</>)
    expect(screen.getByText('已整理搜索结果。')).toBeInTheDocument()
  })

  it('text part: phase 切换文案会转换为 SystemEventChip(role=status)', () => {
    auiMocks.partText = { text: '[Phase 2 完成]' }
    const textPart = { type: 'text', text: '[Phase 2 完成]' } as unknown as PartState
    render(<>{renderBuilderGroupedPart({ part: textPart as never, children: null })}</>)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('tool-call leaf: 优先渲染已注册的 per-tool UI(leaf.toolUI)', () => {
    const leaf = {
      type: 'tool-call',
      toolName: 'phase_timeline',
      toolCallId: 'tc-1',
      args: {},
      status: { type: 'complete' },
      toolUI: <div data-testid="registered">registered</div>,
    } as unknown as EnrichedPartState
    render(<>{renderBuilderGroupedPart({ part: leaf, children: null })}</>)
    expect(screen.getByTestId('registered')).toBeInTheDocument()
  })

  it('tool-call leaf: 未注册工具由 BuilderToolFallback 兜底显示 toolName', () => {
    const leaf = {
      type: 'tool-call',
      toolName: 'unknown_tool',
      toolCallId: 'tc-2',
      args: {},
      status: { type: 'complete' },
    } as unknown as EnrichedPartState
    render(<>{renderBuilderGroupedPart({ part: leaf, children: null })}</>)
    expect(screen.getByText('unknown_tool')).toBeInTheDocument()
  })

  it('indicator part 为 null（另有独立的加载指示器渲染）', () => {
    const { container } = render(
      <>{renderBuilderGroupedPart({ part: { type: 'indicator' }, children: null })}</>,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
