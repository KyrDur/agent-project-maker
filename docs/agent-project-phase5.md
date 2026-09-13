# Agent Project Maker — Phase 5

Repository: the root of this natural-mold checkout.

Phase 4 checkpoint: `f0c80835c157081c0036505cb1b73a8a186ba5ee`

Checkpoint message: **Agent Project Maker Phase 4 optimization loop**

Phase 5 branch: `codex/agent-project-phase5`. Phase 5 changes remain uncommitted.

## Delivered

The existing Agent Project workspace now includes Results / Portfolio, a seven-section Project Report, three resume styles, a fixed public case-study link with revocation, and a GitHub-friendly ZIP download. Try Live Agent navigates to the existing Agent chat. It does not deploy or execute the project Best Version.

The production builder, runtime, tools, MCP, credential resolution, chat, marketplace, evaluation engine and optimization behavior are unchanged. No new dependencies, ORM models or migrations were added.

## Evidence and report flow

`agent_project_portfolio.evidence` reads the owned project, immutable versions and stored runs. The Phase 4 root run determines the frozen benchmark; its stored `best_run_id` / `best_version_id` determine the selected best. The latest version is never used as a substitute. Without a Phase 4 selection, Best Version is unavailable, even if an evaluation exists. Architecture then explicitly uses the original snapshot as descriptive evidence; no best instructions are fabricated for export.

Only terminal runs with complete stored case results and totals can contribute pass rates. Missing metrics stay missing. Mean metric deltas are deterministic differences of stored complete metric summaries. Current editable EvalSet / Eval Spec and cached report prose are not treated as evaluation evidence. Database run reads refresh existing session objects so worker updates are visible.

`render_report` formats this evidence into seven human-readable sections: overview, architecture, build process, evaluation design, bad cases, optimization/regression and final results. It uses no model call. Values displayed as percentages/rounded deltas retain their full stored precision in JSON. The report's `evidence_hash` identifies the exact sanitized evidence payload.

The three resume styles use deterministic templates, producing 1–3 bullets. Repeated generation refreshes evidence; unchanged evidence produces the same wording. There is no LLM polishing or invented user count, deployment, revenue, latency, or accuracy claim.

## Storage

All new persistent content is namespaced inside `agent_projects.report_json`:

- `portfolio_report`: cached report, sanitized evidence, evidence hash and sections.
- `portfolio_resume`: selected style, generated bullets and evidence hash.
- `portfolio_share`: active random token, public path and fixed sanitized report snapshot.

The existing `optimization` namespace is preserved. Writes use the existing project lock and refresh/merge JSON to avoid overwriting Phase 4 state. `GET /report` derives current evidence rather than blindly returning stale cached prose. No version row or live Agent is updated.

## Sharing decision and security

Inspected `backend/app/services/share_service.py`, `backend/app/models/share_link.py`, `backend/app/routers/shares.py` and the existing `/shared/` layout/gate. The conversation share table requires a non-null conversation foreign key and its reader loads conversation data. Creating a dummy conversation or weakening that schema would add unnecessary coupling.

The project-specific mechanism therefore reuses the established random bearer-link, idempotent creation, revoke and public read-only pattern, existing public `/shared/` shell/proxy handling, and common frontend API client. It uses one project lookup plus a constant-time token comparison, with a 32-byte random URL-safe token. Project UUID alone grants no access.

Creating again returns the same active link. Shares are fixed snapshots, not automatically refreshed. Revoke removes active share state; subsequent API reads return 404, and recreating generates a different token. The public page polls every 30 seconds and hides content after a failed read; content already viewed/downloaded cannot be recalled. Public responses use `Cache-Control: no-store` and `Referrer-Policy: no-referrer`; the page has noindex/nofollow metadata and no execution or mutation controls. There is no public export endpoint.

Outbound projection includes only the intended portfolio fields. Credential payloads/IDs, connection details, private source containers, raw cases, tool arguments/results, server paths and hidden reasoning are not serialized. Existing `snapshot_value`, marketplace secret scanning and redaction are reused; paths, URLs, emails and UUID references are additionally removed. Known source strings are removed if copied into summaries or exported textual configuration, including before JSON serialization.

The authenticated report can show sanitized root-cause prose and a short frozen instruction excerpt. Public sharing additionally omits instruction text, raw root-cause prose, metric criteria prose, private requirement text and tool descriptions. Representative examples are case ordinal/status/metric observations, not raw model/tool output. Text is rendered as inert React text, never HTML or executable Markdown.

Freeform text redaction remains heuristic; it is not a semantic PII detector. The share UI asks the owner to review the report, and all raw source containers are excluded independently of scanning. Credentials are never loaded for report generation.

## API

Existing authenticated prefix: `/api/agents/{agent_id}/project`

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/report` | Current deterministic report |
| POST | `/report/generate` | Generate and cache report |
| POST | `/resume/generate` | Style: `ai_product`, `product`, `engineering` |
| POST | `/share` | Create or return active fixed link |
| DELETE | `/share` | Revoke active link |
| GET | `/export` | Authenticated ZIP attachment |

Public read-only endpoint: `GET /api/project-shares/{project_id}/{token}`.

Public page: `/shared/projects/{projectId}/{token}`. Unknown/revoked shares return 404. Owner routes reuse current authentication, CSRF and ownership guards. Request bodies cannot override factual report metrics.

## Frontend integration and deviations

- Added `ProjectResults` to the existing Workbench, retaining existing versions, eval and optimization components.
- Existing components and styling primitives are reused. The project/public pages are Server Component wrappers with small Client islands.
- Added the project page's scoped `agentProject` translation provider. Existing broad test message fixtures had masked its absence in the real page hierarchy.
- Four earlier frontend test fixtures only gain a handler for the new report GET; their existing assertions are retained.
- Public read uses the existing API client; no second chat, trace or global dashboard is added.
- Try Live Agent links to `/agents/{agentId}`, which resolves the existing chat. The existing chat trace UI remains there. Project evaluations do not have a stored conversation trace ID, so the report does not fabricate a trace link or import the production debugger.
- English deterministic report/resume prose is used for portfolio artifacts. UI controls have Korean/English translations. Artifact prose localization is deferred.
- Sharing uses JSON persistence rather than the conversation share table, avoiding migrations.
- ZIP uses a constant safe `agent-project/` root and numbered Skill paths, avoiding user-controlled archive paths.

## Controlled example

The example uses the existing Phase 4 controlled examinee/judge fixture, real project persistence, optimization worker, regression comparison and Phase 5 report/export services. It makes no real provider or external tool calls.

| Version | Passed | Pass rate | Decision |
| --- | --- | --- | --- |
| V1 | 15/20 | 75% | Original baseline |
| V2 | 18/20 | 90% | Accepted; Best Version |
| V3 | 17/20 | 85% | Rejected |

V1 contains five bad cases: three instruction issues and two Skill issues. V2 appends “Retrieve sources before answering.” to instructions and “Separate facts from assumptions.” to frozen Skill text. It fixes four cases, regresses one, and leaves one previously failing case unresolved. V3 is worse and does not replace V2. Task completion increases from 0.725 to 0.830; groundedness stays 0.9 and tool correctness stays 1.0. Missing goal/intended-use fields correctly say Unavailable.

Actual generated AI Product resume bullet:

> Recorded controlled evaluation pass rates of 75.0% at baseline and 90.0% for selected V2; production impact remains unvalidated.

Generated review artifacts (ignored output directory):

- `output/phase5-controlled-example/project_report.md`
- `output/phase5-controlled-example/resume.txt`
- `output/phase5-controlled-example/agent-project.zip`

These are controlled-test examples, not live-production improvement evidence.

## Export structure

```text
agent-project/
├── README.md
├── agent.json
├── instructions.md
├── eval_spec.json
├── eval_results.json
├── skills/
│   ├── README.md
│   └── skill-1/SKILL.md  (only when safely frozen text exists)
├── versions/
│   ├── v1/agent.json + diff.json
│   ├── v2/agent.json + diff.json
│   └── v3/agent.json + diff.json
└── report/project_report.md
```

README contains Problem, Agent Architecture, Tools & Skills, Evaluation, Bad Cases, Optimization, Results and Limitations. `eval_spec.json` comes from the actual frozen run, sanitized for export. Evaluation summaries and versions retain stored decisions. Best instructions come from V2 even when V3 is latest. Missing historical Skill content produces an explanatory README; the current Skill is never read.

Exported configuration is a sanitized descriptive subset, not a deployment/import manifest. Credentials, live connections and executable Skill packages are omitted. ZIP creation occurs in memory with standard-library `zipfile`, and every final file is passed through the existing snapshot scanner before inclusion. No GitHub repository is created or pushed.

## Verification

- Backend Phase 1–5 affected suite: **74 passed** (42.77s), including 11 Phase 5 tests.
- Frontend affected suite: **28 passed**, six test files (62.28s), including seven Phase 5 owner/public tests.
- Ruff checks and affected format checks: passed.
- Pyright affected backend source: zero errors/warnings.
- TypeScript: `tsc --noEmit --incremental false` passed.
- Affected ESLint/accessibility: passed with `--max-warnings 0`.
- Translation guard: passed.
- Frontend architecture guard: passed with 43 pre-existing baseline issues, no new issues.
- Design-system guard: passed; 20 existing card-structure warnings remain unchanged.
- `git diff --check`: passed (Git only reports its existing LF/CRLF conversion notices).

Backend command: `.venv/Scripts/python.exe -m pytest --noconftest tests/test_agent_projects.py tests/test_agent_project_phase2.py tests/test_agent_project_phase3.py tests/test_agent_project_phase4.py tests/test_agent_project_phase5.py -q --basetemp=../output/phase5-tests`.

Frontend command: `vitest run` with the five project test files and the colocated public-project test. Windows ESLint received literal absolute filenames collected from the two affected route directories; wildcard paths containing `[agentId]` were not used in the final check.

The backend suite covers stored metrics, missing metrics, best versus rejected latest, history, limitations, all resume styles, evidence-derived numbers, credential/path/source redaction, unauthenticated share reads, revocation/recreation, fixed share snapshots, export structure, frozen Skills, README results, ownership, immutable versions and unchanged live Agent behavior.

Frontend coverage includes results/report display, all resume styles and copy, live/export links, create/revoke share, public inert text rendering and revoked public state, plus all earlier Phase 1–4 affected tests.

## Remaining limitations

- Controlled SQLite/API/component verification; PostgreSQL, real provider behavior and deployed browser end-to-end flows were not validated.
- The Windows `fcntl` production-runtime limitation remains unchanged. Stored `runtime_platform_unavailable` failures add a truthful report limitation; no runtime shim was added.
- Existing frozen Skill/package reproducibility and Phase 4 in-process background-task recovery limits remain.
- Live Agent equivalence is explicitly unverified; no Best Version promotion or production traffic claim.
- Node 24 is installed while the repository pins Node 22; no dependency or runtime version installation was performed.
- Shared snapshots do not automatically update; revoke/recreate to publish new evidence. Revocation cannot recall already copied artifacts.
- Reports/resumes are deterministic English templates; no LLM prose polishing.

## Files

Added (12):

- `backend/app/schemas/agent_project_portfolio.py`
- `backend/app/services/agent_project_portfolio.py`
- `backend/app/services/agent_project_portfolio_export.py`
- `backend/tests/test_agent_project_phase5.py`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase5.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-results.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-project-portfolio.ts`
- `frontend/src/app/shared/projects/[projectId]/[token]/_components/public-project.test.tsx`
- `frontend/src/app/shared/projects/[projectId]/[token]/_components/public-project.tsx`
- `frontend/src/app/shared/projects/[projectId]/[token]/_lib/public-project-api.ts`
- `frontend/src/app/shared/projects/[projectId]/[token]/page.tsx`
- `docs/agent-project-phase5.md`

Modified (13):

- `backend/app/router_registry.py`
- `backend/app/routers/agent_projects.py`
- `frontend/messages/en.json`
- `frontend/messages/ko.json`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase2.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase3.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase4.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-agent-project.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`
- `frontend/src/app/agents/[agentId]/project/page.tsx`
