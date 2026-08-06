from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount
from apps.seekers.models import EducationData, SkillSet, SeekerSkillSet


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")


class SeekerPermissionTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="s@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.other = UserAccount.objects.create_user(
            email="o@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        self.other_edu = EducationData.objects.create(
            user_account=self.other,
            institute_university_name="X",
            degree_type="Bachelor",
        )

    def test_seeker_cannot_edit_other_education(self):
        _auth(self.client, self.seeker)
        r = self.client.patch(
            f"/api/v1/seekers/education/{self.other_edu.id}/", {"institute_university_name": "Pwned"}, format="json"
        )
        self.assertIn(r.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.other_edu.refresh_from_db()
        self.assertEqual(self.other_edu.institute_university_name, "X")

    def test_seeker_can_create_own_education(self):
        _auth(self.client, self.seeker)
        r = self.client.post(
            "/api/v1/seekers/education/",
            {
                "institute_university_name": "Mine",
                "degree_type": "Bachelor",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(EducationData.objects.get(id=r.data["id"]).user_account_id, self.seeker.id)


from datetime import date
from django.db import IntegrityError
from apps.seekers.models import ExperienceData


class EducationConstraintTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="edu-c@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        _auth(self.client, self.seeker)

    def test_percentage_out_of_range_rejected_by_serializer(self):
        r = self.client.post(
            "/api/v1/seekers/education/",
            {
                "institute_university_name": "X",
                "degree_type": "Bachelor",
                "percentage": 150,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_percentage_out_of_range_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            EducationData.objects.create(
                user_account=self.seeker,
                institute_university_name="X",
                degree_type="Bachelor",
                percentage=150,
            )

    def test_start_after_end_rejected_by_serializer(self):
        r = self.client.post(
            "/api/v1/seekers/education/",
            {
                "institute_university_name": "X",
                "degree_type": "Bachelor",
                "start_date": "2020-01-01",
                "end_date": "2019-01-01",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_start_after_end_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            EducationData.objects.create(
                user_account=self.seeker,
                institute_university_name="X",
                degree_type="Bachelor",
                start_date=date(2020, 1, 1),
                end_date=date(2019, 1, 1),
            )


class ExperienceConstraintTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email="exp-c@example.com", password="Str0ng-Password!", user_type="job_seeker"
        )
        _auth(self.client, self.seeker)

    def test_start_after_end_rejected_by_serializer(self):
        r = self.client.post(
            "/api/v1/seekers/experience/",
            {
                "company_name": "X",
                "position": "Dev",
                "start_date": "2020-01-01",
                "end_date": "2019-01-01",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_start_after_end_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            ExperienceData.objects.create(
                user_account=self.seeker,
                company_name="X",
                position="Dev",
                start_date=date(2020, 1, 1),
                end_date=date(2019, 1, 1),
            )


class SeekerProfileCreateConflictTests(APITestCase):
    def test_seeker_profile_create_returns_400_when_profile_exists(self):
        user = UserAccount.objects.create_user(
            email="sc@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        # Signal already created a SeekerProfile.
        _auth(self.client, user)
        r = self.client.post(
            "/api/v1/seekers/profiles/",
            {
                "first_name": "Dup",
                "last_name": "Attempt",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", r.data)


class SeekerSkillNestedReadTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email='skill-seeker@example.com', password='Str0ng-Password!', user_type='job_seeker')
        self.skill = SkillSet.objects.create(skill_name='Python')
        self.row = SeekerSkillSet.objects.create(
            user_account=self.seeker, skill_set=self.skill, skill_level='Advanced')
        refresh = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_list_nests_skill_name(self):
        r = self.client.get('/api/v1/seekers/seeker-skills/')
        row = r.data['results'][0]
        self.assertEqual(row['skill_set']['skill_name'], 'Python')
        self.assertEqual(row['skill_level'], 'Advanced')

    def test_dashboard_skills_nest_skill_name(self):
        r = self.client.get(f'/api/v1/seekers/dashboard/{self.seeker.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['skills'][0]['skill_set']['skill_name'], 'Python')
