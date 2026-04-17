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
