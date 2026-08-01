# Job Board API — container image for AWS Lambda (and plain Docker).
#
# The AWS Lambda Web Adapter in /opt/extensions translates Lambda events
# into HTTP against gunicorn on port 8080. Outside Lambda the adapter is
# inert, so the same image runs locally:
#
#   docker build -t jobboard-api .
#   docker run --rm -p 8000:8080 --env-file .env -e PGSSLMODE=disable jobboard-api

FROM python:3.13-slim

# uv installs the locked dependencies; pinned to the 0.10 line used locally.
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer first so code-only changes reuse the cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter

# collectstatic imports settings, and config.py demands these variables at
# import time — so feed throwaway values. Nothing here touches the DB or
# the LLM, and none of these leak into the runtime environment.
RUN SECRET_KEY=build-only-dummy-secret-key-never-used-at-runtime-0123456789 \
    DB_NAME=build DB_USER=build DB_PASSWORD=build \
    GEMINI_API_KEY=build \
    ALLOWED_HOSTS=build.invalid \
    DJANGO_SETTINGS_MODULE=jobApp.settings.production \
    .venv/bin/python manage.py collectstatic --noinput

# PGSSLMODE=require: Neon (and RDS) mandate TLS; psycopg2 honors this env
# var, so no settings change is needed. Override to disable for local runs.
ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=jobApp.settings.production \
    AWS_LWA_PORT=8080 \
    PGSSLMODE=require

EXPOSE 8080

# One worker: a Lambda execution environment handles one request at a time.
# The 120s timeout leaves headroom for the AI screening Pro-model calls.
CMD ["gunicorn", "jobApp.wsgi:application", "--bind=0.0.0.0:8080", "--workers=1", "--threads=2", "--timeout=120"]
