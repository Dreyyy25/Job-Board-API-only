# Deploying to AWS Lambda + Neon (always-free tier)

Architecture — every AWS piece is always-free at this project's scale;
Neon's free plan hosts PostgreSQL because AWS has no always-free Postgres:

```
Client ──HTTPS──▶ Lambda Function URL ──▶ Django container (Lambda) ──TLS──▶ Neon PostgreSQL
```

The container is a stock gunicorn app; the AWS Lambda Web Adapter baked
into the image translates Lambda events to HTTP. WhiteNoise serves the
collected static files, so the admin and `/api/docs/` work with no bucket.

## Prerequisites

- Docker Desktop running.
- AWS CLI authenticated (`aws login`).
- A [neon.tech](https://neon.tech) free-plan account.

## 1. Create the database on Neon

1. Neon console → **New project** (pick a region close to your Lambda region).
2. From the project's **Connection details**, note: host, database name,
   user, password. These map to `DB_HOST`, `DB_NAME`, `DB_USER`,
   `DB_PASSWORD` (`DB_PORT` stays `5432`).

## 2. Run migrations from your machine

Neon is reachable from anywhere over TLS, so migrations run locally.
Point `.env` at Neon (the five `DB_*` values), then:

```powershell
$env:PGSSLMODE = 'require'
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

Repeat the `migrate` step after any model change — the Lambda container
never runs migrations itself (concurrent cold starts must not race them).

## 3. Build and push the image to ECR

```powershell
# once: create the repository
aws ecr create-repository --repository-name jobboard-api --region <REGION>

# every deploy: build, tag, push
docker build -t jobboard-api .
aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
docker tag jobboard-api:latest <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/jobboard-api:latest
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/jobboard-api:latest
```

`<ACCOUNT_ID>` is the 12-digit ID from `aws sts get-caller-identity`;
`<REGION>` e.g. `ap-southeast-1`.

## 4. Create the Lambda function (console)

Lambda console → **Create function** → **Container image**:

- Image: browse to `jobboard-api:latest`; architecture **x86_64**.
- **Configuration → General**: memory **1024 MB**, timeout **120 s**
  (headroom for the AI screening endpoint's Pro-model calls).

**Configuration → Environment variables** — set:

| Variable | Value |
|---|---|
| `SECRET_KEY` | 64+ random chars — `uv run python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `ALLOWED_HOSTS` | the Function URL host (add after step 5) |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | from Neon (step 1) |
| `GEMINI_API_KEY` | your Google AI Studio key |
| `SECURE_PROXY_SSL_HEADER` | `HTTP_X_FORWARDED_PROTO=https` |
| `CORS_ALLOWED_ORIGINS` | your frontend origin(s), comma-separated |
| `CSRF_TRUSTED_ORIGINS` | `https://<function-url-host>` (admin logins) |

`DJANGO_SETTINGS_MODULE` and `PGSSLMODE` are baked into the image.
`SECURE_PROXY_SSL_HEADER` is required: the Function URL terminates TLS,
and without it Django's `SECURE_SSL_REDIRECT` loops every request into
a 301.

## 5. Create the Function URL

**Configuration → Function URL → Create**: auth type **NONE**, leave
CORS unconfigured (Django's `django-cors-headers` owns CORS; configuring
both duplicates headers and breaks browsers).

Copy the host (`xxxx.lambda-url.<region>.on.aws`) into the
`ALLOWED_HOSTS` env var — without it every request 400s (DisallowedHost).

## 6. Verify

- `https://<function-url>/api/docs/` → Swagger UI loads (static files +
  boot OK; first hit after idle takes a few seconds — cold start).
- POST `register` from Swagger → 201 proves the Neon connection.
- `https://<function-url>/admin/` → admin logs in over HTTPS.

## 7. Guardrails (do once)

- CloudWatch → the function's log group → retention **7 days** (log
  ingestion has a 5 GB/month always-free allowance).
- ECR → repository → lifecycle policy → keep only the most recent image
  (image storage is the one unavoidable cost: ~$0.10/GB-month ≈ $0.05).
- Billing → Budgets → $1 alert, in case anything drifts.

## Redeploying a code change

Rebuild + push (step 3), then Lambda console → **Image** → **Deploy new
image** (or `aws lambda update-function-code --function-name jobboard-api
--image-uri <same uri>`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Endless 301 redirects | `SECURE_PROXY_SSL_HEADER` env var missing or malformed |
| Every request 400s | Function URL host missing from `ALLOWED_HOSTS` |
| `SSL connection is required` in logs | `PGSSLMODE` was overridden; must be `require` for Neon |
| First request takes 5–10 s | Cold start (plus Neon waking) — expected on the free tiers |
| 502 from the Function URL | App crashed at import — check the CloudWatch log group for the traceback |
