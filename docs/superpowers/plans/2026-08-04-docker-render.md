# Docker Image + Render Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A production Docker image (gunicorn + whitenoise, multi-stage uv build) proven locally via docker-compose, plus the Render deployment doc — registry push and Render setup stay user-owned.

**Architecture:** Minimal production-server code lands first (gunicorn/whitenoise deps, `STATIC_ROOT`, production `STORAGES`, `/healthz`); the Dockerfile builds a slim non-root image with static files collected at build time and an entrypoint that migrates + sets up the AI checkpointer before serving; compose runs that exact image against Postgres 18 for pre-push verification.

**Tech Stack:** Docker multi-stage (`python:3.13-slim` + pinned `uv` 0.10.9), gunicorn (WSGI), whitenoise (compressed-manifest static), docker-compose, Postgres 18.

**Spec:** `docs/superpowers/specs/2026-08-04-docker-render-design.md` (approved).

## Global Constraints

- Branch `feat/docker-render` (exists, off `staging` @ `41fbc4f`; spec committed as `36818c3`).
- Conventional commits. **Never add a `Co-Authored-By` trailer or any attribution footer to commits, and PR bodies carry no attribution footer of any kind.**
- Public repo: no personal emails or organization names beyond the `Dreyyy25` GitHub identity anywhere.
- All dependency changes via `uv` — never pip. `uv.lock` changes ride the same commit as their `pyproject.toml` change (CI runs `uv sync --locked`).
- New/changed `.py` files must pass `uv run ruff check .` and `uv run ruff format --check .` (config is pinned in `pyproject.toml` — quote-preserving, line-length 120).
- The OpenAPI schema must be byte-unaffected: `/healthz` is a plain Django view, never a DRF view.
- No real secret ever appears in a committed file or an image layer: build-time env values are inline-per-`RUN` dummies; `.env.docker` is git-ignored.
- Full test suite green at every task end (`uv run python manage.py test --noinput`; 404 tests before this plan, 407 after Task 1). Known artifact: occasional exit 1 AFTER printing `OK` is the documented autovacuum teardown race, not a failure.
- Never run `ai_smoke` anywhere; `ai_checkpointer_setup` runs only inside containers (entrypoint), never against the dev DB from these tasks.

## Verified facts (measured 2026-08-04, don't re-derive)

- Local uv is `0.10.9` → builder copies from `ghcr.io/astral-sh/uv:0.10.9`.
- Docker Desktop 29.2.1 / Compose v5 running locally.
- `base.py` `MIDDLEWARE` starts at line 159 with `SecurityMiddleware` first; `STATIC_URL = 'static/'` at line 260; no `STATIC_ROOT`, no whitenoise, no gunicorn anywhere.
- `production.py` hard-asserts `DEBUG=False`, ≥50-char `SECRET_KEY`, non-empty `ALLOWED_HOSTS` at import; `manage.py` auto-selects `development` settings unless testing, so **every** container-side Django command needs `DJANGO_SETTINGS_MODULE=jobApp.settings.production` (set as image `ENV`).
- No test asserts `MIDDLEWARE` contents or `STORAGES` (grep-verified) — the whitenoise insertion breaks nothing.
- `.gitattributes` does not exist yet. `.gitignore` has no `staticfiles/` or `.env.docker` entries yet.
- The `postgres:18` Docker image moved its data mount: named volumes mount at `/var/lib/postgresql` (not the old `/var/lib/postgresql/data`). The implementer must verify persistence in Task 3 and adjust only if the container logs prove otherwise.
- Every dependency (incl. gunicorn/whitenoise once added) ships prebuilt cp313 wheels — no compiler needed in either stage.

---

### Task 1: Production server support + /healthz (TDD)

**Files:**
- Modify: `pyproject.toml` + `uv.lock` (via `uv add gunicorn whitenoise`)
- Modify: `jobApp/settings/base.py` (MIDDLEWARE line ~160; below `STATIC_URL` line ~260)
- Modify: `jobApp/settings/production.py` (add `STORAGES`)
- Create: `jobApp/views.py`
- Modify: `jobApp/urls.py`
- Test: `jobApp/tests.py` (new file)

**Interfaces:**
- Produces: `GET /healthz` (exact path, no trailing slash) returning `{"status": "ok"}` 200 / `{"status": "error"}` 503 — Task 4's DEPLOYMENT.md and Task 3's smoke test depend on this path. `STATIC_ROOT = BASE_DIR / 'staticfiles'` — Task 2's Dockerfile collectstatic and `.dockerignore` depend on the directory name `staticfiles`. Gunicorn dep — Task 2's entrypoint runs `gunicorn jobApp.wsgi:application`.

- [ ] **Step 1: Write the failing tests**

Create `jobApp/tests.py`:

```python
"""Project-level tests: the /healthz endpoint and its schema invisibility."""

import json
from unittest.mock import patch

from django.test import TestCase


class HealthzTests(TestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_healthz_db_failure_returns_503(self):
        with patch('jobApp.views.connection') as mock_conn:
            mock_conn.cursor.side_effect = Exception('db down')
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'error'})

    def test_healthz_is_not_in_openapi_schema(self):
        response = self.client.get('/api/schema/?format=json')
        self.assertEqual(response.status_code, 200)
        schema = json.loads(response.content)
        self.assertNotIn('/healthz', schema['paths'])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python manage.py test jobApp -v 2`
Expected red state (verified empirically during plan review): `test_healthz_returns_ok` **FAILS** on the 404 assertion (route absent); `test_healthz_db_failure_returns_503` **ERRORS** with `AttributeError: module 'jobApp' has no attribute 'views'` (the mock patch target resolves at test time and `jobApp/views.py` doesn't exist yet — an ERROR here is the correct red, not a problem); the schema test PASSES already (it guards the invariant going forward). Only if Django reports "no tests found" is the discovery assumption wrong — stop and report instead of moving tests into an app.

- [ ] **Step 3: Add dependencies**

```
uv add gunicorn whitenoise
```

Both land in `[project] dependencies` in `pyproject.toml` with `uv.lock` updated (regular deps — the image imports them; dev group stays test-only).

- [ ] **Step 4: Settings changes**

In `jobApp/settings/base.py`, insert whitenoise as the SECOND middleware entry (directly after `SecurityMiddleware`, before `CorsMiddleware`):

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    ...  # rest unchanged
]
```

Below `STATIC_URL = 'static/'` add:

```python
# Collected by `manage.py collectstatic` (Docker build); served by whitenoise.
STATIC_ROOT = BASE_DIR / 'staticfiles'
```

In `jobApp/settings/production.py` (after the cookie block, before the asserts) add the FULL storages dict — `STORAGES` is replaced wholesale, not merged, so `default` must be restated to keep the framework's default file storage configured (no feature currently writes files, but a silently-missing `default` backend is a trap for whoever adds one):

```python
# Whitenoise serves hashed+compressed static files; `default` must be
# restated because STORAGES is replaced wholesale, not merged.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
```

- [ ] **Step 5: The healthz view and route**

Create `jobApp/views.py`:

```python
"""Project-level plain-Django views (not DRF): infrastructure endpoints."""

from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Health probe: cheap DB ping, no auth/throttling, invisible to the
    OpenAPI schema (plain Django view — drf-spectacular never sees it)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})
```

In `jobApp/urls.py`: add `from jobApp.views import healthz` below the existing imports, and add `path('healthz', healthz, name='healthz'),` as the LAST entry in `urlpatterns` (exact path, no trailing slash — Render probes `/healthz` literally).

- [ ] **Step 6: Run the new tests, then the full suite**

Run: `uv run python manage.py test jobApp -v 2` → 3/3 PASS.
Run: `uv run python manage.py test --noinput` → 407 tests, OK. Expected noise: a whitenoise `UserWarning: No directory at: ...staticfiles` per test process — test settings run `DEBUG=False` with no collected staticfiles dir on disk, so whitenoise warns and serves nothing; that is expected, not a regression (it appears in CI too).
Run: `uv run python manage.py spectacular --validate --fail-on-warn > $null` → exit 0.
Run: `uv run ruff check .` and `uv run ruff format --check .` → both exit 0 (format the new files with `uv run ruff format jobApp/` first if needed).

- [ ] **Step 7: Commit in two pieces**

```bash
git add pyproject.toml uv.lock jobApp/settings/base.py jobApp/settings/production.py
git commit -m "feat: production static-file and WSGI server support (whitenoise, gunicorn)"
git add jobApp/views.py jobApp/urls.py jobApp/tests.py
git commit -m "feat: healthz endpoint for container and platform health checks"
```

---

### Task 2: The production image

**Files:**
- Create: `Dockerfile`
- Create: `docker/entrypoint.sh`
- Create: `.dockerignore`
- Create: `.gitattributes`
- Modify: `.gitignore` (append two entries)

**Interfaces:**
- Consumes: `STATIC_ROOT` name `staticfiles`, gunicorn dep, production settings asserts (Task 1).
- Produces: image tag `jobboard-api:local` listening on `${PORT:-8000}`, entrypoint `migrate → ai_checkpointer_setup → gunicorn` — Task 3's compose and Task 4's docs rely on this exact behavior.

- [ ] **Step 1: Create `.gitattributes`** (repo root; new file)

```
# Shell scripts must stay LF — a CRLF checkout on Windows breaks the
# shebang inside the Linux image.
*.sh text eol=lf
```

- [ ] **Step 2: Append to `.gitignore`** (under the `# Django` section)

```
staticfiles/

# Local docker-compose env (copy from .env.docker.example)
.env.docker
```

- [ ] **Step 3: Create `docker/entrypoint.sh`** (LF endings — verify with `git ls-files --eol docker/entrypoint.sh` after staging)

```sh
#!/bin/sh
# Container start: apply DB state, then serve. Both steps are idempotent.
# They run here (not a deploy hook) because Render's free instance type
# has no pre-deploy command.
set -e

python manage.py migrate --noinput
python manage.py ai_checkpointer_setup

# --timeout 120 is load-bearing: an AI chat turn may legitimately run up
# to its 90 s deadline; a shorter gunicorn timeout would kill the worker.
exec gunicorn jobApp.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
```

Immediately after creating BOTH `.gitattributes` (Step 1) and this file, stage them and verify the line endings BEFORE anything builds an image from the working tree:

```
git add .gitattributes docker/entrypoint.sh
git ls-files --eol docker/entrypoint.sh
```

Expected: `i/lf w/lf`. If it shows `w/crlf`: the gitattribute canNOT rewrite an existing working-tree file (it applies only at add/checkout — verified empirically during plan review), so fix the WORKING TREE: delete `docker/entrypoint.sh` and run `git checkout -- docker/entrypoint.sh` to re-smudge it from the (already LF-normalized) index, then re-verify. Docker copies the working tree, so a CRLF working copy would bake a broken `#!/bin/sh\r` shebang into the image and fail only at compose boot, two steps away from the cause.

- [ ] **Step 4: Create `.dockerignore`**

```
.git
.github
.claude
.superpowers
.ruff_cache
.idea
.vscode
.venv
**/.venv
**/.env*
**/__pycache__
**/*.py[cod]
**/*.log
.python-version
.DS_Store
Thumbs.db
db.sqlite3
media/
staticfiles/
docs/
*.md
Job Board API.postman_collection.json
Dockerfile
docker-compose.yml
.dockerignore
.gitignore
.gitattributes
```

Two load-bearing subtleties (adversarial review both caught real leaks here):
- `.dockerignore` patterns are **context-root-relative** (Go `filepath.Match`), unlike `.gitignore` — a bare `.env` entry excludes only the root-level file. The `**/` forms are what exclude nested copies.
- `.claude/` MUST be excluded: it can contain git worktrees (e.g. `.claude/worktrees/<name>/`) holding a **live copy of the real `.env`** plus a 130+ MB `.venv`. They are invisible to `git status` (excluded via `.git/info/exclude`) but Docker does not read git excludes — without this entry, `COPY . .` bakes real secrets into an image layer.

(`uv.lock`/`pyproject.toml` are NOT ignored — the build needs them. `**/.env*` also drops `.env.docker.example` from the context; nothing in the image needs it.)

- [ ] **Step 5: Create `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1

# --- Builder: resolve the locked dependency set into a venv ---------------
FROM python:3.13-slim AS builder

# Pin to the uv version this repo develops with (uv 0.10.9 locally).
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Lockfile-only layer: dependency changes bust this cache, code changes don't.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# --- Runtime: slim, non-root, no build tooling ----------------------------
FROM python:3.13-slim

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=jobApp.settings.production

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY . .

# Build-time collectstatic under production settings (manifest + compression).
# The env values are single-RUN dummies: they satisfy config.py's import-time
# requirements and production.py's asserts, and never persist in any layer.
# Everything under /app stays ROOT-owned deliberately: the app never writes
# to disk at runtime (no media storage exists; logging is stderr; the
# whitenoise manifest is read-only after build), so the gunicorn user gets
# read-only code — least privilege, no code-persistence primitive.
RUN chmod +x docker/entrypoint.sh && \
    SECRET_KEY=build-only-dummy-secret-key-for-collectstatic-0123456789abcdefgh \
    DB_NAME=build DB_USER=build DB_PASSWORD=build \
    GEMINI_API_KEY=build ALLOWED_HOSTS=build.invalid \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
```

- [ ] **Step 6: Build and inspect**

Run the `docker run` line in **Git Bash**, not PowerShell — PowerShell 5.1 mangles the nested quotes (empirically verified during plan review):

```
docker build -t jobboard-api:local .
docker image ls jobboard-api:local
docker run --rm --entrypoint sh jobboard-api:local -c "whoami && ls staticfiles/admin/css | head -5 && python -c 'import gunicorn, whitenoise; print(\"deps ok\")'"
```

Expected: build succeeds; `whoami` prints `app` (non-root); `staticfiles/admin/css` lists both original and hash-named files (manifest storage collected); `deps ok`. The container run needs no DB — it only execs a shell, not the entrypoint.

- [ ] **Step 7: Verify nothing leaked into the image — config, filesystem, or permissions**

(Git Bash for the `docker run` lines.)

```
docker history --no-trunc jobboard-api:local | grep SECRET_KEY
docker inspect jobboard-api:local --format "{{.Config.Env}}"
docker run --rm --entrypoint sh jobboard-api:local -c "find . -name '.env*' -o -name '.claude' -o -name '.ruff_cache'"
docker run --rm --entrypoint sh jobboard-api:local -c "touch /app/probe 2>&1; true"
```

Expected: `docker history` shows the dummy only inside the single collectstatic `RUN` line (build args in RUN lines are visible in history — fine, they are labeled dummies); `inspect` Env contains only `PATH`, `PYTHONUNBUFFERED`, `DJANGO_SETTINGS_MODULE`, and base-image vars — **no** SECRET_KEY/DB_*/GEMINI values; the `find` prints **nothing** (no env file, no `.claude`, no cache dirs made it into any layer — this is the check that would have caught a worktree `.env` leak); the `touch` prints `Permission denied` (runtime user cannot modify /app).

- [ ] **Step 8: Commit**

```bash
git add .gitattributes .gitignore .dockerignore docker/entrypoint.sh Dockerfile
git commit -m "feat: production Docker image (multi-stage uv build, non-root, whitenoise static)"
```

(The LF check already happened in Step 3, before the build — nothing to re-verify here.)

---

### Task 3: Compose harness + live smoke test

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.docker.example`

**Interfaces:**
- Consumes: image behavior from Task 2 (entrypoint, port 8000, env names from `config.py`), `/healthz` from Task 1.
- Produces: the verified local-run procedure Task 4 documents (`docker compose up --build` + `.env.docker` copy step).

- [ ] **Step 1: Create `.env.docker.example`**

```
# Local docker-compose env. Copy to .env.docker (git-ignored) and adjust.
# Values here are local-only dummies — never production secrets.

SECRET_KEY=local-docker-only-dummy-secret-key-0123456789abcdefghijklmnopqrstuv
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1

# Matches the db service in docker-compose.yml.
DB_NAME=job_board
DB_USER=jobboard
DB_PASSWORD=jobboard
DB_HOST=db
DB_PORT=5432

# Any non-empty value boots; a real key is needed only to exercise AI endpoints.
GEMINI_API_KEY=local-dummy

CORS_ALLOWED_ORIGINS=http://localhost:3000
CSRF_TRUSTED_ORIGINS=http://localhost:8000

# Local is plain http — the image runs production settings, which default
# SSL redirect ON unless this is explicitly set off.
SECURE_SSL_REDIRECT=false
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
# Local parity harness: runs the EXACT production image against Postgres 18.
# Render never reads this file. Copy .env.docker.example -> .env.docker first.
services:
  db:
    image: postgres:18
    environment:
      POSTGRES_USER: jobboard
      POSTGRES_PASSWORD: jobboard
      POSTGRES_DB: job_board
    volumes:
      # postgres:18 images mount data at /var/lib/postgresql (not .../data).
      - pgdata:/var/lib/postgresql
    healthcheck:
      # -h 127.0.0.1 forces the check onto TCP: during first-boot initdb the
      # image runs a TEMPORARY socket-only server, and a socket pg_isready
      # passes while db:5432 still refuses connections — releasing web into a
      # crash. The temp server never listens on TCP, so this form only goes
      # healthy once the real server is up. (Adversarial review, verified
      # against the postgres image entrypoint source.)
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U jobboard -d job_board"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s

  web:
    build: .
    env_file: .env.docker
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy

volumes:
  pgdata:
```

- [ ] **Step 3: Boot the harness**

```
Copy-Item .env.docker.example .env.docker
docker compose up --build -d
docker compose logs web
```

Expected in `web` logs, in order: migration output ("Applying ..." or "No migrations to apply"), the checkpointer setup output, then gunicorn's "Listening at: http://0.0.0.0:8000". Also `docker compose logs db` must NOT warn about an unused/misplaced data volume — if it does, fix the volume mount path per the actual postgres:18 image docs and note the correction in the report.

- [ ] **Step 4: Live smoke against the container**

(Use `curl.exe` explicitly — in PowerShell, bare `curl` aliases to `Invoke-WebRequest` and rejects these flags.)

```
curl.exe -fsS http://localhost:8000/healthz
curl.exe -fsS -o NUL -w "%{http_code}" http://localhost:8000/static/admin/css/base.css
curl.exe -fsS -o NUL -w "%{http_code}" http://localhost:8000/api/docs/
```

Expected: `{"status": "ok"}`, `200`, `200`. Then a register + login round-trip. The payload below is **authoritative** (verified against the live serializers during plan review — do NOT defer to `API_DOCUMENTATION.md`, whose register examples are known-stale: its example password fails `CommonPasswordValidator`, and it still shows `tokens.refresh` in the response body, which register no longer returns since the refresh token moved to the httpOnly cookie):

```
curl.exe -sS -w "\n%{http_code}" -X POST http://localhost:8000/api/v1/accounts/register/ -H "Content-Type: application/json" -d "{\"email\":\"smoke@example.com\",\"password\":\"SmokeTest12345\",\"user_type\":\"job_seeker\"}"
curl.exe -sS -i -X POST http://localhost:8000/api/v1/accounts/login/ -H "Content-Type: application/json" -d "{\"email\":\"smoke@example.com\",\"password\":\"SmokeTest12345\"}"
```

(No `-f`: on a 4xx, `-f` discards the response body — exactly the field-error listing you need to diagnose. Double-quoted JSON with escaped quotes — single-quoted strings don't pass through to curl.exe intact from PowerShell. On a rerun against a kept volume, register 400s with "already registered" — that's the volume persisting, not a failure; skip to login.)

Expected: register 201 with a `profile` payload and `tokens.access` (and NO `tokens.refresh` in the body); login 200 whose headers include `Set-Cookie: refresh_token=...; HttpOnly; Path=/api/v1/accounts/`.

- [ ] **Step 5: Persistence check + teardown**

```
docker compose restart web
curl.exe -fsS http://localhost:8000/healthz
docker compose down
```

Expected: healthz still ok after restart (migrations no-op on second boot proves idempotence). `down` (without `-v`) keeps the pgdata volume.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.docker.example
git commit -m "feat: docker-compose parity harness for local image verification"
```

---

### Task 4: DEPLOYMENT.md + CLAUDE.md + stale-doc fixes

**Files:**
- Create: `DEPLOYMENT.md` (repo root)
- Modify: `CLAUDE.md` (insert new section between `## CI and git workflow` and `## Architecture`)
- Modify: `API_DOCUMENTATION.md` (two stale auth-example spots only)

**Interfaces:**
- Consumes: image/entrypoint behavior (Task 2), compose procedure (Task 3), `/healthz` (Task 1).

- [ ] **Step 1: Create `DEPLOYMENT.md`**

```markdown
# Deploying the Job Board API (Docker → Render)

The repo ships a production Docker image. You build and push it to a registry;
Render runs it as a web service from that image. Nothing in this repo pushes
images or talks to Render.

## 1. Build and verify locally

    docker compose up --build          # copy .env.docker.example -> .env.docker first
    curl http://localhost:8000/healthz # {"status": "ok"}

The compose harness runs the exact production image (gunicorn, whitenoise,
migrations + AI-checkpointer setup in the entrypoint) against Postgres 18.

## 2. Tag and push (user-owned)

    docker build -t <registry>/<namespace>/jobboard-api:<tag> .
    docker push <registry>/<namespace>/jobboard-api:<tag>

Build from a clean checkout of `main` so the image matches a released state.

## 3. Render web service

Create a **Web Service → Existing image** pointing at the pushed image.

- **Health check path:** `/healthz`
- **Port:** Render injects `PORT` automatically; the entrypoint binds it.
- The entrypoint applies migrations and creates the LangGraph checkpointer
  tables on every boot (both idempotent) — required because free instance
  types have no pre-deploy command.

### Environment variables

| Variable | Value |
|---|---|
| `SECRET_KEY` | ≥50 random chars — `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DEBUG` | `false` |
| `ALLOWED_HOSTS` | `<app>.onrender.com` (plus any custom domain) |
| `CSRF_TRUSTED_ORIGINS` | `https://<app>.onrender.com` (comma-separated if more) |
| `CORS_ALLOWED_ORIGINS` | your frontend origin(s), e.g. `https://<frontend>.onrender.com` |
| `SECURE_PROXY_SSL_HEADER` | `HTTP_X_FORWARDED_PROTO=https` (Render terminates TLS at its proxy) |
| `SECURE_SSL_REDIRECT` | `true` |
| `SECURE_HSTS_SECONDS` | `31536000` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | from your Postgres provider's connection info |
| `GEMINI_API_KEY` | real key (https://aistudio.google.com/apikey) |
| `ADMIN_URL` | optional custom admin path, e.g. `manage-7f3k/` |
| `WEB_CONCURRENCY` | optional; gunicorn workers, default 2 |

## 4. Postgres

Any Postgres 14+ reachable from Render works — the app takes five discrete
`DB_*` vars, so Render Postgres and external providers (Neon, Supabase, ...)
are interchangeable. Free-tier realities:

- **Render free Postgres expires after 30 days.** External free tiers vary:
  Neon's doesn't expire; some others (e.g. Supabase) pause idle projects
  after about a week until manually restored — check your provider's policy
  against an API that will sit idle.
- The AI chat checkpointer stores its tables in the **same** database;
  no extra configuration.

## 5. Known free-tier limitations

- Free web services spin down when idle; the first request after sleep is
  slow (cold start + migrations re-check).
- **No file uploads are stored.** Company images are external URLs
  (`CompanyImages.image_url`), and the AI resume-import PDF is parsed in
  memory and discarded — nothing writes to the container's disk, so there
  is nothing to lose on restart. Object storage only becomes relevant if a
  real upload feature is ever added.
- No shell on free instances. To create a superuser, run it from your
  machine against the remote DB:

      # .env temporarily pointed at the remote DB_* values
      uv run python manage.py createsuperuser

  Use your Postgres provider's **external** connection hostname here — the
  internal hostname the web service uses does not resolve from outside the
  platform.

## 6. Verifying a deploy

1. `https://<app>.onrender.com/healthz` → `{"status": "ok"}`
2. `https://<app>.onrender.com/static/admin/css/base.css` → 200
   (whitenoise static serving OK — note `/api/docs/` proves nothing about
   static files; Swagger UI loads from a CDN).
3. `https://<app>.onrender.com/api/docs/` renders (app + schema OK).
4. Register + login round-trip against `/api/v1/accounts/`.
```

- [ ] **Step 2: Insert the CLAUDE.md section**

Between the end of `## CI and git workflow` (after the "...prune locally with `git fetch --prune`." paragraph) and `## Architecture`:

```markdown
## Docker and deployment

`Dockerfile` builds the production image: multi-stage uv → `python:3.13-slim`, non-root user, whitenoise-served static files collected at build time under production settings with inline dummy env. The entrypoint (`docker/entrypoint.sh`) runs `migrate` + `ai_checkpointer_setup` (both idempotent — Render's free tier has no pre-deploy hook) and then gunicorn with `--timeout 120`, which must stay above the AI chat's 90 s deadline. `docker compose up --build` runs that exact image against Postgres 18 locally — copy `.env.docker.example` to `.env.docker` (git-ignored) first. `GET /healthz` is a plain-Django health endpoint (cheap DB ping, no DRF, deliberately invisible to the OpenAPI schema). Render deployment — env table, health-check path, free-tier caveats — is documented in `DEPLOYMENT.md`; registry push and Render service setup are user-owned. Shell scripts are forced to LF via `.gitattributes` — don't commit `.sh` files with CRLF.
```

- [ ] **Step 3: Fix the two known-stale spots in API_DOCUMENTATION.md**

Plan review verified these against the live code — both predate the cookie-auth hardening:

1. The register example's password `password123` fails `CommonPasswordValidator` — replace it (in the register request AND any login examples that reuse it) with `SmokeTest12345` (verified accepted).
2. The register response example still shows `tokens.refresh` in the body — remove it; register/login return only `tokens.access` in the body, with the refresh token in the httpOnly cookie. If the response example already documents the cookie, leave that part as is.

Change nothing else in that file.

- [ ] **Step 4: Verify docs claims and commit**

Re-read the insertions against the actual Task 1–3 artifacts (paths, env names, port, timeout, health path). Then:

```bash
git add DEPLOYMENT.md CLAUDE.md API_DOCUMENTATION.md
git commit -m "docs: Render deployment guide, Docker workflow notes, stale auth examples fixed"
```

---

### Task 5: Full gate + PR

**Files:** none (verification + git/GitHub operations).

**Interfaces:**
- Consumes: everything; the PR must show a green `ci` check before handoff.

- [ ] **Step 1: Run the complete local gate**

```
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn > $null
uv run python manage.py test --noinput
```

Expected: all exit 0; 407 tests OK. Also re-run the deploy check with the CI-style env (see `.github/workflows/ci.yml` deploy-check step for the exact var set) — expected: zero issues.

- [ ] **Step 2: Push and open the PR**

```
git push -u origin feat/docker-render
```

PR: base `staging`, title `Docker image and Render deployment support`, body (verbatim, no attribution footer):

```markdown
## What this adds

- **Production Docker image** — multi-stage uv build on python:3.13-slim, non-root user, whitenoise-served static files collected at build time, entrypoint running `migrate` + `ai_checkpointer_setup` (idempotent) before gunicorn (`--timeout 120`, above the AI chat's 90 s deadline).
- **docker-compose parity harness** — runs the exact production image against Postgres 18 locally (`.env.docker` git-ignored, example committed); verified end-to-end: healthz, admin static via whitenoise, register/login round-trip, restart idempotence.
- **Production server support** — gunicorn + whitenoise as regular deps, `STATIC_ROOT`, production `STORAGES` (default restated + compressed-manifest static).
- **`GET /healthz`** — plain-Django health endpoint (cheap DB ping, 200/503), used as Render's health-check path; deliberately invisible to the OpenAPI schema, with tests locking both behaviors.
- **DEPLOYMENT.md** — Render setup: env table, image build/tag commands, free-tier caveats (idle spin-down, 30-day free Postgres, no shell). Registry push and Render service creation stay manual. Also fixes two stale auth examples in API_DOCUMENTATION.md (weak example password, refresh token no longer in response body).

## Notes

- The OpenAPI schema is unchanged (healthz is not a DRF view; a test asserts it stays out).
- No secrets in any committed file or image layer — build-time env values are labeled single-RUN dummies.
- Suite grows 404 → 407 tests.
```

Create with `gh pr create --base staging --head feat/docker-render --title ... --body-file <file>` (write the body to the SDD workspace directory).

- [ ] **Step 3: Watch CI**

```
gh pr checks --watch --fail-fast
```

Expected: `ci` green. If red: diagnose via `gh run view <id> --log-failed`, fix locally, verify the equivalent local command, commit conventionally, push, re-watch. Never weaken a gate to pass it.

- [ ] **Step 4: Hand off**

Report to the user: PR number/URL, green check, and that merging (staging, then the promotion PR to main) is theirs. Do not merge.

---

## Out of scope (from the spec — do not add)

- Registry push, Render account/service/DB creation.
- `DATABASE_URL` parsing; media/object storage; email/password reset; CD automation.
- Dependabot-update triage (seven branches opened 2026-08-04 — separate decisions).
