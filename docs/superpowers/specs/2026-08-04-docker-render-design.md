# Docker Image + Render Deployment — Design

**Date:** 2026-08-04
**Status:** Approved pending user review
**Scope:** Production Docker image (multi-stage, uv-built), local docker-compose parity harness, minimal production-server code changes (gunicorn/whitenoise/`STATIC_ROOT`), one new `/healthz` endpoint, and a Render deployment doc. The user pushes the image to a registry and creates the Render services — this phase only produces the repo artifacts.

## Goal

`docker build` produces an image that serves the full API production-grade with gunicorn behind Render's proxy; `docker compose up` runs that exact image locally against Postgres 18 so it is proven before any registry push.

## Verified context

- Docker Desktop 29.2.1 + Compose v5 run locally — the image and harness are verifiable on this machine.
- `SECURE_PROXY_SSL_HEADER` is already env-driven (`config.py:60`, applied in `production.py:15`) — no code change needed for Render's TLS-terminating proxy.
- The repo has **no** gunicorn, whitenoise, or `STATIC_ROOT` anywhere (grep-verified) — a strictly-files-only image could not serve production traffic or styled admin/docs pages.
- `wsgi.py` defaults to `jobApp.settings.production`; `config.py` requires `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `GEMINI_API_KEY` at import (build-time steps need inline dummies, like CI).
- Every dependency ships prebuilt wheels for cp313 — `python:3.13-slim` needs no compiler stage.
- Render facts the design leans on: free instance types have **no pre-deploy command** (so migrations run in the entrypoint), `PORT` is injected by the platform, health-check path is configurable, free Postgres expires after 30 days (external `DB_*`-style Postgres like Neon is a drop-in because config takes five discrete vars).

## Decisions (from the Q&A)

| Decision | Choice |
|---|---|
| Scope | Files + production trio (gunicorn, whitenoise, `STATIC_ROOT`/collectstatic) — no `DATABASE_URL` parsing; user sets five `DB_*` vars on Render |
| Build shape | Multi-stage: uv builder → `python:3.13-slim` runtime |
| Health check | New `/healthz` endpoint (approved API change) |
| Migrations | Entrypoint runs `migrate` + `ai_checkpointer_setup` on start (idempotent; free tier has no pre-deploy hook) |
| Registry / Render setup | User-owned; this phase documents, never pushes |

## 1. Supporting code changes

- `uv add gunicorn whitenoise` (regular deps — the image needs them; dev group stays test-only).
- `jobApp/settings/base.py`: `STATIC_ROOT = BASE_DIR / 'staticfiles'`; insert `whitenoise.middleware.WhiteNoiseMiddleware` immediately after `django.middleware.security.SecurityMiddleware` in `MIDDLEWARE`.
- `jobApp/settings/production.py`: define the full `STORAGES` dict — `default` → `django.core.files.storage.FileSystemStorage` (must be stated explicitly; a partial `STORAGES` override would silently drop file-upload storage) and `staticfiles` → `whitenoise.storage.CompressedManifestStaticFilesStorage`. Production-only, so tests never require a collectstatic step.
- `/healthz`: a **plain Django view** (not DRF — no auth/throttle machinery, and drf-spectacular never sees it, so the OpenAPI schema is untouched by construction). `GET` returns `{"status": "ok"}` 200 after a `SELECT 1` on the default connection; DB failure returns `{"status": "error"}` 503. Lives in a new `jobApp/views.py`, routed in `jobApp/urls.py` at `healthz` (outside `/api/v1/`). Tests (200 path; DB-failure path via patching) live in a new `jobApp/tests.py` — plan must verify the test runner discovers it.

## 2. Dockerfile (multi-stage)

- **Builder:** `python:3.13-slim` + pinned `uv` binary copied from `ghcr.io/astral-sh/uv` (pin the tag to the locally-installed uv's minor version — plan verifies with `uv --version`). Copy `pyproject.toml` + `uv.lock` first for layer caching; `UV_COMPILE_BYTECODE=1 uv sync --locked --no-dev` into the project venv.
- **Runtime:** `python:3.13-slim`; non-root user; copy venv + source; `PYTHONUNBUFFERED=1`, `PATH` includes the venv. `collectstatic --noinput` runs **at build time** with inline single-`RUN` dummy env (never persisted as `ENV`/`ARG` layers).
- **Entrypoint** `docker/entrypoint.sh`: `set -e`; `migrate --noinput`; `ai_checkpointer_setup`; `exec gunicorn jobApp.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 120 --access-logfile - --error-logfile -`. The 120 s timeout is load-bearing: the AI chat turn may legitimately run up to its 90 s deadline.
- **Windows guard:** `.gitattributes` rule `*.sh text eol=lf` — a CRLF checkout on this machine would break the shebang inside the Linux image.
- `.dockerignore`: `.git`, `.venv`, `.env*` (secrets must never enter build context; `.env.docker.example` is explicitly re-included), `__pycache__`, `.superpowers`, `staticfiles`, `docs`, workspace/tooling files. Plan enumerates the exact list.

## 3. docker-compose.yml (local parity harness — Render ignores it)

- `db`: `postgres:18`, named volume, `pg_isready` healthcheck.
- `web`: `build: .`, `depends_on: db: condition: service_healthy`, `ports: 8000:8000`, `env_file: .env.docker`.
- `.env.docker` is git-ignored (new `.gitignore` entry); committed `.env.docker.example` documents local values: ≥50-char dummy `SECRET_KEY`, `DEBUG=false`, `ALLOWED_HOSTS=localhost,127.0.0.1`, `DB_HOST=db`, `DB_PORT=5432`, matching `POSTGRES_*` values, `GEMINI_API_KEY` placeholder (real key only if exercising AI endpoints locally), **no** `SECURE_SSL_REDIRECT` (local is http).
- Compose exists to run the production image end-to-end — entrypoint, migrations, checkpointer setup, gunicorn, whitenoise — before any push.

## 4. DEPLOYMENT.md (repo root, linked from CLAUDE.md)

Covers: building/tagging the image locally (exact commands; push itself is user-owned), creating a Render web service from an existing registry image, the full env-var table (`SECRET_KEY`, `DEBUG=false`, `ALLOWED_HOSTS=<app>.onrender.com`, `CSRF_TRUSTED_ORIGINS`/`CORS_ALLOWED_ORIGINS` as https origins, `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO=https`, `SECURE_SSL_REDIRECT=true`, `SECURE_HSTS_SECONDS=31536000`, five `DB_*` vars, `GEMINI_API_KEY`, optional `ADMIN_URL`/`WEB_CONCURRENCY`), health-check path `/healthz`, `PORT` injected by Render, and free-tier realities: idle spin-down (cold first request), 30-day free-Postgres expiry with external-Postgres alternative, checkpointer tables created in the same DB by the entrypoint, and how to create a superuser without a paid shell (run `createsuperuser` locally with `DB_*` pointed at the remote DB).

## 5. Verification

1. Full test suite green (404 + new healthz tests) and `spectacular --validate` byte-identical schema (healthz is invisible to DRF by construction — assert the endpoint count is unchanged).
2. `docker build` succeeds; image runs as non-root; `docker compose up` shows migrate → checkpointer setup → gunicorn boot.
3. Live smoke against the container: `/healthz` 200; register + login round-trip (DB writes, JWT, refresh cookie); one admin static asset 200 via whitenoise (manifest-hashed name); `/api/docs/` 200.
4. `check --deploy` still zero warnings; CI (`--locked`) green on the PR.

## 6. Rollout

Branch `feat/docker-render` (created off staging @ `41fbc4f`). Spec + plan committed; plan receives an adversarial workflow review before execution (ultracode); SDD subagent execution with per-task reviews; PR → staging through the live CI gate; user merges; promotion PR to main; user builds/pushes the image from main per DEPLOYMENT.md.

## Out of scope

- Registry push, Render account/service/DB creation (user-owned).
- `DATABASE_URL` parsing (declined — five `DB_*` vars on the dashboard).
- Email/password reset, AWS deployment, CD automation, Dependabot-update triage (seven update branches appeared 2026-08-04; separate decisions — the Django 6 major bump in particular deserves its own phase).
