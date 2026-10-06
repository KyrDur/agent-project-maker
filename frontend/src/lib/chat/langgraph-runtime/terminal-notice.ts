'use client'

import type { BaseMessage } from '@langchain/core/messages'

/**
 * 合成 terminal-notice 气泡（取消/stale/失败）放入 ``additional_kwargs.metadata`` 的
 * 判定 key。``convertMoldyLangChainMessage`` 会把这个值提升到 ``metadata.custom``
 * （``terminalNotice``），供 ``AssistantMessage`` 渲染读取。尤其是
 * ``failed`` 会触发错误样式 + retry 按钮（G2）。
 *
 * 与 compaction/usage 一样使用 additional_kwargs.metadata 约定——
 * ``convertLangChainBaseMessage`` 不会自动把 additional_kwargs 提升为 custom，
 * 因此需要显式 attach。
 */
export const TERMINAL_NOTICE_METADATA_KEY = 'moldy_terminal_notice'
export const TERMINAL_NOTICE_BOUNDARY_METADATA_KEY = 'moldy_terminal_notice_boundary'

export type TerminalNoticeStatus = 'canceled' | 'canceling' | 'stale' | 'failed'

const TERMINAL_NOTICE_STATUSES: readonly TerminalNoticeStatus[] = [
  'canceled',
  'canceling',
  'stale',
  'failed',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isTerminalNoticeStatus(value: unknown): value is TerminalNoticeStatus {
  return (
    typeof value === 'string' && TERMINAL_NOTICE_STATUSES.includes(value as TerminalNoticeStatus)
  )
}

/** 判定合成 terminal-notice 气泡的消息 id。``appendTerminalRunNotice`` 会
 * 生成 ``moldy-<status>-<runId>`` 形式。checkpoint fork 计算（regenerate/
 * retry/edit）不能把这个合成气泡误认为真实 assistant turn——
 * 尤其失败气泡没有 checkpoint，会使 fork 目标搜索以 null 结束——
 * 因此必须从 fork context 的 visible 消息中排除（G2 retry）。 */
export function isTerminalNoticeMessageId(id: string | undefined | null): boolean {
  if (!id) return false
  return TERMINAL_NOTICE_STATUSES.some((status) => id.startsWith(`moldy-${status}-`))
}

/** 从合成气泡消息中提取 terminal-notice 状态
 *  （与 compactionFromMessage 相同的 additional_kwargs.metadata 约定）。 */
export function terminalNoticeFromMessage(message: BaseMessage): TerminalNoticeStatus | null {
  const additionalKwargs = (message as { additional_kwargs?: unknown }).additional_kwargs
  const metadata =
    isRecord(additionalKwargs) && isRecord(additionalKwargs.metadata)
      ? additionalKwargs.metadata
      : null
  const status = metadata?.[TERMINAL_NOTICE_METADATA_KEY]
  return isTerminalNoticeStatus(status) ? status : null
}
