'use client'

import { AuiIf, useAuiState } from '@assistant-ui/react'
import { useMemo } from 'react'
import { DeepAgentsStatePanel } from '@/components/chat/deepagents-state-panel'
import { RunActivityStrip } from '@/components/chat/run-activity-strip'
import { SubagentProgress } from '@/components/chat/subagent-progress'
import { WittyLoadingMessage } from '@/components/chat/witty-loading'
import { cn } from '@/lib/utils'
import type { RunActivity } from '@/lib/chat/langgraph-runtime/activity-model'
import type { DeepAgentsStateSnapshot } from '@/lib/chat/langgraph-runtime/deepagents-state'
import { useSubagentProgressSummary } from '@/lib/chat/langgraph-runtime/subagent-runtime'

interface StreamingMessageLoadingIndicatorProps {
  readonly activities?: readonly RunActivity[]
  readonly deepAgentsState?: DeepAgentsStateSnapshot
  readonly className?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isStreamingMessageMetadata(metadata: unknown): boolean {
  if (!isRecord(metadata) || !isRecord(metadata.custom)) return false
  return metadata.custom.isStreamingMessage === true
}

function isRunningMessageStatus(status: unknown): boolean {
  return isRecord(status) && status.type === 'running'
}

/** M6 —— 判断消息是否"当前正在流式传输"。
 *
 * 对两个信号执行 OR：(1) 我们直接写入的 `metadata.custom.isStreamingMessage`，
 * (2) assistant-ui status 为 `running`。
 *
 * `metadata.custom.isStreamingMessage` 只会由 `convert-message.ts` 对 id 以 `stream-`
 * 开头的消息写入 `true`，production 路径不会显式写入 `false`
 * （完成时只是该字段不存在）。因此，"如果 metadata 明确为 streaming=false
 * 就忽略 running status"之类的额外 guard 在运行时永远不会触发，属于 dead code
 * —— 已将其移除，恢复为上述两个信号的简单 OR。
 *
 * 关于 sticky/converted 复用可能使已完成消息残留 stale `running` status 的担忧，
 * 由调用组件(`StreamingMessageLoadingIndicator`)通过
 * `AuiIf condition={(s) => s.thread.isRunning}` 包裹来防护；当 thread idle 时，
 * 任何消息都不会渲染指示器。 */
export function isStreamingMessageState(message: unknown): boolean {
  if (!isRecord(message)) return false
  if (isStreamingMessageMetadata(message.metadata)) return true
  return isRunningMessageStatus(message.status)
}

function useIsStreamingMessage(): boolean {
  return useAuiState((s) => isStreamingMessageState(s.message))
}

function currentTurnSubagentToolCallIds(activities: readonly RunActivity[]): readonly string[] {
  const ids = new Set<string>()
  for (const activity of activities) {
    if (activity.kind === 'subagent' && activity.toolCallId) ids.add(activity.toolCallId)
  }
  return Array.from(ids)
}

function isVisibleProgressActivity(activity: RunActivity): boolean {
  return (
    activity.kind !== 'interrupt' &&
    activity.kind !== 'responding' &&
    activity.status !== 'complete' &&
    activity.status !== 'cancelled'
  )
}

export function StreamingMessageLoadingIndicator({
  activities = [],
  deepAgentsState,
  className,
}: StreamingMessageLoadingIndicatorProps) {
  const isStreamingMessage = useIsStreamingMessage()
  const semanticActivities = useMemo(
    () => activities.filter((activity) => activity.kind !== 'interrupt'),
    [activities],
  )
  const progressActivities = useMemo(
    () => semanticActivities.filter(isVisibleProgressActivity),
    [semanticActivities],
  )
  const subagentToolCallIds = useMemo(
    () => currentTurnSubagentToolCallIds(semanticActivities),
    [semanticActivities],
  )
  const subagentProgress = useSubagentProgressSummary(subagentToolCallIds)
  if (!isStreamingMessage) return null
  const hasActivities = progressActivities.length > 0
  // Todos are owned by the assistant message's persistent "Plan" card
  // (the write_todos tool-ui), so the live panel only earns its place when it
  // has files — its live-only content. Gating on files (not all deep-agents
  // state) keeps the planning todos from rendering twice while a run streams,
  // and avoids an empty panel when only todos exist.
  const filesState = deepAgentsState && deepAgentsState.files.length > 0 ? deepAgentsState : null
  const hasSubagentProgress = subagentProgress.total > 0
  const hasStatusPanel = hasActivities || filesState !== null || hasSubagentProgress

  return (
    <AuiIf condition={(s) => s.thread.isRunning}>
      {hasStatusPanel ? (
        <div
          className={cn('mb-1 flex flex-col gap-1.5', className)}
          data-slot="streaming-status-panel"
        >
          {filesState ? <DeepAgentsStatePanel state={filesState} showTodos={false} /> : null}
          {hasSubagentProgress ? <SubagentProgress summary={subagentProgress} /> : null}
          {hasActivities ? <RunActivityStrip activities={semanticActivities} /> : null}
        </div>
      ) : (
        <WittyLoadingMessage className={cn('pointer-events-none mb-1 px-1', className)} />
      )}
    </AuiIf>
  )
}
