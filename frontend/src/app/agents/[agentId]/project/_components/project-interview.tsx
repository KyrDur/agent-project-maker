'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectLearning } from '../_hooks/use-project-learning'

export function ProjectInterview({ agentId, versionId }: { agentId: string; versionId: string }) {
  const t = useTranslations('agentProject.guided')
  const { interview } = useProjectLearning(agentId, versionId)
  const [copyStatus, setCopyStatus] = useState<'copied' | 'copyFailed' | null>(null)
  const draft = interview.data?.draft
  async function copy() {
    if (!draft) return
    try {
      await navigator.clipboard.writeText(
        [
          draft.short_intro,
          draft.long_intro,
          ...draft.answers.map((a) => `${t(`questions.${a.topic}`)}\n${a.answer}`),
        ].join('\n\n'),
      )
      setCopyStatus('copied')
    } catch {
      setCopyStatus('copyFailed')
    }
  }
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">{t('interviewTitle')}</h3>
      <p>{t('interviewDescription')}</p>
      <Button disabled={interview.isPending} onClick={() => interview.mutate()}>
        {t(interview.isPending ? 'working' : 'generateInterview')}
      </Button>
      {interview.isError && <ErrorState />}
      {draft && (
        <>
          <p className="text-sm text-muted-foreground">{t('aiReference')}</p>
          <div>
            <h4 className="font-medium">{t('shortIntro')}</h4>
            <p className="whitespace-pre-wrap">{draft.short_intro}</p>
          </div>
          <details>
            <summary className="cursor-pointer">{t('longIntro')}</summary>
            <p className="mt-2 whitespace-pre-wrap">{draft.long_intro}</p>
          </details>
          {draft.answers.map((answer) => (
            <article key={answer.topic} className="space-y-2 border-t border-border pt-3">
              <h4 className="font-medium">{t(`questions.${answer.topic}`)}</h4>
              <p className="whitespace-pre-wrap">{answer.answer}</p>
              <details>
                <summary className="cursor-pointer">{t('supportingRecords')}</summary>
                {answer.evidence_refs.map((ref) => (
                  <pre
                    key={ref}
                    className="mt-2 overflow-auto whitespace-pre-wrap break-words text-xs"
                  >
                    {JSON.stringify(interview.data?.evidence[ref], null, 2)}
                  </pre>
                ))}
              </details>
              <label className="block space-y-1">
                <span className="text-sm text-muted-foreground">{t('practiceNote')}</span>
                <Textarea placeholder={t('practicePlaceholder')} />
              </label>
            </article>
          ))}
          <Button variant="outline" onClick={() => void copy()}>
            {t('copyMaterial')}
          </Button>
          {copyStatus && <p role="status">{t(copyStatus)}</p>}
        </>
      )}
    </div>
  )
}
