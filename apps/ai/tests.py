from django.test import TestCase

from apps.accounts.models import UserAccount


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
