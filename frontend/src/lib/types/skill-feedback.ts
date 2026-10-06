/** Phase 3 技能级 human feedback（仅展示 — 不影响 pass_rate/health）。 */

export type SkillFeedbackRating = 'up' | 'down'

export type SkillFeedbackMine = {
  readonly rating: SkillFeedbackRating | string
  readonly comment?: string | null
  readonly updated_at: string
}

export type SkillFeedbackSummary = {
  readonly skill_id: string
  readonly up_count: number
  readonly down_count: number
  readonly mine?: SkillFeedbackMine | null
}

export type SkillFeedbackUpsert = {
  readonly rating: SkillFeedbackRating
  readonly comment?: string | null
}
