'use client'

import { useMemo, type ReactNode } from 'react'
import Image from 'next/image'
import Markdown from 'react-markdown'
import { useTranslations } from 'next-intl'
import {
  AuiIf,
  MessagePrimitive,
  ComposerPrimitive,
  useAui,
  useAuiState,
  useMessagePartText,
  type EnrichedPartState,
} from '@assistant-ui/react'
import { LayoutGridIcon, PaperclipIcon, SendIcon } from 'lucide-react'
import { useAtomValue } from 'jotai'

import { buildMarkdownComponents } from './markdown-components'
import { CHAT_FINAL_REMARK_PLUGINS } from './markdown-final-plugins'
import { ToolFallbackPanel } from './tool-ui/generic-tool-ui'
import { ToolGroupContainer } from './tool-ui/tool-group-container'
import {
  groupAssistantParts,
  isGroupToolNode,
  groupToolName,
  type GroupedRenderInfo,
} from '@/lib/chat/group-assistant-parts'
import { parsePhaseNarration, type PhaseSegment } from './builder-phase-parser'
import { SystemEventChip } from './system-event-chip'
import { ImeSafeComposerInput } from './ime-safe-composer-input'
import {
  BuilderAssistantName,
  BuilderAssistantSubtitle,
  BuilderIconButton,
  BuilderMessageBubble,
  BuilderMessageText,
} from './tool-ui/builder-primitives'
import {
  MessageEditComposerInput,
  MessageEditComposerRoot,
  useMessageEditComposerControls,
} from './message-edit-composer'
import { chatCancelInFlightAtom } from '@/lib/stores/chat-store'
import { reportClientWarning } from '@/lib/logging/client-logger'

/**
 * Builder-variant 消息/composer override。
 *
 * 仅当 AssistantThread 为 `variant="builder"` 时使用。默认 variant 行为保持不变。
 * - User: bubble-only (no avatar), mint bubble with tail (designer-directed)
 * - Assistant: bare 38×38 mascot (no chip), "Moldy · 智能体构建器" name row
 * - Composer: mint focus ring, 文件/模板 IconBtn, 模型 meta, Send ↔ Stop toggle
 */

const MASCOT_SRC = '/project-maker.svg'

/** User 消息 —— 无头像 + mint bubble。 */
export function BuilderUserMessage({ metaRow }: { metaRow: React.ReactNode }) {
  return (
    <div className="group relative flex justify-end">
      <div className="flex w-full max-w-[72%] flex-col items-end">
        <BuilderMessageBubble>
          <MessagePrimitive.Content />
        </BuilderMessageBubble>
        {metaRow}
      </div>
    </div>
  )
}

export function BuilderUserEditComposer() {
  const t = useTranslations('chat.message')
  const { canCancel, canSend, cancel } = useMessageEditComposerControls()
  return (
    <div className="flex justify-end">
      <div className="flex w-full max-w-[72%] flex-col items-end">
        <MessageEditComposerRoot className="moldy-builder-edit-composer">
          <MessageEditComposerInput className="moldy-builder-edit-input" autoFocus />
          <div className="flex items-center justify-end gap-1">
            <button
              type="button"
              disabled={!canCancel}
              onClick={cancel}
              className="moldy-builder-button moldy-builder-button-ghost h-7 px-2 disabled:pointer-events-none disabled:opacity-50"
            >
              {t('editCancel')}
            </button>
            <button
              type="submit"
              disabled={!canSend}
              className="moldy-builder-button moldy-builder-button-primary h-7 px-2 disabled:pointer-events-none disabled:opacity-50"
            >
              {t('editSave')}
            </button>
          </div>
        </MessageEditComposerRoot>
      </div>
    </div>
  )
}

const MARKDOWN_COMPONENTS_STREAMING = buildMarkdownComponents({ isStreaming: true })
const MARKDOWN_COMPONENTS_FINAL = buildMarkdownComponents({ isStreaming: false })

/** Builder 专用 text part —— 将 phase narration 转换为 SystemEventChip。 */
function BuilderAssistantTextPart() {
  const tPhase = useTranslations('chat.phaseTimeline')
  const part = useMessagePartText()
  const isRunning = useAuiState(
    (s) => (s.message?.status as { type?: string } | undefined)?.type === 'running',
  )
  const text = part?.text ?? ''
  const segments = useMemo<PhaseSegment[]>(() => parsePhaseNarration(text), [text])
  const components = isRunning ? MARKDOWN_COMPONENTS_STREAMING : MARKDOWN_COMPONENTS_FINAL

  if (segments.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      {segments.map((seg, idx) => {
        if (seg.kind === 'event') {
          const name =
            tPhase(`names.${seg.phaseId}`) || tPhase('phaseNameFallback', { phaseId: seg.phaseId })
          const status =
            seg.transition === 'completed' ? tPhase('completedLabel') : tPhase('startedLabel')
          const label = tPhase('phaseLabel', { phaseId: seg.phaseId, status })
          return (
            <SystemEventChip
              key={`evt-${idx}`}
              kind={seg.transition}
              label={label}
              sublabel={name}
            />
          )
        }
        return (
          <BuilderMessageText key={`txt-${idx}`}>
            <Markdown components={components} remarkPlugins={CHAT_FINAL_REMARK_PLUGINS}>
              {seg.text}
            </Markdown>
          </BuilderMessageText>
        )
      })}
    </div>
  )
}

/** Builder 专用 ToolFallback wrapper —— 视觉展示与默认 ToolFallback 保持一致。
 *
 * 注册到 BUILDER_TOOLKIT 的 tool（phase_timeline / ask_user / recommendation_approval
 * 等）会被自身 ToolUI 拦截，因此不会到达这个 fallback。作为兜底，直接使用默认
 * ToolFallbackPanel，让未知工具也能显示在界面上。 */
function BuilderToolFallback(props: {
  toolName: string
  args: Record<string, unknown>
  result?: unknown
  status: { type: string }
}) {
  const resolved =
    props.status.type === 'running'
      ? ('running' as const)
      : props.status.type === 'complete'
        ? ('complete' as const)
        : ('error' as const)
  return (
    <ToolFallbackPanel
      toolName={props.toolName}
      args={props.args}
      result={props.result}
      status={resolved}
    />
  )
}

// ── Builder 界面 tool-call 分组（与主 v3 共用 GroupedParts）───────────
//
// groupBy/节点判定与主 v3 聊天共用 `group-assistant-parts.ts`。
// 只对 leaf 视觉按 Builder 专用逻辑分支：文本将 phase-narration 转为 SystemEventChip
// 通过 `BuilderAssistantTextPart` 实现，工具框则优先使用已注册的 per-tool UI(leaf.toolUI) →
// 没有则用 `BuilderToolFallback`。与主 v3 不同，不重排 order，保持自然顺序，
// 仅将分组视觉统一为 `ToolGroupContainer`（若为搜索类还会汇总来源）。

/** 以 Builder 风格绘制 GroupedParts 的节点/leaf。group-tool 节点 N≥2 时用容器，
 * N=1 时 passthrough。text leaf 保留 phase-narration，tool-call leaf 优先用已注册 UI。 */
export function renderBuilderGroupedPart({ part, children }: GroupedRenderInfo): ReactNode {
  if (isGroupToolNode(part)) {
    const running = part.status?.type === 'running'
    // N=1 不使用容器，直接传递组内内容（单个 tool-call leaf）。
    if (part.indices.length < 2) {
      return children
    }
    // running→展开/done→折叠通过 key remount 实现（CollapsiblePill 为 uncontrolled）。
    return (
      <ToolGroupContainer
        key={running ? 'running' : 'done'}
        toolName={groupToolName(part)}
        count={part.indices.length}
        running={running}
        indices={part.indices}
      >
        {children}
      </ToolGroupContainer>
    )
  }

  switch (part.type) {
    case 'text':
      return <BuilderAssistantTextPart />
    case 'tool-call': {
      // 已注册的 per-tool UI(BUILDER_TOOLKIT) 走 leaf.toolUI。未注册工具则由
      // BuilderToolFallback 作为兜底显示 —— 与现有 tools.Fallback 行为一致。
      const leaf = part as Extract<EnrichedPartState, { type: 'tool-call' }>
      return (
        leaf.toolUI ?? (
          <BuilderToolFallback
            toolName={leaf.toolName}
            args={leaf.args as Record<string, unknown>}
            result={leaf.result}
            status={leaf.status}
          />
        )
      )
    }
    case 'data':
      // Builder 未注册 dataUI，因此通常为 undefined（=不渲染）。与主 v3 相同，
      // 如果存在已注册 data renderer，就直接委托给它。
      return (part as Extract<EnrichedPartState, { type: 'data' }>).dataRendererUI
    case 'indicator':
      // indicator="never"，因此不会触发，但防御性返回 null。
      return null
    default:
      // image/file/source/reasoning 等：Builder 只渲染 Text/tool，因此默认 null。
      return null
  }
}

/** Builder Assistant 消息正文 —— parts 之间使用 12px gap stack。连续相同工具
 * 与主 v3 一样合并为 1 个分组容器（GroupedParts）。 */
export function BuilderAssistantMessageParts() {
  return (
    <div className="flex flex-col gap-3">
      <MessagePrimitive.GroupedParts groupBy={groupAssistantParts} indicator="never">
        {renderBuilderGroupedPart}
      </MessagePrimitive.GroupedParts>
    </div>
  )
}

/** Assistant 消息 —— 38×38 bare mascot + 名称行。 */
export function BuilderAssistantMessage({
  children,
  metaRow,
  agentSubtitle,
}: {
  /** 消息正文（MessageMetaRow：不包含(X) —— metaRow 单独处理）。 */
  children: React.ReactNode
  metaRow: React.ReactNode
  agentSubtitle?: string
}) {
  const t = useTranslations('agent.conversational')
  const resolvedAgentSubtitle = agentSubtitle ?? t('builderAgentSubtitle')
  return (
    <div className="group relative flex items-start gap-3">
      <Image
        src={MASCOT_SRC}
        alt={t('builderAgentName')}
        width={38}
        height={38}
        className="shrink-0"
      />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-1.5">
          <BuilderAssistantName>{t('builderAgentName')}</BuilderAssistantName>
          <BuilderAssistantSubtitle>{resolvedAgentSubtitle}</BuilderAssistantSubtitle>
        </div>
        {children}
        {metaRow}
      </div>
    </div>
  )
}

/** 左侧工具栏 IconBtn —— 文件附件 / 模板（视觉 stub，点击时仅显示 title）。 */
function IconBtn({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <BuilderIconButton aria-label={label} title={label}>
      {children}
    </BuilderIconButton>
  )
}

/** Stop 按钮 —— 取消进行中的响应（AbortController 路径）。 */
function BuilderStopButton() {
  const tMsg = useTranslations('chat.message')
  const aui = useAui()
  const isCanceling = useAtomValue(chatCancelInFlightAtom)
  const handleStop = () => {
    if (isCanceling) return
    try {
      aui.thread.cancelRun()
    } catch (err) {
      reportClientWarning('BuilderStopButton', 'cancelRun error:', err)
    }
  }
  return (
    <button
      type="button"
      onClick={handleStop}
      disabled={isCanceling}
      aria-label={tMsg('stop')}
      data-moldy-stop-button="true"
      className="moldy-builder-stop"
    >
      <span aria-hidden className="moldy-builder-stop-mark" />
      {tMsg('stop')}
    </button>
  )
}

/** Send 按钮 —— 32×32 mint square。 */
function BuilderSendButton() {
  const t = useTranslations('chat.input')
  return (
    <ComposerPrimitive.Send
      className="moldy-builder-send disabled:cursor-not-allowed"
      aria-label={t('sendButton')}
    >
      <SendIcon className="size-3.5" />
    </ComposerPrimitive.Send>
  )
}

/** Builder 专用 Composer。
 *
 * Spec:
 *  - Outer padding 12/28/18, gradient bg (transparent → #fafafa)
 *  - Card: white, 16 radius, mint focus-within 4px box-shadow ring
 *  - ImeSafeComposerInput submitMode="enter" —— 将 Chrome/IME 组合输入立即同步到 composer 状态
 *  - Toolbar: 文件/模板 IconBtn（仅视觉）+ 1×16 divider + 模型元数据 + Send/Stop 切换
 */
export function BuilderComposer({ modelLabel }: { modelLabel?: string }) {
  const t = useTranslations('chat.input')
  return (
    <div className="moldy-builder-composer-shell">
      <div className="moldy-builder-composer-inner mx-auto">
        <ComposerPrimitive.Root className="moldy-builder-composer-root group">
          <ImeSafeComposerInput
            autoFocus
            placeholder={t('placeholder')}
            submitMode="enter"
            className="moldy-builder-composer-input"
            rows={2}
          />
          <div className="moldy-builder-composer-toolbar flex items-center justify-between">
            <div className="flex items-center gap-1">
              <IconBtn label={t('attachComingSoon')}>
                <PaperclipIcon className="size-4" />
              </IconBtn>
              <IconBtn label={t('templateComingSoon')}>
                <LayoutGridIcon className="size-4" />
              </IconBtn>
              <span aria-hidden className="moldy-builder-composer-divider" />
              {modelLabel && <span className="moldy-builder-model-label">{modelLabel}</span>}
            </div>
            <AuiIf condition={(s) => !s.thread.isRunning}>
              <BuilderSendButton />
            </AuiIf>
            <AuiIf condition={(s) => s.thread.isRunning}>
              <BuilderStopButton />
            </AuiIf>
          </div>
        </ComposerPrimitive.Root>
      </div>
    </div>
  )
}
