'use client'

import Image from 'next/image'
import { WrenchIcon } from 'lucide-react'

interface FixHeroProps {
  title: string
  subtitle: string
  suggestions: string[]
  onSuggestionClick?: (suggestion: string) => void
  /** 存在时以图片显示 hero。不存在时显示紫色虚线圆 + 扳手（Fix 编辑模式 default） */
  imageSrc?: string
}

export function FixHero({
  title,
  subtitle,
  suggestions,
  onSuggestionClick,
  imageSrc,
}: FixHeroProps) {
  return (
    <div className="flex flex-col items-center gap-4 px-4 py-8 text-center">
      {imageSrc ? (
        <Image
          src={imageSrc}
          alt=""
          width={208}
          height={208}
          className="size-44 sm:size-52"
          priority
        />
      ) : (
        <div className="moldy-status-accent moldy-status-surface flex size-32 items-center justify-center rounded-full border-2 border-dashed">
          <WrenchIcon className="moldy-status-icon size-14" strokeWidth={2} />
        </div>
      )}
      <div className="space-y-1.5">
        <h3 className="text-2xl font-bold text-foreground">{title}</h3>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <div className="mt-2 flex flex-col items-center gap-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={!onSuggestionClick}
            className="text-sm text-muted-foreground transition-colors enabled:cursor-pointer enabled:hover:text-foreground disabled:cursor-default"
            onClick={() => onSuggestionClick?.(suggestion)}
          >
            &quot;{suggestion}&quot;
          </button>
        ))}
      </div>
    </div>
  )
}
