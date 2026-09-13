import { apiFetch, API_BASE } from '@/lib/api/client'
import type {
  PortfolioReport,
  PortfolioResume,
  ResumeStyle,
  AgentProject,
  AgentProjectVersion,
  AgentProjectVersionSummary,
  EvaluationCase,
  EvaluationSpec,
  BadCase,
  OptimizationGroup,
  OptimizationState,
  EvaluationSet,
  EvaluationRun,
  VersionComparison,
  VersionCreated,
} from './agent-project-types'

const projectPath = (agentId: string) => `/api/agents/${agentId}/project`

export const agentProjectApi = {
  report: (agentId: string, generate = false) =>
    apiFetch<PortfolioReport>(`${projectPath(agentId)}/report${generate ? '/generate' : ''}`, {
      method: generate ? 'POST' : 'GET',
    }),
  resume: (agentId: string, style: ResumeStyle) =>
    apiFetch<PortfolioResume>(`${projectPath(agentId)}/resume/generate`, {
      method: 'POST',
      body: JSON.stringify({ style }),
    }),
  share: (agentId: string, revoke = false) =>
    apiFetch<{ path: string | null }>(`${projectPath(agentId)}/share`, {
      method: revoke ? 'DELETE' : 'POST',
    }),
  exportUrl: (agentId: string) => `${API_BASE}${projectPath(agentId)}/export`,
  analyze: (agentId: string, runId: string) =>
    apiFetch<{ bad_cases: BadCase[]; groups: OptimizationGroup[] }>(
      `${projectPath(agentId)}/eval-runs/${runId}/analyze`,
      { method: 'POST' },
    ),
  optimize: (agentId: string, runId: string, requestId: string) =>
    apiFetch<OptimizationState>(`${projectPath(agentId)}/eval-runs/${runId}/optimize`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),
  generateSpec: (agentId: string, versionId: string) =>
    apiFetch<EvaluationSpec>(`${projectPath(agentId)}/eval-spec/generate`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    }),
  generateCases: (agentId: string, versionId: string) =>
    apiFetch<EvaluationSet>(`${projectPath(agentId)}/eval-sets/generate`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    }),
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
        cases: data.cases.map(
          ({ id, name, input, context, expected, tags, enabled, mock_tool_data }) => ({
            id,
            name,
            input,
            context,
            expected,
            tags,
            enabled,
            mock_tool_data,
          }),
        ),
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
