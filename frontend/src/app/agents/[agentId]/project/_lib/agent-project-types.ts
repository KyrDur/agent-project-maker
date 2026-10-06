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

export interface ProjectRequirements {
  goal: string
  inputs: string
  deliverables: string
  business_rules: string
  success_conditions: string
}
export interface ProjectDecision {
  stage: 'requirements' | 'capabilities' | 'case_review' | 'optimization'
  choice: string
  reason: string
  version_id: string
  eval_set_id?: string
  case_ids?: string[]
}
export interface ProjectCompletion {
  status: 'completed' | 'incomplete'
  reasons: string[]
  analysis: string | null
}
export interface ProjectInterview {
  evidence_hash: string
  questions: { question: string; references: string[]; answer_points: string[] }[]
}

export interface AgentProject {
  id: string
  user_id: string
  agent_id: string
  builder_session_id: string | null
  title: string
  requirements_json:
    | (JsonObject & {
        task?: ProjectRequirements
        bootstrap?: { stage: string; error: string | null; run_id: string | null }
      })
    | null
  eval_spec_json: EvaluationSpec | null
  report_json: (JsonObject & { optimization?: OptimizationState }) | null
  decisions_json?: ProjectDecision[] | null
  completion_json?: ProjectCompletion | null
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
  initial_state?: Record<string, unknown>
  judgment_basis?: string | null
  expected_behavior?: Record<string, unknown> | null
  metric_applicability?: Record<string, string[]> | null
  metric_applicability_reasons?: Record<string, string>
  id: string
  name: string
  input: string
  context: { role: 'user' | 'assistant'; content: string }[]
  expected: {
    max_characters?: number | null
    attempted_tools?: string[]
    state?: { path: string; value: unknown }[]
    tool_arguments?: { name: string; arguments: Record<string, unknown> }[]
    necessary_order?: string[]
    answer?: string | null
    exact_answer?: string | null
    required_tools: string[]
    forbidden_tools: string[]
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
      operation?: string
      collection?: string
      match_fields?: string[]
      update_fields?: string[]
      fail_on_calls?: number[]
      responses?: { arguments?: Record<string, unknown>; result?: unknown; error?: string }[]
    }
  >
}

export interface EvaluationSet {
  rubric_json?: { purpose?: 'regression' | 'validation'; validation_exposure?: string } | null
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
  trial?: number
  fact_check?: {
    items: {
      claim: string
      kind: string
      verdict: string
      evidence: { reference: string; quote: string }[]
    }[]
    supported: number
    unsupported: number
    unknown: number
    total: number
  }
  case_id: string
  name: string
  input: string
  output: string
  expected: EvaluationCase['expected']
  status: 'passed' | 'failed' | 'errored'
  model_calls?: Record<string, unknown>[]
  judge_calls?: Record<string, unknown>[]
  termination_reason?: string
  final_state?: Record<string, unknown>
  error_phase?: string
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
  metric_scores?: Record<string, MetricVerdict>
  metric_unavailable?: Record<string, string>
  limitations?: string[]
  latency_ms: number
}

export interface EvaluationMetrics {
  model_accounting?: {
    model_invocations: number
    usage_covered_invocations: number
    total_count: number | null
  }

  environment_errors?: number
  repetitions?: number
  trial_pass_rates?: number[]
  fact_support?: {
    supported: number
    unsupported: number
    unknown: number
    total: number
    covered_cases: number
  } | null
  operation_success?: { successful: number; total: number }
  recovery_success?: { successful: number; total: number }
  critical_violations?: { violating: number; total: number }
  total: number
  passed?: number
  failed?: number
  errored?: number
  pass_rate?: number
  execution_errors?: number
  judge_errors?: number
  executed_cases?: number
  executed_pass_rate?: number | null
  complete?: boolean
  metric_scores?: Record<string, MetricSummary>
  rubric_version?: number
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
    purpose?: 'regression' | 'validation'
    validation_exposure?: 'used' | 'unseen' | null
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
  rubric_version?: 1 | 2 | 3
  metrics: ScoringMetric[]
  categories: string[]
  focus_options?: EvaluationFocusOption[]
  case_count: number
  pass_threshold: number
  pass_threshold_reason?: string | null
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
  artifact_status?: Record<string, 'missing' | 'current' | 'stale'>
  markdown: string
  sections: { title: string; body: string }[]
  evidence: {
    project: { name: string; goal: string }
    results: {
      latest_version?: number | null
      current_version?: number | null
      current?: {
        pass_rate: number | null
        passed: number
        total: number
        complete: boolean
      } | null
      best_version: number | null
      best_run_id?: string | null
      baseline_version?: number | null
      comparisons?: {
        source_version: number
        target_version: number
        source_run_id: string
        target_run_id: string
        kind: 'adjacent' | 'cumulative'
        comparable: boolean
        changes: {
          outcome: 'improved' | 'unchanged' | 'regressed'
          pass_rate: { before: number; after: number; delta: number }
          metrics: Record<
            string,
            { before: number | null; after: number | null; delta: number | null }
          >
          regressed_cases: string[]
        } | null
      }[]
      baseline: PortfolioEvaluation | null
      best: PortfolioEvaluation | null
      candidate?: PortfolioEvaluation | null
      candidate_version?: number | null
      metric_deltas: Record<string, number>
    }
    versions: {
      version: number
      best: boolean
      decision: string
      evaluation: PortfolioEvaluation | null
    }[]
    limitations: string[]
    case_cards?: ProjectCaseCard[]
    material_readiness?: string
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
  statistics?: EvaluationMetrics
  eval_spec?: EvaluationSpec | null
  total: number
  passed: number
  bad_case_count: number
  bad_cases: { case_id: string; trial?: number; name: string; reasons: string[] }[]
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

export interface SimulationSession {
  id: string
  version_id: string
  scenario_id: string
  state_json: Record<string, unknown>
  messages_json: Record<string, unknown>[]
  turns_json: {
    request_id: string
    input: string
    output: string
    evidence: Record<string, unknown>
  }[]
  created_at: string
  updated_at: string
}

export interface RequirementReference {
  field: string
  quote: string
}
export interface ScoringMetric {
  verdict_role?: 'task' | 'quality'
  name: string
  type: string
  weight: number
  criteria: string
  display_name?: string | null
  description?: string | null
  requirement_refs?: RequirementReference[]
  scoring_mode?: 'legacy' | 'all_checks' | 'criterion_mean'
  scoring_criteria?: {
    id: string
    description: string
    requirement_refs: RequirementReference[]
    fail: string
    partial: string
    full: string
    critical: boolean
  }[]
}
export interface MetricSummary {
  score: number
  evaluated_cases?: number
  passed_cases?: number
  not_applicable_cases?: number
  unscored_cases?: number
}
export interface MetricVerdict {
  score: number
  passed: boolean
  reason: string
  method: string
  criteria_results?: {
    criterion_id: string
    level: number
    reason: string
    evidence: { reference: string; quote: string }[]
  }[]
  checks?: { kind: string; target?: string; passed: boolean }[]
}

export interface ProjectCaseCard {
  reference: string
  case_id: string
  title: string
  personal_task: string
  system_task: string
  history: {
    reference: string
    version: number
    trial: number
    user_request: string
    success_conditions: string | null
    actual_answer: string
    initial_state: unknown
    judgment_basis: string | null
    checks: unknown
    judgments: unknown
    model_calls: unknown
    final_state: unknown
    termination: string | null
    status: string
    timeline: {
      event: string
      tool: string
      arguments: unknown
      returned_facts: unknown
      error: string | null
    }[]
  }[]
  reviews: { finding: string; source: string }[]
  changes?: {
    title: string
    reason: string | null
    author: string
    source: string
    diffs: unknown
  }[]
  limitations: string[]
}
