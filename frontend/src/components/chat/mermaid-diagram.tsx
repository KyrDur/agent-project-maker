'use client'

import { useEffect, useId, useState } from 'react'
import mermaid from 'mermaid'
import { useTheme } from 'next-themes'
import { useTranslations } from 'next-intl'

type MermaidTheme = 'default' | 'dark'

let currentTheme: MermaidTheme | null = null

function ensureInitialized(theme: MermaidTheme) {
  if (currentTheme === theme) return
  mermaid.initialize({
    startOnLoad: false,
    theme,
    securityLevel: 'strict',
    fontFamily: 'inherit',
  })
  currentTheme = theme
}

interface MermaidDiagramProps {
  code: string
}

export function MermaidDiagram({ code }: MermaidDiagramProps) {
  const t = useTranslations('chat.mermaid')
  const rawId = useId()
  const id = rawId.replace(/[^a-zA-Z0-9-]/g, '-')
  const { resolvedTheme } = useTheme()
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // resolvedTheme 在 hydration 前一刻为 undefined → fallback 到 'default'（与 SSR 一致）。
  // mounted 后变为 'dark' 时，通过 effect deps 变化自然重新 render。
  const mermaidTheme: MermaidTheme = resolvedTheme === 'dark' ? 'dark' : 'default'

  useEffect(() => {
    ensureInitialized(mermaidTheme)
    let cancelled = false
    // P1-C polish — explicit promise handle so cleanup can also rely on the
    // cancelled flag for any in-flight tail callbacks. mermaid.render returns
    // a Promise; we let it settle but ignore results once cancelled.
    const renderPromise = mermaid.render(`mermaid-${id}`, code)
    renderPromise
      .then(({ svg }) => {
        if (cancelled) return
        setSvg(svg)
        setError(null)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : t('renderFailed'))
      })
    return () => {
      cancelled = true
    }
  }, [id, code, mermaidTheme, t])

  if (error) {
    return (
      <pre className="overflow-auto rounded-md border border-border/60 bg-card p-3 text-xs">
        <code>{code}</code>
      </pre>
    )
  }

  if (!svg) {
    return (
      <pre className="overflow-auto rounded-md border border-border/60 bg-card p-3 text-xs">
        <code>{code}</code>
      </pre>
    )
  }

  return (
    <div
      className="overflow-auto rounded-md border border-border/60 bg-card p-3 [&_svg]:max-w-full [&_svg]:h-auto"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
