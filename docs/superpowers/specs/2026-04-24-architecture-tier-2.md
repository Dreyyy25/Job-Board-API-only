# Architecture — Tier 2 Spec

**Date:** 2026-04-24
**Status:** Draft (v2 — plan-review revisions)
**Owner:** Dreyyy25
**Builds on:** `2026-04-24-data-layer-tier-1.md` — merged.

## Goal

Pull business logic out of views into a `services.py` per app, and replace repeated inline `.select_related(...).prefetch_related(...)` chains with custom `QuerySet` / `Manager` methods. No API contract changes.

## Non-Goals

- **New endpoints or fields** — pure refactor.
- **Celery / async jobs** — services are synchronous.
- **Repositories / unit-of-work** — thin services + QuerySets is the idiomatic middle ground.

## Current-State Summary

- `apps.accounts.views.register` / `login` / `logout` inline multi-step flows.
- `apps.jobs.views.apply_for_job` inlines 4 guard checks + 1 create.
- `apps.seekers.views.seeker_dashboard` / `apps.companies.views.company_dashboard` inline multi-model fetch + serialization.
- Every `get_queryset` hand-writes `.select_related(...).prefetch_related(...)`.

## Requirements

### R1 — Services per app

**R1.1** Create `apps/<app>/services.py` for `accounts`, `jobs`, `seekers`, `companies`.

**R1.2 — Service signatures (authoritative — plan must match).**

```python
# apps.accounts.services
def register_user(email, password, user_type, **extra) -> tuple[UserAccount, dict]:
    """
    Returns (user_with_profile_prefetched, tokens_dict).
    The user is fetched through UserAccount.objects.with_profile() so
    downstream code can access user.seeker_profile / user.company_profile
    without an extra query. Profile creation itself is the signal's job
    (Tier 1), so the service does not create it.

    The service ALSO runs django.contrib.auth.password_validation.validate_password
    before create_user so shell/test callers that bypass the DRF serializer
    still get policy enforcement. Weak passwords raise
    django.core.exceptions.ValidationError — translated to DRF
    ValidationError at the view layer.
    """

def login_user(email, password) -> tuple[UserAccount, dict]:
    """Returns (user, tokens_dict). Raises InvalidCredentialsError."""

def logout_user(refresh_token: str) -> None:
    """
    Blacklists the token. Catches simplejwt's TokenError and re-raises
    services.InvalidTokenError(str(e)) from e so the view never imports
    simplejwt directly.
    """

# apps.jobs.services
def apply_for_job(
    user, job_post_id, cover_letter='', user_account_id=None
) -> JobPostActivity:
    """
    user_account_id preserves the existing API contract strictly:
    clients that POST {"user_account": "<uuid>", "job_post": "<uuid>"}
    must include the user_account field AND its value must equal user.id.
    Raising rules:
      - user.user_type != 'job_seeker'                 → InvalidApplicantError
      - user_account_id is None or != str(user.id)     → InvalidApplicantError
      - JobPost not found / unpublished / inactive     → JobNotAvailableError
      - duplicate application for (user, job_post)     → AlreadyAppliedError
    """

def applications_for_job(requester, job_id): ...
def applications_for_user(requester, target_user_id): ...

# apps.seekers.services
def build_seeker_dashboard(requester, user_id) -> dict:
    """Raises ProfileNotFoundError, DashboardPermissionError."""

# apps.companies.services
def build_company_dashboard(requester, user_id) -> dict:
    """Raises CompanyNotFoundError, DashboardPermissionError."""
```

**R1.2.a — Exception-to-HTTP map (authoritative).** Every service exception has exactly one HTTP translation; views must not drift.

| Exception                   | HTTP | Body                                              |
|-----------------------------|------|---------------------------------------------------|
| `InvalidCredentialsError`   | 401  | `{'error': 'Invalid credentials'}`                |
| `InvalidTokenError`         | 400  | `{'error': 'invalid or expired refresh token'}`   |
| `InvalidApplicantError`     | 403  | `{'error': str(exc)}`                             |
| `AlreadyAppliedError`       | 400  | `{'error': 'You have already applied for this job'}` |
| `JobNotAvailableError`      | 404  | `{'error': 'Job not found or not available'}`     |
| `ProfileNotFoundError`      | 404  | `{'error': 'Profile not found'}`                  |
| `CompanyNotFoundError`      | 404  | `{'error': 'Company not found'}`                  |
| `DashboardPermissionError`  | 403  | `{'error': 'You do not have permission to access this dashboard'}` |
| Django `ValidationError` (password policy) | 400 | `{'password': [...]}` — DRF translates |

**R1.3** Services return domain objects / tuples / dicts — **not** DRF `Response`. Views translate exceptions to HTTP responses.

**R1.4** Services that touch multiple tables use `@transaction.atomic`.

**R1.5** Services are importable without Django test setup — pure functions of their args, no request globals.

### R2 — Custom QuerySets and Managers

**R2.1 — `UserAccountManager`. Use the documented Django pattern** (avoids MRO ambiguity):

```python
# apps/accounts/managers.py
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
    """Single-base pattern — from_queryset is inherited via Manager."""

    def create_user(self, email, password=None, **extra_fields):
        # ...moved from models.py unchanged...

    def create_superuser(self, email, password=None, **extra_fields):
        # ...moved from models.py unchanged...
```

Do **not** use `class UserAccountManager(BaseUserManager, Manager.from_queryset(X))` — that's a diamond MRO and breaks method resolution.

**R2.2** `apps.jobs.managers`:
```python
class JobPostQuerySet(models.QuerySet):
    def published(self): return self.filter(is_published=True, is_active=True)
    def for_company(self, user): return self.filter(company__user_account=user)
    def with_related(self):
        return self.select_related(
            'company', 'company__business_stream', 'job_type', 'job_location',
        ).prefetch_related('required_skills__skill_set')


class JobPostActivityQuerySet(models.QuerySet):
    def for_user(self, user): return self.filter(user_account=user)
    def for_company(self, user): return self.filter(job_post__company__user_account=user)
    def with_related(self):
        return self.select_related('user_account', 'job_post', 'job_post__company')
```

**R2.3** `apps.companies.managers`:
```python
class CompanyQuerySet(models.QuerySet):
    def active(self): return self.filter(status='active')
    def for_user(self, user): return self.filter(user_account=user)
    def with_related(self):
        return self.select_related('user_account', 'business_stream').prefetch_related('images')
```

**R2.4** `apps.seekers.managers`:
```python
class SeekerProfileQuerySet(models.QuerySet):
    def with_related(self):
        # SeekerProfile.user_account is the PK; select_related still pays off
        # when the view accesses profile.user_account.email.
        return self.select_related('user_account').prefetch_related(
            'user_account__education',
            'user_account__experiences',
            'user_account__skills__skill_set',
        )

class SeekerSkillSetQuerySet(models.QuerySet):
    def for_user(self, user): return self.filter(user_account=user)
    def with_related(self): return self.select_related('user_account', 'skill_set')
```

**R2.5 — ViewSet `get_queryset` shape.** Each viewset's `get_queryset` becomes:

```python
# JobPostViewSet
def get_queryset(self):
    qs = JobPost.objects.with_related()
    user = self.request.user
    if user.is_staff or user.is_superuser:
        return qs
    if user.is_authenticated and user.user_type == 'company':
        return qs.for_company(user)
    return qs.published()

# JobPostActivityViewSet — explicit fallback, NOT the same shape as JobPostViewSet
def get_queryset(self):
    qs = JobPostActivity.objects.with_related()
    user = self.request.user
    if user.is_staff or user.is_superuser:
        return qs
    if user.user_type == 'job_seeker':
        return qs.for_user(user)
    if user.user_type == 'company':
        return qs.for_company(user)
    return qs.none()  # defense against unknown user_type leaking applications
```

The `.none()` fallback is mandatory for `JobPostActivityViewSet`, `JobPostSkillSetViewSet`, `SeekerSkillSetViewSet`, and any viewset that doesn't have a "public published" semantics.

**R2.6** Query-count regression tests stay green (≤ 10 for list endpoints).

### R3 — View thinness audit

**R3.1** After the refactor, each view body is ≤ 25 lines of logic (docstring excluded). If exceeded, logic belongs in a service.

**R3.2** Function-based views collapse to try/except dispatchers:
```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_for_job(request):
    try:
        activity = services.apply_for_job(
            request.user,
            request.data.get('job_post'),
            cover_letter=request.data.get('cover_letter', ''),
            user_account_id=request.data.get('user_account'),  # preserve contract
        )
    except services.AlreadyAppliedError:
        return Response({'error': 'Already applied'}, status=400)
    except services.InvalidApplicantError as e:
        return Response({'error': str(e)}, status=403)
    except services.JobNotAvailableError:
        return Response({'error': 'Job not found or not available'}, status=404)
    return Response(JobPostActivitySerializer(activity).data, status=201)
```

## Success Criteria

- Every `views.py` imports from `.services` and delegates.
- `grep -rn 'select_related\|prefetch_related' apps/*/views.py` returns 0 matches.
- 42 (Tier 0) + ~8 (Tier 1) + ~6 new service-level unit tests = ~56 green.
- Query counts unchanged.
- `UserAccount.objects.create_user(...)` / `create_superuser(...)` still callable (MRO works).
- `JobPostActivityViewSet` still returns `.none()` for unknown user_types (regression test).

## Risks

- **Circular imports**: resolved by function-local imports (same pattern as Tier 1 signals).
- **Exception translation boilerplate**: accepted as the price of testability. A `@handle_service_errors` decorator is explicitly out of scope.
- **Service + view test overlap**: services unit-tested directly; views integration-tested via API client. Coverage split per `django-tdd`: Services 90%+, Views 80%+.
