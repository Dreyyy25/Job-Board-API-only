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
