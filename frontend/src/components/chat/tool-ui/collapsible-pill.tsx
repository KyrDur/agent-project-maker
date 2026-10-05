'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  BrainIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  CircleSlashIcon,
  Loader2Icon,
  UsersIcon,
  WrenchIcon,
  XCircleIcon,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ──────────────────────────────────────────────
// CollapsiblePill — tool/subagent/thinking 的统一表现
//
// 4 种状态(loading/success/error/cancelled) × 3 类(tool/subagent/thinking)
// 由一个组件统一绘制。将原先 generic-tool-ui / sub-agent-ui / search-tool-ui /
// plan-tool-ui 等中重复的标题区 + status 图标 + 开关模式统一起来。
// ──────────────────────────────────────────────

export type PillStatus = 'loading' | 'success' | 'error' | 'cancelled'
export type PillKind = 'tool' | 'subagent' | 'thinking'

/**
 * 将 assistant-ui 的 ``status.type`` 映射为 PillStatus 的标准辅助函数。
 *
 * 合并分散在 5 个 tool-ui 文件中的映射函数（PR #103 review 中发现的
 * 不匹配）。HiTL reject 等 ``incomplete`` 在语义上应准确映射为 cancelled。
 */
export function pillStatusFromAssistantUi(
  statusType: 'running' | 'complete' | 'incomplete' | 'requires-action' | string | undefined,
): PillStatus {
  if (statusType === 'running' || statusType === 'requires-action') return 'loading'
  if (statusType === 'incomplete') return 'cancelled'
  if (statusType === 'complete') return 'success'
  if (statusType === undefined) return 'loading'
  return 'error'
}

interface CollapsiblePillProps {
  status: PillStatus
  kind?: PillKind
  /** 标题区左侧的粗体标签（工具名/子智能体名/思考阶段名）。 */
  title: string
  /** 标签右侧的辅助文本或计数（"运行中", "5项" 等）。 */
  meta?: ReactNode
  /**
   * 显示在 kind 图标位置的自定义图标。用于区分 file 工具类型
   * （如 FileIcon/FileEditIcon/FilePlusIcon），即使同为 ``kind="tool"``，
   * 也希望在视觉上进一步细分时使用。优先级高于 ``kind`` icon。
   */
  leadingIcon?: LucideIcon
  /** 展开后显示的正文。未指定时隐藏 chevron 本身。 */
  children?: ReactNode
  /** 展开前无需创建的重型正文。 */
  renderBody?: () => ReactNode
  defaultExpanded?: boolean
  /**
   * 在 Chevron 旁额外显示的图标按钮（例如：展开侧边面板）。
   * 需要与点击标题区域分别工作，因此调用方需处理 stopPropagation。
   */
  trailing?: ReactNode
  /** 将整个 pill 当作按钮使用时（如 sub-agent 卡片）。无 children 时推荐。 */
  onClick?: () => void
  className?: string
  /** 供窄布局中也必须保留识别标签的调用方使用的标题类名。 */
  titleClassName?: string
}

const STATUS_META: Record<
  PillStatus,
  {
    Icon: LucideIcon
    iconClass: string
    /** 容器边框/背景变体（error/cancelled 使用轻微色调）。 */
    containerClass: string
    /** 是否为需要旋转/旋转指示器动画的状态。 */
    spin?: boolean
  }
> = {
  loading: {
    Icon: Loader2Icon,
    iconClass: 'text-status-info',
    containerClass: '',
    spin: true,
  },
  success: {
    Icon: CircleCheckIcon,
    iconClass: 'text-status-success',
    containerClass: '',
  },
  error: {
    Icon: XCircleIcon,
    iconClass: 'text-status-danger',
    containerClass: 'border-status-danger/30 bg-status-danger/5',
  },
  cancelled: {
    Icon: CircleSlashIcon,
    iconClass: 'text-muted-foreground',
    containerClass: 'border-border/40 bg-muted/30',
  },
}

const KIND_ICON: Record<PillKind, LucideIcon> = {
  tool: WrenchIcon,
  subagent: UsersIcon,
  thinking: BrainIcon,
}

export function CollapsiblePill({
  status,
  kind,
  title,
  meta,
  leadingIcon,
  children,
  renderBody,
  defaultExpanded = false,
  trailing,
  onClick,
  className,
  titleClassName,
}: CollapsiblePillProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  // `useState` reads `defaultExpanded` only at mount. A subagent card mounts
  // while its discovery snapshot is still being seeded from history hydration
  // (page reload), so `defaultExpanded` starts false and flips true once the
  // snapshot lands. Without re-syncing, the card would stay collapsed on reload
  // even though it auto-expands live — and because the scoped body only mounts
  // (and lazily resolves its messages) when expanded, the subagent's result
  // would never render. Re-sync on the rising edge only, and never once the
  // user has toggled the pill themselves: otherwise a later `defaultExpanded`
  // flip (e.g. the subagent snapshot dropping then re-seeding across runs)
  // would re-open a card the user deliberately collapsed.
  const userToggledRef = useRef(false)
  const prevDefaultExpandedRef = useRef(defaultExpanded)
  useEffect(() => {
    if (defaultExpanded && !prevDefaultExpandedRef.current && !userToggledRef.current) {
      setExpanded(true)
    }
    prevDefaultExpandedRef.current = defaultExpanded
  }, [defaultExpanded])
  const toggleExpanded = () => {
    userToggledRef.current = true
    setExpanded((value) => !value)
  }
  const { Icon: StatusIcon, iconClass, containerClass, spin } = STATUS_META[status]
  // 若显式指定 leadingIcon 则使用它，否则回退到 kind 映射
  const HeaderIcon = leadingIcon ?? (kind ? KIND_ICON[kind] : null)
  const expandable =
    renderBody !== undefined || (children !== undefined && children !== null && children !== false)

  const headerInner = (
    <>
      <StatusIcon className={cn('size-3.5 shrink-0', iconClass, spin && 'animate-spin')} />
      {HeaderIcon ? (
        <HeaderIcon className="size-3 shrink-0 text-muted-foreground" aria-hidden />
      ) : null}
      <span className={cn('truncate font-medium', titleClassName)}>{title}</span>
      {meta ? <span className="min-w-0 truncate text-muted-foreground">{meta}</span> : null}
    </>
  )

  // 将整个 pill 作为按钮：无 children 且仅提供 onClick 的情况
  if (!expandable && onClick) {
    if (trailing) {
      return (
        <div
          className={cn(
            'moldy-tool-pill group flex w-full items-center gap-2 px-3 py-2 text-left text-xs',
            containerClass,
            className,
          )}
        >
          <button
            type="button"
            onClick={onClick}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
          >
            {headerInner}
          </button>
          {trailing}
        </div>
      )
    }

    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'moldy-tool-pill group flex w-full items-center gap-2 px-3 py-2 text-left text-xs',
          containerClass,
          className,
        )}
      >
        {headerInner}
        {trailing}
      </button>
    )
  }

  return (
    <div className={cn('moldy-tool-pill w-full text-xs', containerClass, className)}>
      <div className="flex w-full items-center gap-2 px-3 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          onClick={() => {
            if (expandable) toggleExpanded()
            else if (onClick) onClick()
          }}
          disabled={!expandable && !onClick}
        >
          {headerInner}
        </button>
        {trailing}
        {expandable ? (
          <button
            type="button"
            onClick={toggleExpanded}
            aria-label={expanded ? 'Collapse' : 'Expand'}
            aria-expanded={expanded}
            className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ChevronDownIcon
              className={cn('size-3.5 transition-transform duration-200', expanded && 'rotate-180')}
            />
          </button>
        ) : null}
      </div>
      {expandable && expanded ? (
        <div className="border-t px-3 py-2">{renderBody ? renderBody() : children}</div>
      ) : null}
    </div>
  )
}
