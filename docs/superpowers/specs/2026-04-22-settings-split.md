# Split Settings — dev / prod / test Spec

**Date:** 2026-04-22
**Status:** Draft
**Owner:** Dreyyy25
**Builds on:** `2026-04-17-security-hardening.md` (Tier 0) and `2026-04-17-api-usability-tier-1.md` (Tier 1). Assumes all that work is merged.

## Goal

Replace the single `jobApp/settings.py` file with a settings package (`jobApp/settings/{base,development,production,test}.py`) so each environment has explicit, testable defaults, while keeping the existing `config.py` env-var layer as the single source of secret/runtime config.

## Motivation

The current single-file settings has two awkward traits:

1. **Dev defaults leak into prod by default.** `SECURE_SSL_REDIRECT` is env-driven with `default=False`; an operator who forgets to set `SECURE_SSL_REDIRECT=true` in production ships with redirect disabled. The split makes the default depend on the settings module chosen, not on env-var presence.
2. **Env-var coupling is implicit.** You have to read `config.py` + `settings.py` to know which settings are dev-shaped vs prod-shaped. Explicit `development.py` / `production.py` files make that reading trivial.

## Non-Goals

- Adding `django-debug-toolbar`, Sentry, structured logging, health-check endpoint (each is its own follow-up).
- Replacing `config.py` with `django-environ` or similar (scope creep; current env-reader works).
- Introducing `.env.dev` / `.env.prod` file variants (a single `.env` + `DJANGO_SETTINGS_MODULE` env var is sufficient).
- Changing any business logic, URL routing, models, serializers, or permissions.

## Current-State Summary

- `jobApp/settings.py` (~220 lines) — one file doing everything. Imports from `config.py`.
- `jobApp/urls.py`, `jobApp/wsgi.py`, `jobApp/asgi.py`, `manage.py` all reference `jobApp.settings` via Django's default `DJANGO_SETTINGS_MODULE` mechanism.
- `config.py` exposes env-driven constants: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `ADMIN_URL`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ALL_ORIGINS`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_*`, `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `DB_*`.
- Tests run via Django's default runner (`manage.py test`) against a real Postgres test database.

## Requirements

### R1 — Settings package layout

**R1.1** `jobApp/settings.py` is removed (deleted as a file).
**R1.2** `jobApp/settings/` is a Python package (directory with `__init__.py`).
**R1.3** The package contains:
- `jobApp/settings/__init__.py` — empty (or at most a one-line docstring).
- `jobApp/settings/base.py` — all content that is identical across environments.
- `jobApp/settings/development.py` — `from .base import *` plus dev overrides.
- `jobApp/settings/production.py` — `from .base import *` plus prod overrides + assertions.
- `jobApp/settings/test.py` — `from .base import *` plus test-speed overrides.

**R1.4** `DJANGO_SETTINGS_MODULE` is picked via env var with per-entrypoint defaults:
- `manage.py` default → `jobApp.settings.development`
- `wsgi.py` default → `jobApp.settings.production`
- `asgi.py` default → `jobApp.settings.production`

All three use `os.environ.setdefault('DJANGO_SETTINGS_MODULE', ...)` so an explicit env var always wins.

### R2 — Contents of `base.py`

**R2.1** `base.py` retains everything from the current `jobApp/settings.py` **except** the per-environment items moved in R3–R5. This includes (non-exhaustive):
- `BASE_DIR`, `from config import ...` tuple, `SECRET_KEY` / DB_* assignment
- `INSTALLED_APPS`, `MIDDLEWARE`, `ROOT_URLCONF`, `WSGI_APPLICATION`
- `TEMPLATES`, `DATABASES`, `AUTH_PASSWORD_VALIDATORS`, `AUTH_USER_MODEL`
- `REST_FRAMEWORK`, `SIMPLE_JWT`
- Always-on security headers: `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY`, `X_FRAME_OPTIONS`
- `CORS_ALLOW_CREDENTIALS = True`
- `LANGUAGE_CODE`, `TIME_ZONE`, `USE_I18N`, `USE_TZ`, `STATIC_URL`, `DEFAULT_AUTO_FIELD`

**R2.2** `base.py` does **not** set `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ALL_ORIGINS`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_*`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS`, `SECURE_PROXY_SSL_HEADER` at module scope. Those move to the per-env files.

**R2.3** `base.py` leaves `config.py` untouched — `config.py` still reads env vars; `base.py` just doesn't import the per-env ones.

### R3 — `development.py`

**R3.1** `from .base import *`.
**R3.2** Hardcodes: `DEBUG = True`.
**R3.3** `ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']` — `*` only because dev should never 400 on unrecognized hosts; explicit in dev, never in prod.
**R3.4** `CORS_ALLOW_ALL_ORIGINS = True` (unconditional in dev — easier frontend development).
**R3.5** `CORS_ALLOWED_ORIGINS = []` (redundant with allow-all, but explicit so the attribute exists).
**R3.6** Security-disabling:
- `SECURE_SSL_REDIRECT = False`
- `SECURE_HSTS_SECONDS = 0`
- `SESSION_COOKIE_SECURE = False`
- `CSRF_COOKIE_SECURE = False`

**R3.7** `EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'` — future-proofing so any email-sending code logs to stdout in dev instead of failing.

### R4 — `production.py`

**R4.1** `from .base import *`.
**R4.2** Hardcodes: `DEBUG = False`.
**R4.3** Reads env-driven settings from `config`:
- `ALLOWED_HOSTS` (from `config.ALLOWED_HOSTS`)
- `CORS_ALLOWED_ORIGINS` (from `config.CORS_ALLOWED_ORIGINS`)
- `CSRF_TRUSTED_ORIGINS` (from `config.CSRF_TRUSTED_ORIGINS`)
- `SECURE_PROXY_SSL_HEADER` (from `config.SECURE_PROXY_SSL_HEADER`)
- `SECURE_SSL_REDIRECT` (from `config.SECURE_SSL_REDIRECT`, but default to `True` if env unset — see R4.5)
- `SECURE_HSTS_SECONDS` (from `config.SECURE_HSTS_SECONDS`, defaulting to `31536000` if env unset)
- `SECURE_HSTS_INCLUDE_SUBDOMAINS` (from `config`, default `True`)
- `SECURE_HSTS_PRELOAD` (from `config`, default `True`)
- `SESSION_COOKIE_SECURE = True` (hardcoded; never false in prod)
- `CSRF_COOKIE_SECURE = True` (hardcoded; never false in prod)
- `CORS_ALLOW_ALL_ORIGINS = False` (hardcoded)

**R4.4** `production.py` performs three import-time assertions:
1. `assert not DEBUG, "DEBUG must be False in production"`
2. `assert ALLOWED_HOSTS, "ALLOWED_HOSTS must not be empty in production"`
3. `assert SECRET_KEY and len(SECRET_KEY) >= 50, "SECRET_KEY must be at least 50 chars in production"`

Failing any assertion crashes Django startup with a clear message. This is a belt-and-suspenders check in addition to Django's own `check --deploy` warnings.

**R4.5** When `SECURE_SSL_REDIRECT` / `SECURE_HSTS_SECONDS` are not explicitly set in env, `production.py` applies prod-safe defaults (True / 31536000). Explicit env values still win. This is the opposite of `base` + current single-file behavior, which defaults to off.

**R4.6** Logging — `production.py` ships a minimal `LOGGING` dict that sends WARNING and above from the `django` and `apps.*` loggers to stderr (since logging directly to a file path requires infrastructure assumptions). Structured logging / Sentry is out-of-scope.

### R5 — `test.py`

**R5.1** `from .base import *`.
**R5.2** `DEBUG = False` (match Django default for tests).
**R5.3** `ALLOWED_HOSTS = ['testserver']` (Django's test client sends this host).
**R5.4** `PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']` — speeds user creation by ~10× in the test suite. Safe because tests never see real passwords.
**R5.5** Throttles remain wired (since we test throttling behavior in `ThrottleTests`). Cache backend remains the default local-memory backend.
**R5.6** `SECURE_SSL_REDIRECT = False` (tests talk HTTP).

### R6 — Entrypoint updates

**R6.1** `manage.py` defaults `DJANGO_SETTINGS_MODULE` to `jobApp.settings.development`.
**R6.2** `jobApp/wsgi.py` and `jobApp/asgi.py` default to `jobApp.settings.production`.
**R6.3** Django's test runner picks `jobApp.settings.test` when no `DJANGO_SETTINGS_MODULE` env var is set. Implementation: either patch `manage.py` to auto-pick `test` when `argv[1] == 'test'`, OR introduce a `runtests` shim — pick the simpler option.

Recommended: extend `manage.py` with a two-line branch:

```python
if "test" in sys.argv:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobApp.settings.test")
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobApp.settings.development")
```

### R7 — Documentation

**R7.1** `Readme.md` explains the three settings modules and how to pick one (`DJANGO_SETTINGS_MODULE=jobApp.settings.production uv run python manage.py migrate`).
**R7.2** `CLAUDE.md` adds a short rule: "Put env-identical config in `base.py`. Put env-differing defaults in `development.py` / `production.py` / `test.py`. Never hardcode secrets or DB creds anywhere — those stay in `config.py`."
**R7.3** `.env.example` gets a line at the top explaining `DJANGO_SETTINGS_MODULE` is picked automatically but can be overridden.

### R8 — Tests

**R8.1** A small `apps/accounts/tests.py::SettingsModuleTests` class verifies test-env invariants:
- `settings.DEBUG is False`
- `settings.PASSWORD_HASHERS[0].endswith('MD5PasswordHasher')`
- `settings.SECURE_SSL_REDIRECT is False`
- `'testserver' in settings.ALLOWED_HOSTS`

**R8.2** The existing 38 tests continue to pass under `jobApp.settings.test`. No other test file is modified.

**R8.3** Manual verification in the audit task:
- `DJANGO_SETTINGS_MODULE=jobApp.settings.development uv run python manage.py check` → 0 issues.
- `DJANGO_SETTINGS_MODULE=jobApp.settings.production SECRET_KEY=<50+ char> DB_NAME=x DB_USER=x DB_PASSWORD=x ALLOWED_HOSTS=example.com uv run python manage.py check --deploy` → 0 security warnings.
- `DJANGO_SETTINGS_MODULE=jobApp.settings.production DEBUG=true ... manage.py check` → crashes with AssertionError (`DEBUG must be False in production`).
- `DJANGO_SETTINGS_MODULE=jobApp.settings.production ALLOWED_HOSTS= ... manage.py check` → crashes with AssertionError.

## Acceptance Criteria

1. `uv run python manage.py test` runs with `jobApp.settings.test` and all 38 + 4 new tests pass.
2. `uv run python manage.py runserver` (no env override) uses `jobApp.settings.development` and boots with DEBUG=True.
3. `DJANGO_SETTINGS_MODULE=jobApp.settings.production uv run python manage.py check --deploy` with real prod env vars returns zero security warnings.
4. Production-mode boot crashes if DEBUG=True, ALLOWED_HOSTS empty, or SECRET_KEY short — tested via the three manual startup scenarios in R8.3.
5. `grep -r "from jobApp import settings" .` returns no results (no code depends on the old module path as a direct import).

## Risks & Mitigations

- **`from .base import *` hides dependencies.** Mitigation: acceptable trade-off — it's the Django community idiom and the override points are limited and documented.
- **Hard assertions in `production.py` crash startup.** That's the intent — misconfigured prod should fail loud, not ship an insecure service. Mitigation: assertions have clear messages naming the env var to fix.
- **Any external tool / IDE that assumes `jobApp/settings.py` exists may break.** Mitigation: check Postman, pre-commit hooks (none installed yet), CI config (none yet). Verified via Task 14 audit.
- **`config.py` becomes partly redundant for env-driven security toggles.** That's fine — `config.py` stays as the env-reader; `production.py` chooses which of its values to use and applies prod-safe defaults on top. No behavior regression.

## Out-of-Scope (captured for future work)

- `django-debug-toolbar` in `development.py`.
- Structured logging (`structlog` or `python-json-logger`) in `production.py`.
- Sentry DSN wiring.
- Health-check endpoint (`/healthz`, `/readyz`).
- `.env.production.example` / `.env.development.example` file variants.
- CI pipeline changes (still out-of-scope at the project level).
