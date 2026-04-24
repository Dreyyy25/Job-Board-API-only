# Data Layer Hardening — Tier 1 Spec

**Date:** 2026-04-24
**Status:** Draft (v2 — plan-review revisions)
**Owner:** Dreyyy25
**Builds on:** `2026-04-17-api-usability-tier-1.md`, `2026-04-22-settings-split.md` — both merged.

## Goal

Close three data-layer correctness and performance gaps that the Django patterns skill treats as production baseline: missing indexes on hot query paths, missing `CheckConstraint`s on invariants that the API can't defend alone, and the hand-rolled "user registers, then separately POSTs profile" flow that the `post_save` signal pattern is supposed to replace.

## Non-Goals

- **Service layer extraction / custom QuerySets** → Tier 2 (refactor-only, no schema impact).
- **Argon2 / per-user throttles / cookie SameSite / structured logging** → Tier 3 security pass.
- **`factory_boy` / pytest-django / ruff / CI** → Tier 4 engineering hygiene.
- **Caching reference data (BusinessStream, JobType, SkillSet)** → Tier 2.
- **OpenAPI / `drf-spectacular`** → Tier 4.
- **Email verification, file uploads, password reset** → product backlog.

## Current-State Summary

- **Indexes**: zero composite or functional indexes. Only implicit indexes from `unique=True` / PK / `unique_together`.
- **Constraints**: `JobPost.salary_min` / `salary_max` have no cross-field invariant. `EducationData.percentage` accepts `-50.00` or `999.99` today. `EducationData` and `ExperienceData` don't enforce `start_date <= end_date`.
- **Profile creation**: `apps.accounts.views.register` creates a `UserAccount` and returns tokens. The frontend has to make a second POST to create the profile. `JobPostViewSet.perform_create` 400s with "You must create a company profile before posting jobs" if the second call was skipped.

## Requirements

### R1 — Indexes on hot query paths

**R1.1** `JobPost` gains:
- `Index(fields=['is_published', 'is_active', '-created_at'])` — anonymous list order.
- `Index(fields=['company', '-created_at'])` — a company's own jobs.
- `Index(fields=['deadline_date'])` — `deadline_before` filter.

**R1.2** `JobPostActivity` gains:
- `Index(fields=['job_post', 'application_status'])` — company inspecting applicants.
- `Index(fields=['user_account', '-application_date'])` — user's own applications.

**R1.3** `UserAccount` gains `Index(fields=['user_type'])`.

**R1.4** `JobLocation` gains `Index(fields=['country', 'city'])`.

**R1.5** `Company` gains `Index(fields=['status'])`.

**R1.6** All indexes land in one migration per app. Migrations must be reversible (`AddIndex` already is).

### R2 — CheckConstraints

**R2.1** `JobPost`:
- `Q(salary_min__isnull=True) | Q(salary_max__isnull=True) | Q(salary_min__lte=F('salary_max'))`.
- `(Q(salary_min__isnull=True) | Q(salary_min__gte=0)) & (Q(salary_max__isnull=True) | Q(salary_max__gte=0))` — null-guarded on each side.

**R2.2** `EducationData`:
- `Q(percentage__isnull=True) | (Q(percentage__gte=0) & Q(percentage__lte=100))`.
- `Q(start_date__isnull=True) | Q(end_date__isnull=True) | Q(start_date__lte=F('end_date'))`.

**R2.3** `ExperienceData`: same `start_date <= end_date` rule.

**R2.4** Serializers gain symmetric `validate()` methods that raise `ValidationError` before the DB does. The DB check is a floor — the API should 400, not 500.

**R2.5 — REMOVED.** Pre-deploy violation scan dropped. The app has no real users; an `AddConstraint` migration on an empty table cannot fail on existing data. If/when the app has prod data, add a one-shot `RunPython(check_no_violations, reverse=noop)` in front of the constraint migration at that time.

### R3 — Auto-create profile on registration via `post_save` signal

**R3.1** `apps.accounts.signals` holds one receiver: `post_save, sender=UserAccount`. On `created=True`:
- `user_type == 'job_seeker'`: `SeekerProfile.objects.get_or_create(user_account=instance, defaults={'first_name': '', 'last_name': ''})`.
- `user_type == 'company'`: `stream, _ = BusinessStream.objects.get_or_create(business_stream_name='Uncategorized')`; `Company.objects.get_or_create(user_account=instance, defaults={'company_name': '', 'business_stream': stream})`.
- Model imports happen **inside the receiver body**, not at module top — prevents apps-not-ready errors and keeps the signal module safe to import from anywhere.

**R3.2** `AccountsConfig.ready()` imports signals. Receiver registration only; no other side effects.

**R3.3 — Atomicity (first-class requirement).**
- `register` view body is wrapped in `@transaction.atomic`. Without it, `UserAccount.save()` commits in auto-commit mode and a subsequent signal failure leaves an orphan user row.
- **`UserAccountManager.create_user` is also wrapped in `transaction.atomic()`** (belt-and-suspenders). This covers shell-invoked paths like `manage.py createsuperuser` and direct `UserAccount.objects.create_user(...)` calls from tests/scripts, which run in auto-commit by default and would otherwise leak an orphan user if the signal raised.
- Signal body uses `get_or_create` for idempotence.
- `/admin/` add-user form runs inside the admin view's transaction; no extra decorator needed there.
- Regression test: patch `SeekerProfile.objects.get_or_create` to raise, POST `/register/`, assert `UserAccount.objects.filter(email=...).count() == 0`. Second test: same patch, call `UserAccount.objects.create_user(...)` directly in a test, assert same rollback.

**R3.4** `register` response includes a `profile` payload (serialized `SeekerProfile` or `Company`). Cross-app serializer imports happen **inside the view function**, not at module top, to avoid circular-import fragility as the `accounts` app stays the dependency root.

**R3.5 — `perform_create` behavior.**
- `CompanyViewSet.perform_create` and `SeekerProfileViewSet.perform_create` pre-check existence: `if Company.objects.filter(user_account=request.user).exists(): raise ValidationError({'detail': 'Profile already exists. Use PATCH.'})`.
- Pre-check must land **before** `serializer.save()`. Catching `IntegrityError` after-the-fact would return 500, not 400, because DRF's exception handler doesn't translate `IntegrityError`.

**R3.6 — Admin & non-register signal paths.**
- `UserAccount.objects.create_superuser(...)` — defaults `user_type='company'`, so the signal creates a `Company`. Verified by test.
- `UserAccount.objects.create_user(email=..., user_type='job_seeker', ...)` — signal creates a `SeekerProfile`. Verified by a second test. This is the code path the admin's add-user form takes under the hood.

### R4 — Backwards compatibility

**R4.1** Existing tests that do `UserAccount.objects.create_user(...)` followed by `Company.objects.create(user_account=that_user, ...)` now raise `IntegrityError` on the OneToOne collision. **Exact call sites to migrate:**
- `apps/companies/tests.py:15, 39, 41, 88`
- `apps/jobs/tests.py:24, 56, 58, 106, 158, 221`

Migration strategy: replace the pattern
```python
user = UserAccount.objects.create_user(..., user_type='company')
company = Company.objects.create(user_account=user, company_name='X', business_stream=stream)
```
with
```python
user = UserAccount.objects.create_user(..., user_type='company')
company = user.company_profile  # signal-created
company.company_name = 'X'
company.business_stream = stream
company.save()
```

**R4.2** `seeker_dashboard` / `company_dashboard` endpoints stop returning 404 for freshly-registered users — a profile now always exists.

**R4.3** `JobPostViewSet.perform_create` "must create company profile first" branch stays in place. It is not dead code — it still fires when:
- An admin manually deletes a `Company` row through `/admin/` while the user persists.
- A data migration changes a user's `user_type` from `job_seeker` to `company` without creating a profile (signal only fires on `created=True`).

## Success Criteria

- `uv run python manage.py makemigrations && uv run python manage.py migrate` applies cleanly on an empty DB.
- Test count: 42 → ~50 (new: 5 signal tests + 5 constraint tests + ~3 perform_create 400-path tests).
- `EXPLAIN ANALYZE` on anonymous `JobPost` list uses the new composite index (hand-verified; not a test assertion).
- `JobPostQueryCountTests` still ≤ 10 queries.

## Risks

- **Signal double-creation**: mitigated by `get_or_create`.
- **Admin-created users without `user_type`**: `create_superuser` defaults to `'company'`. Acceptable; noted in CLAUDE.md.
- **Default `BusinessStream='Uncategorized'`**: one extra seed row the admin can rename or leave. Rejected alternative: nullable `business_stream` — would break existing non-null queries.
- **"Uncategorized" rename drift**: if an admin renames `BusinessStream('Uncategorized')` to something else via `/admin/`, the next company user's `get_or_create('Uncategorized')` creates a new row. Acceptable — at worst we end up with two streams, and signal-created Companies always use whatever row is currently named "Uncategorized". Documented here as expected behavior; not worth a fixture with a fixed UUID for now. Admin guidance (in CLAUDE.md) will note "do not rename; delete its companies first, then delete the row."
- **Cross-app import order**: `apps.accounts.views` now references `apps.companies.serializers.CompanySerializer` and `apps.seekers.serializers.SeekerProfileSerializer`. Mitigated by lazy imports inside function bodies. `apps.accounts` stays the dependency root of the project's app graph.
- **Defensive `user_type` handling in `register` view**: even though `RegisterSerializer.validate_user_type` enforces the choice, the profile-lookup code in T1-8 uses explicit `elif user.user_type == 'company'` with a no-op fallback so a future validator regression never 500s on a missing `seeker_profile` / `company_profile` reverse relation.
