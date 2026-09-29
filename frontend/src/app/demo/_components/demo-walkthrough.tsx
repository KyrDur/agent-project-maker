'use client'

import Image from 'next/image'
import { useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  ArrowRightIcon,
  BarChart3Icon,
  BotIcon,
  CheckCircle2Icon,
  ClipboardCheckIcon,
  KeyRoundIcon,
  PlayIcon,
  RotateCcwIcon,
  SparklesIcon,
} from 'lucide-react'

export function DemoWalkthrough() {
  const t = useTranslations('demo')
  const steps = [
    {
      title: t('configure'),
      eyebrow: t('credentials'),
      description: t('configureDescription'),
      icon: KeyRoundIcon,
      detail: t('providers'),
    },
    {
      title: t('build'),
      eyebrow: t('builder'),
      description: t('buildDescription'),
      icon: BotIcon,
      detail: t('buildDetail'),
    },
    {
      title: t('evaluate'),
      eyebrow: t('evaluation'),
      description: t('evaluateDescription'),
      icon: ClipboardCheckIcon,
      detail: t('evaluateDetail'),
    },
    {
      title: t('optimize'),
      eyebrow: t('optimization'),
      description: t('optimizeDescription'),
      icon: RotateCcwIcon,
      detail: t('optimizeDetail'),
    },
  ]

  const [activeStep, setActiveStep] = useState(0)
  const step = steps[activeStep]

  return (
    <main className="min-h-screen overflow-y-auto bg-background text-foreground">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 py-6 sm:px-8 lg:px-12">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground ">
              <SparklesIcon className="size-4" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-semibold ">{t('brand')}</p>
              <p className="text-xs text-muted-foreground">{t('subtitle')}</p>
            </div>
          </div>
          <a
            href="/login"
            className="rounded-full border border-border bg-white px-4 py-2 text-sm font-medium text-primary transition hover:border-primary hover:bg-accent"
          >
            {t('enter')}
          </a>
        </header>

        <section className="grid flex-1 items-center gap-10 py-12 lg:grid-cols-2 lg:py-16">
          <div>
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/30 bg-accent px-3 py-1.5 text-xs font-semibold text-primary">
              <span className="size-1.5 rounded-full bg-primary" />
              {t('tagline')}
            </p>
            <h1 className="max-w-xl text-4xl font-semibold leading-tight  text-foreground sm:text-5xl">
              {t('headline')}
              <span className="text-primary">{t('headlineAccent')}</span>
            </h1>
            <p className="mt-5 max-w-lg text-base leading-7 text-muted-foreground">
              {t('description')}
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => setActiveStep((activeStep + 1) % steps.length)}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground  transition hover:bg-primary/90"
              >
                {t('next')}
                <ArrowRightIcon className="size-4" aria-hidden />
              </button>
              <a
                href="/register"
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-white px-5 py-3 text-sm font-semibold text-primary transition hover:bg-accent"
              >
                {t('register')}
              </a>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-white p-3  sm:p-5">
            <Image
              src="/demo/agent-workflow.png"
              alt={t('imageAlt')}
              width={1536}
              height={1024}
              className="h-auto w-full rounded-lg"
              priority
            />
          </div>
        </section>

        <section className="border-t border-border py-8">
          <p className="mb-3 text-sm text-muted-foreground">{t('exampleNotice')}</p>
          <div className="mb-5 flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                {t('walkthrough')}
              </p>
              <h2 className="mt-1 text-xl font-semibold ">{t('stepsTitle')}</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              {t('currentStep', { current: activeStep + 1, total: steps.length })}
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-4">
            {steps.map((item, index) => {
              const Icon = item.icon
              const isActive = index === activeStep
              return (
                <button
                  type="button"
                  key={item.title}
                  onClick={() => setActiveStep(index)}
                  className={`rounded-lg border p-4 text-left transition ${
                    isActive
                      ? 'border-primary bg-accent '
                      : 'border-border bg-white hover:border-primary/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span
                      className={`flex size-9 items-center justify-center rounded-lg ${isActive ? 'bg-primary text-primary-foreground' : 'bg-muted text-primary'}`}
                    >
                      <Icon className="size-4" aria-hidden />
                    </span>
                    {isActive ? (
                      <CheckCircle2Icon className="size-4 text-primary" aria-hidden />
                    ) : null}
                  </div>
                  <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {item.eyebrow}
                  </p>
                  <h3 className="mt-1 font-semibold">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
                  <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-primary">
                    <BarChart3Icon className="size-3.5" aria-hidden />
                    {item.detail}
                  </p>
                </button>
              )
            })}
          </div>
          <div className="mt-5 flex items-center gap-3 rounded-lg border border-border bg-white px-4 py-3 text-sm text-muted-foreground">
            <PlayIcon className="size-4 fill-primary text-primary" aria-hidden />
            <span>
              <strong className="text-foreground">{step.title}</strong>：{step.description}
            </span>
          </div>
        </section>
      </div>
    </main>
  )
}
