import { atom } from 'jotai'

/**
 * skill builder chat validation rail store（spec AD-5）。
 *
 * 将 `moldy.skill_draft`（stream-head draft 摘要）/ `moldy.skill_validation`
 * （validate_skill·finalize_skill 工具 projection）custom event
 * 按 conversationId scope 保存 — 镜像 chat-subagent-names 模式。
 * payload 仅用于摘要契约（文件路径/大小/计数 + validation issue）— 不含文件内容。
 */

export interface SkillDraftBriefFile {
  readonly path: string
  readonly size: number
}

export interface SkillDraftBrief {
  readonly session_id: string
  readonly mode: string
  readonly slug: string | null
  readonly file_count: number
  readonly files: readonly SkillDraftBriefFile[]
  readonly changed_count: number
  /** draft moldy.yaml 的 credential 需求数（状态卡片行，M7）。 */
  readonly credential_requirement_count: number
}

export interface SkillValidationSnapshot {
  readonly tool_name: string
  readonly session_id?: string
  readonly validation_result: Readonly<Record<string, unknown>>
}

/** conversationId → 最新 draft 摘要（每个 run 替换为最新值）。 */
export const chatSkillDraftBriefAtom = atom<Record<string, SkillDraftBrief>>({})

export const setConversationSkillDraftBriefAtom = atom(
  null,
  (get, set, update: { readonly conversationId: string; readonly brief: SkillDraftBrief }) => {
    const current = get(chatSkillDraftBriefAtom)
    set(chatSkillDraftBriefAtom, { ...current, [update.conversationId]: update.brief })
  },
)

/** conversationId → 最新 validation result projection（validate/finalize 工具结果）。 */
export const chatSkillValidationAtom = atom<Record<string, SkillValidationSnapshot>>({})

export const setConversationSkillValidationAtom = atom(
  null,
  (
    get,
    set,
    update: {
      readonly conversationId: string
      readonly snapshot: SkillValidationSnapshot
    },
  ) => {
    const current = get(chatSkillValidationAtom)
    set(chatSkillValidationAtom, { ...current, [update.conversationId]: update.snapshot })
  },
)
