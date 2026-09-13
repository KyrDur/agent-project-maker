# Agent Project Maker on Alibaba Cloud 2C2G + BaoTa

Repository-side preparation only. No server has been accessed or deployed.
Target: existing Linux Lightweight Application Server, 2 vCPU / 2 GB RAM,
existing BaoTa/BT Nginx, personal use, interview demos and a few external users.
This is not a high-concurrency deployment. The release's remaining live-runtime
validation is recorded in [agent-project-release.md](agent-project-release.md).

## A. Before deployment

Use `compose.alibaba-2c2g.yml` **alone**, never combined with the development
`docker-compose.yml`, which publishes PostgreSQL and binds application ports publicly.
The source release is `7aa8a5e0f48e8c5717f8c652d19c8ba424bd7dd5`.
Deployment files prepared after that release must also be transferred to the server;
they are not automatically present in GitHub main. No commit/push is implied here.

Architecture:

```text
Internet :80/:443 -> existing BaoTa Nginx (TLS)
  /         -> 127.0.0.1:3000 -> frontend (Node 22 standalone)
  /api/...  -> 127.0.0.1:8001 -> backend :8000 (Python 3.12, one async worker)
                                      -> postgres:5432 (private Docker network)
                                      -> external model APIs (user BYOK)
```

No additional Nginx, Redis, monitoring platform, local LLM, embedding service,
Ollama, Kubernetes or certificate manager is required. Linux supplies `fcntl`;
no Windows compatibility shim is added. Keep the existing Dockerfiles.

Before remote work provide: authorized SSH method/user/host/port (no password or
private key in source), Linux distribution/version, CPU architecture, free disk,
current Docker/Compose versions, domain/subdomain, Alibaba region, and existing
BaoTa services/sites/ports and their memory use. Confirm DNS and any hosting
requirements applicable to the region before opening the site. Do not replace
working firewall, Docker or Nginx installations blindly.

## B. Server resource check

Run these read-only commands on the server:

```bash
cat /etc/os-release
uname -m
nproc
free -h
swapon --show
df -h / /var/lib/docker
findmnt -no FSTYPE /
sudo ss -lntp
ps -eo pid,comm,rss --sort=-rss | head -20
docker version
docker compose version
docker info
docker system df
```

If Docker is absent, its checks will fail; continue to D after identifying the OS.
Budget at least 10 GB free **after swap allocation**, plus actual image, database
and backup growth. This is a planning floor, not a measured image-size guarantee.
If existing BaoTa MySQL/PHP/other sites consume most RAM, stop and reassess with
the owner; do not disable unrelated services automatically.

| Consumer | Initial planning estimate | Container RAM cap | RAM + swap cap |
| --- | --- | --- | --- |
| Backend and any skill subprocesses | 400–700 MiB, workload dependent | 768 MiB | 1024 MiB |
| PostgreSQL | 180–350 MiB, query dependent | 384 MiB | 512 MiB |
| Frontend standalone | 100–230 MiB, workload dependent | 256 MiB | 384 MiB |
| Linux, Docker, BaoTa, Nginx, other services | Must fit remaining capacity | About 640 MiB left by caps | Host swap only |

Estimates are not benchmarks. Backend imports, skill subprocesses, large uploads,
Next.js rendering and query workspaces can exceed them. Container caps can cause
an individual OOM; health checks do not prove capacity. Frontend V8 old-space is
160 MiB, distinct from total process RSS. Swap absorbs spikes, not sustained load.
CPU is shared across the two cores; do not scale backend workers or replicas.
The existing skill-evaluation concurrency is one; this is not a global admission
limit for every chat or Agent Project request. Begin with one Eval workflow at a time.

## C. Swap (minimum 2 GiB)

Inspect existing swap first. If total active swap is at least 2 GiB, keep it and
verify its existing boot persistence; do not create another file. If less, the
following guarded block creates a new 2 GiB file, keeping any existing swap.
Change `swap_mib=2048` to `4096` only when disk safely allows it. Use on a local
ext4/XFS filesystem; stop for Btrfs/other filesystems and use their supported
swapfile procedure. Never reformat a partition or overwrite an existing file.

```bash
free -h
swapon --show
df -h /
sudo bash <<'SH'
set -euo pipefail
swap_kib=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
if [ "$swap_kib" -ge 2097152 ]; then
  echo 'At least 2 GiB swap already active; verify its persistence separately.'
  exit 0
fi
case "$(findmnt -no FSTYPE /)" in
  ext4|xfs) ;;
  *) echo 'Stop: filesystem requires a reviewed swapfile procedure.'; exit 1 ;;
esac
swap_path=/swapfile-agent-project
swap_mib=2048
if [ -e "$swap_path" ] || [ -L "$swap_path" ]; then
  echo 'Stop: swap target already exists; inspect it without overwriting.'; exit 1
fi
if grep -Fq "$swap_path" /etc/fstab; then
  echo 'Stop: an fstab entry already exists; reconcile it first.'; exit 1
fi
available_kib=$(df -Pk / | awk 'NR==2 {print $4}')
required_kib=$((swap_mib * 1024 + 10 * 1024 * 1024))
[ "$available_kib" -ge "$required_kib" ] || { echo 'Insufficient free disk'; exit 1; }
umask 077
dd if=/dev/zero of="$swap_path" bs=1M count="$swap_mib" status=progress conv=excl
chmod 600 "$swap_path"
mkswap "$swap_path"
swapon "$swap_path"
cp -a /etc/fstab "/etc/fstab.agent-project.$(date +%Y%m%d-%H%M%S).bak"
printf '%s none swap sw 0 0\n' "$swap_path" >> /etc/fstab
SH
free -h
swapon --show
```

If any step fails, stop and inspect the existing file/active swap before retrying;
do not delete or disable active swap. Verify again after the next planned reboot.

## D. Docker / Compose and image build strategy

Reuse a working Docker Engine + Compose plugin. Installation depends on the
confirmed OS; use the [official distribution instructions](https://docs.docker.com/engine/install/)
or BaoTa's supported installation path. Do not install Docker Desktop on the server.
Check `docker info` for memory/swap-limit support; validate real limits after startup.

**Recommended: build both images on a separate Linux Docker builder**, or Windows
Docker Desktop using Linux containers, matching the server's architecture. This
Windows task currently has no usable Docker CLI, so image builds are still pending.
The existing frontend multi-stage build produces a small standalone runtime but
its build-stage peak memory has not been measured. Building on this 2 GB host
can OOM even with swap, especially beside BaoTa and a live database. Runtime
Compose limits do not constrain Docker build stages. No complex CI/CD is needed.

On a capable builder, from the prepared repository, example for an x86_64 server:

```bash
# Change linux/amd64 to linux/arm64 only if server uname -m is aarch64.
# Domain is baked into frontend JavaScript; do not build for YOUR_DOMAIN literally.
docker buildx build --platform linux/amd64 --load -f backend/Dockerfile \
  -t agent-project-backend:7aa8a5e .
docker buildx build --platform linux/amd64 --load -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://YOUR_DOMAIN \
  --build-arg NEXT_PUBLIC_CHAT_RUNTIME=langgraph_v3 \
  -t agent-project-frontend:7aa8a5e .
docker image save -o agent-project-7aa8a5e.tar \
  agent-project-backend:7aa8a5e agent-project-frontend:7aa8a5e
```

Transfer this archive with your authorized SSH/SFTP method and `docker image load
-i agent-project-7aa8a5e.tar` on the server. Keep archives outside the source tree.
Alternatively tag/push to your chosen registry from the builder, set both image
references in the server environment, and run `dc pull`. Use trusted registry
access appropriate to the server's region; do not guess mirrors. Record image IDs
or immutable digests and the source commit. Never reuse a release tag for updates.
No images have been built or published by this preparation.

Server-side builds are an emergency option only after swap, free disk, maintenance
downtime and headroom are confirmed: build one service at a time (`dc build backend`,
then `dc build frontend`) and watch memory from another SSH session. Abort if the
host thrashes. Off-host builds remain the recommended path.

## E. Environment configuration

Place the prepared repository at `/opt/agent-project-maker` (or an explicitly
chosen directory). Commands below run there using Bash and Docker privileges.

```bash
cd /opt/agent-project-maker
umask 077
# Only on first setup; this refuses to overwrite an existing environment file.
( set -o noclobber; cat .env.production.example > .env.production )
chmod 600 .env.production
# Edit locally on the server with your editor; do not paste secrets into Git/chat.
nano .env.production
```

Set all nine template values. `POSTGRES_USER` and `POSTGRES_DB` should be simple
lowercase letters/digits/underscores. Generate `POSTGRES_PASSWORD` as 32 random
bytes in hexadecimal (`openssl rand -hex 32`); this avoids URL escaping in the
two database connection strings. Generate `ENCRYPTION_KEYS` the same way.
Generate **two separate** JWT/hash secrets with `openssl rand -hex 48`.
Run generation separately in your private terminal and store each result securely.
Do not copy the placeholder values. Retain the encryption key across all restarts,
updates and restores: losing it makes stored BYOK secrets unreadable. Retain the
API hash secret for existing external Agent API keys; changing JWT invalidates sessions.

`PUBLIC_ORIGIN=https://YOUR_DOMAIN` is the public frontend and API origin, **without
`/api` or a trailing slash**. Clients append `/api/...` themselves. Use the same
origin during frontend image build; changing runtime env alone cannot update the
browser bundle. Same-origin routing avoids cross-site cookie configuration.
The backend URL inside Compose is generated as `postgres:5432` for DBs, while
public API access is `https://YOUR_DOMAIN/api/...`. No extra application secret
or OAuth client is required for ordinary email/password login. Cookie domain is
unset (host-only); secure cookies and explicit CORS are already configured.

The Compose file explicitly maps required secrets; it does **not** import
`backend/.env` or ambient model-provider keys. Optional Google/MCP OAuth and external
tool integrations have their own existing setup and are not required for basic use.

Define this wrapper in each operational shell (it pins the production file):

```bash
dc() { docker compose --env-file .env.production -f compose.alibaba-2c2g.yml "$@"; }
dc config --quiet
```

Do not publish the output of plain `dc config` or container environment inspection;
they contain interpolated secrets. `config --quiet` validates syntax, not placeholder
strength. Review that every CHANGE_ME/YOUR_DOMAIN placeholder has been replaced.

## F. PostgreSQL and persistence

```bash
dc up -d postgres
dc ps
dc exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

PostgreSQL 16 uses `postgres -c` options: shared buffers 128 MB, effective cache
size 512 MB, maintenance memory 64 MB, work memory 4 MB, 25 connections, no
parallel query workers per gather. Effective cache size is a planner estimate,
not allocated memory. Work memory is per query operation, not a total cap.
SQLAlchemy allows 3 pooled + 2 overflow connections; the checkpointer allows 1–4,
leaving room for scheduler, maintenance and admin connections. Do not increase
worker counts without re-budgeting all pools.

| Persistent location | Data retained |
| --- | --- |
| `agent-project-maker_postgres_data` | Users/password hashes/sessions; Agents; encrypted credential payloads and metadata; Agent Projects, versions, EvalSets, EvalRuns, reports and share records; other existing application tables and checkpoints |
| `agent-project-maker_backend_data` mounted at `/app/data` | Skills/packages/marketplace files, uploads, conversations/offloads, artifacts, Agent images and user avatars; existing default storage subdirectories |
| Host `.env.production` in secure backups | Encryption/signing/hash secrets and deployment settings |

The existing storage defaults live under `./data` and backend WORKDIR is `/app`.
Do not override individual storage directories to ephemeral locations. Keep any
downloaded report/export you want outside the application in your own backups too.
Frontend has no required persistent volume. Image recreation preserves named
volumes; changing Compose project name creates different volumes. Never use
`down -v`, `volume prune`, or delete Docker's data directory during maintenance.
Changing `POSTGRES_*` does not reconfigure accounts in an already initialized volume.

## G. Application startup and real users

After images are loaded/pulled and configuration validated:

```bash
dc up -d --no-build
dc ps
dc logs --tail=100 backend
curl --fail http://127.0.0.1:8001/api/health
curl --fail -o /dev/null http://127.0.0.1:3000/login
```

Backend startup runs `alembic upgrade head`, then execs Uvicorn with **one worker**.
It uses the installed Python environment directly, avoiding startup package sync.
Production refuses insecure settings, including automatic first-user admin promotion.
Keep `ALLOW_FIRST_USER_AS_ADMIN=false`; do not temporarily run publicly in dev mode.

After H–J establish HTTPS, use `/register` for your operator's ordinary account.
Temporarily restrict this site's access to your IP during bootstrap if needed,
while retaining BaoTa's certificate challenge access. Promote only that known
account in an interactive database session:

```bash
dc exec postgres sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Inside psql, replace the email, inspect the exact matching row, then commit only
after `RETURNING` shows the intended account. This changes an account role, not its
password, and must be done by the server operator:

```sql
\set operator_email 'YOUR_OPERATOR_EMAIL'
SELECT id, email, is_active, is_super_user FROM users WHERE email = :'operator_email';
BEGIN;
UPDATE users SET is_super_user = true
WHERE email = :'operator_email' AND is_active = true
RETURNING id, email, is_super_user;
-- Exactly one intended account must be shown. Otherwise use ROLLBACK.
COMMIT;
\q
```

Sign out/in. Other users use the existing `/register` and `/login`, add their own
provider credential in Credentials, choose/bind an available compatible Model,
create an Agent through the existing manual creation path, and create its Agent
Project. Agent runtime and project planner/judge/examinee resolve user-owned keys;
no provider key is provisioned in this deployment template.

**Existing limitation:** some Builder/Assistant/image flows use operator System
LLM configuration and do not consume arbitrary user BYOK. They remain unconfigured
here; do not promise that conversational creation/image generation works with BYOK
alone. Manual Agent creation and project workflows are the baseline acceptance
path. Any later operator-funded service configuration is a separate decision.
Email verification/password recovery are not provided by adding SMTP/OAuth values
to this template; do not claim those flows are deployment-enabled.

Ownership is unchanged: the project router uses `get_current_user`, passes `user.id`
to services, and `owned_agent`/project queries filter on the owner. Cross-user
lookups return 404. Public shares are intentional token-based exceptions, revocable
and read-only. Run the two-user acceptance check below against the real deployment.

## H. BaoTa reverse proxy

Create/select the website for `YOUR_DOMAIN` in BaoTa. Use
[`deploy/baota-agent-project.conf.example`](../deploy/baota-agent-project.conf.example)
inside that site's HTTPS `server` block. Back up its existing config first.
Do not overwrite global Nginx config or other sites. Keep BaoTa-managed TLS and
ACME locations. Remove conflicting root/PHP/static-extension caching rules for
this application site so Next.js assets and API downloads reach their upstreams.
Do not cache authenticated pages or API responses.

The template preserves `/api` in upstream paths, sets Host, real IP and forwarded
scheme, disables API proxy buffering/cache for SSE, and allows one-hour gaps
between API reads. The existing stream transport is SSE; no application WebSocket
route was found in the inspected router/transport surface, so no unnecessary Upgrade
configuration is installed. Next.js development HMR is irrelevant to production.
The template allows 100 MB requests; application-specific smaller limits still apply.

Nginx overwrites forwarded client IP rather than trusting a client-supplied chain.
Uvicorn trusts proxy headers inside this private Compose network; this depends on
the backend port remaining loopback-only and no untrusted containers joining the
project network. If an upstream CDN/proxy is added later, review its real-IP trust
configuration separately. Do not expose the Uvicorn port.

Use BaoTa's Nginx configuration test, then reload only on success. If the standard
BaoTa path is present, the equivalent test is:

```bash
sudo /www/server/nginx/sbin/nginx -t
```

Reload through BaoTa after a successful test. The exact live server configuration
has not been inspected, so merging the snippet and its final syntax test remain pending.

## I. SSL

Point domain A/AAAA records only to addresses this server actually serves. Obtain
and renew the certificate using BaoTa's normal SSL functionality. Keep its ACME
challenge route reachable, enable HTTPS and redirect ordinary HTTP to HTTPS using
BaoTa. Do not add another certificate manager. Verify:

```bash
curl --fail https://YOUR_DOMAIN/api/health
curl --fail -o /dev/null https://YOUR_DOMAIN/login
```

Confirm browser login persists, secure cookies work and the browser calls the HTTPS
domain rather than localhost. Avoid IP-based HTTP login: secure cookies require HTTPS.

## J. Alibaba firewall / security-group checklist

For Lightweight Application Server, inspect the instance **Firewall** rules in its
console (and any additional applicable security group), not an assumed ECS rule set.
Also review BaoTa/OS firewall and IPv6 rules; current rules are unknown.

- Public inbound TCP 80 and 443 for the site and BaoTa certificate flow.
- Preserve the actual SSH port (22 only if currently used), preferably restricted
  to your administration IP. Keep a working session/console recovery method while editing.
- Restrict the actual BaoTa management port to administrator IPs or a private access
  method. Do not lock yourself out or expose it broadly as an application requirement.
- No public PostgreSQL 5432, backend 8001/8000 or frontend 3000 rules.
- Keep outbound DNS, HTTPS to selected external model APIs and image registries
  reachable. Confirm provider availability from this region without paid test calls.
- Verify host bindings with `sudo ss -lntp` and `dc ps`; test reachability from a
  separate external machine. Do not rely solely on a host firewall to hide Docker ports.

## K. Migration, health and acceptance verification

```bash
dc exec -T backend /app/.venv/bin/alembic current
dc exec -T backend /app/.venv/bin/alembic heads
dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version;"'
dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW max_connections;" -c "SHOW shared_buffers;"'
dc exec -T backend /app/.venv/bin/python --version
dc exec -T frontend node --version
dc ps
docker stats --no-stream
free -h
df -h
```

At this release, the single Alembic head is `m79_project_evaluation`; both commands
must agree. A manual migration during maintenance, with frontend/backend stopped:

```bash
dc stop frontend backend
dc run --rm --no-deps backend /app/.venv/bin/alembic upgrade head
# Continue only if the migration succeeded.
dc up -d --no-build
```

Postgres health checks use pg_isready; backend checks `/api/health`; frontend checks
`/login`. Backend health is lightweight process liveness, not a DB/provider probe.
Docker marks unhealthy containers but does not restart them merely for being unhealthy;
`unless-stopped` handles process exits and daemon restart. Inspect failures.

Before inviting users, verify two accounts cannot read/change each other's Agent
Projects/EvalRuns by substituting IDs (expect 404), register/login, credential save,
Agent creation, one small BYOK Eval workflow, report/export and public share/revoke.
With the user's approval for API charges, run the small real-provider workflow;
no paid calls are part of repository preparation. Confirm data/credential decryption
after a controlled restart. Observe `docker stats`, `free -h`, and `vmstat 1` during
the run. Check for OOM/restarts:

```bash
for service in postgres backend frontend; do
  docker inspect --format '{{.Name}} restart={{.RestartCount}} oom={{.State.OOMKilled}} memory={{.HostConfig.Memory}} memorySwap={{.HostConfig.MemorySwap}}' "$(dc ps -q "$service")"
done
```

Acceptance: no repeated restarts/OOM, stable DB, one workflow completes, responsive
normal browser use and no sustained swap thrashing or continuously exhausted
available RAM. If it fails, stop adding traffic; inspect existing services and workload
size before changing limits. A larger server may be required for that workload.

## L. Logs and status

```bash
dc ps
dc logs --tail=100
dc logs -f --tail=100 backend
dc logs --tail=100 postgres
docker stats
free -h
df -h
```

Each container uses Docker json-file rotation: 10 MB × 3 files. Configure BaoTa
access/error-log rotation separately in the panel. Do not post raw logs publicly;
review/redact user content and credentials first. Images/backups can still fill disk.

## M. Restart and stop

```bash
dc restart
dc up -d --no-build
# Maintenance shutdown; named volumes remain. Causes downtime.
dc down
# Start again using the same project name, configuration and volumes.
dc up -d --no-build
```

`restart` does not apply changed environment/image configuration; use `up -d --no-build`
after updating settings. Never append `-v` to `down`. Plan a quiet window because
active model streams/workflows may be interrupted; do not assume automatic resume.

## N. Backup and restore

Back up PostgreSQL, `/app/data`, exact image identifiers, deployment files and the
encryption/signing secrets as one recovery set. Store protected off-server copies.
Backups contain user data and encrypted credentials; keep secrets separately secured.
Use a quiet window, let active work finish, then stop both application containers
so the SQL dump and filesystem snapshot are mutually consistent. PostgreSQL stays up.

```bash
set -e
umask 077
backup_dir="/opt/agent-project-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
dc stop frontend backend
dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_dir/database.dump"
# Check exit status immediately; do not accept a failed or empty backup.
test -s "$backup_dir/database.dump"
dc run --rm --no-deps --entrypoint tar backend -C /app/data -czf - . > "$backup_dir/backend-data.tar.gz"
test -s "$backup_dir/backend-data.tar.gz"
cp .env.production compose.alibaba-2c2g.yml "$backup_dir/"
docker image inspect --format '{{.Id}} {{json .RepoTags}} {{json .RepoDigests}}' \
  "$(dc images -q backend)" "$(dc images -q frontend)" > "$backup_dir/images.txt"
tar -tzf "$backup_dir/backend-data.tar.gz" > /dev/null
dc exec -T postgres pg_restore --list < "$backup_dir/database.dump" > /dev/null
# Resume only after checking command results. Copy/encrypt the backup off-server.
dc up -d --no-build
```

Run backup commands in a shell with `set -e` (or inspect each exit status before
continuing) so a failed dump/archive is not mistaken for a recovery point. Use a
trusted existing backup/encryption destination; do not commit backup files.

**Restore causes downtime and replaces the active dataset with the backup's point
in time.** Prefer a fresh Compose project with empty named volumes, preserving the
old volumes for recovery. Do not restore onto a running application or merge a
filesystem archive into populated storage. Example on the same host after stopping
the original stack, using copied deployment config and matching old images:

```bash
dc down  # downtime, preserves original volumes
cd /opt/agent-project-backups/YOUR_BACKUP_DIRECTORY
rc() { docker compose -p agent-project-maker-recovery --env-file .env.production -f compose.alibaba-2c2g.yml "$@"; }
# STOP if these names already exist; choose a fresh recovery project name.
docker volume ls --filter name=agent-project-maker-recovery
rc up -d postgres
# Wait for postgres healthy in rc ps before restore.
rc exec -T postgres sh -c 'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database.dump
rc run --rm --no-deps -T --entrypoint tar backend -C /app/data -xzf - < backend-data.tar.gz
rc up -d --no-build
rc ps
```

Load/pull the backup's exact images first if absent. The recovery directory lacks
source build context: always use prebuilt images and `--no-build`. Only restore
trusted archives. Verify K and a real credential decrypt/read before admitting users.
If this recovery becomes production, retain its directory and project name and use
the `rc` wrapper for all subsequent operations; switching back to `dc` would select
the old dataset. Record that change explicitly. Test restoration before relying on backups.

## O. Update procedure

1. Build new versioned images off-host from a reviewed commit, using the same public
   origin. Record source SHA and immutable image IDs/digests; retain previous images.
2. Transfer/load or pull the new images before the downtime window. Do not build on
   the running 2 GB host. Keep Node 22 / Python 3.12 and PostgreSQL major 16.
3. Complete N's verified backup and retain old deployment/environment files.
4. Stop frontend/backend; update deployment files and image references in
   `.env.production`. Preserve all secrets, project name, volume names and DB settings.
5. Run the following, checking each result. Automatic startup migration is idempotent
   after the explicit migration, but rollback compatibility must be reviewed first.

```bash
dc stop frontend backend
dc config --quiet
dc run --rm --no-deps backend /app/.venv/bin/alembic upgrade head
dc up -d --no-build
dc ps
dc logs --tail=100 backend
```

6. Perform K and resource checks; reopen traffic only after success. Do not run
   repository reset/clean, prune volumes, or replace keys as an update mechanism.

## P. Rollback

If no incompatible migration/data change occurred, stop frontend/backend, restore
the prior image references and deployment settings (same secrets), then `dc up -d
--no-build` and verify K. Old code must support the current schema; do not assume it.
Do not run a blind Alembic downgrade. If the schema is incompatible, use N's fresh-volume
restore with the matching old images and backup environment. This loses writes after
the backup; agree the recovery point before switching. Preserve the failed stack's
volumes for investigation. Database rollback is not accomplished by changing an image tag.

## Preparation verification and remaining work

No application/auth/project source files or migrations are changed by this preparation.
Local preparation checks on 2026-09-13:

- Phase 1–5 plus production-hardening tests: **87 passed**, 34.51 seconds, using
  Python 3.12.14 and the existing isolated `--noconftest` fixtures on Windows.
- Ruff and Pyright: passed for the inspected config, production validator, project
  router, ownership service and BYOK model resolver (zero type errors/warnings).
- Official Compose JSON Schema: passed. Template variables, loopback-only published
  ports, database pool budget and the existing production-safety validator passed
  using synthetic secrets. This is not `docker compose config` or Engine validation.
- Existing high-signal secret-content patterns: passed on all six changed/added
  deployment files; `.env.production.example` contains only placeholders.
- Frontend application files are unchanged; TypeScript was not rerun.

Live Docker build, Compose/Engine behavior, BaoTa syntax/SSL, PostgreSQL migrations,
BYOK calls, two-user browser behavior, backup restore and peak memory still require
the actual Linux environment. Repository tests cannot certify 2 GB production capacity.

Next: provide the non-secret server facts in A, choose the domain and off-host image
builder/transfer method, transfer the prepared files, then follow B–K in order.
Stop before remote access until an authorized access method is established.

### Configuration references

- [Docker Compose service configuration](https://docs.docker.com/reference/compose-file/services/)
  for health checks, logging and RAM/total RAM+swap limits.
- [PostgreSQL 16 resource settings](https://www.postgresql.org/docs/16/runtime-config-resource.html)
  for buffer/work-memory semantics.
- [Nginx proxy module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
  for preserved proxy paths, buffering and streaming timeouts.
- [Alibaba Lightweight Server firewall](https://www.alibabacloud.com/help/en/simple-application-server/network-security01)
  for the console firewall surface; inspect actual rules rather than assuming defaults.
- [Linux swapon manual](https://man7.org/linux/man-pages/man8/swapon.8.html)
  for portable swapfile allocation and filesystem restrictions.
