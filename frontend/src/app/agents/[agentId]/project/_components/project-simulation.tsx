'use client'

import ReactMarkdown from 'react-markdown'
import Link from 'next/link'
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { FormFieldShell } from '@/components/shared/form-field-shell'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { ErrorState } from '@/components/shared/error-state'
import {
  readSimulationSession,
  saveSimulationSession,
} from '@/lib/project-simulation/session-storage'
import { agentProjectApi } from '../_lib/agent-project-api'
import { agentProjectKeys } from '../_hooks/use-agent-project'
import type {
  AgentProject,
  AgentProjectVersionSummary,
  SimulationSession,
} from '../_lib/agent-project-types'
import { ProjectSelect } from './project-select'
import { ProjectExecutionLog, ProjectEvidenceValue } from './project-execution-log'

export function ProjectSimulation({
  agentId,
  versions,
  bootstrap,
  planReady = false,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
  bootstrap?: NonNullable<AgentProject['requirements_json']>['bootstrap']
  planReady?: boolean
}) {
  const t = useTranslations('agentProject.simulation')
  const projectT = useTranslations('agentProject')
  const [versionId, setVersion] = useState(
    () => readSimulationSession(`project-simulation-version:${agentId}`) || versions[0]?.id || '',
  )
  const [scenarioId, setScenario] = useState(
    () => readSimulationSession(`project-simulation-scenario:${agentId}`) || 'default',
  )
  const setVersionId = (id: string) => {
    saveSimulationSession(`project-simulation-version:${agentId}`, id)
    setVersion(id)
  }
  const setScenarioId = (id: string) => {
    saveSimulationSession(`project-simulation-scenario:${agentId}`, id)
    setScenario(id)
  }
  const sets = useQuery({
    queryKey: agentProjectKeys.sets(agentId),
    queryFn: () => agentProjectApi.sets(agentId),
  })
  const scenarios =
    sets.data
      ?.find((set) => set.frozen && set.rubric_json?.purpose !== 'validation')
      ?.cases_json.filter((c) => c.enabled) ?? []
  const scenario =
    scenarios.find((c) => c.id === scenarioId) ??
    scenarios.find((c) => c.tags?.includes('normal')) ??
    scenarios[0]
  const activeVersionId = versions.some((v) => v.id === versionId)
    ? versionId
    : versions[0]?.id || ''
  const activeScenarioId =
    scenarioId === 'default' || scenarios.some((c) => c.id === scenarioId) ? scenarioId : 'default'
  const retry = useMutation({
    mutationFn: () => agentProjectApi.bootstrap(agentId),
    onSuccess: () => sets.refetch(),
  })
  const preparing = Boolean(bootstrap?.stage && bootstrap.stage !== 'results' && !bootstrap.error)
  const preparationError = bootstrap?.error
  const planRecovered =
    planReady && bootstrap?.stage === 'plan' && preparationError === 'evaluation_rubric_unsupported'
  return (
    <SettingsSectionCard title={t('title')}>
      <p>{t('description')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <ProjectSelect
          label={t('version')}
          value={activeVersionId}
          onChange={setVersionId}
          options={versions.map((v) => ({ value: v.id, label: `V${v.version_number}` }))}
        />
        <ProjectSelect
          label={t('scenario')}
          value={activeScenarioId}
          onChange={setScenarioId}
          options={[
            { value: 'default', label: t('normal') },
            ...scenarios.map((c) => ({ value: c.id, label: c.name })),
          ]}
        />
      </div>
      {scenario && (
        <div className="space-y-2 text-sm">
          <p>{t('scenarioExample', { input: scenario.input })}</p>
          <p>
            {t('scenarioScope', {
              tools: Object.keys(scenario.mock_tool_data ?? {}).join('、') || t('noTools'),
            })}
          </p>
        </div>
      )}
      {!scenarios.length ? (
        <div className="space-y-2">
          {planRecovered ? (
            <div className="space-y-2">
              <p role="status">{t('planReady')}</p>
              <details>
                <summary>{t('previousFailure')}</summary>
                <p>{projectT('executionErrors.evaluation_rubric_unsupported')}</p>
              </details>
            </div>
          ) : preparationError ? (
            <div role="alert" className="space-y-2">
              <p>
                {t('prepareError', {
                  reason: projectT.has(`executionErrors.${preparationError}`)
                    ? projectT(`executionErrors.${preparationError}`)
                    : projectT('executionErrors.evaluation_execution_failed'),
                })}
              </p>
              <p>
                {t(
                  preparationError === 'evaluation_rubric_unsupported'
                    ? 'rubricHelp'
                    : 'prepareHelp',
                )}
              </p>
              <Link href="/models" className="underline">
                {projectT('bootstrap.models')}
              </Link>
            </div>
          ) : (
            <p role="status">
              {preparing
                ? t('preparing', {
                    stage: projectT.has(`bootstrap.stages.${bootstrap?.stage}`)
                      ? projectT(`bootstrap.stages.${bootstrap?.stage}`)
                      : projectT('bootstrap.title'),
                  })
                : t('notReady')}
            </p>
          )}
          <Button
            variant="outline"
            disabled={retry.isPending || preparing}
            onClick={() => retry.mutate()}
          >
            {t(planRecovered ? 'continuePreparation' : 'retry')}
          </Button>
          {(sets.isError || retry.isError) && <ErrorState />}
        </div>
      ) : (
        <SimulationConversation
          key={`${activeVersionId}:${activeScenarioId}`}
          agentId={agentId}
          versionId={activeVersionId}
          scenarioId={activeScenarioId === 'default' ? '' : activeScenarioId}
          scenarioInput={scenario?.input ?? ''}
        />
      )}
    </SettingsSectionCard>
  )
}

function SimulationConversation({
  agentId,
  versionId,
  scenarioId,
  scenarioInput,
}: {
  agentId: string
  versionId: string
  scenarioId: string
  scenarioInput: string
}) {
  const t = useTranslations('agentProject.simulation')
  const cache = useQueryClient()
  const storageKey = `project-simulation:${agentId}:${versionId}:${scenarioId}`
  const [sessionId, setSessionId] = useState(() => readSimulationSession(storageKey))
  const [content, setContent] = useState('')
  // 网络重试保留同一请求与正文，避免重复操作。
  const pending = useRef<{ request_id: string; content: string } | null>(null)
  const createId = useRef(crypto.randomUUID())
  const resetId = useRef<string | null>(null)
  const session = useQuery({
    queryKey: agentProjectKeys.simulation(agentId, sessionId),
    queryFn: () => agentProjectApi.simulation(agentId, sessionId),
    enabled: !!sessionId,
  })
  const remember = (data: SimulationSession) => {
    cache.setQueryData(agentProjectKeys.simulation(agentId, data.id), data)
    saveSimulationSession(storageKey, data.id)
    setSessionId(data.id)
  }
  const send = useMutation({
    mutationFn: async () => {
      pending.current ??= { request_id: crypto.randomUUID(), content: content.trim() }
      const id =
        sessionId ||
        (
          await agentProjectApi.createSimulation(agentId, {
            request_id: createId.current,
            version_id: versionId,
            ...(scenarioId ? { scenario_id: scenarioId } : {}),
          })
        ).id
      return agentProjectApi.sendSimulation(agentId, id, pending.current)
    },
    onSuccess: (data) => {
      remember(data)
      pending.current = null
      setContent('')
    },
  })
  const reset = useMutation({
    mutationFn: () => {
      resetId.current ??= crypto.randomUUID()
      return agentProjectApi.resetSimulation(agentId, sessionId, resetId.current)
    },
    onSuccess: (data) => {
      remember(data)
      resetId.current = null
      pending.current = null
      createId.current = crypto.randomUUID()
      setContent('')
      send.reset()
    },
  })
  const busy = send.isPending || reset.isPending
  return (
    <div className="mt-4 space-y-4">
      {session.data?.turns_json.map((turn) => (
        <article key={turn.request_id} className="space-y-2 border-b border-border pb-3">
          <p className="whitespace-pre-wrap">
            <strong>{t('you')}: </strong>
            {turn.input}
          </p>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <strong>{t('agent')}: </strong>
            <ReactMarkdown>{turn.output || t('noOutput')}</ReactMarkdown>
          </div>
          <details>
            <summary>{t('evidence')}</summary>
            <ProjectExecutionLog evidence={turn.evidence} />
          </details>
        </article>
      ))}
      {session.data && (
        <details>
          <summary>{t('state')}</summary>
          <ProjectEvidenceValue value={session.data.state_json} />
        </details>
      )}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          send.mutate()
        }}
      >
        <FormFieldShell id="simulation-input" label={t('message')}>
          <Textarea
            id="simulation-input"
            required
            maxLength={10000}
            value={content}
            disabled={busy || send.isError}
            onChange={(event) => setContent(event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            disabled={busy || send.isError || Boolean(content.trim())}
            onClick={() => setContent(scenarioInput)}
          >
            {t('useExample')}
          </Button>
        </FormFieldShell>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy || !content.trim() || !versionId || session.isError}>
            {t(send.isError ? 'retryMessage' : 'send')}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy || !sessionId}
            onClick={() => reset.mutate()}
          >
            {t('reset')}
          </Button>
        </div>
      </form>
      {(send.isError || reset.isError) && <ErrorState title={t('error')} />}
      {session.isError && (
        <ErrorState title={t('restoreError')} onRetry={() => void session.refetch()} />
      )}
      {busy && <p role="status">{t('running')}</p>}
    </div>
  )
}
