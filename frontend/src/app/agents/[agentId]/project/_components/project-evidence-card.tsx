'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectLearning } from '../_hooks/use-project-learning'
import type { EvaluationRun, EvaluationResult } from '../_lib/agent-project-types'

export function ProjectEvidenceCard({
  agentId,
  run,
  result,
}: {
  agentId: string
  run: EvaluationRun
  result: EvaluationResult
}) {
  const t = useTranslations('agentProject.guided')
  const projectT = useTranslations('agentProject')
  const { review } = useProjectLearning(agentId, run.version_id)
  const saved = run.comparison_json?.case_reviews?.[result.case_id]
  const [reason, setReason] = useState(saved?.reason ?? '')
  const [passed, setPassed] = useState(saved?.passed ?? result.status === 'passed')
  const analysis = run.bad_cases_json?.find((r) => r.case_id === result.case_id)
  const failures = result.assertions.filter((a) => !a.passed)
  const metrics = Object.values(result.metric_scores ?? {}).filter(
    (m) => m.passed === false || m.score === null,
  )
  return (
    <article className="space-y-3 rounded-lg border border-border p-4">
      <h4 className="font-medium">
        {result.name} · {projectT(`caseStatuses.${result.status}`)}
      </h4>
      <div>
        <p className="text-sm text-muted-foreground">{t('requirement')}</p>
        <p className="whitespace-pre-wrap">{result.expected.answer ?? result.input}</p>
      </div>
      <div>
        <p className="text-sm text-muted-foreground">{t('actual')}</p>
        <p className="whitespace-pre-wrap break-words">{result.output || t('noOutput')}</p>
      </div>
      <div>
        <p className="text-sm text-muted-foreground">{t('evidence')}</p>
        {failures.map((a, i) => (
          <p key={i}>
            {a.kind}
            {a.target ? ` · ${a.target}` : ''}
          </p>
        ))}
        {metrics.map((m, i) => (
          <p key={i}>{m.reason}</p>
        ))}
        {!failures.length && !metrics.length && <p>{t('noFailureEvidence')}</p>}
        {result.error && <p>{t('executionFailed')}</p>}
      </div>
      {analysis && (
        <div>
          <p className="text-sm text-muted-foreground">{t('hypothesis')}</p>
          <p>{analysis.root_cause}</p>
          <p>{analysis.suggested_fix}</p>
        </div>
      )}
      {['passed', 'failed'].includes(result.status) && (
        <details>
          <summary className="cursor-pointer">{t('humanJudgment')}</summary>
          <div className="mt-3 space-y-3">
            <label className="flex gap-2">
              <input
                type="checkbox"
                aria-label={t('humanPassed')}
                checked={passed}
                onChange={(e) => setPassed(e.target.checked)}
              />
              <span>{t('humanPassed')}</span>
            </label>
            <label className="block space-y-1">
              <span>{t('judgmentReason')}</span>
              <Textarea
                value={reason}
                maxLength={1000}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <Button
              disabled={!reason.trim() || review.isPending}
              onClick={() =>
                review.mutate({
                  runId: run.id,
                  caseId: result.case_id,
                  passed,
                  reason: reason.trim(),
                })
              }
            >
              {t('saveJudgment')}
            </Button>
            {saved && <p>{saved.reason}</p>}
            {review.isSuccess && <p role="status">{t('saved')}</p>}
            {review.isError && <ErrorState />}
          </div>
        </details>
      )}
      <details>
        <summary className="cursor-pointer">{t('rawEvidence')}</summary>
        <pre className="overflow-auto whitespace-pre-wrap break-words text-xs">
          {JSON.stringify(
            {
              input: result.input,
              tool_trace: result.tool_trace,
              assertions: result.assertions,
              metric_scores: result.metric_scores,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </article>
  )
}
