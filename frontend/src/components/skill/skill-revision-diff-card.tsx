'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { FileCode2 } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useSkillRevisionFileContent } from '@/lib/hooks/use-skill-revisions'
import { cn } from '@/lib/utils'
import type { SkillRevisionDetail, SkillRevisionSummary } from '@/lib/types/skill-revision'

import {
  computeRevisionDiffLines,
  hasRevisionDiffChanges,
  type RevisionDiffLine,
} from './skill-revision-diff-lines'

const SKILL_MD = 'SKILL.md'

// diff 计算/渲染上限 — 防止在 2MB 上限的病态输入中 Myers diff + 每行 DOM
// 卡住主线程（超限时显示 placeholder，引导到源查看器）。
const MAX_DIFF_LINES = 5000

/**
 * 选中修订版 vs parent 修订版的 SKILL.md 行 diff (Phase 2 模拟 ver-diff)。
 *
 * 首个修订版（无 parent）相对空原文视为全部新增，pruned 快照和
 * 内容 404（二进制等）按 placeholder 处理 — diff 在前端计算，
 * 后端只提供原文 (规范 AD-6)。
 */
export function SkillRevisionDiffCard({
  skillId,
  revision,
  detail,
}: {
  readonly skillId: string
  readonly revision: SkillRevisionSummary
  readonly detail?: SkillRevisionDetail
}) {
  const t = useTranslations('skill.studio.versions')
  const pruned = Boolean(detail?.metadata_json?.snapshot_pruned)
  const parentRevisionId = detail?.parent_revision_id ?? null
  // detail 加载前 pruned 尚未确定（看起来为 false）— 若直接 fetch，
  // 每次选择 pruned 修订版时，确定的 404 请求都会先于 placeholder 发出 (R5)。
  const contentEnabled = Boolean(detail) && !pruned
  const current = useSkillRevisionFileContent(
    skillId,
    contentEnabled ? revision.id : null,
    SKILL_MD,
  )
  const parent = useSkillRevisionFileContent(
    skillId,
    contentEnabled ? parentRevisionId : null,
    SKILL_MD,
  )

  return (
    <section
      className="space-y-2 rounded-lg border border-border/70 p-3"
      data-testid="revision-diff-card"
    >
      <div className="flex flex-wrap items-center gap-2">
        <FileCode2 className="size-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">{t('diffTitle')}</h3>
        {parentRevisionId === null && detail ? (
          <Badge variant="secondary" className="moldy-ui-micro">
            {t('initialRevision')}
          </Badge>
        ) : null}
        <Link
          href={`/skills/${skillId}/source?revision=${revision.id}`}
          className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'ml-auto')}
        >
          {t('viewRevisionSource')}
        </Link>
      </div>
      <DiffBody
        pruned={pruned}
        detailLoaded={Boolean(detail)}
        currentText={current.data?.content}
        currentError={current.isError}
        currentLoading={current.isLoading}
        parentText={parentRevisionId ? parent.data?.content : ''}
        parentError={parentRevisionId ? parent.isError : false}
        parentLoading={parentRevisionId ? parent.isLoading : false}
      />
    </section>
  )
}

function DiffBody({
  pruned,
  detailLoaded,
  currentText,
  currentError,
  currentLoading,
  parentText,
  parentError,
  parentLoading,
}: {
  readonly pruned: boolean
  readonly detailLoaded: boolean
  readonly currentText: string | undefined
  readonly currentError: boolean
  readonly currentLoading: boolean
  readonly parentText: string | undefined
  readonly parentError: boolean
  readonly parentLoading: boolean
}) {
  const t = useTranslations('skill.studio.versions')

  if (pruned) {
    return <DiffPlaceholder message={t('prunedPlaceholder')} />
  }
  if (!detailLoaded || currentLoading || parentLoading) {
    return <Skeleton className="h-24 w-full rounded-md" />
  }
  if (currentError || currentText === undefined) {
    return <DiffPlaceholder message={t('diffUnavailable')} />
  }
  // parent 快照若被 pruned/丢失，就没有比较基准 — 显式显示 placeholder。
  if (parentError || parentText === undefined) {
    return <DiffPlaceholder message={t('parentUnavailable')} />
  }

  return <DiffLines parentText={parentText} currentText={currentText} />
}

function DiffLines({
  parentText,
  currentText,
}: {
  readonly parentText: string
  readonly currentText: string
}) {
  const t = useTranslations('skill.studio.versions')
  // 不在每次父级重新渲染（rollback pending 等）时重新计算 diff。
  const lines = useMemo(
    () => computeCappedRevisionDiffLines(parentText, currentText),
    [parentText, currentText],
  )
  if (lines === null) {
    return <DiffPlaceholder message={t('diffTooLarge')} />
  }
  if (!hasRevisionDiffChanges(lines)) {
    return <DiffPlaceholder message={t('noChanges')} />
  }

  return (
    <pre className="max-h-96 overflow-auto rounded-md border border-border/60 bg-muted/30 p-2 font-mono text-xs">
      {lines.map((line, index) => (
        <DiffLineRow key={index} line={line} />
      ))}
    </pre>
  )
}

function DiffLineRow({ line }: { readonly line: RevisionDiffLine }) {
  const marker = line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '
  return (
    <div
      className={cn(
        'whitespace-pre-wrap break-all px-1',
        line.type === 'added' && 'moldy-status-success moldy-status-soft',
        line.type === 'removed' && 'moldy-status-danger moldy-status-soft',
      )}
    >
      {marker} {line.text}
    </div>
  )
}

/** 不分配内存的行数统计 — 让预检查本身在病态输入下也不昂贵。 */
export function countInputLines(text: string): number {
  let count = 1
  for (let i = 0; i < text.length; i += 1) {
    if (text.charCodeAt(i) === 10) count += 1
  }
  return count
}

/**
 * 带上限的 diff 计算 — null = 过大，省略 diff（引导 placeholder）。
 *
 * 顺序是契约的一部分 (R6)：① 相同文本无论大小都视为 "无变更"（空数组）
 * — 如果预检查先执行，6千行无变更回滚修订版会被误标为 "变更过大"。
 * ② 在 O(ND) Myers 前做低成本行数预检查 — diff 输出至少为 max(输入行数)，
 * 因此若只凭一侧输入即可确定超限，就直接跳过（仅靠事后检查会在 2MB 病态输入中，
 * 还没来得及决定 placeholder 就先冻住主线程，R5）。③ 事后检查 — 输入在上限内，
 * 但输出超过上限的情况。
 */
export function computeCappedRevisionDiffLines(
  parentText: string,
  currentText: string,
): readonly RevisionDiffLine[] | null {
  // 相同性用与 diff 选项(stripTrailingCr/ignoreNewlineAtEof)一致的规范化方式
  // 判断 — 如果只做字节比较，CRLF 快照 vs LF 修订版（正是该选项针对的
  // 输入类别）在超限时会被误标为"无变更"而不是"过大" (R7)。
  if (parentText === currentText) return []
  // 空字符串不参与规范化比较 — ''(0行) 与 '\n'(1个空行) 按 jsdiff
  // 标准属于真实变更，但规范化会把两者合并，产生错误的"无变更" (R8)。
  if (
    parentText !== '' &&
    currentText !== '' &&
    normalizeForIdentity(parentText) === normalizeForIdentity(currentText)
  ) {
    return []
  }
  if (
    countInputLines(parentText) > MAX_DIFF_LINES ||
    countInputLines(currentText) > MAX_DIFF_LINES
  ) {
    return null
  }
  const lines = computeRevisionDiffLines(parentText, currentText)
  return lines.length > MAX_DIFF_LINES ? null : lines
}

/** 与 diff 选项等价的相同性规范化 — CRLF→LF + 保证末尾换行(ensure)。
 * strip 方式会把 '\n\n' vs '\n' 合并成错误的"无变更" — 应补齐换行而不是删除，
 * 才与 ignoreNewlineAtEof("只忽略末尾是否有换行")等价 (R8)。 */
function normalizeForIdentity(text: string): string {
  const unified = text.includes('\r\n') ? text.split('\r\n').join('\n') : text
  return unified.endsWith('\n') ? unified : `${unified}\n`
}

function DiffPlaceholder({ message }: { readonly message: string }) {
  return (
    <div className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
      {message}
    </div>
  )
}
