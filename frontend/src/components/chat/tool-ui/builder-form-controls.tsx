'use client'

import { useRef, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { BuilderButton, BuilderFeedbackWrap, BuilderTextarea } from './builder-primitives'

interface BuilderFeedbackTextareaProps {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
  placeholder?: string
  rows?: number
}

/**
 * Builder approval/edit 卡共用 textarea。
 *
 * - mint focus ring（`primaryDim` border + 3px box-shadow）
 * - 韩文 IME composition guard（composition 中阻止 Enter 传播）
 * - disabled 时不做灰色处理，仅禁用 —— 视觉上通常在 frozen 状态时 unmount
 */
export function BuilderFeedbackTextarea({
  value,
  onChange,
  disabled = false,
  placeholder,
  rows = 2,
}: BuilderFeedbackTextareaProps) {
  const t = useTranslations('chat.builderApproval')
  const resolvedPlaceholder = placeholder ?? t('shortPlaceholder')
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
        onKeyDown={(e) => {
          if (e.key === 'Enter' && composingRef.current) e.stopPropagation()
        }}
        placeholder={resolvedPlaceholder}
        rows={rows}
        disabled={disabled}
      />
    </BuilderFeedbackWrap>
  )
}

interface ActionButtonProps {
  onClick: () => void
  disabled?: boolean
  label: string
  icon?: ReactNode
}

/** 薄荷绿 primary 按钮 — 用于批准/生成/确认等主要操作。 */
export function MintActionButton({ onClick, disabled, label, icon }: ActionButtonProps) {
  return (
    <BuilderButton tone="primary" onClick={onClick} disabled={disabled} className="px-4">
      {icon}
      {label}
    </BuilderButton>
  )
}

/** 白色 outline 按钮 — 用于修改请求/跳过/重新生成等辅助操作。 */
export function OutlineActionButton({ onClick, disabled, label, icon }: ActionButtonProps) {
  return (
    <BuilderButton tone="secondary" onClick={onClick} disabled={disabled}>
      {icon}
      {label}
    </BuilderButton>
  )
}
