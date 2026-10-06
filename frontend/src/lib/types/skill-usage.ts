/** Phase 3 技能维度 usage 摘要 — 仅实测归属（evaluation run token/cost + chat 执行次数）。 */

export type SkillUsageDailyPoint = {
  readonly date: string
  readonly tokens_in: number
  readonly tokens_out: number
  readonly cost_usd: number
  readonly execution_count: number
}

export type SkillUsageSummary = {
  readonly skill_id: string
  readonly days: number
  readonly tokens_in: number
  readonly tokens_out: number
  /** 已知单价 event 的 cost 总和 — 无单价 event 不计入。 */
  readonly cost_usd: number
  readonly priced_event_count: number
  /** 使用了 token 但没有单价、因此 cost 未知的 event 数量（未知 ≠ 免费）。 */
  readonly unpriced_token_event_count: number
  readonly evaluation_run_count: number
  readonly chat_execution_count: number
  readonly daily: readonly SkillUsageDailyPoint[]
}
