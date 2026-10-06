'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { FormFieldShell } from '@/components/shared/form-field-shell'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import { agentProjectApi } from '../_lib/agent-project-api'
import { agentProjectKeys } from '../_hooks/use-agent-project'
import type {
  AgentProject,
  AgentProjectVersionSummary,
  ProjectDecision,
  ProjectRequirements,
} from '../_lib/agent-project-types'
import { ProjectSelect } from './project-select'

const fields = ['goal', 'inputs', 'deliverables', 'business_rules', 'success_conditions'] as const

export function ProjectPractice({
  agentId,
  project,
  versions,
}: {
  agentId: string
  project: AgentProject
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject.practice')
  const cache = useQueryClient()
  const [task, setTask] = useState<ProjectRequirements>(
    project.requirements_json?.task ?? {
      goal: '',
      inputs: '',
      deliverables: '',
      business_rules: '',
      success_conditions: '',
    },
  )
  const [stage, setStage] = useState<ProjectDecision['stage']>('requirements')
  const [choice, setChoice] = useState('')
  const [reason, setReason] = useState('')
  const [versionId, setVersionId] = useState(
    versions.find((v) => v.version_number === 1)?.id ?? versions[0]?.id ?? '',
  )
  const [analysis, setAnalysis] = useState(project.completion_json?.analysis ?? '')
  const version = useQuery({
    queryKey: agentProjectKeys.version(agentId, versionId),
    queryFn: () => agentProjectApi.version(agentId, versionId),
    enabled: !!versionId,
  })
  const refresh = () =>
    void cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) })
  const save = useMutation({
    mutationFn: () => agentProjectApi.requirements(agentId, task),
    onSuccess: refresh,
  })
  const decision = useMutation({
    mutationFn: () =>
      agentProjectApi.decision(agentId, {
        stage,
        choice,
        reason,
        version_id: versionId,
      }),
    onSuccess: refresh,
  })
  const complete = useMutation({
    mutationFn: () => agentProjectApi.completion(agentId, analysis),
    onSuccess: refresh,
  })
  const interview = useMutation({ mutationFn: () => agentProjectApi.interview(agentId) })
  const snapshot = version.data?.snapshot_json.agent
  return (
    <SettingsSectionCard title={t('title')}>
      <p>{t('intro')}</p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        {fields.map((field) => (
          <FormFieldShell key={field} id={`task-${field}`} label={t(field)}>
            <Textarea
              id={`task-${field}`}
              required
              maxLength={4000}
              value={task[field]}
              onChange={(e) => setTask({ ...task, [field]: e.target.value })}
            />
          </FormFieldShell>
        ))}
        <Button type="submit" disabled={save.isPending}>
          {t('saveRequirements')}
        </Button>
        {save.isSuccess && <p role="status">{t('saved')}</p>}
      </form>
      <form
        className="mt-5 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          decision.mutate()
        }}
      >
        <ProjectSelect
          label={t('version')}
          value={versionId}
          options={versions.map((v) => ({ value: v.id, label: `V${v.version_number}` }))}
          onChange={setVersionId}
        />
        <details>
          <summary>{t('capabilityEvidence')}</summary>
          <pre className="whitespace-pre-wrap break-words text-sm">
            {JSON.stringify(snapshot, null, 2)}
          </pre>
        </details>
        <ProjectSelect
          label={t('stage')}
          value={stage}
          options={(['requirements', 'capabilities'] as const).map((value) => ({
            value,
            label: t(`stages.${value}`),
          }))}
          onChange={(value) => setStage(value as ProjectDecision['stage'])}
        />
        <FormFieldShell id="practice-choice" label={t('choice')}>
          <Textarea
            id="practice-choice"
            required
            maxLength={4000}
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
          />
        </FormFieldShell>
        <FormFieldShell id="practice-reason" label={t('reason')}>
          <Textarea
            id="practice-reason"
            required
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormFieldShell>
        <Button
          type="submit"
          disabled={
            decision.isPending ||
            !choice.trim() ||
            !reason.trim() ||
            !project.requirements_json?.task ||
            !versionId
          }
        >
          {t('saveDecision')}
        </Button>
        {decision.isSuccess && <p role="status">{t('saved')}</p>}
      </form>
      <ul className="mt-4 space-y-2">
        {project.decisions_json?.map((d, i) => (
          <li key={i}>
            {t(`stages.${d.stage}`)}: {d.choice} · {d.reason}
          </li>
        ))}
      </ul>
      <form
        className="mt-5 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          complete.mutate()
        }}
      >
        <FormFieldShell
          id="practice-analysis"
          label={t('analysis')}
          description={t('completionHelp')}
        >
          <Textarea
            id="practice-analysis"
            maxLength={10000}
            value={analysis}
            onChange={(e) => setAnalysis(e.target.value)}
          />
        </FormFieldShell>
        <Button type="submit" disabled={complete.isPending}>
          {t('complete')}
        </Button>
        {complete.data && (
          <div role="status">
            <p>{t(complete.data.status)}</p>
            <ul>
              {complete.data.reasons.map((code) => (
                <li key={code}>{t.has(`errors.${code}`) ? t(`errors.${code}`) : code}</li>
              ))}
            </ul>
          </div>
        )}
      </form>
      <Button
        className="mt-4"
        variant="outline"
        disabled={interview.isPending}
        onClick={() => interview.mutate()}
      >
        {t('interview')}
      </Button>
      {interview.data?.questions.map((q, i) => (
        <details key={i}>
          <summary>{q.question}</summary>
          <p>
            {t('references')}: {q.references.join(', ')}
          </p>
          <ul>
            {q.answer_points.map((point, n) => (
              <li key={n}>{point}</li>
            ))}
          </ul>
        </details>
      ))}
      {(save.isError || decision.isError || complete.isError || interview.isError) && (
        <ErrorState title={t('error')} />
      )}
    </SettingsSectionCard>
  )
}
