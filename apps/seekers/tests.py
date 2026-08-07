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
            email='skill-seeker@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        self.skill = SkillSet.objects.create(skill_name='Python')
        self.row = SeekerSkillSet.objects.create(user_account=self.seeker, skill_set=self.skill, skill_level='Advanced')
        refresh = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def _assert_whole_row(self, row):
        """created_at is a serialized timestamp we don't pin exactly -- pop it,
        assert it's present, then whole-dict-equal the rest so every other
        key (including ones a regression might silently drop) is pinned."""
        created_at = row['skill_set'].pop('created_at')
        self.assertIsNotNone(created_at)
        self.assertEqual(
            row,
            {
                'id': str(self.row.id),
                # FK fields render as the raw related-object pk (a UUID instance) at
                # the pre-JSON-render `response.data` stage DRF's test client exposes
                # -- only direct model UUIDField values (like `id` above) go through
                # UUIDField.to_representation() and come out as str.
                'user_account': self.seeker.id,
                'skill_set': {
                    'id': str(self.skill.id),
                    'skill_name': 'Python',
                },
                'skill_level': 'Advanced',
            },
        )

    def test_list_nests_skill_name(self):
        r = self.client.get('/api/v1/seekers/seeker-skills/')
        row = r.data['results'][0]
        self._assert_whole_row(row)

    def test_dashboard_skills_nest_skill_name(self):
        r = self.client.get(f'/api/v1/seekers/dashboard/{self.seeker.id}/')
        self.assertEqual(r.status_code, 200)
        self._assert_whole_row(r.data['skills'][0])


class SeekerSkillCreateByNameTests(APITestCase):
    def setUp(self):
        self.seeker = UserAccount.objects.create_user(
            email='sbn@example.com', password='Str0ng-Password!', user_type='job_seeker'
        )
        refresh = RefreshToken.for_user(self.seeker)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def _post(self, body):
        return self.client.post('/api/v1/seekers/seeker-skills/', body, format='json')

    def test_new_name_creates_master_skill(self):
        r = self._post({'skill_name': 'Terraform', 'skill_level': 'Advanced'})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(SkillSet.objects.filter(skill_name='Terraform').exists())

    def test_existing_name_reused_case_insensitively(self):
        existing = SkillSet.objects.create(skill_name='Python')
        r = self._post({'skill_name': 'python', 'skill_level': 'Expert'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(SkillSet.objects.filter(skill_name__iexact='python').count(), 1)
        self.assertEqual(SeekerSkillSet.objects.get(user_account=self.seeker).skill_set_id, existing.id)

    def test_duplicate_attach_is_400_not_500(self):
        skill = SkillSet.objects.create(skill_name='SQL')
        SeekerSkillSet.objects.create(user_account=self.seeker, skill_set=skill, skill_level='Beginner')
        r = self._post({'skill_name': 'SQL', 'skill_level': 'Expert'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('already added', str(r.data['skill_set']))

    def test_neither_name_nor_id_is_400(self):
        r = self._post({'skill_level': 'Expert'})
        self.assertEqual(r.status_code, 400)

    def test_patch_level_only(self):
        skill = SkillSet.objects.create(skill_name='Go')
        row = SeekerSkillSet.objects.create(user_account=self.seeker, skill_set=skill, skill_level='Beginner')
        other = SkillSet.objects.create(skill_name='Rust')
        r = self.client.patch(f'/api/v1/seekers/seeker-skills/{row.id}/', {'skill_set': str(other.id)}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f'/api/v1/seekers/seeker-skills/{row.id}/', {'skill_level': 'Advanced'}, format='json')
        self.assertEqual(r.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.skill_level, 'Advanced')
        self.assertEqual(row.skill_set_id, skill.id)
