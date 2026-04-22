# API Usability — Tier 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all Tier 1 requirements from `docs/superpowers/specs/2026-04-17-api-usability-tier-1.md` — pagination, CORS, filter/search/ordering on job posts, eliminate N+1 on list endpoints, wire production security headers through env-driven config.

**Architecture:** Additive on top of the Tier 0 security-hardened baseline. New deps (`django-cors-headers`, `django-filter`) wired through `pyproject.toml`. A `StandardResultsSetPagination` class in `jobApp/pagination.py` caps page sizes. A `JobPostFilter` FilterSet in `apps/jobs/filters.py` handles typed filters. All env access stays routed through `config.py` (Tier 0 rule). N+1 fixed via `select_related` / `prefetch_related` on every list-returning ViewSet.

**Tech Stack:** Django 5.2 + DRF 3.16, PostgreSQL, `django-cors-headers`, `django-filter`, simplejwt — all managed by uv via `pyproject.toml` + `uv.lock`.

---

## Phase 1 — Dependencies

### Task 1: Add `django-cors-headers` and `django-filter` to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Run `uv add`**

Run: `uv add django-cors-headers django-filter`
Expected: `pyproject.toml` grows two lines in `dependencies`; `uv.lock` regenerates; `.venv/` picks up the two packages.

- [ ] **Step 2: Verify both import cleanly**

Run: `uv run python -c "import corsheaders; import django_filters; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add django-cors-headers and django-filter"
```

---

## Phase 2 — Pagination

### Task 2: `StandardResultsSetPagination` class + settings wiring

**Files:**
- Create: `jobApp/pagination.py`
- Modify: `jobApp/settings.py` (REST_FRAMEWORK dict)
- Modify: `apps/jobs/tests.py` (append `PaginationTests` class)

- [ ] **Step 1: Create `jobApp/pagination.py`**

```python
from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
```

- [ ] **Step 2: Wire into `REST_FRAMEWORK`**

In `jobApp/settings.py`, add two keys to the `REST_FRAMEWORK` dict (place them near the existing `DEFAULT_AUTHENTICATION_CLASSES` block):

```python
    'DEFAULT_PAGINATION_CLASS': 'jobApp.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 20,
```

- [ ] **Step 3: Write failing tests**

Append to `apps/jobs/tests.py`:

```python
class PaginationTests(APITestCase):
    def setUp(self):
        for i in range(25):
            JobType.objects.create(job_type_name=f"Type {i}")

    def test_list_paginates_by_default(self):
        r = self.client.get("/api/v1/jobs/job-types/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 25)
        self.assertEqual(len(r.data["results"]), 20)
        self.assertIsNotNone(r.data["next"])

    def test_custom_page_size(self):
        r = self.client.get("/api/v1/jobs/job-types/?page_size=5")
        self.assertEqual(len(r.data["results"]), 5)

    def test_page_size_cap(self):
        r = self.client.get("/api/v1/jobs/job-types/?page_size=500")
        self.assertLessEqual(len(r.data["results"]), 100)
```

- [ ] **Step 4: Run tests**

Run: `uv run python manage.py test apps.jobs.tests.PaginationTests -v 2`
Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add jobApp/pagination.py jobApp/settings.py apps/jobs/tests.py
git commit -m "feat(api): add StandardResultsSetPagination with max_page_size=100"
```

---

## Phase 3 — CORS

### Task 3: `config.py` exposes `CORS_ALLOWED_ORIGINS`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add CORS constants**

Append to the `--- Django core ---` block in `config.py`:

```python
# --- CORS -----------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = _csv("CORS_ALLOWED_ORIGINS")
# When running DEBUG and no origins are explicitly allowed, open CORS for local dev.
CORS_ALLOW_ALL_ORIGINS: bool = DEBUG and not CORS_ALLOWED_ORIGINS
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from config import CORS_ALLOWED_ORIGINS, CORS_ALLOW_ALL_ORIGINS; print(CORS_ALLOWED_ORIGINS, CORS_ALLOW_ALL_ORIGINS)"`
(With a dummy `.env`, expected: `[] True` if DEBUG=true, else `[] False`.)

---

### Task 4: Wire `corsheaders` into Django

**Files:**
- Modify: `jobApp/settings.py` (INSTALLED_APPS, MIDDLEWARE, new CORS_* settings)
- Modify: `.env.example`

- [ ] **Step 1: Add app to `INSTALLED_APPS`**

In `jobApp/settings.py`, insert `'corsheaders',` immediately after `'rest_framework_simplejwt.token_blacklist',` so the block reads:

```python
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'apps.accounts.apps.AccountsConfig',
```

- [ ] **Step 2: Insert middleware before `CommonMiddleware`**

In `jobApp/settings.py`, modify the `MIDDLEWARE` list so it reads:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

- [ ] **Step 3: Import and use CORS settings**

At the top of `jobApp/settings.py`, extend the `from config import (...)` tuple with `CORS_ALLOWED_ORIGINS` and `CORS_ALLOW_ALL_ORIGINS`.

Then, near the bottom of `settings.py` (after the `DATABASES` block), add:

```python
# CORS
CORS_ALLOW_CREDENTIALS = True
```

(`CORS_ALLOWED_ORIGINS` and `CORS_ALLOW_ALL_ORIGINS` are already module-level names thanks to the import — no reassignment needed.)

- [ ] **Step 4: Update `.env.example`**

Append to `.env.example`:

```
# CORS (comma-separated list; empty + DEBUG=true enables CORS_ALLOW_ALL_ORIGINS)
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

- [ ] **Step 5: Smoke-test boot**

Run: `SECRET_KEY=test DB_NAME=x DB_USER=x DB_PASSWORD=x DEBUG=true uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add config.py jobApp/settings.py .env.example
git commit -m "feat(api): wire django-cors-headers with env-driven CORS_ALLOWED_ORIGINS"
```

---

### Task 5: CORS tests

**Files:**
- Modify: `apps/accounts/tests.py` (append `CorsTests` class)

- [ ] **Step 1: Write test**

Append to `apps/accounts/tests.py`:

```python
from django.test import override_settings


@override_settings(
    CORS_ALLOWED_ORIGINS=["http://localhost:3000"],
    CORS_ALLOW_ALL_ORIGINS=False,
)
class CorsTests(APITestCase):
    def test_cors_preflight_from_allowed_origin(self):
        r = self.client.options(
            "/api/v1/accounts/login/",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"),
                         "http://localhost:3000")

    def test_cors_preflight_from_disallowed_origin(self):
        r = self.client.options(
            "/api/v1/accounts/login/",
            HTTP_ORIGIN="http://evil.example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)
```

- [ ] **Step 2: Run**

Run: `uv run python manage.py test apps.accounts.tests.CorsTests -v 2`
Expected: both PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/accounts/tests.py
git commit -m "test(api): CORS preflight allowed/denied"
```

---

## Phase 4 — Filtering, search, ordering

### Task 6: `JobPostFilter` + settings

**Files:**
- Create: `apps/jobs/filters.py`
- Modify: `jobApp/settings.py` (INSTALLED_APPS)
- Modify: `jobApp/settings.py` (REST_FRAMEWORK.DEFAULT_FILTER_BACKENDS)
- Modify: `apps/jobs/views.py` (wire filter + ordering + search on `JobPostViewSet`)

- [ ] **Step 1: Register `django_filters` app**

In `INSTALLED_APPS`, insert `'django_filters',` immediately after `'corsheaders',` so:

```python
    'corsheaders',
    'django_filters',
    'apps.accounts.apps.AccountsConfig',
```

- [ ] **Step 2: Add filter backends to REST_FRAMEWORK**

In the `REST_FRAMEWORK` dict, add:

```python
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
```

- [ ] **Step 3: Create `apps/jobs/filters.py`**

```python
import django_filters

from .models import JobPost


class JobPostFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(
        field_name="job_location__city", lookup_expr="icontains"
    )
    country = django_filters.CharFilter(
        field_name="job_location__country", lookup_expr="exact"
    )
    salary_min_gte = django_filters.NumberFilter(
        field_name="salary_min", lookup_expr="gte"
    )
    salary_max_lte = django_filters.NumberFilter(
        field_name="salary_max", lookup_expr="lte"
    )
    deadline_before = django_filters.DateFilter(
        field_name="deadline_date", lookup_expr="lte"
    )
    required_skill = django_filters.UUIDFilter(
        field_name="required_skills__skill_set"
    )

    class Meta:
        model = JobPost
        fields = ["job_type", "company", "salary_type", "is_published"]
```

- [ ] **Step 4: Wire into `JobPostViewSet`**

In `apps/jobs/views.py`, add the filter imports at the top:

```python
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .filters import JobPostFilter
```

On the `JobPostViewSet` class body, add:

```python
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobPostFilter
    search_fields = ['job_title', 'job_description', 'company__company_name']
    ordering_fields = ['created_at', 'salary_max', 'salary_min', 'deadline_date']
    ordering = ['-created_at']
```

Then **remove** the ad-hoc `search` and `city` handling from `JobPostViewSet.get_queryset()`. After the edit, `get_queryset` returns just the permission-filtered queryset (the filter backends take over from there):

```python
    def get_queryset(self):
        user = self.request.user
        queryset = JobPost.objects.all()
        if user.is_staff or user.is_superuser:
            pass
        elif user.is_authenticated and user.user_type == 'company':
            queryset = queryset.filter(company__user_account=user)
        else:
            queryset = queryset.filter(is_published=True, is_active=True)
        return queryset
```

- [ ] **Step 5: Smoke-test**

Run: `SECRET_KEY=test DB_NAME=x DB_USER=x DB_PASSWORD=x DEBUG=true uv run python manage.py check`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add jobApp/settings.py apps/jobs/filters.py apps/jobs/views.py
git commit -m "feat(jobs): DjangoFilterBackend + search + ordering on JobPostViewSet"
```

---

### Task 7: Filter / search / ordering tests

**Files:**
- Modify: `apps/jobs/tests.py` (append `JobPostFilterTests` class)

- [ ] **Step 1: Append test class**

```python
class JobPostFilterTests(APITestCase):
    def setUp(self):
        owner = UserAccount.objects.create_user(
            email="filt-owner@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        stream = BusinessStream.objects.create(business_stream_name="Filt Tech")
        company = Company.objects.create(
            user_account=owner, company_name="FiltCo", business_stream=stream)
        self.ft = JobType.objects.create(job_type_name="FiltFT")
        self.pt = JobType.objects.create(job_type_name="FiltPT")
        self.manila = JobLocation.objects.create(city="Manila", country="PH")
        self.cebu = JobLocation.objects.create(city="Cebu", country="PH")
        self.tokyo = JobLocation.objects.create(city="Tokyo", country="JP")

        JobPost.objects.create(
            company=company, job_type=self.ft, job_location=self.manila,
            job_title="Senior Developer", job_description="python",
            salary_min=1000, salary_max=5000)
        JobPost.objects.create(
            company=company, job_type=self.pt, job_location=self.cebu,
            job_title="Junior Dev", job_description="...",
            salary_min=500, salary_max=1500)
        JobPost.objects.create(
            company=company, job_type=self.ft, job_location=self.tokyo,
            job_title="Staff Engineer", job_description="leadership",
            salary_min=8000, salary_max=12000)

    def _titles(self, response):
        return sorted(j["job_title"] for j in response.data["results"])

    def test_filter_by_job_type(self):
        r = self.client.get(f"/api/v1/jobs/job-posts/?job_type={self.ft.id}")
        self.assertEqual(self._titles(r), ["Senior Developer", "Staff Engineer"])

    def test_filter_by_city(self):
        r = self.client.get("/api/v1/jobs/job-posts/?city=manila")
        self.assertEqual(self._titles(r), ["Senior Developer"])

    def test_filter_by_salary_range(self):
        r = self.client.get(
            "/api/v1/jobs/job-posts/?salary_min_gte=1000&salary_max_lte=5000"
        )
        self.assertEqual(self._titles(r), ["Senior Developer"])

    def test_search_by_title(self):
        r = self.client.get("/api/v1/jobs/job-posts/?search=developer")
        # "developer" matches "Senior Developer" and "Junior Dev" only if
        # the word is present — assert the senior match explicitly.
        titles = [j["job_title"] for j in r.data["results"]]
        self.assertIn("Senior Developer", titles)
        self.assertNotIn("Staff Engineer", titles)

    def test_ordering_by_salary_max_desc(self):
        r = self.client.get("/api/v1/jobs/job-posts/?ordering=-salary_max")
        titles = [j["job_title"] for j in r.data["results"]]
        self.assertEqual(titles[0], "Staff Engineer")
```

- [ ] **Step 2: Run**

Run: `uv run python manage.py test apps.jobs.tests.JobPostFilterTests -v 2`
Expected: all five PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/jobs/tests.py
git commit -m "test(jobs): filter / search / ordering on JobPostViewSet"
```

---

## Phase 5 — N+1 elimination

### Task 8: `select_related` / `prefetch_related` on JobPost

**Files:**
- Modify: `apps/jobs/views.py`
- Modify: `apps/jobs/tests.py` (append `JobPostQueryCountTests`)

- [ ] **Step 1: Write failing test**

Append to `apps/jobs/tests.py`:

```python
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext


QUERY_BUDGET = 10  # ceiling; tune downward as prefetches are added


class JobPostQueryCountTests(APITestCase):
    def setUp(self):
        owner = UserAccount.objects.create_user(
            email="qc-owner@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        stream = BusinessStream.objects.create(business_stream_name="QC Tech")
        company = Company.objects.create(
            user_account=owner, company_name="QCCo", business_stream=stream)
        jt = JobType.objects.create(job_type_name="QC FT")
        loc = JobLocation.objects.create(city="QCity", country="PH")
        for i in range(50):
            JobPost.objects.create(
                company=company, job_type=jt, job_location=loc,
                job_title=f"Job {i}", job_description="...")

    def test_job_post_list_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/api/v1/jobs/job-posts/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 50)
        self.assertLessEqual(
            len(ctx), QUERY_BUDGET,
            f"Query count {len(ctx)} exceeds budget {QUERY_BUDGET}",
        )
```

`CaptureQueriesContext` is the DRF-compatible pattern: `assertNumQueries` asserts an *exact* count, which produces false failures if the actual count is below the ceiling. We want a ceiling.

- [ ] **Step 2: Run, confirm failure**

Run: `uv run python manage.py test apps.jobs.tests.JobPostQueryCountTests -v 2`
Expected: FAIL — current `get_queryset` has no `select_related`, query count will exceed `QUERY_BUDGET=10`. The assertion message should read something like `Query count 61 exceeds budget 10`.

- [ ] **Step 3: Add prefetches**

In `apps/jobs/views.py`, change `JobPostViewSet.get_queryset()` to:

```python
    def get_queryset(self):
        user = self.request.user
        queryset = (
            JobPost.objects
            .select_related(
                'company', 'company__business_stream',
                'job_type', 'job_location',
            )
            .prefetch_related('required_skills__skill_set')
        )
        if user.is_staff or user.is_superuser:
            pass
        elif user.is_authenticated and user.user_type == 'company':
            queryset = queryset.filter(company__user_account=user)
        else:
            queryset = queryset.filter(is_published=True, is_active=True)
        return queryset
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run python manage.py test apps.jobs.tests.JobPostQueryCountTests -v 2`
Expected: PASS. If the query count is still above 10, inspect `ctx.captured_queries` and add more prefetches — don't raise `QUERY_BUDGET` silently.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/views.py apps/jobs/tests.py
git commit -m "perf(jobs): eliminate N+1 on JobPostViewSet list"
```

---

### Task 9: `select_related` / `prefetch_related` on other viewsets

**Files:**
- Modify: `apps/jobs/views.py` (JobPostActivityViewSet, JobPostSkillSetViewSet)
- Modify: `apps/companies/views.py` (CompanyViewSet, CompanyImagesViewSet)
- Modify: `apps/seekers/views.py` (all four owned viewsets)
- Modify: `apps/companies/tests.py` (append `CompanyQueryCountTests`)

- [ ] **Step 1: Write failing test for companies**

Append to `apps/companies/tests.py`:

```python
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.companies.models import CompanyImages


COMPANY_QUERY_BUDGET = 10


class CompanyQueryCountTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="qc-seeker@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        stream = BusinessStream.objects.create(business_stream_name="QC Finance")
        for i in range(30):
            owner = UserAccount.objects.create_user(
                email=f"qc-co{i}@example.com",
                password="Str0ng-Password!",
                user_type="company",
            )
            co = Company.objects.create(
                user_account=owner, company_name=f"Co {i}", business_stream=stream)
            CompanyImages.objects.create(company=co, image_url="https://x.invalid/a.png")

    def test_company_list_query_count(self):
        token = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/api/v1/companies/profile/")
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(
            len(ctx), COMPANY_QUERY_BUDGET,
            f"Query count {len(ctx)} exceeds budget {COMPANY_QUERY_BUDGET}",
        )
```

Same rationale as the jobs query-count test: `assertNumQueries` asserts an *exact* count, which produces false failures when the optimized query count is below the ceiling. `CaptureQueriesContext` + `assertLessEqual` enforces the budget as a ceiling.

- [ ] **Step 2: Add prefetches to `CompanyViewSet.get_queryset`**

In `apps/companies/views.py`, wrap the `Company.objects.*` returns with:

```python
    def get_queryset(self):
        user = self.request.user
        base = (
            Company.objects
            .select_related('user_account', 'business_stream')
            .prefetch_related('images')
        )
        if user.is_staff or user.is_superuser:
            return base
        elif user.user_type == 'company':
            return base.filter(user_account=user)
        else:
            return base.filter(status='active')
```

- [ ] **Step 3: Add `select_related` to `CompanyImagesViewSet.get_queryset`**

Same file, `CompanyImagesViewSet`:

```python
    def get_queryset(self):
        user = self.request.user
        base = CompanyImages.objects.select_related('company', 'company__user_account')
        if user.is_staff or user.is_superuser:
            return base
        elif user.user_type == 'company':
            return base.filter(company__user_account=user)
        else:
            return base.filter(company__status='active')
```

- [ ] **Step 4: Add prefetches to `JobPostActivityViewSet` and `JobPostSkillSetViewSet`**

In `apps/jobs/views.py`:

```python
    # JobPostActivityViewSet.get_queryset:
    def get_queryset(self):
        user = self.request.user
        base = JobPostActivity.objects.select_related(
            'user_account', 'job_post', 'job_post__company',
        )
        if user.is_staff or user.is_superuser:
            return base
        elif user.user_type == 'job_seeker':
            return base.filter(user_account=user)
        elif user.user_type == 'company':
            return base.filter(job_post__company__user_account=user)
        else:
            return base.none()

    # JobPostSkillSetViewSet.get_queryset:
    def get_queryset(self):
        user = self.request.user
        base = JobPostSkillSet.objects.select_related('job_post', 'skill_set')
        if user.is_staff or user.is_superuser:
            return base
        elif user.is_authenticated and user.user_type == 'company':
            return base.filter(job_post__company__user_account=user)
        else:
            return base.filter(job_post__is_published=True)
```

- [ ] **Step 5: Add `select_related('user_account')` to seeker viewsets**

In `apps/seekers/views.py`, update each of `SeekerProfileViewSet`, `EducationDataViewSet`, `ExperienceDataViewSet`, `SeekerSkillSetViewSet` so their `get_queryset` returns start with `.select_related('user_account')`. For `SeekerSkillSetViewSet`, also `'skill_set'`. Leave `SkillSetViewSet` alone (no user_account FK).

- [ ] **Step 6: Run tests**

Run: `uv run python manage.py test -v 2`
Expected: every test passes including the new `CompanyQueryCountTests.test_company_list_query_count`.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/views.py apps/companies/views.py apps/companies/tests.py apps/seekers/views.py
git commit -m "perf(api): add select_related/prefetch_related across list viewsets"
```

---

## Phase 6 — Production security headers

### Task 10: Extend `config.py` with security-header constants

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add tuple parser helper**

Near the `_bool` and `_csv` helpers in `config.py`:

```python
def _proxy_header(name: str) -> tuple[str, str] | None:
    raw = os.getenv(name)
    if not raw or "=" not in raw:
        return None
    header, value = raw.split("=", 1)
    return (header.strip(), value.strip())
```

- [ ] **Step 2: Add the security constants**

Append a new section to `config.py`:

```python
# --- Production security headers ---------------------------------------------
SECURE_SSL_REDIRECT: bool = _bool("SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS: int = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = _bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
)
SECURE_HSTS_PRELOAD: bool = _bool("SECURE_HSTS_PRELOAD", default=True)
SECURE_PROXY_SSL_HEADER: tuple[str, str] | None = _proxy_header(
    "SECURE_PROXY_SSL_HEADER"
)
CSRF_TRUSTED_ORIGINS: list[str] = _csv("CSRF_TRUSTED_ORIGINS")
SESSION_COOKIE_SECURE: bool = _bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE: bool = _bool("CSRF_COOKIE_SECURE", default=not DEBUG)
```

- [ ] **Step 3: Verify imports**

Run: `SECRET_KEY=test DB_NAME=x DB_USER=x DB_PASSWORD=x DEBUG=true uv run python -c "from config import SECURE_SSL_REDIRECT, SECURE_HSTS_SECONDS, SECURE_PROXY_SSL_HEADER; print(SECURE_SSL_REDIRECT, SECURE_HSTS_SECONDS, SECURE_PROXY_SSL_HEADER)"`
Expected: `False 0 None`.

---

### Task 11: Wire security constants into `settings.py`

**Files:**
- Modify: `jobApp/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Extend the `from config import (...)` block**

Add these names: `CSRF_COOKIE_SECURE, CSRF_TRUSTED_ORIGINS, SECURE_HSTS_INCLUDE_SUBDOMAINS, SECURE_HSTS_PRELOAD, SECURE_HSTS_SECONDS, SECURE_PROXY_SSL_HEADER, SECURE_SSL_REDIRECT, SESSION_COOKIE_SECURE`.

- [ ] **Step 2: Delete the hardcoded security block**

Remove the existing block:

```python
# Security settings
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = False
```

The three names now come from the import above, so no reassignment is needed — but **add** the always-on headers:

```python
# Always-on security headers (not env-driven)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
```

- [ ] **Step 3: Handle the `None`-default `SECURE_PROXY_SSL_HEADER`**

Django only respects `SECURE_PROXY_SSL_HEADER` when it's a tuple; `None` means "do nothing." Django tolerates `None`, so just assign:

```python
# SECURE_PROXY_SSL_HEADER is imported from config; it is None when unset.
```

No extra code needed — the import already made the name available.

- [ ] **Step 4: Update `.env.example`**

Append:

```
# Production security headers (leave defaults for local dev)
# SECURE_SSL_REDIRECT=true
# SECURE_HSTS_SECONDS=31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS=true
# SECURE_HSTS_PRELOAD=true
# SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO=https
# CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
```

- [ ] **Step 5: Smoke-test**

Run: `SECRET_KEY=test DB_NAME=x DB_USER=x DB_PASSWORD=x DEBUG=false ALLOWED_HOSTS=example.com SECURE_SSL_REDIRECT=true SECURE_HSTS_SECONDS=31536000 uv run python manage.py check --deploy`
Expected: warnings only for `STATICFILES_STORAGE` / `DEBUG_PROPAGATE_EXCEPTIONS` (Tier 2 territory). No security warnings for SSL redirect, HSTS, cookies, or content-type sniffing.

- [ ] **Step 6: Commit**

```bash
git add config.py jobApp/settings.py .env.example
git commit -m "feat(security): env-driven SSL/HSTS/CSRF + always-on headers"
```

---

### Task 12: Security-header tests

**Files:**
- Modify: `apps/accounts/tests.py` (append `SecurityHeaderTests`)

- [ ] **Step 1: Append test class**

```python
class SecurityHeaderTests(APITestCase):
    def test_x_frame_options_deny(self):
        r = self.client.get("/api/v1/accounts/register/")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")

    def test_content_type_nosniff(self):
        r = self.client.get("/api/v1/accounts/register/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")

    def test_referrer_policy_same_origin(self):
        r = self.client.get("/api/v1/accounts/register/")
        self.assertEqual(r.headers.get("Referrer-Policy"), "same-origin")

    @override_settings(SECURE_HSTS_SECONDS=3600, SECURE_SSL_REDIRECT=False)
    def test_hsts_header_present_when_configured(self):
        # SecurityMiddleware only sets HSTS on HTTPS requests;
        # APIClient can simulate that via HTTPS=on / wsgi.url_scheme.
        r = self.client.get("/api/v1/accounts/register/", secure=True)
        self.assertIn("max-age=3600", r.headers.get("Strict-Transport-Security", ""))
```

- [ ] **Step 2: Run**

Run: `uv run python manage.py test apps.accounts.tests.SecurityHeaderTests -v 2`
Expected: all four PASS. If HSTS fails, verify `secure=True` actually flips `wsgi.url_scheme` in the test client (some Django versions use `**{"wsgi.url_scheme": "https"}` instead).

- [ ] **Step 3: Commit**

```bash
git add apps/accounts/tests.py
git commit -m "test(security): X-Frame / nosniff / referrer / HSTS headers"
```

---

## Phase 7 — Documentation and audit

### Task 13: Document pagination, ordering, search in Readme + CLAUDE.md

**Files:**
- Modify: `Readme.md`
- Modify: `CLAUDE.md`
- Modify: `API_DOCUMENTATION.md` (pagination clarification)

- [ ] **Step 1: Append API Conventions section to `Readme.md`**

After the existing "API Documentation" section in `Readme.md`, add:

```markdown
## API Conventions

### Pagination

All list endpoints return:

```json
{
  "count": 123,
  "next": "http://host/api/v1/jobs/job-posts/?page=2",
  "previous": null,
  "results": [/* items */]
}
```

Override the page size with `?page_size=N` (max 100).

### Search, filter, ordering (jobs)

- `?search=<term>` — matches job title, description, and company name
- `?ordering=-created_at` — sort; valid fields: `created_at`, `salary_max`, `salary_min`, `deadline_date`
- Filters: `job_type`, `company`, `salary_type`, `is_published`, `city`, `country`, `salary_min_gte`, `salary_max_lte`, `deadline_before`, `required_skill`
```

- [ ] **Step 2: Add the query-optimization rule to `CLAUDE.md`**

Add to the Architecture section of `CLAUDE.md`:

```markdown
### Query hygiene

Any ViewSet returning FK data must `select_related(...)`. Any reverse-FK or M2M returned in the response must `prefetch_related(...)`. Lock the query count on new list endpoints with `CaptureQueriesContext` + `assertLessEqual(len(ctx), N)` — budget `≤ 10` per list response regardless of row count. Avoid `assertNumQueries` for this purpose: it asserts exact equality and produces false failures when the real count lands below the ceiling.
```

- [ ] **Step 3: Fix the pagination claim in `API_DOCUMENTATION.md`**

Find the line (use `grep -n "pagination" API_DOCUMENTATION.md`) and replace whatever vague pagination claim exists with:

```markdown
- **Pagination:** List endpoints return `{count, next, previous, results}`. Default `page_size=20`, max `100`. Override via `?page_size=N&page=M`.
```

- [ ] **Step 4: Commit**

```bash
git add Readme.md CLAUDE.md API_DOCUMENTATION.md
git commit -m "docs: document pagination, filters, ordering, and query-hygiene rule"
```

---

### Task 14: Final audit

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run python manage.py test`
Expected: all tests pass. Record the final count.

- [ ] **Step 2: Deploy check**

Run: `SECRET_KEY=test DB_NAME=x DB_USER=x DB_PASSWORD=x DEBUG=false ALLOWED_HOSTS=example.com SECURE_SSL_REDIRECT=true SECURE_HSTS_SECONDS=31536000 uv run python manage.py check --deploy`
Expected: no security-category warnings.

- [ ] **Step 3: Confirm no `__all__` regressions**

Run: `grep -rn "fields = '__all__'" apps/`
Expected: no output.

- [ ] **Step 4: Spot-check a list endpoint manually**

Boot the dev server and curl:

```bash
uv run python manage.py runserver &
sleep 2
curl -s 'http://localhost:8000/api/v1/jobs/job-posts/?page_size=5&ordering=-created_at' | head -50
```

Expected: JSON with `count`, `next`, `previous`, `results` (≤5 items).

- [ ] **Step 5: Commit the audit results (if any remaining doc tweaks needed)**

If steps 1–4 revealed nothing to change, skip the commit. Otherwise, write a `chore(audit): ...` commit with the fix.

---

## Self-Review Checklist

- [x] R1 pagination → Task 2.
- [x] R2 CORS → Tasks 3 (config), 4 (wiring), 5 (tests).
- [x] R3 filters/search/ordering → Tasks 6 (wiring), 7 (tests).
- [x] R4 N+1 → Tasks 8 (JobPost), 9 (the rest).
- [x] R5 security headers → Tasks 10 (config), 11 (settings wiring), 12 (tests).
- [x] R6 test coverage → tests in Tasks 2, 5, 7, 8, 9, 12.
- [x] R7 documentation → Task 13.
- [x] Acceptance criteria #1–7 → Task 14 audit.

No placeholders. Every code step contains the concrete code. Commits per task. Run commands with expected output included.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-17-api-usability-tier-1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, two-stage review, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
