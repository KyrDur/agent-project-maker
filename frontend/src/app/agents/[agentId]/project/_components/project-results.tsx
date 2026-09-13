'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { formatDisplayNumber } from '@/lib/utils/display-format'
import { Button, buttonVariants } from '@/components/ui/button'
import { useProjectPortfolio } from '../_hooks/use-project-portfolio'
import { agentProjectApi } from '../_lib/agent-project-api'
import type { ResumeStyle } from '../_lib/agent-project-types'

export function ProjectResults({ agentId }: { agentId: string }) {
  const t = useTranslations('agentProject.portfolio')
  const locale = useLocale()
  const { report, generate, resume, share } = useProjectPortfolio(agentId)
  const [style, setStyle] = useState<ResumeStyle>('ai_product')
  const [copyState, setCopyState] = useState<'copied' | 'copyFailed' | null>(null)
  const [showReport, setShowReport] = useState(false)
  const data = report.data?.evidence
  const results = data?.results
  const percent = (value: number | null | undefined) =>
    value == null
      ? t('unavailable')
      : t('percent', {
          value: formatDisplayNumber(value * 100, { locale, maximumFractionDigits: 1 }),
        })
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
    } catch {
      setCopyState('copyFailed')
    }
  }

  return (
    <SettingsSectionCard title={t('title')}>
      <div className="space-y-4">
        {report.isPending && <p role="status">{t('loading')}</p>}
        {report.isError && <ErrorState title={t('error')} onRetry={() => void report.refetch()} />}
        {data && results && (
          <>
            <p>{t('best', { version: results.best_version ?? t('unavailable') })}</p>
            <p>
              {t('evaluation', {
                passed: results.best?.passed ?? t('unavailable'),
                total: results.best?.total ?? t('unavailable'),
              })}{' '}
              · {percent(results.best?.pass_rate)}
            </p>
            <p>
              {t('improvement', {
                before: percent(results.baseline?.pass_rate),
                after: percent(results.best?.pass_rate),
              })}
            </p>
            <dl className="grid gap-2 sm:grid-cols-2">
              {Object.entries(results.best?.metrics ?? {}).map(([name, metric]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>
                    {t('metric', {
                      score: formatDisplayNumber(metric.score, {
                        locale,
                        maximumFractionDigits: 3,
                      }),
                      count: metric.evaluated_cases,
                    })}
                  </dd>
                </div>
              ))}
            </dl>
            <ol className="space-y-2" aria-label={t('journey')}>
              {data.versions.map((v) => (
                <li key={v.version}>
                  {t('version', { version: v.version })} · {percent(v.evaluation?.pass_rate)} ·{' '}
                  {v.decision}
                  {v.best && ` · ${t('bestLabel')}`}
                </li>
              ))}
            </ol>
            <p className="text-sm text-muted-foreground">{t('liveNotice')}</p>
            <div className="flex flex-wrap gap-2">
              <Link className={buttonVariants({ variant: 'outline' })} href={`/agents/${agentId}`}>
                {t('tryLive')}
              </Link>
              <Button variant="outline" onClick={() => setShowReport((v) => !v)}>
                {t('viewReport')}
              </Button>
              <Button
                variant="outline"
                disabled={generate.isPending}
                onClick={() => generate.mutate()}
              >
                {t('refresh')}
              </Button>
              <a
                className={buttonVariants({ variant: 'outline' })}
                href={agentProjectApi.exportUrl(agentId)}
              >
                {t('download')}
              </a>
            </div>
            {showReport && (
              <div className="space-y-4">
                {report.data?.sections.map((section) => (
                  <section key={section.title}>
                    <h3 className="font-medium">{section.title}</h3>
                    <pre className="whitespace-pre-wrap break-words text-sm">{section.body}</pre>
                  </section>
                ))}
              </div>
            )}
            <div className="space-y-2">
              <label className="block" htmlFor={`resume-${agentId}`}>
                {t('style')}
              </label>
              <select
                id={`resume-${agentId}`}
                className="rounded-md border bg-background p-2"
                value={style}
                onChange={(e) => setStyle(e.target.value as ResumeStyle)}
              >
                {(['ai_product', 'product', 'engineering'] as const).map((value) => (
                  <option key={value} value={value}>
                    {t(`styles.${value}`)}
                  </option>
                ))}
              </select>
              <Button
                variant="outline"
                disabled={resume.isPending}
                onClick={() => resume.mutate(style)}
              >
                {t('generateResume')}
              </Button>
              {resume.data && (
                <>
                  <p>{t(`styles.${resume.data.style}`)}</p>
                  <ul className="list-disc space-y-2 pl-5">
                    {resume.data.bullets.map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                  <Button
                    variant="outline"
                    onClick={() => void copy(resume.data.bullets.join('\n'))}
                  >
                    {t('copy')}
                  </Button>
                </>
              )}
            </div>
            <p className="text-sm text-muted-foreground">{t('shareNotice')}</p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={share.isPending}
                onClick={() => share.mutate(false)}
              >
                {t('share')}
              </Button>
              <Button
                variant="outline"
                disabled={share.isPending}
                onClick={() => share.mutate(true)}
              >
                {t('revoke')}
              </Button>
              {share.data?.path && (
                <>
                  <Link href={share.data.path} target="_blank" rel="noopener noreferrer">
                    {t('openShare')}
                  </Link>
                  <Button
                    variant="outline"
                    onClick={() =>
                      void copy(new URL(share.data.path ?? '', window.location.origin).href)
                    }
                  >
                    {t('copyLink')}
                  </Button>
                </>
              )}
            </div>
            {share.isSuccess && !share.data.path && <p role="status">{t('revoked')}</p>}
            {copyState && <p role="status">{t(copyState)}</p>}
            {(generate.isError || resume.isError || share.isError) && (
              <ErrorState title={t('error')} />
            )}
            <ul className="list-disc space-y-2 pl-5">
              {data.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </SettingsSectionCard>
  )
}
