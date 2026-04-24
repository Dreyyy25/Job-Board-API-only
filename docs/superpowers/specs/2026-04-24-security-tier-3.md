# Security Pass — Tier 3 Spec

**Date:** 2026-04-24
**Status:** Draft (v2 — plan-review revisions)
**Owner:** Dreyyy25
**Builds on:** Tier 1 merged. Tier 2 is **recommended but not required** — R4 below specifies both service-layer and view-layer insertion points.

## Goal

Close the remaining gaps between current posture (header + scoped throttle + CORS from Tier 0) and the full `django-security` skill checklist: stronger password hashing, broader rate limiting, explicit cookie SameSite, and structured security/request logging. One coherent pass so `manage.py check --deploy` under production settings returns clean.

## Non-Goals

- Full RBAC / groups & permissions
- Content Security Policy (CSP) — API is JSON-only; CSP is a Tier 4 admin-surface concern
- 2FA / MFA
- Sentry / error-monitoring SaaS (Tier 4)
- OAuth / social login

## Current-State Summary

- `PASSWORD_HASHERS` defaults to PBKDF2. Argon2 is memory-hard; PBKDF2 is not.
- `REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES']` is `ScopedRateThrottle` only. Authenticated users have no per-user throttle.
- `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` not set explicitly.
- `production.py` logs only `django` and `apps` at WARNING. `django.security` / `django.request` sub-loggers not captured.
- No dependency vulnerability scan in CI.

## Requirements

### R1 — Argon2 password hashing

**R1.1** Add `argon2-cffi` to `pyproject.toml`.

**R1.2** `settings/base.py`:
```python
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]
```

**R1.3** `settings/test.py` keeps `MD5PasswordHasher` first for speed.

**R1.4** Existing PBKDF2-hashed passwords keep working — Django falls through the list on verify and upgrades on next login.

**R1.5** Test: `test_new_user_password_stored_with_argon2` — inspect `user.password.startswith('argon2')`.

### R2 — Broader throttling

**R2.1** `REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES']` in `settings/base.py` **adds** `AnonRateThrottle` and `UserRateThrottle` alongside the existing `ScopedRateThrottle`:
```python
'DEFAULT_THROTTLE_CLASSES': [
    'rest_framework.throttling.AnonRateThrottle',
    'rest_framework.throttling.UserRateThrottle',
    'rest_framework.throttling.ScopedRateThrottle',
],
'DEFAULT_THROTTLE_RATES': {
    'anon': '100/day',
    'user': '1000/day',
    'burst': '60/min',
    'register': '5/min',
    'login': '10/min',
    'token_refresh': '20/min',
},
```

**R2.2 — Layered throttle on write-heavy viewsets.** Setting `throttle_classes` on a viewset REPLACES the default list. To add burst protection without losing the anon/user defaults, list all three:
```python
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

class BurstRateThrottle(UserRateThrottle):
    scope = 'burst'  # '60/min' from DEFAULT_THROTTLE_RATES

class JobPostViewSet(ModelViewSet):
    throttle_classes = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle]
    # ...
```

Attached to: `JobPostViewSet`, `apply_for_job`.

**Scope note**: `BurstRateThrottle` subclasses `UserRateThrottle`, whose `get_cache_key` returns `None` for anonymous requests — so burst applies to **authenticated traffic only**. Anonymous callers are bounded by the 100/day `AnonRateThrottle` alone. This is intentional: anon can't authenticate fast enough to need a 60/min ceiling, and adding IP-keyed burst would require subclassing `SimpleRateThrottle` with a composite cache key — deferred to Tier 4 if abuse traffic materializes.

**R2.3** Tests: one anon-throttle test, one user-throttle test, one burst-throttle test. All clear DRF's cache in `setUp`/`tearDown`.

**R2.4** Env-override of rates is deferred to Tier 4 — rates are hardcoded in `base.py`.

### R3 — Explicit SameSite cookies

**R3.1** `settings/base.py`:
```python
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Django default; documented here for intent.
```

**Scope note**: this API uses JWTs in the `Authorization` header. CSRF and session cookies matter only for the Django admin at `ADMIN_URL`. The settings above are admin-surface hardening; an SPA using cookie-based auth would need different values.

**R3.2** `settings/production.py` already sets `SESSION_COOKIE_SECURE=True` / `CSRF_COOKIE_SECURE=True`. No change.

**R3.3** Test: `test_samesite_lax_configured` — assert the four settings.

### R4 — Security + request logging

**R4.1** `settings/production.py` `LOGGING` gains:
```python
'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
```

**R4.2 — Insertion point (tier-flexible).**
- **If Tier 2 merged**: emit the warning inside `apps.accounts.services.login_user` on `InvalidCredentialsError`.
- **If Tier 2 not yet merged**: emit the warning directly in `apps.accounts.views.login` in the `Invalid credentials` branch (both `UserAccount.DoesNotExist` and bad-password).

Both paths produce the same log line; the test below works either way.

**R4.3** Log format:
```python
logging.getLogger('django.security').warning(
    'Failed login attempt for email=%s', email_hash,
)
```

**PII note**: `email_hash` is the SHA-256 of the attempted email, not the plaintext. This preserves forensic value (same attacker hammering one account still shows as one hash) while keeping raw emails out of logs — a GDPR-friendly default. If plaintext is later needed for a specific incident, it can be pulled from request logs gated behind a retention policy. Hashing is added in Tier 3; a retention-policy doc is a Tier 4 deliverable.

**Empty/missing email edge case**: `_email_hash('')` produces the constant `e3b0c44298fc1c14` (SHA-256 of empty string, truncated to 16 chars). This is informationally useful — a spike of that single hash signals a bot that's POSTing without email. The test asserts the hash pattern (`email_hash=`) appears in the log and the plaintext email does not; it does not depend on hash uniqueness.

**R4.4** Test: `test_failed_login_logs_security_warning` using `self.assertLogs('django.security', level='WARNING')`. Assert the hash appears; assert the plaintext does not.

### R5 — Dependency vulnerability scan

**R5.1** Run `uv run --with pip-audit pip-audit` once during T3-5.

**R5.2** Fix Highs and Criticals. Mediums get a tracked issue.

**R5.3** Wiring into CI is Tier 4.

## Success Criteria

- Argon2 in `user.password` prefix.
- `DEFAULT_THROTTLE_CLASSES` lists Anon + User + Scoped.
- `JobPostViewSet.throttle_classes` has all three throttles.
- `settings.SESSION_COOKIE_SAMESITE == 'Lax'`.
- Failed-login WARNING visible via `assertLogs`; plaintext email not in log line.
- `pip-audit` shows zero High/Critical.
- Under `DJANGO_SETTINGS_MODULE=jobApp.settings.production` with a complete env, `manage.py check --deploy` → zero warnings.

## Risks

- **Argon2 install on Windows**: wheels are available. Same posture as `psycopg2-binary`. Low risk.
- **Throttle cache pollution across tests**: `LocMemCache` is not reset between tests. Mitigation: `test.py` raises `anon` / `user` rates to effectively-unlimited (`100000/day`) **and** adds `cache.clear()` to a `BaseAPITestCase` setUp that all tests subclass (or equivalent). Spelled out in the plan.
- **Logging noise**: `django.security` at WARNING can flood logs under automated abuse. Acceptable — log-aggregator-side rate-limiting is the right place to solve that.
- **Email hashing (R4.3)**: loses the ability to search logs for a specific user's failures without pre-hashing. Acceptable for now; reviewable later.
