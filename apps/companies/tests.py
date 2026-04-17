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
