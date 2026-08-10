from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount
from apps.companies.models import BusinessStream, Company
from apps.jobs.models import JobLocation, JobPost, JobType, JobPostActivity


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")


class CompanySerializerTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.other = UserAccount.objects.create_user(
            email="other@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.stream = BusinessStream.objects.create(business_stream_name="Tech")
        self.company = self.owner.company_profile
        self.company.company_name = "Acme"
        self.company.business_stream = self.stream
        self.company.save()
        token = RefreshToken.for_user(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_owner_cannot_reassign_user_account(self):
        self.client.patch(
            f"/api/v1/companies/profile/{self.company.id}/",
            {"user_account": str(self.other.id)},
            format="json",
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.user_account_id, self.owner.id)


class CompanyPermissionTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="co-owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.other = UserAccount.objects.create_user(
            email="co-other@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.seeker = UserAccount.objects.create_user(
            email="co-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.stream = BusinessStream.objects.create(business_stream_name="Finance")
        self.owner_co = self.owner.company_profile
        self.owner_co.company_name = "Owner"
        self.owner_co.business_stream = self.stream
        self.owner_co.save()
        self.other_co = self.other.company_profile
        self.other_co.company_name = "Other"
        self.other_co.business_stream = self.stream
        self.other_co.save()

    def test_owner_cannot_edit_other_company(self):
        token = RefreshToken.for_user(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        r = self.client.patch(
            f"/api/v1/companies/profile/{self.other_co.id}/", {"company_name": "Hacked"}, format="json"
        )
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.other_co.refresh_from_db()
        self.assertEqual(self.other_co.company_name, "Other")

    def test_seeker_cannot_create_company(self):
        token = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        r = self.client.post(
            "/api/v1/companies/profile/",
            {
                "company_name": "SeekerCo",
                "business_stream": str(self.stream.id),
            },
            format="json",
        )
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST))


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
            co = owner.company_profile
            co.company_name = f"Co {i}"
            co.business_stream = stream
            co.save()
            CompanyImages.objects.create(company=co, image_url="https://x.invalid/a.png")

    def test_company_list_query_count(self):
        token = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/api/v1/companies/profile/")
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(
            len(ctx),
            COMPANY_QUERY_BUDGET,
            f"Query count {len(ctx)} exceeds budget {COMPANY_QUERY_BUDGET}",
        )


class CompanyImagesAnonymousReadTests(APITestCase):
    def test_anonymous_can_list_company_images(self):
        owner = UserAccount.objects.create_user(
            email="img-owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        stream = BusinessStream.objects.create(business_stream_name="Img Tech")
        company = owner.company_profile
        company.company_name = "ImgCo"
        company.business_stream = stream
        company.save()
        CompanyImages.objects.create(company=company, image_url="https://x.invalid/a.png")
        r = self.client.get("/api/v1/companies/company-images/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class CompanyCreateConflictTests(APITestCase):
    def test_company_create_returns_400_when_profile_exists(self):
        user = UserAccount.objects.create_user(
            email="cc@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        # Signal already created a Company for this user.
        stream = BusinessStream.objects.create(business_stream_name="CC Tech")
        token = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        r = self.client.post(
            "/api/v1/companies/profile/",
            {
                "company_name": "Another",
                "business_stream": str(stream.id),
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", r.data)


class PublicCompanyListTests(APITestCase):
    """Task 4: /api/v1/companies/public/ list -- anonymous, active-only, shape."""

    def setUp(self):
        self.stream = BusinessStream.objects.create(business_stream_name="Public Tech")

        active_owner = UserAccount.objects.create_user(
            email="pub-active@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.active_co = active_owner.company_profile
        self.active_co.company_name = "Active Co"
        self.active_co.business_stream = self.stream
        self.active_co.profile_description = "We build things"
        self.active_co.company_website_url = "https://active.example.com"
        self.active_co.contact_email = "secret@active.example.com"
        self.active_co.save()

        inactive_owner = UserAccount.objects.create_user(
            email="pub-inactive@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.inactive_co = inactive_owner.company_profile
        self.inactive_co.company_name = "Inactive Co"
        self.inactive_co.business_stream = self.stream
        self.inactive_co.status = "inactive"
        self.inactive_co.save()

        suspended_owner = UserAccount.objects.create_user(
            email="pub-suspended@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.suspended_co = suspended_owner.company_profile
        self.suspended_co.company_name = "Suspended Co"
        self.suspended_co.business_stream = self.stream
        self.suspended_co.status = "suspended"
        self.suspended_co.save()

    def test_anonymous_list_only_returns_active_companies(self):
        r = self.client.get("/api/v1/companies/public/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = {c["id"] for c in r.data["results"]}
        self.assertIn(str(self.active_co.id), ids)
        self.assertNotIn(str(self.inactive_co.id), ids)
        self.assertNotIn(str(self.suspended_co.id), ids)

    def test_list_item_shape(self):
        r = self.client.get("/api/v1/companies/public/")
        sample = next(c for c in r.data["results"] if c["id"] == str(self.active_co.id))
        self.assertEqual(sample["company_name"], "Active Co")
        self.assertEqual(
            sample["business_stream"],
            {"id": str(self.stream.id), "business_stream_name": "Public Tech"},
        )
        self.assertEqual(sample["profile_description"], "We build things")
        self.assertEqual(sample["company_website_url"], "https://active.example.com")
        self.assertEqual(sample["status"], "active")
        self.assertEqual(sample["open_roles_count"], 0)

    def test_list_excludes_contact_email_and_user_account(self):
        r = self.client.get("/api/v1/companies/public/")
        sample = next(c for c in r.data["results"] if c["id"] == str(self.active_co.id))
        self.assertNotIn("contact_email", sample)
        self.assertNotIn("user_account", sample)


class PublicCompanyOpenRolesCountTests(APITestCase):
    """Task 4: open_roles_count counts only is_published=True, is_active=True posts,
    and must not multiply through the images prefetch."""

    def setUp(self):
        stream = BusinessStream.objects.create(business_stream_name="Roles Tech")
        owner = UserAccount.objects.create_user(
            email="pub-roles@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.company = owner.company_profile
        self.company.company_name = "Roles Co"
        self.company.business_stream = stream
        self.company.save()

        job_type = JobType.objects.create(job_type_name="Public Full-time")
        location = JobLocation.objects.create(city="Cebu", country="PH")

        # Published + active: should count.
        JobPost.objects.create(
            company=self.company,
            job_type=job_type,
            job_location=location,
            job_title="Open Role 1",
            job_description="...",
            is_published=True,
            is_active=True,
        )
        JobPost.objects.create(
            company=self.company,
            job_type=job_type,
            job_location=location,
            job_title="Open Role 2",
            job_description="...",
            is_published=True,
            is_active=True,
        )
        # Unpublished: should not count.
        JobPost.objects.create(
            company=self.company,
            job_type=job_type,
            job_location=location,
            job_title="Draft Role",
            job_description="...",
            is_published=False,
            is_active=True,
        )
        # Inactive: should not count.
        JobPost.objects.create(
            company=self.company,
            job_type=job_type,
            job_location=location,
            job_title="Closed Role",
            job_description="...",
            is_published=True,
            is_active=False,
        )
        # Multiple images -- guards against the annotation multiplying rows
        # through the images prefetch.
        for i in range(3):
            CompanyImages.objects.create(company=self.company, image_url=f"https://x.invalid/{i}.png")

    def test_open_roles_count_counts_only_published_and_active(self):
        r = self.client.get("/api/v1/companies/public/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        matches = [c for c in r.data["results"] if c["id"] == str(self.company.id)]
        self.assertEqual(
            len(matches),
            1,
            "company row duplicated -- annotation likely multiplied through the images prefetch",
        )
        self.assertEqual(matches[0]["open_roles_count"], 2)


class PublicCompanyRetrieveTests(APITestCase):
    """Task 4: retrieve adds images; excludes contact_email/user_account; active-only."""

    def setUp(self):
        stream = BusinessStream.objects.create(business_stream_name="Retrieve Tech")
        owner = UserAccount.objects.create_user(
            email="pub-retrieve@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.company = owner.company_profile
        self.company.company_name = "Retrieve Co"
        self.company.business_stream = stream
        self.company.contact_email = "hidden@retrieve.example.com"
        self.company.save()
        self.image = CompanyImages.objects.create(company=self.company, image_url="https://x.invalid/logo.png")

    def test_retrieve_includes_images(self):
        r = self.client.get(f"/api/v1/companies/public/{self.company.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("images", r.data)
        self.assertEqual(len(r.data["images"]), 1)
        image = r.data["images"][0]
        self.assertEqual(image["id"], str(self.image.id))
        self.assertEqual(image["image_url"], "https://x.invalid/logo.png")
        self.assertIn("created_at", image)
        self.assertNotIn("company", image)

    def test_retrieve_excludes_contact_email_and_user_account(self):
        r = self.client.get(f"/api/v1/companies/public/{self.company.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertNotIn("contact_email", r.data)
        self.assertNotIn("user_account", r.data)

    def test_retrieve_404s_for_inactive_company(self):
        self.company.status = "inactive"
        self.company.save()
        r = self.client.get(f"/api/v1/companies/public/{self.company.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class PublicCompanyReadOnlyTests(APITestCase):
    """Task 4: POST/PATCH/DELETE never succeed on the public endpoint."""

    def setUp(self):
        stream = BusinessStream.objects.create(business_stream_name="Write Tech")
        owner = UserAccount.objects.create_user(
            email="pub-write@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.company = owner.company_profile
        self.company.company_name = "Write Co"
        self.company.business_stream = stream
        self.company.save()

    def test_post_never_succeeds(self):
        r = self.client.post(
            "/api/v1/companies/public/",
            {"company_name": "New", "business_stream": str(self.company.business_stream_id)},
            format="json",
        )
        self.assertNotIn(r.status_code, range(200, 300))

    def test_patch_never_succeeds(self):
        r = self.client.patch(
            f"/api/v1/companies/public/{self.company.id}/",
            {"company_name": "Hacked"},
            format="json",
        )
        self.assertNotIn(r.status_code, range(200, 300))
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_name, "Write Co")

    def test_delete_never_succeeds(self):
        r = self.client.delete(f"/api/v1/companies/public/{self.company.id}/")
        self.assertNotIn(r.status_code, range(200, 300))
        self.assertTrue(Company.objects.filter(id=self.company.id).exists())


class PublicCompanyThrottleAttachmentTests(APITestCase):
    """Setting throttle_classes replaces DRF's defaults, so the burst class
    must be listed explicitly alongside anon/user to backstop anonymous
    browse traffic on this endpoint (see jobApp/throttling.py)."""

    def test_public_company_viewset_has_layered_throttles(self):
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        from jobApp.throttling import BurstRateThrottle
        from apps.companies.views import PublicCompanyViewSet

        self.assertEqual(
            PublicCompanyViewSet.throttle_classes,
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle],
        )


class PublicCompanySearchAndFilterTests(APITestCase):
    """Task 4: search over company_name/profile_description; business_stream filter."""

    def setUp(self):
        self.stream_a = BusinessStream.objects.create(business_stream_name="Search Stream A")
        self.stream_b = BusinessStream.objects.create(business_stream_name="Search Stream B")

        owner_a = UserAccount.objects.create_user(
            email="pub-search-a@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.co_a = owner_a.company_profile
        self.co_a.company_name = "Halcyon Systems"
        self.co_a.business_stream = self.stream_a
        self.co_a.profile_description = "We build data platforms"
        self.co_a.save()

        owner_b = UserAccount.objects.create_user(
            email="pub-search-b@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.co_b = owner_b.company_profile
        self.co_b.company_name = "Zenith Robotics"
        self.co_b.business_stream = self.stream_b
        self.co_b.profile_description = "We build hardware"
        self.co_b.save()

    def test_search_by_company_name_narrows(self):
        r = self.client.get("/api/v1/companies/public/?search=Halcyon")
        ids = {c["id"] for c in r.data["results"]}
        self.assertIn(str(self.co_a.id), ids)
        self.assertNotIn(str(self.co_b.id), ids)

    def test_search_by_profile_description_narrows(self):
        r = self.client.get("/api/v1/companies/public/?search=hardware")
        ids = {c["id"] for c in r.data["results"]}
        self.assertIn(str(self.co_b.id), ids)
        self.assertNotIn(str(self.co_a.id), ids)

    def test_filter_by_business_stream_narrows(self):
        r = self.client.get(f"/api/v1/companies/public/?business_stream={self.stream_a.id}")
        ids = {c["id"] for c in r.data["results"]}
        self.assertIn(str(self.co_a.id), ids)
        self.assertNotIn(str(self.co_b.id), ids)


class PublicCompanyQueryCountTests(APITestCase):
    """Task 4: list endpoint stays within the project's ≤10-query budget."""

    def setUp(self):
        stream = BusinessStream.objects.create(business_stream_name="QC Public")
        job_type = JobType.objects.create(job_type_name="QC Public Type")
        location = JobLocation.objects.create(city="Iloilo", country="PH")
        for i in range(15):
            owner = UserAccount.objects.create_user(
                email=f"pub-qc{i}@example.com",
                password="Str0ng-Password!",
                user_type="company",
            )
            co = owner.company_profile
            co.company_name = f"QC Public Co {i}"
            co.business_stream = stream
            co.save()
            CompanyImages.objects.create(company=co, image_url="https://x.invalid/a.png")
            JobPost.objects.create(
                company=co,
                job_type=job_type,
                job_location=location,
                job_title="QC Role",
                job_description="...",
                is_published=True,
                is_active=True,
            )

    def test_public_company_list_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/api/v1/companies/public/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertLessEqual(
            len(ctx),
            COMPANY_QUERY_BUDGET,
            f"Query count {len(ctx)} exceeds budget {COMPANY_QUERY_BUDGET}",
        )


class CompanyDashboardStatsTests(APITestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.jobs.models import JobType, JobLocation, JobPost, JobPostActivity

        self.owner = UserAccount.objects.create_user(
            email="stats-owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.other = UserAccount.objects.create_user(
            email="stats-other@example.com", password="Str0ng-Password!", user_type="company"
        )
        seeker = UserAccount.objects.create_user(
            email="stats-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        stream = BusinessStream.objects.create(business_stream_name="Tech")
        for user, name in ((self.owner, "StatsCo"), (self.other, "OtherCo")):
            c = user.company_profile
            c.company_name = name
            c.business_stream = stream
            c.save()
        jt = JobType.objects.create(job_type_name="Full-time")
        loc = JobLocation.objects.create(city="Kyoto", country="Japan")

        def mk(user, title, **kw):
            return JobPost.objects.create(
                company=user.company_profile, job_type=jt, job_location=loc,
                job_title=title, job_description="d", **kw,
            )

        live = mk(self.owner, "Live")
        mk(self.owner, "Draft", is_published=False)
        mk(self.owner, "Inactive", is_active=False)
        rival_job = mk(self.other, "Rival live")

        now = timezone.now()
        recent = JobPostActivity.objects.create(user_account=seeker, job_post=live)
        recent.application_date = now - timedelta(days=6)
        recent.save()
        seeker2 = UserAccount.objects.create_user(
            email="stats-seeker2@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        old = JobPostActivity.objects.create(user_account=seeker2, job_post=live)
        old.application_date = now - timedelta(days=8)
        old.save()
        # rival application must not count for owner
        JobPostActivity.objects.create(user_account=seeker, job_post=rival_job)

    def test_stats_shape_and_math(self):
        _auth(self.client, self.owner)
        r = self.client.get(f"/api/v1/companies/dashboard/{self.owner.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            r.data["stats"],
            {"active_posts": 1, "total_applications": 2, "new_this_week": 1},
        )


class CompanyStatusRuleTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="status-owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.admin = UserAccount.objects.create_user(
            email="status-admin@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.admin.is_staff = True
        self.admin.save()
        stream = BusinessStream.objects.create(business_stream_name="Tech")
        self.company = self.owner.company_profile
        self.company.company_name = "StatusCo"
        self.company.business_stream = stream
        self.company.save()
        self.url = f"/api/v1/companies/profile/{self.company.id}/"

    def test_owner_can_pause_and_resume(self):
        _auth(self.client, self.owner)
        r = self.client.patch(self.url, {"status": "inactive"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        r = self.client.patch(self.url, {"status": "active"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_owner_cannot_set_suspended(self):
        _auth(self.client, self.owner)
        r = self.client.patch(self.url, {"status": "suspended"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suspended_owner_cannot_escape(self):
        self.company.status = "suspended"
        self.company.save()
        _auth(self.client, self.owner)
        r = self.client.patch(self.url, {"status": "active"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suspended_same_value_and_other_fields_ok(self):
        self.company.status = "suspended"
        self.company.save()
        _auth(self.client, self.owner)
        r = self.client.patch(
            self.url, {"status": "suspended", "profile_description": "still here"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.profile_description, "still here")

    def test_admin_unrestricted(self):
        self.company.status = "suspended"
        self.company.save()
        _auth(self.client, self.admin)
        r = self.client.patch(self.url, {"status": "active"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class CompanyImageOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="img-owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.rival = UserAccount.objects.create_user(
            email="img-rival@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.seeker = UserAccount.objects.create_user(
            email="img-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        stream = BusinessStream.objects.create(business_stream_name="Tech")
        for user, name in ((self.owner, "ImgCo"), (self.rival, "RivalCo")):
            c = user.company_profile
            c.company_name = name
            c.business_stream = stream
            c.save()
        self.url = "/api/v1/companies/company-images/"

    def test_company_creates_for_itself(self):
        _auth(self.client, self.owner)
        r = self.client.post(self.url, {"image_url": "https://cdn.example.com/a.jpg"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        img = CompanyImages.objects.get()
        self.assertEqual(img.company, self.owner.company_profile)

    def test_supplied_company_id_is_ignored(self):
        _auth(self.client, self.rival)
        r = self.client.post(
            self.url,
            {"image_url": "https://cdn.example.com/b.jpg",
             "company": str(self.owner.company_profile.id)},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CompanyImages.objects.get().company, self.rival.company_profile)

    def test_seeker_create_403(self):
        _auth(self.client, self.seeker)
        r = self.client.post(self.url, {"image_url": "https://cdn.example.com/c.jpg"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_deletes_own_image(self):
        img = CompanyImages.objects.create(
            company=self.owner.company_profile, image_url="https://cdn.example.com/d.jpg"
        )
        _auth(self.client, self.owner)
        r = self.client.delete(f"{self.url}{img.id}/")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)

    def test_seeker_cannot_delete(self):
        img = CompanyImages.objects.create(
            company=self.owner.company_profile, image_url="https://cdn.example.com/e.jpg"
        )
        _auth(self.client, self.seeker)
        r = self.client.delete(f"{self.url}{img.id}/")
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.assertTrue(CompanyImages.objects.filter(id=img.id).exists())
