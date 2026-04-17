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
