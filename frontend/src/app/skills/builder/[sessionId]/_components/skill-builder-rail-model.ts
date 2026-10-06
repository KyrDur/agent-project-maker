import type { SkillDraftBrief } from '@/lib/stores/chat-skill-builder'
import type { SkillBuilderFileEntry } from '@/lib/types/skill-builder'

/**
 * 状态卡片派生逻辑（M7 — 借用 skill-studio mock）。
 *
 * 将 mock 的验证 row（Portable frontmatter / trigger 明确性 / Moldy metadata 分离 /
 * runtime compatibility / Credential / sandbox / evaluation）映射到 **真实 validator issue code**。
 * mock 固定的 "5/5 通过" 计数与真实数据（issue list）不符，因此调整为
 * pass/warn/error 三种状态（CHECKPOINT M7 audit note）。
 */

export type StatusTone = 'pass' | 'good' | 'warn' | 'error' | 'pending' | 'none'

export interface StatusRow {
  readonly key: 'frontmatter' | 'moldyMetadata' | 'trigger' | 'secrets' | 'other'
  readonly tone: StatusTone
  /** 来自 issue 的附加说明（第一条 issue message）。 */
  readonly detail: string | null
  /** 仅用于 'other' row — 未分类 issue 数量（用于 label interpolation）。 */
  readonly count?: number
}

export interface HeadState {
  readonly tone: 'pending' | 'pass' | 'warn' | 'error'
  readonly errorCount: number
  readonly warningCount: number
}

interface ValidationIssue {
  readonly code: string
  readonly severity: string
  readonly message: string
  readonly path?: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseIssues(validation: unknown): ValidationIssue[] {
  if (!isRecord(validation) || !Array.isArray(validation.issues)) return []
  const issues: ValidationIssue[] = []
  for (const raw of validation.issues) {
    if (!isRecord(raw)) continue
    const code = typeof raw.code === 'string' ? raw.code : ''
    const severity = typeof raw.severity === 'string' ? raw.severity : 'info'
    const message = typeof raw.message === 'string' ? raw.message : ''
    if (!code) continue
    issues.push({
      code,
      severity,
      message,
      path: typeof raw.path === 'string' ? raw.path : null,
    })
  }
  return issues
}

export function deriveHeadState(validation: unknown): HeadState {
  if (!isRecord(validation)) {
    return { tone: 'pending', errorCount: 0, warningCount: 0 }
  }
  const errorCount = typeof validation.error_count === 'number' ? validation.error_count : 0
  const warningCount = typeof validation.warning_count === 'number' ? validation.warning_count : 0
  if (errorCount > 0) return { tone: 'error', errorCount, warningCount }
  if (warningCount > 0) return { tone: 'warn', errorCount, warningCount }
  return { tone: 'pass', errorCount, warningCount }
}

function rowTone(matched: ValidationIssue[], passTone: StatusTone): StatusTone {
  if (matched.some((issue) => issue.severity === 'error')) return 'error'
  if (matched.some((issue) => issue.severity === 'warning')) return 'warn'
  return passTone
}

function firstMessage(matched: ValidationIssue[]): string | null {
  const significant = matched.find((issue) => issue.severity !== 'info')
  return significant?.message ?? null
}

/** validator issue code → mock check row。验证前（validation null）全部为 pending。 */
export function deriveStatusRows(validation: unknown): StatusRow[] {
  if (!isRecord(validation)) {
    return [
      { key: 'frontmatter', tone: 'pending', detail: null },
      { key: 'moldyMetadata', tone: 'pending', detail: null },
      { key: 'trigger', tone: 'pending', detail: null },
      { key: 'secrets', tone: 'pending', detail: null },
    ]
  }
  const issues = parseIssues(validation)
  const byPrefix = (prefixes: string[]) =>
    issues.filter((issue) => prefixes.some((prefix) => issue.code.startsWith(prefix)))

  const frontmatter = byPrefix(['SKILL_MD_', 'INVALID_PATH'])
  const moldyMetadata = byPrefix([
    'MOLDY_METADATA',
    'MOLDY_ONLY_FRONTMATTER',
    'CREDENTIAL_REQUIREMENT',
    'CREDENTIAL_ENV_',
    'UNKNOWN_CREDENTIAL_',
    'NETWORK_PROFILE_MISSING',
  ])
  const trigger = byPrefix(['WEAK_TRIGGER_DESCRIPTION', 'SCAFFOLDING_MARKER'])
  const secrets = byPrefix(['SECRET_DETECTED'])
  // fallback row（R3）：header pill 使用整体 error/warning count，但如果 detail row
  // 只映射其中子集，就会出现 "错误 1 / 详情全部通过" 的矛盾 — 上述 bucket 中
  // 未捕获的有效（非 info）issue 统一显示为 "其他检查 N 项"。
  const bucketed = new Set([...frontmatter, ...moldyMetadata, ...trigger, ...secrets])
  const other = issues.filter((issue) => !bucketed.has(issue) && issue.severity !== 'info')

  const rows: StatusRow[] = [
    { key: 'frontmatter', tone: rowTone(frontmatter, 'pass'), detail: firstMessage(frontmatter) },
    {
      key: 'moldyMetadata',
      tone: rowTone(moldyMetadata, 'pass'),
      detail: firstMessage(moldyMetadata),
    },
    // mock 中的 "好"(good) — 即使 trigger 文案通过，也属于质量信号，因此使用单独 tone。
    { key: 'trigger', tone: rowTone(trigger, 'good'), detail: firstMessage(trigger) },
    { key: 'secrets', tone: rowTone(secrets, 'pass'), detail: firstMessage(secrets) },
  ]
  if (other.length > 0) {
    rows.push({
      key: 'other',
      tone: rowTone(other, 'pass'),
      detail: firstMessage(other),
      count: other.length,
    })
  }
  return rows
}

export interface RailFileEntry {
  readonly path: string
  readonly size: number
}

/**
 * rail 文件列表 — 有 live brief（每次 run 更新）时优先，否则使用文件 API
 * （用于刚进入·显示 improve seed）。解决截图 13 中发现的 "刚进入时 rail 为空"。
 */
export function mergeRailFiles(
  brief: SkillDraftBrief | undefined,
  apiFiles: readonly SkillBuilderFileEntry[] | undefined,
): RailFileEntry[] {
  if (brief && brief.files.length > 0) {
    return brief.files.map((file) => ({ path: file.path, size: file.size }))
  }
  return (apiFiles ?? []).map((file) => ({ path: file.path, size: file.size }))
}

export function hasScripts(files: readonly RailFileEntry[]): boolean {
  return files.some((file) => file.path.startsWith('scripts/'))
}

export function hasEvals(files: readonly RailFileEntry[]): boolean {
  return files.some((file) => file.path === 'evals/evals.json')
}
