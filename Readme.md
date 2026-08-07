# Job Board API

[![CI](https://github.com/Dreyyy25/Job-Board-API-only/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Dreyyy25/Job-Board-API-only/actions/workflows/ci.yml)

A production-ready REST API for a job board platform: companies post jobs, seekers search and apply, and a Gemini-powered AI suite assists both sides — drafting job posts, importing resumes, screening applicants, and answering seekers through a guarded chat assistant.

Interactive API docs (Swagger UI at `/api/docs/`, ReDoc at `/api/redoc/`) ship with the app — run it locally with the quick start below and explore every endpoint in the browser.

## Features

### Core platform

- **Accounts & auth** — custom UUID-keyed user model (`job_seeker` / `company` roles), JWT access tokens, refresh token in an httpOnly cookie (never in a response body), Argon2 password hashing, layered rate throttling.
- **Companies** — profiles with business-stream categorization and image galleries, plus a public company directory.
- **Seekers** — profiles with education, work experience, and skill sets; per-user dashboards.
- **Jobs** — postings with search/filter/ordering, publication control, skill requirements, applications with status tracking, and public browse without an account.
- **86 documented REST endpoints** across those four modules — see [API_DOCUMENTATION.md](API_DOCUMENTATION.md) and the importable [Postman collection](Job%20Board%20API.postman_collection.json).

### AI suite (Google Gemini via LangChain)

- **Job-post writer** — companies get a structured draft from a rough description; nothing is saved until they submit it themselves.
- **Resume import** — seekers upload a PDF (or paste text) and receive a structured profile draft.
- **Applicant screening** — companies get a scored, ranked report of a post's applicants, cached until a newer application invalidates it.
- **Chat assistant** — a tool-using agent for seekers (job search, job details, profile lookup, fit comparison) with per-user tool closures, read-only data access, sanitized replies, strict per-turn/per-thread model-call budgets, and conversation history checkpointed in Postgres.
- Every billable model call is metered in an audit table; AI endpoints carry their own throttle scopes on top of the global ones.

## Tech stack

| Layer | Choice |
| --- | --- |
| Framework | Django 5.2 · Django REST Framework |
| Database | PostgreSQL (14+; CI and the Docker harness run 18) |
| Auth | SimpleJWT — bearer access token + httpOnly refresh cookie |
| AI | LangChain / LangGraph agents on Google Gemini |
| API schema | drf-spectacular (OpenAPI 3, Swagger UI, ReDoc) |
| Server | gunicorn + whitenoise (Docker), Django dev server locally |
| Tooling | uv (dependencies), ruff (lint + format), GitHub Actions (CI) |

## Quick start

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — provisions the pinned Python 3.13 automatically
- PostgreSQL 14+ running locally

### Setup

```bash
git clone https://github.com/Dreyyy25/Job-Board-API-only.git
cd Job-Board-API-only
uv sync
```

Create a `.env` file in the project root — [`.env.example`](.env.example) documents every key. A typical local `.env`:

```bash
DB_NAME=job_board
DB_USER=your_username
DB_PASSWORD=your_password
DB_HOST=localhost   # optional — this is the default
DB_PORT=5432        # optional — this is the default

SECRET_KEY=any-long-random-string-for-local-dev

# Required at startup. Any non-empty value boots the app; a real key
# (https://aistudio.google.com/apikey) is only needed to use AI endpoints.
GEMINI_API_KEY=your_gemini_api_key
```

Create the database, then migrate and run:

```bash
createdb job_board    # or: psql -c "CREATE DATABASE job_board;"
uv run python manage.py migrate
uv run python manage.py ai_checkpointer_setup   # chat-history tables (idempotent)
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

The API serves at `http://localhost:8000/api/v1/`, with interactive docs at `http://localhost:8000/api/docs/`.

### Settings modules

| Module | When used |
| --- | --- |
| `jobApp.settings.development` | Default for `manage.py` (except `test`). DEBUG on, loose CORS, no HTTPS redirect. |
| `jobApp.settings.production` | Default for `wsgi.py` / `asgi.py` and the Docker image. Strict security, fail-fast assertions. |
| `jobApp.settings.test` | Auto-picked by `manage.py test`. Fast password hasher, offline AI guards. |

### Tests

```bash
uv run python manage.py test
```

449 tests, all offline — AI features are tested against fakes; no network access or real API key needed (the placeholder `GEMINI_API_KEY` from setup must still be present). Your Postgres role needs the `CREATEDB` privilege — the runner creates and drops `test_job_board`. If a run prints `OK` but exits nonzero with a "database is being accessed by other users" error, that's Postgres teardown noise, not a failure — rerun, or use `--keepdb`.

## Docker

The repo ships a production image (multi-stage uv build, non-root user, whitenoise-served static files, gunicorn). Run it locally against Postgres 18:

```bash
cp .env.docker.example .env.docker   # local-only values, git-ignored
docker compose up --build
```

The entrypoint applies migrations and creates the chat-checkpointer tables on every boot (both idempotent), then serves on `http://localhost:8000`.

## Deployment

[DEPLOYMENT.md](DEPLOYMENT.md) is the runbook: build and push the image to a registry, run it on Render (or any container host) with the documented environment variables, point the platform's health check at `/healthz`, and bring your own Postgres (any 14+ provider works — the config takes five discrete `DB_*` values).

## API conventions

**Pagination** — list endpoints return `count` / `next` / `previous` / `results`; override page size with `?page_size=N` (max 100).

**Jobs search & filtering**

- `?search=<term>` — matches job title, description, company name, and required skill names
- `?ordering=-created_at` — sort by `created_at`, `salary_max`, `salary_min`, `deadline_date`, or `salary_rank`
- Filters: `job_type`, `company`, `salary_type`, `is_published`, `city`, `country`, `salary_min_gte`, `salary_max_lte`, `salary_floor`, `deadline_before`, `required_skill`, `business_stream`

**Auth flow** — `register`/`login` return the access token in the body and set the refresh token as an httpOnly cookie scoped to `/api/v1/accounts/`; `token/refresh/` reads only that cookie and rotates it.

## Security posture

- Argon2 password hashing (with transparent upgrade from legacy hashes on login)
- Layered throttling: anonymous/user ceilings + burst limits + scoped per-endpoint rates (register, login, token refresh, AI, chat)
- JSON-only auth endpoints (login-CSRF mitigation for the cookie-based refresh flow)
- Chat replies pass a multi-stage sanitizer (tag stripping, URL removal, HTML-escaping) before reaching clients; agent tools are closed over the requesting user and read-only
- Failed logins are security-logged with hashed identifiers — no plaintext emails in logs
- CI gate on every PR and push to protected branches: ruff lint + format, missing-migration check, OpenAPI schema validation, production deploy check, and the full test suite against Postgres 18

## Project structure

```
├── apps/
│   ├── accounts/     # Custom user model, JWT auth, refresh-cookie flow
│   ├── companies/    # Company profiles, business streams, images, public directory
│   ├── seekers/      # Seeker profiles, education, experience, skills
│   ├── jobs/         # Job posts, applications, skill requirements
│   └── ai/           # Gemini features: writer, resume import, screening, chat
├── jobApp/           # Settings (development/production/test), URLs, healthz
├── docker/           # Container entrypoint
├── config.py         # Centralized env-var access (settings import from here)
├── Dockerfile        # Production image (multi-stage uv build)
└── docker-compose.yml# Local parity harness (exact prod image + Postgres 18)
```

## Development workflow

`staging` and `main` are protected: changes land via pull request with a green CI check. Run the linters locally before pushing:

```bash
uv run ruff check .
uv run ruff format .
```
