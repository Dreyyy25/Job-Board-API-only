from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.accounts.models import UserAccount
from apps.companies.models import BusinessStream, Company
from apps.jobs.models import JobType, JobLocation, JobPost, JobPostActivity, JobPostSkillSet
from apps.seekers.models import SkillSet


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


class JobPostNestedReadTests(APITestCase):
    """Task 2: list/retrieve replace bare FK UUIDs with nested objects."""

    def setUp(self):
        self.owner = UserAccount.objects.create_user(
            email="nested-owner@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.seeker = UserAccount.objects.create_user(
            email="nested-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        stream = BusinessStream.objects.create(business_stream_name="Data & AI")
        self.company = self.owner.company_profile
        self.company.company_name = "Halcyon Systems"
        self.company.business_stream = stream
        self.company.save()
        self.job_type = JobType.objects.create(job_type_name="Full-time")
        self.location = JobLocation.objects.create(
            street_address="1 Main St",
            city="Berlin",
            country="Germany",
            zip="10115",
            country_code="DE",
        )
        self.job = JobPost.objects.create(
            company=self.company,
            job_type=self.job_type,
            job_location=self.location,
            job_title="Backend Engineer",
            job_description="Build things",
            job_description_hidden="internal notes",
            salary_min="90000.00",
            salary_max="120000.00",
            salary_type="yearly",
        )
        self.skill = SkillSet.objects.create(skill_name="Python")
        self.job_skill = JobPostSkillSet.objects.create(
            job_post=self.job,
            skill_set=self.skill,
            skill_level="Advanced",
            is_required=True,
        )

    def _assert_nested_shape(self, data):
        self.assertEqual(data["company"]["id"], str(self.company.id))
        self.assertEqual(data["company"]["company_name"], "Halcyon Systems")
        self.assertEqual(
            data["company"]["business_stream"],
            {"id": str(self.company.business_stream_id), "business_stream_name": "Data & AI"},
        )
        self.assertEqual(
            data["job_type"],
            {"id": str(self.job_type.id), "job_type_name": "Full-time"},
        )
        self.assertEqual(
            data["job_location"],
            {
                "id": str(self.location.id),
                "street_address": "1 Main St",
                "city": "Berlin",
                "country": "Germany",
                "zip": "10115",
                "country_code": "DE",
            },
        )
        self.assertEqual(len(data["required_skills"]), 1)
        skill_entry = data["required_skills"][0]
        self.assertEqual(skill_entry["id"], str(self.job_skill.id))
        self.assertEqual(
            skill_entry["skill_set"],
            {"id": str(self.skill.id), "skill_name": "Python"},
        )
        self.assertEqual(skill_entry["skill_level"], "Advanced")
        self.assertIs(skill_entry["is_required"], True)

    def test_anonymous_list_has_nested_shape(self):
        r = self.client.get("/api/v1/jobs/job-posts/")
        self.assertEqual(r.status_code, 200)
        results = r.data["results"]
        job_data = next(j for j in results if j["id"] == str(self.job.id))
        self._assert_nested_shape(job_data)

    def test_anonymous_retrieve_has_nested_shape(self):
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self._assert_nested_shape(r.data)

    def test_anonymous_does_not_see_hidden_description_in_nested_read(self):
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("job_description_hidden", r.data)

    def test_owner_sees_hidden_description_in_nested_read(self):
        _auth(self.client, self.owner)
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data.get("job_description_hidden"), "internal notes")

    def test_admin_sees_hidden_description_in_nested_read(self):
        # Covers the is_staff/is_superuser branch of _job_post_is_owner,
        # which is not exercised by the owner/anon tests above -- an admin
        # is neither the job's company owner nor anonymous.
        admin = UserAccount.objects.create_superuser(
            email="nested-admin@example.com",
            password="Str0ng-Password!",
        )
        _auth(self.client, admin)
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data.get("job_description_hidden"), "internal notes")

    def test_company_id_is_company_id_not_user_account_id(self):
        r = self.client.get(f"/api/v1/jobs/job-posts/{self.job.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.data["company"]["id"], str(self.owner.id))
        self.assertEqual(r.data["company"]["id"], str(self.company.id))


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


class JobLocationAnonymousReadTests(APITestCase):
    def test_anonymous_can_list_job_locations(self):
        JobLocation.objects.create(city="Iloilo", country="PH")
        r = self.client.get("/api/v1/jobs/job-locations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class JobLocationWritePermissionTests(APITestCase):
    """JobLocation has no owner FK, so write access is company-create /
    admin-only-edit rather than an ownership check (see permissions.py)."""

    def setUp(self):
        self.company = UserAccount.objects.create_user(
            email="loc-company@example.com", password="Str0ng-Password!", user_type="company"
        )
        self.seeker = UserAccount.objects.create_user(
            email="loc-seeker@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.admin = UserAccount.objects.create_superuser(email="loc-admin@example.com", password="Str0ng-Password!")
        self.location = JobLocation.objects.create(city="Baguio", country="PH")

    def test_anonymous_get_list_returns_200(self):
        r = self.client.get("/api/v1/jobs/job-locations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_anonymous_post_returns_401(self):
        r = self.client.post("/api/v1/jobs/job-locations/", {"city": "Vigan", "country": "PH"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_seeker_post_returns_403(self):
        _auth(self.client, self.seeker)
        r = self.client.post("/api/v1/jobs/job-locations/", {"city": "Vigan", "country": "PH"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_post_returns_201(self):
        _auth(self.client, self.company)
        r = self.client.post("/api/v1/jobs/job-locations/", {"city": "Vigan", "country": "PH"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_company_put_returns_403(self):
        _auth(self.client, self.company)
        r = self.client.put(
            f"/api/v1/jobs/job-locations/{self.location.id}/",
            {"city": "Hacked", "country": "PH"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_patch_returns_403(self):
        _auth(self.client, self.company)
        r = self.client.patch(
            f"/api/v1/jobs/job-locations/{self.location.id}/",
            {"city": "Hacked"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_delete_returns_403(self):
        _auth(self.client, self.company)
        r = self.client.delete(f"/api/v1/jobs/job-locations/{self.location.id}/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(JobLocation.objects.filter(id=self.location.id).exists())

    def test_admin_patch_succeeds(self):
        _auth(self.client, self.admin)
        r = self.client.patch(
            f"/api/v1/jobs/job-locations/{self.location.id}/",
            {"city": "Baguio City"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.location.refresh_from_db()
        self.assertEqual(self.location.city, "Baguio City")

    def test_admin_delete_succeeds(self):
        _auth(self.client, self.admin)
        r = self.client.delete(f"/api/v1/jobs/job-locations/{self.location.id}/")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(JobLocation.objects.filter(id=self.location.id).exists())


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


class JobPostAdvancedFilterTests(APITestCase):
    """Task 3: business_stream filter, salary_floor coalesce filter, salary_rank ordering."""

    def setUp(self):
        owner_a = UserAccount.objects.create_user(
            email="adv-owner-a@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        owner_b = UserAccount.objects.create_user(
            email="adv-owner-b@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        self.stream_a = BusinessStream.objects.create(business_stream_name="Adv Stream A")
        self.stream_b = BusinessStream.objects.create(business_stream_name="Adv Stream B")
        self.company_a = owner_a.company_profile
        self.company_a.company_name = "AdvCoA"
        self.company_a.business_stream = self.stream_a
        self.company_a.save()
        self.company_b = owner_b.company_profile
        self.company_b.company_name = "AdvCoB"
        self.company_b.business_stream = self.stream_b
        self.company_b.save()
        jt = JobType.objects.create(job_type_name="AdvFT")
        loc = JobLocation.objects.create(city="AdvCity", country="PH")

        self.job_stream_a = JobPost.objects.create(
            company=self.company_a,
            job_type=jt,
            job_location=loc,
            job_title="Stream A Job",
            job_description="...",
        )
        self.job_stream_b = JobPost.objects.create(
            company=self.company_b,
            job_type=jt,
            job_location=loc,
            job_title="Stream B Job",
            job_description="...",
        )

        self.job_max_only = JobPost.objects.create(
            company=self.company_a,
            job_type=jt,
            job_location=loc,
            job_title="Max Only Job",
            job_description="...",
            salary_min=90000,
            salary_max=120000,
        )
        self.job_min_only = JobPost.objects.create(
            company=self.company_a,
            job_type=jt,
            job_location=loc,
            job_title="Min Only Job",
            job_description="...",
            salary_min=110000,
            salary_max=None,
        )
        self.job_both_null = JobPost.objects.create(
            company=self.company_a,
            job_type=jt,
            job_location=loc,
            job_title="No Salary Job",
            job_description="...",
        )
        self.job_below_floor = JobPost.objects.create(
            company=self.company_a,
            job_type=jt,
            job_location=loc,
            job_title="Below Floor Job",
            job_description="...",
            salary_min=40000,
            salary_max=50000,
        )

    def _titles(self, response):
        return sorted(j["job_title"] for j in response.data["results"])

    def test_filter_by_business_stream(self):
        r = self.client.get(f"/api/v1/jobs/job-posts/?business_stream={self.stream_a.id}")
        titles = self._titles(r)
        self.assertIn("Stream A Job", titles)
        self.assertNotIn("Stream B Job", titles)

    def test_salary_floor_matches_when_salary_max_meets_threshold(self):
        r = self.client.get("/api/v1/jobs/job-posts/?salary_floor=100000")
        self.assertIn("Max Only Job", self._titles(r))

    def test_salary_floor_matches_when_salary_max_null_but_salary_min_meets_threshold(self):
        r = self.client.get("/api/v1/jobs/job-posts/?salary_floor=100000")
        self.assertIn("Min Only Job", self._titles(r))

    def test_salary_floor_excludes_job_with_both_salaries_null(self):
        r = self.client.get("/api/v1/jobs/job-posts/?salary_floor=100000")
        self.assertNotIn("No Salary Job", self._titles(r))

    def test_salary_floor_excludes_job_below_threshold(self):
        r = self.client.get("/api/v1/jobs/job-posts/?salary_floor=100000")
        self.assertNotIn("Below Floor Job", self._titles(r))

    def test_ordering_by_salary_rank_desc_puts_salary_less_jobs_last(self):
        r = self.client.get("/api/v1/jobs/job-posts/?ordering=-salary_rank")
        titles = [j["job_title"] for j in r.data["results"]]
        idx_no_salary = titles.index("No Salary Job")
        idx_max_only = titles.index("Max Only Job")
        idx_min_only = titles.index("Min Only Job")
        idx_below_floor = titles.index("Below Floor Job")
        # Salary-less job (rank 0) sorts after every job with a usable figure.
        self.assertGreater(idx_no_salary, idx_max_only)
        self.assertGreater(idx_no_salary, idx_min_only)
        self.assertGreater(idx_no_salary, idx_below_floor)
        # Among salaried jobs, highest COALESCE(salary_max, salary_min) first.
        self.assertLess(idx_max_only, idx_min_only)
        self.assertLess(idx_min_only, idx_below_floor)


class JobPostSkillSearchTests(APITestCase):
    """Task 3: search_fields includes required_skills__skill_set__skill_name."""

    def setUp(self):
        owner = UserAccount.objects.create_user(
            email="skill-search-owner@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        stream = BusinessStream.objects.create(business_stream_name="Skill Search Tech")
        company = owner.company_profile
        company.company_name = "SkillSearchCo"
        company.business_stream = stream
        company.save()
        jt = JobType.objects.create(job_type_name="Skill Search FT")
        loc = JobLocation.objects.create(city="SkillCity", country="PH")

        self.job = JobPost.objects.create(
            company=company,
            job_type=jt,
            job_location=loc,
            job_title="Backend Role",
            job_description="Build APIs",
        )
        self.python_skill = SkillSet.objects.create(skill_name="Python")
        self.python_django_skill = SkillSet.objects.create(skill_name="Python Django")
        JobPostSkillSet.objects.create(
            job_post=self.job,
            skill_set=self.python_skill,
            skill_level="Advanced",
            is_required=True,
        )
        JobPostSkillSet.objects.create(
            job_post=self.job,
            skill_set=self.python_django_skill,
            skill_level="Intermediate",
            is_required=True,
        )

        self.other_job = JobPost.objects.create(
            company=company,
            job_type=jt,
            job_location=loc,
            job_title="Unrelated Role",
            job_description="General duties",
        )
        ruby_skill = SkillSet.objects.create(skill_name="Ruby")
        JobPostSkillSet.objects.create(
            job_post=self.other_job,
            skill_set=ruby_skill,
            skill_level="Beginner",
            is_required=True,
        )

    def test_search_by_skill_name_finds_job(self):
        r = self.client.get("/api/v1/jobs/job-posts/?search=Python")
        titles = [j["job_title"] for j in r.data["results"]]
        self.assertIn("Backend Role", titles)
        self.assertNotIn("Unrelated Role", titles)

    def test_search_by_skill_name_returns_job_with_two_matches_once(self):
        r = self.client.get("/api/v1/jobs/job-posts/?search=Python")
        matches = [j for j in r.data["results"] if j["job_title"] == "Backend Role"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(r.data["count"], 1)


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
        skill = SkillSet.objects.create(skill_name="QC Skill")
        for i in range(50):
            job = JobPost.objects.create(
                company=company, job_type=jt, job_location=loc, job_title=f"Job {i}", job_description="..."
            )
            if i % 5 == 0:
                # Exercise the required_skills prefetch on a subset of rows
                # so the nested read representation can't sneak in an N+1.
                JobPostSkillSet.objects.create(
                    job_post=job,
                    skill_set=skill,
                    skill_level="Advanced",
                    is_required=True,
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
        # The nested read shape must actually be present, not just cheap.
        sample = r.data["results"][0]
        self.assertIsInstance(sample["company"], dict)
        self.assertIn("business_stream", sample["company"])
        self.assertIsInstance(sample["job_type"], dict)
        self.assertIsInstance(sample["job_location"], dict)
        self.assertIn("required_skills", sample)


class ApplicationNestedReadTests(APITestCase):
    """List/retrieve applications return a nested job_post summary; write shape unchanged."""

    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email='nested-seeker@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        self.company_user = UserAccount.objects.create_user(
            email='nested-co@example.com', password='Str0ng-Password!', user_type='company'
        )
        company = Company.objects.get(user_account=self.company_user)
        company.company_name = 'Nested Co'
        company.save()
        jt = JobType.objects.create(job_type_name='Full-time')
        loc = JobLocation.objects.create(city='Berlin', country='Germany')
        self.job = JobPost.objects.create(
            company=company,
            job_type=jt,
            job_location=loc,
            job_title='ML Engineer',
            job_description='d',
            salary_min=90000,
            salary_max=120000,
            salary_type='yearly',
        )
        self.app = JobPostActivity.objects.create(user_account=self.seeker, job_post=self.job)
        self.expected_job_post = {
            'id': str(self.job.id),
            'job_title': 'ML Engineer',
            'company': {'id': str(self.job.company_id), 'company_name': 'Nested Co'},
            'job_type': {'id': str(self.job.job_type_id), 'job_type_name': 'Full-time'},
            'job_location': {'city': 'Berlin', 'country': 'Germany'},
            'salary_min': '90000.00',
            'salary_max': '120000.00',
            'salary_type': 'yearly',
            'deadline_date': None,
            'is_published': True,
            'is_active': True,
        }
        refresh = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_list_returns_nested_job_post_summary(self):
        r = self.client.get('/api/v1/jobs/job-applications/')
        self.assertEqual(r.status_code, 200)
        row = r.data['results'][0]
        self.assertEqual(row['job_post'], self.expected_job_post)

    def test_unpublished_job_still_nested_for_the_applicant(self):
        self.job.is_published = False
        self.job.save()
        r = self.client.get(f'/api/v1/jobs/job-applications/{self.app.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['job_post']['job_title'], 'ML Engineer')
        self.assertFalse(r.data['job_post']['is_published'])

    def test_user_applications_view_is_nested_too(self):
        r = self.client.get(f'/api/v1/jobs/applications/user/{self.seeker.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]['job_post']['company']['company_name'], 'Nested Co')

    def test_company_view_returns_nested_job_post_summary(self):
        refresh = RefreshToken.for_user(self.company_user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        r = self.client.get(f'/api/v1/jobs/applications/job/{self.job.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]['job_post']['company']['company_name'], 'Nested Co')
        self.assertEqual(r.data[0]['job_post'], self.expected_job_post)

    def test_list_query_count_is_flat(self):
        for i in range(10):
            u = UserAccount.objects.create_user(
                email=f'ns{i}@example.com', password='Str0ng-Password!', user_type='job_seeker'
            )
            JobPostActivity.objects.create(user_account=u, job_post=self.job)
        staff = UserAccount.objects.create_user(
            email='ns-admin@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        staff.is_staff = True
        staff.save()
        refresh = RefreshToken.for_user(staff)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        with self.assertNumQueries(3):  # count + page + auth user lookup
            self.client.get('/api/v1/jobs/job-applications/?page_size=50')


class ApplicationLockdownTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email='lock-seeker@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        self.other_seeker = UserAccount.objects.create_user(
            email='lock-other@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        self.company_user = UserAccount.objects.create_user(
            email='lock-co@example.com', password='Str0ng-Password!', user_type='company'
        )
        company = Company.objects.get(user_account=self.company_user)
        jt = JobType.objects.create(job_type_name='Full-time')
        loc = JobLocation.objects.create(city='X', country='Y')
        self.job = JobPost.objects.create(
            company=company, job_type=jt, job_location=loc, job_title='T', job_description='d'
        )
        self.app = JobPostActivity.objects.create(user_account=self.seeker, job_post=self.job)

    def _as(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def _patch(self, status_value):
        return self.client.patch(
            f'/api/v1/jobs/job-applications/{self.app.id}/', {'application_status': status_value}, format='json'
        )

    def test_viewset_post_is_gone(self):
        self._as(self.other_seeker)
        r = self.client.post(
            '/api/v1/jobs/job-applications/',
            {'user_account': str(self.seeker.id), 'job_post': str(self.job.id), 'application_status': 'accepted'},
            format='json',
        )
        self.assertEqual(r.status_code, 405)

    def test_update_cannot_move_the_application(self):
        self._as(self.seeker)
        r = self.client.patch(
            f'/api/v1/jobs/job-applications/{self.app.id}/',
            {'user_account': str(self.other_seeker.id), 'cover_letter': 'new', 'application_status': 'withdrawn'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.user_account_id, self.seeker.id)  # read-only ignored
        self.assertEqual(self.app.cover_letter, '')
        self.assertEqual(self.app.application_status, 'withdrawn')

    def test_seeker_transitions(self):
        self._as(self.seeker)
        self.assertEqual(self._patch('accepted').status_code, 400)  # self-accept blocked
        self.assertEqual(self._patch('withdrawn').status_code, 200)  # pending -> withdrawn OK
        self.assertEqual(self._patch('pending').status_code, 400)  # un-withdraw blocked

    def test_seeker_can_withdraw_from_reviewed(self):
        self.app.application_status = 'reviewed'
        self.app.save()
        self._as(self.seeker)
        self.assertEqual(self._patch('withdrawn').status_code, 200)

    def test_company_transitions(self):
        self._as(self.company_user)
        self.assertEqual(self._patch('withdrawn').status_code, 400)  # company can't withdraw
        self.assertEqual(self._patch('reviewed').status_code, 200)  # pending -> reviewed
        self.assertEqual(self._patch('pending').status_code, 400)  # no going back
        self.assertEqual(self._patch('accepted').status_code, 200)  # reviewed -> accepted

    def test_same_value_is_a_noop_200(self):
        self._as(self.seeker)
        self.assertEqual(self._patch('pending').status_code, 200)

    def test_admin_unrestricted(self):
        admin = UserAccount.objects.create_user(
            email='lock-admin@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        admin.is_staff = True
        admin.save()
        self._as(admin)
        self.assertEqual(self._patch('accepted').status_code, 200)
        self.assertEqual(self._patch('pending').status_code, 200)
