**Agent Project Maker — Phase 2 implementation and verification**

Repository: `D:\Projects\agent-project-maker\natural-mold`.
Branch: `codex/agent-project-phase1`. Phase 1 and Phase 2 changes remain uncommitted;
the existing history contains the source-import commit `e717881`.

**Architecture and scope**

The existing project service, four project tables, router, snapshot serializer,
canonical JSON hash, authentication, CSRF, and workspace are extended. There is
no new builder, agent configuration format, credential resolver, or runtime engine.
The existing skill-evaluation code was inspected: its skill-package execution,
baseline arms, and grading structures are not an Agent snapshot execution adapter.
They were not repurposed into misleading Agent quality scores.

This is a restricted evaluation foundation, not full live-runtime reproduction.
Version creation, case management, run persistence, structural scoring, and
comparison are implemented. The runtime adapter supports only snapshots without
linked tools, skills, MCP, subagents, custom middleware, or model fallbacks, and
requires a usable user-owned model credential. Unsupported configurations fail
explicitly; no capability is silently dropped or loaded from the current Agent.

**Version creation**

A project write lock serializes version creation on PostgreSQL and SQLite.
The service refreshes the source Agent, reuses the Phase 1 snapshot builder and
canonical hash, and inserts a new immutable candidate with the latest version as
parent. Database constraints protect version numbers and request IDs.

The response outcome is `created`, `unchanged`, or `replayed`. An unchanged hash
returns the latest version without creating another row. A request ID that created
a version always replays that version, even after subsequent source edits. No-op
request IDs are not reserved: submitting one again after a later configuration
change can create a version. The UI retains request IDs across failures and resets
them after a successful response. V1 and later snapshots are never overwritten.

**Database and migration**

`m79_project_evaluation` follows `m78_agent_projects`; the old migration is unchanged.

- `agent_project_versions`: nullable request ID and scoped uniqueness.
- `agent_project_eval_sets`: existing JSON cases remain the dataset storage;
  scoped uniqueness supports composite foreign keys.
- `agent_project_eval_runs`: request ID, frozen case snapshot, dataset hash,
  start time, and fixed-code error field. Existing result/metric fields are reused.
- Composite foreign keys prevent a run from referencing another project's
  version or dataset. Status and request uniqueness constraints are enforced.
- SQLite batch migrations restore the immutable-version trigger after table
  recreation. PostgreSQL ALTER operations preserve the existing trigger.

Each dataset case has an ID, project ID, name, input, optional user/assistant
context, expected behavior, optional exact answer, required/forbidden tools,
optional handoff, tags, enabled flag, and creation/update timestamps. The API
assigns ownership metadata. JSON avoids an unnecessary case-table hierarchy.
There are at most 20 cases per dataset; text/context limits are validated.
Cases can be authored in the UI or imported through the dataset API.

**API**

All paths below are relative to `/api/agents/{agent_id}/project`.

| Method and path | Behavior |
| --- | --- |
| GET base | Existing project or null; unchanged Phase 1 contract |
| POST /create | Explicit project and V1 creation; unchanged contract |
| GET /versions | Version summaries |
| GET /versions/{version_id} | Immutable snapshot and metadata |
| POST /versions | Create/replay version or return unchanged |
| GET /compare?left={uuid}&right={uuid} | Configuration changes and evaluation summaries |
| GET /eval-sets | Owned project's datasets |
| POST /eval-sets | Create dataset |
| PUT /eval-sets/{set_id} | Replace dataset's authored cases |
| DELETE /eval-sets/{set_id} | Delete unused, unfrozen dataset |
| POST /eval-runs | Submit/replay run; HTTP 202 |
| GET /eval-runs | Latest 100 runs |
| GET /eval-runs/{run_id} | Historical status, metrics, and per-case evidence |

Create-version body:

```json
{"request_id":"<uuid>","change_summary":"Optional explanation"}
```

Create/update dataset body:

```json
{
  "name": "Greeting tests",
  "cases": [{
    "name": "Greeting",
    "input": "Hello",
    "context": [],
    "expected": {
      "answer": "Respond politely; manual review only",
      "exact_answer": "Hello!",
      "required_tools": [],
      "forbidden_tools": [],
      "handoff": null
    },
    "tags": ["greeting"],
    "enabled": true
  }]
}
```

Case IDs may be omitted on creation; preserve returned IDs when editing.
Creation/update timestamps and project IDs are response metadata, not writable
case fields. The frontend API client removes that metadata before updates.

Create-run body:

```json
{"request_id":"<uuid>","version_id":"<uuid>","eval_set_id":"<uuid>"}
```

Reusing a run request ID with a different version/dataset returns 409. Every
project/version/dataset/run lookup is ownership-scoped; foreign resources return
404. Mutations use the existing authentication and CSRF dependencies. Project
validation errors omit submitted values to avoid echoing sensitive input.

**Evaluation lifecycle and historical isolation**

Submission atomically stores `pending`, the selected immutable version ID, a
copy of enabled cases, and their canonical hash. A FastAPI background task uses
its own database session and atomically claims `pending -> running`. A repeated
task cannot claim the same run twice. Cases execute sequentially with a 30-second
timeout; per-case results are committed as they finish.

Successful execution with failed assertions is a `completed` run with failed
cases. Execution errors make the run `failed`, retaining case evidence and
aggregate counts. Metrics are total, passed, failed, errored, and pass rate;
they represent structural assertions, not semantic quality. Expected-behavior
prose remains available for manual review and is not automatically scored.

The adapter constructs transient Agent/Model projections from the saved snapshot
solely for the existing credential resolver. It never attaches them to the DB.
The existing model factory and canonical `build_agent` construct the graph with
a fresh `StateBackend`, no shared store/checkpointer, and no live memory or skill
mounts. No Conversation, chat messages, deployments, or source Agent settings are
written. Canonical in-memory built-in graph tools can still produce structural
tool-call evidence. Production memory/temporal-context injection is not reproduced.

Ordinary linked-tool execution is deferred because the current tool adapter
combines credential resolution, live Agent/resource identity, hooks, and approval
policy. MCP snapshots omit connection configuration; skill/subagent references
do not pin a complete executable dependency tree. Implementing that isolation
contract requires another deliberately scoped adapter increment, not a broad
runtime refactor. No trigger-mode approval bypass is used here.

Background tasks are not a durable queue. A process crash can leave pending or
running rows. On the next CSRF-protected run submission, rows older than 15 minutes
are marked failed; they are never automatically replayed. GET endpoints remain
read-only. Until reconciliation, an interrupted run can still display its former
status. Durable queueing/restart recovery is not claimed.

**Comparison and UI**

The workspace retains explicit project creation and adds version creation,
history/hash metadata, secondary raw snapshot details, case add/edit/remove and
enable/disable controls, version selection, run submission/history, and per-case
output/assertion/error inspection. Loading, retry, empty, and disabled states use
the existing shared components. All new copy has Korean and English translations.

Comparison identifies changed configuration fields and added/removed/changed
resource links. Prompt changes are shown side-by-side; larger values are secondary
details. Each version's latest completed run is shown alongside it. Different
dataset hashes or missing runs are explicitly marked non-comparable. The UI never
declares an automatic winner. No rollback or deployment action exists.

**Credential handling**

Credential payloads are not serialized into versions, datasets, runs, or traces.
Execution resolves user credentials through the existing ownership-aware resolver;
explicit missing references fail. Operator/environment fallback is disabled and
keyless resolution is rejected. Credentials may rotate: the saved reference, not
the historical secret value, is used.

The existing protocol redactor masks resolved key values before retained evidence
crosses the database/API boundary. Only tool names are retained, not raw tool
arguments/results. Provider exceptions are replaced by fixed error codes and are
not logged by the new worker. External LangSmith tracing is disabled in the adapter.
Source configuration and authored cases reuse Phase 1's heuristic scanner.
As with that scanner, arbitrary unrecognized secrets pasted into free text cannot
be guaranteed detectable; users should not author cases containing credentials.

**Files added in Phase 2**

- `backend/alembic/versions/m79_project_evaluation.py`
- `backend/app/services/agent_project_evaluation.py`
- `backend/app/services/agent_project_executor.py`
- `backend/tests/test_agent_project_phase2.py`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-project-evaluation.ts`
- `frontend/src/app/agents/[agentId]/project/_components/project-select.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-versions.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-case-editor.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-evaluation.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-comparison.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-phase2.test.tsx`
- `docs/agent-project-phase2.md`

**Phase 1 files modified in Phase 2**

- `backend/app/models/agent_project.py`
- `backend/app/schemas/agent_project.py`
- `backend/app/services/agent_project_service.py`
- `backend/app/routers/agent_projects.py`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-agent-project.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`
- `frontend/messages/ko.json`
- `frontend/messages/en.json`

Existing Phase 1 model/router registration and settings navigation changes remain
in the working tree but were not expanded in Phase 2. Dependency declarations,
lockfiles, builder/runtime/tool/MCP/credential/skill implementations, sharing, and
marketplace modules were not modified.

**Verification**

- Backend: 29 passing tests (8 Phase 1 + 21 Phase 2), using
  `python -m pytest --noconftest tests/test_agent_projects.py tests/test_agent_project_phase2.py -q`.
- Frontend: 15 passing tests (3 retained/adapted Phase 1 + 12 Phase 2), using
  `vitest run` on the two project component test files.
- Affected Python: Ruff check/format and Pyright passed.
- Frontend: TypeScript, affected ESLint, and affected accessibility ESLint passed.
- Translation and design-system guards passed. Architecture guard reported its
  existing 43 issues outside the new project implementation; no baseline edited.
- SQLite: migration upgrade/downgrade, preservation of V1, immutable SQL-update
  protection, scoped foreign keys, and concurrent request deduplication tested.
- The canonical adapter boundary was tested with controlled graph/model/credential
  substitutes, including special-character secret redaction and no source writes.
  No paid/live model call was made.

**Environment limits and deferred work**

No PostgreSQL listener was available on localhost:5432, and no psql/docker command
was found on PATH. PostgreSQL migration execution is not verified. No migration
was applied to a live database. The full application test harness and real
canonical graph import require Unix `fcntl`, unavailable in this Windows Python
environment; isolated router tests do not claim full-runtime integration coverage.
Frontend preflight still fails its Node 22 requirement because installed Node is
24; other available checks were run without altering versions or lockfiles.

Live Agent/runtime behavior is unchanged. V1 remains immutable. Automatic
optimization, prompt rewriting, autonomous improvement/version generation,
LLM-as-Judge, report generation, rollback/deployment, publishing, and production
routing are intentionally excluded. No Phase 3 functionality was started.
