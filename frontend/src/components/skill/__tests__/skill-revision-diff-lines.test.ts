import { describe, expect, it } from 'vitest'

import { computeCappedRevisionDiffLines, countInputLines } from '../skill-revision-diff-card'
import { computeRevisionDiffLines, hasRevisionDiffChanges } from '../skill-revision-diff-lines'

describe('computeRevisionDiffLines', () => {
  it('将新增/删除/上下文行扁平化', () => {
    const before = 'line-1\nline-2\nline-3\n'
    const after = 'line-1\nline-2-changed\nline-3\n'

    const lines = computeRevisionDiffLines(before, after)

    expect(lines).toEqual([
      { type: 'context', text: 'line-1' },
      { type: 'removed', text: 'line-2' },
      { type: 'added', text: 'line-2-changed' },
      { type: 'context', text: 'line-3' },
    ])
    expect(hasRevisionDiffChanges(lines)).toBe(true)
  })

  it('内容相同时只返回上下文行', () => {
    const text = 'same\ncontent\n'
    const lines = computeRevisionDiffLines(text, text)

    expect(lines.every((line) => line.type === 'context')).toBe(true)
    expect(hasRevisionDiffChanges(lines)).toBe(false)
  })

  it('与空原文对比时全部为新增行（首个修订版契约）', () => {
    const lines = computeRevisionDiffLines('', 'a\nb\n')

    expect(lines).toEqual([
      { type: 'added', text: 'a' },
      { type: 'added', text: 'b' },
    ])
  })

  it('CRLF↔LF 换行差异不计为变更 (stripTrailingCr)', () => {
    const lines = computeRevisionDiffLines('a\r\nb\r\n', 'a\nb\n')

    expect(hasRevisionDiffChanges(lines)).toBe(false)
  })

  it('仅末尾换行有无不同的文件，不应把最后一行标成幽灵变更', () => {
    // jsdiff 将 'b' 和 'b\n' 视为同一行（newline 差异不算变更）。
    const lines = computeRevisionDiffLines('a\nb', 'a\nb\n')

    expect(hasRevisionDiffChanges(lines)).toBe(false)
  })

  it('将多行 chunk 拆为单独行，末尾换行不计作一行', () => {
    const lines = computeRevisionDiffLines('x\n', 'x\ny\nz\n')

    expect(lines).toEqual([
      { type: 'context', text: 'x' },
      { type: 'added', text: 'y' },
      { type: 'added', text: 'z' },
    ])
  })
})

describe('countInputLines (diff 预检查, R5)', () => {
  // 在 O(ND) Myers 之前做低成本上限检查 — diff 输出行数至少为 max(输入行数)，
  // 因此若仅凭一侧输入就能确定超过上限，则跳过 diff。
  it('按换行统计行数，不进行分配', () => {
    expect(countInputLines('')).toBe(1)
    expect(countInputLines('a')).toBe(1)
    expect(countInputLines('a\nb')).toBe(2)
    expect(countInputLines('a\nb\n')).toBe(3)
  })

  it('病态输入（数万行）也能立即计数', () => {
    const huge = 'x\n'.repeat(200_000)
    const start = performance.now()
    expect(countInputLines(huge)).toBe(200_001)
    expect(performance.now() - start).toBeLessThan(200)
  })
})

describe('computeCappedRevisionDiffLines (检查顺序契约, R6)', () => {
  it('相同文本即使大小超过上限也应为 "无变更"（空数组）— 禁止误标 tooLarge', () => {
    // 6千行无变更回滚修订版 — 如果预检查先执行，会被误标为"变更过大"
    // 。
    const huge = 'line\n'.repeat(6_000)
    expect(computeCappedRevisionDiffLines(huge, huge)).toEqual([])
  })

  it('如果一侧输入超过上限且内容不同，则不做 diff，返回 null(placeholder)', () => {
    const huge = 'line\n'.repeat(6_000)
    expect(computeCappedRevisionDiffLines(huge, 'other\n')).toBeNull()
    expect(computeCappedRevisionDiffLines('other\n', huge)).toBeNull()
  })

  it('上限内的变更正常返回 diff 行', () => {
    const lines = computeCappedRevisionDiffLines('a\n', 'b\n')
    expect(lines).toEqual([
      { type: 'removed', text: 'a' },
      { type: 'added', text: 'b' },
    ])
  })

  it('仅 CRLF↔LF·末尾换行不同的超上限对也应为 "无变更" — 该选项针对的输入类别 (R7)', () => {
    const lf = 'line\n'.repeat(6_000)
    const crlf = 'line\r\n'.repeat(6_000)
    expect(computeCappedRevisionDiffLines(crlf, lf)).toEqual([])
    expect(computeCappedRevisionDiffLines(lf, lf.slice(0, -1))).toEqual([])
  })

  it("''↔'\\n' 和 '\\n\\n'↔'\\n' 是真实变更 — 若规范化后合并，会产生错误的无变更 (R8)", () => {
    // ''(0行) vs '\n'(1个空行)：按 jsdiff 标准属于新增空行 — strip 规范化会
    // 把两者都变成 '',错误标记为"无变更"。
    const emptyVsNewline = computeCappedRevisionDiffLines('', '\n')
    expect(emptyVsNewline).not.toBeNull()
    expect(emptyVsNewline).not.toEqual([])
    // '\n\n' vs '\n'：删除一个空行 — strip 1 次规范化后的残余合并类别。
    const doubleVsSingle = computeCappedRevisionDiffLines('\n\n', '\n')
    expect(doubleVsSingle).not.toBeNull()
    expect(doubleVsSingle).not.toEqual([])
  })
})
