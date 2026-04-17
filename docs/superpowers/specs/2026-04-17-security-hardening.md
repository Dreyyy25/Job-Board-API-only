# Security Hardening — Tier 0 Spec

**Date:** 2026-04-17
**Status:** Draft
**Owner:** Dreyyy25

## Goal

Close the critical security gaps that currently block public deployment of the Job Board API: privilege escalation via permissive serializers, no throttling on auth endpoints, weak password policy, no token revocation, unsafe default config, and zero test coverage on permissions.

## Non-Goals

Deferred to follow-up specs (do not expand scope here):

- **Tier 1 (usability):** pagination, CORS, search/filter, N+1 query optimization, withdrawal endpoint, production security headers.
- **Tier 2 (product):** file uploads for resumes/images, email verification, password reset, observability, CI pipeline.

## Current-State Summary

- `UserAccountSerializer`, `JobPostSerializer`, `CompanySerializer`, and all seeker serializers use `fields = '__all__'`. Any authenticated user can `PATCH /api/v1/accounts/me/` with `{"is_staff": true, "is_superuser": true}` and escalate. `POST /api/v1/accounts/register/` has the same hole at signup.
- Custom `validate_password` caps minimum at 6 characters. Django's `AUTH_PASSWORD_VALIDATORS` is configured but never actually invoked from the serializer.
- No `DEFAULT_THROTTLE_CLASSES` — `/register/`, `/login/`, `/token/refresh/` are wide open to credential stuffing.
- `rest_framework_simplejwt.token_blacklist` is commented out of `INSTALLED_APPS`. Issued access tokens live 60 min with no way to revoke.
- `DEBUG = True` is hardcoded; `ALLOWED_HOSTS = []`; admin URL path is gated on `DEBUG` (`secure-admin/` vs `admin-secure/`), so flipping debug changes routing.
- All four apps ship `tests.py` stubs. No coverage of the auth/permission logic this spec depends on.

## Requirements

### R1 — Serializer field control

**R1.1** No serializer uses `fields = '__all__'`. Every serializer declares an explicit `fields` list.

**R1.2** The following fields are `read_only` everywhere they appear in a writable serializer: `id`, `is_staff`, `is_superuser`, `groups`, `user_permissions`, `last_login`, `date_joined`, `created_at`, `updated_at`.

**R1.3** `UserAccount.password` is `write_only` (already true — verify regression tests cover it).

**R1.4** `user_type` is immutable after creation. A PATCH or PUT that attempts to change `user_type` on an existing user is rejected with 400.

**R1.5** `JobPost.job_description_hidden` is only present in responses for (a) the owning company's user, or (b) staff/superusers. Anonymous and other authenticated users receive the field either omitted or as empty string.

**R1.6** `Company.user_account` is read-only in `CompanySerializer`. A company owner cannot reassign their company to another user via PATCH.

**R1.7** `JobPost.company` is read-only in `JobPostSerializer`. Ownership is assigned server-side in `perform_create` (already works; spec codifies the rule).

### R2 — Registration hardening

**R2.1** `POST /api/v1/accounts/register/` uses a dedicated `RegisterSerializer` distinct from `UserAccountSerializer`.

**R2.2** `RegisterSerializer` accepts only these fields: `email`, `password`, `user_type`, `date_of_birth`, `contact_number`, `sex`, `user_image_url`. All other fields in the request body are ignored (not rejected — ignored, so malformed clients still register).

**R2.3** Registering with a payload containing `is_staff=true` or `is_superuser=true` must produce a user where both flags are `False`.

**R2.4** `user_type` is required on register and must be `job_seeker` or `company`.

### R3 — Password policy

**R3.1** Minimum password length: 10 characters.

**R3.2** Password validation runs Django's `validate_password()` which applies every validator in `AUTH_PASSWORD_VALIDATORS`: `UserAttributeSimilarityValidator`, `MinimumLengthValidator` (configured `min_length=10`), `CommonPasswordValidator`, `NumericPasswordValidator`.

**R3.3** Validation runs on registration, on `PUT/PATCH` to `UserAccountViewSet`, and on `PATCH` to `/me/`.

**R3.4** The custom 6-char check in `UserAccountSerializer.validate_password` is removed.

### R4 — Rate limiting on auth endpoints

**R4.1** Throttles applied to anonymous clients by IP:

| Endpoint | Scope name | Limit |
| --- | --- | --- |
| `POST /register/` | `register` | 5/min |
| `POST /login/` | `login` | 10/min |
| `POST /token/refresh/` | `token_refresh` | 20/min |

**R4.2** Exceeded limits return HTTP 429 with `Retry-After` header.

**R4.3** Throttling uses `rest_framework.throttling.ScopedRateThrottle` — no custom throttle class.

### R5 — Token revocation (logout)

**R5.1** `rest_framework_simplejwt.token_blacklist` is added to `INSTALLED_APPS` and its migrations applied.

**R5.2** `SIMPLE_JWT` settings updated: `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`.

**R5.3** `POST /api/v1/accounts/logout/` accepts JSON `{"refresh": "<token>"}`, blacklists the refresh token, returns HTTP 205 on success, HTTP 400 on invalid/missing token. Requires authentication.

**R5.4** After logout, using the blacklisted refresh token at `/token/refresh/` returns HTTP 401.

### R6 — Environment-driven configuration

**R6.1** `DEBUG` is read from env var `DEBUG` (string, defaults to `false`). Parsed with `os.getenv("DEBUG", "false").lower() == "true"`.

**R6.2** `ALLOWED_HOSTS` is read from env var `ALLOWED_HOSTS` (comma-separated, defaults to empty list).

**R6.3** Admin URL path is read from env var `ADMIN_URL` (defaults to `admin/`). The `DEBUG`-coupled branching in `jobApp/urls.py` is removed.

**R6.4** `.env.example` is updated with the three new keys and a `# Deployment` section header.

**R6.5** README's "Set up environment variables" section lists the new keys.

### R7 — Permission / privilege test coverage

All tests live under each app's `tests.py` and run via `python manage.py test`.

**R7.1 — `apps.accounts.tests`**
- `test_register_ignores_is_staff_flag`: POST `/register/` with `is_staff=true` → returned user has `is_staff=False`.
- `test_register_ignores_is_superuser_flag`: same for `is_superuser`.
- `test_register_rejects_short_password`: 9-char password → 400.
- `test_register_rejects_common_password`: `"password123"` → 400.
- `test_register_requires_user_type`: missing `user_type` → 400.
- `test_login_returns_tokens`: valid creds → 200 + access/refresh in body.
- `test_login_rejects_wrong_password`: → 401.
- `test_me_patch_rejects_is_staff_escalation`: PATCH `/me/` with `is_staff=true` → user's `is_staff` remains `False` (endpoint may 200 and drop the field, or 400; assertion is on the stored value).
- `test_users_cannot_see_other_users`: user A GET `/users/{B.id}/` → 404.
- `test_users_cannot_patch_user_type`: PATCH `/me/` with `user_type="company"` on a seeker → 400.
- `test_logout_blacklists_refresh_token`: logout then refresh → 401 on refresh.
- `test_register_throttles_after_limit`: 6th POST in a minute → 429.
- `test_login_throttles_after_limit`: 11th POST in a minute → 429.

**R7.2 — `apps.jobs.tests`**
- `test_anonymous_only_sees_published_active_jobs`.
- `test_company_sees_own_unpublished_jobs`.
- `test_company_cannot_edit_other_company_job`: 403.
- `test_job_seeker_cannot_apply_twice`: 400 (already enforced via `unique_together`; test locks the behavior).
- `test_job_seeker_cannot_apply_as_another_user`: 403.
- `test_non_company_cannot_create_job`: seeker POST `/job-posts/` → 403.

**R7.3 — `apps.companies.tests`**
- `test_company_owner_can_edit_own_profile`.
- `test_company_owner_cannot_edit_other_company`: 403.
- `test_seeker_cannot_create_company`: 403 (via `user_type` guard).
- `test_company_cannot_reassign_user_account`: PATCH with `user_account=<other_user>` → field ignored, record unchanged.

**R7.4 — `apps.seekers.tests`**
- `test_seeker_can_manage_own_education`.
- `test_seeker_cannot_edit_other_seeker_education`: 403.
- `test_company_cannot_create_seeker_profile`: 403.

### R8 — Settings sanity

**R8.1** `python manage.py check --deploy` produces no critical issues in a `DEBUG=false` environment, with the exception of warnings for items explicitly deferred to Tier 1 (SSL redirect, HSTS).

**R8.2** The `# 'rest_framework_simplejwt.token_blacklist'` comment is removed once the app is enabled.

## Acceptance Criteria

1. `python manage.py test` runs all R7 tests and they pass.
2. Manual smoke test: register with `{"email":"a@b.c","password":"longEnough1!","user_type":"job_seeker","is_staff":true}` → response `user.is_staff == false`.
3. Manual smoke test: 6 `POST /register/` within 60s from one IP → 6th returns 429.
4. Manual smoke test: login → logout (with refresh) → hit `/token/refresh/` with the same refresh → 401.
5. `grep -r "fields = '__all__'" apps/` returns no results.
6. `DEBUG=false python manage.py runserver` boots without `SECRET_KEY`-style startup crashes (env loaded from `.env`).

## Risks & Mitigations

- **Migration for `token_blacklist` requires a DB change.** Risk: prod DB users need to run `migrate` before deployment. Mitigation: documented in `.env.example` changelog note; deploys already run migrations.
- **`ROTATE_REFRESH_TOKENS=True` changes client behavior.** Risk: existing clients holding a long-lived refresh token will now get a new one on each use. Mitigation: this is a pre-production API; no real clients yet.
- **Tightened password policy breaks test fixtures.** Risk: any seed data / fixtures using short passwords will fail. Mitigation: this repo has no fixtures today; tests create users through the serializer.

## Out-of-Scope (captured for Tier 1 / Tier 2 specs)

- Pagination defaults, CORS allowlist, search filters, query perf — **Tier 1**.
- File uploads (resumes, company images), email verification, password reset, observability, CI — **Tier 2**.
- Refactoring function-view permission checks into permission classes — **Tier 2** (quality cleanup).
