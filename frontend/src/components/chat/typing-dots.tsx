'use client'

export interface TypingDotsProps {
  /** 显示在旁边的辅助标签。例：`正在整理意图…` */
  label?: string
}

/**
 * Builder 响应进行中指示器。
 *
 * 3 个点以 cb-bounce(translateY + opacity) 每隔 0.15 秒 stagger 动画。
 * 若旁边提供 label，则同时作为 typing 文本显示。
 */
export function TypingDots({ label }: TypingDotsProps) {
  return (
    <div className="moldy-typing-dots flex items-center gap-2 moldy-ui-compact">
      <span className="moldy-typing-dots-track">
        {[0, 1, 2].map((i) => (
          <span key={i} className="moldy-typing-dot" />
        ))}
      </span>
      {label && <span>{label}</span>}
    </div>
  )
}
