# Phase 6 — Release validation record

This is a validation/documentation phase. No Agent Project Maker product feature,
runtime, builder, evaluation or optimization behavior was changed.

## Git

- Phase 5 checkpoint: `c7c450b4ad349da2ce71c2ebff1112a402b604f1`.
- Checkpoint message: `Agent Project Maker Phase 5 portfolio and export`.
- Release branch: `codex/agent-project-release`.
- Release documentation, ignore rules and the controlled validation command are
  committed on this branch; use `git log -1` for its release-preparation commit.
- No GitHub remote is configured and no repository was published or pushed.

## Publication audit

The tracked-file audit covered 2,838 files at the Phase 5 checkpoint. No tracked
credential environment file, virtual environment, dependency directory, SQLite
database, generated ZIP, local test output or build cache was found. Only example
environment files are tracked. Ignore rules now also cover environment variants,
Playwright output, TypeScript incremental files and pnpm cache directories.

High-signal scanning checked model-provider keys, GitHub tokens, private-key headers,
Slack tokens and Google API keys. Findings were synthetic redaction/security fixtures,
the upstream scripted E2E model's dummy token, and documentation showing PEM headers;
no actual configured provider credential was identified. This is a pattern/name audit,
not a guarantee against every encoded secret or arbitrary private prose.

Machine-specific checkout paths were removed from the Phase 2–5 documents. Remaining
Windows path literals occur only in four security-test files and represent synthetic
malicious-path fixtures, not this machine's configuration. Earlier checkpoint history
still contains the previous documentation paths; history was not rewritten.

`LICENSE` and `NOTICES.md` are unchanged. The top-level README preserves upstream
natural-mold attribution and adds the Agent Project Maker workflow, architecture,
evaluation/optimization explanation, setup links and truthful limitations.

## Runtime/dependency validation

| Check | Result |
| --- | --- |
| Python | 3.12.14; matches `>=3.12,<3.13` |
| Backend dependency compatibility | 160 installed packages checked; compatible |
| Alembic discovery | `m79_project_evaluation` is the single head |
| Local Node | 24.13.0; repository requires Node 22 |
| Node 22 preparation | Official 22.x metadata reachable; archive downloads failed/interrupted; unverified binary not executed |
| Frontend preflight | Failed only Node major; dependencies, WASM and both translations present |
| Existing Dockerfiles | Node 22 and Python 3.12 inspected; unchanged |
| Docker execution | Not executed: Docker CLI/daemon unavailable |
| WSL/Linux | No installed WSL distribution found |
| PostgreSQL | Not executed: no local service/client or listening temporary instance; Docker unavailable |
| Full backend startup | Import attempted; `ModuleNotFoundError: fcntl`; no shim added |
| Normal production frontend build | Not executed in unsupported Node 24 environment |
| Browser E2E | Not executed: supported full application runtime unavailable |

Installed core backend versions include FastAPI 0.135.2, SQLAlchemy 2.0.48,
Alembic 1.18.4, asyncpg 0.31.0, psycopg-binary 3.3.3, LangChain 1.3.18 and
deepagents 0.7.11. No application dependency, lockfile or Docker architecture was changed.

The existing Compose path is documented in [setup](agent-project-setup.md). It uses
the frontend, backend and PostgreSQL services with isolated disposable volumes and
automatic migration before backend startup. Real PostgreSQL migration execution,
immutability triggers, foreign keys and API persistence still require validation there.
SQLite migration/constraint tests are not reported as PostgreSQL validation.

## Real-provider smoke test

**Not executed.** No backend environment/database is configured or reachable, so
there is no verified user-owned credential available through the existing BYOK store.
Presence of ambient provider environment variables was not treated as BYOK ownership,
and they were neither printed nor used. Zero paid model calls were made.

Pending: generate one real Eval Spec, one EvalSet and one semantic judge result using
the existing services and a user-owned credential. Do not run the full paid optimization
loop without a separate explicit request.

## Controlled demo and artifact/share validation

Command, from `backend`:

```sh
uv run python scripts/validate_agent_project_release.py
```

The Weekly Report Agent uses synthetic structured work records. The command reuses
the Phase 4 controlled SQLite fixture and Phase 5 services/public ASGI routes. It does
not exercise the conversational builder, real provider, live production tools or browser.

- V1: 15/20, 75%.
- V2: 18/20, 90%; accepted and selected best.
- V3: 17/20, 85%; rejected.
- Report and resume generated from the stored experiment.
- ZIP structure and all JSON files validated; final files passed existing secret scanning.
- No local drive paths, credential IDs or raw synthetic source records found in exports.
- Anonymous public read: 200. Public write: 405.
- Share revoked; subsequent read: 404. No persistent public internet link remains.

Ignored artifacts are in `output/agent-project-release-demo/`: report, resume, ZIP
and `validation.json`. The exported package contains README, sanitized Agent configuration,
best instructions, frozen Eval Spec, Eval results, Skills, versions and report.

## Quality gate

Final results:

- Backend Phase 1–5: **74 passed**, 40.28 seconds.
- Frontend Phase 1–5/public share: **28 passed**, six files, 63.44 seconds.
- Ruff (project backend modules/tests and release command): passed.
- Pyright (affected project services/router and release command): zero errors/warnings.
- TypeScript: `tsc --noEmit --incremental false` passed.
- Affected ESLint/accessibility: passed with `--max-warnings 0`.
- Translation guard and `git diff --check`: passed.
- Controlled release command: passed; export scan and share 200/405/404 checks passed.

Frontend tests ran on installed Node 24 and do not certify Node 22 production behavior.
Preflight deliberately rejected that Node major; the normal production build was not run.

- Backend: Phase 1–5 affected suite, Ruff and Pyright, plus controlled validation command.
- Frontend: Phase 1–5 owner/public component tests, affected ESLint/accessibility,
  translation guard and TypeScript.
- Git: diff whitespace check, ignored-output check, unchanged license/notices.

## Remaining release blockers

1. Run the full application and production build under Node 22 / Linux or Docker.
2. Execute the full migration chain on disposable PostgreSQL and verify real constraints,
   immutable UPDATE rejection, scoped foreign keys, EvalSet and EvalRun persistence.
3. Configure a verified user-owned model credential and perform the small provider smoke test.
4. Complete the real browser routing/UI walkthrough on the supported running stack.
5. Choose a destination GitHub repository/remote before any publication. If historical
   documentation paths must also be removed, plan that history cleanup separately.

The controlled MVP is reproducible; production/deployment readiness is **not certified**.
