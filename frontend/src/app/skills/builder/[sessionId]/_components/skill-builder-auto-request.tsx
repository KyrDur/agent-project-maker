'use client'

import { useEffect, useRef } from 'react'
import { useAui, useAuiState } from '@assistant-ui/react'

import { reportClientWarning } from '@/lib/logging/client-logger'
import type { MessagesEnvelope } from '@/lib/types'
import type { SkillBuilderSession } from '@/lib/types/skill-builder'

/**
 * 判断是否可以自动发出首条消息 — 基于 server truth 的 guard（纯函数，Phase 1.5）。
 *
 * create/improve dialog 的 user_request 在创建 session 时只会保存，不会发送，
 * 因此用户此前必须在 builder 页面重新输入同一请求。仅当以下条件全部
 * 为真时才自动发送：
 *
 * - session 为 v2 active 状态（`active`）— 排除重新进入 completed/confirming session
 * - envelope query 已 resolved — loading 中禁止判断
 * - 对话历史 0 条 + 无 run 历史（active/latest 均无）— 防止 reload·中断 run 重发
 */
export function resolveAutoFirstMessage(
  session: Pick<SkillBuilderSession, 'status' | 'user_request'> | undefined,
  envelope: MessagesEnvelope | undefined,
): string | null {
  if (!session || session.status !== 'active') return null
  if (!envelope) return null
  if ((envelope.messages?.length ?? 0) > 0) return null
  if (envelope.active_run || envelope.latest_run) return null
  const text = session.user_request?.trim()
  return text ? text : null
}

/**
 * 在首次进入 builder 时，将 user_request 自动作为第一条用户消息发送。
 *
 * 通过 AssistantThread 的 composerHint slot 渲染，因此位于 AssistantRuntimeProvider
 * context 内，可以执行 thread append（沿用 SkillBuilderTryHint 先例）。
 *
 * 三重重发 guard：① 仅当父级基于 server truth（resolveAutoFirstMessage）下发 text 时，
 * ② live thread 非空则 no-op（防止 remount 重复发出），
 * ③ ref latch（防止 StrictMode effect 重复执行）。
 */
export function SkillBuilderAutoRequest({ text }: { readonly text: string | null }) {
  const aui = useAui()
  // 防御部分 mock state — 不知道 thread 状态时不发出消息（fail-closed）。
  const isThreadEmpty = useAuiState((s) => s.thread?.isEmpty ?? false)
  const sentRef = useRef(false)

  useEffect(() => {
    if (!text || sentRef.current || !isThreadEmpty) return
    sentRef.current = true
    try {
      // 与 clarifying-question-ui 相同 pattern — 直接向 thread append user message。
      aui.thread.append({ content: [{ type: 'text', text }] })
    } catch (err) {
      reportClientWarning('skill-builder', 'auto first message append error:', err)
    }
  }, [aui, isThreadEmpty, text])

  return null
}
