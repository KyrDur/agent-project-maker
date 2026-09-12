type JsonObject = Record<string, unknown>

export interface AgentProject {
  id: string
  user_id: string
  agent_id: string
  builder_session_id: string | null
  title: string
  requirements_json: JsonObject | null
  eval_spec_json: JsonObject | null
  report_json: JsonObject | null
  created_at: string
  updated_at: string
}

export interface AgentProjectVersionSummary {
  id: string
  project_id: string
  version_number: number
  parent_version_id: string | null
  status: 'original' | 'candidate' | 'accepted' | 'rejected'
  change_summary: string | null
  config_hash: string | null
  created_at: string
}

export interface AgentProjectVersion extends AgentProjectVersionSummary {
  snapshot_json: JsonObject
}

export interface VersionCreated {
  outcome: 'created' | 'unchanged' | 'replayed'
  version: AgentProjectVersion
}

export interface EvaluationCase {
  id: string
  name: string
  input: string
  context: { role: 'user' | 'assistant'; content: string }[]
  expected: {
    answer?: string | null
    exact_answer?: string | null
    required_tools: string[]
    forbidden_tools: string[]
    handoff?: string | null
  }
  tags: string[]
  enabled: boolean
}

export interface EvaluationSet {
  id: string
  project_id: string
  name: string
  cases_json: (EvaluationCase & { project_id: string; created_at: string; updated_at: string })[]
  frozen: boolean
  created_at: string
}

export interface EvaluationResult {
  case_id: string
  name: string
  input: string
  output: string
  expected: EvaluationCase['expected']
  status: 'passed' | 'failed' | 'errored'
  tool_calls: { name: string }[]
  assertions: { kind: string; target?: string; passed: boolean }[]
  error: string | null
  latency_ms: number
}

export interface EvaluationMetrics {
  total: number
  passed?: number
  failed?: number
  errored?: number
  pass_rate?: number
}

export interface EvaluationRun {
  id: string
  version_id: string
  eval_set_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  dataset_hash: string | null
  started_at: string | null
  created_at: string
  completed_at: string | null
  error: string | null
  metrics_json: EvaluationMetrics | null
  results_json: EvaluationResult[] | null
}

export interface VersionComparison {
  changes: {
    field: string
    before: unknown
    after: unknown
    added?: string[]
    removed?: string[]
    changed?: string[]
  }[]
  evaluations: ({ run_id: string; dataset_hash: string; metrics: EvaluationMetrics } | null)[]
  same_dataset: boolean
}
