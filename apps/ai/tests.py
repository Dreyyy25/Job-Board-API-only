from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserAccount


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")


class AIUsageLogTests(TestCase):
    def test_creates_row_with_feature_choice(self):
        from apps.ai.models import AIUsageLog
        user = UserAccount.objects.create_user(
            email="co@example.com", password="Str0ng-Password!", user_type="company")
        row = AIUsageLog.objects.create(
            feature=AIUsageLog.Feature.JOB_POST_WRITER,
            user=user,
            model="gemini-2.5-flash",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1200,
        )
        self.assertEqual(row.feature, "job_post_writer")
        self.assertIsNotNone(row.id)

    def test_user_delete_keeps_log(self):
        from apps.ai.models import AIUsageLog
        user = UserAccount.objects.create_user(
            email="co2@example.com", password="Str0ng-Password!", user_type="company")
        row = AIUsageLog.objects.create(
            feature=AIUsageLog.Feature.CHAT, user=user, model="m")
        user.delete()
        row.refresh_from_db()
        self.assertIsNone(row.user)


class ModelFactoryTests(TestCase):
    def test_flash_tier_uses_configured_model(self):
        import config
        from apps.ai.llm import get_model
        model = get_model('flash')
        # ChatGoogleGenerativeAI normalises to 'models/<id>'
        self.assertIn(config.AI_MODEL_FLASH, model.model)

    def test_pro_tier_uses_configured_model(self):
        import config
        from apps.ai.llm import get_model
        self.assertIn(config.AI_MODEL_PRO, get_model('pro').model)

    def test_unknown_tier_raises(self):
        from apps.ai.llm import get_model
        with self.assertRaises(ValueError):
            get_model('turbo')


class SchemaTests(TestCase):
    def test_job_post_draft_validates(self):
        from apps.ai.schemas import JobPostDraft
        draft = JobPostDraft(
            job_title="Backend Dev",
            job_description="Build APIs.",
            suggested_skills=[
                {"skill_name": "Python", "skill_level": "Advanced", "is_required": True},
            ],
        )
        self.assertEqual(draft.suggested_skills[0].skill_name, "Python")

    def test_bad_skill_level_rejected(self):
        from pydantic import ValidationError
        from apps.ai.schemas import JobPostDraft
        with self.assertRaises(ValidationError):
            JobPostDraft(
                job_title="X", job_description="Y",
                suggested_skills=[
                    {"skill_name": "Python", "skill_level": "Ninja", "is_required": True},
                ],
            )


class PromptTests(TestCase):
    def test_prompt_carries_notes_and_taxonomy(self):
        from apps.ai.prompts import build_job_post_writer_prompt
        messages = build_job_post_writer_prompt(
            notes="need a django dev",
            company_name="Acme",
            business_stream="Tech",
            job_type_name="Full-time",
            location_hint="Manila",
            skill_names=["Django", "Python"],
        )
        human = messages[-1][1]
        self.assertIn("need a django dev", human)
        self.assertIn("Django", human)
        self.assertIn("Acme", human)
        self.assertEqual(messages[0][0], "system")


class GenerateJobPostDraftTests(TestCase):
    def setUp(self):
        from apps.seekers.models import SkillSet
        self.company_user = UserAccount.objects.create_user(
            email="acme@example.com", password="Str0ng-Password!", user_type="company")
        profile = self.company_user.company_profile
        profile.company_name = "Acme"
        profile.save()
        self.python = SkillSet.objects.create(skill_name="Python")
        SkillSet.objects.create(skill_name="Django")

    def _draft(self, skills):
        from apps.ai.schemas import JobPostDraft
        return JobPostDraft(
            job_title="Backend Dev", job_description="Build APIs.",
            suggested_skills=skills,
        )

    def test_happy_path_maps_names_to_ids_and_drops_inventions(self):
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([self._draft([
            {"skill_name": "python", "skill_level": "Advanced", "is_required": True},
            {"skill_name": "Blockchain Ninja", "skill_level": "Expert", "is_required": False},
        ])])
        result = generate_job_post_draft(
            self.company_user, notes="need a dev", model=fake)
        self.assertEqual(result["job_title"], "Backend Dev")
        self.assertEqual(len(result["suggested_skills"]), 1)  # invention dropped
        self.assertEqual(result["suggested_skills"][0]["skill_set_id"], str(self.python.id))
        self.assertEqual(result["suggested_skills"][0]["skill_name"], "Python")

    def test_writes_usage_log_row(self):
        from apps.ai.models import AIUsageLog
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([self._draft([])])
        generate_job_post_draft(self.company_user, notes="n", model=fake)
        row = AIUsageLog.objects.get()
        self.assertEqual(row.feature, "job_post_writer")
        self.assertEqual(row.input_tokens, 100)
        self.assertEqual(row.output_tokens, 50)
        self.assertEqual(row.user, self.company_user)

    def test_provider_error_retries_once_then_raises(self):
        from apps.ai.exceptions import AIProviderError
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([RuntimeError("boom"), RuntimeError("boom")])
        with self.assertRaises(AIProviderError):
            generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(fake.parsed_outputs, [])  # both attempts consumed

    def test_provider_error_then_success_recovers(self):
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([RuntimeError("boom"), self._draft([])])
        result = generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(result["job_title"], "Backend Dev")

    def test_quota_error_raises_immediately_without_retry(self):
        from apps.ai.exceptions import AIQuotaExceededError
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        quota = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        fake = FakeStructuredChatModel([quota, self._draft([])])
        with self.assertRaises(AIQuotaExceededError):
            generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(len(fake.parsed_outputs), 1)  # no second attempt

    def test_unparseable_output_raises_invalid_after_retry(self):
        from apps.ai.exceptions import AIResponseInvalidError
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([None, None])
        with self.assertRaises(AIResponseInvalidError):
            generate_job_post_draft(self.company_user, notes="n", model=fake)


class JobPostAssistEndpointTests(APITestCase):
    URL = "/api/v1/ai/job-post-assist/"

    def setUp(self):
        from apps.seekers.models import SkillSet
        self.company_user = UserAccount.objects.create_user(
            email="co@example.com", password="Str0ng-Password!", user_type="company")
        self.seeker = UserAccount.objects.create_user(
            email="sk@example.com", password="Str0ng-Password!", user_type="job_seeker")
        self.python = SkillSet.objects.create(skill_name="Python")

    def _fake(self, *items):
        from apps.ai.testing import FakeStructuredChatModel
        return FakeStructuredChatModel(list(items))

    def _ok_draft(self):
        from apps.ai.schemas import JobPostDraft
        return JobPostDraft(
            job_title="Backend Dev", job_description="Build APIs.",
            suggested_skills=[{"skill_name": "Python",
                               "skill_level": "Advanced", "is_required": True}],
        )

    def test_anonymous_gets_401(self):
        r = self.client.post(self.URL, {"notes": "x"})
        self.assertEqual(r.status_code, 401)

    def test_seeker_gets_403(self):
        _auth(self.client, self.seeker)
        r = self.client.post(self.URL, {"notes": "x"})
        self.assertEqual(r.status_code, 403)

    def test_missing_notes_gets_400(self):
        _auth(self.client, self.company_user)
        r = self.client.post(self.URL, {})
        self.assertEqual(r.status_code, 400)

    def test_company_gets_draft_with_real_skill_ids(self):
        _auth(self.client, self.company_user)
        with patch("apps.ai.services.get_model", return_value=self._fake(self._ok_draft())):
            r = self.client.post(self.URL, {"notes": "need a django dev"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["job_title"], "Backend Dev")
        self.assertEqual(
            r.data["suggested_skills"][0]["skill_set_id"], str(self.python.id))

    def test_quota_error_maps_to_429(self):
        _auth(self.client, self.company_user)
        boom = RuntimeError("429 RESOURCE_EXHAUSTED")
        with patch("apps.ai.services.get_model", return_value=self._fake(boom)):
            r = self.client.post(self.URL, {"notes": "x"})
        self.assertEqual(r.status_code, 429)

    def test_provider_error_maps_to_502(self):
        _auth(self.client, self.company_user)
        with patch("apps.ai.services.get_model",
                   return_value=self._fake(RuntimeError("boom"), RuntimeError("boom"))):
            r = self.client.post(self.URL, {"notes": "x"})
        self.assertEqual(r.status_code, 502)

    def test_throttle_classes_are_the_four_layer_stack(self):
        from apps.ai import views
        from apps.ai.throttling import AIRateThrottle
        from jobApp.throttling import BurstRateThrottle
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        self.assertEqual(
            views.job_post_assist.cls.throttle_classes,
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])
