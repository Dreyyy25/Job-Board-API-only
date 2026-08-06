# Deploying the Job Board API (Docker → Render)

The repo ships a production Docker image. You build and push it to a registry;
Render runs it as a web service from that image. Nothing in this repo pushes
images or talks to Render.

## 1. Build and verify locally

    docker compose up --build          # copy .env.docker.example -> .env.docker first
    curl http://localhost:8000/healthz # {"status": "ok"}

The compose harness runs the exact production image (gunicorn, whitenoise,
migrations + AI-checkpointer setup in the entrypoint) against Postgres 18.

## 2. Tag and push (user-owned)

    docker build -t <registry>/<namespace>/jobboard-api:<tag> .
    docker push <registry>/<namespace>/jobboard-api:<tag>

Build from a clean checkout of `main` so the image matches a released state.

## 3. Render web service

Create a **Web Service → Existing image** pointing at the pushed image.

- **Health check path:** `/healthz`
- **Port:** Render injects `PORT` automatically; the entrypoint binds it.
- The entrypoint applies migrations and creates the LangGraph checkpointer
  tables on every boot (both idempotent) — required because free instance
  types have no pre-deploy command.

### Environment variables

| Variable | Value |
|---|---|
| `SECRET_KEY` | ≥50 random chars — `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DEBUG` | `false` |
| `ALLOWED_HOSTS` | `<app>.onrender.com` (plus any custom domain) |
| `CSRF_TRUSTED_ORIGINS` | `https://<app>.onrender.com` (comma-separated if more) |
| `CORS_ALLOWED_ORIGINS` | your frontend origin(s), e.g. `https://<frontend>.onrender.com` |
| `SECURE_PROXY_SSL_HEADER` | `HTTP_X_FORWARDED_PROTO=https` (Render terminates TLS at its proxy) |
| `SECURE_SSL_REDIRECT` | `true` |
| `SECURE_HSTS_SECONDS` | `31536000` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | from your Postgres provider's connection info |
| `GEMINI_API_KEY` | real key (https://aistudio.google.com/apikey) |
| `ADMIN_URL` | optional custom admin path, e.g. `manage-7f3k/` |
| `WEB_CONCURRENCY` | optional; gunicorn workers, default 2 |

## 4. Postgres

Any Postgres 14+ reachable from Render works — the app takes five discrete
`DB_*` vars, so Render Postgres and external providers (Neon, Supabase, ...)
are interchangeable. Free-tier realities:

- **Render free Postgres expires after 30 days.** External free tiers vary:
  Neon's doesn't expire; some others (e.g. Supabase) pause idle projects
  after about a week until manually restored — check your provider's policy
  against an API that will sit idle.
- The AI chat checkpointer stores its tables in the **same** database;
  no extra configuration.

## 5. Known free-tier limitations

- Free web services spin down when idle; the first request after sleep is
  slow (cold start + migrations re-check).
- **No file uploads are stored.** Company images are external URLs
  (`CompanyImages.image_url`), and the AI resume-import PDF is parsed in
  memory and discarded — nothing writes to the container's disk, so there
  is nothing to lose on restart. Object storage only becomes relevant if a
  real upload feature is ever added.
- No shell on free instances. To create a superuser, run it from your
  machine against the remote DB:

      # .env temporarily pointed at the remote DB_* values
      uv run python manage.py createsuperuser

  Use your Postgres provider's **external** connection hostname here — the
  internal hostname the web service uses does not resolve from outside the
  platform.
- One log line on every boot is expected and benign: a gunicorn
  `Permission denied: '/app/.gunicorn'` control-socket error — the app
  directory is deliberately read-only to the runtime user. It does not
  affect request handling.

## 6. Verifying a deploy

1. `https://<app>.onrender.com/healthz` → `{"status": "ok"}`
2. `https://<app>.onrender.com/static/admin/css/base.css` → 200
   (whitenoise static serving OK — note `/api/docs/` proves nothing about
   static files; Swagger UI loads from a CDN).
3. `https://<app>.onrender.com/api/docs/` renders (app + schema OK).
4. Register + login round-trip against `/api/v1/accounts/`.
