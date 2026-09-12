import { apiFetch } from '@/lib/api/client'
import type {
  AgentProject,
  AgentProjectVersion,
  AgentProjectVersionSummary,
  EvaluationCase,
  EvaluationSet,
  EvaluationRun,
  VersionComparison,
  VersionCreated,
} from './agent-project-types'

const projectPath = (agentId: string) => `/api/agents/${agentId}/project`

export const agentProjectApi = {
  get: (agentId: string) => apiFetch<AgentProject | null>(projectPath(agentId)),
  create: (agentId: string) =>
    apiFetch<AgentProject>(`${projectPath(agentId)}/create`, { method: 'POST' }),
  versions: (agentId: string) =>
    apiFetch<AgentProjectVersionSummary[]>(`${projectPath(agentId)}/versions`),
  version: (agentId: string, versionId: string) =>
    apiFetch<AgentProjectVersion>(`${projectPath(agentId)}/versions/${versionId}`),
  createVersion: (agentId: string, requestId: string) =>
    apiFetch<VersionCreated>(`${projectPath(agentId)}/versions`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),
  sets: (agentId: string) => apiFetch<EvaluationSet[]>(`${projectPath(agentId)}/eval-sets`),
  saveSet: (agentId: string, data: { id?: string; name: string; cases: EvaluationCase[] }) =>
    apiFetch<EvaluationSet>(`${projectPath(agentId)}/eval-sets${data.id ? `/${data.id}` : ''}`, {
      method: data.id ? 'PUT' : 'POST',
      body: JSON.stringify({
        name: data.name,
        cases: data.cases.map(({ id, name, input, context, expected, tags, enabled }) => ({
          id,
          name,
          input,
          context,
          expected,
          tags,
          enabled,
        })),
      }),
    }),
  runs: (agentId: string) => apiFetch<EvaluationRun[]>(`${projectPath(agentId)}/eval-runs`),
  run: (agentId: string, runId: string) =>
    apiFetch<EvaluationRun>(`${projectPath(agentId)}/eval-runs/${runId}`),
  createRun: (
    agentId: string,
    data: { request_id: string; version_id: string; eval_set_id: string },
  ) =>
    apiFetch<EvaluationRun>(`${projectPath(agentId)}/eval-runs`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  compare: (agentId: string, left: string, right: string) =>
    apiFetch<VersionComparison>(`${projectPath(agentId)}/compare?left=${left}&right=${right}`),
}
