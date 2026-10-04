'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/shared/error-state'
import { useProjectLearning } from '../_hooks/use-project-learning'
import type { AgentProject, BriefContent, LearningBrief } from '../_lib/agent-project-types'

function BriefEditor({ agentId, draft }: { agentId: string; draft: LearningBrief }) {
  const t = useTranslations('agentProject.guided')
  const { confirm } = useProjectLearning(agentId, draft.version_id)
  const [content, setContent] = useState<BriefContent>(draft.content)
  const [criteria, setCriteria] = useState(draft.content.success_criteria.join('\n'))
  const lines = criteria
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const valid =
    lines.length >= 2 &&
    lines.length <= 6 &&
    lines.every((s) => s.length <= 1000) &&
    content.audience.trim() &&
    content.problem.trim() &&
    content.workflow.trim()
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t('aiBrief')}</p>
      {(['audience', 'problem', 'workflow'] as const).map((key) => (
        <label key={key} className="block space-y-1">
          <span>{t(key)}</span>
          <Textarea
            value={content[key]}
            maxLength={key === 'audience' ? 500 : key === 'problem' ? 1000 : 1500}
            onChange={(e) => setContent({ ...content, [key]: e.target.value })}
          />
        </label>
      ))}
      <label className="block space-y-1">
        <span>{t('criteria')}</span>
        <Textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} />
      </label>
      <p className="text-sm text-muted-foreground">{t('criteriaHelp')}</p>
      <Button
        disabled={!valid || confirm.isPending}
        onClick={() =>
          confirm.mutate({
            draftHash: draft.draft_hash,
            content: { ...content, success_criteria: lines },
          })
        }
      >
        {t(confirm.isPending ? 'working' : 'confirmBrief')}
      </Button>
      {confirm.isSuccess && <p role="status">{t('saved')}</p>}
      {confirm.isError && <ErrorState />}
    </div>
  )
}
export function ProjectBrief({
  agentId,
  versionId,
  project,
}: {
  agentId: string
  versionId: string
  project: AgentProject
}) {
  const t = useTranslations('agentProject.guided')
  const { brief } = useProjectLearning(agentId, versionId)
  const [editing, setEditing] = useState(false)
  const saved = project.requirements_json?.learning_brief
  const draft = brief.data ?? project.requirements_json?.brief_draft
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">{t('briefTitle')}</h3>
      <p>{t('briefDescription')}</p>
      {saved && !editing ? (
        <>
          <dl className="space-y-3">
            {(['audience', 'problem', 'workflow'] as const).map((key) => (
              <div key={key}>
                <dt className="text-sm text-muted-foreground">{t(key)}</dt>
                <dd>{saved.content[key]}</dd>
              </div>
            ))}
            <div>
              <dt>{t('criteria')}</dt>
              <dd>
                <ul className="list-disc pl-5">
                  {saved.content.success_criteria.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </dd>
            </div>
          </dl>
          <p className="text-sm text-muted-foreground">
            {t(saved.contribution === 'user_edited' ? 'briefEdited' : 'briefConfirmed')}
          </p>
          <Button
            variant="outline"
            onClick={() => {
              setEditing(true)
              brief.mutate()
            }}
            disabled={brief.isPending}
          >
            {t('reviseBrief')}
          </Button>
        </>
      ) : (
        <>
          <Button disabled={brief.isPending} onClick={() => brief.mutate()}>
            {t(brief.isPending ? 'working' : 'generateBrief')}
          </Button>
          {draft?.version_id === versionId && (
            <BriefEditor key={draft.draft_hash} agentId={agentId} draft={draft} />
          )}
        </>
      )}
      {brief.isError && <ErrorState />}
    </div>
  )
}
