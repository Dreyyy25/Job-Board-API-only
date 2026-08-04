# CI Pipeline — Design

**Date:** 2026-08-04
**Status:** Approved pending user review
**Scope:** GitHub Actions CI gate, ruff adoption, Dependabot, branch protection with a PR-based workflow. No CD/deployment — that is a separate future phase.

## Goal

Every change to `staging` or `main` must pass the full verification suite before it can land, enforced by GitHub — not by discipline. The repository moves from direct fast-forward pushes to a PR-based flow with required status checks on both long-lived branches.

## Verified context

- Repo: `Dreyyy25/Job-Board-API-only`, **public** → GitHub Actions minutes are free and unlimited.
- `gh` CLI authenticated with `repo` + `workflow` scopes → workflow files can be pushed and rulesets/repo settings automated.
- Local PostgreSQL is **18.3** → CI pins the `postgres:18` image.
- Test suite: 404 tests, ~16 s, requires real Postgres with `CREATEDB` (the service container's `postgres` superuser has it).
- `config.py` reads `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `GEMINI_API_KEY` via `os.environ[...]` and crashes at import without them → CI must set all of them (dummy values; tests never touch the network and `AI_BLOCK_REAL_CHECKPOINTER=True` blocks the real checkpointer).
- `jobApp/settings/production.py` hard-asserts non-empty `ALLOWED_HOSTS` and a ≥50-char `SECRET_KEY` → the deploy-check step needs those set (dummies are fine).
- Known local artifact: `manage.py test` occasionally exits 1 after printing `OK` (autovacuum vs `DROP DATABASE` race) → CI sidesteps it with `--keepdb` (see below).

## Decisions (from the Q&A)

| Decision | Choice |
|---|---|
| Platform | GitHub Actions |
| Checks | Core five + ruff lint/format + Dependabot (no pip-audit) |
| Enforcement | Rulesets on **both** `staging` and `main`; full PR flow |
| Merge method | Merge commits only |
| Authority | Assistant pushes feature branches + opens PRs; user reviews and merges |
| Workflow structure | Single `ci` job |

## 1. Workflow — `.github/workflows/ci.yml`

- **Triggers:** `pull_request` (any target branch) and `push` to `staging`/`main` (post-merge confirmation run).
- **Concurrency:** group keyed on workflow + ref, `cancel-in-progress: true` — new commits to a PR cancel the superseded run.
- **Service:** `postgres:18` container with `pg_isready` health check, port 5432 published.
- **Env (all dummy, no secrets anywhere in the workflow):** `SECRET_KEY` (≥50 chars, value clearly labeled as a CI-only dummy — the repo is public), `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST=127.0.0.1`/`DB_PORT=5432` pointed at the service, `GEMINI_API_KEY` dummy, plus the minimum production env from `.env.example` for the deploy-check step (mirror that file, don't guess).
- **Steps, fail-fast order:**
  1. Checkout; `astral-sh/setup-uv` with caching; `uv sync --frozen` (lockfile is authoritative).
  2. `uv run ruff check .`
  3. `uv run ruff format --check .`
  4. `uv run python manage.py makemigrations --check --dry-run` — model changes without migrations fail here.
  5. `uv run python manage.py spectacular --validate --fail-on-warn` — enforces the CLAUDE.md promise that schema warnings fail CI. (Implementer verifies the exact flag name against the installed drf-spectacular before relying on it.)
  6. `check --deploy` with `DJANGO_SETTINGS_MODULE=jobApp.settings.production` — currently zero warnings; this locks it.
  7. `uv run python manage.py test --noinput --keepdb` — `manage.py` auto-picks test settings. `--keepdb` is deliberate: the runner is discarded after the job, so dropping the test DB is pointless, and skipping the drop entirely sidesteps the autovacuum teardown race.

## 2. Ruff

- `uv add --dev ruff`; config lives in `pyproject.toml`.
- `target-version = "py313"`; default lint rules (pyflakes + core pycodestyle) to start — stricter rule sets are future one-commit follow-ups.
- Format config matches the existing codebase (predominantly single quotes; implementer measures prevailing line length before choosing) — the goal is a small honest diff, not a blame-destroying reformat.
- `*/migrations/*` excluded from lint and format — generated code.
- Two separate commits: (a) dependency + config, (b) one-time cleanup making the existing codebase pass.

## 3. Dependabot — `.github/dependabot.yml`

- Ecosystems: `uv` (Python deps via `uv.lock`) and `github-actions` (action version bumps), both weekly.
- `target-branch: staging` for both — updates never target `main` directly; every update PR runs the full CI gate like any other PR.

## 4. Branch protection and repo settings

- Two rulesets via `gh api`, one each for `staging` and `main`:
  - Require a pull request before merging (0 required approvals — sole-maintainer repo; authors cannot approve their own PRs).
  - Require the `ci` status check to pass.
  - Block force pushes; restrict deletions.
  - **No bypass actors** — the rules bind everyone, including the owner.
- Repo settings: merge commits **on**, squash **off**, rebase **off** (the only merge button is the chosen method); "automatically delete head branches" **on**.
- Consequence, stated openly: `staging → main` promotions become PRs, `main` gains one merge commit per promotion, and the two branches stop being SHA-identical. That is expected under this model, not drift.

## 5. Rollout order (the CI PR proves itself)

1. Branch `feat/ci-pipeline` off `staging`: this spec, the plan, ruff config + cleanup, workflow, Dependabot config, docs updates.
2. Push the branch and open the first PR → `staging`. The `pull_request` event runs the new workflow from the branch — the CI PR is its own live test.
3. Only after that run is green: create the rulesets and flip the repo merge settings. Protection activates only once the check it requires demonstrably works.
4. User merges the PR; the push to `staging` triggers the post-merge run.
5. The existing 54-commit backlog then goes to `main` as the first promotion PR through the active gate.

## 6. Documentation updates

- `CLAUDE.md`: new CI section — what the gate runs, why `--keepdb` in CI, `uv run ruff check` / `uv run ruff format` as local commands, and the PR-based workflow rules (no direct pushes to `staging`/`main`, merge commits only).

## Error handling and edge cases

- **Dependabot/fork PRs:** run CI safely — the workflow contains zero real secrets, so restricted-token runs lose nothing.
- **Teardown flake:** eliminated in CI by `--keepdb`; the CLAUDE.md local-run note stays as-is.
- **`ai_smoke` and `ai_checkpointer_setup`:** never run in CI — one is billable, the other is a deploy step.
- **Duplicate runs:** `push` to feature branches is intentionally not a trigger; PRs cover them, so no push+PR double runs.

## Success criteria

1. A PR with a failing test, lint error, missing migration, or schema warning shows a red `ci` check and cannot be merged.
2. A direct push to `staging` or `main` is rejected by GitHub.
3. A green PR merges via merge commit; the post-merge push run on `staging` is green.
4. Dependabot opens its update PRs against `staging` and they run the gate.
5. Total CI wall-clock stays under ~3 minutes.

## Out of scope

- CD / deployment of any kind (runtime choice, gunicorn/whitenoise, caches — future phase).
- pip-audit (declined for now), coverage reporting, stricter ruff rule sets.
- Password reset / email — separate phase.
