import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'

/**
 * Follow-up ghost 建议状态。
 *
 * - `followupEnabledAtom`：开关选项 — 在对话页面（composer toolbar）中 toggle，
 *   并持久化到 localStorage（浏览器全局设置）。
 * - `chatFollowupSuggestionAtom`：每个对话当前 1 条建议。run 结束时由
 *   use-followup-suggestion 填充，新 run 开始·Esc 解除·接受时清空。
 */

export const followupEnabledAtom = atomWithStorage<boolean>('moldy-followup-enabled', true)

export type ChatFollowupState = Record<string, string | null>

export const chatFollowupSuggestionAtom = atom<ChatFollowupState>({})

export const setConversationFollowupAtom = atom(
  null,
  (get, set, payload: { conversationId: string; suggestion: string | null }) => {
    const current = get(chatFollowupSuggestionAtom)
    set(chatFollowupSuggestionAtom, {
      ...current,
      [payload.conversationId]: payload.suggestion,
    })
  },
)
