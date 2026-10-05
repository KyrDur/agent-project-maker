'use client'

import { lazy, Suspense } from 'react'
import { languageForExtension } from './code-language'

// 复用与聊天 markdown 相同的 highlighter —— 按 heavy library 规则
// lazy 加载，加载中/不支持的语言/大文件则 fallback 到现有 plain <pre>。
const MarkdownCodeHighlighter = lazy(() => import('../markdown-code-highlighter'))

const HIGHLIGHT_MAX_LINES = 1500
const HIGHLIGHT_MAX_CHARS = 200_000

function PlainArtifactCode({ text }: { text: string }) {
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
      {text}
    </pre>
  )
}

export function ArtifactCodeBlock({
  text,
  extension,
}: {
  text: string
  extension: string | null | undefined
}) {
  const language = languageForExtension(extension)
  const tooLarge =
    text.length > HIGHLIGHT_MAX_CHARS || text.split('\n').length > HIGHLIGHT_MAX_LINES
  if (!language || tooLarge || !text) {
    return <PlainArtifactCode text={text} />
  }
  return (
    <Suspense fallback={<PlainArtifactCode text={text} />}>
      <MarkdownCodeHighlighter language={language} code={text} />
    </Suspense>
  )
}
