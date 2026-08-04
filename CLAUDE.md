# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Run from the repository root (where `manage.py` lives). Dependencies are managed by **uv** (Python 3.13 pinned via `.python-version`). Either activate the venv (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` otherwise) or prefix commands with `uv run`.

- Install / sync deps: `uv sync`
- Add a dependency: `uv add <package>` (writes to `pyproject.toml` + `uv.lock`)
- Run dev server: `uv run python manage.py runserver` (API served at `http://localhost:8000/api/v1/`)
- Make migrations: `uv run python manage.py makemigrations`
- Apply migrations: `uv run python manage.py migrate`
- Create superuser: `uv run python manage.py createsuperuser` (prompts for `email` + `user_type`; superusers default to `user_type='company'`)
- Run all tests: `uv run python manage.py test`
- Run tests for one app: `uv run python manage.py test apps.jobs`
- Run a single test: `uv run python manage.py test apps.jobs.tests.TestClassName.test_method`
- Django shell: `uv run python manage.py shell`

**Known dev artifact:** `manage.py test` occasionally exits 1 *after* printing `OK` — a Postgres autovacuum worker on the churn-heavy test DB doesn't release `test_job_board` within `DROP DATABASE`'s 5-second grace ("database is being accessed by other users"). That is teardown noise, not a test failure; rerun, or drop it manually:
```
uv run python -c "import psycopg; from apps.ai.checkpointer import build_conn_string; c=psycopg.connect(build_conn_string().rsplit('/',1)[0]+'/postgres', autocommit=True); c.execute(\"select pg_terminate_backend(pid) from pg_stat_activity where datname='test_job_board' and pid <> pg_backend_pid()\"); c.execute('DROP DATABASE IF EXISTS test_job_board')"
```

A `.env` file is required at the repo root. Required keys: `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (required); `DB_HOST`, `DB_PORT`, `DEBUG`, `ALLOWED_HOSTS`, `ADMIN_URL` (optional, see `.env.example`). `SECRET_KEY`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are read via `os.environ[...]` in `config.py` — the app crashes at import time if any of them are missing. PostgreSQL is required (not SQLite).

All env access goes through `config.py` at the repo root. `jobApp/settings.py` and `jobApp/urls.py` import plain Python constants from it. Do **not** add new `os.getenv()` calls scattered through the codebase — extend `config.py` instead.

## CI and git workflow

CI is a single GitHub Actions job (`ci` in `.github/workflows/ci.yml`) that runs on every PR and on pushes to `staging`/`main`: `ruff check`, `ruff format --check`, `makemigrations --check --dry-run`, `spectacular --validate --fail-on-warn`, production `check --deploy`, and the full test suite against a `postgres:18` service. All env values in the workflow are dummies — it uses no secrets, so Dependabot/fork PRs are safe. The test step uses `--keepdb` deliberately: the runner is discarded, and skipping the teardown `DROP DATABASE` sidesteps the autovacuum race described above. Never add `ai_smoke` (billable) or `ai_checkpointer_setup` (deploy step) to CI.

Ruff is the linter/formatter: `uv run ruff check .` and `uv run ruff format .` locally before pushing. Lint rules are pinned to `E4/E7/E9/F` in `pyproject.toml` — don't widen the selection casually; ruff's own defaults are broader and will flood the diff. The one-time format-normalization commit is listed in `.git-blame-ignore-revs` (GitHub's blame view respects it automatically; locally run `git config blame.ignoreRevsFile .git-blame-ignore-revs` once).

`staging` and `main` are protected by rulesets: changes land via PR with a green `ci` check — direct pushes are rejected, force pushes and deletions blocked, and the only merge method is a merge commit. Consequence: `staging` → `main` promotions are PRs, `main` gains one merge commit per promotion, and the two branches are no longer SHA-identical — that is expected, not drift. Merged head branches auto-delete on GitHub; prune locally with `git fetch --prune`.

## Docker and deployment

`Dockerfile` builds the production image: multi-stage uv → `python:3.13-slim`, non-root user, whitenoise-served static files collected at build time under production settings with inline dummy env. The entrypoint (`docker/entrypoint.sh`) runs `migrate` + `ai_checkpointer_setup` (both idempotent — Render's free tier has no pre-deploy hook) and then gunicorn with `--timeout 120`, which must stay above the AI chat's 90 s deadline. `docker compose up --build` runs that exact image against Postgres 18 locally — copy `.env.docker.example` to `.env.docker` (git-ignored) first. `GET /healthz` is a plain-Django health endpoint (cheap DB ping, no DRF, deliberately invisible to the OpenAPI schema). Render deployment — env table, health-check path, free-tier caveats — is documented in `DEPLOYMENT.md`; registry push and Render service setup are user-owned. Shell scripts are forced to LF via `.gitattributes` — don't commit `.sh` files with CRLF.

## Architecture

Django 5.2 + DRF monolith with JWT auth. Four domain apps under `apps/`, each mounted under `/api/v1/<app>/` by `jobApp/urls.py`. The admin URL path is read from the `ADMIN_URL` env var (default `admin/`).

### Custom user model — the center of everything

`apps.accounts.UserAccount` (`AUTH_USER_MODEL = 'accounts.UserAccount'`) replaces Django's default user. Key properties that drive the rest of the system:

- UUID primary keys across every model in the project (not integer IDs).
- `USERNAME_FIELD = 'email'` — there is no `username` field.
- `user_type` is `'job_seeker'` or `'company'`. Most permission checks and queryset filters branch on this field, so always preserve it when touching auth flows.
- `CustomJWTAuthentication` (in `apps/accounts/authentication.py`) overrides SimpleJWT's `get_user` to load `UserAccount` by `user_id` from the token. Every `ViewSet` in the project sets `authentication_classes = [CustomJWTAuthentication]` — don't rely on DRF's default session auth for API endpoints.
- JWTs are minted manually in `register` / `login` views via `RefreshToken.for_user(user)` and enriched with `user_id`, `email`, and `user_type` claims.
- The access token still travels in the JSON body (`tokens.access`); the refresh token never does. `register`/`login` set it as an httpOnly, path-scoped (`/api/v1/accounts/`), `SameSite=Lax` cookie (`AUTH_REFRESH_COOKIE` in `jobApp/settings/base.py`, plus `AUTH_REFRESH_COOKIE_SECURE`, which defaults to `True` in `base.py` and is overridden to `False` by development/test); `CookieTokenRefreshView` (`apps/accounts/views.py`) reads and rotates it cookie-only with no body fallback, and 401s — never 500s — when the token's user row is gone; `logout` blacklists and deletes it. Cookie helpers live in `apps/accounts/cookies.py`.

### App responsibilities and cross-app links

- `apps.accounts` — `UserAccount`, auth (register/login/me), JWT setup. Everything else FK's into `UserAccount`.
- `apps.companies` — `Company` (OneToOne to `UserAccount` with `limit_choices_to={'user_type': 'company'}`), `BusinessStream`, `CompanyImages`.
- `apps.seekers` — `SeekerProfile` (OneToOne, PK = `UserAccount`, `limit_choices_to={'user_type': 'job_seeker'}`), `EducationData`, `ExperienceData`, `SkillSet`, `SeekerSkillSet`.
- `apps.jobs` — `JobType`, `JobLocation`, `JobPost` (FK → `Company`), `JobPostActivity` (applications: FK → `UserAccount` + `JobPost`, `unique_together`), `JobPostSkillSet` (FK → `JobPost` + `SkillSet` from `apps.seekers`).

`apps.jobs` imports from both `apps.companies` and `apps.seekers`, so those two apps must be importable before jobs. `INSTALLED_APPS` order in `jobApp/settings.py` reflects this.

### Permission pattern (repeated across every viewset)

Each app has its own `permissions.py`. The shared convention:

1. `has_permission` gates by authentication / HTTP method.
2. `has_object_permission` branches: admin (`is_staff` or `is_superuser`) → allow; then owner check via `obj.<...>.user_account.id == request.user.id`.
3. Reference data (`JobType`, `BusinessStream`, `SkillSet`) uses `IsAdminOrReadOnly` — public read, admin write.
4. ViewSets additionally narrow `get_queryset()` by `user_type`. For example `JobPostViewSet.get_queryset` returns all jobs for admins, the company's own jobs (including unpublished) for company users, and only `is_published=True, is_active=True` for everyone else. Object-level permission and queryset filtering both enforce access — keep them consistent when adding endpoints.

`perform_create` hooks auto-assign ownership: `CompanyViewSet` sets `user_account=request.user`, `JobPostViewSet` looks up the user's `Company` and sets it on the post (and 400s if none exists). Follow this pattern for any new owned resource.

### Security posture (Argon2 / throttles / SameSite / logging)

Password hashing uses **Argon2** first (`argon2-cffi` installed), with PBKDF2/BCrypt kept in the list so existing hashes verify and auto-upgrade on next login. `settings/test.py` overrides to `MD5PasswordHasher` for test-suite speed — override via `@override_settings` when a test needs the real hasher.

Throttling is **layered**: `DEFAULT_THROTTLE_CLASSES = [AnonRateThrottle, UserRateThrottle, ScopedRateThrottle]` with rates `anon:100/day / user:1000/day / burst:60/min / register:5/min / login:10/min / token_refresh:20/min`. Write-heavy viewsets (`JobPostViewSet`, `apply_for_job`) explicitly list `throttle_classes = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle]` — setting this attribute **replaces** the defaults, so always list all three to preserve layered protection. `test.py` bumps anon/user/burst to `100000/day` via inner-dict spread so tests don't 429 each other through the shared LocMemCache; scoped rates (register/login/token_refresh) are preserved from base.

Cookie defaults: `SESSION_COOKIE_SAMESITE='Lax'`, `CSRF_COOKIE_SAMESITE='Lax'`, `SESSION_COOKIE_HTTPONLY=True`. These harden the admin surface — the API itself uses JWTs in the Authorization header, so an SPA with cookie-based auth would need different values.

`login` and `register` are **JSON-only** (`@parser_classes([JSONParser])` in `apps/accounts/views.py`) — a login-CSRF mitigation now that auth state lives in a cookie. Both are `AllowAny` `@api_view` FBVs, which DRF wraps in `csrf_exempt`, and both set the httpOnly refresh cookie; if they parsed form/multipart bodies a cross-site HTML `<form method="POST">` could plant an attacker's refresh token in a victim's browser (session fixation — `SameSite=Lax` governs when a cookie is *sent*, not whether a `Set-Cookie` is *accepted*). HTML forms cannot send `application/json`, and a cross-site `fetch` that does triggers a CORS preflight that fails. Do **not** generalize this to `DEFAULT_PARSER_CLASSES` — the AI resume-import endpoint needs multipart.

Failed-login attempts log a `WARNING` to `django.security` keyed by a 16-char SHA-256 prefix of the attempted email — preserves forensic correlation while keeping plaintext emails out of logs (GDPR-friendly default). Production LOGGING adds `django.security` and `django.request` loggers on top of the general `django`/`apps` set.

`DJANGO_SETTINGS_MODULE=jobApp.settings.production manage.py check --deploy` returns zero warnings when the required env is set — see `.env.example` "Minimum production env" section.

### Service layer + custom QuerySets

Every app has a `services.py` that owns the multi-step business logic (`apps.accounts.services.register_user`, `apps.jobs.services.apply_for_job`, `apps.seekers.services.build_seeker_dashboard`, etc.). Views are thin try/except dispatchers: they call a service, translate domain exceptions into HTTP responses, and serialize the return. Domain exceptions like `InvalidCredentialsError`, `InvalidApplicantError`, `DashboardPermissionError` map 1:1 to HTTP statuses — don't invent new translations in views, extend the service's exception set instead.

Every app also has a `managers.py` exposing a custom `QuerySet` with `.with_related()` / `.published()` / `.for_user(user)` / `.for_company(user)` / `.active()` chainable methods. Viewsets' `get_queryset` is now three-to-four branches of queryset-method composition — never inline `.select_related(...)`. `grep -rn 'select_related\|prefetch_related' apps/*/views.py` must return zero matches; the moment it doesn't, the N+1 regression is back.

The custom `UserAccountManager` uses the single-base `BaseUserManager.from_queryset(UserAccountQuerySet)` pattern — not `(BaseUserManager, Manager.from_queryset(X))` — to avoid the Manager-diamond MRO ambiguity. Keep `create_user` / `create_superuser` on the composite class body.

### Profile auto-creation (post_save signal)

Registering a `UserAccount` auto-creates its downstream profile via `apps.accounts.signals.create_user_profile`:

- `user_type='job_seeker'` → `SeekerProfile(first_name='', last_name='')`.
- `user_type='company'` → `Company(company_name='', business_stream=<Uncategorized>)`. The `'Uncategorized'` `BusinessStream` is `get_or_create`d on demand. Don't rename it — delete it and its companies first if you need to retire the catch-all.

`UserAccountManager.create_user` and the `register` view are both wrapped in `transaction.atomic()`, so signal failure rolls back the user row. `CompanyViewSet.perform_create` and `SeekerProfileViewSet.perform_create` 400 with `{'detail': 'Profile already exists...'}` — the signal guarantees a profile exists, so POST becomes PATCH territory. `register`'s response body includes a serialized `profile` payload so the frontend doesn't need a second round-trip.

### Routing

Each app exposes a DRF `DefaultRouter` plus a few function-based endpoints:

- `/api/v1/accounts/` — `users` viewset, plus `register/`, `login/`, `me/`, `token/refresh/`, `token/verify/`.
- `/api/v1/companies/` — `business-streams`, `profile` (CompanyViewSet — path is `profile`, not `companies`), `company-images`, plus `dashboard/<uuid:user_id>/`.
- `/api/v1/seekers/` — `profiles`, `education`, `experience`, `skills`, `seeker-skills`, plus `dashboard/<uuid:user_id>/`.
- `/api/v1/jobs/` — `job-types`, `job-locations`, `job-posts`, `job-applications`, `job-skills`, plus `apply/`, `applications/job/<uuid>/`, `applications/user/<uuid>/`.
- `/api/v1/ai/` — `job-post-assist/` (POST, company-only) and `resume-import/` (POST, seeker-only, exactly one of `text`/PDF `file` ≤ 5 MB) return drafts and create nothing; `job-posts/<uuid:job_post_id>/screen/` (POST, company-owner-or-admin, `?refresh=true` to bypass the cache) scores and ranks that post's applicants and caches the run as a `ScreeningReport`; `chat/` (POST, seeker-only, `{conversation_id?, message}` → `{conversation_id, reply}`), `chat/conversations/` (GET, seeker-only, own threads newest-first, capped at 50) and `chat/conversations/<uuid:conversation_id>/` (GET returns the transcript, DELETE removes the thread and its messages) drive the stateful chat assistant — the transcript GET was a deliberate addition beyond the original three-endpoint spec.

### AI features (`apps.ai`)

Leaf app for LLM features (Google Gemini via LangChain). All env access via
`config.py` (`GEMINI_API_KEY` required; `AI_MODEL_PRO`/`AI_MODEL_FLASH`
overridable). Services own the LangChain calls and accept the model as an
injectable — tests use `apps.ai.testing.FakeStructuredChatModel`, never the
network. AI views list **four** throttle classes
`[AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle]`
(overriding replaces defaults; `BurstRateThrottle` is shared in
`jobApp/throttling.py`, `AIRateThrottle` lives in `apps/ai/throttling.py`).
Every token-consuming LLM call — including failed-validation retries — writes an `AIUsageLog` row. Manual connectivity check:
`uv run python manage.py ai_smoke` (billable — not in the test suite).
Two error envelopes reach clients and the OpenAPI responses must say which:
the views' own exception translations return `{'error': ...}`, while DRF
answers permission (401/403) and throttle (429) failures itself with
`{'detail': ...}` before the view body runs. Statuses that can produce either —
screening's 403, every endpoint's 429 — are declared as the `AIErrorOrDetail`
`oneOf`. `AIErrorSchemaHonestyTests` locks both the declaration and the runtime
bodies, so the two cannot drift apart again.
Screening uses the **Pro** tier (writer and resume import use Flash), sends at
most 50 applicants (newest first — beyond that the response carries
`truncated` plus `excluded_count`), and labels candidates `candidate_1..N` so
the model never handles a UUID; labels it did not issue are dropped. Each
dossier is also capped per section (10 education / 15 experience / 30 skills,
constants in `services.py`) — seekers create those rows through unrestricted
viewsets, so an uncapped dossier is an applicant-controlled cost amplifier.
A stored `ScreeningReport` is replayed without an LLM call until
`?refresh=true` is passed or a `JobPostActivity` newer than
`report.created_at` exists — a timestamp rule, deliberately not a count, so
withdraw-plus-reapply still invalidates. `created_at` is stamped with the
**run's start**, not the row's write time, so an application arriving during
the LLM call still invalidates the report instead of being lost forever.

The chat assistant (**Pro** tier, seeker-only) is a `langchain.agents.create_agent`
ReAct loop over four **read-only** tools in `apps/ai/tools.py`. `build_tools(user)`
returns closures over the requesting user — **no tool takes a user id**, so text
injected into a company-authored job description cannot redirect a tool at
someone else's data. Tools only ever see `.published()` jobs and never expose
`job_description_hidden`.

Injection is also handled on the way *out*. `_sanitize_reply`
(`apps/ai/services.py`) runs every live reply, and every stored message
replayed into a transcript, through five ordered stages: (1) HTML entities are
unescaped first, so a scheme can't be smuggled past the URL matchers by
encoding a character; (2) dangerous raw HTML tags are stripped to a **fixed
point** — a tag-name allowlist plus an any-attribute-assignment rule, so both
named tags (`<img>`, `<script>`, `<image>`, ...) and unlisted tags carrying a
fetch/execute attribute (`<div onmouseover=...>`) are caught — looped up to a
pass bound because a single pass can leave a tag half-assembled
(`<scr<img src=x>ipt>` reassembles into `<script>`); if the bound is hit with
tag-shaped text still present, the loop **fails closed** into an unconditional
`<...>` strip with no name/attribute allowlist at all, rather than leaking a
partially-stripped tag; (3) markdown images/links are stripped; (4) bare
scheme URLs (any scheme, not an enumerated list), `www.`-prefixed URLs, and
protocol-relative (`//host/...`) URLs are stripped; (5) as the **final,
load-bearing step**, the survivor is run through `html.escape(text,
quote=False)` — a user-approved contract change, so whatever markup shape the
matchers above didn't anticipate still reaches the client as inert
`&lt;.../&gt;` text instead of live markup, closing the arms race by principle
instead of by enumeration. Consequence for API consumers: the `chat/` `reply`
field and a transcript's `assistant`-role `content` both carry
`&lt;`/`&gt;`/`&amp;` entities — markdown/HTML clients render correctly as-is,
plain-text clients must entity-decode once and render the decoded output as
text only — never insert it into HTML/the DOM, since markup that survived
stripping is inert only while escaped (decode-then-`innerHTML` on
`&lt;my-el onmouseover=...&gt;` reconstitutes a live element with a live
handler). Transcript **user**-role `content` is the opposite:
`HumanMessage.text` verbatim, never escaped, because it is
the requester's own text played back to them — clients must escape it
themselves before rendering as HTML. (Declared in the serializers'
`help_text` in `views.py`; stated here too because it's easy to miss.)

Four bounds are enforced, all in `_build_chat_agent` plus the model factory:
`ModelCallLimitMiddleware(run_limit=8, thread_limit=60, **exit_behavior='error'**)`,
a 90s wall-clock deadline checked between model calls, a 20-message cap on what
the model *sees*, and `max_output_tokens=1024`. `exit_behavior` must stay
`'error'`: the default `'end'` appends a synthetic reply reading *"Model call
limits exceeded: run limit (8/8)"* and hands it to the user as the assistant's
answer. The two call limits map to **different** exceptions —
`run_limit` → `AgentLimitExceededError` → **504** (retryable), `thread_limit` →
`ConversationExhaustedError` → **409** (never retryable, because the counter is
checkpointed and every future turn on that thread would raise too).

Four LangChain v1 behaviours are counterintuitive and are each locked by tests:
`agent.invoke()` returns the **whole thread**, so per-turn billing sums usage only
over messages after the last `HumanMessage`; history trimming **must** use
`@wrap_model_call` + `request.override(messages=...)` (a `@before_model` hook
returning a subset does nothing, because `add_messages` appends rather than
replaces); the trim uses `trim_messages(..., start_on='human', include_system=False)`
rather than a raw tail slice, since a slice can open the window on a
`ToolMessage` whose parent `AIMessage` was cut and Gemini rejects a
`functionResponse` with no preceding `functionCall` — **with a fallback**: a
single turn's own parallel tool calls can exceed `CHAT_HISTORY_MESSAGES` on
their own, leaving no `HumanMessage` inside the trimmed window; when that
happens the window becomes everything from the last `HumanMessage` onward
instead, deliberately allowed to overflow the cap, because a turn cannot be
truncated mid tool-call-sequence without orphaning a `ToolMessage`; and the
system prompt lives in `ModelRequest.system_message`, so it is never part of
the trimmed list. Failed turns still write their `AIUsageLog` row — the
run-limit path has already made eight billed Pro calls — because usage is
read back from the checkpoint and recorded **before** any rollback runs; that
usage-recording call and the rollback call are each wrapped in their own
`try/except Exception: logger.exception(...)`, so a bookkeeping failure in
either can never mask or replace the original domain exception.

Chat history lives in a LangGraph Postgres checkpointer (`apps/ai/checkpointer.py`),
not in Django models: its own psycopg3 pool, its own schema, created once by
`uv run python manage.py ai_checkpointer_setup` (**not** a Django migration).
Deserialization is hardened by passing `JsonPlusSerializer(allowed_msgpack_modules=None)`
explicitly to `PostgresSaver(...)` — that explicit serializer is the actual
control. The `LANGGRAPH_STRICT_MSGPACK` env var set early in
`jobApp/settings/base.py` is defence in depth only: langgraph snapshots that
var into a module constant at import time (which `import langchain.agents`
already triggers), so an app-code assignment is a verified no-op — do not rely
on it alone. The offline test suite has its own guard: `jobApp/settings/test.py`
sets `AI_BLOCK_REAL_CHECKPOINTER = True`, which makes the real
`get_checkpointer()` raise `AssertionError` instead of opening a pool against
the dev database (`config.DB_NAME`, a module constant the test runner never
rewrites to `test_<db>`) — any new test that forgets to inject a
fake/patched checkpointer fails loudly instead of quietly touching real data.

Deleting chat content goes through one path: a `pre_delete` receiver on
`Conversation` (`apps/ai/signals.py`) purges the checkpointer thread. That matters
because `Conversation.user` is CASCADE and the messages live in tables with no FK
to anything Django manages — without the receiver, deleting an account would
strand the whole transcript in Postgres, unreachable and unpurgeable. Registering
the receiver also disables Django's fast-delete path, which is what makes it fire
on direct delete, `user.delete()` cascades, and bulk deletes alike. The purge runs
**before** the row delete and **fails closed**: the checkpointer's autocommit pool
cannot join a Django transaction, so a failed purge aborting the row delete —
rather than deleting the row and leaving an unpurgeable transcript behind — is
the safe direction, deliberately at the cost of blocking account deletion while
the checkpointer is unreachable. Both delete sites (`delete_conversation` and the
new-conversation rollback inside `send_chat_message`) wrap `conversation.delete()`
in their own `transaction.atomic()`, because Django's collector runs
`Collector.delete()` inside `atomic(savepoint=False)`; without a savepoint to
unwind to, a raising `pre_delete` receiver would otherwise poison the caller's
transaction so every later query raises `TransactionManagementError` even
though the row itself survived. Partial-cascade caveat: deleting a user with N
conversations purges thread-then-row one conversation at a time; if the purge
for conversation #2 fails, Django rolls back that row delete (and the whole
cascade, including the user row) — but conversation #1's thread is already
gone, because the autocommit checkpointer pool has no transaction to roll back
— so a retry-after-fix can leave conversation #1 rowed-and-listed with its
transcript already purged.

Throttling splits by cost: `chat/` is token-consuming and lists the **four**
classes with `AIChatRateThrottle` (scope `ai-chat`, 10/min); the conversation
list/detail/delete endpoints consume no tokens and use the house trio.

### Query hygiene

Any ViewSet returning FK data must `select_related(...)`. Any reverse-FK or M2M returned in the response must `prefetch_related(...)`. Lock the query count on new list endpoints with `CaptureQueriesContext` + `assertLessEqual(len(ctx), N)` — budget `≤ 10` per list response regardless of row count. Avoid `assertNumQueries` for this purpose: it asserts exact equality and produces false failures when the real count lands below the ceiling.

### Settings organization

Put env-identical config in `jobApp/settings/base.py`. Put env-differing defaults in `development.py` / `production.py` / `test.py`. Never hardcode secrets or DB credentials anywhere — those stay in `config.py` and are read via `from config import ...`. `production.py` uses hard `assert` statements to fail-fast on missing `ALLOWED_HOSTS` or short `SECRET_KEY`. `manage.py` auto-picks `jobApp.settings.test` when running tests, `jobApp.settings.development` otherwise; `wsgi.py` / `asgi.py` default to `jobApp.settings.production`.

### OpenAPI schema (`drf-spectacular`)

- Live schema (OpenAPI 3): `GET /api/schema/` (YAML) or `?format=json` for JSON.
- Swagger UI: `GET /api/docs/` — interactive try-it-out console.
- ReDoc: `GET /api/redoc/`.
- Auth shows up as `jwtAuth` (HTTP bearer, format JWT) thanks to `apps.accounts.schema_extensions.CustomJWTAuthenticationScheme`, which is registered in `AccountsConfig.ready()`.
- Function-based views (`register`, `login`, `logout`, `me`, `apply_for_job`, `job_applications`, `user_applications`, `seeker_dashboard`, `company_dashboard`) declare request/response shapes via `@extend_schema(...)` with inline serializers. Keep these in sync when you change a function-view payload — viewsets auto-generate from their serializer_class.
- Regenerate / validate locally: `uv run python manage.py spectacular --validate`. CI should fail if this emits warnings.
- Frontend TS types: point your OpenAPI codegen at `http://localhost:8000/api/schema/?format=json`.

### Reference docs

- `API_DOCUMENTATION.md` — full endpoint catalog with request/response examples.
- `Job Board API.postman_collection.json` — importable Postman collection, kept alongside the docs.
