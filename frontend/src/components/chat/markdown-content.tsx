'use client'

import { useMemo } from 'react'
import Markdown, { defaultUrlTransform } from 'react-markdown'
import rehypeKatex from 'rehype-katex'

import { CHAT_FINAL_REMARK_PLUGINS } from '@/components/chat/markdown-final-plugins'
import { buildMarkdownComponents } from '@/components/chat/markdown-components'
import { cn } from '@/lib/utils'

import 'katex/dist/katex.min.css'
import './markdown-styles.css'

// 模块级常量 —— 避免每次 render 都创建新数组。
const REHYPE_PLUGINS = [rehypeKatex]

/** Allow sandbox: and file: URLs that LLMs prepend, then delegate to default. */
function urlTransform(url: string): string {
  const cleaned = url.replace(/^(sandbox|file):/, '')
  return defaultUrlTransform(cleaned)
}

interface MarkdownContentProps {
  content: string
  className?: string
  isStreaming?: boolean
}

export function MarkdownContent({ content, className, isStreaming = false }: MarkdownContentProps) {
  const components = useMemo(() => buildMarkdownComponents({ isStreaming }), [isStreaming])
  return (
    <div className={cn('prose-chat', className)}>
      <Markdown
        components={components}
        urlTransform={urlTransform}
        remarkPlugins={CHAT_FINAL_REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
      >
        {content}
      </Markdown>
    </div>
  )
}
