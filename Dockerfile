# syntax=docker/dockerfile:1

# --- Builder: resolve the locked dependency set into a venv ---------------
FROM python:3.13-slim AS builder

# Pin to the uv version this repo develops with (uv 0.10.9 locally).
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Lockfile-only layer: dependency changes bust this cache, code changes don't.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# --- Runtime: slim, non-root, no build tooling ----------------------------
FROM python:3.13-slim

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=jobApp.settings.production

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY . .

# Build-time collectstatic under production settings (manifest + compression).
# The env values are single-RUN dummies: they satisfy config.py's import-time
# requirements and production.py's asserts, and never persist in any layer.
# Everything under /app stays ROOT-owned deliberately: the app never writes
# to disk at runtime (no media storage exists; logging is stderr; the
# whitenoise manifest is read-only after build), so the gunicorn user gets
# read-only code — least privilege, no code-persistence primitive.
RUN chmod +x docker/entrypoint.sh && \
    SECRET_KEY=build-only-dummy-secret-key-for-collectstatic-0123456789abcdefgh \
    DB_NAME=build DB_USER=build DB_PASSWORD=build \
    GEMINI_API_KEY=build ALLOWED_HOSTS=build.invalid \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
