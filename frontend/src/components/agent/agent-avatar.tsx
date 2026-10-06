'use client'

import { useState } from 'react'
import Image from 'next/image'
import { BotIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { API_BASE } from '@/lib/api/client'

const sizeMap = {
  xs: { container: 'size-7', icon: 'size-3.5', px: 28 },
  sm: { container: 'size-8', icon: 'size-4', px: 32 },
  md: { container: 'size-10', icon: 'size-5', px: 40 },
  lg: { container: 'size-14', icon: 'size-7', px: 56 },
  // 与 FixHero 相同大小（size-44 = 176px, sm:size-52 = 208px）。px 以最大值为准。
  xl: { container: 'size-44 sm:size-52', icon: 'size-16', px: 208 },
} as const

function appendPreviewVariant(src: string): string {
  if (src.includes('variant=')) return src
  return `${src}${src.includes('?') ? '&' : '?'}variant=preview`
}

interface AgentAvatarProps {
  imageUrl: string | null
  name: string
  size?: keyof typeof sizeMap
  className?: string
  /** 为 true 时直接使用 imageUrl（frontend public/* 资源）。默认 false：prepend backend API_BASE */
  publicAsset?: boolean
}

export function AgentAvatar({
  imageUrl,
  name,
  size = 'sm',
  className,
  publicAsset = false,
}: AgentAvatarProps) {
  const { container, icon, px } = sizeMap[size]
  const [hasError, setHasError] = useState(false)
  // imageUrl 变化时重置之前的 error 状态（React 官方 "rendering 中比较" pattern）。
  // useEffect + setState 违反 react-hooks/set-state-in-effect lint。
  const [prevImageUrl, setPrevImageUrl] = useState(imageUrl)
  if (prevImageUrl !== imageUrl) {
    setPrevImageUrl(imageUrl)
    setHasError(false)
  }

  if (imageUrl && !hasError) {
    const src = publicAsset ? imageUrl : appendPreviewVariant(`${API_BASE}${imageUrl}`)
    return (
      <Image
        src={src}
        alt={name}
        width={px}
        height={px}
        unoptimized={!publicAsset}
        onError={() => setHasError(true)}
        className={cn('shrink-0 rounded-full bg-primary object-cover', container, className)}
      />
    )
  }

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground',
        container,
        className,
      )}
    >
      <BotIcon className={icon} />
    </div>
  )
}
