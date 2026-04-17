# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Run from the repository root (where `manage.py` lives). Activate the virtualenv first (`venv\Scripts\activate` on Windows, `source venv/bin/activate` otherwise).

- Install deps: `pip install -r requirements.txt`
- Run dev server: `python manage.py runserver` (API served at `http://localhost:8000/api/v1/`)
- Make migrations: `python manage.py makemigrations`
- Apply migrations: `python manage.py migrate`
- Create superuser: `python manage.py createsuperuser` (prompts for `email` + `user_type`; superusers default to `user_type='company'`)
- Run all tests: `python manage.py test`
- Run tests for one app: `python manage.py test apps.jobs`
- Run a single test: `python manage.py test apps.jobs.tests.TestClassName.test_method`
- Django shell: `python manage.py shell`

A `.env` file is required at the repo root. Required keys: `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (see `.env.example`). `SECRET_KEY` is read with `os.environ[...]` — the app will crash on startup if it's missing. PostgreSQL is required (not SQLite).

## Architecture

Django 5.2 + DRF monolith with JWT auth. Four domain apps under `apps/`, each mounted under `/api/v1/<app>/` by `jobApp/urls.py`. The admin URL is `secure-admin/` when `DEBUG=True` and `admin-secure/` otherwise.

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

### Reference docs

- `API_DOCUMENTATION.md` — full endpoint catalog with request/response examples.
- `Job Board API.postman_collection.json` — importable Postman collection, kept alongside the docs.
