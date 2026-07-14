# AI Agent Suite — Design

**Date:** 2026-07-14
**Status:** Approved by user (brainstorming session)

## Summary

Add four AI-powered features to the Job Board API, built as a single new Django app (`apps.ai`) mounted at `/api/v1/ai/`. All features are consumed by the existing frontend as ordinary authenticated DRF endpoints.

## Decisions (user-confirmed)

| Decision | Choice |
|---|---|
| Features | All four: job post writer, resume import, applicant screening, job-search chat assistant |
| Provider | Google Gemini |
| Framework | LangChain + LangGraph |
| Model strategy | Mixed tiers: Pro-class for chat + screening, Flash-class for writer + resume extraction |
| Architecture | Dedicated `apps.ai` app (Approach A) |
| Build order | Foundation → job post writer → resume import → applicant screening → chat assistant |

Exact Gemini model IDs, current pricing, and library versions are verified against live docs at implementation-plan time; the design pins them via env config, not code.

## Build phases

Each phase is independently shippable and reuses everything before it.

- **Phase 0 — Foundation:** `apps.ai` skeleton, dependencies, config, throttles, `AIUsageLog`, testing seam.
- **Phase 1 — Job post writer** (Flash, company-only).
- **Phase 2 — Resume import** (Flash, seeker-only).
- **Phase 3 — Applicant screening** (Pro, company-only) — introduces `ScreeningReport`.
- **Phase 4 — Chat assistant** (Pro, seeker-only) — introduces `Conversation` + LangGraph Postgres checkpointer.

## Phase 0 — Shared foundation

### Placement and dependencies

- `apps.ai` is appended at the end of `INSTALLED_APPS` as a convention signalling a leaf app — it imports from `apps.companies`, `apps.seekers`, and `apps.jobs`; nothing imports from it. Removing the AI layer later means removing one app. Django does not require dependency ordering in `INSTALLED_APPS` (the existing list is `accounts, jobs, seekers, companies`) — do **not** reorder the existing entries.
- `jobApp/urls.py` mounts it at `/api/v1/ai/`.
- Dependencies via `uv add`: `langchain`, `langchain-google-genai`, `langgraph`; `langgraph-checkpoint-postgres` is added in Phase 4 only.

### Configuration (all via `config.py`, per house rule)

| Key | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes — `os.environ[...]`, crash at import if missing | Provider auth |
| `AI_MODEL_PRO` | No — defaults to current Gemini Pro-class ID | Chat + screening model |
| `AI_MODEL_FLASH` | No — defaults to current Gemini Flash-class ID | Writer + extraction model |

`.env.example` gains a documented AI section.

### App structure

| File | Responsibility |
|---|---|
| `llm.py` | Model factory: `get_model("pro" \| "flash")` → configured `ChatGoogleGenerativeAI` |
| `prompts.py` | All prompt templates |
| `schemas.py` | Pydantic output schemas; services bind them via `with_structured_output(Schema, method="json_schema")` — Gemini's native responseSchema, more reliable than the default function-calling method on nested schemas |
| `services.py` | One service per agent; owns all LangChain/LangGraph logic |
| `views.py` | Thin try/except dispatchers, `@extend_schema` on every endpoint |
| `permissions.py` | `IsCompanyUser` (writer), `IsCompanyUserOrAdmin` (screening — folds the `is_staff`/`is_superuser` bypass into the class, per the `IsJobPosterOrAdmin` house pattern), `IsSeekerUser` (resume import, chat) |
| `exceptions.py` | Domain exceptions mapping 1:1 to HTTP statuses |
| `throttling.py` | AI-specific scoped throttle classes |
| `models.py` | `AIUsageLog` (Phase 0), `ScreeningReport` (Phase 3), `Conversation` (Phase 4) |

### Auth and throttling

- Every endpoint uses `CustomJWTAuthentication`; no anonymous access (each call costs money).
- Layered throttling preserved — with one deliberate deviation from the three-class house rule: AI views set `throttle_classes = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIScopedRateThrottle]` (**four** classes). Overriding `throttle_classes` replaces the defaults entirely, and the house-rule trio does not include `ScopedRateThrottle`, so the AI scoped throttle must be listed explicitly or the new rates silently never fire. Scoped rates, tunable in settings: `ai` ≈ 30/min for single-call features, `ai-chat` ≈ 10/min for the agent loop. `BurstRateThrottle` currently lives inside `apps/jobs/views.py`; Phase 0 promotes it to a shared module and updates the existing imports.
- Test settings add the new scopes to the existing high-limit overrides so the suite doesn't 429 itself.

### Usage tracking

`AIUsageLog(feature, user FK, model, input_tokens, output_tokens, latency_ms, created_at)` — UUID PK like every other model. `feature` uses model choices: `job_post_writer | resume_import | screening | chat`. Phases 1–3 write one row per LLM call; chat writes **one row per turn** with token counts summed across every LLM call in the agent loop. Populated from LangChain's response usage metadata; provides per-feature/per-user cost visibility from day one.

### Testing seam

Services accept the chat model as an injectable parameter defaulting to the `llm.py` factory. Tests inject fakes; the suite never performs network I/O. Caveat: LangChain's stock fakes (`GenericFakeChatModel`) do not implement `bind_tools`/`with_structured_output`, so `apps.ai` ships a small test-only fake subclass implementing them (or the seam injects the structured-output runnable rather than the raw model) for the Phase 1–3 structured-output services.

## Phase 1 — Job post writer

- **Endpoint:** `POST /api/v1/ai/job-post-assist/` — company-only — **Flash**.
- **Input:** `{notes: string (required), job_type_id?: UUID of an existing JobType, location_hint?: string}` — the service resolves `job_type_id` to its name for the prompt; `location_hint` is free text.
- **Flow:** service loads the requesting company's context (name, business stream) and the `SkillSet` taxonomy → one structured-output call → draft `{job_title, job_description, suggested_skills: [{skill_set_id, skill_level, is_required}]}`. Keys mirror the real write paths: `job_title`/`job_description` match `JobPost` fields (requirements prose is folded into `job_description` — `JobPost` has no requirements field), and each suggested skill carries the values the `JobPostSkillSet` write path needs.
- **Skill grounding:** the prompt carries the taxonomy (id + name); returned skills are validated against the DB server-side and invented ones are dropped. Only real `SkillSet` IDs reach the client.
- **Draft-only:** the endpoint never creates a `JobPost`. The frontend submits the confirmed draft through the existing job-post create endpoint, then the suggested skills through the existing `job-skills` endpoint — both write paths and their permissions unchanged.

## Phase 2 — Resume import

- **Endpoint:** `POST /api/v1/ai/resume-import/` — seeker-only — **Flash**.
- **Input:** `multipart/form-data` with **exactly one** of `text` (string) or `file` (PDF); both or neither → 400 `InvalidResumeFileError`. Gemini reads PDFs natively — no parsing library. Cap: ~5 MB.
- **Output schema mirrors the models:** education entries shaped like `EducationData`, experience like `ExperienceData`, skills matched to the `SkillSet` taxonomy; unmatched skills returned separately as "new skill suggestions".
- **Draft-only:** the seeker reviews and confirms in the UI; confirmed rows are persisted through the existing seekers CRUD endpoints. No auto-committed AI output, no new write paths.

## Phase 3 — Applicant screening

- **Endpoint:** `POST /api/v1/ai/job-posts/{job_post_id}/screen/` — company-only with object-level ownership check (`job_post.company.user_account == request.user`; admins allowed) — **Pro**.
- **Flow:** gather applicants via `JobPostActivity.objects.with_related()` **plus explicit** `prefetch_related('user_account__seeker_profile', 'user_account__education', 'user_account__experiences', 'user_account__skills__skill_set')` — `with_related()` alone only covers `user_account`/`job_post`/company and would blow the ≤10-query budget → send compact dossiers + the post's description and required skills → structured output: per-candidate `{applicant_id, score, strengths, gaps, summary}` plus an overall ranking (deterministic sort of per-candidate scores — no second LLM call).
- **Cost guards:**
  - Hard cap: only the 50 most recent applicants are screened. When applicants are excluded, the response carries `truncated: true` plus the excluded count — no silent exclusion, no unbounded cost. `applicant_count` records the number actually screened.
  - Results persisted in `ScreeningReport(job_post FK, report JSONField, applicant_count, created_at)`. Repeat requests return the stored report without an LLM call; a fresh run occurs only on `?refresh=true` or when the report is stale. Staleness rule: any `JobPostActivity` for the post with `application_date` later than `report.created_at` — explicitly **not** a count comparison, which withdraw-plus-reapply would fool.
- **Empty pool:** `NoApplicantsError` → 409.

## Phase 4 — Chat assistant

- **Endpoints:** `POST /api/v1/ai/chat/` (`{conversation_id?, message}` → `{conversation_id, reply}` — the id is always returned, whether the conversation is new or existing), `GET /api/v1/ai/chat/conversations/` (own conversations, `[{id, title, created_at}]` newest-first), `DELETE /api/v1/ai/chat/conversations/{id}/` — seeker-only — **Pro**. `Conversation.title` is the first user message truncated to 60 chars, set once at creation (no LLM call).
- **Agent:** ReAct-style agent built with `langchain.agents.create_agent` (LangChain v1's supported agent factory, running on LangGraph — `langgraph.prebuilt.create_react_agent` is deprecated) with **read-only** tools wrapping the existing service/queryset layer:
  - `search_jobs(filters)` — published + active jobs via existing managers
  - `get_job_details(job_post_id)`
  - `get_my_profile()` — requesting seeker's profile, education, experience, skills
  - `compare_fit(job_post_id)` — skill overlap computed deterministically in Python; the agent narrates the result
- **No `apply_to_job` tool in v1 (deliberate).** Job descriptions are company-authored text injected into the agent's context — a prompt-injection vector. The agent returns job references; the frontend renders its normal Apply button. A confirmed-apply tool may be revisited later with explicit safeguards.
- **State:** LangGraph Postgres checkpointer keyed by conversation UUID, plus a light `Conversation(id, user FK, title, created_at)` model for listing and ownership enforcement. Checkpointer wiring:
  - Connects with the same DB credentials already exposed by `config.py` — no new env keys. `langgraph-checkpoint-postgres` requires psycopg v3, which coexists with the project's psycopg2 driver; the checkpointer manages its own connection pool (`autocommit=True`, `dict_row`) separate from Django's connections.
  - Its tables are created by `checkpointer.setup()`, exposed as a `manage.py ai_checkpointer_setup` command run once at deploy — not via Django migrations.
  - Deserialization hardening: `LANGGRAPH_STRICT_MSGPACK=true`.
  - Deleting a `Conversation` also deletes its checkpointer thread rows in the same transaction — no orphaned chat history (see Logging and privacy).
- **Bounds:** max ~8 tool iterations per turn, ~90s request timeout, output token cap, trimmed history window. Hitting the iteration or timeout bound without a final reply raises `AgentLimitExceededError` → 504 (see error table).
- **Delivery:** v1 is synchronous JSON. SSE streaming is a flagged future enhancement, not in scope.

## Error handling

Domain exceptions map 1:1 to HTTP statuses; views stay thin dispatchers:

| Exception | HTTP | Meaning |
|---|---|---|
| `AIProviderError` | 502 | Gemini unreachable / provider 5xx after one retry |
| `AIQuotaExceededError` | 429 | Provider-side quota exhausted (distinct from local throttle 429) |
| `AIResponseInvalidError` | 502 | Output failed schema validation after one retry |
| `InvalidResumeFileError` | 400 | Wrong type / over cap / unreadable |
| `NoApplicantsError` | 409 | Screening on a post with zero applicants |
| `ConversationNotFoundError` | 404 | Chat thread missing or not owned by requester |
| `AgentLimitExceededError` | 504 | Chat agent hit its iteration/timeout bound without producing a final reply |

Transient provider failures retry exactly once. All calls carry timeouts (~30s single-call, ~90s agent loop).

## Logging and privacy

Usage metrics, latency, and error classes log to the `apps` logger. Resume content, chat messages, and full prompt bodies are never logged — consistent with the project's hashed-email/GDPR-friendly logging posture.

## Testing strategy

- **Offline suite:** services receive fake LangChain chat models via the injectable seam; no test performs network I/O.
- **Per-feature assertions:** invented skills dropped (Phase 1); size caps and exactly-one-of `text`/`file` enforced (Phase 2); cached `ScreeningReport` returned without an LLM call, staleness/refresh semantics, 50-applicant cap with `truncated` flag (Phase 3); conversation ownership enforced, iteration bound surfaces `AgentLimitExceededError` → 504 (Phase 4).
- **Permissions:** each endpoint tested for both `user_type`s plus anonymous, matching existing conventions; screening additionally tests the admin (`is_staff`/`is_superuser`) bypass promised by `IsCompanyUserOrAdmin`.
- **Query hygiene:** dossier assembly (Phase 3) locked with `CaptureQueriesContext` + `assertLessEqual(len(ctx), 10)`.
- **Schema:** `uv run python manage.py spectacular --validate` stays warning-free.
- **Live smoke check:** `manage.py ai_smoke` management command makes one cheap Flash call — manual post-deploy verification only, never part of the test suite.

## Out of scope (v1)

- Apply-from-chat tool (prompt-injection safeguards needed first)
- SSE/streaming chat responses
- Batch "recommended jobs for you" scoring
- Company-side chat assistant
- Embedding-based semantic search / RAG
