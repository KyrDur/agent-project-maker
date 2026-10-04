import { apiFetch, API_BASE } from '@/lib/api/client'
import type {
  BriefContent,
  LearningBrief,
  InterviewMaterial,
  ReliabilitySummary,
  EvaluationReports,
  OptimizationProposal,
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
  EvaluationSet,
  EvaluationRun,
  VersionComparison,
  VersionCreated,
} from './agent-project-types'

const projectPath = (agentId: string) => `/api/agents/${agentId}/project`

export const agentProjectApi = {
  generateBrief: (agentId: string, versionId: string, locale: string) =>
    apiFetch<LearningBrief>(`${projectPath(agentId)}/learning/brief/generate`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId, locale }),
    }),
  confirmBrief: (agentId: string, versionId: string, draftHash: string, content: BriefContent) =>
    apiFetch<LearningBrief>(`${projectPath(agentId)}/learning/brief/confirm`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId, draft_hash: draftHash, content }),
    }),
  interview: (agentId: string, versionId: string, locale: string) =>
    apiFetch<InterviewMaterial>(`${projectPath(agentId)}/learning/interview`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId, locale }),
    }),
  reviewCase: (agentId: string, runId: string, caseId: string, passed: boolean, reason: string) =>
    apiFetch(`${projectPath(agentId)}/eval-runs/${runId}/cases/${caseId}/review`, {
      method: 'POST',
      body: JSON.stringify({ passed, reason }),
    }),
  holdout: (agentId: string, developmentSetId: string, requestId: string) =>
    apiFetch<EvaluationSet>(`${projectPath(agentId)}/reliability/holdout`, {
      method: 'POST',
      body: JSON.stringify({ development_set_id: developmentSetId, request_id: requestId }),
    }),
  repeat: (agentId: string, runId: string, requestId: string, repetitions: number) =>
    apiFetch<EvaluationRun[]>(`${projectPath(agentId)}/eval-runs/${runId}/repeat`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId, repetitions }),
    }),
  validate: (
    agentId: string,
    baselineRunId: string,
    candidateVersionId: string,
    holdoutSetId: string,
    requestId: string,
    repetitions: number,
  ) =>
    apiFetch<EvaluationRun[]>(`${projectPath(agentId)}/reliability/validate`, {
      method: 'POST',
      body: JSON.stringify({
        baseline_run_id: baselineRunId,
        candidate_version_id: candidateVersionId,
        holdout_set_id: holdoutSetId,
        request_id: requestId,
        repetitions,
      }),
    }),
  reliability: (agentId: string, versionId: string) =>
    apiFetch<ReliabilitySummary>(`${projectPath(agentId)}/reliability/${versionId}`),
  propose: (agentId: string, runId: string, requestId: string) =>
    apiFetch<OptimizationProposal>(`${projectPath(agentId)}/eval-runs/${runId}/proposals`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),
  decideProposal: (
    agentId: string,
    runId: string,
    proposalId: string,
    decision: 'accepted' | 'rejected',
    decisionReason?: string,
    reasonSource?: 'ai_confirmed' | 'user_authored',
  ) =>
    apiFetch<OptimizationProposal>(
      `${projectPath(agentId)}/eval-runs/${runId}/proposals/${proposalId}/decision`,
      {
        method: 'POST',
        body: JSON.stringify({
          decision,
          decision_reason: decisionReason ?? null,
          ...(reasonSource ? { reason_source: reasonSource } : {}),
        }),
      },
    ),
  proposalRegression: (agentId: string, runId: string, proposalId: string, requestId: string) =>
    apiFetch<EvaluationRun>(
      `${projectPath(agentId)}/eval-runs/${runId}/proposals/${proposalId}/regression`,
      {
        method: 'POST',
        body: JSON.stringify({ request_id: requestId }),
      },
    ),
  evaluationReports: (agentId: string) =>
    apiFetch<EvaluationReports>(`${projectPath(agentId)}/evaluation-reports`),
  bootstrap: (agentId: string) => apiFetch(`${projectPath(agentId)}/bootstrap`, { method: 'POST' }),
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
  generateSpec: (agentId: string, versionId: string) =>
    apiFetch<EvaluationSpec>(`${projectPath(agentId)}/eval-spec/generate`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    }),
  generateCases: (
    agentId: string,
    versionId: string,
    data: { evaluation_focus: string[]; evaluation_focus_reason?: string | null },
  ) =>
    apiFetch<EvaluationSet>(`${projectPath(agentId)}/eval-sets/generate`, {
      method: 'POST',
      body: JSON.stringify({
        version_id: versionId,
        evaluation_focus: data.evaluation_focus,
        evaluation_focus_reason: data.evaluation_focus_reason || null,
      }),
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
  judgeSet: (agentId: string, setId: string) =>
    apiFetch<EvaluationSet>(`${projectPath(agentId)}/eval-sets/${setId}/quality`, {
      method: 'POST',
    }),
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
  cancelRun: (agentId: string, runId: string) =>
    apiFetch(`${projectPath(agentId)}/eval-runs/${runId}/cancel`, { method: 'POST' }),
  retryRun: (agentId: string, runId: string, requestId: string) =>
    apiFetch(`${projectPath(agentId)}/eval-runs/${runId}/retry`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),
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
