# Security Pass — Tier 3 Plan

**Spec:** `docs/superpowers/specs/2026-04-24-security-tier-3.md`
**Date:** 2026-04-24 (v2 — plan-review revisions)

## Prerequisite

- **Tier 1 merged** (required — signal-created profiles are referenced in the Argon2 test's `create_user` path).
- **Tier 2 merged** (recommended; T3-4 has a fallback insertion point in `views.login` if not).

## Execution order

### T3-1 — Argon2 hasher

**Files:** `pyproject.toml`, `jobApp/settings/base.py`, `apps/accounts/tests.py`.

1. `uv add argon2-cffi`.
2. `base.py` `PASSWORD_HASHERS` = Argon2 first (spec R1.2). `test.py` unchanged (MD5 stays).
3. Test `test_new_user_password_stored_with_argon2`:
   ```python
   from django.test import override_settings

   @override_settings(
       PASSWORD_HASHERS=[
           'django.contrib.auth.hashers.Argon2PasswordHasher',
           'django.contrib.auth.hashers.PBKDF2PasswordHasher',
       ],
   )
   def test_new_user_password_stored_with_argon2(self):
       user = UserAccount.objects.create_user(
           email='argon@example.com', password='Str0ng-Password!',
           user_type='job_seeker',
       )
       self.assertTrue(user.password.startswith('argon2'))
   ```
4. `uv run python manage.py test` — green.

### T3-2 — Default + burst throttles (with correct dict-merge)

**Files:** `jobApp/settings/base.py`, `jobApp/settings/test.py`, `apps/jobs/views.py`, `apps/accounts/tests.py`, `apps/jobs/tests.py`.

1. `base.py` `REST_FRAMEWORK` — extend per spec R2.1. Confirm `DEFAULT_THROTTLE_CLASSES` lists Anon + User + Scoped and `DEFAULT_THROTTLE_RATES` includes `anon`, `user`, `burst`, `register`, `login`, `token_refresh`.

2. `test.py` — raise anon/user/burst rates to effectively-unlimited, **preserving existing scoped rates via inner dict spread**:
   ```python
   from .base import REST_FRAMEWORK as _BASE_RF

   REST_FRAMEWORK = {
       **_BASE_RF,
       'DEFAULT_THROTTLE_RATES': {
           **_BASE_RF['DEFAULT_THROTTLE_RATES'],
           'anon': '100000/day',
           'user': '100000/day',
           'burst': '100000/day',
           # register/login/token_refresh inherit from base — DO NOT override.
       },
   }
   ```
   Verify `test_register_throttles_after_limit` (uses `register: 5/min` from base) still passes.

3. Add a base test case with per-test cache clearing to prevent throttle bleed:
   ```python
   # apps/accounts/tests.py (or a new apps/_shared/testing.py if preferred)
   from django.core.cache import cache
   from rest_framework.test import APITestCase

   class BaseAPITestCase(APITestCase):
       def setUp(self):
           cache.clear()
           super().setUp()
   ```
   Migrate existing `APITestCase` subclasses to `BaseAPITestCase` where they make many requests — start with `PaginationTests`, `ThrottleTests` (already does this manually), and the new burst-throttle test.

4. `apps/jobs/views.py`:
   ```python
   from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

   class BurstRateThrottle(UserRateThrottle):
       scope = 'burst'

   class JobPostViewSet(viewsets.ModelViewSet):
       throttle_classes = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle]
       # ...
   ```
   Attach the same `throttle_classes` list to `apply_for_job`'s `@throttle_classes([...])` decorator. **Do not use `[BurstRateThrottle]` alone** — that removes the anon/user defaults.

5. Tests:
   - `test_burst_throttle_kicks_in` — under `override_settings(REST_FRAMEWORK={...'burst': '3/min', ...})`, hit `apply_for_job` 4 times rapidly; assert 4th is 429.
   - `test_anon_throttle_kicks_in` — similar with `anon: '3/day'`.
   - `test_user_throttle_kicks_in` — similar with `user: '3/day'`.

6. `uv run python manage.py test` — green.

### T3-3 — SameSite cookies

**Files:** `jobApp/settings/base.py`, `apps/accounts/tests.py` (SettingsModuleTests).

1. `base.py` — add four settings per spec R3.1.
2. In `SettingsModuleTests`, add:
   ```python
   def test_samesite_lax_configured(self):
       self.assertEqual(django_settings.SESSION_COOKIE_SAMESITE, 'Lax')
       self.assertEqual(django_settings.CSRF_COOKIE_SAMESITE, 'Lax')
       self.assertTrue(django_settings.SESSION_COOKIE_HTTPONLY)
       self.assertFalse(django_settings.CSRF_COOKIE_HTTPONLY)
   ```
3. Run tests.

### T3-4 — Security + request loggers (tier-flexible)

**Files:** `jobApp/settings/production.py`, `apps/accounts/services.py` **or** `apps/accounts/views.py`, `apps/accounts/tests.py`.

1. `production.py` `LOGGING['loggers']` — add `django.security` and `django.request` entries per spec R4.1.

2. Pick insertion point based on whether Tier 2 has merged:
   - **Tier 2 merged** (preferred): `apps.accounts.services.login_user` — in the `InvalidCredentialsError` branches (user-not-found AND bad-password), log the warning before raising.
   - **Tier 2 NOT merged** (fallback): `apps.accounts.views.login` — in both `Invalid credentials` 401 branches.

3. Log emission uses a SHA-256 hash of the attempted email:
   ```python
   import hashlib
   import logging

   def _email_hash(email: str) -> str:
       return hashlib.sha256((email or '').strip().lower().encode()).hexdigest()[:16]

   logging.getLogger('django.security').warning(
       'Failed login attempt for email_hash=%s', _email_hash(email),
   )
   ```

4. Test `test_failed_login_logs_security_warning`:
   ```python
   def test_failed_login_logs_security_warning(self):
       with self.assertLogs('django.security', level='WARNING') as cm:
           r = self.client.post(
               '/api/v1/accounts/login/',
               {'email': 'ghost@example.com', 'password': 'x'},
               format='json',
           )
       self.assertEqual(r.status_code, 401)
       log_output = '\n'.join(cm.output)
       self.assertIn('email_hash=', log_output)
       self.assertNotIn('ghost@example.com', log_output)  # plaintext must not leak
   ```

5. Run tests.

### T3-5 — `pip-audit` sweep

1. `uv run --with pip-audit pip-audit` — review output.
2. For any High/Critical: `uv lock --upgrade-package <pkg>` or update the pin in `pyproject.toml`; re-run audit.
3. Commit `uv.lock` diff if any.

### T3-6 — Production `check --deploy` sweep

**Exact shell invocation** (production.py asserts on env at import time, so all vars must be set in the same command):

```bash
SECRET_KEY=$(uv run python -c 'import secrets; print(secrets.token_urlsafe(64))') \
ALLOWED_HOSTS=example.com \
DEBUG=false \
SECURE_SSL_REDIRECT=true \
SECURE_HSTS_SECONDS=31536000 \
CORS_ALLOWED_ORIGINS=https://example.com \
CSRF_TRUSTED_ORIGINS=https://example.com \
DJANGO_SETTINGS_MODULE=jobApp.settings.production \
DB_NAME=jobboard DB_USER=postgres DB_PASSWORD=x DB_HOST=localhost DB_PORT=5432 \
uv run python manage.py check --deploy
```

Expected output: zero warnings. If any warning remains, either fix `production.py` or document the exception in the spec's Risks section.

### T3-7 — Final audit

1. `uv run python manage.py test` — green (expect ~60+ tests after all three tiers).
2. `CLAUDE.md`: one paragraph on logging + throttle posture.
3. `.env.example`: add the "Minimum production env" section documenting the variables T3-6 set.
