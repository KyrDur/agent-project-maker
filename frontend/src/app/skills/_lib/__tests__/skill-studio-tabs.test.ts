import { describe, expect, it } from 'vitest'

import {
  deriveSkillStudioContext,
  legacyDetailTabToStudioTab,
  skillStudioTabHref,
} from '../skill-studio-tabs'

const SKILL_ID = '11111111-2222-3333-4444-555555555555'
const SESSION_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

describe('deriveSkillStudioContext', () => {
  it('列表 route 是 list tab', () => {
    expect(deriveSkillStudioContext('/skills')).toEqual({
      activeTab: 'list',
      skillId: null,
      sessionId: null,
    })
  })

  it('builder index/session route 是 builder tab + sessionId', () => {
    expect(deriveSkillStudioContext('/skills/builder')).toEqual({
      activeTab: 'builder',
      skillId: null,
      sessionId: null,
    })
    expect(deriveSkillStudioContext(`/skills/builder/${SESSION_ID}`)).toEqual({
      activeTab: 'builder',
      skillId: null,
      sessionId: SESSION_ID,
    })
  })

  it('原样激活 skill scope tab segment', () => {
    for (const tab of ['evaluation', 'versions', 'source', 'settings'] as const) {
      expect(deriveSkillStudioContext(`/skills/${SKILL_ID}/${tab}`)).toEqual({
        activeTab: tab,
        skillId: SKILL_ID,
        sessionId: null,
      })
    }
  })

  it('没有 tab segment 或值未知时按 source 解释（与 server redirect 相同）', () => {
    expect(deriveSkillStudioContext(`/skills/${SKILL_ID}`).activeTab).toBe('source')
    expect(deriveSkillStudioContext(`/skills/${SKILL_ID}/unknown`).activeTab).toBe('source')
  })

  it('null/无关 route fallback 到 list', () => {
    expect(deriveSkillStudioContext(null).activeTab).toBe('list')
    expect(deriveSkillStudioContext('/agents').activeTab).toBe('list')
  })
})

describe('skillStudioTabHref', () => {
  it('skill scope tab 在没有 context skill 时为 null（disabled）', () => {
    expect(skillStudioTabHref('evaluation', null)).toBeNull()
    expect(skillStudioTabHref('evaluation', SKILL_ID)).toBe(`/skills/${SKILL_ID}/evaluation`)
  })

  it('builder tab 将 context skill 传给 index query', () => {
    expect(skillStudioTabHref('builder', null)).toBe('/skills/builder')
    expect(skillStudioTabHref('builder', SKILL_ID)).toBe(`/skills/builder?skillId=${SKILL_ID}`)
  })

  it('list tab 始终是 /skills', () => {
    expect(skillStudioTabHref('list', SKILL_ID)).toBe('/skills')
  })
})

describe('legacyDetailTabToStudioTab', () => {
  it('legacy dialog tab → studio segment 映射（M2b redirect 契约）', () => {
    expect(legacyDetailTabToStudioTab('content')).toBe('source')
    expect(legacyDetailTabToStudioTab('credentials')).toBe('settings')
    expect(legacyDetailTabToStudioTab('metadata')).toBe('settings')
    expect(legacyDetailTabToStudioTab('evaluation')).toBe('evaluation')
    expect(legacyDetailTabToStudioTab('history')).toBe('versions')
    expect(legacyDetailTabToStudioTab(null)).toBe('source')
    expect(legacyDetailTabToStudioTab('bogus')).toBe('source')
  })
})
