'use client'

import { useRef, useState } from 'react'
import type { ToolCallMessagePartProps } from '@assistant-ui/react'
import { useTranslations } from 'next-intl'
import {
  BlocksIcon,
  BookOpenIcon,
  CheckIcon,
  FolderIcon,
  PencilIcon,
  PlugIcon,
  WrenchIcon,
  XIcon,
} from 'lucide-react'
import {
  BuilderActionRow,
  BuilderBody,
  BuilderButton,
  BuilderFeedbackWrap,
  BuilderHeaderIcon,
  BuilderMuted,
  BuilderPath,
  BuilderPhaseLabel,
  BuilderRow,
  BuilderRowIcon,
  BuilderSummary,
  BuilderTag,
  BuilderTextarea,
  BuilderTitle,
} from './builder-primitives'
import { PhaseCard, PhaseCardFooter, PhaseCardHeader } from './phase-card'
import { useApprovalForm, type ApprovalFormState } from './use-approval-form'
import { useMiddlewares } from '@/lib/hooks/use-middlewares'

type ItemKind = 'tool' | 'middleware'
type RowKind = 'tool' | 'mcp' | 'skill' | 'planned' | 'generated_skill' | 'middleware'

interface ToolItem {
  tool_name?: string
  middleware_name?: string
  description?: string
  reason?: string
  path?: string
  kind?: 'tool' | 'mcp' | 'skill' | 'planned' | 'generated_skill'
  content?: string
}

interface RecommendationArgs {
  phase: number
  title: string
  items: ToolItem[]
  summary?: string
  retry_only?: boolean
  item_kind: ItemKind
}

const ROW_PATH_PREFIX: Record<RowKind, string> = {
  tool: 'tools',
  mcp: 'mcp',
  skill: 'skills',
  generated_skill: 'skills',
  planned: 'planned-tools',
  middleware: 'middlewares',
}

const ROW_ICON: Record<RowKind, typeof WrenchIcon> = {
  tool: WrenchIcon,
  mcp: PlugIcon,
  skill: BookOpenIcon,
  generated_skill: BookOpenIcon,
  planned: PlugIcon,
  middleware: BlocksIcon,
}

function getItemName(item: ToolItem, kind: ItemKind): string {
  if (kind === 'tool') return item.tool_name ?? ''
  return item.middleware_name ?? ''
}

function resolveRowKind(item: ToolItem, cardKind: ItemKind): RowKind {
  if (cardKind === 'middleware') return 'middleware'
  return item.kind ?? 'tool'
}

function getItemPath(item: ToolItem, rowKind: RowKind): string {
  if (item.path) return item.path
  const name = rowKind === 'middleware' ? (item.middleware_name ?? '') : (item.tool_name ?? '')
  return `${ROW_PATH_PREFIX[rowKind]}/${name}.yaml`
}

function ToolRecommendationHeader({
  cardKind,
  title,
  count,
  phase,
}: {
  cardKind: ItemKind
  title: string
  count: number
  phase: number
}) {
  const t = useTranslations('chat.recommendation')
  const HeaderIcon = cardKind === 'middleware' ? BlocksIcon : WrenchIcon
  return (
    <PhaseCardHeader>
      <BuilderHeaderIcon>
        <HeaderIcon className="size-3" />
      </BuilderHeaderIcon>
      <BuilderTitle>{title}</BuilderTitle>
      <BuilderMuted>{t('reviewCount', { count })}</BuilderMuted>
      <div className="flex-1" />
      <BuilderPhaseLabel>PHASE {phase}</BuilderPhaseLabel>
    </PhaseCardHeader>
  )
}

function ToolRow({
  item,
  cardKind,
  middleware,
}: {
  item: ToolItem
  cardKind: ItemKind
  middleware?: { display_name: string; description: string }
}) {
  const t = useTranslations('chat.recommendation')
  const name = getItemName(item, cardKind)
  const rowKind = resolveRowKind(item, cardKind)
  const Icon = ROW_ICON[rowKind]
  const path = getItemPath(item, rowKind)
  const purposeKey = `middlewarePurposes.${name}`
  const purpose =
    cardKind === 'middleware' && t.has(purposeKey)
      ? t(purposeKey)
      : middleware?.description || item.description

  return (
    <BuilderRow>
      <BuilderRowIcon>
        <Icon className="size-4" />
      </BuilderRowIcon>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          {middleware ? (
            <BuilderTitle>{middleware.display_name}</BuilderTitle>
          ) : (
            <code className="moldy-builder-code font-mono">{name}</code>
          )}
          <BuilderTag>{rowKind === 'planned' ? t('planned') : t('recommended')}</BuilderTag>
        </div>
        <div className="mb-1.5 inline-flex items-center gap-1 moldy-builder-color-muted">
          <FolderIcon className="size-2.5" />
          <BuilderPath>{path}</BuilderPath>
        </div>
        {purpose && (
          <p className="mb-1.5 moldy-builder-copy">
            <span className="mr-1.5 font-semibold moldy-builder-color-muted">{t('purpose')}</span>
            {purpose}
          </p>
        )}
        {item.reason && (
          <p className="moldy-builder-copy">
            <span className="mr-1.5 font-semibold moldy-builder-color-muted">{t('reason')}</span>
            {item.reason}
          </p>
        )}
      </div>
    </BuilderRow>
  )
}

function FeedbackTextarea({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  disabled: boolean
}) {
  const t = useTranslations('chat.recommendation')
  const composingRef = useRef(false)

  return (
    <BuilderFeedbackWrap>
      <BuilderTextarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onCompositionStart={() => {
          composingRef.current = true
        }}
        onCompositionEnd={() => {
          composingRef.current = false
        }}
        // 中文输入法组合期间不触发提交，提交由按钮完成。
        onKeyDown={(e) => {
          if (e.key === 'Enter' && composingRef.current) {
            e.stopPropagation()
          }
        }}
        placeholder={t('feedbackPlaceholder')}
        rows={2}
        disabled={disabled}
      />
    </BuilderFeedbackWrap>
  )
}

function ApproveButton({
  onClick,
  disabled,
  submitted,
  retryOnly,
}: {
  onClick: () => void
  disabled: boolean
  submitted: boolean
  retryOnly?: boolean
}) {
  const t = useTranslations('chat.recommendation')
  return (
    <BuilderButton tone="primary" onClick={onClick} disabled={disabled} className="px-4">
      <CheckIcon className="size-3" strokeWidth={3} />
      {submitted ? t('approved') : retryOnly ? t('retry') : t('approveAndContinue')}
    </BuilderButton>
  )
}

function RejectButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  const t = useTranslations('chat.recommendation')
  return (
    <BuilderButton tone="secondary" onClick={onClick} disabled={disabled}>
      <XIcon className="size-3" strokeWidth={2.5} />
      {t('requestRevision')}
    </BuilderButton>
  )
}

function FooterRow({
  form,
  feedbackOpen,
  setFeedbackOpen,
  approveDisabled = false,
  retryOnly = false,
}: {
  form: ApprovalFormState
  approveDisabled?: boolean
  retryOnly?: boolean
  feedbackOpen: boolean
  setFeedbackOpen: (v: boolean) => void
}) {
  const t = useTranslations('chat.recommendation')
  const { submitted, isLocked, handleApprove, handleRevision } = form

  return (
    <BuilderActionRow>
      {!retryOnly && (
        <BuilderButton
          tone="ghost"
          onClick={() => setFeedbackOpen(!feedbackOpen)}
          disabled={isLocked}
        >
          <PencilIcon className="size-3" />
          {feedbackOpen ? t('closeFeedback') : t('writeFeedback')}
        </BuilderButton>
      )}
      <div className="flex items-center gap-2">
        {!retryOnly && <RejectButton onClick={handleRevision} disabled={isLocked} />}
        <ApproveButton
          onClick={handleApprove}
          disabled={isLocked || approveDisabled}
          retryOnly={retryOnly}
          submitted={submitted === 'approved'}
        />
      </div>
    </BuilderActionRow>
  )
}

function RecommendationApproval({
  args,
  status,
}: {
  args: RecommendationArgs
  status: 'running' | 'complete' | 'incomplete' | 'requires-action'
}) {
  const t = useTranslations('chat.recommendation')
  const [reason, setReason] = useState('')
  const [skillContents, setSkillContents] = useState<Record<string, string>>({})
  const needsReason = args.phase === 3 && !args.retry_only
  const form = useApprovalForm({
    isComplete: status === 'complete',
    approvePayload: needsReason
      ? () => ({ approved: true, reason, skill_contents: skillContents })
      : undefined,
    approveDisplay: t('approve'),
    revisionFallback: t('requestRevision'),
  })
  const [feedbackOpen, setFeedbackOpen] = useState(false)

  const items = args.items ?? []
  const cardKind = args.item_kind ?? 'tool'
  const { data: middlewares } = useMiddlewares({ enabled: cardKind === 'middleware' })
  const title = args.title || (cardKind === 'middleware' ? t('middlewareTitle') : t('toolTitle'))

  return (
    <div className="my-3">
      <PhaseCard
        header={
          <ToolRecommendationHeader
            cardKind={cardKind}
            title={title}
            count={items.length}
            phase={args.phase}
          />
        }
        footer={
          // 确认后移除编辑操作，保留确认时的卡片记录。
          form.isLocked ? null : (
            <PhaseCardFooter>
              {needsReason && (
                <label className="block space-y-2">
                  <span>{t('confirmationReason')}</span>
                  <BuilderTextarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    disabled={form.isLocked}
                    required
                    rows={2}
                  />
                </label>
              )}
              {feedbackOpen && (
                <FeedbackTextarea
                  value={form.revision}
                  onChange={form.setRevision}
                  disabled={form.isLocked}
                />
              )}
              <FooterRow
                form={form}
                approveDisabled={needsReason && !reason.trim()}
                retryOnly={args.retry_only}
                feedbackOpen={feedbackOpen}
                setFeedbackOpen={setFeedbackOpen}
              />
            </PhaseCardFooter>
          )
        }
      >
        <BuilderBody>
          {items.length === 0 && (
            <p className="px-2.5 py-3 moldy-ui-body-sm moldy-builder-color-muted">{t('empty')}</p>
          )}
          {items.map((item, idx) => (
            <div key={idx}>
              <ToolRow
                key={idx}
                item={item}
                cardKind={cardKind}
                middleware={
                  cardKind === 'middleware'
                    ? middlewares?.find((entry) => entry.type === item.middleware_name)
                    : undefined
                }
              />
              {item.kind === 'generated_skill' && (
                <label className="block space-y-2 p-3">
                  <span>{t('skillPreview')}</span>
                  <BuilderTextarea
                    rows={12}
                    disabled={form.isLocked}
                    value={skillContents[item.tool_name ?? ''] ?? item.content ?? ''}
                    onChange={(e) =>
                      setSkillContents((prev) => ({
                        ...prev,
                        [item.tool_name ?? '']: e.target.value,
                      }))
                    }
                  />
                </label>
              )}
            </div>
          ))}
        </BuilderBody>
        {args.summary && <BuilderSummary>{args.summary}</BuilderSummary>}
      </PhaseCard>
    </div>
  )
}

export function RecommendationApprovalToolUI({
  args,
  status,
}: ToolCallMessagePartProps<RecommendationArgs, unknown>) {
  return <RecommendationApproval args={args} status={status.type} />
}
