'use client'

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
import type { AgentProjectVersionSummary, SimulationSession } from '../_lib/agent-project-types'
import { ProjectSelect } from './project-select'

export function ProjectSimulation({
  agentId,
  versions,
}: {
  agentId: string
  versions: AgentProjectVersionSummary[]
}) {
  const t = useTranslations('agentProject.simulation')
  const [versionId, setVersionId] = useState(versions[0]?.id ?? '')
  const [scenarioId, setScenarioId] = useState('default')
  const sets = useQuery({
    queryKey: agentProjectKeys.sets(agentId),
    queryFn: () => agentProjectApi.sets(agentId),
  })
  const scenarios = sets.data?.find((set) => set.frozen)?.cases_json.filter((c) => c.enabled) ?? []
  const retry = useMutation({
    mutationFn: () => agentProjectApi.bootstrap(agentId),
    onSuccess: () => sets.refetch(),
  })
  return (
    <SettingsSectionCard title={t('title')}>
      <p>{t('description')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <ProjectSelect
          label={t('version')}
          value={versionId}
          onChange={setVersionId}
          options={versions.map((v) => ({ value: v.id, label: `V${v.version_number}` }))}
        />
        <ProjectSelect
          label={t('scenario')}
          value={scenarioId}
          onChange={setScenarioId}
          options={[
            { value: 'default', label: t('normal') },
            ...scenarios.map((c) => ({ value: c.id, label: c.name })),
          ]}
        />
      </div>
      {!scenarios.length ? (
        <div className="space-y-2">
          <p role="status">{t('notReady')}</p>
          <Button variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}>
            {t('retry')}
          </Button>
          {(sets.isError || retry.isError) && <ErrorState />}
        </div>
      ) : (
        <SimulationConversation
          key={`${versionId}:${scenarioId}`}
          agentId={agentId}
          versionId={versionId}
          scenarioId={scenarioId === 'default' ? '' : scenarioId}
        />
      )}
    </SettingsSectionCard>
  )
}

function SimulationConversation({
  agentId,
  versionId,
  scenarioId,
}: {
  agentId: string
  versionId: string
  scenarioId: string
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
          <p className="whitespace-pre-wrap">
            <strong>{t('agent')}: </strong>
            {turn.output || t('noOutput')}
          </p>
          <details>
            <summary>{t('evidence')}</summary>
            <pre className="whitespace-pre-wrap break-words text-sm">
              {JSON.stringify(turn.evidence, null, 2)}
            </pre>
          </details>
        </article>
      ))}
      {session.data && (
        <details>
          <summary>{t('state')}</summary>
          <pre className="whitespace-pre-wrap break-words text-sm">
            {JSON.stringify(session.data.state_json, null, 2)}
          </pre>
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
