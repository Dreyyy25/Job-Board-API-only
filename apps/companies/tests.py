from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount
from apps.companies.models import BusinessStream, Company


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
        r = self.client.patch(
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
