import { describe, expect, it } from 'vitest'

import {
  deriveHeadState,
  deriveStatusRows,
  hasEvals,
  hasScripts,
  mergeRailFiles,
} from '../skill-builder-rail-model'
import type { SkillDraftBrief } from '@/lib/stores/chat-skill-builder'

function brief(overrides: Partial<SkillDraftBrief> = {}): SkillDraftBrief {
  return {
    session_id: 's1',
    mode: 'create',
    slug: 'notes',
    file_count: 1,
    files: [{ path: 'SKILL.md', size: 100 }],
    changed_count: 1,
    credential_requirement_count: 0,
    ...overrides,
  }
}

describe('deriveHeadState', () => {
  it('验证前为 pending', () => {
    expect(deriveHeadState(null).tone).toBe('pending')
    expect(deriveHeadState(undefined).tone).toBe('pending')
  })

  it('error_count > 0 时为 error，仅有 warning 时为 warn，两者都没有时为 pass', () => {
    expect(deriveHeadState({ valid: false, error_count: 2, warning_count: 1 }).tone).toBe('error')
    expect(deriveHeadState({ valid: true, error_count: 0, warning_count: 3 }).tone).toBe('warn')
    expect(deriveHeadState({ valid: true, error_count: 0, warning_count: 0 }).tone).toBe('pass')
  })
})

describe('deriveStatusRows', () => {
  it('验证前所有 row 都是 pending', () => {
    const rows = deriveStatusRows(null)
    expect(rows).toHaveLength(4)
    expect(rows.every((row) => row.tone === 'pending')).toBe(true)
  })

  it('将 issue code 映射到 row — trigger warning/secret error', () => {
    const rows = deriveStatusRows({
      valid: false,
      error_count: 1,
      warning_count: 1,
      issues: [
        {
          code: 'WEAK_TRIGGER_DESCRIPTION',
          severity: 'warning',
          message: 'Description should state concrete trigger conditions.',
          path: 'SKILL.md',
        },
        {
          code: 'SECRET_DETECTED',
          severity: 'error',
          message: 'Potential secret detected by content scanner.',
          path: 'SKILL.md',
        },
      ],
    })
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]))
    expect(byKey.frontmatter.tone).toBe('pass')
    expect(byKey.moldyMetadata.tone).toBe('pass')
    expect(byKey.trigger.tone).toBe('warn')
    expect(byKey.trigger.detail).toContain('trigger conditions')
    expect(byKey.secrets.tone).toBe('error')
  })

  it('没有 issue 时 trigger row 为 good，其余为 pass', () => {
    const rows = deriveStatusRows({ valid: true, error_count: 0, warning_count: 0, issues: [] })
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]))
    expect(byKey.trigger.tone).toBe('good')
    expect(byKey.frontmatter.tone).toBe('pass')
    // 没有未分类 issue 时，也不存在 fallback row。
    expect(byKey.other).toBeUndefined()
  })

  it('bucket 外 issue 会显示为 "其他检查" fallback row（R3 — 防止 header/detail 矛盾）', () => {
    const rows = deriveStatusRows({
      valid: false,
      error_count: 1,
      warning_count: 1,
      issues: [
        {
          code: 'UNSUPPORTED_SCRIPT_EXTENSION',
          severity: 'error',
          message: 'Only .py scripts are supported.',
          path: 'scripts/run.sh',
        },
        {
          code: 'UNMENTIONED_REFERENCES',
          severity: 'warning',
          message: 'references/x.md is never mentioned.',
          path: 'references/x.md',
        },
        { code: 'SOME_INFO_ONLY', severity: 'info', message: 'ignore me', path: null },
      ],
    })
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]))
    expect(byKey.other).toBeDefined()
    expect(byKey.other.tone).toBe('error')
    expect(byKey.other.count).toBe(2) // 排除 info
    expect(byKey.other.detail).toContain('Only .py')
    // NETWORK_PROFILE_MISSING/CREDENTIAL_ENV_* 会归入 moldyMetadata bucket。
    const networkRows = deriveStatusRows({
      valid: false,
      error_count: 1,
      warning_count: 0,
      issues: [
        {
          code: 'NETWORK_PROFILE_MISSING',
          severity: 'error',
          message: 'network profile missing',
          path: 'agents/moldy.yaml',
        },
      ],
    })
    const networkByKey = Object.fromEntries(networkRows.map((row) => [row.key, row]))
    expect(networkByKey.moldyMetadata.tone).toBe('error')
    expect(networkByKey.other).toBeUndefined()
  })
})

describe('mergeRailFiles', () => {
  it('存在 live brief 时优先使用', () => {
    const merged = mergeRailFiles(brief(), [{ path: 'old.md', size: 1, role: 'asset' }])
    expect(merged.map((file) => file.path)).toEqual(['SKILL.md'])
  })

  it('brief 不存在或为空时 fallback 到文件 API（刚进入/improve seed）', () => {
    expect(
      mergeRailFiles(undefined, [{ path: 'SKILL.md', size: 10, role: 'skill' }]).map(
        (file) => file.path,
      ),
    ).toEqual(['SKILL.md'])
    expect(
      mergeRailFiles(brief({ files: [], file_count: 0 }), [
        { path: 'seeded.md', size: 5, role: 'reference' },
      ]).map((file) => file.path),
    ).toEqual(['seeded.md'])
  })
})

describe('hasScripts / hasEvals', () => {
  it('检测以 scripts/ 开头的文件以及 evals/evals.json', () => {
    const files = [
      { path: 'SKILL.md', size: 1 },
      { path: 'scripts/run.py', size: 1 },
      { path: 'evals/evals.json', size: 1 },
    ]
    expect(hasScripts(files)).toBe(true)
    expect(hasEvals(files)).toBe(true)
    expect(hasScripts([{ path: 'SKILL.md', size: 1 }])).toBe(false)
    expect(hasEvals([{ path: 'SKILL.md', size: 1 }])).toBe(false)
  })
})
