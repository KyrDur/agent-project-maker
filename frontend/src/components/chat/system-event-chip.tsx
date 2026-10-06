'use client'

import { ArrowRightIcon, CheckIcon } from 'lucide-react'

export type SystemEventKind = 'completed' | 'started'

export interface SystemEventChipProps {
  /** 主标签。例如：`Phase 2 完成`、`Phase 3 开始` */
  label: string
  /** 辅助标签。例如：`用户意图分析` */
  sublabel?: string
  /** disk icon variant。默认 `completed`（勾选）/ `started`（向右箭头）。 */
  kind?: SystemEventKind
}

/**
 * 插入消息之间的 phase 切换 chip。
 *
 * Builder 的 phase 开始/完成通知不 baking 到消息中，而用独立 chip 显示。
 * 无头像、无名称的 centered pill (designer-directed)。
 */
export function SystemEventChip({ label, sublabel, kind = 'completed' }: SystemEventChipProps) {
  const Icon = kind === 'completed' ? CheckIcon : ArrowRightIcon
  return (
    <div role="status" className="moldy-system-event flex justify-center">
      <div className="moldy-system-event-chip">
        <span className="moldy-system-event-icon">
          <Icon className="size-2.5" strokeWidth={3.5} />
        </span>
        <span>{label}</span>
        {sublabel && <span className="moldy-system-event-subtle">· {sublabel}</span>}
      </div>
    </div>
  )
}
