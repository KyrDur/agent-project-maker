/**
 * Builder phase narration 解析器。
 *
 * 从 机器人文本中提取被 dump 出来的 phase 切换文案（`[Phase N 完成]`、`现在开始 Phase N: <阶段名>`
 * 等），转换为 SystemEvent 事件，并原样返回剩余普通文本。
 *
 * 标准做法应由 backend 单独 emit `phase_transition` 事件；暂时不能改 backend 时，
 * 前端用正则 split 做 fallback。
 */

export type PhaseTransition = 'started' | 'completed'

export type PhaseSegment =
  | { kind: 'text'; text: string }
  | { kind: 'event'; phaseId: number; transition: PhaseTransition }

interface PatternMatch {
  start: number
  end: number
  phaseId: number
  transition: PhaseTransition
}

/**
 * Phase narration 模式 —— 按优先级顺序应用。每个正则的第 1 个捕获组是 phase id。
 *
 * 完成模式:
 *   - `[Phase N 完成]` + 后续 narration（如 `项目初始化完成。` 这类 redundant 单行）
 * 开始模式:
 *   - `现在开始 Phase N: <name> / 将继续进行`
 *   - `现在 Phase N ... 开始/进行`
 *   - `Phase N: <name>`（独立标题）
 */
const COMPLETED_PATTERNS: RegExp[] = [
  /\[Phase\s+(\d+)\s*(?:已完成|完成|completed)\][^\n.!?。！？\[]*[.!?。！？]?\s*/gi,
]

const STARTED_PATTERNS: RegExp[] = [
  /(?:现在|接下来)[^\n.!?。！？]*?Phase\s+(\d+)[^\n.!?。！？]*[.!?。！？]?\s*/g,
  /Phase\s+(\d+)\s*[:：·][^\n.!?。！？]*[.!?。！？]?\s*/g,
]

function collectMatches(
  text: string,
  patterns: RegExp[],
  transition: PhaseTransition,
): PatternMatch[] {
  const matches: PatternMatch[] = []
  for (const re of patterns) {
    re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text)) !== null) {
      const phaseId = Number.parseInt(m[1] ?? '', 10)
      if (!Number.isFinite(phaseId) || phaseId < 1 || phaseId > 8) continue
      matches.push({
        start: m.index,
        end: m.index + m[0].length,
        phaseId,
        transition,
      })
    }
  }
  return matches
}

/**
 * 将文本拆分为 phase narration / 普通文本 片段。
 *
 * - 模式 作为 phase 切换 标记 提取 → 渲染为 SystemEvent。
 * - 匹配 之间的普通文本 trim 后保留为 文本片段。
 * - 连续提取到相同 phase + transition 时 dedup。
 */
export function parsePhaseNarration(text: string): PhaseSegment[] {
  if (!text) return []

  const all: PatternMatch[] = [
    ...collectMatches(text, COMPLETED_PATTERNS, 'completed'),
    ...collectMatches(text, STARTED_PATTERNS, 'started'),
  ]
  if (all.length === 0) return [{ kind: 'text', text }]

  // 按起始位置升序。重叠时 longer 优先 → 保留前面的 pattern
  all.sort((a, b) => a.start - b.start || b.end - a.end)
  const merged: PatternMatch[] = []
  let lastEnd = -1
  for (const m of all) {
    if (m.start >= lastEnd) {
      merged.push(m)
      lastEnd = m.end
    }
  }

  const segments: PhaseSegment[] = []
  let cursor = 0
  let lastEvent: { phaseId: number; transition: PhaseTransition } | null = null
  for (const m of merged) {
    if (m.start > cursor) {
      const slice = text.slice(cursor, m.start).trim()
      if (slice) segments.push({ kind: 'text', text: slice })
    }
    const isDup =
      lastEvent !== null && lastEvent.phaseId === m.phaseId && lastEvent.transition === m.transition
    if (!isDup) {
      segments.push({ kind: 'event', phaseId: m.phaseId, transition: m.transition })
      lastEvent = { phaseId: m.phaseId, transition: m.transition }
    }
    cursor = m.end
  }
  if (cursor < text.length) {
    const slice = text.slice(cursor).trim()
    if (slice) segments.push({ kind: 'text', text: slice })
  }
  return segments
}
