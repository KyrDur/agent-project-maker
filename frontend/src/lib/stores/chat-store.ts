import { atom } from 'jotai'
import type { TokenUsageBreakdown } from '@/lib/types'

export interface TokenUsage {
  inputTokens: number
  outputTokens: number
  cost: number
}

export const sessionTokenUsageAtom = atom<TokenUsage>({
  inputTokens: 0,
  outputTokens: 0,
  cost: 0,
})

/**
 * 最近一个 assistant turn 的 usage breakdown（非 session 累计）。context window usage
 * gauge 使用 `prompt_tokens`（= LangChain `input_tokens`，包含 cache 的总
 * input）作为占用量。session 累计（`sessionTokenUsageAtom`）会把每个 turn 的 input+output
 * 全部相加，用作 context 占用会过度计算，因此放在独立 atom。首个 turn 前或
 * 模型未发布 usage 时为 null。
 */
export const latestTurnUsageAtom = atom<TokenUsageBreakdown | null>(null)

/** SSE stream 重连 indicator 状态。仅在 ``reconnecting`` 期间显示 badge。
 *  失败时发出 toast 后立即回到 idle（无永久 badge）。 */
export type ReconnectState = 'idle' | 'reconnecting'

export const reconnectStateAtom = atom<ReconnectState>('idle')

/** server cancel 请求进行期间，用于阻止连续点击 Stop 按钮的 UI 状态。 */
export const chatCancelInFlightAtom = atom(false)

export interface PendingEditBranchPickerSuppression {
  conversationId: string | null
  messageId: string | null
  content: string
}

export const pendingEditBranchPickerSuppressionAtom =
  atom<PendingEditBranchPickerSuppression | null>(null)
