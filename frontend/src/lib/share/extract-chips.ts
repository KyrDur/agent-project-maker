/**
 * W6 — 从每个 turn 的 SSE event sequence 中提取要在公开页面 chip 中展示的信息。
 *
 * 输入：一条 ``TurnTrace`` 的 events（``message_start`` … ``message_end``）。
 * 输出：``ChipInfo[]`` — 浮在 assistant 消息正文上方的工具/子代理
 *      badge 列表。
 *
 * 提取规则：
 * - 发现 ``tool_call_start`` → 开始一个工具 chip（status="success", kind="tool"）
 *   - 若后面存在同一 ``tool_name`` 的 ``tool_call_result`` 则匹配（最近的
 *     一个，一对一）。若结果未到达，chip 仍按 success 处理（stream
 *     已结束，因此 loading 没有意义）。
 *   - 工具名为 ``task`` 时转换为子代理 chip（kind="subagent"，
 *     名称回退顺序为 ``args.agent_name`` 或 ``args.subagent_type``）。
 *   - 工具名为 ``write_todos`` 时转换为 plan chip — 名称 "Plan"，meta 为 todos 数量。
 * - 忽略其他事件（content_delta 等已作为正文文本暴露）。
 */

import { asRecord, isRecord, planMeta, resultMeta, subagentTitle, text } from './chip-values'
import { protocolChips } from './protocol-chips'
import type { ChipInfo } from './chip-values'
import type { LegacyTraceEvent, TraceEvent, TurnTrace } from '@/lib/types/share'

export type { ChipInfo, ChipKind, ChipStatus } from './chip-values'

const _isLegacyEvent = (evt: TraceEvent): evt is LegacyTraceEvent =>
  'event' in evt && typeof evt.event === 'string' && isRecord(evt.data)

function _legacyChips(events: TraceEvent[]): ChipInfo[] {
  const chips: ChipInfo[] = []
  const pendingResults: Map<string, LegacyTraceEvent[]> = new Map()
  for (const evt of events) {
    if (!_isLegacyEvent(evt) || evt.event !== 'tool_call_result') continue
    const name = text(evt.data.tool_name) ?? ''
    if (!name) continue
    const queue = pendingResults.get(name) ?? []
    queue.push(evt)
    pendingResults.set(name, queue)
  }

  for (const evt of events) {
    if (!_isLegacyEvent(evt) || evt.event !== 'tool_call_start') continue
    const toolName = text(evt.data.tool_name) ?? ''
    if (!toolName) continue
    const params = asRecord(evt.data.parameters)
    const queue = pendingResults.get(toolName) ?? []
    const matched = queue.shift()
    pendingResults.set(toolName, queue)

    if (toolName === 'task') {
      chips.push({ kind: 'subagent', status: 'success', title: subagentTitle(params) })
      continue
    }
    if (toolName === 'write_todos') {
      chips.push({ kind: 'tool', status: 'success', title: 'Plan', meta: planMeta(params) })
      continue
    }
    chips.push({
      kind: 'tool',
      status: 'success',
      title: toolName,
      meta: resultMeta(matched?.data.result),
    })
  }
  return chips
}

/**
 * 将一条 Turn 的 events 转换为 chip 数组。若为空数组（没有 tool 调用的普通
 * 文本响应），返回空结果。
 */
export function extractChips(turn: TurnTrace): ChipInfo[] {
  return [..._legacyChips(turn.events), ...protocolChips(turn.events)]
}

/**
 * 在 traces 数组中查找与 assistant 消息 id 匹配的 turn。后端的
 * ``MessageResponse.id`` 是 raw langchain id 或 deterministic uuid5 — 即便如此，
 * 与 ``TurnTrace.assistant_msg_id``（stream_agent_response 的 msg_id）做字符串
 * 相等比较仍是最常见路径。匹配不到则返回 null → 不显示 chip。
 */
export function findTurnForMessage(traces: TurnTrace[], messageId: string): TurnTrace | null {
  for (const t of traces) {
    if (t.assistant_msg_id === messageId) return t
  }
  return null
}
