# AI Resume Import Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seekers upload a PDF resume or paste text at `POST /api/v1/ai/resume-import/` and get back structured education/experience/skills drafts shaped like the real `EducationData`/`ExperienceData` models, per the approved spec `docs/superpowers/specs/2026-07-14-ai-agents-design.md` (Phase 2).

**Architecture:** Reuses the Phase 0/1 foundation in `apps.ai` — `get_model('flash')`, `_invoke_structured(model, schema, prompt, usage_sink)`, the per-attempt `AIUsageLog` pattern, `FakeStructuredChatModel`, `AIRateThrottle`, and the thin-view/exception-translation style. New pieces: `InvalidResumeFileError`, `IsSeekerUser`, resume extraction schemas, a multimodal prompt builder (PDF via inline base64 content block), the `extract_resume` service, and the endpoint. Draft-only — nothing is persisted except usage logs; confirmed rows go through the existing seekers CRUD endpoints.

**Tech Stack:** existing `langchain-google-genai` 4.2.7 (no new dependencies).

## Global Constraints

- Same house rules as Phase 1: uv commands; env only via `config.py`; UUID PKs; thin views; services own logic; domain exceptions map 1:1 to HTTP; `CustomJWTAuthentication` default; four throttle classes `[AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle]`; `@extend_schema` on function views; `spectacular --validate` warning-free; offline tests only; conventional commits, **no Co-Authored-By footer**.
- Verified stack facts (July 2026, from langchain-google-genai 4.2.x source):
  - Inline PDF block shape (the package's own docstring form): `{"type": "file", "source_type": "base64", "mime_type": "application/pdf", "data": <b64 str>}` inside `HumanMessage(content=[...])`, alongside a `{"type": "text", ...}` block.
  - `with_structured_output(Schema, method="json_schema", include_raw=True)` composes with multimodal messages — no restriction.
  - 5 MB inline PDF is far under Gemini's limits (50 MB PDF cap, 100 MB inline payload).
  - **Date fields must be plain `str`** — the library silently strips `format` from schemas before they reach Gemini, so `datetime.date`/`format:"date"` hints are lost. Convey the ISO format in the field `description` instead.
- `FakeStructuredChatModel` ignores its input, so message-shape coverage (PDF block, text block) lives in prompt-builder unit tests, not service tests.
- Current service interfaces (post-final-review fix, verbatim): `_invoke_structured(model, schema, prompt, usage_sink)` appends `{'usage': dict, 'latency_ms': int}` per token-consuming attempt and returns the parsed instance; callers write ledger rows in a `finally` block.

## File Structure

| File | Change |
|---|---|
| `apps/ai/exceptions.py` (modify) | Add `InvalidResumeFileError` |
| `apps/ai/permissions.py` (modify) | Add `IsSeekerUser` |
| `apps/ai/schemas.py` (modify) | Add `EducationEntry`, `ExperienceEntry`, `ResumeSkill`, `ResumeExtract` |
| `apps/ai/prompts.py` (modify) | Add `RESUME_IMPORT_SYSTEM` + `build_resume_import_messages` |
| `apps/ai/services.py` (modify) | Extract `_record_usage` helper (refactor Phase 1 caller); add `extract_resume` |
| `apps/ai/serializers.py` (modify) | Add `ResumeImportRequestSerializer` |
| `apps/ai/views.py` (modify) | Add `resume_import` view + response inline serializers |
| `apps/ai/urls.py` (modify) | Add `resume-import/` path |
| `apps/ai/tests.py` (modify) | Append test classes per task |
| `CLAUDE.md` (modify) | Extend the `/api/v1/ai/` routing bullet |

---

### Task 1: Exception, permission, and extraction schemas

**Files:**
- Modify: `apps/ai/exceptions.py`, `apps/ai/permissions.py`, `apps/ai/schemas.py`
- Test: `apps/ai/tests.py` (append)

**Interfaces:**
- Produces: `InvalidResumeFileError`; `IsSeekerUser`; `ResumeExtract(education: list[EducationEntry], experience: list[ExperienceEntry], skills: list[ResumeSkill])` where entry field names mirror `EducationData`/`ExperienceData` model fields exactly and all date fields are `str | None`.

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.ResumeSchemaTests apps.ai.tests.IsSeekerUserTests
```

Expected: ERROR — `ResumeExtract`/`IsSeekerUser` don't exist.

- [ ] **Step 3: Add to `apps/ai/exceptions.py`**

```python
class InvalidResumeFileError(Exception):
    """Resume upload rejected: wrong type, over size cap, unreadable, or
    not exactly one of text/file → HTTP 400."""
```

- [ ] **Step 4: Add to `apps/ai/permissions.py`**

```python
class IsSeekerUser(BasePermission):
    """Job-seeker-type users only. Unauthenticated → 401 via DRF."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'job_seeker'
        )
```

- [ ] **Step 5: Add to `apps/ai/schemas.py`** (below the existing classes; `SkillLevel` and `Literal`/`BaseModel`/`Field` imports already exist)

```python
DegreeType = Literal[
    'High School', 'Associate', 'Bachelor', 'Master', 'PhD',
    'Certificate', 'Diploma',
]

# Date fields are plain str, NOT datetime.date: langchain-google-genai strips
# `format` from schemas before they reach Gemini, so the ISO rule must live in
# the description. Field names mirror the Django models so confirmed drafts
# POST straight to the existing seekers CRUD endpoints.


class EducationEntry(BaseModel):
    institute_university_name: str = Field(description="Institution name as written in the resume.")
    degree_type: DegreeType | None = Field(
        description="Closest matching degree type, or null if unclear.")
    field_of_study: str = Field(description="Major/field, empty string if absent.")
    academic_details: str = Field(description="Honors, thesis, or notes; empty string if absent.")
    percentage: float | None = Field(
        description="Grade as a 0-100 number ONLY if explicitly stated, else null.")
    start_date: str | None = Field(
        description="ISO date YYYY-MM-DD; year-only becomes YYYY-01-01; null if absent.")
    end_date: str | None = Field(
        description="ISO date YYYY-MM-DD; year-only becomes YYYY-01-01; null if absent or ongoing.")


class ExperienceEntry(BaseModel):
    company_name: str = Field(description="Employer name as written.")
    position: str = Field(description="Job title as written.")
    description: str = Field(description="Responsibilities/achievements; empty string if absent.")
    job_location_city: str = Field(description="City, empty string if absent.")
    job_location_country: str = Field(description="Country, empty string if absent.")
    start_date: str | None = Field(
        description="ISO date YYYY-MM-DD; year-only becomes YYYY-01-01; null if absent.")
    end_date: str | None = Field(
        description="ISO date YYYY-MM-DD; null if absent or current role.")


class ResumeSkill(BaseModel):
    skill_name: str = Field(description="One skill as named in the resume.")
    skill_level: SkillLevel = Field(
        description="Proficiency estimated from context; Intermediate when unclear.")


class ResumeExtract(BaseModel):
    education: list[EducationEntry] = Field(description="All education records found.")
    experience: list[ExperienceEntry] = Field(description="All work experience found.")
    skills: list[ResumeSkill] = Field(description="All identifiable skills.")
```

- [ ] **Step 6: Run tests to verify pass, then the app suite**

```bash
uv run python manage.py test apps.ai
```

Expected: all PASS (27 existing + 4 new).

- [ ] **Step 7: Commit**

```bash
git add apps/ai/exceptions.py apps/ai/permissions.py apps/ai/schemas.py apps/ai/tests.py
git commit -m "feat(ai): resume extraction schemas, seeker permission, resume file exception"
```

---

### Task 2: Multimodal prompt builder

**Files:**
- Modify: `apps/ai/prompts.py`
- Test: `apps/ai/tests.py` (append)

**Interfaces:**
- Produces: `build_resume_import_messages(*, resume_text=None, pdf_b64=None) -> list` — `[("system", RESUME_IMPORT_SYSTEM), HumanMessage(content=[...])]`. Exactly one of the kwargs is non-None (the service guarantees this; the builder does not re-validate).

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.ResumePromptTests
```

Expected: ERROR — `build_resume_import_messages` doesn't exist.

- [ ] **Step 3: Add to `apps/ai/prompts.py`**

At the top of the file add the import:

```python
from langchain_core.messages import HumanMessage
```

Then append:

```python
RESUME_IMPORT_SYSTEM = (
    "You are a resume parser for a job board. Extract the candidate's education, "
    "work experience, and skills EXACTLY as stated — never invent institutions, "
    "employers, dates, or numbers that are not in the resume. Dates are ISO "
    "YYYY-MM-DD; when only a year or month is given use the first day; use null "
    "when absent. Map degree names to the closest degree_type choice or null. "
    "Estimate skill_level from context, defaulting to Intermediate. percentage "
    "is a 0-100 grade figure — null unless explicitly stated."
)

_RESUME_INSTRUCTION = "Extract structured data from this resume."


def build_resume_import_messages(*, resume_text=None, pdf_b64=None):
    """Messages for resume extraction. Exactly one kwarg is non-None
    (enforced by the service; not re-validated here).

    PDF bytes travel as an inline base64 file content block — the shape
    langchain-google-genai's own docstring documents for Gemini.
    """
    if pdf_b64 is not None:
        content = [
            {
                "type": "file",
                "source_type": "base64",
                "mime_type": "application/pdf",
                "data": pdf_b64,
            },
            {"type": "text", "text": _RESUME_INSTRUCTION},
        ]
    else:
        content = [
            {"type": "text", "text": f"{_RESUME_INSTRUCTION}\n\nResume:\n{resume_text}"},
        ]
    return [("system", RESUME_IMPORT_SYSTEM), HumanMessage(content=content)]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run python manage.py test apps.ai
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai/prompts.py apps/ai/tests.py
git commit -m "feat(ai): resume import prompt with inline-PDF content block"
```

---

### Task 3: `extract_resume` service + `_record_usage` refactor

**Files:**
- Modify: `apps/ai/services.py`
- Test: `apps/ai/tests.py` (append)

**Interfaces:**
- Consumes: `_invoke_structured(model, schema, prompt, usage_sink)` (existing), `build_resume_import_messages` (Task 2), `ResumeExtract` (Task 1), `InvalidResumeFileError` (Task 1).
- Produces: `_record_usage(feature, user, model, usage_sink)` (shared helper; Phase 1 caller refactored onto it — its tests must stay green); `extract_resume(user, *, text='', file=None, model=None) -> dict` returning `{'education': [...], 'experience': [...], 'skills': [{'skill_set_id','skill_name','skill_level'}], 'new_skill_suggestions': [str]}`; raises `InvalidResumeFileError | AIQuotaExceededError | AIProviderError | AIResponseInvalidError`.

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

At the top of the file add (alongside existing imports):

```python
from django.core.files.uploadedfile import SimpleUploadedFile
```

Then append:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.ExtractResumeTests
```

Expected: ERROR — `extract_resume` doesn't exist.

- [ ] **Step 3: Modify `apps/ai/services.py`**

Add imports at the top (alongside the existing ones):

```python
import base64
```

and extend the two `from .` import blocks:

```python
from .exceptions import (
    AIProviderError,
    AIQuotaExceededError,
    AIResponseInvalidError,
    CompanyProfileMissingError,
    InvalidResumeFileError,
)
from .prompts import build_job_post_writer_prompt, build_resume_import_messages
from .schemas import JobPostDraft, ResumeExtract
```

Add the constant and helper below `_invoke_structured`:

```python
MAX_RESUME_BYTES = 5 * 1024 * 1024


def _record_usage(feature, user, model, usage_sink):
    """One AIUsageLog row per token-consuming attempt (see _invoke_structured)."""
    for entry in usage_sink:
        usage = entry['usage']
        AIUsageLog.objects.create(
            feature=feature,
            user=user,
            model=str(getattr(model, 'model', '')),
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            latency_ms=entry['latency_ms'],
        )
```

Refactor `generate_job_post_draft`'s `finally` block to use it — replace the existing `for entry in usage_sink:` loop (and its comment) with:

```python
    finally:
        # One row per attempt that returned a result object — including
        # parse failures — so billable spend is never silently dropped.
        _record_usage(AIUsageLog.Feature.JOB_POST_WRITER, user, model, usage_sink)
```

Append the new service:

```python
def extract_resume(user, *, text='', file=None, model=None):
    """Extract structured education/experience/skills from a resume.

    Draft-only: persists nothing but usage logs. Returns
    {'education': [...], 'experience': [...],
     'skills': [{'skill_set_id', 'skill_name', 'skill_level'}],
     'new_skill_suggestions': [str]} — entry keys mirror the
    EducationData/ExperienceData models; known skills map to real SkillSet
    rows, unknown ones surface as suggestions instead of being dropped.
    """
    text = (text or '').strip()
    if bool(text) == bool(file):
        raise InvalidResumeFileError('Provide exactly one of text or file.')

    pdf_b64 = None
    if file is not None:
        if file.size > MAX_RESUME_BYTES:
            raise InvalidResumeFileError('PDF must be 5 MB or smaller.')
        header = file.read(5)
        file.seek(0)
        if header != b'%PDF-':
            raise InvalidResumeFileError('File is not a readable PDF.')
        pdf_b64 = base64.b64encode(file.read()).decode('ascii')

    model = model or get_model('flash')
    prompt = build_resume_import_messages(
        resume_text=text or None, pdf_b64=pdf_b64)

    usage_sink = []
    try:
        extract = _invoke_structured(model, ResumeExtract, prompt, usage_sink)
    finally:
        _record_usage(AIUsageLog.Feature.RESUME_IMPORT, user, model, usage_sink)

    by_name = {s.skill_name.lower(): s for s in SkillSet.objects.all()}
    skills, suggestions, seen = [], [], set()
    for item in extract.skills:
        name = item.skill_name.strip()
        if not name:
            continue
        skill = by_name.get(name.lower())
        if skill is not None:
            if str(skill.id) in seen:
                continue
            seen.add(str(skill.id))
            skills.append({
                'skill_set_id': str(skill.id),
                'skill_name': skill.skill_name,
                'skill_level': item.skill_level,
            })
        elif name.lower() not in {s.lower() for s in suggestions}:
            suggestions.append(name)

    return {
        'education': [e.model_dump() for e in extract.education],
        'experience': [e.model_dump() for e in extract.experience],
        'skills': skills,
        'new_skill_suggestions': suggestions,
    }
```

- [ ] **Step 4: Run the app suite — new tests AND Phase 1 usage-log tests must pass**

```bash
uv run python manage.py test apps.ai
```

Expected: all PASS (the `_record_usage` refactor must not disturb `GenerateJobPostDraftTests`).

- [ ] **Step 5: Commit**

```bash
git add apps/ai/services.py apps/ai/tests.py
git commit -m "feat(ai): resume extraction service with skill mapping and shared usage recorder"
```

---

### Task 4: Serializer, view, URL

**Files:**
- Modify: `apps/ai/serializers.py`, `apps/ai/views.py`, `apps/ai/urls.py`
- Test: `apps/ai/tests.py` (append)

**Interfaces:**
- Consumes: `extract_resume` (Task 3), `IsSeekerUser` (Task 1), `InvalidResumeFileError` (Task 1), existing `_AIErrorSerializer`/throttles. Tests patch `"apps.ai.services.get_model"` exactly as Phase 1 endpoint tests do.
- Produces: `POST /api/v1/ai/resume-import/` (name `ai-resume-import`) — multipart or form body with exactly one of `text`/`file` → 200 draft; 400 file/combination errors; 401 anon; 403 company; 429 quota; 502 provider.

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.ResumeImportEndpointTests
```

Expected: 404s / attribute errors — view doesn't exist yet.

- [ ] **Step 3: Add to `apps/ai/serializers.py`**

```python
class ResumeImportRequestSerializer(serializers.Serializer):
    """Exactly-one-of validation lives in the service (InvalidResumeFileError)."""
    text = serializers.CharField(
        max_length=20000, required=False, allow_blank=True, default='')
    file = serializers.FileField(required=False, allow_null=True)
```

- [ ] **Step 4: Add to `apps/ai/views.py`**

Extend the exceptions import with `InvalidResumeFileError` and the serializers import with `ResumeImportRequestSerializer`, plus add `IsSeekerUser` to the permissions import. Then append below the existing view:

```python
_EducationEntrySerializer = inline_serializer(
    name='ResumeEducationEntry',
    fields={
        'institute_university_name': drf_serializers.CharField(),
        'degree_type': drf_serializers.CharField(allow_null=True),
        'field_of_study': drf_serializers.CharField(allow_blank=True),
        'academic_details': drf_serializers.CharField(allow_blank=True),
        'percentage': drf_serializers.FloatField(allow_null=True),
        'start_date': drf_serializers.CharField(allow_null=True),
        'end_date': drf_serializers.CharField(allow_null=True),
    },
)

_ExperienceEntrySerializer = inline_serializer(
    name='ResumeExperienceEntry',
    fields={
        'company_name': drf_serializers.CharField(),
        'position': drf_serializers.CharField(),
        'description': drf_serializers.CharField(allow_blank=True),
        'job_location_city': drf_serializers.CharField(allow_blank=True),
        'job_location_country': drf_serializers.CharField(allow_blank=True),
        'start_date': drf_serializers.CharField(allow_null=True),
        'end_date': drf_serializers.CharField(allow_null=True),
    },
)

_ResumeSkillSerializer = inline_serializer(
    name='ResumeSkillOut',
    fields={
        'skill_set_id': drf_serializers.UUIDField(),
        'skill_name': drf_serializers.CharField(),
        'skill_level': drf_serializers.CharField(),
    },
)

_ResumeImportResponseSerializer = inline_serializer(
    name='ResumeImportResponse',
    fields={
        # inline_serializer returns an instance; recover the class to build the many=True list
        'education': type(_EducationEntrySerializer)(many=True),
        'experience': type(_ExperienceEntrySerializer)(many=True),
        'skills': type(_ResumeSkillSerializer)(many=True),
        'new_skill_suggestions': drf_serializers.ListField(
            child=drf_serializers.CharField()),
    },
)


@extend_schema(
    request=ResumeImportRequestSerializer,
    responses={
        200: _ResumeImportResponseSerializer,
        400: _AIErrorSerializer,
        401: _AIErrorSerializer,
        403: _AIErrorSerializer,
        429: _AIErrorSerializer,
        502: _AIErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['POST'])
@permission_classes([IsSeekerUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])
def resume_import(request):
    """Extract a structured draft from a resume. Returns a draft — creates nothing."""
    serializer = ResumeImportRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        draft = services.extract_resume(
            request.user,
            text=serializer.validated_data.get('text', ''),
            file=serializer.validated_data.get('file'),
        )
    except InvalidResumeFileError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except AIQuotaExceededError:
        return Response({'error': 'AI provider quota exceeded — try again later'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'},
                        status=status.HTTP_502_BAD_GATEWAY)
    return Response(draft)
```

- [ ] **Step 5: Add the route in `apps/ai/urls.py`**

```python
    path('resume-import/', views.resume_import, name='ai-resume-import'),
```

- [ ] **Step 6: Run the app suite, then the full suite**

```bash
uv run python manage.py test apps.ai
uv run python manage.py test
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/ai/serializers.py apps/ai/views.py apps/ai/urls.py apps/ai/tests.py
git commit -m "feat(ai): resume-import endpoint with seeker gate and layered throttles"
```

---

### Task 5: Validation gate + docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Validate the OpenAPI schema**

```bash
uv run python manage.py spectacular --validate
```

Expected: zero warnings. A warning naming `resume_import` means the Task 4 `@extend_schema` block is incomplete — fix there.

- [ ] **Step 2: Full suite one final time**

```bash
uv run python manage.py test
```

Expected: all PASS.

- [ ] **Step 3: Update `CLAUDE.md`**

Replace the existing AI routing bullet:

```markdown
- `/api/v1/ai/` — `job-post-assist/` (POST, company-only, returns a draft — creates nothing).
```

with:

```markdown
- `/api/v1/ai/` — `job-post-assist/` (POST, company-only) and `resume-import/` (POST, seeker-only, exactly one of `text`/PDF `file` ≤ 5 MB). Both return drafts — they create nothing.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document resume-import endpoint in CLAUDE.md"
```
