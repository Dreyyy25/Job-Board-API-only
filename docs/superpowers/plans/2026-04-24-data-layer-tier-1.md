# Data Layer Hardening — Tier 1 Plan

**Spec:** `docs/superpowers/specs/2026-04-24-data-layer-tier-1.md`
**Date:** 2026-04-24 (v2 — plan-review revisions)

## Execution order

Each task ends in a passing `uv run python manage.py test`. No task lands a broken suite.

### T1-1 — `UserAccount.user_type` index + `Company.status` index

**Files:** `apps/accounts/models.py`, `apps/companies/models.py`, new migrations.

1. `UserAccount.Meta.indexes = [Index(fields=['user_type'], name='useracct_user_type_idx')]`.
2. `Company.Meta.indexes = [Index(fields=['status'], name='company_status_idx')]`.
3. `uv run python manage.py makemigrations accounts companies`.
4. `uv run python manage.py migrate`.
5. `uv run python manage.py test apps.accounts apps.companies`.

### T1-2 — `JobLocation` + `JobPost` + `JobPostActivity` indexes

**Files:** `apps/jobs/models.py`, one migration.

1. `JobLocation.Meta.indexes = [Index(fields=['country', 'city'], name='joblocation_country_city_idx')]`.
2. `JobPost.Meta.indexes`:
   - `Index(fields=['is_published', 'is_active', '-created_at'], name='jobpost_pub_active_created_idx')`
   - `Index(fields=['company', '-created_at'], name='jobpost_company_created_idx')`
   - `Index(fields=['deadline_date'], name='jobpost_deadline_idx')`
3. `JobPostActivity.Meta.indexes`:
   - `Index(fields=['job_post', 'application_status'], name='jpactivity_job_status_idx')`
   - `Index(fields=['user_account', '-application_date'], name='jpactivity_user_date_idx')`
4. Migrate, run jobs tests.

### T1-3 — `JobPost` salary constraints

**Files:** `apps/jobs/models.py`, `apps/jobs/serializers.py`, `apps/jobs/tests.py`, migration.

1. `JobPost.Meta.constraints`:
   ```python
   models.CheckConstraint(
       check=models.Q(salary_min__isnull=True)
             | models.Q(salary_max__isnull=True)
             | models.Q(salary_min__lte=models.F('salary_max')),
       name='jobpost_salary_min_le_max',
   ),
   models.CheckConstraint(
       check=(models.Q(salary_min__isnull=True) | models.Q(salary_min__gte=0))
             & (models.Q(salary_max__isnull=True) | models.Q(salary_max__gte=0)),
       name='jobpost_salary_non_negative',
   ),
   ```
2. `JobPostSerializer.validate()`: same invariant, raise `ValidationError({'salary_min': ...})`.
3. Tests:
   - `test_salary_min_gt_max_rejected_by_serializer` — 400 via API.
   - `test_salary_min_gt_max_rejected_by_db` — `JobPost.objects.create(...)` inside `assertRaises(IntegrityError)`.
   - `test_negative_salary_rejected_by_serializer`.
4. Migrate, run tests.

### T1-4 — `EducationData` + `ExperienceData` constraints

**Files:** `apps/seekers/models.py`, `apps/seekers/serializers.py`, `apps/seekers/tests.py`, migration.

1. `EducationData.Meta.constraints`:
   ```python
   models.CheckConstraint(
       check=models.Q(percentage__isnull=True)
             | (models.Q(percentage__gte=0) & models.Q(percentage__lte=100)),
       name='education_percentage_range',
   ),
   models.CheckConstraint(
       check=models.Q(start_date__isnull=True)
             | models.Q(end_date__isnull=True)
             | models.Q(start_date__lte=models.F('end_date')),
       name='education_date_order',
   ),
   ```
2. `ExperienceData.Meta.constraints`: same `start <= end`.
3. Symmetric `validate()` on both serializers.
4. Tests — one per constraint at DB layer (IntegrityError) and one at API layer (400).
5. Migrate, run tests.

### T1-5 — Signal: auto-create profile on `UserAccount` post_save

**Files:** `apps/accounts/signals.py` (new), `apps/accounts/apps.py`, `apps/accounts/views.py`.

1. Create `apps/accounts/signals.py`:
   ```python
   from django.db.models.signals import post_save
   from django.dispatch import receiver

   from .models import UserAccount


   @receiver(post_save, sender=UserAccount)
   def create_user_profile(sender, instance, created, **kwargs):
       if not created:
           return

       # Lazy imports — avoid cycles and apps-not-ready at import time.
       from apps.companies.models import BusinessStream, Company
       from apps.seekers.models import SeekerProfile

       if instance.user_type == 'job_seeker':
           SeekerProfile.objects.get_or_create(
               user_account=instance,
               defaults={'first_name': '', 'last_name': ''},
           )
       elif instance.user_type == 'company':
           stream, _ = BusinessStream.objects.get_or_create(
               business_stream_name='Uncategorized',
           )
           Company.objects.get_or_create(
               user_account=instance,
               defaults={'company_name': '', 'business_stream': stream},
           )
   ```
2. `apps/accounts/apps.py`:
   ```python
   class AccountsConfig(AppConfig):
       default_auto_field = "django.db.models.BigAutoField"
       name = "apps.accounts"

       def ready(self):
           from . import signals  # noqa: F401
   ```
3. **`register` view gets `@transaction.atomic`** (promoted from sub-step to first-class):
   ```python
   from django.db import transaction

   @api_view(['POST'])
   @permission_classes([AllowAny])
   @throttle_classes([RegisterThrottle])
   @transaction.atomic
   def register(request):
       ...
   ```
4. **`UserAccountManager.create_user` also wrapped in `transaction.atomic()`** (covers shell-invoked paths like `manage.py createsuperuser` which run in autocommit):
   ```python
   # apps/accounts/models.py
   from django.db import transaction

   class UserAccountManager(BaseUserManager):
       def create_user(self, email, password=None, **extra_fields):
           if not email:
               raise ValueError('Email is required')
           email = self.normalize_email(email)
           with transaction.atomic():
               user = self.model(email=email, **extra_fields)
               user.set_password(password)
               user.save(using=self._db)
           return user
   ```
   Add regression test `test_create_user_rollback_on_signal_failure` that patches `SeekerProfile.objects.get_or_create` to raise and asserts no `UserAccount` row persists.

### T1-6 — Migrate existing tests (enumerated)

**Files:** `apps/companies/tests.py`, `apps/jobs/tests.py`.

Replace each `Company.objects.create(user_account=X, ...)` with:
```python
company = X.company_profile  # signal-created
company.company_name = '...'
company.business_stream = stream
company.save()
```

**Exact call sites (must all be migrated in this task):**
- `apps/companies/tests.py` lines 15, 39, 41, 88
- `apps/jobs/tests.py` lines 24, 56, 58, 106, 158, 221

**Preserve pre-existing fixture scaffolding.** Every `BusinessStream.objects.create(business_stream_name='Tech2')` (or similar named stream) in `setUp` stays unchanged — the signal-created "Uncategorized" row is a distinct seed; tests that want a different stream create it themselves and then assign it through `company.business_stream = stream; company.save()`.

Before migrating, verify each enumerated `Company.objects.create(...)` is paired with a `user_type='company'` user. If any pairs an `Company.objects.create` with a `user_type='job_seeker'` user, that was a pre-existing semantic bug — delete the `Company.objects.create(...)` entirely rather than migrating it.

Run `uv run python manage.py test` — expect all existing tests green.

### T1-7 — New signal-creation regression tests

**Files:** `apps/accounts/tests.py`.

1. `test_registering_seeker_creates_profile` — POST `/register/` with `user_type='job_seeker'`, assert `SeekerProfile.objects.filter(user_account=user).exists()`.
2. `test_registering_company_creates_company_row` — same for companies; assert `Company.objects.filter(user_account=user).exists()` and `business_stream.business_stream_name == 'Uncategorized'`.
3. `test_signal_creates_company_on_create_superuser` — `UserAccount.objects.create_superuser(...)` → `Company` exists.
4. `test_signal_creates_seeker_profile_on_create_user` — `UserAccount.objects.create_user(email=..., user_type='job_seeker', ...)` → `SeekerProfile` exists. (Covers the admin-form-adds-job-seeker path.)
5. `test_signal_idempotent_on_resave` — `user.save()` on existing user does not create a second profile.
6. `test_register_rollback_on_signal_failure` — patch `SeekerProfile.objects.get_or_create` to raise; POST `/register/`; assert `UserAccount.objects.filter(email='...').count() == 0`. (Proves `@transaction.atomic` works.)

### T1-8 — Update `register` response with profile payload

**Files:** `apps/accounts/views.py`, `apps/accounts/tests.py`.

1. Inside the `register` function body (lazy imports to avoid cycles; explicit `elif` prevents 500s if `user_type` ever slips validation):
   ```python
   def register(request):
       ...
       profile_data = None
       if user.user_type == 'job_seeker':
           from apps.seekers.serializers import SeekerProfileSerializer
           profile = getattr(user, 'seeker_profile', None)
           if profile is not None:
               profile_data = SeekerProfileSerializer(profile).data
       elif user.user_type == 'company':
           from apps.companies.serializers import CompanySerializer
           profile = getattr(user, 'company_profile', None)
           if profile is not None:
               profile_data = CompanySerializer(profile).data

       return Response({
           ...existing fields...,
           'profile': profile_data,
       }, status=status.HTTP_201_CREATED)
   ```
2. Test: `test_register_response_includes_profile` — seeker branch + company branch.

### T1-9 — `perform_create` existence pre-check

**Files:** `apps/companies/views.py`, `apps/seekers/views.py`, tests.

1. `CompanyViewSet.perform_create`:
   ```python
   def perform_create(self, serializer):
       if self.request.user.user_type != 'company':
           raise PermissionDenied("Only company users can create companies")
       if Company.objects.filter(user_account=self.request.user).exists():
           raise ValidationError({'detail': 'Profile already exists. Use PATCH to update.'})
       serializer.save(user_account=self.request.user)
   ```
2. `SeekerProfileViewSet.perform_create`: same pattern.
3. Tests:
   - `test_company_create_returns_400_when_profile_exists` — expects 400 with the `detail` message.
   - `test_seeker_profile_create_returns_400_when_profile_exists` — same.

### T1-10 — Final verification

1. `uv run python manage.py makemigrations --check --dry-run` → exit 0.
2. `uv run python manage.py test` → green.
3. `uv run python manage.py check --deploy` — same 5 dev warnings, no new.
4. Query-count tests still pass.
5. `CLAUDE.md` updated: one paragraph explaining auto-created profiles.

## Out of scope reminders

- No new endpoints.
- No viewset → QuerySet/Manager refactor (Tier 2).
- No Argon2 / throttle / logging changes (Tier 3).
- No `factory_boy` (Tier 4).
