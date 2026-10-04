export interface EvalSetQualityReport {
  eval_set_id: string
  coverage_score: number
  validity_score: number
  diversity_score: number
  evaluability_score: number
  overall_score: number
  issues: string[]
  recommendation: string
  status: 'pending' | 'approved' | 'rejected'
}

type JsonObject = Record<string, unknown>

export interface AgentProject {
  id: string
  user_id: string
  agent_id: string
  builder_session_id: string | null
  title: string
  requirements_json:
    | (JsonObject & {
        bootstrap?: { stage: string; error: string | null; run_id: string | null }
        learning_brief?: LearningBrief
        brief_draft?: LearningBrief
      })
    | null
  eval_spec_json: EvaluationSpec | null
  report_json: (JsonObject & { optimization?: OptimizationState }) | null
  created_at: string
  updated_at: string
}

export interface AgentProjectVersionSummary {
  created_from?: {
    source_version_id: string
    optimization_proposal_id: string
    source_run_id: string
  } | null
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
  evaluation_type?: 'normal' | 'edge' | 'failure'
  difficulty?: 'easy' | 'medium' | 'hard'
  source?: 'ai_generated' | 'imported' | 'official_benchmark'
  expected_behavior?: Record<string, unknown> | null
  id: string
  name: string
  input: string
  context: { role: 'user' | 'assistant'; content: string }[]
  expected: {
    answer?: string | null
    exact_answer?: string | null
    required_tools: string[]
    forbidden_tools: string[]
    tool_assertions?: {
      name: string
      arguments?: Record<string, unknown> | null
      argument_equals?: Record<string, unknown> | null
      argument_contains?: Record<string, string> | null
      min_calls?: number
      max_calls?: number
    }[]
    tool_sequence?: string[]
    handoff?: string | null
    format_rule?: 'json_object' | 'json_array' | null
  }
  tags: string[]
  enabled: boolean
  mock_tool_data?: Record<
    string,
    {
      description?: string
      result?: unknown
      error?: string | null
      rules?: {
        arguments: Record<string, unknown>
        responses: { result?: unknown; error?: string | null }[]
      }[]
    }
  >
}

export interface EvaluationSet {
  rubric_json?: {
    version_id?: string
    purpose?: string
    development_set_id?: string
    source_version_id?: string
    business_contract?: { content_hash?: string }
  } | null
  id: string
  project_id: string
  name: string
  evaluation_focus_json?: EvaluationFocusOption[] | null
  evaluation_focus_reason?: string | null
  cases_json: (EvaluationCase & { project_id: string; created_at: string; updated_at: string })[]
  frozen: boolean
  quality_report_json?: EvalSetQualityReport | null
  created_at: string
}

export interface EvaluationResult {
  case_id: string
  name: string
  input: string
  output: string
  expected: EvaluationCase['expected']
  status: 'passed' | 'failed' | 'errored' | 'not_evaluated'
  tool_calls: { name: string }[]
  tool_trace?: {
    name: string
    order?: number
    arguments?: Record<string, unknown>
    output?: unknown
    error?: string | null
    latency_ms?: number
  }[]
  assertions: { kind: string; target?: string; passed: boolean }[]
  error: string | null
  metric_scores?: Record<
    string,
    { score: number | null; passed: boolean | null; reason: string; method: string }
  >
  limitations?: string[]
  latency_ms: number
}

export interface EvaluationMetrics {
  total: number
  passed?: number
  failed?: number
  errored?: number
  not_evaluated?: number
  pass_rate?: number | null
  quality_complete?: boolean
  metric_scores?: Record<string, { score: number; evaluated_cases: number }>
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
  bad_cases_json?: BadCase[] | null
  comparison_json?: {
    purpose?: string
    reliability?: {
      group_id: string
      kind: string
      repetitions: number
      index: number
      source_run_id: string
    }
    case_reviews?: Record<string, { passed: boolean; reason: string }>
    proposals?: OptimizationProposal[]
    regression?: { source_run_id: string; proposal_id: string }
    eval_spec?: EvaluationSpec
    analysis?: { groups: OptimizationGroup[] }
    deferred_changes?: { limitation: string; content: string }[]
    optimization?: OptimizationState
  } | null
}

export interface VersionComparison {
  comparable?: boolean
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

export interface EvaluationSpec {
  capability_profile?: Record<string, unknown>
  version_id: string
  metrics: { name: string; type: string; weight: number; criteria: string }[]
  categories: string[]
  focus_options?: EvaluationFocusOption[]
  case_count: number
  pass_threshold: number
}

export interface EvaluationFocusOption {
  id: string
  label: string
  description: string
}

export interface BadCase {
  case_id: string
  category: string
  root_cause: string
  evidence: string[]
  recommended_target: string
  suggested_fix: string
  observations: { reference: string; value: unknown }[]
}
export interface OptimizationGroup {
  category: string
  case_ids: string[]
  root_cause: string
  target: string
  proposed_change: string
}
export interface RegressionComparison {
  fixed_cases: string[]
  regressed_cases: string[]
  still_failing_cases: string[]
  still_passing_cases: string[]
  pass_rate: { before: number; after: number; delta: number }
  metrics: Record<string, { before: number | null; after: number | null; delta: number | null }>
  decision: 'accepted' | 'rejected'
  reasons: string[]
}
export interface OptimizationState {
  state?: 'pending' | 'running' | 'completed' | 'failed'
  root_run_id: string
  best_version_id?: string
  best_run_id?: string
  stop_reason?: string | null
  rounds?: {
    version_id: string
    parent_version_id: string
    run_id: string
    decision: string
    comparison?: RegressionComparison
  }[]
}
export interface PortfolioReport {
  evidence_hash: string
  markdown: string
  sections: { title: string; body: string }[]
  evidence: {
    project: { name: string; goal: string }
    results: {
      best_version: number | null
      baseline: PortfolioEvaluation | null
      best: PortfolioEvaluation | null
      metric_deltas: Record<string, number>
    }
    versions: {
      version: number
      best: boolean
      decision: string
      evaluation: PortfolioEvaluation | null
    }[]
    limitations: string[]
  }
}

export interface PortfolioEvaluation {
  pass_rate: number | null
  passed: number | null
  total: number | null
  metrics: Record<string, { score: number; evaluated_cases: number }>
}

export type ResumeStyle = 'ai_product' | 'product' | 'engineering'
export interface PortfolioResume {
  style: ResumeStyle
  bullets: string[]
  evidence_hash: string
}
export interface EvaluationReport {
  proposals?: OptimizationProposal[]
  source_run_id?: string | null
  version_id: string
  eval_set_id: string
  evaluation_run_id: string
  status: string
  score: number | null
  metrics: Record<string, number>
  total: number
  passed: number
  bad_case_count: number
  bad_cases: { case_id: string; name: string; reasons: string[] }[]
  optimization_suggestions: string[]
  comparison_key: string | null
  created_at: string
}

export interface EvaluationReports {
  reports: EvaluationReport[]
  best_run_ids: Record<string, string>
  active: boolean
}

export interface OptimizationProposal {
  decision_reason_source?: 'ai_confirmed' | 'user_authored'
  id: string
  proposal_request_id?: string
  source_version_id: string
  source_run_id: string
  eval_set_id: string
  status: 'pending' | 'accepted' | 'rejected'
  created_at: string
  decided_at: string | null
  decision_reason?: string | null
  version_id: string | null
  title?: string
  what_changes?: string
  why_it_may_work?: string
  benefits?: string[]
  risks?: string[]
  targeted_case_ids?: string[]
  superseded_by?: string
  affected_capabilities: string[]
  failure_patterns: OptimizationGroup[]
  diffs: { target: string; before: string; after: string; reason: string }[]
  deferred_changes: { target: string; content: string; limitation: string }[]
  can_accept: boolean
}

export interface BriefContent {
  audience: string
  problem: string
  workflow: string
  success_criteria: string[]
}
export interface LearningBrief {
  version_id: string
  draft_hash: string
  content_hash?: string
  content: BriefContent
  status: 'draft' | 'confirmed'
  contribution?: 'user_edited' | 'user_confirmed'
}
export interface InterviewMaterial {
  status: 'ai_draft'
  evidence_hash: string
  draft: {
    short_intro: string
    long_intro: string
    answers: { topic: string; answer: string; evidence_refs: string[] }[]
  }
  evidence: Record<string, unknown>
}
export interface TrialSummary {
  scheduled: number
  completed: number
  incomplete: number
  comparable: boolean
  mean: number | null
  min: number | null
  max: number | null
  stddev: number | null
  run_ids: string[]
}
export interface ReliabilitySummary {
  trials: { group_id: string; kind: string; versions: Record<string, TrialSummary> }[]
  calibration: {
    reviewed: number
    disagreements: number
    agreement_rate: number | null
    reviews: {
      run_id: string
      case_id: string
      judge_passed: boolean
      human_passed: boolean
      reason: string
      agreed: boolean
    }[]
  }
  limitations: string[]
}
