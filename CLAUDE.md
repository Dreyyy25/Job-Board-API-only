# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Run from the repository root (where `manage.py` lives). Dependencies are managed by **uv** (Python 3.13 pinned via `.python-version`). Either activate the venv (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` otherwise) or prefix commands with `uv run`.

- Install / sync deps: `uv sync`
- Add a dependency: `uv add <package>` (writes to `pyproject.toml` + `uv.lock`)
- Run dev server: `uv run python manage.py runserver` (API served at `http://localhost:8000/api/v1/`)
- Make migrations: `uv run python manage.py makemigrations`
- Apply migrations: `uv run python manage.py migrate`
- Create superuser: `uv run python manage.py createsuperuser` (prompts for `email` + `user_type`; superusers default to `user_type='company'`)
- Run all tests: `uv run python manage.py test`
- Run tests for one app: `uv run python manage.py test apps.jobs`
- Run a single test: `uv run python manage.py test apps.jobs.tests.TestClassName.test_method`
- Django shell: `uv run python manage.py shell`

A `.env` file is required at the repo root. Required keys: `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (required); `DB_HOST`, `DB_PORT`, `DEBUG`, `ALLOWED_HOSTS`, `ADMIN_URL` (optional, see `.env.example`). `SECRET_KEY`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are read via `os.environ[...]` in `config.py` — the app crashes at import time if any of them are missing. PostgreSQL is required (not SQLite).

All env access goes through `config.py` at the repo root. `jobApp/settings.py` and `jobApp/urls.py` import plain Python constants from it. Do **not** add new `os.getenv()` calls scattered through the codebase — extend `config.py` instead.

## Architecture

Django 5.2 + DRF monolith with JWT auth. Four domain apps under `apps/`, each mounted under `/api/v1/<app>/` by `jobApp/urls.py`. The admin URL path is read from the `ADMIN_URL` env var (default `admin/`).

### Custom user model — the center of everything

`apps.accounts.UserAccount` (`AUTH_USER_MODEL = 'accounts.UserAccount'`) replaces Django's default user. Key properties that drive the rest of the system:

- UUID primary keys across every model in the project (not integer IDs).
- `USERNAME_FIELD = 'email'` — there is no `username` field.
- `user_type` is `'job_seeker'` or `'company'`. Most permission checks and queryset filters branch on this field, so always preserve it when touching auth flows.
- `CustomJWTAuthentication` (in `apps/accounts/authentication.py`) overrides SimpleJWT's `get_user` to load `UserAccount` by `user_id` from the token. Every `ViewSet` in the project sets `authentication_classes = [CustomJWTAuthentication]` — don't rely on DRF's default session auth for API endpoints.
- JWTs are minted manually in `register` / `login` views via `RefreshToken.for_user(user)` and enriched with `user_id`, `email`, and `user_type` claims.

### App responsibilities and cross-app links

- `apps.accounts` — `UserAccount`, auth (register/login/me), JWT setup. Everything else FK's into `UserAccount`.
- `apps.companies` — `Company` (OneToOne to `UserAccount` with `limit_choices_to={'user_type': 'company'}`), `BusinessStream`, `CompanyImages`.
- `apps.seekers` — `SeekerProfile` (OneToOne, PK = `UserAccount`, `limit_choices_to={'user_type': 'job_seeker'}`), `EducationData`, `ExperienceData`, `SkillSet`, `SeekerSkillSet`.
- `apps.jobs` — `JobType`, `JobLocation`, `JobPost` (FK → `Company`), `JobPostActivity` (applications: FK → `UserAccount` + `JobPost`, `unique_together`), `JobPostSkillSet` (FK → `JobPost` + `SkillSet` from `apps.seekers`).

`apps.jobs` imports from both `apps.companies` and `apps.seekers`, so those two apps must be importable before jobs. `INSTALLED_APPS` order in `jobApp/settings.py` reflects this.

### Permission pattern (repeated across every viewset)

Each app has its own `permissions.py`. The shared convention:

1. `has_permission` gates by authentication / HTTP method.
2. `has_object_permission` branches: admin (`is_staff` or `is_superuser`) → allow; then owner check via `obj.<...>.user_account.id == request.user.id`.
3. Reference data (`JobType`, `BusinessStream`, `SkillSet`) uses `IsAdminOrReadOnly` — public read, admin write.
4. ViewSets additionally narrow `get_queryset()` by `user_type`. For example `JobPostViewSet.get_queryset` returns all jobs for admins, the company's own jobs (including unpublished) for company users, and only `is_published=True, is_active=True` for everyone else. Object-level permission and queryset filtering both enforce access — keep them consistent when adding endpoints.

`perform_create` hooks auto-assign ownership: `CompanyViewSet` sets `user_account=request.user`, `JobPostViewSet` looks up the user's `Company` and sets it on the post (and 400s if none exists). Follow this pattern for any new owned resource.

### Routing

Each app exposes a DRF `DefaultRouter` plus a few function-based endpoints:

- `/api/v1/accounts/` — `users` viewset, plus `register/`, `login/`, `me/`, `token/refresh/`, `token/verify/`.
- `/api/v1/companies/` — `business-streams`, `profile` (CompanyViewSet — path is `profile`, not `companies`), `company-images`, plus `dashboard/<uuid:user_id>/`.
- `/api/v1/seekers/` — `profiles`, `education`, `experience`, `skills`, `seeker-skills`, plus `dashboard/<uuid:user_id>/`.
- `/api/v1/jobs/` — `job-types`, `job-locations`, `job-posts`, `job-applications`, `job-skills`, plus `apply/`, `applications/job/<uuid>/`, `applications/user/<uuid>/`.

### Query hygiene

Any ViewSet returning FK data must `select_related(...)`. Any reverse-FK or M2M returned in the response must `prefetch_related(...)`. Lock the query count on new list endpoints with `CaptureQueriesContext` + `assertLessEqual(len(ctx), N)` — budget `≤ 10` per list response regardless of row count. Avoid `assertNumQueries` for this purpose: it asserts exact equality and produces false failures when the real count lands below the ceiling.

### Settings organization

Put env-identical config in `jobApp/settings/base.py`. Put env-differing defaults in `development.py` / `production.py` / `test.py`. Never hardcode secrets or DB credentials anywhere — those stay in `config.py` and are read via `from config import ...`. `production.py` uses hard `assert` statements to fail-fast on missing `ALLOWED_HOSTS` or short `SECRET_KEY`. `manage.py` auto-picks `jobApp.settings.test` when running tests, `jobApp.settings.development` otherwise; `wsgi.py` / `asgi.py` default to `jobApp.settings.production`.

### Reference docs

- `API_DOCUMENTATION.md` — full endpoint catalog with request/response examples.
- `Job Board API.postman_collection.json` — importable Postman collection, kept alongside the docs.
