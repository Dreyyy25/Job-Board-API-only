# Architecture — Tier 2 Plan

**Spec:** `docs/superpowers/specs/2026-04-24-architecture-tier-2.md`
**Date:** 2026-04-24 (v2 — plan-review revisions)

## Execution order

### T2-1 — `apps.accounts` QuerySet + Manager (fixed MRO)

**Files:** `apps/accounts/models.py`, `apps/accounts/managers.py` (new).

1. Create `apps/accounts/managers.py`:
   ```python
   from django.contrib.auth.models import BaseUserManager
   from django.db import models


   class UserAccountQuerySet(models.QuerySet):
       def seekers(self):
           return self.filter(user_type='job_seeker')

       def companies(self):
           return self.filter(user_type='company')

       def with_profile(self):
           return self.select_related('seeker_profile', 'company_profile')


   class UserAccountManager(BaseUserManager.from_queryset(UserAccountQuerySet)):
       def create_user(self, email, password=None, **extra_fields):
           if not email:
               raise ValueError('Email is required')
           email = self.normalize_email(email)
           user = self.model(email=email, **extra_fields)
           user.set_password(password)
           user.save(using=self._db)
           return user

       def create_superuser(self, email, password=None, **extra_fields):
           extra_fields.setdefault('is_staff', True)
           extra_fields.setdefault('is_superuser', True)
           extra_fields.setdefault('is_active', True)
           extra_fields.setdefault('user_type', 'company')

           if extra_fields.get('is_staff') is not True:
               raise ValueError('Superuser must have is_staff=True')
           if extra_fields.get('is_superuser') is not True:
               raise ValueError('Superuser must have is_superuser=True')

           return self.create_user(email, password, **extra_fields)
   ```
2. `apps/accounts/models.py`:
   ```python
   from .managers import UserAccountManager
   # ... delete inline UserAccountManager class ...
   class UserAccount(AbstractBaseUser, PermissionsMixin):
       # ...
       objects = UserAccountManager()
   ```
3. Verification: `UserAccount.objects.seekers()`, `UserAccount.objects.with_profile()`, `UserAccount.objects.create_user('a@b.com', 'x', user_type='job_seeker')` all work.
4. `uv run python manage.py test apps.accounts` → green.

### T2-2 — `apps.jobs` QuerySets

**Files:** `apps/jobs/models.py`, `apps/jobs/managers.py` (new).

1. Create `JobPostQuerySet(.published, .for_company, .with_related)` and `JobPostActivityQuerySet(.for_user, .for_company, .with_related)` per spec R2.2.
2. `JobPost.objects = JobPostQuerySet.as_manager()`.
3. `JobPostActivity.objects = JobPostActivityQuerySet.as_manager()`.
4. Tests green.

### T2-3 — `apps.companies` + `apps.seekers` QuerySets

**Files:** `apps/companies/managers.py`, `apps/seekers/managers.py`.

1. `CompanyQuerySet` with `.active()`, `.for_user(user)`, `.with_related()` (spec R2.3).
2. `SeekerProfileQuerySet.with_related()` — spells out `select_related('user_account').prefetch_related('user_account__education', 'user_account__experiences', 'user_account__skills__skill_set')`.
3. `SeekerSkillSetQuerySet.for_user(user)` and `.with_related()`.
4. Wire up: `Company.objects = CompanyQuerySet.as_manager()`, etc.
5. Tests green.

### T2-4 — Refactor `get_queryset` methods

**Files:** all four apps' `views.py`.

1. `JobPostViewSet.get_queryset` — spec R2.5 reference code.
2. `JobPostActivityViewSet.get_queryset` — **MUST keep the `.none()` fallback for unknown user_types**. Spec R2.5 explicit code.
3. `JobPostSkillSetViewSet.get_queryset` — same pattern as ActivityViewSet where appropriate (use `.none()` for unknown user_types; current code falls back to published-job skills — preserve that exactly).
4. `CompanyViewSet.get_queryset` — three branches: admin → all; company → `.for_user(user)`; else → `.active()`.
5. `SeekerProfileViewSet` / `EducationDataViewSet` / `ExperienceDataViewSet` / `SeekerSkillSetViewSet` — preserve their existing three-branch logic; unknown user_type → `.none()`.
6. **Verification**: `grep -rn 'select_related\|prefetch_related' apps/*/views.py` → 0 matches. If non-zero, fix.
7. Full test run — green. Query-count tests unchanged.

### T2-5 — `apps.accounts.services` (fixed return shape + logout wrapping)

**Files:** `apps/accounts/services.py` (new), `apps/accounts/views.py`.

1. `services.py`:
   ```python
   from django.contrib.auth.password_validation import validate_password
   from django.core.exceptions import ValidationError as DjangoValidationError
   from django.db import transaction
   from rest_framework_simplejwt.exceptions import TokenError
   from rest_framework_simplejwt.tokens import RefreshToken

   from .models import UserAccount


   class InvalidCredentialsError(Exception):
       pass


   class InvalidTokenError(Exception):
       pass


   def _mint_tokens(user):
       refresh = RefreshToken.for_user(user)
       refresh['user_id'] = str(user.id)
       refresh['email'] = user.email
       refresh['user_type'] = user.user_type
       return {
           'refresh': str(refresh),
           'access': str(refresh.access_token),
       }


   @transaction.atomic
   def register_user(email, password, user_type, **extra):
       # Password policy enforced here so shell/test callers that bypass
       # the DRF serializer still hit Django's validators. Raises
       # DjangoValidationError on weak password; view translates to 400.
       validate_password(
           password,
           user=UserAccount(email=email, user_type=user_type),
       )
       user = UserAccount.objects.create_user(
           email=email, password=password, user_type=user_type, **extra,
       )
       # Re-fetch with profile prefetched so the view can serialize
       # user.seeker_profile / user.company_profile without an extra query.
       user = UserAccount.objects.with_profile().get(pk=user.pk)
       return user, _mint_tokens(user)


   def login_user(email, password):
       try:
           user = UserAccount.objects.get(email=email)
       except UserAccount.DoesNotExist:
           raise InvalidCredentialsError()
       if not user.check_password(password):
           raise InvalidCredentialsError()
       from django.utils import timezone
       user.last_login = timezone.now()
       user.save(update_fields=['last_login'])
       return user, _mint_tokens(user)


   def logout_user(refresh_token: str) -> None:
       try:
           RefreshToken(refresh_token).blacklist()
       except TokenError as e:
           raise InvalidTokenError(str(e)) from e
   ```
2. `views.py` collapses register/login/logout to dispatch + serialize using `services`. The view does NOT import `simplejwt` anymore — abstraction holds.
3. Tests green.

### T2-6 — `apps.jobs.services` (preserves `user_account` contract)

**Files:** `apps/jobs/services.py` (new), `apps/jobs/views.py`.

1. Domain exceptions: `AlreadyAppliedError`, `InvalidApplicantError`, `JobNotAvailableError`.
2. `apply_for_job(user, job_post_id, cover_letter='', user_account_id=None)` — STRICT contract preservation: `user_account_id` must be present AND match:
   ```python
   def apply_for_job(user, job_post_id, cover_letter='', user_account_id=None):
       if user.user_type != 'job_seeker':
           raise InvalidApplicantError('Only job seekers can apply for jobs')
       # Preserve existing API contract strictly: user_account is required
       # in the body and must match the authenticated user. Current view
       # 403s when the field is omitted (str(None) != str(uuid)); the
       # service preserves that behavior.
       if user_account_id is None or str(user_account_id) != str(user.id):
           raise InvalidApplicantError('You can only apply for jobs for yourself')
       try:
           job = JobPost.objects.get(
               id=job_post_id, is_published=True, is_active=True,
           )
       except JobPost.DoesNotExist:
           raise JobNotAvailableError()
       if JobPostActivity.objects.filter(
           user_account=user, job_post=job,
       ).exists():
           raise AlreadyAppliedError()
       return JobPostActivity.objects.create(
           user_account=user, job_post=job, cover_letter=cover_letter,
       )
   ```
   **Regression test (mandatory):** `test_apply_for_job_requires_user_account_in_body` — POST `/apply/` with only `job_post` (no `user_account` key), expect 403 with the "apply for jobs for yourself" error. Guards against the silent loosening the reviewer flagged.
3. `applications_for_job(requester, job_id)` / `applications_for_user(requester, target_id)` — extract permission checks from the current views. Raise `PermissionDenied` (DRF's) for refusal and `Http404` semantics via a dedicated `JobNotFoundError`.
4. Views become try/except dispatchers per spec R3.2.
5. Service-level unit tests added to `apps/jobs/tests.py` — direct service calls with assertions on raised exceptions.
6. Tests green.

### T2-7 — `apps.seekers.services` + `apps.companies.services`

**Files:** new `services.py` in each; view edits.

1. `DashboardPermissionError`, `ProfileNotFoundError`, `CompanyNotFoundError`.
2. `build_seeker_dashboard(requester, user_id)` — permission gate (owner / admin / company) + fetch.
3. `build_company_dashboard(requester, user_id)` — owner / admin only.
4. Views reduced to try/except dispatchers.
5. Tests green.

### T2-8 — Service-level unit tests

**Files:** each app's `tests.py`.

1. Happy paths — `services.register_user(...)` returns `(user, tokens)`, assert `user.seeker_profile` exists AND is accessed without a DB hit (use `CaptureQueriesContext` to verify the prefetch worked).
2. `services.login_user('unknown@x.com', 'x')` → `InvalidCredentialsError`.
3. `services.logout_user('not-a-token')` → `InvalidTokenError`.
4. `services.apply_for_job(company_user, job_id)` → `InvalidApplicantError`.
5. `services.apply_for_job(seeker, job_id, user_account_id=str(other_seeker.id))` → `InvalidApplicantError`.
6. `services.apply_for_job(seeker, job_id)` twice → second raises `AlreadyAppliedError`.

### T2-9 — Final audit

1. `grep -rn 'select_related\|prefetch_related' apps/*/views.py` → 0.
2. Every view ≤ 25 lines of logic.
3. `uv run python manage.py test` — green.
4. `uv run python manage.py check --deploy` — no new warnings.
5. CLAUDE.md: one paragraph on the services pattern + one on QuerySets.
