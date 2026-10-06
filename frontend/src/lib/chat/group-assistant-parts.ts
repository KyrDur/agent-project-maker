import type { ReactNode } from 'react'
import type { EnrichedPartState, PartState } from '@assistant-ui/react'
import { isGroupableTool } from '@/lib/chat/tool-group-meta'

// ──────────────────────────────────────────────
// 共享 tool-call 分组 helper。
//
// 主 v3 聊天（`assistant-thread.tsx`）与 builder 渲染（`builder-overrides.tsx`）
// 共享同一个 `MessagePrimitive.GroupedParts` groupBy/节点判定。各表面的
// leaf 渲染（文本/工具框视觉）彼此不同，因此 render fn 按表面分别保留，但
// "哪些 part 应按哪些 group key 分组"以及"如何判定/解释 group 节点"
// 统一定义在一处，避免两个表面行为不一致。
// ──────────────────────────────────────────────

export const GROUP_TOOL_PREFIX = 'group-tool:'

const APPROVAL_TOOL = 'request_approval'

/**
 * request_approval 按 interrupt 边界拆分组——group 容器表示"一个
 * interrupt 的 N 个 action"集合（GroupedApprovalCard contract），如果 key 只有工具名，
 * 前一个 interrupt 的 resolved 卡片与新 interrupt 的 pending 卡片相邻时会被
 * coalesce 成一组，出现"等待批准 2 项"这类虚假计数（M8-3）。
 */
function approvalInterruptSuffix(part: PartState): string {
  if (part.type !== 'tool-call' || part.toolName !== APPROVAL_TOOL) return ''
  const id = (part.args as Record<string, unknown> | undefined)?.hitl_interrupt_id
  return typeof id === 'string' && id ? `:${id}` : ''
}

/**
 * groupBy：如果是 tool-call 且属于可分组对象，则使用 `group-tool:<toolName>` 单一路径，否则为 null。
 * key 中包含 toolName，因此只合并"连续相同工具"，相邻的不同工具会分开。
 * request_approval 细分为 `group-tool:request_approval:<interruptId>`。
 *
 * 定义为模块级 const，避免 assistant-ui 内部基于 identity 的 memoization 每个 token
 * 都失效——如果每次 render 都创建新函数，streaming 显示会不稳定。
 */
export function groupAssistantParts(part: PartState): readonly [`group-${string}`] | null {
  if (part.type === 'tool-call' && isGroupableTool(part.toolName)) {
    return [
      `${GROUP_TOOL_PREFIX}${part.toolName}${approvalInterruptSuffix(part)}` as `group-${string}`,
    ]
  }
  return null
}

/** GroupedParts 合成的 group-tool 节点。status 镜像最后一个 part 的状态。 */
export type GroupToolNode = {
  readonly type: `group-${string}`
  readonly status?: { type?: string }
  readonly indices: readonly number[]
}

/** GroupedParts render fn 接收的节点——group 节点 / leaf part / indicator 三者之一。 */
export type GroupedRenderInfo = {
  readonly part: GroupToolNode | EnrichedPartState | { readonly type: 'indicator' }
  readonly children: ReactNode
}

/** 判断 part 是否为 group-tool 节点（= type 是否以 GROUP_TOOL_PREFIX 开头）。 */
export function isGroupToolNode(part: { readonly type: string }): part is GroupToolNode {
  return part.type.startsWith(GROUP_TOOL_PREFIX)
}

/** 从 group-tool 节点的 type 中恢复原始 toolName。 */
export function groupToolName(node: GroupToolNode): string {
  const raw = node.type.slice(GROUP_TOOL_PREFIX.length)
  // request_approval 编码为 `request_approval:<interruptId>`——只恢复工具名。
  if (raw.startsWith(`${APPROVAL_TOOL}:`)) return APPROVAL_TOOL
  return raw
}
