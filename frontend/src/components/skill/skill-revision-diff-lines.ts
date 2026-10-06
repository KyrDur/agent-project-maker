import { diffLines } from 'diff'

/** 修订版 SKILL.md 行 diff — 渲染器使用的扁平化行列表。 */
export type RevisionDiffLine = {
  readonly type: 'added' | 'removed' | 'context'
  readonly text: string
}

export function computeRevisionDiffLines(
  before: string,
  after: string,
): readonly RevisionDiffLine[] {
  const lines: RevisionDiffLine[] = []
  // stripTrailingCr — 比较 CRLF 快照（Windows 创建的 .skill）与 LF 修订版时，防止
  // 所有行被误标。ignoreNewlineAtEof — 仅末尾换行有无不同的最后一行
  // 不应形成幽灵 -x/+x 对（按内容而非字节做 diff）。
  for (const change of diffLines(before, after, {
    stripTrailingCr: true,
    ignoreNewlineAtEof: true,
  })) {
    const type = change.added ? 'added' : change.removed ? 'removed' : 'context'
    // diffLines 的 chunk 以换行结束 — 不把最后一个空片段计为一行。
    const chunk = change.value.endsWith('\n') ? change.value.slice(0, -1) : change.value
    for (const text of chunk.split('\n')) {
      lines.push({ type, text })
    }
  }
  return lines
}

export function hasRevisionDiffChanges(lines: readonly RevisionDiffLine[]): boolean {
  return lines.some((line) => line.type !== 'context')
}
