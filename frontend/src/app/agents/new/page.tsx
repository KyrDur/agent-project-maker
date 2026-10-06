'use client'

import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import Image from 'next/image'
import { SendIcon, SparklesIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'

type ExamplePrompt = { emoji: string; label: string; text: string }

export default function AgentNewPage() {
  const t = useTranslations('agent.new')
  const router = useRouter()
  const [input, setInput] = useState('')
  const isComposingRef = useRef(false)

  function handleChatSubmit() {
    const text = input.trim()
    if (!text) return
    router.push(`/agents/new/conversational?initialMessage=${encodeURIComponent(text)}`)
  }

  const examples = t.raw('examples.items') as ExamplePrompt[]
  const hasInput = input.trim().length > 0

  return (
    <div className="moldy-agent-create-shell flex flex-1 flex-col items-center justify-center overflow-auto">
      <div className="flex w-full max-w-3xl flex-col gap-7 px-8 py-10">
        <Hero title={t('hero.title')} subtitle={t('hero.subtitle')} />

        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={handleChatSubmit}
          onCompositionStart={() => {
            isComposingRef.current = true
          }}
          onCompositionEnd={() => {
            isComposingRef.current = false
          }}
          isComposingRef={isComposingRef}
          placeholder={t('chatPlaceholder')}
          submitLabel={t('startButtonAria')}
          hasInput={hasInput}
        />

        <ExamplePrompts heading={t('examples.heading')} items={examples} onPick={setInput} />
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────── Hero

function Hero({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <div className="relative">
        <div aria-hidden className="moldy-agent-create-glow" />
        <Image
          src="/project-maker.svg"
          alt=""
          width={160}
          height={160}
          priority
          draggable={false}
          className="moldy-agent-create-mascot relative select-none"
        />
      </div>
      <div className="flex flex-col gap-2">
        <h1 className="moldy-page-title leading-snug">{title}</h1>
        <p className="mx-auto max-w-lg text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
      </div>
    </div>
  )
}

// ───────────────────────────────────────────────────────────── Chat input

type ChatInputProps = {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  onCompositionStart: () => void
  onCompositionEnd: () => void
  isComposingRef: React.MutableRefObject<boolean>
  placeholder: string
  submitLabel: string
  hasInput: boolean
}

function ChatInput({
  value,
  onChange,
  onSubmit,
  onCompositionStart,
  onCompositionEnd,
  isComposingRef,
  placeholder,
  submitLabel,
  hasInput,
}: ChatInputProps) {
  return (
    <div className="moldy-create-input group relative">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !isComposingRef.current) {
            e.preventDefault()
            onSubmit()
          }
        }}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={onCompositionEnd}
        aria-label={placeholder}
        placeholder={placeholder}
        rows={4}
        className="moldy-composer-input min-h-28 w-full resize-none bg-transparent px-5 pb-2 pt-4 text-sm leading-relaxed text-foreground outline-hidden placeholder:text-muted-foreground"
      />
      <div className="flex justify-end px-3 pb-3">
        <Button
          type="button"
          size="icon"
          onClick={onSubmit}
          disabled={!hasInput}
          aria-label={submitLabel}
          className={[
            'moldy-composer-submit size-9 transition-colors',
            hasInput
              ? 'bg-primary-strong text-white hover:bg-primary-strong/90'
              : 'bg-muted text-muted-foreground hover:bg-muted',
          ].join(' ')}
        >
          <SendIcon className="size-4" />
        </Button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────── Example prompts

function ExamplePrompts({
  heading,
  items,
  onPick,
}: {
  heading: string
  items: ExamplePrompt[]
  onPick: (text: string) => void
}) {
  return (
    <div>
      <div className="mb-2.5 flex items-center gap-1.5">
        <SparklesIcon className="size-3 moldy-color-primary-strong" />
        <span className="text-xs font-semibold text-muted-foreground">{heading}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onPick(p.text)}
            className={[
              'inline-flex items-center gap-1.5 rounded-full border px-3 transition-colors',
              'h-8 border-border bg-background text-xs text-foreground sm:text-sm',
              'hover:border-primary-strong/30 hover:bg-primary',
            ].join(' ')}
          >
            <span className="text-sm leading-none">{p.emoji}</span>
            <span className="leading-none">{p.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
