# Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all Tier 0 requirements from `docs/superpowers/specs/2026-04-17-security-hardening.md` — close privilege-escalation holes, add throttling, enforce password policy, enable token revocation, move config to env, add permission tests.

**Architecture:** Per-app serializer audits replace `fields = '__all__'` with explicit whitelists. A dedicated `RegisterSerializer` isolates signup. `ScopedRateThrottle` guards auth endpoints. `rest_framework_simplejwt.token_blacklist` enables logout. All tests use DRF's `APITestCase` + `APIClient` and run via `python manage.py test`.

**Tech Stack:** Django 5.2, DRF 3.16, djangorestframework-simplejwt 5.5, PostgreSQL, python-dotenv.

---

## Phase 1 — Configuration

### Task 1: Read `DEBUG`, `ALLOWED_HOSTS`, `ADMIN_URL` from env

**Files:**
- Modify: `jobApp/settings.py:31-33`
- Modify: `jobApp/urls.py:22`
- Modify: `.env.example`

- [ ] **Step 1: Update `settings.py` to read from env**

Replace lines 31–33 of `jobApp/settings.py`:

```python
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
```

- [ ] **Step 2: Replace admin URL branching in `urls.py`**

In `jobApp/urls.py`, replace the `admin_url = 'secure-admin/' if settings.DEBUG else 'admin-secure/'` line and the `from jobApp import settings` import with:

```python
import os
admin_url = os.getenv("ADMIN_URL", "admin/")
```

Remove the now-unused `from jobApp import settings` import if nothing else references it.

- [ ] **Step 3: Update `.env.example`**

Append to `.env.example`:

```
# Deployment
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
ADMIN_URL=admin/
```

- [ ] **Step 4: Smoke-test dev boot**

Run: `DEBUG=true python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add jobApp/settings.py jobApp/urls.py .env.example
git commit -m "chore(config): read DEBUG, ALLOWED_HOSTS, ADMIN_URL from env"
```

---

### Task 2: Enable SimpleJWT token blacklist

**Files:**
- Modify: `jobApp/settings.py:38-52`
- Modify: `jobApp/settings.py:69-99`

- [ ] **Step 1: Add blacklist app to `INSTALLED_APPS`**

In `jobApp/settings.py`, replace the commented-out line `# 'rest_framework_simplejwt.token_blacklist',` with the active entry so `INSTALLED_APPS` reads:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'apps.accounts.apps.AccountsConfig',
    'apps.jobs',
    'apps.seekers',
    'apps.companies',
]
```

- [ ] **Step 2: Turn on rotation + blacklist in `SIMPLE_JWT`**

In the `SIMPLE_JWT = { ... }` dict, change:

```python
'ROTATE_REFRESH_TOKENS': True,
'BLACKLIST_AFTER_ROTATION': True,
```

- [ ] **Step 3: Run the blacklist migration**

Run: `python manage.py migrate token_blacklist`
Expected: `Applying token_blacklist.0001_initial... OK` (and follow-ups) on first run.

- [ ] **Step 4: Commit**

```bash
git add jobApp/settings.py
git commit -m "feat(auth): enable JWT token blacklist app and refresh rotation"
```

---

## Phase 2 — Password policy

### Task 3: Wire Django password validators through the serializer

**Files:**
- Modify: `jobApp/settings.py:155-168`
- Modify: `apps/accounts/serializers.py:34-38`

- [ ] **Step 1: Configure `MinimumLengthValidator` with 10 chars**

Replace the `AUTH_PASSWORD_VALIDATORS` block:

```python
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
```

- [ ] **Step 2: Replace custom password check with Django's `validate_password`**

In `apps/accounts/serializers.py`, replace the existing `validate_password` method with:

```python
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

def validate_password(self, value):
    try:
        validate_password(value)
    except DjangoValidationError as e:
        raise serializers.ValidationError(list(e.messages))
    return value
```

Add the two imports at the top of the file if they aren't present.

- [ ] **Step 3: Write failing test for short password**

Add to `apps/accounts/tests.py`:

```python
from rest_framework.test import APITestCase
from rest_framework import status

class PasswordPolicyTests(APITestCase):
    def test_register_rejects_short_password(self):
        payload = {
            "email": "short@example.com",
            "password": "abc123",
            "user_type": "job_seeker",
        }
        r = self.client.post("/api/v1/accounts/register/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", r.data)
```

- [ ] **Step 4: Run test, confirm it passes after steps 1–2**

Run: `python manage.py test apps.accounts.tests.PasswordPolicyTests.test_register_rejects_short_password -v 2`
Expected: PASS.

- [ ] **Step 5: Add common-password test**

Append to the same test class:

```python
    def test_register_rejects_common_password(self):
        payload = {
            "email": "common@example.com",
            "password": "password123",
            "user_type": "job_seeker",
        }
        r = self.client.post("/api/v1/accounts/register/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", r.data)
```

- [ ] **Step 6: Run both tests**

Run: `python manage.py test apps.accounts.tests.PasswordPolicyTests -v 2`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add jobApp/settings.py apps/accounts/serializers.py apps/accounts/tests.py
git commit -m "feat(accounts): enforce Django password validators (min 10 chars)"
```

---

## Phase 3 — Registration hardening

### Task 4: Dedicated `RegisterSerializer`

**Files:**
- Create: `apps/accounts/serializers.py` (append class)
- Modify: `apps/accounts/views.py:55-81`
- Modify: `apps/accounts/tests.py` (append class)

- [ ] **Step 1: Write failing test — register must ignore `is_staff`**

Append to `apps/accounts/tests.py`:

```python
from apps.accounts.models import UserAccount

class RegisterHardeningTests(APITestCase):
    def _payload(self, **overrides):
        base = {
            "email": "newuser@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }
        base.update(overrides)
        return base

    def test_register_ignores_is_staff_flag(self):
        r = self.client.post("/api/v1/accounts/register/",
                             self._payload(is_staff=True, is_superuser=True),
                             format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = UserAccount.objects.get(email="newuser@example.com")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_register_requires_user_type(self):
        payload = self._payload()
        payload.pop("user_type")
        r = self.client.post("/api/v1/accounts/register/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
```

- [ ] **Step 2: Run test, confirm failure**

Run: `python manage.py test apps.accounts.tests.RegisterHardeningTests.test_register_ignores_is_staff_flag -v 2`
Expected: FAIL — existing serializer happily saves `is_staff=True`.

- [ ] **Step 3: Add `RegisterSerializer`**

Append to `apps/accounts/serializers.py`:

```python
class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = [
            'email', 'password', 'user_type',
            'date_of_birth', 'contact_number', 'sex', 'user_image_url',
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'user_type': {'required': True},
        }

    def validate_user_type(self, value):
        if value not in ['job_seeker', 'company']:
            raise serializers.ValidationError(
                "Invalid user type. Must be 'job_seeker' or 'company'"
            )
        return value

    def validate_email(self, value):
        if UserAccount.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered")
        return value.lower().strip()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)
```

- [ ] **Step 4: Switch `register` view to the new serializer**

In `apps/accounts/views.py`, change the `register` function so the top reads:

```python
from .serializers import UserAccountSerializer, RegisterSerializer

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Register a new user account"""
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        refresh['user_id'] = str(user.id)
        refresh['email'] = user.email
        refresh['user_type'] = user.user_type
        return Response({
            'message': 'User created successfully',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'user_type': user.user_type,
            },
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
```

- [ ] **Step 5: Run the full class, expect pass**

Run: `python manage.py test apps.accounts.tests.RegisterHardeningTests -v 2`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/serializers.py apps/accounts/views.py apps/accounts/tests.py
git commit -m "feat(accounts): add RegisterSerializer that ignores admin flags"
```

---

## Phase 4 — Serializer field audit

### Task 5: Lock down `UserAccountSerializer` fields

**Files:**
- Modify: `apps/accounts/serializers.py:5-49`
- Modify: `apps/accounts/tests.py` (append class)

- [ ] **Step 1: Write failing test — PATCH `/me/` cannot escalate**

Append to `apps/accounts/tests.py`:

```python
from rest_framework_simplejwt.tokens import RefreshToken

class MePatchTests(APITestCase):
    def setUp(self):
        self.user = UserAccount.objects.create_user(
            email="seeker@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_me_patch_rejects_is_staff_escalation(self):
        r = self.client.patch("/api/v1/accounts/me/",
                              {"is_staff": True, "is_superuser": True},
                              format="json")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_me_patch_rejects_user_type_change(self):
        r = self.client.patch("/api/v1/accounts/me/",
                              {"user_type": "company"},
                              format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_type, "job_seeker")
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `python manage.py test apps.accounts.tests.MePatchTests -v 2`
Expected: both FAIL (escalation currently succeeds; user_type change currently succeeds).

- [ ] **Step 3: Replace the `Meta` block in `UserAccountSerializer`**

In `apps/accounts/serializers.py`, replace the `Meta` class of `UserAccountSerializer` with:

```python
    class Meta:
        model = UserAccount
        fields = [
            'id', 'email', 'password', 'user_type',
            'date_of_birth', 'contact_number', 'sex', 'user_image_url',
            'is_active', 'last_login', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'last_login', 'created_at', 'updated_at']
        extra_kwargs = {'password': {'write_only': True, 'required': False}}
```

- [ ] **Step 4: Make `user_type` immutable after creation**

Update `validate_user_type` in the same class:

```python
    def validate_user_type(self, value):
        if value not in ['job_seeker', 'company']:
            raise serializers.ValidationError(
                "Invalid user type. Must be 'job_seeker' or 'company'"
            )
        if self.instance and self.instance.user_type != value:
            raise serializers.ValidationError("user_type cannot be changed")
        return value
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `python manage.py test apps.accounts.tests.MePatchTests -v 2`
Expected: both PASS.

- [ ] **Step 6: Add cross-user isolation test**

Append to the same class:

```python
    def test_users_cannot_see_other_users(self):
        other = UserAccount.objects.create_user(
            email="other@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        r = self.client.get(f"/api/v1/accounts/users/{other.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
```

- [ ] **Step 7: Run the class again**

Run: `python manage.py test apps.accounts.tests.MePatchTests -v 2`
Expected: all three PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/accounts/serializers.py apps/accounts/tests.py
git commit -m "fix(accounts): lock down UserAccountSerializer fields, freeze user_type"
```

---

### Task 6: Audit `CompanySerializer`

**Files:**
- Modify: `apps/companies/serializers.py`
- Modify: `apps/companies/tests.py`

- [ ] **Step 1: Write failing test**

Replace `apps/companies/tests.py` contents with:

```python
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount
from apps.companies.models import BusinessStream, Company


class CompanySerializerTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="owner@example.com", password="Str0ng-Password!", user_type="company")
        self.other = UserAccount.objects.create_user(
            email="other@example.com", password="Str0ng-Password!", user_type="company")
        self.stream = BusinessStream.objects.create(business_stream_name="Tech")
        self.company = Company.objects.create(
            user_account=self.owner, company_name="Acme", business_stream=self.stream)
        token = RefreshToken.for_user(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_owner_cannot_reassign_user_account(self):
        r = self.client.patch(
            f"/api/v1/companies/profile/{self.company.id}/",
            {"user_account": str(self.other.id)},
            format="json",
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.user_account_id, self.owner.id)
```

- [ ] **Step 2: Run, confirm failure**

Run: `python manage.py test apps.companies.tests.CompanySerializerTests -v 2`
Expected: FAIL — reassignment currently succeeds.

- [ ] **Step 3: Tighten `CompanySerializer`**

Replace `apps/companies/serializers.py` with:

```python
from rest_framework import serializers
from .models import BusinessStream, Company, CompanyImages


class BusinessStreamSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessStream
        fields = ['id', 'business_stream_name']
        read_only_fields = ['id']


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            'id', 'user_account', 'company_name', 'business_stream',
            'profile_description', 'company_website_url', 'contact_email',
            'status', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']


class CompanyImagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyImages
        fields = ['id', 'company', 'image_url', 'created_at']
        read_only_fields = ['id', 'created_at']
```

- [ ] **Step 4: Run test, confirm pass**

Run: `python manage.py test apps.companies.tests.CompanySerializerTests -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/companies/serializers.py apps/companies/tests.py
git commit -m "fix(companies): make user_account read-only in CompanySerializer"
```

---

### Task 7: Audit `JobPost*` serializers and hide `job_description_hidden`

**Files:**
- Modify: `apps/jobs/serializers.py`
- Modify: `apps/jobs/tests.py`

- [ ] **Step 1: Write failing test**

Replace `apps/jobs/tests.py` with a baseline that exercises hidden-field disclosure:

```python
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount
from apps.companies.models import BusinessStream, Company
from apps.jobs.models import JobType, JobLocation, JobPost


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")


class JobPostHiddenFieldTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="owner@example.com", password="Str0ng-Password!", user_type="company")
        self.seeker = UserAccount.objects.create_user(
            email="seeker@example.com", password="Str0ng-Password!", user_type="job_seeker")
        stream = BusinessStream.objects.create(business_stream_name="Tech")
        company = Company.objects.create(
            user_account=self.owner, company_name="Acme", business_stream=stream)
        job_type = JobType.objects.create(job_type_name="Full-time")
        location = JobLocation.objects.create(city="Manila", country="PH")
        self.job = JobPost.objects.create(
            company=company, job_type=job_type, job_location=location,
            job_title="Dev", job_description="public",
            job_description_hidden="secret-notes",
        )

    def test_seeker_does_not_see_hidden_description(self):
        _auth(self.client, self.seeker)
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("job_description_hidden", r.data)

    def test_owner_sees_hidden_description(self):
        _auth(self.client, self.owner)
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data.get("job_description_hidden"), "secret-notes")
```

- [ ] **Step 2: Run, confirm the seeker test fails**

Run: `python manage.py test apps.jobs.tests.JobPostHiddenFieldTests -v 2`
Expected: `test_seeker_does_not_see_hidden_description` FAILs — hidden field is currently returned.

- [ ] **Step 3: Rewrite `apps/jobs/serializers.py`**

```python
from rest_framework import serializers
from .models import JobType, JobLocation, JobPost, JobPostActivity, JobPostSkillSet


class JobTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobType
        fields = ['id', 'job_type_name', 'description']
        read_only_fields = ['id']


class JobLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLocation
        fields = ['id', 'street_address', 'city', 'country', 'zip', 'country_code']
        read_only_fields = ['id']


class JobPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPost
        fields = [
            'id', 'company', 'job_type', 'job_location',
            'job_title', 'job_description', 'job_description_hidden',
            'salary_min', 'salary_max', 'salary_type', 'deadline_date',
            'is_published', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'company', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        is_owner = bool(
            user and user.is_authenticated and (
                user.is_staff or user.is_superuser
                or instance.company.user_account_id == user.id
            )
        )
        if not is_owner:
            data.pop('job_description_hidden', None)
        return data


class JobPostActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostActivity
        fields = [
            'id', 'user_account', 'job_post', 'application_date',
            'application_status', 'cover_letter', 'updated_at',
        ]
        read_only_fields = ['id', 'application_date', 'updated_at']


class JobPostSkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostSkillSet
        fields = ['id', 'job_post', 'skill_set', 'skill_level', 'is_required']
        read_only_fields = ['id']
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `python manage.py test apps.jobs.tests.JobPostHiddenFieldTests -v 2`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/serializers.py apps/jobs/tests.py
git commit -m "fix(jobs): explicit serializer fields; hide job_description_hidden from non-owners"
```

---

### Task 8: Audit seeker serializers

**Files:**
- Modify: `apps/seekers/serializers.py`

- [ ] **Step 1: Read current content**

Read `apps/seekers/serializers.py` and list every serializer defined. Expected serializers: `SeekerProfileSerializer`, `EducationDataSerializer`, `ExperienceDataSerializer`, `SkillSetSerializer`, `SeekerSkillSetSerializer`. (If any are missing, keep the existing set and only audit what's there.)

- [ ] **Step 2: Replace file contents**

```python
from rest_framework import serializers
from .models import (
    SeekerProfile, EducationData, ExperienceData, SkillSet, SeekerSkillSet,
)


class SeekerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeekerProfile
        fields = [
            'user_account', 'first_name', 'last_name',
            'contact_details', 'goals', 'resume_url',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['user_account', 'created_at', 'updated_at']


class EducationDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = EducationData
        fields = [
            'id', 'user_account', 'institute_university_name', 'degree_type',
            'field_of_study', 'academic_details', 'percentage',
            'start_date', 'end_date', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']


class ExperienceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperienceData
        fields = [
            'id', 'user_account', 'company_name', 'position', 'description',
            'job_location_city', 'job_location_country',
            'start_date', 'end_date', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']


class SkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillSet
        fields = ['id', 'skill_name', 'created_at']
        read_only_fields = ['id', 'created_at']


class SeekerSkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeekerSkillSet
        fields = ['id', 'user_account', 'skill_set', 'skill_level']
        read_only_fields = ['id', 'user_account']
```

- [ ] **Step 3: Update seeker viewsets to assign `user_account` server-side**

Open `apps/seekers/views.py` and for every ViewSet whose model has a `user_account` FK (SeekerProfile, EducationData, ExperienceData, SeekerSkillSet), ensure a `perform_create` exists like:

```python
    def perform_create(self, serializer):
        serializer.save(user_account=self.request.user)
```

If `perform_create` already exists with equivalent behaviour, leave it. Do not change queryset filtering.

- [ ] **Step 4: Regression check — run the full test suite**

Run: `python manage.py test`
Expected: all previously-passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add apps/seekers/serializers.py apps/seekers/views.py
git commit -m "fix(seekers): explicit serializer fields; user_account assigned server-side"
```

---

## Phase 5 — Logout endpoint

### Task 9: Add `POST /logout/`

**Files:**
- Modify: `apps/accounts/views.py`
- Modify: `apps/accounts/urls.py:13-22`
- Modify: `apps/accounts/tests.py`

- [ ] **Step 1: Write failing test**

Append to `apps/accounts/tests.py`:

```python
from rest_framework_simplejwt.tokens import RefreshToken


class LogoutTests(APITestCase):
    def setUp(self):
        self.user = UserAccount.objects.create_user(
            email="logout@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.refresh.access_token}")

    def test_logout_blacklists_refresh_token(self):
        r = self.client.post("/api/v1/accounts/logout/",
                             {"refresh": str(self.refresh)}, format="json")
        self.assertEqual(r.status_code, status.HTTP_205_RESET_CONTENT)
        self.client.credentials()  # drop auth header
        r2 = self.client.post("/api/v1/accounts/token/refresh/",
                              {"refresh": str(self.refresh)}, format="json")
        self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_missing_refresh_returns_400(self):
        r = self.client.post("/api/v1/accounts/logout/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
```

- [ ] **Step 2: Run, confirm failure**

Run: `python manage.py test apps.accounts.tests.LogoutTests -v 2`
Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Add the view**

Append to `apps/accounts/views.py`:

```python
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken as SimpleJWTRefreshToken


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """Blacklist the supplied refresh token."""
    token = request.data.get('refresh')
    if not token:
        return Response({'error': 'refresh token required'},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        SimpleJWTRefreshToken(token).blacklist()
    except TokenError:
        return Response({'error': 'invalid or expired refresh token'},
                        status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_205_RESET_CONTENT)
```

- [ ] **Step 4: Wire URL**

In `apps/accounts/urls.py`, add inside `urlpatterns`:

```python
    path('logout/', views.logout, name='logout'),
```

- [ ] **Step 5: Run tests**

Run: `python manage.py test apps.accounts.tests.LogoutTests -v 2`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/views.py apps/accounts/urls.py apps/accounts/tests.py
git commit -m "feat(accounts): POST /logout/ blacklists refresh token"
```

---

## Phase 6 — Throttling

### Task 10: ScopedRateThrottle on auth endpoints

**Files:**
- Modify: `jobApp/settings.py:58-66`
- Modify: `apps/accounts/views.py` (add decorators)
- Modify: `apps/accounts/urls.py` (wrap refresh view)
- Modify: `apps/accounts/tests.py`

- [ ] **Step 1: Add throttle config to settings**

In `jobApp/settings.py`, replace the `REST_FRAMEWORK` dict with:

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.accounts.authentication.CustomJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'register': '5/min',
        'login': '10/min',
        'token_refresh': '20/min',
    },
}
```

- [ ] **Step 2: Scope the `register` and `login` views**

At the top of `apps/accounts/views.py` add:

```python
from rest_framework.decorators import throttle_classes
from rest_framework.throttling import ScopedRateThrottle
```

Then directly above the `register` function, add:

```python
@throttle_classes([ScopedRateThrottle])
```

and inside the function body at the very top:

```python
    register.throttle_scope = 'register'
```

(Setting `throttle_scope` as a function attribute is the idiomatic way for function-based views. Alternatively, decorate with a small wrapper — stick with the attribute assignment.)

Actually, for function-based views the attribute needs to be set on the view function itself. Replace the above with a one-liner **after** the decorators:

```python
register.throttle_scope = 'register'
login.throttle_scope = 'login'
```

Place those two lines at module level, immediately after both function definitions.

- [ ] **Step 3: Scope the token refresh view**

In `apps/accounts/urls.py`, change the `TokenRefreshView` wiring to:

```python
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'token_refresh'
```

and update the path:

```python
    path('token/refresh/', ThrottledTokenRefreshView.as_view(), name='token-refresh'),
```

Add `from rest_framework.throttling import ScopedRateThrottle` to the file's imports.

- [ ] **Step 4: Write throttle test**

Append to `apps/accounts/tests.py`:

```python
from django.core.cache import cache


class ThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_register_throttles_after_limit(self):
        url = "/api/v1/accounts/register/"
        for i in range(5):
            r = self.client.post(url, {
                "email": f"thr{i}@example.com",
                "password": "Str0ng-Password!",
                "user_type": "job_seeker",
            }, format="json")
            self.assertIn(r.status_code, (status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST))
        r6 = self.client.post(url, {
            "email": "thr6@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }, format="json")
        self.assertEqual(r6.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
```

- [ ] **Step 5: Run throttle test**

Run: `python manage.py test apps.accounts.tests.ThrottleTests -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add jobApp/settings.py apps/accounts/views.py apps/accounts/urls.py apps/accounts/tests.py
git commit -m "feat(auth): throttle register/login/token-refresh via ScopedRateThrottle"
```

---

## Phase 7 — Cross-app permission tests

### Task 11: Job ownership & application tests

**Files:**
- Modify: `apps/jobs/tests.py` (append class)

- [ ] **Step 1: Append test class**

```python
class JobPostPermissionTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="owner@example.com", password="Str0ng-Password!", user_type="company")
        self.rival = UserAccount.objects.create_user(
            email="rival@example.com", password="Str0ng-Password!", user_type="company")
        self.seeker = UserAccount.objects.create_user(
            email="s@example.com", password="Str0ng-Password!", user_type="job_seeker")
        stream = BusinessStream.objects.create(business_stream_name="Tech2")
        self.owner_co = Company.objects.create(
            user_account=self.owner, company_name="Owner Co", business_stream=stream)
        self.rival_co = Company.objects.create(
            user_account=self.rival, company_name="Rival Co", business_stream=stream)
        self.job_type = JobType.objects.create(job_type_name="Contract")
        self.loc = JobLocation.objects.create(city="Cebu", country="PH")
        self.owner_job = JobPost.objects.create(
            company=self.owner_co, job_type=self.job_type, job_location=self.loc,
            job_title="Owner Job", job_description="...")

    def test_anonymous_only_sees_published_active(self):
        JobPost.objects.create(
            company=self.owner_co, job_type=self.job_type, job_location=self.loc,
            job_title="Draft", job_description="x", is_published=False)
        r = self.client.get("/api/v1/jobs/job-posts/")
        self.assertEqual(r.status_code, 200)
        titles = [j["job_title"] for j in (r.data if isinstance(r.data, list) else r.data.get("results", []))]
        self.assertIn("Owner Job", titles)
        self.assertNotIn("Draft", titles)

    def test_rival_cannot_edit_owner_job(self):
        _auth(self.client, self.rival)
        r = self.client.patch(f"/api/v1/jobs/job-posts/{self.owner_job.id}/",
                              {"job_title": "Pwned"}, format="json")
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.owner_job.refresh_from_db()
        self.assertEqual(self.owner_job.job_title, "Owner Job")

    def test_seeker_cannot_create_job(self):
        _auth(self.client, self.seeker)
        r = self.client.post("/api/v1/jobs/job-posts/", {
            "job_type": str(self.job_type.id),
            "job_location": str(self.loc.id),
            "job_title": "Nope", "job_description": "x",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
```

- [ ] **Step 2: Run the class**

Run: `python manage.py test apps.jobs.tests.JobPostPermissionTests -v 2`
Expected: all three PASS. If the rival edit test returns 200 instead of 403/404, the `IsJobPosterOrAdmin` permission is mis-wired — fix there before moving on.

- [ ] **Step 3: Commit**

```bash
git add apps/jobs/tests.py
git commit -m "test(jobs): lock down job-post ownership and anon visibility"
```

---

### Task 12: Application permission tests

**Files:**
- Modify: `apps/jobs/tests.py` (append class)

- [ ] **Step 1: Append test class**

```python
from apps.jobs.models import JobPostActivity


class ApplicationTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="app@example.com", password="Str0ng-Password!", user_type="job_seeker")
        self.other_seeker = UserAccount.objects.create_user(
            email="app2@example.com", password="Str0ng-Password!", user_type="job_seeker")
        owner = UserAccount.objects.create_user(
            email="appowner@example.com", password="Str0ng-Password!", user_type="company")
        stream = BusinessStream.objects.create(business_stream_name="Tech3")
        company = Company.objects.create(
            user_account=owner, company_name="Co", business_stream=stream)
        job_type = JobType.objects.create(job_type_name="Intern")
        loc = JobLocation.objects.create(city="Davao", country="PH")
        self.job = JobPost.objects.create(
            company=company, job_type=job_type, job_location=loc,
            job_title="App Job", job_description="...")

    def test_seeker_cannot_apply_twice(self):
        _auth(self.client, self.seeker)
        payload = {"user_account": str(self.seeker.id), "job_post": str(self.job.id)}
        r1 = self.client.post("/api/v1/jobs/apply/", payload, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        r2 = self.client.post("/api/v1/jobs/apply/", payload, format="json")
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_seeker_cannot_apply_as_another_user(self):
        _auth(self.client, self.seeker)
        payload = {"user_account": str(self.other_seeker.id), "job_post": str(self.job.id)}
        r = self.client.post("/api/v1/jobs/apply/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
```

- [ ] **Step 2: Run the class**

Run: `python manage.py test apps.jobs.tests.ApplicationTests -v 2`
Expected: both PASS (logic already exists in `apply_for_job`).

- [ ] **Step 3: Commit**

```bash
git add apps/jobs/tests.py
git commit -m "test(jobs): lock down application dedup and spoofing guards"
```

---

### Task 13: Company permission tests

**Files:**
- Modify: `apps/companies/tests.py` (append class)

- [ ] **Step 1: Append test class**

```python
class CompanyPermissionTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="co-owner@example.com", password="Str0ng-Password!", user_type="company")
        self.other = UserAccount.objects.create_user(
            email="co-other@example.com", password="Str0ng-Password!", user_type="company")
        self.seeker = UserAccount.objects.create_user(
            email="co-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker")
        self.stream = BusinessStream.objects.create(business_stream_name="Finance")
        self.owner_co = Company.objects.create(
            user_account=self.owner, company_name="Owner", business_stream=self.stream)
        self.other_co = Company.objects.create(
            user_account=self.other, company_name="Other", business_stream=self.stream)

    def test_owner_cannot_edit_other_company(self):
        token = RefreshToken.for_user(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        r = self.client.patch(
            f"/api/v1/companies/profile/{self.other_co.id}/",
            {"company_name": "Hacked"}, format="json")
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.other_co.refresh_from_db()
        self.assertEqual(self.other_co.company_name, "Other")

    def test_seeker_cannot_create_company(self):
        token = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        r = self.client.post("/api/v1/companies/profile/", {
            "company_name": "SeekerCo",
            "business_stream": str(self.stream.id),
        }, format="json")
        self.assertIn(r.status_code,
                      (status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST))
```

Ensure the `from rest_framework_simplejwt.tokens import RefreshToken` import is at the top of the file (add if missing).

- [ ] **Step 2: Run**

Run: `python manage.py test apps.companies.tests.CompanyPermissionTests -v 2`
Expected: both PASS. If `test_seeker_cannot_create_company` returns 201, the `IsCompanyOwnerOrAdmin` permission is too lax — fix the permission before merging this task.

- [ ] **Step 3: Commit**

```bash
git add apps/companies/tests.py
git commit -m "test(companies): verify cross-owner and non-company write guards"
```

---

### Task 14: Seeker permission tests

**Files:**
- Modify: `apps/seekers/tests.py`

- [ ] **Step 1: Replace file contents**

```python
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount
from apps.seekers.models import EducationData


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")


class SeekerPermissionTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="s@example.com", password="Str0ng-Password!", user_type="job_seeker")
        self.other = UserAccount.objects.create_user(
            email="o@example.com", password="Str0ng-Password!", user_type="job_seeker")
        self.other_edu = EducationData.objects.create(
            user_account=self.other,
            institute_university_name="X",
            degree_type="Bachelor",
        )

    def test_seeker_cannot_edit_other_education(self):
        _auth(self.client, self.seeker)
        r = self.client.patch(
            f"/api/v1/seekers/education/{self.other_edu.id}/",
            {"institute_university_name": "Pwned"}, format="json")
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.other_edu.refresh_from_db()
        self.assertEqual(self.other_edu.institute_university_name, "X")

    def test_seeker_can_create_own_education(self):
        _auth(self.client, self.seeker)
        r = self.client.post("/api/v1/seekers/education/", {
            "institute_university_name": "Mine",
            "degree_type": "Bachelor",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(EducationData.objects.get(id=r.data["id"]).user_account_id, self.seeker.id)
```

- [ ] **Step 2: Run**

Run: `python manage.py test apps.seekers.tests.SeekerPermissionTests -v 2`
Expected: both PASS. If `user_account` ends up as `None` or the other seeker's ID, Task 8 Step 3 wasn't applied — fix `perform_create` and rerun.

- [ ] **Step 3: Commit**

```bash
git add apps/seekers/tests.py
git commit -m "test(seekers): verify user_account is auto-assigned and owner-only writes"
```

---

## Phase 8 — Full-suite audit

### Task 15: Final audit pass

**Files:**
- Modify: `Readme.md` (if env changes need documenting)

- [ ] **Step 1: Grep for remaining `__all__` serializers**

Run: `grep -rn "fields = '__all__'" apps/`
Expected: no output.

- [ ] **Step 2: Run the whole suite**

Run: `python manage.py test`
Expected: 0 failures, 0 errors.

- [ ] **Step 3: `check --deploy`**

Run: `DEBUG=false SECRET_KEY=test-key ALLOWED_HOSTS=example.com DB_NAME=x DB_USER=x DB_PASSWORD=x DB_HOST=x DB_PORT=5432 python manage.py check --deploy`
Expected: warnings limited to SSL/HSTS (deferred to Tier 1). No critical security issues for serializer `__all__`, privilege escalation, or token revocation.

- [ ] **Step 4: Update README env section**

In `Readme.md`, expand the "Set up environment variables" block to include:

```
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
ADMIN_URL=admin/
```

- [ ] **Step 5: Commit**

```bash
git add Readme.md
git commit -m "docs: document DEBUG/ALLOWED_HOSTS/ADMIN_URL env vars"
```

---

## Self-Review Checklist

- [x] R1 serializer field control → Tasks 5, 6, 7, 8 each lock one app's serializers.
- [x] R2 registration hardening → Task 4.
- [x] R3 password policy → Task 3.
- [x] R4 throttling → Task 10.
- [x] R5 logout / blacklist → Tasks 2 (infra) + 9 (endpoint).
- [x] R6 env-driven config → Task 1.
- [x] R7 permission tests → Tasks 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14 collectively.
- [x] R8 deploy check → Task 15.

No placeholders or "TBD"s. Every code step contains concrete code. Commands include expected output. Commits are per-task.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-17-security-hardening.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
