# AI Foundation + Job Post Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared AI foundation (`apps.ai`) and the first AI feature — a company-facing job post writing assistant at `POST /api/v1/ai/job-post-assist/` — per the approved spec `docs/superpowers/specs/2026-07-14-ai-agents-design.md` (Phases 0–1).

**Architecture:** A new leaf app `apps.ai` mounted at `/api/v1/ai/` holds all LLM concerns: a Gemini model factory, prompt templates, Pydantic output schemas, a service layer that views dispatch to, AI-specific throttles, and an `AIUsageLog` cost ledger. The writer feature makes one structured-output call to Gemini Flash and returns a draft the frontend feeds into the *existing* job-post + job-skills write paths — this endpoint creates nothing.

**Tech Stack:** Django 5.2 + DRF (existing), `langchain>=1.3,<2`, `langchain-google-genai>=4.2,<5`, `langgraph>=1.2,<2` (dependency added now per spec; first used in Phase 4), Google Gemini (`gemini-2.5-pro` / `gemini-2.5-flash` defaults, env-overridable).

## Global Constraints

- Python 3.13, deps managed by **uv** (`uv add`, `uv run`); PostgreSQL required.
- **All env access goes through `config.py`** — never `os.getenv()` elsewhere.
- UUID primary keys on every new model.
- Views are thin try/except dispatchers; **services own business logic**; domain exceptions map 1:1 to HTTP statuses.
- `grep -rn 'select_related\|prefetch_related' apps/*/views.py` must stay empty.
- Every endpoint authenticated via `CustomJWTAuthentication` (already the DRF default) — no anonymous AI calls.
- Overriding `throttle_classes` replaces defaults: AI views list **four** classes `[AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle]`.
- OpenAPI: function views carry `@extend_schema`; `uv run python manage.py spectacular --validate` must stay warning-free.
- Tests: offline only (no network); house style is one `tests.py` per app, `APITestCase`, `_auth` helper, `create_user(email=..., password=..., user_type=...)` (profiles auto-created by signal).
- Commits: conventional style (`feat(ai): ...`), **no Co-Authored-By footer**.
- Verified stack facts (July 2026): `with_structured_output(Schema, method="json_schema", include_raw=True)` returns `{"raw": AIMessage, "parsed": <Pydantic instance>, "parsing_error": ...}`; token usage lives at `AIMessage.usage_metadata["input_tokens"|"output_tokens"]`; stock LangChain fakes raise `NotImplementedError` on `with_structured_output`; `ChatGoogleGenerativeAI` accepts the key via `api_key=` kwarg.

## File Structure

| File | Responsibility |
|---|---|
| `config.py` (modify) | `GEMINI_API_KEY` (required), `AI_MODEL_PRO`, `AI_MODEL_FLASH` (defaults) |
| `.env.example` (modify) | Documented AI section |
| `jobApp/throttling.py` (create) | Shared `BurstRateThrottle` (promoted out of `apps/jobs/views.py`) |
| `apps/jobs/views.py` (modify) | Import `BurstRateThrottle` from shared module (drop local class) |
| `apps/ai/throttling.py` (create) | `AIRateThrottle` (scope `ai`) |
| `jobApp/settings/base.py` (modify) | `apps.ai` appended to `INSTALLED_APPS`; `ai`/`ai-chat` throttle rates |
| `jobApp/settings/test.py` (modify) | High-limit overrides for `ai`/`ai-chat` scopes |
| `jobApp/urls.py` (modify) | Mount `/api/v1/ai/` |
| `apps/ai/__init__.py`, `apps/ai/apps.py` (create) | App registration |
| `apps/ai/models.py` (create) | `AIUsageLog` |
| `apps/ai/exceptions.py` (create) | `AIProviderError`, `AIQuotaExceededError`, `AIResponseInvalidError` |
| `apps/ai/llm.py` (create) | `get_model("pro"\|"flash")` factory |
| `apps/ai/schemas.py` (create) | `JobPostDraft`, `SuggestedSkillDraft` Pydantic schemas |
| `apps/ai/prompts.py` (create) | Writer system prompt + prompt builder |
| `apps/ai/services.py` (create) | `generate_job_post_draft` + shared `_invoke_structured` |
| `apps/ai/serializers.py` (create) | `JobPostAssistRequestSerializer` |
| `apps/ai/permissions.py` (create) | `IsCompanyUser` |
| `apps/ai/views.py` (create) | `job_post_assist` function view |
| `apps/ai/urls.py` (create) | Router-less urlpatterns |
| `apps/ai/testing.py` (create) | `FakeStructuredChatModel` test fake (reused by later phases) |
| `apps/ai/tests.py` (create) | All Phase 0/1 tests |
| `apps/ai/management/commands/ai_smoke.py` (create) | Manual post-deploy smoke check |
| `CLAUDE.md` (modify) | Routing + app note |

Design note (small deviation from the spec, same guarantee): the LLM returns skill **names**, not UUIDs — models mangle UUIDs. The service maps names → `SkillSet` rows case-insensitively, drops anything unmatched, and emits `skill_set_id` from the DB. "Only real `SkillSet` IDs reach the client" is preserved.

---

### Task 1: Dependencies + config plumbing

**Files:**
- Modify: `pyproject.toml` (via `uv add`)
- Modify: `config.py`
- Modify: `.env.example`
- Modify: your local `.env` (placeholder key)

**Interfaces:**
- Produces: `config.GEMINI_API_KEY: str`, `config.AI_MODEL_PRO: str`, `config.AI_MODEL_FLASH: str` — imported by `apps/ai/llm.py` (Task 5).

- [ ] **Step 1: Add dependencies**

```bash
uv add "langchain>=1.3,<2" "langchain-google-genai>=4.2,<5" "langgraph>=1.2,<2"
```

Expected: resolves and writes to `pyproject.toml` + `uv.lock` without conflicts (verified compatible: langchain 1.3.13, langchain-google-genai 4.2.7, langgraph 1.2.9).

- [ ] **Step 2: Add the AI block to `config.py`**

Append after the `# --- Database ---` block:

```python
# --- AI (Google Gemini via LangChain) ------------------------------------------
# Required: the app must crash at import if the key is missing (same fail-fast
# contract as SECRET_KEY/DB_*). Any placeholder satisfies it for test runs —
# the offline test suite never sends it anywhere.
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]

# Model tiers are env-overridable so versions bump without a deploy.
# Flash default is gemini-2.5-flash (not 3.5-flash, which now prices above
# 2.5-pro input and would defeat the cheap-tier intent).
AI_MODEL_PRO: str = os.getenv("AI_MODEL_PRO", "gemini-2.5-pro")
AI_MODEL_FLASH: str = os.getenv("AI_MODEL_FLASH", "gemini-2.5-flash")
```

- [ ] **Step 3: Document in `.env.example`**

Append after the CORS block:

```
# AI (Google Gemini) — required; any non-empty placeholder works for tests
# (the offline suite never calls the network). Real key: https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key
# Optional model overrides (defaults: gemini-2.5-pro / gemini-2.5-flash)
# AI_MODEL_PRO=gemini-2.5-pro
# AI_MODEL_FLASH=gemini-2.5-flash
```

- [ ] **Step 4: Add a placeholder to your local `.env`** (required — config.py now crashes without it)

```bash
echo "GEMINI_API_KEY=test-not-a-real-key" >> .env
```

- [ ] **Step 5: Verify import + existing suite still green**

```bash
uv run python -c "import config; print(config.AI_MODEL_PRO, config.AI_MODEL_FLASH)"
uv run python manage.py test
```

Expected: prints `gemini-2.5-pro gemini-2.5-flash`; full suite passes.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock config.py .env.example
git commit -m "chore(deps): add langchain, langchain-google-genai, langgraph; AI config keys"
```

---

### Task 2: Promote `BurstRateThrottle` to a shared module

**Files:**
- Create: `jobApp/throttling.py`
- Modify: `apps/jobs/views.py:57-64` (delete local class, import instead)

**Interfaces:**
- Produces: `jobApp.throttling.BurstRateThrottle` (scope `burst`) — consumed by `apps/jobs/views.py` (unchanged behavior) and `apps/ai/views.py` (Task 8). The AI-specific throttle lives in `apps/ai/throttling.py` (created in Task 8, per the spec's app-structure table).

- [ ] **Step 1: Create `jobApp/throttling.py`**

```python
"""Shared throttle classes.

Subclassing UserRateThrottle means anonymous requests are not throttled by
these classes (get_cache_key returns None for anon) — anon traffic stays
bounded by the default AnonRateThrottle. Rates live in
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] keyed by `scope`.
"""
from rest_framework.throttling import UserRateThrottle


class BurstRateThrottle(UserRateThrottle):
    """Per-user burst ceiling for write-heavy endpoints."""
    scope = 'burst'
```

- [ ] **Step 2: Swap the import in `apps/jobs/views.py`**

Delete the local class (lines 57–64):

```python
class BurstRateThrottle(UserRateThrottle):
    """Per-user burst ceiling for write-heavy endpoints.

    Inherits UserRateThrottle so anonymous requests are not burst-throttled
    (get_cache_key returns None for anon). Anon traffic is bounded by the
    default AnonRateThrottle (100/day).
    """
    scope = 'burst'
```

and add to the imports at the top of the file:

```python
from jobApp.throttling import BurstRateThrottle
```

(`views.BurstRateThrottle` stays importable, so `BurstThrottleAttachmentTests` keeps passing unmodified.)

- [ ] **Step 3: Run the jobs suite to prove no regression**

```bash
uv run python manage.py test apps.jobs
```

Expected: PASS, including `BurstThrottleAttachmentTests`.

- [ ] **Step 4: Commit**

```bash
git add jobApp/throttling.py apps/jobs/views.py
git commit -m "refactor(throttling): promote BurstRateThrottle to shared jobApp module"
```

---

### Task 3: `apps.ai` skeleton, settings registration, URL mount

**Files:**
- Create: `apps/ai/__init__.py`, `apps/ai/apps.py`, `apps/ai/urls.py`
- Modify: `jobApp/settings/base.py:44-48` (INSTALLED_APPS) and `:69-76` (throttle rates)
- Modify: `jobApp/settings/test.py:30-38`
- Modify: `jobApp/urls.py:29-40`

**Interfaces:**
- Produces: the `apps.ai` Django app (label `ai`), mounted at `/api/v1/ai/`; throttle rates `ai: 30/min`, `ai-chat: 10/min`.

- [ ] **Step 1: Create the app files**

`apps/ai/__init__.py`: empty file.

`apps/ai/apps.py`:

```python
from django.apps import AppConfig


class AiConfig(AppConfig):
    name = 'apps.ai'
```

`apps/ai/urls.py`:

```python
urlpatterns = []
```

- [ ] **Step 2: Register in `jobApp/settings/base.py`**

Append to `INSTALLED_APPS` (after `'apps.companies',` — do **not** reorder existing entries):

```python
    'apps.ai',
```

Extend `DEFAULT_THROTTLE_RATES` (after `'token_refresh': '20/min',`):

```python
        'ai': '30/min',
        'ai-chat': '10/min',
```

- [ ] **Step 3: High-limit overrides in `jobApp/settings/test.py`**

Extend the override dict (after `'burst': '100000/day',`):

```python
        'ai': '100000/day',
        'ai-chat': '100000/day',
```

- [ ] **Step 4: Mount in `jobApp/urls.py`**

After the companies include:

```python
    path('api/v1/ai/', include('apps.ai.urls')),
```

- [ ] **Step 5: Verify**

```bash
uv run python manage.py check
uv run python manage.py test
```

Expected: `System check identified no issues`; full suite passes.

- [ ] **Step 6: Commit**

```bash
git add apps/ai jobApp/settings/base.py jobApp/settings/test.py jobApp/urls.py
git commit -m "feat(ai): register apps.ai skeleton, throttle scopes, /api/v1/ai/ mount"
```

---

### Task 4: `AIUsageLog` model

**Files:**
- Create: `apps/ai/models.py`, `apps/ai/tests.py`
- Create (generated): `apps/ai/migrations/0001_initial.py`

**Interfaces:**
- Produces: `AIUsageLog` with `AIUsageLog.Feature` choices (`JOB_POST_WRITER`, `RESUME_IMPORT`, `SCREENING`, `CHAT`) — written by `services.generate_job_post_draft` (Task 7).

- [ ] **Step 1: Write the failing test — create `apps/ai/tests.py`**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run python manage.py test apps.ai
```

Expected: FAIL/ERROR — `cannot import name 'AIUsageLog'`.

- [ ] **Step 3: Create `apps/ai/models.py`**

```python
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AIUsageLog(models.Model):
    """One row per LLM call (chat, later, writes one row per turn).

    The project's Gemini bill, queryable per feature and per user.
    """

    class Feature(models.TextChoices):
        JOB_POST_WRITER = 'job_post_writer', 'Job post writer'
        RESUME_IMPORT = 'resume_import', 'Resume import'
        SCREENING = 'screening', 'Screening'
        CHAT = 'chat', 'Chat'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feature = models.CharField(max_length=32, choices=Feature.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='ai_usage_logs',
    )
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.feature} {self.model} in={self.input_tokens} out={self.output_tokens}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['feature', '-created_at'], name='aiusage_feature_created_idx'),
        ]
```

- [ ] **Step 4: Generate + apply the migration, run tests**

```bash
uv run python manage.py makemigrations ai
uv run python manage.py migrate
uv run python manage.py test apps.ai
```

Expected: `0001_initial.py` created; both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai/models.py apps/ai/migrations apps/ai/tests.py
git commit -m "feat(ai): AIUsageLog cost ledger with feature choices"
```

---

### Task 5: Domain exceptions + model factory

**Files:**
- Create: `apps/ai/exceptions.py`, `apps/ai/llm.py`
- Modify: `apps/ai/tests.py` (append)

**Interfaces:**
- Produces: `AIProviderError`, `AIQuotaExceededError`, `AIResponseInvalidError` (consumed by services Task 7 and views Task 8); `get_model(tier: str) -> ChatGoogleGenerativeAI` (`tier` ∈ `"pro"|"flash"`, else `ValueError`).

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

```python
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
```

(also add `from django.test import TestCase` if the import list needs it — it's already imported in Task 4.)

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.ModelFactoryTests
```

Expected: ERROR — `No module named 'apps.ai.llm'`.

- [ ] **Step 3: Create `apps/ai/exceptions.py`**

```python
"""Domain exceptions for AI features. Views map these 1:1 to HTTP statuses."""


class AIProviderError(Exception):
    """Gemini unreachable / provider 5xx after one retry → HTTP 502."""


class AIQuotaExceededError(Exception):
    """Provider-side quota exhausted (distinct from local throttle) → HTTP 429."""


class AIResponseInvalidError(Exception):
    """Model output failed schema validation after one retry → HTTP 502."""
```

- [ ] **Step 4: Create `apps/ai/llm.py`**

```python
"""Gemini model factory. The only place LangChain chat models are constructed."""
from langchain_google_genai import ChatGoogleGenerativeAI

from config import AI_MODEL_FLASH, AI_MODEL_PRO, GEMINI_API_KEY

_MODEL_IDS = {'pro': AI_MODEL_PRO, 'flash': AI_MODEL_FLASH}


def get_model(tier: str) -> ChatGoogleGenerativeAI:
    """Return a configured chat model for the given tier ('pro' | 'flash').

    max_retries=0 because the service layer owns the single-retry policy —
    stacking SDK retries on top would multiply latency and cost.
    """
    try:
        model_id = _MODEL_IDS[tier]
    except KeyError:
        raise ValueError(f"Unknown model tier: {tier!r} (expected 'pro' or 'flash')")
    return ChatGoogleGenerativeAI(
        model=model_id,
        api_key=GEMINI_API_KEY,
        timeout=30,
        max_retries=0,
    )
```

Note: `timeout`/`max_retries` are long-standing `ChatGoogleGenerativeAI` fields. The `ModelFactoryTests` instantiate the class, so if 4.2.x renamed either kwarg the test errors immediately — drop the offending kwarg and note it in the commit if so.

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run python manage.py test apps.ai
```

Expected: PASS (constructor performs no network I/O).

- [ ] **Step 6: Commit**

```bash
git add apps/ai/exceptions.py apps/ai/llm.py apps/ai/tests.py
git commit -m "feat(ai): domain exceptions and Gemini model factory"
```

---

### Task 6: Output schemas + prompts

**Files:**
- Create: `apps/ai/schemas.py`, `apps/ai/prompts.py`
- Modify: `apps/ai/tests.py` (append)

**Interfaces:**
- Produces: `JobPostDraft(job_title, job_description, suggested_skills: list[SuggestedSkillDraft])`; `SuggestedSkillDraft(skill_name, skill_level, is_required)` with `skill_level ∈ Beginner|Intermediate|Advanced|Expert`; `build_job_post_writer_prompt(*, notes, company_name, business_stream, job_type_name, location_hint, skill_names) -> list[tuple[str, str]]`.

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.SchemaTests apps.ai.tests.PromptTests
```

Expected: ERROR — missing modules.

- [ ] **Step 3: Create `apps/ai/schemas.py`**

```python
"""Pydantic schemas bound to Gemini structured output.

Services bind these via with_structured_output(Schema, method="json_schema")
— Gemini's native responseSchema (the 4.x default; pinned explicitly).
The LLM returns skill *names*, never UUIDs — the service maps names to real
SkillSet rows and drops inventions.
"""
from typing import Literal

from pydantic import BaseModel, Field

SkillLevel = Literal['Beginner', 'Intermediate', 'Advanced', 'Expert']


class SuggestedSkillDraft(BaseModel):
    skill_name: str = Field(description="A skill name chosen from the provided taxonomy list.")
    skill_level: SkillLevel = Field(description="Required proficiency for this job.")
    is_required: bool = Field(description="True if must-have, False if nice-to-have.")


class JobPostDraft(BaseModel):
    job_title: str = Field(description="Concise job title, max ~120 characters.")
    job_description: str = Field(
        description="Full description including responsibilities and requirements prose.")
    suggested_skills: list[SuggestedSkillDraft] = Field(
        description="3-8 skills strictly from the provided taxonomy list.")
```

- [ ] **Step 4: Create `apps/ai/prompts.py`**

```python
"""Prompt templates for AI features — every prompt lives here."""

JOB_POST_WRITER_SYSTEM = (
    "You are a hiring copywriter for a job board. Given a company's rough notes, "
    "write a polished, honest job post draft. Fold any requirements into the "
    "job_description as a clearly formatted section — do not invent perks, salary "
    "figures, or qualifications the notes don't support. Suggest 3-8 relevant "
    "skills, choosing skill_name values ONLY from the provided taxonomy list, "
    "verbatim. If the taxonomy has no relevant skill, suggest fewer skills rather "
    "than inventing names."
)


def build_job_post_writer_prompt(
    *,
    notes: str,
    company_name: str,
    business_stream: str,
    job_type_name: str,
    location_hint: str,
    skill_names: list[str],
) -> list[tuple[str, str]]:
    """Return (role, content) message tuples for model.invoke()."""
    context_lines = [
        f"Company: {company_name} (industry: {business_stream})",
    ]
    if job_type_name:
        context_lines.append(f"Job type: {job_type_name}")
    if location_hint:
        context_lines.append(f"Location: {location_hint}")
    human = (
        "\n".join(context_lines)
        + "\n\nSkill taxonomy (choose skill_name values only from this list):\n"
        + ", ".join(skill_names)
        + "\n\nCompany's rough notes:\n"
        + notes
    )
    return [("system", JOB_POST_WRITER_SYSTEM), ("human", human)]
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run python manage.py test apps.ai
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ai/schemas.py apps/ai/prompts.py apps/ai/tests.py
git commit -m "feat(ai): job post draft schema and writer prompt"
```

---

### Task 7: Test fake + `generate_job_post_draft` service

**Files:**
- Create: `apps/ai/testing.py`, `apps/ai/services.py`
- Modify: `apps/ai/tests.py` (append)

**Interfaces:**
- Consumes: `get_model` (Task 5), `JobPostDraft` (Task 6), `AIUsageLog` (Task 4), exceptions (Task 5).
- Produces: `generate_job_post_draft(user, *, notes, job_type=None, location_hint='', model=None) -> dict` returning `{'job_title': str, 'job_description': str, 'suggested_skills': [{'skill_set_id': str, 'skill_name': str, 'skill_level': str, 'is_required': bool}]}`; raises `AIQuotaExceededError | AIProviderError | AIResponseInvalidError`. Also `FakeStructuredChatModel` (reused by later phases) and the internal `_invoke_structured(model, schema, prompt) -> (parsed, usage_dict)` helper reused by Phases 2–3.

- [ ] **Step 1: Create `apps/ai/testing.py`** (the fake first — tests need it)

```python
"""Test doubles for AI services.

Stock LangChain fakes raise NotImplementedError on with_structured_output
(BaseChatModel.bind_tools guard), so this project ships its own. Lives
outside tests.py so later phases (resume import, screening) reuse it.
Never imported by production code.
"""
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


class FakeStructuredChatModel(GenericFakeChatModel):
    """Returns canned parsed output; mirrors include_raw=True shape.

    parsed_outputs is consumed one per call — supply several to script
    retry behaviour. An entry that is an Exception is raised instead
    (simulates provider errors); an entry of None simulates a parse failure.
    """
    parsed_outputs: list[Any] = []
    usage: dict = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    model: str = "fake-model"

    def __init__(self, parsed_outputs=None, **kwargs):
        kwargs.setdefault("messages", iter([]))
        super().__init__(parsed_outputs=list(parsed_outputs or []), **kwargs)

    def with_structured_output(self, schema, method="json_schema", *,
                               include_raw=False, **kwargs):
        def _call(_input):
            item = self.parsed_outputs.pop(0)
            if isinstance(item, Exception):
                raise item
            raw = AIMessage(content="", usage_metadata=dict(self.usage))
            if include_raw:
                error = None if item is not None else ValueError("parse failed")
                return {"raw": raw, "parsed": item, "parsing_error": error}
            return item
        return RunnableLambda(_call)
```

- [ ] **Step 2: Write the failing tests — append to `apps/ai/tests.py`**

```python
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
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.GenerateJobPostDraftTests
```

Expected: ERROR — `No module named 'apps.ai.services'`.

- [ ] **Step 4: Create `apps/ai/services.py`**

```python
"""Service layer for AI features. Views translate domain exceptions to HTTP."""
import logging
import time

from apps.seekers.models import SkillSet

from .exceptions import AIProviderError, AIQuotaExceededError, AIResponseInvalidError
from .llm import get_model
from .models import AIUsageLog
from .prompts import build_job_post_writer_prompt
from .schemas import JobPostDraft

logger = logging.getLogger('apps.ai')


def _classify_provider_error(exc):
    """Quota signals → AIQuotaExceededError; everything else → AIProviderError."""
    code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    text = str(exc)
    if code == 429 or 'RESOURCE_EXHAUSTED' in text or 'quota' in text.lower():
        return AIQuotaExceededError(text)
    return AIProviderError(text)


def _invoke_structured(model, schema, prompt):
    """One structured-output call with exactly one retry.

    Retries transient provider errors and parse failures; quota errors
    raise immediately (retrying spends more quota for nothing).
    Returns (parsed instance, usage_metadata dict).
    """
    structured = model.with_structured_output(
        schema, method='json_schema', include_raw=True)
    last_error = None
    for attempt in range(2):
        try:
            result = structured.invoke(prompt)
        except Exception as exc:
            last_error = _classify_provider_error(exc)
            logger.warning('ai provider error attempt=%s cls=%s', attempt,
                           type(exc).__name__)
            if isinstance(last_error, AIQuotaExceededError):
                raise last_error
            continue
        if result.get('parsed') is None:
            last_error = AIResponseInvalidError(str(result.get('parsing_error')))
            logger.warning('ai parse failure attempt=%s', attempt)
            continue
        usage = getattr(result.get('raw'), 'usage_metadata', None) or {}
        return result['parsed'], usage
    raise last_error


def generate_job_post_draft(user, *, notes, job_type=None, location_hint='',
                            model=None):
    """Draft a job post from rough notes. Creates nothing but the usage log.

    Returns {'job_title', 'job_description', 'suggested_skills': [
        {'skill_set_id', 'skill_name', 'skill_level', 'is_required'}]}
    with skills mapped to real SkillSet rows; inventions dropped.
    """
    model = model or get_model('flash')
    company = user.company_profile
    skills = list(SkillSet.objects.order_by('skill_name'))
    prompt = build_job_post_writer_prompt(
        notes=notes,
        company_name=company.company_name,
        business_stream=company.business_stream.business_stream_name,
        job_type_name=job_type.job_type_name if job_type else '',
        location_hint=location_hint,
        skill_names=[s.skill_name for s in skills],
    )

    started = time.monotonic()
    draft, usage = _invoke_structured(model, JobPostDraft, prompt)
    latency_ms = int((time.monotonic() - started) * 1000)

    by_name = {s.skill_name.lower(): s for s in skills}
    suggested = []
    for item in draft.suggested_skills:
        skill = by_name.get(item.skill_name.strip().lower())
        if skill is None:
            continue  # invented by the model
        suggested.append({
            'skill_set_id': str(skill.id),
            'skill_name': skill.skill_name,
            'skill_level': item.skill_level,
            'is_required': item.is_required,
        })

    AIUsageLog.objects.create(
        feature=AIUsageLog.Feature.JOB_POST_WRITER,
        user=user,
        model=str(getattr(model, 'model', '')),
        input_tokens=usage.get('input_tokens', 0),
        output_tokens=usage.get('output_tokens', 0),
        latency_ms=latency_ms,
    )
    return {
        'job_title': draft.job_title,
        'job_description': draft.job_description,
        'suggested_skills': suggested,
    }
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run python manage.py test apps.ai
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ai/testing.py apps/ai/services.py apps/ai/tests.py
git commit -m "feat(ai): job post draft service with retry policy and usage logging"
```

---

### Task 8: Permission, serializer, view, URL

**Files:**
- Create: `apps/ai/throttling.py`, `apps/ai/permissions.py`, `apps/ai/serializers.py`, `apps/ai/views.py`
- Modify: `apps/ai/urls.py`, `apps/ai/tests.py` (append)

**Interfaces:**
- Consumes: `generate_job_post_draft` (Task 7), exceptions (Task 5), `BurstRateThrottle` (Task 2).
- Produces (besides the endpoint): `apps.ai.throttling.AIRateThrottle` (scope `ai`) — reused by every later AI endpoint.
- Produces: `POST /api/v1/ai/job-post-assist/` — request `{notes, job_type_id?, location_hint?}` → 200 draft payload; 401 anon; 403 seeker; 429 quota; 502 provider/invalid.

- [ ] **Step 1: Write the failing tests — append to `apps/ai/tests.py`**

At top of file, extend imports:

```python
from unittest.mock import patch

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


def _auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
```

Then append:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run python manage.py test apps.ai.tests.JobPostAssistEndpointTests
```

Expected: 404s / import errors — view doesn't exist yet.

- [ ] **Step 3: Create `apps/ai/throttling.py`**

```python
"""AI-specific throttle classes (rates in DEFAULT_THROTTLE_RATES)."""
from rest_framework.throttling import UserRateThrottle


class AIRateThrottle(UserRateThrottle):
    """Per-user ceiling for LLM-backed endpoints — protects the Gemini bill."""
    scope = 'ai'
```

- [ ] **Step 3b: Create `apps/ai/permissions.py`**

```python
"""Permission classes for AI endpoints."""
from rest_framework.permissions import BasePermission


class IsCompanyUser(BasePermission):
    """Company-type users only. Unauthenticated → 401 via DRF."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'company'
        )
```

- [ ] **Step 4: Create `apps/ai/serializers.py`**

```python
from rest_framework import serializers

from apps.jobs.models import JobType


class JobPostAssistRequestSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=4000)
    job_type_id = serializers.PrimaryKeyRelatedField(
        queryset=JobType.objects.all(), required=False, allow_null=True)
    location_hint = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='')
```

- [ ] **Step 5: Create `apps/ai/views.py`**

```python
"""Thin dispatchers: validate input, call the service, translate exceptions."""
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from jobApp.throttling import BurstRateThrottle

from . import services
from .throttling import AIRateThrottle
from .exceptions import AIProviderError, AIQuotaExceededError, AIResponseInvalidError
from .permissions import IsCompanyUser
from .serializers import JobPostAssistRequestSerializer

_AIErrorSerializer = inline_serializer(
    name='AIError', fields={'error': drf_serializers.CharField()},
)

_SuggestedSkillSerializer = inline_serializer(
    name='SuggestedSkill',
    fields={
        'skill_set_id': drf_serializers.UUIDField(),
        'skill_name': drf_serializers.CharField(),
        'skill_level': drf_serializers.CharField(),
        'is_required': drf_serializers.BooleanField(),
    },
)

_JobPostDraftSerializer = inline_serializer(
    name='JobPostDraftResponse',
    fields={
        'job_title': drf_serializers.CharField(),
        'job_description': drf_serializers.CharField(),
        'suggested_skills': _SuggestedSkillSerializer(many=True),
    },
)


@extend_schema(
    request=JobPostAssistRequestSerializer,
    responses={
        200: _JobPostDraftSerializer,
        429: _AIErrorSerializer,
        502: _AIErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['POST'])
@permission_classes([IsCompanyUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])
def job_post_assist(request):
    """Draft a job post from rough notes. Returns a draft — creates nothing."""
    serializer = JobPostAssistRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        draft = services.generate_job_post_draft(
            request.user,
            notes=serializer.validated_data['notes'],
            job_type=serializer.validated_data.get('job_type_id'),
            location_hint=serializer.validated_data.get('location_hint', ''),
        )
    except AIQuotaExceededError:
        return Response({'error': 'AI provider quota exceeded — try again later'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'},
                        status=status.HTTP_502_BAD_GATEWAY)
    return Response(draft)
```

- [ ] **Step 6: Wire `apps/ai/urls.py`**

```python
from django.urls import path

from . import views

urlpatterns = [
    path('job-post-assist/', views.job_post_assist, name='ai-job-post-assist'),
]
```

- [ ] **Step 7: Run the app suite, then the full suite**

```bash
uv run python manage.py test apps.ai
uv run python manage.py test
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/ai/throttling.py apps/ai/permissions.py apps/ai/serializers.py apps/ai/views.py apps/ai/urls.py apps/ai/tests.py
git commit -m "feat(ai): job-post-assist endpoint with company gate and layered throttles"
```

---

### Task 9: `ai_smoke` management command

**Files:**
- Create: `apps/ai/management/__init__.py`, `apps/ai/management/commands/__init__.py`, `apps/ai/management/commands/ai_smoke.py`

**Interfaces:**
- Consumes: `get_model` (Task 5).
- Produces: `uv run python manage.py ai_smoke` — one cheap Flash call, manual post-deploy verification only. Never runs in the test suite.

- [ ] **Step 1: Create the command**

`apps/ai/management/__init__.py` and `apps/ai/management/commands/__init__.py`: empty files.

`apps/ai/management/commands/ai_smoke.py`:

```python
"""Manual smoke check: one cheap Flash call. Requires a real GEMINI_API_KEY.

Run after deploys: uv run python manage.py ai_smoke
Deliberately NOT exercised by the test suite (network + billable).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.ai.llm import get_model


class Command(BaseCommand):
    help = "Make one cheap Gemini Flash call to verify AI connectivity."

    def handle(self, *args, **options):
        model = get_model('flash')
        try:
            reply = model.invoke("Reply with exactly: OK")
        except Exception as exc:
            raise CommandError(f"Gemini call failed: {type(exc).__name__}: {exc}")
        usage = reply.usage_metadata or {}
        self.stdout.write(self.style.SUCCESS(
            f"model={model.model} reply={reply.content!r} "
            f"in={usage.get('input_tokens')} out={usage.get('output_tokens')}"
        ))
```

- [ ] **Step 2: Verify registration (no network)**

```bash
uv run python manage.py ai_smoke --help
```

Expected: prints the command help.

- [ ] **Step 3: Commit**

```bash
git add apps/ai/management
git commit -m "feat(ai): ai_smoke management command for manual connectivity checks"
```

---

### Task 10: OpenAPI validation, full suite, docs

**Files:**
- Modify: `CLAUDE.md` (routing section + AI note)

**Interfaces:** none — final verification gate.

- [ ] **Step 1: Validate the OpenAPI schema**

```bash
uv run python manage.py spectacular --validate
```

Expected: schema output, **zero warnings**. If a warning names `job_post_assist`, the `@extend_schema` block in Task 8 is incomplete — fix there.

- [ ] **Step 2: Run the complete suite one final time**

```bash
uv run python manage.py test
```

Expected: all apps PASS.

- [ ] **Step 3: Document in `CLAUDE.md`**

In the **Routing** section, add:

```markdown
- `/api/v1/ai/` — `job-post-assist/` (POST, company-only, returns a draft — creates nothing).
```

After the Routing section, add:

```markdown
### AI features (`apps.ai`)

Leaf app for LLM features (Google Gemini via LangChain). All env access via
`config.py` (`GEMINI_API_KEY` required; `AI_MODEL_PRO`/`AI_MODEL_FLASH`
overridable). Services own the LangChain calls and accept the model as an
injectable — tests use `apps.ai.testing.FakeStructuredChatModel`, never the
network. AI views list **four** throttle classes
`[AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle]`
(overriding replaces defaults; `BurstRateThrottle` is shared in
`jobApp/throttling.py`, `AIRateThrottle` lives in `apps/ai/throttling.py`).
Every LLM call writes an `AIUsageLog` row. Manual connectivity check:
`uv run python manage.py ai_smoke` (billable — not in the test suite).
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document apps.ai routing and conventions in CLAUDE.md"
```
