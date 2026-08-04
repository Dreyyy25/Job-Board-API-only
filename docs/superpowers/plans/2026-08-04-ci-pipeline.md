# CI Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GitHub Actions gate that every change to `staging` or `main` must pass, enforced by branch rulesets and a PR-based workflow.

**Architecture:** One `ci` job runs ruff, the missing-migration check, OpenAPI validation, the production deploy check, and the full test suite against a Postgres 18 service container, using only dummy env values. Rulesets on `staging`/`main` require a PR plus a green `ci` check; Dependabot keeps dependencies and action versions current via PRs that run the same gate.

**Tech Stack:** GitHub Actions, `astral-sh/setup-uv`, `postgres:18` service container, ruff (pinned rule selection), Dependabot (`uv` + `github-actions` ecosystems), `gh` CLI for rulesets/repo settings.

**Spec:** `docs/superpowers/specs/2026-08-04-ci-pipeline-design.md` (approved).

## Global Constraints

- Work on branch `feat/ci-pipeline` (exists, branched off `staging`; spec committed as `358381a`).
- Commit style: conventional (`type(scope): summary`). **Never add a `Co-Authored-By` trailer.**
- The repo is **public**. No personal emails or organization names beyond the `Dreyyy25` GitHub identity in any commit message, PR text, code comment, or doc.
- The workflow must contain **zero real secrets** — every env value is a dummy.
- Never run `manage.py ai_smoke` in CI (billable) or `ai_checkpointer_setup` (deploy step).
- All dependency changes via `uv` (`uv add`, `uv sync`) — never pip.
- Lint rule selection is pinned explicitly. Installed ruff (0.16.1) has wider defaults (`I`, `RUF`, `SIM`, …) than the spec's "pyflakes + core pycodestyle" — do NOT rely on ruff defaults.
- The CI job's id/name must be exactly `ci` — Task 6's rulesets reference that status-check context string.
- Full test suite = 404 tests. Any task that touches Python code ends with the suite green.

## Verified facts (measured 2026-08-04, don't re-litigate)

- Local Postgres is 18.3 → CI pins `postgres:18`.
- `manage.py spectacular --help` shows `--fail-on-warn` exists.
- `check --deploy` under production settings with the exact dummy env in Task 3 returns "System check identified no issues (0 silenced)."
- `ruff check --select E4,E7,E9,F` finds exactly 33 violations (breakdown in Task 1).
- `ruff format` with `quote-style = "preserve"`, `line-length = 120`, migrations excluded reformats 71 of 106 files — whitespace/blank-line/comment-spacing churn only. This was measured as the *minimum* churn config (single-quote: 77 files, double-quote: 80). The 106 included markdown files (ruff 0.16 formats Python fences in `.md`); with `docs/` also excluded the count drops — Task 2 re-measures via `ruff format --check` before formatting. Execution note: the plan's original Task 1 config block omitted `[tool.ruff.format]`; Task 2's implementer caught it via the stop-the-line rule and the config was corrected before any format commit.
- Codebase max line length is 113 → `line-length = 120` means the formatter never rewraps an existing line.
- `gh` is authenticated as `Dreyyy25` with `repo` + `workflow` scopes.

---

### Task 1: Ruff dependency, config, and lint cleanup

**Files:**
- Modify: `pyproject.toml`
- Modify: `apps/accounts/tests.py:71`, `apps/companies/tests.py:23` (F841)
- Modify (via `ruff check --fix`): `apps/companies/admin.py`, `apps/jobs/admin.py`, `apps/seekers/admin.py`, `apps/companies/tests.py`, `apps/companies/views.py`, `apps/jobs/tests.py`, `apps/jobs/views.py`, `apps/seekers/tests.py`, `apps/seekers/views.py` (F401)

**Interfaces:**
- Produces: `[tool.ruff]` config in `pyproject.toml` consumed by Task 2 (format) and Task 3 (CI runs `uv run ruff check .` and `uv run ruff format --check .`).

- [ ] **Step 1: Add ruff as a dev dependency**

```
uv add --dev ruff
```

This creates a `[dependency-groups]` table in `pyproject.toml` with `dev = ["ruff>=0.16.1"]` (or newer) and updates `uv.lock`.

- [ ] **Step 2: Add the ruff config to `pyproject.toml`**

Append after the existing `[tool.uv]` table:

```toml
[tool.ruff]
target-version = "py313"
line-length = 120
# docs/ excluded too: ruff 0.16 formats Python fences inside markdown, and
# churning committed plan/spec documents serves nobody.
extend-exclude = ["migrations", "docs"]

[tool.ruff.format]
# Keep existing quote characters — formatting normalizes whitespace only.
quote-style = "preserve"

[tool.ruff.lint]
# Pinned deliberately: installed ruff's defaults are wider (I, RUF, SIM, ...)
# and would force a large noisy cleanup. Stricter sets are future follow-ups.
select = ["E4", "E7", "E9", "F"]

[tool.ruff.lint.per-file-ignores]
# Test modules accrete section-scoped imports between test classes; harmless.
"apps/*/tests.py" = ["E402"]
# Django settings idiom: star-import from base, then reference/override names.
"jobApp/settings/*" = ["F403", "F405"]
```

- [ ] **Step 3: Run the auto-fixer for the 12 unused imports**

```
uv run ruff check --fix .
```

Expected: it removes exactly the 12 `F401` unused imports — `django.contrib.admin` in the three stub `admin.py` files (companies/jobs/seekers — accounts' has real registrations and is not flagged), `OpenApiResponse`/`OpenApiParameter` leftovers in `companies/jobs/seekers` `views.py`, and five stale test imports (`Company` ×2, `cache`, `override_settings`, `JobPostActivity`, `SeekerProfile`). Review `git diff` to confirm nothing else changed — none of these are re-exports; all are dead.

- [ ] **Step 4: Fix the two F841 unused variables by hand**

`apps/accounts/tests.py:71` and `apps/companies/tests.py:23` each assign `r = self.client...` and never read `r`. Read the surrounding lines first, then delete just the `r = ` prefix, keeping the call. Line numbers may have shifted slightly after Step 3 — locate with `uv run ruff check .`, which after this step must report the remaining violations as zero.

- [ ] **Step 5: Verify lint is clean**

```
uv run ruff check .
```

Expected: `All checks passed!`, exit 0.

- [ ] **Step 6: Verify the suite still passes**

```
uv run python manage.py test --noinput
```

Expected: `OK`, 404 tests. (If the process exits 1 *after* printing `OK`, that's the documented autovacuum teardown race — rerun or use the CLAUDE.md cleanup one-liner; it is not a failure.)

- [ ] **Step 7: Commit in two pieces**

```
git add pyproject.toml uv.lock
git commit -m "build(dev): add ruff with lint rules pinned to pyflakes + core pycodestyle"
git add -A
git commit -m "refactor: drop unused imports and variables flagged by ruff"
```

---

### Task 2: One-time format normalization + blame shield

**Files:**
- Modify: ~71 Python files (whitespace-only churn, no logic changes)
- Create: `.git-blame-ignore-revs`

**Interfaces:**
- Consumes: `[tool.ruff]` config from Task 1.
- Produces: a formatted tree where `uv run ruff format --check .` exits 0 (Task 3's CI step depends on this).

- [ ] **Step 0: Confirm the config is quote-preserving before touching anything**

```
uv run ruff format --check .
```

Verify `pyproject.toml` contains `[tool.ruff.format]` with `quote-style = "preserve"` and that `extend-exclude` covers both `migrations` and `docs`. Record the "N files would be reformatted" count — that is this run's expectation for Step 1. Only `.py` files may appear in the list; any `.md` file listed means the docs exclusion is broken — stop and fix the config first.

- [ ] **Step 1: Run the formatter**

```
uv run ruff format .
```

Expected: exactly the file count Step 0 reported (~55–75 `.py` files). The diff is trailing whitespace, blank-line normalization, and comment spacing — no line rewrapping (max existing line 113 < 120) and **zero quote-character changes**.

- [ ] **Step 2: Sanity-check the diff is format-only**

```
git diff --stat
```

Then skim `git diff` itself (spot-check at least five files, including one from each app). Everything must be whitespace, blank lines, or comment spacing. Any semantic-looking change — altered string contents, reordered arguments, changed operators — is a stop-the-line finding: revert and investigate before committing.

- [ ] **Step 3: Prove behavior is unchanged**

```
uv run python manage.py test --noinput
```

Expected: `OK`, 404 tests.

- [ ] **Step 4: Commit the normalization**

```
git add -A
git commit -m "style: one-time ruff format normalization (no behavior change)"
```

- [ ] **Step 5: Shield `git blame` from the normalization commit**

```
git rev-parse HEAD
```

Create `.git-blame-ignore-revs` at the repo root containing (substitute the real 40-char SHA):

```
# One-time ruff format normalization; whitespace-only, no behavior change.
# Use: git config blame.ignoreRevsFile .git-blame-ignore-revs
# GitHub's blame view picks this file up automatically.
<sha-from-git-rev-parse>
```

Then:

```
git config blame.ignoreRevsFile .git-blame-ignore-revs
git add .git-blame-ignore-revs
git commit -m "chore: ignore the format normalization commit in git blame"
```

- [ ] **Step 6: Verify the format gate is green**

```
uv run ruff format --check .
```

Expected: all files already formatted, exit 0.

---

### Task 3: The CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: ruff config (Task 1) and formatted tree (Task 2).
- Produces: a status check named `ci` — Task 6's rulesets require exactly this context string. Do not rename the job.

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [staging, main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  ci:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    services:
      postgres:
        image: postgres:18
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: job_board
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      # Every value below is a CI-only dummy. This workflow uses no secrets.
      SECRET_KEY: ci-only-dummy-key-not-a-secret-0123456789abcdefghijklmnopqrstuvwxyz
      DB_NAME: job_board
      DB_USER: postgres
      DB_PASSWORD: postgres
      DB_HOST: 127.0.0.1
      DB_PORT: "5432"
      GEMINI_API_KEY: ci-dummy
      ALLOWED_HOSTS: ci.invalid
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - name: Install dependencies
        run: uv sync --locked
      - name: Lint
        run: uv run ruff check .
      - name: Format check
        run: uv run ruff format --check .
      - name: Missing-migration check
        run: uv run python manage.py makemigrations --check --dry-run
      - name: OpenAPI schema validation
        run: uv run python manage.py spectacular --validate --fail-on-warn > /dev/null
      - name: Production deploy check
        env:
          DJANGO_SETTINGS_MODULE: jobApp.settings.production
          DEBUG: "false"
          SECURE_SSL_REDIRECT: "true"
          SECURE_HSTS_SECONDS: "31536000"
          CORS_ALLOWED_ORIGINS: https://ci.invalid
          CSRF_TRUSTED_ORIGINS: https://ci.invalid
        run: uv run python manage.py check --deploy
      - name: Tests
        run: uv run python manage.py test --noinput --keepdb
```

Design notes the implementer must not "improve" away:
- The production env block is **step-scoped** so `SECURE_SSL_REDIRECT` can never leak into the test run and 301-redirect every test request.
- `--keepdb`: the runner is discarded after the job, so dropping the test DB is pointless — and skipping the drop sidesteps the documented autovacuum teardown race.
- `--locked` makes a stale `uv.lock` a build failure instead of a silent re-resolve.
- `push` deliberately covers only `staging`/`main` — feature branches get their run from the `pull_request` event, so no double runs.
- The schema output is sent to `/dev/null`; only warnings/errors (stderr) and the exit code matter.

- [ ] **Step 2: Verify the YAML parses**

```
uvx yamllint -d "{extends: relaxed, rules: {line-length: disable}}" .github/workflows/ci.yml
```

Expected: exit 0, no errors (warnings acceptable).

- [ ] **Step 3: Run each gate command locally exactly as CI will**

```
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn > $null
```

(`> $null` is the PowerShell null redirect; in Bash use `> /dev/null` — the point is only that warnings arrive on stderr and the exit code decides.)

Expected: all exit 0. Then the deploy check with the step env (PowerShell):

```
$env:DJANGO_SETTINGS_MODULE='jobApp.settings.production'; $env:DEBUG='false'
$env:SECRET_KEY='ci-only-dummy-key-not-a-secret-0123456789abcdefghijklmnopqrstuvwxyz'
$env:ALLOWED_HOSTS='ci.invalid'; $env:SECURE_SSL_REDIRECT='true'
$env:SECURE_HSTS_SECONDS='31536000'
$env:CORS_ALLOWED_ORIGINS='https://ci.invalid'; $env:CSRF_TRUSTED_ORIGINS='https://ci.invalid'
uv run python manage.py check --deploy
```

Expected: `System check identified no issues (0 silenced).` (already verified once during planning — this re-run guards against drift). Run these in a fresh shell afterwards (or unset the vars) so the production settings module doesn't contaminate later commands.

- [ ] **Step 4: Commit**

```
git add .github/workflows/ci.yml
git commit -m "ci: GitHub Actions gate (ruff, migrations, schema, deploy check, tests)"
```

---

### Task 4: Dependabot + documentation

**Files:**
- Create: `.github/dependabot.yml`
- Modify: `CLAUDE.md` (insert new section between `## Commands` and `## Architecture`)

**Interfaces:**
- Consumes: nothing.
- Produces: docs stating the workflow rules Task 5–7 follow.

- [ ] **Step 1: Write `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
    target-branch: "staging"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    target-branch: "staging"
```

`target-branch: staging` means version-update PRs never aim at `main`; they run the full `ci` gate like any PR. (Note: with a custom target branch, Dependabot *security* updates still target the default branch — acceptable.) If GitHub's Dependabot tab reports the `uv` ecosystem as unknown after merge (it is supported, but this is the one un-verifiable-before-push fact), fall back to `package-ecosystem: "pip"` in a follow-up PR.

- [ ] **Step 2: Verify the YAML parses**

```
uvx yamllint -d "{extends: relaxed, rules: {line-length: disable}}" .github/dependabot.yml
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```
git add .github/dependabot.yml
git commit -m "ci: weekly Dependabot updates for Python deps and action versions"
```

- [ ] **Step 4: Add the CI section to CLAUDE.md**

Insert between the `## Commands` section (after the paragraph ending "extend `config.py` instead.") and `## Architecture`:

```markdown
## CI and git workflow

CI is a single GitHub Actions job (`ci` in `.github/workflows/ci.yml`) that runs on every PR and on pushes to `staging`/`main`: `ruff check`, `ruff format --check`, `makemigrations --check --dry-run`, `spectacular --validate --fail-on-warn`, production `check --deploy`, and the full test suite against a `postgres:18` service. All env values in the workflow are dummies — it uses no secrets, so Dependabot/fork PRs are safe. The test step uses `--keepdb` deliberately: the runner is discarded, and skipping the teardown `DROP DATABASE` sidesteps the autovacuum race described above. Never add `ai_smoke` (billable) or `ai_checkpointer_setup` (deploy step) to CI.

Ruff is the linter/formatter: `uv run ruff check .` and `uv run ruff format .` locally before pushing. Lint rules are pinned to `E4/E7/E9/F` in `pyproject.toml` — don't widen the selection casually; ruff's own defaults are broader and will flood the diff. The one-time format-normalization commit is listed in `.git-blame-ignore-revs` (GitHub's blame view respects it automatically; locally run `git config blame.ignoreRevsFile .git-blame-ignore-revs` once).

`staging` and `main` are protected by rulesets: changes land via PR with a green `ci` check — direct pushes are rejected, force pushes and deletions blocked, and the only merge method is a merge commit. Consequence: `staging` → `main` promotions are PRs, `main` gains one merge commit per promotion, and the two branches are no longer SHA-identical — that is expected, not drift. Merged head branches auto-delete on GitHub; prune locally with `git fetch --prune`.
```

- [ ] **Step 5: Commit**

```
git add CLAUDE.md
git commit -m "docs: document the CI gate and PR-based workflow"
```

---

### Task 5: Push, open the PR, watch the first live run

**Files:** none (git/GitHub operations only).

**Interfaces:**
- Consumes: all commits from Tasks 1–4 plus the spec/plan commits.
- Produces: an open PR `feat/ci-pipeline` → `staging` with a green `ci` check; Task 6 will not run before that check has passed.

- [ ] **Step 1: Push the branch**

```
git push -u origin feat/ci-pipeline
```

- [ ] **Step 2: Open the PR**

Write the body to a temp file (`$CLAUDE_JOB_DIR/tmp/pr-body.md`), content exactly:

```markdown
## What this adds

- **GitHub Actions gate** — a single `ci` job on every PR and on pushes to `staging`/`main`: ruff lint + format check, missing-migration check, OpenAPI schema validation (fails on warnings), production deploy check, and the full 404-test suite against a Postgres 18 service container.
- **Ruff** — lint rules pinned to pyflakes + core pycodestyle; format config chosen to match the existing code (quote-preserving, line length 120). Includes a one-time whitespace-only normalization commit, listed in `.git-blame-ignore-revs` so blame stays useful.
- **Dependabot** — weekly update PRs for Python dependencies and action versions, targeting `staging`.
- **Docs** — CLAUDE.md section describing the gate and the PR-based workflow.

## Notes

- The workflow contains zero secrets — every env value is a dummy, so Dependabot and fork PRs run safely.
- The test step uses `--keepdb`: the runner is discarded after the job, and skipping the teardown drop sidesteps a local autovacuum/DROP DATABASE race documented in CLAUDE.md.
- Once this PR's `ci` check is green, branch rulesets (PR-only, required `ci` check, merge commits only) are activated on `staging` and `main` — this PR proves the gate before the gate becomes law.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Then:

```
gh pr create --base staging --head feat/ci-pipeline --title "CI pipeline: GitHub Actions gate, ruff, Dependabot" --body-file "$CLAUDE_JOB_DIR/tmp/pr-body.md"
```

- [ ] **Step 3: Watch the run**

```
gh pr checks --watch --fail-fast
```

Expected: the `ci` check passes. This is the workflow's first execution on real GitHub infrastructure — the local runs in Task 3 make failure unlikely but not impossible (action version typos, service-container startup, Linux-vs-Windows differences).

- [ ] **Step 4: If the run fails — fix loop**

```
gh run list --branch feat/ci-pipeline --limit 1
gh run view <run-id> --log-failed
```

Diagnose from the failing step's log, fix locally, verify the equivalent local command passes, commit with a conventional message, push, and re-watch. Do not merge, rerun-without-diagnosis, or disable a failing step to get to green.

---

### Task 6: Activate protection, then hand off for merge

**Files:** none (GitHub API operations only). **Precondition: Task 5's `ci` check is green.**

**Interfaces:**
- Consumes: the green `ci` status-check context from Task 5.
- Produces: active rulesets on `staging` and `main`; repo merge settings restricted to merge commits.

- [ ] **Step 1: Restrict repo merge methods and enable head-branch auto-delete**

```
gh api -X PATCH repos/Dreyyy25/Job-Board-API-only -F allow_squash_merge=false -F allow_rebase_merge=false -F allow_merge_commit=true -F delete_branch_on_merge=true
```

- [ ] **Step 2: Create the staging ruleset**

Write `$CLAUDE_JOB_DIR/tmp/ruleset-staging.json`:

```json
{
  "name": "protect-staging",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/staging"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge"]
      } },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [ { "context": "ci" } ]
      } }
  ]
}
```

```
gh api -X POST repos/Dreyyy25/Job-Board-API-only/rulesets --input "$CLAUDE_JOB_DIR/tmp/ruleset-staging.json"
```

Fallback: if the API 422s specifically on `allowed_merge_methods` (field name drift), delete that key and retry — Step 1's repo settings already enforce merge-commit-only repo-wide.

- [ ] **Step 3: Create the main ruleset**

Same JSON with `"name": "protect-main"` and `"include": ["refs/heads/main"]`, saved as `ruleset-main.json`, POSTed the same way.

- [ ] **Step 4: Verify both rulesets are active**

```
gh api repos/Dreyyy25/Job-Board-API-only/rulesets
```

Expected: two entries, `enforcement: "active"`, targets `staging` and `main`. Note: zero required approvals is deliberate — a sole maintainer cannot approve their own PRs; the gate is the `ci` check plus the PR-shaped audit trail. **No bypass actors** — the rules bind the owner too.

- [ ] **Step 5: STOP — user gate**

Report to the user: the PR is green and protection is live. **The user merges the PR** (the only button available is "Create a merge commit", gated on `ci`). Do not merge it for them.

---

### Task 7: Post-merge confirmation + promotion PR (after the user merges)

**Files:** none. **Precondition: the user has merged PR feat/ci-pipeline → staging.**

- [ ] **Step 1: Confirm the post-merge run**

```
gh run list --branch staging --limit 1
```

Expected: a completed, successful `CI` run triggered by the merge push.

- [ ] **Step 2: Sync local state**

```
git switch staging
git pull
git branch -d feat/ci-pipeline
git fetch --prune
```

(The remote branch auto-deleted on merge; `-d` is safe because the merge commit contains the branch.)

- [ ] **Step 3: Open the promotion PR (the backlog goes to main)**

Body to `$CLAUDE_JOB_DIR/tmp/promo-body.md`:

```markdown
Promotes everything accumulated on `staging` to `main` — the first promotion through the new CI gate:

- Refresh-token cookie auth flow + security hardening (Argon2, layered throttles, JSON-only auth endpoints, security logging).
- The complete AI suite: job-post writer, resume import, applicant screening, and the seeker chat assistant (sanitized replies, Postgres-checkpointed history, GDPR-safe deletion).
- The CI gate itself: GitHub Actions checks, ruff, Dependabot, and branch protection on `staging` and `main`.

Full test suite: 404 tests, green in CI.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

```
gh pr create --base main --head staging --title "Promote staging to main: hardening, AI suite, CI gate" --body-file "$CLAUDE_JOB_DIR/tmp/promo-body.md"
```

- [ ] **Step 4: Watch its `ci` check, then hand off**

```
gh pr checks --watch --fail-fast
```

Expected: green (same tree that just passed, plus the merge commit). Then report to the user: **the user merges** the promotion PR. `main` gains a merge commit and stops being SHA-identical to `staging` — expected under the new model, per the spec.

---

## Out of scope (from the spec — do not add)

- CD/deployment, gunicorn/whitenoise, cache backends.
- pip-audit, coverage reporting, stricter ruff rule sets, import sorting (`I`).
- Password reset / email.
