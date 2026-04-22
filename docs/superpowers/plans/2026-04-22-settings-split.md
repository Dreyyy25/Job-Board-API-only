# Split Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all requirements from `docs/superpowers/specs/2026-04-22-settings-split.md` — convert `jobApp/settings.py` into a `jobApp/settings/` package with `base.py`, `development.py`, `production.py`, `test.py`, wire entrypoints to pick the right module, and lock the behavior with tests.

**Architecture:** Django's standard split-settings idiom. `base.py` holds env-identical config (imports still routed through `config.py`). Per-env files `from .base import *` and override. Test-runner auto-picks `test.py`; `manage.py` defaults to `development`; `wsgi.py`/`asgi.py` default to `production`. Hard assertions in `production.py` fail-fast on misconfiguration.

**Tech Stack:** Django 5.2, DRF 3.16, simplejwt 5.5, `django-filter`, `django-cors-headers`, `config.py` env-reader, PostgreSQL. No new dependencies.

---

## Phase 1 — Create the settings package

### Task 1: Extract `base.py` from the current settings.py

**Files:**
- Create: `jobApp/settings/__init__.py`
- Create: `jobApp/settings/base.py`
- Delete: `jobApp/settings.py` (after Task 1.4 — see below)

- [ ] **Step 1: Read current `jobApp/settings.py` and snapshot its content**

Run: `cat jobApp/settings.py > /tmp/settings_snapshot.py`
Expected: snapshot file created.

- [ ] **Step 2: Create the settings package directory and `__init__.py`**

Create `jobApp/settings/__init__.py` with a one-line docstring:

```python
"""Settings package. Pick a submodule via DJANGO_SETTINGS_MODULE."""
```

- [ ] **Step 3: Create `jobApp/settings/base.py`**

Copy the entire content of `jobApp/settings.py` into `jobApp/settings/base.py`, then remove these blocks:

- The `from config import (...)` tuple entries that are per-env-only: `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ALL_ORIGINS`, `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SECURE_HSTS_SECONDS`, `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `DEBUG`, `ALLOWED_HOSTS`. Leave only `SECRET_KEY`, `DB_HOST`, `DB_NAME`, `DB_PASSWORD`, `DB_PORT`, `DB_USER`.
- Any module-level references to the removed names (they shouldn't exist at module scope — the imported names are just consumed elsewhere in settings like `DATABASES` uses `DB_*` and `SIMPLE_JWT` uses `SECRET_KEY`).

The resulting `base.py` must contain (at module scope, non-exhaustive):
- `BASE_DIR`, `SECRET_KEY` import
- `INSTALLED_APPS`, `AUTH_USER_MODEL`
- `REST_FRAMEWORK` (full dict)
- `SIMPLE_JWT` (full dict)
- `MIDDLEWARE`, `ROOT_URLCONF`, `TEMPLATES`, `WSGI_APPLICATION`
- `DATABASES` (uses DB_* from config)
- `AUTH_PASSWORD_VALIDATORS`
- Always-on security headers: `SECURE_CONTENT_TYPE_NOSNIFF = True`, `SECURE_REFERRER_POLICY = 'same-origin'`, `X_FRAME_OPTIONS = 'DENY'`
- `CORS_ALLOW_CREDENTIALS = True`
- `LANGUAGE_CODE`, `TIME_ZONE`, `USE_I18N`, `USE_TZ`
- `STATIC_URL`, `DEFAULT_AUTO_FIELD`

And must **not** contain any of: `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ALL_ORIGINS`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_*`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS`, `SECURE_PROXY_SSL_HEADER`.

Note: `base.py` lives at `jobApp/settings/base.py`, so `BASE_DIR = Path(__file__).resolve().parent.parent` in the current file points to `jobApp/`. Update to `BASE_DIR = Path(__file__).resolve().parent.parent.parent` so `BASE_DIR` still points to the project root.

- [ ] **Step 4: Delete `jobApp/settings.py`**

Run: `rm jobApp/settings.py`
Verify: `ls jobApp/settings*` shows only the `jobApp/settings/` directory.

- [ ] **Step 5: Smoke-test that base imports cleanly (no Django boot yet)**

Run: `uv run python -c "from jobApp.settings import base; print('BASE_DIR:', base.BASE_DIR); print('SECRET_KEY set:', bool(base.SECRET_KEY))"`
Expected: prints a path ending with the repo root and `SECRET_KEY set: True`.
Debug: if it fails with `ImportError`, the removal in Step 3 was too aggressive — check that names referenced elsewhere in the file (e.g., `SECRET_KEY` inside `SIMPLE_JWT`) are still imported.

- [ ] **Step 6: Commit**

```bash
git add jobApp/settings/__init__.py jobApp/settings/base.py
git rm jobApp/settings.py
git commit -m "refactor(settings): extract base.py from monolithic settings"
```

---

## Phase 2 — Per-environment files

### Task 2: `development.py`

**Files:**
- Create: `jobApp/settings/development.py`

- [ ] **Step 1: Write the file**

```python
"""Development settings — loose defaults optimized for local iteration."""
from .base import *  # noqa: F401,F403

DEBUG = True

# Any host goes in dev; never use '*' in prod.
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# CORS wide-open for local frontend dev.
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = []

# Security toggles OFF — dev is plain HTTP.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Print emails to stdout instead of sending.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

- [ ] **Step 2: Smoke-test**

Run: `DJANGO_SETTINGS_MODULE=jobApp.settings.development uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit**

```bash
git add jobApp/settings/development.py
git commit -m "feat(settings): add development environment module"
```

---

### Task 3: `production.py`

**Files:**
- Create: `jobApp/settings/production.py`

- [ ] **Step 1: Write the file**

```python
"""Production settings — strict defaults, fail-fast on misconfiguration."""
import config
from .base import *  # noqa: F401,F403

DEBUG = False

# All env-driven — REQUIRED to be set, checked below.
ALLOWED_HOSTS = config.ALLOWED_HOSTS
CORS_ALLOWED_ORIGINS = config.CORS_ALLOWED_ORIGINS
CORS_ALLOW_ALL_ORIGINS = False
CSRF_TRUSTED_ORIGINS = config.CSRF_TRUSTED_ORIGINS
SECURE_PROXY_SSL_HEADER = config.SECURE_PROXY_SSL_HEADER

# Prod-safe defaults: on unless env explicitly turns them off (unusual).
SECURE_SSL_REDIRECT = config.SECURE_SSL_REDIRECT if "SECURE_SSL_REDIRECT" in __import__("os").environ else True
SECURE_HSTS_SECONDS = config.SECURE_HSTS_SECONDS if config.SECURE_HSTS_SECONDS else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = config.SECURE_HSTS_INCLUDE_SUBDOMAINS
SECURE_HSTS_PRELOAD = config.SECURE_HSTS_PRELOAD

# Hardcoded True — cookies over HTTPS only.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Fail-fast on misconfiguration. Clearer than a silent bad-deploy.
assert not DEBUG, "DEBUG must be False in production"
assert ALLOWED_HOSTS, "ALLOWED_HOSTS must not be empty in production"
assert SECRET_KEY and len(SECRET_KEY) >= 50, (
    "SECRET_KEY must be at least 50 chars in production"
)

# Minimal stderr logging — structured logging / Sentry come later.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
```

- [ ] **Step 2: Smoke-test with valid prod env**

Run:
```bash
DJANGO_SETTINGS_MODULE=jobApp.settings.production \
  SECRET_KEY="placeholder-that-is-definitely-long-enough-for-check-deploy-to-not-warn-about-w009" \
  DB_NAME=x DB_USER=x DB_PASSWORD=x \
  ALLOWED_HOSTS=example.com \
  uv run python manage.py check --deploy
```
Expected: `System check identified no issues (0 silenced).` — all security warnings clear.

- [ ] **Step 3: Smoke-test that `DEBUG=true` crashes**

Run:
```bash
DJANGO_SETTINGS_MODULE=jobApp.settings.production \
  SECRET_KEY="placeholder-that-is-definitely-long-enough-for-check-deploy-to-not-warn-about-w009" \
  DB_NAME=x DB_USER=x DB_PASSWORD=x \
  ALLOWED_HOSTS=example.com \
  DEBUG=true \
  uv run python manage.py check
```
Expected: `AssertionError: DEBUG must be False in production`.

Note: this test only works if the base.py → config.py chain doesn't force DEBUG from env. Since we removed DEBUG from base's `from config import`, and production.py hardcodes `DEBUG = False`, this scenario is impossible via env. The assertion is defensive — it catches anyone who later adds `DEBUG = <something>` below our hardcode. Skip this test if you can't construct a failing case; instead verify the assertion exists in the source.

- [ ] **Step 4: Smoke-test that empty `ALLOWED_HOSTS` crashes**

Run:
```bash
DJANGO_SETTINGS_MODULE=jobApp.settings.production \
  SECRET_KEY="placeholder-that-is-definitely-long-enough-for-check-deploy-to-not-warn-about-w009" \
  DB_NAME=x DB_USER=x DB_PASSWORD=x \
  uv run python manage.py check
```
Expected: `AssertionError: ALLOWED_HOSTS must not be empty in production`.

- [ ] **Step 5: Commit**

```bash
git add jobApp/settings/production.py
git commit -m "feat(settings): add production module with fail-fast assertions"
```

---

### Task 4: `test.py`

**Files:**
- Create: `jobApp/settings/test.py`

- [ ] **Step 1: Write the file**

```python
"""Test settings — fast password hashing, loose host list, no SSL redirect."""
from .base import *  # noqa: F401,F403

DEBUG = False

# Django's test client sends Host: testserver.
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

# Dramatic speedup for UserAccount.create_user(...) in setUp blocks.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Tests talk HTTP.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# CORS settings — tests rely on override_settings to enable specific origins.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
```

- [ ] **Step 2: Smoke-test**

Run: `DJANGO_SETTINGS_MODULE=jobApp.settings.test uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit**

```bash
git add jobApp/settings/test.py
git commit -m "feat(settings): add test module with fast password hasher"
```

---

## Phase 3 — Entrypoint wiring

### Task 5: Update `manage.py` to auto-pick dev/test

**Files:**
- Modify: `manage.py`

- [ ] **Step 1: Read current `manage.py`**

Run: `cat manage.py`
Expected: see the standard Django template (`os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jobApp.settings')`).

- [ ] **Step 2: Replace its `main()` body**

Replace `manage.py` content with:

```python
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    if "test" in sys.argv:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobApp.settings.test")
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobApp.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-tests**

Run:
- `uv run python manage.py check` → uses development, zero issues.
- `uv run python manage.py test apps.accounts.tests.PasswordPolicyTests.test_register_rejects_short_password` → uses test, passes.

- [ ] **Step 4: Commit**

```bash
git add manage.py
git commit -m "chore(settings): manage.py picks test module for test runs, dev otherwise"
```

---

### Task 6: Update `wsgi.py` and `asgi.py` defaults

**Files:**
- Modify: `jobApp/wsgi.py`
- Modify: `jobApp/asgi.py`

- [ ] **Step 1: Edit both files**

In each file, change the existing `os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jobApp.settings')` line to:

```python
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jobApp.settings.production')
```

- [ ] **Step 2: Smoke-test wsgi boot**

Run:
```bash
DJANGO_SETTINGS_MODULE=jobApp.settings.production \
  SECRET_KEY="placeholder-that-is-definitely-long-enough-for-check-deploy-to-not-warn-about-w009" \
  DB_NAME=x DB_USER=x DB_PASSWORD=x \
  ALLOWED_HOSTS=example.com \
  uv run python -c "from jobApp.wsgi import application; print('wsgi ok')"
```
Expected: `wsgi ok`.

- [ ] **Step 3: Commit**

```bash
git add jobApp/wsgi.py jobApp/asgi.py
git commit -m "chore(settings): wsgi/asgi default to production module"
```

---

## Phase 4 — Tests

### Task 7: `SettingsModuleTests`

**Files:**
- Modify: `apps/accounts/tests.py` (append class)

- [ ] **Step 1: Append class**

```python
from django.conf import settings as django_settings


class SettingsModuleTests(APITestCase):
    """Verify we're running under the test settings module."""

    def test_debug_is_false(self):
        self.assertFalse(django_settings.DEBUG)

    def test_password_hasher_is_md5(self):
        self.assertTrue(
            django_settings.PASSWORD_HASHERS[0].endswith('MD5PasswordHasher'),
            f"Expected MD5 hasher, got {django_settings.PASSWORD_HASHERS[0]}",
        )

    def test_ssl_redirect_off_in_tests(self):
        self.assertFalse(django_settings.SECURE_SSL_REDIRECT)

    def test_testserver_in_allowed_hosts(self):
        self.assertIn('testserver', django_settings.ALLOWED_HOSTS)
```

- [ ] **Step 2: Run**

Run: `uv run python manage.py test apps.accounts.tests.SettingsModuleTests -v 2`
Expected: all four PASS.

- [ ] **Step 3: Run the full suite**

Run: `uv run python manage.py test -v 0`
Expected: 42 tests (38 from prior tier + 4 new), all pass. The MD5 hasher speedup should visibly shorten runtime — previous ~24s, expect under 10s.

- [ ] **Step 4: Commit**

```bash
git add apps/accounts/tests.py
git commit -m "test(settings): assert test-module invariants"
```

---

## Phase 5 — Documentation

### Task 8: Update `Readme.md`, `CLAUDE.md`, `.env.example`

**Files:**
- Modify: `Readme.md`
- Modify: `CLAUDE.md`
- Modify: `.env.example`

- [ ] **Step 1: Append settings module docs to `Readme.md`**

After the "Set up environment variables" section, add:

```markdown
### Picking a settings module

The settings package exposes three environment modules:

| Module | When used |
| --- | --- |
| `jobApp.settings.development` | Default for `manage.py` (except `test`). DEBUG=True, loose CORS, no HTTPS redirect. |
| `jobApp.settings.production` | Default for `wsgi.py` / `asgi.py`. DEBUG=False, strict security, fail-fast assertions. |
| `jobApp.settings.test` | Auto-picked when running `manage.py test`. Fast MD5 hasher, ALLOWED_HOSTS locked to `testserver`. |

Override with `DJANGO_SETTINGS_MODULE`:

```bash
DJANGO_SETTINGS_MODULE=jobApp.settings.production uv run python manage.py migrate
```
```

- [ ] **Step 2: Add the rule to `CLAUDE.md`**

Under the Architecture section (alongside "Query hygiene"), add:

```markdown
### Settings organization

Put env-identical config in `jobApp/settings/base.py`. Put env-differing defaults in `development.py` / `production.py` / `test.py`. Never hardcode secrets or DB credentials anywhere — those stay in `config.py` and are read via `from config import ...`. `production.py` uses hard `assert` statements to fail-fast on missing `ALLOWED_HOSTS` or short `SECRET_KEY`.
```

- [ ] **Step 3: Note `DJANGO_SETTINGS_MODULE` in `.env.example`**

At the very top of `.env.example`, prepend:

```
# DJANGO_SETTINGS_MODULE is auto-selected by manage.py (test → .test, else → .development)
# and by wsgi/asgi (→ .production). Override only if you know why.
# DJANGO_SETTINGS_MODULE=jobApp.settings.development

```

- [ ] **Step 4: Commit**

```bash
git add Readme.md CLAUDE.md .env.example
git commit -m "docs(settings): document dev/prod/test modules and override"
```

---

## Phase 6 — Final audit

### Task 9: Verify clean end-state

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run python manage.py test`
Expected: 42 tests, all pass.

- [ ] **Step 2: `check --deploy` in prod mode**

Run:
```bash
DJANGO_SETTINGS_MODULE=jobApp.settings.production \
  SECRET_KEY="placeholder-that-is-definitely-long-enough-for-check-deploy-to-not-warn-about-w009" \
  DB_NAME=x DB_USER=x DB_PASSWORD=x \
  ALLOWED_HOSTS=example.com \
  uv run python manage.py check --deploy
```
Expected: no security warnings.

- [ ] **Step 3: No lingering imports from old path**

Run: `grep -rn "from jobApp import settings" .` and `grep -rn "jobApp\.settings[^\.]" .`
Expected: no hits (except maybe `__pycache__` which we ignore; skip `.venv`).

- [ ] **Step 4: Manual grep for dev-only leaks into prod settings**

Run: `grep -n "DEBUG\|ALLOWED_HOSTS\|SECURE_SSL_REDIRECT" jobApp/settings/base.py`
Expected: no matches — these names must NOT appear at module scope in `base.py`.

- [ ] **Step 5: Confirm `production.py` assertions would fire**

Run these three manual scenarios and assert each errors out:
- Empty `ALLOWED_HOSTS`: `AssertionError: ALLOWED_HOSTS must not be empty in production`
- Short `SECRET_KEY` (e.g., `SECRET_KEY=short`): `AssertionError: SECRET_KEY must be at least 50 chars in production`

- [ ] **Step 6: No commit needed unless audit surfaces a fix**

Audit-only step. If any of the above fails, fix and commit `fix(settings): <specific issue>`.

---

## Self-Review Checklist

- [x] R1 settings-package layout → Tasks 1–4 (create package + three env files).
- [x] R2 base.py contents → Task 1.
- [x] R3 development.py → Task 2.
- [x] R4 production.py → Task 3 (env-driven settings, prod-safe defaults, assertions, logging).
- [x] R5 test.py → Task 4.
- [x] R6 entrypoints → Tasks 5 (manage.py), 6 (wsgi/asgi).
- [x] R7 documentation → Task 8.
- [x] R8 tests → Task 7 + Task 9 manual audit.
- [x] Acceptance criteria 1–5 → Task 9.

No placeholders. Every code block has concrete content. Commits are per task.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-settings-split.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
