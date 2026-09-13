# Agent Project Maker setup

Run commands from the repository root unless a working directory is shown.
Use Node **22.x**, pnpm **9.15.9**, Python **3.12.x**, PostgreSQL **16** and the
committed lockfiles. Do not work around the production runtime's Unix dependencies
with Windows compatibility shims.

## Existing Docker Compose path

Docker Engine/Desktop with Linux containers and Compose v2 is required. The existing
Dockerfiles already use Node 22 and Python 3.12. No alternate deployment stack is needed.

For a disposable validation instance, first create an ignored backend environment file.
Do not overwrite an existing environment or reuse a production database:

```sh
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('backend/.env')
if p.exists():
    raise SystemExit('Existing environment: review it instead of overwriting it.')
text = Path('backend/.env.example').read_text()
text = text.replace('ENCRYPTION_KEYS=\n', 'ENCRYPTION_KEYS=' + secrets.token_hex(32) + '\n')
text = text.replace('JWT_SECRET=\n', 'JWT_SECRET=' + secrets.token_hex(32) + '\n')
p.write_text(text)
p.chmod(0o600)
PY
export COMPOSE_PROJECT_NAME="apm-release-$(date +%s)"
docker compose up -d --build
docker compose ps
docker compose exec backend uv run alembic current
```

The backend runs `alembic upgrade head` before serving. Expected head:
`m79_project_evaluation`, following `m78_agent_projects`. PostgreSQL and backend
data use volumes scoped to this disposable Compose project. Default ports 5432,
8001 and 3000 must be free. Open `http://localhost:3000`; the backend is at
`http://localhost:8001`. Keep the chosen Compose project name for later commands.

Required settings are `ENCRYPTION_KEYS`, `JWT_SECRET`, `DATABASE_URL`,
`DATABASE_URL_SYNC`, and matching `CORS_ALLOWED_ORIGINS`. Compose overrides both
database URLs to its own PostgreSQL service. `NEXT_PUBLIC_API_BASE_URL` is a
frontend **build argument**; rebuild after changing the browser-facing API origin.
The example development database credentials are not suitable for public deployment.

For production, follow the existing deployment/security documentation and set the
real HTTPS origins and hardened application settings. This development Compose
recipe does not constitute production validation.

After collecting results, remove only this disposable instance:

```sh
docker compose down -v
```

## Native Linux development

Install/select Node 22 using your normal version manager, verify `node --version`,
and activate pnpm 9.15.9. Use the existing uv environment and lockfile:

```sh
corepack enable
corepack prepare pnpm@9.15.9 --activate
pnpm install --frozen-lockfile
cd backend
uv sync --frozen --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Before migration, set both database URLs in the ignored backend environment to a
fresh disposable PostgreSQL database. In another terminal:

```sh
cd frontend
pnpm preflight
pnpm dev
# For the normal production compilation:
pnpm build
```

## BYOK and a small real-provider smoke test

Register the first account on the disposable instance; the existing development
setting `ALLOW_FIRST_USER_AS_ADMIN=true` grants first-user administration. Add a
credential through the existing Credentials UI, bind it to the appropriate model
and Agent, and confirm ownership. Never paste keys into source, logs or reports.

For a minimal smoke test, use the existing project routes/UI to generate one Eval
Spec and one 20-case EvalSet. A single semantic judge invocation through the existing
`grade_case` service can verify provider JSON parsing using one frozen case and
synthetic evidence. This is an operator validation step, not a new judge implementation.
Record only success/failure, role, provider/model descriptor and sanitized errors.

Do not click Run Evaluation or Optimize for a paid 20-case loop as part of this small
smoke test. The complete demo can use the controlled command below. Environment keys
alone are not proof of a user-owned credential in the BYOK database.

## Validation commands

From `backend`, using the installed development dependencies:

```sh
uv run pytest --noconftest tests/test_agent_projects.py tests/test_agent_project_phase2.py tests/test_agent_project_phase3.py tests/test_agent_project_phase4.py tests/test_agent_project_phase5.py -q
uv run python scripts/validate_agent_project_release.py
```

The second command always creates an isolated in-memory SQLite fixture. It does not
contact a provider or use a production database. It writes ignored artifacts under
`output/agent-project-release-demo/`.

For PostgreSQL validation, separately confirm the full migration chain on the
disposable database, inspect all four project tables, test unique version/request
constraints and cross-project foreign keys, and attempt a version UPDATE inside a
rolled-back transaction to verify `agent_project_versions_immutable`. Exercise EvalSet
and EvalRun creation/read through authenticated project APIs. SQLite test success
does not prove these PostgreSQL behaviors.

See [release validation](agent-project-release.md) for what was actually executed.
