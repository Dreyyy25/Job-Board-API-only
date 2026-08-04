from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from apps.accounts.models import UserAccount
from apps.companies.models import BusinessStream, Company
from apps.jobs.models import JobType, JobLocation, JobPost


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")


class JobPostHiddenFieldTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.seeker = UserAccount.objects.create_user(
            email="seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        stream = BusinessStream.objects.create(business_stream_name="Tech")
        company = self.owner.company_profile
        company.company_name = "Acme"
        company.business_stream = stream
        company.save()
        job_type = JobType.objects.create(job_type_name="Full-time")
        location = JobLocation.objects.create(city="Manila", country="PH")
        self.job = JobPost.objects.create(
            company=company,
            job_type=job_type,
            job_location=location,
            job_title="Dev",
            job_description="public",
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


class JobPostPermissionTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.rival = UserAccount.objects.create_user(
            email="rival@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.seeker = UserAccount.objects.create_user(
            email="s@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        stream = BusinessStream.objects.create(business_stream_name="Tech2")
        self.owner_co = self.owner.company_profile
        self.owner_co.company_name = "Owner Co"
        self.owner_co.business_stream = stream
        self.owner_co.save()
        self.rival_co = self.rival.company_profile
        self.rival_co.company_name = "Rival Co"
        self.rival_co.business_stream = stream
        self.rival_co.save()
        self.job_type = JobType.objects.create(job_type_name="Contract")
        self.loc = JobLocation.objects.create(city="Cebu", country="PH")
        self.owner_job = JobPost.objects.create(
            company=self.owner_co,
            job_type=self.job_type,
            job_location=self.loc,
            job_title="Owner Job",
            job_description="...",
        )

    def test_anonymous_only_sees_published_active(self):
        JobPost.objects.create(
            company=self.owner_co,
            job_type=self.job_type,
            job_location=self.loc,
            job_title="Draft",
            job_description="x",
            is_published=False,
        )
        r = self.client.get("/api/v1/jobs/job-posts/")
        self.assertEqual(r.status_code, 200)
        titles = [j["job_title"] for j in (r.data if isinstance(r.data, list) else r.data.get("results", []))]
        self.assertIn("Owner Job", titles)
        self.assertNotIn("Draft", titles)

    def test_rival_cannot_edit_owner_job(self):
        _auth(self.client, self.rival)
        r = self.client.patch(f"/api/v1/jobs/job-posts/{self.owner_job.id}/", {"job_title": "Pwned"}, format="json")
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.owner_job.refresh_from_db()
        self.assertEqual(self.owner_job.job_title, "Owner Job")

    def test_seeker_cannot_create_job(self):
        _auth(self.client, self.seeker)
        r = self.client.post(
            "/api/v1/jobs/job-posts/",
            {
                "job_type": str(self.job_type.id),
                "job_location": str(self.loc.id),
                "job_title": "Nope",
                "job_description": "x",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


from apps.jobs.models import JobPostActivity


class JobLocationAnonymousReadTests(APITestCase):
    def test_anonymous_can_list_job_locations(self):
        JobLocation.objects.create(city="Iloilo", country="PH")
        r = self.client.get("/api/v1/jobs/job-locations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class ApplicationTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="app@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.other_seeker = UserAccount.objects.create_user(
            email="app2@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        owner = UserAccount.objects.create_user(
            email="appowner@example.com", password="Str0ng-Password!", user_type="company"
        )
        stream = BusinessStream.objects.create(business_stream_name="Tech3")
        company = owner.company_profile
        company.company_name = "Co"
        company.business_stream = stream
        company.save()
        job_type = JobType.objects.create(job_type_name="Intern")
        loc = JobLocation.objects.create(city="Davao", country="PH")
        self.job = JobPost.objects.create(
            company=company, job_type=job_type, job_location=loc, job_title="App Job", job_description="..."
        )

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


class JobPostFilterTests(APITestCase):
    def setUp(self):
        owner = UserAccount.objects.create_user(
            email="filt-owner@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        stream = BusinessStream.objects.create(business_stream_name="Filt Tech")
        company = owner.company_profile
        company.company_name = "FiltCo"
        company.business_stream = stream
        company.save()
        self.ft = JobType.objects.create(job_type_name="FiltFT")
        self.pt = JobType.objects.create(job_type_name="FiltPT")
        self.manila = JobLocation.objects.create(city="Manila", country="PH")
        self.cebu = JobLocation.objects.create(city="Cebu", country="PH")
        self.tokyo = JobLocation.objects.create(city="Tokyo", country="JP")

        JobPost.objects.create(
            company=company,
            job_type=self.ft,
            job_location=self.manila,
            job_title="Senior Developer",
            job_description="python",
            salary_min=1000,
            salary_max=5000,
        )
        JobPost.objects.create(
            company=company,
            job_type=self.pt,
            job_location=self.cebu,
            job_title="Junior Dev",
            job_description="...",
            salary_min=500,
            salary_max=1500,
        )
        JobPost.objects.create(
            company=company,
            job_type=self.ft,
            job_location=self.tokyo,
            job_title="Staff Engineer",
            job_description="leadership",
            salary_min=8000,
            salary_max=12000,
        )

    def _titles(self, response):
        return sorted(j["job_title"] for j in response.data["results"])

    def test_filter_by_job_type(self):
        r = self.client.get(f"/api/v1/jobs/job-posts/?job_type={self.ft.id}")
        self.assertEqual(self._titles(r), ["Senior Developer", "Staff Engineer"])

    def test_filter_by_city(self):
        r = self.client.get("/api/v1/jobs/job-posts/?city=manila")
        self.assertEqual(self._titles(r), ["Senior Developer"])

    def test_filter_by_salary_range(self):
        r = self.client.get("/api/v1/jobs/job-posts/?salary_min_gte=1000&salary_max_lte=5000")
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


QUERY_BUDGET = 10  # ceiling; tune downward as prefetches are added


from django.db import IntegrityError


class JobPostSalaryConstraintTests(APITestCase):
    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="sal-owner@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        stream = BusinessStream.objects.create(business_stream_name="SalTech")
        self.company = self.owner.company_profile
        self.company.company_name = "SalCo"
        self.company.business_stream = stream
        self.company.save()
        self.job_type = JobType.objects.create(job_type_name="SalFT")
        self.loc = JobLocation.objects.create(city="SalCity", country="PH")
        _auth(self.client, self.owner)

    def _payload(self, **overrides):
        base = {
            "job_type": str(self.job_type.id),
            "job_location": str(self.loc.id),
            "job_title": "Dev",
            "job_description": "...",
        }
        base.update(overrides)
        return base

    def test_salary_min_gt_max_rejected_by_serializer(self):
        r = self.client.post(
            "/api/v1/jobs/job-posts/",
            self._payload(salary_min=5000, salary_max=1000),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("salary_min", r.data)

    def test_salary_min_gt_max_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            JobPost.objects.create(
                company=self.company,
                job_type=self.job_type,
                job_location=self.loc,
                job_title="Bad",
                job_description="...",
                salary_min=9000,
                salary_max=100,
            )

    def test_negative_salary_rejected_by_serializer(self):
        r = self.client.post(
            "/api/v1/jobs/job-posts/",
            self._payload(salary_min=-1, salary_max=100),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


from apps.jobs import services as jobs_services


class JobsServiceTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="svc-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.other_seeker = UserAccount.objects.create_user(
            email="svc-other@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.company_user = UserAccount.objects.create_user(
            email="svc-co@example.com", password="Str0ng-Password!", user_type="company"
        )
        stream = BusinessStream.objects.create(business_stream_name="Svc Tech")
        company = self.company_user.company_profile
        company.company_name = "SvcCo"
        company.business_stream = stream
        company.save()
        jt = JobType.objects.create(job_type_name="Svc FT")
        loc = JobLocation.objects.create(city="SvcCity", country="PH")
        self.job = JobPost.objects.create(
            company=company, job_type=jt, job_location=loc, job_title="Svc Job", job_description="..."
        )

    def test_apply_for_job_rejects_company_user(self):
        with self.assertRaises(jobs_services.InvalidApplicantError):
            jobs_services.apply_for_job(
                self.company_user,
                str(self.job.id),
                user_account_id=str(self.company_user.id),
            )

    def test_apply_for_job_requires_user_account_in_body(self):
        # Omitting user_account_id must raise; preserves pre-Tier-2 behaviour
        # where the view 403'd because str(None) != str(user.id).
        with self.assertRaises(jobs_services.InvalidApplicantError):
            jobs_services.apply_for_job(
                self.seeker,
                str(self.job.id),
                user_account_id=None,
            )

    def test_apply_for_job_rejects_mismatched_user_account(self):
        with self.assertRaises(jobs_services.InvalidApplicantError):
            jobs_services.apply_for_job(
                self.seeker,
                str(self.job.id),
                user_account_id=str(self.other_seeker.id),
            )

    def test_apply_for_job_happy_path(self):
        activity = jobs_services.apply_for_job(
            self.seeker,
            str(self.job.id),
            user_account_id=str(self.seeker.id),
            cover_letter="hi",
        )
        self.assertEqual(activity.user_account_id, self.seeker.id)
        self.assertEqual(activity.cover_letter, "hi")

    def test_apply_for_job_duplicate_raises_already_applied(self):
        jobs_services.apply_for_job(
            self.seeker,
            str(self.job.id),
            user_account_id=str(self.seeker.id),
        )
        with self.assertRaises(jobs_services.AlreadyAppliedError):
            jobs_services.apply_for_job(
                self.seeker,
                str(self.job.id),
                user_account_id=str(self.seeker.id),
            )

    def test_apply_for_job_unknown_job_raises(self):
        with self.assertRaises(jobs_services.JobNotAvailableError):
            jobs_services.apply_for_job(
                self.seeker,
                "00000000-0000-0000-0000-000000000000",
                user_account_id=str(self.seeker.id),
            )


class ApplyEndpointContractTests(APITestCase):
    """Regression tests guaranteeing the /apply/ endpoint behaviour survives Tier 2."""

    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="contract-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        co_user = UserAccount.objects.create_user(
            email="contract-co@example.com", password="Str0ng-Password!", user_type="company"
        )
        stream = BusinessStream.objects.create(business_stream_name="Contract Tech")
        company = co_user.company_profile
        company.company_name = "ContractCo"
        company.business_stream = stream
        company.save()
        jt = JobType.objects.create(job_type_name="Contract FT")
        loc = JobLocation.objects.create(city="C", country="PH")
        self.job = JobPost.objects.create(
            company=company, job_type=jt, job_location=loc, job_title="C Job", job_description="..."
        )
        _auth(self.client, self.seeker)

    def test_apply_endpoint_returns_403_when_user_account_missing(self):
        r = self.client.post(
            "/api/v1/jobs/apply/",
            {
                "job_post": str(self.job.id),
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class BurstThrottleAttachmentTests(APITestCase):
    """Layered throttle composition is a class-attribute contract.

    We assert the contract directly on the view — hitting real 429s in
    tests is fragile because DRF's api_settings caches THROTTLE_RATES in
    ways that don't always pick up test-time override_settings changes.
    Composition is what matters; the rate ceilings are exercised in
    production traffic.
    """

    def test_jobpost_viewset_has_layered_throttles(self):
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        from apps.jobs.views import BurstRateThrottle, JobPostViewSet

        self.assertEqual(
            JobPostViewSet.throttle_classes,
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle],
        )

    def test_apply_for_job_has_burst_throttle(self):
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        from apps.jobs.views import BurstRateThrottle, apply_for_job

        # @throttle_classes decorator stores the list on the wrapped view
        # via .throttle_classes (resolved by APIView metaclass).
        classes = getattr(apply_for_job.cls, 'throttle_classes', None)
        self.assertEqual(
            classes,
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle],
        )

    def test_burst_throttle_scope_is_burst(self):
        from apps.jobs.views import BurstRateThrottle

        self.assertEqual(BurstRateThrottle.scope, 'burst')


class JobPostQueryCountTests(APITestCase):
    def setUp(self):
        owner = UserAccount.objects.create_user(
            email="qc-owner@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        stream = BusinessStream.objects.create(business_stream_name="QC Tech")
        company = owner.company_profile
        company.company_name = "QCCo"
        company.business_stream = stream
        company.save()
        jt = JobType.objects.create(job_type_name="QC FT")
        loc = JobLocation.objects.create(city="QCity", country="PH")
        for i in range(50):
            JobPost.objects.create(
                company=company, job_type=jt, job_location=loc, job_title=f"Job {i}", job_description="..."
            )

    def test_job_post_list_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/api/v1/jobs/job-posts/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 50)
        self.assertLessEqual(
            len(ctx),
            QUERY_BUDGET,
            f"Query count {len(ctx)} exceeds budget {QUERY_BUDGET}",
        )
