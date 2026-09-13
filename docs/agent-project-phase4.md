# Agent Project Maker — Phase 4

Repository: the root of this natural-mold checkout.

Phase 3 checkpoint: `91c4999e1ad77088c4b1603c45e24d1418fa0b96`

Commit message: **Agent Project Maker Phase 3 semantic evaluation**

Current branch: `codex/agent-project-phase4`. Phase 4 changes are uncommitted.

## Delivered behavior

The existing Project workspace now supports:

1. Analyze failed/errored cases from a terminal semantic evaluation.
2. Inspect individual observable evidence and grouped root causes.
3. Generate bounded textual patches for shared causes.
4. Create an immutable candidate from the evaluated parent snapshot.
5. Evaluate the candidate through the existing Phase 3 worker using the baseline run's exact frozen experiment.
6. Compare every case and every selected metric, then record accepted/rejected.
7. Run at most one additional optimization round if the candidate improves.
8. Retain the best measured project version, even if the latest candidate is worse.

The live Agent is never updated. No deployment/promote endpoint was added. Project Best Version and Live Agent may differ, and the UI says so.

## Minimal integration choices and deviations

- No new table, migration, dependency, evaluation engine, credential resolver or production runtime behavior.
- The existing version row is entirely immutable, including its physical status column. That guarantee remains intact. Acceptance decisions are stored in run/project JSON; existing version GET/list responses overlay the measured status for display. Physical rows stay `candidate`, while project history shows `accepted` or `rejected` from the stored decision. Original versions remain `original`.
- `append_snapshot_version` reuses the existing project write lock, request identity and increasing version number. Both ordinary manual snapshot creation and optimization share this insert path. Candidate snapshots are never built from the live Agent.
- `insert_frozen_run` is the shared existing run insertion boundary. Regression copies the baseline run's `cases_snapshot_json`, `eval_set_id`, mock data and plan fields directly. It never reads the current EvalSet to construct the candidate test.
- The full existing prompt generator deliberately rewrites prompts and uses builder/system model roles. It is not called. Phase 4 instead reuses Phase 3's bounded user-owned JSON caller and model/redaction helpers.
- Output optimization uses textual `output_instructions` mapped to the snapshot system prompt. No new executable output-schema mechanism is invented.
- One bounded optimization chain is supported per project in this MVP. Retried requests, requests on its candidates and new request UUIDs do not reset its two-round limit. Starting a different benchmark chain in the same project returns a conflict; there is no reset/restart UI.

## JSON storage

| Existing field | Phase 4 contents |
| --- | --- |
| Run `bad_cases_json` | Individual analyses, categories, suggested fixes and resolved observable references |
| Run `comparison_json.analysis` | Root-cause groups and analysis format version |
| Version `snapshot_json.optimization` | Immutable parent/root run lineage, round, grouped plan, applied before/after patches and deferred changes |
| Candidate run `comparison_json.optimization` | Root/parent provenance, case partitions, metric deltas, decision, policy and reasons |
| Root run `comparison_json.optimization` | Bounded chain state, rounds, best measured version/run and stop reason |
| Project `report_json.optimization` | Same lightweight chain/selection metadata for project history and polling |

Using the `optimization` namespace of the existing `report_json` field does not implement a Project Report. Other keys are preserved. No report generation, export, resume or public page is included.

Version snapshots retain the original `agent` configuration plus immutable optimization metadata. Patches can only change allowlisted textual Agent fields; metadata is not a patch target. The config hash covers the stored candidate snapshot. Historical snapshots, frozen cases and rubric are not rewritten.

## Analysis and patch contracts

Supported categories:

- `instruction_issue`
- `skill_issue`
- `tool_selection_issue`
- `tool_description_issue`
- `output_issue`
- `external_unfixable`

Only failing/errored cases are provided to the analyzer, alongside the immutable snapshot, frozen Eval Spec, expected behavior, output, called tool names, deterministic assertions, metric scores/reasons and mock sources. The analyzer does not receive hidden chain-of-thought.

Execution/provider/judge errors are classified by code as `external_unfixable` and excluded from model-generated fixable groups. Ordinary simulated outage scenarios may still expose a quality problem in how an Agent handles the outage; the analyzer must ground that inference in observable test evidence.

Evidence strings are JSON pointers into the case evidence object, such as `/actual_output` or `/metric_scores/task_completion/score`. Server validation resolves those pointers and stores the resulting observations. Missing paths, hidden-reasoning references, missing/duplicate case IDs, inconsistent group targets and incomplete grouping are rejected. All fixable cases must belong to exactly one of at most five groups. Root-cause explanations remain model inferences, not proven internal causal traces.

Patches support:

- `append` to instructions, frozen Skill text or a tool description;
- `replace_section` with a unique exact old text anchor, excluding full-text replacement;
- `replace_value` only for a tool description with the exact prior value.

Targets are explicit enums, not arbitrary JSON paths. A patch must reference an existing fixable group's target. At most five patches and 3,000 content characters per proposal are accepted, with a 1,500-character per-patch limit and 800-character replacement anchor limit. Duplicate appended rules become no-ops. Test cases, Eval Spec, thresholds, judge/model configuration, credentials, source code, runtime and production resources are not valid patch targets.

Tool-description changes affect only frozen linked tool/MCP descriptions. The project mock adapter prefers the version description over the unchanged case description; mock results, errors and schemas are unchanged. No production tool is modified or called.

Skill changes require an existing nonempty `skill_links[].content` string in the parent snapshot. Missing historical text produces a recorded deferred suggestion. The current Skill package is never read or mutated. If all patches are unsupported/no-ops, no candidate is created and the loop stops.

## Frozen regression and acceptance

Regression checks equality of the EvalSet ID, frozen cases (including mock data), dataset hash, Eval Spec, spec hash, model-role metadata and execution mode. The existing Phase 3 executor and judge then produce an ordinary persisted Eval Run. The judge model/provider/configuration remains the same because optimizer patches cannot modify those fields. Credential values are resolved by the existing user-owned policy at call time; secret rotations are not historical key snapshots.

Comparison partitions the same case IDs into fixed, regressed, still failing and still passing. Pass rates are recomputed from per-case results. Every selected metric, including a custom metric, gets its own before/after/delta. There is no combined AI score.

A candidate is accepted only when:

1. Its pass rate increases, **or** pass rate stays equal and at least one `llm_judge` metric improves by at least 0.05.
2. No metric mean drops by more than 0.02.
3. Regressed cases do not exceed `floor(case_count * 0.05)` — one for a 20-case set, zero for fewer than 20.
4. There are no new failing tool-correctness, groundedness or format-compliance metrics on any case.
5. Both runs have complete metric evidence and no errored cases.

The exact policy and decision reasons are stored and displayed. Infrastructure errors never justify accepting a supposed prompt improvement. An incomplete candidate run cannot receive a measured acceptance; the chain fails and retains its prior best selection.

The loop stops on all-pass results, no fixable groups, no supported changes, no improvement/rejection, a worker/model failure, or completion of two rounds. It never treats the latest version as automatically best. No automatic reset allows a third round in the same chain.

## API and interface

New authenticated/CSRF-protected endpoints in the existing router:

```text
POST /api/agents/{agent_id}/project/eval-runs/{run_id}/analyze
POST /api/agents/{agent_id}/project/eval-runs/{run_id}/optimize
     {"request_id":"<UUID>"}
```

Analysis is inspectable before optimization, or optimization can perform it itself. The optimize endpoint starts a background process and returns 202. Repeated requests reuse the persisted chain and do not schedule duplicate work. Existing project, run and version GET endpoints expose progress and outcomes.

The existing workspace adds bad-case category counts, grouped plans, Optimize Agent, before/after text, case regression counts, metric changes, stop reasons and a Best Version label in history. It preserves the existing case editor, normal evaluation and version comparison controls. Project state polling refreshes version/run data as candidates and decisions arrive.

## Real controlled example

Evidence source: `backend/tests/test_agent_project_phase4.py::test_full_two_round_loop_preserves_experiment_and_selects_v2`.

This test uses the real API handlers, database storage, snapshot/patch logic, Phase 3 worker, assertions, score persistence and comparison. Model/examinee responses are controlled substitutes. **It does not demonstrate live-provider quality improvement.**

| Version | Passed | Pass rate | Task completion mean | Tool correctness | Groundedness | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| V1 | 15 / 20 | 75% | 0.725 | 1.0 | 0.9 | Original baseline |
| V2 | 18 / 20 | 90% | 0.830 | 1.0 | 0.9 | Accepted |
| V3 | 17 / 20 | 85% | 0.795 | 1.0 | 0.9 | Rejected |

V1 has five failed cases, named `Case 15` through `Case 19` (fixture names are zero-based). The analyzer groups them into three instruction issues and two Skill issues.

Applied V1 → V2 changes:

```text
Instructions: + Retrieve sources before answering.
Frozen Skill text: + Separate facts from assumptions.
```

V1 → V2 regression result:

- Fixed: **4** — Case 15, 16, 17, 18.
- Regressed: **1** — Case 14.
- Still failing: **1** — Case 19.
- Still passing: **14** — Case 0 through Case 13.
- Pass rate: **75% → 90%**.
- Best Version: **V2**.

V3 adds a general instruction to verify every requested section before finalizing, but the controlled examinee regresses on Case 13. Pass rate falls to 85% and the task-completion mean drops by 0.035. V3 is rejected, the loop stops, and Best Version remains V2.

The test deliberately empties the editable EvalSet and removes the current project Eval Spec before optimization. Both candidate runs still contain exactly the original 20 frozen cases, identical mock data, rubric, thresholds and role configuration. V1 stays immutable, and the live Agent prompt stays unchanged. Repeated requests on V1 or V2 do not create a fourth version.

## Files added

- `backend/app/schemas/agent_project_optimization.py`
- `backend/app/services/agent_project_optimization.py`
- `backend/app/services/agent_project_optimization_rules.py`
- `backend/tests/test_agent_project_phase4.py`
- `frontend/src/app/agents/[agentId]/project/_components/project-optimization.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase4.test.tsx`
- `docs/agent-project-phase4.md`

## Files modified

- `backend/app/routers/agent_projects.py`
- `backend/app/schemas/agent_project.py`
- `backend/app/services/agent_project_evaluation.py`
- `backend/app/services/agent_project_mock_tools.py`
- `backend/app/services/agent_project_service.py`
- `frontend/messages/en.json`
- `frontend/messages/ko.json`
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-versions.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-agent-project.ts`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-project-evaluation.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`

## Verification and limits

Final verification:

| Check | Result |
| --- | --- |
| Backend Phase 1–4 suites, isolated SQLite fixtures | **63 passed** (including 17 Phase 4 tests) |
| Frontend Phase 1–4 suites | **21 passed** |
| Final Phase 4 UI check after type narrowing fix | **3 passed** |
| Ruff on affected Python | Passed |
| Ruff formatting on affected Python | 9 files already formatted |
| Pyright on affected backend source | 0 errors, 0 warnings |
| TypeScript `--noEmit --incremental false` | Passed |
| Affected frontend ESLint | Passed |
| Affected JSX accessibility lint | Passed |
| Static translation guard | Passed |
| Design-system guard | Passed; 20 existing baseline warnings unchanged |
| `git diff --check` | Passed (only Git line-ending notices) |

Backend command: `.venv/Scripts/python.exe -m pytest --noconftest tests/test_agent_projects.py tests/test_agent_project_phase2.py tests/test_agent_project_phase3.py tests/test_agent_project_phase4.py -q` with temporary storage on D:.

Frontend suites: `project-workbench.test.tsx`, `project-phase2.test.tsx`, `project-phase3.test.tsx`, and `project-phase4.test.tsx`. These cover the original flows plus grouped analysis, optimization state, measured Best Version, actual stored changes, external-only failures and request identity on retry.

The installed Node remains version 24 while the repository pins Node 22. No production build or live browser E2E validation is claimed.

No production builder/runtime/tool/MCP/credential/chat/sharing/marketplace code, ORM model, migration, dependency manifest or lockfile changed. M79 remains the database migration head; no migration or dependency installation was performed.

The existing Windows `fcntl` limitation remains. There were no live model-provider calls, live Linux runtime tests, PostgreSQL tests or external tool integration tests. The controlled tests exercise the project-only workflow and mock evidence, not actual model reasoning quality. Historical Skill package execution remains unsupported even when an inline text patch is possible.

The optimization worker reuses in-process BackgroundTasks and is not a durable job queue. A process crash can leave pending/running chain metadata; no automatic retry/restart or crash-recovery feature is added here. The two-round limit and persisted state prevent repeated submissions from silently replaying billed work. Provider credentials are resolved at call time using the existing user-owned policy. Resolved key values are redacted before retained optimizer evidence; arbitrary free-text secret detection remains heuristic.

No Project Report feature, resume generator, public case study, download/export, or live deployment/promotion was implemented.
