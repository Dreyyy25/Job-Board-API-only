from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
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
