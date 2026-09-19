import { describe, expect, it } from 'vitest'
import { parsePhaseNarration } from '../builder-phase-parser'

describe('parsePhaseNarration', () => {
  it('returns the original text when no phase markers are present', () => {
    const segs = parsePhaseNarration('你好！我们一步步来创建。')
    expect(segs).toEqual([{ kind: 'text', text: '你好！我们一步步来创建。' }])
  })

  it('extracts a [Phase N 已完成] marker and trims redundant narration', () => {
    const segs = parsePhaseNarration('[Phase 1 已完成] 项目初始化已完成。')
    expect(segs).toEqual([{ kind: 'event', phaseId: 1, transition: 'completed' }])
  })

  it('extracts "现在开始 Phase N：<name>" as a started event', () => {
    const segs = parsePhaseNarration('现在开始 Phase 2：用户意图分析。')
    expect(segs).toEqual([{ kind: 'event', phaseId: 2, transition: 'started' }])
  })

  it('handles the full mid-session narration from the conversational builder', () => {
    const text =
      '我来帮你创建智能体！ 现在开始 Phase 1：项目初始化。' +
      '[Phase 1 已完成] 项目初始化已完成。 现在开始 Phase 2：用户意图分析。' +
      '接下来分析用户意图。'

    const segs = parsePhaseNarration(text)
    // 问候 + Phase 1 开始 + Phase 1 完成 + Phase 2 开始 + 后续说明
    expect(segs).toEqual([
      { kind: 'text', text: '我来帮你创建智能体！' },
      { kind: 'event', phaseId: 1, transition: 'started' },
      { kind: 'event', phaseId: 1, transition: 'completed' },
      { kind: 'event', phaseId: 2, transition: 'started' },
      { kind: 'text', text: '接下来分析用户意图。' },
    ])
  })

  it('dedupes consecutive identical events', () => {
    const text = '[Phase 1 已完成] [Phase 1 已完成]'
    const segs = parsePhaseNarration(text)
    expect(segs).toEqual([{ kind: 'event', phaseId: 1, transition: 'completed' }])
  })

  it('ignores out-of-range phase ids', () => {
    const text = 'Phase 9: foo. Phase 0: bar.'
    const segs = parsePhaseNarration(text)
    expect(segs).toEqual([{ kind: 'text', text }])
  })

  it('returns empty for empty input', () => {
    expect(parsePhaseNarration('')).toEqual([])
  })
})
