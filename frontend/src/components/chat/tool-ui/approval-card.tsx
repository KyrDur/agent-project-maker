'use client'

import { useState, useCallback, useEffect, useId, useMemo } from 'react'
import type { ToolCallMessagePartProps } from '@assistant-ui/react'
import {
  ShieldCheckIcon,
  CheckIcon,
  XIcon,
  PencilIcon,
  Loader2Icon,
  ChevronDownIcon,
  WrenchIcon,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'
import { toApprove, toEdit, toReject } from '@/lib/chat/decision-mappers'
import { useHiTL } from '@/lib/chat/hitl-context'
import { useMultiApproval } from './multi-approval-context'
import {
  isSensitiveDisplayKey,
  redactSensitiveRecord,
  redactSensitiveText,
} from '@/lib/chat/sensitive-display'
import { useApprovalDeadline } from '@/lib/hooks/use-approval-deadline'
import type { Decision as StandardDecision } from '@/lib/types'
import { CountdownBadge } from './countdown-badge'

interface ApprovalArgs {
  /** 待审批工具名 */
  tool_name?: string
  /** 工具执行参数 */
  tool_args?: Record<string, unknown>
  /** 说明为什么需要审批 */
  description?: string
  /** 消息（替代 description） */
  message?: string
  /** 审批过期 timeout（秒）—— 未指定时为 5 分钟 */
  timeout_seconds?: number
  /** 审批标识符 —— 用作 deadline reset key */
  approval_id?: string
  /** 标准 HiTL interrupt 内的 action index */
  hitl_action_index?: number
  hitl_total_actions?: number
  hitl_interrupt_id?: string | null
  allowed_decisions?: StandardDecision['type'][]
  /** 技能 Builder AD-4 —— 显示 "留出本次会议的剩余时间" 选项（review_configs flag） */
  session_consent_eligible?: boolean
}

type Decision = 'approved' | 'modified' | 'rejected'
const REDACTED_PLACEHOLDER = '<redacted>'

interface ApprovalResult {
  decision: Decision
  modified_args?: Record<string, unknown>
  reason?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseApprovalResult(result: unknown): ApprovalResult | null {
  const value =
    typeof result === 'string'
      ? (() => {
          try {
            const parsed: unknown = JSON.parse(result)
            return parsed
          } catch {
            return null
          }
        })()
      : result
  if (!isRecord(value)) return null
  const decision = value.decision
  if (decision !== 'approved' && decision !== 'modified' && decision !== 'rejected') return null
  const modifiedArgs = isRecord(value.modified_args) ? value.modified_args : undefined
  const reason = typeof value.reason === 'string' ? value.reason : undefined
  return {
    decision,
    ...(modifiedArgs ? { modified_args: modifiedArgs } : {}),
    ...(reason ? { reason } : {}),
  }
}

function addApprovalResultIfSupported(
  addResult: (result: unknown) => void,
  result: ApprovalResult,
): boolean {
  try {
    addResult(result)
    return true
  } catch {
    return false
  }
}

function toDecision(
  d: Decision,
  response: ApprovalResult,
  toolName: string | undefined,
  options?: { sessionScope?: boolean },
): StandardDecision {
  switch (d) {
    case 'approved':
      return toApprove(options)
    case 'modified':
      // edited_action.name 由 backend 按 positional index 匹配 pending action 后
      // 权威填充。知道工具名时作为 advisory 附带，不知道则省略
      // （过去 name 缺失会硬中断，但现在已不需要）。
      return toEdit(
        toolName
          ? { name: toolName, args: response.modified_args ?? {} }
          : { args: response.modified_args ?? {} },
      )
    case 'rejected':
      return toReject(response.reason)
  }
}

function useDecisionStyles() {
  const t = useTranslations('chat.approval')
  return {
    approved: {
      tone: 'moldy-status-success',
      icon: CheckIcon,
      iconColor: 'moldy-status-icon',
      textColor: 'moldy-status-text',
      label: t('approved'),
    },
    modified: {
      tone: 'moldy-status-info',
      icon: PencilIcon,
      iconColor: 'moldy-status-icon',
      textColor: 'moldy-status-text',
      label: t('editApproved'),
    },
    rejected: {
      tone: 'moldy-status-danger',
      icon: XIcon,
      iconColor: 'moldy-status-icon',
      textColor: 'moldy-status-text',
      label: t('rejected'),
    },
  } as const
}

function ApprovalBadge({ result }: { result: unknown }) {
  const styles = useDecisionStyles()
  const parsed = parseApprovalResult(result)
  const decision = parsed?.decision ?? 'approved'
  const style = styles[decision] ?? styles.approved
  const Icon = style.icon

  return (
    <div
      className={cn(
        'moldy-status-surface moldy-status-card flex items-center gap-2 text-xs',
        style.tone,
      )}
    >
      <Icon className={cn('size-3.5 shrink-0', style.iconColor)} />
      <span className={cn('font-medium', style.textColor)}>{style.label}</span>
      {parsed?.reason && (
        <span className={cn('truncate opacity-70', style.textColor)}>— {parsed.reason}</span>
      )}
    </div>
  )
}

/**
 * Human-readable rendering of a single arg value. Scalars are shown as-is so the
 * approver reads "report.md" not "\"report.md\""; objects/arrays fall back to
 * compact JSON (the common approval args — command, file_path, url — are scalar).
 */
function formatArgValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null) return 'null'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function isScalarArg(value: unknown): boolean {
  return (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  )
}

// langchain's HumanInTheLoopMiddleware auto-builds the description as
// `${prefix}\n\nTool: ${name}\nArgs: ${args}`, which just repeats the card's
// header, tool-name line, and args list. Strip that boilerplate so the card
// isn't three copies of the same thing; keep only a meaningful custom prefix.
const DEFAULT_APPROVAL_DESCRIPTION_PREFIX = 'Tool execution requires approval'

function cleanApprovalDescription(raw: string | undefined): string | undefined {
  if (!raw) return undefined
  const prefix = raw.split(/\n\nTool:/)[0].trim()
  if (!prefix || prefix === DEFAULT_APPROVAL_DESCRIPTION_PREFIX) return undefined
  return prefix
}

// The headline should name the actual action being approved. `execute_in_skill`
// is a generic mechanism (and redundant with the "工具使用审批" header), so show
// the skill itself instead — derived from skill_directory ("/skills/docx-document"
// → "docx-document") or an explicit skill arg.
function resolveApprovalToolName(
  toolName: string | undefined,
  toolArgs: Record<string, unknown> | undefined,
): string | undefined {
  if (toolName === 'execute_in_skill' && toolArgs) {
    const dir = toolArgs.skill_directory
    if (typeof dir === 'string') {
      const skill = dir.split('/').filter(Boolean).pop()
      if (skill) return skill
    }
    const named = toolArgs.skill ?? toolArgs.skill_name
    if (typeof named === 'string' && named.trim()) return named.trim()
  }
  return toolName
}

function ArgsPreview({ args }: { args: Record<string, unknown> }) {
  const t = useTranslations('chat.approval')
  const [expanded, setExpanded] = useState(false)
  const entries = Object.entries(args)
  if (entries.length === 0) return null

  return (
    <div className="rounded-lg border border-border/40 bg-muted/30">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
      >
        <WrenchIcon className="size-3 text-muted-foreground" />
        <span className="font-medium">{t('args')}</span>
        <span className="text-muted-foreground">{t('argsCount', { count: entries.length })}</span>
        <ChevronDownIcon
          className={cn(
            'ml-auto size-3 text-muted-foreground transition-transform',
            expanded && 'rotate-180',
          )}
        />
      </button>
      {expanded && (
        // Readable key/value list instead of a raw JSON dump — each arg name is a
        // label and its value renders plainly (mono only for non-scalar JSON).
        <dl className="space-y-1.5 border-t border-border/40 px-3 py-2">
          {entries.map(([key, value]) => (
            <div key={key} className="moldy-approval-args-grid">
              <dt className="truncate font-mono font-medium text-muted-foreground" title={key}>
                {key}
              </dt>
              <dd
                className={cn(
                  'min-w-0 break-words whitespace-pre-wrap text-foreground/80',
                  !isScalarArg(value) && 'font-mono',
                )}
              >
                {formatArgValue(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

/**
 * Field-based editor for approval args. Each value is editable in its own
 * control instead of one raw JSON blob, so a syntax error in a single field
 * can't abort the whole submit. Secret keys (`isSensitiveDisplayKey`) are
 * locked read-only as `<redacted>` — the backend restores them from the
 * checkpoint by index, so the frontend never reconstructs or leaks them.
 */
function ArgsEditor({
  value,
  onChange,
  onInteract,
}: {
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
  onInteract: () => void
}) {
  const t = useTranslations('chat.approval')
  // Non-scalar (object/array/number/boolean/null) values are edited as compact
  // JSON text; a parse failure flags only that field and keeps the last good
  // value in the draft — it never blocks submit (§ field-editor contract).
  const [jsonText, setJsonText] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(value)
        .filter(([key, item]) => !isSensitiveDisplayKey(key) && typeof item !== 'string')
        .map(([key, item]) => [key, JSON.stringify(item)]),
    ),
  )
  const [fieldErrors, setFieldErrors] = useState<Record<string, boolean>>({})

  const entries = Object.entries(value)
  if (entries.length === 0) return null

  const updateString = (key: string, next: string) => {
    onInteract()
    onChange({ ...value, [key]: next })
  }

  const updateJson = (key: string, next: string) => {
    onInteract()
    setJsonText((prev) => ({ ...prev, [key]: next }))
    try {
      const parsed: unknown = JSON.parse(next)
      onChange({ ...value, [key]: parsed })
      setFieldErrors((prev) => ({ ...prev, [key]: false }))
    } catch {
      setFieldErrors((prev) => ({ ...prev, [key]: true }))
    }
  }

  return (
    <dl className="space-y-1.5 rounded-lg border border-border/40 bg-muted/30 px-3 py-2">
      {entries.map(([key, item]) => {
        const locked = isSensitiveDisplayKey(key)
        const isStringField = typeof item === 'string'
        return (
          <div key={key} className="space-y-1 text-xs">
            <dt className="truncate font-mono font-medium text-muted-foreground" title={key}>
              {key}
            </dt>
            <dd className="min-w-0">
              {locked ? (
                <input
                  type="text"
                  aria-label={key}
                  value={REDACTED_PLACEHOLDER}
                  readOnly
                  disabled
                  title={t('lockedSecretHint')}
                  className="moldy-field-status w-full cursor-not-allowed rounded-lg border bg-muted/50 px-2 py-1 font-mono text-xs text-muted-foreground outline-hidden"
                />
              ) : isStringField ? (
                <input
                  type="text"
                  aria-label={key}
                  value={String(value[key] ?? '')}
                  onChange={(e) => updateString(key, e.target.value)}
                  onFocus={onInteract}
                  className="moldy-field-status moldy-status-info w-full rounded-lg border bg-background px-2 py-1 text-xs outline-hidden"
                />
              ) : (
                <>
                  <input
                    type="text"
                    aria-label={key}
                    value={jsonText[key] ?? JSON.stringify(item)}
                    onChange={(e) => updateJson(key, e.target.value)}
                    onFocus={onInteract}
                    className="moldy-field-status moldy-status-info w-full rounded-lg border bg-background px-2 py-1 font-mono text-xs outline-hidden"
                  />
                  {fieldErrors[key] && (
                    <p className="mt-0.5 text-xs text-destructive">{t('invalidFieldValue')}</p>
                  )}
                </>
              )}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

export function ApprovalCard({
  args,
  result,
  status,
  addResult,
}: ToolCallMessagePartProps<ApprovalArgs, unknown>) {
  const t = useTranslations('chat.approval')
  const styles = useDecisionStyles()
  const hitl = useHiTL()
  const multi = useMultiApproval()
  const [decision, setDecision] = useState<Decision | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  // 编辑模式 draft —— field-based editor 按 key 分字段编辑。不用 raw JSON 文本
  // 而是逐字段保存值，因此不会因 JSON.parse 失败而阻塞整个 submit。
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [showEdit, setShowEdit] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)
  const [localResult, setLocalResult] = useState<ApprovalResult | null>(null)
  // 技能 Builder AD-4 —— "留出本次会议的剩余时间" 勾选状态。仅当有 review_configs flag
  // (session_consent_eligible) 时才 render/send。
  const [consentSession, setConsentSession] = useState(false)

  // 每个卡片实例的稳定 key —— 优先 args.approval_id，没有则 mount 时生成
  const fallbackId = useId()
  const approvalId = args?.approval_id ?? `approval-${fallbackId}`

  // 仅在 requires-action 状态启用 timer
  const isPending = status.type !== 'complete' && status.type !== 'running' && result === undefined
  // 在分组（多 action）内渲染时使用 compact 模式 —— 隐藏自身 header/countdown
  // （由分组容器代为显示），并注册批准回调供 "批准全部" 使用。
  const grouped = Boolean(multi) && typeof args?.hitl_action_index === 'number'
  const actionIndex = args?.hitl_action_index
  const groupedActive = !grouped || multi?.isActive(actionIndex ?? -1) === true
  const cardTestId = typeof actionIndex === 'number' ? `approval-action-${actionIndex}` : undefined
  const totalActions =
    typeof args?.hitl_total_actions === 'number' ? String(args.hitl_total_actions) : undefined

  const resumeDecision = useCallback(
    async (standardDecision: StandardDecision, displayText?: string) => {
      if (grouped && multi && typeof actionIndex === 'number') {
        await multi.submitDecision(
          actionIndex,
          standardDecision,
          displayText,
          args?.hitl_interrupt_id,
        )
        return
      }
      if (typeof args?.hitl_action_index === 'number' && hitl?.registerDecision) {
        await hitl.registerDecision(
          args.hitl_action_index,
          standardDecision,
          displayText,
          args.hitl_interrupt_id,
        )
        return
      }
      await hitl?.onResumeDecisions([standardDecision], displayText)
    },
    [actionIndex, args, grouped, hitl, multi],
  )

  const handleDecision = useCallback(
    async (d: Decision, opts?: { reasonOverride?: string }) => {
      setDecision(d)
      setSubmitting(true)

      const reason = opts?.reasonOverride ?? (d === 'rejected' ? rejectReason : undefined)
      const response: ApprovalResult = { decision: d }
      const resumeResponse: ApprovalResult = { decision: d }

      if (reason) {
        response.reason = reason
        resumeResponse.reason = reason
      }

      if (d === 'modified') {
        // 直接使用 field-based editor 的 draft。secret 字段被锁定，
        // 保持为 <redacted>，由 backend 从 checkpoint 原始值恢复（frontend
        // 不做恢复）。由于没有 JSON.parse，因此不会因 syntax error 被阻塞。
        response.modified_args = draft
        resumeResponse.modified_args = draft
      }

      const standardDecision = toDecision(d, resumeResponse, args?.tool_name, {
        sessionScope: args?.session_consent_eligible === true && consentSession,
      })
      try {
        await resumeDecision(standardDecision, styles[d].label)
      } catch {
        setResumeError(t('resumeFailed'))
        setSubmitting(false)
        setDecision(null)
        return false
      }
      addApprovalResultIfSupported(addResult, response)
      setLocalResult(response)
      setSubmitting(false)
      return true
    },
    [addResult, rejectReason, draft, t, styles, args, resumeDecision, consentSession],
  )

  const visibleResult = result ?? localResult

  // The group owns its heading. Count this action only after the runtime
  // accepted a decision (or supplied an already-complete tool result), never
  // when the user merely starts an approval, rejection, or edit flow.
  useEffect(() => {
    if (
      grouped &&
      multi &&
      typeof actionIndex === 'number' &&
      (status.type === 'complete' || visibleResult !== null)
    ) {
      multi.resolve(actionIndex)
    }
  }, [actionIndex, grouped, multi, status.type, visibleResult])

  // 过期时自动 reject —— 保存在 ref 中，避免受 handleDecision 变化影响
  const expireMessage = t('autoRejected')
  const handleExpire = useCallback(() => {
    if (submitting || decision !== null) return
    void handleDecision('rejected', { reasonOverride: expireMessage })
  }, [handleDecision, submitting, decision, expireMessage])

  const { remaining, isUrgent, formatted, extend } = useApprovalDeadline({
    approvalId,
    initialTimeoutSeconds: args?.timeout_seconds,
    onExpire: handleExpire,
    // In a group the countdown badge isn't rendered, so keeping the timer would
    // silently auto-reject a card mid-decision. Disable per-card auto-expire in
    // compact mode (the group has no visible deadline).
    active: isPending && !grouped,
  })

  const onInteract = useMemo(() => extend, [extend])

  // 按工具的 allowed_decisions gating —— 按卡片收到的 whitelist 显示按钮。
  // 为空/缺失时仅 approve+reject（排除 edit）—— 与 standard-interrupt 的 reviewForAction
  // fallback 相同。execute_in_skill(approve,reject) 不显示编辑按钮。
  const allowedDecisions = useMemo(
    () => new Set(args?.allowed_decisions ?? []),
    [args?.allowed_decisions],
  )
  const canApprove = allowedDecisions.size === 0 || allowedDecisions.has('approve')
  const canEdit = allowedDecisions.has('edit')
  const canReject = allowedDecisions.size === 0 || allowedDecisions.has('reject')

  // 为 "批准全部" 向分组容器注册未决卡片的批准回调。已决定，或
  // (localResult) 用户已经进入拒绝/编辑流程的卡片(decision/showEdit)则
  // 从注册中排除，避免 "批准全部" 覆盖正在进行的拒绝/编辑意图。
  useEffect(() => {
    const idx = args?.hitl_action_index
    if (
      !grouped ||
      !multi ||
      typeof idx !== 'number' ||
      !canApprove ||
      localResult !== null ||
      decision !== null ||
      showEdit
    ) {
      return
    }
    multi.register(idx, () => handleDecision('approved'))
    return () => multi.unregister(idx)
  }, [
    grouped,
    multi,
    canApprove,
    localResult,
    decision,
    showEdit,
    args?.hitl_action_index,
    handleDecision,
  ])

  // ── 完成状态 ──
  if (status.type === 'complete' || visibleResult !== null) {
    const badge = <ApprovalBadge result={visibleResult} />
    if (!grouped) return badge
    return (
      <div
        data-testid={cardTestId}
        data-hitl-total-actions={totalActions}
        data-hitl-active={groupedActive ? 'true' : 'false'}
        hidden={!groupedActive}
        className={cn('w-full', !groupedActive && 'hidden')}
      >
        {badge}
      </div>
    )
  }

  // ── 加载状态 ──
  if (status.type === 'running') {
    return (
      <div className="moldy-chat-card flex items-center gap-2 px-3 py-2 text-xs">
        <Loader2Icon className="size-3.5 animate-spin text-primary-strong" />
        <span className="text-muted-foreground">{t('preparing')}</span>
      </div>
    )
  }

  // ── requires-action: 审批卡 ──
  const toolName = resolveApprovalToolName(args?.tool_name, args?.tool_args) ?? t('toolCall')
  const rawDescription = cleanApprovalDescription(args?.description ?? args?.message)
  const description = rawDescription ? redactSensitiveText(rawDescription) : undefined
  const toolArgs = args?.tool_args ? redactSensitiveRecord(args.tool_args) : undefined

  const body = (
    <div className="space-y-3 p-4">
      {/* Tool name + description */}
      <div>
        <div className="mb-1 flex items-center gap-1.5">
          <WrenchIcon className="size-3 text-muted-foreground" />
          <span className="text-xs font-semibold">{toolName}</span>
        </div>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>

      {/* Args preview — collapsed by default; the headline now names the
              actual skill/tool, so expanding is only needed to inspect details. */}
      {toolArgs && Object.keys(toolArgs).length > 0 && <ArgsPreview args={toolArgs} />}

      {/* 거부 사유 입력 (거부 선택 시) */}
      {decision === 'rejected' && !submitting && (
        <textarea
          aria-label={t('rejectReasonLabel')}
          value={rejectReason}
          onChange={(e) => {
            setRejectReason(e.target.value)
            onInteract()
          }}
          onFocus={onInteract}
          placeholder={t('rejectReasonPlaceholder')}
          className="moldy-field-status moldy-status-danger w-full resize-none rounded-lg border bg-background px-3 py-2 text-xs outline-hidden placeholder:text-muted-foreground"
          rows={2}
        />
      )}

      {/* 수정 인자 입력 (수정 선택 시) — 칸별 field editor. 시크릿 키는
              read-only 잠금, 비-scalar는 칸별 JSON. raw JSON textarea 아님. */}
      {showEdit && !submitting && (
        <ArgsEditor value={draft} onChange={setDraft} onInteract={onInteract} />
      )}

      {resumeError && <p className="mt-1 text-xs text-destructive">{resumeError}</p>}

      {/* 세션 동의 옵션 (스킬 빌더 AD-4) — review_configs 플래그 조건부.
              체크 후 승인하면 decisions에 scope:'session'이 첨부되어 이 세션의
              같은 도구는 이후 승인 카드 없이 실행된다. */}
      {args?.session_consent_eligible === true && canApprove && !submitting && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            id={`${approvalId}-session-consent`}
            type="checkbox"
            aria-label={t('allowForSession')}
            checked={consentSession}
            onChange={(e) => {
              setConsentSession(e.target.checked)
              onInteract()
            }}
            data-testid="approval-session-consent"
            className="size-3.5 accent-primary"
          />
          <label htmlFor={`${approvalId}-session-consent`} className="cursor-pointer">
            {t('allowForSession')}
          </label>
        </div>
      )}

      {/* Action buttons */}
      {!submitting ? (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {/* 승인 */}
          {canApprove && (
            <button
              type="button"
              onClick={() => handleDecision('approved')}
              data-testid="approval-approve-button"
              data-variant="solid"
              className="moldy-action-pill moldy-status-success order-last"
            >
              <CheckIcon className="size-3" />
              {t('approve')}
            </button>
          )}

          {/* 수정 후 승인 — allowed_decisions에 edit이 있을 때만 노출 */}
          {canEdit &&
            (!showEdit ? (
              <button
                type="button"
                onClick={() => {
                  setShowEdit(true)
                  setDraft({ ...(toolArgs ?? {}) })
                }}
                data-variant="outline"
                className="moldy-action-pill moldy-status-info"
              >
                <PencilIcon className="size-3" />
                {t('edit')}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => handleDecision('modified')}
                data-variant="solid"
                className="moldy-action-pill moldy-status-info"
              >
                <PencilIcon className="size-3" />
                {t('editAndApprove')}
              </button>
            ))}

          {/* 거부 */}
          {canReject &&
            (decision !== 'rejected' ? (
              <button
                type="button"
                onClick={() => setDecision('rejected')}
                data-variant="outline"
                className="moldy-action-pill moldy-status-danger"
              >
                <XIcon className="size-3" />
                {t('reject')}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => handleDecision('rejected')}
                data-variant="solid"
                className="moldy-action-pill moldy-status-danger"
              >
                <XIcon className="size-3" />
                {t('rejectConfirm')}
              </button>
            ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2Icon className="size-3 animate-spin" />
          {t('processing')}
        </div>
      )}
    </div>
  )

  // 分组（多 action）内：compact block，不带 header/countdown。分组容器
  // 负责 "待审批 N 项" header、单一 countdown 和 "批准全部"。
  if (grouped) {
    return (
      <div
        data-testid={cardTestId}
        data-hitl-total-actions={totalActions}
        data-hitl-active={groupedActive ? 'true' : 'false'}
        hidden={!groupedActive}
        className={cn('moldy-chat-card w-full', !groupedActive && 'hidden')}
      >
        {body}
      </div>
    )
  }

  return (
    <div
      className="moldy-chat-card moldy-status-warn w-full border border-border bg-card text-foreground"
      data-testid={cardTestId}
      data-hitl-total-actions={totalActions}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
        <ShieldCheckIcon className="moldy-status-icon size-4" />
        <span className="text-sm font-medium">{t('approvalRequired')}</span>
        <CountdownBadge
          formatted={formatted}
          isUrgent={isUrgent}
          expired={remaining <= 0}
          label={t('expiresIn')}
          expiredLabel={t('expired')}
          className="ml-auto"
        />
      </div>
      {body}
    </div>
  )
}
