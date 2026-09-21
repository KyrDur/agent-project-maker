'use client'

import { useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/shared/error-state'
import { formatDisplayDateTime } from '@/lib/utils/display-format'
import { useProjectProposals } from '../_hooks/use-project-evaluation'
import type { AgentProjectVersionSummary, EvaluationRun } from '../_lib/agent-project-types'

export function ProjectProposals({
  agentId,
  run,
  versions,
  runs = [],
}: {
  agentId: string
  run: EvaluationRun
  versions: AgentProjectVersionSummary[]
  runs?: EvaluationRun[]
}) {
  const t = useTranslations('agentProject.lifecycle')
  const projectT = useTranslations('agentProject')
  const locale = useLocale()
  const { generate, decide, regression } = useProjectProposals(agentId, run.id)
  const generationId = useRef<string | null>(null)
  const regressionIds = useRef<Record<string, string>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const items = run.comparison_json?.proposals ?? []
  const busy = generate.isPending || decide.isPending || regression.isPending
  const version = (id: string) =>
    projectT('version', { number: versions.find((v) => v.id === id)?.version_number ?? 0 })
  const hasFailures = run.results_json?.some((r) => r.status === 'failed')
  return (
    <section className="space-y-4" aria-label={t('proposals')}>
      <h4 className="font-medium">{t('proposals')}</h4>
      <p className="text-sm text-muted-foreground">{t('reviewFirst')}</p>
      <Button
        disabled={
          busy ||
          !hasFailures ||
          items.some((p) => p.status === 'pending') ||
          (run.comparison_json?.analysis != null && !run.comparison_json.analysis.groups.length)
        }
        onClick={() => {
          generationId.current ??= crypto.randomUUID()
          generate.mutate(generationId.current, {
            onSuccess: () => {
              generationId.current = null
            },
          })
        }}
      >
        {t(generate.isPending ? 'generating' : 'generate')}
      </Button>
      {items.map((item) => {
        const latest = runs.find((r) => r.comparison_json?.regression?.proposal_id === item.id)
        const running = latest?.status === 'pending' || latest?.status === 'running'
        return (
          <article key={item.id} className="space-y-3 border-t border-border pt-4">
            <p className="font-medium">
              {item.title || t('defaultProposalTitle')} · {t(`statuses.${item.status}`)} ·{' '}
              {version(item.source_version_id)}
            </p>
            <p className="text-sm text-muted-foreground">
              {formatDisplayDateTime(item.created_at, { locale })}
            </p>
            {item.what_changes && <p>{t('whatChanges', { value: item.what_changes })}</p>}
            {item.why_it_may_work && (
              <p>{t('whyItMayWork', { value: item.why_it_may_work })}</p>
            )}
            {!!item.targeted_case_ids?.length && (
              <p>{t('targetedCases', { value: item.targeted_case_ids.join(', ') })}</p>
            )}
            {!!item.benefits?.length && (
              <div>
                <p className="font-medium">{t('benefits')}</p>
                <ul className="list-disc space-y-1 pl-5">
                  {item.benefits.map((benefit, index) => (
                    <li key={index}>{benefit}</li>
                  ))}
                </ul>
              </div>
            )}
            {!!item.risks?.length && (
              <div>
                <p className="font-medium">{t('risks')}</p>
                <ul className="list-disc space-y-1 pl-5">
                  {item.risks.map((risk, index) => (
                    <li key={index}>{risk}</li>
                  ))}
                </ul>
              </div>
            )}
            <p>{t('capabilities', { value: item.affected_capabilities.join(', ') })}</p>
            {item.failure_patterns.map((pattern, i) => (
              <div key={i} className="space-y-1">
                <p>
                  {projectT.has(`causeCategories.${pattern.category}`)
                    ? projectT(`causeCategories.${pattern.category}`)
                    : pattern.category}
                </p>
                <p>{t('rootCause', { value: pattern.root_cause })}</p>
                <p>{t('suggestion', { value: pattern.proposed_change })}</p>
              </div>
            ))}
            {item.diffs.map((diff, i) => (
              <details key={i}>
                <summary>{t('change', { target: diff.target })}</summary>
                <p>{diff.reason}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p>{projectT('beforeChange')}</p>
                    <pre className="whitespace-pre-wrap break-words text-sm">{diff.before}</pre>
                  </div>
                  <div>
                    <p>{projectT('afterChange')}</p>
                    <pre className="whitespace-pre-wrap break-words text-sm">{diff.after}</pre>
                  </div>
                </div>
              </details>
            ))}
            {item.deferred_changes.map((change, i) => (
              <p key={i}>{t('deferred', { value: change.content })}</p>
            ))}
            {item.status === 'pending' && (
              <div className="space-y-3">
                <label className="block space-y-1">
                  <span className="text-sm font-medium">{t('decisionReason')}</span>
                  <Textarea
                    value={reasons[item.id] ?? ''}
                    onChange={(event) =>
                      setReasons((current) => ({ ...current, [item.id]: event.target.value }))
                    }
                    placeholder={t('decisionReasonPlaceholder')}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                <Button
                  disabled={busy || !item.can_accept}
                  onClick={() =>
                    decide.mutate({
                      id: item.id,
                      decision: 'accepted',
                      reason: reasons[item.id]?.trim(),
                    })
                  }
                >
                  {t('accept')}
                </Button>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    decide.mutate({
                      id: item.id,
                      decision: 'rejected',
                      reason: reasons[item.id]?.trim(),
                    })
                  }
                >
                  {t('reject')}
                </Button>
                {!item.can_accept && <p>{t('cannotApply')}</p>}
                </div>
              </div>
            )}
            {item.decision_reason && (
              <p className="text-sm text-muted-foreground">
                {t('savedDecisionReason', { value: item.decision_reason })}
              </p>
            )}
            {item.status === 'accepted' && item.version_id && (
              <div className="space-y-2">
                <p>
                  {t('versionCreated', {
                    version: version(item.version_id),
                    source: version(item.source_version_id),
                  })}
                </p>
                <Button
                  disabled={busy || running}
                  onClick={() => {
                    regressionIds.current[item.id] ??= crypto.randomUUID()
                    regression.mutate(
                      { id: item.id, requestId: regressionIds.current[item.id] },
                      {
                        onSuccess: () => {
                          delete regressionIds.current[item.id]
                        },
                      },
                    )
                  }}
                >
                  {t(running ? 'regressionRunning' : latest ? 'rerunRegression' : 'runRegression')}
                </Button>
                {latest && (
                  <p>
                    {projectT(`runStatuses.${latest.status}`)} ·{' '}
                    <a className="underline" href="#evaluation-report">
                      {t('compareReport')}
                    </a>
                  </p>
                )}
              </div>
            )}
            {item.status === 'rejected' && <p>{t('rejectedHistory')}</p>}
          </article>
        )
      })}
      {(generate.isError || decide.isError || regression.isError) && (
        <ErrorState title={t('error')} />
      )}
    </section>
  )
}
