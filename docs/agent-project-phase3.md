# Agent Project Maker — Phase 3: Automatic Semantic Evaluation

Repository: the root of this natural-mold checkout.

Checkpoint: `1146221528b8deb79566a83d7800dd18f1ee1424` — **Agent Project Maker Phase 1-2 foundation**.
Current branch: `codex/agent-project-phase3`. Phase 3 changes are uncommitted.
Git global identity is Jieqi <181125631+KyrDur@users.noreply.github.com>; repository-local identity overrides were removed.

## Implemented flow

1. Select an immutable version in the existing Project workspace.
2. **Generate Eval Plan** calls the selected snapshot model with the existing user-owned credential resolver. The plan is validated and saved in `agent_projects.eval_spec_json`.
3. **Generate 20 Test Cases** validates exactly 20 unique, enabled cases, nonempty expected behavior, and all six categories. Every case has exactly one scenario tag; required tools must have mock data. Invalid generations fail without inserting a dataset.
4. Review/edit cases in the existing editor, including mock JSON, conversation context and an optional JSON output rule. The generated dataset remains unfrozen/editable and pins its plan in existing `rubric_json`.
5. The existing run POST freezes the enabled cases and the plan/model-role metadata. Case edits and plan regeneration do not change submitted runs.
6. The existing worker runs the snapshot through the canonical graph factory with synthetic tools and an in-memory StateBackend. It then grades semantic metrics through a separate judge call.
7. The workspace displays case status, pass rate, separate metric averages and coverage counts, actual output, expected behavior, tool names, assertions, judge reasons and historical Skill limitations. Failed/errored cases sort first.

No new table, migration or dependency was added. M79 remains the migration head. No live database migration was performed.

## Minimal integration and storage

- `agent_projects.eval_spec_json`: current generated plan, source version/config hash, categories, count and model-role metadata.
- `agent_project_eval_sets.cases_json`: existing case objects plus optional `mock_tool_data` and `expected.format_rule`.
- `agent_project_eval_sets.rubric_json`: the plan used to generate a dataset. Editing cases preserves it; regenerating a project plan does not replace an existing dataset's rubric.
- `agent_project_eval_runs.cases_snapshot_json`: existing frozen enabled-case copy, including mock data.
- `agent_project_eval_runs.comparison_json`: frozen `eval_spec`, `spec_hash`, examinee/judge descriptors and mock execution mode. This previously unused Phase 1 field avoids a migration; it is not an optimizer or version comparison job.
- `agent_project_eval_runs.results_json`: existing result evidence plus `execution_status`, `passed`, `actual_output`, `called_tools`, `deterministic_assertions`, `metric_scores`, `judge_reasons`, `error_code`.
- `agent_project_eval_runs.metrics_json`: pass/fail/error counts, pass rate, scoring version and independent metric means with scored-case counts.

Old hand-authored datasets without a project plan retain structural-only evaluation. Generated datasets use their pinned rubric, even after a different project plan is generated. There is no automatic conversion or modification of historical runs/versions.

## API

Both new endpoints extend the existing authenticated, CSRF-protected project router:

```text
POST /api/agents/{agent_id}/project/eval-spec/generate
POST /api/agents/{agent_id}/project/eval-sets/generate
Body: {"version_id": "<owned immutable version UUID>"}
```

The first returns the saved plan; the second returns the existing EvalSet response (201). Existing PUT `/eval-sets/{id}` edits generated cases. Existing POST `/eval-runs` and GET run/list endpoints are reused. Ownership checks occur before a model call.

## Metrics and verdicts

A plan contains 3–5 metrics total, at least three from the fixed pool and at most one custom business metric. Metric names are unique, weights are positive and sum to one, and every metric has criteria. The fixed pool is task_completion, tool_correctness, groundedness, format_compliance and business_quality.

- Tool correctness uses required/forbidden tool and handoff assertions. It never uses the judge. With no tool assertions it is vacuously satisfied; it is not proof of tool reliability or an integration test.
- JSON object/array rules and exact output rules are deterministic. Both checks apply if both are specified. A deterministic format metric without a rule fails explicitly.
- Task completion, groundedness, business quality and a custom metric use the judge. Format compliance without an explicit rule may use the judge when configured as `llm_judge`.
- A case passes only when execution succeeds, all structural assertions pass, and every selected metric passes. The default per-metric threshold is 0.7. Inconsistent/out-of-range/incomplete judge JSON is an error, never a pass.
- Weights are retained as plan metadata; this MVP does not calculate a weighted overall AI score or use weights to hide a failed metric.
- Pass rate is passed cases / all evaluated cases, including errored attempts in the denominator. Metric means only include recorded scores, with each metric's coverage count displayed. Errors do not invent zero or successful scores.
- A run with execution/judge errors has status `failed`; a run with valid failing assertions or low semantic grades has status `completed` and a lower pass rate.
- An examinee can have `execution_status=completed` while the case is errored due to invalid judge output; its output remains visible.

## Model and mock isolation

`agent_project_llm.resolve_model` reuses `get_for_user`, `resolve_llm_api_key_for_agent` and `create_chat_model` on transient snapshot Agent/Model objects. No source Agent or Model is persisted or updated. The examinee, planner and judge make distinct calls; the stored judge role is `evaluator`. MVP uses the snapshot's model/provider and user credential policy for all roles. Credential references are resolved at execution time, so rotation is supported; secret versions are not frozen.

The builder's full `invoke_with_json_retry` helper is unsuitable here because it selects operator/system models and logs provider exceptions. Only its `strip_code_fences` parser is reused by a bounded, project-local JSON caller. No separate credential storage or operator/environment fallback is introduced. LangSmith tracing is disabled, callbacks are empty, and raw provider exceptions are not retained. The existing value-based protocol redactor removes resolved keys before results are stored, followed by the existing snapshot scanner.

`agent_project_mock_tools` creates LangChain StructuredTool instances from frozen names/MCP input schemas and case mock behaviors. It never calls a production tool factory, MCP connection, Skill executable, or integration credential resolver. Arguments cannot override the closed-over frozen result. An authored `error` simulates an outage as a tool response. Missing required mocks fail before model execution; calling an exposed tool without mock data fails explicitly and retains redacted final/tool-name evidence. No fallback to production exists.

Tool argument values and raw production results are not retained. Only tool names and handoff names are recorded; mock sources are already part of the frozen case. These are functional mocks, not faithful replicas of vendor validation, OAuth or transport behavior. Ordinary tool snapshots lack full execution schemas/descriptions, so case descriptions and permissive synthetic input objects are used when a frozen MCP schema is not available.

## Skills and runtime limitations

Phase 1/2 immutable Skill links capture revision/configuration references, not filesystem content. They cannot safely reconstruct a historical package. The adapter never reads the current Skill row or storage path. If a snapshot contains frozen `content`, it includes that text inline and reuses `build_skills_prompt`; otherwise it records `historical_skill_content_unavailable`. It always records that historical package execution is unavailable when Skill links exist. Existing snapshots are not amended, and no automatic versions are created.

Configured subagents, custom middleware and model fallback lists remain unsupported and fail explicitly. Built-in graph facilities remain the existing canonical graph's in-memory behavior; this is not a full historical executable environment. Redacted executable configuration also fails explicitly rather than silently substituting live configuration.

Windows still cannot import the full canonical runtime because existing code imports Unix `fcntl`. No runtime rewrite or platform shim was added. Local tests use controlled graph/model substitutes and real synthetic tools, SQLAlchemy storage, API handlers, schemas and redaction. **Live Linux graph execution, live model-provider quality, PostgreSQL behavior and external integrations were not validated.** No live external integration is needed or intended for mock evaluations.

The existing FastAPI BackgroundTasks worker is not a durable queue. Examinee execution is bounded at 30 seconds/case; JSON model calls have a 90-second budget and up to two JSON parsing attempts; judging is additionally bounded at 95 seconds/case. The stale-run lease is extended from 15 to 45 minutes for 20 sequential cases. Reconciliation still occurs only on an authenticated run submission, not on GET. Generation is a synchronous bounded request and is not idempotent across repeated independent submissions.

Free-text secret scanning remains heuristic. Resolved model key values are explicitly removed, but arbitrary user-authored sensitive prose cannot be guaranteed to be recognized as a secret.

## Files

Added:

- `backend/app/services/agent_project_llm.py`
- `backend/app/services/agent_project_mock_tools.py`
- `backend/app/services/agent_project_semantic.py`
- `backend/tests/test_agent_project_phase3.py`
- `frontend/src/app/agents/[agentId]/project/_components/project-eval-plan.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase3.test.tsx`
- `docs/agent-project-phase3.md`

Modified:

- `backend/app/routers/agent_projects.py`
- `backend/app/schemas/agent_project.py`
- `backend/app/services/agent_project_evaluation.py`
- `backend/app/services/agent_project_executor.py`
- `backend/tests/test_agent_project_phase2.py` — replace obsolete blanket tool/Skill/MCP rejection coverage with Phase 3 isolation tests; update stale lease assertion.
- `frontend/messages/en.json`
- `frontend/messages/ko.json`
- `frontend/src/app/agents/[agentId]/project/_components/project-case-editor.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-project-evaluation.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`

Conversational builder, production runtime/tools/MCP, credential storage, chat, sharing, marketplace, ORM models, migrations, dependency manifests and lockfiles are unchanged from the checkpoint.

## Examples

These are controlled-test examples, not claims of live provider results. IDs below are illustrative. Generation returns 20 cases; only one is shown.

Eval Spec (stored metadata additionally includes source version, categories, count and role descriptors):

```json
{
  "metrics": [
    {"name":"task_completion","type":"llm_judge","weight":0.4,"criteria":"Complete the requested task."},
    {"name":"tool_correctness","type":"deterministic","weight":0.3,"criteria":"Call required tools; avoid forbidden tools."},
    {"name":"groundedness","type":"llm_judge","weight":0.3,"criteria":"Only report facts present in sources."}
  ],
  "pass_threshold": 0.7
}
```

Generated Eval Case:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "name": "Project summary",
  "input": "Summarize the project.",
  "context": [],
  "expected": {
    "answer": "Report login review only.",
    "exact_answer": null,
    "required_tools": ["search"],
    "forbidden_tools": ["delete"],
    "handoff": null,
    "format_rule": null
  },
  "tags": ["normal"],
  "enabled": true,
  "mock_tool_data": {"search": {"description":"Search project work","result":["Login reviewed"],"error":null}}
}
```

Persisted controlled run summary (two enabled cases, one unsupported revenue claim):

```json
{
  "status": "completed",
  "metrics_json": {
    "total": 2, "passed": 1, "failed": 1, "errored": 0,
    "pass_rate": 0.5,
    "scoring": "semantic_v1",
    "metric_scores": {
      "task_completion": {"score": 0.55, "evaluated_cases": 2},
      "tool_correctness": {"score": 1.0, "evaluated_cases": 2},
      "groundedness": {"score": 0.55, "evaluated_cases": 2}
    }
  }
}
```

Failed-case evidence excerpt:

```json
{
  "execution_status": "completed",
  "passed": false,
  "actual_output": "Revenue doubled",
  "called_tools": [{"name":"search"}],
  "metric_scores": {
    "groundedness": {"score":0.2,"passed":false,"reason":"Revenue is absent from sources.","method":"llm_judge"}
  },
  "judge_reasons": {"groundedness":"Revenue is absent from sources."},
  "error_code": null
}
```

## Verification

- Backend affected suites: **46 passed** (`test_agent_projects.py`, `test_agent_project_phase2.py`, `test_agent_project_phase3.py`; isolated `--noconftest` fixtures, SQLite).
- Frontend affected suites: **18 passed** (`project-workbench.test.tsx`, `project-phase2.test.tsx`, `project-phase3.test.tsx`).
- Ruff check/format on affected Python: passed.
- Pyright on affected backend source: 0 errors, 0 warnings.
- TypeScript `--noEmit --incremental false`: passed.
- Affected ESLint and direct JSX accessibility lint: passed.
- Static i18n guard: passed.
- Design-system guard: passed with the existing 20 card-structure baseline warnings; baseline unchanged.
- No broad repository test/refactor effort or dependency installation was performed. Installed Node remains 24 while the repository pins 22; this is not a production build or browser E2E validation.

The new backend tests cover valid/invalid metric plans, exactly 20 cases, all six categories, ownership before generation, editable datasets, frozen run cases/rubrics, mock invocation, argument override resistance, simulated tool failure, missing mock failure/evidence, required/forbidden tools, deterministic format rules, structured/invalid judge results, unsupported-fact grading with a controlled judge, persisted per-case scores and aggregates, persisted resolved-key redaction, and unchanged source Agent/version state. Frontend tests cover generation, mock editing, scores/evidence and error states while retaining the Phase 1/2 creation/versioning tests.

No optimizer, bad-case classification/fix, prompt rewrite, automatic version generation, Project Report, resume generator or public project page was implemented.
