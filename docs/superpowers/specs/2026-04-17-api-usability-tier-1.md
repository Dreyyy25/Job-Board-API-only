# API Usability — Tier 1 Spec

**Date:** 2026-04-17
**Status:** Draft
**Owner:** Dreyyy25
**Builds on:** `2026-04-17-security-hardening.md` (Tier 0) — all referenced security work assumed merged.

## Goal

Make the Job Board API usable from a real frontend by adding pagination, CORS, filter/search/ordering on job posts, eliminating guaranteed N+1 query patterns on list endpoints, and wiring production HTTPS/HSTS headers through env-driven config.

## Non-Goals

Captured here so scope creep stays out:

- **File uploads** (resumes, company images) → Tier 2 product spec.
- **Email verification / password reset flows** → Tier 2.
- **Redis cache backend for throttles across gunicorn workers** → deferred; rationale in §Risks. The current `AnonRateThrottle` works single-worker in dev, and the project has no real clients yet.
- **`drf-spectacular` / OpenAPI schema / Swagger UI** → Tier 2 engineering hygiene.
- **Ruff / mypy / black / pytest migration / CI pipeline** → Tier 2 engineering hygiene.
- **Application withdrawal endpoint** → Tier 2 product spec (small but orthogonal; keeping it out lets this plan stay focused).
- **Sentry / error monitoring, structured logging, health-check endpoint** → Tier 2.

## Current-State Summary

After the Tier 0 merge:

- DRF has no `DEFAULT_PAGINATION_CLASS` — all list endpoints return unbounded arrays. `API_DOCUMENTATION.md` claims pagination exists; it doesn't.
- No `corsheaders` middleware or app. Any browser frontend on a different origin cannot call the API.
- `JobPostViewSet.get_queryset()` supports only ad-hoc `?search=` (title/description `icontains`) and `?city=`. No typed filters, no ordering, no skill-based search.
- `JobPost` list endpoints will issue 1 + N × (company + job_type + job_location) queries — at `PAGE_SIZE=20` that's 1 + 60 = 61 queries per page, before application code hits `required_skills`.
- `settings.py` has `SECURE_SSL_REDIRECT = False` hardcoded. `SECURE_HSTS_*`, `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS`, `SECURE_REFERRER_POLICY` are all at Django defaults (mostly unset).

## Requirements

### R1 — Pagination

**R1.1** `REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS']` = `'jobApp.pagination.StandardResultsSetPagination'`.
**R1.2** `REST_FRAMEWORK['PAGE_SIZE']` = `20`.
**R1.3** Every list endpoint in the project returns the shape `{"count": int, "next": str|null, "previous": str|null, "results": [...]}`.
**R1.4** Clients may override page size via `?page_size=N`, capped at `100`. Values over the cap silently clamp (not 400).
**R1.5** A custom `StandardResultsSetPagination(PageNumberPagination)` class in `jobApp/pagination.py` enforces `page_size_query_param = 'page_size'` and `max_page_size = 100`.

### R2 — CORS

**R2.1** `django-cors-headers` added to `pyproject.toml`.
**R2.2** `corsheaders` registered in `INSTALLED_APPS`. `corsheaders.middleware.CorsMiddleware` inserted **before** `django.middleware.common.CommonMiddleware` in `MIDDLEWARE` (django-cors-headers docs: must be before CommonMiddleware).
**R2.3** `config.py` exposes `CORS_ALLOWED_ORIGINS: list[str]` parsed from the `CORS_ALLOWED_ORIGINS` env var (comma-separated). Empty list → CORS middleware is a no-op.
**R2.4** When `DEBUG=True` **and** `CORS_ALLOWED_ORIGINS` is empty, `CORS_ALLOW_ALL_ORIGINS = True`. In any other case it stays `False`.
**R2.5** `CORS_ALLOW_CREDENTIALS = True` so JWT cookies work if the frontend switches to cookie auth later.
**R2.6** `.env.example` documents `CORS_ALLOWED_ORIGINS=http://localhost:3000`.

### R3 — Filtering, search, and ordering on `JobPostViewSet`

**R3.1** `django-filter` added to `pyproject.toml` and to `INSTALLED_APPS` as `'django_filters'`.
**R3.2** `REST_FRAMEWORK['DEFAULT_FILTER_BACKENDS']` set to:
```python
[
    'django_filters.rest_framework.DjangoFilterBackend',
    'rest_framework.filters.SearchFilter',
    'rest_framework.filters.OrderingFilter',
]
```
**R3.3** `JobPostViewSet` declares a custom `JobPostFilter(django_filters.FilterSet)` in `apps/jobs/filters.py` supporting:
  - `job_type` (exact FK)
  - `company` (exact FK)
  - `salary_type` (choice)
  - `is_published` (bool, admin/company use)
  - `city` (icontains on `job_location__city`)
  - `country` (exact on `job_location__country`)
  - `salary_min_gte` → `salary_min__gte`
  - `salary_max_lte` → `salary_max__lte`
  - `deadline_before` → `deadline_date__lte`
  - `required_skill` → exact FK on `required_skills__skill_set`
Plus:
  - `search_fields = ['job_title', 'job_description', 'company__company_name']`
  - `ordering_fields = ['created_at', 'salary_max', 'salary_min', 'deadline_date']`
  - `ordering = ['-created_at']` (default)

**R3.4** The existing ad-hoc `?search=` and `?city=` handling in `JobPostViewSet.get_queryset()` is removed — those params are now handled by the filter backends.

### R4 — N+1 query elimination

**R4.1** `JobPostViewSet.get_queryset()` returns a queryset pre-optimized with:
```python
.select_related('company', 'company__business_stream', 'job_type', 'job_location')
.prefetch_related('required_skills__skill_set')
```

**R4.2** `JobPostActivityViewSet.get_queryset()` uses:
```python
.select_related('job_post__company', 'user_account')
```

**R4.3** `CompanyViewSet.get_queryset()` uses:
```python
.select_related('user_account', 'business_stream')
.prefetch_related('images')
```

**R4.4** `SeekerProfileViewSet`, `EducationDataViewSet`, `ExperienceDataViewSet`, `SeekerSkillSetViewSet` each `.select_related('user_account')` (and `skill_set` where present).

**R4.5** Tests lock a ceiling on query count for each list endpoint: create 50 rows, wrap the request in `django.test.utils.CaptureQueriesContext`, and `assertLessEqual(len(ctx), 10)`. (Django's built-in `assertNumQueries` asserts an *exact* count, so it produces false failures when the real count is below the budget — use the capture-context pattern instead.)

### R5 — Production security headers

**R5.1** `config.py` exposes:
- `SECURE_SSL_REDIRECT: bool` (default `False`)
- `SECURE_HSTS_SECONDS: int` (default `0`)
- `SECURE_HSTS_INCLUDE_SUBDOMAINS: bool` (default `True`)
- `SECURE_HSTS_PRELOAD: bool` (default `True`)
- `SECURE_PROXY_SSL_HEADER: tuple[str, str] | None` parsed from env `SECURE_PROXY_SSL_HEADER="HTTP_X_FORWARDED_PROTO=https"` (format `HEADER=VALUE`, empty → `None`)
- `CSRF_TRUSTED_ORIGINS: list[str]` (comma-separated)
- `SESSION_COOKIE_SECURE: bool` (default: `not DEBUG`)
- `CSRF_COOKIE_SECURE: bool` (default: `not DEBUG`)

**R5.2** `settings.py` imports and uses these directly. The hardcoded `SECURE_SSL_REDIRECT = False`, `CSRF_COOKIE_SECURE = True`, `SESSION_COOKIE_SECURE = True` block in the current `settings.py` is removed.

**R5.3** Always-on (not env-driven):
- `SECURE_CONTENT_TYPE_NOSNIFF = True`
- `SECURE_REFERRER_POLICY = 'same-origin'`
- `X_FRAME_OPTIONS = 'DENY'`

**R5.4** `.env.example` documents the new keys with sane production-shaped examples (commented out for dev).

### R6 — Test coverage for R1–R5

All new tests under existing `apps/*/tests.py` files. Django's `manage.py test` runs them.

**R6.1 — Pagination**
- `test_list_paginates_by_default`: create 25 job types, GET list, assert `response.data` has `count=25`, `results` length `20`, `next` present.
- `test_custom_page_size`: `?page_size=5` returns 5 results.
- `test_page_size_cap`: `?page_size=500` returns at most 100.

**R6.2 — CORS**
- `test_cors_preflight_from_allowed_origin`: `OPTIONS /api/v1/accounts/login/` with `Origin: http://localhost:3000` (allowed) returns `Access-Control-Allow-Origin: http://localhost:3000`.
- `test_cors_preflight_from_disallowed_origin`: same but with `Origin: http://evil.example.com` returns no `Access-Control-Allow-Origin` header.

**R6.3 — Filters / search / ordering**
- `test_filter_by_job_type`: two job types, three posts, `?job_type=<id>` returns only matching.
- `test_filter_by_city`: three posts in different cities, `?city=manila` case-insensitive match.
- `test_filter_by_salary_range`: `?salary_min_gte=1000&salary_max_lte=5000` returns only matching.
- `test_search_by_title`: `?search=developer` returns posts with "developer" in title or description.
- `test_ordering_by_salary_max_desc`: `?ordering=-salary_max` returns highest first.

**R6.4 — N+1**
- `test_job_post_list_query_count`: create 50 published job posts (with distinct companies, job_types, locations), `assertNumQueries(<= 10)` on `GET /api/v1/jobs/job-posts/`.
- `test_company_list_query_count`: 30 companies with images, `assertNumQueries(<= 10)` on `GET /api/v1/companies/profile/`.

**R6.5 — Security headers**
- `test_hsts_header_present_when_configured`: `@override_settings(SECURE_HSTS_SECONDS=3600, SECURE_SSL_REDIRECT=False)` → `Strict-Transport-Security` in response.
- `test_x_frame_options_deny`: any response has `X-Frame-Options: DENY`.
- `test_content_type_nosniff`: any response has `X-Content-Type-Options: nosniff`.
- `test_referrer_policy_same_origin`: any response has `Referrer-Policy: same-origin`.

### R7 — Documentation

**R7.1** `Readme.md` gets a short "API conventions" section: pagination shape, allowed ordering fields, search params.
**R7.2** `CLAUDE.md` records the rule: "any ViewSet returning FK data must `select_related`; any reverse-FK or M2M must `prefetch_related`. Lock the query count with `assertNumQueries` in the test suite."
**R7.3** `.env.example` updated with CORS + security-header keys.
**R7.4** `API_DOCUMENTATION.md` — scope the update to clarify that pagination is now real (fix the claim that's currently false). Full endpoint re-documentation is out of scope (Tier 2 when `drf-spectacular` lands).

## Acceptance Criteria

1. `uv run python manage.py test` passes; new R6 tests run green.
2. `GET /api/v1/jobs/job-posts/` returns `{count, next, previous, results}`.
3. `GET /api/v1/jobs/job-posts/?search=dev&ordering=-salary_max&page_size=5&city=manila` works end-to-end and returns at most 5 filtered, ordered results.
4. With 50 `JobPost` rows seeded, `CaptureQueriesContext` records ≤ 10 queries on `GET /api/v1/jobs/job-posts/`.
5. A browser fetch from `http://localhost:3000` to the API succeeds when `CORS_ALLOWED_ORIGINS=http://localhost:3000` is set; fails from any other origin.
6. With prod env (`DEBUG=false SECURE_SSL_REDIRECT=true SECURE_HSTS_SECONDS=31536000 ...`), `manage.py check --deploy` returns zero critical warnings. Remaining warnings are explicitly non-security (e.g., `STATICFILES_STORAGE` choice, which is Tier 2).
7. `grep "__all__" apps/` still returns no results (no regression on Tier 0).

## Risks & Mitigations

- **Redis deferred.** `AnonRateThrottle` uses Django's default local-memory cache. Under multi-worker gunicorn, each worker has an independent counter, so the effective rate limit becomes `rate × num_workers`. Mitigation: documented in the spec; Redis gets a dedicated Tier 2 item. For the current stage (dev + single-worker staging), this is acceptable.
- **Pagination default breaks unpaginated clients.** None exist yet. If one appears later, point them at `?page_size=100` or add a `limit=0` escape hatch (not doing that now — YAGNI).
- **`prefetch_related` on `required_skills__skill_set` fires 2 extra queries.** This is by design (one per prefetch level) and still constant regardless of row count. The `assertNumQueries(<= 10)` budget includes them.
- **`django-cors-headers` middleware ordering.** Must be before `CommonMiddleware`. Getting this wrong silently breaks CORS. The test in R6.2 catches it.
- **Filter field names must match model fields.** Getting `salary_min_gte` wrong (e.g., typing `salary_min__gte` in filter_fields) returns a 500. The R6.3 tests cover this.

## Out-of-Scope (captured for Tier 2)

- Redis cache backend (`django-redis`) + `CACHES` config.
- File upload pipeline (resumes to S3, company images).
- Email verification, password reset, invite flows.
- `drf-spectacular` → OpenAPI 3 schema → Swagger/Redoc UI.
- `ruff`, `mypy`, `black`, `isort`, `pytest-django`, `pytest-cov`, `coverage.py`.
- Sentry / structured logging / health-check endpoint.
- CI pipeline (`.github/workflows/ci.yml`).
- Dockerfile / docker-compose.yml.
- Application-withdrawal endpoint (`POST /job-applications/{id}/withdraw/`).
