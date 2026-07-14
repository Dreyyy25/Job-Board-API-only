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

- `apps.ai` is added **last** in `INSTALLED_APPS` — it imports from `apps.companies`, `apps.seekers`, and `apps.jobs`; nothing imports from it. Removing the AI layer later means removing one app.
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
| `schemas.py` | Pydantic output schemas for structured outputs |
| `services.py` | One service per agent; owns all LangChain/LangGraph logic |
| `views.py` | Thin try/except dispatchers, `@extend_schema` on every endpoint |
| `permissions.py` | `IsCompanyUser` (writer, screening), `IsSeekerUser` (resume import, chat) |
| `exceptions.py` | Domain exceptions mapping 1:1 to HTTP statuses |
| `throttling.py` | AI-specific scoped throttle classes |
| `models.py` | `AIUsageLog` (Phase 0), `ScreeningReport` (Phase 3), `Conversation` (Phase 4) |

### Auth and throttling

- Every endpoint uses `CustomJWTAuthentication`; no anonymous access (each call costs money).
- Layered throttling preserved per house rule (list all three classes when overriding). New scoped rates, tunable in settings: `ai` ≈ 30/min for single-call features, `ai-chat` ≈ 10/min for the agent loop.
- Test settings add the new scopes to the existing high-limit overrides so the suite doesn't 429 itself.

### Usage tracking

`AIUsageLog(feature, user FK, model, input_tokens, output_tokens, latency_ms, created_at)` — written by every service call from LangChain's response usage metadata. UUID PK like every other model. Provides per-feature/per-user cost visibility from day one.

### Testing seam

Services accept the chat model as an injectable parameter defaulting to the `llm.py` factory. Tests inject LangChain fake chat models; the suite never performs network I/O.

## Phase 1 — Job post writer

- **Endpoint:** `POST /api/v1/ai/job-post-assist/` — company-only — **Flash**.
- **Input:** rough free-text notes; optional hints (job type, location).
- **Flow:** service loads the requesting company's context (name, business stream) and the `SkillSet` taxonomy → one structured-output call → draft `{title, description, requirements, suggested_skills}`.
- **Skill grounding:** the prompt carries the taxonomy (id + name); returned skills are validated against the DB server-side and invented ones are dropped. Only real `SkillSet` IDs reach the client.
- **Draft-only:** the endpoint never creates a `JobPost`. The frontend feeds the draft into the existing job-post create endpoint, keeping the write path and its permissions unchanged.

## Phase 2 — Resume import

- **Endpoint:** `POST /api/v1/ai/resume-import/` — seeker-only — **Flash**.
- **Input:** pasted text or an uploaded PDF (multipart). Gemini reads PDFs natively — no parsing library. Cap: ~5 MB.
- **Output schema mirrors the models:** education entries shaped like `EducationData`, experience like `ExperienceData`, skills matched to the `SkillSet` taxonomy; unmatched skills returned separately as "new skill suggestions".
- **Draft-only:** the seeker reviews and confirms in the UI; confirmed rows are persisted through the existing seekers CRUD endpoints. No auto-committed AI output, no new write paths.

## Phase 3 — Applicant screening

- **Endpoint:** `POST /api/v1/ai/job-posts/{job_post_id}/screen/` — company-only with object-level ownership check (`job_post.company.user_account == request.user`; admins allowed) — **Pro**.
- **Flow:** gather applicants (`JobPostActivity` → seeker dossiers via `.with_related()` querysets, honoring the ≤10-query budget) → send compact dossiers + the post's description and required skills → structured output: per-candidate `{applicant_id, score, strengths, gaps, summary}` plus an overall ranking.
- **Cost guards:**
  - Applicant pool capped at ~50 most recent; larger pools are chunked and merged.
  - Results persisted in `ScreeningReport(job_post FK, report JSONField, applicant_count, created_at)`. Repeat requests return the stored report without an LLM call; a fresh run occurs only on `?refresh=true` or when new applications arrived since the report.
- **Empty pool:** `NoApplicantsError` → 409.

## Phase 4 — Chat assistant

- **Endpoints:** `POST /api/v1/ai/chat/` (`{conversation_id?, message}` → reply), `GET /api/v1/ai/chat/conversations/` (list own), `DELETE /api/v1/ai/chat/conversations/{id}/` — seeker-only — **Pro**.
- **Agent:** LangGraph ReAct agent with **read-only** tools wrapping the existing service/queryset layer:
  - `search_jobs(filters)` — published + active jobs via existing managers
  - `get_job_details(job_post_id)`
  - `get_my_profile()` — requesting seeker's profile, education, experience, skills
  - `compare_fit(job_post_id)` — skill overlap computed deterministically in Python; the agent narrates the result
- **No `apply_to_job` tool in v1 (deliberate).** Job descriptions are company-authored text injected into the agent's context — a prompt-injection vector. The agent returns job references; the frontend renders its normal Apply button. A confirmed-apply tool may be revisited later with explicit safeguards.
- **State:** LangGraph Postgres checkpointer keyed by conversation UUID, plus a light `Conversation(id, user FK, title, created_at)` model for listing and ownership enforcement.
- **Bounds:** max ~8 tool iterations per turn, ~90s request timeout, output token cap, trimmed history window.
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

Transient provider failures retry exactly once. All calls carry timeouts (~30s single-call, ~90s agent loop).

## Logging and privacy

Usage metrics, latency, and error classes log to the `apps` logger. Resume content, chat messages, and full prompt bodies are never logged — consistent with the project's hashed-email/GDPR-friendly logging posture.

## Testing strategy

- **Offline suite:** services receive fake LangChain chat models via the injectable seam; no test performs network I/O.
- **Per-feature assertions:** invented skills dropped (Phase 1); size caps enforced (Phase 2); cached `ScreeningReport` returned without an LLM call, refresh semantics (Phase 3); conversation ownership enforced, iteration bound respected (Phase 4).
- **Permissions:** each endpoint tested for both `user_type`s plus anonymous, matching existing conventions.
- **Query hygiene:** dossier assembly (Phase 3) locked with `CaptureQueriesContext` + `assertLessEqual(len(ctx), 10)`.
- **Schema:** `uv run python manage.py spectacular --validate` stays warning-free.
- **Live smoke check:** `manage.py ai_smoke` management command makes one cheap Flash call — manual post-deploy verification only, never part of the test suite.

## Out of scope (v1)

- Apply-from-chat tool (prompt-injection safeguards needed first)
- SSE/streaming chat responses
- Batch "recommended jobs for you" scoring
- Company-side chat assistant
- Embedding-based semantic search / RAG
